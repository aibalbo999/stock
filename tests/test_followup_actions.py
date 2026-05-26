from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.models.schemas import MarketSnapshot, MonthlyRevenue
from app.models.schemas import ReportRequest
from app.services.followup_actions import (
    FollowUpAction,
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    company_filing_document_types_from_reason,
    execute_follow_up_actions_sync,
    follow_up_news_queries,
    render_follow_up_actions_markdown,
    skipped_fresh_tracking_details,
    summarize_follow_up_execution,
)
from app.services.persistence import MarketRepository, MonthlyRevenueRepository


def test_quality_gate_remediation_becomes_executable_actions() -> None:
    gate = {
        "status": "caution",
        "warnings": [
            "月營收資料覆蓋偏低",
            "估值資料覆蓋偏低",
            "領先訊號覆蓋偏低，潛力/風險排序信心需下修",
        ],
        "remediation_actions": ["補齊股價歷史、成交量、月營收與估值資料，避免只靠新聞排序潛力與風險標的。"],
    }

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2330", "2382"]),
        quality_gate=gate,
    )

    action_types = {action.action_type for action in actions}
    assert "refresh_market" in action_types
    assert "refresh_monthly_revenue" in action_types
    assert "refresh_valuations" in action_types
    assert "rerun_analysis" in action_types


def test_llm_fallback_warning_becomes_rerun_action() -> None:
    gate = {
        "status": "caution",
        "warnings": ["LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿"],
        "remediation_actions": ["檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。"],
    }

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        quality_gate=gate,
    )

    assert [action.action_type for action in actions] == ["rerun_analysis"]
    assert actions[0].priority == "high"


def test_company_data_audit_becomes_required_follow_up_actions() -> None:
    audit = {
        "rows": [
            {
                "ticker": "3017",
                "status": "partial",
                "missing": ["可稽核入庫公司文本不足", "可稽核入庫 AI 歸因不足"],
            },
            {
                "ticker": "2059",
                "status": "insufficient",
                "missing": ["股價歷史不足或過舊", "估值資料不足或過舊"],
            },
        ]
    }

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["3017", "2059"]),
        company_data_audit=audit,
    )

    keys = {(action.action_type, action.tickers) for action in actions}
    assert ("ingest_news", ("3017",)) in keys
    assert ("refresh_market", ("2059",)) in keys
    assert ("refresh_valuations", ("2059",)) in keys
    assert ("rerun_analysis", ("3017", "2059")) in keys


def test_monitoring_table_becomes_ticker_specific_actions(monkeypatch) -> None:
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    markdown = """
## 監控清單
| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |
|---|---|---|---|---|
| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號由偏空轉為中性以上；補齊估值 | 降值風險高於 5% | 每週 |
| 2382 廣達 | 觀察 / 等風險降低 | 補齊月營收與公司文本後重跑 AI 歸因 | 升值情境低於 10% | 每月 |

## 先看結論
測試
"""

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2330", "2382"]),
        markdown=markdown,
    )

    keys = {(action.action_type, action.tickers) for action in actions}
    assert ("refresh_market", ("2330",)) in keys
    assert ("refresh_valuations", ("2330",)) in keys
    assert ("refresh_monthly_revenue", ("2382",)) in keys
    assert ("ingest_news", ("2382",)) in keys
    assert {action.purpose for action in actions} == {"tracking"}


def test_render_follow_up_actions_markdown_is_user_readable() -> None:
    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        quality_gate={"warnings": ["股價資料覆蓋率低於 50%"]},
    )

    markdown = render_follow_up_actions_markdown(actions)

    assert "##" not in markdown
    assert actions[0].to_dict()["label"]
    assert "資料缺口補強" in markdown
    assert "刷新股價/量能" in markdown
    assert "重跑分析報告" in markdown


