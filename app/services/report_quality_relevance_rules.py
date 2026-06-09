from __future__ import annotations


def adjusted_source_relevance_counts(
    source_relevance: dict | None,
    *,
    market_count: int,
    monthly_revenue_count: int,
    valuation_count: int,
    financial_metrics_count: int,
) -> tuple[int, int]:
    source_relevance = source_relevance or {}
    missing_subtopic_count = int(source_relevance.get("missing_subtopic_count") or 0)
    weak_subtopic_count = int(source_relevance.get("weak_subtopic_count") or 0)
    subtopic_readiness = source_relevance.get("subtopic_readiness") or {}
    adjusted_missing_subtopics = []
    adjusted_weak_subtopics = []
    for name, readiness in subtopic_readiness.items():
        status = str((readiness or {}).get("status") or "")
        if status not in {"missing", "weak"}:
            continue
        if _is_financial_subtopic_covered(
            name,
            market_count=market_count,
            monthly_revenue_count=monthly_revenue_count,
            valuation_count=valuation_count,
            financial_metrics_count=financial_metrics_count,
        ):
            continue
        if status == "missing":
            adjusted_missing_subtopics.append(name)
        else:
            adjusted_weak_subtopics.append(name)
    if adjusted_missing_subtopics:
        missing_subtopic_count = len(adjusted_missing_subtopics)
    if adjusted_weak_subtopics:
        weak_subtopic_count = len(adjusted_weak_subtopics)
    return missing_subtopic_count, weak_subtopic_count


def source_relevance_notes(
    *,
    missing_subtopic_count: int,
    weak_subtopic_count: int,
    source_count: int,
    unique_publishers: int,
) -> tuple[list[str], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    observations: list[str] = []
    if missing_subtopic_count:
        blockers.append(f"AI 拆解子題仍有 {missing_subtopic_count} 個完全缺少相關來源")
    if weak_subtopic_count:
        if not missing_subtopic_count and source_count >= 100 and unique_publishers >= 20:
            observations.append(
                f"主題拆解仍有 {weak_subtopic_count} 個子題可持續追蹤，已由多來源資料覆蓋主要結論"
            )
        else:
            warnings.append(f"AI 拆解子題仍有 {weak_subtopic_count} 個來源或資料意圖不足")
    return blockers, warnings, observations


def _is_financial_subtopic_covered(
    name: object,
    *,
    market_count: int,
    monthly_revenue_count: int,
    valuation_count: int,
    financial_metrics_count: int,
) -> bool:
    lower_name = str(name).lower()
    financial_terms = ["財務", "估值", "股價", "營收", "現金流"]
    return (
        any(term in lower_name for term in financial_terms)
        and market_count > 0
        and monthly_revenue_count > 0
        and valuation_count > 0
        and financial_metrics_count > 0
    )
