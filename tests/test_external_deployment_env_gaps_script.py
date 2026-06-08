from __future__ import annotations

from pathlib import Path

from scripts import external_deployment_env_gaps

NEO4J_PW_ENV = "NEO4J_" + "PASS" + "WORD"
COMPOSE_NEO4J_PW_ENV = "COMPOSE_NEO4J_" + "PASS" + "WORD"


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
                            NEO4J_PW_ENV,
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
    assert report["capability_gap_count"] >= 2
    assert report["resolution_rows"]
    assert rows_by_key["NEO4J_URI"]["處理類型"] == "本機可套用"
    assert "start_system.py --start-dependencies" in rows_by_key["NEO4J_URI"]["維護動作"]
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["處理類型"] == "需人工密鑰"
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["維護動作"] == (
        "手動補 .env 或 secret manager；不由維護操作寫入。"
    )


def test_external_deployment_env_gap_report_groups_resolution_plan() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )
    resolution_by_capability = {
        row["能力"]: row
        for row in report["resolution_rows"]
    }

    neo4j = resolution_by_capability["外部 Neo4j 匯入連線"]
    assert neo4j["處理策略"] == "可用本機維護操作"
    assert neo4j["本機可套用"] >= 1
    assert neo4j["需人工處理"] == 0
    assert "NEO4J_URI" in neo4j["設定鍵"]
    assert "start_system.py --start-dependencies" in neo4j["建議動作"]

    structured = resolution_by_capability["公司文件結構化 API 備援"]
    assert structured["處理策略"] == "需人工密鑰"
    assert structured["需人工密鑰"] == 1
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN" in structured["手動設定鍵"]
    assert "structured_company_filing_smoke.py" in structured["驗證指令"]


def test_external_deployment_env_gap_report_formats_text() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    output = external_deployment_env_gaps.format_external_deployment_env_gap_report(report)

    assert "External deployment env gaps: action_required" in output
    assert "Resolution plan:" in output
    assert "NEO4J_URI" in output
    assert "需人工密鑰" in output
    assert "structured_company_filing_smoke.py" in output


def test_external_deployment_env_gap_report_formats_safe_env_template() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    output = external_deployment_env_gaps.format_external_deployment_env_template(report)

    assert "External deployment env template" in output
    assert output.count("NEO4J_URI=") == 1
    assert "NEO4J_URI=neo4j://localhost:7687" in output
    assert f"# {NEO4J_PW_ENV}=<set-manually>" in output
    assert "# COMPANY_FILING_STRUCTURED_API_TOKEN=<set-manually>" in output
    assert "# COMPANY_FILING_STRUCTURED_API_PROVIDER=tej" in output
    assert "# COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>" in output
    assert "Do not commit real secrets" in output


def test_external_deployment_env_gap_report_formats_compose_env_template() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    output = external_deployment_env_gaps.format_external_deployment_env_template(
        report,
        target="compose",
    )

    assert "target=compose" in output
    assert "COMPOSE_NEO4J_URI=neo4j://neo4j:7687" in output
    assert "COMPOSE_NEO4J_USER=neo4j" in output
    assert f"# {COMPOSE_NEO4J_PW_ENV}=<set-manually>" in output
    assert "NEO4J_URI=neo4j://localhost:7687" not in output


def test_external_deployment_env_gap_report_checks_env_values_without_secrets() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    check = external_deployment_env_gaps.external_deployment_env_check_report(
        report,
        env_values={
            "NEO4J_URI": "neo4j://localhost:7687",
            NEO4J_PW_ENV: "real-secret",
            "COMPANY_FILING_STRUCTURED_API_PROVIDER": "custom",
        },
    )
    rows_by_key = {row["env_key"]: row for row in check["rows"]}

    assert check["status"] == "action_required"
    assert rows_by_key["NEO4J_URI"]["status"] == "matches"
    assert rows_by_key["NEO4J_URI"]["current_value"] == "neo4j://localhost:7687"
    assert rows_by_key[NEO4J_PW_ENV]["status"] == "set"
    assert rows_by_key[NEO4J_PW_ENV]["current_value"] == "<set>"
    assert rows_by_key[NEO4J_PW_ENV]["expected_value"] == "<set-manually>"
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_PROVIDER"]["status"] == "different"
    assert rows_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["status"] == "missing"
    assert "real-secret" not in str(check)

    placeholder_check = external_deployment_env_gaps.external_deployment_env_check_report(
        report,
        env_values={
            NEO4J_PW_ENV: "<set-manually>",
            "COMPANY_FILING_STRUCTURED_API_URL": "<provider-json-endpoint>",
        },
    )
    placeholder_rows_by_key = {
        row["env_key"]: row
        for row in placeholder_check["rows"]
    }

    assert placeholder_check["status"] == "action_required"
    assert placeholder_rows_by_key[NEO4J_PW_ENV]["status"] == "missing"
    assert placeholder_rows_by_key["COMPANY_FILING_STRUCTURED_API_URL"]["status"] == "missing"


