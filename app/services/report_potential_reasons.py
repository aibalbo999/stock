from __future__ import annotations

from app.models.schemas import MonthlyRevenue, NewsDocument
from app.services.leading_signals import LeadingSignal


def has_month_over_month_revenue_decline_text(documents: list[NewsDocument]) -> bool:
    decline_patterns = [
        "月減",
        "月下滑",
        "月營收下滑",
        "營收下滑",
        "較上月下滑",
        "較上月減",
        "mom",
    ]
    for document in documents:
        text = f"{document.title}\n{document.text[:500]}".lower()
        if "營收" in text and any(pattern in text for pattern in decline_patterns):
            return True
    return False


def month_over_month_revenue_caveat(
    documents: list[NewsDocument],
    monthly_revenue: MonthlyRevenue | None,
) -> str:
    if not monthly_revenue or monthly_revenue.yoy_pct is None or monthly_revenue.yoy_pct <= 0:
        return ""
    if not has_month_over_month_revenue_decline_text(documents):
        return ""
    return (
        f"月營收年增率 {monthly_revenue.yoy_pct:.2f}% 屬 YoY 年增；"
        "來源標題若提到營收下滑，多半是在描述 MoM 月減或單月高檔回落。"
        "本系統已把兩者拆開：YoY 可支撐需求成長，但 MoM 下滑仍列為短期觀察。"
    )


def format_potential_factors(factors: list[tuple[str, int]]) -> str:
    if not factors:
        return "未觸發"
    return "、".join(f"{label} +{score}" for label, score in factors)


def upside_evidence_reason_prefix(
    document_count: int,
    positive_hits: int,
    opportunity_findings: int,
    evidence_score: int,
) -> str:
    if evidence_score > 0:
        return f"有 {document_count} 筆公司相關文本，正向關鍵證據 {positive_hits} 項、機會歸因 {opportunity_findings} 筆"
    if document_count:
        return f"公司相關文本 {document_count} 筆；新聞/RAG 本身未形成主要升值加分"
    return "缺少公司相關文本"


def downside_evidence_reason_prefix(
    negative_hits: int,
    structural_findings: int,
    volatility_findings: int,
    news_risk_score: int,
) -> str:
    if news_risk_score <= 0:
        return "新聞/RAG 未偵測到主要負向或瓶頸證據"
    parts = []
    if negative_hits:
        parts.append(f"文字風險關鍵字 {negative_hits} 項")
    if structural_findings:
        parts.append(f"結構性瓶頸歸因 {structural_findings} 筆")
    if volatility_findings:
        parts.append(f"短期波動歸因 {volatility_findings} 筆")
    return "偵測到" + "、".join(parts)


def revenue_reason(
    monthly_revenue: MonthlyRevenue | None,
    score_delta: int,
    positive: bool,
) -> str:
    if not monthly_revenue or monthly_revenue.yoy_pct is None:
        return ""
    direction = "正向加分" if positive else "風險加分"
    if score_delta <= 0:
        return f"，月營收年增率 {monthly_revenue.yoy_pct:.2f}% 未觸發{direction}"
    return f"，月營收年增率 {monthly_revenue.yoy_pct:.2f}% 觸發{direction} {score_delta} 點"


def leading_signal_reason(leading_signal: LeadingSignal | None, positive: bool) -> str:
    if not leading_signal:
        return ""
    if positive and leading_signal.direction == "偏空":
        return ""
    if not positive and leading_signal.direction == "偏多":
        return ""
    score = leading_signal.upside_bonus if positive else leading_signal.downside_penalty
    if score <= 0:
        return ""
    if leading_signal.direction == "中性":
        label = "近況正向子項目" if positive else "近況風險子項目"
        direction = "加分" if positive else "風險加分"
        return f"，{label}{direction} {score} 點"
    direction = "正向加分" if positive else "風險加分"
    return f"，近況訊號{leading_signal.direction}觸發{direction} {score} 點"


def leading_signal_factor_label(leading_signal: LeadingSignal, positive: bool) -> str:
    if leading_signal.direction == "中性":
        return "近況正向子項目" if positive else "近況風險子項目"
    return "近況訊號偏多" if positive else "近況訊號偏空"


def financial_assessment_reason(assessment: dict, positive: bool) -> str:
    if not assessment or not assessment.get("has_inputs"):
        return ""
    score_key = "upside_score" if positive else "risk_score"
    score = int(assessment.get(score_key) or 0)
    if score <= 0:
        return ""
    label = assessment.get("upside_summary" if positive else "risk_summary")
    direction = "正向加分" if positive else "風險加分"
    scope = "長期/已揭露財務與目前估值"
    return f"，{scope}{direction} {score} 點（{label}）"


def scoring_text_for_document(document: NewsDocument) -> str:
    if document.id.startswith("filing-"):
        return document.title
    return f"{document.title}\n{document.text[:1200]}"


__all__ = [
    "downside_evidence_reason_prefix",
    "financial_assessment_reason",
    "format_potential_factors",
    "has_month_over_month_revenue_decline_text",
    "leading_signal_factor_label",
    "leading_signal_reason",
    "month_over_month_revenue_caveat",
    "revenue_reason",
    "scoring_text_for_document",
    "upside_evidence_reason_prefix",
]
