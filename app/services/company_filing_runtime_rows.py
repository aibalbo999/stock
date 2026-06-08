from __future__ import annotations


def company_filing_runtime_rows(service_snapshot: dict) -> list[dict]:
    company_filings = _company_filings_status(service_snapshot)
    if not company_filings:
        return []
    pdf_dependencies = _nested_dict(company_filings, "pdf_parser_dependencies")
    visual_rag_runtime = _nested_dict(company_filings, "visual_rag_runtime")
    browser_runtime = _nested_dict(company_filings, "browser_render_runtime")
    playwright_runtime = _nested_dict(company_filings, "playwright_render_runtime")
    structured_runtime = _nested_dict(company_filings, "structured_api_runtime")
    return [
        {
            "能力": "PDF parser",
            "狀態": _ready_label(bool(company_filings.get("pdf_parser_available"))),
            "目前": str(company_filings.get("pdf_parser") or "-"),
            "細節": _runtime_detail(pdf_dependencies),
            "下一步": (
                "安裝 PDF 額外相依套件。"
                if not company_filings.get("pdf_parser_available")
                else "可處理文字型 PDF。"
            ),
        },
        {
            "能力": "PDF 表格抽取",
            "狀態": _ready_label(bool(company_filings.get("pdf_table_parser_available"))),
            "目前": "enabled" if company_filings.get("pdf_extract_tables") else "disabled",
            "細節": _runtime_detail(pdf_dependencies),
            "下一步": (
                "安裝 pdfplumber 或 unstructured[pdf]。"
                if not company_filings.get("pdf_table_parser_available")
                else "可抽取財報表格。"
            ),
        },
        {
            "能力": "Visual RAG",
            "狀態": _ready_label(bool(company_filings.get("visual_rag_runtime_available"))),
            "目前": str(
                company_filings.get("visual_rag_runtime_model")
                or visual_rag_runtime.get("runtime_model")
                or company_filings.get("visual_rag_model")
                or "-"
            ),
            "細節": _runtime_detail(visual_rag_runtime),
            "下一步": (
                "檢查 PyMuPDF、COMPANY_FILING_VISUAL_RAG_MODEL 與 vision LLM key/gateway。"
                if not company_filings.get("visual_rag_runtime_available")
                else "可作為掃描型/複雜 PDF 後援。"
            ),
        },
        {
            "能力": "Playwright render",
            "狀態": _ready_label(bool(company_filings.get("playwright_render_configured"))),
            "目前": str(company_filings.get("playwright_render_browser") or "-"),
            "細節": _runtime_detail(playwright_runtime),
            "下一步": (
                "安裝 Playwright browser binary 或改用 Browserless/FlareSolverr。"
                if not company_filings.get("playwright_render_configured")
                else "可處理動態 IR/公開文件頁。"
            ),
        },
        {
            "能力": "Browser / unlocker",
            "狀態": _ready_label(bool(company_filings.get("browser_render_configured"))),
            "目前": str(company_filings.get("browser_render_provider") or "-"),
            "細節": _runtime_detail(browser_runtime),
            "下一步": (
                "設定 Browserless、FlareSolverr、ScrapingBee 或 BrightData render URL。"
                if not company_filings.get("browser_render_configured")
                else "可作為反爬蟲/登入頁後援。"
            ),
        },
        {
            "能力": "結構化文件 API",
            "狀態": _ready_label(
                bool(company_filings.get("structured_api_configured")),
                optional=True,
            ),
            "目前": str(company_filings.get("structured_api_provider") or "-"),
            "細節": _runtime_detail(structured_runtime),
            "下一步": (
                "若 MOPS/IR 常被擋，可串接 TEJ 或專業文件 API。"
                if not company_filings.get("structured_api_configured")
                else "可作為授權資料源備援。"
            ),
        },
    ]


def company_filing_visual_rag_model_chain_rows(service_snapshot: dict) -> list[dict]:
    company_filings = _company_filings_status(service_snapshot)
    if not company_filings:
        return []
    model_chain = _nested_dict(company_filings, "visual_rag_model_chain")
    if not model_chain:
        runtime = _nested_dict(company_filings, "visual_rag_runtime")
        model_chain = _nested_dict(runtime, "model_chain")
    candidate_rows = [
        row for row in model_chain.get("candidate_rows") or [] if isinstance(row, dict)
    ]
    if not candidate_rows:
        return []
    rejected_reasons = {
        _model_chain_row_key(row): str(row.get("rejection_reason") or "")
        for row in model_chain.get("rejected_candidates") or []
        if isinstance(row, dict)
    }
    runtime_model = str(
        company_filings.get("visual_rag_runtime_model")
        or _nested_dict(company_filings, "visual_rag_runtime").get("runtime_model")
        or ""
    )
    quota_mode = (
        "hard_routing"
        if model_chain.get("quota_hard_routing_enabled")
        else "tracking_only"
    )
    return [
        {
            "順位": row.get("rank"),
            "模型": row.get("model") or "-",
            "Vision": "yes" if row.get("vision_supported") else "excluded",
            "Runtime": "selected" if str(row.get("model") or "") == runtime_model else "-",
            "Key": _key_status(row),
            "每日請求額度": _budget_value(row.get("request_budget")),
            "Token 額度": _budget_value(row.get("token_budget")),
            "類型": row.get("routing_tier") or "-",
            "額度治理": quota_mode,
            "狀態/排除原因": rejected_reasons.get(
                _model_chain_row_key(row),
                "vision_candidate",
            ),
        }
        for row in candidate_rows
    ]


def _company_filings_status(service_snapshot: dict) -> dict:
    return _nested_dict(service_snapshot, "company_filings")


def _nested_dict(payload: dict, key: str) -> dict:
    value = payload.get(key) if isinstance(payload, dict) else {}
    return value if isinstance(value, dict) else {}


def _ready_label(value: bool, *, optional: bool = False) -> str:
    if value:
        return "ready"
    return "optional" if optional else "not_ready"


def _runtime_detail(runtime: dict) -> str:
    fallback_reason = str(runtime.get("fallback_reason") or "").strip()
    if fallback_reason:
        return fallback_reason
    if runtime.get("runtime_available") is True:
        return "runtime_available"
    if runtime.get("configured") is True:
        return "configured"
    if runtime.get("enabled") is False:
        return "disabled"
    return "-"


def _model_chain_row_key(row: dict) -> tuple[object, str, str]:
    return (
        row.get("rank"),
        str(row.get("model") or ""),
        str(row.get("model_key") or ""),
    )


def _key_status(row: dict) -> str:
    value = row.get("key_configured")
    if value is True:
        return "ready"
    if value is False:
        return "missing"
    return "-"


def _budget_value(value: object) -> object:
    if value is None:
        return "-"
    return value
