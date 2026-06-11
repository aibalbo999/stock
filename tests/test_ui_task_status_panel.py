from __future__ import annotations

from app.ui.task_status_panel import (
    _fetch_task_status,
    _render_task_status_panel_controls,
    company_filing_gap_rows,
    render_task_action_preflight_summary,
    task_action_preflight_summary,
    task_execution_context_rows,
    task_run_summary_rows,
    task_status_diagnostic_rows,
    task_status_metric_values,
    task_status_poll_caption,
    task_status_poll_interval_seconds,
    task_status_progress_caption,
)


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict = {}


class FakeTaskStatusStreamlit:
    def __init__(
        self,
        *,
        checked: dict[str, bool] | None = None,
        pressed: set[str] | None = None,
    ):
        self.session_state: dict = {}
        self.checked = checked or {}
        self.pressed = pressed or set()
        self.buttons: list[dict] = []
        self.checkboxes: list[dict] = []
        self.captions: list[str] = []
        self.markdowns: list[str] = []
        self.successes: list[str] = []

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def checkbox(self, label: str, *, value: bool = False, key: str):
        self.checkboxes.append({"label": label, "value": value, "key": key})
        return self.checked.get(key, value)

    def button(self, label: str, *, key: str, disabled: bool = False):
        self.buttons.append({"label": label, "key": key, "disabled": disabled})
        return key in self.pressed and not disabled

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def markdown(self, body: str, **_kwargs) -> None:
        self.markdowns.append(str(body))

    def success(self, text: str) -> None:
        self.successes.append(text)


def test_task_action_preflight_summary_warns_before_retry_confirmation() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-quota",
            "status": "FAILURE",
            "operation": "report_generation",
            "retryable": True,
            "retry_kind": "report_generation",
            "error_category": "quota",
        },
        action="retry",
        confirmed=False,
    )

    assert summary == {
        "state": "attention",
        "label": "任務操作摘要",
        "title": "準備重試背景任務",
        "detail": "Task task-quota｜狀態 失敗｜操作 報告生成｜重試類型 報告生成",
        "next_step": "勾選確認後，再按「重試任務」重新送出背景任務。",
        "impact": "會重新排隊並可能再次消耗模型、外部資料源或 API 額度；若錯誤類型是 quota，建議先確認額度是否恢復。",
    }


def test_task_action_preflight_summary_blocks_explicitly_non_retryable_task() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-bad-payload",
            "status": "FAILURE",
            "operation": "data_operation",
            "retryable": False,
            "retry_kind": None,
            "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
        },
        action="retry",
        confirmed=True,
    )

    assert summary == {
        "state": "blocked",
        "label": "任務操作摘要",
        "title": "此任務不支援一鍵重試",
        "detail": "Task task-bad-payload｜狀態 失敗｜操作 資料補強｜重試類型 -",
        "next_step": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
        "impact": "尚未送出重試；先修正輸入、白名單或外部設定，避免重複失敗與額度浪費。",
    }


def test_task_action_preflight_summary_blocks_retry_for_successful_task() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-success",
            "status": "SUCCESS",
            "operation": "market_refresh",
            "ready": True,
            "successful": True,
        },
        action="retry",
        confirmed=True,
    )

    assert summary == {
        "state": "blocked",
        "label": "任務操作摘要",
        "title": "此任務已成功，不需要一鍵重試",
        "detail": "Task task-success｜狀態 成功｜操作 市場資料刷新｜重試類型 -",
        "next_step": "若需要重新執行，請回原本功能入口建立新任務。",
        "impact": "不會送出重試；避免對已成功任務重複消耗模型、外部資料源或 API 額度。",
    }


def test_task_action_preflight_summary_blocks_cancel_for_finished_task() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-success",
            "status": "SUCCESS",
            "operation": "market_refresh",
            "ready": True,
            "successful": True,
        },
        action="cancel",
        confirmed=True,
    )

    assert summary == {
        "state": "blocked",
        "label": "任務操作摘要",
        "title": "此任務已結束，不能取消",
        "detail": "Task task-success｜狀態 成功｜操作 市場資料刷新",
        "next_step": "不需取消；若結果失敗且支援重試，請使用重試或回原入口重新送出。",
        "impact": "不會送出取消要求；避免改動已完成任務紀錄。",
    }


