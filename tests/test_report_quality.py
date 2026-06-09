from datetime import date
from pathlib import Path

from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    ReportResponse,
    ValuationMetric,
)
from app.services.llm_client import LLMResult
from app.services import report_quality, report_quality_runtime
from app.services import report_quality_recovery
from app.services import report_quality_llm_rules
from app.services import report_quality_market_rules
from app.services import report_quality_plan_rules
from app.services import report_quality_rag_rules
from app.services import report_quality_relevance_rules
from app.services import report_quality_sources
from app.services import report_quality_action_policy
from app.services import report_quality_coverage_rules
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_report_quality_gate,
    market_provider_summary,
    market_trade_date_summary,
    parse_quality_gate_from_markdown,
    render_quality_action_guard_markdown,
    render_quality_gate_markdown,
    should_recover_market_data_quality,
    summarize_llm_status,
)


def test_quality_recovery_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    recovery_source = Path("app/services/report_quality_recovery.py").read_text()

    assert (
        should_recover_market_data_quality
        is report_quality_recovery.should_recover_market_data_quality
    )
    assert "def should_recover_market_data_quality" not in report_quality_source
    assert "def quality_remediation_actions" not in report_quality_source
    assert "def should_recover_market_data_quality" in recovery_source
    assert "def quality_remediation_actions" in recovery_source


def test_report_quality_runtime_helpers_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    runtime_source = Path("app/services/report_quality_runtime.py").read_text()

    assert report_quality.summarize_llm_status is report_quality_runtime.summarize_llm_status
    assert report_quality.rag_runtime_status is report_quality_runtime.rag_runtime_status
    for helper in [
        "def summarize_llm_status(",
        "def rag_runtime_status(",
        "def _rag_persistent_collection_enabled(",
        "def _module_available(",
    ]:
        assert helper not in report_quality_source
        assert helper in runtime_source
    assert "RagReranker" not in report_quality_source
    assert "VectorStore.runtime_embedding_provider_status(" not in report_quality_source


def test_report_quality_rag_warning_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    rag_rules_source = Path("app/services/report_quality_rag_rules.py").read_text()

    assert report_quality.rag_quality_warnings is report_quality_rag_rules.rag_quality_warnings
    assert "def rag_quality_warnings(" in rag_rules_source
    assert "RAG reranker 目前僅使用關鍵字排序" in rag_rules_source
    assert "RAG 自訂 embedding 未啟用" in rag_rules_source
    assert "RAG reranker 目前僅使用關鍵字排序" not in report_quality_source
    assert "RAG 自訂 embedding 未啟用" not in report_quality_source


def test_report_quality_llm_warning_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    llm_rules_source = Path("app/services/report_quality_llm_rules.py").read_text()

    assert report_quality.llm_quality_notes is report_quality_llm_rules.llm_quality_notes
    assert "def llm_quality_notes(" in llm_rules_source
    assert "LLM 補充分析未啟用或呼叫失敗" in llm_rules_source
    assert "LLM 補充分析已完成，但曾經重試或切換備援模型" in llm_rules_source
    assert "LLM 補充分析未啟用或呼叫失敗" not in report_quality_source
    assert "LLM 補充分析已完成，但曾經重試或切換備援模型" not in report_quality_source


def test_report_quality_plan_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    plan_rules_source = Path("app/services/report_quality_plan_rules.py").read_text()

    assert (
        report_quality.discovery_plan_quality_notes
        is report_quality_plan_rules.discovery_plan_quality_notes
    )
    assert "def discovery_plan_quality_notes(" in plan_rules_source
    assert "AI 拆解任務品質不足" in plan_rules_source
    assert "AI 拆解任務仍有缺口" in plan_rules_source
    assert "AI 拆解任務品質不足" not in report_quality_source
    assert "AI 拆解任務仍有缺口" not in report_quality_source


def test_report_quality_source_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    source_rules_source = Path("app/services/report_quality_sources.py").read_text()

    assert report_quality.source_quality_notes is report_quality_sources.source_quality_notes
    assert "def source_quality_notes(" in source_rules_source
    assert "來源時間戳覆蓋率低於 50%" in source_rules_source
    assert "資料來源發布者過於單一" in source_rules_source
    assert "高可信來源比例偏低" in source_rules_source
    assert "來源時間戳覆蓋率低於 50%" not in report_quality_source
    assert "資料來源發布者過於單一" not in report_quality_source
    assert "高可信來源比例偏低" not in report_quality_source


def test_report_quality_relevance_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    relevance_rules_source = Path("app/services/report_quality_relevance_rules.py").read_text()

    assert (
        report_quality.adjusted_source_relevance_counts
        is report_quality_relevance_rules.adjusted_source_relevance_counts
    )
    assert (
        report_quality.source_relevance_notes
        is report_quality_relevance_rules.source_relevance_notes
    )
    assert "def adjusted_source_relevance_counts(" in relevance_rules_source
    assert "def source_relevance_notes(" in relevance_rules_source
    assert "AI 拆解子題仍有" in relevance_rules_source
    assert "主題拆解仍有" in relevance_rules_source
    assert "is_financial_subtopic" not in report_quality_source
    assert "AI 拆解子題仍有" not in report_quality_source


