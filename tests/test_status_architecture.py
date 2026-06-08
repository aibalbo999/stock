import sys
from pathlib import Path

from app.core.config import Settings
from app.services.local_dependency_diagnostics import local_dependency_runtime_status


def test_backend_status_collectors_for_database_workflow_and_security(
    service_status_snapshot,
) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_security_source = Path("app/services/status_security.py").read_text()
    local_dependency_source = Path("app/services/local_dependency_diagnostics.py").read_text()

    assert "database" in status
    assert "workflow_orchestration" in status
    assert "python_runtime" in status
    assert "task_queue" in status
    assert "local_dependencies" in status
    assert status["local_dependencies"]["collector_path"] == (
        "app/services/local_dependency_diagnostics.py"
    )
    assert status["local_dependencies"]["compose_path"] == "docker-compose.yml"
    assert isinstance(status["local_dependencies"]["compose_file_present"], bool)
    assert status["local_dependencies"]["status"] in {"ready", "partial", "not_running"}
    assert {row["service"] for row in status["local_dependencies"]["ports"]} == {
        "redis",
        "postgres",
        "neo4j",
        "browserless",
        "chroma",
        "flaresolverr",
    }
    assert all(isinstance(row["open"], bool) for row in status["local_dependencies"]["ports"])
    assert "start_core" in status["local_dependencies"]["commands"]
    assert "verify_flaresolverr" in status["local_dependencies"]["commands"]
    assert isinstance(status["local_dependencies"]["repair_plan"], list)
    assert all(
        {"item", "state", "next_step", "repair_command", "verify_command", "severity"} <= set(row)
        for row in status["local_dependencies"]["repair_plan"]
    )
    assert status["local_dependencies"]["last_start"]["path"] == (
        "data/local_dependency_start_status.json"
    )
    assert isinstance(status["local_dependencies"]["last_start"]["available"], bool)
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
    assert (
        "from app.services.local_dependency_diagnostics import local_dependency_runtime_status"
        in service_status_source
    )
    assert "def local_dependency_runtime_status(" in local_dependency_source
    assert "def local_dependency_last_start_status(" in local_dependency_source
    assert "def local_dependency_repair_plan(" in local_dependency_source
    assert "def is_local_port_open(" in local_dependency_source
    assert "def _security_scan_status(" not in service_status_source
    assert "def security_scan_status(" in status_security_source
    assert status["security_scanning"]["default_engine"] in {
        "detect-secrets",
        "gitleaks",
        "local_regex",
    }


def test_local_dependency_runtime_status_reads_last_start_snapshot(tmp_path) -> None:
    status_path = tmp_path / "data/local_dependency_start_status.json"
    status_path.parent.mkdir()
    status_path.write_text(
        (
            '{"schema_version":1,"updated_at":"2026-06-09T01:02:03Z",'
            '"status":"已啟動","message":"ok","services":["neo4j"],'
            '"wait":{"neo4j":true},"applied_env_keys":["NEO4J_URI"],'
            '"include_unlocker":false,"wait_seconds":5}'
        ),
        encoding="utf-8",
    )

    status = local_dependency_runtime_status(
        root=tmp_path,
        port_open_func=lambda _host, _port: False,
    )

    assert status["last_start"]["available"] is True
    assert status["last_start"]["path"] == "data/local_dependency_start_status.json"
    assert status["last_start"]["status"] == "已啟動"
    assert status["last_start"]["wait"] == {"neo4j": True}


