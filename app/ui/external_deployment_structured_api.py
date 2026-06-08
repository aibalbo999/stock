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
        runtime.get("provider_profile")
        if isinstance(runtime.get("provider_profile"), dict)
        else {}
    )
    contract = (
        runtime.get("request_contract")
        if isinstance(runtime.get("request_contract"), dict)
        else evidence.get("request_contract")
        if isinstance(evidence.get("request_contract"), dict)
        else {}
    )
    sample_contract = (
        runtime.get("sample_contract")
        if isinstance(runtime.get("sample_contract"), dict)
        else {}
    )
    return [
        {
            "項目": "Provider profile",
            "狀態": "已設定" if runtime.get("configured") else "待設定",
            "指令": structured_filing_env_hint(runtime),
            "說明": _structured_filing_provider_detail(
                evidence,
                runtime,
                provider_profile,
            ),
        },
        {
            "項目": "Sample contract",
            "狀態": str(sample_contract.get("status") or "可執行"),
            "指令": structured_filing_sample_command(runtime),
            "說明": _structured_filing_sample_contract_detail(sample_contract),
        },
        {
            "項目": "Live smoke",
            "狀態": "可執行" if runtime.get("configured") else "待設定",
            "指令": structured_filing_live_smoke_command(runtime),
            "說明": "設定 provider URL/token 後，驗證 live API、欄位轉換與公司/文件類型命中。",
        },
        {
            "項目": "Request contract",
            "狀態": str(contract.get("method") or "GET"),
            "指令": "-",
            "說明": _structured_filing_request_contract_detail(contract),
        },
        {
            "項目": "Required fields",
            "狀態": "必備",
            "指令": "-",
            "說明": _structured_filing_required_fields_detail(evidence, runtime),
        },
        {
            "項目": "Fallback 判斷",
            "狀態": "ready" if runtime.get("configured") else "not_configured",
            "指令": "-",
            "說明": _structured_filing_fallback_detail(runtime),
        },
    ]


def structured_filing_env_hint(runtime: dict) -> str:
    provider = str(runtime.get("provider") or runtime.get("provider_profile_key") or "tej")
    return "\n".join(
        [
            f"COMPANY_FILING_STRUCTURED_API_PROVIDER={provider}",
            "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
            "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>",
        ]
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


def _structured_filing_sample_contract_detail(sample_contract: dict) -> str:
    if not sample_contract:
        return "先用本機樣本 JSON 驗證 provider payload 是否可轉成 CompanyFilingDocument。"
    raw_rows = int(sample_contract.get("raw_row_count") or 0)
    documents = int(sample_contract.get("document_count") or 0)
    errors = int(sample_contract.get("error_count") or 0)
    mode = str(sample_contract.get("mode") or "sample_json_contract")
    return f"{mode}；raw_rows={raw_rows}；documents={documents}；errors={errors}。"


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
