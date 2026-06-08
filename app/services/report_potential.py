from __future__ import annotations

from datetime import timedelta

from app.core.time import now_taipei
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
from app.services.report_quality import is_stale_market_data_source
from app.services.scoring_engine import PotentialScoringEngine


def data_quality_grade(
    related_documents: list[NewsDocument],
    related_findings,
    snapshot: MarketSnapshot | None,
    monthly_revenue: MonthlyRevenue | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    include_fundamentals: bool = False,
    leading_signal: LeadingSignal | None = None,
    company_filing_missing: list[str] | None = None,
    recent_source_days: int | None = None,
) -> dict:
    missing = []
    has_company_filing = (
        include_fundamentals
        and company_filing_missing is not None
        and not company_filing_missing
    )
    has_topic_attribution = bool(related_findings) or has_company_filing or len(related_documents) >= 2
    if len(related_documents) < 2 and not has_company_filing:
        missing.append("公司文本不足")
    if not has_topic_attribution:
        missing.append("缺主題歸因")
    if not snapshot:
        missing.append("缺股價")
    elif is_stale_market_data_source(snapshot.source):
        missing.append("股價為快取救援")
    if not monthly_revenue:
        missing.append("缺月營收")
    elif is_stale_market_data_source(monthly_revenue.source):
        missing.append("月營收為快取救援")
    if include_fundamentals and not financial_metrics:
        missing.append("缺已揭露年度財報")
    elif include_fundamentals and any(is_stale_market_data_source(metric.source) for metric in financial_metrics or []):
        missing.append("財報為快取救援")
    if include_fundamentals and not valuation:
        missing.append("缺估值")
    elif include_fundamentals and valuation and is_stale_market_data_source(valuation.source):
        missing.append("估值為快取救援")
    if include_fundamentals and leading_signal is not None and not leading_signal.has_signal_data:
        missing.append("缺近況訊號")
    if include_fundamentals and recent_source_days is not None and related_documents:
        cutoff = now_taipei().date() - timedelta(days=recent_source_days)
        latest_related_date = max(
            (
                document.source.published_at
                for document in related_documents
                if document.source.published_at is not None
            ),
            default=None,
        )
        if latest_related_date is None or latest_related_date < cutoff:
            missing.append(f"缺近 {recent_source_days} 天公司文本")
    if include_fundamentals:
        missing.extend(company_filing_missing or [])

    if not missing:
        grade = "supported"
    elif snapshot and monthly_revenue and financial_metrics and valuation:
        grade = "partial"
    else:
        grade = "weak"
    return {"grade": grade, "missing": missing}


def score_data_note(
    confidence_notes: list[str],
    financial_metrics: list[FinancialMetric],
    valuation: ValuationMetric | None,
) -> str:
    notes = list(confidence_notes)
    if financial_metrics:
        notes.append(f"財報 {len(financial_metrics)} 筆")
    else:
        notes.append("缺財報")
    if valuation:
        notes.append(f"估值 {valuation.trade_date.isoformat()}")
    else:
        notes.append("缺估值")
    return "；".join(notes) if notes else "完整"


def quality_label(grade: str) -> str:
    labels = {
        "supported": "完整",
        "partial": "待補",
        "weak": "不足",
    }
    return labels.get(grade, grade)


def decision_label(
    estimate: dict,
    quality: dict,
    related_findings,
    downside_gate: int,
    leading_signal: LeadingSignal | None = None,
) -> str:
    if "缺股價" in quality["missing"]:
        return "資料不足"
    if estimate["downside_pct"] > estimate["upside_pct"]:
        return "避開 / 降低曝險"
    financial = estimate.get("financial_assessment") or {}
    if financial.get("red_flag") and int(financial.get("risk_score") or 0) >= 5:
        return "避開 / 降低曝險"
    if estimate["downside_pct"] > downside_gate:
        return "觀察 / 等風險降低"
    if leading_signal and leading_signal.direction == "偏空":
        return "觀察 / 等風險降低"
    if financial.get("red_flag"):
        return "觀察 / 等風險降低"
    if any(finding.risk_type == RiskType.insufficient_data for finding in related_findings):
        return "觀察 / 資料待補"
    if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
        return "觀察 / 等風險降低"
    if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
        return "觀察"
    if estimate["upside_pct"] > 10 and quality["grade"] != "supported":
        return "觀察 / 資料待補"
    if estimate["upside_pct"] > 10:
        return "可小額分批研究"
    if quality["grade"] == "weak":
        return "觀察 / 資料不足"
    return "觀察"


