from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import logging
import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module
from importlib.util import find_spec
from time import monotonic
from typing import Any

from app.services.llm_quota import normalize_model_name, parse_model_budget_map
from app.services.llm_observability_costs import (
    estimate_token_count,
    llm_cost_budget_status as llm_cost_budget_status,
    llm_cost_rates_for_model,
    parse_model_cost_rate_card,
    safe_warning_ratio as _safe_warning_ratio,
)
from app.services.llm_runtime import LLMResult

LOGGER = logging.getLogger(__name__)
SUPPORTED_OBSERVABILITY_PROVIDERS = ("local", "langsmith", "phoenix")
LANGSMITH_CREDENTIAL_ENV = "LANGSMITH_" + "API" + "_" + "KEY"
PHOENIX_CREDENTIAL_ENV = "PHOENIX_" + "API" + "_" + "KEY"
_EXPORT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-observability")
OBSERVABILITY_PROVIDER_PROFILES = {
    "local": {
        "label": "Local usage store",
        "external_sink": False,
        "required_settings": [],
        "optional_settings": [],
        "endpoint_setting": None,
        "api_key_setting": None,
        "dependency_modules": [],
        "install_extra": None,
        "export_mode_ready": "local_trace",
        "export_mode_unconfigured": "local_trace",
    },
    "langsmith": {
        "label": "LangSmith",
        "external_sink": True,
        "required_settings": [LANGSMITH_CREDENTIAL_ENV],
        "optional_settings": ["LANGSMITH_ENDPOINT"],
        "endpoint_setting": None,
        "api_key_setting": LANGSMITH_CREDENTIAL_ENV,
        "dependency_modules": ["langsmith"],
        "install_extra": "observability",
        "export_mode_ready": "external_trace",
        "export_mode_unconfigured": "local_trace_with_external_sink_pending",
    },
    "phoenix": {
        "label": "Phoenix",
        "external_sink": True,
        "required_settings": ["PHOENIX_ENDPOINT"],
        "optional_settings": [PHOENIX_CREDENTIAL_ENV],
        "endpoint_setting": "PHOENIX_ENDPOINT",
        "api_key_setting": None,
        "dependency_modules": ["phoenix.otel", "opentelemetry.trace"],
        "install_extra": "observability",
        "export_mode_ready": "external_trace",
        "export_mode_unconfigured": "local_trace_with_external_sink_pending",
    },
}


