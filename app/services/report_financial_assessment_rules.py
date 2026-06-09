from __future__ import annotations

from dataclasses import dataclass, field

from app.models.schemas import FinancialMetric, ValuationMetric
from app.services.report_financial_narrative import (
    balance_sheet_total_series,
    debt_equity_phrase,
    metric_series,
)
from app.services.report_quality import is_stale_market_data_source
from app.services.report_valuation_position import valuation_position_label_for


@dataclass
class FinancialAssessmentNotes:
    upside_score: int = 0
    risk_score: int = 0
    strengths: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)

    def add_strength(self, points: int, note: str) -> None:
        self.upside_score += points
        self.strengths.append(note)

    def add_caution(self, points: int, note: str) -> None:
        self.risk_score += points
        self.cautions.append(note)

    def add_red_flag(self, points: int, note: str) -> None:
        self.risk_score += points
        self.red_flags.append(note)


@dataclass(frozen=True)
class FinancialAssessmentSeries:
    revenue: dict[int, float]
    net_income: dict[int, float]
    latest_revenue: float | None
    latest_net_income: float | None
    equity: dict[int, float]
    liabilities: dict[int, float]


def series_growth_pct(series: dict[int, float]) -> float | None:
    if len(series) < 2:
        return None
    years = sorted(series)
    first = series[years[0]]
    last = series[years[-1]]
    if first == 0:
        return None
    return round((last - first) / abs(first) * 100, 2)


def series_period_text(series: dict[int, float]) -> str:
    years = sorted(series)
    if len(years) < 2:
        return "已揭露年度"
    return f"{years[0]}-{years[-1]} 年度"


def decline_risk_points(growth_pct: float, *, metric: str) -> int:
    decline = abs(growth_pct)
    if metric == "net_income":
        return _net_income_decline_points(decline)
    if decline >= 40:
        return 4
    if decline >= 20:
        return 3
    return 1


def financial_valuation_assessment_payload(
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    peer_summary: dict[str, float | None] | None = None,
) -> dict:
    metrics = financial_metrics or []
    notes = FinancialAssessmentNotes()
    if any(is_stale_market_data_source(metric.source) for metric in metrics):
        notes.cautions.append("財務資料為快取救援，需刷新後覆核")

    series = _financial_assessment_series(metrics)
    revenue_growth = _add_revenue_trend(notes, series.revenue, has_metrics=bool(metrics))
    net_income_growth = _add_net_income_trend(
        notes,
        series.net_income,
        series.latest_net_income,
        has_metrics=bool(metrics),
    )
    _add_net_margin(notes, series.latest_net_income, series.latest_revenue)
    _add_debt_equity(notes, series.liabilities, series.equity, has_metrics=bool(metrics))
    _add_roe(notes, series.latest_net_income, series.equity)
    _add_valuation_position(notes, valuation, peer_summary or {}, metrics)
    _add_combined_decline_flag(notes, revenue_growth, net_income_growth)
    return _assessment_payload(notes, has_inputs=bool(metrics or valuation))


def peer_valuation_summary(valuations: list[ValuationMetric]) -> dict[str, float | None]:
    pe_values = [
        valuation.pe_ratio
        for valuation in valuations
        if valuation.pe_ratio is not None and valuation.pe_ratio > 0
    ]
    pb_values = [
        valuation.pb_ratio
        for valuation in valuations
        if valuation.pb_ratio is not None and valuation.pb_ratio > 0
    ]
    return {
        "pe_avg": sum(pe_values) / len(pe_values) if pe_values else None,
        "pb_avg": sum(pb_values) / len(pb_values) if pb_values else None,
        "count": len(valuations),
    }


def has_negative_profitability(metrics: list[FinancialMetric]) -> bool:
    revenue = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
    )
    net_income = _net_income_series(metrics, annual_only=False)
    equity = balance_sheet_total_series(
        metrics,
        metric_names={"Equity", "權益總額", "權益總計"},
        origin_names={"權益總額", "權益總計"},
    )
    if not net_income:
        return False
    latest_year = max(net_income)
    latest_net_income = net_income[latest_year]
    if latest_net_income <= 0:
        return True
    latest_revenue = revenue.get(latest_year)
    if latest_revenue and latest_net_income / latest_revenue < 0:
        return True
    latest_equity = equity.get(max(equity)) if equity else None
    return bool(latest_equity and latest_net_income / latest_equity < 0)


