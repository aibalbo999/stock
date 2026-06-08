from __future__ import annotations

from importlib.util import find_spec
from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.data_sources.company_filing_render import (
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
)
from app.data_sources.company_filings import (
    company_filing_structured_api_status,
)
from app.db.migration_status import db_migration_status
from app.db.session import engine
from app.services.candidate_confidence import confidence_thresholds
from app.services.llm_client import RETRYABLE_HTTP_STATUSES
from app.services.llm_observability import llm_observability_status
from app.services.local_dependency_diagnostics import local_dependency_runtime_status
from app.services.source_quality import SOURCE_CREDIBILITY_LABELS, SOURCE_CREDIBILITY_WEIGHTS
from app.services.status_company_filings import (
    company_filing_status as collect_company_filing_status,
)
from app.services.status_capability_matrix import (
    upgrade_capability_matrix as build_upgrade_capability_matrix,
)
from app.services.status_frontend import frontend_status as collect_frontend_status
from app.services.status_llm import (
    _llm_effective_fallback_models,
    _llm_model_provider,
    _llm_quota_routing_status,
)
from app.services.status_graphrag import (
    supply_chain_graph_status as collect_supply_chain_graph_status,
)
from app.services.status_market_data import (
    market_data_status as collect_market_data_status,
)
from app.services.status_python_runtime import (
    python_runtime_status as collect_python_runtime_status,
)
from app.services.status_report_retention import (
    report_retention_status as collect_report_retention_status,
)
from app.services.status_security import security_scan_status as collect_security_scan_status
from app.services.status_task_queue import task_queue_status as collect_task_queue_status
from app.services.status_vector_store import vector_store_status as collect_vector_store_status
from app.services.visual_rag import visual_rag_status
from app.services.workflow_orchestration import workflow_orchestration_status


def service_status() -> dict:
    settings = get_settings()
    high_threshold, medium_threshold = confidence_thresholds()
    redis_status = _redis_status(settings.redis_url)
    llm_fallback_models = _llm_effective_fallback_models(settings)
    llm_local_gateway_configured = any(
        _llm_model_provider(model) == "local" for model in llm_fallback_models
    )
    llm_quota_routing = _llm_quota_routing_status(settings)
    llm_observability = llm_observability_status(settings)
    visual_rag_runtime = visual_rag_status(settings)
    market_data_status = collect_market_data_status(settings, redis_status=redis_status)
    supply_chain_graph_status = collect_supply_chain_graph_status()
    vector_store_status = collect_vector_store_status(
        settings,
        module_available=_module_available,
    )
    company_filing_status = collect_company_filing_status(
        settings,
        redis_status=redis_status,
        visual_rag_runtime=visual_rag_runtime,
        module_available=_module_available,
        browser_render_status_func=company_filing_browser_render_status,
        playwright_browser_status_func=company_filing_playwright_browser_status,
        structured_api_status_func=company_filing_structured_api_status,
    )
    frontend_status = collect_frontend_status()
    local_dependencies_status = local_dependency_runtime_status()
    python_runtime_status = collect_python_runtime_status()
    report_retention_status = collect_report_retention_status()
    task_queue_status = collect_task_queue_status(
        settings,
        redis_status=redis_status,
        redact_url=_redact_url,
    )
    status = {
        "database": {
            "init_mode": settings.database_init_mode,
            "create_all_non_sqlite_allowed": settings.database_allow_create_all_non_sqlite,
            "migration": db_migration_status(bind=engine),
        },
        "redis": redis_status,
        "gemini": {
            "configured": len(settings.gemini_api_keys) > 0,
            "key_count": len(settings.gemini_api_keys),
            "model": settings.primary_llm_model,
            "provider": settings.llm_provider,
            "fallback_models": llm_fallback_models,
            "provider_keys_configured": {
                "gemini": len(settings.gemini_api_keys) > 0,
                "openai": bool(settings.openai_api_key),
                "anthropic": bool(settings.anthropic_api_key),
                "local": llm_local_gateway_configured,
            },
            "retryable_http_statuses": sorted(RETRYABLE_HTTP_STATUSES),
            "max_retries_per_key": max(0, int(settings.llm_max_retries_per_key)),
            "base_retry_delay_seconds": max(0.0, float(settings.llm_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.llm_max_retry_delay_seconds)),
        },
        "frontend": frontend_status,
        "local_dependencies": local_dependencies_status,
        "python_runtime": python_runtime_status,
        "report_retention": report_retention_status,
        "llm_quota_routing": llm_quota_routing,
        "llm_observability": llm_observability,
        "finmind": market_data_status["finmind"],
        "fugle": market_data_status["fugle"],
        "market_data_cache": market_data_status["market_data_cache"],
        "company_filings": company_filing_status,
        "vector_store": vector_store_status,
        "supply_chain_graph": supply_chain_graph_status,
        "celery": {
            "broker_url": task_queue_status["broker_url"],
            "backend_url": task_queue_status["backend_url"],
            "ready": task_queue_status["ready"],
            "submission_contract_ready": task_queue_status["submission_contract_ready"],
        },
        "task_queue": task_queue_status,
        "workflow_orchestration": workflow_orchestration_status(settings),
        "security_scanning": collect_security_scan_status(
            module_available=_module_available,
        ),
        "candidate_confidence": {
            "high_threshold": high_threshold,
            "medium_threshold": medium_threshold,
            "promotion_rule": "正式分析需至少 2 篇證據、2 個來源，證據信心達高信心門檻，且低可信來源不得單獨支撐高信心。",
            "source_credibility_weights": SOURCE_CREDIBILITY_WEIGHTS,
            "source_credibility_labels": SOURCE_CREDIBILITY_LABELS,
        },
    }
    status["upgrade_capability_matrix"] = build_upgrade_capability_matrix(status)
    return status


def _redis_status(redis_url: str) -> dict:
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        pong = client.ping()
        return {"ok": bool(pong), "url": _redact_url(redis_url)}
    except Exception as exc:
        return {"ok": False, "url": _redact_url(redis_url), "error": str(exc)}


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


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