def test_report_quality_market_rescue_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    market_rules_source = Path("app/services/report_quality_market_rules.py").read_text()

    assert (
        report_quality.market_rescue_quality_notes
        is report_quality_market_rules.market_rescue_quality_notes
    )
    assert (
        report_quality.market_coverage_quality_notes
        is report_quality_market_rules.market_coverage_quality_notes
    )
    assert (
        report_quality.market_trade_date_quality_notes
        is report_quality_market_rules.market_trade_date_quality_notes
    )
    assert "def market_coverage_quality_notes(" in market_rules_source
    assert "def market_trade_date_quality_notes(" in market_rules_source
    assert "def market_rescue_quality_notes(" in market_rules_source
    assert "股價資料覆蓋率低於 50%" in market_rules_source
    assert "股價日期不一致" in market_rules_source
    assert "部分股票未取得資料庫最新交易日股價" in market_rules_source
    assert "月營收資料覆蓋偏低" in market_rules_source
    assert "部分市場或財務資料使用快取救援" in market_rules_source
    assert "部分市場或財務資料只使用官方最新救援資料" in market_rules_source
    assert "股價資料覆蓋率低於 50%" not in report_quality_source
    assert "股價日期不一致" not in report_quality_source
    assert "部分股票未取得資料庫最新交易日股價" not in report_quality_source
    assert "月營收資料覆蓋偏低" not in report_quality_source
    assert "部分市場或財務資料使用快取救援" not in report_quality_source
    assert "部分市場或財務資料只使用官方最新救援資料" not in report_quality_source


def test_report_quality_action_policy_lives_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    action_policy_source = Path("app/services/report_quality_action_policy.py").read_text()

    assert (
        report_quality.quality_gate_action_policy
        is report_quality_action_policy.quality_gate_action_policy
    )
    assert "def quality_gate_action_policy(" in action_policy_source
    assert "僅供研究，不允許投入資金" in action_policy_source
    assert "需人工覆核，最多只可動用可投入資金的 25%" in action_policy_source
    assert "quality_gate_action_policy(" in report_quality_source
    assert "max_deployable_multiplier = 0.25" not in report_quality_source
    assert "deployable_base = max(" not in report_quality_source


def test_report_quality_coverage_rules_live_outside_quality_gate_module() -> None:
    report_quality_source = Path("app/services/report_quality.py").read_text()
    coverage_rules_source = Path("app/services/report_quality_coverage_rules.py").read_text()

    assert (
        report_quality.coverage_quality_notes
        is report_quality_coverage_rules.coverage_quality_notes
    )
    assert "def coverage_quality_notes(" in coverage_rules_source
    assert "近況訊號覆蓋偏低" in coverage_rules_source
    assert "公司公開文件覆蓋率低於 50%" in coverage_rules_source
    assert "近況訊號覆蓋偏低" not in report_quality_source
    assert "公司公開文件覆蓋率低於 50%" not in report_quality_source


def _quality_gate(
    *,
    candidate_support: dict | None = None,
    dynamic_stored_count: int = 24,
    promoted_tickers: list[str] | None = None,
    source_audit_extra: dict | None = None,
    **kwargs,
) -> dict:
    promoted_tickers = ["2330"] if promoted_tickers is None else promoted_tickers
    source_audit = {
        "candidate_support": candidate_support
        or {
            "supported_ratio": 1.0,
            "formal_confidence_avg": 88.5,
            "formal_confidence_min": 80,
        },
        "dynamic_queries": {"stored_count": dynamic_stored_count},
    }
    if source_audit_extra:
        source_audit.update(source_audit_extra)

    defaults = {
        "market_count": len(promoted_tickers),
        "monthly_revenue_count": len(promoted_tickers),
        "financial_metrics_count": len(promoted_tickers) * 12,
        "valuation_count": len(promoted_tickers),
    }
    defaults.update(kwargs)
    return build_report_quality_gate(source_audit, promoted_tickers, **defaults)


