from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_report_workflow_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    report_state_source = ui_sources["report_state.py"]
    report_panels_source = ui_sources["report_panels.py"]
    report_follow_up_controls_source = ui_sources["report_follow_up_controls.py"]
    report_observability_panel_source = ui_sources["report_observability_panel.py"]
    report_center_source = ui_sources["report_center.py"]
    report_health_source = ui_sources["report_health.py"]
    report_lifecycle_source = ui_sources["report_lifecycle.py"]
    operator_decisions_source = ui_sources["operator_decisions.py"]
    style_source = (
        source_context.style_path.read_text(encoding="utf-8")
        if source_context.style_path.exists()
        else ""
    )
    report_debug_expander_index = report_center_source.find(
        'with st.expander("疑難排解：執行紀錄")'
    )
    report_delete_button_index = report_center_source.find('"刪除此報告",')
    return {
        "frontend_report_workflow_status_extracted": True,
        "frontend_report_workflow_status_path": (
            "app/services/status_frontend_report_workflow.py"
        ),
        "ui_report_observability_summary_enabled": "/reports/observability/summary?limit=20"
        in ui_source
        and "報告生成觀測" in ui_source
        and "trace_captured_count" in ui_source
        and "keyword_fallback_count" in ui_source,
        "ui_report_observability_bottlenecks_enabled": (
            "def report_observability_bottleneck_rows("
        )
        in report_observability_panel_source
        and 'summary.get("bottlenecks")' in report_observability_panel_source
        and "優先優化清單" in report_observability_panel_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source,
        "ui_report_observability_recommendations_enabled": (
            "def report_observability_recommendation_rows("
        )
        in report_observability_panel_source
        and 'summary.get("recommendations")' in report_observability_panel_source
        and "建議處理順序" in report_observability_panel_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source,
        "ui_report_observability_alert_operator_messages_enabled": (
            "def _observability_alert_message(" in report_observability_panel_source
            and "def _observability_alert_next_step(" in report_observability_panel_source
            and '"提醒"' in report_observability_panel_source
            and '"下一步"' in report_observability_panel_source
            and "部分最新版報告使用模型降級路由" in report_observability_panel_source
            and "確認聰明模型額度用完後才降級" in report_observability_panel_source
            and "Some latest reports used LLM fallback routing."
            not in report_observability_panel_source
            and 'alert.get("message") or alert.get("code")' not in report_observability_panel_source
        ),
        "ui_report_observability_recommendation_operator_text_enabled": (
            "def _observability_evidence_text(" in report_observability_panel_source
            and "def _observability_evidence_label(" in report_observability_panel_source
            and "def _operator_action_text(" in report_observability_panel_source
            and '"證據": _observability_evidence_text(row.get("evidence"))'
            in report_observability_panel_source
            and '"下一步": _operator_action_text(row.get("next_action"))'
            in report_observability_panel_source
            and "return _operator_action_text(ALERT_NEXT_STEPS[code])"
            in report_observability_panel_source
            and '"fallback": "後援"' in report_observability_panel_source
            and '"quota_skips": "額度略過"' in report_observability_panel_source
            and '"degraded": "模型降級"' in report_observability_panel_source
            and '"keyword_fallback": "關鍵字後援"' in report_observability_panel_source
            and '"cooldown": "冷卻"' in report_observability_panel_source
            and '"證據": row.get("evidence") or "-"' not in report_observability_panel_source
        ),
        "ui_report_observability_row_operator_labels_enabled": (
            "def _observability_bottleneck_label(" in report_observability_panel_source
            and "def _observability_recommendation_label(" in report_observability_panel_source
            and '"主要瓶頸"' in report_observability_panel_source
            and '"關聯報告"' in report_observability_panel_source
            and '"Token 估算"' in report_observability_panel_source
            and '"LLM 延遲 ms"' in report_observability_panel_source
            and '"檢索延遲 ms"' in report_observability_panel_source
            and "dominant_factor" in report_observability_panel_source
            and "top_report_id" in report_observability_panel_source
            and "llm_latency_ms" in report_observability_panel_source
            and 'st.dataframe(recommendation_rows' in report_observability_panel_source
            and 'st.dataframe(bottleneck_rows' in report_observability_panel_source
            and 'st.dataframe(report_rows' in report_observability_panel_source
        ),
        "ui_report_observability_graphrag_metrics_enabled": (
            "graph_reasoning_path_count" in report_observability_panel_source
            and "graph_reasoning_coverage_ratio" in report_observability_panel_source
            and "圖譜推理路徑" in report_observability_panel_source
            and "圖譜推理覆蓋率" in report_observability_panel_source
        ),
        "ui_report_observability_metric_operator_labels_enabled": (
            "追蹤覆蓋" in report_observability_panel_source
            and "圖譜推理路徑" in report_observability_panel_source
            and "圖譜推理覆蓋率" in report_observability_panel_source
            and "平均 LLM 延遲 ms" in report_observability_panel_source
            and "P95 LLM 延遲 ms" in report_observability_panel_source
            and "P95 檢索延遲 ms" in report_observability_panel_source
            and "關鍵字後援" in report_observability_panel_source
            and "額度略過" in report_observability_panel_source
            and "GraphRAG paths" not in report_observability_panel_source
            and "Graph 覆蓋率" not in report_observability_panel_source
            and "P95 Retrieval ms" not in report_observability_panel_source
            and "Keyword fallback" not in report_observability_panel_source
            and "Quota skip" not in report_observability_panel_source
        ),
        "ui_report_lifecycle_data_gap_prefill_enabled": (
            "from app.ui.data_gap_actions import data_gap_action_items"
            in report_lifecycle_source
            and "def _primary_data_gap_action(" in report_lifecycle_source
            and 'gap_action.get("route_hint")' in report_lifecycle_source
            and "primary_action_detail" in report_lifecycle_source
            and 'lifecycle.get("primary_action_detail"' in ui_source
            and 'key="report_lifecycle_primary_action"' in ui_source
        ),
        "ui_report_health_identity_enabled": (
            "def latest_report_health_summary(" in report_health_source
            and '"report_meta_label": _report_meta_label(' in report_health_source
            and "def _format_generated_at(" in report_health_source
            and '"title": report_payload.get("title")' in ui_source
            and '"generated_at": report_payload.get("generated_at")' in ui_source
            and 'summary.get("report_meta_label"' in ui_source
            and ".report-health-card em" in style_source
        ),
        "ui_report_health_action_enabled": (
            "def _follow_up_health_state(" in report_health_source
            and '"follow_up_state": follow_up_state' in report_health_source
            and '"rerun_running"' in report_health_source
            and '"blocked"' in report_health_source
            and "data_gap_action_items(" in report_health_source
            and 'summary.get("action_label"' in ui_source
            and 'summary.get("follow_up_state"' in ui_source
            and "report-health-action" in ui_source
            and ".report-health-action" in style_source
        ),
        "ui_report_reader_decision_summary_enabled": (
            "def report_reader_decision_summary(" in report_center_source
            and "def _render_report_reader_decision_summary(" in report_center_source
            and "health_summary = latest_report_health_summary(" in report_center_source
            and "report_reader_decision_summary(lifecycle, health_summary)"
            in report_center_source
            and 'class="report-reader-decision' in report_center_source
            and "閱讀決策" in report_center_source
            and "可先閱讀，但投資判斷需標示限制" in report_center_source
            and "暫停採信，先處理阻塞" in report_center_source
            and ".report-reader-decision" in style_source
            and ".report-reader-decision-grid" in style_source
        ),
        "ui_report_quality_unknown_guard_enabled": (
            "def _quality_gate_known(" in report_lifecycle_source
            and 'quality_state = "unknown"' in report_lifecycle_source
            and "尚無法判斷品質門檻" in report_lifecycle_source
            and "確認品質門檻" in report_lifecycle_source
            and "def _quality_gate_known(" in report_health_source
            and '"quality_unknown"' in report_health_source
            and "尚無法判斷" in report_health_source
            and 'quality_stage.get("state") == "unknown"' in operator_decisions_source
            and "先確認報告品質狀態" in operator_decisions_source
        ),
        "ui_report_market_freshness_action_enabled": (
            "market_freshness_action_item" in report_lifecycle_source
            and "market_freshness_action = market_freshness_action_item(report)"
            in report_lifecycle_source
            and 'market_freshness_action.get("summary_label")' in report_lifecycle_source
            and 'market_freshness_action.get("impact")' in report_lifecycle_source
            and "market_freshness_action_item" in report_health_source
            and '"market_freshness"' in report_health_source
            and "股價需刷新" in report_health_source
            and "market_freshness_action_item" in operator_decisions_source
            and "priority=9" in operator_decisions_source
        ),
        "ui_report_latest_only_picker_enabled": (
            'load_api_json_or_default(\n        "/reports?limit=5"' in report_center_source
            and "def latest_report_picker_state(" in report_center_source
            and '"single_latest"' in report_center_source
            and '"multi_topic_latest"' in report_center_source
            and "目前最新版報告" in report_center_source
            and "選擇主題最新版報告" in report_center_source
            and "建立分析後，這裡會顯示目前保留的最新版報告。" in report_center_source
            and ".latest-report-picker" in style_source
        ),
        "ui_report_latest_only_scope_note_enabled": (
            '"scope_note": "這不是歷史版本清單；每個主題只顯示最新一份可讀報告。"'
            in report_center_source
            and "此頁只顯示目前保留的最新版" in report_center_source
            and "報告中心不需要手動整理歷史版本" in report_center_source
            and "latest-report-picker-note" in report_center_source
            and ".latest-report-picker-note" in style_source
        ),
        "ui_report_empty_create_analysis_action_enabled": (
            "def empty_report_action_summary(" in report_center_source
            and '"mode": "empty"' in report_center_source
            and '"action_label": "建立分析"' in report_center_source
            and '"route_hint": "analysis"' in report_center_source
            and "建立第一份最新版報告" in report_center_source
            and "前往分析工作區建立報告；完成後回到這裡閱讀最新版。"
            in report_center_source
            and 'key="report_empty_state_primary_action"' in report_center_source
            and ".report-lifecycle-action em" in style_source
        ),
        "ui_report_empty_running_task_state_enabled": (
            '"/tasks/summary?days=7&limit=10"' in report_center_source
            and "task_summary=task_summary" in report_center_source
            and "def _latest_task_running(" in report_center_source
            and "def _task_running(" in report_center_source
            and "最新版報告生成中" in report_center_source
            and "最新任務正在背景執行；完成前不需要重複建立分析。"
            in report_center_source
            and '"action_label": "查看任務"' in report_center_source
            and '"route_hint": _task_route_hint(latest_running_task)' in report_center_source
            and 'key="report_empty_state_primary_action"' in report_center_source
            and (
                report_center_source.find('"/tasks/summary?days=7&limit=10"')
                < report_center_source.find("latest_report_picker_state(")
            )
        ),
        "ui_report_advanced_controls_progressive_disclosure_enabled": (
            'with st.expander("疑難排解：執行紀錄")' in report_center_source
            and 'with st.expander("報告管理")' not in report_center_source
            and "進階操作，只在需要移除最新版報告時使用。" in report_center_source
            and '"刪除此報告",' in report_center_source
            and report_debug_expander_index >= 0
            and report_delete_button_index >= 0
            and report_debug_expander_index < report_delete_button_index
            and 'with st.expander("原始紀錄內容"):' in report_center_source
            and 'with st.expander("背景任務狀態", expanded=False):' in report_center_source
        ),
        "ui_report_run_history_operator_labels_enabled": (
            "def report_run_history_rows(" in report_center_source
            and "def report_run_history_ids(" in report_center_source
            and "RUN_SOURCE_LABELS = {" in report_center_source
            and "RUN_STATUS_LABELS = {" in report_center_source
            and "RUN_ERROR_LABELS = {" in report_center_source
            and '"來源": _run_source_label(run.get("source"))' in report_center_source
            and '"狀態": _run_status_label(run.get("status"))' in report_center_source
            and '"錯誤": _run_error_label(run.get("error"))' in report_center_source
            and "run_rows = report_run_history_rows(runs)" in report_center_source
            and "run_ids = report_run_history_ids(runs)" in report_center_source
            and "options=run_ids" in report_center_source
            and '"source": run.get("source")' not in report_center_source
            and '"status": run.get("status")' not in report_center_source
            and '"error": run.get("error")' not in report_center_source
        ),
        "ui_report_run_detail_error_operator_label_enabled": (
            "def report_run_detail_error_message(" in report_center_source
            and "執行紀錄錯誤：" in report_center_source
            and "st.error(report_run_detail_error_message(selected_run_error))"
            in report_center_source
            and '"查看執行紀錄"' in report_center_source
            and '"查看 run"' not in report_center_source
            and "st.error(selected_run_error)" not in report_center_source
        ),
        "ui_report_delete_confirmation_gate_enabled": (
            "report_delete_confirmed = st.checkbox(" in report_center_source
            and 'key=f"confirm_delete_report_{selected_id}"' in report_center_source
            and "disabled=not report_delete_confirmed" in report_center_source
            and "刪除報告會移除目前最新版報告與安全範圍內的報告檔"
            in report_center_source
            and "避免誤觸" in report_center_source
        ),
        "ui_run_delete_confirmation_gate_enabled": (
            "run_delete_confirmed = st.checkbox(" in report_center_source
            and 'key=f"confirm_delete_run_{selected_run_id}"' in report_center_source
            and 'key=f"delete_run_{selected_run_id}"' in report_center_source
            and "disabled=not run_delete_confirmed" in report_center_source
            and "避免誤觸" in report_center_source
        ),
        "ui_report_delete_scope_caption_enabled": (
            "刪除報告會移除目前最新版報告與安全範圍內的報告檔"
            in report_center_source
            and "分析紀錄會保留" in report_center_source
            and "刪除分析紀錄只會移除此筆執行歷史，不會刪除目前最新版報告"
            in report_center_source
        ),
        "ui_report_follow_up_submission_confirmation_enabled": (
            "followup_run_confirmed = st.checkbox(" in report_follow_up_controls_source
            and 'key=f"followup_run_confirm_{key_suffix}"'
            in report_follow_up_controls_source
            and "我了解這會送出自動補強背景任務" in report_follow_up_controls_source
            and "避免誤觸補強" in report_follow_up_controls_source
            and "disabled=not has_executable_actions or not followup_run_confirmed"
            in report_follow_up_controls_source
            and 'submit_api_task(\n            f"/reports/{report_id}/follow-up/run_async"'
            in report_follow_up_controls_source
        ),
        "ui_report_follow_up_submission_preflight_summary_enabled": (
            "def follow_up_submission_preflight_summary("
            in report_follow_up_controls_source
            and "def render_follow_up_submission_summary("
            in report_follow_up_controls_source
            and "render_follow_up_submission_summary(" in report_follow_up_controls_source
            and "follow_up_submission_preflight_summary(" in report_follow_up_controls_source
            and 'class="follow-up-submission-summary' in report_follow_up_controls_source
            and "會使用背景任務、外部資料來源與可能的 AI 額度"
            in report_follow_up_controls_source
            and "完成後套用補強結果並查看最新版生命週期"
            in report_follow_up_controls_source
            and "尚未送出背景任務；先確認範圍可避免空任務與額度浪費"
            in report_follow_up_controls_source
        ),
        "ui_report_follow_up_action_operator_labels_enabled": (
            "from app.services.followup_models import FOLLOW_UP_ACTION_LABELS"
            in report_follow_up_controls_source
            and "def _follow_up_task_label(" in report_follow_up_controls_source
            and "def _labeled_value(" in report_follow_up_controls_source
            and "FOLLOW_UP_ACTION_LABELS.get(action_type" in report_follow_up_controls_source
            and '"任務": _follow_up_task_label(action)' in report_follow_up_controls_source
            and '"正式文件"' in report_follow_up_controls_source
            and '"候選證據缺口"' in report_follow_up_controls_source
            and '"高"' in report_follow_up_controls_source
            and '"一次"' in report_follow_up_controls_source
            and 'action.get("action_type", "-")' not in report_follow_up_controls_source
            and 'action.get("target") or "-"' not in report_follow_up_controls_source
            and 'action.get("reason", "-")' not in report_follow_up_controls_source
        ),
        "ui_report_observability_panel_extracted": (
            ui_dir / "report_observability_panel.py"
        ).exists()
        and "def report_observability_metric_values(" in report_observability_panel_source
        and "def report_observability_bottleneck_rows(" in report_observability_panel_source
        and "def report_observability_recommendation_rows("
        in report_observability_panel_source
        and "graph_reasoning_path_count" in report_observability_panel_source
        and "def render_report_observability_panel(" in report_observability_panel_source
        and "from app.ui.report_observability_panel import render_report_observability_panel"
        in ui_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source
        and "report_obs_cols" not in ui_source,
        "ui_report_observability_panel_path": "app/ui/report_observability_panel.py",
        "ui_report_state_extracted": (ui_dir / "report_state.py").exists()
        and "def hydrate_active_report_result(" in report_state_source
        and "def parse_json_object(" in report_state_source
        and "def hydrate_active_report_result(" not in dashboard_core_source
        and "def parse_json_object(" not in dashboard_core_source
        and "from app.ui.report_state import " in ui_source,
        "ui_report_state_path": "app/ui/report_state.py",
        "ui_report_panels_extracted": (ui_dir / "report_panels.py").exists()
        and "def render_quality_gate(" in report_panels_source
        and "def render_source_audit(" in report_panels_source
        and "def render_company_data_audit(" in report_panels_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_quality_gate(" not in dashboard_core_source
        and "from app.ui.report_panels import (" in ui_source,
        "ui_report_panels_path": "app/ui/report_panels.py",
        "ui_report_preview_iframe_renderer_enabled": (
            "def render_report_document(" in report_panels_source
            and "def load_legacy_streamlit_components(" in report_panels_source
            and "render_report_document(report_html(markdown, result), height=820)"
            in report_panels_source
            and 'getattr(streamlit_module, "iframe", None)' in report_panels_source
            and 'iframe(document_html, width="stretch", height=height)'
            in report_panels_source
            and "components_importer().html(document_html, height=height, scrolling=True)"
            in report_panels_source
            and "import streamlit.components.v1" not in report_panels_source
            and "components.html(report_html(" not in report_panels_source
        ),
        "ui_report_follow_up_controls_extracted": (
            ui_dir / "report_follow_up_controls.py"
        ).exists()
        and "def render_follow_up_controls(" in report_follow_up_controls_source
        and "def render_follow_up_flash(" in report_follow_up_controls_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_follow_up_flash(" not in report_panels_source
        and "def render_follow_up_controls(" not in dashboard_core_source
        and "from app.ui.report_follow_up_controls import" in ui_source,
        "ui_report_follow_up_controls_path": "app/ui/report_follow_up_controls.py",
    }
