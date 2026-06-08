from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from app.api.schemas import FollowUpRunRequest
from app.models.schemas import ReportRequest, ReportResponse
from app.services.followup_actions import FollowUpAction
from app.services.report_followup import follow_up_plan_next_actions
from app.services.report_followup_plan import AutoFollowUpStartService, ReportFollowUpPlanService
from app.services.report_followup_runner import ReportFollowUpRunService


async def _default_prepare_follow_up_context(context, request, actions):
    return {
        "request": request,
        "whitelist": None,
        "candidate_whitelist": context.get("candidate_whitelist") or [],
        "candidate_revalidation": {
            "candidate_whitelist": context.get("candidate_whitelist") or [],
            "promoted_tickers": request.tickers,
            "newly_promoted": [],
            "no_longer_promoted": [],
            "status_changes": [],
            "changed": False,
        },
    }


async def _default_execute_follow_up_actions(actions, request, news_limit=30):
    return {
        "actions": [action.to_dict() for action in actions],
        "results": {},
        "execution_summary": {},
    }


def _follow_up_runner_service(
    *,
    context: dict,
    analysis_run_repository_cls: type,
    report_repository_cls: type = object,
    follow_up_action_planner_cls: type,
    execute_follow_up_actions_func=_default_execute_follow_up_actions,
    prepare_follow_up_report_context_func=_default_prepare_follow_up_context,
    report_build_service_factory=lambda: None,
    split_fresh_tracking_actions_func=lambda actions, request: (actions, []),
    render_follow_up_actions_markdown_func=lambda actions: "",
    tracking_freshness_thresholds: dict | None = None,
) -> ReportFollowUpRunService:
    @contextmanager
    def fake_session_scope():
        yield object()

    return ReportFollowUpRunService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=analysis_run_repository_cls,
        report_repository_cls=report_repository_cls,
        follow_up_action_planner_cls=follow_up_action_planner_cls,
        load_report_follow_up_context_func=lambda report_id: context,
        prepare_follow_up_report_context_func=prepare_follow_up_report_context_func,
        execute_follow_up_actions_func=execute_follow_up_actions_func,
        summarize_follow_up_execution_func=lambda execution: (
            execution.get("execution_summary") or {}
        ),
        split_fresh_tracking_actions_func=split_fresh_tracking_actions_func,
        render_follow_up_actions_markdown_func=render_follow_up_actions_markdown_func,
        report_build_service_factory=report_build_service_factory,
        count_sufficient_company_filings_func=lambda tickers: 0,
        safe_mark_run_failed_func=lambda run_id, error: None,
        tracking_freshness_thresholds=tracking_freshness_thresholds or {"refresh_market": 5},
        task_cancellation_checker=lambda run_id: None,
    )


def _follow_up_context(
    *,
    request: ReportRequest,
    markdown: str = "# report",
    quality_gate: dict | None = None,
    company_data_audit: dict | None = None,
    candidate_whitelist: list[dict] | None = None,
    run_payload: dict | None = None,
) -> dict:
    return {
        "source_report_id": 7,
        "source_report_topic": request.topic,
        "source_report_tickers": request.tickers,
        "source_report_generated_at": None,
        "source_report_created_at": None,
        "request": request,
        "quality_gate": quality_gate or {"status": "ready", "warnings": [], "blockers": []},
        "company_data_audit": company_data_audit or {"status": "sufficient"},
        "source_audit": {},
        "markdown": markdown,
        "candidate_whitelist": candidate_whitelist or [],
        "run_payload": run_payload or {"request": request.model_dump(mode="json")},
    }


