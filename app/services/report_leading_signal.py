from __future__ import annotations

from app.services import report_formatting
from app.services.leading_signals import LeadingSignal


def render_leading_signal_check(
    tickers: list[str],
    leading_signals: dict[str, LeadingSignal],
) -> str:
    if not tickers:
        return "目前無足夠數據判斷。"
    lines = [
        "本段使用截至最新資料日的股價歷史、成交量、月營收加速與目前同業估值位置，補足新聞較慢的問題；它是近況警示與排序訊號，不是未來走勢預測或單獨買賣依據。",
        "",
        "| 股票 | 近況方向 | 分數 | 近20日股價 | 近60日股價 | 近20日量能 | 最新月營收YoY | 營收加速 | 目前估值 | 核心訊號 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for ticker in tickers:
        signal = leading_signals.get(ticker)
        if not signal:
            lines.append(
                report_formatting.table_row(
                    [ticker, "未評估", 0, "-", "-", "-", "-", "-", "未評估", "目前無足夠近況訊號。"]
                )
            )
            continue
        lines.append(
            report_formatting.table_row(
                [
                    ticker,
                    signal.direction,
                    str(signal.score),
                    format_optional_pct(signal.price_20d_pct),
                    format_optional_pct(signal.price_60d_pct),
                    format_optional_ratio(signal.volume_ratio_20d),
                    format_optional_pct(signal.revenue_yoy_pct),
                    format_optional_pct(signal.revenue_acceleration_pct),
                    signal.valuation_label,
                    signal.summary,
                ]
            )
        )
    return "\n".join(lines)


def format_optional_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def format_optional_ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}x"
