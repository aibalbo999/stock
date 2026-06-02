from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.followup_actions import FollowUpAction
from app.services.report_followup import (
    filter_follow_up_actions,
    follow_up_plan_next_actions,
    latest_follow_up_run_for_report,
    matching_follow_up_rerun_report_id,
    parse_run_payload,
    request_from_report_record,
    should_require_candidate_audit_follow_up,
)


def test_parse_run_payload_handles_invalid_json() -> None:
    assert parse_run_payload("{not-json") == {}


def test_request_from_report_record_prefers_stored_request_payload() -> None:
    request = request_from_report_record(
        "舊主題",
        ["2330"],
        '{"request":{"topic":"AI 產業鏈","tickers":["2382"],"lookback_days":120}}',
    )

    assert request.topic == "AI 產業鏈"
    assert request.tickers == ["2382"]
    assert request.lookback_days == 120


def test_candidate_follow_up_does_not_require_rerun_for_source_only_gap() -> None:
    quality_gate = {
        "status": "needs_attention",
        "warnings": ["主題拆解子題覆蓋不足"],
        "metrics": {
            "promoted_count": 3,
            "candidate_supported_ratio": 0.8,
            "discovery_plan_status": "ready",
        },
    }

    assert should_require_candidate_audit_follow_up(quality_gate, {}, []) is False


def test_filter_follow_up_actions_keeps_rerun_analysis_with_required_actions() -> None:
    actions = [
        FollowUpAction("ingest_news", "補新聞", ("2330",), purpose="required"),
        FollowUpAction("refresh_market", "追蹤股價", ("2330",), purpose="tracking"),
        FollowUpAction("rerun_analysis", "重跑報告", ("2330",), purpose="all"),
    ]

    selected = filter_follow_up_actions(actions, "required")

    assert [action.action_type for action in selected] == ["ingest_news", "rerun_analysis"]


def test_follow_up_plan_next_actions_exposes_completion_checks() -> None:
    rows = follow_up_plan_next_actions(
        [
            FollowUpAction(
                "ingest_company_filings",
                "缺少 annual_report 官方文件",
                ("2330",),
            )
        ]
    )

    assert rows[0]["target"] == "annual_report"
    assert rows[0]["completion_checks"][0]["check"] == "company_filing_quality"
    assert rows[0]["completion_checks"][0]["min_quality_score"] == 70


def test_latest_follow_up_run_requires_same_source_report_and_topic() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308","1504"]',
        generated_at=datetime(2026, 5, 30, 10, 0, 0),
    )
    old_unrelated = SimpleNamespace(
        id=1,
        source="follow_up_api",
        status="success",
        payload_json='{"source_report_id":18,"source_report_topic":"AI 伺服器","source_report_tickers":["2330"]}',
        report_id=19,
        output_path=None,
        error=None,
        started_at=datetime(2026, 5, 30, 11, 0, 0),
        finished_at=datetime(2026, 5, 30, 11, 1, 0),
    )
    matching = SimpleNamespace(
        id=2,
        source="follow_up_api",
        status="success",
        payload_json='{"source_report_id":18,"source_report_topic":"機器人 產業鏈","source_report_tickers":["2308","1504"]}',
        report_id=20,
        output_path=None,
        error=None,
        started_at=report.generated_at + timedelta(minutes=10),
        finished_at=report.generated_at + timedelta(minutes=11),
    )
    repository = SimpleNamespace(latest=lambda limit: [old_unrelated, matching])

    latest = latest_follow_up_run_for_report(repository, report)

    assert latest is not None
    assert latest["id"] == 2
    assert latest["source_report_topic"] == "機器人 產業鏈"


def test_latest_follow_up_rejects_rerun_request_with_different_topic_without_repository() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308"]',
        generated_at=datetime(2026, 5, 30, 10, 0, 0),
    )
    run = SimpleNamespace(
        id=3,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":18,"source_report_topic":"機器人 產業鏈",'
            '"source_report_tickers":["2308"],'
            '"rerun_report":{"report_id":19,"request":{"topic":"AI 伺服器","tickers":["2330"]}}}'
        ),
        report_id=19,
        output_path=None,
        error=None,
        started_at=report.generated_at + timedelta(minutes=10),
        finished_at=report.generated_at + timedelta(minutes=11),
    )
    repository = SimpleNamespace(latest=lambda limit: [run])

    latest = latest_follow_up_run_for_report(repository, report)

    assert latest is None


