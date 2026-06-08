from __future__ import annotations

from app.models.schemas import FinancialMetric, ValuationMetric
from app.services.report_financial_narrative import (
    balance_sheet_total_series,
    debt_equity_phrase,
    metric_series,
)
from app.services.report_quality import is_stale_market_data_source


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
        if decline >= 70:
            return 5
        if decline >= 50:
            return 4
        if decline >= 20:
            return 3
        return 1
    if decline >= 40:
        return 4
    if decline >= 20:
        return 3
    return 1


def financial_valuation_assessment(
    financial_metrics: list[FinancialMetric] | None = None,
    valuation: ValuationMetric | None = None,
    peer_summary: dict[str, float | None] | None = None,
) -> dict:
    metrics = financial_metrics or []
    peer_summary = peer_summary or {}
    upside_score = 0
    risk_score = 0
    strengths: list[str] = []
    cautions: list[str] = []
    red_flags: list[str] = []
    if any(is_stale_market_data_source(metric.source) for metric in metrics):
        cautions.append("財務資料為快取救援，需刷新後覆核")

    revenue = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
        annual_only=True,
    )
    net_income = metric_series(
        metrics,
        ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
        statement_types={"income_statement"},
        exclude_keywords=["歸屬", "綜合損益", "稅前"],
        annual_only=True,
    )
    latest_revenue_series = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
    )
    latest_net_income_series = metric_series(
        metrics,
        ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
        statement_types={"income_statement"},
        exclude_keywords=["歸屬", "綜合損益", "稅前"],
    )
    equity = balance_sheet_total_series(
        metrics,
        metric_names={"Equity", "權益總額", "權益總計"},
        origin_names={"權益總額", "權益總計"},
    )
    liabilities = balance_sheet_total_series(
        metrics,
        metric_names={"Liabilities", "負債總額", "負債總計"},
        origin_names={"負債總額", "負債總計"},
    )

    revenue_growth = series_growth_pct(revenue)
    if revenue_growth is not None:
        revenue_period = series_period_text(revenue)
        if revenue_growth >= 30:
            upside_score += 2
            strengths.append(f"{revenue_period}營收成長 {revenue_growth:.1f}%")
        elif revenue_growth >= 5:
            upside_score += 1
            strengths.append(f"{revenue_period}營收成長 {revenue_growth:.1f}%")
        elif revenue_growth <= -20:
            risk_score += decline_risk_points(revenue_growth, metric="revenue")
            red_flags.append(f"{revenue_period}營收下滑 {abs(revenue_growth):.1f}%")
        elif revenue_growth < 0:
            risk_score += 1
            cautions.append(f"{revenue_period}營收小幅下滑 {abs(revenue_growth):.1f}%")
    elif metrics:
        cautions.append("已揭露年度營收趨勢不足")

    net_income_growth = series_growth_pct(net_income)
    latest_net_income = latest_net_income_series[max(latest_net_income_series)] if latest_net_income_series else None
    latest_revenue = latest_revenue_series[max(latest_revenue_series)] if latest_revenue_series else None
    if latest_net_income is not None and latest_net_income <= 0:
        risk_score += 3
        red_flags.append("最新財報期間淨利為負或接近虧損")
    elif net_income_growth is not None:
        net_income_period = series_period_text(net_income)
        if net_income_growth >= 20:
            upside_score += 2
            strengths.append(f"{net_income_period}淨利成長 {net_income_growth:.1f}%")
        elif net_income_growth > 0:
            upside_score += 1
            strengths.append(f"{net_income_period}淨利成長 {net_income_growth:.1f}%")
        elif net_income_growth <= -20:
            risk_score += decline_risk_points(net_income_growth, metric="net_income")
            red_flags.append(f"{net_income_period}淨利下滑 {abs(net_income_growth):.1f}%")
        else:
            risk_score += 1
            cautions.append(f"{net_income_period}淨利小幅下滑 {abs(net_income_growth):.1f}%")
    elif metrics:
        cautions.append("已揭露年度淨利趨勢不足")

    if latest_net_income is not None and latest_revenue:
        net_margin = latest_net_income / latest_revenue * 100
        if net_margin >= 15:
            upside_score += 1
            strengths.append(f"最新淨利率約 {net_margin:.1f}%")
        elif net_margin < 0:
            risk_score += 2
            red_flags.append(f"最新淨利率為負 {net_margin:.1f}%")
        elif net_margin < 5:
            risk_score += 1
            cautions.append(f"最新淨利率偏低 {net_margin:.1f}%")

    common_years = sorted(set(liabilities) & set(equity))
    if common_years and equity[common_years[-1]]:
        debt_equity = liabilities[common_years[-1]] / equity[common_years[-1]]
        if debt_equity < 0.8:
            upside_score += 1
            strengths.append(debt_equity_phrase(debt_equity))
        elif debt_equity >= 2:
            risk_score += 2
            red_flags.append(f"負債權益比偏高 {debt_equity:.2f} 倍")
        elif debt_equity >= 1.5:
            risk_score += 1
            cautions.append(f"負債權益比略高 {debt_equity:.2f} 倍")
    elif metrics:
        cautions.append("負債權益比不足")

    if latest_net_income is not None and equity:
        latest_equity = equity[max(equity)]
        if latest_equity:
            roe = latest_net_income / latest_equity * 100
            if roe >= 10:
                upside_score += 1
                strengths.append(f"ROE 約 {roe:.1f}%")
            elif roe < 0:
                risk_score += 1
                red_flags.append(f"ROE 為負 {roe:.1f}%")

    valuation_label = valuation_position_label(
        valuation,
        peer_summary,
        has_negative_profitability(metrics),
    )
    if valuation_label == "估值為快取救援，需刷新":
        cautions.append("估值資料為快取救援，刷新前不判定低估/高估")
    elif valuation_label == "獲利為負，不判低估":
        risk_score += 1
        cautions.append("獲利為負或偏弱，低 P/B/P/E 不直接視為低估")
    elif valuation_label == "目前估值低於同業":
        upside_score += 2
        strengths.append(valuation_label)
    elif valuation_label == "目前估值略低":
        upside_score += 1
        strengths.append(valuation_label)
    elif valuation_label == "目前估值略高":
        risk_score += 1
        cautions.append(valuation_label)
    elif valuation_label == "目前估值偏高":
        risk_score += 2
        cautions.append(valuation_label)
    elif not valuation:
        cautions.append("缺估值資料")

    if (
        revenue_growth is not None
        and net_income_growth is not None
        and revenue_growth <= -20
        and net_income_growth <= -20
    ):
        risk_score += 1
        red_flags.append("營收與淨利同步大幅下滑")

    upside_score = min(6, upside_score)
    risk_score = min(10, risk_score)
    red_flag = bool(red_flags) or risk_score >= 4
    return {
        "has_inputs": bool(metrics or valuation),
        "upside_score": upside_score,
        "risk_score": risk_score,
        "red_flag": red_flag,
        "strengths": strengths,
        "cautions": cautions,
        "red_flags": red_flags,
        "upside_summary": "；".join(strengths[:3]) if strengths else "財務/估值未形成明確加分",
        "risk_summary": "；".join((red_flags + cautions)[:3]) if red_flags or cautions else "財務/估值未形成明確風險",
        "summary": "；".join((strengths + red_flags + cautions)[:4]) if strengths or red_flags or cautions else "財務/估值中性",
    }


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


