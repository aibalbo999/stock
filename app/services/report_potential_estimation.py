from __future__ import annotations

from dataclasses import dataclass, field

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    RiskType,
    ValuationMetric,
)
from app.services.leading_signals import LeadingSignal
from app.services.report_financial_assessment import financial_valuation_assessment
from app.services.report_potential_quality import data_quality_grade_for
from app.services.report_potential_reasons import (
    downside_evidence_reason_prefix,
    financial_assessment_reason,
    leading_signal_factor_label,
    leading_signal_reason,
    month_over_month_revenue_caveat,
    revenue_reason,
    scoring_text_for_document,
    upside_evidence_reason_prefix,
)
from app.services.scoring_engine import PotentialScoringEngine


@dataclass(frozen=True)
class PotentialEvidenceSignals:
    positive_hits: int
    negative_hits: int
    structural_findings: int
    volatility_findings: int
    opportunity_findings: int
    mom_revenue_caveat: str


@dataclass
class PotentialEstimateState:
    scoring: PotentialScoringEngine = field(default_factory=PotentialScoringEngine)
    upside_pct: int = 0
    downside_pct: int = 0
    upside_factors: list[tuple[str, int]] = field(default_factory=list)
    downside_factors: list[tuple[str, int]] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    evidence_score: int = 0
    news_risk_score: int = 0
    revenue_upside_bonus: int = 0
    revenue_downside_penalty: int = 0


def estimate_potential_for(
    related_documents: list[NewsDocument],
    related_findings,
    snapshot: MarketSnapshot | None,
    monthly_revenue: MonthlyRevenue | None = None,
    leading_signal: LeadingSignal | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    peer_valuation_summary: dict[str, float | None] | None = None,
) -> dict:
    if not snapshot:
        return _missing_market_estimate(
            related_documents,
            financial_metrics,
            valuation,
            peer_valuation_summary,
        )

    signals = _evidence_signals(related_documents, related_findings, monthly_revenue)
    state = PotentialEstimateState()
    _apply_news_scores(state, signals, document_count=len(related_documents))
    _apply_revenue_scores(state, monthly_revenue)
    _apply_leading_signal_scores(state, leading_signal)
    financial_assessment = _apply_financial_assessment(
        state,
        financial_metrics,
        valuation,
        peer_valuation_summary,
    )
    upside_cap_note = _apply_financial_red_flag_cap(state, financial_assessment)
    _append_evidence_confidence_notes(state, related_documents, related_findings)
    quality = data_quality_grade_for(
        related_documents,
        related_findings,
        snapshot,
        monthly_revenue,
    )
    return _estimate_payload(
        state,
        signals,
        related_documents=related_documents,
        related_findings=related_findings,
        snapshot=snapshot,
        monthly_revenue=monthly_revenue,
        leading_signal=leading_signal,
        financial_assessment=financial_assessment,
        upside_cap_note=upside_cap_note,
        quality=quality,
    )


def early_potential_profile(
    related_documents: list[NewsDocument],
    monthly_revenue: MonthlyRevenue | None,
    leading_signal: LeadingSignal | None,
    upside_pct: int,
    downside_pct: int,
    snapshot: MarketSnapshot | None = None,
    document_count_override: int | None = None,
    publisher_count_override: int | None = None,
) -> dict:
    document_count = (
        document_count_override if document_count_override is not None else len(related_documents)
    )
    publisher_count = _publisher_count(
        related_documents,
        publisher_count_override=publisher_count_override,
    )
    scoring = PotentialScoringEngine()
    attention_label, attention_bonus = scoring.early_attention(
        document_count=document_count,
        publisher_count=publisher_count,
        trading_money=snapshot.trading_money if snapshot else None,
    )
    signal_bonus, reasons = _early_signal_bonus_and_reasons(
        scoring,
        document_count=document_count,
        publisher_count=publisher_count,
        monthly_revenue=monthly_revenue,
        leading_signal=leading_signal,
        downside_pct=downside_pct,
    )
    return {
        "early_potential_score": scoring.early_score(
            attention_bonus=attention_bonus,
            signal_bonus=signal_bonus,
            upside_pct=upside_pct,
        ),
        "attention_label": attention_label,
        "attention_document_count": document_count,
        "attention_publisher_count": publisher_count,
        "early_potential_reason": _early_potential_reason(attention_label, reasons),
    }


