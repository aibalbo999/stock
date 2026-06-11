from __future__ import annotations

import json

from app.services import task_submission_smoke as smoke


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def getcode(self) -> int:
        return self.status


def test_task_submission_smoke_default_api_url_comes_from_runtime_settings() -> None:
    assert smoke.DEFAULT_API_URL == smoke.get_settings().api_base_url


def test_task_submission_smoke_posts_noop_market_refresh_payload() -> None:
    captured = []

    def fake_opener(request, timeout):
        captured.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "body": json.loads((request.data or b"{}").decode("utf-8")),
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/services/status"):
            return FakeResponse(
                {
                    "task_queue": {
                        "ready": True,
                        "processing_ready": True,
                        "submission_contract_ready": True,
                        "worker_online": True,
                    }
                }
            )
        return FakeResponse(
            {"task_id": "task-1", "status": "queued", "operation": "market_refresh"}
        )

    report = smoke.run_task_submission_smoke(
        api_url="http://api.test",
        submit=True,
        check_runtime_identity=False,
        opener=fake_opener,
        timeout_seconds=3,
    )

    assert report["status"] == "passed"
    assert captured[0]["method"] == "GET"
    assert captured[1]["method"] == "POST"
    assert captured[1]["url"] == "http://api.test/tasks/data-operation"
    assert captured[1]["body"]["operation"] == "market_refresh"
    assert captured[1]["body"]["payload"]["tickers"] == ["2330"]
    assert captured[1]["body"]["payload"]["smoke"] is True
    assert captured[1]["body"]["payload"]["task_submission_smoke"] is True
    assert report["submission"]["json"]["task_id"] == "task-1"
    assert report["next_actions"] == ["背景任務提交路徑正常。"]


def test_task_submission_smoke_polls_until_task_success() -> None:
    responses = [
        FakeResponse(
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": True,
                    "submission_contract_ready": True,
                    "worker_online": True,
                }
            }
        ),
        FakeResponse({"task_id": "task-1", "status": "queued", "operation": "market_refresh"}),
        FakeResponse({"task_id": "task-1", "status": "PENDING", "ready": False}),
        FakeResponse(
            {
                "task_id": "task-1",
                "status": "SUCCESS",
                "ready": True,
                "successful": True,
                "result": {"smoke": True},
            }
        ),
    ]
    sleeps = []

    def fake_opener(_request, timeout):
        return responses.pop(0)

    report = smoke.run_task_submission_smoke(
        submit=True,
        wait=True,
        check_runtime_identity=False,
        opener=fake_opener,
        clock=lambda: 0.0,
        sleeper=lambda seconds: sleeps.append(seconds),
        poll_interval_seconds=0.2,
    )

    assert report["status"] == "passed"
    assert report["task_poll"]["status"] == "completed"
    assert report["task_poll"]["attempts"] == 2
    assert sleeps == [0.2]


def test_task_submission_smoke_reports_api_submission_failure() -> None:
    def fake_opener(request, timeout):
        if request.full_url.endswith("/services/status"):
            return FakeResponse(
                {
                    "task_queue": {
                        "ready": True,
                        "processing_ready": True,
                        "submission_contract_ready": True,
                    }
                }
            )
        return FakeResponse(
            {"detail": {"error": "background_task_submission_failed"}},
            status=500,
        )

    report = smoke.run_task_submission_smoke(
        submit=True,
        check_runtime_identity=False,
        opener=fake_opener,
    )

    assert report["status"] == "failed"
    assert report["submission"]["status_code"] == 500
    assert "background_task_submission_failed" in report["submission"]["error"]
    assert any(
        "檢查 /tasks/data-operation structured error detail" in action
        for action in report["next_actions"]
    )


def test_task_submission_smoke_uses_operator_queue_repair_guidance() -> None:
    def fake_opener(request, timeout):
        return FakeResponse(
            {
                "task_queue": {
                    "ready": False,
                    "processing_ready": False,
                    "submission_contract_ready": False,
                    "worker_online": False,
                }
            }
        )

    report = smoke.run_task_submission_smoke(
        check_runtime_identity=False,
        opener=fake_opener,
    )

    rendered = " ".join(report["next_actions"])
    assert "確認 Redis 佇列/結果儲存與任務註冊，再重跑系統狀態檢查。" in rendered
    assert "Redis broker/backend" not in rendered
    assert "Celery task exports" not in rendered


