from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_operator_workbench_status(source_context: FrontendSourceContext) -> dict:
    analysis_workspace_source = source_context.ui_sources.get("analysis_workspace.py", "")
    data_enrichment_common_source = source_context.ui_sources.get(
        "data_enrichment_common.py", ""
    )
    operator_status_source = source_context.ui_sources.get("operator_status.py", "")
    operator_decisions_source = source_context.ui_sources.get("operator_decisions.py", "")

    return {
        "frontend_operator_workbench_status_extracted": True,
        "frontend_operator_workbench_status_path": (
            "app/services/status_frontend_operator_workbench.py"
        ),
        "ui_analysis_submission_quota_confirmation_enabled": (
            "def analysis_submission_ready(" in analysis_workspace_source
            and "analysis_quota_confirmed = st.checkbox(" in analysis_workspace_source
            and 'key="confirm_analysis_submission_quota_usage"' in analysis_workspace_source
            and "我了解這會送出分析背景任務並消耗 AI/API 額度"
            in analysis_workspace_source
            and "分析會在背景執行，送出後可用任務編號查詢進度。"
            in analysis_workspace_source
            and "分析任務一律交由 FastAPI / Celery 背景執行"
            not in analysis_workspace_source
            and "送出後可用 task id 查詢進度" not in analysis_workspace_source
            and "避免誤觸與免費額度消耗" in analysis_workspace_source
            and "disabled=not analysis_submission_ready(" in analysis_workspace_source
            and "ai_discovery_mode=bool(ai_discovery_mode)" in analysis_workspace_source
            and "manual_tickers=tickers" in analysis_workspace_source
            and 'submit_api_task(\n                    "/pipeline/run_discovered_async"'
            in analysis_workspace_source
            and 'submit_api_task(\n                    "/reports/generate_async"'
            in analysis_workspace_source
        ),
        "ui_analysis_submission_preflight_summary_enabled": (
            "def analysis_submission_summary(" in analysis_workspace_source
            and "def _render_analysis_submission_summary(" in analysis_workspace_source
            and "analysis_submission_summary(" in analysis_workspace_source
            and "_render_analysis_submission_summary(submission_summary)"
            in analysis_workspace_source
            and 'class="analysis-submission-summary' in analysis_workspace_source
            and "送出前確認" in analysis_workspace_source
            and "可送出分析背景任務" in analysis_workspace_source
            and "手動模式請先選擇至少一檔股票" in analysis_workspace_source
        ),
        "ui_analysis_submission_quota_pressure_guidance_enabled": (
            "def analysis_submission_quota_pressure(" in analysis_workspace_source
            and "quota_pressure" in analysis_workspace_source
            and "quota_pressure_class" in analysis_workspace_source
            and "額度壓力：" in analysis_workspace_source
            and "適合快速試跑或額度偏緊時使用" in analysis_workspace_source
            and "適合收盤後或額度剛重置時執行" in analysis_workspace_source
            and "class=\"quota-pressure" in analysis_workspace_source
        ),
        "ui_data_task_followup_summary_enabled": (
            "def data_task_followup_summary(" in data_enrichment_common_source
            and "def _render_data_task_followup_summary(" in data_enrichment_common_source
            and "data_task_followup_summary(task_status)" in data_enrichment_common_source
            and "_render_data_task_followup_summary(" in data_enrichment_common_source
            and 'class="data-task-followup-summary' in data_enrichment_common_source
            and "資料補強完成" in data_enrichment_common_source
            and "等待資料補強完成" in data_enrichment_common_source
            and "資料補強未完成" in data_enrichment_common_source
            and "回報告中心確認最新版生命週期" in data_enrichment_common_source
            and "render_operator_route_button(" in data_enrichment_common_source
        ),
        "ui_data_task_followup_failure_operator_guidance_enabled": (
            "def _data_task_failure_next_step(" in data_enrichment_common_source
            and '"next_step": _data_task_failure_next_step(task_status)'
            in data_enrichment_common_source
            and '"POST " not in next_action' in data_enrichment_common_source
            and '"/tasks/" not in next_action' in data_enrichment_common_source
            and "到任務狀態面板查看診斷，確認後可重試此資料任務。"
            in data_enrichment_common_source
            and "到維護頁查看診斷並視情況重試資料任務。"
            in data_enrichment_common_source
            and "呼叫 POST /tasks/" not in data_enrichment_common_source
        ),
        "ui_operator_quota_summary_enabled": (
            "def quota_operator_summary(" in operator_status_source
            and "model_order_label" in operator_status_source
            and "limited_model_label" in operator_status_source
            and "high_quota_fallback_label" in operator_status_source
            and "def _model_order_label(" in operator_status_source
            and "def _limited_model_label(" in operator_status_source
            and "def _first_limited_quota_model(" in operator_status_source
            and (
                "quota_summary[\"caption\"]" in operator_status_source
                or "quota_summary['caption']" in operator_status_source
                or 'quota_summary["operator_caption"]' in operator_status_source
                or "quota_summary['operator_caption']" in operator_status_source
            )
        ),
        "ui_operator_quota_step_caption_enabled": (
            "operator_caption" in operator_status_source
            and "next_model_label" in operator_status_source
            and "def _next_quota_model_label(" in operator_status_source
            and "def _quota_operator_card_caption(" in operator_status_source
            and "聰明優先" in operator_status_source
            and "免費額度" in operator_status_source
            and "下一順位" in operator_status_source
            and "保底 " in operator_status_source
            and 'quota_summary["operator_caption"]' in operator_status_source
        ),
        "ui_operator_retryable_failure_primary_action_enabled": (
            "def _retryable_failure_affecting_report(" in operator_decisions_source
            and "def _task_summary_failures(" in operator_decisions_source
            and "重試影響最新版報告的任務" in operator_decisions_source
            and "priority=7" in operator_decisions_source
            and 'action_label="重試任務"' in operator_decisions_source
            and 'route_hint=f"task:{retry_task_id}"' in operator_decisions_source
        ),
        "ui_operator_stale_running_primary_action_enabled": (
            "def _first_incident_by_id(" in operator_decisions_source
            and "task_queue_stale_running" in operator_decisions_source
            and "task_queue:stale_running" in operator_decisions_source
            and "檢查卡住的背景任務" in operator_decisions_source
            and "priority=2" in operator_decisions_source
            and 'action_label=stale_running_incident.get("action_label") or "查看任務"'
            in operator_decisions_source
            and 'route_hint=stale_running_incident["route_hint"]' in operator_decisions_source
        ),
        "ui_operator_quota_missing_read_guard_enabled": (
            "def _healthy_read_reason(" in operator_decisions_source
            and "def _healthy_read_risk(" in operator_decisions_source
            and "quota_missing = not quota_payload" in operator_decisions_source
            and "模型額度狀態暫不可讀" in operator_decisions_source
            and "閱讀現有報告不消耗額度" in operator_decisions_source
            and "reason=_healthy_read_reason(quota_missing=quota_missing)"
            in operator_decisions_source
            and "risk=_healthy_read_risk(quota_missing=quota_missing)"
            in operator_decisions_source
        ),
        "ui_operator_market_freshness_primary_action_enabled": (
            "market_freshness_action_item" in operator_decisions_source
            and "market_freshness_action = market_freshness_action_item(report_payload)"
            in operator_decisions_source
            and "priority=9" in operator_decisions_source
            and 'title=f"先{action_label}"' in operator_decisions_source
            and "股價資料落後資料庫最新快取" in operator_decisions_source
            and "閱讀前未刷新股價" in operator_decisions_source
            and "data_enrichment:market_refresh" in operator_decisions_source
            and (
                operator_decisions_source.find("if quota_payload:")
                < operator_decisions_source.find(
                    "market_freshness_action = market_freshness_action_item(report_payload)"
                )
            )
        ),
        "ui_operator_secondary_action_labels_enabled": (
            '"action_label": incident.get("action_label") or "查看事件"'
            in operator_decisions_source
            and "operator_secondary_actions(" in operator_decisions_source
            and "render_operator_route_button(" in source_context.ui_sources.get(
                "analysis_workspace.py", ""
            )
            and "action.get(\"action_label\")" in source_context.ui_sources.get(
                "operator_route_controls.py", ""
            )
        ),
        "ui_operator_source_labels_enabled": (
            "def _operator_source_label(" in analysis_workspace_source
            and "source_label = _operator_source_label(source_text)"
            in analysis_workspace_source
            and '"optimization:auto_local_defaults"' in analysis_workspace_source
            and '"本機 defaults 優化缺口"' in analysis_workspace_source
            and '"optimization:company_filing_structured_api_fallback"'
            in analysis_workspace_source
            and '"公司文件結構化 API 選配"' in analysis_workspace_source
            and 'if value == "services_status":' in analysis_workspace_source
            and "優化目標缺口" in analysis_workspace_source
        ),
        "ui_operator_local_defaults_secondary_action_enabled": (
            "def _optimization_local_defaults_action(" in operator_decisions_source
            and "local_defaults_action = _optimization_local_defaults_action(service_snapshot)"
            in operator_decisions_source
            and '"驗證本機 defaults"' in operator_decisions_source
            and '"settings:maintenance:local_defaults"' in operator_decisions_source
            and '"optimization:auto_local_defaults"' in operator_decisions_source
            and '"查看本機操作"' in operator_decisions_source
        ),
        "ui_operator_free_validation_secondary_action_enabled": (
            "def _optimization_free_validation_action(" in operator_decisions_source
            and "def _optimization_actions(" in operator_decisions_source
            and "free_validation_action = _optimization_free_validation_action(service_snapshot)"
            in operator_decisions_source
            and '"驗證公司文件 API 格式"' in operator_decisions_source
            and '"settings:maintenance:structured_api"' in operator_decisions_source
            and '"optimization:company_filing_structured_api_fallback"'
            in operator_decisions_source
            and '"查看免費驗證"' in operator_decisions_source
            and "正式串 TEJ 或付費資料商前" in operator_decisions_source
        ),
        "ui_operator_service_status_unknown_guard_enabled": (
            "def service_status_unavailable(" in operator_status_source
            and "系統狀態暫不可讀" in operator_status_source
            and "無法讀取系統狀態" in operator_status_source
            and "目前無法讀取系統狀態；請到維護頁確認 API 與背景任務狀態。"
            in operator_status_source
            and "無法讀取 /services/status" not in operator_status_source
            and "目前無法讀取 /services/status" not in operator_status_source
            and "service_status_unavailable(service_snapshot)" in operator_decisions_source
            and "確認系統狀態" in operator_decisions_source
            and "這不代表背景任務已壞掉" in operator_decisions_source
            and "確認系統狀態恢復後，再送出新的長時間任務。"
            in operator_decisions_source
            and "確認 /services/status 恢復後" not in operator_decisions_source
            and 'source_ids=["services_status"]' in operator_decisions_source
        ),
        "ui_operator_task_summary_unknown_guard_enabled": (
            "def task_summary_unavailable(" in operator_status_source
            and "任務摘要暫不可讀" in operator_status_source
            and "目前無法讀取任務摘要；不代表沒有失敗任務。" in operator_status_source
            and "目前無法讀取 /tasks/summary；不代表沒有失敗任務。"
            not in operator_status_source
            and "task_summary_unavailable(task_summary)" in operator_status_source
            and '"route_hint": "settings:maintenance"' in operator_status_source
        ),
        "ui_operator_running_task_overall_message_enabled": (
            "def _latest_task_running(" in operator_status_source
            and "def _task_running(" in operator_status_source
            and "if _latest_task_running(task_summary):" in operator_status_source
            and "最新任務執行中" in operator_status_source
            and "背景任務正在處理；完成前先等待結果，不要重複送出同類任務。"
            in operator_status_source
            and (
                operator_status_source.find('if _int_value(totals.get("stale_running_count")) > 0:')
                < operator_status_source.find("if _latest_task_running(task_summary):")
            )
            and (
                operator_status_source.find("if _latest_task_running(task_summary):")
                < operator_status_source.find("if not _latest_report(reports):")
            )
        ),
        "ui_operator_running_task_primary_action_enabled": (
            "def _latest_task_running(" in operator_decisions_source
            and "def _task_row_running(" in operator_decisions_source
            and "latest_running_task = _latest_task_running(task_summary)"
            in operator_decisions_source
            and "等待最新任務完成" in operator_decisions_source
            and "尚未產生可閱讀的最新版報告" in operator_decisions_source
            and "重複送出同類任務" in operator_decisions_source
            and 'action_label="查看任務進度"' in operator_decisions_source
            and 'route_hint=f"task:{task_id}" if task_id else "settings:maintenance"'
            in operator_decisions_source
            and (
                operator_decisions_source.find(
                    "latest_running_task = _latest_task_running(task_summary)"
                )
                < operator_decisions_source.find('title="先建立最新版報告"')
            )
        ),
        "ui_operator_running_task_report_card_enabled": (
            "running_task = _latest_task(task_summary) if _latest_task_running(task_summary) else {}"
            in operator_status_source
            and "生成中" in operator_status_source
            and "最新任務執行中" in operator_status_source
            and '"查看任務" if running_task else "建立分析"' in operator_status_source
            and "def _task_route_hint(" in operator_status_source
            and "_task_route_hint(running_task)" in operator_status_source
            and (
                operator_status_source.find(
                    "running_task = _latest_task(task_summary) if _latest_task_running(task_summary) else {}"
                )
                < operator_status_source.find('"title": "最新版報告"')
            )
        ),
        "ui_operator_running_task_pending_card_enabled": (
            "def _running_task_summary(" in operator_status_source
            and "if not first_failure and _latest_task_running(task_summary):"
            in operator_status_source
            and "等待任務完成" in operator_status_source
            and "最新任務正在背景執行；完成前不需要重複送出。"
            in operator_status_source
            and '"action_label": "查看任務"' in operator_status_source
            and '"route_hint": _task_route_hint(task)' in operator_status_source
            and (
                operator_status_source.find(
                    "if not first_failure and _latest_task_running(task_summary):"
                )
                < operator_status_source.find(
                    "if first_failure and _latest_task_successful(task_summary):"
                )
            )
        ),
        "ui_operator_running_task_queue_card_enabled": (
            "queue_running = queue_state == \"ready\" and bool(running_task)"
            in operator_status_source
            and "處理中" in operator_status_source
            and "背景執行器在線，最新任務執行中" in operator_status_source
            and "請先到系統設定檢查背景任務佇列與背景執行器。"
            in operator_status_source
            and "Worker 線上" not in operator_status_source
            and "Redis/Celery worker" not in operator_status_source
            and '"查看任務" if queue_running' in operator_status_source
            and "_task_route_hint(running_task)" in operator_status_source
            and (
                operator_status_source.find(
                    "queue_running = queue_state == \"ready\" and bool(running_task)"
                )
                < operator_status_source.find('"title": "系統狀態"')
            )
        ),
        "ui_operator_historical_failure_secondary_when_latest_task_healthy_enabled": (
            "def _latest_task_successful(" in operator_decisions_source
            and "def _task_row_successful(" in operator_decisions_source
            and "def _critical_incident_should_block(" in operator_decisions_source
            and "def _is_task_failure_incident(" in operator_decisions_source
            and "critical_incident and _critical_incident_should_block("
            in operator_decisions_source
            and "not _latest_task_successful(task_summary)" in operator_decisions_source
            and 'dedupe_key.startswith("failure:")' in operator_decisions_source
            and 'incident_id.startswith("failure_")' in operator_decisions_source
            and "successful" in operator_decisions_source
            and "celery_status" in operator_decisions_source
        ),
        "ui_operator_overall_historical_failure_ready_when_latest_task_healthy_enabled": (
            "def operator_status_overall(" in operator_status_source
            and "def _latest_task_successful(" in operator_status_source
            and "def _task_successful(" in operator_status_source
            and "if _latest_task_successful(task_summary):" in operator_status_source
            and '"state": "ready"' in operator_status_source
            and "歷史失敗仍可追蹤" in operator_status_source
            and "celery_status" in operator_status_source
        ),
        "ui_operator_missing_report_prioritized_before_historical_failure_enabled": (
            "尚無最新版報告" in operator_status_source
            and "系統可執行，請先建立分析報告。" in operator_status_source
            and (
                operator_status_source.find("if not _latest_report(reports):")
                < operator_status_source.find("failure_count = len(_recent_failures(task_summary))")
            )
            and (
                operator_status_source.find("if not _latest_report(reports):") > -1
            )
            and (
                operator_status_source.find("failure_count = len(_recent_failures(task_summary))")
                > -1
            )
        ),
        "ui_operator_latest_failure_overall_message_enabled": (
            "def _latest_task_failed(" in operator_status_source
            and "if _latest_task_failed(task_summary):" in operator_status_source
            and "最新任務需要確認" in operator_status_source
            and "最新任務失敗或取消；請先查看任務診斷後再重試或重新送出。"
            in operator_status_source
            and "歷史失敗" in operator_status_source
            and (
                operator_status_source.find("if _latest_task_failed(task_summary):")
                < operator_status_source.find("if _latest_task_successful(task_summary):")
            )
        ),
        "ui_operator_card_historical_failure_trackable_when_latest_task_healthy_enabled": (
            "def _first_failure_summary(" in operator_status_source
            and "def _historical_failure_summary(" in operator_status_source
            and "first_failure and _latest_task_successful(task_summary)"
            in operator_status_source
            and "歷史失敗可追蹤" in operator_status_source
            and "最新任務已成功；舊失敗保留於維護頁，不影響閱讀最新版報告。"
            in operator_status_source
            and "補強或重跑任務曾被輸入驗證擋下；修正後可重試。"
            in operator_status_source
            and "payload 驗證" not in operator_status_source
            and '"action_label": "查看紀錄"' in operator_status_source
            and 'route_hint": f"task:{task_id}"' in operator_status_source
        ),
    }