def test_market_provider_summary_groups_sources_and_stale_counts() -> None:
    summary = market_provider_summary(
        [
            MarketSnapshot(
                ticker="2330",
                trade_date=date(2026, 5, 29),
                close=1000,
                source="Fugle historical stats",
            ),
            MarketSnapshot(
                ticker="2382",
                trade_date=date(2026, 5, 29),
                close=300,
                source="FinMind TaiwanStockPrice; cached-stale",
            ),
            MarketSnapshot(
                ticker="2454",
                trade_date=date(2026, 5, 29),
                close=1200,
                source="TWSE OpenAPI STOCK_DAY_ALL; latest-only",
            ),
        ],
        [
            MonthlyRevenue(
                ticker="2330",
                revenue_date=date(2026, 4, 10),
                revenue=100,
                revenue_year=2026,
                revenue_month=4,
                source="FinMind TaiwanStockMonthRevenue",
            )
        ],
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營業收入",
                value=100.0,
                source="FinMind TaiwanStockFinancialStatements",
            )
        ],
        [
            ValuationMetric(
                ticker="2330",
                trade_date=date(2026, 5, 29),
                pe_ratio=20,
                source="FinMind TaiwanStockPER",
            )
        ],
    )

    assert summary["price_history"]["providers"] == ["Fugle", "FinMind", "TWSE OpenAPI"]
    assert summary["price_history"]["stale_count"] == 1
    assert summary["price_history"]["latest_only_count"] == 1
    assert summary["monthly_revenue"]["providers"] == ["FinMind"]
    assert summary["financial_metrics"]["row_count"] == 1
    assert summary["valuation"]["sources"] == ["FinMind TaiwanStockPER"]


def test_quality_gate_markdown_includes_market_provider_summary() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 12}},
        ["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=8,
        valuation_count=1,
        market_provider_summary={
            "price_history": {
                "label": "股價",
                "providers": ["Fugle"],
                "stale_count": 0,
                "latest_only_count": 0,
            },
            "monthly_revenue": {
                "label": "月營收",
                "providers": ["TWSE OpenAPI"],
                "stale_count": 0,
                "latest_only_count": 1,
            },
            "financial_metrics": {"label": "五年財務", "providers": ["FinMind"], "stale_count": 0},
            "valuation": {
                "label": "估值",
                "providers": ["FinMind"],
                "stale_count": 1,
                "latest_only_count": 0,
            },
        },
        monthly_revenue_latest_only_count=1,
    )

    markdown = render_quality_gate_markdown(gate)

    assert (
        "市場資料來源：股價 Fugle；月營收 TWSE OpenAPI（含官方最新救援 1 筆）；"
        "五年財務 FinMind；估值 FinMind（含快取救援 1 筆）"
    ) in markdown
    assert "官方最新救援資料：股價 0 檔、月營收 1 檔、五年財務 0 檔、估值 0 檔" in markdown
    assert "不能代表完整歷史趨勢" in "；".join(gate["warnings"])
    assert gate["metrics"]["market_provider_summary"]["price_history"]["providers"] == ["Fugle"]


def test_quality_gate_warns_when_report_prices_lag_database_latest_date() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 12}},
        ["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=16,
        valuation_count=2,
        market_latest_trade_date=date(2026, 6, 1),
        market_latest_trade_date_coverage=0.5,
        market_database_latest_trade_date=date(2026, 6, 5),
        market_older_than_database_latest_count=1,
        market_max_trade_date_lag_days=4,
    )

    markdown = render_quality_gate_markdown(gate)

    assert "股價日期不一致" in "；".join(gate["warnings"])
    assert "最新可取得交易日：2026-06-01" in markdown
    assert "同日覆蓋率 50%" in markdown
    assert should_recover_market_data_quality(gate) is True


def test_quality_gate_treats_one_day_market_date_lag_as_observation() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 20}},
        ["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=16,
        valuation_count=2,
        market_latest_trade_date=date(2026, 6, 5),
        market_latest_trade_date_coverage=0.5,
        market_database_latest_trade_date=date(2026, 6, 5),
        market_older_than_database_latest_count=1,
        market_max_trade_date_lag_days=1,
    )

    issue_text = "；".join(gate["warnings"])
    observation_text = "；".join(gate["observations"])
    plan = gate["self_healing"]

    assert gate["status"] == "ready"
    assert "股價日期不一致" not in issue_text
    assert "資料庫最新交易日股價" not in issue_text
    assert "股價日期略有差異" in observation_text
    assert gate["metrics"]["market_trade_date_lag_days"] == 1
    assert gate["metrics"]["market_trade_date_warning_suppressed"] is True
    assert should_recover_market_data_quality(gate) is False
    assert "market_data_gap" not in plan["triggers"]
    assert not any(action["action_type"] == "refresh_market" for action in plan["actions"])


