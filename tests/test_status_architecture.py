import sys
from pathlib import Path

from app.core.config import Settings


def test_backend_status_collectors_for_database_workflow_and_security(
    service_status_snapshot,
) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_security_source = Path("app/services/status_security.py").read_text()

    assert "database" in status
    assert "workflow_orchestration" in status
    assert "python_runtime" in status
    assert "task_queue" in status
    assert status["database"]["init_mode"] == Settings().database_init_mode
    assert status["database"]["create_all_non_sqlite_allowed"] is False
    assert "migration" in status["database"]
    assert "up_to_date" in status["database"]["migration"]
    assert status["workflow_orchestration"]["engine"] == Settings().workflow_engine
    assert status["workflow_orchestration"]["checkpoint_store"] == "analysis_run.payload_json"
    assert status["workflow_orchestration"]["local_fallback_enabled"] is True
    assert status["workflow_orchestration"]["ready"] is True
    assert status["security_scanning"]["external_engine_integration"] is True
    assert status["security_scanning"]["external_engine_available"] is True
    assert status["security_scanning"]["default_engine_external"] is True
    assert status["security_scanning"]["local_regex_active"] is False
    assert status["security_scanning"]["detect_secrets_dependency_declared"] is True
    assert status["security_scanning"]["local_regex_fallback_enabled"] is True
    assert status["security_scanning"]["external_engine_structured_findings"] is True
    assert status["security_scanning"]["gitleaks_json_report_supported"] is True
    assert status["security_scanning"]["baseline_read_only_default"] is True
    assert status["security_scanning"]["baseline_update_flag"] == "--update-baseline"
    assert status["security_scanning"]["collector_path"] == "app/services/status_security.py"
    assert (
        "from app.services.status_security import security_scan_status as collect_security_scan_status"
        in service_status_source
    )
    assert "def _security_scan_status(" not in service_status_source
    assert "def security_scan_status(" in status_security_source
    assert status["security_scanning"]["default_engine"] in {
        "detect-secrets",
        "gitleaks",
        "local_regex",
    }


def test_task_queue_status_contract_and_compatibility_alias(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_task_queue_source = Path("app/services/status_task_queue.py").read_text()

    assert status["task_queue"]["collector_path"] == "app/services/status_task_queue.py"
    assert status["task_queue"]["broker_ok"] == status["redis"]["ok"]
    assert status["task_queue"]["backend_ok"] == status["redis"]["ok"]
    assert status["task_queue"]["submission_contract_ready"] is True
    assert status["task_queue"]["processing_ready"] is bool(
        status["task_queue"]["ready"] and status["task_queue"]["worker_online"]
    )
    assert status["task_queue"]["task_export_namespace_available"] is True
    assert status["task_queue"]["celery_app_available"] is True
    assert isinstance(status["task_queue"]["worker_ping_checked"], bool)
    assert isinstance(status["task_queue"]["worker_online"], bool)
    assert isinstance(status["task_queue"]["worker_count"], int)
    assert isinstance(status["task_queue"]["worker_nodes"], list)
    assert status["task_queue"]["worker_ping_timeout_seconds"] >= 0.1
    assert status["task_queue"]["required_task_exports"] == [
        "celery_app",
        "generate_report_task",
        "discovered_report_task",
        "data_operation_task",
        "report_follow_up_task",
    ]
    assert status["task_queue"]["missing_task_exports"] == []
    assert status["task_queue"]["task_names_match_expected"] is True
    assert status["task_queue"]["task_async_bridge_guard_present"] is True
    assert status["task_queue"]["task_async_bridge"]["direct_asyncio_run_count"] == 0
    assert status["task_queue"]["task_async_bridge"]["helper_imported"] is True
    assert all(status["task_queue"]["task_async_bridge"]["operation_markers"].values())
    assert status["task_queue"]["compose_runtime_env_passthrough_ready"] is True
    assert status["task_queue"]["compose_runtime_env"]["celery_services_use_anchor"] is True
    assert status["task_queue"]["compose_runtime_env"]["missing_by_group"] == {}
    assert status["task_queue"]["compose_runtime_env"]["present_groups"]["llm"]["GOOGLE_API_KEYS"] is True
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["company_filings"][
            "COMPANY_FILING_STRUCTURED_API_URL"
        ]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["observability"][
            "PHOENIX_ENDPOINT"
        ]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"][
            "COMPOSE_NEO4J_URI"
        ]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["NEO4J_URI"]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"][
            "COMPOSE_NEO4J_AUTH"
        ]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["NEO4J_AUTH"]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["workflow"][
            "WORKFLOW_ENGINE"
        ]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["report_policy"][
            "SYNC_REPORT_PRE_REFRESH_ENABLED"
        ]
        is True
    )
    assert "POST /tasks/data-operation" in status["task_queue"]["submission_endpoints"]
    assert "GET /tasks/summary" in status["task_queue"]["status_endpoints"]
    assert status["celery"]["ready"] == status["task_queue"]["ready"]
    assert status["celery"]["submission_contract_ready"] is True
    assert (
        "from app.services.status_task_queue import task_queue_status as collect_task_queue_status"
        in service_status_source
    )
    assert "def task_queue_status(" in status_task_queue_source