def test_candidate_audit_becomes_required_follow_up_actions(monkeypatch) -> None:
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    markdown = """
## 候選公司審計
本段保留 AI 初始候選到正式分析的完整軌跡。

| 項目 | 數量 |
|---|---:|
| AI 初始候選 | 2 |
| 正式分析 | 1 |

| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 信心 |
|---|---|---|---:|---|---|---:|
| 2382 廣達 | 系統組裝 | 正式分析 | 2 篇 / 2 來源 | 通過正式分析門檻 | 納入正式分析 | 高 88 |
| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據：來源不足 | 補抓公司新聞後再驗證 | 中 52 |
| 2308 台達電 | 電源與散熱 | 待補證據 | 0 篇 / 0 來源 | 缺少公司主題證據 | 重新補抓公司層級來源 | 未評分 |
"""

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2382"]),
        markdown=markdown,
    )

    keys = {(action.action_type, action.tickers, action.purpose) for action in actions}
    assert ("ingest_news", ("3324",), "required") in keys
    assert ("ingest_news", ("2308",), "required") in keys
    assert any(action.action_type == "rerun_discovery" for action in actions)
    assert any(action.action_type == "rerun_analysis" for action in actions)
    news_action = next(action for action in actions if action.action_type == "ingest_news" and action.tickers == ("3324",))
    assert "股票：3324 雙鴻" in news_action.reason
    assert "產業位置：散熱模組" in news_action.reason
    assert "信心：中 52" in news_action.reason


def test_candidate_audit_can_be_tracking_when_report_is_ready(monkeypatch) -> None:
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    markdown = """
## 候選公司審計
| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 信心 |
|---|---|---|---:|---|---|---:|
| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據：來源不足 | 補抓公司新聞後再驗證 | 中 52 |
"""

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2382"]),
        markdown=markdown,
        candidate_audit_required=False,
    )

    assert {action.purpose for action in actions} == {"tracking"}
    assert any(action.action_type == "ingest_news" and action.tickers == ("3324",) for action in actions)


def test_company_filing_follow_up_targets_missing_document_type() -> None:
    assert company_filing_document_types_from_reason("缺高品質必要公司文件：annual_report") == ["annual_report"]
    assert company_filing_document_types_from_reason("建議補高品質公司文件：investor_presentation") == [
        "investor_presentation"
    ]
    assert company_filing_document_types_from_reason("公司原始公開文件不足或來源品質偏低") is None


def test_candidate_tracking_prioritizes_near_promotion_candidates(monkeypatch) -> None:
    monkeypatch.setattr("app.services.followup_actions.tracking_freshness_details_by_action", lambda actions, request: {})
    markdown = """
## 候選公司審計
| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 | 信心 |
|---|---|---|---:|---|---|---:|
| 1001 零證一 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 1002 零證二 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 1003 零證三 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 1004 零證四 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 1005 零證五 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 1006 零證六 | 測試 | 待補證據 | 0 篇 / 0 來源 | 缺資料 | 補抓 | 未評分 |
| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據 | 補抓 | 中 52 |
| 3661 世芯-KY | ASIC | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據 | 補抓 | 中 60 |
"""

    actions = FollowUpActionPlanner().plan(
        ReportRequest(topic="AI 產業鏈", tickers=["2382"]),
        markdown=markdown,
        candidate_audit_required=False,
    )

    ingest_tickers = [
        action.tickers[0]
        for action in actions
        if action.action_type == "ingest_news"
    ]
    assert ingest_tickers[:2] == ["3661", "3324"]
    assert len(ingest_tickers) == 5
    assert "1006" not in ingest_tickers


def test_candidate_follow_up_news_queries_are_targeted() -> None:
    action = FollowUpAction(
        "ingest_news",
        "候選公司未升格，需補齊公司層級證據：股票：3324 雙鴻；產業位置：散熱模組；弱證據觀察；補抓公司新聞後再驗證",
        ("3324",),
        "high",
        "weekly",
        "required",
    )

    queries = follow_up_news_queries(action, ReportRequest(topic="AI 產業鏈", tickers=["2382"]))

    assert queries
    assert any("3324" in query and "AI 產業鏈" in query for query in queries)
    assert any("散熱模組" in query for query in queries)