def test_report_follow_up_runner_reruns_report_after_tracking_actions() -> None:
    class NewReport:
        id = 8

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, response) -> NewReport:
            assert request.tickers == ["2330"]
            assert "重跑後報告" in response.markdown
            return NewReport()

    class FakeRun:
        id = 31
        payload_json = '{"request":{"topic":"AI 產業鏈","tickers":["2330"],"lookback_days":30}}'

    class FakeAnalysisRunRepository:
        success_report_id = None

        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun | None:
            assert report_id == 7
            return FakeRun()

        def start(self, source: str, payload: dict) -> FakeRun:
            assert source == "follow_up_api"
            assert payload["source_report_id"] == 7
            assert payload["planned_actions"]
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 31
            assert payload["execution"] == {
                "actions": payload["planned_actions"],
                "results": {"refresh_monthly_revenue:2330": {"stored_count": 12, "errors": []}},
                "execution_summary": {
                    "task_result_count": 1,
                    "stored_count": 12,
                    "error_count": 0,
                    "has_errors": False,
                    "items": [],
                },
            }
            return FakeRun()

        def mark_success(
            self, run_id: int, report_id: int, output_path: str | None = None
        ) -> FakeRun:
            assert run_id == 31
            FakeAnalysisRunRepository.success_report_id = report_id
            return FakeRun()

    class FakeBuildService:
        def build(self, request, **kwargs):
            assert request.topic == "AI 產業鏈"
            return {
                "response": ReportResponse(title="重跑後報告", markdown="# 重跑後報告"),
                "quality_gate": {"status": "ready", "warnings": [], "blockers": []},
                "report_execution": {},
            }

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction(
                    "refresh_monthly_revenue", "補月營收", ("2330",), "high", "monthly", "tracking"
                ),
                FollowUpAction(
                    "refresh_valuations", "補估值", ("2330",), "high", "daily", "tracking"
                ),
                FollowUpAction(
                    "rerun_analysis", "補資料後重新產生報告", ("2330",), "high", "once", "tracking"
                ),
            ]

    async def fake_execute(actions, request, news_limit=30):
        assert {action.action_type for action in actions} >= {
            "refresh_monthly_revenue",
            "refresh_valuations",
            "rerun_analysis",
        }
        assert request.tickers == ["2330"]
        return {
            "actions": [action.to_dict() for action in actions],
            "results": {"refresh_monthly_revenue:2330": {"stored_count": 12, "errors": []}},
            "execution_summary": {
                "task_result_count": 1,
                "stored_count": 12,
                "error_count": 0,
                "has_errors": False,
                "items": [],
            },
        }

    service = _follow_up_runner_service(
        context=_follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=30),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n"
                "## 監控清單\n"
                "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
                "|---|---|---|---|---|\n"
                "| 2330 台積電 | 觀察 / 等風險降低 | 補齊月營收與估值 | 降值風險高於 5% | 每週 |\n"
            ),
        ),
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
        follow_up_action_planner_cls=FakePlanner,
        execute_follow_up_actions_func=fake_execute,
        report_build_service_factory=lambda: FakeBuildService(),
    )

    body = asyncio.run(service.run(7, FollowUpRunRequest(rerun_report=True)))
    assert body["status"] == "executed"
    assert body["run_id"] == 31
    assert body["summary"]["selected"]["total_count"] >= 3
    assert body["summary"]["execution"]["stored_count"] == 12
    assert body["rerun_report"]["report_id"] == 8
    assert FakeAnalysisRunRepository.success_report_id == 8


