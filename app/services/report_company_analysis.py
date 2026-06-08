from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.core.time import format_taipei
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services import report_company_narrative, report_formatting


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


class CompanyAnalysisDependencies(Protocol):
    whitelist: Any

    def _group_financial_metrics(self, metrics: list[FinancialMetric]) -> dict[str, list[FinancialMetric]]: ...

    def _peer_valuation_summary(self, valuations: list[ValuationMetric]) -> dict[str, float | None]: ...

    def _candidate_audit_by_ticker(self) -> dict[str, dict]: ...

    def _sort_decision_contexts(self, contexts: list[dict]) -> list[dict]: ...

    def _decision_contexts(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, Any] | None = None,
    ) -> list[dict]: ...

    def _downside_gate(self, request: ReportRequest) -> int: ...

    def _decision_reason(
        self,
        decision: str,
        estimate: dict,
        quality: dict,
        related_findings,
        related_documents: list[NewsDocument],
        downside_gate: int,
        request: ReportRequest,
        leading_signal: Any = None,
    ) -> str: ...

    def _financial_confidence_label(
        self,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        revenue: MonthlyRevenue | None,
    ) -> str: ...

    def _company_quick_take(
        self,
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str: ...

    def _is_company_filing_document(self, ticker: str, document: NewsDocument) -> bool: ...

    def _news_document_filing_type(self, document: NewsDocument) -> str | None: ...

    def _company_risk_summary(self, related_findings) -> str: ...


def render_company_analysis_section(
    dependencies: CompanyAnalysisDependencies,
    tickers: list[str],
    documents: list[NewsDocument],
    findings,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue] | None = None,
    financial_metrics: list[FinancialMetric] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
    request: ReportRequest | None = None,
    leading_signals: dict[str, Any] | None = None,
    *,
    reading_sort_note: str,
) -> str:
    if not tickers:
        return "未指定白名單個股，無法產出個別公司分析。"
    request = request or ReportRequest(tickers=tickers)

    metrics_by_ticker = dependencies._group_financial_metrics(financial_metrics or [])
    companies = {company.ticker: company for company in dependencies.whitelist.companies()}
    latest_valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
    peer_summary = dependencies._peer_valuation_summary(list(latest_valuations.values()))
    candidate_audit = dependencies._candidate_audit_by_ticker()
    contexts = dependencies._sort_decision_contexts(
        dependencies._decision_contexts(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
    )
    overview_rows: list[str] = []
    detail_blocks: list[str] = []
    for context in contexts:
        ticker = context["ticker"]
        company = companies.get(ticker)
        segment = dependencies.whitelist.segment_for_ticker(ticker)
        snapshot = context.get("snapshot")
        revenue = context.get("revenue")
        ticker_metrics = metrics_by_ticker.get(ticker, [])
        valuation = context.get("valuation")
        related_findings = context.get("findings") or []
        related_documents = context.get("documents") or []
        signal = context.get("leading_signal")
        estimate = context["estimate"]
        quality = context["quality"]
        downside_gate = dependencies._downside_gate(request)
        decision = context["decision"]
        decision_reason = dependencies._decision_reason(
            decision,
            estimate,
            quality,
            related_findings,
            related_documents,
            downside_gate,
            request,
            signal,
        )

        name = company.name if company else ticker
        segment_name = segment.name if segment else "白名單未分類"
        current_price = price_label(snapshot)
        valuation_position = context["valuation_label"]
        financial_confidence = dependencies._financial_confidence_label(ticker_metrics, valuation, revenue)
        overview_rows.append(overview_row(context, segment_name, financial_confidence))

        detail_blocks.append(f"### {ticker} {name}")
        detail_blocks.append(
            "- 個股結論摘要："
            + dependencies._company_quick_take(
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                related_documents,
                related_findings,
            )
        )
        detail_blocks.append(f"- 資料信心：{financial_confidence}；目前估值位置：{valuation_position}。")
        detail_blocks.append(f"- 追價風險標籤：{context['current_price_label']}；最新可取得收盤價：{current_price}。")
        detail_blocks.append(f"- 產業鏈位置：{segment_name}")
        detail_blocks.extend(
            basic_intro(
                ticker,
                name,
                segment_name,
                company,
                related_documents,
                candidate_audit.get(ticker, {}),
                dependencies._is_company_filing_document,
                dependencies._news_document_filing_type,
            )
        )
        if snapshot:
            detail_blocks.append(
                "- 市場資料："
                f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close if snapshot.close is not None else 'NA'}，"
                f"漲跌 {snapshot.spread if snapshot.spread is not None else 'NA'}，"
                f"成交量 {snapshot.trading_volume if snapshot.trading_volume is not None else 'NA'}；"
                f"來源：{snapshot.source}，擷取時間（台灣）{format_taipei(snapshot.fetched_at)}"
            )
        else:
            detail_blocks.append("- 市場資料：目前無足夠數據判斷。")

        if revenue:
            yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
            detail_blocks.append(
                "- 月營收："
                f"{revenue.revenue_year}-{revenue.revenue_month:02d} 營收 {revenue.revenue:,}，"
                f"年增率 {yoy}；來源：{revenue.source}，"
                f"擷取時間（台灣）{format_taipei(revenue.fetched_at)}"
            )
        else:
            detail_blocks.append("- 月營收：目前無足夠數據判斷。")

        if related_findings:
            for finding in related_findings[:3]:
                source_date = finding.source.published_at.isoformat() if finding.source.published_at else "日期不明"
                detail_blocks.append(
                    f"- 風險/機會證據：{finding.risk_type.value}；{finding.evidence}；"
                    f"來源：{source_date} {finding.source.publisher or ''} {finding.source.title}"
                )
            if len(related_findings) > 3:
                detail_blocks.append(f"- 其餘 {len(related_findings) - 3} 筆證據已收斂於風險摘要與資料來源附錄。")
        elif related_documents:
            detail_blocks.append(f"- 新聞/研究證據：找到 {len(related_documents)} 筆相關文本，但未形成可歸因風險。")
        else:
            detail_blocks.append("- 新聞/研究證據：目前無足夠數據判斷。")
        detail_blocks.extend(
            report_company_narrative.render_wall_street_company_sections(
                name,
                segment_name,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                peer_summary,
                related_documents,
                related_findings,
                dependencies._company_risk_summary(related_findings),
                decision,
                decision_reason,
            )
        )
        detail_blocks.append("")

    return render_company_analysis(overview_rows, detail_blocks, reading_sort_note)


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
