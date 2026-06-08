from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import NewsDocument, ReportRequest
from app.services import report_allocation, report_formatting


def source_label(
    context: dict,
    representative_sources_resolver: Callable[[list[NewsDocument]], str],
) -> str:
    ticker = context["ticker"]
    snapshot = context.get("snapshot")
    revenue = context.get("revenue")
    related_documents = context.get("documents") or []
    source = (
        f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
        if snapshot
        else "目前無足夠數據判斷"
    )
    if revenue:
        source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"
    if related_documents:
        source += f"；代表性文本：{representative_sources_resolver(related_documents)}"
    return source


def position_limit(decision: str, request: ReportRequest) -> str:
    if decision != "可小額分批研究":
        return "不適用 / 0 元"
    return f"約 {report_allocation.max_position_amount(request):,} 元"


def recommendation_row(
    context: dict,
    request: ReportRequest,
    representative_sources_resolver: Callable[[list[NewsDocument]], str],
) -> str:
    decision = context["decision"]
    return report_formatting.table_row(
        [
            context["label"],
            context["current_price"],
            context["current_price_label"],
            decision,
            context["rationale"],
            position_limit(decision, request),
            source_label(context, representative_sources_resolver),
        ]
    )


def render_investment_recommendations(
    contexts: list[dict],
    request: ReportRequest,
    reading_sort_note: str,
    representative_sources_resolver: Callable[[list[NewsDocument]], str],
) -> str:
    if not contexts:
        return "目前無足夠數據判斷。"

    lines = [
        "以下為非個人化研究建議；未納入投資人風險承受度、持股成本與資金配置，不構成個別買賣指令。",
        reading_sort_note,
        "",
        "| 股票 | 最新可取得收盤價 | 追價風險標籤 | 建議 | 理由 | 單檔上限 | 來源 |",
        "|---|---|---|---|---|---:|---|",
    ]
    lines.extend(
        recommendation_row(context, request, representative_sources_resolver)
        for context in contexts
    )
    return "\n".join(lines)