def test_quality_gate_records_llm_observability_metrics() -> None:
    llm_status = summarize_llm_status(
        LLMResult(
            text="分析完成",
            model="gemini-2.5-flash",
            provider="gemini",
            attempts=(
                {
                    "provider": "gemini",
                    "model": "gemini-3.5-flash",
                    "outcome": "sdk_error",
                    "status": 429,
                },
                {
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "outcome": "success",
                    "attempt": 1,
                },
            ),
            observability={
                "latency_ms": 123.4,
                "input_token_estimate": 120,
                "output_token_estimate": 34,
                "total_token_estimate": 154,
                "estimated_cost_usd": 0.001234,
                "cost_tracking_mode": "configured_rate_card",
            },
        )
    )
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 20}},
        ["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=8,
        valuation_count=1,
        llm_status=llm_status,
    )

    metrics = gate["metrics"]
    markdown = render_quality_gate_markdown(gate)

    assert metrics["llm_model_fallback_used"] is True
    assert metrics["llm_primary_failure_category"] == "rate_limited"
    assert metrics["llm_total_token_estimate"] == 154
    assert metrics["llm_estimated_cost_usd"] == 0.001234
    assert "已切換備援模型" in markdown
    assert "token估算：154" in markdown
    assert "估算成本：$0.001234" in markdown


def test_quality_gate_adds_self_healing_plan_for_recoverable_gaps() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 4}},
        ["2330"],
        market_count=0,
        monthly_revenue_count=0,
        financial_metrics_count=0,
        valuation_count=0,
        monthly_revenue_stale_count=1,
    )

    plan = gate["self_healing"]
    action_types = [action["action_type"] for action in plan["actions"]]

    assert plan["status"] == "planned"
    assert "ingest_news" in action_types
    assert "refresh_market" in action_types
    assert "refresh_monthly_revenue" in action_types
    assert action_types[-1] == "rerun_analysis"
    assert "自癒補強計畫" in render_quality_gate_markdown(gate)


def test_quality_gate_self_healing_plans_market_recovery_for_trade_date_mismatch() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 20}},
        ["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=16,
        valuation_count=2,
        market_latest_trade_date=date(2026, 6, 2),
        market_latest_trade_date_coverage=0.5,
        market_database_latest_trade_date=date(2026, 6, 5),
        market_older_than_database_latest_count=1,
        market_max_trade_date_lag_days=3,
    )

    plan = gate["self_healing"]

    assert should_recover_market_data_quality(gate) is True
    assert "market_data_gap" in plan["triggers"]
    assert any(action["action_type"] == "refresh_market" for action in plan["actions"])


def test_market_trade_date_summary_counts_tickers_older_than_database_latest_date() -> None:
    summary = market_trade_date_summary(
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 6, 1), close=1000),
            MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 29), close=300),
        ],
        ["2330", "2382"],
        date(2026, 6, 1),
    )

    assert summary["latest_trade_date"] == date(2026, 6, 1)
    assert summary["latest_trade_date_coverage"] == 0.5
    assert summary["older_than_database_latest_count"] == 1
    assert summary["max_trade_date_lag_days"] == 3


def test_report_quality_gate_blocks_undated_sources() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.8},
        dynamic_stored_count=12,
        source_quality={
            "unique_publisher_count": 3,
            "timestamp_coverage": 0.25,
            "recent_coverage": 0.8,
        },
    )

    assert gate["status"] == "insufficient"
    assert "來源時間戳覆蓋率低於 50%" in gate["blockers"]


def test_report_quality_gate_warns_on_low_source_diversity() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.8},
        dynamic_stored_count=12,
        source_quality={
            "unique_publisher_count": 2,
            "timestamp_coverage": 1,
            "recent_coverage": 1,
        },
    )

    assert gate["status"] == "caution"
    assert "資料來源多樣性偏低" in gate["warnings"]


def test_report_quality_gate_warns_when_low_credibility_sources_dominate() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 1.0},
        dynamic_stored_count=12,
        source_quality={
            "unique_publisher_count": 4,
            "timestamp_coverage": 1,
            "recent_coverage": 1,
            "high_credibility_ratio": 0.25,
            "low_credibility_ratio": 0.58,
        },
    )

    assert gate["status"] == "caution"
    assert "高可信來源比例偏低，正式結論需補官方文件或主流財經新聞" in gate["warnings"]
    assert "投資網誌或社群型來源比例偏高，不能直接支撐高可信投資理由" in gate["warnings"]


def test_report_quality_gate_blocks_weak_research_inputs() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.4},
        dynamic_stored_count=5,
        promoted_tickers=[],
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "insufficient"
    assert gate["action_policy"]["policy"] == "research_only"
    assert gate["action_policy"]["max_deployable_amount"] == 0
    assert "沒有通過證據驗證的正式分析股票" in gate["blockers"]
    assert "候選公司證據覆蓋率低於 60%" in gate["blockers"]


def test_report_quality_gate_blocks_missing_subtopic_sources() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 1.0},
        source_audit_extra={
            "source_relevance": {
                "missing_subtopic_count": 1,
                "weak_subtopic_count": 2,
            }
        },
    )

    assert gate["status"] == "insufficient"
    assert "AI 拆解子題仍有 1 個完全缺少相關來源" in gate["blockers"]
    assert "AI 拆解子題仍有 2 個來源或資料意圖不足" in gate["warnings"]
    assert gate["metrics"]["missing_subtopic_count"] == 1
    assert gate["metrics"]["weak_subtopic_count"] == 2
    assert any("針對缺來源或弱來源子題" in action for action in gate["remediation_actions"])


