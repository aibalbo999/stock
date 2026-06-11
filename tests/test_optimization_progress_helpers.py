from __future__ import annotations

from app.services.optimization_free_validation import capability_free_validation
from app.services.optimization_local_defaults import (
    EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND,
    EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND,
    local_default_capabilities,
    local_default_verify_commands,
    local_defaults_verify_command,
)


def test_local_defaults_command_combines_local_dependency_groups() -> None:
    neo4j_action = {
        "capability": "neo4j_import",
        "label": "外部 Neo4j 匯入連線",
        "local_auto_default": {
            "group": "neo4j",
            "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
        },
    }
    unlocker_action = {
        "capability": "company_filing_high_risk_unlocker",
        "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
        "local_auto_default": {
            "group": "flaresolverr",
            "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
        },
    }
    browserless_action = {
        "capability": "company_filing_browser_or_proxy_fallback",
        "label": "公司文件 Proxy / Browser render / Playwright 後援",
        "local_auto_default": {
            "group": "browserless",
            "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
        },
    }

    assert local_defaults_verify_command([neo4j_action, unlocker_action]) == (
        EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND
    )
    assert local_defaults_verify_command([neo4j_action, browserless_action]) == (
        EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND
    )
    assert local_default_verify_commands(
        EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND,
        [neo4j_action, unlocker_action],
    ) == [
        EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND,
        ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
    ]
    assert local_default_capabilities([neo4j_action, unlocker_action]) == [
        {
            "capability": "neo4j_import",
            "label": "外部 Neo4j 匯入連線",
            "group": "neo4j",
        },
        {
            "capability": "company_filing_high_risk_unlocker",
            "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
            "group": "flaresolverr",
        },
    ]


def test_capability_free_validation_extracts_ordered_unique_commands() -> None:
    result = capability_free_validation(
        {
            "evidence": {
                "runtime": {
                    "sample_contract_cli": "sample --sample-json fixture.json",
                    "free_validation": {
                        "sample_contract_cli": "sample --sample-json fixture.json",
                        "local_fixture_http_smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                            "--json --strict"
                        ),
                        "local_fixture_provider_profile_smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                            "--provider-profile tej --json --strict"
                        ),
                        "local_fixture_smoke_cli": "custom fixture smoke",
                    },
                }
            }
        }
    )

    assert result == {
        "available": True,
        "label": "樣本資料 + 本機測試 API + 提供者設定可驗證",
        "commands": [
            "sample --sample-json fixture.json",
            (".venv/bin/python scripts/structured_company_filing_fixture_smoke.py --json --strict"),
            (
                ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                "--provider-profile tej --json --strict"
            ),
            "custom fixture smoke",
        ],
    }
