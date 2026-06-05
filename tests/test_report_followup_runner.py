from contextlib import contextmanager
from types import SimpleNamespace

from app.models.schemas import ReportRequest
from app.services.report_followup_runner import ReportFollowUpRunService


@contextmanager
def fake_session_scope():
    yield object()


class EmptyPlanner:
    def plan(self, *args, **kwargs):
        return []


def _service(**overrides) -> ReportFollowUpRunService:
    defaults = {
        "session_scope_factory": fake_session_scope,
        "analysis_run_repository_cls": object,
        "report_repository_cls": object,
        "follow_up_action_planner_cls": EmptyPlanner,
        "load_report_follow_up_context_func": lambda report_id: {
            "request": ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            "quality_gate": {"status": "ready"},
            "company_data_audit": {},
            "source_audit": {},
            "markdown": "# report",
            "candidate_whitelist": [],
        },
        "prepare_follow_up_report_context_func": None,
        "execute_follow_up_actions_func": None,
        "summarize_follow_up_execution_func": lambda execution: {},
        "split_fresh_tracking_actions_func": lambda actions, request: (actions, []),
        "render_follow_up_actions_markdown_func": lambda actions: "",
        "report_build_service_factory": lambda: None,
        "count_sufficient_company_filings_func": lambda tickers: 0,
        "safe_mark_run_failed_func": lambda run_id, error: None,
        "tracking_freshness_thresholds": {},
    }
    defaults.update(overrides)
    return ReportFollowUpRunService(**defaults)


def _payload(**overrides):
    values = {
        "rerun_report": True,
        "news_limit": 30,
        "purpose": "all",
        "record_noop": False,
        "force_refresh": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_follow_up_run_service_returns_noop_without_creating_run() -> None:
    class FailingRunRepository:
        def __init__(self, session):
            pass

        def start(self, source, payload):
            raise AssertionError("non-recorded noop should not create an analysis run")

    result = run_async(
        _service(analysis_run_repository_cls=FailingRunRepository).run(7, _payload())
    )

    assert result["status"] == "no_action_required"
    assert result["run_id"] is None


def test_follow_up_run_service_records_noop_when_requested() -> None:
    captured = {}

    class FakeRun:
        id = 42

    class FakeRunRepository:
        def __init__(self, session):
            pass

        def start(self, source, payload):
            captured["start_source"] = source
            return FakeRun()

        def update_payload(self, run_id, payload):
            captured["updated_payload"] = payload

        def mark_success(self, run_id, report_id, output_path=None):
            captured["success"] = (run_id, report_id)

    result = run_async(
        _service(analysis_run_repository_cls=FakeRunRepository).run(
            7,
            _payload(record_noop=True),
        )
    )

    assert result["status"] == "no_action_required"
    assert result["run_id"] == 42
    assert captured["start_source"] == "follow_up_api"
    assert captured["updated_payload"]["status"] == "no_action_required"
    assert captured["success"] == (42, 7)


def test_follow_up_run_service_force_refresh_creates_manual_tracking_actions() -> None:
    captured = {}

    class FakeRun:
        id = 43

    class FakeRunRepository:
        def __init__(self, session):
            pass

        def start(self, source, payload):
            captured["start_payload"] = payload
            return FakeRun()

        def update_payload(self, run_id, payload):
            captured["updated_payload"] = payload

        def mark_success(self, run_id, report_id, output_path=None):
            captured["success"] = (run_id, report_id)

    async def execute(actions, request, news_limit):
        captured["executed_actions"] = [action.to_dict() for action in actions]
        captured["news_limit"] = news_limit
        return {
            "results": {"ingest_news:2330": {"count": 2, "items": []}},
            "execution_summary": {
                "stored_count": 2,
                "error_count": 0,
                "rerun_blocked": False,
            },
        }

    result = run_async(
        _service(
            analysis_run_repository_cls=FakeRunRepository,
            execute_follow_up_actions_func=execute,
        ).run(
            7,
            _payload(
                force_refresh=True,
                purpose="tracking",
                rerun_report=False,
                news_limit=100,
            ),
        )
    )

    assert result["status"] == "executed"
    assert result["summary"]["selected"] == {
        "required_count": 0,
        "tracking_count": 2,
        "total_count": 2,
    }
    assert [action["action_type"] for action in captured["executed_actions"]] == [
        "ingest_news",
        "rerun_analysis",
    ]
    assert captured["news_limit"] == 100
    assert captured["updated_payload"]["force_refresh"] is True
    assert captured["success"] == (43, 7)


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