def test_report_quality_gate_treats_weak_subtopics_as_observation_when_sources_are_broad() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 1.0},
        dynamic_stored_count=160,
        source_audit_extra={"source_relevance": {"weak_subtopic_count": 2}},
        source_quality={
            "unique_publisher_count": 35,
            "timestamp_coverage": 1.0,
            "recent_coverage": 1.0,
        },
        company_filing_sufficient_count=1,
    )

    assert gate["status"] == "ready"
    assert gate["warnings"] == []
    assert "主題拆解仍有 2 個子題可持續追蹤" in gate["observations"][0]


def test_report_quality_gate_passes_complete_research_inputs() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 0.8,
            "formal_confidence_avg": 88.5,
            "formal_confidence_min": 80,
        },
        promoted_tickers=["2330", "2382"],
        financial_metrics_count=20,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "ready"
    assert gate["action_policy"]["policy"] == "actionable"
    assert gate["action_policy"]["max_deployable_amount"] == 700_000
    assert gate["blockers"] == []
    assert gate["warnings"] == []


def test_report_quality_gate_warns_when_company_filings_are_missing() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 1.0},
        promoted_tickers=["2330", "2382"],
        financial_metrics_count=20,
        company_filing_sufficient_count=0,
    )

    assert gate["status"] == "caution"
    assert "公司公開文件覆蓋率低於 50%，正式投入前需補年報或法說會" in gate["warnings"]
    assert gate["metrics"]["company_filing_coverage"] == 0


def test_report_quality_gate_warns_when_llm_falls_back() -> None:
    gate = _quality_gate(
        llm_status={
            "fallback": True,
            "model": None,
            "key_index": None,
            "provider": "litellm",
            "attempt_summary": {
                "attempt_count": 2,
                "primary_failure_category": "rate_limited",
                "retryable_failure_count": 2,
            },
        },
    )

    assert gate["status"] == "caution"
    assert "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿" in gate["warnings"]
    assert gate["metrics"]["llm_analysis_status"] == "fallback"
    assert gate["metrics"]["llm_provider"] == "litellm"
    assert gate["metrics"]["llm_attempt_count"] == 2
    assert gate["metrics"]["llm_primary_failure_category"] == "rate_limited"
    assert gate["metrics"]["llm_retryable_failure_count"] == 2
    assert any("檢查 LLM API key" in action for action in gate["remediation_actions"])


def test_report_quality_gate_warns_when_rag_embedding_falls_back() -> None:
    gate = _quality_gate(
        rag_status={
            "use_chroma": True,
            "chroma_available": True,
            "persistent_collection_enabled": False,
            "retrieval_mode": "memory_hybrid",
            "embedding_status": {
                "provider": "sentence_transformers",
                "custom_embedding_requested": True,
                "custom_embedding_enabled": False,
                "chroma_default_fallback_allowed": False,
                "fallback_reason": "missing_dependency:sentence_transformers",
            },
            "reranker_status": {
                "provider": "keyword",
                "normalized_provider": "keyword",
                "available": True,
                "execution_mode": "keyword",
                "fallback_reason": None,
            },
            "retrieval_status": {
                "strategy": "hybrid-vector-bm25",
                "hybrid_search_enabled": True,
                "bm25_enabled": True,
                "keyword_corpus_limit": 2000,
                "vector_weight": 0.6,
                "keyword_weight": 0.4,
                "rerank_top_k": 40,
            },
        },
    )

    assert gate["status"] == "caution"
    assert "RAG 自訂 embedding 未啟用，已停用持久化向量庫並退回關鍵字檢索" in gate["warnings"]
    assert gate["metrics"]["rag_embedding_enabled"] is False
    assert (
        gate["metrics"]["rag_embedding_fallback_reason"]
        == "missing_dependency:sentence_transformers"
    )
    assert gate["metrics"]["rag_retrieval_strategy"] == "hybrid-vector-bm25"
    assert gate["metrics"]["rag_bm25_enabled"] is True
    assert gate["metrics"]["rag_keyword_corpus_limit"] == 2000
    assert gate["metrics"]["rag_vector_weight"] == 0.6
    assert gate["metrics"]["rag_keyword_weight"] == 0.4
    assert gate["metrics"]["rag_rerank_top_k"] == 40
    assert any("檢查 RAG embedding" in action for action in gate["remediation_actions"])