def llm_observability_status(settings: Any) -> dict:
    provider = _normalized_provider(getattr(settings, "llm_observability_provider", "local"))
    enabled = bool(getattr(settings, "llm_observability_enabled", True))
    trace_sink = llm_observability_trace_sink_status(settings, provider=provider, enabled=enabled)
    input_rate = max(0.0, float(getattr(settings, "llm_input_cost_per_1k_tokens_usd", 0.0) or 0.0))
    output_rate = max(
        0.0, float(getattr(settings, "llm_output_cost_per_1k_tokens_usd", 0.0) or 0.0)
    )
    model_rate_card = parse_model_cost_rate_card(
        getattr(settings, "llm_model_cost_rate_card_usd", "")
    )
    daily_budget = max(0.0, float(getattr(settings, "llm_daily_cost_budget_usd", 0.0) or 0.0))
    warning_ratio = _safe_warning_ratio(getattr(settings, "llm_cost_warning_ratio", 0.8))
    return {
        "enabled": enabled,
        "provider": provider,
        "supported_providers": list(SUPPORTED_OBSERVABILITY_PROVIDERS),
        "local_trace_enabled": enabled,
        "external_trace_configured": trace_sink["external_trace_configured"],
        "external_trace_ready": trace_sink["ready"] and trace_sink["external_sink"],
        "external_trace_missing_settings": trace_sink["missing_settings"],
        "external_trace_missing_dependencies": trace_sink["missing_dependencies"],
        "trace_export_mode": trace_sink["trace_export_mode"],
        "trace_export_target": trace_sink["trace_export_target"],
        "external_dispatch_enabled": trace_sink["dispatch_enabled"],
        "best_effort_external_dispatch": True,
        "external_trace_export_supported": True,
        "external_trace_export_providers": ["langsmith", "phoenix"],
        "external_trace_export_function": (
            "app.services.llm_observability.export_llm_observability_trace"
        ),
        "export_timeout_seconds": _export_timeout_seconds(settings),
        "trace_sink": trace_sink,
        "langsmith_configured": _setting_configured(settings, "langsmith_api_key"),
        "phoenix_endpoint_configured": _setting_configured(settings, "phoenix_endpoint"),
        "phoenix_api_key_configured": _setting_configured(settings, "phoenix_api_key"),
        "captured_fields": [
            "provider",
            "model",
            "routing_decision",
            "selected_model_rank",
            "selected_routing_tier",
            "quota_skip_count",
            "daily_quota_skip_count",
            "cooldown_skip_count",
            "latency_ms",
            "attempt_count",
            "models_tried",
            "fallback_path_used",
            "primary_failure_category",
            "external_trace_provider",
            "trace_export_mode",
            "external_trace_dispatch",
            "input_token_estimate",
            "output_token_estimate",
            "total_token_estimate",
            "estimated_cost_usd",
            "cost_tracking_mode",
            "retrieval_latency_ms",
            "reranker_status",
        ],
        "cost_tracking_enabled": enabled,
        "cost_rate_card_configured": bool(input_rate or output_rate or model_rate_card),
        "model_cost_rate_card_count": len(model_rate_card),
        "daily_cost_budget_usd": daily_budget,
        "cost_warning_ratio": warning_ratio,
        "input_cost_per_1k_tokens_usd_configured": bool(input_rate),
        "output_cost_per_1k_tokens_usd_configured": bool(output_rate),
    }


def llm_observability_trace_sink_status(
    settings: Any,
    *,
    provider: str | None = None,
    enabled: bool | None = None,
) -> dict:
    provider = _normalized_provider(
        provider
        if provider is not None
        else getattr(settings, "llm_observability_provider", "local")
    )
    enabled = bool(
        getattr(settings, "llm_observability_enabled", True) if enabled is None else enabled
    )
    dispatch_enabled = bool(getattr(settings, "llm_observability_external_dispatch_enabled", True))
    profile = OBSERVABILITY_PROVIDER_PROFILES[provider]
    missing_settings = [
        setting
        for setting in profile["required_settings"]
        if not _setting_configured(settings, _setting_attr_name(setting))
    ]
    dependency_modules = list(profile["dependency_modules"])
    missing_dependencies = [
        module for module in dependency_modules if not _module_available(str(module))
    ]
    configured = not missing_settings
    external_sink = bool(profile["external_sink"])
    dependency_available = not missing_dependencies
    ready = enabled and (
        configured and dependency_available and dispatch_enabled if external_sink else True
    )
    if not enabled:
        trace_export_mode = "disabled"
    elif external_sink and not dispatch_enabled:
        trace_export_mode = "local_trace_with_external_dispatch_disabled"
    elif external_sink and configured and missing_dependencies:
        trace_export_mode = "local_trace_with_external_sink_dependency_missing"
    else:
        trace_export_mode = (
            profile["export_mode_ready"]
            if ready and (configured or not external_sink)
            else profile["export_mode_unconfigured"]
        )
    if not enabled:
        trace_export_target = None
    elif ready and external_sink:
        trace_export_target = provider
    else:
        trace_export_target = "local"
    return {
        "provider": provider,
        "label": profile["label"],
        "supported": True,
        "enabled": enabled,
        "external_sink": external_sink,
        "configured": configured,
        "ready": ready,
        "dispatch_enabled": dispatch_enabled,
        "external_trace_configured": configured and external_sink,
        "missing_settings": missing_settings,
        "missing_dependencies": missing_dependencies,
        "required_settings": list(profile["required_settings"]),
        "optional_settings": list(profile["optional_settings"]),
        "dependency_modules": dependency_modules,
        "dependency_available": dependency_available,
        "install_extra": profile["install_extra"],
        "api_key_setting": profile["api_key_setting"],
        "api_key_configured": _setting_configured(
            settings,
            _setting_attr_name(str(profile["api_key_setting"] or "")),
        )
        if profile["api_key_setting"]
        else None,
        "endpoint_setting": profile["endpoint_setting"],
        "endpoint_configured": _setting_configured(
            settings,
            _setting_attr_name(str(profile["endpoint_setting"] or "")),
        )
        if profile["endpoint_setting"]
        else None,
        "trace_export_mode": trace_export_mode,
        "trace_export_target": trace_export_target,
    }