def valuation_position_label(
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
    has_negative_profitability: bool = False,
) -> str:
    if not valuation:
        return "缺估值"
    if is_stale_market_data_source(valuation.source):
        return "估值為快取救援，需刷新"
    pe_avg = (peer_summary or {}).get("pe_avg")
    pb_avg = (peer_summary or {}).get("pb_avg")
    pressure = 0
    discount = 0
    if valuation.pe_ratio is not None and pe_avg:
        if valuation.pe_ratio > pe_avg * 1.1:
            pressure += 1
        elif valuation.pe_ratio < pe_avg * 0.9:
            discount += 1
    if valuation.pb_ratio is not None and pb_avg:
        if valuation.pb_ratio > pb_avg * 1.1:
            pressure += 1
        elif valuation.pb_ratio < pb_avg * 0.9:
            discount += 1
    if pressure >= 2:
        return "目前估值偏高"
    if pressure == 1 and discount == 0:
        return "目前估值略高"
    if has_negative_profitability and discount > 0 and pressure == 0:
        return "獲利為負，不判低估"
    if discount >= 2:
        return "目前估值低於同業"
    if discount == 1 and pressure == 0:
        return "目前估值略低"
    return "目前估值接近同業"


def has_negative_profitability(metrics: list[FinancialMetric]) -> bool:
    revenue = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
    )
    net_income = metric_series(
        metrics,
        ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
        statement_types={"income_statement"},
        exclude_keywords=["歸屬", "綜合損益", "稅前"],
    )
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
