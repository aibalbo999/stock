from __future__ import annotations

from pathlib import Path

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_external_deployment_domain_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    external_deployment_source = ui_sources["external_deployment_diagnostics.py"]
    external_deployment_common_source = ui_sources["external_deployment_common.py"]
    external_deployment_env_keys_source = ui_sources["external_deployment_env_keys.py"]
    external_deployment_unlocker_source = ui_sources["external_deployment_unlocker.py"]
    external_deployment_neo4j_source = ui_sources["external_deployment_neo4j.py"]
    external_deployment_structured_api_source = ui_sources[
        "external_deployment_structured_api.py"
    ]
    maintenance_status_source = ui_sources["maintenance_status.py"]
    env_gap_service_path = root / "app" / "services" / "external_deployment_env_gaps.py"
    env_gap_service_source = _read_text(env_gap_service_path)
    readiness_service_path = root / "app" / "services" / "external_deployment_readiness.py"
    readiness_service_source = _read_text(readiness_service_path)
    profile_catalog_path = root / "app" / "services" / "external_deployment_profiles.py"
    profile_catalog_source = _read_text(profile_catalog_path)
    return {
        "frontend_external_deployment_domain_status_extracted": True,
        "frontend_external_deployment_domain_status_path": (
            "app/services/status_frontend_external_deployment_domains.py"
        ),
        "ui_external_deployment_diagnostics_enabled": "def external_deployment_warning_rows("
        in external_deployment_source
        and "def external_deployment_readiness_rows(" in external_deployment_source
        and "external_deployment_readiness_rows(\n        upgrade_audit," in ui_source
        and "外部部署 readiness checklist" in ui_source
        and "最近本機依賴啟動" in ui_source
        and "本機依賴修復指引" in ui_source
        and "本機依賴狀態" in ui_source
        and "def external_deployment_smoke_commands(" in external_deployment_source
        and "def external_deployment_env_key_rows(" in external_deployment_source
        and "def external_deployment_env_resolution_rows(" in external_deployment_source
        and "external_deployment_env_key_rows(upgrade_audit, service_snapshot)"
        in ui_source
        and "external_deployment_env_resolution_rows(" in ui_source
        and "外部設定處理計畫" in ui_source
        and "recommended_maintenance_operation_id(" in ui_source
        and "index=recommended_operation_index" in ui_source
        and "外部設定缺口" in ui_source
        and "optional_warnings" in maintenance_status_source
        and "external_deployment_warning_rows(upgrade_audit)" in ui_source
        and "external_deployment_smoke_commands(upgrade_audit)" in ui_source
        and "def local_neo4j_operation_rows(" in external_deployment_source
        and "local_neo4j_operation_rows(upgrade_audit)" in ui_source
        and "本機 Neo4j / GraphRAG 操作提示" in ui_source
        and "def local_unlocker_operation_rows(" in external_deployment_source
        and "local_unlocker_operation_rows(upgrade_audit)" in ui_source
        and "本機 unlocker 操作提示" in ui_source
        and "def structured_filing_api_operation_rows(" in external_deployment_source
        and "structured_filing_api_operation_rows(upgrade_audit)" in ui_source
        and "結構化文件 API 操作提示" in ui_source
        and "設定檢查" in external_deployment_structured_api_source
        and "configuration_check" in external_deployment_structured_api_source
        and "設定檢查" in external_deployment_unlocker_source
        and "configuration_check" in external_deployment_unlocker_source
        and "單項診斷指令" in ui_source
        and "external_integrations_smoke.py --strict --json" in ui_source,
        "ui_external_deployment_diagnostics_extracted": (
            ui_dir / "external_deployment_diagnostics.py"
        ).exists()
        and "from app.ui.external_deployment_diagnostics import (" in ui_source
        and "def external_deployment_readiness_rows(" in external_deployment_source
        and "def local_dependency_status_rows(" in external_deployment_source
        and "def local_dependency_last_start_rows(" in external_deployment_source
        and "def local_dependency_repair_rows(" in external_deployment_source
        and "def external_deployment_env_key_rows(" in external_deployment_env_keys_source
        and "def external_deployment_env_resolution_rows("
        in external_deployment_env_keys_source
        and "from app.services.external_deployment_env_gaps import"
        in external_deployment_env_keys_source
        and "def external_deployment_env_key_rows(" in env_gap_service_source
        and "def external_deployment_env_resolution_rows(" in env_gap_service_source
        and '"處理策略"' in env_gap_service_source
        and '"處理類型"' in env_gap_service_source
        and '"維護動作"' in env_gap_service_source
        and "external_deployment_env_key_rows(upgrade_audit, service_snapshot)"
        in ui_source
        and "外部設定處理計畫" in ui_source
        and "recommended_maintenance_operation_id(" in ui_source
        and "maintenance_operation_recommendation_caption(" in ui_source
        and "外部設定缺口" in ui_source
        and "def external_deployment_warning_rows(" in external_deployment_source
        and "def high_risk_filing_unlocker_rows(" in external_deployment_source
        and "def local_neo4j_operation_rows(" in external_deployment_source
        and "def structured_filing_api_operation_rows(" in external_deployment_source
        and "def external_deployment_warning_rows(" not in maintenance_status_source
        and "def local_neo4j_operation_rows(" not in maintenance_status_source
        and "def structured_filing_api_operation_rows(" not in maintenance_status_source,
        "ui_external_deployment_diagnostics_path": "app/ui/external_deployment_diagnostics.py",
        "ui_external_deployment_domain_helpers_extracted": (
            ui_dir / "external_deployment_common.py"
        ).exists()
        and readiness_service_path.exists()
        and profile_catalog_path.exists()
        and (ui_dir / "external_deployment_env_keys.py").exists()
        and env_gap_service_path.exists()
        and (ui_dir / "external_deployment_unlocker.py").exists()
        and (ui_dir / "external_deployment_neo4j.py").exists()
        and (ui_dir / "external_deployment_structured_api.py").exists()
        and "def external_deployment_warning_items(" in external_deployment_common_source
        and "from app.services.external_deployment_readiness import"
        in external_deployment_common_source
        and "def external_deployment_readiness_rows(" in external_deployment_common_source
        and "def external_deployment_env_key_rows(" in external_deployment_env_keys_source
        and "def external_deployment_env_resolution_rows("
        in external_deployment_env_keys_source
        and "from app.services.external_deployment_env_gaps import"
        in external_deployment_env_keys_source
        and "def external_deployment_env_gap_report(" in env_gap_service_source
        and "from app.services.external_deployment_profiles import"
        in readiness_service_source
        and "EXTERNAL_READINESS_METADATA = {" in profile_catalog_source
        and "EXTERNAL_LOCAL_ACTION_METADATA = {" in profile_catalog_source
        and "def high_risk_filing_unlocker_rows(" in external_deployment_unlocker_source
        and "def local_unlocker_operation_rows(" in external_deployment_unlocker_source
        and "def local_neo4j_operation_rows(" in external_deployment_neo4j_source
        and "def structured_filing_api_operation_rows(" in external_deployment_structured_api_source
        and "from app.ui.external_deployment_common import" in external_deployment_source
        and "from app.ui.external_deployment_env_keys import" in external_deployment_source
        and "from app.ui.external_deployment_unlocker import" in external_deployment_source
        and "from app.ui.external_deployment_neo4j import" in external_deployment_source
        and "from app.ui.external_deployment_structured_api import" in external_deployment_source,
        "ui_structured_filing_api_operation_operator_labels_enabled": (
            "def _structured_filing_status_label(" in external_deployment_structured_api_source
            and '"設定檢查"' in external_deployment_structured_api_source
            and '"資料商設定檔"' in external_deployment_structured_api_source
            and '"資料商選擇矩陣"' in external_deployment_structured_api_source
            and '"資料商設定預覽"' in external_deployment_structured_api_source
            and '"範例 JSON 合約"' in external_deployment_structured_api_source
            and '"正式 API smoke"' in external_deployment_structured_api_source
            and '"請求格式"' in external_deployment_structured_api_source
            and '"必備欄位"' in external_deployment_structured_api_source
            and '"備援判斷"' in external_deployment_structured_api_source
            and '"missing_required_env": "缺少必要設定"'
            in external_deployment_structured_api_source
            and '"not_configured": "未設定"' in external_deployment_structured_api_source
            and "Configuration check" not in external_deployment_structured_api_source
            and "Provider profile" not in external_deployment_structured_api_source
            and "Provider decision matrix" not in external_deployment_structured_api_source
            and "Provider setup preview" not in external_deployment_structured_api_source
            and "Sample contract" not in external_deployment_structured_api_source
            and "Live smoke" not in external_deployment_structured_api_source
            and "Request contract" not in external_deployment_structured_api_source
            and "Required fields" not in external_deployment_structured_api_source
        ),
        "ui_unlocker_operation_operator_labels_enabled": (
            "def _high_risk_unlocker_status_label(" in external_deployment_unlocker_source
            and '"解鎖服務"' in external_deployment_unlocker_source
            and '"設定檢查"' in external_deployment_unlocker_source
            and '"備援判斷"' in external_deployment_unlocker_source
            and '"MOPS smoke 驗證"' in external_deployment_unlocker_source
            and '"missing_required_env": "缺少必要設定"'
            in external_deployment_unlocker_source
            and "Browser render 後援" in external_deployment_unlocker_source
            and "Configuration check" not in external_deployment_unlocker_source
            and "Fallback 判斷" not in external_deployment_unlocker_source
            and '"項目": "Provider"' not in external_deployment_unlocker_source
            and "browser render fallback" not in external_deployment_unlocker_source
        ),
        "ui_neo4j_operation_operator_labels_enabled": (
            '"圖譜匯入預檢"' in external_deployment_neo4j_source
            and '"Live 查詢驗證"' in external_deployment_neo4j_source
            and '"先匯入再查詢驗證"' in external_deployment_neo4j_source
            and "payload 可用" in external_deployment_neo4j_source
            and "Payload dry-run" not in external_deployment_neo4j_source
            and "Live query smoke" not in external_deployment_neo4j_source
            and "Import-first smoke" not in external_deployment_neo4j_source
            and "payload ready" not in external_deployment_neo4j_source
        ),
        "ui_external_deployment_domain_helper_paths": [
            "app/ui/external_deployment_common.py",
            "app/services/external_deployment_readiness.py",
            "app/services/external_deployment_profiles.py",
            "app/ui/external_deployment_env_keys.py",
            "app/services/external_deployment_env_gaps.py",
            "app/ui/external_deployment_unlocker.py",
            "app/ui/external_deployment_neo4j.py",
            "app/ui/external_deployment_structured_api.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