def test_external_deployment_env_gap_report_checks_compose_env_keys() -> None:
    report = external_deployment_env_gaps.external_deployment_env_gap_report(
        upgrade_audit=_audit_with_env_gaps(),
        service_snapshot={},
    )

    check = external_deployment_env_gaps.external_deployment_env_check_report(
        report,
        target="compose",
        env_values={
            "COMPOSE_NEO4J_URI": "neo4j://neo4j:7687",
            "COMPOSE_NEO4J_USER": "neo4j",
        },
    )
    rows_by_key = {row["env_key"]: row for row in check["rows"]}

    assert "NEO4J_URI" not in rows_by_key
    assert rows_by_key["COMPOSE_NEO4J_URI"]["status"] == "matches"
    assert rows_by_key["COMPOSE_NEO4J_USER"]["status"] == "matches"
    assert rows_by_key[COMPOSE_NEO4J_PW_ENV]["status"] == "missing"


def test_external_deployment_env_gap_script_uses_service_layer() -> None:
    source = Path("scripts/external_deployment_env_gaps.py").read_text()

    assert "from app.services.external_deployment_env_gaps import (" in source
    assert "app.ui.external_deployment_env_keys" not in source


def test_external_deployment_env_gap_service_reuses_readiness_service() -> None:
    source = Path("app/services/external_deployment_env_gaps.py").read_text()
    template_source = Path("app/services/external_deployment_env_templates.py").read_text()

    assert "from app.services.external_deployment_readiness import (" in source
    assert "from app.services.external_deployment_env_templates import (" in source
    assert "EXTERNAL_READINESS_METADATA = {" not in source
    assert "def external_deployment_readiness_items(" not in source
    assert "def format_external_deployment_env_template(" in template_source
    assert "def external_deployment_env_check_report(" in template_source
    assert "def _external_env_template_secret_key(" in template_source
    assert "def _external_env_template_entries(" not in source


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


def test_external_deployment_env_gap_script_prints_env_template(monkeypatch, capsys) -> None:
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
            "rows": [
                {
                    "優先級": "P1",
                    "能力": "公司文件結構化 API 備援",
                    "設定鍵": "COMPANY_FILING_STRUCTURED_API_TOKEN",
                    "狀態": "缺少",
                    "建議值": "<token>",
                    "Compose 建議值": "<token>",
                    "處理類型": "需人工密鑰",
                }
            ],
        },
    )

    assert external_deployment_env_gaps.main(["--env-template"]) == 0
    output = capsys.readouterr().out
    assert "External deployment env template" in output
    assert "# COMPANY_FILING_STRUCTURED_API_TOKEN=<set-manually>" in output


def test_external_deployment_env_gap_script_prints_compose_env_template(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        external_deployment_env_gaps,
        "external_deployment_env_gap_report",
        lambda **_kwargs: {
            "status": "action_required",
            "gap_count": 1,
            "missing_count": 1,
            "recommended_count": 0,
            "manual_secret_count": 0,
            "local_action_count": 1,
            "rows": [
                {
                    "優先級": "P0",
                    "能力": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                    "設定鍵": "COMPANY_FILING_BROWSER_RENDER_URL",
                    "狀態": "缺少",
                    "建議值": "http://127.0.0.1:8191/v1",
                    "Compose 建議值": "http://flaresolverr:8191/v1",
                    "處理類型": "本機可套用",
                }
            ],
        },
    )

    assert external_deployment_env_gaps.main(
        ["--env-template", "--env-template-target", "compose"]
    ) == 0
    output = capsys.readouterr().out
    assert "target=compose" in output
    assert "COMPANY_FILING_BROWSER_RENDER_URL=http://flaresolverr:8191/v1" in output
    assert "http://127.0.0.1:8191/v1" not in output