def test_auto_start_required_follow_up_runs_required_scope() -> None:
    captured = {}

    def fake_plan(report_id: int) -> dict:
        assert report_id == 7
        return {
            "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            "summary": {"required_count": 2, "tracking_count": 1, "total_count": 3},
            "next_actions": [{"action": "ingest_company_filings"}],
        }

    async def fake_run(report_id: int, payload) -> dict:
        assert report_id == 7
        captured["payload"] = payload
        return {
            "run_id": 31,
            "summary": {"selected": {"total_count": 2}, "execution": {"stored_count": 5}},
            "freshness": {},
            "actions": [{"action_type": "ingest_company_filings"}],
            "rerun_report": {"report_id": 8},
            "results": {"ingest_company_filings:2330": {"stored_count": 5}},
        }

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(
            auto_follow_up_enabled=True, auto_follow_up_news_limit=40
        ),
        plan_provider=fake_plan,
        follow_up_run_request_cls=FollowUpRunRequest,
        run_follow_up_func=fake_run,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    result = asyncio.run(service.start(7, run_in_background=False))

    assert result["status"] == "started"
    assert result["run_id"] == 31
    assert result["rerun_report"]["report_id"] == 8
    assert result["source_report_topic"] == "AI 產業鏈"
    assert result["source_report_tickers"] == ["2330"]
    assert captured["payload"].purpose == "required"
    assert captured["payload"].rerun_report is True
    assert captured["payload"].news_limit == 40


def test_auto_start_required_follow_up_queues_background_task_by_default() -> None:
    captured = {}

    def fake_create_task(coro):
        captured["queued"] = True
        coro.close()
        return SimpleNamespace()

    async def fake_background_runner(report_id, payload):
        captured["background"] = {"report_id": report_id, "payload": payload}

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(
            auto_follow_up_enabled=True, auto_follow_up_news_limit=40
        ),
        plan_provider=lambda report_id: {
            "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            "summary": {"required_count": 2, "total_count": 3},
            "actions": [{"action_type": "ingest_news"}],
            "next_actions": [{"action": "ingest_news"}],
        },
        follow_up_run_request_cls=FollowUpRunRequest,
        run_follow_up_func=lambda report_id, payload: None,
        background_runner_func=fake_background_runner,
        create_task_func=fake_create_task,
    )

    result = asyncio.run(service.start(7))

    assert result["status"] == "queued"
    assert captured["queued"] is True
    assert result["summary"]["selected"]["required_count"] == 2
    assert result["source_report_topic"] == "AI 產業鏈"
    assert result["source_report_tickers"] == ["2330"]
    assert result["next_actions"][0]["action"] == "ingest_news"


def test_auto_start_required_follow_up_skips_when_no_required_gap() -> None:
    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(
            auto_follow_up_enabled=True, auto_follow_up_news_limit=40
        ),
        plan_provider=lambda report_id: {"summary": {"required_count": 0}, "next_actions": []},
        follow_up_run_request_cls=FollowUpRunRequest,
        run_follow_up_func=lambda report_id, payload: None,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    result = asyncio.run(service.start(7, run_in_background=False))

    assert result["status"] == "not_needed"
    assert result["reason"] == "no_required_data_gap"


def test_auto_start_required_follow_up_runs_candidate_gaps_even_when_report_is_ready() -> None:
    captured = {}

    async def fake_run(report_id: int, payload) -> dict:
        captured["payload"] = payload
        return {
            "run_id": 31,
            "summary": {"selected": {"required_count": 4}},
            "freshness": {},
            "actions": [{"action_type": "ingest_news"}],
            "rerun_report": {"report_id": 8},
            "results": {},
        }

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(
            auto_follow_up_enabled=True, auto_follow_up_news_limit=40
        ),
        plan_provider=lambda report_id: {
            "request": {"topic": "機器人 產業鏈", "tickers": ["2308"]},
            "quality_gate_status": "ready",
            "summary": {"required_count": 4, "total_count": 4},
            "next_actions": [{"action": "ingest_news"}],
        },
        follow_up_run_request_cls=FollowUpRunRequest,
        run_follow_up_func=fake_run,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    result = asyncio.run(service.start(7, run_in_background=False))

    assert result["status"] == "started"
    assert result["run_id"] == 31
    assert result["source_report_topic"] == "機器人 產業鏈"
    assert result["source_report_tickers"] == ["2308"]
    assert captured["payload"].purpose == "required"


