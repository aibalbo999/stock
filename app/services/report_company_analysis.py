from __future__ import annotations

from app.models.schemas import MarketSnapshot, MonthlyRevenue
from app.services import report_formatting


def price_label(snapshot: MarketSnapshot | None) -> str:
    if not snapshot:
        return "缺"
    close = snapshot.close if snapshot.close is not None else "NA"
    return f"{snapshot.trade_date.isoformat()} 收盤 {close}"


def revenue_label(revenue: MonthlyRevenue | None) -> str:
    if not revenue:
        return "缺"
    if revenue.yoy_pct is None:
        return f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY NA"
    return f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY {revenue.yoy_pct:.2f}%"


def evidence_label(related_documents: list, related_findings) -> str:
    return f"{len(related_documents)} 文本 / {len(related_findings)} 歸因"


def overview_row(
    context: dict,
    segment_name: str,
    financial_confidence: str,
) -> str:
    return report_formatting.table_row(
        [
            context["label"],
            segment_name,
            price_label(context.get("snapshot")),
            context["current_price_label"],
            revenue_label(context.get("revenue")),
            context["valuation_label"],
            financial_confidence,
            evidence_label(context.get("documents") or [], context.get("findings") or []),
        ]
    )


def render_company_analysis(
    overview_rows: list[str],
    detail_blocks: list[str],
    reading_sort_note: str,
) -> str:
    lines = [
        "### 個股速覽",
        reading_sort_note,
        "",
        "| 股票 | 產業位置 | 最新可取得收盤價 | 追價風險標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |",
        "|---|---|---|---|---|---|---|---|",
        *overview_rows,
        "",
        "### 個股細節",
        *detail_blocks,
    ]
    return "\n".join(lines).strip()