def test_report_quality_gate_warns_when_cross_encoder_reranker_falls_back() -> None:
    gate = _quality_gate(
        rag_status={
            "use_chroma": True,
            "chroma_available": True,
            "persistent_collection_enabled": True,
            "retrieval_mode": "chroma_hybrid",
            "embedding_status": {
                "provider": "sentence_transformers",
                "custom_embedding_requested": True,
                "custom_embedding_enabled": True,
                "fallback_reason": None,
            },
            "reranker_status": {
                "provider": "bge",
                "normalized_provider": "bge",
                "available": False,
                "execution_mode": "input_order_fallback",
                "fallback_reason": "missing_dependency:sentence_transformers",
            },
        },
    )

    assert gate["status"] == "caution"
    assert "RAG reranker 未啟用或推論失敗，檢索排序信心需人工覆核" in gate["warnings"]
    assert gate["metrics"]["rag_reranker_available"] is False
    assert gate["metrics"]["rag_reranker_model_ready"] is False
    assert (
        gate["metrics"]["rag_reranker_fallback_reason"]
        == "missing_dependency:sentence_transformers"
    )


def test_report_quality_gate_warns_when_reranker_is_keyword_only() -> None:
    gate = _quality_gate(
        rag_status={
            "use_chroma": True,
            "chroma_available": True,
            "persistent_collection_enabled": True,
            "retrieval_mode": "chroma_hybrid",
            "embedding_status": {
                "provider": "sentence_transformers",
                "custom_embedding_requested": True,
                "custom_embedding_enabled": True,
                "fallback_reason": None,
            },
            "reranker_status": {
                "provider": "keyword",
                "normalized_provider": "keyword",
                "available": True,
                "execution_mode": "keyword",
                "quality_tier": "lexical_fallback",
                "keyword_fallback": True,
                "model_reranker_ready": False,
                "model_reranker_gap": "keyword_provider_selected",
                "fallback_reason": None,
            },
        },
    )

    assert gate["status"] == "caution"
    assert (
        "RAG reranker 目前僅使用關鍵字排序，尚未啟用模型級重排序，來源排序信心需人工覆核"
        in gate["warnings"]
    )
    assert gate["metrics"]["rag_reranker_available"] is True
    assert gate["metrics"]["rag_reranker_model_ready"] is False
    assert gate["metrics"]["rag_reranker_keyword_fallback"] is True
    assert gate["metrics"]["rag_reranker_model_gap"] == "keyword_provider_selected"


def test_report_quality_gate_warns_when_market_data_uses_stale_cache() -> None:
    gate = _quality_gate(
        market_stale_count=1,
        monthly_revenue_stale_count=1,
        financial_metrics_stale_ticker_count=1,
        valuation_stale_count=1,
    )

    assert gate["status"] == "caution"
    assert "部分市場或財務資料使用快取救援，需刷新確認最新資料" in gate["warnings"]
    assert gate["metrics"]["stale_market_dataset_count"] == 4
    assert gate["metrics"]["market_fresh_coverage"] == 0
    assert any("快取救援資料只能作暫時參考" in action for action in gate["remediation_actions"])


def test_report_quality_gate_records_enabled_llm_as_observation() -> None:
    gate = _quality_gate(
        llm_status={
            "fallback": False,
            "model": "gemini-test",
            "key_index": 2,
            "provider": "google_genai",
            "attempt_summary": {"attempt_count": 1, "retryable_failure_count": 0},
        },
    )

    assert gate["status"] == "ready"
    assert gate["metrics"]["llm_analysis_status"] == "enabled"
    assert gate["metrics"]["llm_model"] == "gemini-test"
    assert gate["metrics"]["llm_key_index"] == 2
    assert gate["metrics"]["llm_provider"] == "google_genai"
    assert gate["metrics"]["llm_attempt_count"] == 1
    assert "LLM 補充分析已完成，且仍受來源與白名單驗證約束" in gate["observations"]


def test_report_quality_gate_discloses_llm_recovery_path() -> None:
    gate = _quality_gate(
        llm_status={
            "fallback": False,
            "model": "gemini/gemini-backup",
            "provider": "litellm",
            "attempt_summary": {
                "attempt_count": 2,
                "failed_attempt_count": 1,
                "success_after_failure": True,
                "retry_used": False,
                "fallback_path_used": True,
                "provider_fallback_used": False,
                "model_fallback_used": True,
                "primary_failure_category": "rate_limited",
                "retryable_failure_count": 1,
                "final_outcome": "success",
            },
        },
    )

    assert gate["status"] == "ready"
    assert gate["metrics"]["llm_analysis_status"] == "enabled"
    assert gate["metrics"]["llm_failed_attempt_count"] == 1
    assert gate["metrics"]["llm_success_after_failure"] is True
    assert gate["metrics"]["llm_fallback_path_used"] is True
    assert (
        "LLM 補充分析已完成，但曾經重試或切換備援模型；模型穩定性需持續觀察" in gate["observations"]
    )