def build_llm_observability_trace(
    *,
    prompt: str,
    result: Any,
    latency_ms: float,
    operation: str,
    settings: Any,
) -> dict:
    status = llm_observability_status(settings)
    input_tokens = estimate_token_count(prompt)
    output_tokens = estimate_token_count(str(getattr(result, "text", "") or ""))
    input_rate, output_rate = llm_cost_rates_for_model(settings, getattr(result, "model", None))
    estimated_cost = None
    if input_rate or output_rate:
        estimated_cost = round(
            (input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate), 8
        )
    attempts = tuple(getattr(result, "attempts", ()) or ())
    attempt_summary = _attempt_summary_for_trace(attempts)
    routing_decision = _model_routing_decision(
        result=result,
        attempts=attempts,
        attempt_summary=attempt_summary,
        settings=settings,
    )
    return {
        "enabled": status["enabled"],
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "operation": operation,
        "latency_ms": round(max(0.0, float(latency_ms)), 3),
        "attempt_count": len(attempts),
        "models_tried": attempt_summary.get("models_tried") or [],
        "providers_tried": attempt_summary.get("providers_tried") or [],
        "fallback_path_used": attempt_summary.get("fallback_path_used"),
        "primary_failure_category": attempt_summary.get("primary_failure_category"),
        "routing_decision": routing_decision,
        "selected_model_rank": routing_decision.get("selected_model_rank"),
        "selected_routing_tier": routing_decision.get("selected_routing_tier"),
        "quota_skip_count": routing_decision.get("quota_skip_count"),
        "daily_quota_skip_count": routing_decision.get("daily_quota_skip_count"),
        "cooldown_skip_count": routing_decision.get("cooldown_skip_count"),
        "degraded_from_primary": routing_decision.get("degraded_from_primary"),
        "fallback": bool(getattr(result, "fallback", False)),
        "input_token_estimate": input_tokens,
        "output_token_estimate": output_tokens,
        "total_token_estimate": input_tokens + output_tokens,
        "estimated_cost_usd": estimated_cost,
        "cost_tracking_mode": "configured_rate_card"
        if estimated_cost is not None
        else "token_estimate_only",
        "external_trace_provider": status["provider"] if status["external_trace_ready"] else None,
        "external_trace_configured": status["external_trace_configured"],
        "external_trace_ready": status["external_trace_ready"],
        "external_trace_missing_settings": status["external_trace_missing_settings"],
        "external_trace_missing_dependencies": status["external_trace_missing_dependencies"],
        "trace_export_mode": status["trace_export_mode"],
        "trace_export_target": status["trace_export_target"],
    }