def test_local_dependency_runtime_status_builds_service_repair_plan(tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    def fake_port_open(_host: str, port: int) -> bool:
        return port in {6379, 5432, 8001}

    status = local_dependency_runtime_status(
        root=tmp_path,
        environ={"COMPANY_FILING_BROWSER_RENDER_URL": "http://127.0.0.1:8191/v1"},
        port_open_func=fake_port_open,
    )

    repair_by_item = {row["item"]: row for row in status["repair_plan"]}
    assert repair_by_item["Neo4j"] == {
        "item": "Neo4j",
        "state": "未偵測",
        "next_step": "GraphRAG live graph。啟動核心本機依賴後重新檢查。",
        "repair_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
        "severity": "error",
    }
    assert repair_by_item["Browserless"]["verify_command"] == (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--wait-local-browserless 20 --local-browser-render-defaults --json"
    )
    assert repair_by_item["FlareSolverr unlocker"]["severity"] == "warning"
    assert "--prefer-unlocker" in repair_by_item["FlareSolverr unlocker"]["repair_command"]


def test_task_queue_status_contract_and_compatibility_alias(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_task_queue_source = Path("app/services/status_task_queue.py").read_text()
    status_task_queue_sources_source = Path("app/services/status_task_queue_sources.py").read_text()

    assert status["task_queue"]["collector_path"] == "app/services/status_task_queue.py"
    assert status["task_queue"]["task_queue_source_diagnostics_extracted"] is True
    assert status["task_queue"]["task_queue_source_diagnostics_path"] == (
        "app/services/status_task_queue_sources.py"
    )
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
    assert status["task_queue"]["repair_commands"]["inspect_ping"].endswith("inspect ping")
    assert (
        "scripts/start_system.py --start-dependencies"
        in status["task_queue"]["repair_commands"]["start_dependencies"]
    )
    assert (
        "worker -B --loglevel=INFO --pool=solo"
        in status["task_queue"]["repair_commands"]["start_worker"]
    )
    assert "scripts/upgrade_audit.py" in status["task_queue"]["repair_commands"]["upgrade_audit"]
    assert isinstance(status["task_queue"]["repair_plan"], list)
    assert all(
        {"item", "state", "next_step", "repair_command", "verify_command", "severity"} <= set(row)
        for row in status["task_queue"]["repair_plan"]
    )
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
    assert status["task_queue"]["app_asyncio_run_policy_ready"] is True
    assert status["task_queue"]["app_asyncio_run_policy"]["scan_root"] == "app"
    assert status["task_queue"]["app_asyncio_run_policy"]["scan_file_count"] >= 100
    assert status["task_queue"]["app_asyncio_run_policy"]["allowed_paths"] == [
        "app/core/async_bridge.py"
    ]
    app_asyncio_run_locations = status["task_queue"]["app_asyncio_run_policy"]["locations"]
    assert [location["path"] for location in app_asyncio_run_locations] == [
        "app/core/async_bridge.py"
    ]
    assert app_asyncio_run_locations[0]["line"] >= 1
    assert status["task_queue"]["app_asyncio_run_policy"]["forbidden_locations"] == []
    assert status["task_queue"]["app_asyncio_run_policy"]["parse_errors"] == []
    assert status["task_queue"]["compose_runtime_env_passthrough_ready"] is True
    assert status["task_queue"]["compose_runtime_env"]["celery_services_use_anchor"] is True
    assert status["task_queue"]["compose_runtime_env"]["missing_by_group"] == {}
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["llm"]["GOOGLE_API_KEYS"]
        is True
    )
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
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["COMPOSE_NEO4J_URI"]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["NEO4J_URI"] is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["COMPOSE_NEO4J_AUTH"]
        is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["neo4j"]["NEO4J_AUTH"] is True
    )
    assert (
        status["task_queue"]["compose_runtime_env"]["present_groups"]["workflow"]["WORKFLOW_ENGINE"]
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
    assert "def _asyncio_run_call_locations(" not in status_task_queue_source
    assert "def task_queue_source_diagnostics(" in status_task_queue_sources_source


def test_thin_api_controller_architecture_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    thin_api = status["upgrade_capability_matrix"]["architecture"]["thin_api_controller"]
    evidence = thin_api["evidence"]
    status_api_source = Path("app/services/status_api_architecture.py").read_text()
    status_api_compatibility_source = Path(
        "app/services/status_api_architecture_compatibility.py"
    ).read_text()

    assert thin_api["status"] == "ready"
    assert evidence["collector_path"] == "app/services/status_api_architecture.py"
    assert evidence["api_source_context_extracted"] is True
    assert evidence["api_source_context_path"] == (
        "app/services/status_api_architecture_sources.py"
    )
    assert "def api_compatibility_architecture_status(" in (
        status_api_compatibility_source
    )
    assert "api_compatibility_architecture_status(source_context)" in status_api_source
    assert '"compatibility_export_domain_builders_extracted"' not in status_api_source
    assert '"compatibility_helper_domain_builders_extracted"' not in status_api_source
    assert '"compatibility_service_domain_mixins_extracted"' not in status_api_source
    assert '"legacy_facade_alias_only"' not in status_api_source
    assert evidence["api_compatibility_architecture_status_extracted"] is True
    assert evidence["api_compatibility_architecture_status_path"] == (
        "app/services/status_api_architecture_compatibility.py"
    )
    assert evidence["main_py_lines"] <= 120
    assert "report_routes.py" in evidence["route_modules"]
    assert evidence["app_factory_present"] is True
    assert evidence["main_uses_app_factory"] is True
    assert evidence["compatibility_exports_present"] is True
    assert evidence["main_uses_compatibility_exports"] is True
    assert evidence["compatibility_export_domain_builders_extracted"] is True
    assert evidence["compatibility_export_domain_builder_paths"] == [
        "app/api/compatibility_export_core.py",
        "app/api/compatibility_export_data.py",
        "app/api/compatibility_export_discovery.py",
        "app/api/compatibility_export_report.py",
        "app/api/compatibility_export_workflow.py",
    ]
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
    assert evidence["task_submission_error_helper_path"] == "app/api/task_submission_errors.py"
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
    assert "app/api/main.py" in evidence["legacy_facade_api_reference_scan_paths"]
    assert "app/api/runtime.py" in evidence["legacy_facade_api_reference_scan_paths"]
    assert "app/api/legacy_facade.py" not in evidence["legacy_facade_api_reference_scan_paths"]
    assert evidence["legacy_facade_api_reference_scan_file_count"] >= 20
    assert evidence["legacy_facade_api_reference_count"] == 0
    assert evidence["legacy_facade_api_reference_locations"] == []
    assert evidence["legacy_facade_present"] is True
    assert evidence["legacy_facade_alias_only"] is True


def test_background_task_queue_architecture_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    task_queue_arch = status["upgrade_capability_matrix"]["architecture"]["background_task_queue"]

    assert task_queue_arch["status"] == ("ready" if status["task_queue"]["ready"] else "degraded")
    assert task_queue_arch["evidence"]["submission_contract_ready"] is True
    assert task_queue_arch["evidence"]["broker_ok"] == status["redis"]["ok"]
    assert (
        task_queue_arch["evidence"]["processing_ready"] == status["task_queue"]["processing_ready"]
    )
    assert task_queue_arch["evidence"]["worker_online"] == status["task_queue"]["worker_online"]
    assert "worker_nodes" in task_queue_arch["evidence"]
    assert task_queue_arch["evidence"]["task_queue_source_diagnostics_extracted"] is True
    assert task_queue_arch["evidence"]["task_async_bridge_guard_present"] is True
    assert task_queue_arch["evidence"]["task_async_bridge"]["direct_asyncio_run_count"] == 0
    assert task_queue_arch["evidence"]["app_asyncio_run_policy_ready"] is True
    assert task_queue_arch["evidence"]["app_asyncio_run_policy"]["forbidden_locations"] == []
    assert task_queue_arch["evidence"]["app_asyncio_run_policy"]["allowed_paths"] == [
        "app/core/async_bridge.py"
    ]
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
    assert (
        architecture["secret_scanning"]["evidence"]["external_engine_structured_findings"] is True
    )
    assert architecture["secret_scanning"]["evidence"]["gitleaks_json_report_supported"] is True
    assert (
        "detect-secrets"
        in architecture["secret_scanning"]["evidence"]["supported_external_engines"]
    )