def test_thin_api_controller_architecture_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    thin_api = status["upgrade_capability_matrix"]["architecture"]["thin_api_controller"]
    evidence = thin_api["evidence"]

    assert thin_api["status"] == "ready"
    assert evidence["collector_path"] == "app/services/status_api_architecture.py"
    assert evidence["main_py_lines"] <= 120
    assert "report_routes.py" in evidence["route_modules"]
    assert evidence["app_factory_present"] is True
    assert evidence["main_uses_app_factory"] is True
    assert evidence["compatibility_exports_present"] is True
    assert evidence["main_uses_compatibility_exports"] is True
    assert evidence["service_factory_lines"] < 260
    assert evidence["report_service_factory_extracted"] is True
    assert evidence["report_service_factory_path"] == "app/api/service_factory_report.py"
    assert evidence["data_service_factory_extracted"] is True
    assert evidence["data_service_factory_path"] == "app/api/service_factory_data.py"
    assert evidence["workflow_service_factory_extracted"] is True
    assert evidence["workflow_service_factory_path"] == "app/api/service_factory_workflow.py"
    assert evidence["ai_graph_service_factory_extracted"] is True
    assert evidence["ai_graph_service_factory_path"] == "app/api/service_factory_ai.py"
    assert evidence["compatibility_helpers_present"] is True
    assert evidence["main_uses_compatibility_helpers"] is True
    assert evidence["compatibility_helper_domain_builders_extracted"] is True
    assert evidence["compatibility_helper_domain_builder_paths"] == [
        "app/api/compatibility_helper_candidate.py",
        "app/api/compatibility_helper_discovery.py",
        "app/api/compatibility_helper_followup.py",
        "app/api/compatibility_helper_run_state.py",
    ]
    assert evidence["api_runtime_present"] is True
    assert evidence["main_uses_api_runtime"] is True
    assert evidence["task_uses_api_runtime"] is True
    assert evidence["task_exports_present"] is True
    assert evidence["api_runtime_uses_task_exports"] is True
    assert evidence["task_imports_api_main"] is False
    assert evidence["compatibility_exports_imports_tasks"] is False
    assert evidence["main_direct_domain_import_count"] == 0
    assert evidence["structured_task_submission_errors"] is True
    assert evidence["task_submission_error_detail_path"] == "app/api/error_details.py"
    assert evidence["task_submission_error_endpoint_coverage"] == {
        "generate_report_async": True,
        "run_discovered_async": True,
        "data_operation": True,
        "report_follow_up": True,
    }
    assert evidence["sync_report_network_refresh_opt_in"] is True
    assert evidence["sync_report_pre_refresh_default_enabled"] is False
    assert evidence["sync_report_quality_recovery_default_enabled"] is False
    assert evidence["sync_report_blocking_async_refresh_calls_present"] is True
    assert evidence["sync_report_async_bridge_guard_present"] is True
    assert evidence["sync_report_blocking_async_calls_gated"] is True
    assert evidence["compatibility_service_present"] is True
    assert evidence["compatibility_service_domain_mixins_extracted"] is True
    assert evidence["compatibility_service_domain_mixin_paths"] == [
        "app/services/api_compatibility_candidate.py",
        "app/services/api_compatibility_discovery.py",
        "app/services/api_compatibility_followup.py",
        "app/services/api_compatibility_run_state.py",
    ]
    assert evidence["main_imports_legacy_facade"] is False
    assert evidence["legacy_facade_present"] is True
    assert evidence["legacy_facade_alias_only"] is True