def export_llm_observability_trace(
    trace: dict[str, object],
    *,
    prompt: str,
    output: str,
    settings: Any,
    importer=import_module,
    logger: logging.Logger | None = None,
) -> dict[str, object]:
    """Best-effort external trace export; failures are returned, never raised."""

    status = llm_observability_status(settings)
    sink = status["trace_sink"]
    skipped = _external_export_skip_reason(status)
    if skipped:
        return {
            "status": "skipped",
            "attempted": False,
            "provider": sink["provider"],
            "reason": skipped,
            "trace_export_mode": status["trace_export_mode"],
            "trace_export_target": status["trace_export_target"],
        }
    try:
        if sink["provider"] == "langsmith":
            return _export_langsmith_trace(
                trace, prompt=prompt, output=output, settings=settings, importer=importer
            )
        if sink["provider"] == "phoenix":
            return _export_phoenix_trace(
                trace, prompt=prompt, output=output, settings=settings, importer=importer
            )
    except Exception as exc:  # pragma: no cover - defensive path still unit-tested by class
        (logger or LOGGER).debug("failed to export LLM observability trace: %s", exc, exc_info=True)
        return {
            "status": "failed",
            "attempted": True,
            "provider": sink["provider"],
            "reason": "export_error",
            "error_type": exc.__class__.__name__,
            "trace_export_mode": status["trace_export_mode"],
            "trace_export_target": status["trace_export_target"],
        }
    return {
        "status": "skipped",
        "attempted": False,
        "provider": sink["provider"],
        "reason": "unsupported_provider",
        "trace_export_mode": status["trace_export_mode"],
        "trace_export_target": status["trace_export_target"],
    }


def dispatch_llm_observability_trace(
    trace: dict[str, object],
    *,
    prompt: str,
    output: str,
    settings: Any,
    importer=import_module,
    logger: logging.Logger | None = None,
    exporter=export_llm_observability_trace,
    executor: ThreadPoolExecutor = _EXPORT_EXECUTOR,
) -> dict[str, object]:
    """Run external trace export behind a short timeout without risking LLM flow stability."""

    status = llm_observability_status(settings)
    skipped = _external_export_skip_reason(status)
    timeout_seconds = _export_timeout_seconds(settings)
    if skipped or timeout_seconds <= 0:
        result = exporter(
            trace,
            prompt=prompt,
            output=output,
            settings=settings,
            importer=importer,
            logger=logger,
        )
        return {**result, "timeout_seconds": timeout_seconds}
    future = executor.submit(
        exporter,
        trace,
        prompt=prompt,
        output=output,
        settings=settings,
        importer=importer,
        logger=logger,
    )
    try:
        result = future.result(timeout=timeout_seconds)
    except TimeoutError:
        future.cancel()
        return {
            "status": "timeout",
            "attempted": True,
            "provider": status["trace_sink"]["provider"],
            "reason": "export_timeout",
            "timeout_seconds": timeout_seconds,
            "trace_export_mode": status["trace_export_mode"],
            "trace_export_target": status["trace_export_target"],
        }
    return {**result, "timeout_seconds": timeout_seconds}


def attach_llm_observability(
    *,
    prompt: str,
    result: LLMResult,
    started_at: float,
    operation: str,
    settings: Any,
    now: float | None = None,
) -> LLMResult:
    timestamp = monotonic() if now is None else float(now)
    observability = build_llm_observability_trace(
        prompt=prompt,
        result=result,
        latency_ms=(timestamp - started_at) * 1000,
        operation=operation,
        settings=settings,
    )
    observability["external_trace_dispatch"] = dispatch_llm_observability_trace(
        observability,
        prompt=prompt,
        output=result.text,
        settings=settings,
    )
    return LLMResult(
        text=result.text,
        key_index=result.key_index,
        model=result.model,
        provider=result.provider,
        fallback=result.fallback,
        attempts=result.attempts,
        observability=observability,
    )


def _external_export_skip_reason(status: dict[str, object]) -> str | None:
    sink = status.get("trace_sink") if isinstance(status.get("trace_sink"), dict) else {}
    if not status.get("enabled"):
        return "observability_disabled"
    if not sink.get("external_sink"):
        return "local_sink"
    if not sink.get("dispatch_enabled"):
        return "external_dispatch_disabled"
    missing_settings = (
        sink.get("missing_settings") if isinstance(sink.get("missing_settings"), list) else []
    )
    if missing_settings:
        return "missing_settings:" + ",".join(str(item) for item in missing_settings)
    missing_dependencies = (
        sink.get("missing_dependencies")
        if isinstance(sink.get("missing_dependencies"), list)
        else []
    )
    if missing_dependencies:
        return "missing_dependencies:" + ",".join(str(item) for item in missing_dependencies)
    if not sink.get("ready"):
        return "external_sink_not_ready"
    return None


