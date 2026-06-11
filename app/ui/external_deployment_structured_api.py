from __future__ import annotations

from app.ui.external_deployment_common import (
    external_deployment_item_by_capability,
    string_list,
)


def structured_filing_api_operation_rows(upgrade_audit: dict) -> list[dict]:
    item = external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_structured_api_fallback",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else evidence
    provider_profile = (
        runtime.get("provider_profile") if isinstance(runtime.get("provider_profile"), dict) else {}
    )
    contract = (
        runtime.get("request_contract")
        if isinstance(runtime.get("request_contract"), dict)
        else evidence.get("request_contract")
        if isinstance(evidence.get("request_contract"), dict)
        else {}
    )
    sample_contract = (
        runtime.get("sample_contract") if isinstance(runtime.get("sample_contract"), dict) else {}
    )
    provider_setup_preview = (
        runtime.get("provider_setup_preview")
        if isinstance(runtime.get("provider_setup_preview"), dict)
        else {}
    )
    configuration_check = (
        runtime.get("configuration_check")
        if isinstance(runtime.get("configuration_check"), dict)
        else {}
    )
    return [
        {
            "項目": "設定檢查",
            "狀態": _structured_filing_status_label(
                _structured_filing_configuration_status(configuration_check)
            ),
            "指令": structured_filing_env_hint(runtime),
            "說明": _structured_filing_configuration_detail(configuration_check),
        },
        {
            "項目": "資料商設定檔",
            "狀態": "已完整" if runtime.get("configuration_ready") else "待設定",
            "指令": structured_filing_env_hint(runtime),
            "說明": _structured_filing_provider_detail(
                evidence,
                runtime,
                provider_profile,
            ),
        },
        {
            "項目": "資料商選擇矩陣",
            "狀態": _structured_filing_provider_matrix_status(runtime),
            "指令": structured_filing_env_hint(runtime),
            "說明": _structured_filing_provider_matrix_detail(runtime),
        },
        {
            "項目": "資料商設定預覽",
            "狀態": _structured_filing_provider_setup_status(provider_setup_preview),
            "指令": _structured_filing_provider_setup_command(
                provider_setup_preview,
                runtime,
            ),
            "說明": _structured_filing_provider_setup_detail(provider_setup_preview),
        },
        {
            "項目": "範例 JSON 合約",
            "狀態": _structured_filing_status_label(sample_contract.get("status") or "可執行"),
            "指令": structured_filing_sample_command(runtime),
            "說明": _structured_filing_sample_contract_detail(sample_contract),
        },
        {
            "項目": "本機 fixture HTTP",
            "狀態": _structured_filing_local_fixture_status(runtime),
            "指令": structured_filing_local_fixture_command(runtime),
            "說明": _structured_filing_local_fixture_detail(runtime),
        },
        {
            "項目": "正式 API smoke",
            "狀態": "可執行" if runtime.get("configured") else "待設定",
            "指令": structured_filing_live_smoke_command(runtime),
            "說明": "設定 provider URL/token 後，驗證 live API、欄位轉換與公司/文件類型命中。",
        },
        {
            "項目": "請求格式",
            "狀態": str(contract.get("method") or "GET"),
            "指令": "-",
            "說明": _structured_filing_request_contract_detail(contract),
        },
        {
            "項目": "必備欄位",
            "狀態": "必備",
            "指令": "-",
            "說明": _structured_filing_required_fields_detail(evidence, runtime),
        },
        {
            "項目": "備援判斷",
            "狀態": _structured_filing_status_label(
                "ready" if runtime.get("configured") else "not_configured"
            ),
            "指令": "-",
            "說明": _structured_filing_fallback_detail(runtime),
        },
    ]


def structured_filing_env_hint(runtime: dict) -> str:
    setup_preview = (
        runtime.get("provider_setup_preview")
        if isinstance(runtime.get("provider_setup_preview"), dict)
        else {}
    )
    env_template = string_list(setup_preview.get("env_template"))
    if env_template and not runtime.get("configured"):
        return "\n".join(env_template)
    provider = str(
        runtime.get("provider")
        or (
            runtime.get("provider_profile_key")
            if runtime.get("configured") or runtime.get("configuration_ready")
            else ""
        )
        or "tej"
    )
    configuration_check = (
        runtime.get("configuration_check")
        if isinstance(runtime.get("configuration_check"), dict)
        else {}
    )
    lines = [
        f"COMPANY_FILING_STRUCTURED_API_PROVIDER={provider}",
        "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
    ]
    if configuration_check.get("token_required") or runtime.get("token_configured"):
        lines.append("COMPANY_FILING_STRUCTURED_API_TOKEN=<token>")
    return "\n".join(lines)


def _structured_filing_provider_setup_status(preview: dict) -> str:
    if not preview:
        return "未提供"
    provider = str(preview.get("profile_key") or preview.get("provider") or "-")
    return f"{provider} / token 已遮蔽" if preview.get("token_redacted") else provider


