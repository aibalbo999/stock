from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Callable
from urllib.parse import urljoin

from app.core.config import get_settings
from app.services.api_runtime_identity_check import check_api_runtime_identity


DEFAULT_API_URL = get_settings().api_base_url
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
    check_processing_ready: bool = True,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
    check_runtime_identity: bool = True,
    expected_api_commit: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    base_url = _base_url(api_url)
    checks = []
    runtime_identity = None
    if check_runtime_identity:
        runtime_identity = check_api_runtime_identity(
            base_url,
            expected_commit=expected_api_commit,
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
        checks.append(_runtime_identity_check(runtime_identity))
    service_status = _request_json(
        "GET",
        _api_url(base_url, "/services/status"),
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    checks.append(_check_from_http("service_status", service_status))
    task_queue = _task_queue_payload(service_status.get("json"))
    checks.extend(_task_queue_checks(task_queue, check_processing_ready=check_processing_ready))

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
        "check_processing_ready": check_processing_ready,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "submission_payload": _submission_payload(operation=operation, tickers=tickers)
        if submit
        else None,
        "runtime_identity": runtime_identity,
        "task_queue": task_queue,
        "submission": _public_http_result(submission),
        "task_poll": poll_result,
        "checks": checks,
        "next_actions": _next_actions(
            status,
            task_queue,
            submission,
            poll_result,
            runtime_identity,
            check_processing_ready=check_processing_ready,
        ),
    }


def format_task_submission_smoke(report: dict) -> str:
    lines = [
        f"背景任務送出檢查: {report.get('status', 'unknown')}",
        f"- API: {report.get('api_url', '-')}",
        f"- 操作: {report.get('operation', '-')}",
        f"- 會送出任務: {_yes_no(report.get('submit'))}",
    ]
    task_queue = report.get("task_queue") if isinstance(report.get("task_queue"), dict) else {}
    runtime_identity = (
        report.get("runtime_identity")
        if isinstance(report.get("runtime_identity"), dict)
        else {}
    )
    if runtime_identity:
        lines.append(
            "- API 執行版本: "
            f"狀態={runtime_identity.get('status', '-')}；"
            f"預期={runtime_identity.get('expected_commit_short') or '-'}；"
            f"實際={runtime_identity.get('actual_commit_short') or '-'}"
        )
    if task_queue:
        lines.append(
            "- 背景任務佇列: "
            f"可送出={_yes_no(task_queue.get('ready'))}；"
            f"可執行={_yes_no(task_queue.get('processing_ready'))}；"
            f"背景執行器在線={_yes_no(task_queue.get('worker_online'))}"
        )
    submission = report.get("submission") if isinstance(report.get("submission"), dict) else {}
    if submission:
        body = submission.get("json") if isinstance(submission.get("json"), dict) else {}
        lines.append(
            "- 任務送出: "
            f"成功={_yes_no(submission.get('ok'))}；"
            f"HTTP={submission.get('status_code')}；"
            f"任務 ID={body.get('task_id', '-')}"
        )
    poll = report.get("task_poll") if isinstance(report.get("task_poll"), dict) else {}
    if poll:
        lines.append(
            "- 任務輪詢: "
            f"狀態={poll.get('status', '-')}；"
            f"完成={_yes_no(poll.get('ready'))}；"
            f"成功={_yes_no(poll.get('successful'))}"
        )
    for action in report.get("next_actions") or []:
        lines.append(f"- 下一步: {action}")
    return "\n".join(lines)


def _yes_no(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value if value is not None else "-")


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


def _task_queue_checks(task_queue: dict, *, check_processing_ready: bool = True) -> list[dict]:
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
    if check_processing_ready and "processing_ready" in task_queue:
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


def _runtime_identity_check(runtime_identity: dict) -> dict:
    status = str(runtime_identity.get("status") or "failed")
    reason = runtime_identity.get("reason") or runtime_identity.get("error")
    if status == "passed":
        message = "API runtime commit matches current checkout."
    elif status == "skipped":
        message = str(reason or "runtime identity check skipped")
    else:
        message = str(reason or "API runtime identity check failed")
    return {
        "name": "api_runtime_identity",
        "status": status,
        "message": message,
        "expected_commit_short": runtime_identity.get("expected_commit_short"),
        "actual_commit_short": runtime_identity.get("actual_commit_short"),
    }


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
    runtime_identity: dict | None,
    *,
    check_processing_ready: bool = True,
) -> list[str]:
    actions = []
    runtime_identity = runtime_identity if isinstance(runtime_identity, dict) else {}
    if runtime_identity.get("status") == "failed":
        reason = str(runtime_identity.get("reason") or runtime_identity.get("error") or "")
        if reason == "api_runtime_commit_mismatch":
            actions.append("重啟 API 服務與背景執行器，目前 API 版本不是目前工作樹 commit。")
        elif reason == "api_runtime_commit_unavailable":
            actions.append("確認 /services/runtime-identity 可回傳 git_commit，或用 --skip-runtime-identity 略過遠端部署比對。")
        else:
            actions.append("確認 API 已啟動並可讀取 /services/runtime-identity，或用 --skip-runtime-identity 略過比對。")
    if task_queue.get("legacy_status_shape"):
        actions.append("重啟 API 服務，使 /services/status 載入新版背景任務診斷欄位。")
    if not task_queue.get("ready"):
        actions.append("確認背景任務佇列、結果儲存與任務註冊，再重跑系統狀態檢查。")
    poll_succeeded = bool(
        poll_result
        and poll_result.get("status") == "completed"
        and poll_result.get("successful")
    )
    if (
        check_processing_ready
        and task_queue
        and not task_queue.get("processing_ready")
        and not poll_succeeded
    ):
        actions.append("啟動背景執行器後重跑 --submit --wait 背景任務送出檢查。")
    if submission and not submission.get("ok"):
        actions.append("檢查 /tasks/data-operation structured error detail 與 API logs。")
    if poll_result and poll_result.get("status") == "timeout":
        actions.append("任務已送出但未完成；檢查背景執行器是否在線或是否卡在執行中。")
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
