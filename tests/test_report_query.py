from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from app.services.report_query import ReportQueryNotFound, ReportQueryService


def test_report_query_service_builds_reader_payload_with_candidate_audit_and_follow_up() -> None:
    captured = {}

    class FakeReport:
        id = 7
        title = "AI 產業鏈 自動分析報告"
        topic = "AI 產業鏈"
        tickers_json = '["2330"]'
        markdown = (
            "# AI 產業鏈 自動分析報告\n\n"
            "## 一頁摘要\n測試\n"
            "- 2026-05-12 CMoney《1815 富喬-股市爆料同學會》\n"
            "## 來源覆蓋\n"
            "| 股票 | 公司相關文本 | 國際文本 | 最近來源日期 | 代表來源 |\n"
            "|---|---:|---:|---|---|\n"
            "| 1504 東元 | 15 |  | 2026-05-26 | "
            "2026-05-26 CMoney《1504 東元 - 股市爆料同學會》；"
            "2026-05-25 富聯網《東元受邀參加法人說明會》 |\n"
        )
        generated_at = datetime(2026, 5, 28, 10, 0, 0)

    class FakeRun:
        payload_json = (
            '{"workflow":{"name":"standard_report_pipeline","status":"success"},'
            '"candidate_whitelist":[{"ticker":"2330","name":"台積電","segment":"晶圓代工",'
            '"status":"evidence_supported","evidence_count":2,"evidence_source_count":2},'
            '{"ticker":"3324","name":"雙鴻","segment":"散熱模組","status":"weak_evidence",'
            '"evidence_count":1,"evidence_source_count":1,"validation_reason":"弱證據：來源不足"}]}'
        )

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            captured["report_session"] = session

        def get(self, report_id: int):
            assert report_id == 7
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            captured["run_session"] = session

        def get_by_report_id(self, report_id: int):
            assert report_id == 7
            return FakeRun()

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        latest_follow_up_run_for_report_func=lambda *args: {"status": "success", "rerun_report": {"report_id": 8}},
    )

    payload = service.get_report(7)

    assert captured == {"report_session": "session", "run_session": "session"}
    assert payload["id"] == 7
    assert payload["workflow"]["name"] == "standard_report_pipeline"
    assert payload["auto_follow_up"]["rerun_report"]["report_id"] == 8
    assert "股市爆料同學會" not in payload["markdown"]
    assert "| 1504 東元 |" in payload["markdown"]
    assert "2026-05-25 富聯網" in payload["markdown"]
    assert "## 候選公司審計" in payload["markdown"]
    assert payload["candidate_audit"]["summary"]["total"] == 2
    assert payload["candidate_audit"]["summary"]["weak_count"] == 1
    assert "3324 雙鴻" in payload["candidate_audit"]["markdown"]


def test_report_query_service_sanitizes_and_replaces_candidate_audit_section() -> None:
    candidate_payload = {
        "candidate_whitelist": [
            {
                "ticker": "1504",
                "name": "東元",
                "segment": "伺服馬達",
                "status": "evidence_supported",
                "promotion_eligible": True,
                "evidence_count": 2,
                "evidence_source_count": 2,
                "evidence_confidence_score": 100,
                "evidence_confidence_label": "高",
                "validation_reason": "通過多來源證據",
                "next_action": "納入正式分析。",
                "evidence_sources": [
                    {
                        "title": "東元智慧製造接單",
                        "publisher": "經濟日報",
                        "published_at": "2026-05-25",
                    },
                    {
                        "title": "1504 東元 - 股市爆料同學會",
                        "publisher": "CMoney",
                        "published_at": "2026-05-26",
                        "url": "https://www.cmoney.tw/forum/stock/1504",
                    },
                ],
            }
        ]
    }

    class FakeReport:
        id = 7
        title = "機器人 產業鏈 自動分析報告"
        topic = "機器人 產業鏈"
        tickers_json = '["1504"]'
        markdown = "# 機器人 產業鏈 自動分析報告\n\n## 候選公司審計\n舊候選審計段落\n\n## 下一段\n保留"
        generated_at = datetime(2026, 5, 28, 10, 0, 0)

    class FakeRun:
        payload_json = json.dumps(candidate_payload, ensure_ascii=False)

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int):
            assert report_id == 7
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int):
            assert report_id == 7
            return FakeRun()

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        latest_follow_up_run_for_report_func=lambda *args: None,
    )

    payload = service.get_report(7)

    assert "舊候選審計段落" not in payload["markdown"]
    assert "股市爆料同學會" not in payload["markdown"]
    assert "弱證據觀察" in payload["markdown"]
    assert "不得進入配置" in payload["markdown"]
    assert "## 下一段" in payload["markdown"]
    assert payload["candidate_audit"]["summary"]["supported_count"] == 0
    assert payload["candidate_audit"]["summary"]["weak_count"] == 1