def test_task_action_preflight_summary_uses_execution_context_operation() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-maintenance",
            "status": "SUCCESS",
            "ready": True,
            "successful": True,
            "execution_context": {
                "run_source": "celery_maintenance_cleanup",
                "operation": "maintenance_cleanup",
            },
        },
        action="cancel",
        confirmed=True,
    )

    assert summary["detail"] == "Task task-maintenance｜狀態 成功｜操作 維護清理"


def test_task_action_preflight_summary_infers_operation_from_run_payload() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-maintenance",
            "status": "SUCCESS",
            "ready": True,
            "successful": True,
            "run": {
                "source": "celery_maintenance_cleanup",
                "payload": (
                    '{"task": "maintenance_cleanup", '
                    '"payload": {"latest_reports_only": true}}'
                ),
            },
        },
        action="retry",
        confirmed=True,
    )

    assert (
        summary["detail"]
        == "Task task-maintenance｜狀態 成功｜操作 維護清理｜重試類型 -"
    )


def test_task_action_preflight_summary_allows_confirmed_cancel() -> None:
    summary = task_action_preflight_summary(
        {
            "task_id": "task-running",
            "status": "STARTED",
            "operation": "market_refresh",
        },
        action="cancel",
        confirmed=True,
    )

    assert summary == {
        "state": "ready",
        "label": "任務操作摘要",
        "title": "可以送出取消要求",
        "detail": "Task task-running｜狀態 執行中｜操作 市場資料刷新",
        "next_step": "按「取消任務」通知背景任務停止；取消後請刷新狀態確認是否已停止。",
        "impact": "取消要求會寫入任務紀錄；若 worker 已完成，可能只會留下取消請求紀錄。",
    }


