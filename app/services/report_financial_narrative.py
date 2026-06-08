from __future__ import annotations

from app.models.schemas import FinancialMetric


def financial_statement_summary(metrics: list[FinancialMetric]) -> dict[str, str]:
    if not metrics:
        unavailable = "目前無足夠數據判斷；需補 FinMind 財報三表。"
        return {
            "health": unavailable,
            "revenue_trend": unavailable,
            "net_income_trend": unavailable,
            "fcf_trend": unavailable,
            "margin_trend": unavailable,
            "debt_trend": unavailable,
            "roe_trend": unavailable,
            "strength": "只依目前資料無法判斷長期體質變強或走弱。",
        }

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
    latest_revenue = metric_series(
        metrics,
        ["營業收入", "revenue"],
        statement_types={"income_statement"},
    )
    latest_net_income = metric_series(
        metrics,
        ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
        statement_types={"income_statement"},
        exclude_keywords=["歸屬", "綜合損益", "稅前"],
    )
    if not revenue:
        revenue = latest_revenue
    if not net_income:
        net_income = latest_net_income
    annual_balance_metrics = [
        metric for metric in metrics if metric.report_date.month == 12 and metric.report_date.day == 31
    ]
    balance_metrics = annual_balance_metrics or metrics
    equity = balance_sheet_total_series(
        balance_metrics,
        metric_names={"Equity", "權益總額", "權益總計"},
        origin_names={"權益總額", "權益總計"},
    )
    liabilities = balance_sheet_total_series(
        balance_metrics,
        metric_names={"Liabilities", "負債總額", "負債總計"},
        origin_names={"負債總額", "負債總計"},
    )
    operating_cash = metric_series(
        metrics,
        ["營業活動", "operating cash"],
        statement_types={"cash_flow"},
        annual_only=True,
    )
    capex = metric_series(
        metrics,
        ["投資活動", "capital expenditure", "capex"],
        statement_types={"cash_flow"},
        annual_only=True,
    )
    gross_profit = metric_series(
        metrics,
        ["營業毛利", "gross profit"],
        statement_types={"income_statement"},
    )

    revenue_trend = series_trend_text(revenue, "營收")
    net_income_trend = series_trend_text(net_income, "淨利")
    fcf_trend = fcf_trend_text(operating_cash, capex)
    margin_trend = margin_text(gross_profit, latest_net_income, latest_revenue)
    debt_trend = debt_text(liabilities, equity)
    roe_trend = roe_text(net_income, equity)
    strength = financial_strength_text(revenue, net_income, liabilities, equity)
    return {
        "health": f"{revenue_trend} {net_income_trend} {debt_trend}",
        "revenue_trend": revenue_trend,
        "net_income_trend": net_income_trend,
        "fcf_trend": fcf_trend,
        "margin_trend": margin_trend,
        "debt_trend": debt_trend,
        "roe_trend": roe_trend,
        "strength": strength,
    }


def metric_series(
    metrics: list[FinancialMetric],
    keywords: list[str],
    statement_types: set[str] | None = None,
    exclude_keywords: list[str] | None = None,
    annual_only: bool = False,
) -> dict[int, float]:
    series: dict[int, float] = {}
    dates: dict[int, object] = {}
    exclude_keywords = exclude_keywords or []
    for metric in metrics:
        if annual_only and (metric.report_date.month != 12 or metric.report_date.day != 31):
            continue
        if statement_types and metric.statement_type not in statement_types:
            continue
        name = f"{metric.metric} {metric.origin_name or ''}".lower()
        if any(keyword.lower() in name for keyword in exclude_keywords):
            continue
        if not any(keyword.lower() in name for keyword in keywords):
            continue
        year = metric.report_date.year
        if year not in series or metric.report_date >= dates[year]:
            series[year] = metric.value
            dates[year] = metric.report_date
    return dict(sorted(series.items())[-5:])


