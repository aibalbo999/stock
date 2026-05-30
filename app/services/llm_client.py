from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep
from typing import Optional

import httpx

from app.core.config import get_settings

RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
ROTATABLE_HTTP_STATUSES = {401, 403, *RETRYABLE_HTTP_STATUSES}
DEFAULT_MAX_RETRIES_PER_KEY = 2
DEFAULT_BASE_RETRY_DELAY_SECONDS = 0.5
DEFAULT_MAX_RETRY_DELAY_SECONDS = 5.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class LLMResult:
    text: str
    key_index: int | None = None
    model: str | None = None
    fallback: bool = False


class APIKeyRotator:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self._index = 0
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self.keys)

    def candidates(self) -> list[tuple[int, str]]:
        if not self.keys:
            return []
        with self._lock:
            start = self._index
            self._index = (self._index + 1) % len(self.keys)
        return [
            ((start + offset) % len(self.keys), self.keys[(start + offset) % len(self.keys)])
            for offset in range(len(self.keys))
        ]


_rotator_cache: dict[tuple[str, ...], APIKeyRotator] = {}
_rotator_cache_lock = Lock()


def get_shared_rotator(keys: list[str]) -> APIKeyRotator:
    fingerprint = tuple(keys)
    with _rotator_cache_lock:
        if fingerprint not in _rotator_cache:
            _rotator_cache[fingerprint] = APIKeyRotator(keys)
        return _rotator_cache[fingerprint]


class LLMClient:
    """Provider boundary for Gemini/Gemma analysis.

    The MVP keeps this adapter deliberately thin. In production, put provider-specific
    SDK calls here and keep prompts, evidence, and whitelist checks outside the model.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.rotator = get_shared_rotator(self.settings.gemini_api_keys)

    def generate(self, prompt: str) -> str:
        result = self.generate_with_metadata(prompt)
        if result.fallback:
            return result.text
        key_note = f"Gemini API key pool index：{result.key_index}" if result.key_index is not None else "Gemini API"
        return f"{result.text}\n\n模型狀態：{key_note}，model={result.model}"

    def generate_with_metadata(self, prompt: str) -> LLMResult:
        if len(self.rotator) == 0:
            return LLMResult(
                text=(
                    "目前未設定 LLM API key；已改用規則引擎產生報告草稿。"
                    "接上供應商 SDK 後，仍需保留白名單與來源檢查。"
                ),
                fallback=True,
            )

        errors: list[str] = []
        deadline = monotonic() + self.total_timeout_seconds
        for key_index, api_key in self.rotator.candidates():
            if monotonic() >= deadline:
                errors.append("LLM total timeout reached before trying next key")
                break
            should_stop = False
            max_retries = self.max_retries_per_key
            for attempt in range(max_retries + 1):
                if monotonic() >= deadline:
                    errors.append(f"key[{key_index}] total timeout before attempt {attempt + 1}")
                    should_stop = True
                    break
                try:
                    text = self._call_gemini(prompt, api_key, timeout_seconds=max(1.0, deadline - monotonic()))
                    if text:
                        return LLMResult(text=text, key_index=key_index, model=self.settings.primary_llm_model)
                    errors.append(f"key[{key_index}] empty response")
                    break
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    errors.append(f"key[{key_index}] HTTP {status} attempt {attempt + 1}")
                    if status not in ROTATABLE_HTTP_STATUSES:
                        should_stop = True
                        break
                    if status in RETRYABLE_HTTP_STATUSES and attempt < max_retries and monotonic() < deadline:
                        self._sleep_before_retry(exc.response, attempt)
                        continue
                    break
                except httpx.HTTPError as exc:
                    errors.append(f"key[{key_index}] {exc.__class__.__name__} attempt {attempt + 1}")
                    if attempt < max_retries and monotonic() < deadline:
                        self._sleep_before_retry(None, attempt)
                        continue
                    break
            if should_stop:
                break

        return LLMResult(
            text=(
                "LLM 呼叫失敗，已改用規則引擎產生報告草稿。"
                f"輪調嘗試：{'; '.join(errors) if errors else '無'}"
            ),
            fallback=True,
        )

    def _sleep_before_retry(self, response: Optional[httpx.Response], attempt: int) -> None:
        sleep(self._retry_delay_seconds(response, attempt))

    def _retry_delay_seconds(self, response: Optional[httpx.Response], attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(self.max_retry_delay_seconds, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        return min(self.max_retry_delay_seconds, self.base_retry_delay_seconds * (2**attempt))

    @property
    def max_retries_per_key(self) -> int:
        return max(0, int(getattr(self.settings, "llm_max_retries_per_key", DEFAULT_MAX_RETRIES_PER_KEY)))

    @property
    def base_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "llm_base_retry_delay_seconds", DEFAULT_BASE_RETRY_DELAY_SECONDS)))

    @property
    def max_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "llm_max_retry_delay_seconds", DEFAULT_MAX_RETRY_DELAY_SECONDS)))

    @property
    def total_timeout_seconds(self) -> float:
        return max(1.0, float(getattr(self.settings, "llm_total_timeout_seconds", DEFAULT_TOTAL_TIMEOUT_SECONDS)))

    def healthcheck(self) -> LLMResult:
        return self.generate_with_metadata(
            "請只回答 ok，不要輸出任何其他文字。"
        )

    def _call_gemini(self, prompt: str, api_key: str, timeout_seconds: float | None = None) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.primary_llm_model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 8192,
            },
        }
        with httpx.Client(timeout=min(45.0, timeout_seconds or 45.0)) as client:
            response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
            response.raise_for_status()
        data = response.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts).strip()