def _structured_filing_provider_setup_command(preview: dict, runtime: dict) -> str:
    env_template = string_list(preview.get("env_template"))
    if env_template:
        return "\n".join(env_template)
    return structured_filing_env_hint(runtime)


def _structured_filing_provider_setup_detail(preview: dict) -> str:
    if not preview:
        return "缺少 provider_setup_preview；請重跑 /services/status 或 upgrade audit。"
    params = preview.get("params") if isinstance(preview.get("params"), dict) else {}
    headers = preview.get("headers") if isinstance(preview.get("headers"), dict) else {}
    param_keys = ",".join(str(key) for key in params)
    header_keys = ",".join(str(key) for key in headers)
    token_state = "redacted" if preview.get("token_redacted") else "not-required"
    return (
        f"{preview.get('method') or 'GET'} {preview.get('endpoint') or '-'}；"
        f"provider={preview.get('profile_key') or preview.get('provider') or '-'}；"
        f"auth={preview.get('auth_mode') or '-'}；token={token_state}；"
        f"headers={header_keys or '-'}；params={param_keys or '-'}。"
    )


def structured_filing_sample_command(runtime: dict) -> str:
    return str(
        runtime.get("sample_contract_cli")
        or (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--sample-json examples/structured_company_filing_sample.json "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        )
    )


def structured_filing_live_smoke_command(runtime: dict) -> str:
    return str(
        runtime.get("smoke_cli")
        or (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
        )
    )


def structured_filing_local_fixture_command(runtime: dict) -> str:
    free_validation = (
        runtime.get("free_validation")
        if isinstance(runtime.get("free_validation"), dict)
        else {}
    )
    one_shot_cli = str(
        free_validation.get("local_fixture_http_smoke_cli")
        or runtime.get("local_fixture_http_smoke_cli")
        or ""
    ).strip()
    provider_profile_cli = str(
        free_validation.get("local_fixture_provider_profile_smoke_cli")
        or runtime.get("local_fixture_provider_profile_smoke_cli")
        or ""
    ).strip()
    start_cli = str(
        free_validation.get("local_fixture_start_cli")
        or runtime.get("local_fixture_start_cli")
        or ""
    ).strip()
    smoke_cli = str(
        free_validation.get("local_fixture_smoke_cli")
        or runtime.get("local_fixture_smoke_cli")
        or ""
    ).strip()
    commands = [
        command for command in (one_shot_cli, provider_profile_cli, start_cli, smoke_cli) if command
    ]
    return "\n".join(commands) if commands else "-"


def _structured_filing_provider_detail(
    evidence: dict,
    runtime: dict,
    provider_profile: dict,
) -> str:
    provider = runtime.get("provider") or provider_profile.get("provider") or "-"
    profile = runtime.get("provider_profile_key") or provider_profile.get("profile_key") or "-"
    supported = string_list(evidence.get("supported_provider_examples")) or string_list(
        runtime.get("supported_provider_examples")
    )
    supported_text = "、".join(supported) if supported else "-"
    return f"provider={provider}；profile={profile}；supported={supported_text}。"


def _structured_filing_provider_matrix_status(runtime: dict) -> str:
    matrix = runtime.get("provider_decision_matrix")
    if not isinstance(matrix, list) or not matrix:
        return "未提供"
    paid_count = sum(1 for row in matrix if isinstance(row, dict) and row.get("token_required"))
    return f"{len(matrix)} 組 profile / {paid_count} 組需 token"


def _structured_filing_provider_matrix_detail(runtime: dict) -> str:
    matrix = runtime.get("provider_decision_matrix")
    if not isinstance(matrix, list) or not matrix:
        return "缺少 provider_decision_matrix；請重跑 /services/status。"
    provider_summaries = []
    for row in matrix[:4]:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "-")
        token = "token" if row.get("token_required") else "no-token"
        document_param = str(row.get("document_type_param") or "-")
        provider_summaries.append(f"{provider}:{token}/{document_param}")
    hint = str(runtime.get("provider_selection_hint") or "").strip()
    return "；".join(provider_summaries) + ("。" + hint if hint else "。")


def _structured_filing_sample_contract_detail(sample_contract: dict) -> str:
    if not sample_contract:
        return "先用本機樣本 JSON 驗證 provider payload 是否可轉成 CompanyFilingDocument。"
    raw_rows = int(sample_contract.get("raw_row_count") or 0)
    documents = int(sample_contract.get("document_count") or 0)
    errors = int(sample_contract.get("error_count") or 0)
    mode = str(sample_contract.get("mode") or "sample_json_contract")
    diagnostics = (
        sample_contract.get("contract_diagnostics")
        if isinstance(sample_contract.get("contract_diagnostics"), dict)
        else {}
    )
    diagnostics_text = _structured_filing_contract_diagnostics_detail(diagnostics)
    return (
        f"{mode}；raw_rows={raw_rows}；documents={documents}；errors={errors}"
        f"{diagnostics_text}。"
    )


