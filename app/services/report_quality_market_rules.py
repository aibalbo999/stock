from __future__ import annotations


def market_coverage_quality_notes(
    *,
    promoted_count: int,
    market_coverage: float,
    monthly_coverage: float,
    financial_metrics_count: int,
    valuation_coverage: float,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if promoted_count and market_coverage < 0.5:
        blockers.append("股價資料覆蓋率低於 50%")
    elif promoted_count and market_coverage < 1:
        warnings.append("部分股票缺少最新股價資料")
    if promoted_count and monthly_coverage < 0.5:
        warnings.append("月營收資料覆蓋偏低")
    if promoted_count and financial_metrics_count < promoted_count * 8:
        warnings.append("五年財務資料不足，個股財務判斷信心需下修")
    if promoted_count and valuation_coverage < 0.5:
        warnings.append("估值資料覆蓋偏低")
    return blockers, warnings


def market_rescue_quality_notes(
    *,
    stale_market_dataset_count: int,
    market_stale_count: int,
    monthly_revenue_stale_count: int,
    financial_metrics_stale_ticker_count: int,
    valuation_stale_count: int,
    latest_only_market_dataset_count: int,
    market_latest_only_count: int,
    monthly_revenue_latest_only_count: int,
    financial_metrics_latest_only_ticker_count: int,
    valuation_latest_only_count: int,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    observations: list[str] = []
    if stale_market_dataset_count:
        warnings.append("部分市場或財務資料使用快取救援，需刷新確認最新資料")
        if market_stale_count:
            observations.append("股價資料含快取救援來源，價格與成交量解讀需以刷新後資料覆核")
        if monthly_revenue_stale_count:
            observations.append("月營收資料含快取救援來源，成長率判斷需以最新公告覆核")
        if financial_metrics_stale_ticker_count:
            observations.append("五年財務資料含快取救援來源，財務體質結論需以最新財報覆核")
        if valuation_stale_count:
            observations.append("估值資料含快取救援來源，目前估值結論需以刷新後資料覆核")
    if latest_only_market_dataset_count:
        warnings.append("部分市場或財務資料只使用官方最新救援資料，不能代表完整歷史趨勢")
        if market_latest_only_count:
            observations.append("股價資料含官方最新救援來源，動能與區間漲跌需等待完整歷史資料覆核")
        if monthly_revenue_latest_only_count:
            observations.append(
                "月營收資料含官方最新救援來源，連續成長趨勢需等待完整月營收歷史覆核"
            )
        if financial_metrics_latest_only_ticker_count:
            observations.append(
                "財務資料含官方最新季報救援來源，五年財務趨勢需等待完整歷史財報覆核"
            )
        if valuation_latest_only_count:
            observations.append("估值資料含官方最新救援來源，同業估值比較需等待完整估值歷史覆核")
    return warnings, observations
