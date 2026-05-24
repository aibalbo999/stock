from __future__ import annotations

from collections import Counter

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
from app.services.entity_mapping import EntityMapper
from app.services.llm_client import LLMClient, LLMResult
from app.services.llm_analysis import LLMSupplementValidator
from app.services.persistence import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ValuationMetricRepository,
)
from app.services.risk_analyzer import RiskAnalyzer
from app.services.whitelist import SupplyChainWhitelist


class ReportGenerator:
    def __init__(
        self,
        vector_store: VectorStore | None = None,
        whitelist: SupplyChainWhitelist | None = None,
    ) -> None:
        self.whitelist = whitelist or SupplyChainWhitelist()
        self.vector_store = vector_store or VectorStore()
        self.mapper = EntityMapper(self.whitelist)
        self.risk_analyzer = RiskAnalyzer(self.whitelist, self.mapper, use_llm=True)
        self.llm = LLMClient()
        self.last_evidence_documents: list[NewsDocument] = []

    def generate(self, request: ReportRequest, documents: list[NewsDocument] | None = None) -> ReportResponse:
        evidence_docs = documents or self._retrieve_evidence(request)
        self.last_evidence_documents = list(evidence_docs)
        findings = self.risk_analyzer.analyze_documents(evidence_docs)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        market_snapshots = self._latest_market_snapshots(tickers)
        monthly_revenues = self._latest_monthly_revenues(tickers)
        financial_metrics = self._financial_metrics(tickers)
        valuation_metrics = self._latest_valuations(tickers)

        prompt = SYSTEM_PROMPT + "\n\n" + REPORT_PROMPT_TEMPLATE.format(
            whitelist=self.whitelist.as_prompt_context(),
            evidence=self._format_evidence(evidence_docs),
            market_data=self._format_market_data(market_snapshots, monthly_revenues),
        )
        llm_result = self.llm.generate_with_metadata(prompt)
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
        except Exception:
            db_documents = []
        documents = self._dedupe_documents([*evidence_docs, *db_documents])
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
    ) -> str:
        lines = [
            f"# {request.topic} 自動分析報告",
            "",
            f"生成時間（台灣）：{now_taipei().isoformat(timespec='seconds')}",
            "",
            "## 一頁摘要",
            self._render_executive_snapshot(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 下一步行動",
            self._render_action_checklist(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 先看結論",
            self._summary(findings),
            "",
            "## 資料完整度",
            self._render_data_quality(
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 來源覆蓋",
            self._render_source_coverage(request, tickers, documents),
            "",
            "## 資金控管建議",
            self._render_beginner_portfolio_plan(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 投資建議",
            self._render_investment_recommendations(
                request,
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 二次綜合篩選",
            self._render_final_potential_screen(
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 評分明細",
            self._render_score_breakdown(
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 基本面月營收檢查",
            self._render_revenue_check(tickers, monthly_revenues),
            "",
            "## 個別公司分析",
            self._render_company_analysis(
                tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
            ),
            "",
            "## 主要風險與瓶頸",
            self._render_risk_overview(findings),
            "",
            "## 分析範圍",
            self._render_scope(tickers, market_snapshots, monthly_revenues),
            "",
            "## 附錄：AI 補充與資料來源",
            self._render_appendix(llm_result, documents, market_snapshots),
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
    ) -> list[dict]:
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        downside_gate = self._downside_gate(request)
        contexts = []
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            estimate = self._estimate_potential(related_documents, related_findings, snapshot, revenue)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
            )
            decision = self._decision_label(estimate, quality, related_findings, downside_gate)
            contexts.append(
                {
                    "ticker": ticker,
                    "name": company.name if company else ticker,
                    "label": f"{ticker} {company.name if company else ticker}",
                    "documents": related_documents,
                    "findings": related_findings,
                    "snapshot": snapshot,
                    "revenue": revenue,
                    "estimate": estimate,
                    "quality": quality,
                    "decision": decision,
                }
            )
        return contexts

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
    ) -> str:
        if not tickers:
            return "1. 先補足新聞與市場資料，再重新執行分析。"

        contexts = self._decision_contexts(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
        )
        research = [item for item in contexts if item["decision"] == "可小額分批研究"]
        watch = [
            item
            for item in contexts
            if item["decision"] not in {"可小額分批研究", "避開 / 降低曝險"}
        ]
        avoid = [item for item in contexts if item["decision"] == "避開 / 降低曝險"]

        lines = [
            "1. 先處理資料缺口：若有「缺 AI 歸因、缺月營收、缺股價」，先補資料再考慮加碼。",
            "2. 只把資料完整且通過降值門檻的股票放進小額研究清單。",
            "3. 對降值風險高於門檻的股票，先等風險下降或新資料確認。",
            "",
            "### 可立即研究",
        ]
        if research:
            for item in research:
                lines.append(
                    f"- {item['label']}：可看資金控管建議中的首筆配置；"
                    f"升值 {item['estimate']['upside_pct']}%，降值 {item['estimate']['downside_pct']}%。"
                )
        else:
            lines.append("- 目前沒有同時通過資料完整度與風險門檻的標的。")

        lines.extend(["", "### 待補資料 / 觀察"])
        if watch:
            for item in watch:
                missing = "、".join(item["quality"]["missing"]) if item["quality"]["missing"] else "等待新證據"
                lines.append(f"- {item['label']}：{item['decision']}；下一步補查 {missing}。")
        else:
            lines.append("- 目前沒有待補資料名單。")

        lines.extend(["", "### 先避開"])
        if avoid:
            for item in avoid:
                lines.append(
                    f"- {item['label']}：降值風險 {item['estimate']['downside_pct']}%，"
                    "暫不列入買進研究。"
                )
        else:
            lines.append("- 目前沒有明確避開名單。")
        return "\n".join(lines)

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
    ) -> str:
        if not tickers:
            return "本次沒有形成可驗證個股清單；先補資料，不建議依此報告做個股配置。"

        rows = []
        actionable = 0
        watch = 0
        avoid = 0
        weak = 0
        for item in self._decision_contexts(
            request,
            tickers,
            documents,
            findings,
            market_snapshots,
            monthly_revenues,
            financial_metrics,
            valuation_metrics,
        ):
            decision = item["decision"]
            quality = item["quality"]
            estimate = item["estimate"]
            if decision == "可小額分批研究":
                actionable += 1
            elif decision == "避開 / 降低曝險":
                avoid += 1
            elif quality["grade"] == "weak":
                weak += 1
            else:
                watch += 1
            rows.append(
                "| "
                + " | ".join(
                    [
                        item["label"],
                        decision,
                        self._quality_label(quality["grade"]),
                        f"{estimate['upside_pct']}%",
                        f"{estimate['downside_pct']}%",
                        "、".join(quality["missing"]) if quality["missing"] else "完整",
                    ]
                )
                + " |"
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
            f"| 投資人設定 | {self._profile_label(request)}；總資金 {request.investor_capital:,} 元；本輪可投入上限約 {deployable:,} 元 |",
            f"| 本次股票範圍 | {len(tickers)} 檔 |",
            f"| 可小額研究 | {actionable} 檔 |",
            f"| 觀察/待補 | {watch + weak} 檔 |",
            f"| 避開/降低曝險 | {avoid} 檔 |",
            "",
            "### 決策總覽",
            "| 股票 | 判斷 | 資料等級 | 升值情境 | 降值風險 | 主要缺口 |",
            "|---|---|---|---:|---:|---|",
            *rows,
            "",
            "閱讀方式：先看「判斷」與「主要缺口」，再到後面的資金控管與個別公司分析確認原因。",
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
            "本段檢查每檔股票是否同時具備新聞/RAG、AI 歸因、股價、月營收、五年財報與估值資料；資料不足時，系統會降低建議強度。",
            "",
            "| 股票 | 新聞/RAG | AI歸因 | 股價 | 月營收 | 五年財報 | 估值 | 判讀 |",
            "|---|---:|---:|---|---|---:|---|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            has_snapshot = ticker in snapshots
            has_revenue = ticker in revenues
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshots.get(ticker),
                revenues.get(ticker),
                ticker_metrics,
                valuation,
                financial_metrics is not None or valuation_metrics is not None,
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
            lines.append(
                f"| {label} | {len(related_documents)} | {len(related_findings)} | "
                f"{price_label} | {revenue_label} | {financial_label} | {valuation_label} | {verdict} |"
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
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        lines = [
            "此段拆解研究分級來源；分數是排序與風險控管用途，不代表預期報酬率。",
            "",
            "| 股票 | 升值 | 降值 | 主要加分 | 主要風險 | 資料提醒 |",
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
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        label,
                        f"{estimate['upside_pct']}%",
                        f"{estimate['downside_pct']}%",
                        self._format_factors(estimate["upside_factors"]),
                        self._format_factors(estimate["downside_factors"]),
                        self._score_data_note(
                            estimate["confidence_notes"],
                            metrics_by_ticker.get(ticker, []),
                            valuations.get(ticker),
                        ),
                    ]
                )
                + " |"
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
            "本段說明本次 RAG 證據池的來源覆蓋；來源多不代表一定可買，仍需看公司層級歸因與財務資料是否同時成立。",
            "",
            "| 項目 | 結果 |",
            "|---|---|",
            f"| 報告證據上限 | {request.evidence_limit} 筆 |",
            f"| 實際納入證據 | {len(documents)} 筆 |",
            f"| 台灣來源 | {taiwan_count} 筆 |",
            f"| 國際來源 | {international_count} 筆 |",
            f"| 主要來源 | {'、'.join(f'{publisher}({count})' for publisher, count in publisher_counts.most_common(6))} |",
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
            lines.append(f"| {label} | {len(related_documents)} | {related_international} | {latest} |")
        if international_count == 0:
            lines.extend(["", "提醒：本次沒有國際來源進入證據池；若要擴大國際覆蓋，請開啟深度分析與國際資料源。"])
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
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
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
            estimate = self._estimate_potential(related_documents, related_findings, snapshot, revenue)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
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
                        f"- {label}：升值分數約 {estimate['upside_pct']}%，但資料品質不足；"
                        f"{'；'.join(quality['missing'])}。"
                    )
                else:
                    upside_rows.append(
                        f"- {label}：情境升值潛力約 {estimate['upside_pct']}%。"
                        f"理由：{estimate['upside_reason']} 來源：{source}。"
                    )
            if estimate["downside_pct"] > 5:
                downside_rows.append(
                    f"- {label}：情境降值風險約 {estimate['downside_pct']}%。"
                    f"理由：{estimate['downside_reason']} 來源：{source}。"
                )
            if estimate["upside_pct"] <= 10 and estimate["downside_pct"] <= 5:
                insufficient_rows.append(f"- {label}：未達升值/降值門檻或資料不足。")

        lines = [
            "本段為非個人化情境篩選；百分比是依新聞/RAG 證據與市場資料的研究分級，不是保證報酬或停損幅度。",
            "",
            "### 升值潛力股（情境潛力 >10%）",
        ]
        lines.extend(upside_rows or ["目前無足夠數據判斷。"])
        lines.extend(["", "### 降值風險股（情境風險 >5%）"])
        lines.extend(downside_rows or ["目前無足夠數據判斷。"])
        if insufficient_rows:
            lines.extend(["", "### 未達門檻 / 資料不足", *insufficient_rows])
        return "\n".join(lines)

    def _render_company_analysis(
        self,
        tickers: list[str],
        documents: list[NewsDocument],
        findings,
        market_snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation_metrics: list[ValuationMetric] | None = None,
    ) -> str:
        if not tickers:
            return "未指定白名單個股，無法產出個別公司分析。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        peer_valuation_summary = self._peer_valuation_summary(list(valuations.values()))
        companies = {company.ticker: company for company in self.whitelist.companies()}
        overview_rows: list[str] = []
        detail_blocks: list[str] = []
        for ticker in tickers:
            company = companies.get(ticker)
            segment = self.whitelist.segment_for_ticker(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            ticker_metrics = metrics_by_ticker.get(ticker, [])
            valuation = valuations.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)

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
            overview_rows.append(
                f"| {ticker} {name} | {segment_name} | {price_label} | {revenue_label} | {evidence_label} |"
            )

            detail_blocks.append(f"### {ticker} {name}")
            detail_blocks.append(f"- 產業鏈位置：{segment_name}")
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
                detail_blocks.append(f"- 新聞/RAG 證據：找到 {len(related_documents)} 筆相關文本，但未形成可歸因風險。")
            else:
                detail_blocks.append("- 新聞/RAG 證據：目前無足夠數據判斷。")
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
                )
            )
            detail_blocks.append("")

        lines = [
            "### 個股速覽",
            "| 股票 | 產業位置 | 股價 | 月營收 | 證據狀態 |",
            "|---|---|---|---|---|",
            *overview_rows,
            "",
            "### 個股細節",
            *detail_blocks,
        ]
        return "\n".join(lines).strip()

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
    ) -> list[str]:
        financial_summary = self._financial_statement_summary(financial_metrics)
        valuation_summary = self._valuation_summary(valuation, peer_valuation_summary)
        evidence_summary = self._company_evidence_summary(related_documents, related_findings)
        revenue_summary = self._company_revenue_summary(revenue)
        moat_score = self._moat_score(related_documents, related_findings, revenue, financial_summary)
        final_rating = self._company_rating(snapshot, revenue, related_documents, related_findings)
        return [
            "",
            "#### 華爾街式完整分析框架",
            f"- 商業模式與收入來源：{name} 本次被歸類在「{segment_name}」。"
            f"收入來源需以年報/法說資料確認；本系統目前僅能用主題文本與月營收觀察需求方向。{evidence_summary}",
            f"- 競爭優勢（護城河）：目前可觀察到的證據為 {evidence_summary}"
            f"護城河初評 {moat_score}/10；品牌、轉換成本、成本優勢、專利/獨家技術仍需年報與同業資料補強。",
            f"- 產業趨勢：{self._trend_summary(related_documents, related_findings)}",
            f"- 財務健康狀況：{financial_summary['health']} {revenue_summary}",
            "- 關鍵風險：" + self._company_risk_summary(related_findings),
            f"- 與競爭對手的估值比較：{valuation_summary} 同業 EV/EBITDA、毛利率與成長率比較仍需補資料。",
            "- 多頭情境：若需求證據延續、月營收成長改善且風險 finding 未升高，股價具備重新評價機會。",
            "- 空頭情境：若風險 finding 增加、月營收轉弱或產業瓶頸影響出貨，應降低曝險或等待資料修復。",
            "- 基本情境：維持觀察，除非資料完整度與降值風險門檻同時通過，才進入小額分批研究。",
            f"- 未來 12-24 個月展望：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            "",
            "#### 過去 5 年財務檢查",
            f"- 營收成長：{financial_summary['revenue_trend']}",
            f"- 淨利趨勢：{financial_summary['net_income_trend']}",
            f"- 自由現金流：{financial_summary['fcf_trend']}",
            f"- 利潤率：{financial_summary['margin_trend']}",
            f"- 負債水準：{financial_summary['debt_trend']}",
            f"- ROE：{financial_summary['roe_trend']}",
            f"- 財務體質判斷：{financial_summary['strength']}",
            "",
            "#### 競爭護城河",
            "- 品牌影響力：目前無足夠數據判斷；可用公司市占、客戶名單與長約資料補強。",
            "- 網路效應：多數硬體/供應鏈公司通常不是典型網路效應，需要個案證據確認。",
            "- 轉換成本：目前無足夠數據判斷；需客戶認證週期、設計導入與良率資料。",
            "- 成本優勢：目前無足夠數據判斷；需毛利率、規模與製程效率比較。",
            "- 專利或獨家技術：目前無足夠數據判斷；需專利、技術節點或客戶認證資料。",
            f"- 護城河強度：{moat_score}/10。此分數只根據目前 RAG/月營收訊號，非完整同業研究。",
            "",
            "#### 估值分析",
            f"- P/E 與同業比較：{valuation_summary}",
            "- DCF 估值：目前無足夠數據判斷；缺 5-10 年 FCF、折現率與終值假設。",
            "- 產業平均估值：目前無足夠數據判斷；需同業樣本與估值資料。",
            f"- 是否低估或高估：{self._valuation_conclusion(snapshot, valuation, peer_valuation_summary)}",
            "",
            "#### 未來成長潛力",
            f"- 市場規模與產業成長率：{self._trend_summary(related_documents, related_findings)}",
            "- 擴張機會與新產品：目前無足夠數據判斷；需法說、資本支出與產品路線圖。",
            "- AI 或技術優勢：若文本明確指向 AI 供應鏈受惠，可列為觀察點，但仍需訂單與財務驗證。",
            "- 5-10 年潛在成長空間：目前無足夠數據判斷；需要長期營收、毛利與現金流假設。",
            "",
            "#### 多空辯論",
            f"- 多頭分析師：{self._bull_case(revenue, related_documents)}",
            f"- 空頭分析師：{self._bear_case(related_findings)}",
            "- 中性結論：目前以資料完整度與風險門檻為準；缺少完整財報/估值時，不應只靠題材做重倉決策。",
            "",
            "#### 是否應該投資",
            f"- 短期展望（1 年內）：{self._near_term_outlook(revenue, related_documents, related_findings)}",
            "- 長期展望（5 年以上）：目前無足夠數據判斷；需補長期財務、產業規模與競爭格局。",
            "- 關鍵催化因素：月營收加速、客戶/訂單驗證、產能瓶頸緩解、毛利率改善。",
            "- 主要風險：" + self._company_risk_summary(related_findings),
            f"- 最終結論：{final_rating}。此結論依目前系統資料產生，不等於個人化買賣建議。",
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
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}
        lines = [
            "以下為非個人化研究建議；未納入投資人風險承受度、持股成本與資金配置，不構成個別買賣指令。",
            "",
            "| 股票 | 建議 | 理由 | 單檔上限 | 來源 |",
            "|---|---|---|---:|---|",
        ]
        for ticker in tickers:
            company = companies.get(ticker)
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            related_findings = self._related_findings(ticker, findings)
            related_documents = self._related_documents(ticker, documents)
            estimate = self._estimate_potential(related_documents, related_findings, snapshot, revenue)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
            )
            downside_gate = self._downside_gate(request)
            name = company.name if company else ticker
            rating = self._decision_label(estimate, quality, related_findings, downside_gate)
            rationale = self._decision_reason(
                rating,
                estimate,
                quality,
                related_findings,
                related_documents,
                downside_gate,
                request,
            )

            max_position = self._max_position_amount(request)
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source} {ticker}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source} {ticker}"
            lines.append(
                f"| {ticker} {name} | {rating} | {rationale} | 約 {max_position:,} 元 | {source} |"
            )
        return "\n".join(lines)

    @staticmethod
    def _company_evidence_summary(related_documents: list[NewsDocument], related_findings) -> str:
        if not related_documents and not related_findings:
            return "目前沒有足夠公司層級文本或 AI 歸因證據。"
        return f"目前有 {len(related_documents)} 筆公司相關文本、{len(related_findings)} 筆 AI 歸因證據。"

    @staticmethod
    def _company_revenue_summary(revenue: MonthlyRevenue | None) -> str:
        if not revenue:
            return "目前無月營收資料，無法判斷近期營收動能。"
        yoy = f"{revenue.yoy_pct:.2f}%" if revenue.yoy_pct is not None else "無去年同期可比資料"
        return f"{revenue.revenue_year}-{revenue.revenue_month:02d} 月營收 {revenue.revenue:,}，年增率 {yoy}。"

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
                "strength": "只依目前資料無法判斷 5 年體質變強或走弱。",
            }

        revenue = ReportGenerator._metric_series(metrics, ["營業收入", "revenue"])
        net_income = ReportGenerator._metric_series(metrics, ["本期淨利", "淨利", "net income"])
        equity = ReportGenerator._metric_series(metrics, ["權益總計", "權益", "equity"])
        liabilities = ReportGenerator._metric_series(metrics, ["負債總計", "負債", "liabilities"])
        operating_cash = ReportGenerator._metric_series(metrics, ["營業活動", "operating cash"])
        capex = ReportGenerator._metric_series(metrics, ["投資活動", "capital expenditure", "capex"])
        gross_profit = ReportGenerator._metric_series(metrics, ["營業毛利", "gross profit"])

        revenue_trend = ReportGenerator._series_trend_text(revenue, "營收")
        net_income_trend = ReportGenerator._series_trend_text(net_income, "淨利")
        fcf_trend = ReportGenerator._fcf_trend_text(operating_cash, capex)
        margin_trend = ReportGenerator._margin_text(gross_profit, net_income, revenue)
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
    def _metric_series(metrics: list[FinancialMetric], keywords: list[str]) -> dict[int, float]:
        series: dict[int, float] = {}
        for metric in metrics:
            name = f"{metric.metric} {metric.origin_name or ''}".lower()
            if not any(keyword.lower() in name for keyword in keywords):
                continue
            year = metric.report_date.year
            if year not in series or metric.report_date >= max(
                item.report_date
                for item in metrics
                if item.report_date.year == year
            ):
                series[year] = metric.value
        return dict(sorted(series.items())[-5:])

    @staticmethod
    def _series_trend_text(series: dict[int, float], label: str) -> str:
        if len(series) < 2:
            return f"{label}目前無足夠 5 年數據判斷。"
        years = sorted(series)
        first = series[years[0]]
        last = series[years[-1]]
        if first == 0:
            return f"{label}有資料但起始值為 0，無法計算成長率。"
        growth = (last - first) / abs(first) * 100
        direction = "成長" if growth > 0 else "下滑"
        return f"{years[0]} 至 {years[-1]} {label}{direction} {abs(growth):.2f}%。"

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
        return "、".join(parts) + "。" if parts else "目前無足夠數據判斷；需補毛利率、營益率與淨利率。"

    @staticmethod
    def _debt_text(liabilities: dict[int, float], equity: dict[int, float]) -> str:
        common_years = sorted(set(liabilities) & set(equity))
        if not common_years:
            return "目前無足夠數據判斷；需補資產負債表。"
        latest = common_years[-1]
        if equity[latest] == 0:
            return "負債與權益資料存在，但權益為 0，無法計算負債權益比。"
        return f"{latest} 負債權益比約 {liabilities[latest] / equity[latest]:.2f} 倍。"

    @staticmethod
    def _roe_text(net_income: dict[int, float], equity: dict[int, float]) -> str:
        common_years = sorted(set(net_income) & set(equity))
        if not common_years:
            return "目前無足夠數據判斷；需補股東權益與淨利。"
        latest = common_years[-1]
        if equity[latest] == 0:
            return "淨利與權益資料存在，但權益為 0，無法計算 ROE。"
        return f"{latest} ROE 約 {net_income[latest] / equity[latest] * 100:.2f}%。"

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
        return "相對估值：" + "；".join(parts) + "。"

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
            return "短期需優先追蹤風險 finding 是否擴大，以及月營收是否能支撐題材。"
        if revenue and revenue.yoy_pct is not None and revenue.yoy_pct > 0 and related_documents:
            return "短期具備觀察價值，但仍需確認成長是否延續到獲利與現金流。"
        if related_documents:
            return "短期已有題材文本，但缺少足夠財務驗證。"
        return "目前無足夠數據判斷。"

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
            return "目前無明確風險 finding，但缺少證據不等於沒有風險。"
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
            lines.append("LLM 補充分析未啟用；本報告目前使用規則引擎與 RAG 證據生成。")
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

    def _related_documents(self, ticker: str, documents: list[NewsDocument]) -> list[NewsDocument]:
        return [
            document
            for document in documents
            if any(match.ticker == ticker for match in self.mapper.match_document(document))
        ]

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
    ) -> str:
        if not tickers:
            return "目前無足夠數據判斷。"

        capital = request.investor_capital
        reserve = int(capital * request.cash_reserve_pct)
        deployable = capital - reserve
        max_position = self._max_position_amount(request)
        first_tranche = int(max_position * self._first_tranche_ratio(request))
        downside_gate = self._downside_gate(request)
        snapshots = {snapshot.ticker: snapshot for snapshot in market_snapshots}
        revenues = {revenue.ticker: revenue for revenue in monthly_revenues or []}
        metrics_by_ticker = self._group_financial_metrics(financial_metrics or [])
        valuations = {valuation.ticker: valuation for valuation in valuation_metrics or []}
        companies = {company.ticker: company for company in self.whitelist.companies()}

        candidate_rows = []
        allocation_candidates = []
        avoid_rows = []
        watch_rows = []
        for ticker in tickers:
            company = companies.get(ticker)
            label = f"{ticker} {company.name if company else ticker}"
            snapshot = snapshots.get(ticker)
            revenue = revenues.get(ticker)
            related_documents = self._related_documents(ticker, documents)
            related_findings = self._related_findings(ticker, findings)
            estimate = self._estimate_potential(related_documents, related_findings, snapshot, revenue)
            quality = self._data_quality_grade(
                related_documents,
                related_findings,
                snapshot,
                revenue,
                metrics_by_ticker.get(ticker, []),
                valuations.get(ticker),
                financial_metrics is not None or valuation_metrics is not None,
            )
            evidence_count = len(related_documents)
            has_structural_risk = any(
                finding.risk_type == RiskType.structural_bottleneck for finding in related_findings
            )
            source = (
                f"{snapshot.trade_date.isoformat()} {snapshot.source}"
                if snapshot
                else "目前無足夠數據判斷"
            )
            if revenue:
                source += f"；{revenue.revenue_date.isoformat()} {revenue.source}"

            if not snapshot or evidence_count < 2:
                watch_rows.append(f"- {label}：觀察。原因：資料筆數不足，暫不納入部位配置。來源：{source}。")
            elif estimate["downside_pct"] > estimate["upside_pct"] or estimate["downside_pct"] > 12:
                avoid_rows.append(
                    f"- {label}：避開或降低曝險。原因：降值風險 {estimate['downside_pct']}%，"
                    f"升值潛力 {estimate['upside_pct']}%；{self._risk_warning_reason(estimate)}來源：{source}。"
                )
            elif has_structural_risk:
                watch_rows.append(
                    f"- {label}：觀察 / 小部位研究。原因：存在結構性瓶頸證據，"
                    f"升值潛力 {estimate['upside_pct']}%，降值風險 {estimate['downside_pct']}%。來源：{source}。"
                )
            elif estimate["upside_pct"] > 10 and quality["grade"] != "supported":
                watch_rows.append(
                    f"- {label}：觀察 / 資料待補。原因：升值潛力 {estimate['upside_pct']}%，"
                    f"但資料層未完整：{'、'.join(quality['missing'])}；來源：{source}。"
                )
            elif estimate["upside_pct"] > 10 and estimate["downside_pct"] <= downside_gate:
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
                    f"單檔上限約 {max_position:,} 元；升值潛力 {estimate['upside_pct']}%，"
                    f"降值風險 {estimate['downside_pct']}%。來源：{source}。"
                )
            elif estimate["upside_pct"] > 10 and estimate["downside_pct"] > downside_gate:
                watch_rows.append(
                    f"- {label}：觀察 / 等風險降低。原因：升值潛力 {estimate['upside_pct']}%，"
                    f"但降值風險 {estimate['downside_pct']}% 已超過 {downside_gate}% "
                    f"{self._profile_label(request)}門檻；來源：{source}。"
                )
            else:
                watch_rows.append(
                    f"- {label}：觀察。原因：升值/風險差距不足；"
                    f"升值潛力 {estimate['upside_pct']}%，降值風險 {estimate['downside_pct']}%。來源：{source}。"
                )

        lines = [
            f"資金設定：總資金 {capital:,} 元以內；建議保留現金約 {reserve:,} 元，"
            f"本輪可投入資金上限約 {deployable:,} 元。",
            f"投資人設定：{self._profile_label(request)}；單檔部位上限 {request.max_position_pct:.0%}，"
            f"首筆試單約單檔上限的 {self._first_tranche_ratio(request):.0%}，"
            f"降值觀察門檻 {downside_gate}%。",
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
        lines.extend(candidate_rows or ["目前無足夠數據判斷。"])
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
                f"依升值 {candidate['upside_pct']}% / 降值 {candidate['downside_pct']}% 權重分配。"
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
        if estimate["downside_pct"] > estimate["upside_pct"]:
            return "降值風險高於升值潛力，對新手資金不適合追價。"
        return "降值風險超過新手警戒門檻 12%，即使有上行情境也不適合追價。"

    @staticmethod
    def _related_findings(ticker: str, findings) -> list:
        return [
            finding
            for finding in findings
            if any(match.ticker == ticker for match in finding.related_companies)
        ]

    @staticmethod
    def _data_quality_grade(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
        financial_metrics: list[FinancialMetric] | None = None,
        valuation: ValuationMetric | None = None,
        include_fundamentals: bool = False,
    ) -> dict:
        missing = []
        if len(related_documents) < 2:
            missing.append("公司文本不足")
        if not related_findings:
            missing.append("缺 AI 歸因")
        if not snapshot:
            missing.append("缺股價")
        if not monthly_revenue:
            missing.append("缺月營收")
        if include_fundamentals and not financial_metrics:
            missing.append("缺五年財報")
        if include_fundamentals and not valuation:
            missing.append("缺估值")

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
            notes.append(f"五年財報 {len(financial_metrics)} 筆")
        else:
            notes.append("缺五年財報")
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
    ) -> str:
        if "缺股價" in quality["missing"]:
            return "資料不足"
        if estimate["downside_pct"] > estimate["upside_pct"] or estimate["downside_pct"] > 12:
            return "避開 / 降低曝險"
        if estimate["downside_pct"] > downside_gate:
            return "觀察 / 等風險降低"
        if any(finding.risk_type == RiskType.structural_bottleneck for finding in related_findings):
            return "觀察 / 小部位研究"
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
    ) -> str:
        if rating == "資料不足":
            return "缺少可驗證市場資料。"
        if rating == "避開 / 降低曝險":
            return ReportGenerator._risk_warning_reason(estimate)
        if rating == "觀察 / 等風險降低":
            return (
                f"升值情境雖高於 10%，但降值風險已超過 {downside_gate}%，"
                f"依{ReportGenerator._profile_label(request)}設定先列觀察。"
            )
        if rating == "觀察 / 小部位研究":
            return "存在結構性瓶頸證據，只適合等待風險緩解或用很小部位追蹤。"
        if rating == "觀察":
            if any(finding.risk_type == RiskType.short_term_volatility for finding in related_findings):
                return "主要證據偏短期波動，需追蹤後續訂單、庫存與出貨變化。"
            if related_documents:
                return "已有公司相關文本證據，但尚未形成足夠的升值/風險差距。"
            return "升值/風險差距不足，先觀察。"
        if rating == "觀察 / 資料待補":
            return "升值情境高於 10%，但資料層尚未完整；" + "、".join(quality["missing"]) + "。"
        if rating == "可小額分批研究":
            return (
                f"升值情境高於 10%，降值風險未超過 {downside_gate}% 設定門檻，"
                "且資料層完整。"
            )
        return "目前只有單日價量資料，缺少新聞、財報或法說證據支撐投資結論。"

    @staticmethod
    def _estimate_potential(
        related_documents: list[NewsDocument],
        related_findings,
        snapshot: MarketSnapshot | None,
        monthly_revenue: MonthlyRevenue | None = None,
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
            }

        text = "\n".join([document.title for document in related_documents] + [finding.evidence for finding in related_findings])
        positive_keywords = ["成長", "大單", "擴產", "需求", "受惠", "看好", "上調", "旺", "爆發", "滿載"]
        negative_keywords = ["下滑", "重摔", "毛利", "禁令", "制裁", "缺電", "產能不足", "吃緊", "延遲", "鬆動", "風險"]
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

        if len(related_documents) < 2:
            confidence_notes.append(f"公司相關文本僅 {len(related_documents)} 筆")
        if not related_findings:
            confidence_notes.append("無 AI 驗證後風險/機會 finding")
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
                f"{ReportGenerator._revenue_reason(monthly_revenue, revenue_upside_bonus, True)}。"
                if upside_pct
                else "正向證據未達 >10% 情境門檻。"
            ),
            "downside_reason": (
                f"偵測到負向/瓶頸證據 {negative_hits + structural_findings + volatility_findings} 項"
                f"{ReportGenerator._revenue_reason(monthly_revenue, revenue_downside_penalty, False)}。"
                if downside_pct
                else "風險證據未達 >5% 情境門檻。"
            ),
            "upside_factors": upside_factors,
            "downside_factors": downside_factors,
            "confidence_notes": confidence_notes,
            "evidence_grade": quality["grade"],
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
