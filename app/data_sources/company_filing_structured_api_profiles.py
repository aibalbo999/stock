from __future__ import annotations

from urllib.parse import urlparse


STRUCTURED_API_RECOMMENDED_PAID_PROVIDER = "tej"
STRUCTURED_API_PROVIDER_PROFILES = {
    "tej": {
        "label": "TEJ structured company filings",
        "auth_mode": "bearer",
        "token_location": "authorization_header",
        "document_type_param": "document_type",
        "request_param_keys": ["ticker", "company_name", "limit", "document_type"],
    },
    "scrapingbee_dataset": {
        "label": "ScrapingBee dataset/API fallback",
        "auth_mode": "query_param",
        "token_location": "query_param",
        "token_param": "api_key",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types", "api_key"],
    },
    "brightdata_dataset": {
        "label": "BrightData dataset/API fallback",
        "auth_mode": "bearer",
        "token_location": "authorization_header",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types"],
    },
    "custom": {
        "label": "Custom structured company filing API",
        "auth_mode": "bearer_optional",
        "token_location": "authorization_header",
        "document_type_param": "document_types",
        "request_param_keys": ["ticker", "company_name", "limit", "document_types"],
    },
}
STRUCTURED_API_RESPONSE_ROW_ALIASES = ("documents", "data", "results", "items", "records", "list")
STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS = (
    "title/name/headline/doc_title",
    "text/content/body/abstract/summary",
    "ticker_or_company_mention",
    "document_type_match",
)