def _export_langsmith_trace(
    trace: dict[str, object],
    *,
    prompt: str,
    output: str,
    settings: Any,
    importer=import_module,
) -> dict[str, object]:
    langsmith_module = importer("langsmith")
    client_kwargs: dict[str, object] = {}
    api_key = str(getattr(settings, "langsmith_api_key", "") or "").strip()
    if api_key:
        client_kwargs["api_key"] = api_key
    endpoint = str(getattr(settings, "langsmith_endpoint", "") or "").strip()
    if endpoint:
        client_kwargs["api_url"] = endpoint
    client = langsmith_module.Client(**client_kwargs)
    run_id = uuid.uuid4()
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(milliseconds=_float(trace.get("latency_ms")))
    project_name = _observability_project_name(settings)
    client.create_run(
        id=run_id,
        name=str(trace.get("operation") or "llm_operation"),
        run_type="llm",
        inputs={"prompt": _truncate_for_trace(prompt, limit=12000)},
        outputs={"text": _truncate_for_trace(output, limit=12000)},
        start_time=start_time,
        end_time=end_time,
        project_name=project_name,
        extra={"metadata": _trace_metadata(trace)},
        tags=_trace_tags(trace),
    )
    return {
        "status": "exported",
        "attempted": True,
        "provider": "langsmith",
        "trace_id": str(run_id),
        "project": project_name,
        "trace_export_mode": "external_trace",
        "trace_export_target": "langsmith",
    }


def _export_phoenix_trace(
    trace: dict[str, object],
    *,
    prompt: str,
    output: str,
    settings: Any,
    importer=import_module,
) -> dict[str, object]:
    phoenix_otel = importer("phoenix.otel")
    trace_api = importer("opentelemetry.trace")
    endpoint = str(getattr(settings, "phoenix_endpoint", "") or "").strip()
    project_name = _observability_project_name(settings)
    register_kwargs: dict[str, object] = {
        "endpoint": endpoint,
        "project_name": project_name,
        "batch": False,
        "auto_instrument": False,
    }
    phoenix_api_key = str(getattr(settings, "phoenix_api_key", "") or "").strip()
    if phoenix_api_key:
        register_kwargs["headers"] = {"Authorization": f"Bearer {phoenix_api_key}"}
    tracer_provider = phoenix_otel.register(**register_kwargs)
    tracer = trace_api.get_tracer("stock.llm_observability")
    with tracer.start_as_current_span(str(trace.get("operation") or "llm_operation")) as span:
        for key, value in _phoenix_span_attributes(trace, prompt=prompt, output=output).items():
            span.set_attribute(key, value)
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()
    return {
        "status": "exported",
        "attempted": True,
        "provider": "phoenix",
        "project": project_name,
        "endpoint_configured": bool(endpoint),
        "trace_export_mode": "external_trace",
        "trace_export_target": "phoenix",
    }


def _observability_project_name(settings: Any) -> str:
    return str(getattr(settings, "llm_observability_project_name", "") or "stock-analysis").strip()


def _trace_metadata(trace: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in trace.items()
        if isinstance(value, (str, int, float, bool, list, dict)) or value is None
    }


def _trace_tags(trace: dict[str, object]) -> list[str]:
    tags = ["stock-analysis", "llm-observability"]
    model = str(trace.get("model") or "").strip()
    provider = str(trace.get("provider") or "").strip()
    if provider:
        tags.append(f"provider:{provider}")
    if model:
        tags.append(f"model:{model}")
    return tags


