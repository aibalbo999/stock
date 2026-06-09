from __future__ import annotations

from app.services.status_capability_data_business_filings import company_filing_capabilities
from app.services.status_capability_helpers import capability as _capability
from app.services.status_market_data import _market_data_provider_readiness


def data_business_capabilities(
    *,
    market_cache_status: dict,
    finmind_status: dict,
    fugle_status: dict,
    company_filing_status: dict,
    report_retention_status: dict,
    candidate_confidence_status: dict,
) -> dict:
    market_provider_readiness = _market_data_provider_readiness(
        market_cache_status,
        finmind_status,
        fugle_status,
    )

    return {
        "market_data_cache": _capability(
            "ready" if market_cache_status.get("available") else "degraded",
            evidence={
                "enabled": market_cache_status.get("enabled"),
                "available": market_cache_status.get("available"),
                "backend": market_cache_status.get("backend"),
                "stale_rescue_enabled": market_cache_status.get("stale_rescue_enabled"),
                "latest_only_source_marker": market_cache_status.get("latest_only_source_marker"),
                "financial_metrics_ttl_seconds": market_cache_status.get(
                    "financial_metrics_ttl_seconds"
                ),
                "valuation_metrics_ttl_seconds": market_cache_status.get(
                    "valuation_metrics_ttl_seconds"
                ),
            },
        ),
        "market_data_provider_fallback": _capability(
            "ready" if market_provider_readiness.get("ready") else "degraded",
            evidence={
                "price_provider_order": market_cache_status.get("price_provider_order"),
                "provider_matrix": market_cache_status.get("provider_matrix"),
                "fugle_configured": fugle_status.get("configured"),
                "finmind_configured": finmind_status.get("configured"),
                **market_provider_readiness,
            },
        ),
        "latest_report_retention": _capability(
            "ready"
            if report_retention_status.get("write_prunes_db_by_topic")
            and report_retention_status.get("write_prunes_report_artifacts_by_topic")
            and report_retention_status.get("repository_create_records_retention_result")
            and report_retention_status.get("report_file_write_returns_retention_result")
            and report_retention_status.get("report_file_write_retains_latest_version")
            and report_retention_status.get("repository_create_retains_latest_version")
            and report_retention_status.get("celery_report_write_uses_combined_retention_guard")
            and report_retention_status.get("list_reports_uses_latest_by_topic")
            and report_retention_status.get("quality_summary_uses_latest_by_topic")
            and report_retention_status.get("maintenance_prunes_db_by_topic")
            and report_retention_status.get("maintenance_prunes_report_artifacts_by_topic")
            and report_retention_status.get("scheduled_cleanup_config_available")
            and report_retention_status.get("scheduled_cleanup_payload_retains_latest")
            and report_retention_status.get("scheduled_cleanup_task_registered")
            and report_retention_status.get("scheduled_cleanup_beat_registered")
            and report_retention_status.get("scheduled_cleanup_task_queue_visible")
            and report_retention_status.get("settings_ui_scheduled_cleanup_controls")
            and report_retention_status.get("run_links_cleared_for_pruned_reports")
            and report_retention_status.get("run_output_paths_cleared_for_pruned_reports")
            and report_retention_status.get("delete_before_clears_run_links")
            and report_retention_status.get("orphan_cleanup_clears_output_path")
            and report_retention_status.get("manual_delete_clears_run_links")
            and report_retention_status.get("manual_delete_prunes_report_artifacts")
            and report_retention_status.get("manual_delete_artifact_guardrail")
            and report_retention_status.get("report_artifact_retention_smoke_passed")
            and report_retention_status.get("report_retention_preview_smoke_passed")
            else "degraded",
            evidence=report_retention_status,
            detail=(
                "Generated reports use latest-per-topic retention across DB writes, "
                "report center queries, quality summary, scheduled maintenance cleanup, "
                "and report artifacts."
            ),
        ),
        **company_filing_capabilities(company_filing_status=company_filing_status),
        "source_quality_weighting": _capability(
            "ready"
            if (candidate_confidence_status.get("source_credibility_weights") or {}).get(
                "investment_blog", 1.0
            )
            < 0.75
            else "degraded",
            evidence={
                "promotion_rule": candidate_confidence_status.get("promotion_rule"),
                "source_credibility_weights": candidate_confidence_status.get(
                    "source_credibility_weights"
                ),
            },
        ),
    }