def _missing_market_estimate(
    related_documents: list[NewsDocument],
    financial_metrics: list[FinancialMetric] | None,
    valuation: ValuationMetric | None,
    peer_valuation_summary: dict[str, float | None] | None,
) -> dict:
    return {
        "upside_pct": 0,
        "downside_pct": 0,
        "upside_reason": "缺少市場資料。",
        "downside_reason": "缺少市場資料。",
        "upside_factors": [],
        "downside_factors": [],
        "confidence_notes": ["缺少市場資料"],
        "evidence_grade": "weak",
        "early_potential_score": 0,
        "attention_label": "未評估",
        "attention_document_count": len(related_documents),
        "attention_publisher_count": 0,
        "early_potential_reason": "缺少市場資料，不能判斷是否為早期潛力股。",
        "financial_assessment": financial_valuation_assessment(
            financial_metrics,
            valuation,
            peer_valuation_summary,
        ),
        "financial_red_flag": False,
    }


def _evidence_signals(
    related_documents: list[NewsDocument],
    related_findings,
    monthly_revenue: MonthlyRevenue | None,
) -> PotentialEvidenceSignals:
    text = "\n".join(
        [scoring_text_for_document(document) for document in related_documents]
        + [finding.evidence for finding in related_findings]
    )
    positive_hits = sum(1 for keyword in _positive_keywords() if keyword in text)
    negative_hits = sum(1 for keyword in _negative_keywords() if keyword in text)
    mom_revenue_caveat = month_over_month_revenue_caveat(
        related_documents,
        monthly_revenue,
    )
    if mom_revenue_caveat and negative_hits:
        negative_hits = max(0, negative_hits - 1)
    return PotentialEvidenceSignals(
        positive_hits=positive_hits,
        negative_hits=negative_hits,
        structural_findings=_risk_type_count(related_findings, RiskType.structural_bottleneck),
        volatility_findings=_risk_type_count(related_findings, RiskType.short_term_volatility),
        opportunity_findings=_risk_type_count(related_findings, RiskType.opportunity_or_growth),
        mom_revenue_caveat=mom_revenue_caveat,
    )


def _positive_keywords() -> tuple[str, ...]:
    return ("成長", "大單", "擴產", "需求", "受惠", "看好", "上調", "旺", "爆發", "滿載")


def _negative_keywords() -> tuple[str, ...]:
    return ("下滑", "重摔", "毛利", "禁令", "制裁", "缺電", "產能不足", "吃緊", "延遲", "鬆動")


def _risk_type_count(related_findings, risk_type: RiskType) -> int:
    return sum(1 for finding in related_findings if finding.risk_type == risk_type)


def _apply_news_scores(
    state: PotentialEstimateState,
    signals: PotentialEvidenceSignals,
    *,
    document_count: int,
) -> None:
    state.evidence_score, state.upside_pct = state.scoring.news_upside_score(
        document_count=document_count,
        positive_hits=signals.positive_hits,
        opportunity_findings=signals.opportunity_findings,
    )
    if state.evidence_score:
        state.upside_factors.append(
            (
                f"公司相關文本 {document_count} 筆、正向關鍵證據 {signals.positive_hits} 項、"
                f"機會歸因 {signals.opportunity_findings} 筆",
                state.evidence_score,
            )
        )
    state.news_risk_score, state.downside_pct = state.scoring.news_downside_score(
        negative_hits=signals.negative_hits,
        structural_findings=signals.structural_findings,
        volatility_findings=signals.volatility_findings,
    )
    if state.news_risk_score:
        state.downside_factors.append(
            (
                f"負向字詞 {signals.negative_hits} 項、結構性瓶頸 "
                f"{signals.structural_findings} 筆、短期波動 {signals.volatility_findings} 筆",
                state.news_risk_score,
            )
        )


def _apply_revenue_scores(
    state: PotentialEstimateState,
    monthly_revenue: MonthlyRevenue | None,
) -> None:
    if monthly_revenue and monthly_revenue.yoy_pct is not None:
        _apply_revenue_yoy_scores(state, monthly_revenue)
    elif monthly_revenue:
        state.confidence_notes.append("月營收缺去年同期比較")
    else:
        state.confidence_notes.append("缺少月營收資料")