def test_render_task_action_preflight_summary_outputs_operator_card(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit()
    monkeypatch.setattr(task_status_panel, "st", fake_st)

    render_task_action_preflight_summary(
        {
            "state": "attention",
            "label": "任務操作摘要",
            "title": "準備重試背景任務",
            "detail": "Task task-1｜狀態 FAILURE",
            "next_step": "勾選確認後再重試。",
            "impact": "可能再次消耗模型或資料源額度。",
        }
    )

    assert any(
        'class="task-action-preflight-summary is-attention"' in markdown
        and "準備重試背景任務" in markdown
        and "可能再次消耗模型或資料源額度" in markdown
        for markdown in fake_st.markdowns
    )


def test_fetch_task_status_uses_api_loader_and_stores_dict(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeStreamlit()
    captured = {}
    monkeypatch.setattr(task_status_panel, "st", fake_st)

    def fake_loader(path: str, fallback, *, error_message: str):
        captured.update({"path": path, "fallback": fallback, "error_message": error_message})
        return {"task_id": "task-1", "status": "SUCCESS"}

    monkeypatch.setattr(task_status_panel, "load_api_json_or_default", fake_loader)

    assert _fetch_task_status("task-1", "task_status") == {
        "task_id": "task-1",
        "status": "SUCCESS",
    }
    assert fake_st.session_state["task_status"] == {"task_id": "task-1", "status": "SUCCESS"}
    assert captured == {
        "path": "/tasks/task-1",
        "fallback": None,
        "error_message": "查詢失敗",
    }


def test_fetch_task_status_ignores_non_dict_loader_fallback(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeStreamlit()
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "load_api_json_or_default", lambda *args, **kwargs: None)

    assert _fetch_task_status("task-1", "task_status") is None
    assert "task_status" not in fake_st.session_state


def test_task_status_controls_require_confirmation_before_cancel_or_retry(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit()
    fake_st.session_state["task_status"] = {"task_id": "task-1", "status": "STARTED"}
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "render_task_status", lambda task_status: None)

    api_calls = []
    monkeypatch.setattr(
        task_status_panel,
        "run_api_action_or_none",
        lambda action, *, error_message: api_calls.append(error_message),
    )

    assert (
        _render_task_status_panel_controls(
            task_id="task-1",
            refresh_key="task_panel",
            status_state_key="task_status",
            apply_result_key=None,
            task_state_key="last_task_id",
        )
        == {"task_id": "task-1", "status": "STARTED"}
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會取消目前背景任務",
            "value": False,
            "key": "task_panel_confirm_cancel",
        },
        {
            "label": "我了解這會重新送出任務，可能消耗模型或資料源額度",
            "value": False,
            "key": "task_panel_confirm_retry",
        },
    ]
    assert fake_st.buttons == [
        {"label": "取消任務", "key": "task_panel_cancel", "disabled": True},
        {"label": "重試任務", "key": "task_panel_retry", "disabled": True},
    ]
    assert any("避免誤觸取消" in caption for caption in fake_st.captions)
    assert any("避免誤觸重試" in caption for caption in fake_st.captions)
    assert api_calls == []


def test_task_status_controls_submit_only_after_confirmation(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit(
        checked={
            "task_panel_confirm_cancel": True,
            "task_panel_confirm_retry": True,
        },
        pressed={"task_panel_cancel", "task_panel_retry"},
    )
    fake_st.session_state["task_status"] = {
        "task_id": "task-1",
        "status": "FAILURE",
        "operation": "report_generation",
        "retryable": True,
        "retry_kind": "report_generation",
    }
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "render_task_status", lambda task_status: None)

    posted_paths = []

    def fake_api_task_post(path: str, payload: dict) -> dict:
        posted_paths.append((path, payload))
        return {"task_id": "task-retry"} if path.endswith("/retry") else {"task_id": "task-1"}

    monkeypatch.setattr(task_status_panel, "api_task_post", fake_api_task_post)
    monkeypatch.setattr(
        task_status_panel,
        "run_api_action_or_none",
        lambda action, *, error_message: action(),
    )

    _render_task_status_panel_controls(
        task_id="task-1",
        refresh_key="task_panel",
        status_state_key="task_status",
        apply_result_key=None,
        task_state_key="last_task_id",
    )

    assert posted_paths == [("/tasks/task-1/retry", {})]
    assert fake_st.buttons == [
        {"label": "取消任務", "key": "task_panel_cancel", "disabled": True},
        {"label": "重試任務", "key": "task_panel_retry", "disabled": False},
    ]
    assert fake_st.session_state["last_task_id"] == "task-retry"
    assert fake_st.session_state["task_status"] == {"task_id": "task-retry"}
    assert "已送出取消要求。" not in fake_st.successes
    assert "已送出重試任務：task-retry" in fake_st.successes


def test_task_status_controls_allow_cancel_for_running_task_after_confirmation(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit(
        checked={
            "task_panel_confirm_cancel": True,
            "task_panel_confirm_retry": False,
        },
        pressed={"task_panel_cancel"},
    )
    fake_st.session_state["task_status"] = {
        "task_id": "task-running",
        "status": "STARTED",
        "operation": "market_refresh",
        "ready": False,
    }
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "render_task_status", lambda task_status: None)

    posted_paths = []

    def fake_api_task_post(path: str, payload: dict) -> dict:
        posted_paths.append((path, payload))
        return {"task_id": "task-running", "cancel_requested": True}

    monkeypatch.setattr(task_status_panel, "api_task_post", fake_api_task_post)
    monkeypatch.setattr(
        task_status_panel,
        "run_api_action_or_none",
        lambda action, *, error_message: action(),
    )

    _render_task_status_panel_controls(
        task_id="task-running",
        refresh_key="task_panel",
        status_state_key="task_status",
        apply_result_key=None,
        task_state_key="last_task_id",
    )

    assert posted_paths == [("/tasks/task-running/cancel", {})]
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["取消任務"]["disabled"] is False
    assert by_label["重試任務"]["disabled"] is True
    assert "已送出取消要求。" in fake_st.successes


def test_task_status_controls_block_retry_when_task_is_explicitly_non_retryable(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit(
        checked={
            "task_panel_confirm_cancel": True,
            "task_panel_confirm_retry": True,
        },
        pressed={"task_panel_retry"},
    )
    fake_st.session_state["task_status"] = {
        "task_id": "task-1",
        "status": "FAILURE",
        "operation": "data_operation",
        "retryable": False,
        "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
    }
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "render_task_status", lambda task_status: None)

    posted_paths = []
    monkeypatch.setattr(
        task_status_panel,
        "run_api_action_or_none",
        lambda action, *, error_message: posted_paths.append(error_message),
    )

    _render_task_status_panel_controls(
        task_id="task-1",
        refresh_key="task_panel",
        status_state_key="task_status",
        apply_result_key=None,
        task_state_key="last_task_id",
    )

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["重試任務"]["disabled"] is True
    assert any(
        'class="task-action-preflight-summary is-blocked"' in markdown
        and "此任務不支援一鍵重試" in markdown
        and "payload 不支援自動重試" in markdown
        for markdown in fake_st.markdowns
    )
    assert posted_paths == []


def test_task_status_controls_block_retry_and_cancel_for_successful_task(monkeypatch) -> None:
    from app.ui import task_status_panel

    fake_st = FakeTaskStatusStreamlit(
        checked={
            "task_panel_confirm_cancel": True,
            "task_panel_confirm_retry": True,
        },
        pressed={"task_panel_cancel", "task_panel_retry"},
    )
    fake_st.session_state["task_status"] = {
        "task_id": "task-success",
        "status": "SUCCESS",
        "operation": "market_refresh",
        "ready": True,
        "successful": True,
    }
    monkeypatch.setattr(task_status_panel, "st", fake_st)
    monkeypatch.setattr(task_status_panel, "render_task_status", lambda task_status: None)

    posted_paths = []
    monkeypatch.setattr(
        task_status_panel,
        "run_api_action_or_none",
        lambda action, *, error_message: posted_paths.append(error_message),
    )

    _render_task_status_panel_controls(
        task_id="task-success",
        refresh_key="task_panel",
        status_state_key="task_status",
        apply_result_key=None,
        task_state_key="last_task_id",
    )

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["取消任務"]["disabled"] is True
    assert by_label["重試任務"]["disabled"] is True
    assert any(
        "此任務已結束，不能取消" in markdown
        and "此任務已成功，不需要一鍵重試" in "\n".join(fake_st.markdowns)
        for markdown in fake_st.markdowns
    )
    assert posted_paths == []


def test_task_status_diagnostic_rows_show_failure_category_and_next_steps() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "report_generation",
            "error_category": "quota",
            "error_severity": "warning",
            "error_summary": "模型/API 額度或速率限制",
            "retryable": True,
            "retry_kind": "report_generation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": [
                "查看 AI 額度與模型路由或資料源額度。",
                "等待額度重置後再重試。",
            ],
        }
    )

    assert rows == [
        {
            "operation": "報告生成",
            "category": "模型/API 額度",
            "severity": "警告",
            "summary": "模型/API 額度或速率限制",
            "retry": "可重試",
            "retry_kind": "報告生成",
            "action_route": "一鍵重試",
            "action_route_detail": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-quota/retry",
            "next_steps": "查看 AI 額度與模型路由或資料源額度。；等待額度重置後再重試。",
        }
    ]


