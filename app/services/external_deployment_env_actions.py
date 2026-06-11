from __future__ import annotations

from app.services.external_deployment_env_catalog import (
    external_capability_env_defaults,
    external_env_key_hint,
)
from app.services.external_deployment_readiness import string_list


def external_env_summary(item: dict) -> dict:
    payload = item.get("evidence") if isinstance(item.get("evidence"), dict) else item
    return {
        "missing": set(_collect_named_string_lists(payload, {"missing_env_keys"})),
        "configured": set(_collect_named_string_lists(payload, {"configured_env_keys"})),
        "required": set(_collect_named_string_lists(payload, {"required_env_keys", "env_keys"})),
        "recommended": _collect_env_recommendations(payload, {"recommended_env"}),
        "compose_recommended": _collect_env_recommendations(
            payload,
            {"compose_recommended_env"},
        ),
        "fallback_reasons": set(
            _collect_named_strings(
                payload,
                {"fallback_reason", "reason", "connection_error", "runtime_error"},
            )
        ),
    }


def external_env_key_actions(item: dict, env_summary: dict) -> list[tuple[str, str]]:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    missing = set(env_summary["missing"])
    configured = set(env_summary["configured"])
    recommended = set(env_summary["recommended"])
    defaults = set(external_capability_env_defaults(*key))
    actions: list[tuple[str, str]] = []
    if _external_env_missing_neo4j_uri(key, env_summary):
        missing.add("NEO4J_URI")
    for env_key in sorted(missing - configured):
        actions.append((env_key, "缺少"))
    if _external_env_needs_default_keys(item, env_summary):
        for env_key in sorted((defaults or env_summary["required"]) - configured - missing):
            actions.append((env_key, "建議"))
    for env_key in sorted(recommended - configured - missing):
        if defaults and env_key not in defaults:
            continue
        actions.append((env_key, "建議"))
    for env_key in sorted(recommended & configured):
        if defaults and env_key not in defaults:
            continue
        if _external_env_should_recommend_configured_value(key, env_key):
            actions.append((env_key, "建議"))
    return actions


def external_env_key_next_step(item: dict, env_key: str, status: str) -> str:
    remediation = str(item.get("remediation") or "").strip()
    if status == "缺少":
        return f"補齊 {env_key} 後重跑對應檢查。"
    if remediation:
        return remediation
    return f"需要該能力時設定 {env_key}，再重跑啟用檢查清單。"


def external_env_resolution_type(item: dict, env_key: str, recommended_value: str) -> str:
    capability = str(item.get("capability") or "")
    if capability in {"neo4j_import", "graphrag_live_cypher_query"}:
        return "本機可套用"
    if capability == "company_filing_high_risk_unlocker" and env_key in {
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    }:
        if (
            "flaresolverr" in recommended_value
            or "127.0.0.1" in recommended_value
            or "localhost" in recommended_value
        ):
            return "本機可套用"
        return "外部服務選配"
    if env_key.endswith("_TOKEN") or env_key.endswith("_PASSWORD") or "API_KEY" in env_key:
        return "需人工密鑰"
    if env_key == "COMPANY_FILING_STRUCTURED_API_PROVIDER":
        return "外部資料源設定"
    if env_key == "COMPANY_FILING_STRUCTURED_API_URL":
        return "外部資料源設定"
    if env_key == "COMPANY_FILING_PROXY_URLS":
        return "外部服務選配"
    if "<" in recommended_value and ">" in recommended_value:
        return "需人工設定"
    return "本機可套用"


def external_env_maintenance_action(
    item: dict,
    env_key: str,
    recommended_value: str,
    resolution_type: str,
) -> str:
    if resolution_type == "需人工密鑰":
        return "手動補 .env 或 secret manager；不由維護操作寫入。"
    if resolution_type in {"外部資料源設定", "外部服務選配", "需人工設定"}:
        return "手動補 .env 或部署 secret 後重跑外部設定缺口診斷。"
    capability = str(item.get("capability") or "")
    if capability in {"neo4j_import", "graphrag_live_cypher_query"}:
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    if capability == "company_filing_high_risk_unlocker":
        return ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
    if capability == "company_filing_browser_or_proxy_fallback":
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    if "127.0.0.1" in recommended_value or "localhost" in recommended_value:
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    return "手動補 .env 或部署 secret 後重跑外部設定缺口診斷。"


def _external_env_missing_neo4j_uri(key: tuple[str, str], env_summary: dict) -> bool:
    if key not in {
        ("ai_rag", "neo4j_import"),
        ("ai_rag", "graphrag_live_cypher_query"),
    }:
        return False
    return any(
        str(reason).startswith("missing_settings:neo4j_uri")
        for reason in env_summary["fallback_reasons"]
    )


def _external_env_needs_default_keys(item: dict, env_summary: dict) -> bool:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    fallback_reasons = env_summary["fallback_reasons"]
    if key in {
        ("ai_rag", "neo4j_import"),
        ("ai_rag", "graphrag_live_cypher_query"),
    }:
        return any(str(reason).startswith("missing_settings:neo4j") for reason in fallback_reasons)
    if key == ("ai_rag", "visual_rag"):
        return any(
            "missing_vision_llm_key_or_gateway" in str(reason) for reason in fallback_reasons
        )
    return False


def _external_env_should_recommend_configured_value(
    key: tuple[str, str],
    env_key: str,
) -> bool:
    return key == ("data_business_logic", "company_filing_high_risk_unlocker") and env_key in {
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    }


def _collect_named_string_lists(payload: object, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in keys:
                values.extend(string_list(value))
            else:
                values.extend(_collect_named_string_lists(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_collect_named_string_lists(value, keys))
    return values


def _collect_named_strings(payload: object, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in keys and str(value or "").strip():
                values.append(str(value).strip())
            else:
                values.extend(_collect_named_strings(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_collect_named_strings(value, keys))
    return values


def _collect_env_recommendations(
    payload: object,
    keys: set[str] | None = None,
) -> dict[str, str]:
    recommendations: dict[str, str] = {}
    for line in _collect_named_string_lists(
        payload,
        keys or {"recommended_env", "compose_recommended_env"},
    ):
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.isupper():
            continue
        recommendations.setdefault(
            key,
            value.strip() or external_env_key_hint(key).get("default") or "-",
        )
    return recommendations
