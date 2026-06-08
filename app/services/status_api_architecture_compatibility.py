from __future__ import annotations

from app.services.status_api_architecture_sources import ApiArchitectureSourceContext


def api_compatibility_architecture_status(
    source_context: ApiArchitectureSourceContext,
) -> dict:
    root = source_context.root
    paths = source_context.paths
    sources = source_context.sources
    main_source = sources["main"]
    runtime_source = sources["runtime"]
    compatibility_exports_source = sources["compatibility_exports"]
    compatibility_helpers_source = sources["compatibility_helpers"]
    return {
        "api_compatibility_architecture_status_extracted": True,
        "api_compatibility_architecture_status_path": (
            "app/services/status_api_architecture_compatibility.py"
        ),
        "compatibility_exports_present": paths["compatibility_exports"].exists(),
        "main_uses_compatibility_exports": (
            "compatibility_export_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_exports" in main_source
                and "compatibility_export_namespace" in runtime_source
            )
        ),
        **_compatibility_export_domain_status(source_context, compatibility_exports_source),
        "compatibility_helpers_present": paths["compatibility_helpers"].exists(),
        "main_uses_compatibility_helpers": (
            "compatibility_helper_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_helpers" in main_source
                and "compatibility_helper_namespace" in runtime_source
            )
        ),
        **_compatibility_helper_domain_status(source_context, compatibility_helpers_source),
        **_compatibility_service_domain_status(source_context),
        "main_imports_legacy_facade": "app.api.legacy_facade" in main_source
        or "LegacyApiFacade" in main_source,
        "legacy_facade_api_reference_scan_paths": [
            str(path.relative_to(root))
            for path in source_context.legacy_facade_reference_scan_paths
        ],
        "legacy_facade_api_reference_scan_file_count": len(
            source_context.legacy_facade_reference_scan_paths
        ),
        "legacy_facade_api_reference_locations": (
            source_context.legacy_facade_api_reference_locations
        ),
        "legacy_facade_api_reference_count": sum(
            item["count"] for item in source_context.legacy_facade_api_reference_locations
        ),
        "legacy_facade_present": paths["legacy_facade"].exists(),
        "legacy_facade_alias_only": "ApiCompatibilityService" in sources["legacy_facade"]
        and "class LegacyApiFacade(ApiCompatibilityService)" in sources["legacy_facade"],
    }


def _compatibility_export_domain_status(
    source_context: ApiArchitectureSourceContext,
    compatibility_exports_source: str,
) -> dict:
    paths = source_context.paths
    sources = source_context.sources
    return {
        "compatibility_export_domain_builders_extracted": (
            paths["compatibility_export_core"].exists()
            and paths["compatibility_export_data"].exists()
            and paths["compatibility_export_discovery"].exists()
            and paths["compatibility_export_report"].exists()
            and paths["compatibility_export_workflow"].exists()
            and "def compatibility_core_export_namespace("
            in sources["compatibility_export_core"]
            and "def compatibility_data_export_namespace("
            in sources["compatibility_export_data"]
            and "def compatibility_discovery_export_namespace("
            in sources["compatibility_export_discovery"]
            and "def compatibility_report_export_namespace("
            in sources["compatibility_export_report"]
            and "def compatibility_workflow_export_namespace("
            in sources["compatibility_export_workflow"]
            and "compatibility_core_export_namespace" in compatibility_exports_source
            and "compatibility_data_export_namespace" in compatibility_exports_source
            and "compatibility_discovery_export_namespace" in compatibility_exports_source
            and "compatibility_report_export_namespace" in compatibility_exports_source
            and "compatibility_workflow_export_namespace" in compatibility_exports_source
            and "from app.data_sources." not in compatibility_exports_source
            and "from app.services.report_generator import" not in compatibility_exports_source
            and "from app.services.discovery_workflow import" not in compatibility_exports_source
        ),
        "compatibility_export_domain_builder_paths": [
            "app/api/compatibility_export_core.py",
            "app/api/compatibility_export_data.py",
            "app/api/compatibility_export_discovery.py",
            "app/api/compatibility_export_report.py",
            "app/api/compatibility_export_workflow.py",
        ],
    }


def _compatibility_helper_domain_status(
    source_context: ApiArchitectureSourceContext,
    compatibility_helpers_source: str,
) -> dict:
    paths = source_context.paths
    sources = source_context.sources
    return {
        "compatibility_helper_domain_builders_extracted": (
            paths["compatibility_helper_candidate"].exists()
            and paths["compatibility_helper_discovery"].exists()
            and paths["compatibility_helper_followup"].exists()
            and paths["compatibility_helper_run_state"].exists()
            and "def candidate_compatibility_helper_namespace("
            in sources["compatibility_helper_candidate"]
            and "def discovery_compatibility_helper_namespace("
            in sources["compatibility_helper_discovery"]
            and "def follow_up_compatibility_helper_namespace("
            in sources["compatibility_helper_followup"]
            and "def run_state_compatibility_helper_namespace("
            in sources["compatibility_helper_run_state"]
            and "candidate_compatibility_helper_namespace" in compatibility_helpers_source
            and "discovery_compatibility_helper_namespace" in compatibility_helpers_source
            and "follow_up_compatibility_helper_namespace" in compatibility_helpers_source
            and "run_state_compatibility_helper_namespace" in compatibility_helpers_source
            and "def run_topic_discovery_ingestion(" not in compatibility_helpers_source
            and "def run_report_follow_up(" not in compatibility_helpers_source
            and "def apply_company_filing_gate_to_candidate_payload("
            not in compatibility_helpers_source
            and "def safe_mark_run_failed(" not in compatibility_helpers_source
        ),
        "compatibility_helper_domain_builder_paths": [
            "app/api/compatibility_helper_candidate.py",
            "app/api/compatibility_helper_discovery.py",
            "app/api/compatibility_helper_followup.py",
            "app/api/compatibility_helper_run_state.py",
        ],
    }


def _compatibility_service_domain_status(
    source_context: ApiArchitectureSourceContext,
) -> dict:
    paths = source_context.paths
    sources = source_context.sources
    api_compatibility_source = sources["api_compatibility"]
    return {
        "compatibility_service_present": paths["api_compatibility"].exists(),
        "compatibility_service_domain_mixins_extracted": (
            paths["compatibility_candidate"].exists()
            and paths["compatibility_discovery"].exists()
            and paths["compatibility_followup"].exists()
            and paths["compatibility_run_state"].exists()
            and "class CandidateCompatibilityMixin" in sources["compatibility_candidate"]
            and "class DiscoveryCompatibilityMixin" in sources["compatibility_discovery"]
            and "class FollowUpCompatibilityMixin" in sources["compatibility_followup"]
            and "class RunStateCompatibilityMixin" in sources["compatibility_run_state"]
            and "CandidateCompatibilityMixin" in api_compatibility_source
            and "DiscoveryCompatibilityMixin" in api_compatibility_source
            and "FollowUpCompatibilityMixin" in api_compatibility_source
            and "RunStateCompatibilityMixin" in api_compatibility_source
            and "def run_topic_discovery_ingestion(" not in api_compatibility_source
            and "def run_report_follow_up(" not in api_compatibility_source
            and "def apply_company_filing_gate_to_candidate_payload("
            not in api_compatibility_source
            and "def safe_mark_run_failed(" not in api_compatibility_source
        ),
        "compatibility_service_domain_mixin_paths": [
            "app/services/api_compatibility_candidate.py",
            "app/services/api_compatibility_discovery.py",
            "app/services/api_compatibility_followup.py",
            "app/services/api_compatibility_run_state.py",
        ],
    }
