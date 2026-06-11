from __future__ import annotations


def task_queue_label(task_queue: dict) -> str:
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "可排隊"
    return "可送出"


def task_queue_processing_label(task_queue: dict) -> str:
    if _task_queue_processing_ready(task_queue):
        return "可執行"
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "等待背景執行器"
    return "未確認"


def task_queue_health_rows(service_snapshot: dict) -> list[dict]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    return [
        {
            "項目": "背景任務提交",
            "狀態": task_queue_label(task_queue),
            "說明": _task_queue_submission_detail(task_queue),
        },
        {
            "項目": "背景任務執行",
            "狀態": task_queue_processing_label(task_queue),
            "說明": _task_queue_processing_detail(task_queue),
        },
        {
            "項目": "Redis 佇列服務",
            "狀態": _ok_label(task_queue.get("broker_ok")),
            "說明": _connection_detail(task_queue, "broker_url"),
        },
        {
            "項目": "Redis 結果儲存",
            "狀態": _ok_label(task_queue.get("backend_ok")),
            "說明": _connection_detail(task_queue, "backend_url"),
        },
        {
            "項目": "任務註冊",
            "狀態": "正常" if task_queue.get("submission_contract_ready") else "檢查",
            "說明": _task_wiring_detail(task_queue),
        },
        {
            "項目": "背景執行器",
            "狀態": _worker_label(task_queue),
            "說明": _worker_detail(task_queue),
        },
    ]


def task_queue_health_alert(service_snapshot: dict) -> dict | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    if not task_queue:
        return {
            "severity": "warning",
            "message": "尚未取得背景任務狀態；請確認系統設定 > 維護頁是否能讀取服務狀態。",
        }
    if not task_queue.get("ready"):
        return {
            "severity": "error",
            "message": f"背景任務尚不可送出：{_task_queue_submission_detail(task_queue)}",
        }
    if _task_queue_processing_ready(task_queue):
        worker_count = int(task_queue.get("worker_count") or 0)
        return {
            "severity": "success",
            "message": f"背景任務可送出且背景執行器可執行；目前 {worker_count} 個背景執行器節點回應。",
        }
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return {
            "severity": "warning",
            "message": "背景任務可排隊，但背景執行器未回應；任務可能停在佇列。",
        }
    return {
        "severity": "info",
        "message": "背景任務可送出；背景執行器健康檢查尚未執行或被跳過。",
    }


def task_queue_smoke_command(service_snapshot: dict) -> str | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    commands = task_queue.get("smoke_commands")
    if isinstance(commands, list) and commands:
        return str(commands[0])
    return None


def task_queue_repair_rows(service_snapshot: dict) -> list[dict]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    repair_plan = task_queue.get("repair_plan")
    if isinstance(repair_plan, list):
        return [_task_queue_repair_plan_row(row) for row in repair_plan if isinstance(row, dict)]
    commands = _task_queue_repair_commands(task_queue)
    verify_command = commands["inspect_ping"]
    if not task_queue:
        return [
            {
                "項目": "背景任務狀態",
                "狀態": "未取得",
                "下一步": "確認系統設定 > 維護頁可讀取服務狀態，再重新整理維護頁。",
                "修復指令": "-",
                "驗證指令": "curl -s http://127.0.0.1:8000/services/status",
            }
        ]
    rows: list[dict] = []
    if not task_queue.get("broker_configured"):
        rows.append(
            {
                "項目": "Redis 設定",
                "狀態": "未設定",
                "下一步": "設定 REDIS_URL，或使用一鍵啟動帶起本機 Redis。",
                "修復指令": commands["start_dependencies"],
                "驗證指令": commands["upgrade_audit"],
            }
        )
    if not task_queue.get("broker_ok") or not task_queue.get("backend_ok"):
        rows.append(
            {
                "項目": "Redis 佇列/結果服務",
                "狀態": "未連線",
                "下一步": "啟動本機依賴後，重新檢查 Redis 佇列與結果儲存連線。",
                "修復指令": commands["start_dependencies"],
                "驗證指令": commands["upgrade_audit"],
            }
        )
    if not task_queue.get("submission_contract_ready"):
        rows.append(
            {
                "項目": "Celery 任務註冊",
                "狀態": "未對齊",
                "下一步": _task_wiring_detail(task_queue),
                "修復指令": commands["upgrade_audit"],
                "驗證指令": commands["upgrade_audit"],
            }
        )
    if task_queue.get("ready") and not _task_queue_processing_ready(task_queue):
        if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
            rows.append(
                {
                    "項目": "背景執行器",
                    "狀態": "未回應",
                    "下一步": "啟動背景執行器，或確認既有背景執行器能連到同一個 Redis 訊息佇列。",
                    "修復指令": commands["start_worker"],
                    "驗證指令": verify_command,
                }
            )
        elif not task_queue.get("worker_ping_checked"):
            rows.append(
                {
                    "項目": "背景執行器健康檢查",
                    "狀態": "未檢查",
                    "下一步": "執行健康檢查，確認是否有背景執行器回應。",
                    "修復指令": verify_command,
                    "驗證指令": verify_command,
                }
            )
    return rows