def structured_api_configuration_check(
    *,
    provider: str,
    endpoint: str,
    token: str,
    profile: dict,
) -> dict:
    normalized_provider = str(provider or "").strip().lower()
    normalized_endpoint = str(endpoint or "").strip()
    token_configured = bool(str(token or "").strip())
    token_required = _structured_api_token_required(profile)
    required_env_keys = [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    if token_required:
        required_env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    configured_env_keys = []
    if normalized_provider:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_PROVIDER")
    if normalized_endpoint:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_URL")
    if token_configured:
        configured_env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    missing_env_keys = [key for key in required_env_keys if key not in set(configured_env_keys)]
    parsed = urlparse(normalized_endpoint)
    endpoint_valid = bool(parsed.scheme in {"http", "https"} and parsed.hostname)
    if missing_env_keys:
        fallback_reason = "missing_structured_api_provider_or_url"
        if missing_env_keys == ["COMPANY_FILING_STRUCTURED_API_TOKEN"]:
            fallback_reason = "missing_structured_api_token"
        status = "missing_required_env"
    elif not endpoint_valid:
        fallback_reason = "invalid_structured_api_url"
        status = "invalid_url"
    else:
        fallback_reason = None
        status = "ready"
    return {
        "ready": status == "ready",
        "status": status,
        "fallback_reason": fallback_reason,
        "required_env_keys": required_env_keys,
        "configured_env_keys": configured_env_keys,
        "missing_env_keys": missing_env_keys,
        "token_required": token_required,
        "token_configured": token_configured,
        "endpoint_configured": bool(normalized_endpoint),
        "endpoint_valid": endpoint_valid,
        "endpoint_scheme": parsed.scheme or None,
        "endpoint_host_configured": bool(parsed.hostname),
        "provider_profile_key": str(profile.get("profile_key") or "custom"),
        "auth_mode": str(profile.get("auth_mode") or "bearer_optional"),
        "token_location": str(profile.get("token_location") or "authorization_header"),
    }


def structured_api_provider_decision_matrix() -> list[dict]:
    rows: list[dict] = []
    for provider_key, profile in STRUCTURED_API_PROVIDER_PROFILES.items():
        token_required = _structured_api_token_required(profile)
        query_param_keys = [str(key) for key in profile["request_param_keys"]]
        rows.append(
            {
                "provider": provider_key,
                "label": str(profile["label"]),
                "auth_mode": str(profile["auth_mode"]),
                "token_required": token_required,
                "token_location": str(profile["token_location"]),
                "document_type_param": str(profile["document_type_param"]),
                "request_param_keys": query_param_keys,
                "response_row_aliases": list(STRUCTURED_API_RESPONSE_ROW_ALIASES),
                "required_document_fields": list(STRUCTURED_API_REQUIRED_DOCUMENT_FIELDS),
                "env_keys": _structured_api_provider_env_keys(token_required),
                "recommended_when": _structured_api_provider_recommendation(provider_key),
            }
        )
    return rows


def structured_api_provider_setup_preview(
    *,
    provider: str,
    endpoint: str,
    token: str = "",
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    preview_provider = str(provider or "").strip().lower() or STRUCTURED_API_RECOMMENDED_PAID_PROVIDER
    profile = structured_api_provider_profile(preview_provider)
    token_required = _structured_api_token_required(profile)
    preview_endpoint = str(endpoint or "").strip() or "<provider-json-endpoint>"
    preview_token = str(token or "").strip()
    if not preview_token and token_required:
        preview_token = "<token>"
    contract = structured_api_request_contract(
        provider=preview_provider,
        endpoint=preview_endpoint,
        token=preview_token,
        ticker=ticker,
        company_name=company_name,
        limit=limit,
        document_types=document_types,
    )
    headers = dict(contract["headers"])
    params = dict(contract["params"])
    token_redacted = False
    if "Authorization" in headers:
        headers["Authorization"] = "Bearer <redacted>"
        token_redacted = True
    token_param = str(profile.get("token_param") or "api_key")
    if token_param in params:
        params[token_param] = "<redacted>"
        token_redacted = True
    env_template = [
        f"COMPANY_FILING_STRUCTURED_API_PROVIDER={profile['profile_key']}",
        "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
    ]
    if token_required:
        env_template.append("COMPANY_FILING_STRUCTURED_API_TOKEN=<token>")
    return {
        "recommended_provider": STRUCTURED_API_RECOMMENDED_PAID_PROVIDER,
        "provider": profile["provider"],
        "profile_key": profile["profile_key"],
        "label": profile["label"],
        "env_template": env_template,
        "method": contract["method"],
        "endpoint": contract["endpoint"],
        "headers": headers,
        "params": params,
        "auth_mode": contract["auth_mode"],
        "token_location": contract["token_location"],
        "token_required": token_required,
        "token_redacted": token_redacted,
        "document_type_param": contract["document_type_param"],
    }


def structured_api_provider_profile(provider: str) -> dict:
    provider_key = str(provider or "").strip().lower() or "custom"
    profile_key = provider_key if provider_key in STRUCTURED_API_PROVIDER_PROFILES else "custom"
    profile = dict(STRUCTURED_API_PROVIDER_PROFILES[profile_key])
    profile["provider"] = provider_key
    profile["profile_key"] = profile_key
    profile["profile_supported"] = (
        provider_key in STRUCTURED_API_PROVIDER_PROFILES or profile_key == "custom"
    )
    return profile


def structured_api_request_contract(
    *,
    provider: str,
    endpoint: str,
    token: str = "",
    ticker: str,
    company_name: str = "",
    limit: int = 3,
    document_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    profile = structured_api_provider_profile(provider)
    headers = {"Accept": "application/json"}
    params: dict[str, object] = {
        "ticker": ticker,
        "company_name": company_name,
        "limit": max(1, int(limit)),
    }
    requested_types = ",".join(document_types or ())
    if requested_types:
        params[str(profile["document_type_param"])] = requested_types
    normalized_token = str(token or "").strip()
    if normalized_token and profile["token_location"] == "authorization_header":
        headers["Authorization"] = f"Bearer {normalized_token}"
    elif normalized_token and profile["token_location"] == "query_param":
        params[str(profile.get("token_param") or "api_key")] = normalized_token
    return {
        "method": "GET",
        "provider": profile["provider"],
        "profile_key": profile["profile_key"],
        "endpoint": endpoint,
        "headers": headers,
        "params": params,
        "auth_mode": profile["auth_mode"],
        "token_location": profile["token_location"],
        "document_type_param": profile["document_type_param"],
    }


def _structured_api_provider_env_keys(token_required: bool) -> list[str]:
    env_keys = [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    if token_required:
        env_keys.append("COMPANY_FILING_STRUCTURED_API_TOKEN")
    return env_keys


def _structured_api_provider_recommendation(provider_key: str) -> str:
    recommendations = {
        "tej": "正式穩定取得台灣法說會、重大訊息或專業財經資料時優先評估。",
        "scrapingbee_dataset": "已有 ScrapingBee dataset/API 或需要 managed scraping pipeline 時使用。",
        "brightdata_dataset": "已有 BrightData dataset/API 或需要商用資料採集 SLA 時使用。",
        "custom": "免費版、本機 fixture、內部資料湖或自行包裝資料商 API 時使用。",
    }
    return recommendations.get(provider_key, "依資料商 contract 設定。")


def _structured_api_token_required(profile: dict) -> bool:
    return str(profile.get("auth_mode") or "").strip().lower() not in {
        "",
        "bearer_optional",
        "none",
    }
