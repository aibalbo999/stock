from __future__ import annotations


def local_dependency_status_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    ports = status.get("ports") if isinstance(status.get("ports"), list) else []
    return [
        {
            "服務": row.get("label") or row.get("service") or "-",
            "狀態": "已啟動" if row.get("open") else "未偵測",
            "本機端口": f"{row.get('host') or '127.0.0.1'}:{row.get('port') or '-'}",
            "用途": row.get("role") or "-",
        }
        for row in ports
        if isinstance(row, dict)
    ]


def local_dependency_repair_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    repair_plan = status.get("repair_plan") if isinstance(status.get("repair_plan"), list) else []
    return [
        {
            "項目": row.get("item") or row.get("項目") or "-",
            "狀態": row.get("state") or row.get("狀態") or "-",
            "下一步": row.get("next_step") or row.get("下一步") or "-",
            "修復指令": row.get("repair_command") or row.get("修復指令") or "-",
            "驗證指令": row.get("verify_command") or row.get("驗證指令") or "-",
        }
        for row in repair_plan
        if isinstance(row, dict)
    ]


def local_dependency_last_start_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    last_start = status.get("last_start") if isinstance(status.get("last_start"), dict) else {}
    if not last_start.get("available"):
        return []
    updated_at = str(last_start.get("updated_at") or "-")
    rows = [
        {
            "項目": "最近啟動",
            "狀態": last_start.get("status") or "-",
            "更新時間": updated_at,
            "說明": last_start.get("message") or "-",
            "細節": _local_dependency_last_start_detail(last_start),
        }
    ]
    wait_status = last_start.get("wait") if isinstance(last_start.get("wait"), dict) else {}
    for service, ready in sorted(wait_status.items()):
        if isinstance(ready, bool):
            rows.append(
                {
                    "項目": f"等待 {_local_dependency_wait_label(str(service))}",
                    "狀態": "就緒" if ready else "尚未就緒",
                    "更新時間": updated_at,
                    "說明": "scripts/start_system.py --start-dependencies 等待結果",
                    "細節": str(last_start.get("path") or "-"),
                }
            )
        elif isinstance(ready, dict):
            rows.append(
                {
                    "項目": _local_dependency_wait_label(str(service)),
                    "狀態": ready.get("status") or "-",
                    "更新時間": updated_at,
                    "說明": ready.get("reason") or "-",
                    "細節": ready.get("provider") or ready.get("browser") or "-",
                }
            )
    return rows


def local_dependency_port_state(local_dependency_status: dict | None, service: str) -> bool | None:
    if not service or not isinstance(local_dependency_status, dict):
        return None
    ports = local_dependency_status.get("ports")
    if not isinstance(ports, list):
        return None
    for row in ports:
        if isinstance(row, dict) and row.get("service") == service:
            return bool(row.get("open"))
    return None


def _local_dependency_last_start_detail(last_start: dict) -> str:
    services = "、".join(str(service) for service in last_start.get("services") or []) or "-"
    env_keys = "、".join(str(key) for key in last_start.get("applied_env_keys") or []) or "-"
    unlocker = "含 unlocker" if last_start.get("include_unlocker") else "核心依賴"
    wait_seconds = last_start.get("wait_seconds")
    wait_text = f"等待 {wait_seconds}s" if wait_seconds is not None else "等待時間未記錄"
    return f"{unlocker}；服務 {services}；{wait_text}；env keys {env_keys}"


def _local_dependency_wait_label(service: str) -> str:
    labels = {
        "neo4j": "Neo4j 7687",
        "browserless": "Browserless 3000",
        "chroma": "Chroma 8001",
        "postgres": "Postgres 5432",
        "redis": "Redis 6379",
        "flaresolverr": "FlareSolverr 8191",
        "browser_render_fallback": "Browser render fallback",
    }
    return labels.get(service, service)