def test_background_task_queue_architecture_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    task_queue_arch = status["upgrade_capability_matrix"]["architecture"]["background_task_queue"]

    assert task_queue_arch["status"] == ("ready" if status["task_queue"]["ready"] else "degraded")
    assert task_queue_arch["evidence"]["submission_contract_ready"] is True
    assert task_queue_arch["evidence"]["broker_ok"] == status["redis"]["ok"]
    assert task_queue_arch["evidence"]["processing_ready"] == status["task_queue"]["processing_ready"]
    assert task_queue_arch["evidence"]["worker_online"] == status["task_queue"]["worker_online"]
    assert "worker_nodes" in task_queue_arch["evidence"]
    assert task_queue_arch["evidence"]["task_async_bridge_guard_present"] is True
    assert task_queue_arch["evidence"]["task_async_bridge"]["direct_asyncio_run_count"] == 0
    assert task_queue_arch["evidence"]["compose_runtime_env_passthrough_ready"] is True
    assert task_queue_arch["evidence"]["compose_runtime_env"]["missing_by_group"] == {}
    assert task_queue_arch["evidence"]["structured_task_submission_errors"] is True
    assert task_queue_arch["evidence"]["task_failure_diagnostics_shared_service"] is True
    assert task_queue_arch["evidence"]["task_failure_diagnostics_persisted_to_run_payload"] is True
    assert "POST /tasks/data-operation" in task_queue_arch["evidence"]["submission_endpoints"]


def test_runtime_migration_and_secret_scanning_architecture_capabilities(
    service_status_snapshot,
) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_python_runtime_source = Path("app/services/status_python_runtime.py").read_text()
    architecture = status["upgrade_capability_matrix"]["architecture"]

    assert architecture["workflow_orchestration"]["status"] == "ready"

    python_runtime = architecture["python_runtime"]
    expected_python_runtime_status = "ready" if sys.version_info[:2] >= (3, 11) else "degraded"
    assert python_runtime["status"] == expected_python_runtime_status
    assert status["python_runtime"]["required_specifier"] == ">=3.11"
    assert status["python_runtime"]["minimum_supported"] == "3.11"
    assert status["python_runtime"]["python_version_file"] == "3.11"
    assert status["python_runtime"]["project_targets_aligned"] is True
    assert status["python_runtime"]["collector_path"] == "app/services/status_python_runtime.py"
    assert "from app.services.status_python_runtime import (" in service_status_source
    assert "def _python_runtime_status(" not in service_status_source
    assert "def python_runtime_status(" in status_python_runtime_source
    assert (
        status["python_runtime"]["bootstrap_cli"]
        == ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing"
    )
    assert status["python_runtime"]["bootstrap_dry_run_cli"].endswith(
        "scripts/bootstrap_python_runtime.py --json"
    )
    assert status["python_runtime"]["interpreter_install_hints"][0] == {
        "tool": "homebrew",
        "command": "brew install python@3.11",
        "venv_command": "python3.11 -m venv .venv",
    }
    assert architecture["database_migrations"]["status"] in {"ready", "degraded"}
    assert architecture["database_migrations"]["evidence"]["head_revision"]
    assert architecture["secret_scanning"]["status"] == "ready"
    assert architecture["secret_scanning"]["evidence"]["external_engine_available"] is True
    assert architecture["secret_scanning"]["evidence"]["default_engine_external"] is True
    assert architecture["secret_scanning"]["evidence"]["local_regex_active"] is False
    assert architecture["secret_scanning"]["evidence"]["local_regex_fallback_role"] == (
        "fallback_only"
    )
    assert architecture["secret_scanning"]["evidence"]["external_engine_structured_findings"] is True
    assert architecture["secret_scanning"]["evidence"]["gitleaks_json_report_supported"] is True
    assert "detect-secrets" in architecture["secret_scanning"]["evidence"][
        "supported_external_engines"
    ]