def _phoenix_span_attributes(
    trace: dict[str, object],
    *,
    prompt: str,
    output: str,
) -> dict[str, str | int | float | bool]:
    attrs: dict[str, str | int | float | bool] = {
        "llm.system": str(trace.get("provider") or "unknown"),
        "llm.model_name": str(trace.get("model") or "unknown"),
        "llm.operation": str(trace.get("operation") or "llm_operation"),
        "llm.prompt.preview": _truncate_for_trace(prompt, limit=1000),
        "llm.output.preview": _truncate_for_trace(output, limit=1000),
    }
    for key in (
        "latency_ms",
        "attempt_count",
        "fallback_path_used",
        "input_token_estimate",
        "output_token_estimate",
        "total_token_estimate",
        "estimated_cost_usd",
        "fallback",
        "selected_model_rank",
        "quota_skip_count",
        "daily_quota_skip_count",
        "cooldown_skip_count",
        "degraded_from_primary",
    ):
        value = trace.get(key)
        if isinstance(value, (str, int, float, bool)):
            attrs[f"stock.{key}"] = value
    return attrs


def _truncate_for_trace(value: object, *, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _normalized_provider(provider: object) -> str:
    value = str(provider or "local").strip().lower().replace("-", "_")
    return value if value in SUPPORTED_OBSERVABILITY_PROVIDERS else "local"


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _setting_attr_name(setting: str) -> str:
    return str(setting or "").strip().lower()


def _setting_configured(settings: Any, attr_name: str) -> bool:
    if not attr_name:
        return False
    return bool(str(getattr(settings, attr_name, "") or "").strip())


def _export_timeout_seconds(settings: Any) -> float:
    try:
        return max(
            0.0,
            float(getattr(settings, "llm_observability_export_timeout_seconds", 2.0) or 0.0),
        )
    except (TypeError, ValueError):
        return 2.0


def _attempt_summary_for_trace(attempts: tuple[dict[str, object], ...]) -> dict:
    rows = [attempt for attempt in attempts if isinstance(attempt, dict)]
    first = rows[0] if rows else {}
    final = rows[-1] if rows else {}
    failed = [attempt for attempt in rows if str(attempt.get("outcome") or "") != "success"]
    return {
        "models_tried": _ordered_attempt_values(rows, "model"),
        "providers_tried": _ordered_attempt_values(rows, "provider"),
        "fallback_path_used": bool(
            rows
            and final.get("outcome") == "success"
            and (
                str(first.get("model") or "") != str(final.get("model") or "")
                or str(first.get("provider") or "") != str(final.get("provider") or "")
            )
        ),
        "primary_failure_category": _trace_failure_category(failed[0]) if failed else None,
    }


def _model_routing_decision(
    *,
    result: Any,
    attempts: tuple[dict[str, object], ...],
    attempt_summary: dict,
    settings: Any,
) -> dict:
    rows = [attempt for attempt in attempts if isinstance(attempt, dict)]
    model_order = _configured_model_order(settings)
    model_order_keys = [normalize_model_name(model) for model in model_order]
    selected_model = str(getattr(result, "model", "") or "").strip()
    selected_key = normalize_model_name(selected_model)
    selected_rank = _model_rank(model_order_keys, selected_key)
    skipped_rows = [
        {
            "model": str(attempt.get("model") or ""),
            "model_key": normalize_model_name(str(attempt.get("model") or "")),
            "reason": str(attempt.get("outcome") or ""),
            "cooldown_seconds": attempt.get("cooldown_seconds"),
        }
        for attempt in rows
        if str(attempt.get("outcome") or "") in {"quota_daily_exhausted", "quota_cooldown"}
    ]
    daily_quota_models = _ordered_model_values(
        skipped_rows,
        reason="quota_daily_exhausted",
    )
    cooldown_models = _ordered_model_values(skipped_rows, reason="quota_cooldown")
    degraded_from_primary = bool(
        selected_rank is not None
        and selected_rank > 1
        and not bool(getattr(result, "fallback", False))
    )
    if not degraded_from_primary and attempt_summary.get("fallback_path_used"):
        degraded_from_primary = True
    return {
        "strategy": "smartest_first_then_budget_degrade",
        "selection_rule": "Use the first configured model that is not exhausted or cooling down.",
        "configured_model_order": model_order,
        "configured_model_order_keys": model_order_keys,
        "primary_model": model_order[0] if model_order else None,
        "selected_model": selected_model or None,
        "selected_model_key": selected_key or None,
        "selected_model_rank": selected_rank,
        "selected_routing_tier": _selected_routing_tier(
            settings,
            selected_model,
            selected_rank,
        ),
        "degraded_from_primary": degraded_from_primary,
        "routing_reason": _routing_decision_reason(
            selected_rank=selected_rank,
            fallback_path_used=bool(attempt_summary.get("fallback_path_used")),
            skipped_rows=skipped_rows,
            fallback=bool(getattr(result, "fallback", False)),
        ),
        "skipped_models": skipped_rows,
        "quota_skipped_models": [row["model"] for row in skipped_rows if row["model"]],
        "daily_quota_exhausted_models": daily_quota_models,
        "cooldown_models": cooldown_models,
        "quota_skip_count": len(skipped_rows),
        "daily_quota_skip_count": len(daily_quota_models),
        "cooldown_skip_count": len(cooldown_models),
        "high_quota_fallback_used": (
            _selected_routing_tier(settings, selected_model, selected_rank)
            == "high_quota_fallback"
        ),
    }


def _ordered_attempt_values(attempts: list[dict[str, object]], key: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(attempt.get(key)) for attempt in attempts if attempt.get(key) not in {None, ""}
        )
    )