def _structured_filing_contract_diagnostics_detail(diagnostics: dict) -> str:
    if not diagnostics:
        return ""
    coverage = (
        diagnostics.get("field_coverage")
        if isinstance(diagnostics.get("field_coverage"), dict)
        else {}
    )
    coverage_keys = (
        "title",
        "text",
        "ticker_or_company_mention",
        "requested_document_type_match",
    )
    coverage_text = ",".join(
        f"{key}={coverage.get(key, 0)}" for key in coverage_keys if key in coverage
    )
    return (
        f"；row_container={diagnostics.get('row_container') or '-'}"
        f"；conversion_ratio={diagnostics.get('conversion_ratio', 0)}"
        + (f"；coverage={coverage_text}" if coverage_text else "")
    )


def _structured_filing_local_fixture_status(runtime: dict) -> str:
    free_validation = (
        runtime.get("free_validation")
        if isinstance(runtime.get("free_validation"), dict)
        else {}
    )
    if free_validation.get("sample_contract_ready") or runtime.get("sample_contract_ready"):
        return "可執行"
    return "需先修 sample"


def _structured_filing_local_fixture_detail(runtime: dict) -> str:
    free_validation = (
        runtime.get("free_validation")
        if isinstance(runtime.get("free_validation"), dict)
        else {}
    )
    fixture = (
        runtime.get("local_fixture_api")
        if isinstance(runtime.get("local_fixture_api"), dict)
        else {}
    )
    url = (
        free_validation.get("local_fixture_url")
        or fixture.get("url")
        or "http://127.0.0.1:8794/filings"
    )
    purpose = (
        free_validation.get("purpose")
        or fixture.get("purpose")
        or "用本機 fixture 驗證 live HTTP fetch path，不需要付費資料商 token。"
    )
    provider_profile = str(
        free_validation.get("provider_profile") or fixture.get("provider_profile") or ""
    ).strip()
    profile_text = f"；provider_profile={provider_profile} local smoke" if provider_profile else ""
    return f"url={url}{profile_text}；{purpose}"


def _structured_filing_configuration_status(configuration_check: dict) -> str:
    if configuration_check.get("ready"):
        return "ready"
    return str(configuration_check.get("status") or "missing_required_env")


def _structured_filing_status_label(value: object) -> str:
    status_labels = {
        "ready": "可用",
        "missing_required_env": "缺少必要設定",
        "not_configured": "未設定",
        "configured": "已設定",
        "degraded": "需處理",
        "failed": "需處理",
        "unknown": "未評估",
    }
    text = str(value or "unknown")
    return status_labels.get(text, text)


def _structured_filing_configuration_detail(configuration_check: dict) -> str:
    if not configuration_check:
        return "缺少 configuration_check；請重跑 /services/status 或 upgrade audit。"
    missing = string_list(configuration_check.get("missing_env_keys"))
    configured = string_list(configuration_check.get("configured_env_keys"))
    token_state = "required" if configuration_check.get("token_required") else "optional"
    endpoint_state = "valid" if configuration_check.get("endpoint_valid") else "missing/invalid"
    return (
        f"missing={','.join(missing) or '-'}；"
        f"configured={','.join(configured) or '-'}；"
        f"token={token_state}；endpoint={endpoint_state}。"
    )


def _structured_filing_request_contract_detail(contract: dict) -> str:
    query_keys = string_list(contract.get("query_param_keys"))
    rows = string_list(contract.get("response_rows"))
    auth = str(contract.get("auth_mode") or "-")
    document_param = str(contract.get("document_type_param") or "-")
    return (
        f"auth={auth}；document_type_param={document_param}；"
        f"query={','.join(query_keys) or '-'}；rows={','.join(rows) or '-'}。"
    )


def _structured_filing_required_fields_detail(evidence: dict, runtime: dict) -> str:
    fields = string_list(runtime.get("required_document_fields")) or string_list(
        evidence.get("required_document_fields")
    )
    aliases = string_list(runtime.get("response_row_aliases")) or string_list(
        evidence.get("response_row_aliases")
    )
    return (
        "fields="
        + ("；".join(fields) if fields else "-")
        + "；response_rows="
        + ("、".join(aliases) if aliases else "-")
        + "。"
    )


def _structured_filing_fallback_detail(runtime: dict) -> str:
    if runtime.get("configured"):
        provider = runtime.get("provider") or runtime.get("provider_profile_key") or "-"
        return f"structured filing API 已設定；provider={provider}。"
    reason = runtime.get("fallback_reason") or "missing_structured_api_provider_or_url"
    return f"尚未設定授權資料源；目前會改用 Google News/官方網站搜尋與既有爬蟲流程：{reason}。"
