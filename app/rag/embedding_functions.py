from __future__ import annotations

import os
import re
import time
from importlib import import_module
from typing import Any, Iterable


class ChromaCompatibleEmbedding(list):
    """List-compatible vector that also satisfies Chroma HTTP's tolist() path."""

    def tolist(self) -> list[float]:
        return list(self)


class GoogleGenAIEmbeddingFunction:
    """Chroma-compatible embedding function backed by the official Google GenAI SDK."""

    MAX_BATCH_SIZE = 100
    MAX_RETRIES = 6
    BASE_RETRY_SECONDS = 3.0
    MAX_RETRY_SECONDS = 30.0

    def __init__(
        self,
        api_key: str,
        model_name: str,
        output_dimensionality: int | None = None,
        api_key_env_var: str = "GOOGLE_API_KEY",
        api_key_pool_env_var: str = "GOOGLE_API_KEYS",
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.output_dimensionality = output_dimensionality
        self.api_key_env_var = api_key_env_var
        self.api_key_pool_env_var = api_key_pool_env_var

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        genai = import_module("google.genai")
        genai_types = import_module("google.genai.types")
        client = genai.Client(api_key=self.api_key)
        config = None
        if self.output_dimensionality:
            config = genai_types.EmbedContentConfig(
                output_dimensionality=int(self.output_dimensionality),
            )
        contents = list(input)
        vectors: list[list[float]] = []
        for start in range(0, len(contents), self.MAX_BATCH_SIZE):
            vectors.extend(
                self._embed_content_with_retry(
                    client,
                    contents[start : start + self.MAX_BATCH_SIZE],
                    config,
                )
            )
        return vectors

    def embed_query(self, input: Iterable[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:
        return self(input)

    def _embed_content_with_retry(
        self,
        client: Any,
        contents: list[str],
        config: Any,
    ) -> list[list[float]]:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = client.models.embed_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
                return self._extract_embeddings(response)
            except Exception as exc:
                if attempt >= self.MAX_RETRIES - 1 or not self._is_retryable_quota_error(exc):
                    raise
                retry_delay = self._retry_delay_seconds(exc, attempt)
                if retry_delay is None:
                    raise
                time.sleep(retry_delay)
        return []

    @classmethod
    def _is_retryable_quota_error(cls, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        text = str(exc)
        return status_code == 429 or "RESOURCE_EXHAUSTED" in text or "Quota exceeded" in text

    @classmethod
    def _retry_delay_seconds(cls, exc: Exception, attempt: int) -> float | None:
        text = str(exc)
        for pattern in (
            r"retryDelay['\"]?\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
            r"retry in ([0-9]+(?:\.[0-9]+)?)s",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                backoff = cls.BASE_RETRY_SECONDS * (2**attempt)
                return min(cls.MAX_RETRY_SECONDS, max(backoff, float(match.group(1))))
        return None

    @staticmethod
    def _extract_embeddings(response: object) -> list[list[float]]:
        embeddings = []
        if isinstance(response, dict):
            embeddings = response.get("embeddings") or []
            if not embeddings and response.get("embedding"):
                embeddings = [response["embedding"]]
        else:
            embeddings = getattr(response, "embeddings", None) or []
            if not embeddings and getattr(response, "embedding", None):
                embeddings = [getattr(response, "embedding")]

        vectors: list[list[float]] = []
        for embedding in embeddings:
            values = (
                embedding.get("values")
                if isinstance(embedding, dict)
                else getattr(embedding, "values", None)
            )
            if values is None:
                values = embedding
            vectors.append(ChromaCompatibleEmbedding(float(value) for value in values))
        return vectors

    @staticmethod
    def name() -> str:
        return "google_genai"

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "GoogleGenAIEmbeddingFunction":
        model_name = str(config.get("model_name") or "").strip()
        if not model_name:
            raise ValueError("model_name is required for Google GenAI embeddings.")
        api_key_env_var = str(config.get("api_key_env_var") or "GOOGLE_API_KEY").strip()
        api_key_pool_env_var = str(config.get("api_key_pool_env_var") or "GOOGLE_API_KEYS").strip()
        api_key = GoogleGenAIEmbeddingFunction._api_key_from_env(
            api_key_env_var,
            api_key_pool_env_var,
        )
        if not api_key:
            raise ValueError(
                f"{api_key_env_var} or {api_key_pool_env_var} is required for Google GenAI embeddings."
            )
        output_dimensionality = config.get("output_dimensionality")
        return GoogleGenAIEmbeddingFunction(
            api_key=api_key,
            model_name=model_name,
            output_dimensionality=int(output_dimensionality) if output_dimensionality else None,
            api_key_env_var=api_key_env_var,
            api_key_pool_env_var=api_key_pool_env_var,
        )

    @staticmethod
    def _api_key_from_env(api_key_env_var: str, api_key_pool_env_var: str) -> str | None:
        pooled_keys = os.getenv(api_key_pool_env_var, "")
        for raw_key in pooled_keys.split(","):
            key = raw_key.strip()
            if key:
                return key
        return os.getenv(api_key_env_var) or None

    def get_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "model_name": self.model_name,
            "api_key_env_var": self.api_key_env_var,
            "api_key_pool_env_var": self.api_key_pool_env_var,
        }
        if self.output_dimensionality:
            config["output_dimensionality"] = self.output_dimensionality
        return config
