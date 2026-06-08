from __future__ import annotations

from app.models.schemas import FinancialMetric, ValuationMetric
from app.services import report_company_narrative, report_decision_rules, report_formatting
from app.services.leading_signals import LeadingSignal
from app.services.report_financial_assessment import has_negative_profitability, valuation_position_label


def company_matrix_reminder(
    estimate: dict,
    quality: dict,
    related_findings,
    valuation: ValuationMetric | None,
    peer_summary: dict[str, float | None] | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    leading_signal: LeadingSignal | None = None,
) -> str:
    if quality.get("grade") != "supported":
        return "先補資料：" + "、".join(quality.get("missing", [])[:2])
    if leading_signal and leading_signal.direction == "偏空":
        return "等近況訊號修復"
    valuation_label = valuation_position_label(
        valuation,
        peer_summary,
        has_negative_profitability(financial_metrics or []),
    )
    if estimate["downside_pct"] > 5:
        return f"先追蹤目前情境降值分 {estimate['downside_pct']} 分"
    if "偏高" in valuation_label or "略高" in valuation_label:
        return f"{valuation_label}，分批觀察"
    if related_findings:
        return f"追蹤 {len(related_findings)} 筆歸因是否延續"
    if estimate["upside_pct"] > 10:
        return "題材與基本面可再深入"
    return "暫列觀察"


def build_company_matrix_rows(
    contexts: list[dict],
    financial_metrics_by_ticker: dict[str, list[FinancialMetric]],
    peer_valuation_summary: dict[str, float | None],
) -> list[dict]:
    rows = []
    for context in report_decision_rules.sort_decision_contexts(contexts):
        ticker = context["ticker"]
        ticker_metrics = financial_metrics_by_ticker.get(ticker, [])
        valuation = context.get("valuation")
        revenue = context.get("revenue")
        estimate = context["estimate"]
        quality = context["quality"]
        rows.append(
            {
                "label": context["label"],
                "decision": context["decision"],
                "current_price": context["current_price"],
                "current_price_label": context["current_price_label"],
                "upside": estimate["upside_pct"],
                "downside": estimate["downside_pct"],
                "valuation": context.get("valuation_label")
                or valuation_position_label(
                    valuation,
                    peer_valuation_summary,
                    has_negative_profitability(ticker_metrics),
                ),
                "confidence": report_company_narrative.financial_confidence_label(
                    ticker_metrics,
                    valuation,
                    revenue,
                ),
                "reminder": company_matrix_reminder(
                    estimate,
                    quality,
                    context.get("findings", []),
                    valuation,
                    peer_valuation_summary,
                    ticker_metrics,
                    context.get("leading_signal"),
                ),
            }
        )
    return rows


def render_company_comparison_matrix(
    contexts: list[dict],
    financial_metrics_by_ticker: dict[str, list[FinancialMetric]],
    peer_valuation_summary: dict[str, float | None],
    reading_sort_note: str,
) -> str:
    if not contexts:
        return "目前無足夠數據判斷。"

    lines = [
        "這張表用來比較正式分析股票的相對位置；它是研究排序工具，不是買賣指令。",
        reading_sort_note,
        "",
        "| 股票 | 判斷 | 最新可取得收盤價 | 追價風險標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |",
        "|---|---|---|---|---:|---:|---|---|---|",
    ]
    for row in build_company_matrix_rows(contexts, financial_metrics_by_ticker, peer_valuation_summary):
        lines.append(
            report_formatting.table_row(
                [
                    row["label"],
                    row["decision"],
                    row["current_price"],
                    row["current_price_label"],
                    f"{row['upside']} 分",
                    f"{row['downside']} 分",
                    row["valuation"],
                    row["confidence"],
                    row["reminder"],
                ]
            )
        )
    return "\n".join(lines)