def test_report_follow_up_skips_rerun_when_company_filing_gaps_remain() -> None:
    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, response):
            raise AssertionError("report should not rerun while company filing blockers remain")

    class FakeRun:
        id = 31
        payload_json = '{"request":{"topic":"AI 產業鏈","tickers":["2382"],"lookback_days":30}}'

    class FakeAnalysisRunRepository:
        success_report_id = None

        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun | None:
            assert report_id == 7
            return FakeRun()

        def start(self, source: str, payload: dict) -> FakeRun:
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert payload["rerun_report"]["status"] == "skipped"
            return FakeRun()

        def mark_success(
            self, run_id: int, report_id: int, output_path: str | None = None
        ) -> FakeRun:
            FakeAnalysisRunRepository.success_report_id = report_id
            return FakeRun()

    async def fake_execute(actions, request, news_limit=30):
        return {
            "actions": [action.to_dict() for action in actions],
            "results": {
                "ingest_company_filings:2382": {
                    "stored_count": 0,
                    "errors": [],
                    "gap_summary": {"blocked_tickers": ["2382"], "retryable_tickers": []},
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "manual_company_filing_import",
                            "missing_required_types": ["annual_report"],
                            "missing_recommended_types": [],
                            "reason": "請補官方文件：annual_report",
                        }
                    ],
                }
            },
            "execution_summary": {
                "task_result_count": 1,
                "stored_count": 0,
                "error_count": 0,
                "has_errors": False,
                "rerun_blocked": True,
                "rerun_blockers": ["公司公開文件仍不足：2382"],
                "rerun_blocker_actions": [
                    {
                        "ticker": "2382",
                        "company_name": "廣達",
                        "action": "manual_company_filing_import",
                        "missing_required_types": ["annual_report"],
                        "missing_recommended_types": [],
                        "reason": "請補官方文件：annual_report",
                    }
                ],
                "items": [],
            },
        }

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction(
                    "ingest_company_filings",
                    "個股資料審計缺口：缺高品質必要公司文件：annual_report",
                    ("2382",),
                    "high",
                    "monthly",
                    "required",
                )
            ]

    service = _follow_up_runner_service(
        context=_follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2382"], lookback_days=30),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n## 資料完整度\n- 缺高品質必要公司文件：annual_report\n"
            ),
        ),
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
        follow_up_action_planner_cls=FakePlanner,
        execute_follow_up_actions_func=fake_execute,
    )

    body = asyncio.run(service.run(7, FollowUpRunRequest(rerun_report=True)))
    assert body["rerun_report"]["status"] == "skipped"
    assert body["rerun_report"]["blockers"] == ["公司公開文件仍不足：2382"]
    assert body["rerun_report"]["next_actions"][0]["ticker"] == "2382"
    assert FakeAnalysisRunRepository.success_report_id == 7