def _apply_revenue_yoy_scores(
    state: PotentialEstimateState,
    monthly_revenue: MonthlyRevenue,
) -> None:
    state.revenue_upside_bonus = state.scoring.revenue_upside_bonus(monthly_revenue.yoy_pct)
    state.revenue_downside_penalty = state.scoring.revenue_downside_penalty(
        monthly_revenue.yoy_pct
    )
    if state.revenue_upside_bonus:
        state.upside_pct = state.scoring.activate_upside(
            state.upside_pct,
            state.revenue_upside_bonus,
        )
        state.upside_factors.append(
            (f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", state.revenue_upside_bonus)
        )
    elif state.revenue_downside_penalty:
        state.downside_pct = state.scoring.activate_downside(
            state.downside_pct,
            state.revenue_downside_penalty,
        )
        state.downside_factors.append(
            (f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", state.revenue_downside_penalty)
        )


def _apply_leading_signal_scores(
    state: PotentialEstimateState,
    leading_signal: LeadingSignal | None,
) -> None:
    if not leading_signal:
        state.confidence_notes.append("缺少近況訊號")
        return
    if leading_signal.upside_bonus and leading_signal.direction != "偏空":
        state.upside_pct = state.scoring.activate_upside(
            state.upside_pct,
            leading_signal.upside_bonus,
        )
        state.upside_factors.append(
            (
                f"{leading_signal_factor_label(leading_signal, True)}："
                f"{leading_signal.summary}",
                leading_signal.upside_bonus,
            )
        )
    if leading_signal.downside_penalty and leading_signal.direction != "偏多":
        state.downside_pct = state.scoring.activate_downside(
            state.downside_pct,
            leading_signal.downside_penalty,
        )
        state.downside_factors.append(
            (
                f"{leading_signal_factor_label(leading_signal, False)}："
                f"{leading_signal.summary}",
                leading_signal.downside_penalty,
            )
        )
    state.confidence_notes.append(f"近況訊號 {leading_signal.direction}（分數 {leading_signal.score}）")


def _apply_financial_assessment(
    state: PotentialEstimateState,
    financial_metrics: list[FinancialMetric] | None,
    valuation: ValuationMetric | None,
    peer_valuation_summary: dict[str, float | None] | None,
) -> dict:
    assessment = financial_valuation_assessment(
        financial_metrics,
        valuation,
        peer_valuation_summary,
    )
    if assessment["upside_score"]:
        state.upside_pct = state.scoring.activate_upside(
            state.upside_pct,
            assessment["upside_score"],
        )
        state.upside_factors.append(
            (
                f"長期/已揭露財務與目前估值加分：{assessment['upside_summary']}",
                assessment["upside_score"],
            )
        )
    if assessment["risk_score"]:
        state.downside_pct = state.scoring.activate_downside(
            state.downside_pct,
            assessment["risk_score"],
        )
        state.downside_factors.append(
            (
                f"長期/已揭露財務與目前估值風險：{assessment['risk_summary']}",
                assessment["risk_score"],
            )
        )
    if assessment["has_inputs"]:
        state.confidence_notes.append("財務/估值檢查：" + assessment["summary"])
    return assessment


def _apply_financial_red_flag_cap(
    state: PotentialEstimateState,
    financial_assessment: dict,
) -> str:
    if not _should_cap_financial_red_flag_upside(state, financial_assessment):
        return ""
    original_upside = state.upside_pct
    state.upside_pct = state.scoring.config.thresholds.financial_red_flag_upside_cap
    note = (
        f"基本面紅旗（{financial_assessment['risk_summary']}）"
        f"已將升值分從 {original_upside} 分壓低至 {state.upside_pct} 分"
    )
    state.confidence_notes.append(note)
    return note


def _should_cap_financial_red_flag_upside(
    state: PotentialEstimateState,
    financial_assessment: dict,
) -> bool:
    thresholds = state.scoring.config.thresholds
    return bool(
        financial_assessment["red_flag"]
        and int(financial_assessment.get("risk_score") or 0)
        >= thresholds.financial_red_flag_min_risk_score
        and state.upside_pct > thresholds.financial_red_flag_upside_cap
    )


def _append_evidence_confidence_notes(
    state: PotentialEstimateState,
    related_documents: list[NewsDocument],
    related_findings,
) -> None:
    if len(related_documents) < 2:
        state.confidence_notes.append(f"公司相關文本僅 {len(related_documents)} 筆")
    if not related_findings:
        state.confidence_notes.append("無模型驗證後風險/機會證據")


def _estimate_payload(
    state: PotentialEstimateState,
    signals: PotentialEvidenceSignals,
    *,
    related_documents: list[NewsDocument],
    related_findings,
    snapshot: MarketSnapshot,
    monthly_revenue: MonthlyRevenue | None,
    leading_signal: LeadingSignal | None,
    financial_assessment: dict,
    upside_cap_note: str,
    quality: dict,
) -> dict:
    return {
        "upside_pct": state.upside_pct,
        "downside_pct": state.downside_pct,
        "upside_reason": _upside_reason(
            state,
            signals,
            monthly_revenue,
            leading_signal,
            financial_assessment,
            upside_cap_note,
            document_count=len(related_documents),
        ),
        "downside_reason": _downside_reason(
            state,
            signals,
            monthly_revenue,
            leading_signal,
            financial_assessment,
        ),
        "upside_factors": state.upside_factors,
        "downside_factors": state.downside_factors,
        "confidence_notes": state.confidence_notes,
        "evidence_grade": quality["grade"],
        "financial_assessment": financial_assessment,
        "financial_red_flag": financial_assessment["red_flag"],
        "mom_revenue_caveat": signals.mom_revenue_caveat,
        "upside_cap_note": upside_cap_note,
        **early_potential_profile(
            related_documents,
            monthly_revenue,
            leading_signal,
            state.upside_pct,
            state.downside_pct,
            snapshot,
        ),
    }


def _upside_reason(
    state: PotentialEstimateState,
    signals: PotentialEvidenceSignals,
    monthly_revenue: MonthlyRevenue | None,
    leading_signal: LeadingSignal | None,
    financial_assessment: dict,
    upside_cap_note: str,
    *,
    document_count: int,
) -> str:
    if not state.upside_pct:
        return "正向證據未達 >10 分情境門檻。"
    reason = (
        upside_evidence_reason_prefix(
            document_count,
            signals.positive_hits,
            signals.opportunity_findings,
            state.evidence_score,
        )
        + revenue_reason(monthly_revenue, state.revenue_upside_bonus, True)
        + leading_signal_reason(leading_signal, True)
        + financial_assessment_reason(financial_assessment, True)
        + "。"
    )
    return reason + (f" {upside_cap_note}。" if upside_cap_note else "")


def _downside_reason(
    state: PotentialEstimateState,
    signals: PotentialEvidenceSignals,
    monthly_revenue: MonthlyRevenue | None,
    leading_signal: LeadingSignal | None,
    financial_assessment: dict,
) -> str:
    if not state.downside_pct:
        return "風險證據未達 >5 分情境門檻。"
    return (
        downside_evidence_reason_prefix(
            signals.negative_hits,
            signals.structural_findings,
            signals.volatility_findings,
            state.news_risk_score,
        )
        + revenue_reason(monthly_revenue, state.revenue_downside_penalty, False)
        + leading_signal_reason(leading_signal, False)
        + financial_assessment_reason(financial_assessment, False)
        + "。"
    )


def _publisher_count(
    related_documents: list[NewsDocument],
    *,
    publisher_count_override: int | None,
) -> int:
    if publisher_count_override is not None:
        return publisher_count_override
    return len(
        {document.source.publisher or document.source.url or document.title for document in related_documents}
    )


def _early_signal_bonus_and_reasons(
    scoring: PotentialScoringEngine,
    *,
    document_count: int,
    publisher_count: int,
    monthly_revenue: MonthlyRevenue | None,
    leading_signal: LeadingSignal | None,
    downside_pct: int,
) -> tuple[int, list[str]]:
    signal_bonus = 0
    reasons = [f"公司文本 {document_count} 筆 / {publisher_count} 來源"]
    revenue_signal_bonus = scoring.early_revenue_bonus(
        monthly_revenue.yoy_pct if monthly_revenue else None
    )
    if revenue_signal_bonus:
        signal_bonus += revenue_signal_bonus
        reasons.append(f"月營收年增 {monthly_revenue.yoy_pct:.1f}%")
    leading_signal_bonus = scoring.early_leading_signal_bonus(
        leading_signal.upside_bonus if leading_signal else 0
    )
    if leading_signal and leading_signal_bonus:
        signal_bonus += leading_signal_bonus
        reasons.append(f"近況訊號 {leading_signal.direction}：{leading_signal.summary}")
    signal_bonus = _apply_early_downside_penalty(
        scoring,
        signal_bonus,
        downside_pct=downside_pct,
        reasons=reasons,
    )
    return signal_bonus, reasons


def _apply_early_downside_penalty(
    scoring: PotentialScoringEngine,
    signal_bonus: int,
    *,
    downside_pct: int,
    reasons: list[str],
) -> int:
    downside_penalty = scoring.early_downside_penalty(downside_pct)
    if not downside_penalty:
        return signal_bonus
    if downside_pct > scoring.config.early_potential.high_downside_threshold:
        reasons.append("目前情境降值分偏高，需等待風險下降")
    else:
        reasons.append("仍有風險訊號")
    return signal_bonus - downside_penalty


def _early_potential_reason(attention_label: str, reasons: list[str]) -> str:
    if attention_label == "截至目前成交熱度高":
        return "截至目前成交金額偏高，較不像尚未被市場注意的冷門線索。"
    if attention_label == "截至目前大量報導":
        return "截至目前題材已被大量報導，較不像尚未被市場發現。"
    return "；".join(reasons)


__all__ = ["early_potential_profile", "estimate_potential_for"]
