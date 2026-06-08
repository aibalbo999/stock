from __future__ import annotations

from collections import Counter

from app.data_sources.company_filing_discovery import RECOMMENDED_DOCUMENT_TYPES
from app.data_sources.company_filing_http import (
    categorize_company_filing_error,
    is_retryable_company_filing_error_category,
)

__all__ = [
    "COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES",
    "COMPANY_FILING_BROWSER_SETUP_CATEGORIES",
    "COMPANY_FILING_BROADEN_SEARCH_CATEGORIES",
    "COMPANY_FILING_MANUAL_BLOCKING_CATEGORIES",
    "COMPANY_FILING_PDF_SETUP_CATEGORIES",
    "COMPANY_FILING_TEXT_RECOVERY_CATEGORIES",
    "COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES",
    "COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES",
    "LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP",
    "classify_company_filing_error",
    "company_filing_attempt_result",
    "company_filing_error_category_counts",
    "company_filing_error_is_retryable",
    "company_filing_gap_summary",
    "company_filing_next_action_type",
    "company_filing_next_actions",
    "company_filing_next_step",
    "company_filing_status",
    "company_filing_ticker_result",
    "enrich_company_filing_errors",
    "missing_company_filing_document_types",
    "normalize_company_filing_error_category",
    "should_broaden_company_filing_search",
    "should_retry_company_filing_fetch",
]


def classify_company_filing_error(message: str) -> str:
    category = categorize_company_filing_error(message)
    if category in {
        "pdf_no_text",
        "encrypted_pdf",
        "pdf_parse_error",
        "unsupported_pdf_parser",
        "visual_rag_failed",
        "visual_rag_missing_dependency",
        "visual_rag_not_configured",
        "visual_rag_quota",
    }:
        return "manual_text_required"
    if category in {
        "blocked_or_forbidden",
        "blocked_or_placeholder",
        "browser_render_failed",
        "browser_render_not_configured",
    }:
        return "source_access_restricted"
    if is_retryable_company_filing_error_category(category):
        return "retryable_source_error"
    if category in {
        "company_mismatch",
        "document_type_mismatch",
        "too_short",
        "too_large",
        "unsafe_url",
    }:
        return "content_not_usable"
    return "source_fetch_error"


LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP = {
    "retryable_source_error": "upstream_retryable",
    "manual_text_required": "pdf_no_text",
    "source_access_restricted": "blocked_or_forbidden",
    "content_not_usable": "company_mismatch",
    "source_fetch_error": "unknown",
}
COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES = {
    "blocked_or_forbidden",
    "blocked_or_placeholder",
    "browser_render_failed",
}
COMPANY_FILING_BROWSER_SETUP_CATEGORIES = {"browser_render_not_configured"}
COMPANY_FILING_PDF_SETUP_CATEGORIES = {
    "missing_pdf_dependency",
    "unsupported_pdf_parser",
}
COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES = {
    "visual_rag_missing_dependency",
    "visual_rag_not_configured",
}
COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES = {
    "visual_rag_failed",
    "visual_rag_quota",
}
COMPANY_FILING_TEXT_RECOVERY_CATEGORIES = {
    "encrypted_pdf",
    "pdf_no_text",
    "pdf_parse_error",
}
COMPANY_FILING_BROADEN_SEARCH_CATEGORIES = {
    "company_mismatch",
    "document_type_mismatch",
    "http_not_found",
    "missing_pdf_link",
    "too_large",
    "too_short",
    "website_not_found",
}
COMPANY_FILING_MANUAL_BLOCKING_CATEGORIES = {
    *COMPANY_FILING_BROWSER_SETUP_CATEGORIES,
    *COMPANY_FILING_PDF_SETUP_CATEGORIES,
    *COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES,
    *COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES,
    *COMPANY_FILING_TEXT_RECOVERY_CATEGORIES,
    "unsafe_url",
    "unknown",
}


def enrich_company_filing_errors(errors: list[dict], ticker: str, company_name: str) -> list[dict]:
    enriched = []
    for error in errors:
        message = str(error.get("error", ""))
        category = normalize_company_filing_error_category(error)
        retryable = error.get("retryable")
        if retryable is None:
            retryable = is_retryable_company_filing_error_category(category)
        enriched.append(
            {
                **error,
                "ticker": ticker,
                "company_name": company_name,
                "category": category,
                "legacy_category": error.get("legacy_category")
                or classify_company_filing_error(message),
                "retryable": bool(retryable),
            }
        )
    return enriched


def normalize_company_filing_error_category(error: dict) -> str:
    raw_category = str(error.get("category") or "")
    if raw_category and raw_category not in LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP:
        return raw_category
    detected = categorize_company_filing_error(error.get("error", ""))
    if detected != "unknown":
        return detected
    return LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP.get(raw_category, "unknown")


def should_retry_company_filing_fetch(documents: list, errors: list[dict]) -> bool:
    if documents or not errors:
        return False
    return all(company_filing_error_is_retryable(error) for error in errors)


def should_broaden_company_filing_search(
    documents: list,
    errors: list[dict],
    document_types: list[str] | None,
) -> bool:
    return bool(missing_company_filing_document_types(documents, document_types))