def _net_income_decline_points(decline: float) -> int:
    if decline >= 70:
        return 5
    if decline >= 50:
        return 4
    if decline >= 20:
        return 3
    return 1


def _financial_assessment_series(metrics: list[FinancialMetric]) -> FinancialAssessmentSeries:
    latest_revenue_series = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
    )
    latest_net_income_series = _net_income_series(metrics, annual_only=False)
    return FinancialAssessmentSeries(
        revenue=metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
            annual_only=True,
        ),
        net_income=_net_income_series(metrics, annual_only=True),
        latest_revenue=_latest_series_value(latest_revenue_series),
        latest_net_income=_latest_series_value(latest_net_income_series),
        equity=balance_sheet_total_series(
            metrics,
            metric_names={"Equity", "權益總額", "權益總計"},
            origin_names={"權益總額", "權益總計"},
        ),
        liabilities=balance_sheet_total_series(
            metrics,
            metric_names={"Liabilities", "負債總額", "負債總計"},
            origin_names={"負債總額", "負債總計"},
        ),
    )


def _net_income_series(
    metrics: list[FinancialMetric],
    *,
    annual_only: bool,
) -> dict[int, float]:
    return metric_series(
        metrics,
        ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
        statement_types={"income_statement"},
        exclude_keywords=["歸屬", "綜合損益", "稅前"],
        annual_only=annual_only,
    )


def _latest_series_value(series: dict[int, float]) -> float | None:
    return series[max(series)] if series else None


def _add_revenue_trend(
    notes: FinancialAssessmentNotes,
    revenue: dict[int, float],
    *,
    has_metrics: bool,
) -> float | None:
    revenue_growth = series_growth_pct(revenue)
    if revenue_growth is None:
        if has_metrics:
            notes.cautions.append("已揭露年度營收趨勢不足")
        return None
    period = series_period_text(revenue)
    if revenue_growth >= 30:
        notes.add_strength(2, f"{period}營收成長 {revenue_growth:.1f}%")
    elif revenue_growth >= 5:
        notes.add_strength(1, f"{period}營收成長 {revenue_growth:.1f}%")
    elif revenue_growth <= -20:
        notes.add_red_flag(
            decline_risk_points(revenue_growth, metric="revenue"),
            f"{period}營收下滑 {abs(revenue_growth):.1f}%",
        )
    elif revenue_growth < 0:
        notes.add_caution(1, f"{period}營收小幅下滑 {abs(revenue_growth):.1f}%")
    return revenue_growth


def _add_net_income_trend(
    notes: FinancialAssessmentNotes,
    net_income: dict[int, float],
    latest_net_income: float | None,
    *,
    has_metrics: bool,
) -> float | None:
    net_income_growth = series_growth_pct(net_income)
    if latest_net_income is not None and latest_net_income <= 0:
        notes.add_red_flag(3, "最新財報期間淨利為負或接近虧損")
    elif net_income_growth is not None:
        _add_net_income_growth_note(notes, net_income, net_income_growth)
    elif has_metrics:
        notes.cautions.append("已揭露年度淨利趨勢不足")
    return net_income_growth


def _add_net_income_growth_note(
    notes: FinancialAssessmentNotes,
    net_income: dict[int, float],
    net_income_growth: float,
) -> None:
    period = series_period_text(net_income)
    if net_income_growth >= 20:
        notes.add_strength(2, f"{period}淨利成長 {net_income_growth:.1f}%")
    elif net_income_growth > 0:
        notes.add_strength(1, f"{period}淨利成長 {net_income_growth:.1f}%")
    elif net_income_growth <= -20:
        notes.add_red_flag(
            decline_risk_points(net_income_growth, metric="net_income"),
            f"{period}淨利下滑 {abs(net_income_growth):.1f}%",
        )
    else:
        notes.add_caution(1, f"{period}淨利小幅下滑 {abs(net_income_growth):.1f}%")


def _add_net_margin(
    notes: FinancialAssessmentNotes,
    latest_net_income: float | None,
    latest_revenue: float | None,
) -> None:
    if latest_net_income is None or not latest_revenue:
        return
    net_margin = latest_net_income / latest_revenue * 100
    if net_margin >= 15:
        notes.add_strength(1, f"最新淨利率約 {net_margin:.1f}%")
    elif net_margin < 0:
        notes.add_red_flag(2, f"最新淨利率為負 {net_margin:.1f}%")
    elif net_margin < 5:
        notes.add_caution(1, f"最新淨利率偏低 {net_margin:.1f}%")


