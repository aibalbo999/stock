from __future__ import annotations

from app.models.schemas import MarketSnapshot, MonthlyRevenue


def render_scope(
    tickers: list[str],
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    *,
    whitelist_context: str,
) -> str:
    lines = [
        "### 本次個股範圍",
        ", ".join(tickers) if tickers else "未指定，或指定股票不在白名單內。",
        "",
        "### 市場資料摘要",
    ]
    if market_snapshots:
        for snapshot in market_snapshots:
            lines.append(
                "- "
                f"{snapshot.ticker} {snapshot.trade_date.isoformat()} "
                f"收盤 {snapshot.close if snapshot.close is not None else 'NA'}，"
                f"漲跌 {snapshot.spread if snapshot.spread is not None else 'NA'}，"
                f"成交量 {snapshot.trading_volume if snapshot.trading_volume is not None else 'NA'}。"
            )
    else:
        lines.append("目前無市場資料快取；可先呼叫 /market/refresh。")
    lines.extend(["", "### 月營收資料摘要"])
    if monthly_revenues:
        for revenue in monthly_revenues:
            yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "NA"
            lines.append(
                "- "
                f"{revenue.ticker} {revenue.revenue_year}-{revenue.revenue_month:02d} "
                f"營收 {revenue.revenue:,}，年增率 {yoy}。"
            )
    else:
        lines.append("目前無月營收資料快取；可先執行一鍵分析或市場更新。")
    lines.extend(["", "### 動態產業鏈白名單", whitelist_context])
    return "\n".join(lines)


def render_revenue_check(tickers: list[str], monthly_revenues: list[MonthlyRevenue]) -> str:
    if not tickers:
        return "目前無足夠數據判斷。"
    revenues = {revenue.ticker: revenue for revenue in monthly_revenues}
    lines = [
        "月營收用來確認題材是否反映到公司基本面；若缺資料，本系統不會把它當成正向理由。"
    ]
    for ticker in tickers:
        revenue = revenues.get(ticker)
        if not revenue:
            lines.append(f"- {ticker}：目前無足夠數據判斷。")
            continue
        yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
        lines.append(
            f"- {ticker}：{revenue.revenue_year}-{revenue.revenue_month:02d} "
            f"月營收 {revenue.revenue:,}，年增率 {yoy}；來源："
            f"{revenue.revenue_date.isoformat()} {revenue.source} {ticker}。"
        )
    return "\n".join(lines)
