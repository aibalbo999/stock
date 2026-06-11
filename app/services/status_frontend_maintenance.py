from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_maintenance_ui_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    system_settings_source = ui_sources["system_settings.py"]
    operator_routes_source = ui_sources["operator_routes.py"]
    system_settings_maintenance_source = ui_sources["system_settings_maintenance.py"]
    maintenance_panels_source = ui_sources["maintenance_panels.py"]
    maintenance_deployment_panel_source = ui_sources["maintenance_deployment_panel.py"]
    maintenance_deployment_presenter_source = ui_sources["maintenance_deployment_presenter.py"]
    maintenance_ai_panels_source = ui_sources["maintenance_ai_panels.py"]
    maintenance_task_panels_source = ui_sources["maintenance_task_panels.py"]
    maintenance_cleanup_panel_source = ui_sources["maintenance_cleanup_panel.py"]
    llm_quota_panel_source = ui_sources["llm_quota_panel.py"]
    style_source = (
        source_context.style_path.read_text(encoding="utf-8")
        if source_context.style_path.exists()
        else ""
    )
    return {
        "frontend_maintenance_ui_status_extracted": True,
        "frontend_maintenance_ui_status_path": "app/services/status_frontend_maintenance.py",
        "ui_settings_ai_quota_route_focus_enabled": (
            "def maintenance_focus_from_pending_section(" in system_settings_source
            and '"pending_maintenance_focus"' in system_settings_source
            and "maintenance_focus_from_pending_section(pending_section)"
            in system_settings_source
            and "def _consume_pending_maintenance_focus(" in system_settings_maintenance_source
            and 'st.session_state.pop("pending_maintenance_focus"' in system_settings_maintenance_source
            and 'if maintenance_focus == "ai_quota":' in system_settings_maintenance_source
            and "render_ai_quota_panel(llm_quota, service_snapshot)"
            in system_settings_maintenance_source
            and 'if maintenance_focus != "ai_quota":' in system_settings_maintenance_source
        ),
        "ui_settings_task_route_focus_enabled": (
            '"maintenance_inspect_task_id": task_id' in operator_routes_source
            and '"pending_maintenance_focus": "task_observability"' in operator_routes_source
            and 'if maintenance_focus == "task_observability":'
            in system_settings_maintenance_source
            and 'if maintenance_focus != "task_observability":'
            in system_settings_maintenance_source
            and 'focus in {"ai_quota", "task_observability", "external_deployment"}'
            in system_settings_maintenance_source
            and system_settings_maintenance_source.count(
                "render_background_task_observability_panel("
            )
            >= 2
        ),
        "ui_settings_local_defaults_route_focus_enabled": (
            '"settings:maintenance:local_defaults"' in operator_routes_source
            and '"pending_settings_section": "maintenance_local_defaults"'
            in operator_routes_source
            and '"maintenance_local_defaults"' in system_settings_source
            and 'return "external_deployment"' in system_settings_source
            and 'if maintenance_focus == "external_deployment":'
            in system_settings_maintenance_source
            and "external_deployment_rendered = True" in system_settings_maintenance_source
            and "if not external_deployment_rendered:" in system_settings_maintenance_source
            and 'focus in {"ai_quota", "task_observability", "external_deployment"}'
            in system_settings_maintenance_source
            and system_settings_maintenance_source.count("render_external_deployment_panel(")
            >= 2
        ),
        "ui_settings_structured_api_route_focus_enabled": (
            '"settings:maintenance:structured_api"' in operator_routes_source
            and '"pending_settings_section": "maintenance_structured_api"'
            in operator_routes_source
            and '"maintenance_structured_api"' in system_settings_source
            and 'return "external_deployment"' in system_settings_source
            and 'if maintenance_focus == "external_deployment":'
            in system_settings_maintenance_source
            and "external_deployment_rendered = True" in system_settings_maintenance_source
            and "if not external_deployment_rendered:" in system_settings_maintenance_source
            and 'focus in {"ai_quota", "task_observability", "external_deployment"}'
            in system_settings_maintenance_source
            and "structured_filing_api_operation_rows(upgrade_audit)"
            in maintenance_deployment_panel_source
            and system_settings_maintenance_source.count("render_external_deployment_panel(")
            >= 2
        ),
        "ui_settings_structured_api_focus_context_enabled": (
            "def external_deployment_focus_from_pending_section(" in system_settings_source
            and '"maintenance_structured_api"' in system_settings_source
            and 'return "structured_api"' in system_settings_source
            and '"pending_external_deployment_focus"' in system_settings_source
            and "def _consume_pending_external_deployment_focus("
            in system_settings_maintenance_source
            and '"structured_api"' in system_settings_maintenance_source
            and "focus_context=external_deployment_focus" in system_settings_maintenance_source
            and "def external_deployment_focus_banner("
            in maintenance_deployment_presenter_source
            and '"公司文件結構化 API 免費驗證"'
            in maintenance_deployment_presenter_source
            and "正式串 TEJ 或付費資料商前" in maintenance_deployment_presenter_source
            and "external_deployment_focus_banner(focus_context)"
            in maintenance_deployment_panel_source
            and "maintenance-focus-banner" in maintenance_deployment_panel_source
            and "expanded=bool(external_warning_rows) or bool(focus_banner)"
            in maintenance_deployment_panel_source
        ),
        "ui_incident_action_labels_enabled": (
            '"action_label": incident_action_label(incident, index)'
            in system_settings_maintenance_source
            and "def incident_action_label(" in system_settings_maintenance_source
            and '"action_label": _failure_action_label(category, retryable)' in ui_source
            and "def _failure_action_label(" in ui_source
            and 'return "重試任務"' in ui_source
            and 'return "檢查任務"' in ui_source
        ),
        "ui_incident_report_lifecycle_enabled": (
            "from app.ui.report_lifecycle import latest_report_lifecycle"
            in system_settings_maintenance_source
            and "def _latest_report_lifecycle_for_maintenance("
            in system_settings_maintenance_source
            and '"/reports?limit=1"' in system_settings_maintenance_source
            and 'f"/reports/{normalized_report_id}"' in system_settings_maintenance_source
            and 'f"/reports/{normalized_report_id}/follow-up/plan"'
            in system_settings_maintenance_source
            and "latest_report_lifecycle(report_context, follow_up_plan)"
            in system_settings_maintenance_source
            and "latest_report_lifecycle_snapshot = _latest_report_lifecycle_for_maintenance()"
            in system_settings_maintenance_source
            and "latest_report_lifecycle_snapshot,\n        )"
            in system_settings_maintenance_source
        ),
        "ui_incident_priority_summary_enabled": (
            "_render_incident_priority_summary(incidents)" in system_settings_maintenance_source
            and "def _render_incident_priority_summary(" in system_settings_maintenance_source
            and "def incident_action_priority_summary(" in system_settings_maintenance_source
            and "Critical {critical} / Warning {warning} / Info {info}"
            in system_settings_maintenance_source
            and "retryable_count" in system_settings_maintenance_source
            and "task_linked_count" in system_settings_maintenance_source
            and "passive_count" in system_settings_maintenance_source
            and "歷史趨勢/觀測" in system_settings_maintenance_source
            and ".incident-priority-summary" in style_source
        ),
        "ui_incident_historical_context_enabled": (
            "def _latest_success_timestamp(" in ui_source
            and "historical_after_latest_success" in ui_source
            and "trend_only" in ui_source
            and "def _historical_incident(" in system_settings_maintenance_source
            and "historical_count" in system_settings_maintenance_source
            and "目前任務健康，追蹤" in system_settings_maintenance_source
            and "當前 Critical 事件" in system_settings_maintenance_source
            and "最新任務已成功；先確認是否影響最新版報告"
            in system_settings_maintenance_source
        ),
        "ui_incident_header_current_context_enabled": (
            "def incident_inbox_header_badges(" in system_settings_maintenance_source
            and "incident_inbox_header_badges(incidents)" in system_settings_maintenance_source
            and "當前 Critical" in system_settings_maintenance_source
            and "當前 Warning" in system_settings_maintenance_source
            and "歷史/趨勢" in system_settings_maintenance_source
            and "historical_count" in system_settings_maintenance_source
        ),
        "ui_incident_grouped_summary_enabled": (
            "def incident_summary_cards(" in system_settings_maintenance_source
            and "incident_summary_cards(incidents)" in system_settings_maintenance_source
            and "top_incidents(summaries, limit=limit)" in system_settings_maintenance_source
            and "repeat_count" in system_settings_maintenance_source
            and "hidden_count" in system_settings_maintenance_source
            and "route_hints" in system_settings_maintenance_source
            and "source_ids" in system_settings_maintenance_source
            and "同類事件" in system_settings_maintenance_source
            and "另有 {hidden_count} 筆同類事件" in system_settings_maintenance_source
            and "_render_incident_action_controls(incidents)" in system_settings_maintenance_source
            and "def _incident_summary_key(" in system_settings_maintenance_source
            and ".incident-card-head" in style_source
            and ".incident-card .incident-repeat-badge" in style_source
        ),
        "ui_incident_grouped_action_controls_enabled": (
            "def incident_action_summaries(" in system_settings_maintenance_source
            and "incident_action_summaries(incidents)" in system_settings_maintenance_source
            and "for incident in incident_summary_cards(incidents, limit=limit)"
            in system_settings_maintenance_source
            and "def incident_action_caption(" in system_settings_maintenance_source
            and "同類事件 {repeat_count} 筆" in system_settings_maintenance_source
            and "st.caption(incident_action_caption(incident))"
            in system_settings_maintenance_source
            and "actionable = incident_action_summaries(incidents)"
            in system_settings_maintenance_source
        ),
        "ui_maintenance_panels_extracted": (ui_dir / "maintenance_panels.py").exists()
        and (ui_dir / "maintenance_deployment_panel.py").exists()
        and (ui_dir / "maintenance_ai_panels.py").exists()
        and (ui_dir / "maintenance_task_panels.py").exists()
        and (ui_dir / "maintenance_cleanup_panel.py").exists()
        and "from app.ui.maintenance_deployment_panel import render_external_deployment_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_ai_panels import (" in maintenance_panels_source
        and "from app.ui.maintenance_task_panels import render_background_task_observability_panel"
        in maintenance_panels_source
        and "from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel"
        in maintenance_panels_source
        and "def render_external_deployment_panel(" in maintenance_deployment_panel_source
        and "service_snapshot: dict | None = None" in maintenance_deployment_panel_source
        and "local_dependency_status_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "local_dependency_last_start_rows(service_snapshot)"
        in maintenance_deployment_panel_source
        and "local_dependency_repair_rows(service_snapshot)" in maintenance_deployment_panel_source
        and "def render_ai_usage_panel(" in maintenance_ai_panels_source
        and "def render_background_task_observability_panel(" in maintenance_task_panels_source
        and "def render_report_quality_panel(" in maintenance_panels_source
        and "def render_maintenance_cleanup_panel(" in maintenance_cleanup_panel_source
        and "from app.ui.maintenance_panels import (" in system_settings_maintenance_source
        and system_settings_maintenance_source.count("render_external_deployment_panel(") >= 2
        and "upgrade_audit,\n            service_snapshot,\n            maintenance_operations,\n            external_env_check,"
        in system_settings_maintenance_source
        and 'maintenance_operations = load_api_json_or_default(\n        "/maintenance/operations"'
        in system_settings_maintenance_source
        and 'external_env_check = load_api_json_or_default(\n        "/services/external-deployment/env-check"'
        in system_settings_maintenance_source
        and "maintenance_operations,\n            external_env_check,\n        )"
        in system_settings_maintenance_source
        and "render_background_task_observability_panel(" in system_settings_maintenance_source
        and "maintenance_diagnostics," in system_settings_maintenance_source
        and 'maintenance_diagnostics = load_api_json_or_default(\n        "/maintenance/diagnostics"'
        in system_settings_maintenance_source
        and "external_deployment_warning_rows(upgrade_audit)"
        not in system_settings_maintenance_source
        and 'st.expander("背景任務觀測"' not in system_settings_maintenance_source,
        "ui_maintenance_panels_path": "app/ui/maintenance_panels.py",
        "ui_maintenance_panel_module_paths": [
            "app/ui/maintenance_deployment_panel.py",
            "app/ui/maintenance_ai_panels.py",
            "app/ui/maintenance_task_panels.py",
            "app/ui/maintenance_cleanup_panel.py",
        ],
        "ui_submission_guard_panel_enabled": (
            "def render_submission_guard_panel(service_snapshot: dict) -> None:"
            in maintenance_panels_source
            and "def submission_guard_metric_values(" in maintenance_panels_source
            and "def submission_guard_rows(" in maintenance_panels_source
            and "高風險操作保護" in maintenance_panels_source
            and "ui_risky_submission_guard_rows" in maintenance_panels_source
            and "確認所有會寫入、刪除、消耗額度或重試任務的入口都有確認閘門"
            in maintenance_panels_source
            and all(
                label in maintenance_panels_source
                for label in ("完整", "需處理", "已保護", "缺保護", "未知")
            )
            and "render_submission_guard_panel(service_snapshot)"
            in system_settings_maintenance_source
        ),
        "ui_maintenance_cleanup_confirmation_gate_enabled": (
            "cleanup_confirmed = st.checkbox(" in maintenance_cleanup_panel_source
            and 'key="confirm_maintenance_cleanup"' in maintenance_cleanup_panel_source
            and "我了解這裡會改動或刪除歷史資料" in maintenance_cleanup_panel_source
            and "清理操作會刪除歷史紀錄" in maintenance_cleanup_panel_source
            and "disabled=not cleanup_confirmed" in maintenance_cleanup_panel_source
            and 'api_post("/maintenance/cleanup"' in maintenance_cleanup_panel_source
        ),
        "ui_llm_quota_panel_extracted": (ui_dir / "llm_quota_panel.py").exists()
        and "def llm_quota_metric_values(" in llm_quota_panel_source
        and "def llm_quota_model_rows(" in llm_quota_panel_source
        and "def llm_quota_captions(" in llm_quota_panel_source
        and "額度重置" in llm_quota_panel_source
        and "quota_hit_count" in llm_quota_panel_source
        and "quota_skip_count" in llm_quota_panel_source
        and "active_cooldown" in llm_quota_panel_source
        and "from app.ui.llm_quota_panel import (" in ui_source
        and "llm_quota_metric_values(llm_quota)" in ui_source
        and "llm_quota_model_rows(llm_quota)" in ui_source,
        "ui_llm_quota_panel_path": "app/ui/llm_quota_panel.py",
    }