def _add_debt_equity(
    notes: FinancialAssessmentNotes,
    liabilities: dict[int, float],
    equity: dict[int, float],
    *,
    has_metrics: bool,
) -> None:
    common_years = sorted(set(liabilities) & set(equity))
    if not common_years or not equity[common_years[-1]]:
        if has_metrics:
            notes.cautions.append("負債權益比不足")
        return
    debt_equity = liabilities[common_years[-1]] / equity[common_years[-1]]
    if debt_equity < 0.8:
        notes.add_strength(1, debt_equity_phrase(debt_equity))
    elif debt_equity >= 2:
        notes.add_red_flag(2, f"負債權益比偏高 {debt_equity:.2f} 倍")
    elif debt_equity >= 1.5:
        notes.add_caution(1, f"負債權益比略高 {debt_equity:.2f} 倍")


def _add_roe(
    notes: FinancialAssessmentNotes,
    latest_net_income: float | None,
    equity: dict[int, float],
) -> None:
    if latest_net_income is None or not equity:
        return
    latest_equity = equity[max(equity)]
    if not latest_equity:
        return
    roe = latest_net_income / latest_equity * 100
    if roe >= 10:
        notes.add_strength(1, f"ROE 約 {roe:.1f}%")
    elif roe < 0:
        notes.add_red_flag(1, f"ROE 為負 {roe:.1f}%")


def _add_valuation_position(
    notes: FinancialAssessmentNotes,
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None],
    metrics: list[FinancialMetric],
) -> None:
    label = valuation_position_label_for(valuation, peer_summary, has_negative_profitability(metrics))
    if label == "估值為快取救援，需刷新":
        notes.cautions.append("估值資料為快取救援，刷新前不判定低估/高估")
    elif label == "獲利為負，不判低估":
        notes.add_caution(1, "獲利為負或偏弱，低 P/B/P/E 不直接視為低估")
    elif label == "目前估值低於同業":
        notes.add_strength(2, label)
    elif label == "目前估值略低":
        notes.add_strength(1, label)
    elif label == "目前估值略高":
        notes.add_caution(1, label)
    elif label == "目前估值偏高":
        notes.add_caution(2, label)
    elif not valuation:
        notes.cautions.append("缺估值資料")


def _add_combined_decline_flag(
    notes: FinancialAssessmentNotes,
    revenue_growth: float | None,
    net_income_growth: float | None,
) -> None:
    if (
        revenue_growth is not None
        and net_income_growth is not None
        and revenue_growth <= -20
        and net_income_growth <= -20
    ):
        notes.add_red_flag(1, "營收與淨利同步大幅下滑")


def _assessment_payload(notes: FinancialAssessmentNotes, *, has_inputs: bool) -> dict:
    upside_score = min(6, notes.upside_score)
    risk_score = min(10, notes.risk_score)
    red_flag = bool(notes.red_flags) or risk_score >= 4
    return {
        "has_inputs": has_inputs,
        "upside_score": upside_score,
        "risk_score": risk_score,
        "red_flag": red_flag,
        "strengths": notes.strengths,
        "cautions": notes.cautions,
        "red_flags": notes.red_flags,
        "upside_summary": _upside_summary(notes.strengths),
        "risk_summary": _risk_summary(notes.red_flags, notes.cautions),
        "summary": _assessment_summary(notes.strengths, notes.red_flags, notes.cautions),
    }


def _upside_summary(strengths: list[str]) -> str:
    return "；".join(strengths[:3]) if strengths else "財務/估值未形成明確加分"


def _risk_summary(red_flags: list[str], cautions: list[str]) -> str:
    return (
        "；".join((red_flags + cautions)[:3])
        if red_flags or cautions
        else "財務/估值未形成明確風險"
    )


def _assessment_summary(
    strengths: list[str],
    red_flags: list[str],
    cautions: list[str],
) -> str:
    if not strengths and not red_flags and not cautions:
        return "財務/估值中性"
    return "；".join((strengths + red_flags + cautions)[:4])


__all__ = [
    "decline_risk_points",
    "financial_valuation_assessment_payload",
    "has_negative_profitability",
    "peer_valuation_summary",
    "series_growth_pct",
    "series_period_text",
]
