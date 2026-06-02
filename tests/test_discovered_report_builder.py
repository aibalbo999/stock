from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from app.data_sources.market import MarketFetchError
from app.models.schemas import (
    FinancialMetric,
    InvestorProfile,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportResponse,
    Source,
    ValuationMetric,
)
from app.services.discovered_report_builder import (
    DiscoveredReportBuilderService,
    leading_signal_covered_count,
)


def test_leading_signal_covered_count_counts_each_ticker_once() -> None:
    count = leading_signal_covered_count(
        ["2330", "2382", "3231"],
        [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200)],
        [MonthlyRevenue(ticker="2382", revenue_date=date(2026, 4, 30), revenue=100, revenue_year=2026, revenue_month=4)],
        [
            ValuationMetric(ticker="2330", trade_date=date(2026, 5, 29), pe_ratio=20),
            ValuationMetric(ticker="3231", trade_date=date(2026, 5, 29), pb_ratio=2),
        ],
    )

    assert count == 3


def test_discovered_report_builder_builds_single_source_of_truth_payload() -> None:
    captured = {}
    formal_document = NewsDocument(
        id="formal-1",
        title="台積電 CoWoS 產能擴張",
        text="台積電 CoWoS 產能擴張，並有月營收資料支持。",
        source=Source(title="台積電 CoWoS 產能擴張", publisher="經濟日報", published_at=date(2026, 5, 1)),
    )
    forum_document = NewsDocument(
        id="forum-1",
        title="1815 富喬-追買低檔群創也不要去追高高檔的富喬住套房-股市爆料同學會",
        text="散戶閒聊。",
        source=Source(
            title="1815 富喬-股市爆料同學會",
            publisher="股市爆料同學會",
            published_at=date(2026, 5, 2),
        ),
    )

    class FakeReport:
        id = 42

    class FakeReportRepository:
        def __init__(self, session):
            self.session = session

        def create(self, request, response):
            captured["stored_request"] = request
            captured["stored_response"] = response
            return FakeReport()

    class FakeGenerator:
        def __init__(self, whitelist=None):
            self.whitelist = whitelist
            self.last_llm_result = SimpleNamespace(fallback=False, model="gpt-test", provider="test", key_index=0)
            self.last_evidence_documents = []
            self.last_excluded_low_quality_documents = []
            self.last_filtered_tickers = []
            self.last_dropped_tickers = []

        def generate(self, request, documents):
            captured["generator_whitelist"] = self.whitelist
            captured["generated_request"] = request
            captured["generated_documents"] = documents
            self.last_evidence_documents = documents
            return ReportResponse(title="AI report", markdown="body")

    def fake_quality_gate(source_audit, promoted_tickers, **kwargs):
        captured["quality_source_audit"] = source_audit
        captured["quality_promoted_tickers"] = promoted_tickers
        captured["quality_kwargs"] = kwargs
        return {
            "status": "ready",
            "metrics": {
                "market_count": kwargs["market_count"],
                "leading_signal_count": kwargs["leading_signal_count"],
            },
        }

    def fake_attach(response, quality_gate):
        return response.model_copy(
            update={
                "markdown": f"{response.markdown}\nquality-ready",
                "quality_gate": quality_gate,
            }
        )

    def fake_source_quality(documents, lookback_days):
        captured["source_quality_document_ids"] = [document.id for document in documents]
        captured["source_quality_lookback_days"] = lookback_days
        return {"document_count": len(documents), "fresh_ratio": 1.0}

    @contextmanager
    def fake_session_scope():
        yield object()

    payload = SimpleNamespace(
        topic="機器人",
        lookback_days=14,
        analysis_mode="standard",
        deep_analysis=False,
        investor_capital=180_000,
        beginner_mode=False,
        investor_profile=InvestorProfile.aggressive,
        max_position_pct=0.12,
        cash_reserve_pct=0.25,
    )
    market_data = {
        "snapshots": [
            MarketSnapshot(
                ticker="2308",
                trade_date=date(2026, 5, 29),
                close=900,
                source="FinMind TaiwanStockPrice; cached-stale",
            ),
        ],
        "price_history_snapshots": [
            MarketSnapshot(ticker="2308", trade_date=date(2026, 5, 28), close=880),
            MarketSnapshot(
                ticker="2308",
                trade_date=date(2026, 5, 29),
                close=900,
                source="FinMind TaiwanStockPrice; cached-stale",
            ),
        ],
        "market_errors": [MarketFetchError(ticker="1504", dataset="TaiwanStockPrice", error="timeout")],
        "monthly_revenues": [
            MonthlyRevenue(
                ticker="1504",
                revenue_date=date(2026, 4, 30),
                revenue=200,
                revenue_year=2026,
                revenue_month=4,
                source="FinMind TaiwanStockMonthRevenue; cached-stale",
            ),
        ],
        "monthly_revenue_errors": [],
        "latest_monthly_revenues": [
            MonthlyRevenue(
                ticker="1504",
                revenue_date=date(2026, 4, 30),
                revenue=200,
                revenue_year=2026,
                revenue_month=4,
                source="FinMind TaiwanStockMonthRevenue; cached-stale",
            ),
        ],
        "financial_metrics": [
            FinancialMetric(
                ticker="2308",
                report_date=date(2026, 3, 31),
                statement_type="income",
                metric="revenue",
                value=1000,
                source="FinMind TaiwanStockFinancialStatements; cached-stale",
            )
        ],
        "financial_metric_errors": [],
        "valuations": [
            ValuationMetric(
                ticker="1504",
                trade_date=date(2026, 5, 29),
                pb_ratio=1.5,
                source="FinMind TaiwanStockPER; cached-stale",
            ),
        ],
        "valuation_errors": [],
    }

    service = DiscoveredReportBuilderService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        report_generator_cls=FakeGenerator,
        build_report_quality_gate_func=fake_quality_gate,
        attach_quality_gate_to_report_func=fake_attach,
        summarize_document_source_quality_func=fake_source_quality,
        count_sufficient_company_filings_func=lambda tickers: 2,
    )

    result = service.build_and_store_report(
        payload=payload,
        promoted_tickers=["2308", "1504"],
        dynamic_whitelist=SimpleNamespace(name="dynamic"),
        documents=[formal_document, forum_document],
        evidence_limit=80,
        source_audit={"plan_quality": {"status": "complete"}},
        discovery={"plan": {"candidate_companies": []}},
        urls=["https://example.com/rss"],
        ingestion_results=[{"count": 2}],
        fixed_source_ingestion={"count": 1},
        dynamic_query_ingestion=[{"count": 1}],
        candidate_filing_ingestion={"requested_tickers": ["2308", "1504"]},
        company_filing_ingestion={"requested_tickers": ["2308", "1504"]},
        candidate_payload=[{"ticker": "2308"}, {"ticker": "1504"}],
        market_data=market_data,
    )

    run_payload = result["run_payload"]

    assert result["report_id"] == 42
    assert result["quality_gate"]["status"] == "ready"
    assert result["report_execution"]["evidence_count"] == 2
    assert captured["generator_whitelist"].name == "dynamic"
    assert captured["generated_request"].tickers == ["2308", "1504"]
    assert captured["generated_request"].lookback_days == 60
    assert captured["source_quality_document_ids"] == ["formal-1"]
    assert captured["source_quality_lookback_days"] == 60
    assert captured["quality_kwargs"]["market_count"] == 1
    assert captured["quality_kwargs"]["monthly_revenue_count"] == 1
    assert captured["quality_kwargs"]["financial_metrics_count"] == 1
    assert captured["quality_kwargs"]["valuation_count"] == 1
    assert captured["quality_kwargs"]["leading_signal_count"] == 2
    assert captured["quality_kwargs"]["company_filing_sufficient_count"] == 2
    assert captured["quality_kwargs"]["market_stale_count"] == 1
    assert captured["quality_kwargs"]["monthly_revenue_stale_count"] == 1
    assert captured["quality_kwargs"]["financial_metrics_stale_ticker_count"] == 1
    assert captured["quality_kwargs"]["valuation_stale_count"] == 1
    assert run_payload["request"]["topic"] == "機器人"
    assert run_payload["market_history_days"] == 240
    assert run_payload["market_history_count"] == 2
    assert run_payload["market_stale_count"] == 1
    assert run_payload["market_errors"] == [
        {"ticker": "1504", "dataset": "TaiwanStockPrice", "error": "timeout"}
    ]
    assert run_payload["monthly_revenue_stale_count"] == 1
    assert run_payload["financial_metrics_stale_ticker_count"] == 1
    assert run_payload["valuation_stale_count"] == 1
    assert run_payload["quality_gate"] == result["quality_gate"]
    assert run_payload["report_execution"] == result["report_execution"]
    assert captured["stored_response"].quality_gate == result["quality_gate"]
