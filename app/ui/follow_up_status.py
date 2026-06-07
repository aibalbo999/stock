from __future__ import annotations

from typing import Optional


def candidate_revalidation_summary(result: dict) -> dict:
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    revalidation = rerun.get("candidate_revalidation") or {}
    candidates = revalidation.get("candidate_whitelist") or []
    promoted = set(revalidation.get("promoted_tickers") or [])
    supported = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    weak = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "weak_evidence"
    ]
    needs = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "needs_evidence"
    ]
    limited = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_limited"
    ]
    unavailable = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_unavailable"
    ]
    return {
        "changed": bool(revalidation.get("changed")),
        "total": len(candidates),
        "promoted_count": len(promoted) if promoted else len(supported),
        "weak_count": len(weak),
        "needs_evidence_count": len(needs),
        "limited_count": len(limited),
        "unavailable_count": len(unavailable),
        "document_query_count": int(revalidation.get("document_query_count") or 0),
        "document_count": int(revalidation.get("document_count") or 0),
        "newly_promoted": revalidation.get("newly_promoted") or [],
        "no_longer_promoted": revalidation.get("no_longer_promoted") or [],
        "status_changes": revalidation.get("status_changes") or [],
        "rows": [
            {
                "股票": f"{candidate.get('ticker')} {candidate.get('name')}",
                "產業位置": candidate.get("segment"),
                "狀態": {
                    "evidence_supported": "正式分析",
                    "weak_evidence": "弱證據",
                    "needs_evidence": "待補證據",
                    "evidence_limited": "補查後未升格",
                    "evidence_unavailable": "資料不足排除",
                }.get(candidate.get("status"), "待補證據"),
                "證據": f"{candidate.get('evidence_count', 0)} 篇 / {candidate.get('evidence_source_count', 0)} 來源",
                "原因": candidate.get("validation_reason") or "-",
                "下一步": candidate.get("next_action") or "-",
            }
            for candidate in candidates
        ],
    }


def follow_up_result_message(result: dict, summary_text: str) -> tuple[str, str]:
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    if rerun.get("report_id"):
        return "success", f"{summary_text}，已產生新報告 #{rerun['report_id']}。"
    if rerun.get("status") == "skipped":
        blockers = "；".join(rerun.get("blockers") or [])
        reason = rerun.get("reason") or "補資料後仍有關鍵缺口，先不重新產生報告。"
        detail = f"（{blockers}）" if blockers else ""
        return "warning", f"{summary_text}，{reason}{detail}"
    return "success", f"{summary_text}，補強任務已完成。"


def follow_up_check_value_text(value: Optional[dict]) -> str:
    if not value:
        return "-"
    labels = {
        "stored_count": "已取得",
        "error_count": "錯誤",
        "blocked_tickers": "仍缺公司",
        "min_days": "至少天數",
        "min_months": "至少月份",
        "min_years": "至少年數",
        "min_records": "至少筆數",
        "min_documents": "至少文件",
        "status": "狀態",
        "manual_review": "需人工覆核",
    }
    parts = []
    for key, raw_value in value.items():
        label = labels.get(key, key)
        if isinstance(raw_value, list):
            display = "、".join(str(item) for item in raw_value) if raw_value else "無"
        elif isinstance(raw_value, bool):
            display = "是" if raw_value else "否"
        else:
            display = str(raw_value)
        parts.append(f"{label} {display}")
    return "；".join(parts)


def follow_up_blocker_action_rows(result: dict) -> list[dict]:
    rows = []
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    rerun_actions = rerun.get("next_actions") or []
    action_sources = [{"next_actions": rerun_actions}] if rerun_actions else (result.get("results") or {}).values()
    for task_result in action_sources:
        if not isinstance(task_result, dict):
            continue
        for action in task_result.get("next_actions") or []:
            rows.append(
                {
                    "股票": action.get("ticker") or "-",
                    "公司": action.get("company_name") or "-",
                    "下一步": {
                        "manual_company_filing_import": "人工匯入官方文件",
                        "retry_company_filing_search": "稍後自動重試",
                        "broaden_company_filing_search": "擴大官方搜尋",
                        "configure_company_filing_browser_render": "設定瀏覽器後援",
                        "install_company_filing_pdf_dependencies": "安裝 PDF 相依套件",
                        "configure_company_filing_visual_rag": "設定 Visual RAG",
                        "review_visual_rag_or_manual_import": "檢查 Visual RAG/人工匯入",
                        "ocr_or_manual_company_filing_text_import": "OCR 或人工匯入",
                        "retry_company_filing_with_browser_or_proxy": "改用瀏覽器/Proxy 重試",
                        "complete_follow_up_check": "補齊未達標資料",
                    }.get(action.get("action"), action.get("action") or "-"),
                    "缺必要文件": "、".join(action.get("missing_required_types") or []),
                    "缺建議文件": "、".join(action.get("missing_recommended_types") or []),
                    "目前": follow_up_check_value_text(action.get("observed")),
                    "要求": follow_up_check_value_text(action.get("required")),
                    "原因": action.get("reason") or "-",
                }
            )
    if rows:
        return rows
    for blocker in rerun.get("blockers") or []:
        rows.append(
            {
                "股票": "-",
                "公司": "-",
                "下一步": "補齊資料後再重跑",
                "缺必要文件": "-",
                "缺建議文件": "-",
                "目前": "-",
                "要求": "-",
                "原因": blocker,
            }
        )
    return rows