def _task_queue_repair_plan_row(row: dict) -> dict:
    return {
        "項目": row.get("item") or row.get("項目") or "-",
        "狀態": row.get("state") or row.get("狀態") or "-",
        "下一步": row.get("next_step") or row.get("下一步") or "-",
        "修復指令": row.get("repair_command") or row.get("修復指令") or "-",
        "驗證指令": row.get("verify_command") or row.get("驗證指令") or "-",
    }


def _task_queue_from_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def _task_queue_repair_commands(task_queue: dict) -> dict[str, str]:
    defaults = {
        "inspect_ping": ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping",
        "start_dependencies": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "start_worker": (
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker "
            "-B --loglevel=INFO --pool=solo"
        ),
        "upgrade_audit": ".venv/bin/python scripts/upgrade_audit.py",
    }
    configured = task_queue.get("repair_commands")
    if not isinstance(configured, dict):
        return defaults
    return {key: str(configured.get(key) or default) for key, default in defaults.items()}


def _ok_label(value: object) -> str:
    return "正常" if value else "檢查"


def _task_queue_submission_detail(task_queue: dict) -> str:
    if task_queue.get("ready"):
        if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
            return "Redis 與任務註冊可送出；背景執行器未回應時任務會先留在佇列。"
        return "Redis 佇列與結果儲存、Celery 任務註冊已可提交。"
    issues = []
    if not task_queue:
        issues.append("尚未取得背景任務診斷")
    if not task_queue.get("broker_configured"):
        issues.append("Redis 佇列 URL 未設定")
    if not task_queue.get("broker_ok"):
        issues.append("Redis 佇列服務未連線")
    if not task_queue.get("backend_ok"):
        issues.append("Redis 結果儲存未連線")
    if not task_queue.get("submission_contract_ready"):
        issues.append("Celery 任務匯出或名稱尚未對齊")
    return "；".join(issues) or "狀態未知"


def _task_queue_processing_detail(task_queue: dict) -> str:
    if _task_queue_processing_ready(task_queue):
        return "背景任務已可提交，且背景執行器可接手執行。"
    if not task_queue.get("ready"):
        return "背景任務尚不可提交，需先修復提交狀態。"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "背景任務可收件，但背景執行器未回應；任務會停在佇列直到背景執行器上線。"
    return "背景任務可提交，但背景執行器健康檢查尚未執行；執行狀態未確認。"


def _task_queue_processing_ready(task_queue: dict) -> bool:
    if "processing_ready" in task_queue:
        return bool(task_queue.get("processing_ready"))
    return bool(task_queue.get("ready") and task_queue.get("worker_online"))


def _connection_detail(task_queue: dict, url_key: str) -> str:
    url = task_queue.get(url_key) or "-"
    redis_error = task_queue.get("redis_error")
    if redis_error:
        return f"{url}；Redis 錯誤：{redis_error}"
    return str(url)


def _task_wiring_detail(task_queue: dict) -> str:
    if task_queue.get("submission_contract_ready"):
        return "必要 Celery 任務匯出與名稱已對齊。"
    missing = task_queue.get("missing_task_exports")
    if isinstance(missing, list) and missing:
        return "缺少任務匯出：" + "、".join(str(item) for item in missing)
    if task_queue.get("task_export_error"):
        return f"任務匯出錯誤：{task_queue['task_export_error']}"
    if task_queue.get("task_names_match_expected") is False:
        return "任務名稱與預期不一致。"
    return "尚未取得任務註冊診斷。"


def _worker_label(task_queue: dict) -> str:
    if not task_queue.get("worker_ping_checked"):
        return "未檢查"
    if task_queue.get("worker_online"):
        return "在線"
    return "未回應"


def _worker_detail(task_queue: dict) -> str:
    if task_queue.get("worker_online"):
        nodes = task_queue.get("worker_nodes") or []
        if nodes:
            return "回應節點：" + "、".join(str(node) for node in nodes)
        return f"回應數量：{int(task_queue.get('worker_count') or 0)}"
    if not task_queue.get("worker_ping_checked"):
        reason = task_queue.get("worker_ping_skipped_reason") or "背景執行器健康檢查未執行"
        return f"未執行健康檢查：{reason}"
    details = ["背景執行器健康檢查無回應"]
    if task_queue.get("worker_ping_error"):
        details.append(f"錯誤：{task_queue['worker_ping_error']}")
    timeout = task_queue.get("worker_ping_timeout_seconds")
    if timeout:
        details.append(f"timeout {timeout}s")
    return "；".join(details)
