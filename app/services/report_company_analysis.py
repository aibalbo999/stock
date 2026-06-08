from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import MarketSnapshot, MonthlyRevenue, NewsDocument
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


def basic_intro(
    ticker: str,
    name: str,
    segment_name: str,
    company,
    related_documents: list[NewsDocument],
    candidate: dict,
    is_company_filing_document: Callable[[str, NewsDocument], bool],
    news_document_filing_type: Callable[[NewsDocument], str | None],
) -> list[str]:
    aliases = [
        alias
        for alias in (getattr(company, "aliases", []) or [])
        if alias and alias not in {ticker, name}
    ]
    keywords = (
        list(getattr(company, "evidence_keywords", []) or [])
        or list(candidate.get("evidence_keywords") or [])
    )
    rationale = report_formatting.compact_text(candidate.get("rationale") or "", max_chars=120)
    if rationale:
        role_text = f"{rationale}。"
    else:
        role_text = "本報告只把它視為此主題中的可驗證研究對象，不直接推論為受惠股。"
    alias_text = "、".join(aliases[:4]) if aliases else "本次主要使用股票代號與公司名稱比對。"
    keyword_text = (
        "、".join(str(keyword) for keyword in keywords[:6])
        if keywords
        else "尚未設定固定關鍵字，主要依公司名稱、代號與來源文本比對。"
    )
    filing_documents = [
        document for document in related_documents if is_company_filing_document(ticker, document)
    ]
    filing_types = sorted(
        {
            news_document_filing_type(document) or "company_disclosure"
            for document in filing_documents
        }
    )
    publisher_count = len({document.source.publisher or "未知來源" for document in related_documents})
    filing_text = (
        f"已納入 {len(filing_documents)} 份公司公開文件（{', '.join(filing_types[:3])}）。"
        if filing_documents
        else "尚未取得可用公司公開文件。"
    )
    return [
        "#### 公司基本介紹",
        f"- 基本定位：{ticker} {name}，本報告歸類在「{segment_name}」。{role_text}",
        f"- 常見名稱/代號：{alias_text}",
        f"- 本主題關聯關鍵字：{keyword_text}",
        f"- 本次資料基礎：{filing_text}另有 {len(related_documents)} 筆公司相關文本、{publisher_count} 個來源供交叉檢查。",
    ]


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
