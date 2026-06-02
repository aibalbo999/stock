from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha1

import redis

from app.core.config import get_settings
from app.models.schemas import NewsDocument


class RedisCompanyFilingCache:
    """Best-effort Redis cache for parsed company filing documents."""

    KEY_NAMESPACE = "stock-ai:company-filing:url-document:v1"

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        enabled: bool | None = None,
        ttl_seconds: int | None = None,
        client_factory: Callable[[str], object] | None = None,
    ) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.enabled = settings.company_filing_cache_enabled if enabled is None else enabled
        self.ttl_seconds = (
            int(settings.company_filing_cache_ttl_seconds)
            if ttl_seconds is None
            else int(ttl_seconds)
        )
        self._client_factory = client_factory or self._default_client_factory
        self._client: object | None = None
        self._disabled_after_error = False

    def get_url_document(
        self,
        url: str,
        *,
        parser: str,
        extract_tables: bool,
        html_extract_tables: bool,
    ) -> NewsDocument | None:
        payload = self._get_json(self._url_document_key(url, parser, extract_tables, html_extract_tables))
        if not isinstance(payload, dict):
            return None
        try:
            return NewsDocument.model_validate(payload)
        except Exception:
            return None

    def set_url_document(
        self,
        url: str,
        document: NewsDocument,
        *,
        parser: str,
        extract_tables: bool,
        html_extract_tables: bool,
    ) -> None:
        self._set_json(
            self._url_document_key(url, parser, extract_tables, html_extract_tables),
            document.model_dump(mode="json"),
            self.ttl_seconds,
        )

    @property
    def available(self) -> bool:
        return self.enabled and not self._disabled_after_error

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "backend": "redis",
            "ttl_seconds": self.ttl_seconds,
            "key_namespace": self.KEY_NAMESPACE,
            "key_scope": ["url", "parser", "extract_tables", "html_extract_tables"],
        }

    @staticmethod
    def _url_document_key(
        url: str,
        parser: str,
        extract_tables: bool,
        html_extract_tables: bool,
    ) -> str:
        digest = sha1(
            f"{url}|{parser}|tables={int(extract_tables)}|html_tables={int(html_extract_tables)}".encode("utf-8")
        ).hexdigest()
        return f"{RedisCompanyFilingCache.KEY_NAMESPACE}:{digest}"

    @staticmethod
    def _default_client_factory(redis_url: str) -> object:
        return redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )

    def _redis(self) -> object | None:
        if not self.enabled or self._disabled_after_error:
            return None
        if self._client is not None:
            return self._client
        try:
            self._client = self._client_factory(self.redis_url)
            return self._client
        except Exception:
            self._disabled_after_error = True
            return None

    def _get_json(self, key: str) -> object | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(key)
        except Exception:
            self._disabled_after_error = True
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _set_json(self, key: str, value: object, ttl_seconds: int) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            client.setex(key, max(1, int(ttl_seconds)), json.dumps(value, ensure_ascii=False))
        except Exception:
            self._disabled_after_error = True
