from types import SimpleNamespace

from app.models.schemas import ReportRequest
from app.services.followup_actions import FollowUpAction
from app.services.report_followup_plan import AutoFollowUpStartService, ReportFollowUpPlanService


class FakePlanner:
    def plan(self, *args, **kwargs):
        return [
            FollowUpAction("ingest_news", "補新聞", ("2330",), purpose="required"),
            FollowUpAction("refresh_market", "追蹤股價", ("2330",), purpose="tracking"),
        ]


class FakeRunRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_report_follow_up_plan_service_builds_reader_ready_plan() -> None:
    captured = {}

    def load_context(report_id):
        assert report_id == 7
        return {
            "request": ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            "markdown": "# report",
            "quality_gate": {"status": "ready"},
            "company_data_audit": {"status": "needs_attention"},
            "source_audit": {"stored_count": 2},
            "candidate_whitelist": [{"ticker": "2330", "status": "weak_evidence"}],
        }

    def should_follow_up(quality_gate, company_data_audit, candidates):
        captured["candidate_check"] = {
            "quality_gate": quality_gate,
            "company_data_audit": company_data_audit,
            "candidates": candidates,
        }
        return True

    def split_fresh(actions, request):
        return actions[:1], [{"action_type": "refresh_market", "freshness": {"age_days": 1}}]

    service = ReportFollowUpPlanService(
        load_report_follow_up_context_func=load_context,
        follow_up_action_planner_cls=FakePlanner,
        should_require_candidate_audit_follow_up_func=should_follow_up,
        split_fresh_tracking_actions_func=split_fresh,
        follow_up_plan_next_actions_func=lambda actions: [{"action": action.action_type} for action in actions],
        render_follow_up_actions_markdown_func=lambda actions: "| 任務 | 股票 |",
        tracking_freshness_thresholds={"refresh_market": 5},
    )

    plan = service.build(7)

    assert plan["report_id"] == 7
    assert plan["request"]["tickers"] == ["2330"]
    assert plan["quality_gate_status"] == "ready"
    assert plan["summary"] == {"required_count": 1, "tracking_count": 0, "total_count": 1}
    assert plan["freshness"]["skipped_count"] == 1
    assert plan["freshness"]["skipped_actions"] == [{"action_type": "refresh_market"}]
    assert plan["freshness"]["message"] == "部分追蹤更新因資料仍在新鮮範圍內而略過。"
    assert plan["next_actions"] == [{"action": "ingest_news"}]
    assert plan["markdown_preview"] == "| 任務 | 股票 |"
    assert captured["candidate_check"]["candidates"][0]["ticker"] == "2330"


def test_auto_follow_up_start_service_runs_required_scope_immediately() -> None:
    captured = {}

    async def run_follow_up(report_id, payload):
        captured["run"] = {"report_id": report_id, "payload": payload}
        return {
            "run_id": 31,
            "summary": {"selected": {"required_count": 2}, "execution": {"stored_count": 5}},
            "freshness": {},
            "actions": [{"action_type": "ingest_news"}],
            "rerun_report": {"report_id": 8},
            "results": {},
        }

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(auto_follow_up_enabled=True, auto_follow_up_news_limit=40),
        plan_provider=lambda report_id: {
            "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
            "summary": {"required_count": 2},
            "next_actions": [],
        },
        follow_up_run_request_cls=FakeRunRequest,
        run_follow_up_func=run_follow_up,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    result = run_async(service.start(7, run_in_background=False))

    assert result["status"] == "started"
    assert result["run_id"] == 31
    assert result["rerun_report"]["report_id"] == 8
    assert result["source_report_topic"] == "AI 產業鏈"
    assert result["source_report_tickers"] == ["2330"]
    assert captured["run"]["report_id"] == 7
    assert captured["run"]["payload"].purpose == "required"
    assert captured["run"]["payload"].rerun_report is True
    assert captured["run"]["payload"].news_limit == 40


def test_auto_follow_up_start_service_queues_background_work() -> None:
    captured = {}

    async def background_runner(report_id, payload):
        captured["background"] = {"report_id": report_id, "payload": payload}

    def create_task(coro):
        captured["queued"] = coro
        coro.close()

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(auto_follow_up_enabled=True, auto_follow_up_news_limit=30),
        plan_provider=lambda report_id: {
            "request": {"topic": "機器人 產業鏈", "tickers": ["2308", "1504"]},
            "summary": {"required_count": 1},
            "actions": [{"action_type": "ingest_news"}],
            "next_actions": [{"action": "ingest_news"}],
        },
        follow_up_run_request_cls=FakeRunRequest,
        run_follow_up_func=lambda report_id, payload: None,
        background_runner_func=background_runner,
        create_task_func=create_task,
    )

    result = run_async(service.start(7))

    assert result["status"] == "queued"
    assert result["summary"]["selected"]["required_count"] == 1
    assert result["next_actions"] == [{"action": "ingest_news"}]
    assert result["source_report_topic"] == "機器人 產業鏈"
    assert result["source_report_tickers"] == ["2308", "1504"]
    assert "queued" in captured


def test_auto_follow_up_start_service_skips_when_not_needed_or_disabled() -> None:
    disabled = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(auto_follow_up_enabled=False, auto_follow_up_news_limit=30),
        plan_provider=lambda report_id: {},
        follow_up_run_request_cls=FakeRunRequest,
        run_follow_up_func=lambda report_id, payload: None,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    disabled_result = run_async(disabled.start(7, run_in_background=False))

    assert disabled_result == {"status": "disabled", "reason": "AUTO_FOLLOW_UP_ENABLED=false"}

    service = AutoFollowUpStartService(
        settings_provider=lambda: SimpleNamespace(auto_follow_up_enabled=True, auto_follow_up_news_limit=30),
        plan_provider=lambda report_id: {
            "quality_gate_status": "ready",
            "summary": {"required_count": 0},
            "next_actions": [],
        },
        follow_up_run_request_cls=FakeRunRequest,
        run_follow_up_func=lambda report_id, payload: None,
        background_runner_func=lambda report_id, payload: None,
        create_task_func=lambda coro: None,
    )

    result = run_async(service.start(7, run_in_background=False))

    assert result["status"] == "not_needed"
    assert result["reason"] == "quality_gate_ready"


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
