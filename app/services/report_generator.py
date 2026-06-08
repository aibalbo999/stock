from __future__ import annotations

from collections.abc import Callable

from app.data_sources.company_filing_discovery import REQUIRED_CORE_DOCUMENT_TYPES, filing_quality_score
from app.core.time import format_taipei, now_taipei
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
from app.services.llm_client import LLMClient, LLMResult, summarize_llm_attempts
from app.services.llm_analysis import LLMSupplementValidator
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.persistence import (
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.report_financial_narrative import (
    balance_sheet_total_series,
    debt_equity_phrase,
    debt_text,
    fcf_trend_text,
    financial_statement_summary,
    financial_strength_text,
    margin_text,
    metric_series,
    roe_text,
    series_trend_text,
)
from app.services.report_financial_assessment import (
    decline_risk_points,
    financial_valuation_assessment,
    has_negative_profitability,
    peer_valuation_summary,
    series_growth_pct,
    series_period_text,
    valuation_position_label,
)
from app.services.report_integrity import ReportIntegrityError, assert_report_integrity
from app.services.report_prompt_builder import (
    build_report_prompt,
    format_llm_evidence,
    format_market_data,
)
from app.services import (
    report_action_checklist,
    report_appendix,
    report_allocation,
    report_beginner_portfolio,
    report_company_analysis,
    report_company_narrative,
    report_company_matrix,
    report_data_quality,
    report_credibility_check,
    report_decision_narrative,
    report_decision_rules,
    report_document_matching,
    report_early_potential,
    report_evidence_retrieval,
    report_executive_snapshot,
    report_final_potential,
    report_formatting,
    report_leading_signal,
    report_investment_thesis,
    report_investment_recommendations,
    report_markdown_sections,
    report_monitoring_checklist,
    report_potential,
    report_risk_overview,
    report_scope_sections,
    report_score_breakdown,
    report_source_coverage,
)
from app.services.report_source_references import (
    downside_source_references,
    ordered_source_documents,
    representative_sources,
    source_reference_line,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_document,
    remove_low_quality_investor_forum_lines,
)
from app.services.whitelist import SupplyChainWhitelist


REPORT_READING_SORT_NOTE = (
    "排序：先依判斷結果分組（可研究、觀察、待補、避開），"
    "同組再依最新可取得收盤價由高到低；缺股價者排在同組後段。"
)


class ReportExecutionError(ValueError):
    pass


def report_execution_summary(generator: object) -> dict:
    evidence_documents = getattr(generator, "last_evidence_documents", None) or []
    excluded_low_quality = getattr(generator, "last_excluded_low_quality_documents", None) or []
    llm_result = getattr(generator, "last_llm_result", None)
    vector_store = getattr(generator, "vector_store", None)
    retrieval_trace = getattr(vector_store, "last_retrieval_trace", None) if vector_store is not None else None
    graph_reasoning_plan = getattr(generator, "last_graph_reasoning_plan", None)
    llm_status = None
    if llm_result is not None:
        llm_status = {
            "fallback": bool(getattr(llm_result, "fallback", False)),
            "model": getattr(llm_result, "model", None),
            "provider": getattr(llm_result, "provider", None),
            "key_index": getattr(llm_result, "key_index", None),
            "observability": getattr(llm_result, "observability", {}) or {},
            "attempt_summary": summarize_llm_attempts(getattr(llm_result, "attempts", ())),
            "attempts": list(getattr(llm_result, "attempts", ())[-10:]),
        }
    return {
        "filtered_tickers": list(getattr(generator, "last_filtered_tickers", None) or []),
        "dropped_tickers": list(getattr(generator, "last_dropped_tickers", None) or []),
        "evidence_count": len(evidence_documents),
        "excluded_low_quality_source_count": len(excluded_low_quality),
        "retrieval_trace": retrieval_trace,
        "graph_reasoning": graph_reasoning_plan,
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
        self.last_excluded_low_quality_documents: list[NewsDocument] = []
        self.last_llm_result: LLMResult | None = None
        self.last_graph_reasoning_plan: dict | None = None
        self.last_filtered_tickers: list[str] = []
        self.last_dropped_tickers: list[str] = []
        self._document_match_cache: dict[tuple[str, str, str, int], list] = {}

    def generate(self, request: ReportRequest, documents: list[NewsDocument] | None = None) -> ReportResponse:
        raw_evidence_docs = documents or self._retrieve_evidence(request)
        evidence_docs = filter_formal_evidence_documents(raw_evidence_docs)
        self.last_excluded_low_quality_documents = [
            document
            for document in raw_evidence_docs
            if not is_formal_evidence_document(document)
        ]
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

        graph_reasoning_context = self._graph_reasoning_context(request, tickers)
        prompt = build_report_prompt(
            whitelist_context=self.whitelist.as_prompt_context(),
            graph_context=graph_reasoning_context,
            evidence_documents=evidence_docs,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            ticker_label_resolver=self._document_company_labels,
        )
        llm_result = self._generate_llm_supplement(prompt)
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
        markdown = remove_low_quality_investor_forum_lines(markdown)
        self._assert_report_integrity(markdown, self.whitelist)
        return ReportResponse(
            title=f"{request.topic} 自動分析報告",
            generated_at=now_taipei(),
            markdown=markdown,
            findings=findings,
        )

    @staticmethod
    def _assert_report_integrity(markdown: str, whitelist: SupplyChainWhitelist | None = None) -> None:
        try:
            assert_report_integrity(markdown, whitelist)
        except ReportIntegrityError as exc:
            raise ReportExecutionError(str(exc)) from exc

    def _generate_llm_supplement(self, prompt: str) -> LLMResult:
        structured_generate = getattr(self.llm, "generate_structured_with_metadata", None)
        if callable(structured_generate):
            return structured_generate(
                prompt,
                tool_schema=LLMSupplementValidator.tool_schema(),
                tool_name="submit_report_supplement",
            )
        return self.llm.generate_with_metadata(prompt)

    def _retrieve_evidence(self, request: ReportRequest) -> list[NewsDocument]:
        return report_evidence_retrieval.retrieve_evidence(
            request,
            mapper=self.mapper,
            whitelist=self.whitelist,
            vector_store=self.vector_store,
            document_matcher=self._document_matches,
            session_scope_func=session_scope,
        )

    def _vector_search(
        self,
        query: str,
        target_tickers: list[str],
        target_aliases: dict[str, list[str]] | None = None,
    ) -> list[NewsDocument]:
        return report_evidence_retrieval.vector_search(
            query,
            self.vector_store,
            target_tickers,
            target_aliases,
        )

    def _target_aliases_by_ticker(self, tickers: list[str]) -> dict[str, list[str]]:
        return report_evidence_retrieval.target_aliases_by_ticker(tickers, self.whitelist)

    def _graph_rag_search_queries(self, request: ReportRequest, limit: int = 12) -> list[str]:
        return report_evidence_retrieval.graph_rag_search_queries(
            request,
            mapper=self.mapper,
            whitelist=self.whitelist,
            limit=limit,
        )

    def _graph_reasoning_context(self, request: ReportRequest, tickers: list[str]) -> str:
        self.last_graph_reasoning_plan = None
        context, plan = report_evidence_retrieval.graph_reasoning_context(
            request,
            tickers,
            whitelist=self.whitelist,
        )
        self.last_graph_reasoning_plan = plan
        return context

    @staticmethod
    def _graph_neighbor_search_terms(graph, ticker: str, node_by_ticker: dict, max_neighbors: int = 4) -> list[str]:
        return report_evidence_retrieval.graph_neighbor_search_terms(
            graph,
            ticker,
            node_by_ticker,
            max_neighbors=max_neighbors,
        )

    @staticmethod
    def _append_search_query(queries: list[str], query: str, limit: int) -> None:
        report_evidence_retrieval.append_search_query(queries, query, limit)

    @staticmethod
    def _compact_search_terms(terms, max_terms: int = 18) -> list[str]:
        return report_evidence_retrieval.compact_search_terms(terms, max_terms=max_terms)

    @staticmethod
    def _dedupe_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        return report_evidence_retrieval.dedupe_documents(documents)

    def _rank_evidence_documents(
        self,
        request: ReportRequest,
        documents: list[NewsDocument],
    ) -> list[NewsDocument]:
        return report_evidence_retrieval.rank_evidence_documents(
            request,
            documents,
            mapper=self.mapper,
            whitelist=self.whitelist,
            document_matcher=self._document_matches,
        )

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
        return report_markdown_sections.render_markdown(
            self,
            request,
            documents,
            findings,
            tickers,
            llm_result,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
            leading_signals,
        )

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
        return report_credibility_check.render_credibility_check(
            request=request,
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
            company_filing_missing_resolver=self._company_filing_missing,
        )

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
                recent_source_days=request.lookback_days,
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
        return report_decision_rules.sort_decision_contexts(contexts)

    @classmethod
    def _decision_sort_key(cls, context: dict) -> tuple:
        return report_decision_rules.decision_sort_key(context)

    @staticmethod
    def _decision_rank(decision: str | None) -> int:
        return report_decision_rules.decision_rank(decision)

    @staticmethod
    def _context_current_price(context: dict) -> float:
        return report_decision_rules.context_current_price(context)

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
            return report_action_checklist.render_action_checklist([], self._downside_gate(request))

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
        return report_action_checklist.render_action_checklist(contexts, self._downside_gate(request))

    @staticmethod
    def _recheck_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.recheck_trigger_text(context, downside_gate)

    @staticmethod
    def _avoid_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.avoid_trigger_text(context, downside_gate)

    @staticmethod
    def _monitor_frequency(context: dict) -> str:
        return report_decision_rules.monitor_frequency(context)

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
            return report_monitoring_checklist.render_monitoring_checklist([], self._downside_gate(request))
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
        return report_monitoring_checklist.render_monitoring_checklist(contexts, downside_gate)

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
                "- 「追價風險標籤」會納入最新可取得收盤價、近 20/60 日股價動能、量能、目前相對估值與目前情境降值分；它是追價風險提示，不是即時報價或買賣指令。",
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
                "- 「追價風險標籤」若顯示不適合追價、等止跌、等回檔或等風險下降，代表現在不應只因題材熱度就投入。",
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
        return report_executive_snapshot.render_executive_snapshot(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
        )

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
        request: ReportRequest | None = None,
    ) -> str:
        return report_data_quality.render_data_quality(
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
            company_filing_missing_resolver=self._company_filing_missing,
            recent_source_days=request.lookback_days if request else None,
        )

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
        return report_score_breakdown.render_score_breakdown(
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            leading_signals=leading_signals,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
        )

    def _render_source_coverage(
        self,
        request: ReportRequest,
        tickers: list[str],
        documents: list[NewsDocument],
    ) -> str:
        return report_source_coverage.render_source_coverage(
            evidence_limit=request.evidence_limit,
            tickers=tickers,
            documents=documents,
            companies=self.whitelist.companies(),
            related_documents_resolver=self._related_documents,
        )

    def _render_candidate_audit(self, promoted_tickers: list[str]) -> str:
        return render_candidate_audit_markdown(self.whitelist.candidate_audit(), promoted_tickers)

    @staticmethod
    def _render_leading_signal_check(
        tickers: list[str],
        leading_signals: dict[str, LeadingSignal],
    ) -> str:
        return report_leading_signal.render_leading_signal_check(tickers, leading_signals)

    @staticmethod
    def _format_optional_pct(value: float | None) -> str:
        return report_leading_signal.format_optional_pct(value)

    @staticmethod
    def _format_optional_ratio(value: float | None) -> str:
        return report_leading_signal.format_optional_ratio(value)

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
        return report_early_potential.render_early_potential_radar(
            request=request,
            tickers=tickers,
            documents=documents,
            findings=findings,
            market_snapshots=market_snapshots,
            monthly_revenues=monthly_revenues,
            leading_signals=leading_signals,
            financial_metrics=financial_metrics,
            valuation_metrics=valuation_metrics,
            companies=self.whitelist.companies(),
            candidate_audit=self.whitelist.candidate_audit(),
            decision_contexts_resolver=self._decision_contexts,
            related_documents_resolver=self._related_documents,
            related_findings_resolver=self._related_findings,
        )

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
        request: ReportRequest | None = None,
    ) -> str:
        if not tickers:
            return report_final_potential.render_final_potential_screen([])

        request = request or ReportRequest(tickers=tickers)
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
        return report_final_potential.render_final_potential_screen(contexts)

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
            return report_company_matrix.render_company_comparison_matrix([], {}, {}, REPORT_READING_SORT_NOTE)

        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
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
        return report_company_matrix.render_company_comparison_matrix(
            contexts,
            metrics_by_ticker,
            peer_valuation_summary,
            REPORT_READING_SORT_NOTE,
        )

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
            return report_investment_thesis.render_investment_thesis_map(
                [],
                request,
                REPORT_READING_SORT_NOTE,
                self._representative_sources,
                self._downside_source_references,
            )

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
        return report_investment_thesis.render_investment_thesis_map(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
            self._representative_sources,
            self._downside_source_references,
        )

    @staticmethod
    def _thesis_reason(context: dict, request: ReportRequest) -> str:
        return report_investment_thesis.thesis_reason(context, request)

    @staticmethod
    def _thesis_verification_items(
        quality: dict,
        findings,
        related_documents: list[NewsDocument],
    ) -> str:
        return report_investment_thesis.thesis_verification_items(quality, findings, related_documents)

    @staticmethod
    def _representative_sources(documents: list[NewsDocument], limit: int = 3) -> str:
        return representative_sources(documents, limit=limit)

    @staticmethod
    def _downside_source_references(
        documents: list[NewsDocument],
        findings,
        limit: int = 3,
    ) -> str:
        return downside_source_references(
            documents,
            findings,
            limit=limit,
            scoring_text_for_document=ReportGenerator._scoring_text_for_document,
        )

    @staticmethod
    def _ordered_source_documents(documents: list[NewsDocument]) -> list[NewsDocument]:
        return ordered_source_documents(documents)

    def _appendix_documents_for_tickers(
        self,
        documents: list[NewsDocument],
        tickers: list[str] | None,
    ) -> list[NewsDocument]:
        return report_appendix.appendix_documents_for_tickers(
            documents,
            tickers,
            document_match_resolver=self._document_matches,
        )

    @staticmethod
    def _source_reference_line(document: NewsDocument) -> str:
        return source_reference_line(document)

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

        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        companies = {company.ticker: company for company in self.whitelist.companies()}
        latest_valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(latest_valuations.values()))
        candidate_audit = self._candidate_audit_by_ticker()
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
        overview_rows: list[str] = []
        detail_blocks: list[str] = []
        for context in contexts:
            ticker = context["ticker"]
            company = companies.get(ticker)
            segment = self.whitelist.segment_for_ticker(ticker)
            snapshot = context.get("snapshot")
            revenue = context.get("revenue")
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = context.get("valuation")
            related_findings = context.get("findings") or []
            related_documents = context.get("documents") or []
            signal = context.get("leading_signal")
            estimate = context["estimate"]
            quality = context["quality"]
            downside_gate = self._downside_gate(request)
            decision = context["decision"]
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
            price_label = report_company_analysis.price_label(snapshot)
            valuation_position = context["valuation_label"]
            financial_confidence = self._financial_confidence_label(ticker_metrics, valuation, revenue)
            overview_rows.append(
                report_company_analysis.overview_row(
                    context,
                    segment_name,
                    financial_confidence,
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
            detail_blocks.append(f"- 追價風險標籤：{context['current_price_label']}；最新可取得收盤價：{price_label}。")
            detail_blocks.append(f"- 產業鏈位置：{segment_name}")
            detail_blocks.extend(
                report_company_analysis.basic_intro(
                    ticker,
                    name,
                    segment_name,
                    company,
                    related_documents,
                    candidate_audit.get(ticker, {}),
                    self._is_company_filing_document,
                    self._news_document_filing_type,
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
                    peer_valuation_summary,
                    related_documents,
                    related_findings,
                    self._company_risk_summary(related_findings),
                    decision,
                    decision_reason,
                )
            )
            detail_blocks.append("")

        return report_company_analysis.render_company_analysis(
            overview_rows,
            detail_blocks,
            REPORT_READING_SORT_NOTE,
        )

    def _candidate_audit_by_ticker(self) -> dict[str, dict]:
        return {
            str(candidate.get("ticker")): candidate
            for candidate in self.whitelist.candidate_audit()
            if candidate.get("ticker")
        }

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
        downside_gate = self._downside_gate(request)
        contexts = []
        for context in self._sort_decision_contexts(
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
            context = dict(context)
            context["rationale"] = self._decision_reason(
                context["decision"],
                context["estimate"],
                context["quality"],
                context.get("findings") or [],
                context.get("documents") or [],
                downside_gate,
                request,
                context.get("leading_signal"),
            )
            contexts.append(context)
        return report_investment_recommendations.render_investment_recommendations(
            contexts,
            request,
            REPORT_READING_SORT_NOTE,
            lambda related_documents: self._representative_sources(related_documents, limit=2),
        )

    @staticmethod
    def _company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.company_evidence_summary(related_documents, related_findings)

    @staticmethod
    def _company_filing_evidence_summary(related_documents: list[NewsDocument]) -> str:
        return report_company_narrative.company_filing_evidence_summary(related_documents)

    @staticmethod
    def _company_revenue_summary(revenue: MonthlyRevenue | None) -> str:
        return report_company_narrative.company_revenue_summary(revenue)

    @staticmethod
    def _company_quick_take(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        return report_company_narrative.company_quick_take(
            snapshot,
            revenue,
            financial_metrics,
            valuation,
            related_documents,
            related_findings,
        )

    @staticmethod
    def _group_financial_metrics(metrics: list[FinancialMetric]) -> dict[str, list[FinancialMetric]]:
        return report_company_narrative.group_financial_metrics(metrics)

    @staticmethod
    def _financial_statement_summary(metrics: list[FinancialMetric]) -> dict[str, str]:
        return financial_statement_summary(metrics)

    @staticmethod
    def _metric_series(
        metrics: list[FinancialMetric],
        keywords: list[str],
        statement_types: set[str] | None = None,
        exclude_keywords: list[str] | None = None,
        annual_only: bool = False,
    ) -> dict[int, float]:
        return metric_series(
            metrics,
            keywords,
            statement_types=statement_types,
            exclude_keywords=exclude_keywords,
            annual_only=annual_only,
        )

    @staticmethod
    def _balance_sheet_total_series(
        metrics: list[FinancialMetric],
        metric_names: set[str],
        origin_names: set[str],
    ) -> dict[int, float]:
        return balance_sheet_total_series(metrics, metric_names, origin_names)

    @staticmethod
    def _series_trend_text(series: dict[int, float], label: str) -> str:
        return series_trend_text(series, label)

    @staticmethod
    def _fcf_trend_text(operating_cash: dict[int, float], capex: dict[int, float]) -> str:
        return fcf_trend_text(operating_cash, capex)

    @staticmethod
    def _margin_text(gross_profit: dict[int, float], net_income: dict[int, float], revenue: dict[int, float]) -> str:
        return margin_text(gross_profit, net_income, revenue)

    @staticmethod
    def _debt_text(liabilities: dict[int, float], equity: dict[int, float]) -> str:
        return debt_text(liabilities, equity)

    @staticmethod
    def _debt_equity_phrase(ratio: float) -> str:
        return debt_equity_phrase(ratio)

    @staticmethod
    def _roe_text(net_income: dict[int, float], equity: dict[int, float]) -> str:
        return roe_text(net_income, equity)

    @staticmethod
    def _financial_strength_text(
        revenue: dict[int, float],
        net_income: dict[int, float],
        liabilities: dict[int, float],
        equity: dict[int, float],
    ) -> str:
        return financial_strength_text(revenue, net_income, liabilities, equity)

    @staticmethod
    def _series_growth_pct(series: dict[int, float]) -> float | None:
        return series_growth_pct(series)

    @staticmethod
    def _series_period_text(series: dict[int, float]) -> str:
        return series_period_text(series)

    @staticmethod
    def _decline_risk_points(growth_pct: float, *, metric: str) -> int:
        return decline_risk_points(growth_pct, metric=metric)

    @staticmethod
    def _financial_valuation_assessment(
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> dict:
        return financial_valuation_assessment(financial_metrics, valuation, peer_summary)

    @staticmethod
    def _peer_valuation_summary(valuations: list[ValuationMetric]) -> dict[str, float | None]:
        return peer_valuation_summary(valuations)

    @staticmethod
    def _valuation_summary(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        return report_company_narrative.valuation_summary(valuation, peer_summary)

    @staticmethod
    def _valuation_peer_comparison(
        valuation: ValuationMetric,
        peer_summary: dict[str, float | None],
    ) -> str:
        return report_company_narrative.valuation_peer_comparison(valuation, peer_summary)

    @staticmethod
    def _valuation_position_label(
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
        has_negative_profitability: bool = False,
    ) -> str:
        return valuation_position_label(valuation, peer_summary, has_negative_profitability)

    @staticmethod
    def _has_negative_profitability(metrics: list[FinancialMetric]) -> bool:
        return has_negative_profitability(metrics)

    @staticmethod
    def _sanitize_leading_signal_for_profitability(
        signal: LeadingSignal,
        has_negative_profitability: bool,
    ) -> LeadingSignal:
        return report_company_narrative.sanitize_leading_signal_for_profitability(
            signal,
            has_negative_profitability,
        )

    @staticmethod
    def _current_price_text(snapshot: MarketSnapshot | None) -> str:
        return report_decision_rules.current_price_text(snapshot)

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
        return report_decision_rules.current_price_label(
            snapshot,
            estimate,
            quality,
            valuation_label,
            leading_signal,
            decision,
            downside_gate,
        )

    @staticmethod
    def _financial_confidence_label(
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
        revenue: MonthlyRevenue | None,
    ) -> str:
        return report_company_narrative.financial_confidence_label(
            financial_metrics,
            valuation,
            revenue,
        )

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
        return report_company_matrix.company_matrix_reminder(
            estimate,
            quality,
            related_findings,
            valuation,
            peer_summary,
            financial_metrics,
            leading_signal,
        )

    @staticmethod
    def _valuation_conclusion(
        snapshot: MarketSnapshot | None,
        valuation: ValuationMetric | None,
        peer_summary: dict[str, float | None] | None = None,
    ) -> str:
        return report_company_narrative.valuation_conclusion(snapshot, valuation, peer_summary)

    @staticmethod
    def _company_market_summary(snapshot: MarketSnapshot | None) -> str:
        return report_company_narrative.company_market_summary(snapshot)

    def _company_risk_summary(self, related_findings) -> str:
        if not related_findings:
            return "未偵測到可歸因的重大風險；仍需持續追蹤新聞、月營收與官方文件。"
        topics = []
        for finding in related_findings[:3]:
            topics.append(self._sanitized_risk_topic_for_finding(finding))
        return "、".join(topics)

    @staticmethod
    def _trend_summary(related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.trend_summary(related_documents, related_findings)

    @staticmethod
    def _near_term_outlook(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument], related_findings) -> str:
        return report_company_narrative.near_term_outlook(
            revenue,
            related_documents,
            related_findings,
        )

    @staticmethod
    def _growth_opportunity_text(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
    ) -> str:
        return report_company_narrative.growth_opportunity_text(
            related_documents,
            related_findings,
            revenue,
        )

    @staticmethod
    def _long_term_growth_text(
        financial_summary: dict[str, str],
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
    ) -> str:
        return report_company_narrative.long_term_growth_text(
            financial_summary,
            revenue,
            related_documents,
        )

    @staticmethod
    def _dcf_proxy_text(financial_summary: dict[str, str], valuation: ValuationMetric | None) -> str:
        return report_company_narrative.dcf_proxy_text(financial_summary, valuation)

    @staticmethod
    def _industry_average_text(peer_summary: dict[str, float | None]) -> str:
        return report_company_narrative.industry_average_text(peer_summary)

    @staticmethod
    def _bull_case(revenue: MonthlyRevenue | None, related_documents: list[NewsDocument]) -> str:
        return report_company_narrative.bull_case(revenue, related_documents)

    @staticmethod
    def _bear_case(related_findings) -> str:
        return report_company_narrative.bear_case(related_findings)

    @staticmethod
    def _moat_score(
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> int:
        return report_company_narrative.moat_score(
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _moat_reason(
        score: int,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str] | None = None,
    ) -> str:
        return report_company_narrative.moat_reason(
            score,
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _moat_factor_text(
        factor: str,
        related_documents: list[NewsDocument],
        related_findings,
        revenue: MonthlyRevenue | None,
        financial_summary: dict[str, str],
    ) -> str:
        return report_company_narrative.moat_factor_text(
            factor,
            related_documents,
            related_findings,
            revenue,
            financial_summary,
        )

    @staticmethod
    def _company_rating(
        snapshot: MarketSnapshot | None,
        revenue: MonthlyRevenue | None,
        related_documents: list[NewsDocument],
        related_findings,
    ) -> str:
        return report_company_narrative.company_rating(
            snapshot,
            revenue,
            related_documents,
            related_findings,
        )

    def _sanitized_risk_topic_for_finding(self, finding) -> str:
        return report_risk_overview.sanitized_risk_topic_for_finding(finding, self.whitelist)

    def _sanitize_risk_topic(self, topic: str, tickers: list[str] | None = None) -> str:
        return report_risk_overview.sanitize_risk_topic(topic, tickers, whitelist=self.whitelist)

    def _companies_allow_ai_infra_risk(self, tickers: list[str]) -> bool:
        return report_risk_overview.companies_allow_ai_infra_risk(tickers, self.whitelist)

    def _company_allows_ai_infra_risk(self, ticker: str) -> bool:
        return report_risk_overview.company_allows_ai_infra_risk(ticker, self.whitelist)

    @staticmethod
    def _is_ai_infra_specific_risk_term(term: str) -> bool:
        return report_risk_overview.is_ai_infra_specific_risk_term(term)

    @staticmethod
    def _finding_scope_companies(finding, scope_tickers: set[str] | None = None) -> list:
        return report_risk_overview.finding_scope_companies(finding, scope_tickers)

    def _risk_findings_for_scope(self, findings, tickers: list[str] | None = None) -> list:
        return report_risk_overview.risk_findings_for_scope(findings, tickers)

    def _render_risk_overview(self, findings, tickers: list[str] | None = None) -> str:
        return report_risk_overview.render_risk_overview(findings, tickers, whitelist=self.whitelist)

    def _render_scope(
        self,
        tickers: list[str],
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
    ) -> str:
        return report_scope_sections.render_scope(
            tickers,
            market_snapshots,
            monthly_revenues,
            whitelist_context=self.whitelist.as_prompt_context(),
        )

    @staticmethod
    def _render_revenue_check(tickers: list[str], monthly_revenues: list[MonthlyRevenue]) -> str:
        return report_scope_sections.render_revenue_check(tickers, monthly_revenues)

    def _render_appendix(
        self,
        llm_result: LLMResult,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot],
        tickers: list[str] | None = None,
    ) -> str:
        return report_appendix.render_appendix(
            llm_result,
            documents,
            market_snapshots,
            tickers=tickers,
            document_match_resolver=self._document_matches,
            claim_ticker_resolver=lambda claim: self.mapper.match_text(claim),
        )

    @staticmethod
    def _is_international_source(document: NewsDocument) -> bool:
        return report_source_coverage.is_international_source(document)

    def _document_matches(self, document: NewsDocument) -> list:
        cache = getattr(self, "_document_match_cache", None)
        if cache is None:
            cache = {}
            self._document_match_cache = cache
        return report_document_matching.document_matches(
            document,
            mapper=self.mapper,
            whitelist=self.whitelist,
            cache=cache,
        )

    def _document_metadata_matches(self, document: NewsDocument) -> list:
        return report_document_matching.document_metadata_matches(document, self.whitelist)

    def _related_documents(self, ticker: str, documents: list[NewsDocument]) -> list[NewsDocument]:
        return report_document_matching.related_documents(
            ticker,
            documents,
            document_match_resolver=self._document_matches,
        )

    def _document_company_labels(self, document: NewsDocument) -> list[str]:
        return report_document_matching.document_company_labels(
            document,
            document_match_resolver=self._document_matches,
        )

    def _candidate_audit_evidence_counts(self) -> dict[str, dict[str, int]]:
        return report_document_matching.candidate_audit_evidence_counts(self.whitelist.candidate_audit())

    @staticmethod
    def _publisher_count(documents: list[NewsDocument]) -> int:
        return report_document_matching.publisher_count(documents)

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
            return report_beginner_portfolio.render_beginner_portfolio_plan(
                [],
                request,
                self._decision_reason,
            )

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
        return report_beginner_portfolio.render_beginner_portfolio_plan(
            contexts,
            request,
            self._decision_reason,
        )

    @staticmethod
    def _render_allocation_plan(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[str]:
        return report_allocation.render_allocation_plan(candidates, deployable, first_tranche)

    @staticmethod
    def _allocation_amounts(
        candidates: list[dict],
        deployable: int,
        first_tranche: int,
    ) -> list[int]:
        return report_allocation.allocation_amounts(candidates, deployable, first_tranche)

    @staticmethod
    def _round_lot_amount(amount: int) -> int:
        return report_allocation.round_lot_amount(amount)

    @staticmethod
    def _round_down_lot_amount(amount: int) -> int:
        return report_allocation.round_down_lot_amount(amount)

    @staticmethod
    def _max_position_amount(request: ReportRequest) -> int:
        return report_allocation.max_position_amount(request)

    @staticmethod
    def _profile(request: ReportRequest) -> InvestorProfile:
        return report_allocation.profile(request)

    @staticmethod
    def _profile_label(request: ReportRequest) -> str:
        return report_allocation.profile_label(request)

    @staticmethod
    def _downside_gate(request: ReportRequest) -> int:
        return report_allocation.downside_gate(request)

    @staticmethod
    def _first_tranche_ratio(request: ReportRequest) -> float:
        return report_allocation.first_tranche_ratio(request)

    @staticmethod
    def _risk_warning_reason(estimate: dict) -> str:
        return report_decision_rules.risk_warning_reason(estimate)

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
        return report_company_narrative.filing_type_label(document_type)

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
        return report_company_narrative.news_document_filing_type(document)

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
        recent_source_days: int | None = None,
    ) -> dict:
        return report_potential.data_quality_grade(
            related_documents,
            related_findings,
            snapshot,
            monthly_revenue=monthly_revenue,
            financial_metrics=financial_metrics,
            valuation=valuation,
            include_fundamentals=include_fundamentals,
            leading_signal=leading_signal,
            company_filing_missing=company_filing_missing,
            recent_source_days=recent_source_days,
        )

    @staticmethod
    def _score_data_note(
        confidence_notes: list[str],
        financial_metrics: list[FinancialMetric],
        valuation: ValuationMetric | None,
    ) -> str:
        return report_potential.score_data_note(confidence_notes, financial_metrics, valuation)

    @staticmethod
    def _quality_label(grade: str) -> str:
        return report_potential.quality_label(grade)

    @staticmethod
    def _decision_label(
        estimate: dict,
        quality: dict,
        related_findings,
        downside_gate: int,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        return report_potential.decision_label(
            estimate,
            quality,
            related_findings,
            downside_gate,
            leading_signal,
        )

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
        return report_decision_narrative.decision_reason(
            rating,
            estimate,
            quality,
            related_findings,
            related_documents,
            downside_gate,
            request,
            leading_signal,
        )

    @staticmethod
    def _structural_bottleneck_reason(related_findings) -> str:
        return report_decision_narrative.structural_bottleneck_reason(related_findings)

    @staticmethod
    def _compact_text(value: object, max_chars: int = 80) -> str:
        return report_formatting.compact_text(value, max_chars=max_chars)

    @staticmethod
    def _table_cell(value: object) -> str:
        return report_formatting.table_cell(value)

    @staticmethod
    def _table_row(cells: list[object]) -> str:
        return report_formatting.table_row(cells)

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
        return report_potential.estimate_potential(
            related_documents,
            related_findings,
            snapshot,
            monthly_revenue=monthly_revenue,
            leading_signal=leading_signal,
            financial_metrics=financial_metrics,
            valuation=valuation,
            peer_valuation_summary=peer_valuation_summary,
        )

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
        return report_potential.early_potential_profile(
            related_documents,
            monthly_revenue,
            leading_signal,
            upside_pct,
            downside_pct,
            snapshot=snapshot,
            document_count_override=document_count_override,
            publisher_count_override=publisher_count_override,
        )

    @staticmethod
    def _has_month_over_month_revenue_decline_text(documents: list[NewsDocument]) -> bool:
        return report_potential.has_month_over_month_revenue_decline_text(documents)

    @staticmethod
    def _month_over_month_revenue_caveat(
        documents: list[NewsDocument],
        monthly_revenue: MonthlyRevenue | None,
    ) -> str:
        return report_potential.month_over_month_revenue_caveat(documents, monthly_revenue)

    @staticmethod
    def _format_factors(factors: list[tuple[str, int]]) -> str:
        return report_potential.format_potential_factors(factors)

    @staticmethod
    def _upside_evidence_reason_prefix(
        document_count: int,
        positive_hits: int,
        opportunity_findings: int,
        evidence_score: int,
    ) -> str:
        return report_potential.upside_evidence_reason_prefix(
            document_count,
            positive_hits,
            opportunity_findings,
            evidence_score,
        )

    @staticmethod
    def _downside_evidence_reason_prefix(
        negative_hits: int,
        structural_findings: int,
        volatility_findings: int,
        news_risk_score: int,
    ) -> str:
        return report_potential.downside_evidence_reason_prefix(
            negative_hits,
            structural_findings,
            volatility_findings,
            news_risk_score,
        )

    @staticmethod
    def _revenue_reason(
        monthly_revenue: MonthlyRevenue | None,
        score_delta: int,
        positive: bool,
    ) -> str:
        return report_potential.revenue_reason(monthly_revenue, score_delta, positive)

    @staticmethod
    def _leading_signal_reason(leading_signal: LeadingSignal | None, positive: bool) -> str:
        return report_potential.leading_signal_reason(leading_signal, positive)

    @staticmethod
    def _leading_signal_factor_label(leading_signal: LeadingSignal, positive: bool) -> str:
        return report_potential.leading_signal_factor_label(leading_signal, positive)

    @staticmethod
    def _financial_assessment_reason(assessment: dict, positive: bool) -> str:
        return report_potential.financial_assessment_reason(assessment, positive)

    @staticmethod
    def _scoring_text_for_document(document: NewsDocument) -> str:
        return report_potential.scoring_text_for_document(document)

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
        documents = filter_formal_evidence_documents(documents)
        if not documents:
            return "目前無足夠數據判斷。"
        return "\n".join(
            f"- {doc.source.published_at or '日期不明'} {doc.source.publisher or ''} {doc.title}: {doc.text[:500]}"
            for doc in documents
        )

    @staticmethod
    def _format_llm_evidence(
        documents: list[NewsDocument],
        ticker_label_resolver: Callable[[NewsDocument], list[str]] | None = None,
    ) -> str:
        return format_llm_evidence(documents, ticker_label_resolver)

    @staticmethod
    def _format_market_data(
        snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
    ) -> str:
        return format_market_data(snapshots, monthly_revenues)

    @staticmethod
    def _model_status(result: LLMResult) -> str:
        return report_appendix.model_status(result)