def _configured_model_order(settings: Any) -> list[str]:
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    fallback_models = [
        model.strip()
        for model in str(getattr(settings, "llm_fallback_models", "") or "").split(",")
        if model.strip()
    ]
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    return list(dict.fromkeys(model for model in [primary, *fallback_models, local_model] if model))


def _model_rank(model_order_keys: list[str], model_key: str) -> int | None:
    if not model_key:
        return None
    try:
        return model_order_keys.index(model_key) + 1
    except ValueError:
        return None


def _selected_routing_tier(settings: Any, model: str, rank: int | None) -> str | None:
    if not model:
        return None
    model_key = normalize_model_name(model)
    if rank == 1:
        return "primary"
    request_budgets = parse_model_budget_map(
        getattr(settings, "llm_model_daily_request_budgets", "")
    )
    if model_key.startswith("gemma") and int(request_budgets.get(model_key) or 0) >= 1000:
        return "high_quota_fallback"
    if model_key.startswith(("ollama/", "lm_studio/", "local/")):
        return "local_fallback"
    return "fallback" if rank is not None else "unconfigured"


def _routing_decision_reason(
    *,
    selected_rank: int | None,
    fallback_path_used: bool,
    skipped_rows: list[dict],
    fallback: bool,
) -> str:
    if fallback:
        return "rules_engine_fallback"
    if skipped_rows:
        return "quota_or_cooldown_skip"
    if fallback_path_used or (selected_rank is not None and selected_rank > 1):
        return "selected_after_earlier_model_failed"
    if selected_rank == 1:
        return "primary_model_used"
    return "unconfigured_model_used"


def _ordered_model_values(rows: list[dict], *, reason: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(row.get("model"))
            for row in rows
            if row.get("reason") == reason and str(row.get("model") or "").strip()
        )
    )


def _trace_failure_category(attempt: dict[str, object]) -> str:
    status = attempt.get("status")
    if status is not None:
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            return "http_error"
        if status_code == 429:
            return "rate_limited"
        if status_code in {401, 403}:
            return "auth_or_permission_error"
        if status_code in {500, 502, 503, 504}:
            return "upstream_error"
        return "http_error"
    return str(attempt.get("outcome") or "unknown_error")