def test_report_follow_up_rerun_persists_revalidated_request() -> None:
    captured = {}

    class NewReport:
        id = 18

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, response) -> NewReport:
            captured["created_request"] = request.model_dump(mode="json")
            return NewReport()

    class FakeRun:
        id = 61
        payload_json = (
            '{"request":{"topic":"AI 產業鏈","tickers":["2330"],"lookback_days":30},'
            '"candidate_whitelist":['
            '{"ticker":"2330","name":"台積電","segment":"晶圓代工","status":"evidence_supported"},'
            '{"ticker":"3324","name":"雙鴻","segment":"散熱模組","status":"weak_evidence"}]}'
        )

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> FakeRun:
            assert report_id == 7
            return FakeRun()

        def start(self, source: str, payload: dict) -> FakeRun:
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            captured["payload"] = payload
            return FakeRun()

        def mark_success(
            self, run_id: int, report_id: int, output_path: str | None = None
        ) -> FakeRun:
            return FakeRun()

    class FakeBuildService:
        def build(self, request, **kwargs):
            assert request.tickers == ["2330", "3324"]
            return {
                "response": ReportResponse(title="升格後報告", markdown="# 升格後報告"),
                "quality_gate": {"status": "ready"},
                "report_execution": {},
            }

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction("ingest_news", "補候選", ("3324",), "high", "daily", "required"),
                FollowUpAction("rerun_analysis", "補資料後重新產生報告", ("3324",), "high", "once"),
            ]

    async def fake_execute(actions, request, news_limit=30):
        return {
            "actions": [action.to_dict() for action in actions],
            "results": {},
            "execution_summary": {},
        }

    async def fake_prepare(context, request, actions):
        rerun_request = request.model_copy(update={"tickers": ["2330", "3324"]})
        captured["refreshed_request"] = rerun_request.model_dump(mode="json")
        return {
            "request": rerun_request,
            "whitelist": None,
            "candidate_whitelist": [
                {
                    "ticker": "2330",
                    "name": "台積電",
                    "segment": "晶圓代工",
                    "status": "evidence_supported",
                },
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "status": "evidence_supported",
                },
            ],
            "candidate_revalidation": {
                "candidate_whitelist": [
                    {
                        "ticker": "2330",
                        "name": "台積電",
                        "segment": "晶圓代工",
                        "status": "evidence_supported",
                    },
                    {
                        "ticker": "3324",
                        "name": "雙鴻",
                        "segment": "散熱模組",
                        "status": "evidence_supported",
                    },
                ],
                "promoted_tickers": ["2330", "3324"],
                "newly_promoted": ["3324"],
                "no_longer_promoted": [],
                "status_changes": [
                    {
                        "ticker": "3324",
                        "previous_status": "weak_evidence",
                        "current_status": "evidence_supported",
                    }
                ],
                "changed": True,
            },
        }

    service = _follow_up_runner_service(
        context=_follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=30),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n"
                "## 候選公司審計\n"
                "| 股票 | 產業位置 | 狀態 | 證據 | 排除 / 升格原因 | 下一步 |\n"
                "|---|---|---|---:|---|---|\n"
                "| 2330 台積電 | 晶圓代工 | 正式分析 | 2 篇 / 2 來源 | 通過 | 納入正式分析 |\n"
                "| 3324 雙鴻 | 散熱模組 | 弱證據觀察 | 1 篇 / 1 來源 | 弱證據 | 補抓公司新聞 |\n"
            ),
            candidate_whitelist=[
                {
                    "ticker": "2330",
                    "name": "台積電",
                    "segment": "晶圓代工",
                    "status": "evidence_supported",
                },
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment": "散熱模組",
                    "status": "weak_evidence",
                },
            ],
        ),
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
        follow_up_action_planner_cls=FakePlanner,
        execute_follow_up_actions_func=fake_execute,
        prepare_follow_up_report_context_func=fake_prepare,
        report_build_service_factory=lambda: FakeBuildService(),
    )

    asyncio.run(service.run(7, FollowUpRunRequest(rerun_report=True)))
    assert captured["created_request"]["tickers"] == ["2330", "3324"]
    assert captured["refreshed_request"]["tickers"] == ["2330", "3324"]
    assert captured["payload"]["request"]["tickers"] == ["2330", "3324"]
    assert captured["payload"]["candidate_whitelist"][1]["status"] == "evidence_supported"
    assert captured["payload"]["rerun_report"]["candidate_revalidation"]["newly_promoted"] == [
        "3324"
    ]