def test_candidate_follow_up_queries_prioritize_fresh_sources_for_low_confidence() -> None:
    action = FollowUpAction(
        "ingest_news",
        "候選公司未升格，需補齊公司層級證據：股票：3324 雙鴻；產業位置：散熱模組；"
        "弱證據：篇數與來源數達標，但證據信心只有 60 分，需補近期或有日期來源；信心：中 60",
        ("3324",),
        "high",
        "weekly",
        "required",
    )

    queries = follow_up_news_queries(action, ReportRequest(topic="AI 產業鏈", tickers=["2382"]))

    assert any("法說會" in query and "近期" in query for query in queries)
    assert any("investor conference" in query for query in queries)
    assert any("發布日期" in query and "多來源" in query for query in queries)


def test_execute_follow_up_news_uses_targeted_google_queries(monkeypatch) -> None:
    calls = []

    class FakePipeline:
        async def ingest_feeds(self, **kwargs):
            calls.append(kwargs)
            return {
                "count": 1,
                "items": [
                    {
                        "id": kwargs["url"],
                        "title": "雙鴻 AI 散熱補強來源",
                        "publisher": "Google News follow-up",
                    }
                ],
                "errors": [],
            }

    monkeypatch.setattr("app.services.followup_actions.IngestionPipeline", FakePipeline)
    monkeypatch.setattr("app.services.followup_actions.today_taipei", lambda: date(2026, 5, 25))
    action = FollowUpAction(
        "ingest_news",
        "候選公司未升格，需補齊公司層級證據：股票：3324 雙鴻；產業位置：散熱模組；弱證據觀察",
        ("3324",),
        "high",
        "weekly",
        "required",
    )

    result = execute_follow_up_actions_sync([action], ReportRequest(topic="AI 產業鏈", tickers=["2382"]), news_limit=12)

    news_result = result["results"]["ingest_news:3324"]
    assert news_result["source"] == "Google News targeted follow-up"
    assert news_result["queries"]
    assert calls
    assert all("news.google.com/rss/search" in call["url"] for call in calls)
    assert any("3324" in query["query"] for query in news_result["queries"])


def test_execute_follow_up_market_refresh_fetches_enough_calendar_days(monkeypatch) -> None:
    captured = {}

    class FakePipeline:
        async def refresh_market(self, tickers, start_date, end_date, filter_allowed=True):
            captured["tickers"] = tickers
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            captured["filter_allowed"] = filter_allowed
            return {"stored_history_count": 120, "errors": []}

    monkeypatch.setattr("app.services.followup_actions.IngestionPipeline", FakePipeline)
    monkeypatch.setattr("app.services.followup_actions.today_taipei", lambda: date(2026, 5, 25))
    action = FollowUpAction("refresh_market", "補齊股價歷史", ("2330",), "high")

    result = execute_follow_up_actions_sync([action], ReportRequest(topic="AI 產業鏈", tickers=["2330"]), news_limit=12)

    assert captured == {
        "tickers": ["2330"],
        "start_date": date(2026, 5, 25) - timedelta(days=240),
        "end_date": date(2026, 5, 25),
        "filter_allowed": False,
    }
    assert result["execution_summary"]["completion"]["all_completed"] is True


def test_summarize_follow_up_execution_counts_stored_items_and_errors() -> None:
    summary = summarize_follow_up_execution(
        {
            "results": {
                "refresh_market:2330": {
                    "stored_history_count": 90,
                    "errors": [{"ticker": "9999"}],
                    "source": "FinMind TaiwanStockPrice",
                },
                "refresh_valuations:2330": {
                    "stored": [{"ticker": "2330"}],
                    "errors": [],
                    "source": "FinMind TaiwanStockPER",
                },
            }
        }
    )

    assert summary["task_result_count"] == 2
    assert summary["stored_count"] == 91
    assert summary["error_count"] == 1
    assert summary["has_errors"] is True
    assert summary["completion"]["all_completed"] is False
    assert summary["items"][0]["completion"]["check"] == "market_history_coverage"
    assert summary["items"][0]["completion"]["completed"] is False
    assert summary["items"][1]["completion"]["check"] == "valuation_availability"
    assert summary["items"][1]["completion"]["completed"] is True
    assert summary["rerun_blocked"] is True
    assert summary["rerun_blockers"] == ["補強任務未達完成條件：refresh_market:2330"]
    assert summary["rerun_blocker_actions"][0]["action"] == "complete_follow_up_check"
    assert summary["rerun_blocker_actions"][0]["target"] == "股價與量能"
    assert summary["rerun_blocker_actions"][0]["observed"] == {"stored_count": 90, "error_count": 1}
    assert summary["rerun_blocker_actions"][0]["required"] == {"min_days": 120, "error_count": 0}


