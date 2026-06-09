from __future__ import annotations

from typing import Any

from app.services.discovery_workflow_settings import (
    discovery_analysis_mode,
    discovery_effective_lookback_days,
)


def summarize_ingestion_stage(results: list[dict]) -> dict:
    stored_count = 0
    error_count = 0
    sample_titles = []
    for result in results:
        stored_count += int(result.get("count") or 0)
        error_count += len(result.get("errors") or [])
        for item in result.get("items") or []:
            title = item.get("title") if isinstance(item, dict) else None
            if title and title not in sample_titles:
                sample_titles.append(title)
            if len(sample_titles) >= 8:
                break
    return {
        "source_runs": len(results),
        "stored_count": stored_count,
        "error_count": error_count,
        "sample_titles": sample_titles,
        "source_category_counts": summarize_source_categories(results),
        "source_intent_counts": summarize_source_intents(results),
        "source_selection": summarize_source_selection(results),
    }


def summarize_source_categories(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        for category, count in (result.get("source_category_counts") or {}).items():
            counts[str(category)] = counts.get(str(category), 0) + int(count or 0)
    return counts


def summarize_source_intents(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for result in results:
        for source_result in result.get("source_results") or []:
            stored_count = int(source_result.get("stored_count") or 0)
            for intent in source_result.get("source_intents") or []:
                counts[str(intent)] = counts.get(str(intent), 0) + stored_count
    return counts


def summarize_source_selection(results: list[dict]) -> dict:
    selected = []
    skipped = []
    for result in results:
        selection = result.get("source_selection") or {}
        selected.extend(selection.get("selected") or [])
        skipped.extend(selection.get("skipped") or [])
    return {
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "selected_sample": selected[:12],
        "skipped_sample": skipped[:12],
    }


def build_source_audit(
    payload: Any,
    urls: list[str],
    fixed_source_ingestion: dict,
    dynamic_query_ingestion: list[dict],
    limit_per_query: int,
    evidence_limit: int,
    max_queries: int,
    query_metadata: list[dict] | None = None,
) -> dict:
    dynamic_summary = summarize_ingestion_stage(dynamic_query_ingestion)
    fixed_summary = summarize_ingestion_stage([fixed_source_ingestion])
    query_metadata = query_metadata or []
    query_type_counts: dict[str, int] = {}
    query_intent_counts: dict[str, int] = {}
    for item in query_metadata:
        source_type = str(item.get("source_type") or "unknown")
        query_type_counts[source_type] = query_type_counts.get(source_type, 0) + 1
        source_intent = str(item.get("source_intent") or "unknown")
        query_intent_counts[source_intent] = query_intent_counts.get(source_intent, 0) + 1
    query_type_labels = {
        source_type: query_type_label(source_type) for source_type in query_type_counts
    }
    query_intent_labels = {
        source_intent: query_intent_label(source_intent) for source_intent in query_intent_counts
    }
    return {
        "topic": payload.topic,
        "lookback_days": payload.lookback_days,
        "effective_lookback_days": discovery_effective_lookback_days(payload),
        "analysis_mode": discovery_analysis_mode(payload),
        "deep_analysis": payload.deep_analysis,
        "include_international": payload.include_international,
        "limit_per_query": limit_per_query,
        "evidence_limit": evidence_limit,
        "max_queries": max_queries,
        "fixed_sources": fixed_summary,
        "dynamic_queries": dynamic_summary,
        "dynamic_query_count": len(urls),
        "dynamic_query_sample": urls[:10],
        "query_type_counts": query_type_counts,
        "query_intent_counts": query_intent_counts,
        "query_intent_labels": query_intent_labels,
        "query_type_labels": query_type_labels,
        "query_metadata_sample": query_metadata[:10],
        "total_stored_count": fixed_summary["stored_count"] + dynamic_summary["stored_count"],
        "total_error_count": fixed_summary["error_count"] + dynamic_summary["error_count"],
    }


def query_type_label(source_type: str) -> dict:
    labels = {
        "research_task": ("研究任務", "由拆解任務的目的、必查證據與風險焦點產生。"),
        "subtopic": ("子題查詢", "由 AI 原始子題搜尋 query 產生。"),
        "subtopic_international": ("子題國際查詢", "由子題 query 延伸的國際市場搜尋。"),
        "candidate": ("候選公司查詢", "用於驗證候選公司與主題證據是否同時存在。"),
        "candidate_international": (
            "候選公司國際查詢",
            "用於查核台股候選公司在國際供應鏈中的證據。",
        ),
        "coverage_gap": ("缺口補強查詢", "系統依拆解品質缺口自動補上的搜尋。"),
        "query_quality_gap": (
            "查詢品質補強",
            "系統依籠統、未對齊或缺國際資料的 query 自動補上的搜尋。",
        ),
        "international_context": ("國際背景查詢", "系統固定加入的國際供應鏈背景搜尋。"),
        "supplemental": ("補抓查詢", "第一次抓取後因證據不足自動追加的搜尋。"),
        "unknown": ("未分類查詢", "尚未分類的查詢來源。"),
    }
    label, description = labels.get(source_type, labels["unknown"])
    return {"label": label, "description": description}


def query_intent_label(source_intent: str) -> dict:
    labels = {
        "industry_news": ("產業新聞", "追蹤需求、供給、競爭與產業變化。"),
        "company_disclosure": ("公司公開資訊", "追蹤法說、年報、重大訊息與公司層級證據。"),
        "financial_metrics": ("財務資料", "追蹤營收、獲利、毛利、現金流與 ROE。"),
        "valuation": ("估值資料", "追蹤本益比、股價、同業估值與評價合理性。"),
        "capacity_supply": ("產能供給", "追蹤產能、良率、交期與供應鏈瓶頸。"),
        "regulatory_policy": ("政策法規", "追蹤出口管制、地緣政治、法規與政策變化。"),
        "international_context": ("國際脈絡", "追蹤海外需求、國際供應鏈與全球市場訊號。"),
        "early_signal": ("早期訊號", "追蹤報導較少、月營收或產能訊號正在轉強的長尾線索。"),
        "unknown": ("未分類意圖", "尚未分類的資料需求。"),
    }
    label, description = labels.get(source_intent, labels["unknown"])
    return {"label": label, "description": description}


__all__ = [
    "build_source_audit",
    "query_intent_label",
    "query_type_label",
    "summarize_ingestion_stage",
    "summarize_source_categories",
    "summarize_source_intents",
    "summarize_source_selection",
]