def test_report_quality_gate_blocks_low_confidence_formal_stocks() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 1.0,
            "formal_supported_ratio": 1.0,
            "formal_confidence_avg": 72,
            "formal_confidence_min": 68,
            "formal_low_confidence_count": 1,
        }
    )

    assert gate["status"] == "insufficient"
    assert "正式分析股票含低信心證據公司" in gate["blockers"]
    assert gate["metrics"]["formal_confidence_avg"] == 72
    assert any("低信心正式股票" in action for action in gate["remediation_actions"])


def test_report_quality_gate_treats_broad_candidate_list_as_observation_after_promotion() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 0.4,
            "exploration_supported_ratio": 0.4,
            "formal_supported_ratio": 1.0,
        },
        promoted_tickers=["2330", "2382"],
        financial_metrics_count=20,
    )

    assert gate["status"] == "ready"
    assert gate["blockers"] == []
    assert gate["warnings"] == []
    assert "AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票" in gate["observations"]
    assert gate["metrics"]["candidate_supported_ratio"] == 1.0
    assert gate["metrics"]["exploration_candidate_supported_ratio"] == 0.4
    assert gate["remediation_actions"] == []


def test_report_quality_gate_accepts_diffuse_exploration_when_formal_stocks_are_verified() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 0.2,
            "exploration_supported_ratio": 0.2,
            "formal_supported_ratio": 1.0,
        },
    )

    assert gate["status"] == "ready"
    assert gate["blockers"] == []
    assert "AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票" in gate["observations"]


def test_report_quality_gate_blocks_weak_formal_stocks() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 0.8,
            "exploration_supported_ratio": 0.8,
            "formal_supported_ratio": 0.75,
        },
        promoted_tickers=["2330", "2382"],
        financial_metrics_count=20,
    )

    assert gate["status"] == "insufficient"
    assert "正式分析股票仍含弱證據公司" in gate["blockers"]


def test_report_quality_gate_warns_when_leading_signal_coverage_is_low() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 1.0},
        promoted_tickers=["2330", "2382"],
        financial_metrics_count=20,
        leading_signal_count=0,
    )

    assert gate["status"] == "caution"
    assert "近況訊號覆蓋偏低，目前情境升值/降值排序信心需下修" in gate["warnings"]
    assert gate["metrics"]["leading_signal_coverage"] == 0
    assert any("補齊股價歷史" in action for action in gate["remediation_actions"])


def test_report_quality_gate_blocks_incomplete_discovery_plan() -> None:
    gate = _quality_gate(
        plan_quality={
            "status": "insufficient",
            "score": 30,
            "missing": ["缺少估值/股價研究任務"],
        }
    )

    assert gate["status"] == "insufficient"
    assert gate["action_policy"]["policy"] == "research_only"
    assert any("AI 拆解任務品質不足" in blocker for blocker in gate["blockers"])
    assert gate["metrics"]["discovery_plan_status"] == "insufficient"
    assert gate["metrics"]["discovery_plan_score"] == 30


def test_report_quality_gate_warns_on_caution_discovery_plan() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.8},
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
        plan_quality={
            "status": "caution",
            "score": 70,
            "missing": ["缺少風險/瓶頸研究任務"],
        },
    )

    assert gate["status"] == "caution"
    assert gate["action_policy"]["policy"] == "manual_review_required"
    assert gate["action_policy"]["max_deployable_amount"] == 175_000
    assert any("AI 拆解任務仍有缺口" in warning for warning in gate["warnings"])


def test_report_quality_gate_caps_caution_deployable_amount() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.8},
        dynamic_stored_count=10,
        financial_metrics_count=6,
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )

    assert gate["status"] == "caution"
    assert gate["action_policy"]["policy"] == "manual_review_required"
    assert gate["action_policy"]["max_deployable_amount"] == 175_000


def test_attach_quality_gate_to_report_persists_gate_in_markdown_and_payload() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.8},
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
    )

    updated = attach_quality_gate_to_report(response, gate)

    assert updated.quality_gate == gate
    assert "## 報告品質門檻" in updated.markdown
    assert updated.markdown.find("## 報告品質門檻") < updated.markdown.find("## 一頁摘要")
    assert "狀態：資料品質可用" in updated.markdown
    assert "品質門檻研究額度上限：約 700,000 元" in updated.markdown
    assert "不是本次配置或買進指令" in updated.markdown


