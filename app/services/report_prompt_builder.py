from __future__ import annotations

from collections.abc import Callable

from app.core.prompts import REPORT_PROMPT_TEMPLATE, SYSTEM_PROMPT
from app.models.schemas import MarketSnapshot, MonthlyRevenue, NewsDocument
from app.services.source_quality import filter_formal_evidence_documents


MAX_LLM_EVIDENCE_DOCUMENTS = 60
MAX_LLM_EVIDENCE_TEXT_CHARS = 300


def build_report_prompt(
    *,
    whitelist_context: str,
    graph_context: str,
    evidence_documents: list[NewsDocument],
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    ticker_label_resolver: Callable[[NewsDocument], list[str]] | None = None,
) -> str:
    return SYSTEM_PROMPT + "\n\n" + REPORT_PROMPT_TEMPLATE.format(
        whitelist=whitelist_context,
        graph_context=graph_context,
        evidence=format_llm_evidence(evidence_documents, ticker_label_resolver),
        market_data=format_market_data(market_snapshots, monthly_revenues),
    )


def format_llm_evidence(
    documents: list[NewsDocument],
    ticker_label_resolver: Callable[[NewsDocument], list[str]] | None = None,
) -> str:
    documents = filter_formal_evidence_documents(documents)
    if not documents:
        return "目前無足夠數據判斷。"
    selected = documents[:MAX_LLM_EVIDENCE_DOCUMENTS]
    lines = [
        "以下為供模型補充分析用的截斷證據摘要；正式報告仍會使用完整資料庫、財報與估值規則交叉檢查。"
    ]
    for doc in selected:
        text = " ".join(doc.text.split())[:MAX_LLM_EVIDENCE_TEXT_CHARS]
        source_date = doc.source.published_at or "日期不明"
        company_labels = ticker_label_resolver(doc) if ticker_label_resolver else []
        source_id = ",".join(
            label.split(" ", 1)[0] for label in company_labels if label.split(" ", 1)[0]
        )
        company_mapping = "、".join(company_labels) if company_labels else "未明確對應白名單公司"
        lines.append(
            "- "
            f"source_date={source_date} | "
            f"source_publisher={doc.source.publisher or ''} | "
            f"source_title={doc.title} | "
            f"source_id={source_id} | "
            f"公司對應={company_mapping} | "
            f"text={text}"
        )
    omitted = len(documents) - len(selected)
    if omitted > 0:
        lines.append(f"- 其餘 {omitted} 筆來源保留於系統資料庫，未放入模型提示以避免逾時。")
    return "\n".join(lines)


def format_evidence_digest(documents: list[NewsDocument]) -> str:
    documents = filter_formal_evidence_documents(documents)
    if not documents:
        return "目前無足夠數據判斷。"
    return "\n".join(
        f"- {doc.source.published_at or '日期不明'} {doc.source.publisher or ''} {doc.title}: {doc.text[:500]}"
        for doc in documents
    )


def format_market_data(
    snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
) -> str:
    lines = []
    if snapshots:
        lines.extend(
            [
                "- "
                f"{snapshot.ticker} trade_date={snapshot.trade_date.isoformat()} "
                f"close={snapshot.close} spread={snapshot.spread} "
                f"trading_volume={snapshot.trading_volume} source={snapshot.source} ticker={snapshot.ticker} "
                f"fetched_at={snapshot.fetched_at.isoformat(timespec='seconds')}"
                for snapshot in snapshots
            ]
        )
    if monthly_revenues:
        lines.extend(
            [
                "- "
                f"{revenue.ticker} revenue_month={revenue.revenue_year}-{revenue.revenue_month:02d} "
                f"revenue={revenue.revenue} yoy_pct={revenue.yoy_pct} source={revenue.source} "
                f"fetched_at={revenue.fetched_at.isoformat(timespec='seconds')}"
                for revenue in monthly_revenues
            ]
        )
    if not lines:
        return "目前無市場資料快取。"
    return "\n".join(lines)
