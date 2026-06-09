from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Callable
from urllib.parse import urljoin


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_OPERATION = "market_refresh"
DEFAULT_TICKERS = ("2330",)
SMOKE_USER_AGENT = "stock-ai-task-submission-smoke/1.0"


def run_task_submission_smoke(
    *,
    api_url: str = DEFAULT_API_URL,
    operation: str = DEFAULT_OPERATION,
    tickers: tuple[str, ...] | list[str] = DEFAULT_TICKERS,
    submit: bool = False,
    wait: bool = False,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    base_url = _base_url(api_url)
    checks = []
    service_status = _request_json(
        "GET",
        _api_url(base_url, "/services/status"),
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    checks.append(_check_from_http("service_status", service_status))
    task_queue = _task_queue_payload(service_status.get("json"))
    checks.extend(_task_queue_checks(task_queue))

    submission = None
    poll_result = None
    if submit and service_status.get("ok"):
        payload = _submission_payload(operation=operation, tickers=tickers)
        submission = _request_json(
            "POST",
            _api_url(base_url, "/tasks/data-operation"),
            payload=payload,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        checks.append(_check_from_http("data_operation_submission", submission))
        task_id = _task_id(submission.get("json"))
        if wait and task_id and submission.get("ok"):
            poll_result = _poll_task_status(
                base_url=base_url,
                task_id=task_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                opener=opener,
                clock=clock,
                sleeper=sleeper,
            )
            checks.append(_task_poll_check(poll_result))

    status = _overall_status(
        checks=checks,
        submit=submit,
        wait=wait,
        submission=submission,
        poll_result=poll_result,
    )
    return {
        "status": status,
        "api_url": base_url,
        "operation": operation,
        "submit": submit,
        "wait": wait,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "submission_payload": _submission_payload(operation=operation, tickers=tickers)
        if submit
        else None,
        "task_queue": task_queue,
        "submission": _public_http_result(submission),
        "task_poll": poll_result,
        "checks": checks,
        "next_actions": _next_actions(status, task_queue, submission, poll_result),
    }


def format_task_submission_smoke(report: dict) -> str:
    lines = [
        f"Task submission smoke: {report.get('status', 'unknown')}",
        f"- api: {report.get('api_url', '-')}",
        f"- operation: {report.get('operation', '-')}",
        f"- submit: {bool(report.get('submit'))}",
    ]
    task_queue = report.get("task_queue") if isinstance(report.get("task_queue"), dict) else {}
    if task_queue:
        lines.append(
            "- task queue: "
            f"ready={bool(task_queue.get('ready'))}; "
            f"processing_ready={bool(task_queue.get('processing_ready'))}; "
            f"worker_online={bool(task_queue.get('worker_online'))}"
        )
    submission = report.get("submission") if isinstance(report.get("submission"), dict) else {}
    if submission:
        body = submission.get("json") if isinstance(submission.get("json"), dict) else {}
        lines.append(
            "- submission: "
            f"ok={bool(submission.get('ok'))}; "
            f"status_code={submission.get('status_code')}; "
            f"task_id={body.get('task_id', '-')}"
        )
    poll = report.get("task_poll") if isinstance(report.get("task_poll"), dict) else {}
    if poll:
        lines.append(
            "- task poll: "
            f"status={poll.get('status', '-')}; "
            f"ready={bool(poll.get('ready'))}; "
            f"successful={bool(poll.get('successful'))}"
        )
    for action in report.get("next_actions") or []:
        lines.append(f"- next: {action}")
    return "\n".join(lines)


def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def smoke_exit_code(report: dict, *, strict: bool = False) -> int:
    if report.get("status") == "passed":
        return 0
    if report.get("status") == "caution" and not strict:
        return 0
    return 1


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    opener: Callable[..., Any],
    timeout_seconds: float,
) -> dict:
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": SMOKE_USER_AGENT,
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener(request, timeout=max(0.1, float(timeout_seconds))) as response:
            body = response.read(2_000_000)
            status_code = _response_status(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(2_000_000)
        status_code = int(exc.code)
        return _http_result(url=url, method=method, status_code=status_code, body=body)
    except Exception as exc:
        return {
            "ok": False,
            "method": method,
            "url": url,
            "status_code": None,
            "json": None,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return _http_result(url=url, method=method, status_code=status_code, body=body)


def _http_result(*, url: str, method: str, status_code: int, body: bytes) -> dict:
    parsed = _parse_json(body)
    return {
        "ok": 200 <= int(status_code) < 300,
        "method": method,
        "url": url,
        "status_code": int(status_code),
        "json": parsed,
        "error": None if 200 <= int(status_code) < 300 else _error_text(parsed, body),
    }


def _poll_task_status(
    *,
    base_url: str,
    task_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    opener: Callable[..., Any],
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> dict:
    deadline = clock() + max(0.1, float(timeout_seconds))
    attempts = 0
    while True:
        attempts += 1
        last_result = _request_json(
            "GET",
            _api_url(base_url, f"/tasks/{task_id}"),
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        payload = last_result.get("json") if isinstance(last_result.get("json"), dict) else {}
        if not last_result.get("ok") or payload.get("ready"):
            return {
                "status": "completed" if payload.get("ready") else "failed",
                "attempts": attempts,
                "task_id": task_id,
                "ready": bool(payload.get("ready")),
                "successful": bool(payload.get("successful")),
                "task_status": payload.get("status"),
                "response": _public_http_result(last_result),
            }
        if clock() >= deadline:
            return {
                "status": "timeout",
                "attempts": attempts,
                "task_id": task_id,
                "ready": False,
                "successful": False,
                "task_status": payload.get("status"),
                "response": _public_http_result(last_result),
            }
        sleeper(max(0.1, float(poll_interval_seconds)))


def _submission_payload(*, operation: str, tickers: tuple[str, ...] | list[str]) -> dict:
    today = date.today().isoformat()
    return {
        "operation": operation,
        "payload": {
            "tickers": list(tickers),
            "start_date": today,
            "end_date": today,
            "smoke": True,
            "task_submission_smoke": True,
        },
    }


def _task_queue_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    task_queue = payload.get("task_queue")
    if isinstance(task_queue, dict):
        return task_queue
    legacy_celery = payload.get("celery")
    if isinstance(legacy_celery, dict):
        return {
            **legacy_celery,
            "processing_ready": False,
            "worker_online": False,
            "legacy_status_shape": True,
            "status_shape_warning": (
                "GET /services/status returned legacy celery summary without task_queue; "
                "restart the API process to load the current runtime."
            ),
        }
    return {}


def _task_queue_checks(task_queue: dict) -> list[dict]:
    if not task_queue:
        return [
            {
                "name": "task_queue_status",
                "status": "failed",
                "message": "GET /services/status did not include task_queue.",
            }
        ]
    checks = [
        ("task_queue_ready", bool(task_queue.get("ready"))),
        ("submission_contract_ready", bool(task_queue.get("submission_contract_ready"))),
    ]
    if "processing_ready" in task_queue:
        checks.append(("processing_ready", bool(task_queue.get("processing_ready"))))
    rows = [
        {
            "name": name,
            "status": "passed" if ok else "warning",
            "message": "ready" if ok else "not ready",
        }
        for name, ok in checks
    ]
    if task_queue.get("legacy_status_shape"):
        rows.append(
            {
                "name": "task_queue_status_shape",
                "status": "warning",
                "message": str(task_queue.get("status_shape_warning") or "legacy status shape"),
            }
        )
    return rows


def _check_from_http(name: str, result: dict | None) -> dict:
    if not result:
        return {"name": name, "status": "failed", "message": "not executed"}
    return {
        "name": name,
        "status": "passed" if result.get("ok") else "failed",
        "message": (
            f"HTTP {result.get('status_code')}"
            if result.get("status_code") is not None
            else str(result.get("error") or "request failed")
        ),
    }


def _task_poll_check(poll_result: dict) -> dict:
    if poll_result.get("status") == "completed" and poll_result.get("successful"):
        return {"name": "task_poll", "status": "passed", "message": "task completed"}
    if poll_result.get("status") == "timeout":
        return {
            "name": "task_poll",
            "status": "warning",
            "message": "task did not finish before timeout",
        }
    return {
        "name": "task_poll",
        "status": "failed",
        "message": str(poll_result.get("task_status") or "failed"),
    }


def _overall_status(
    *,
    checks: list[dict],
    submit: bool,
    wait: bool,
    submission: dict | None,
    poll_result: dict | None,
) -> str:
    if any(check.get("status") == "failed" for check in checks):
        return "failed"
    if submit and (not submission or not submission.get("ok")):
        return "failed"
    if wait and poll_result:
        if poll_result.get("status") == "completed" and poll_result.get("successful"):
            return "passed"
        if poll_result.get("status") == "timeout":
            return "caution"
        return "failed"
    if any(check.get("status") == "warning" for check in checks):
        return "caution"
    return "passed"


def _next_actions(
    status: str,
    task_queue: dict,
    submission: dict | None,
    poll_result: dict | None,
) -> list[str]:
    actions = []
    if task_queue.get("legacy_status_shape"):
        actions.append("重啟 FastAPI，使 /services/status 載入新版 task_queue 診斷欄位。")
    if not task_queue.get("ready"):
        actions.append("確認 Redis broker/backend 與 Celery task exports，重跑 /services/status。")
    if task_queue and not task_queue.get("processing_ready"):
        actions.append("啟動 Celery worker 後重跑 --submit --wait smoke。")
    if submission and not submission.get("ok"):
        actions.append("檢查 /tasks/data-operation structured error detail 與 API logs。")
    if poll_result and poll_result.get("status") == "timeout":
        actions.append("任務已送出但未完成；檢查 worker 是否在線或是否卡在執行中。")
    if not actions and status == "passed":
        actions.append("背景任務提交路徑正常。")
    return actions


def _public_http_result(result: dict | None) -> dict | None:
    if not result:
        return None
    return {
        "ok": bool(result.get("ok")),
        "method": result.get("method"),
        "url": result.get("url"),
        "status_code": result.get("status_code"),
        "json": result.get("json"),
        "error": result.get("error"),
    }


def _parse_json(body: bytes) -> object:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _error_text(parsed: object, body: bytes) -> str:
    if isinstance(parsed, dict) and parsed.get("detail"):
        return str(parsed["detail"])
    return body.decode("utf-8", errors="replace")[:1000]


def _response_status(response: object) -> int:
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        return int(getcode())
    return int(getattr(response, "status", 200) or 200)


def _task_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("task_id") or "").strip()


def _base_url(api_url: str) -> str:
    return str(api_url or DEFAULT_API_URL).rstrip("/") + "/"


def _api_url(base_url: str, path: str) -> str:
    return urljoin(base_url, path.lstrip("/"))