def test_parse_quality_gate_from_markdown_restores_history_report_metrics() -> None:
    gate = _quality_gate(
        candidate_support={
            "supported_ratio": 0.8,
            "formal_confidence_avg": 88.5,
            "formal_confidence_min": 80,
        },
        investor_capital=1_000_000,
        cash_reserve_pct=0.3,
        source_quality={
            "unique_publisher_count": 5,
            "timestamp_coverage": 0.92,
            "recent_coverage": 0.75,
        },
        plan_quality={
            "status": "ready",
            "score": 95,
            "missing": [],
        },
    )
    response = attach_quality_gate_to_report(
        ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
        ),
        gate,
    )

    assert "正式股票證據信心：平均 高 88.5 / 最低 高 80" in response.markdown

    parsed = parse_quality_gate_from_markdown(response.markdown)

    assert parsed is not None
    assert parsed["status"] == "ready"
    assert parsed["action_policy"]["max_deployable_amount"] == 700_000
    assert parsed["metrics"]["promoted_count"] == 1
    assert parsed["metrics"]["dynamic_source_count"] == 24
    assert parsed["metrics"]["source_unique_publishers"] == 5
    assert parsed["metrics"]["source_timestamp_coverage"] == 0.92
    assert parsed["metrics"]["source_recent_coverage"] == 0.75
    assert parsed["metrics"]["discovery_plan_status"] == "ready"
    assert parsed["metrics"]["discovery_plan_score"] == 95
    assert parsed["metrics"]["exploration_candidate_supported_ratio"] == 0.8
    assert parsed["metrics"]["formal_confidence_avg"] == 88.5
    assert parsed["metrics"]["formal_confidence_min"] == 80


def test_quality_gate_markdown_uses_investor_friendly_model_warning() -> None:
    markdown = render_quality_gate_markdown(
        {
            "status": "caution",
            "recommendation": "資料大致可用，但仍需人工確認警示項。",
            "warnings": ["LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿"],
            "blockers": [],
            "observations": [],
            "metrics": {"llm_analysis_status": "fallback"},
            "remediation_actions": [
                "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。"
            ],
            "action_policy": {"label": "需人工覆核"},
        }
    )

    assert "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核" in markdown
    assert "請系統管理者恢復模型補充分析，恢復後重新產生報告並保留事實核查" in markdown
    assert "LLM API key" not in markdown
    assert "規則引擎草稿" not in markdown
    parsed = parse_quality_gate_from_markdown(markdown)
    assert parsed["warnings"] == [
        "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核"
    ]


def test_parse_quality_gate_from_markdown_restores_remediation_actions() -> None:
    gate = _quality_gate(candidate_support={"supported_ratio": 1.0}, dynamic_stored_count=10)
    response = attach_quality_gate_to_report(
        ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
        ),
        gate,
    )

    parsed = parse_quality_gate_from_markdown(response.markdown)

    assert parsed is not None
    assert parsed["remediation_actions"] == gate["remediation_actions"]


def test_attach_quality_gate_adds_action_guard_for_insufficient_report() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.3}, dynamic_stored_count=3, promoted_tickers=[]
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告\n\n## 投資建議\n- 測試",
    )

    updated = attach_quality_gate_to_report(response, gate)

    assert "## 投資行動限制" in updated.markdown
    assert "不得視為買入清單" in updated.markdown
    assert updated.markdown.find("## 投資行動限制") < updated.markdown.find("## 投資建議")


def test_attach_quality_gate_replaces_existing_quality_sections() -> None:
    gate = _quality_gate(candidate_support={"supported_ratio": 0.8})
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown=(
            "# AI 產業鏈 自動分析報告\n\n"
            "## 報告品質門檻\n"
            "- 狀態：資料不足\n"
            "- 阻擋項：舊資料不足\n\n"
            "## 投資行動限制\n"
            "- 舊限制段落\n\n"
            "## 一頁摘要\n"
            "- 測試"
        ),
    )

    updated = attach_quality_gate_to_report(response, gate)

    assert updated.markdown.count("## 報告品質門檻") == 1
    assert "狀態：資料品質可用" in updated.markdown
    assert "狀態：資料不足" not in updated.markdown
    assert "舊資料不足" not in updated.markdown
    assert "舊限制段落" not in updated.markdown
    assert "## 投資行動限制" not in updated.markdown
    assert updated.markdown.find("## 報告品質門檻") < updated.markdown.find("## 一頁摘要")


def test_attach_quality_gate_replaces_ready_section_with_new_action_guard() -> None:
    gate = _quality_gate(
        candidate_support={"supported_ratio": 0.3}, dynamic_stored_count=3, promoted_tickers=[]
    )
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown=(
            "# AI 產業鏈 自動分析報告\n\n"
            "## 報告品質門檻\n"
            "- 狀態：資料品質可用\n\n"
            "## 投資建議\n"
            "- 舊建議"
        ),
    )

    updated = attach_quality_gate_to_report(response, gate)

    assert updated.markdown.count("## 報告品質門檻") == 1
    assert updated.markdown.count("## 投資行動限制") == 1
    assert "狀態：資料不足" in updated.markdown
    assert "狀態：資料品質可用" not in updated.markdown
    assert "不得視為買入清單" in updated.markdown
    assert updated.markdown.find("## 投資行動限制") < updated.markdown.find("## 投資建議")


def test_ready_quality_gate_does_not_add_action_guard() -> None:
    gate = _quality_gate(candidate_support={"supported_ratio": 0.8})

    assert render_quality_action_guard_markdown(gate) == ""
