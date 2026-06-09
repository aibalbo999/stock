from __future__ import annotations

from app.services.optimization_local_defaults import AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND
from app.services.optimization_progress_summary import (
    effective_gap_note,
    primary_next_action,
    progress_summary,
    local_resolution_projection,
    status_note,
)


def test_local_resolution_projection_groups_local_and_remaining_actions() -> None:
    local_action = {
        "capability": "neo4j_import",
        "label": "外部 Neo4j 匯入連線",
        "action_type": "free_local_or_external_config",
        "locally_available": True,
        "local_auto_default": {
            "group": "neo4j",
            "verify_command": AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
        },
    }
    paid_action = {
        "capability": "company_filing_structured_api_fallback",
        "label": "公司文件結構化 API 備援",
        "action_type": "paid_external",
        "locally_available": False,
    }

    projection = local_resolution_projection(
        projected_status="ready_with_optional_gaps",
        local_resolvable_gap_count=1,
        projected_blocking_gap_count=0,
        projected_optional_gap_count=1,
        prioritized_next_actions=[local_action, paid_action],
    )

    assert projection["status_after_local_defaults"] == "ready_with_optional_gaps"
    assert projection["remaining_paid_external_pending"] == 1
    assert projection["local_action_capabilities"] == ["neo4j_import"]
    assert projection["remaining_action_capabilities"] == ["company_filing_structured_api_fallback"]
    assert projection["local_default_capabilities"] == [
        {
            "capability": "neo4j_import",
            "label": "外部 Neo4j 匯入連線",
            "group": "neo4j",
        }
    ]
    assert "剩餘 1 項外部/付費選配" in projection["next_action"]


def test_primary_next_action_and_summary_surface_local_defaults_decision() -> None:
    primary = primary_next_action(
        "ready_with_optional_gaps",
        [],
        optional_gap_count=2,
        local_resolvable_gap_count=1,
        projected_optional_gap_count=1,
        local_defaults_verify_command="custom local audit",
    )
    summary = progress_summary(
        overall_status="ready_with_optional_gaps",
        effective_status="ready_with_optional_gaps",
        total_domains=4,
        total_checks=33,
        ready_checks=32,
        completion_ratio=0.9697,
        blocking_gap_count=0,
        optional_gap_count=2,
        local_resolvable_gap_count=1,
        effective_blocking_gap_count=0,
        effective_optional_gap_count=1,
        projected_blocking_gap_count=0,
        projected_optional_gap_count=1,
        primary_next_action=primary,
    )

    assert primary["capability"] == "auto_local_defaults"
    assert primary["verify_command"] == "custom local audit"
    assert primary["locally_available"] is True
    assert "相容自動偵測入口" in primary["next_action"]
    assert summary["primary_next_action_capability"] == "auto_local_defaults"
    assert summary["primary_next_action_cost_profile"] == "free_local_available"
    assert summary["projected_optional_gap_count_after_local_defaults"] == 1


def test_progress_summary_helpers_describe_effective_and_ready_states() -> None:
    assert (
        effective_gap_note(
            raw_blocking_gap_count=0,
            raw_optional_gap_count=3,
            effective_blocking_gap_count=0,
            effective_optional_gap_count=1,
            local_resolvable_gap_count=2,
        )
        == "原始缺口為 0 blocking / 3 選配；本機 defaults 可驗證 2 項後，有效剩餘 0 blocking / 1 選配。"
    )
    assert (
        effective_gap_note(
            raw_blocking_gap_count=0,
            raw_optional_gap_count=1,
            effective_blocking_gap_count=0,
            effective_optional_gap_count=1,
            local_resolvable_gap_count=0,
        )
        == ""
    )
    assert status_note("ready") == "核心實作與已選定的外部能力都已就緒。"
    assert status_note("ready_with_optional_gaps") == (
        "核心實作已就緒；剩餘項目屬於外部部署、額度或付費資料源選配。"
    )