def test_report_query_service_ignores_follow_up_rerun_when_report_id_points_to_other_topic() -> None:
    class SourceReport:
        id = 18
        title = "機器人 產業鏈 自動分析報告"
        topic = "機器人 產業鏈"
        tickers_json = '["2308","1504"]'
        markdown = "# 機器人 產業鏈 自動分析報告\n\n## 一頁摘要\n測試"
        generated_at = datetime(2026, 5, 31, 22, 8, 0)

    class OtherTopicReport:
        id = 19
        title = "AI 產業鏈低關注潛力股 自動分析報告"
        topic = "AI 產業鏈低關注潛力股"
        tickers_json = '["2330","1815"]'
        markdown = "# AI 產業鏈低關注潛力股 自動分析報告\n"
        generated_at = datetime(2026, 5, 31, 22, 10, 0)

    class ReportRun:
        payload_json = '{"request":{"topic":"機器人 產業鏈","tickers":["2308","1504"]}}'

    class StaleFollowUpRun:
        id = 147
        source = "follow_up_api"
        status = "success"
        payload_json = json.dumps(
            {
                "source_report_id": 18,
                "request": {"topic": "機器人 產業鏈", "tickers": ["2308", "1504"]},
                "rerun_report": {
                    "report_id": 19,
                    "request": {"topic": "機器人 產業鏈", "tickers": ["2308", "1504"]},
                },
            },
            ensure_ascii=False,
        )
        report_id = 19
        output_path = None
        error = None
        started_at = datetime(2026, 5, 31, 22, 9, 0)
        finished_at = datetime(2026, 5, 31, 22, 11, 0)

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get(self, report_id: int):
            if report_id == 18:
                return SourceReport()
            if report_id == 19:
                return OtherTopicReport()
            raise AssertionError(f"unexpected report_id: {report_id}")

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_report_id(self, report_id: int):
            assert report_id == 18
            return ReportRun()

        def latest(self, limit: int = 100):
            assert limit == 100
            return [StaleFollowUpRun()]

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
    )

    payload = service.get_report(18)

    assert payload["auto_follow_up"] is None


def test_report_query_service_lists_and_deletes_reports() -> None:
    deleted_ids = []
    reports = [
        SimpleNamespace(
            id=1,
            title="報告 A",
            topic="AI",
            generated_at=datetime(2026, 5, 1, 9, 0, 0),
        )
    ]

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def latest(self, limit: int):
            assert limit == 3
            return reports

        def delete(self, report_id: int) -> bool:
            deleted_ids.append(report_id)
            return report_id == 1

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = ReportQueryService(
        session_scope_factory=fake_session_scope,
        report_repository_cls=FakeReportRepository,
    )

    assert service.list_reports(3) == [
        {
            "id": 1,
            "title": "報告 A",
            "topic": "AI",
            "generated_at": "2026-05-01T09:00:00",
        }
    ]
    assert service.delete_report(1) == {"deleted": True, "id": 1}

    try:
        service.delete_report(2)
    except ReportQueryNotFound as exc:
        assert str(exc) == "report not found"
    else:
        raise AssertionError("missing report deletion should raise")
    assert deleted_ids == [1, 2]
