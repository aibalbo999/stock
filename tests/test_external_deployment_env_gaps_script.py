from __future__ import annotations

from scripts import external_deployment_env_gaps


def _audit_with_env_gaps() -> dict:
    return {
        "optional_warnings": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": {
                    "ready": False,
                    "fallback_reason": "missing_settings:neo4j_uri",
                    "local_docker_defaults": {
                        "env_keys": [
                            "NEO4J_URI",
                            "NEO4J_USER",
                            "NEO4J_PASSWORD",
                            "NEO4J_DATABASE",
                        ],
                    },
                    "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                },
                "remediation": "設定 Neo4j。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": {
                    "runtime": {
                        "configuration_ready": False,
                        "configuration_check": {
                            "ready": False,
                            "status": "missing_required_env",
                            "missing_env_keys": [
                                "COMPANY_FILING_STRUCTURED_API_PROVIDER",
                                "COMPANY_FILING_STRUCTURED_API_TOKEN",
                                "COMPANY_FILING_STRUCTURED_API_URL",
                            ],
                            "configured_env_keys": [],
                            "token_required": True,
                        },
                        "smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--ticker 2330 --json"
                        ),
                    }
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ]
    }


def test_external_deployment_env_gap_report_classifies_actions() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )
    rows_by_key = {row["設定鍵"]: row for row in report["rows"]}

    assert report["status"] == "action_required"
    assert report["gap_count"] >= 4
    assert report["missing_count"] >= 2
    assert report["manual_secret_count"] >= 1
    assert report["local_action_count"] >= 1
    assert rows_by_key["NEO4J_URI"]["處理類型"] == "本機可套用"
    assert "start_system.py --start-dependencies" in rows_by_key["NEO4J_URI"]["維護動作"]
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["處理類型"] == "需人工密鑰"
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["維護動作"] == (
        "手動補 .env 或 secret manager；不由維護操作寫入。"
    )


def test_external_deployment_env_gap_report_formats_text() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    output = external_deployment_env_gaps.format_external_deployment_env_gap_report(report)

    assert "External deployment env gaps: action_required" in output
    assert "NEO4J_URI" in output
    assert "需人工密鑰" in output
    assert "structured_company_filing_smoke.py" in output


def test_external_deployment_env_gap_script_json_and_strict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        external_deployment_env_gaps,
        "external_deployment_env_gap_report",
        lambda **_kwargs: {
            "status": "action_required",
            "gap_count": 1,
            "missing_count": 1,
            "recommended_count": 0,
            "manual_secret_count": 1,
            "local_action_count": 0,
            "rows": [{"設定鍵": "COMPANY_FILING_STRUCTURED_API_TOKEN"}],
        },
    )

    assert external_deployment_env_gaps.main(["--json"]) == 0
    assert '"COMPANY_FILING_STRUCTURED_API_TOKEN"' in capsys.readouterr().out
    assert external_deployment_env_gaps.main(["--strict", "--json"]) == 1