def balance_sheet_total_series(
    metrics: list[FinancialMetric],
    metric_names: set[str],
    origin_names: set[str],
) -> dict[int, float]:
    series: dict[int, float] = {}
    dates: dict[int, object] = {}
    priorities: dict[int, int] = {}
    normalized_metrics = {name.lower() for name in metric_names}
    normalized_origins = {name.lower() for name in origin_names}
    for metric in metrics:
        if metric.statement_type != "balance_sheet":
            continue
        metric_name = str(metric.metric or "").strip().lower()
        origin_name = str(metric.origin_name or "").strip().lower()
        metric_match = metric_name in normalized_metrics
        origin_match = origin_name in normalized_origins
        if not metric_match and not origin_match:
            continue
        year = metric.report_date.year
        priority = (2 if metric_match else 0) + (1 if origin_match else 0)
        if (
            year not in series
            or metric.report_date > dates[year]
            or (metric.report_date == dates[year] and priority > priorities[year])
        ):
            series[year] = metric.value
            dates[year] = metric.report_date
            priorities[year] = priority
    return dict(sorted(series.items())[-5:])


def series_trend_text(series: dict[int, float], label: str) -> str:
    if len(series) < 2:
        return f"{label}目前無足夠已揭露年度數據判斷。"
    years = sorted(series)
    first = series[years[0]]
    last = series[years[-1]]
    if first == 0:
        return f"{label}有資料但起始值為 0，無法計算成長率。"
    growth = (last - first) / abs(first) * 100
    direction = "成長" if growth > 0 else "下滑"
    return f"{years[0]} 年度至 {years[-1]} 年度{label}{direction} {abs(growth):.2f}%。"


def fcf_trend_text(operating_cash: dict[int, float], capex: dict[int, float]) -> str:
    common_years = sorted(set(operating_cash) & set(capex))
    if len(common_years) < 2:
        return "目前無足夠數據判斷；需補營業現金流與資本支出。"
    fcf = {year: operating_cash[year] + capex[year] for year in common_years}
    return series_trend_text(fcf, "自由現金流")


def margin_text(
    gross_profit: dict[int, float],
    net_income: dict[int, float],
    revenue: dict[int, float],
) -> str:
    if not revenue:
        return "目前無足夠數據判斷；需補營收與獲利科目。"
    latest_year = max(revenue)
    parts = []
    if latest_year in gross_profit and revenue[latest_year]:
        parts.append(f"毛利率約 {gross_profit[latest_year] / revenue[latest_year] * 100:.2f}%")
    if latest_year in net_income and revenue[latest_year]:
        parts.append(f"淨利率約 {net_income[latest_year] / revenue[latest_year] * 100:.2f}%")
    return (
        f"最近一期（{latest_year} 年內資料）" + "、".join(parts) + "。"
        if parts
        else "目前無足夠數據判斷；需補毛利率、營益率與淨利率。"
    )


def debt_text(liabilities: dict[int, float], equity: dict[int, float]) -> str:
    common_years = sorted(set(liabilities) & set(equity))
    if not common_years:
        return "目前無足夠數據判斷；需補資產負債表。"
    latest = common_years[-1]
    if equity[latest] == 0:
        return "負債與權益資料存在，但權益為 0，無法計算負債權益比。"
    return f"{latest} 年度{debt_equity_phrase(liabilities[latest] / equity[latest])}。"


def debt_equity_phrase(ratio: float) -> str:
    if ratio > 0 and ratio < 0.01:
        return "負債權益比低於 0.01 倍"
    return f"負債權益比約 {ratio:.2f} 倍"


def roe_text(net_income: dict[int, float], equity: dict[int, float]) -> str:
    common_years = sorted(set(net_income) & set(equity))
    if not common_years:
        return "目前無足夠數據判斷；需補股東權益與淨利。"
    latest = common_years[-1]
    if equity[latest] == 0:
        return "淨利與權益資料存在，但權益為 0，無法計算 ROE。"
    return f"{latest} 年度 ROE 約 {net_income[latest] / equity[latest] * 100:.2f}%。"


def financial_strength_text(
    revenue: dict[int, float],
    net_income: dict[int, float],
    liabilities: dict[int, float],
    equity: dict[int, float],
) -> str:
    score = 0
    if len(revenue) >= 2 and list(revenue.values())[-1] > list(revenue.values())[0]:
        score += 1
    if len(net_income) >= 2 and list(net_income.values())[-1] > list(net_income.values())[0]:
        score += 1
    common_years = sorted(set(liabilities) & set(equity))
    if common_years and equity[common_years[-1]] and liabilities[common_years[-1]] / equity[common_years[-1]] < 1:
        score += 1
    if score >= 2:
        return "目前可用資料偏向體質改善，但仍需人工覆核科目對應。"
    if score == 0:
        return "目前可用資料不足或偏弱，需補完整財報後再判斷。"
    return "目前可用資料呈中性，尚不足以判斷明顯轉強或轉弱。"