def test_latest_follow_up_rejects_unlinked_rerun_report_without_repository() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308"]',
        generated_at=datetime(2026, 5, 31, 22, 8, 0),
    )
    run = SimpleNamespace(
        id=147,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":18,'
            '"request":{"topic":"機器人 產業鏈","tickers":["2308"]},'
            '"rerun_report":{"report_id":19,"request":{"topic":"機器人 產業鏈","tickers":["2308"]}}}'
        ),
        report_id=None,
        output_path=None,
        error=None,
        started_at=report.generated_at + timedelta(minutes=1),
        finished_at=report.generated_at + timedelta(minutes=2),
    )
    repository = SimpleNamespace(latest=lambda limit: [run])

    latest = latest_follow_up_run_for_report(repository, report)

    assert latest is None


def test_latest_follow_up_rejects_rerun_report_id_that_differs_from_run_link() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308"]',
        generated_at=datetime(2026, 5, 31, 22, 8, 0),
    )
    run = SimpleNamespace(
        id=148,
        source="follow_up_api",
        status="success",
        payload_json=(
            '{"source_report_id":18,'
            '"source_report_topic":"機器人 產業鏈",'
            '"source_report_tickers":["2308"],'
            '"rerun_report":{"report_id":19,"request":{"topic":"機器人 產業鏈","tickers":["2308"]}}}'
        ),
        report_id=20,
        output_path=None,
        error=None,
        started_at=report.generated_at + timedelta(minutes=1),
        finished_at=report.generated_at + timedelta(minutes=2),
    )
    repository = SimpleNamespace(latest=lambda limit: [run])

    latest = latest_follow_up_run_for_report(repository, report)

    assert latest is None


def test_matching_follow_up_rerun_report_id_requires_same_source_report() -> None:
    assert (
        matching_follow_up_rerun_report_id(
            {"source_report_id": 18, "rerun_report": {"report_id": 20}},
            18,
        )
        == 20
    )
    assert (
        matching_follow_up_rerun_report_id(
            {"source_report_id": 19, "rerun_report": {"report_id": 20}},
            18,
        )
        is None
    )
    assert matching_follow_up_rerun_report_id({"rerun_report": True}, 18) is None


def test_matching_follow_up_rerun_report_id_rejects_different_rerun_topic() -> None:
    assert (
        matching_follow_up_rerun_report_id(
            {
                "source_report_id": 18,
                "source_report_topic": "機器人 產業鏈",
                "rerun_report": {
                    "report_id": 19,
                    "request": {"topic": "AI 產業鏈低關注潛力股", "tickers": ["2330"]},
                },
            },
            18,
            source_topic="機器人 產業鏈",
            source_tickers=["2308", "1504"],
        )
        is None
    )


def test_matching_follow_up_rerun_report_id_requires_source_metadata_when_known() -> None:
    assert (
        matching_follow_up_rerun_report_id(
            {
                "source_report_id": 18,
                "rerun_report": {
                    "report_id": 19,
                    "request": {"topic": "機器人 產業鏈", "tickers": ["2308"]},
                },
            },
            18,
            source_topic="機器人 產業鏈",
            source_tickers=["2308"],
        )
        is None
    )


def test_matching_follow_up_rerun_report_id_rejects_unknown_rerun_topic_when_source_topic_is_known() -> None:
    assert (
        matching_follow_up_rerun_report_id(
            {
                "source_report_id": 18,
                "source_report_topic": "機器人 產業鏈",
                "rerun_report": {"report_id": 19},
            },
            18,
            source_topic="機器人 產業鏈",
        )
        is None
    )


def test_latest_follow_up_rejects_rerun_report_with_different_stored_topic() -> None:
    report = SimpleNamespace(
        id=18,
        topic="機器人 產業鏈",
        tickers_json='["2308"]',
        generated_at=datetime(2026, 5, 30, 10, 0, 0),
    )
    run = SimpleNamespace(
        id=4,
        source="follow_up_api",
        status="success",
        payload_json='{"source_report_id":18,"source_report_topic":"機器人 產業鏈","source_report_tickers":["2308"],"rerun_report":{"report_id":19}}',
        report_id=19,
        output_path=None,
        error=None,
        started_at=report.generated_at + timedelta(minutes=10),
        finished_at=report.generated_at + timedelta(minutes=11),
    )
    run_repository = SimpleNamespace(latest=lambda limit: [run])
    report_repository = SimpleNamespace(
        get=lambda report_id: SimpleNamespace(id=report_id, topic="AI 產業鏈低關注潛力股")
    )

    latest = latest_follow_up_run_for_report(run_repository, report, report_repository)

    assert latest is None
