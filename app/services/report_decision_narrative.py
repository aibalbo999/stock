from __future__ import annotations

from app.models.schemas import NewsDocument, ReportRequest, RiskType
from app.services import report_allocation, report_decision_rules, report_formatting
from app.services.leading_signals import LeadingSignal


def decision_reason(
    rating: str,
    estimate: dict,
    quality: dict,
    related_findings,
    related_documents: list[NewsDocument],
    downside_gate: int,
    request: ReportRequest,
    leading_signal: LeadingSignal | None = None,
) -> str:
    if rating == "資料不足":
        return "缺少可驗證市場資料。"
    if rating == "避開 / 降低曝險":
        return report_decision_rules.risk_warning_reason(estimate)
    if rating == "觀察 / 等風險降低":
        financial = estimate.get("financial_assessment") or {}
        if financial.get("red_flag"):
            return (
                "財務/估值紅旗尚未解除："
                f"{financial.get('risk_summary', '需補財務與估值覆核')}；即使題材分數較高，也先列觀察。"
            )
        if leading_signal and leading_signal.direction == "偏空":
            return (
                f"近況訊號偏空（{leading_signal.summary}），"
                "先等量價、營收或估值訊號修復。"
            )
        if estimate.get("downside_pct", 0) > downside_gate:
            return (
                f"目前情境降值分 {estimate['downside_pct']} 分已超過 {downside_gate} 分，"
                f"依{report_allocation.profile_label(request)}設定先列觀察。"
            )
        if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
            return structural_bottleneck_reason(related_findings)
        return "目前仍有風險條件未完全通過，先等新資料確認。"
    if rating == "觀察":
        if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
            return "主要證據偏短期波動，需追蹤後續訂單、庫存與出貨變化。"
        if related_documents:
            return "已有公司相關文本證據，但尚未形成足夠的目前情境升值/降值差距。"
        return "目前情境升值/降值差距不足，先觀察。"
    if rating == "觀察 / 資料待補":
        if any(finding.risk_type == RiskType.insufficient_data for finding in related_findings):
            return "模型或來源判定資料仍不足；補齊公司層級來源、財報與估值後再重新評估。"
        return "目前情境升值分高於 10，但資料層尚未完整；" + "、".join(quality["missing"]) + "。"
    if rating == "可小額分批研究":
        return (
            f"目前情境升值分高於 10 分，情境降值分未超過 {downside_gate} 分設定門檻，"
            "資料層完整，且未偵測到財務/估值紅旗。"
        )
    return "目前只有單日價量資料，缺少新聞、財報或法說證據支撐投資結論。"


def structural_bottleneck_reason(related_findings) -> str:
    bottlenecks = [
        finding for finding in related_findings if finding.risk_type == RiskType.structural_bottleneck
    ]
    if not bottlenecks:
        return "瓶頸或限制證據尚未釐清，先等待風險緩解，不列入本次配置。"

    evidence_labels = []
    seen: set[str] = set()
    for finding in bottlenecks:
        evidence = report_formatting.compact_text(
            finding.evidence or finding.topic or finding.source.title,
            max_chars=64,
        )
        if not evidence or evidence in seen:
            continue
        seen.add(evidence)
        source_parts = []
        if finding.source.published_at:
            source_parts.append(finding.source.published_at.isoformat())
        if finding.source.publisher:
            source_parts.append(finding.source.publisher)
        source_label = " ".join(source_parts)
        evidence_labels.append(f"{evidence}（{source_label}）" if source_label else evidence)
        if len(evidence_labels) >= 2:
            break

    if not evidence_labels:
        evidence_labels.append("來源指出供給、產能、技術轉換或成本限制仍需追蹤")
    return "瓶頸/限制證據：" + "；".join(evidence_labels) + "。先等待公司文件、月營收或法說確認風險緩解，不列入本次配置。"