def test_task_status_diagnostic_rows_show_external_config_action_route() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "data_operation",
            "error_category": "task_queue",
            "error_severity": "error",
            "error_summary": "Redis/Celery queue 或 worker 異常",
            "retryable": False,
            "retry_kind": None,
            "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
            "next_steps": [
                "確認 /services/status 的 task_queue.ready 與 worker_online。",
                "執行 Celery inspect ping 或重新啟動 Redis/Celery worker。",
            ],
        }
    )

    assert rows[0]["action_route"] == "外部配置缺失"
    assert rows[0]["operation"] == "資料補強"
    assert rows[0]["category"] == "背景任務服務"
    assert rows[0]["severity"] == "錯誤"
    assert "Redis/Celery" in rows[0]["action_route_detail"]
    assert "/services/status" not in rows[0]["next_steps"]
    assert "task_queue.ready" not in rows[0]["next_steps"]
    assert "系統設定 > 維護 > 背景任務觀測" in rows[0]["next_steps"]


def test_task_status_diagnostic_rows_show_structured_api_config_guard() -> None:
    rows = task_status_diagnostic_rows(
        {
            "operation": "company_filings_fetch",
            "error_category": "external_config",
            "error_severity": "warning",
            "error_summary": "外部資料源或文件後援配置缺失",
            "retryable": True,
            "retry_kind": "data_operation",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-structured-api/retry",
            "next_steps": [
                "查看 /services/status 與外部部署 readiness checklist，確認缺少的 env key。",
                "補齊結構化文件 API、Browser render/unlocker、Visual RAG gateway 或 Neo4j 設定後再重送任務。",
            ],
        }
    )

    assert rows[0]["action_route"] == "外部配置缺失"
    assert "Structured API" in rows[0]["action_route_detail"]
    assert "外部部署 readiness" in rows[0]["next_steps"]