def test_task_submission_smoke_uses_operator_worker_timeout_guidance() -> None:
    responses = [
        FakeResponse(
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": True,
                    "submission_contract_ready": True,
                    "worker_online": True,
                }
            }
        ),
        FakeResponse({"task_id": "task-1", "status": "queued", "operation": "market_refresh"}),
        FakeResponse({"task_id": "task-1", "status": "PENDING", "ready": False}),
    ]

    def fake_opener(_request, timeout):
        return responses.pop(0)

    ticks = iter([0.0, 1.0])
    report = smoke.run_task_submission_smoke(
        submit=True,
        wait=True,
        check_runtime_identity=False,
        opener=fake_opener,
        clock=lambda: next(ticks),
        sleeper=lambda seconds: None,
        timeout_seconds=0.0,
    )

    rendered = " ".join(report["next_actions"])
    assert "任務已送出但未完成；檢查背景執行器是否在線或是否卡在執行中。" in rendered
    assert "worker" not in rendered


def test_task_submission_smoke_can_skip_processing_readiness_for_enqueue_only() -> None:
    def fake_opener(request, timeout):
        if request.full_url.endswith("/services/status"):
            return FakeResponse(
                {
                    "task_queue": {
                        "ready": True,
                        "processing_ready": False,
                        "submission_contract_ready": True,
                        "worker_online": False,
                    }
                }
            )
        return FakeResponse(
            {"task_id": "task-1", "status": "queued", "operation": "market_refresh"}
        )

    report = smoke.run_task_submission_smoke(
        submit=True,
        check_processing_ready=False,
        check_runtime_identity=False,
        opener=fake_opener,
    )

    assert report["status"] == "passed"
    assert report["check_processing_ready"] is False
    assert "啟動 Celery worker" not in " ".join(report["next_actions"])
    assert {
        check["name"]: check["status"]
        for check in report["checks"]
    }["submission_contract_ready"] == "passed"


def test_task_submission_smoke_suppresses_worker_hint_when_poll_succeeds() -> None:
    responses = [
        FakeResponse(
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": False,
                    "submission_contract_ready": True,
                    "worker_online": False,
                }
            }
        ),
        FakeResponse({"task_id": "task-1", "status": "queued", "operation": "market_refresh"}),
        FakeResponse(
            {
                "task_id": "task-1",
                "status": "SUCCESS",
                "ready": True,
                "successful": True,
                "result": {"smoke": True},
            }
        ),
    ]

    def fake_opener(_request, timeout):
        return responses.pop(0)

    report = smoke.run_task_submission_smoke(
        submit=True,
        wait=True,
        check_runtime_identity=False,
        opener=fake_opener,
    )

    assert report["status"] == "passed"
    assert "啟動 Celery worker" not in " ".join(report["next_actions"])
    assert report["next_actions"] == ["背景任務提交路徑正常。"]


def test_task_submission_smoke_accepts_legacy_celery_status_shape_as_caution() -> None:
    def fake_opener(request, timeout):
        return FakeResponse(
            {
                "celery": {
                    "ready": True,
                    "submission_contract_ready": True,
                    "broker_url": "redis://localhost:6379/0",
                }
            }
        )

    report = smoke.run_task_submission_smoke(check_runtime_identity=False, opener=fake_opener)

    assert report["status"] == "caution"
    assert report["task_queue"]["legacy_status_shape"] is True
    assert "重啟 FastAPI" in report["next_actions"][0]
    assert {
        check["name"]: check["status"]
        for check in report["checks"]
    }["task_queue_status_shape"] == "warning"


def test_task_submission_smoke_reports_api_runtime_commit_mismatch() -> None:
    def fake_opener(request, timeout):
        if request.full_url.endswith("/services/runtime-identity"):
            return FakeResponse(
                {
                    "git_commit": "old-api-commit",
                    "source": "git",
                    "git_dirty": False,
                }
            )
        return FakeResponse(
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": True,
                    "submission_contract_ready": True,
                    "worker_online": True,
                }
            }
        )

    report = smoke.run_task_submission_smoke(
        api_url="http://api.test",
        expected_api_commit="new-api-commit",
        opener=fake_opener,
    )

    assert report["status"] == "failed"
    assert report["runtime_identity"]["reason"] == "api_runtime_commit_mismatch"
    assert {
        check["name"]: check["status"]
        for check in report["checks"]
    }["api_runtime_identity"] == "failed"
    assert "重啟 FastAPI/Celery" in report["next_actions"][0]
