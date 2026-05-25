from __future__ import annotations

from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD


def service_status() -> dict:
    settings = get_settings()
    return {
        "redis": _redis_status(settings.redis_url),
        "gemini": {
            "configured": len(settings.gemini_api_keys) > 0,
            "key_count": len(settings.gemini_api_keys),
            "model": settings.primary_llm_model,
        },
        "finmind": {
            "configured": bool(settings.finmind_token),
            "mode": "authenticated" if settings.finmind_token else "public_or_limited",
        },
        "vector_store": {
            "use_chroma": settings.use_chroma,
            "path": str(settings.vector_db_path),
        },
        "celery": {
            "broker_url": _redact_url(settings.redis_url),
            "backend_url": _redact_url(settings.redis_url),
        },
        "candidate_confidence": {
            "high_threshold": HIGH_CONFIDENCE_THRESHOLD,
            "medium_threshold": MEDIUM_CONFIDENCE_THRESHOLD,
            "promotion_rule": "正式分析需至少 2 篇證據、2 個來源，且證據信心達高信心門檻。",
        },
    }


def _redis_status(redis_url: str) -> dict:
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        pong = client.ping()
        return {"ok": bool(pong), "url": _redact_url(redis_url)}
    except Exception as exc:
        return {"ok": False, "url": _redact_url(redis_url), "error": str(exc)}


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    return parsed._replace(netloc=netloc).geturl()