def missing_company_filing_document_types(
    documents: list,
    document_types: list[str] | None,
) -> list[str]:
    if not document_types:
        return []
    available_types = {getattr(document, "document_type", "") for document in documents}
    return [
        document_type for document_type in document_types if document_type not in available_types
    ]


def company_filing_attempt_result(strategy: str, documents: list, errors: list[dict]) -> dict:
    category_counts = company_filing_error_category_counts(errors)
    return {
        "strategy": strategy,
        "stored_count": len(documents),
        "error_count": len(errors),
        "error_categories": sorted(category_counts),
        "error_category_counts": category_counts,
        "retryable_error_count": sum(
            1 for error in errors if company_filing_error_is_retryable(error)
        ),
    }


def company_filing_ticker_result(
    ticker: str,
    company_name: str,
    documents: list,
    target_document_types: tuple[str, ...],
    errors: list[dict],
    attempts: list[dict] | None = None,
) -> dict:
    document_types = sorted({document.document_type for document in documents})
    missing_required = [
        document_type
        for document_type in target_document_types
        if document_type not in document_types
    ]
    missing_recommended = [
        document_type
        for document_type in RECOMMENDED_DOCUMENT_TYPES
        if document_type not in document_types and document_type not in target_document_types
    ]
    error_category_counts = company_filing_error_category_counts(errors)
    error_categories = sorted(error_category_counts)
    retryable_error_count = sum(1 for error in errors if company_filing_error_is_retryable(error))
    status = company_filing_status(documents, missing_required, error_categories)
    return {
        "ticker": ticker,
        "company_name": company_name,
        "stored_count": len(documents),
        "document_types": document_types,
        "missing_required_types": missing_required,
        "missing_recommended_types": missing_recommended,
        "error_count": len(errors),
        "error_categories": error_categories,
        "error_category_counts": error_category_counts,
        "retryable_error_count": retryable_error_count,
        "non_retryable_error_count": len(errors) - retryable_error_count,
        "attempts": attempts or [],
        "status": status,
        "next_step": company_filing_next_step(
            status,
            missing_required,
            missing_recommended,
            error_categories,
        ),
    }


def company_filing_status(
    documents: list,
    missing_required: list[str],
    error_categories: list[str],
) -> str:
    if documents and not missing_required:
        return "sufficient"
    if not documents and not error_categories:
        return "broader_search_recommended"
    category_set = set(error_categories)
    if category_set & COMPANY_FILING_MANUAL_BLOCKING_CATEGORIES:
        return "needs_manual_source"
    if any(is_retryable_company_filing_error_category(category) for category in category_set):
        return "retry_recommended"
    if category_set and category_set.issubset(COMPANY_FILING_BROADEN_SEARCH_CATEGORIES):
        return "broader_search_recommended"
    return "needs_manual_source"


def company_filing_next_step(
    status: str,
    missing_required: list[str],
    missing_recommended: list[str],
    error_categories: list[str] | None = None,
) -> str:
    category_set = set(error_categories or [])
    if category_set & COMPANY_FILING_BROWSER_SETUP_CATEGORIES:
        return "官方頁面疑似需要動態渲染；請設定 Browserless/Playwright 渲染服務後再自動補抓。"
    if category_set & COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES:
        return "官方頁面疑似被反爬蟲或登入頁擋住；系統應改用 Proxy 或 Browser render/unlocker 後重試官方搜尋。"
    if category_set & COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES:
        return "掃描型或複雜 PDF 需要 Visual RAG 後援；請確認 PyMuPDF、COMPANY_FILING_VISUAL_RAG_MODEL 與 vision LLM key/gateway 已配置。"
    if category_set & COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES:
        return "Visual RAG 後援已觸發但未產生可用文字；請檢查 VLM 額度/模型回應，或改用官方 HTML/文字版與人工匯入。"
    if category_set & COMPANY_FILING_PDF_SETUP_CATEGORIES:
        return "PDF 解析相依套件不足；請安裝 PDF 額外相依套件後再重試公司公開文件補抓。"
    if category_set & COMPANY_FILING_TEXT_RECOVERY_CATEGORIES:
        return "PDF 無法抽取可用文字；請改用官方 HTML/文字版，或先 OCR 後人工匯入。"
    if category_set & {"company_mismatch", "document_type_mismatch"}:
        return "抓到的文件與公司或文件類型不符；系統應擴大官方入口搜尋並避免採用錯誤公司證據。"
    if status == "sufficient" and not missing_recommended:
        return "公司公開文件已足夠進入個股分析。"
    if status == "retry_recommended":
        return "資料源暫時不穩，系統可稍後自動重試同一批官方搜尋。"
    if status == "broader_search_recommended":
        return "目前搜尋不到足夠文件，系統應擴大官方入口與公司 IR 查詢後再重跑。"
    missing = missing_required or missing_recommended
    if missing:
        return (
            "請補官方文件："
            + "、".join(missing)
            + "；可使用 MOPS、TWSE/TPEx 或公司 IR 的 HTML/PDF/文字版。"
        )
    return "請改用公司 IR/MOPS 官方 URL 或人工貼上文件文字。"