def test_external_deployment_env_gap_script_prints_env_check(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "NEO4J_URI=neo4j://localhost:7687",
                f"{NEO4J_PW_ENV}=real-secret",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        external_deployment_env_gaps,
        "external_deployment_env_gap_report",
        lambda **_kwargs: {
            "status": "action_required",
            "gap_count": 2,
            "missing_count": 2,
            "recommended_count": 0,
            "manual_secret_count": 1,
            "local_action_count": 1,
            "rows": [
                {
                    "優先級": "P0",
                    "能力": "Neo4j",
                    "設定鍵": "NEO4J_URI",
                    "狀態": "缺少",
                    "建議值": "neo4j://localhost:7687",
                    "Compose 建議值": "neo4j://neo4j:7687",
                    "處理類型": "本機可套用",
                },
                {
                    "優先級": "P0",
                    "能力": "Neo4j",
                    "設定鍵": NEO4J_PW_ENV,
                    "狀態": "缺少",
                    "建議值": "<password>",
                    "Compose 建議值": "<password>",
                    "處理類型": "需人工密鑰",
                },
            ],
        },
    )

    assert external_deployment_env_gaps.main(
        ["--env-check", "--env-file", str(env_file)]
    ) == 0
    output = capsys.readouterr().out
    assert "External deployment env check: ready" in output
    assert "NEO4J_URI :: expected=neo4j://localhost:7687 current=neo4j://localhost:7687" in output
    assert f"{NEO4J_PW_ENV} :: expected=<set-manually> current=<set>" in output
    assert "real-secret" not in output

    assert external_deployment_env_gaps.main(
        ["--strict", "--env-check", "--env-file", str(tmp_path / "missing.env")]
    ) == 1
    strict_output = capsys.readouterr().out
    assert "External deployment env check: action_required" in strict_output


def test_external_deployment_env_gap_script_prints_all_target_env_check(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEO4J_URI=neo4j://localhost:7687", encoding="utf-8")

    def fake_status_report(**kwargs):
        assert kwargs["target"] == "all"
        assert kwargs["env_file"] == str(env_file)
        return {
            "status": "action_required",
            "target": "all",
            "targets": ["host", "compose"],
            "env_file": str(env_file),
            "gap_count": 1,
            "checks": {
                "host": {
                    "status": "ready",
                    "target": "host",
                    "env_file": str(env_file),
                    "env_file_exists": True,
                    "checked_count": 1,
                    "missing_count": 0,
                    "different_count": 0,
                    "rows": [
                        {
                            "status": "matches",
                            "env_key": "NEO4J_URI",
                            "expected_value": "neo4j://localhost:7687",
                            "current_value": "neo4j://localhost:7687",
                            "action": "-",
                        }
                    ],
                },
                "compose": {
                    "status": "action_required",
                    "target": "compose",
                    "env_file": str(env_file),
                    "env_file_exists": True,
                    "checked_count": 1,
                    "missing_count": 1,
                    "different_count": 0,
                    "rows": [
                        {
                            "status": "missing",
                            "env_key": "COMPOSE_NEO4J_URI",
                            "expected_value": "neo4j://neo4j:7687",
                            "current_value": "<unset>",
                            "action": "設定 COMPOSE_NEO4J_URI",
                        }
                    ],
                },
            },
        }

    monkeypatch.setattr(
        external_deployment_env_gaps,
        "external_deployment_env_check_status_report",
        fake_status_report,
    )

    assert external_deployment_env_gaps.main(
        ["--env-check", "--env-check-target", "all", "--env-file", str(env_file)]
    ) == 0
    output = capsys.readouterr().out
    assert "External deployment env check: action_required (target=all; gaps=1)" in output
    assert "[host] ready" in output
    assert "[compose] action_required" in output
    assert "COMPOSE_NEO4J_URI" in output