def test_task_status_diagnostic_rows_hide_when_no_failure_category() -> None:
    assert task_status_diagnostic_rows({"status": "SUCCESS"}) == []


def test_task_status_metric_values_use_operator_labels() -> None:
    rows = task_status_metric_values(
        {
            "status": "FAILURE",
            "ready": True,
            "successful": False,
            "run": {"id": 42},
        }
    )

    assert rows == [
        {"label": "任務狀態", "value": "失敗"},
        {"label": "是否結束", "value": "已結束"},
        {"label": "是否成功", "value": "未成功"},
        {"label": "執行紀錄", "value": "#42"},
    ]
    rendered = str(rows)
    assert "Task" not in rendered
    assert "Ready" not in rendered
    assert "Success" not in rendered
    assert "Run" not in rendered
    assert "FAILURE" not in rendered


def test_task_run_summary_rows_use_operator_columns_and_status() -> None:
    rows = task_run_summary_rows(
        {
            "run": {
                "id": 42,
                "status": "failed",
                "report_id": 7,
                "output_path": "reports/latest.html",
                "started_at": "2026-06-11T09:00:00+08:00",
                "finished_at": "2026-06-11T09:03:00+08:00",
            }
        }
    )

    assert rows == [
        {
            "執行紀錄": "#42",
            "狀態": "失敗",
            "報告": "#7",
            "輸出檔": "reports/latest.html",
            "開始": "2026-06-11T09:00:00+08:00",
            "結束": "2026-06-11T09:03:00+08:00",
        }
    ]
    rendered = str(rows)
    assert "run_id" not in rendered
    assert "report_id" not in rendered
    assert "output_path" not in rendered
    assert "started_at" not in rendered
    assert "finished_at" not in rendered
    assert "failed" not in rendered


def test_task_status_progress_caption_labels_status_for_operator() -> None:
    assert task_status_progress_caption(
        {
            "status": "STARTED",
            "progress": {"status": "STARTED", "current_step": "fetch_market_data"},
        }
    ) == "進度：執行中｜fetch_market_data"
    assert task_status_progress_caption({"status": "SUCCESS"}) == ""


def test_task_execution_context_rows_summarize_payload_and_exception() -> None:
    rows = task_execution_context_rows(
        {
            "task_id": "task-sensitive",
            "status": "FAILURE",
            "ready": True,
            "successful": False,
            "execution_context": {
                "celery_status": "FAILURE",
                "ready": True,
                "successful": False,
                "run_id": 35,
                "run_status": "failed",
                "run_source": "celery_data_operation",
                "operation": "market_refresh",
                "payload_shape": {
                    "present": True,
                    "top_level_keys": ["celery_task_id", "operation", "payload", "task"],
                    "request_keys": [],
                    "operation_payload_keys": ["<sensitive>", "tickers"],
                    "ticker_count": 2,
                    "sensitive_key_count": 1,
                },
                "celery_info_shape": {
                    "present": True,
                    "type": "dict",
                    "top_level_keys": ["progress"],
                    "progress_keys": ["current_step"],
                    "sensitive_key_count": 0,
                },
                "exception_type": "RuntimeError",
                "exception_message_preview": "api_key=<redacted> timeout",
            },
        }
    )

    assert rows == [
        {
            "celery_status": "失敗",
            "ready": "已結束",
            "successful": "未成功",
            "run": "#35",
            "run_status": "失敗",
            "source": "資料補強背景任務",
            "operation": "市場資料刷新",
            "payload": (
                "資料欄位：celery_task_id、operation、payload、task；股票 2 檔；"
                "任務欄位：已遮蔽敏感欄位、tickers；已遮蔽敏感欄位 1 個"
            ),
            "celery_info": "回報型態：dict；回報欄位：progress；進度欄位：current_step",
            "exception": "RuntimeError: api_key=<redacted> timeout",
        }
    ]


def test_task_execution_context_rows_hide_without_context() -> None:
    assert task_execution_context_rows({"status": "SUCCESS"}) == []


