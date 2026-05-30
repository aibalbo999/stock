from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from app.data_sources.company_filings import REQUIRED_CORE_DOCUMENT_TYPES, filing_quality_score
from app.core.time import format_taipei, now_taipei
from app.core.prompts import REPORT_PROMPT_TEMPLATE, SYSTEM_PROMPT
from app.db.session import session_scope
from app.models.schemas import (
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ReportResponse,
    RiskType,
    ValuationMetric,
)
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import render_candidate_audit_markdown
from app.services.entity_mapping import EntityMapper, company_filing_owner_ticker
from app.services.followup_actions import FollowUpActionPlanner, render_follow_up_actions_markdown
from app.services.llm_client import LLMClient, LLMResult
from app.services.llm_analysis import LLMSupplementValidator
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.persistence import (
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ValuationMetricRepository,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.whitelist import SupplyChainWhitelist


MAX_LLM_EVIDENCE_DOCUMENTS = 60
MAX_LLM_EVIDENCE_TEXT_CHARS = 300
REPORT_READING_SORT_NOTE = (
    "排序：先依判斷結果分組（可研究、觀察、待補、避開），"
    "同組再依目前股價由高到低；缺股價者排在同組後段。"
)


class ReportExecutionError(ValueError):
    pass


def report_execution_summary(generator: object) -> dict:
    evidence_documents = getattr(generator, "last_evidence_documents", None) or []
    llm_result = getattr(generator, "last_llm_result", None)
    llm_status = None
    if llm_result is not None:
        llm_status = {
            "fallback": bool(getattr(llm_result, "fallback", False)),
            "model": getattr(llm_result, "model", None),
            "key_index": getattr(llm_result, "key_index", None),
        }
    return {
        "filtered_tickers": list(getattr(generator, "last_filtered_tickers", None) or []),
        "dropped_tickers": list(getattr(generator, "last_dropped_tickers", None) or []),
        "evidence_count": len(evidence_documents),
        "llm": llm_status,
    }


class ReportGenerator:
    def __init__(
        self,
        vector_store: VectorStore | None = None,
        whitelist: SupplyChainWhitelist | None = None,
    ) -> None:
        self.whitelist = whitelist or SupplyChainWhitelist()
        self.vector_store = vector_store or VectorStore()
        self.mapper = EntityMapper(self.whitelist)
        self.risk_analyzer = RiskAnalyzer(self.whitelist, self.mapper, use_llm=False)
        self.llm = LLMClient()
        self.last_evidence_documents: list[NewsDocument] = []
        self.last_llm_result: LLMResult | None = None
        self.last_filtered_tickers: list[str] = []
        self.last_dropped_tickers: list[str] = []
        self._document_match_cache: dict[tuple[str, str, str, int], list] = {}

    def generate(self, request: ReportRequest, documents: list[NewsDocument] | None = None) -> ReportResponse:
        evidence_docs = documents or self._retrieve_evidence(request)
        self.last_evidence_documents = list(evidence_docs)
        findings = self.risk_analyzer.analyze_documents(evidence_docs)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        self.last_filtered_tickers = tickers
        self.last_dropped_tickers = [ticker for ticker in request.tickers if ticker not in set(tickers)]
        if self.last_dropped_tickers:
            dropped_tickers = "、".join(self.last_dropped_tickers)
            raise ReportExecutionError(
                f"報告產生中止：以下指定股票未進入目前白名單：{dropped_tickers}。"
                "若這是 AI 主題探索或補強重跑，必須套用候選公司動態白名單，"
                "避免產出缺漏個股分析卻顯示成功的報告。"
            )
        market_snapshots = self._latest_market_snapshots(tickers)
        monthly_revenues = self._latest_monthly_revenues(tickers)
        financial_metrics = self._financial_metrics(tickers)
        valuation_metrics = self._latest_valuations(tickers)
        leading_signals = self._leading_signals(tickers, valuation_metrics)

        prompt = SYSTEM_PROMPT + "\n\n" + REPORT_PROMPT_TEMPLATE.format(
            whitelist=self.whitelist.as_prompt_context(),
            evidence=self._format_llm_evidence(evidence_docs),
            market_data=self._format_market_data(market_snapshots, monthly_revenues),
        )
        llm_result = self.llm.generate_with_metadata(prompt)
        self.last_llm_result = llm_result
        markdown = self._render_markdown(
            request,
            evidence_docs,
            findings,
            tickers,
            llm_result,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )
        return ReportResponse(
            title=f"{request.topic} 自動分析報告",
            generated_at=now_taipei(),
            markdown=markdown,
            findings=findings,
        )

    def _retrieve_evidence(self, request: ReportRequest) -> list[NewsDocument]:
        evidence_docs = self.vector_store.search(request.topic)
        try:
            with session_scope() as session:
                db_documents = NewsRepository(session).latest_documents(limit=300)
                filing_tickers = list(dict.fromkeys(request.tickers)) or self.mapper.filter_allowed_tickers(request.tickers)
                company_filing_documents = [
                    CompanyFilingRepository.to_news_document(document)
                    for document in CompanyFilingRepository(session).latest_by_tickers(
                        filing_tickers,
                        limit_per_ticker=6,
                    )
                ]
        except Exception:
            db_documents = []
            company_filing_documents = []
        documents = self._dedupe_documents([*evidence_docs, *db_documents, *company_filing_documents])
        ranked = self._rank_evidence_documents(request, documents)
        if ranked:
            return ranked[: request.evidence_limit]
        if evidence_docs:
            return evidence_docs
        try:
            with session_scope() as session:
                return NewsRepository(session).search_documents(request.topic, limit=20)
        except Exception:
            return []

    @staticmethod
    def _dedupe_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        deduped: dict[str, NewsDocument] = {}
        for document in documents:
            key = document.id or document.source.url or document.title
            deduped.setdefault(key, document)
        return list(deduped.values())

    def _rank_evidence_documents(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
    ) -> list[NewsDocument]:
        topic_terms = [term for term in request.topic.replace("/", " ").split() if term]
        requested = self.mapper.filter_allowed_tickers(request.tickers)
        companies = {company.ticker: company for company in self.whitelist.companies()}
        entity_terms: list[str] = []
        evidence_terms: list[str] = []
        for ticker in requested:
            company = companies.get(ticker)
            if not company:
                continue
            entity_terms.extend([ticker, company.name, *company.aliases])
            evidence_terms.extend(company.evidence_keywords)
        if not entity_terms:
            entity_terms = [
                term
                for company in self.whitelist.companies()
                for term in [company.ticker, company.name, *company.aliases]
                if term
            ]
            evidence_terms = [
                keyword
                for company in self.whitelist.companies()
                for keyword in company.evidence_keywords
                if keyword
            ]

        ranked: list[tuple[int, NewsDocument]] = []
        for document in documents:
            text = f"{document.title}\n{document.text}"
            entity_hits = sum(1 for term in entity_terms if term and term in text)
            evidence_hits = sum(1 for term in evidence_terms if term and term in text)
            topic_hits = sum(1 for term in topic_terms if term and term in text)
            risk_hits = sum(
                1
                for keywords in self.whitelist.risk_keywords.values()
                for keyword in keywords
                if keyword and keyword in text
            )
            if not entity_hits and not evidence_hits and not topic_hits and not risk_hits:
                continue
            score = entity_hits * 5 + evidence_hits * 3 + topic_hits * 2 + risk_hits
            ranked.append((score, document))
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1].source.published_at.isoformat() if item[1].source.published_at else "",
            ),
            reverse=True,
        )
        return [document for _score, document in ranked]

    def _latest_market_snapshots(self, tickers: list[str]) -> list[MarketSnapshot]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return MarketRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _latest_monthly_revenues(self, tickers: list[str]) -> list[MonthlyRevenue]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return MonthlyRevenueRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _financial_metrics(self, tickers: list[str]) -> list[FinancialMetric]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return FinancialMetricRepository(session).by_tickers(tickers)
        except Exception:
            return []

    def _latest_valuations(self, tickers: list[str]) -> list[ValuationMetric]:
        if not tickers:
            return []
        try:
            with session_scope() as session:
                return ValuationMetricRepository(session).latest_by_tickers(tickers)
        except Exception:
            return []

    def _leading_signals(
        self,
        tickers: list[str],
        valuation_metrics: list[ValuationMetric],
    ) -> dict[str, LeadingSignal]:
        if not tickers:
            return {}
        try:
            with session_scope() as session:
                price_histories = MarketRepository(session).history_by_tickers(tickers, limit=90)
                revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(tickers, limit=18)
        except Exception:
            price_histories = {}
            revenue_histories = {}
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics}
        peer_summary = self._peer_valuation_summary(valuation_metrics)
        return LeadingSignalAnalyzer().build(tickers, price_histories, revenue_histories, valuations, peer_summary)

    def _render_markdown(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
        findings,
        tickers: list[str],
        llm_result: LLMResult,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue],
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        leading_signals = leading_signals or {}
        if financial_metrics:
            metrics_by_ticker = self._group_financial_metrics(financial_metrics)
            leading_signals = {
                ticker: self._sanitize_leading_signal_for_profitability(
                    signal,
                    self._has_negative_profitability(metrics_by_ticker.get(ticker, [])),
                )
                for ticker, signal in leading_signals.items()
            }
        ordered_tickers = self._ordered_tickers_for_reading(
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
        lines = [
            f"# {request.topic} 自動分析報告",
            "",
            f"生成時間（台灣）：{now_taipei().isoformat(timespec='seconds')}",
            "",
            "## 一頁摘要",
            self._render_executive_snapshot(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 可信度檢查",
            self._render_credibility_check(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 時間口徑說明",
            self._render_time_scope_note(
                request,
                market_snapshots,
                monthly_revenues,
                valuation_metrics,
            ),
            "",
            "## 判斷準則說明",
            self._render_decision_criteria_note(request),
            "",
            "## 下一步行動",
            self._render_action_checklist(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 監控清單",
            self._render_monitoring_checklist(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 自動補強任務",
            self._render_follow_up_actions(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 先看結論",
            self._summary(findings),
            "",
            "## 候選公司審計",
            self._render_candidate_audit(ordered_tickers),
            "",
            "## 資料完整度",
            self._render_data_quality(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 來源覆蓋",
            self._render_source_coverage(request, ordered_tickers, documents),
            "",
            "## 近況訊號檢查",
            self._render_leading_signal_check(ordered_tickers, leading_signals),
            "",
            "## 早期潛力雷達",
            self._render_early_potential_radar(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                leading_signals,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 資金控管建議",
            self._render_beginner_portfolio_plan(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 投資建議",
            self._render_investment_recommendations(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 個股比較矩陣",
            self._render_company_comparison_matrix(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 投資理由地圖",
            self._render_investment_thesis_map(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 二次綜合篩選",
            self._render_final_potential_screen(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 評分明細",
            self._render_score_breakdown(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
            "",
            "## 基本面月營收檢查",
            self._render_revenue_check(ordered_tickers, monthly_revenues),
            "",
            "## 個別公司分析",
            self._render_company_analysis(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                request=request,
                leading_signals=leading_signals,
            ),
            "",
            "## 主要風險與瓶頸",
            self._render_risk_overview(findings),
            "",
            "## 分析範圍",
            self._render_scope(ordered_tickers, market_snapshots, monthly_revenues),
            "",
            "## 附錄：AI 補充與資料來源",
            self._render_appendix(llm_result, documents, market_snapshots),
        ]
        return "\n".join(lines)

    def _render_credibility_check(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前沒有形成可驗證股票範圍；本報告可信度不足，只能作為主題觀察。"

        publishers = {
            document.source.publisher or document.source.url or document.title or "來源不明"
            for document in documents
        }
        dated_documents = [document for document in documents if document.source.published_at is not None]
        cutoff = now_taipei().date() - timedelta(days=request.lookback_days)
        recent_documents = [
            document
            for document in dated_documents
            if document.source.published_at and document.source.published_at >= cutoff
        ]
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}

        company_rows = []
        high_count = 0
        medium_count = 0
        low_count = 0
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            related_publishers = {
                document.source.publisher or document.source.url or document.title or "來源不明"
                for document in related_documents
            }
            latest_dates = [
                document.source.published_at
                for document in related_documents
                if document.source.published_at is not None
            ]
            latest = max(latest_dates).isoformat() if latest_dates else "日期不明"
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            signal = (leading_signals or {}).get(ticker)
            filing_missing = self._company_filing_missing(ticker, documents)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                ticker_metrics,
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                filing_missing,
            )
            limitations = []
            if len(related_documents) < 2:
                limitations.append("公司文本少於 2 筆")
            if len(related_publishers) < 2:
                limitations.append("來源家數少於 2")
            if not related_findings:
                limitations.append("缺少風險/機會歸因")
            if ticker not in snapshots:
                limitations.append("缺股價")
            if ticker not in revenues:
                limitations.append("缺月營收")
            if not ticker_metrics:
                limitations.append("缺已揭露年度財報")
            if ticker not in valuations:
                limitations.append("缺估值")
            if filing_missing:
                limitations.append("缺公司公開文件")

            if quality["grade"] == "complete" and len(related_publishers) >= 2 and related_findings:
                credibility = "高"
                high_count += 1
            elif quality["grade"] in {"complete", "partial"} or (len(related_documents) >= 2 and len(related_publishers) >= 2):
                credibility = "中"
                medium_count += 1
            else:
                credibility = "低"
                low_count += 1
            label = f"{ticker} {company.name if company else ticker}"
            company_rows.append(
                self._table_row(
                    [
                        label,
                        credibility,
                        f"{len(related_documents)} 筆 / {len(related_publishers)} 來源",
                        f"{len(related_findings)} 筆",
                        latest,
                        "、".join(limitations[:5]) if limitations else "未發現重大資料缺口",
                    ]
                )
            )

        date_coverage = f"{len(dated_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
        recent_coverage = f"{len(recent_documents)}/{len(documents)} 筆" if documents else "0/0 筆"
        source_status = "可追溯" if documents else "不足"
        diversity_status = "多來源" if len(publishers) >= 3 else "偏少"
        date_status = "可判讀" if dated_documents else "不足"
        company_status = "可用" if high_count or medium_count else "不足"
        lines = [
            "本段先檢查報告本身的可信度，再看個股投資理由；若可信度不足，結論會降級為觀察或待補資料。",
            "",
            "| 檢查項目 | 狀態 | 本次證據 | 對投資判斷的影響 |",
            "|---|---|---|---|",
            f"| 可追溯來源 | {source_status} | 共 {len(documents)} 筆文本 | 沒有來源時只保留主題觀察，不產生買進研究。 |",
            f"| 來源多樣性 | {diversity_status} | {len(publishers)} 個發布者 | 來源過少時，避免被單一新聞或單一觀點誤導。 |",
            f"| 來源時間戳 | {date_status} | {date_coverage} 有日期；近 {request.lookback_days} 天 {recent_coverage} | 日期不足或過舊時，目前情境分數需下修。 |",
            f"| 公司層級證據 | {company_status} | 高可信 {high_count} 檔、中可信 {medium_count} 檔、低可信 {low_count} 檔 | 只有題材但缺公司證據時，不列入可研究標的。 |",
            f"| 市場與財務資料 | 可檢查 | 股價 {len(snapshots)} 檔、月營收 {len(revenues)} 檔、估值 {len(valuations)} 檔 | 財務或估值缺口會限制投資理由強度。 |",
            f"| 風險/機會歸因 | {'可用' if findings else '不足'} | {len(findings)} 筆系統驗證後歸因 | 風險未歸因時，不把新聞熱度直接當投資理由。 |",
            "",
            "### 個股可信度核對",
            "| 股票 | 可信度 | 公司文本 | 歸因證據 | 最近來源日期 | 主要限制 |",
            "|---|---|---:|---:|---|---|",
            *company_rows,
            "",
            "### 可信度判讀規則",
            "- 高可信：公司文本、來源家數、風險/機會歸因、股價、月營收、財報、估值與公司文件大致齊備。",
            "- 中可信：已有公司層級證據，但仍有財務、估值、官方文件或近期資料缺口。",
            "- 低可信：文本、來源家數或公司層級歸因不足；只能觀察，不應形成買進研究。",
        ]
        return "\n".join(lines)

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
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> list[dict]:
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        downside_gate = self._downside_gate(request)
        contexts = []
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            valuation = valuations.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
            )
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            valuation_label = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            contexts.append(
                {
                    "ticker": ticker,
                    "name": company.name if company else ticker,
                    "label": f"{ticker} {company.name if company else ticker}",
                    "documents": related_documents,
                    "findings": related_findings,
                    "snapshot": snapshot,
                    "revenue": revenue,
                    "valuation": valuation,
                    "valuation_label": valuation_label,
                    "current_price": self._current_price_text(snapshot),
                    "current_price_label": self._current_price_label(
                        snapshot,
                        estimate,
                        quality,
                        valuation_label,
                        signal,
                        decision,
                        downside_gate,
                    ),
                    "estimate": estimate,
                    "leading_signal": signal,
                    "quality": quality,
                    "decision": decision,
                }
            )
        return contexts

    def _ordered_tickers_for_reading(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> list[str]:
        contexts = self._decision_contexts(
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
        return [context["ticker"] for context in self._sort_decision_contexts(contexts)]

    @classmethod
    def _sort_decision_contexts(cls, contexts: list[dict]) -> list[dict]:
        return sorted(contexts, key=cls._decision_sort_key)

    @classmethod
    def _decision_sort_key(cls, context: dict) -> tuple:
        estimate = context.get("estimate") or {}
        return (
            cls._decision_rank(context.get("decision")),
            -cls._context_current_price(context),
            -float(estimate.get("upside_pct") or 0),
            float(estimate.get("downside_pct") or 0),
            str(context.get("ticker") or ""),
        )

    @staticmethod
    def _decision_rank(decision: str | None) -> int:
        ranks = {
            "可小額分批研究": 0,
            "觀察 / 等風險降低": 1,
            "觀察": 2,
            "觀察 / 資料待補": 3,
            "觀察 / 資料不足": 4,
            "資料不足": 5,
            "避開 / 降低曝險": 6,
        }
        return ranks.get(decision or "", 99)

    @staticmethod
    def _context_current_price(context: dict) -> float:
        snapshot = context.get("snapshot")
        close = getattr(snapshot, "close", None)
        if close is None:
            return -1.0
        try:
            return float(close)
        except (TypeError, ValueError):
            return -1.0

    def _render_action_checklist(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "1. 先補足新聞與市場資料，再重新執行分析。"

        contexts = self._sort_decision_contexts(
            self._decision_contexts(
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
        research = [item for item in contexts if item["decision"] == "可小額分批研究"]
        watch = [
            item
            for item in contexts
            if item["decision"] not in {"可小額分批研究", "避開 / 降低曝險"}
        ]
        avoid = [item for item in contexts if item["decision"] == "避開 / 降低曝險"]

        lines = [
            "1. 先處理資料缺口：若有「缺主題歸因、缺月營收、缺股價、缺公司公開文件」，先補資料再考慮加碼。",
            "2. 只把資料完整且通過目前情境降值門檻的股票放進小額研究清單。",
            "3. 對目前情境降值分高於門檻或近況訊號偏空的股票，先等風險下降或新資料確認。",
            "",
            "### 可立即研究",
        ]
        if research:
            for item in research:
                lines.append(
                    f"- {item['label']}：可看資金控管建議中的首筆配置；"
                    f"目前情境升值分 {item['estimate']['upside_pct']} 分，"
                    f"目前情境降值分 {item['estimate']['downside_pct']} 分。"
                )
        else:
            lines.append("- 目前沒有同時通過資料完整度與風險門檻的標的。")

        lines.extend(["", "### 待補資料 / 觀察"])
        if watch:
            for item in watch:
                missing = "、".join(item["quality"]["missing"]) if item["quality"]["missing"] else "等待新證據"
                lines.append(
                    f"- {item['label']}：{item['decision']}；下一步補查 {missing}。"
                    f"重新評估條件：{self._recheck_trigger_text(item, self._downside_gate(request))}"
                )
        else:
            lines.append("- 目前沒有待補資料名單。")

        lines.extend(["", "### 先避開"])
        if avoid:
            for item in avoid:
                lines.append(
                    f"- {item['label']}：目前情境降值分 {item['estimate']['downside_pct']} 分，"
                    f"暫不列入買進研究。重新評估條件：{self._recheck_trigger_text(item, self._downside_gate(request))}"
                )
        else:
            lines.append("- 目前沒有明確避開名單。")
        return "\n".join(lines)

    @staticmethod
    def _recheck_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        estimate = context.get("estimate") or {}
        quality = context.get("quality") or {}
        signal: LeadingSignal | None = context.get("leading_signal")
        gate = int(downside_gate or context.get("downside_gate") or 5)
        triggers = []
        if quality.get("missing"):
            triggers.append("補齊" + "、".join(quality["missing"][:3]))
        if signal and signal.direction == "偏空":
            triggers.append("近況訊號由偏空轉為中性以上")
        elif signal and signal.direction == "中性":
            triggers.append("近況訊號轉偏多且量價/營收同步改善")
        elif not signal or not signal.has_signal_data:
            triggers.append("補齊股價歷史、月營收或估值後重算近況訊號")
        if estimate.get("downside_pct", 0) > gate:
            triggers.append(f"目前情境降值分降至 {gate} 分以下")
        if estimate.get("upside_pct", 0) <= 10:
            triggers.append("目前情境升值分重新站上 10 分")
        return "；".join(triggers[:4]) if triggers else "等待新來源確認投資假設延續"

    @staticmethod
    def _avoid_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        estimate = context.get("estimate") or {}
        signal: LeadingSignal | None = context.get("leading_signal")
        gate = int(downside_gate or context.get("downside_gate") or 5)
        triggers = []
        if estimate.get("downside_pct", 0) > gate:
            triggers.append(f"目前情境降值分仍高於 {gate} 分")
        if signal and signal.direction == "偏空":
            triggers.append("近況訊號維持偏空")
        if estimate.get("upside_pct", 0) <= 10:
            triggers.append("目前情境升值分低於 10 分")
        return "；".join(triggers[:3]) if triggers else "若新資料未改善，維持觀察"

    @staticmethod
    def _monitor_frequency(context: dict) -> str:
        decision = context.get("decision")
        estimate = context.get("estimate") or {}
        signal: LeadingSignal | None = context.get("leading_signal")
        if decision == "避開 / 降低曝險":
            return "每週"
        if signal and signal.direction == "偏空":
            return "每週"
        if estimate.get("downside_pct", 0) > 5:
            return "每週"
        if decision == "可小額分批研究":
            return "每週"
        return "每月"

    def _render_monitoring_checklist(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無可監控股票。"
        downside_gate = self._downside_gate(request)
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
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
        lines = [
            "這張表把觀察與避開名單轉成可執行監控規則；條件未改善前，不把觀察股升級為買進研究。",
            "",
            "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |",
            "|---|---|---|---|---|",
        ]
        for context in contexts:
            lines.append(
                self._table_row(
                    [
                        context["label"],
                        context["decision"],
                        self._recheck_trigger_text(context, downside_gate),
                        self._avoid_trigger_text(context, downside_gate),
                        self._monitor_frequency(context),
                    ]
                )
            )
        return "\n".join(lines)

    def _render_follow_up_actions(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
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
        downside_gate = self._downside_gate(request)
        for context in contexts:
            context["downside_gate"] = downside_gate
            context["recheck_trigger"] = self._recheck_trigger_text(context, downside_gate)
            context["avoid_trigger"] = self._avoid_trigger_text(context, downside_gate)
        actions = FollowUpActionPlanner().plan(request, contexts=contexts)
        return render_follow_up_actions_markdown(actions)

    @staticmethod
    def _render_time_scope_note(
        request: ReportRequest,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
    ) -> str:
        latest_market = max((snapshot.trade_date for snapshot in market_snapshots), default=None)
        latest_revenue = max((revenue.revenue_date for revenue in monthly_revenues or []), default=None)
        latest_valuation = max((valuation.trade_date for valuation in valuation_metrics or []), default=None)
        market_text = latest_market.isoformat() if latest_market else "尚無股價日期"
        revenue_text = latest_revenue.isoformat() if latest_revenue else "尚無月營收日期"
        valuation_text = latest_valuation.isoformat() if latest_valuation else "尚無估值日期"
        generated_text = now_taipei().isoformat(timespec="seconds")
        return "\n".join(
            [
                f"- 「目前」指本報告生成時間（台灣）{generated_text} 前已取得並通過資料品質檢查的內容，不代表未來一定維持。",
                f"- 「近 {request.lookback_days} 天來源」指新聞/RAG 來源回看區間；公司公開文件、已揭露年度財報與估值仍以各自原始日期判讀。",
                f"- 「目前估值」只比較最新估值日 {valuation_text} 的 P/E、P/B、殖利率與本次同業樣本，不是未來估值預測。",
                "- 「當下股價標籤」會納入最新收盤價、近 20/60 日股價動能、量能、目前相對估值與目前情境降值分；它是追價風險提示，不是買賣指令。",
                "- 「目前情境升值分／目前情境降值分」是依目前證據計算的排序分數，不是預期報酬率、目標價或保證幅度。",
                f"- 「近況訊號」使用最新股價日 {market_text}、月營收日 {revenue_text} 與估值日 {valuation_text} 的近 20/60 日或月資料，是追蹤警示，不是未來走勢預測。",
            ]
        )

    @staticmethod
    def _render_decision_criteria_note(request: ReportRequest) -> str:
        downside_gate = ReportGenerator._downside_gate(request)
        return "\n".join(
            [
                f"- 本次投資人設定為「{ReportGenerator._profile_label(request)}」；目前情境降值分超過 {downside_gate} 分時，原則上先列觀察。",
                "- 「可小額分批研究」必須同時符合：資料等級完整、目前情境升值分高於 10 分、目前情境降值分未超過投資人門檻、近況訊號不偏空，且沒有結構性瓶頸、短期波動或財務/估值紅旗。",
                "- 「觀察 / 等風險降低」代表題材與資料可以追蹤，但存在結構性瓶頸或尚未解除的財務/估值疑慮，不列入本次配置。",
                "- 「避開 / 降低曝險」代表目前情境降值分已高於升值分，或財務/估值紅旗偏重；單純超過投資人門檻會先列觀察，不會一票否決。",
                "- 「當下股價標籤」若顯示不適合追價、等止跌、等回檔或等風險下降，代表現在不應只因題材熱度就投入。",
                "- 財務/估值檢查會納入已揭露年度營收、淨利、負債權益比、ROE/淨利率與目前相對估值；若財務紅旗存在，題材分數不能單獨升級成可研究標的。",
            ]
        )

    def _render_executive_snapshot(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "本次沒有形成可驗證個股清單；先補資料，不建議依此報告做個股配置。"

        rows = []
        actionable = 0
        watch = 0
        avoid = 0
        weak = 0
        for item in self._sort_decision_contexts(
            self._decision_contexts(
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
        ):
            decision = item["decision"]
            quality = item["quality"]
            estimate = item["estimate"]
            signal = item.get("leading_signal")
            if decision == "可小額分批研究":
                actionable += 1
            elif decision == "避開 / 降低曝險":
                avoid += 1
            elif quality["grade"] == "weak":
                weak += 1
            else:
                watch += 1
            rows.append(
                self._table_row(
                    [
                        item["label"],
                        decision,
                        item["current_price"],
                        item["current_price_label"],
                        self._quality_label(quality["grade"]),
                        f"{estimate['upside_pct']} 分",
                        f"{estimate['downside_pct']} 分",
                        signal.direction if signal else "未評估",
                        "、".join(quality["missing"]) if quality["missing"] else "完整",
                    ]
                )
            )

        deployable = request.investor_capital - int(request.investor_capital * request.cash_reserve_pct)
        if actionable:
            headline = f"本次有 {actionable} 檔可小額研究；仍需依資金控管分批，不建議一次買滿。"
        elif avoid:
            headline = "本次沒有可小額研究標的，且有股票進入避開/降低曝險名單。"
        else:
            headline = "本次沒有可小額研究標的；先補資料或等待新證據。"
        lines = [
            f"**重點提醒：{headline}**",
            "",
            "| 項目 | 結果 |",
            "|---|---|",
            f"| 投資人設定 | {self._profile_label(request)}；總資金 {request.investor_capital:,} 元；"
            f"品質門檻最多允許研究約 {deployable:,} 元，但本次實際配置以投資建議與資金控管為準 |",
            f"| 本次股票範圍 | {len(tickers)} 檔 |",
            f"| 可小額研究 | {actionable} 檔 |",
            f"| 觀察/待補 | {watch + weak} 檔 |",
            f"| 避開/降低曝險 | {avoid} 檔 |",
            "",
            "### 決策總覽",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 判斷 | 目前股價 | 當下股價標籤 | 資料等級 | 目前情境升值分 | 目前情境降值分 | 近況訊號 | 主要缺口 |",
            "|---|---|---|---|---|---:|---:|---|---|",
            *rows,
            "",
            "閱讀方式：先看「判斷」與「主要缺口」；升值/降值欄位是目前情境分數，不是未來報酬率。",
        ]
        return "\n".join(lines)

    def _render_data_quality(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "未形成可驗證股票範圍；本次報告只能保留主題觀察，不能產出個股投資判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        strong = 0
        partial = 0
        weak = 0
        lines = [
            "本段檢查每檔股票是否同時具備新聞/RAG、主題歸因、股價、月營收、已揭露年度財報、估值與公司公開文件；資料不足時，系統會降低建議強度。",
            "",
            "| 股票 | 新聞/RAG | 主題歸因 | 股價 | 月營收 | 年度財報 | 估值 | 公司文件 | 近況訊號 | 判讀 |",
            "|---|---:|---:|---|---|---:|---|---|---|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            has_snapshot = ticker in snapshots
            has_revenue = ticker in revenues
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            filing_missing = self._company_filing_missing(ticker, documents)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                filing_missing,
            )
            missing = quality["missing"]

            if not missing:
                verdict = "完整，可進入二次篩選"
                strong += 1
            elif quality["grade"] == "partial":
                verdict = "部分可用，僅列觀察：" + "、".join(missing)
                partial += 1
            else:
                verdict = "不足：" + "、".join(missing)
                weak += 1

            label = f"{ticker} {company.name if company else ticker}"
            price_label = snapshots[ticker].trade_date.isoformat() if has_snapshot else "缺"
            revenue_label = (
                f"{revenues[ticker].revenue_year}-{revenues[ticker].revenue_month:02d}"
                if has_revenue
                else "缺"
            )
            financial_label = str(len(ticker_metrics)) if ticker_metrics else "缺"
            valuation_label = valuation.trade_date.isoformat() if valuation else "缺"
            filing_label = "足夠" if not filing_missing else "缺"
            signal_label = signal.direction if signal and signal.has_signal_data else "缺"
            lines.append(
                self._table_row(
                    [
                        label,
                        len(related_documents),
                        len(related_findings),
                        price_label,
                        revenue_label,
                        financial_label,
                        valuation_label,
                        filing_label,
                        signal_label,
                        verdict,
                    ]
                )
            )

        lines.extend(
            [
                "",
                f"整體判讀：完整 {strong} 檔、部分可用 {partial} 檔、資料不足 {weak} 檔。",
            ]
        )
        if weak or partial:
            lines.append("投資結論會優先採用資料完整標的；資料不足標的不會只因單一題材或單一財務數字被列為優先買進。")
        return "\n".join(lines)

    def _render_score_breakdown(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        lines = [
            "此段拆解研究分級來源；分數是排序與風險控管用途，不代表預期報酬率。",
            "",
            "| 股票 | 目前情境升值分 | 目前情境降值分 | 主要加分 | 主要風險 | 資料提醒 |",
            "|---|---:|---:|---|---|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            label = f"{ticker} {company.name if company else ticker}"
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                (leading_signals or {}).get(ticker),
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            lines.append(
                self._table_row(
                    [
                        label,
                        f"{estimate['upside_pct']} 分",
                        f"{estimate['downside_pct']} 分",
                        self._format_factors(estimate["upside_factors"]),
                        self._format_factors(estimate["downside_factors"]),
                        self._score_data_note(
                            estimate["confidence_notes"],
                            metrics_by_ticker.get(ticker, []),
                            valuations.get(ticker),
                        ),
                    ]
                )
            )
        return "\n".join(lines)

    def _render_source_coverage(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
    ) -> str:
        if not documents:
            return "目前無足夠數據判斷。"

        publisher_counts = Counter(document.source.publisher or "來源不明" for document in documents)
        international_count = sum(1 for document in documents if self._is_international_source(document))
        taiwan_count = len(documents) - international_count
        lines = [
            "本段說明本次可追溯證據池的來源覆蓋；來源多不代表一定可買，仍需看公司層級歸因與財務資料是否同時成立。",
            "",
            "| 項目 | 結果 |",
            "|---|---|",
            f"| 摘要使用證據上限 | {request.evidence_limit} 筆 |",
            f"| 可追溯證據池總量 | {len(documents)} 筆 |",
            f"| 台灣來源 | {taiwan_count} 筆 |",
            f"| 國際來源 | {international_count} 筆 |",
            self._table_row(
                [
                    "主要來源",
                    "、".join(f"{publisher}({count})" for publisher, count in publisher_counts.most_common(6)),
                ]
            ),
            "",
            "### 個股來源覆蓋",
            "| 股票 | 公司相關文本 | 國際文本 | 最近來源日期 |",
            "|---|---:|---:|---|",
        ]
        companies = {company.ticker: company for company in self.whitelist.companies()}
        for ticker in tickers:
            related_documents = self._related_documents(ticker, documents)
            related_international = sum(1 for document in related_documents if self._is_international_source(document))
            latest_dates = [
                document.source.published_at
                for document in related_documents
                if document.source.published_at is not None
            ]
            latest = max(latest_dates).isoformat() if latest_dates else "日期不明"
            company = companies.get(ticker)
            label = f"{ticker} {company.name if company else ticker}"
            lines.append(self._table_row([label, len(related_documents), related_international, latest]))
        if international_count == 0:
            lines.extend(["", "提醒：本次沒有國際來源進入證據池；若要擴大國際覆蓋，請開啟深度分析與國際資料源。"])
        return "\n".join(lines)

    def _render_candidate_audit(self, promoted_tickers: list[str]) -> str:
        return render_candidate_audit_markdown(self.whitelist.candidate_audit(), promoted_tickers)

    @staticmethod
    def _render_leading_signal_check(
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
                    ReportGenerator._table_row(
                        [ticker, "未評估", 0, "-", "-", "-", "-", "-", "未評估", "目前無足夠近況訊號。"]
                    )
                )
                continue
            lines.append(
                ReportGenerator._table_row(
                    [
                        ticker,
                        signal.direction,
                        str(signal.score),
                        ReportGenerator._format_optional_pct(signal.price_20d_pct),
                        ReportGenerator._format_optional_pct(signal.price_60d_pct),
                        ReportGenerator._format_optional_ratio(signal.volume_ratio_20d),
                        ReportGenerator._format_optional_pct(signal.revenue_yoy_pct),
                        ReportGenerator._format_optional_pct(signal.revenue_acceleration_pct),
                        signal.valuation_label,
                        signal.summary,
                    ]
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _format_optional_pct(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}%"

    @staticmethod
    def _format_optional_ratio(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}x"

    def _render_early_potential_radar(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        candidate_evidence = self._candidate_audit_evidence_counts()
        contexts = {
            context["ticker"]: context
            for context in self._decision_contexts(
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
        }
        rows = []
        for ticker in tickers:
            context = contexts.get(ticker)
            if context and context["decision"] == "避開 / 降低曝險":
                continue
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            signal = (leading_signals or {}).get(ticker)
            estimate = dict(context["estimate"]) if context else self._estimate_potential(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                signal,
            )
            audit_counts = candidate_evidence.get(ticker, {})
            estimate.update(
                self._early_potential_profile(
                    related_documents,
                    revenues.get(ticker),
                    signal,
                    estimate["upside_pct"],
                    estimate["downside_pct"],
                    snapshots.get(ticker),
                    document_count_override=max(
                        len(related_documents),
                        int(audit_counts.get("evidence_count") or 0),
                    ),
                    publisher_count_override=max(
                        self._publisher_count(related_documents),
                        int(audit_counts.get("source_count") or 0),
                    ),
                )
            )
            if estimate["early_potential_score"] <= 0:
                continue
            if estimate["attention_label"] not in {"報導較少", "報導偏少"}:
                continue
            company = companies.get(ticker)
            decision_note = f"目前決策：{context['decision']}；" if context else ""
            rows.append(
                {
                    "label": f"{ticker} {company.name if company else ticker}",
                    "score": estimate["early_potential_score"],
                    "attention": estimate["attention_label"],
                    "upside": estimate["upside_pct"],
                    "downside": estimate["downside_pct"],
                    "reason": decision_note + estimate["early_potential_reason"],
                    "source": self._representative_sources(related_documents, limit=2),
                }
            )
        rows.sort(key=lambda row: (-row["score"], row["downside"], -row["upside"]))
        lines = [
            "本段專門找「截至目前報導較少、但近況訊號轉強」的研究線索；已排除避開/降低曝險標的。報導較少不是利多，代表仍需更多來源、成交量與公司文件驗證。",
            "",
            "| 股票 | 早期線索分 | 截至目前報導熱度 | 目前情境升值分 | 目前情境降值分 | 為什麼可能還早 | 代表來源 |",
            "|---|---:|---|---:|---:|---|---|",
        ]
        if not rows:
            lines.append("| 目前無足夠數據判斷 | 0 | - | - | - | 沒有同時符合報導較少與訊號轉強的標的。 | - |")
            return "\n".join(lines)
        for row in rows[:8]:
            lines.append(
                self._table_row(
                    [
                        row["label"],
                        str(row["score"]),
                        row["attention"],
                        f"{row['upside']} 分",
                        f"{row['downside']} 分",
                        row["reason"],
                        row["source"],
                    ]
                )
            )
        return "\n".join(lines)

    def _render_final_potential_screen(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        upside_rows = []
        downside_rows = []
        insufficient_rows = []

        for ticker in tickers:
            company = companies.get(ticker)
            name = company.name if company else ticker
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            signal = (leading_signals or {}).get(ticker)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
            )
            label = f"{ticker} {name}"
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"

            if estimate["upside_pct"] > 10:
                if quality["grade"] != "supported":
                    insufficient_rows.append(
                        f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分，但資料品質不足；"
                        f"{'；'.join(quality['missing'])}。"
                    )
                else:
                    upside_rows.append(
                        f"- {label}：目前證據的情境升值分約 {estimate['upside_pct']} 分。"
                        f"理由：{estimate['upside_reason']} 來源：{source}。"
                    )
            if estimate["downside_pct"] > 5:
                downside_rows.append(
                    f"- {label}：目前證據的情境降值分約 {estimate['downside_pct']} 分。"
                    f"理由：{estimate['downside_reason']} 來源：{source}。"
                )
            if estimate["upside_pct"] <= 10 and estimate["downside_pct"] <= 5:
                insufficient_rows.append(f"- {label}：未達目前情境升值/降值門檻或資料不足。")

        lines = [
            "本段為非個人化情境篩選；分數是依新聞、財務、估值與市場資料的研究分級，不是保證報酬或停損幅度。",
            "",
            "### 目前情境升值分較高（目前證據 >10）",
        ]
        lines.extend(upside_rows or ["目前無足夠數據判斷。"])
        lines.extend(["", "### 目前情境降值分較高（目前證據 >5）"])
        lines.extend(downside_rows or ["目前無足夠數據判斷。"])
        if insufficient_rows:
            lines.extend(["", "### 未達門檻 / 資料不足", *insufficient_rows])
        return "\n".join(lines)

    def _render_company_comparison_matrix(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        downside_gate = self._downside_gate(request)
        rows = []
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            signal = (leading_signals or {}).get(ticker)
            valuation_label = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
            )
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            rows.append(
                {
                    "ticker": ticker,
                    "label": f"{ticker} {company.name if company else ticker}",
                    "decision": decision,
                    "snapshot": snapshot,
                    "estimate": estimate,
                    "current_price": self._current_price_text(snapshot),
                    "current_price_label": self._current_price_label(
                        snapshot,
                        estimate,
                        quality,
                        valuation_label,
                        signal,
                        decision,
                        downside_gate,
                    ),
                    "upside": estimate["upside_pct"],
                    "downside": estimate["downside_pct"],
                    "valuation": valuation_label,
                    "confidence": self._financial_confidence_label(ticker_metrics, valuation, revenue),
                    "reminder": self._company_matrix_reminder(
                        estimate,
                        quality,
                        related_findings,
                        valuation,
                        peer_valuation_summary,
                        ticker_metrics,
                        signal,
                    ),
                }
            )
        rows.sort(key=self._decision_sort_key)
        lines = [
            "這張表用來比較正式分析股票的相對位置；它是研究排序工具，不是買賣指令。",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 判斷 | 目前股價 | 當下股價標籤 | 目前情境升值分 | 目前情境降值分 | 目前估值位置 | 財務信心 | 核心提醒 |",
            "|---|---|---|---|---:|---:|---|---|---|",
        ]
        for row in rows:
            lines.append(
                self._table_row(
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

    def _render_investment_thesis_map(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前沒有通過證據門檻的正式分析股票；先補候選公司證據，再建立投資理由。"

        contexts = self._sort_decision_contexts(
            self._decision_contexts(
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
        lines = [
            "本段把每檔股票拆成「為什麼值得研究」與「為什麼可能不成立」。這是研究假設，不是報酬保證或買賣指令。",
            REPORT_READING_SORT_NOTE,
        ]
        for context in contexts:
            estimate = context["estimate"]
            quality = context["quality"]
            documents_for_company = context["documents"]
            findings_for_company = context["findings"]
            signal: LeadingSignal | None = context.get("leading_signal")
            lines.extend(
                [
                    "",
                    f"### {context['label']}",
                    f"- 目前判斷：{context['decision']}；資料等級：{self._quality_label(quality['grade'])}。",
                    f"- 成長假設：{estimate['upside_reason']}",
                    f"- 主要風險：{estimate['downside_reason']}",
                    f"- 具體投資理由：{self._thesis_reason(context, request)}",
                    f"- 近況訊號：{signal.summary if signal and signal.has_signal_data else '目前缺股價歷史、月營收或估值序列，無法形成完整近況訊號。'}",
                    f"- 需要再確認：{self._thesis_verification_items(quality, findings_for_company, documents_for_company)}",
                    f"- 代表性來源：{self._representative_sources(documents_for_company)}",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _thesis_reason(context: dict, request: ReportRequest) -> str:
        estimate = context.get("estimate") or {}
        quality = context.get("quality") or {}
        decision = context.get("decision") or "觀察"
        reasons = []
        if estimate.get("upside_pct", 0) > 10:
            reasons.append(f"目前情境升值分 {estimate['upside_pct']} 高於 10 分的研究門檻")
        if estimate.get("downside_pct", 0) <= ReportGenerator._downside_gate(request):
            reasons.append(f"目前情境降值分 {estimate['downside_pct']} 未超過投資人設定門檻")
        if quality.get("grade") == "supported":
            reasons.append("新聞/主題歸因、股價、營收、財務/估值與公司文件的資料層較完整")
        if decision == "可小額分批研究":
            reasons.append("可先放入小額研究清單，用資金上限控管，而不是一次性建立大部位")
        if not reasons:
            missing = "、".join(quality.get("missing") or [])
            return f"目前投資理由尚未完整，主要卡在 {missing or '目前情境升值分與降值分差距不夠明確'}。"
        return "；".join(reasons) + "。"

    @staticmethod
    def _thesis_verification_items(
        quality: dict,
        findings,
        related_documents: list[NewsDocument],
    ) -> str:
        items = []
        items.extend(quality.get("missing") or [])
        if any(finding.risk_type == RiskType.structural_bottleneck for finding in findings):
            items.append("結構性瓶頸是否緩解")
        if len(related_documents) < 3:
            items.append("公司層級來源是否能增加到至少 3 筆")
        if not items:
            items.append("下一期月營收、法說或官方文件是否延續目前假設")
        return "、".join(list(dict.fromkeys(items))[:5])

    @staticmethod
    def _representative_sources(documents: list[NewsDocument], limit: int = 3) -> str:
        if not documents:
            return "目前無足夠公司層級來源。"
        labels = []
        for document in documents[:limit]:
            date_label = document.source.published_at.isoformat() if document.source.published_at else "日期不明"
            publisher = document.source.publisher or "來源不明"
            labels.append(f"{date_label} {publisher}《{document.title}》")
        return "；".join(labels)

    def _render_company_analysis(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        request: ReportRequest | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "未指定白名單個股，無法產出個別公司分析。"
        request = request or ReportRequest(tickers=tickers)

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        ordered_tickers = self._ordered_tickers_for_reading(
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
        overview_rows: list[str] = []
        detail_blocks: list[str] = []
        for ticker in ordered_tickers:
            company = companies.get(ticker)
            segment = self.whitelist.segment_for_ticker(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)
            signal = (leading_signals or {}).get(ticker)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                ticker_metrics,
                valuation,
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
            )
            downside_gate = self._downside_gate(request)
            decision = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            decision_reason = self._decision_reason(
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
            price_label = (
                f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close if snapshot.close is not None else 'NA'}"
                if snapshot
                else "缺"
            )
            revenue_label = (
                f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY "
                f"{revenue.yoy_pct:.2f}%"
                if revenue and revenue.yoy_pct is not None
                else "缺" if not revenue else f"{revenue.revenue_year}-{revenue.revenue_month:02d} YoY NA"
            )
            evidence_label = (
                f"{len(related_documents)} 文本 / {len(related_findings)} 歸因"
            )
            valuation_position = self._valuation_position_label(
                valuation,
                peer_valuation_summary,
                self._has_negative_profitability(ticker_metrics),
            )
            financial_confidence = self._financial_confidence_label(ticker_metrics, valuation, revenue)
            current_price_label = self._current_price_label(
                snapshot,
                estimate,
                quality,
                valuation_position,
                signal,
                decision,
                downside_gate,
            )
            overview_rows.append(
                self._table_row(
                    [
                        f"{ticker} {name}",
                        segment_name,
                        price_label,
                        current_price_label,
                        revenue_label,
                        valuation_position,
                        financial_confidence,
                        evidence_label,
                    ]
                )
            )

            detail_blocks.append(f"### {ticker} {name}")
            detail_blocks.append(
                "- 個股結論摘要："
                + self._company_quick_take(
                    snapshot,
                    revenue,
                    ticker_metrics,
                    valuation,
                    related_documents,
                    related_findings,
                )
            )
            detail_blocks.append(
                f"- 資料信心：{financial_confidence}；目前估值位置：{valuation_position}。"
            )
            detail_blocks.append(f"- 當下股價標籤：{current_price_label}；目前股價：{price_label}。")
            detail_blocks.append(f"- 產業鏈位置：{segment_name}")
            detail_blocks.extend(
                self._company_basic_intro(
                    ticker,
                    name,
                    segment_name,
                    company,
                    related_documents,
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
                self._render_wall_street_company_sections(
                    ticker,
                    name,
                    segment_name,
                    snapshot,
                    revenue,
                    ticker_metrics,
                    valuation,
                    peer_valuation_summary,
                    related_documents,
                    related_findings,
                    decision,
                    decision_reason,
                )
            )
            detail_blocks.append("")

        lines = [
            "### 個股速覽",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 產業位置 | 股價 | 當下股價標籤 | 月營收 | 目前估值位置 | 財務信心 | 證據狀態 |",
            "|---|---|---|---|---|---|---|---|",
            *overview_rows,
            "",
            "### 個股細節",
            *detail_blocks,
        ]
        return "\n".join(lines).strip()

    def _company_basic_intro(
        self,
        ticker: str,
        name: str,
        segment_name: str,
        company,
        related_documents: list[NewsDocument],
    ) -> list[str]:
        candidate = self._candidate_audit_by_ticker().get(ticker, {})
        aliases = [
            alias
            for alias in (getattr(company, "aliases", []) or [])
            if alias and alias not in {ticker, name}
        ]
        keywords = (
            list(getattr(company, "evidence_keywords", []) or [])
            or list(candidate.get("evidence_keywords") or [])
        )
        rationale = self._compact_text(candidate.get("rationale") or "", 120)
        if rationale:
            role_text = f"{rationale}。"
        else:
            role_text = "本報告只把它視為此主題中的可驗證研究對象，不直接推論為受惠股。"
        alias_text = "、".join(aliases[:4]) if aliases else "本次主要使用股票代號與公司名稱比對。"
        keyword_text = "、".join(str(keyword) for keyword in keywords[:6]) if keywords else "尚未設定固定關鍵字，主要依公司名稱、代號與來源文本比對。"
        filing_documents = [document for document in related_documents if self._is_company_filing_document(ticker, document)]
        filing_types = sorted(
            {
                self._news_document_filing_type(document) or "company_disclosure"
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

    def _candidate_audit_by_ticker(self) -> dict[str, dict]:
        return {
            str(candidate.get("ticker")): candidate
            for candidate in self.whitelist.candidate_audit()
            if candidate.get("ticker")
        }

    def _render_wall_street_company_sections(
        self,
        ticker: str,
        name: str,
        segment_name: str,
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        peer_valuation_summary: dict[str, float | None],
        related_documents: list[NewsDocument],
        related_findings,
        decision: str,
        decision_reason: str,
    ) -> list[str]:
        financial_summary = self._financial_statement_summary(financial_metrics)
        valuation_summary = self._valuation_summary(valuation, peer_valuation_summary)
        evidence_summary = self._company_evidence_summary(related_documents, related_findings)
        filing_summary = self._company_filing_evidence_summary(related_documents)
        revenue_summary = self._company_revenue_summary(revenue)
        moat_score = self._moat_score(related_documents, related_findings, revenue, financial_summary)
        return [
            "",
            "#### 華爾街式完整分析框架",
            f"- 商業模式與收入來源：{name} 本次被歸類在「{segment_name}」。"
            f"{filing_summary}本系統會交叉使用主題文本、月營收、已揭露年度財報與估值資料判斷需求是否落到公司層級。{evidence_summary}",
            f"- 競爭優勢（護城河）：護城河初評 {moat_score}/10。"
            f"依據：{self._moat_reason(moat_score, related_documents, related_findings, revenue, financial_summary)}",
            f"- 產業趨勢：{self._trend_summary(related_documents, related_findings)}",
            f"- 財務健康狀況：{financial_summary['health']} {revenue_summary}",
            "- 關鍵風險：" + self._company_risk_summary(related_findings),
            f"- 與競爭對手的估值比較：{valuation_summary} 同業 EV/EBITDA、毛利率與成長率比較仍需補資料。",
            "- 未來多頭情境：若需求證據延續、月營收成長改善且風險訊號未升高，股價具備重新評價機會。",
            "- 未來空頭情境：若風險訊號增加、月營收轉弱或產業瓶頸影響出貨，應降低曝險或等待資料修復。",
            "- 目前基本情境：維持觀察，除非資料完整度與目前情境降值門檻同時通過，才進入小額分批研究。",
            f"- 未來 12-24 個月展望：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            "",
            "#### 已揭露年度財務檢查",
            f"- 營收成長：{financial_summary['revenue_trend']}",
            f"- 淨利趨勢：{financial_summary['net_income_trend']}",
            f"- 自由現金流：{financial_summary['fcf_trend']}",
            f"- 利潤率：{financial_summary['margin_trend']}",
            f"- 負債水準：{financial_summary['debt_trend']}",
            f"- ROE：{financial_summary['roe_trend']}",
            f"- 財務體質判斷：{financial_summary['strength']}",
            "",
            "#### 競爭護城河",
            f"- 品牌影響力：{self._moat_factor_text('brand', related_documents, related_findings, revenue, financial_summary)}",
            f"- 網路效應：{self._moat_factor_text('network', related_documents, related_findings, revenue, financial_summary)}",
            f"- 轉換成本：{self._moat_factor_text('switching_cost', related_documents, related_findings, revenue, financial_summary)}",
            f"- 成本優勢：{self._moat_factor_text('cost', related_documents, related_findings, revenue, financial_summary)}",
            f"- 專利或獨家技術：{self._moat_factor_text('technology', related_documents, related_findings, revenue, financial_summary)}",
            f"- 護城河強度：{moat_score}/10。此分數只根據目前來源與月營收訊號，非完整同業研究。",
            "",
            "#### 估值分析",
            f"- P/E 與同業比較：{valuation_summary}",
            f"- DCF 估值：{self._dcf_proxy_text(financial_summary, valuation)}",
            f"- 產業平均估值：{self._industry_average_text(peer_valuation_summary)}",
            f"- 目前是否低估或高估：{self._valuation_conclusion(snapshot, valuation, peer_valuation_summary)}",
            "",
            "#### 未來成長假設",
            f"- 市場規模與產業成長率：{self._trend_summary(related_documents, related_findings)}",
            f"- 擴張機會與新產品：{self._growth_opportunity_text(related_documents, related_findings, revenue)}",
            "- AI 或技術優勢：若文本明確指向 AI 供應鏈受惠，可列為觀察點，但仍需訂單與財務驗證。",
            f"- 5-10 年潛在成長空間：{self._long_term_growth_text(financial_summary, revenue, related_documents)}",
            "",
            "#### 多空辯論",
            f"- 多頭分析師：{self._bull_case(revenue, related_documents)}",
            f"- 空頭分析師：{self._bear_case(related_findings)}",
            "- 中性結論：目前以資料完整度與風險門檻為準；缺少完整財報/估值時，不應只靠題材做重倉決策。",
            "",
            "#### 是否應該投資",
            f"- 短期展望（1 年內）：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            f"- 長期展望（5 年以上）：{self._long_term_growth_text(financial_summary, revenue, related_documents)}",
            "- 關鍵催化因素：月營收加速、客戶/訂單驗證、產能瓶頸緩解、毛利率改善。",
            "- 主要風險：" + self._company_risk_summary(related_findings),
            f"- 本次操作結論：{decision}。理由：{decision_reason}；此結論沿用投資建議總表，不等於個人化買賣建議。",
        ]

    def _render_investment_recommendations(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        ordered_tickers = self._ordered_tickers_for_reading(
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
        lines = [
            "以下為非個人化研究建議；未納入投資人風險承受度、持股成本與資金配置，不構成個別買賣指令。",
            REPORT_READING_SORT_NOTE,
            "",
            "| 股票 | 目前股價 | 當下股價標籤 | 建議 | 理由 | 單檔上限 | 來源 |",
            "|---|---|---|---|---|---:|---|",
        ]
        for ticker in ordered_tickers:
            company = companies.get(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)
            signal = (leading_signals or {}).get(ticker)
            estimate = self._estimate_potential(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                signal,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                peer_valuation_summary,
            )
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
                signal,
                self._company_filing_missing(ticker, documents),
            )
            downside_gate = self._downside_gate(request)
            name = company.name if company else ticker
            rating = self._decision_label(estimate, quality, related_findings, downside_gate, signal)
            valuation_label = self._valuation_position_label(
                valuations.get(ticker),
                peer_valuation_summary,
                self._has_negative_profitability(metrics_by_ticker.get(ticker, [])),
            )
            current_price = self._current_price_text(snapshot)
            current_price_label = self._current_price_label(
                snapshot,
                estimate,
                quality,
                valuation_label,
                signal,
                rating,
                downside_gate,
            )
            rationale = self._decision_reason(
                rating,
                estimate,
                quality,
                related_findings,
                related_documents,
                downside_gate,
                request,
                signal,
            )

            max_position = self._max_position_amount(request)
            position_limit = f"約 {max_position:,} 元" if rating == "可小額分批研究" else "不適用 / 0 元"
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"
            if related_documents:
                source += f"；代表性文本：{self._representative_sources(related_documents, limit=2)}"
            lines.append(
                self._table_row(
                    [f"{ticker} {name}", current_price, current_price_label, rating, rationale, position_limit, source]
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
        if not related_documents and not related_findings:
            return "目前沒有足夠公司層級文本或主題/風險歸因證據。"
        return f"目前有 {len(related_documents)} 筆公司相關文本、{len(related_findings)} 筆主題/風險歸因證據。"

    @staticmethod
    def _company_filing_evidence_summary(related_documents: list[NewsDocument]) -> str:
        filing_documents = [document for document in related_documents if document.id.startswith("filing-")]
        if not filing_documents:
            return "尚未取得足夠官方公開文件，因此收入拆分仍以外部資料與財報科目輔助判斷。"
        types = sorted(
            {
                ReportGenerator._news_document_filing_type(document) or "company_disclosure"
                for document in filing_documents
            }
        )
        publishers = sorted({document.source.publisher or "公開文件" for document in filing_documents})
        return (
            f"已納入 {len(filing_documents)} 份官方/公司公開文件"
            f"（{', '.join(types[:3])}；來源：{', '.join(publishers[:2])}），"
            "可用來校正商業模式、風險與財務敘述。"
        )

    @staticmethod
    def _company_revenue_summary(revenue: MonthlyRevenue | None) -> str:
        if not revenue:
            return "目前無月營收資料，無法判斷近期營收動能。"
        yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
        return f"{revenue.revenue_year}-{revenue.revenue_month:02d} 月營收 {revenue.revenue:,}，年增率 {yoy}。"

    @staticmethod
    def _company_quick_take(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        strengths = []
        cautions = []
        if related_documents:
            strengths.append(f"有 {len(related_documents)} 筆公司相關文本")
        else:
            cautions.append("缺公司層級新聞/研究證據")
        if revenue and revenue.yoy_pct is not None:
            if revenue.yoy_pct >= 20:
                strengths.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
            elif revenue.yoy_pct < 0:
                cautions.append(f"月營收年減 {abs(revenue.yoy_pct):.2f}%")
        else:
            cautions.append("缺月營收年增率")
        if valuation and valuation.pe_ratio is not None:
            strengths.append(f"P/E {valuation.pe_ratio:.2f}")
        else:
            cautions.append("缺估值倍數")
        if not financial_metrics:
            cautions.append("缺已揭露年度財報資料")
        if related_findings:
            cautions.append(f"需追蹤 {len(related_findings)} 筆風險/機會歸因")
        if not snapshot:
            cautions.append("缺最新股價")
        strength_text = "、".join(strengths[:3]) if strengths else "目前無明確加分訊號"
        caution_text = "、".join(cautions[:3]) if cautions else "暫無重大資料缺口"
        return f"{strength_text}；主要檢查點：{caution_text}。"

    @staticmethod
    def _group_financial_metrics(metrics: list[FinancialMetric]) -> dict[str, list[FinancialMetric]]:
        grouped: dict[str, list[FinancialMetric]] = {}
        for metric in metrics:
            grouped.setdefault(metric.ticker, []).append(metric)
        return grouped

    @staticmethod
    def _financial_statement_summary(metrics: list[FinancialMetric]) -> dict[str, str]:
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

        revenue = ReportGenerator._metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
            annual_only=True,
        )
        net_income = ReportGenerator._metric_series(
            metrics,
            ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
            statement_types={"income_statement"},
            exclude_keywords=["歸屬", "綜合損益", "稅前"],
            annual_only=True,
        )
        latest_revenue = ReportGenerator._metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
        )
        latest_net_income = ReportGenerator._metric_series(
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
        equity = ReportGenerator._balance_sheet_total_series(
            balance_metrics,
            metric_names={"Equity", "權益總額", "權益總計"},
            origin_names={"權益總額", "權益總計"},
        )
        liabilities = ReportGenerator._balance_sheet_total_series(
            balance_metrics,
            metric_names={"Liabilities", "負債總額", "負債總計"},
            origin_names={"負債總額", "負債總計"},
        )
        operating_cash = ReportGenerator._metric_series(
            metrics,
            ["營業活動", "operating cash"],
            statement_types={"cash_flow"},
            annual_only=True,
        )
        capex = ReportGenerator._metric_series(
            metrics,
            ["投資活動", "capital expenditure", "capex"],
            statement_types={"cash_flow"},
            annual_only=True,
        )
        gross_profit = ReportGenerator._metric_series(
            metrics,
            ["營業毛利", "gross profit"],
            statement_types={"income_statement"},
        )

        revenue_trend = ReportGenerator._series_trend_text(revenue, "營收")
        net_income_trend = ReportGenerator._series_trend_text(net_income, "淨利")
        fcf_trend = ReportGenerator._fcf_trend_text(operating_cash, capex)
        margin_trend = ReportGenerator._margin_text(gross_profit, latest_net_income, latest_revenue)
        debt_trend = ReportGenerator._debt_text(liabilities, equity)
        roe_trend = ReportGenerator._roe_text(net_income, equity)
        strength = ReportGenerator._financial_strength_text(revenue, net_income, liabilities, equity)
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

    @staticmethod
    def _metric_series(
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

    @staticmethod
    def _balance_sheet_total_series(
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

    @staticmethod
    def _series_trend_text(series: dict[int, float], label: str) -> str:
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

    @staticmethod
    def _fcf_trend_text(operating_cash: dict[int, float], capex: dict[int, float]) -> str:
        common_years = sorted(set(operating_cash) & set(capex))
        if len(common_years) < 2:
            return "目前無足夠數據判斷；需補營業現金流與資本支出。"
        fcf = {year: operating_cash[year] + capex[year] for year in common_years}
        return ReportGenerator._series_trend_text(fcf, "自由現金流")

    @staticmethod
    def _margin_text(gross_profit: dict[int, float], net_income: dict[int, float], revenue: dict[int, float]) -> str:
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

    @staticmethod
    def _debt_text(liabilities: dict[int, float], equity: dict[int, float]) -> str:
        common_years = sorted(set(liabilities) & set(equity))
        if not common_years:
            return "目前無足夠數據判斷；需補資產負債表。"
        latest = common_years[-1]
        if equity[latest] == 0:
            return "負債與權益資料存在，但權益為 0，無法計算負債權益比。"
        return f"{latest} 年度{ReportGenerator._debt_equity_phrase(liabilities[latest] / equity[latest])}。"

    @staticmethod
    def _debt_equity_phrase(ratio: float) -> str:
        if ratio > 0 and ratio < 0.01:
            return "負債權益比低於 0.01 倍"
        return f"負債權益比約 {ratio:.2f} 倍"

    @staticmethod
    def _roe_text(net_income: dict[int, float], equity: dict[int, float]) -> str:
        common_years = sorted(set(net_income) & set(equity))
        if not common_years:
            return "目前無足夠數據判斷；需補股東權益與淨利。"
        latest = common_years[-1]
        if equity[latest] == 0:
            return "淨利與權益資料存在，但權益為 0，無法計算 ROE。"
        return f"{latest} 年度 ROE 約 {net_income[latest] / equity[latest] * 100:.2f}%。"

    @staticmethod
    def _financial_strength_text(
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

    @staticmethod
    def _series_growth_pct(series: dict[int, float]) -> float | None:
        if len(series) < 2:
            return None
        years = sorted(series)
        first = series[years[0]]
        last = series[years[-1]]
        if first == 0:
            return None
        return round((last - first) / abs(first) * 100, 2)

    @staticmethod
    def _financial_valuation_assessment(
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> dict:
        metrics = financial_metrics or []
        peer_summary = peer_summary or {}
        upside_score = 0
        risk_score = 0
        strengths: list[str] = []
        cautions: list[str] = []
        red_flags: list[str] = []

        revenue = ReportGenerator._metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
            annual_only=True,
        )
        net_income = ReportGenerator._metric_series(
            metrics,
            ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
            statement_types={"income_statement"},
            exclude_keywords=["歸屬", "綜合損益", "稅前"],
            annual_only=True,
        )
        latest_revenue_series = ReportGenerator._metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
        )
        latest_net_income_series = ReportGenerator._metric_series(
            metrics,
            ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
            statement_types={"income_statement"},
            exclude_keywords=["歸屬", "綜合損益", "稅前"],
        )
        equity = ReportGenerator._balance_sheet_total_series(
            metrics,
            metric_names={"Equity", "權益總額", "權益總計"},
            origin_names={"權益總額", "權益總計"},
        )
        liabilities = ReportGenerator._balance_sheet_total_series(
            metrics,
            metric_names={"Liabilities", "負債總額", "負債總計"},
            origin_names={"負債總額", "負債總計"},
        )

        revenue_growth = ReportGenerator._series_growth_pct(revenue)
        if revenue_growth is not None:
            if revenue_growth >= 30:
                upside_score += 2
                strengths.append(f"已揭露年度營收成長 {revenue_growth:.1f}%")
            elif revenue_growth >= 5:
                upside_score += 1
                strengths.append(f"已揭露年度營收成長 {revenue_growth:.1f}%")
            elif revenue_growth <= -20:
                risk_score += 2
                red_flags.append(f"已揭露年度營收下滑 {abs(revenue_growth):.1f}%")
            elif revenue_growth < 0:
                risk_score += 1
                cautions.append(f"已揭露年度營收小幅下滑 {abs(revenue_growth):.1f}%")
        elif metrics:
            cautions.append("已揭露年度營收趨勢不足")

        net_income_growth = ReportGenerator._series_growth_pct(net_income)
        latest_net_income = latest_net_income_series[max(latest_net_income_series)] if latest_net_income_series else None
        latest_revenue = latest_revenue_series[max(latest_revenue_series)] if latest_revenue_series else None
        if latest_net_income is not None and latest_net_income <= 0:
            risk_score += 3
            red_flags.append("最新財報期間淨利為負或接近虧損")
        elif net_income_growth is not None:
            if net_income_growth >= 20:
                upside_score += 2
                strengths.append(f"已揭露年度淨利成長 {net_income_growth:.1f}%")
            elif net_income_growth > 0:
                upside_score += 1
                strengths.append(f"已揭露年度淨利成長 {net_income_growth:.1f}%")
            elif net_income_growth <= -20:
                risk_score += 2
                red_flags.append(f"已揭露年度淨利下滑 {abs(net_income_growth):.1f}%")
            else:
                risk_score += 1
                cautions.append(f"已揭露年度淨利小幅下滑 {abs(net_income_growth):.1f}%")
        elif metrics:
            cautions.append("已揭露年度淨利趨勢不足")

        if latest_net_income is not None and latest_revenue:
            net_margin = latest_net_income / latest_revenue * 100
            if net_margin >= 15:
                upside_score += 1
                strengths.append(f"最新淨利率約 {net_margin:.1f}%")
            elif net_margin < 0:
                risk_score += 2
                red_flags.append(f"最新淨利率為負 {net_margin:.1f}%")
            elif net_margin < 5:
                risk_score += 1
                cautions.append(f"最新淨利率偏低 {net_margin:.1f}%")

        common_years = sorted(set(liabilities) & set(equity))
        if common_years and equity[common_years[-1]]:
            debt_equity = liabilities[common_years[-1]] / equity[common_years[-1]]
            if debt_equity < 0.8:
                upside_score += 1
                strengths.append(ReportGenerator._debt_equity_phrase(debt_equity))
            elif debt_equity >= 2:
                risk_score += 2
                red_flags.append(f"負債權益比偏高 {debt_equity:.2f} 倍")
            elif debt_equity >= 1.5:
                risk_score += 1
                cautions.append(f"負債權益比略高 {debt_equity:.2f} 倍")
        elif metrics:
            cautions.append("負債權益比不足")

        if latest_net_income is not None and equity:
            latest_equity = equity[max(equity)]
            if latest_equity:
                roe = latest_net_income / latest_equity * 100
                if roe >= 10:
                    upside_score += 1
                    strengths.append(f"ROE 約 {roe:.1f}%")
                elif roe < 0:
                    risk_score += 1
                    red_flags.append(f"ROE 為負 {roe:.1f}%")

        has_negative_profitability = ReportGenerator._has_negative_profitability(metrics)
        valuation_label = ReportGenerator._valuation_position_label(valuation, peer_summary, has_negative_profitability)
        if valuation_label == "獲利為負，不判低估":
            risk_score += 1
            cautions.append("獲利為負或偏弱，低 P/B/P/E 不直接視為低估")
        elif valuation_label == "目前估值低於同業":
            upside_score += 2
            strengths.append(valuation_label)
        elif valuation_label == "目前估值略低":
            upside_score += 1
            strengths.append(valuation_label)
        elif valuation_label == "目前估值略高":
            risk_score += 1
            cautions.append(valuation_label)
        elif valuation_label == "目前估值偏高":
            risk_score += 2
            cautions.append(valuation_label)
        elif not valuation:
            cautions.append("缺估值資料")

        upside_score = min(6, upside_score)
        risk_score = min(6, risk_score)
        red_flag = bool(red_flags) or risk_score >= 4
        return {
            "has_inputs": bool(metrics or valuation),
            "upside_score": upside_score,
            "risk_score": risk_score,
            "red_flag": red_flag,
            "strengths": strengths,
            "cautions": cautions,
            "red_flags": red_flags,
            "upside_summary": "；".join(strengths[:3]) if strengths else "財務/估值未形成明確加分",
            "risk_summary": "；".join((red_flags + cautions)[:3]) if red_flags or cautions else "財務/估值未形成明確風險",
            "summary": "；".join((strengths + red_flags + cautions)[:4]) if strengths or red_flags or cautions else "財務/估值中性",
        }

    @staticmethod
    def _peer_valuation_summary(valuations: list[ValuationMetric]) -> dict[str, float | None]:
        pe_values = [valuation.pe_ratio for valuation in valuations if valuation.pe_ratio is not None and valuation.pe_ratio > 0]
        pb_values = [valuation.pb_ratio for valuation in valuations if valuation.pb_ratio is not None and valuation.pb_ratio > 0]
        return {
            "pe_avg": sum(pe_values) / len(pe_values) if pe_values else None,
            "pb_avg": sum(pb_values) / len(pb_values) if pb_values else None,
            "count": len(valuations),
        }

    @staticmethod
    def _valuation_summary(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        if not valuation:
            return "目前無足夠數據判斷；缺 P/E、P/B 與殖利率資料。"
        pe = f"P/E {valuation.pe_ratio:.2f}" if valuation.pe_ratio is not None else "P/E NA"
        pb = f"P/B {valuation.pb_ratio:.2f}" if valuation.pb_ratio is not None else "P/B NA"
        dividend = (
            f"殖利率 {valuation.dividend_yield:.2f}%"
            if valuation.dividend_yield is not None
            else "殖利率 NA"
        )
        comparison = ReportGenerator._valuation_peer_comparison(valuation, peer_summary or {})
        return f"{valuation.trade_date.isoformat()} {pe}、{pb}、{dividend}。{comparison}"

    @staticmethod
    def _valuation_peer_comparison(
        valuation: ValuationMetric,
        peer_summary: dict[str, float | None],
    ) -> str:
        pe_avg = peer_summary.get("pe_avg")
        pb_avg = peer_summary.get("pb_avg")
        count = int(peer_summary.get("count") or 0)
        if count < 2 or (pe_avg is None and pb_avg is None):
            return "同業樣本不足，無法做相對估值比較。"
        parts = []
        if valuation.pe_ratio is not None and pe_avg:
            level = "高於" if valuation.pe_ratio > pe_avg * 1.1 else "低於" if valuation.pe_ratio < pe_avg * 0.9 else "接近"
            parts.append(f"P/E {level}同業平均 {pe_avg:.2f}")
        if valuation.pb_ratio is not None and pb_avg:
            level = "高於" if valuation.pb_ratio > pb_avg * 1.1 else "低於" if valuation.pb_ratio < pb_avg * 0.9 else "接近"
            parts.append(f"P/B {level}同業平均 {pb_avg:.2f}")
        return "目前相對估值：" + "；".join(parts) + "。"

    @staticmethod
    def _valuation_position_label(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
        has_negative_profitability: bool = False,
    ) -> str:
        if not valuation:
            return "缺估值"
        pe_avg = (peer_summary or {}).get("pe_avg")
        pb_avg = (peer_summary or {}).get("pb_avg")
        pressure = 0
        discount = 0
        if valuation.pe_ratio is not None and pe_avg:
            if valuation.pe_ratio > pe_avg * 1.1:
                pressure += 1
            elif valuation.pe_ratio < pe_avg * 0.9:
                discount += 1
        if valuation.pb_ratio is not None and pb_avg:
            if valuation.pb_ratio > pb_avg * 1.1:
                pressure += 1
            elif valuation.pb_ratio < pb_avg * 0.9:
                discount += 1
        if pressure >= 2:
            return "目前估值偏高"
        if pressure == 1 and discount == 0:
            return "目前估值略高"
        if has_negative_profitability and discount > 0 and pressure == 0:
            return "獲利為負，不判低估"
        if discount >= 2:
            return "目前估值低於同業"
        if discount == 1 and pressure == 0:
            return "目前估值略低"
        return "目前估值接近同業"

    @staticmethod
    def _has_negative_profitability(metrics: list[FinancialMetric]) -> bool:
        revenue = ReportGenerator._metric_series(
            metrics,
            ["營業收入", "revenue"],
            statement_types={"income_statement"},
        )
        net_income = ReportGenerator._metric_series(
            metrics,
            ["本期淨利（淨損）", "本期淨利", "incomeaftertaxes", "netincome"],
            statement_types={"income_statement"},
            exclude_keywords=["歸屬", "綜合損益", "稅前"],
        )
        equity = ReportGenerator._balance_sheet_total_series(
            metrics,
            metric_names={"Equity", "權益總額", "權益總計"},
            origin_names={"權益總額", "權益總計"},
        )
        if not net_income:
            return False
        latest_year = max(net_income)
        latest_net_income = net_income[latest_year]
        if latest_net_income <= 0:
            return True
        latest_revenue = revenue.get(latest_year)
        if latest_revenue and latest_net_income / latest_revenue < 0:
            return True
        latest_equity = equity.get(max(equity)) if equity else None
        return bool(latest_equity and latest_net_income / latest_equity < 0)

    @staticmethod
    def _sanitize_leading_signal_for_profitability(
        signal: LeadingSignal,
        has_negative_profitability: bool,
    ) -> LeadingSignal:
        if not has_negative_profitability or signal.valuation_label != "目前估值低於同業":
            return signal
        bullish_factors = [factor for factor in signal.bullish_factors if factor != "目前估值低於同業"]
        upside_bonus = max(0, signal.upside_bonus - 2)
        return LeadingSignal(
            ticker=signal.ticker,
            score=upside_bonus - signal.downside_penalty,
            upside_bonus=upside_bonus,
            downside_penalty=signal.downside_penalty,
            price_20d_pct=signal.price_20d_pct,
            price_60d_pct=signal.price_60d_pct,
            volume_ratio_20d=signal.volume_ratio_20d,
            revenue_yoy_pct=signal.revenue_yoy_pct,
            revenue_acceleration_pct=signal.revenue_acceleration_pct,
            valuation_label="獲利為負，不判低估",
            bullish_factors=bullish_factors,
            bearish_factors=signal.bearish_factors,
            neutral_factors=signal.neutral_factors,
        )

    @staticmethod
    def _current_price_text(snapshot: MarketSnapshot | None) -> str:
        if not snapshot or snapshot.close is None:
            return "缺股價"
        return f"{snapshot.trade_date.isoformat()} 收盤 {snapshot.close:g}"

    @staticmethod
    def _current_price_label(
        snapshot: MarketSnapshot | None,
        estimate: dict,
        quality: dict,
        valuation_label: str,
        leading_signal: LeadingSignal | None,
        decision: str,
        downside_gate: int,
    ) -> str:
        if not snapshot or snapshot.close is None or "缺股價" in quality.get("missing", []):
            return "股價資料不足"
        downside = int(estimate.get("downside_pct") or 0)
        upside = int(estimate.get("upside_pct") or 0)
        if decision == "避開 / 降低曝險" or downside > upside:
            return "不適合追價"
        if leading_signal and leading_signal.direction == "偏空":
            return "等止跌"
        if downside > downside_gate:
            return "等風險下降"

        price_hot = False
        if leading_signal:
            price_hot = any(
                [
                    leading_signal.price_20d_pct is not None and leading_signal.price_20d_pct >= 8,
                    leading_signal.price_60d_pct is not None and leading_signal.price_60d_pct >= 15,
                    leading_signal.volume_ratio_20d is not None
                    and leading_signal.volume_ratio_20d >= 1.5
                    and leading_signal.price_20d_pct is not None
                    and leading_signal.price_20d_pct > 0,
                ]
            )
        valuation_hot = "偏高" in valuation_label or "略高" in valuation_label
        if decision == "可小額分批研究" and not valuation_hot and not price_hot:
            return "可小額分批"
        if decision == "可小額分批研究":
            return "可研究但勿追高"
        if valuation_hot or price_hot:
            return "等回檔/降溫"
        return "觀察等待"

    @staticmethod
    def _financial_confidence_label(
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        revenue: MonthlyRevenue | None,
    ) -> str:
        score = 0
        if len(financial_metrics) >= 8:
            score += 1
        if len(financial_metrics) >= 40:
            score += 1
        if valuation:
            score += 1
        if revenue:
            score += 1
        if score >= 4:
            return "高"
        if score >= 2:
            return "中"
        return "低"

    @staticmethod
    def _company_matrix_reminder(
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
        valuation_label = ReportGenerator._valuation_position_label(
            valuation,
            peer_summary,
            ReportGenerator._has_negative_profitability(financial_metrics or []),
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

    @staticmethod
    def _valuation_conclusion(
        snapshot: MarketSnapshot | None,
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        market_summary = ReportGenerator._company_market_summary(snapshot)
        if not valuation:
            return f"{market_summary} 但缺 P/E、P/B、DCF 與同業估值資料，因此不能下低估/高估結論。"
        return (
            f"{market_summary} 已有單公司估值：{ReportGenerator._valuation_summary(valuation, peer_summary)}"
            "仍缺 DCF 與完整同業成長率，因此不能單靠倍數判斷低估/高估。"
        )

    @staticmethod
    def _company_market_summary(snapshot: MarketSnapshot | None) -> str:
        if not snapshot:
            return "目前無可驗證股價資料。"
        close = snapshot.close if snapshot.close is not None else "NA"
        return f"{snapshot.trade_date.isoformat()} 收盤價 {close}。"

    @staticmethod
    def _company_risk_summary(related_findings) -> str:
        if not related_findings:
            return "目前無足夠數據判斷。"
        topics = [finding.topic for finding in related_findings[:3]]
        return "、".join(topics)

    @staticmethod
    def _trend_summary(related_documents: list[NewsDocument], related_findings) -> str:
        text = " ".join([document.title for document in related_documents] + [finding.evidence for finding in related_findings])
        if not text:
            return "目前無足夠數據判斷。"
        if any(term in text for term in ["AI", "伺服器", "CoWoS", "HBM", "液冷", "散熱", "成長", "擴產", "需求"]):
            return "現有文本顯示公司與本次主題需求有關，但仍需用訂單、營收與毛利率驗證。"
        return "現有文本不足以判斷明確產業趨勢。"

    @staticmethod
    def _near_term_outlook(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument], related_findings) -> str:
        if related_findings:
            return "短期需優先追蹤風險證據是否擴大，以及月營收是否能支撐題材。"
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 0 and related_documents:
            return "短期具備觀察價值，但仍需確認成長是否延續到獲利與現金流。"
        if related_documents:
            return "短期已有題材文本，但缺少足夠財務驗證。"
        return "目前無足夠數據判斷。"

    @staticmethod
    def _growth_opportunity_text(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
    ) -> str:
        text = " ".join([document.title + " " + document.text[:300] for document in related_documents])
        signals = []
        for keyword in ["擴產", "新平台", "AI", "伺服器", "CoWoS", "HBM", "液冷", "訂單", "產能"]:
            if keyword in text:
                signals.append(keyword)
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
            signals.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
        if related_findings:
            signals.append(f"{len(related_findings)} 筆主題/風險歸因證據")
        if not signals:
            return "目前沒有足夠可驗證訊號，需等待法說會、訂單或營收資料補強。"
        return "可追蹤 " + "、".join(list(dict.fromkeys(signals))[:5]) + " 是否延續到營收、毛利與現金流。"

    @staticmethod
    def _long_term_growth_text(
        financial_summary: dict[str, str],
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
    ) -> str:
        positives = []
        if "成長" in financial_summary.get("revenue_trend", ""):
            positives.append(financial_summary["revenue_trend"])
        if "體質改善" in financial_summary.get("strength", ""):
            positives.append("財務體質呈改善訊號")
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
            positives.append(f"近期月營收年增 {revenue.yoy_pct:.2f}%")
        if len(related_documents) >= 2:
            positives.append(f"{len(related_documents)} 筆公司層級文本支撐主題關聯")
        if not positives:
            return "目前缺少長期成長證據，需補產業規模、資本支出與競爭格局資料。"
        return "；".join(positives[:3]) + "；仍需用 5-10 年產業規模、毛利率與自由現金流假設做二次驗證。"

    @staticmethod
    def _dcf_proxy_text(financial_summary: dict[str, str], valuation: ValuationMetric | None) -> str:
        available = []
        if "自由現金流" in financial_summary.get("fcf_trend", "") and "目前無足夠" not in financial_summary["fcf_trend"]:
            available.append(financial_summary["fcf_trend"])
        if valuation and valuation.pe_ratio is not None:
            available.append(f"目前可用 P/E {valuation.pe_ratio:.2f} 作為相對估值交叉檢查")
        if not available:
            return "尚缺可驗證 FCF 序列、折現率與終值假設，不自動給目標價。"
        return "；".join(available) + "；系統暫不硬算目標價，避免用未驗證假設製造精準幻覺。"

    @staticmethod
    def _industry_average_text(peer_summary: dict[str, float | None]) -> str:
        count = int(peer_summary.get("count") or 0)
        pe_avg = peer_summary.get("pe_avg")
        pb_avg = peer_summary.get("pb_avg")
        if count < 2 or (pe_avg is None and pb_avg is None):
            return "同業樣本不足，需補更多可比公司後再判斷產業平均。"
        parts = [f"同業樣本 {count} 檔"]
        if pe_avg is not None:
            parts.append(f"平均 P/E {pe_avg:.2f}")
        if pb_avg is not None:
            parts.append(f"平均 P/B {pb_avg:.2f}")
        return "、".join(parts) + "。"

    @staticmethod
    def _bull_case(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument]) -> str:
        points = []
        if related_documents:
            points.append(f"有 {len(related_documents)} 筆公司相關文本支持題材關聯")
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 0:
            points.append(f"月營收年增率 {revenue.yoy_pct:.2f}%")
        return "；".join(points) + "。" if points else "目前無足夠數據支持多頭論點。"

    @staticmethod
    def _bear_case(related_findings) -> str:
        if not related_findings:
            return "目前無明確風險證據，但缺少證據不等於沒有風險。"
        return f"已有 {len(related_findings)} 筆風險/機會歸因，需確認是否影響出貨、毛利或估值。"

    @staticmethod
    def _moat_score(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> int:
        score = 3
        if len(related_documents) >= 2:
            score += 1
        if related_findings:
            score += 1
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
            score += 1
        if financial_summary and "體質改善" in financial_summary.get("strength", ""):
            score += 1
        return min(score, 6)

    @staticmethod
    def _moat_reason(
        score: int,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> str:
        reasons = []
        if len(related_documents) >= 2:
            reasons.append(f"{len(related_documents)} 筆公司層級文本")
        if related_findings:
            reasons.append(f"{len(related_findings)} 筆主題/風險歸因證據")
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
            reasons.append(f"月營收年增 {revenue.yoy_pct:.2f}%")
        if financial_summary and "體質改善" in financial_summary.get("strength", ""):
            reasons.append("財務趨勢偏改善")
        if not reasons:
            reasons.append("目前缺少可量化護城河證據")
        caveat = "仍需補客戶集中度、市占、長約、認證週期與專利/技術資料。"
        return f"{'、'.join(reasons)}，因此暫評 {score}/10；{caveat}"

    @staticmethod
    def _moat_factor_text(
        factor: str,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str],
    ) -> str:
        text = " ".join([document.title + " " + document.text[:500] for document in related_documents])
        if factor == "brand":
            if len(related_documents) >= 5:
                return f"公司在本主題下有 {len(related_documents)} 筆可追溯文本，顯示市場辨識度高；仍需市占與客戶結構驗證。"
            if related_documents:
                return f"已有 {len(related_documents)} 筆公司層級文本，但品牌/市占強度仍需更多來源交叉比對。"
        if factor == "network":
            return "硬體與供應鏈公司通常不是典型網路效應，系統不會把題材熱度誤判成網路效應。"
        if factor == "switching_cost":
            if any(keyword in text for keyword in ["認證", "導入", "長約", "客戶", "良率", "供應鏈"]):
                return "文本出現客戶認證、導入或供應鏈關鍵字，可能存在轉換成本；仍需客戶與合約資料確認。"
            return "尚未看到足夠客戶認證或導入週期證據，暫不加分。"
        if factor == "cost":
            if "負債權益比" in financial_summary.get("debt_trend", "") or "利率約" in financial_summary.get("margin_trend", ""):
                return f"可用財報顯示 {financial_summary.get('margin_trend')} {financial_summary.get('debt_trend')}，可作為成本優勢初步檢查。"
            if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 20:
                return f"月營收年增 {revenue.yoy_pct:.2f}% 顯示規模動能，但仍需毛利率驗證成本優勢。"
        if factor == "technology":
            keywords = [keyword for keyword in ["專利", "先進製程", "CoWoS", "HBM", "液冷", "導軌", "ASIC"] if keyword in text]
            if keywords:
                return f"文本出現 {', '.join(keywords[:4])} 等技術/產品關鍵字，可列為技術壁壘候選；仍需官方技術或專利來源驗證。"
        return "目前證據不足，系統保留為待補資料，不自動給護城河加分。"

    @staticmethod
    def _company_rating(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        if not snapshot:
            return "避免"
        if related_findings:
            return "持有/觀察"
        if len(related_documents) >= 2 and revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 10:
            return "持有"
        return "持有/觀察"

    def _render_risk_overview(self, findings) -> str:
        if not findings:
            return "目前無足夠數據判斷。"

        topic_counts = Counter(finding.topic for finding in findings)
        company_counts: Counter[str] = Counter()
        for finding in findings:
            for company in finding.related_companies:
                company_counts[f"{company.ticker} {company.name}"] += 1

        lines = [
            f"- 結構性瓶頸：{sum(1 for finding in findings if finding.risk_type == RiskType.structural_bottleneck)} 筆",
            f"- 短期波動：{sum(1 for finding in findings if finding.risk_type == RiskType.short_term_volatility)} 筆",
            f"- 機會/成長：{sum(1 for finding in findings if finding.risk_type == RiskType.opportunity_or_growth)} 筆",
            "- 主要歸因主題："
            + ("、".join(f"{topic}({count})" for topic, count in topic_counts.most_common(5)) or "目前無足夠數據判斷"),
            "- 受影響公司："
            + ("、".join(f"{company}({count})" for company, count in company_counts.most_common(5)) or "未明確對應公司"),
            "",
            "### 代表性證據",
        ]
        for finding in findings[:8]:
            source_date = finding.source.published_at.isoformat() if finding.source.published_at else "日期不明"
            companies = ", ".join(f"{c.ticker} {c.name}" for c in finding.related_companies) or "未明確對應公司"
            lines.append(
                f"- {finding.topic}：{companies}；來源：{source_date} "
                f"{finding.source.publisher or ''} {finding.source.title}"
            )
        if len(findings) > 8:
            lines.append(f"- 其餘 {len(findings) - 8} 筆歸因證據已保留於系統資料庫，不在主報告逐條展開。")
        return "\n".join(lines)

    def _render_scope(
        self,
        tickers: list[str],
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
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
        lines.extend(["", "### 動態產業鏈白名單", self.whitelist.as_prompt_context()])
        return "\n".join(lines)

    @staticmethod
    def _render_revenue_check(tickers: list[str], monthly_revenues: list[MonthlyRevenue]) -> str:
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

    def _render_appendix(
        self,
        llm_result: LLMResult,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot],
    ) -> str:
        lines = ["### AI 補充分析"]
        if llm_result.fallback:
            lines.append("模型補充分析未啟用；本報告目前改用可追溯來源與資料規則生成，需人工覆核。")
        else:
            lines.append(
                LLMSupplementValidator.render_markdown(
                    llm_result.text,
                    documents,
                    market_snapshots,
                )
            )

        lines.extend(["", "### 資料來源與時間戳記"])
        if documents:
            for document in documents[:40]:
                source_date = (
                    document.source.published_at.isoformat() if document.source.published_at else "日期不明"
                )
                lines.append(f"- {source_date} {document.source.publisher or ''} {document.title}")
            if len(documents) > 40:
                lines.append(f"- 其餘 {len(documents) - 40} 筆來源已存入資料庫，本報告僅列前 40 筆。")
        else:
            lines.append("- 目前無足夠數據判斷。")

        lines.extend(["", "### 模型狀態", self._model_status(llm_result)])
        return "\n".join(lines)

    @staticmethod
    def _is_international_source(document: NewsDocument) -> bool:
        publisher = (document.source.publisher or "").lower()
        title = document.title.lower()
        url = (document.source.url or "").lower()
        international_markers = [
            "nvidia",
            "trendforce",
            "reuters",
            "bloomberg",
            "cnbc",
            "the information",
            "semianalysis",
            "center for a new american",
            "bessemer",
            "astute",
            "designnews",
            "wsj",
            "financial times",
            "ft.com",
        ]
        haystack = f"{publisher} {title} {url}"
        if any(marker in haystack for marker in international_markers):
            return True
        return "hl=en" in url or "ceid=us:en" in url

    def _document_matches(self, document: NewsDocument) -> list:
        cache = getattr(self, "_document_match_cache", None)
        if cache is None:
            cache = {}
            self._document_match_cache = cache
        key = (
            document.id or "",
            document.source.url or "",
            document.title,
            len(document.text or ""),
        )
        if key not in cache:
            cache[key] = self.mapper.match_document(document)
        return cache[key]

    def _related_documents(self, ticker: str, documents: list[NewsDocument]) -> list[NewsDocument]:
        return [
            document
            for document in documents
            if any(match.ticker == ticker for match in self._document_matches(document))
        ]

    def _candidate_audit_evidence_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for candidate in self.whitelist.candidate_audit():
            ticker = str(candidate.get("ticker") or "")
            if not ticker:
                continue
            counts[ticker] = {
                "evidence_count": int(candidate.get("evidence_count") or 0),
                "source_count": int(candidate.get("evidence_source_count") or 0),
            }
        return counts

    @staticmethod
    def _publisher_count(documents: list[NewsDocument]) -> int:
        return len(
            {
                document.source.publisher or document.source.url or document.title
                for document in documents
            }
        )

    def _render_beginner_portfolio_plan(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
        leading_signals: dict[str, LeadingSignal] | None = None,
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        capital = request.investor_capital
        reserve = int(capital * request.cash_reserve_pct)
        deployable = capital - reserve
        max_position = self._max_position_amount(request)
        first_tranche = int(max_position * self._first_tranche_ratio(request))
        downside_gate = self._downside_gate(request)
        contexts = self._sort_decision_contexts(
            self._decision_contexts(
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

        candidate_rows = []
        allocation_candidates = []
        avoid_rows = []
        watch_rows = []
        for context in contexts:
            label = context["label"]
            snapshot = context.get("snapshot")
            revenue = context.get("revenue")
            related_documents = context.get("documents") or []
            related_findings = context.get("findings") or []
            signal = context.get("leading_signal")
            estimate = context["estimate"]
            decision = context["decision"]
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source}"
            reason = self._decision_reason(
                decision,
                estimate,
                context["quality"],
                related_findings,
                related_documents,
                downside_gate,
                request,
                signal,
            )

            if decision == "可小額分批研究":
                allocation_candidates.append(
                    {
                        "label": label,
                        "upside_pct": estimate["upside_pct"],
                        "downside_pct": estimate["downside_pct"],
                        "source": source,
                    }
                )
                candidate_rows.append(
                    f"- {label}：可列小額分批研究。首筆約 {first_tranche:,} 元，"
                    f"單檔上限約 {max_position:,} 元；目前情境升值分 {estimate['upside_pct']} 分，"
                    f"目前情境降值分 {estimate['downside_pct']} 分。原因：{reason}來源：{source}。"
                )
            elif decision == "避開 / 降低曝險":
                avoid_rows.append(
                    f"- {label}：避開或降低曝險。原因：目前情境降值分 {estimate['downside_pct']} 分，"
                    f"目前情境升值分 {estimate['upside_pct']} 分；{reason}來源：{source}。"
                )
            else:
                watch_rows.append(
                    f"- {label}：{decision}。原因：{reason}來源：{source}。"
                )

        lines = [
            f"資金設定：總資金 {capital:,} 元以內；建議保留現金約 {reserve:,} 元，"
            f"本輪可投入資金上限約 {deployable:,} 元。",
            f"投資人設定：{self._profile_label(request)}；單檔部位上限 {request.max_position_pct:.0%}，"
            f"首筆試單約單檔上限的 {self._first_tranche_ratio(request):.0%}，"
            f"目前情境降值觀察門檻 {downside_gate} 分。",
            "原則：先控風險再追報酬；同一題材不宜一次滿倉，且資料不足時不進入可研究名單。",
        ]
        lines.extend(["", "### 首筆配置草案"])
        lines.extend(
            self._render_allocation_plan(
                allocation_candidates,
                deployable,
                first_tranche,
            )
        )
        lines.extend(["", "### 可小額分批研究"])
        lines.extend(candidate_rows or ["目前沒有同時通過資料完整度、風險門檻與投資理由一致性檢查的標的。"])
        lines.extend(["", "### 避開 / 降低曝險"])
        lines.extend(avoid_rows or ["目前無明確高風險名單。"])
        lines.extend(["", "### 觀察名單"])
        lines.extend(watch_rows or ["目前無觀察名單。"])
        return "\n".join(lines)

    @staticmethod
    def _render_allocation_plan(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[str]:
        if not candidates:
            return ["目前無可配置標的。"]
        weights = []
        for candidate in candidates:
            score = max(1, candidate["upside_pct"] - candidate["downside_pct"])
            weights.append(score)
        total_weight = sum(weights)
        budget = min(deployable, first_tranche * len(candidates))
        amounts = []
        remaining_budget = budget
        remaining_weight = total_weight
        for index, weight in enumerate(weights):
            if index == len(weights) - 1:
                amount = min(first_tranche, remaining_budget)
            else:
                raw_amount = int(remaining_budget * weight / remaining_weight)
                amount = min(first_tranche, max(0, raw_amount))
                amount = ReportGenerator._round_lot_amount(amount)
                if amount > remaining_budget:
                    amount = ReportGenerator._round_down_lot_amount(remaining_budget)
            amounts.append(amount)
            remaining_budget -= amount
            remaining_weight -= weight

        rows = []
        allocated_total = sum(amounts)
        for candidate, amount in zip(candidates, amounts):
            rows.append(
                f"- {candidate['label']}：首筆配置約 {amount:,} 元；"
                f"依目前情境升值分 {candidate['upside_pct']} / 降值分 {candidate['downside_pct']} 權重分配。"
            )
        rows.insert(0, f"本輪首筆配置合計約 {allocated_total:,} 元；可投入上限 {deployable:,} 元。")
        return rows

    @staticmethod
    def _round_lot_amount(amount: int) -> int:
        if amount <= 0:
            return 0
        return max(10_000, round(amount / 10_000) * 10_000)

    @staticmethod
    def _round_down_lot_amount(amount: int) -> int:
        if amount <= 0:
            return 0
        return max(10_000, (amount // 10_000) * 10_000)

    @staticmethod
    def _max_position_amount(request: ReportRequest) -> int:
        capital = request.investor_capital
        deployable = capital * (1 - request.cash_reserve_pct)
        return int(min(capital * request.max_position_pct, deployable * 0.25))

    @staticmethod
    def _profile(request: ReportRequest) -> InvestorProfile:
        if request.investor_profile != InvestorProfile.beginner:
            return request.investor_profile
        if not request.beginner_mode and request.investor_profile == InvestorProfile.beginner:
            return InvestorProfile.balanced
        return InvestorProfile.beginner

    @staticmethod
    def _profile_label(request: ReportRequest) -> str:
        labels = {
            InvestorProfile.beginner: "新手保守",
            InvestorProfile.balanced: "一般穩健",
            InvestorProfile.aggressive: "積極成長",
        }
        return labels[ReportGenerator._profile(request)]

    @staticmethod
    def _downside_gate(request: ReportRequest) -> int:
        gates = {
            InvestorProfile.beginner: 5,
            InvestorProfile.balanced: 8,
            InvestorProfile.aggressive: 12,
        }
        return gates[ReportGenerator._profile(request)]

    @staticmethod
    def _first_tranche_ratio(request: ReportRequest) -> float:
        ratios = {
            InvestorProfile.beginner: 0.30,
            InvestorProfile.balanced: 0.40,
            InvestorProfile.aggressive: 0.50,
        }
        return ratios[ReportGenerator._profile(request)]

    @staticmethod
    def _risk_warning_reason(estimate: dict) -> str:
        financial = estimate.get("financial_assessment") or {}
        if financial.get("red_flag") and int(financial.get("risk_score") or 0) >= 5:
            return "財務/估值紅旗偏重：" + financial.get("risk_summary", "需先覆核基本面風險") + "。"
        if estimate["downside_pct"] > estimate["upside_pct"]:
            return "目前情境降值分高於升值分，風險權重已壓過投資理由，不適合追價。"
        return "財務或估值紅旗偏重，需先等基本面修復或補充來源驗證。"

    @staticmethod
    def _related_findings(ticker: str, findings) -> list:
        related = []
        seen: set[tuple[str, str, str, str]] = set()
        for finding in findings:
            if not any(match.ticker == ticker for match in finding.related_companies):
                continue
            key = (
                str(finding.risk_type),
                finding.topic,
                finding.source.title,
                finding.source.publisher or "",
            )
            if key in seen:
                continue
            seen.add(key)
            related.append(finding)
        return related

    def _company_filing_missing(self, ticker: str, documents: list[NewsDocument]) -> list[str]:
        companies = {company.ticker: company for company in self.whitelist.companies()}
        company = companies.get(ticker)
        company_name = company.name if company else ""
        high_quality_types: set[str] = set()

        for document in self._company_filing_documents_from_db(ticker):
            if filing_quality_score(document, ticker, company_name) >= 70:
                high_quality_types.add(document.document_type)

        for document in documents:
            if not self._is_company_filing_document(ticker, document):
                continue
            document_type = self._news_document_filing_type(document)
            if document_type and filing_quality_score(document, ticker, company_name) >= 70:
                high_quality_types.add(document_type)

        missing_required = [
            document_type for document_type in REQUIRED_CORE_DOCUMENT_TYPES if document_type not in high_quality_types
        ]
        if not missing_required:
            return []
        return ["缺公司公開文件（" + "、".join(self._filing_type_label(item) for item in missing_required) + "）"]

    @staticmethod
    def _filing_type_label(document_type: str) -> str:
        labels = {
            "annual_report": "年報",
            "investor_presentation": "法說會簡報",
            "prospectus": "公開說明書",
            "material_information": "重大訊息",
            "company_disclosure": "公司公告",
        }
        return labels.get(document_type, document_type)

    @staticmethod
    def _company_filing_documents_from_db(ticker: str):
        try:
            with session_scope() as session:
                return CompanyFilingRepository(session).latest_by_tickers([ticker], limit_per_ticker=8)
        except Exception:
            return []

    @staticmethod
    def _is_company_filing_document(ticker: str, document: NewsDocument) -> bool:
        return company_filing_owner_ticker(document) == ticker

    @staticmethod
    def _news_document_filing_type(document: NewsDocument) -> str | None:
        for line in document.text.splitlines():
            if line.startswith("文件類型："):
                return line.split("：", 1)[1].strip()
        return None

    @staticmethod
    def _data_quality_grade(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        include_fundamentals: bool = False,
        leading_signal: LeadingSignal | None = None,
        company_filing_missing: list[str] | None = None,
    ) -> dict:
        missing = []
        has_company_filing = (
            include_fundamentals
            and company_filing_missing is not None
            and not company_filing_missing
        )
        has_topic_attribution = bool(related_findings) or has_company_filing or len(related_documents) >= 2
        if len(related_documents) < 2 and not has_company_filing:
            missing.append("公司文本不足")
        if not has_topic_attribution:
            missing.append("缺主題歸因")
        if not snapshot:
            missing.append("缺股價")
        if not monthly_revenue:
            missing.append("缺月營收")
        if include_fundamentals and not financial_metrics:
            missing.append("缺已揭露年度財報")
        if include_fundamentals and not valuation:
            missing.append("缺估值")
        if include_fundamentals and leading_signal is not None and not leading_signal.has_signal_data:
            missing.append("缺近況訊號")
        if include_fundamentals:
            missing.extend(company_filing_missing or [])

        if not missing:
            grade = "supported"
        elif snapshot and monthly_revenue and financial_metrics and valuation:
            grade = "partial"
        else:
            grade = "weak"
        return {"grade": grade, "missing": missing}

    @staticmethod
    def _score_data_note(
        confidence_notes: list[str],
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
    ) -> str:
        notes = list(confidence_notes)
        if financial_metrics:
            notes.append(f"財報 {len(financial_metrics)} 筆")
        else:
            notes.append("缺財報")
        if valuation:
            notes.append(f"估值 {valuation.trade_date.isoformat()}")
        else:
            notes.append("缺估值")
        return "；".join(notes) if notes else "完整"

    @staticmethod
    def _quality_label(grade: str) -> str:
        labels = {
            "supported": "完整",
            "partial": "待補",
            "weak": "不足",
        }
        return labels.get(grade, grade)

    @staticmethod
    def _decision_label(
        estimate: dict,
        quality: dict,
        related_findings,
        downside_gate: int,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        if "缺股價" in quality["missing"]:
            return "資料不足"
        if estimate["downside_pct"] > estimate["upside_pct"]:
            return "避開 / 降低曝險"
        financial = estimate.get("financial_assessment") or {}
        if financial.get("red_flag") and int(financial.get("risk_score") or 0) >= 5:
            return "避開 / 降低曝險"
        if estimate["downside_pct"] > downside_gate:
            return "觀察 / 等風險降低"
        if leading_signal and leading_signal.direction == "偏空":
            return "觀察 / 等風險降低"
        if financial.get("red_flag"):
            return "觀察 / 等風險降低"
        if any(finding.risk_type == RiskType.insufficient_data for finding in related_findings):
            return "觀察 / 資料待補"
        if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
            return "觀察 / 等風險降低"
        if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
            return "觀察"
        if estimate["upside_pct"] > 10 and quality["grade"] != "supported":
            return "觀察 / 資料待補"
        if estimate["upside_pct"] > 10:
            return "可小額分批研究"
        if quality["grade"] == "weak":
            return "觀察 / 資料不足"
        return "觀察"

    @staticmethod
    def _decision_reason(
        rating: str,
        estimate: dict,
        quality: dict,
        related_findings,
        related_documents: list[NewsDocument],
        downside_gate: int,
        request: ReportRequest,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        if rating == "資料不足":
            return "缺少可驗證市場資料。"
        if rating == "避開 / 降低曝險":
            return ReportGenerator._risk_warning_reason(estimate)
        if rating == "觀察 / 等風險降低":
            financial = estimate.get("financial_assessment") or {}
            if financial.get("red_flag"):
                return (
                    "財務/估值紅旗尚未解除："
                    f"{financial.get('risk_summary', '需補財務與估值覆核')}；即使題材分數較高，也先列觀察。"
                )
            if leading_signal and leading_signal.direction == "偏空":
                return (
                    f"近況訊號偏空（{leading_signal.summary}），"
                    "先等量價、營收或估值訊號修復。"
                )
            if estimate.get("downside_pct", 0) > downside_gate:
                return (
                    f"目前情境降值分 {estimate['downside_pct']} 分已超過 {downside_gate} 分，"
                    f"依{ReportGenerator._profile_label(request)}設定先列觀察。"
                )
            if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
                return ReportGenerator._structural_bottleneck_reason(related_findings)
            return "目前仍有風險條件未完全通過，先等新資料確認。"
        if rating == "觀察":
            if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
                return "主要證據偏短期波動，需追蹤後續訂單、庫存與出貨變化。"
            if related_documents:
                return "已有公司相關文本證據，但尚未形成足夠的目前情境升值/降值差距。"
            return "目前情境升值/降值差距不足，先觀察。"
        if rating == "觀察 / 資料待補":
            if any(finding.risk_type == RiskType.insufficient_data for finding in related_findings):
                return "模型或來源判定資料仍不足；補齊公司層級來源、財報與估值後再重新評估。"
            return "目前情境升值分高於 10，但資料層尚未完整；" + "、".join(quality["missing"]) + "。"
        if rating == "可小額分批研究":
            return (
                f"目前情境升值分高於 10 分，情境降值分未超過 {downside_gate} 分設定門檻，"
                "資料層完整，且未偵測到財務/估值紅旗。"
            )
        return "目前只有單日價量資料，缺少新聞、財報或法說證據支撐投資結論。"

    @staticmethod
    def _structural_bottleneck_reason(related_findings) -> str:
        bottlenecks = [
            finding for finding in related_findings if finding.risk_type == RiskType.structural_bottleneck
        ]
        if not bottlenecks:
            return "瓶頸或限制證據尚未釐清，先等待風險緩解，不列入本次配置。"

        evidence_labels = []
        seen: set[str] = set()
        for finding in bottlenecks:
            evidence = ReportGenerator._compact_text(
                finding.evidence or finding.topic or finding.source.title,
                max_chars=64,
            )
            if not evidence or evidence in seen:
                continue
            seen.add(evidence)
            source_parts = []
            if finding.source.published_at:
                source_parts.append(finding.source.published_at.isoformat())
            if finding.source.publisher:
                source_parts.append(finding.source.publisher)
            source_label = " ".join(source_parts)
            evidence_labels.append(f"{evidence}（{source_label}）" if source_label else evidence)
            if len(evidence_labels) >= 2:
                break

        if not evidence_labels:
            evidence_labels.append("來源指出供給、產能、技術轉換或成本限制仍需追蹤")
        return "瓶頸/限制證據：" + "；".join(evidence_labels) + "。先等待公司文件、月營收或法說確認風險緩解，不列入本次配置。"

    @staticmethod
    def _compact_text(value: object, max_chars: int = 80) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 3)].rstrip() + "..."

    @staticmethod
    def _table_cell(value: object) -> str:
        return " ".join(str(value or "").split()).replace("|", "\\|")

    @staticmethod
    def _table_row(cells: list[object]) -> str:
        return "| " + " | ".join(ReportGenerator._table_cell(cell) for cell in cells) + " |"

    @staticmethod
    def _estimate_potential(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
        leading_signal: LeadingSignal | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        peer_valuation_summary: dict[str, float | None] | None = None,
    ) -> dict:
        if not snapshot:
            return {
                "upside_pct": 0,
                "downside_pct": 0,
                "upside_reason": "缺少市場資料。",
                "downside_reason": "缺少市場資料。",
                "upside_factors": [],
                "downside_factors": [],
                "confidence_notes": ["缺少市場資料"],
                "evidence_grade": "weak",
                "early_potential_score": 0,
                "attention_label": "未評估",
                "attention_document_count": len(related_documents),
                "attention_publisher_count": 0,
                "early_potential_reason": "缺少市場資料，不能判斷是否為早期潛力股。",
                "financial_assessment": ReportGenerator._financial_valuation_assessment(
                    financial_metrics,
                    valuation,
                    peer_valuation_summary,
                ),
                "financial_red_flag": False,
            }

        text = "\n".join([document.title for document in related_documents] + [finding.evidence for finding in related_findings])
        text = "\n".join(
            [ReportGenerator._scoring_text_for_document(document) for document in related_documents]
            + [finding.evidence for finding in related_findings]
        )
        positive_keywords = ["成長", "大單", "擴產", "需求", "受惠", "看好", "上調", "旺", "爆發", "滿載"]
        negative_keywords = ["下滑", "重摔", "毛利", "禁令", "制裁", "缺電", "產能不足", "吃緊", "延遲", "鬆動"]
        positive_hits = sum(1 for keyword in positive_keywords if keyword in text)
        negative_hits = sum(1 for keyword in negative_keywords if keyword in text)
        structural_findings = sum(
            1 for finding in related_findings if finding.risk_type == RiskType.structural_bottleneck
        )
        volatility_findings = sum(
            1 for finding in related_findings if finding.risk_type == RiskType.short_term_volatility
        )
        opportunity_findings = sum(
            1 for finding in related_findings if finding.risk_type == RiskType.opportunity_or_growth
        )

        upside_pct = 0
        downside_pct = 0
        upside_factors: list[tuple[str, int]] = []
        downside_factors: list[tuple[str, int]] = []
        confidence_notes: list[str] = []
        if len(related_documents) >= 2 and (positive_hits >= 1 or opportunity_findings):
            evidence_score = min(15, positive_hits * 2 + opportunity_findings * 3 + max(0, len(related_documents) - 2))
            upside_pct = 10 + evidence_score
            upside_factors.append(
                (
                    f"公司相關文本 {len(related_documents)} 筆、正向關鍵證據 {positive_hits} 項、機會歸因 {opportunity_findings} 筆",
                    evidence_score,
                )
            )
        if negative_hits >= 1 or structural_findings or volatility_findings:
            risk_score = min(15, negative_hits * 2 + structural_findings * 2 + volatility_findings)
            downside_pct = 5 + risk_score
            downside_factors.append(
                (
                    f"負向字詞 {negative_hits} 項、結構性瓶頸 {structural_findings} 筆、短期波動 {volatility_findings} 筆",
                    risk_score,
                )
            )

        revenue_upside_bonus = 0
        revenue_downside_penalty = 0
        if monthly_revenue and monthly_revenue.yoy_pct is not None:
            if monthly_revenue.yoy_pct >= 10:
                revenue_upside_bonus = min(5, max(2, int(monthly_revenue.yoy_pct // 10)))
                upside_pct = max(11, upside_pct) + revenue_upside_bonus
                upside_factors.append((f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", revenue_upside_bonus))
            elif monthly_revenue.yoy_pct < 0:
                revenue_downside_penalty = min(6, max(2, int(abs(monthly_revenue.yoy_pct) // 5)))
                downside_pct = max(6, downside_pct) + revenue_downside_penalty
                downside_factors.append((f"月營收年增率 {monthly_revenue.yoy_pct:.2f}%", revenue_downside_penalty))
        elif monthly_revenue:
            confidence_notes.append("月營收缺去年同期比較")
        else:
            confidence_notes.append("缺少月營收資料")

        if leading_signal:
            if leading_signal.upside_bonus:
                upside_pct = max(11, upside_pct) + leading_signal.upside_bonus
                upside_factors.append((f"近況訊號偏多：{leading_signal.summary}", leading_signal.upside_bonus))
            if leading_signal.downside_penalty:
                downside_pct = max(6, downside_pct) + leading_signal.downside_penalty
                downside_factors.append((f"近況訊號偏空：{leading_signal.summary}", leading_signal.downside_penalty))
            confidence_notes.append(f"近況訊號 {leading_signal.direction}（分數 {leading_signal.score}）")
        else:
            confidence_notes.append("缺少近況訊號")

        financial_assessment = ReportGenerator._financial_valuation_assessment(
            financial_metrics,
            valuation,
            peer_valuation_summary,
        )
        if financial_assessment["upside_score"]:
            upside_pct = max(11, upside_pct) + financial_assessment["upside_score"]
            upside_factors.append(
                (
                    f"財務/估值加分：{financial_assessment['upside_summary']}",
                    financial_assessment["upside_score"],
                )
            )
        if financial_assessment["risk_score"]:
            downside_pct = max(6, downside_pct) + financial_assessment["risk_score"]
            downside_factors.append(
                (
                    f"財務/估值風險：{financial_assessment['risk_summary']}",
                    financial_assessment["risk_score"],
                )
            )
        if financial_assessment["has_inputs"]:
            confidence_notes.append("財務/估值檢查：" + financial_assessment["summary"])

        if len(related_documents) < 2:
            confidence_notes.append(f"公司相關文本僅 {len(related_documents)} 筆")
        if not related_findings:
            confidence_notes.append("無模型驗證後風險/機會證據")
        quality = ReportGenerator._data_quality_grade(
            related_documents,
            related_findings,
            snapshot,
            monthly_revenue,
        )

        return {
            "upside_pct": upside_pct,
            "downside_pct": downside_pct,
            "upside_reason": (
                f"有 {len(related_documents)} 筆公司相關文本，正向關鍵證據 {positive_hits} 項、機會歸因 {opportunity_findings} 筆"
                f"{ReportGenerator._revenue_reason(monthly_revenue, revenue_upside_bonus, True)}"
                f"{ReportGenerator._leading_signal_reason(leading_signal, True)}"
                f"{ReportGenerator._financial_assessment_reason(financial_assessment, True)}。"
                if upside_pct
                else "正向證據未達 >10 分情境門檻。"
            ),
            "downside_reason": (
                f"偵測到負向/瓶頸證據 {negative_hits + structural_findings + volatility_findings} 項"
                f"{ReportGenerator._revenue_reason(monthly_revenue, revenue_downside_penalty, False)}"
                f"{ReportGenerator._leading_signal_reason(leading_signal, False)}"
                f"{ReportGenerator._financial_assessment_reason(financial_assessment, False)}。"
                if downside_pct
                else "風險證據未達 >5 分情境門檻。"
            ),
            "upside_factors": upside_factors,
            "downside_factors": downside_factors,
            "confidence_notes": confidence_notes,
            "evidence_grade": quality["grade"],
            "financial_assessment": financial_assessment,
            "financial_red_flag": financial_assessment["red_flag"],
            **ReportGenerator._early_potential_profile(
                related_documents,
                monthly_revenue,
                leading_signal,
                upside_pct,
                downside_pct,
                snapshot,
            ),
        }

    @staticmethod
    def _early_potential_profile(
        related_documents: list[NewsDocument],
        monthly_revenue: MonthlyRevenue | None,
        leading_signal: LeadingSignal | None,
        upside_pct: int,
        downside_pct: int,
        snapshot: MarketSnapshot | None = None,
        document_count_override: int | None = None,
        publisher_count_override: int | None = None,
    ) -> dict:
        document_count = (
            document_count_override if document_count_override is not None else len(related_documents)
        )
        publisher_count = (
            publisher_count_override
            if publisher_count_override is not None
            else len({document.source.publisher or document.source.url or document.title for document in related_documents})
        )
        trading_money = snapshot.trading_money if snapshot else None
        if trading_money is not None and trading_money >= 1_000_000_000:
            attention_label = "截至目前成交熱度高"
            attention_bonus = -4
        elif document_count <= 3 and publisher_count <= 2:
            attention_label = "報導較少"
            attention_bonus = 10
        elif document_count <= 8 and publisher_count <= 5:
            attention_label = "報導偏少"
            attention_bonus = 6
        elif document_count <= 15:
            attention_label = "截至目前已有報導"
            attention_bonus = 2
        else:
            attention_label = "截至目前大量報導"
            attention_bonus = -4

        signal_bonus = 0
        reasons = [f"公司文本 {document_count} 筆 / {publisher_count} 來源"]
        if monthly_revenue and monthly_revenue.yoy_pct is not None and monthly_revenue.yoy_pct >= 20:
            signal_bonus += 6
            reasons.append(f"月營收年增 {monthly_revenue.yoy_pct:.1f}%")
        if monthly_revenue and monthly_revenue.yoy_pct is not None and monthly_revenue.yoy_pct >= 10:
            signal_bonus += 3
        if leading_signal and leading_signal.upside_bonus >= 5:
            signal_bonus += 6
            reasons.append(f"近況訊號 {leading_signal.direction}：{leading_signal.summary}")
        elif leading_signal and leading_signal.upside_bonus > 0:
            signal_bonus += 3
            reasons.append(f"近況訊號 {leading_signal.direction}")
        if downside_pct > 12:
            signal_bonus -= 8
            reasons.append("目前情境降值分偏高，需等待風險下降")
        elif downside_pct > 5:
            signal_bonus -= 3
            reasons.append("仍有風險訊號")

        score = max(0, min(30, attention_bonus + signal_bonus + max(0, upside_pct - 10) // 3))
        if attention_label == "截至目前成交熱度高":
            reason = "截至目前成交金額偏高，較不像尚未被市場注意的冷門線索。"
        elif attention_label == "截至目前大量報導":
            reason = "截至目前題材已被大量報導，較不像尚未被市場發現。"
        else:
            reason = "；".join(reasons)
        return {
            "early_potential_score": score,
            "attention_label": attention_label,
            "attention_document_count": document_count,
            "attention_publisher_count": publisher_count,
            "early_potential_reason": reason,
        }

    @staticmethod
    def _format_factors(factors: list[tuple[str, int]]) -> str:
        if not factors:
            return "未觸發"
        return "、".join(f"{label} +{score}" for label, score in factors)

    @staticmethod
    def _revenue_reason(
        monthly_revenue: MonthlyRevenue | None,
        score_delta: int,
        positive: bool,
    ) -> str:
        if not monthly_revenue or monthly_revenue.yoy_pct is None:
            return ""
        direction = "正向加分" if positive else "風險加分"
        if score_delta <= 0:
            return f"，月營收年增率 {monthly_revenue.yoy_pct:.2f}% 未觸發{direction}"
        return f"，月營收年增率 {monthly_revenue.yoy_pct:.2f}% 觸發{direction} {score_delta} 點"

    @staticmethod
    def _leading_signal_reason(leading_signal: LeadingSignal | None, positive: bool) -> str:
        if not leading_signal:
            return ""
        score = leading_signal.upside_bonus if positive else leading_signal.downside_penalty
        if score <= 0:
            return ""
        direction = "正向加分" if positive else "風險加分"
        return f"，近況訊號{leading_signal.direction}觸發{direction} {score} 點"

    @staticmethod
    def _financial_assessment_reason(assessment: dict, positive: bool) -> str:
        if not assessment or not assessment.get("has_inputs"):
            return ""
        score_key = "upside_score" if positive else "risk_score"
        score = int(assessment.get(score_key) or 0)
        if score <= 0:
            return ""
        label = assessment.get("upside_summary" if positive else "risk_summary")
        direction = "正向加分" if positive else "風險加分"
        return f"，財務/估值{direction} {score} 點（{label}）"

    @staticmethod
    def _scoring_text_for_document(document: NewsDocument) -> str:
        if document.id.startswith("filing-"):
            return document.title
        return f"{document.title}\n{document.text[:1200]}"

    @staticmethod
    def _summary(findings) -> str:
        if not findings:
            return "目前檢索證據不足，無法判斷 AI 產業鏈主要瓶頸。"
        structural_count = sum(1 for finding in findings if finding.risk_type == RiskType.structural_bottleneck)
        volatility_count = sum(1 for finding in findings if finding.risk_type == RiskType.short_term_volatility)
        opportunity_count = sum(1 for finding in findings if finding.risk_type == RiskType.opportunity_or_growth)
        return f"本次檢出 {structural_count} 項結構性瓶頸、{volatility_count} 項短期波動、{opportunity_count} 項機會/成長歸因。"

    @staticmethod
    def _format_evidence(documents: list[NewsDocument]) -> str:
        if not documents:
            return "目前無足夠數據判斷。"
        return "\n".join(
            f"- {doc.source.published_at or '日期不明'} {doc.source.publisher or ''} {doc.title}: {doc.text[:500]}"
            for doc in documents
        )

    @staticmethod
    def _format_llm_evidence(documents: list[NewsDocument]) -> str:
        if not documents:
            return "目前無足夠數據判斷。"
        selected = documents[:MAX_LLM_EVIDENCE_DOCUMENTS]
        lines = [
            "以下為供模型補充分析用的截斷證據摘要；正式報告仍會使用完整資料庫、財報與估值規則交叉檢查。"
        ]
        for doc in selected:
            text = " ".join(doc.text.split())[:MAX_LLM_EVIDENCE_TEXT_CHARS]
            source_date = doc.source.published_at or "日期不明"
            lines.append(f"- {source_date} {doc.source.publisher or ''} {doc.title}: {text}")
        omitted = len(documents) - len(selected)
        if omitted > 0:
            lines.append(f"- 其餘 {omitted} 筆來源保留於系統資料庫，未放入模型提示以避免逾時。")
        return "\n".join(lines)

    @staticmethod
    def _format_market_data(
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

    @staticmethod
    def _model_status(result: LLMResult) -> str:
        if result.fallback:
            return result.text
        return f"Gemini 已啟用；model={result.model}；key_pool_index={result.key_index}"