def estimate_potential(
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

    text = "\n".join(
        [scoring_text_for_document(document) for document in related_documents]
        + [finding.evidence for finding in related_findings]
    )
    positive_keywords = ["成長", "大單", "擴產", "需求", "受惠", "看好", "上調", "旺", "爆發", "滿載"]
    negative_keywords = ["下滑", "重摔", "毛利", "禁令", "制裁", "缺電", "產能不足", "吃緊", "延遲", "鬆動"]
    positive_hits = sum(1 for keyword in positive_keywords if keyword in text)
    negative_hits = sum(1 for keyword in negative_keywords if keyword in text)
    mom_revenue_caveat = month_over_month_revenue_caveat(
        related_documents,
        monthly_revenue,
    )
    if mom_revenue_caveat and negative_hits:
        negative_hits = max(0, negative_hits - 1)
    structural_findings = sum(
        1 for finding in related_findings if finding.risk_type == RiskType.structural_bottleneck
    )
    volatility_findings = sum(
        1 for finding in related_findings if finding.risk_type == RiskType.short_term_volatility
    )
    opportunity_findings = sum(
        1 for finding in related_findings if finding.risk_type == RiskType.opportunity_or_growth
    )

    scoring = PotentialScoringEngine()
    upside_pct = 0
    downside_pct = 0
    upside_factors: list[tuple[str, int]] = []
    downside_factors: list[tuple[str, int]] = []
    confidence_notes: list[str] = []
    evidence_score = 0
    evidence_score, upside_pct = scoring.news_upside_score(
        document_count=len(related_documents),
        positive_hits=positive_hits,
        opportunity_findings=opportunity_findings,
    )
    if evidence_score:
        upside_factors.append(
            (
                f"公司相關文本 {len(related_documents)} 筆、正向關鍵證據 {positive_hits} 項、機會歸因 {opportunity_findings} 筆",
                evidence_score,
            )
        )
    news_risk_score = 0
    news_risk_score, downside_pct = scoring.news_downside_score(
        negative_hits=negative_hits,
        structural_findings=structural_findings,
        volatility_findings=volatility_findings,
    )
    if news_risk_score:
        downside_factors.append(
            (
                f"負向字詞 {negative_hits} 項、結構性瓶頸 {structural_findings} 筆、短期波動 {volatility_findings} 筆",
                news_risk_score,
            )
        )

    revenue_upside_bonus = 0
    revenue_downside_penalty = 0
    if monthly_revenue and monthly_revenue.yoy_pct is not None:
        revenue_upside_bonus = scoring.revenue_upside_bonus(monthly_revenue.yoy_pct)
        revenue_downside_penalty = scoring.revenue_downside_penalty(monthly_revenue.yoy_pct)
        if revenue_upside_bonus:
            upside_pct = scoring.activate_upside(upside_pct, revenue_upside_bonus)
            upside_factors.append((f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", revenue_upside_bonus))
        elif revenue_downside_penalty:
            downside_pct = scoring.activate_downside(downside_pct, revenue_downside_penalty)
            downside_factors.append((f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", revenue_downside_penalty))
    elif monthly_revenue:
        confidence_notes.append("月營收缺去年同期比較")
    else:
        confidence_notes.append("缺少月營收資料")

    if leading_signal:
        if leading_signal.upside_bonus and leading_signal.direction != "偏空":
            upside_pct = scoring.activate_upside(upside_pct, leading_signal.upside_bonus)
            upside_factors.append(
                (
                    f"{leading_signal_factor_label(leading_signal, True)}：{leading_signal.summary}",
                    leading_signal.upside_bonus,
                )
            )
        if leading_signal.downside_penalty and leading_signal.direction != "偏多":
            downside_pct = scoring.activate_downside(downside_pct, leading_signal.downside_penalty)
            downside_factors.append(
                (
                    f"{leading_signal_factor_label(leading_signal, False)}：{leading_signal.summary}",
                    leading_signal.downside_penalty,
                )
            )
        confidence_notes.append(f"近況訊號 {leading_signal.direction}（分數 {leading_signal.score}）")
    else:
        confidence_notes.append("缺少近況訊號")

    financial_assessment = financial_valuation_assessment(
        financial_metrics,
        valuation,
        peer_valuation_summary,
    )
    if financial_assessment["upside_score"]:
        upside_pct = scoring.activate_upside(upside_pct, financial_assessment["upside_score"])
        upside_factors.append(
            (
                f"長期/已揭露財務與目前估值加分：{financial_assessment['upside_summary']}",
                financial_assessment["upside_score"],
            )
        )
    if financial_assessment["risk_score"]:
        downside_pct = scoring.activate_downside(downside_pct, financial_assessment["risk_score"])
        downside_factors.append(
            (
                f"長期/已揭露財務與目前估值風險：{financial_assessment['risk_summary']}",
                financial_assessment["risk_score"],
            )
        )
    if financial_assessment["has_inputs"]:
        confidence_notes.append("財務/估值檢查：" + financial_assessment["summary"])
    upside_cap_note = ""
    if (
        financial_assessment["red_flag"]
        and int(financial_assessment.get("risk_score") or 0)
        >= scoring.config.thresholds.financial_red_flag_min_risk_score
        and upside_pct > scoring.config.thresholds.financial_red_flag_upside_cap
    ):
        original_upside = upside_pct
        upside_pct = scoring.config.thresholds.financial_red_flag_upside_cap
        upside_cap_note = (
            f"基本面紅旗（{financial_assessment['risk_summary']}）"
            f"已將升值分從 {original_upside} 分壓低至 {upside_pct} 分"
        )
        confidence_notes.append(upside_cap_note)

    if len(related_documents) < 2:
        confidence_notes.append(f"公司相關文本僅 {len(related_documents)} 筆")
    if not related_findings:
        confidence_notes.append("無模型驗證後風險/機會證據")
    quality = data_quality_grade(
        related_documents,
        related_findings,
        snapshot,
        monthly_revenue,
    )

    return {
        "upside_pct": upside_pct,
        "downside_pct": downside_pct,
        "upside_reason": (
            upside_evidence_reason_prefix(
                len(related_documents),
                positive_hits,
                opportunity_findings,
                evidence_score,
            )
            + f"{revenue_reason(monthly_revenue, revenue_upside_bonus, True)}"
            + f"{leading_signal_reason(leading_signal, True)}"
            + f"{financial_assessment_reason(financial_assessment, True)}。"
            + (f" {upside_cap_note}。" if upside_cap_note else "")
            if upside_pct
            else "正向證據未達 >10 分情境門檻。"
        ),
        "downside_reason": (
            downside_evidence_reason_prefix(
                negative_hits,
                structural_findings,
                volatility_findings,
                news_risk_score,
            )
            + f"{revenue_reason(monthly_revenue, revenue_downside_penalty, False)}"
            + f"{leading_signal_reason(leading_signal, False)}"
            + f"{financial_assessment_reason(financial_assessment, False)}。"
            if downside_pct
            else "風險證據未達 >5 分情境門檻。"
        ),
        "upside_factors": upside_factors,
        "downside_factors": downside_factors,
        "confidence_notes": confidence_notes,
        "evidence_grade": quality["grade"],
        "financial_assessment": financial_assessment,
        "financial_red_flag": financial_assessment["red_flag"],
        "mom_revenue_caveat": mom_revenue_caveat,
        "upside_cap_note": upside_cap_note,
        **early_potential_profile(
            related_documents,
            monthly_revenue,
            leading_signal,
            upside_pct,
            downside_pct,
            snapshot,
        ),
    }


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
    publisher_count = (
        publisher_count_override
        if publisher_count_override is not None
        else len({document.source.publisher or document.source.url or document.title for document in related_documents})
    )
    trading_money = snapshot.trading_money if snapshot else None
    scoring = PotentialScoringEngine()
    attention_label, attention_bonus = scoring.early_attention(
        document_count=document_count,
        publisher_count=publisher_count,
        trading_money=trading_money,
    )

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
    downside_penalty = scoring.early_downside_penalty(downside_pct)
    if downside_penalty:
        signal_bonus -= downside_penalty
    if downside_penalty and downside_pct > scoring.config.early_potential.high_downside_threshold:
        reasons.append("目前情境降值分偏高，需等待風險下降")
    elif downside_penalty:
        reasons.append("仍有風險訊號")

    score = scoring.early_score(
        attention_bonus=attention_bonus,
        signal_bonus=signal_bonus,
        upside_pct=upside_pct,
    )
    if attention_label == "截至目前成交熱度高":
        reason = "截至目前成交金額偏高，較不像尚未被市場注意的冷門線索。"
    elif attention_label == "截至目前大量報導":
        reason = "截至目前題材已被大量報導，較不像尚未被市場發現。"
    else:
        reason = "；".join(reasons)
    return {
        "early_potential_score": score,
        "attention_label": attention_label,
        "attention_document_count": document_count,
        "attention_publisher_count": publisher_count,
        "early_potential_reason": reason,
    }


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
    if news_risk_score > 0:
        parts = []
        if negative_hits:
            parts.append(f"文字風險關鍵字 {negative_hits} 項")
        if structural_findings:
            parts.append(f"結構性瓶頸歸因 {structural_findings} 筆")
        if volatility_findings:
            parts.append(f"短期波動歸因 {volatility_findings} 筆")
        return "偵測到" + "、".join(parts)
    return "新聞/RAG 未偵測到主要負向或瓶頸證據"


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