def test_report_follow_up_runner_can_skip_tracking_when_required_only() -> None:
    class FakeRun:
        id = 41
        payload_json = "{}"

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> None:
            assert report_id == 7
            return None

        def start(self, source: str, payload: dict) -> FakeRun:
            raise AssertionError("no-op follow-up should not create a run by default")

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 41
            assert payload["planned_actions"] == []
            assert payload["status"] == "no_action_required"
            return FakeRun()

        def mark_success(
            self, run_id: int, report_id: int, output_path: str | None = None
        ) -> FakeRun:
            assert run_id == 41
            FakeAnalysisRunRepository.marked_report_id = report_id
            return FakeRun()

    async def fake_execute(actions, request, news_limit=30):
        raise AssertionError("required-only run should skip tracking actions")

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction(
                    "refresh_market", "追蹤股價", ("2330",), "high", "daily", "tracking"
                ),
                FollowUpAction(
                    "rerun_analysis", "補資料後重新產生報告", ("2330",), "high", "once", "tracking"
                ),
            ]

    service = _follow_up_runner_service(
        context=_follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n"
                "## 監控清單\n"
                "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
                "|---|---|---|---|---|\n"
                "| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號由偏空轉為中性以上 | 降值風險高於 5% | 每週 |\n"
            ),
        ),
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        follow_up_action_planner_cls=FakePlanner,
        execute_follow_up_actions_func=fake_execute,
    )

    result = asyncio.run(service.run(7, FollowUpRunRequest(rerun_report=True, purpose="required")))

    assert result["status"] == "no_action_required"
    assert result["run_id"] is None
    assert result["summary"]["selected"]["total_count"] == 0
    assert result["summary"]["available"]["tracking_count"] >= 1
    assert result["available_actions"]


def test_report_follow_up_runner_can_force_fresh_tracking_actions() -> None:
    class FakeRun:
        id = 51
        payload_json = "{}"

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int) -> None:
            assert report_id == 7
            return None

        def start(self, source: str, payload: dict) -> FakeRun:
            assert source == "follow_up_api"
            assert payload["force_refresh"] is True
            assert payload["planned_actions"]
            return FakeRun()

        def update_payload(self, run_id: int, payload: dict) -> FakeRun:
            assert run_id == 51
            assert payload["force_refresh"] is True
            return FakeRun()

        def mark_success(
            self, run_id: int, report_id: int, output_path: str | None = None
        ) -> FakeRun:
            assert run_id == 51
            return FakeRun()

    async def fake_execute(actions, request, news_limit=30):
        assert any(action.action_type == "refresh_market" for action in actions)
        return {
            "actions": [action.to_dict() for action in actions],
            "results": {},
            "execution_summary": {},
        }

    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction(
                    "refresh_market", "追蹤股價", ("2330",), "high", "daily", "tracking"
                ),
                FollowUpAction(
                    "rerun_analysis", "補資料後重新產生報告", ("2330",), "high", "once", "tracking"
                ),
            ]

    service = _follow_up_runner_service(
        context=_follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n"
                "## 監控清單\n"
                "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
                "|---|---|---|---|---|\n"
                "| 2330 台積電 | 觀察 / 等風險降低 | 領先訊號由偏空轉為中性以上 | 降值風險高於 5% | 每週 |\n"
            ),
        ),
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        follow_up_action_planner_cls=FakePlanner,
        execute_follow_up_actions_func=fake_execute,
        split_fresh_tracking_actions_func=lambda actions, request: (
            [],
            [
                {
                    **action.to_dict(),
                    "freshness": {
                        "is_fresh": True,
                        "max_age_days": 5,
                        "latest_dates": {"2330": "2026-05-25"},
                    },
                }
                for action in actions
                if action.action_type == "refresh_market"
            ],
        ),
    )

    result = asyncio.run(
        service.run(
            7,
            FollowUpRunRequest(rerun_report=False, purpose="tracking", force_refresh=True),
        )
    )

    assert result["status"] == "executed"
    assert result["force_refresh"] is True