def test_company_filing_gap_rows_show_visual_rag_next_actions_from_data_task_result() -> None:
    rows = company_filing_gap_rows(
        {
            "result": {
                "operation": "company_filings_fetch",
                "result": {
                    "gap_summary": {
                        "visual_rag_setup_tickers": ["2382"],
                        "visual_rag_review_tickers": ["3324"],
                    },
                    "next_actions": [
                        {
                            "ticker": "2382",
                            "company_name": "廣達",
                            "action": "configure_company_filing_visual_rag",
                            "missing_required_types": ["annual_report"],
                            "error_categories": ["visual_rag_not_configured"],
                            "reason": "請確認 PyMuPDF、VLM key 與模型。",
                        },
                        {
                            "ticker": "3324",
                            "company_name": "雙鴻",
                            "action": "review_visual_rag_or_manual_import",
                            "missing_recommended_types": ["investor_presentation"],
                            "error_categories": ["visual_rag_quota"],
                            "reason": "Visual RAG 額度用完。",
                        },
                    ],
                },
            }
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "廣達",
            "下一步": "設定 Visual RAG",
            "缺必要文件": "annual_report",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_not_configured",
            "原因": "請確認 PyMuPDF、VLM key 與模型。",
        },
        {
            "股票": "3324",
            "公司": "雙鴻",
            "下一步": "檢查 Visual RAG/人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "investor_presentation",
            "錯誤類型": "visual_rag_quota",
            "原因": "Visual RAG 額度用完。",
        },
    ]


def test_company_filing_gap_rows_fall_back_to_gap_summary() -> None:
    rows = company_filing_gap_rows(
        {
            "result": {
                "company_filings": {
                    "gap_summary": {
                        "visual_rag_setup_tickers": ["2382"],
                        "visual_rag_review_tickers": ["3324"],
                        "ocr_required_tickers": ["2308"],
                    }
                }
            }
        }
    )

    assert rows == [
        {
            "股票": "2382",
            "公司": "-",
            "下一步": "設定 Visual RAG",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_setup_tickers",
            "原因": "需要 PyMuPDF、VLM model 或 vision key/gateway",
        },
        {
            "股票": "3324",
            "公司": "-",
            "下一步": "檢查 Visual RAG/人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "visual_rag_review_tickers",
            "原因": "VLM 額度、模型回應或抽取結果需要檢查",
        },
        {
            "股票": "2308",
            "公司": "-",
            "下一步": "OCR 或人工匯入",
            "缺必要文件": "-",
            "缺建議文件": "-",
            "錯誤類型": "ocr_required_tickers",
            "原因": "PDF 沒有可抽取文字或解析失敗",
        },
    ]


def test_task_status_poll_interval_backs_off_for_queued_tasks() -> None:
    assert (
        task_status_poll_interval_seconds(
            {"status": "PENDING", "ready": False},
            default_seconds=5,
        )
        == 8
    )


def test_task_status_poll_interval_backs_off_more_for_retry_tasks() -> None:
    assert (
        task_status_poll_interval_seconds(
            {"status": "RETRY", "ready": False},
            default_seconds=5,
        )
        == 15
    )


def test_task_status_poll_interval_keeps_fast_polling_for_active_progress() -> None:
    assert (
        task_status_poll_interval_seconds(
            {
                "status": "STARTED",
                "ready": False,
                "progress": {"progress_pct": 0.4},
            },
            default_seconds=5,
        )
        == 5
    )


def test_task_status_poll_caption_explains_queued_poll_cadence() -> None:
    assert (
        task_status_poll_caption(
            {"status": "PENDING", "ready": False},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：約每 8 秒更新，排隊中。"
    )


def test_task_status_poll_caption_explains_retry_poll_cadence() -> None:
    assert (
        task_status_poll_caption(
            {"status": "RETRY", "ready": False},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：約每 15 秒更新，等待重試。"
    )


def test_task_status_poll_caption_reports_stopped_when_ready() -> None:
    assert (
        task_status_poll_caption(
            {"status": "SUCCESS", "ready": True},
            auto_refresh=True,
            fragment_supported=True,
            default_seconds=5,
        )
        == "狀態輪詢：任務已結束，自動刷新停止。"
    )