def test_summarize_follow_up_execution_requires_news_to_match_target_company() -> None:
    summary = summarize_follow_up_execution(
        {
            "results": {
                "ingest_news:3324": {
                    "count": 2,
                    "items": [
                        {"title": "AI 供應鏈總覽", "entity_matches": []},
                        {"title": "廣達 AI 伺服器", "entity_matches": [{"ticker": "2382"}]},
                    ],
                    "errors": [],
                }
            }
        }
    )

    completion = summary["items"][0]["completion"]

    assert completion["check"] == "company_evidence_sources"
    assert completion["completed"] is False
    assert completion["observed"]["matched_target_count"] == 0
    assert summary["rerun_blockers"] == ["補強任務未達完成條件：ingest_news:3324"]


def test_summarize_follow_up_execution_marks_all_completed_when_checks_pass() -> None:
    summary = summarize_follow_up_execution(
        {
            "results": {
                "refresh_market:2330": {
                    "stored_history_count": 120,
                    "errors": [],
                },
                "refresh_monthly_revenue:2330": {
                    "stored_count": 12,
                    "errors": [],
                },
                "refresh_financial_metrics:2330": {
                    "stored_count": 5,
                    "errors": [],
                },
            }
        }
    )

    assert summary["completion"] == {
        "completed_count": 3,
        "total_count": 3,
        "all_completed": True,
        "blocked_tasks": [],
    }
    assert summary["rerun_blocked"] is False
    assert summary["rerun_blockers"] == []


def test_summarize_follow_up_execution_blocks_rerun_when_company_filings_still_missing() -> None:
    summary = summarize_follow_up_execution(
        {
            "results": {
                "ingest_company_filings:2382": {
                    "stored_count": 0,
                    "errors": [],
                    "gap_summary": {
                        "blocked_tickers": ["2382"],
                        "retryable_tickers": ["3324"],
                    },
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "action": "manual_company_filing_import",
                            "missing_required_types": ["annual_report"],
                        }
                    ],
                }
            }
        }
    )

    assert summary["rerun_blocked"] is True
    assert summary["rerun_blockers"] == ["公司公開文件仍不足：2382"]
    assert summary["rerun_blocker_actions"][0]["ticker"] == "2382"
    assert summary["retryable_company_filing_tickers"] == ["3324"]


def test_tracking_actions_are_skipped_when_cached_data_is_fresh(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        MarketRepository(session).upsert_snapshots(
            [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 24), close=100)]
        )
        MonthlyRevenueRepository(session).upsert_revenues(
            [
                MonthlyRevenue(
                    ticker="2330",
                    revenue_date=date(2026, 4, 10),
                    revenue=100,
                    revenue_year=2026,
                    revenue_month=4,
                )
            ]
        )
        session.commit()

        @contextmanager
        def fake_session_scope():
            yield session

        monkeypatch.setattr("app.services.followup_actions.session_scope", fake_session_scope)
        monkeypatch.setattr("app.services.followup_actions.today_taipei", lambda: date(2026, 5, 25))

        markdown = """
## 監控清單
| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |
|---|---|---|---|---|
| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號轉偏多且量價/營收同步改善 | 降值風險高於 5% | 每週 |
"""

        actions = FollowUpActionPlanner().plan(
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            markdown=markdown,
        )

        assert actions == []
        details = skipped_fresh_tracking_details(
            FollowUpActionPlanner().plan(
                ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
                markdown=markdown,
                apply_freshness=False,
            ),
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
        )
        assert details[0]["freshness"]["latest_dates"]["2330"] == "2026-05-24"
        assert details[0]["freshness"]["max_age_days"] == TRACKING_FRESHNESS_THRESHOLDS["refresh_market"]
    finally:
        session.close()