def test_report_follow_up_plan_preview_uses_report_history() -> None:
    class FakePlanner:
        def plan(self, *args, **kwargs):
            return [
                FollowUpAction(
                    "refresh_monthly_revenue", "補月營收", ("2330",), "high", "monthly", "tracking"
                ),
                FollowUpAction(
                    "refresh_valuations", "補估值", ("2330",), "high", "daily", "tracking"
                ),
                FollowUpAction(
                    "rerun_analysis", "補資料後重新產生報告", ("2330",), "high", "once", "tracking"
                ),
            ]

    service = ReportFollowUpPlanService(
        load_report_follow_up_context_func=lambda report_id: _follow_up_context(
            request=ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            markdown=(
                "# AI 產業鏈 自動分析報告\n\n"
                "## 監控清單\n"
                "| 股票 | 目前動作 | 重新研究條件 | 繼續避開/觀察條件 | 監控頻率 |\n"
                "|---|---|---|---|---|\n"
                "| 2330 台積電 | 觀察 / 等風險降低 | 補齊月營收與估值 | 降值風險高於 5% | 每週 |\n"
            ),
        ),
        follow_up_action_planner_cls=FakePlanner,
        split_fresh_tracking_actions_func=lambda actions, request: (actions, []),
        render_follow_up_actions_markdown_func=lambda actions: (
            "| 任務 | 股票 | 性質 | 優先級 | 頻率 | 觸發原因 |"
        ),
        tracking_freshness_thresholds={"refresh_market": 5},
    )

    body = service.build(7)

    assert body["freshness"]["thresholds"]["refresh_market"] == 5
    action_types = {action["action_type"] for action in body["actions"]}
    assert "refresh_monthly_revenue" in action_types
    assert "refresh_valuations" in action_types
    assert "rerun_analysis" in action_types
    assert body["summary"]["tracking_count"] >= 1
    assert "| 任務 | 股票 | 性質 | 優先級 | 頻率 | 觸發原因 |" in body["markdown_preview"]


def test_follow_up_plan_next_actions_describe_planned_work() -> None:
    rows = follow_up_plan_next_actions(
        [
            FollowUpAction(
                "ingest_company_filings",
                "個股資料審計缺口：缺高品質必要公司文件：annual_report",
                ("2382",),
                "high",
                "monthly",
                "required",
            ),
            FollowUpAction(
                "refresh_market",
                "個股資料審計缺口：股價",
                ("2382",),
                "high",
            ),
            FollowUpAction(
                "rerun_analysis",
                "補資料後重新產生報告",
                ("2382",),
                "high",
                "once",
            ),
        ]
    )

    assert rows == [
        {
            "action": "ingest_company_filings",
            "tickers": ["2382"],
            "target": "annual_report",
            "priority": "high",
            "purpose": "required",
            "reason": "個股資料審計缺口：缺高品質必要公司文件：annual_report",
            "next_step": "先自動搜尋官方/MOPS/IR 文件；若仍不足，系統會列出需人工匯入的文件。",
            "completion_criteria": "每檔至少有必要類型的高品質官方文件；若仍缺件，列入人工匯入清單。",
            "completion_checks": [
                {
                    "check": "company_filing_quality",
                    "required_document_types": ["annual_report"],
                    "min_quality_score": 70,
                    "min_documents_per_ticker": 1,
                }
            ],
        },
        {
            "action": "refresh_market",
            "tickers": ["2382"],
            "target": "股價與量能",
            "priority": "high",
            "purpose": "required",
            "reason": "個股資料審計缺口：股價",
            "next_step": "刷新近 120 天股價、量能與波動資料，用於目前情境降值分與進出場檢查。",
            "completion_criteria": "目標股票近 120 天內有可用股價與量能資料。",
            "completion_checks": [{"check": "market_history_coverage", "min_days": 120}],
        },
        {
            "action": "rerun_analysis",
            "tickers": ["2382"],
            "target": "完整投資報告",
            "priority": "high",
            "purpose": "required",
            "reason": "補資料後重新產生報告",
            "next_step": "在補資料後重新產生報告；若仍有關鍵缺口，系統會先暫停重跑。",
            "completion_criteria": "補強後無關鍵 blocker，才重新產生完整投資報告。",
            "completion_checks": [{"check": "quality_gate_no_blockers"}],
        },
    ]