def company_filing_next_actions(per_ticker_results: list[dict]) -> list[dict]:
    actions = []
    for row in per_ticker_results:
        if row["status"] == "sufficient":
            continue
        action_type = company_filing_next_action_type(row)
        actions.append(
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "action": action_type,
                "reason": row["next_step"],
                "missing_required_types": row["missing_required_types"],
                "missing_recommended_types": row["missing_recommended_types"],
                "error_categories": row.get("error_categories", []),
                "error_category_counts": row.get("error_category_counts", {}),
                "retryable_error_count": row.get("retryable_error_count", 0),
            }
        )
    return actions


def company_filing_next_action_type(row: dict) -> str:
    category_set = set(row.get("error_categories") or [])
    if category_set & COMPANY_FILING_BROWSER_SETUP_CATEGORIES:
        return "configure_company_filing_browser_render"
    if category_set & COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES:
        return "configure_company_filing_visual_rag"
    if category_set & COMPANY_FILING_PDF_SETUP_CATEGORIES:
        return "install_company_filing_pdf_dependencies"
    if category_set & COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES:
        return "review_visual_rag_or_manual_import"
    if category_set & COMPANY_FILING_TEXT_RECOVERY_CATEGORIES:
        return "ocr_or_manual_company_filing_text_import"
    if category_set & COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES:
        return "retry_company_filing_with_browser_or_proxy"
    if category_set & COMPANY_FILING_BROADEN_SEARCH_CATEGORIES:
        return "broaden_company_filing_search"
    return {
        "retry_recommended": "retry_company_filing_search",
        "broader_search_recommended": "broaden_company_filing_search",
    }.get(row.get("status"), "manual_company_filing_import")


def company_filing_gap_summary(per_ticker_results: list[dict]) -> dict:
    status_counts: dict[str, int] = {}
    category_counter: Counter[str] = Counter()
    browser_required = []
    setup_required = []
    ocr_required = []
    visual_rag_setup = []
    visual_rag_review = []
    broaden_search = []
    manual_import = []
    for row in per_ticker_results:
        status = row.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        category_counts = row.get("error_category_counts") or {}
        if category_counts:
            category_counter.update(
                {str(category): int(count) for category, count in category_counts.items()}
            )
        else:
            category_counter.update(str(category) for category in row.get("error_categories") or [])
        category_set = set(row.get("error_categories") or [])
        ticker = row.get("ticker")
        if not ticker:
            continue
        if category_set & COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES:
            browser_required.append(ticker)
        if category_set & (
            COMPANY_FILING_BROWSER_SETUP_CATEGORIES | COMPANY_FILING_PDF_SETUP_CATEGORIES
        ):
            setup_required.append(ticker)
        if category_set & COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES:
            setup_required.append(ticker)
            visual_rag_setup.append(ticker)
        if category_set & COMPANY_FILING_TEXT_RECOVERY_CATEGORIES:
            ocr_required.append(ticker)
        if category_set & COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES:
            visual_rag_review.append(ticker)
        if (
            row.get("status") == "broader_search_recommended"
            or category_set & COMPANY_FILING_BROADEN_SEARCH_CATEGORIES
        ):
            broaden_search.append(ticker)
        if row.get("status") == "needs_manual_source":
            manual_import.append(ticker)
    blocked = [
        row["ticker"]
        for row in per_ticker_results
        if row.get("status") in {"needs_manual_source", "broader_search_recommended"}
    ]
    retryable = [
        row["ticker"] for row in per_ticker_results if row.get("status") == "retry_recommended"
    ]
    if blocked:
        recommendation = "部分公司仍缺官方文件，需先補來源或擴大官方搜尋後再進入完整個股分析。"
    elif retryable:
        recommendation = "部分公司因資料源暫時錯誤而不足，建議稍後自動重試後再重跑分析。"
    else:
        recommendation = "公司文件補強狀態足夠，可進入完整個股分析。"
    return {
        "total_tickers": len(per_ticker_results),
        "status_counts": status_counts,
        "retryable_tickers": retryable,
        "blocked_tickers": blocked,
        "error_category_counts": dict(sorted(category_counter.items())),
        "browser_recovery_tickers": sorted(set(browser_required)),
        "setup_required_tickers": sorted(set(setup_required)),
        "ocr_required_tickers": sorted(set(ocr_required)),
        "visual_rag_setup_tickers": sorted(set(visual_rag_setup)),
        "visual_rag_review_tickers": sorted(set(visual_rag_review)),
        "broaden_search_tickers": sorted(set(broaden_search)),
        "manual_import_tickers": sorted(set(manual_import)),
        "recommendation": recommendation,
    }


def company_filing_error_category_counts(errors: list[dict]) -> dict[str, int]:
    return dict(
        sorted(Counter(normalize_company_filing_error_category(error) for error in errors).items())
    )


def company_filing_error_is_retryable(error: dict) -> bool:
    retryable = error.get("retryable")
    if retryable is not None:
        return bool(retryable)
    return is_retryable_company_filing_error_category(
        normalize_company_filing_error_category(error)
    )
