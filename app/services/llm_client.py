from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import httpx

from app.core.config import get_settings


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
        for key_index, api_key in self.rotator.candidates():
            try:
                text = self._call_gemini(prompt, api_key)
                if text:
                    return LLMResult(text=text, key_index=key_index, model=self.settings.primary_llm_model)
                errors.append(f"key[{key_index}] empty response")
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                errors.append(f"key[{key_index}] HTTP {status}")
                if status not in {401, 403, 429, 500, 502, 503, 504}:
                    break
            except httpx.HTTPError as exc:
                errors.append(f"key[{key_index}] {exc.__class__.__name__}")

        return LLMResult(
            text=(
                "LLM 呼叫失敗，已改用規則引擎產生報告草稿。"
                f"輪調嘗試：{'; '.join(errors) if errors else '無'}"
            ),
            fallback=True,
        )

    def healthcheck(self) -> LLMResult:
        return self.generate_with_metadata(
            "請只回答 ok，不要輸出任何其他文字。"
        )

    def _call_gemini(self, prompt: str, api_key: str) -> str:
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
        with httpx.Client(timeout=45) as client:
            response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
            response.raise_for_status()
        data = response.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts).strip()
