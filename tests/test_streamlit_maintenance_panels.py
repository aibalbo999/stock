from __future__ import annotations

from pathlib import Path

from app.services import (
    external_deployment_enablement,
    external_deployment_items,
    external_deployment_local_dependencies,
)
from app.services.external_deployment_env_gaps import (
    external_deployment_env_check_status_report,
)
from app.services.external_deployment_readiness import (
    external_deployment_enablement_profile,
    external_deployment_item_ready,
    external_deployment_local_projection,
    external_deployment_readiness_items,
    external_smoke_commands_from_payload,
    local_dependency_last_start_rows,
    local_dependency_repair_rows,
    local_dependency_status_rows,
)
from app.ui.maintenance_deployment_panel import (
    external_deployment_effective_gap_rows,
    maintenance_operation_recommendation_caption,
    maintenance_operation_post_run_diagnostic_action_ids,
    maintenance_operation_post_run_check_rows,
    maintenance_operation_rows,
    recommended_maintenance_operation_id,
)
from app.ui.maintenance_task_panels import maintenance_diagnostic_action_rows
from app.ui.maintenance_task_panels import task_observability_expander_expanded
from app.ui.task_failure_diagnostics import (
    recommended_task_retry_option,
    task_retry_option_index,
)
from streamlit_ui_test_helpers import load_report_helpers


def test_external_deployment_item_logic_lives_outside_readiness_facade() -> None:
    readiness_source = Path("app/services/external_deployment_readiness.py").read_text()
    item_source = Path("app/services/external_deployment_items.py").read_text()
    enablement_source = Path("app/services/external_deployment_enablement.py").read_text()
    local_dependency_source = Path(
        "app/services/external_deployment_local_dependencies.py"
    ).read_text()
    audit = {
        "checks": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "external_integration": True,
                "deployment_check": True,
                "severity": "pass",
                "status": "ready",
            },
            {"capability": "internal_only", "external_integration": False},
        ],
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "external_integration": True,
                "deployment_check": True,
                "severity": "warn",
                "optional": True,
                "evidence": {"unlocker_provider_ready": True},
            }
        ],
    }

    assert external_deployment_items.external_deployment_item_ready is external_deployment_item_ready
    assert (
        external_deployment_enablement.external_deployment_enablement_profile
        is external_deployment_enablement_profile
    )
    assert (
        external_deployment_enablement.external_deployment_local_projection
        is external_deployment_local_projection
    )
    assert (
        external_deployment_local_dependencies.local_dependency_status_rows
        is local_dependency_status_rows
    )
    assert (
        external_deployment_local_dependencies.local_dependency_last_start_rows
        is local_dependency_last_start_rows
    )
    assert (
        external_deployment_local_dependencies.local_dependency_repair_rows
        is local_dependency_repair_rows
    )
    assert [item["capability"] for item in external_deployment_readiness_items(audit)] == [
        "company_filing_high_risk_unlocker",
        "neo4j_import",
    ]
    assert external_deployment_item_ready(audit["optional_warnings"][0]) is True
    assert external_smoke_commands_from_payload(
        {"nested": {"smoke_cli": "cmd-a"}, "rows": [{"verify_smoke_command": "cmd-b"}]}
    ) == ["cmd-a", "cmd-b"]
    assert "def external_deployment_readiness_items(" not in readiness_source
    assert "def external_deployment_readiness_items(" in item_source
    assert "def _external_readiness_item_ready(" not in readiness_source
    assert "def _external_readiness_item_ready(" in item_source
    assert "def collect_external_smoke_commands(" not in readiness_source
    assert "def collect_external_smoke_commands(" in item_source
    assert "def external_deployment_enablement_profile(" not in readiness_source
    assert "def external_deployment_enablement_profile(" in enablement_source
    assert "def external_deployment_local_projection(" not in readiness_source
    assert "def external_deployment_local_projection(" in enablement_source
    assert "def local_dependency_status_rows(" not in readiness_source
    assert "def local_dependency_status_rows(" in local_dependency_source
    assert "def local_dependency_last_start_rows(" not in readiness_source
    assert "def local_dependency_last_start_rows(" in local_dependency_source
    assert "def local_dependency_repair_rows(" not in readiness_source
    assert "def local_dependency_repair_rows(" in local_dependency_source


def test_maintenance_service_metrics_show_promotion_threshold() -> None:
    helpers = load_report_helpers()

    metrics = helpers["maintenance_service_metrics"](
        {"integrity": {"ok": True}},
        {
            "redis": {"ok": True},
            "task_queue": {"ready": True},
            "gemini": {"key_count": 5},
            "finmind": {"mode": "public_or_limited"},
            "candidate_confidence": {"high_threshold": 75},
        },
    )

    assert metrics["資料庫"] == "正常"
    assert metrics["Redis"] == "正常"
    assert metrics["背景任務"] == "可送出"
    assert metrics["AI Key"] == 5
    assert metrics["市場資料"] == "可用"
    assert metrics["升格門檻"] == "高 75"


def test_submission_guard_summary_rows_show_operator_ready_and_missing() -> None:
    from app.ui import maintenance_panels

    service_snapshot = {
        "frontend": {
            "ui_risky_submission_guard_ready_count": 1,
            "ui_risky_submission_guard_total_count": 2,
            "ui_risky_submission_guard_missing": ["run_delete"],
            "ui_risky_submission_guard_rows": [
                {
                    "id": "analysis_submission",
                    "surface": "analysis_workspace",
                    "guard_key": "ui_analysis_submission_quota_confirmation_enabled",
                    "ready": True,
                },
                {
                    "id": "run_delete",
                    "surface": "report_center",
                    "guard_key": "ui_run_delete_confirmation_gate_enabled",
                    "ready": False,
                },
            ],
        }
    }

    assert maintenance_panels.submission_guard_metric_values(service_snapshot) == {
        "狀態": "missing",
        "完成": "1/2",
        "缺口": 1,
    }
    assert maintenance_panels.submission_guard_rows(service_snapshot) == [
        {
            "操作": "送出分析任務",
            "區域": "分析工作區",
            "狀態": "protected",
            "Evidence": "ui_analysis_submission_quota_confirmation_enabled",
        },
        {
            "操作": "刪除分析紀錄",
            "區域": "報告中心",
            "狀態": "missing",
            "Evidence": "ui_run_delete_confirmation_gate_enabled",
        },
    ]


def test_submission_guard_summary_handles_missing_frontend_snapshot() -> None:
    from app.ui import maintenance_panels

    assert maintenance_panels.submission_guard_metric_values({}) == {
        "狀態": "unknown",
        "完成": "0/0",
        "缺口": 0,
    }
    assert maintenance_panels.submission_guard_rows({}) == []


def test_maintenance_operation_recommendation_prefers_unlocker_when_plan_needs_it() -> None:
    catalog = {
        "operations": [
            {
                "id": "start_local_dependencies",
                "label": "啟動本機核心依賴",
                "display_command": "docker compose up -d redis neo4j browserless",
                "mutates_local_state": True,
            },
            {
                "id": "start_local_dependencies_with_unlocker",
                "label": "啟動本機依賴與 unlocker",
                "display_command": "docker compose --profile unlocker up -d flaresolverr",
                "mutates_local_state": True,
            },
        ]
    }
    resolution_rows = [
        {
            "能力": "MOPS/TWSE/TPEx 高風險文件 unlocker",
            "本機可套用": 2,
            "本機指令": (
                ".venv/bin/python scripts/start_system.py "
                "--start-dependencies --prefer-unlocker"
            ),
        }
    ]

    recommended = recommended_maintenance_operation_id(catalog, resolution_rows)

    assert recommended == "start_local_dependencies_with_unlocker"
    assert maintenance_operation_recommendation_caption(catalog, recommended) == (
        "建議操作：啟動本機依賴與 unlocker；會預選此操作，確認後才會執行。"
        "指令：docker compose --profile unlocker up -d flaresolverr"
    )


def test_maintenance_operation_recommendation_uses_projection_before_env_rows() -> None:
    catalog = {
        "operations": [
            {
                "id": "start_local_dependencies",
                "label": "啟動本機核心依賴",
                "display_command": "docker compose up -d redis neo4j browserless",
                "mutates_local_state": True,
            },
            {
                "id": "start_local_dependencies_with_unlocker",
                "label": "啟動本機依賴與 unlocker",
                "display_command": "docker compose --profile unlocker up -d flaresolverr",
                "mutates_local_state": True,
            },
        ]
    }

    assert (
        recommended_maintenance_operation_id(
            catalog,
            [],
            {
                "local_action_capabilities": [
                    "neo4j_import",
                    "graphrag_live_cypher_query",
                    "company_filing_high_risk_unlocker",
                ]
            },
        )
        == "start_local_dependencies_with_unlocker"
    )
    assert (
        recommended_maintenance_operation_id(
            catalog,
            [],
            {"local_action_capabilities": ["neo4j_import"]},
        )
        == "start_local_dependencies"
    )
    assert (
        recommended_maintenance_operation_id(
            catalog,
            [],
            {
                "local_default_capabilities": [
                    {"capability": "neo4j_import"},
                    {"capability": "company_filing_high_risk_unlocker"},
                ]
            },
        )
        == "start_local_dependencies_with_unlocker"
    )


def test_external_deployment_effective_gap_rows_show_effective_remaining_gap() -> None:
    rows = external_deployment_effective_gap_rows(
        {
            "current_pending": 4,
            "available_local_default_gap_count": 3,
            "remaining_pending": 1,
            "remaining_blocking_pending": 0,
            "remaining_optional_pending": 1,
            "remaining_paid_external_pending": 1,
            "local_default_capabilities": [
                {"capability": "neo4j_import", "label": "外部 Neo4j 匯入連線"},
                {
                    "capability": "company_filing_high_risk_unlocker",
                    "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                },
            ],
            "remaining_capabilities": [
                {
                    "capability": "company_filing_structured_api_fallback",
                    "label": "公司文件結構化 API 備援",
                }
            ],
            "local_default_verify_commands": [
                ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
            ],
        }
    )

    assert rows[0] == {
        "項目": "原始外部選配",
        "數量": 4,
        "說明": "尚未扣除已偵測本機 defaults",
    }
    assert rows[1]["項目"] == "本機 defaults 可處理"
    assert rows[1]["數量"] == 3
    assert "外部 Neo4j 匯入連線" in rows[1]["說明"]
    assert "高風險文件 unlocker" in rows[1]["說明"]
    assert rows[2] == {
        "項目": "有效剩餘",
        "數量": 1,
        "說明": "公司文件結構化 API 備援",
    }
    assert rows[3]["數量"] == 0
    assert rows[4]["數量"] == 1
    assert rows[5] == {
        "項目": "付費外部 API",
        "數量": 1,
        "說明": "公司文件結構化 API 備援",
    }
    assert rows[6]["項目"] == "本機驗證指令"
    assert "--auto-local-defaults" in rows[6]["說明"]


def test_maintenance_operation_recommendation_uses_core_dependencies_for_local_plan() -> None:
    catalog = {
        "operations": [
            {
                "id": "start_local_dependencies",
                "label": "啟動本機核心依賴",
                "display_command": "docker compose up -d redis neo4j browserless",
                "mutates_local_state": True,
            },
            {
                "id": "start_local_dependencies_with_unlocker",
                "label": "啟動本機依賴與 unlocker",
                "display_command": "docker compose --profile unlocker up -d flaresolverr",
                "mutates_local_state": True,
            },
        ]
    }

    assert (
        recommended_maintenance_operation_id(
            catalog,
            [
                {
                    "能力": "外部 Neo4j 匯入連線",
                    "本機可套用": 4,
                    "本機指令": ".venv/bin/python scripts/start_system.py --start-dependencies",
                }
            ],
        )
        == "start_local_dependencies"
    )
    assert recommended_maintenance_operation_id(catalog, [{"本機可套用": 0}]) == ""


def test_maintenance_operation_post_run_check_rows_surface_verify_commands() -> None:
    rows = maintenance_operation_post_run_check_rows(
        {
            "post_run_checks": [
                {
                    "item": "GraphRAG live Neo4j smoke",
                    "purpose": "驗證 live query",
                    "diagnostic_action_id": "graphrag_live_query_smoke",
                    "command": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                },
                {
                    "item": "高風險 MOPS unlocker smoke",
                    "purpose": "驗證 MOPS unlocker",
                    "diagnostic_action_id": "high_risk_unlocker_smoke",
                    "command": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--local-browser-render-defaults --prefer-unlocker "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
            ]
        }
    )

    assert rows == [
        {
            "項目": "GraphRAG live Neo4j smoke",
            "用途": "驗證 live query",
            "可執行診斷": "graphrag_live_query_smoke",
            "指令": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
        },
        {
            "項目": "高風險 MOPS unlocker smoke",
            "用途": "驗證 MOPS unlocker",
            "可執行診斷": "high_risk_unlocker_smoke",
            "指令": (
                ".venv/bin/python scripts/company_filing_render_smoke.py "
                "--local-browser-render-defaults --prefer-unlocker "
                "--url https://mops.twse.com.tw/ --json"
            ),
        },
    ]
    assert maintenance_operation_post_run_diagnostic_action_ids(
        [
            rows[0],
            {**rows[0]},
            {"可執行診斷": "-"},
            rows[1],
            {"可執行診斷": ""},
        ]
    ) == ["graphrag_live_query_smoke", "high_risk_unlocker_smoke"]


def test_maintenance_service_metrics_show_worker_queue_warning_label() -> None:
    helpers = load_report_helpers()

    metrics = helpers["maintenance_service_metrics"](
        {"integrity": {"ok": True}},
        {
            "redis": {"ok": True},
            "task_queue": {"ready": True, "worker_ping_checked": True, "worker_online": False},
            "gemini": {"key_count": 5},
            "finmind": {"mode": "public_or_limited"},
            "candidate_confidence": {"high_threshold": 75},
        },
    )

    assert metrics["背景任務"] == "可排隊"


def test_task_queue_health_rows_show_worker_nodes_and_smoke_command() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": True,
            "broker_configured": True,
            "broker_ok": True,
            "backend_ok": True,
            "broker_url": "redis://localhost:6379/0",
            "backend_url": "redis://localhost:6379/0",
            "submission_contract_ready": True,
            "processing_ready": True,
            "worker_ping_checked": True,
            "worker_online": True,
            "worker_count": 1,
            "worker_nodes": ["celery@test.local"],
            "smoke_commands": [".venv/bin/python -m celery inspect ping"],
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)
    repair_rows = helpers["task_queue_repair_rows"](snapshot)

    assert rows[0]["項目"] == "Queue 提交"
    assert rows[0]["狀態"] == "可送出"
    assert rows[1]["項目"] == "Queue 執行"
    assert rows[1]["狀態"] == "可執行"
    assert "worker 可接手執行" in rows[1]["說明"]
    assert rows[5]["項目"] == "Celery Worker"
    assert rows[5]["狀態"] == "在線"
    assert "celery@test.local" in rows[5]["說明"]
    assert alert == {
        "severity": "success",
        "message": "Queue 與 Celery worker 可用；目前 1 個 worker 節點回應。",
    }
    assert (
        helpers["task_queue_smoke_command"](snapshot) == ".venv/bin/python -m celery inspect ping"
    )
    assert repair_rows == []


def test_task_queue_health_alert_warns_when_worker_is_offline_but_queue_can_submit() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": True,
            "broker_configured": True,
            "broker_ok": True,
            "backend_ok": True,
            "submission_contract_ready": True,
            "processing_ready": False,
            "worker_ping_checked": True,
            "worker_online": False,
            "worker_count": 0,
            "worker_nodes": [],
            "worker_ping_timeout_seconds": 1.0,
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)
    repair_rows = helpers["task_queue_repair_rows"](snapshot)

    assert rows[0]["狀態"] == "可排隊"
    assert "worker 未回應" in rows[0]["說明"]
    assert rows[1]["項目"] == "Queue 執行"
    assert rows[1]["狀態"] == "等待 worker"
    assert "停在佇列直到 worker 上線" in rows[1]["說明"]
    assert rows[5]["狀態"] == "未回應"
    assert "timeout 1.0s" in rows[5]["說明"]
    assert alert["severity"] == "warning"
    assert "Celery worker 未回應" in alert["message"]
    assert repair_rows == [
        {
            "項目": "Celery Worker",
            "狀態": "未回應",
            "下一步": "啟動 worker，或確認既有 worker 能連到同一個 Redis broker。",
            "修復指令": (
                ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker "
                "-B --loglevel=INFO --pool=solo"
            ),
            "驗證指令": ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping",
        }
    ]


def test_task_queue_health_alert_blocks_unready_queue() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "ready": False,
            "broker_configured": True,
            "broker_ok": False,
            "backend_ok": False,
            "submission_contract_ready": True,
            "processing_ready": False,
            "redis_error": "connection refused",
            "broker_url": "redis://localhost:6379/0",
            "backend_url": "redis://localhost:6379/0",
        }
    }

    rows = helpers["task_queue_health_rows"](snapshot)
    alert = helpers["task_queue_health_alert"](snapshot)
    repair_rows = helpers["task_queue_repair_rows"](snapshot)

    assert rows[0]["狀態"] == "檢查"
    assert "Redis broker 未連線" in rows[0]["說明"]
    assert rows[1]["項目"] == "Queue 執行"
    assert rows[1]["狀態"] == "檢查"
    assert "Queue 尚不可提交" in rows[1]["說明"]
    assert "connection refused" in rows[2]["說明"]
    assert alert["severity"] == "error"
    assert "背景任務 queue 尚不可送出" in alert["message"]
    assert repair_rows == [
        {
            "項目": "Redis Broker/Backend",
            "狀態": "未連線",
            "下一步": "啟動本機依賴後重新檢查 Redis broker/backend 連線。",
            "修復指令": ".venv/bin/python scripts/start_system.py --start-dependencies",
            "驗證指令": ".venv/bin/python scripts/upgrade_audit.py",
        }
    ]


def test_task_queue_repair_rows_prefer_status_payload() -> None:
    helpers = load_report_helpers()
    snapshot = {
        "task_queue": {
            "repair_plan": [
                {
                    "item": "Custom repair",
                    "state": "needs_action",
                    "next_step": "Run the allowlisted diagnostic.",
                    "repair_command": ".venv/bin/python scripts/upgrade_audit.py",
                    "verify_command": ".venv/bin/python scripts/upgrade_audit.py --json",
                    "severity": "warning",
                }
            ],
        }
    }

    assert helpers["task_queue_repair_rows"](snapshot) == [
        {
            "項目": "Custom repair",
            "狀態": "needs_action",
            "下一步": "Run the allowlisted diagnostic.",
            "修復指令": ".venv/bin/python scripts/upgrade_audit.py",
            "驗證指令": ".venv/bin/python scripts/upgrade_audit.py --json",
        }
    ]


def test_maintenance_diagnostic_action_rows_surface_allowlisted_actions() -> None:
    rows = maintenance_diagnostic_action_rows(
        {
            "actions": [
                {
                    "id": "upgrade_audit",
                    "label": "Upgrade audit",
                    "description": "檢查核心升級能力與外部部署選配狀態。",
                    "display_command": ".venv/bin/python scripts/upgrade_audit.py",
                    "timeout_seconds": 90,
                    "read_only": True,
                    "effect": "read_only",
                    "safe_to_run": True,
                },
                {
                    "id": "task_submission_noop_smoke",
                    "label": "Task submission no-op",
                    "description": "送出 smoke=true 的 no-op market_refresh。",
                    "display_command": ".venv/bin/python scripts/task_submission_smoke.py --submit --wait --json",
                    "timeout_seconds": 45,
                    "read_only": False,
                    "effect": "safe_noop_task_submission",
                    "safe_to_run": True,
                },
                {
                    "id": "graphrag_import_first_smoke",
                    "label": "GraphRAG import-first smoke",
                    "description": "匯入 bundled graph payload 後驗證 live Cypher。",
                    "display_command": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
                    "timeout_seconds": 120,
                    "read_only": False,
                    "effect": "safe_local_neo4j_import_smoke",
                    "safe_to_run": True,
                },
                {
                    "id": "unsafe_action",
                    "label": "Unsafe action",
                    "description": "",
                    "display_command": "",
                    "timeout_seconds": 0,
                    "read_only": False,
                },
            ]
        }
    )

    assert rows == [
        {
            "動作": "Upgrade audit",
            "狀態": "只讀可執行",
            "效果": "read_only",
            "說明": "檢查核心升級能力與外部部署選配狀態。",
            "指令": ".venv/bin/python scripts/upgrade_audit.py",
            "Timeout": 90,
        },
        {
            "動作": "Task submission no-op",
            "狀態": "安全 no-op",
            "效果": "safe_noop_task_submission",
            "說明": "送出 smoke=true 的 no-op market_refresh。",
            "指令": ".venv/bin/python scripts/task_submission_smoke.py --submit --wait --json",
            "Timeout": 45,
        },
        {
            "動作": "GraphRAG import-first smoke",
            "狀態": "本機 Neo4j smoke",
            "效果": "safe_local_neo4j_import_smoke",
            "說明": "匯入 bundled graph payload 後驗證 live Cypher。",
            "指令": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
            "Timeout": 120,
        },
        {
            "動作": "Unsafe action",
            "狀態": "停用",
            "效果": "-",
            "說明": "-",
            "指令": "-",
            "Timeout": 0,
        },
    ]


def test_maintenance_diagnostic_actions_require_confirmation_before_submit(monkeypatch) -> None:
    from app.ui import maintenance_task_panels

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.buttons: list[dict] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict] = []
            self.dataframes: list[list[dict]] = []
            self.selectboxes: list[dict] = []

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def dataframe(self, rows, **_kwargs) -> None:
            self.dataframes.append(list(rows))

        def selectbox(self, label, options, *, format_func, key):
            selected = options[0]
            self.selectboxes.append(
                {
                    "label": label,
                    "options": list(options),
                    "key": key,
                    "selected_label": format_func(selected),
                }
            )
            return selected

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return kwargs.get("key") == "maintenance_run_diagnostic_action" and not kwargs.get(
                "disabled"
            )

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []
    monkeypatch.setattr(maintenance_task_panels, "st", fake_st)
    monkeypatch.setattr(
        maintenance_task_panels,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    maintenance_task_panels._render_maintenance_diagnostic_actions(
        {
            "actions": [
                {
                    "id": "upgrade_audit",
                    "label": "Upgrade audit",
                    "description": "檢查核心升級能力與外部部署選配狀態。",
                    "display_command": ".venv/bin/python scripts/upgrade_audit.py",
                    "timeout_seconds": 90,
                    "read_only": True,
                    "effect": "read_only",
                    "safe_to_run": True,
                }
            ]
        }
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出維護診斷背景任務",
            "value": False,
            "key": "maintenance_diagnostic_confirm_upgrade_audit",
        }
    ]
    assert fake_st.buttons == [
        {
            "label": "執行診斷",
            "key": "maintenance_run_diagnostic_action",
            "disabled": True,
        }
    ]
    assert any("避免誤觸診斷" in caption for caption in fake_st.captions)
    assert submitted == []


def test_maintenance_diagnostic_actions_submit_after_confirmation(monkeypatch) -> None:
    from app.ui import maintenance_task_panels

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.buttons: list[dict] = []
            self.checkboxes: list[dict] = []

        def caption(self, _body: str) -> None:
            return None

        def dataframe(self, _rows, **_kwargs) -> None:
            return None

        def selectbox(self, _label, options, *, format_func, key):
            assert key == "maintenance_diagnostic_action_select"
            assert format_func(options[0]) == "Task submission no-op"
            return options[0]

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return key == "maintenance_diagnostic_confirm_task_submission_noop_smoke"

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return kwargs.get("key") == "maintenance_run_diagnostic_action" and not kwargs.get(
                "disabled"
            )

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []
    monkeypatch.setattr(maintenance_task_panels, "st", fake_st)
    monkeypatch.setattr(
        maintenance_task_panels,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    maintenance_task_panels._render_maintenance_diagnostic_actions(
        {
            "actions": [
                {
                    "id": "task_submission_noop_smoke",
                    "label": "Task submission no-op",
                    "description": "送出 smoke=true 的 no-op market_refresh。",
                    "display_command": ".venv/bin/python scripts/task_submission_smoke.py",
                    "timeout_seconds": 45,
                    "read_only": False,
                    "effect": "safe_noop_task_submission",
                    "safe_to_run": True,
                }
            ]
        }
    )

    assert fake_st.buttons == [
        {
            "label": "執行診斷",
            "key": "maintenance_run_diagnostic_action",
            "disabled": False,
        }
    ]
    assert submitted == [
        (
            ("/tasks/maintenance-diagnostic/task_submission_noop_smoke", {}),
            {
                "task_state_key": "last_maintenance_diagnostic_task_id",
                "status_state_keys": ("refresh_maintenance_diagnostic_action_status_status",),
                "success_message": "已送出維護診斷背景任務",
                "error_message": "診斷執行失敗",
                "task_type_state_key": "last_maintenance_diagnostic_action_type",
                "task_type": "task_submission_noop_smoke",
            },
        )
    ]


def test_maintenance_operation_rows_surface_confirmed_local_dependency_operations() -> None:
    rows = maintenance_operation_rows(
        {
            "operations": [
                {
                    "id": "start_local_dependencies",
                    "label": "啟動本機核心依賴",
                    "description": "啟動 Redis、Postgres、Neo4j、Browserless 與 Chroma。",
                    "display_command": "docker compose up -d redis postgres neo4j browserless chroma",
                    "timeout_seconds": 240,
                    "requires_confirmation": True,
                    "mutates_local_state": True,
                    "scope": "Docker services and current API process env defaults",
                    "resolves_capabilities": [
                        {
                            "capability": "neo4j_import",
                            "label": "外部 Neo4j 匯入連線",
                        }
                    ],
                },
                {
                    "id": "inspect_only",
                    "label": "Inspect only",
                    "description": "",
                    "display_command": "",
                    "timeout_seconds": 0,
                    "requires_confirmation": False,
                    "mutates_local_state": False,
                    "scope": "",
                },
            ]
        }
    )

    assert rows == [
        {
            "操作": "啟動本機核心依賴",
            "狀態": "需確認",
            "作用範圍": "Docker services and current API process env defaults",
            "可處理能力": "外部 Neo4j 匯入連線",
            "說明": "啟動 Redis、Postgres、Neo4j、Browserless 與 Chroma。",
            "指令": "docker compose up -d redis postgres neo4j browserless chroma",
            "Timeout": 240,
        },
        {
            "操作": "Inspect only",
            "狀態": "可執行",
            "作用範圍": "-",
            "可處理能力": "-",
            "說明": "-",
            "指令": "-",
            "Timeout": 0,
        },
    ]


def test_post_run_diagnostic_actions_require_confirmation_before_submit(monkeypatch) -> None:
    from app.ui import maintenance_deployment_panel

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.buttons: list[dict] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict] = []

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return kwargs.get("key") == "maintenance_post_run_diagnostic_upgrade_audit" and not (
                kwargs.get("disabled")
            )

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []
    monkeypatch.setattr(maintenance_deployment_panel, "st", fake_st)
    monkeypatch.setattr(
        maintenance_deployment_panel,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    maintenance_deployment_panel._render_post_run_diagnostic_actions(
        [{"可執行診斷": "upgrade_audit"}]
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出後續診斷背景任務",
            "value": False,
            "key": "maintenance_post_run_diagnostic_confirm_upgrade_audit",
        }
    ]
    assert fake_st.buttons == [
        {
            "label": "執行 upgrade_audit",
            "key": "maintenance_post_run_diagnostic_upgrade_audit",
            "disabled": True,
        }
    ]
    assert any("避免誤觸後續診斷" in caption for caption in fake_st.captions)
    assert submitted == []


def test_post_run_diagnostic_actions_submit_after_confirmation(monkeypatch) -> None:
    from app.ui import maintenance_deployment_panel

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.buttons: list[dict] = []
            self.checkboxes: list[dict] = []

        def caption(self, _body: str) -> None:
            return None

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return key == "maintenance_post_run_diagnostic_confirm_upgrade_audit"

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return kwargs.get("key") == "maintenance_post_run_diagnostic_upgrade_audit" and not (
                kwargs.get("disabled")
            )

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []
    monkeypatch.setattr(maintenance_deployment_panel, "st", fake_st)
    monkeypatch.setattr(
        maintenance_deployment_panel,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    maintenance_deployment_panel._render_post_run_diagnostic_actions(
        [{"可執行診斷": "upgrade_audit"}]
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出後續診斷背景任務",
            "value": False,
            "key": "maintenance_post_run_diagnostic_confirm_upgrade_audit",
        }
    ]
    assert fake_st.buttons == [
        {
            "label": "執行 upgrade_audit",
            "key": "maintenance_post_run_diagnostic_upgrade_audit",
            "disabled": False,
        }
    ]
    assert submitted == [
        (
            ("/tasks/maintenance-diagnostic/upgrade_audit", {}),
            {
                "task_state_key": "last_post_run_diagnostic_task_id",
                "status_state_keys": ("refresh_maintenance_diagnostic_task_status_status",),
                "success_message": "已送出後續診斷背景任務",
                "error_message": "後續診斷執行失敗",
                "task_type_state_key": "last_post_run_diagnostic_type",
                "task_type": "upgrade_audit",
            },
        )
    ]


def test_task_failure_drilldown_rows_and_retry_options_are_actionable() -> None:
    helpers = load_report_helpers()
    task_summary = {
        "recent_failures": [
            {
                "id": 22,
                "operation": "report_generation",
                "status": "failed",
                "task_id": "task-failed",
                "retryable": True,
                "retry_kind": "report_generation",
                "error_category": "quota",
                "error_severity": "warning",
                "error_summary": "模型/API 額度或速率限制",
                "next_steps": [
                    "查看 AI 額度與模型路由或資料源額度。",
                    "等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。",
                ],
                "retry_endpoint": "POST /tasks/task-failed/retry",
                "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry",
                "error": "quota exhausted",
                "started_at": "2026-06-07T10:00:00",
            },
            {
                "id": 23,
                "operation": "after_close_report_update",
                "status": "failed",
                "task_id": "task-after-close",
                "retryable": False,
                "retry_kind": None,
                "next_action": "payload 不支援自動重試；請依錯誤內容手動重新送出。",
                "error": "missing target",
                "started_at": "2026-06-07T11:00:00",
            },
            {
                "id": 24,
                "operation": "data_operation",
                "status": "failed",
                "task_id": "task-queue",
                "retryable": False,
                "retry_kind": None,
                "error_category": "task_queue",
                "error_severity": "error",
                "error_summary": "Redis/Celery queue 或 worker 異常",
                "next_steps": [
                    "確認 /services/status 的 task_queue.ready 與 worker_online。",
                    "執行 Celery inspect ping 或重新啟動 Redis/Celery worker。",
                ],
                "error": "worker offline",
                "started_at": "2026-06-07T12:00:00",
            },
            {
                "id": 25,
                "operation": "company_filings_fetch",
                "status": "failed",
                "task_id": "task-filing",
                "retryable": True,
                "retry_kind": "data_operation",
                "error_category": "data_source",
                "error_severity": "warning",
                "error_summary": "市場資料、公司文件或新聞來源異常",
                "next_steps": [
                    "檢查資料源 token、日期範圍與 company filing 後援設定。",
                    "可先重刷快取或降低本次資料補強範圍。",
                ],
                "retry_endpoint": "POST /tasks/task-filing/retry",
                "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-filing/retry",
                "error": "MOPS blocked",
                "started_at": "2026-06-07T13:00:00",
            },
            {
                "id": 26,
                "operation": "company_filings_fetch",
                "status": "failed",
                "task_id": "task-structured-api",
                "retryable": True,
                "retry_kind": "data_operation",
                "error_category": "external_config",
                "error_severity": "warning",
                "error_summary": "外部資料源或文件後援配置缺失",
                "next_steps": [
                    "查看 /services/status 與外部部署 readiness checklist，確認缺少的 env key。",
                    "補齊結構化文件 API、Browser render/unlocker、Visual RAG gateway 或 Neo4j 設定後再重送任務。",
                ],
                "retry_endpoint": "POST /tasks/task-structured-api/retry",
                "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-structured-api/retry",
                "error": "structured_api_configuration: missing_structured_api_token",
                "started_at": "2026-06-07T14:00:00",
            },
            {
                "id": 27,
                "operation": "after_close_report_update",
                "status": "failed",
                "task_id": "task-vector",
                "retryable": False,
                "retry_kind": None,
                "error_category": "vector_store",
                "error_severity": "warning",
                "error_summary": "RAG/Chroma 向量庫或 embedding 相容性異常",
                "next_steps": [
                    "確認 RAG embedding 模型、Chroma client/server 版本與向量庫連線狀態。",
                    "若任務已降級為關鍵字檢索仍可繼續；修復 embedding 後重新補索引或重送任務。",
                ],
                "error": "Inconsistent number of IDs, embeddings, documents, URIs and metadatas",
                "started_at": "2026-06-07T15:00:00",
            },
            {
                "id": 28,
                "operation": "after_close_report_update",
                "status": "failed",
                "task_id": "task-storage",
                "retryable": False,
                "retry_kind": None,
                "error_category": "runtime_storage",
                "error_severity": "error",
                "error_summary": "本機檔案或資料庫儲存異常",
                "next_steps": [
                    "確認 report_dir、SQLite/資料庫檔案與備份目錄存在且目前程序有讀寫權限。",
                    "若剛重啟過 Redis/Celery/API，重新啟動服務並重送任務以取得新的完整 traceback。",
                ],
                "error": "[Errno 2] No such file or directory",
                "started_at": "2026-06-07T16:00:00",
            },
        ]
    }

    rows = helpers["task_failure_drilldown_rows"](task_summary)
    action_rows = helpers["task_failure_action_route_rows"](task_summary)
    options = helpers["task_retry_options"](task_summary)

    assert rows[0]["run_id"] == 22
    assert rows[0]["category"] == "quota"
    assert rows[0]["severity"] == "warning"
    assert rows[0]["summary"] == "模型/API 額度或速率限制"
    assert (
        rows[0]["next_steps"]
        == "查看 AI 額度與模型路由或資料源額度。；等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。"
    )
    assert rows[0]["retry"] == "可重試"
    assert rows[0]["retry_kind"] == "report_generation"
    assert rows[0]["action_route"] == "一鍵重試"
    assert "維護頁直接重試" in rows[0]["action_route_detail"]
    assert rows[0]["next_action"] == "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry"
    assert rows[1]["retry"] == "需人工"
    assert rows[1]["retry_kind"] == "-"
    assert rows[1]["action_route"] == "需人工處理"
    assert rows[1]["next_steps"] == "-"
    assert rows[2]["action_route"] == "外部配置缺失"
    assert "Redis/Celery" in rows[2]["action_route_detail"]
    assert rows[3]["retry"] == "可重試"
    assert rows[3]["action_route"] == "外部配置缺失"
    assert rows[4]["category"] == "external_config"
    assert rows[4]["action_route"] == "外部配置缺失"
    assert "外部部署 readiness" in rows[4]["next_steps"]
    assert rows[5]["category"] == "vector_store"
    assert rows[5]["action_route"] == "需人工處理"
    assert "Chroma client/server" in rows[5]["action_route_detail"]
    assert rows[6]["category"] == "runtime_storage"
    assert rows[6]["action_route"] == "需人工處理"
    assert "SQLite" in rows[6]["action_route_detail"]
    assert action_rows == [
        {
            "處理路徑": "一鍵重試",
            "數量": 1,
            "說明": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
            "代表任務": "report_generation｜task-failed",
        },
        {
            "處理路徑": "外部配置缺失",
            "數量": 3,
            "說明": "先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
            "代表任務": "data_operation｜task-queue；company_filings_fetch｜task-filing；company_filings_fetch｜task-structured-api",
        },
        {
            "處理路徑": "需人工處理",
            "數量": 3,
            "說明": "payload、輸入範圍、向量庫/本機儲存或取消狀態需人工檢查，修正後從原工作流程重送。",
            "代表任務": "after_close_report_update｜task-after-close；after_close_report_update｜task-vector；after_close_report_update｜task-storage",
        },
    ]
    assert options == [
        {
            "task_id": "task-failed",
            "label": "report_generation｜run #22｜task-failed",
            "operation": "report_generation",
            "run_id": 22,
            "retry_endpoint": "POST /tasks/task-failed/retry",
            "action_route": "一鍵重試",
            "action_route_detail": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
            "retry_guarded": False,
            "retry_guard_message": "",
        },
        {
            "task_id": "task-filing",
            "label": "company_filings_fetch｜run #25｜task-filing",
            "operation": "company_filings_fetch",
            "run_id": 25,
            "retry_endpoint": "POST /tasks/task-filing/retry",
            "action_route": "外部配置缺失",
            "action_route_detail": "先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
            "retry_guarded": True,
            "retry_guard_message": "先修配置再重試：先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
        },
        {
            "task_id": "task-structured-api",
            "label": "company_filings_fetch｜run #26｜task-structured-api",
            "operation": "company_filings_fetch",
            "run_id": 26,
            "retry_endpoint": "POST /tasks/task-structured-api/retry",
            "action_route": "外部配置缺失",
            "action_route_detail": "先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
            "retry_guarded": True,
            "retry_guard_message": "先修配置再重試：先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
        },
    ]


def test_task_observability_expander_opens_when_operator_action_is_needed() -> None:
    assert task_observability_expander_expanded(
        {"recent_failures": [{"task_id": "task-1", "retryable": True}]}
    ) is True
    assert task_observability_expander_expanded(
        {"alerts": [{"severity": "warning", "message": "quota"}]}
    ) is True
    assert task_observability_expander_expanded(
        {"totals": {"failed_count": 1, "stale_running_count": 0}}
    ) is True
    assert task_observability_expander_expanded(
        {"totals": {"failed_count": 0, "stale_running_count": 0}, "recent_failures": []}
    ) is False


def test_recommended_task_retry_option_prefers_safe_inspected_task() -> None:
    retry_options = [
        {
            "task_id": "task-safe-old",
            "label": "report_generation｜run #21｜task-safe-old",
            "retry_guarded": False,
        },
        {
            "task_id": "task-guarded",
            "label": "company_filings_fetch｜run #22｜task-guarded",
            "retry_guarded": True,
        },
        {
            "task_id": "task-safe-selected",
            "label": "report_generation｜run #23｜task-safe-selected",
            "retry_guarded": False,
        },
    ]

    assert recommended_task_retry_option(
        retry_options,
        preferred_task_id="task-safe-selected",
    )["task_id"] == "task-safe-selected"
    assert recommended_task_retry_option(
        retry_options,
        preferred_task_id="task-guarded",
    )["task_id"] == "task-safe-old"
    assert task_retry_option_index(retry_options, preferred_task_id="task-safe-selected") == 2
    assert task_retry_option_index(retry_options, preferred_task_id="missing") == 0


def test_task_retry_controls_one_click_retries_recommended_task(monkeypatch) -> None:
    from app.ui import maintenance_task_panels

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"maintenance_inspect_task_id": "task-safe-selected"}
            self.buttons: list[dict] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict] = []
            self.successes: list[str] = []
            self.warnings: list[str] = []
            self.selectboxes: list[dict] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return (
                kwargs.get("key") == "maintenance_retry_recommended_task"
                and not kwargs.get("disabled")
            )

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return key == "maintenance_retry_recommended_confirm_task-safe-selected"

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def warning(self, body: str) -> None:
            self.warnings.append(str(body))

        def success(self, body: str) -> None:
            self.successes.append(str(body))

        def columns(self, _spec):
            return [FakeColumn(), FakeColumn()]

        def selectbox(self, label, options, *, format_func, key, index=0):
            self.selectboxes.append(
                {
                    "label": label,
                    "options": list(options),
                    "key": key,
                    "index": index,
                    "selected_label": format_func(options[index]),
                }
            )
            return options[index]

    fake_st = FakeStreamlit()
    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(maintenance_task_panels, "st", fake_st)
    monkeypatch.setattr(
        maintenance_task_panels,
        "run_api_action_or_none",
        lambda action, **_kwargs: action(),
    )
    monkeypatch.setattr(
        maintenance_task_panels,
        "api_task_post",
        lambda endpoint, payload: posted.append((endpoint, payload))
        or {"task_id": "task-retry-new"},
    )

    maintenance_task_panels._render_task_retry_controls(
        [
            {
                "task_id": "task-safe-old",
                "label": "report_generation｜run #21｜task-safe-old",
                "retry_guarded": False,
                "retry_guard_message": "",
            },
            {
                "task_id": "task-safe-selected",
                "label": "report_generation｜run #23｜task-safe-selected",
                "retry_guarded": False,
                "retry_guard_message": "",
            },
        ]
    )

    assert posted == [("/tasks/task-safe-selected/retry", {})]
    assert fake_st.session_state["maintenance_inspect_task_id"] == "task-retry-new"
    assert fake_st.successes == ["已送出重試任務：task-retry-new"]
    assert fake_st.selectboxes[0]["index"] == 1
    assert fake_st.buttons[0]["label"] == "一鍵重試建議任務"
    assert fake_st.buttons[0]["type"] == "primary"
    assert fake_st.checkboxes[0]["key"] == "maintenance_retry_recommended_confirm_task-safe-selected"


def test_task_retry_controls_require_confirmation_before_retry_submission(monkeypatch) -> None:
    from app.ui import maintenance_task_panels

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"maintenance_inspect_task_id": "task-selected"}
            self.buttons: list[dict] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict] = []
            self.selectboxes: list[dict] = []
            self.successes: list[str] = []
            self.warnings: list[str] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return kwargs.get("key") in {
                "maintenance_retry_recommended_task",
                "maintenance_retry_failed_task",
            } and not kwargs.get("disabled")

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def warning(self, body: str) -> None:
            self.warnings.append(str(body))

        def success(self, body: str) -> None:
            self.successes.append(str(body))

        def columns(self, _spec):
            return [FakeColumn(), FakeColumn()]

        def selectbox(self, label, options, *, format_func, key, index=0):
            self.selectboxes.append(
                {
                    "label": label,
                    "options": list(options),
                    "key": key,
                    "index": index,
                    "selected_label": format_func(options[index]),
                }
            )
            return options[index]

    fake_st = FakeStreamlit()
    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(maintenance_task_panels, "st", fake_st)
    monkeypatch.setattr(
        maintenance_task_panels,
        "run_api_action_or_none",
        lambda action, **_kwargs: action(),
    )
    monkeypatch.setattr(
        maintenance_task_panels,
        "api_task_post",
        lambda endpoint, payload: posted.append((endpoint, payload))
        or {"task_id": "task-retry-new"},
    )

    maintenance_task_panels._render_task_retry_controls(
        [
            {
                "task_id": "task-selected",
                "label": "report_generation｜run #23｜task-selected",
                "retry_guarded": False,
                "retry_guard_message": "",
            }
        ]
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會重試建議任務，可能消耗模型或資料源額度",
            "value": False,
            "key": "maintenance_retry_recommended_confirm_task-selected",
        },
        {
            "label": "我了解這會重試選取任務，可能消耗模型或資料源額度",
            "value": False,
            "key": "maintenance_retry_selected_confirm_task-selected",
        },
    ]
    assert fake_st.buttons[0]["label"] == "一鍵重試建議任務"
    assert fake_st.buttons[0]["disabled"] is True
    assert fake_st.buttons[1]["label"] == "重試選取任務"
    assert fake_st.buttons[1]["disabled"] is True
    assert any("避免誤觸重試" in caption for caption in fake_st.captions)
    assert posted == []


def test_external_deployment_warning_rows_include_optional_and_smoke_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "failures": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "fail",
                "external_integration": True,
                "detail": "connection_failed:neo4j",
                "evidence": {
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
                    "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                    "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                },
                "remediation": "啟動 Neo4j 並設定帳密。",
            }
        ],
        "warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_browser_or_proxy_fallback",
                "label": "公司文件 Proxy / Browser render / Playwright 後援",
                "status": "not_configured",
                "severity": "warn",
                "external_integration": True,
                "detail": "browser_or_proxy_fallback_configured=false",
                "evidence": {
                    "browser_render_runtime": {
                        "fallback_reason": "missing_browser_render_url",
                        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
                    },
                    "playwright_render_runtime": {
                        "smoke_cli": (
                            ".venv/bin/python scripts/company_filing_render_smoke.py "
                            "--local-browser-render-defaults --prefer-unlocker "
                            "--url https://mops.twse.com.tw/ --json"
                        ),
                    },
                },
                "remediation": "設定 Browserless 或 Playwright。",
            }
        ],
        "optional_warnings": [
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "label": "GraphRAG guarded live Cypher query",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "Neo4j is required for live guarded Cypher execution.",
                "evidence": {
                    "endpoint": "GET /supply-chain/graph/cypher-query",
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
                    "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                    "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
                },
                "remediation": "啟動 Neo4j 後驗證 live read-only query。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "configured=false",
                "evidence": {
                    "runtime": {
                        "fallback_reason": "missing_structured_api_provider_or_url",
                        "smoke_cli": ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
                    }
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ],
        "all_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "external_integration": True,
                "severity": "warn",
            }
        ],
    }

    rows = helpers["external_deployment_warning_rows"](audit)
    readiness_rows = helpers["external_deployment_readiness_rows"](audit)
    enablement_summary = helpers["external_deployment_enablement_summary"](audit)
    enablement_summary_rows = helpers["external_deployment_enablement_summary_rows"](audit)
    pending_gap_rows = helpers["external_deployment_pending_gap_rows"](audit)
    pending_gap_display_rows = helpers["external_deployment_pending_gap_display_rows"](audit)
    commands = helpers["external_deployment_smoke_commands"](audit)

    assert [row["能力"] for row in rows] == [
        "外部 Neo4j 匯入連線",
        "公司文件 Proxy / Browser render / Playwright 後援",
        "GraphRAG guarded live Cypher query",
        "公司文件結構化 API 備援",
    ]
    assert rows[0]["警示層級"] == "需處理"
    assert rows[1]["警示層級"] == "注意"
    assert rows[2]["警示層級"] == "外部選配"
    assert "neo4j_graphrag_smoke.py" in rows[2]["診斷指令"]
    assert rows[3]["警示層級"] == "外部選配"
    assert [row["啟用分類"] for row in rows] == [
        "可本機免費啟用",
        "可本機免費啟用",
        "可本機免費啟用",
        "需外部資料 API",
    ]
    assert "託管 Neo4j" in rows[0]["成本/額度"]
    assert "rotating proxy" in rows[1]["成本/額度"]
    assert "TEJ" in rows[3]["成本/額度"]
    assert "missing_browser_render_url" in rows[1]["說明"]
    assert "structured_company_filing_smoke.py" in rows[3]["診斷指令"]
    assert len(rows) == 4
    assert enablement_summary["total"] == 4
    assert enablement_summary["pending"] == 4
    assert enablement_summary["free_local_pending"] == 3
    assert enablement_summary["local_action_available"] == 3
    assert enablement_summary["quota_or_external_pending"] == 0
    assert enablement_summary["paid_external_pending"] == 1
    assert enablement_summary["primary_next_action"] == (
        "先處理本機免費可補強項目，再評估 API 額度或付費資料商。"
    )
    assert [row["分類"] for row in enablement_summary_rows] == [
        "可本機免費啟用",
        "需外部資料 API",
    ]
    assert enablement_summary_rows[0]["待處理"] == 3
    assert enablement_summary_rows[0]["已就緒"] == 0
    assert "外部 Neo4j 匯入連線" in enablement_summary_rows[0]["待處理項目"]
    assert enablement_summary_rows[1]["待處理"] == 1
    assert "TEJ" in enablement_summary_rows[1]["成本/額度"]
    assert {
        row["capability"]: row["action_type"] for row in pending_gap_rows
    } == {
        "company_filing_browser_or_proxy_fallback": "local_action",
        "graphrag_live_cypher_query": "local_action",
        "neo4j_import": "local_action",
        "company_filing_structured_api_fallback": "paid_external",
    }
    assert pending_gap_rows[-1]["capability"] == "company_filing_structured_api_fallback"
    assert [row["處理類型"] for row in pending_gap_display_rows].count("本機可修") == 3
    assert pending_gap_display_rows[-1]["處理類型"] == "付費外部 API"
    browser_gap = next(
        row
        for row in pending_gap_display_rows
        if row["能力"] == "公司文件 Proxy / Browser render / Playwright 後援"
    )
    assert "start_system.py --start-dependencies" in browser_gap["本機指令"]
    assert "TEJ" in pending_gap_display_rows[-1]["成本/額度"]
    assert [row["項目"] for row in readiness_rows] == [
        "外部 Neo4j 匯入連線",
        "公司文件 Proxy / Browser render / Playwright 後援",
        "GraphRAG guarded live Cypher query",
        "公司文件結構化 API 備援",
    ]
    assert [row["狀態"] for row in readiness_rows] == [
        "阻塞",
        "待配置",
        "外部選配",
        "外部選配",
    ]
    assert [row["部署決策"] for row in readiness_rows] == [
        "正式部署前必修",
        "建議優先處理",
        "需要該能力時配置",
        "需要該能力時配置",
    ]
    assert [row["啟用分類"] for row in readiness_rows] == [
        "可本機免費啟用",
        "可本機免費啟用",
        "可本機免費啟用",
        "需外部資料 API",
    ]
    assert "本機 Neo4j 免費" in readiness_rows[0]["成本/額度"]
    assert "先用 Playwright" in readiness_rows[1]["建議路徑"]
    assert "免費版先保留 sample contract" in readiness_rows[3]["建議路徑"]
    assert [row["本機動作"] for row in readiness_rows] == [
        "可啟動",
        "可啟動",
        "可啟動",
        "需外部設定",
    ]
    assert readiness_rows[0]["優先級"] == "P1"
    assert "scripts/start_system.py --start-dependencies" in readiness_rows[0]["本機指令"]
    assert "scripts/start_system.py --start-dependencies" in readiness_rows[1]["本機指令"]
    assert "GraphRAG payload" in readiness_rows[0]["影響範圍"]
    assert "另有 2 個 smoke 指令" in readiness_rows[0]["驗證指令"]
    assert "company_filing_render_smoke.py" in readiness_rows[1]["驗證指令"]
    assert "structured_company_filing_smoke.py" in readiness_rows[3]["驗證指令"]
    assert commands == [
        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run --tickers 2330 --output graph_payload.json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json",
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json",
        (
            ".venv/bin/python scripts/company_filing_render_smoke.py "
            "--local-browser-render-defaults --prefer-unlocker "
            "--url https://mops.twse.com.tw/ --json"
        ),
        ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
    ]
    service_snapshot = {
        "local_dependencies": {
            "repair_plan": [
                {
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
            ],
            "last_start": {
                "available": True,
                "path": "data/local_dependency_start_status.json",
                "updated_at": "2026-06-09T01:02:03Z",
                "status": "已啟動",
                "message": "Neo4j 與 Browserless 已送出啟動指令。",
                "services": ["neo4j", "browserless"],
                "wait": {
                    "neo4j": True,
                    "browserless": False,
                    "browser_render_fallback": {
                        "status": "switched_to_playwright",
                        "reason": "browserless_not_ready",
                        "browser": "chromium",
                    },
                },
                "applied_env_keys": [
                    "NEO4J_URI",
                    "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
                ],
                "include_unlocker": False,
                "wait_seconds": 7,
            },
            "ports": [
                {
                    "service": "neo4j",
                    "label": "Neo4j",
                    "host": "127.0.0.1",
                    "port": 7687,
                    "open": True,
                    "role": "GraphRAG live graph",
                },
                {
                    "service": "flaresolverr",
                    "label": "FlareSolverr",
                    "host": "127.0.0.1",
                    "port": 8191,
                    "open": False,
                    "role": "MOPS unlocker",
                },
            ],
        }
    }
    readiness_with_local_status = helpers["external_deployment_readiness_rows"](
        audit,
        service_snapshot["local_dependencies"],
    )
    local_rows = helpers["local_dependency_status_rows"](service_snapshot)
    last_start_rows = helpers["local_dependency_last_start_rows"](service_snapshot)
    repair_rows = helpers["local_dependency_repair_rows"](service_snapshot)

    assert readiness_with_local_status[0]["項目"] == "外部 Neo4j 匯入連線"
    assert readiness_with_local_status[0]["本機動作"] == "端口已啟動，需驗證"
    assert "--wait-local-neo4j 20" in readiness_with_local_status[0]["本機指令"]
    assert local_rows == [
        {
            "服務": "Neo4j",
            "狀態": "已啟動",
            "本機端口": "127.0.0.1:7687",
            "用途": "GraphRAG live graph",
        },
        {
            "服務": "FlareSolverr",
            "狀態": "未偵測",
            "本機端口": "127.0.0.1:8191",
            "用途": "MOPS unlocker",
        },
    ]
    assert last_start_rows[0]["項目"] == "最近啟動"
    assert last_start_rows[0]["狀態"] == "已啟動"
    assert "服務 neo4j、browserless" in last_start_rows[0]["細節"]
    assert "等待 7s" in last_start_rows[0]["細節"]
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" in last_start_rows[0]["細節"]
    assert {
        "項目": "等待 Neo4j 7687",
        "狀態": "就緒",
        "更新時間": "2026-06-09T01:02:03Z",
        "說明": "scripts/start_system.py --start-dependencies 等待結果",
        "細節": "data/local_dependency_start_status.json",
    } in last_start_rows
    assert {
        "項目": "等待 Browserless 3000",
        "狀態": "尚未就緒",
        "更新時間": "2026-06-09T01:02:03Z",
        "說明": "scripts/start_system.py --start-dependencies 等待結果",
        "細節": "data/local_dependency_start_status.json",
    } in last_start_rows
    assert {
        "項目": "Browser render fallback",
        "狀態": "switched_to_playwright",
        "更新時間": "2026-06-09T01:02:03Z",
        "說明": "browserless_not_ready",
        "細節": "chromium",
    } in last_start_rows
    assert repair_rows == [
        {
            "項目": "Neo4j",
            "狀態": "未偵測",
            "下一步": "GraphRAG live graph。啟動核心本機依賴後重新檢查。",
            "修復指令": ".venv/bin/python scripts/start_system.py --start-dependencies",
            "驗證指令": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--local-neo4j-defaults --wait-local-neo4j 20 --json"
            ),
        }
    ]


def test_external_deployment_env_key_rows_map_status_missing_settings() -> None:
    helpers = load_report_helpers()
    managed_provider = "scraping" + "bee"
    audit = {
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
                        "default_uri": "neo4j://localhost:7687",
                    },
                    "payload_dry_run_cli": (
                        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run"
                    ),
                },
                "remediation": "設定 Neo4j。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": {
                    "playwright_render_configured": True,
                    "browser_only_render_ready": True,
                    "high_risk_mitigation_ready": False,
                    "configuration_check": {
                        "ready": False,
                        "status": "missing_required_env",
                        "missing_env_keys": ["COMPANY_FILING_BROWSER_RENDER_TOKEN"],
                        "configured_env_keys": [
                            "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
                            "COMPANY_FILING_BROWSER_RENDER_URL",
                        ],
                        "token_required": True,
                    },
                    "recommended_env": [
                        f"COMPANY_FILING_BROWSER_RENDER_PROVIDER={managed_provider}",
                        "COMPANY_FILING_BROWSER_RENDER_URL=https://app.scrapingbee.com/api/v1",
                        "COMPANY_FILING_BROWSER_RENDER_TOKEN=<token>",
                    ],
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--local-browser-render-defaults --prefer-unlocker "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
                "remediation": "設定 managed unlocker token。",
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
                                "COMPANY_FILING_STRUCTURED_API_URL",
                            ],
                            "configured_env_keys": [],
                        },
                        "provider_profile_key": "custom",
                        "smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--ticker 2330 --company-name 台積電 "
                            "--document-type investor_presentation --json"
                        ),
                    },
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ]
    }
    service_snapshot = {
        "company_filings": {
            "visual_rag_runtime": {
                "runtime_available": False,
                "fallback_reason": "missing_vision_llm_key_or_gateway",
            }
        }
    }

    rows = helpers["external_deployment_env_key_rows"](audit, service_snapshot)
    resolution_rows = helpers["external_deployment_env_resolution_rows"](audit, service_snapshot)
    rows_by_key = {
        (row["能力"], row["設定鍵"]): row
        for row in rows
    }
    resolution_by_capability = {
        row["能力"]: row
        for row in resolution_rows
    }

    assert rows_by_key[("外部 Neo4j 匯入連線", "NEO4J_URI")]["狀態"] == "缺少"
    assert rows_by_key[("外部 Neo4j 匯入連線", "NEO4J_URI")]["建議值"] == (
        "neo4j://localhost:7687"
    )
    assert rows_by_key[("外部 Neo4j 匯入連線", "NEO4J_URI")]["處理類型"] == "本機可套用"
    assert "start_system.py --start-dependencies" in rows_by_key[
        ("外部 Neo4j 匯入連線", "NEO4J_URI")
    ]["維護動作"]
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_TOKEN")
    ]["狀態"] == "缺少"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_TOKEN")
    ]["建議值"] == "<token>"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_TOKEN")
    ]["處理類型"] == "需人工密鑰"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_PROVIDER")
    ]["狀態"] == "建議"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_PROVIDER")
    ]["建議值"] == managed_provider
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_PROVIDER")
    ]["處理類型"] == "外部服務選配"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_URL")
    ]["建議值"] == "https://app.scrapingbee.com/api/v1"
    assert rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_URL")
    ]["Compose 建議值"] == "https://app.scrapingbee.com/api/v1"
    assert "不由維護操作寫入" in rows_by_key[
        ("MOPS/TWSE/TPEx 高風險文件 unlocker", "COMPANY_FILING_BROWSER_RENDER_TOKEN")
    ]["維護動作"]
    assert rows_by_key[
        ("公司文件結構化 API 備援", "COMPANY_FILING_STRUCTURED_API_PROVIDER")
    ]["狀態"] == "缺少"
    assert rows_by_key[
        ("公司文件結構化 API 備援", "COMPANY_FILING_STRUCTURED_API_URL")
    ]["建議值"] == "<provider-json-endpoint>"
    assert rows_by_key[("Visual RAG / VLM 財報解析", "GOOGLE_API_KEY")]["來源"] == (
        "/services/status"
    )
    assert "structured_company_filing_smoke.py" in rows_by_key[
        ("公司文件結構化 API 備援", "COMPANY_FILING_STRUCTURED_API_PROVIDER")
    ]["驗證指令"]
    assert resolution_by_capability["外部 Neo4j 匯入連線"]["處理策略"] == (
        "可用本機維護操作"
    )
    assert "start_system.py --start-dependencies" in resolution_by_capability[
        "外部 Neo4j 匯入連線"
    ]["建議動作"]
    assert resolution_by_capability["MOPS/TWSE/TPEx 高風險文件 unlocker"]["處理策略"] == (
        "需人工密鑰"
    )
    assert "COMPANY_FILING_BROWSER_RENDER_TOKEN" in resolution_by_capability[
        "MOPS/TWSE/TPEx 高風險文件 unlocker"
    ]["手動設定鍵"]
    assert "GOOGLE_API_KEY" in resolution_by_capability[
        "Visual RAG / VLM 財報解析"
    ]["設定鍵"]


def test_external_deployment_env_check_rows_surface_env_drift_without_secret_leak(
    tmp_path,
) -> None:
    helpers = load_report_helpers()
    neo4j_pw_env = "NEO4J_" + "PASS" + "WORD"
    db_value = "actual-db-" + "value"
    structured_value = "actual-structured-" + "value"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "NEO4J_URI=neo4j://localhost:7687",
                "NEO4J_USER=neo4j",
                f"{neo4j_pw_env}={db_value}",
                "NEO4J_DATABASE=neo4j",
                "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom",
                "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
                f"COMPANY_FILING_STRUCTURED_API_TOKEN={structured_value}",
            ]
        ),
        encoding="utf-8",
    )
    audit = {
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
                            neo4j_pw_env,
                            "NEO4J_DATABASE",
                        ],
                        "default_uri": "neo4j://localhost:7687",
                    },
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
                    },
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ]
    }

    check_payload = external_deployment_env_check_status_report(
        upgrade_audit=audit,
        service_snapshot={},
        env_file=str(env_file),
    )
    summary_rows = helpers["external_deployment_env_check_summary_rows"](check_payload)
    host_rows = helpers["external_deployment_env_check_detail_rows"](check_payload)
    compose_rows = helpers["external_deployment_env_check_detail_rows"](
        check_payload,
        target="compose",
    )
    summary_by_target = {row["目標"]: row for row in summary_rows}
    host_by_key = {row["設定鍵"]: row for row in host_rows}
    compose_by_key = {row["設定鍵"]: row for row in compose_rows}

    assert summary_by_target["host"]["狀態"] == "需補設定"
    assert summary_by_target["host"][".env"] == "存在"
    assert summary_by_target["host"]["檢查鍵數"] == 7
    assert summary_by_target["host"]["已設定"] == 5
    assert summary_by_target["host"]["缺少"] == 1
    assert summary_by_target["host"]["值不同"] == 1
    assert "--env-check" in summary_by_target["host"]["檢查指令"]
    assert summary_by_target["compose"]["檢查鍵數"] == 7
    assert summary_by_target["compose"]["缺少"] == 5
    assert "--env-template-target compose" in summary_by_target["compose"]["檢查指令"]

    assert host_by_key["NEO4J_URI"]["狀態"] == "就緒"
    assert host_by_key[neo4j_pw_env]["目前值"] == "<set>"
    assert host_by_key[neo4j_pw_env]["類型"] == "密鑰"
    assert host_by_key["COMPANY_FILING_STRUCTURED_API_PROVIDER"]["狀態"] == "需確認"
    assert host_by_key["COMPANY_FILING_STRUCTURED_API_PROVIDER"]["目前值"] == "custom"
    assert host_by_key["COMPANY_FILING_STRUCTURED_API_URL"]["狀態"] == "需補設定"
    assert host_by_key["COMPANY_FILING_STRUCTURED_API_URL"]["目前值"] == (
        "<provider-json-endpoint>"
    )
    assert host_by_key["COMPANY_FILING_STRUCTURED_API_TOKEN"]["目前值"] == "<set>"
    assert "COMPOSE_NEO4J_URI" in compose_by_key
    assert "NEO4J_URI" not in compose_by_key
    assert db_value not in str(host_rows)
    assert structured_value not in str(host_rows)


def test_external_deployment_readiness_rows_reflect_local_dependency_wait() -> None:
    helpers = load_report_helpers()
    unlocker_provider = "flare" + "solverr"
    audit = {
        "local_dependency_wait": {
            "neo4j": False,
            "neo4j_timeout_seconds": 20,
            "flaresolverr": True,
            "flaresolverr_timeout_seconds": 20,
        },
        "checks": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": {"payload_export_ready": True},
                "remediation": "啟動 Neo4j。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": {
                    "recommended_env": [
                        f"COMPANY_FILING_BROWSER_RENDER_PROVIDER={unlocker_provider}",
                        "COMPANY_FILING_BROWSER_RENDER_URL=http://127.0.0.1:8191/v1",
                    ],
                },
                "remediation": "啟動 FlareSolverr。",
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
                "evidence": {},
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ],
    }

    rows_by_item = {
        row["項目"]: row for row in helpers["external_deployment_readiness_rows"](audit)
    }
    enablement_summary = helpers["external_deployment_enablement_summary"](audit)

    assert rows_by_item["外部 Neo4j 匯入連線"]["本機動作"] == "驗證失敗"
    assert "--wait-local-neo4j 20" in rows_by_item["外部 Neo4j 匯入連線"]["本機指令"]
    assert rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["本機動作"] == (
        "端口已啟動，需驗證"
    )
    assert rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["啟用分類"] == (
        "本機免費或付費 unlocker"
    )
    assert "FlareSolverr 本機免費" in rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["成本/額度"]
    assert (
        "--wait-local-flaresolverr 20"
        in rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["本機指令"]
    )
    assert rows_by_item["公司文件結構化 API 備援"]["本機動作"] == "需外部設定"
    assert rows_by_item["公司文件結構化 API 備援"]["本機指令"] == "-"
    assert rows_by_item["公司文件結構化 API 備援"]["啟用分類"] == "需外部資料 API"
    assert enablement_summary["pending"] == 3
    assert enablement_summary["local_action_available"] == 2


def test_high_risk_filing_unlocker_rows_surface_policy_details() -> None:
    helpers = load_report_helpers()
    provider_env = "COMPANY_FILING_BROWSER_RENDER_PROVIDER" + "=flaresolverr"
    render_url_env = "COMPANY_FILING_BROWSER_RENDER_URL" + "=http://127.0.0.1:8191/v1"
    compose_render_url_env = "COMPANY_FILING_BROWSER_RENDER_URL" + "=http://flaresolverr:8191/v1"
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "needs unlocker",
                "evidence": {
                    "configured_provider": "browserless",
                    "provider_tier": "browser_render",
                    "provider_capability": {
                        "provider": "browserless",
                        "tier": "browser_render",
                        "captcha_unlocker": False,
                    },
                    "browser_only_render_ready": True,
                    "unlocker_provider_ready": False,
                    "captcha_challenge_ready": False,
                    "configuration_ready": True,
                    "configuration_check": {
                        "ready": True,
                        "status": "ready",
                        "provider": "browserless",
                        "provider_supported": True,
                        "missing_env_keys": [],
                        "configured_env_keys": [
                            "COMPANY_FILING_BROWSER_RENDER_ENABLED",
                            "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
                            "COMPANY_FILING_BROWSER_RENDER_URL",
                        ],
                        "token_required": False,
                        "token_configured": False,
                        "endpoint_configured": True,
                        "endpoint_valid": True,
                    },
                    "fallback_reason": "browser_or_playwright_render_lacks_captcha_unlocker",
                    "domains": ["mops.twse.com.tw", "doc.twse.com.tw"],
                    "recommended_env": [provider_env, render_url_env],
                    "compose_recommended_env": [provider_env, compose_render_url_env],
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--local-browser-render-defaults --prefer-unlocker "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
                "remediation": "設定 FlareSolverr 或 managed unlocker。",
            }
        ]
    }

    rows = helpers["high_risk_filing_unlocker_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "Provider",
        "Configuration check",
        "高風險防護",
        "高風險網域",
        "建議 env",
        "MOPS smoke",
    ]
    assert rows[0]["狀態"] == "待配置"
    assert rows[0]["目前"] == "browserless"
    assert "captcha_unlocker=否" in rows[0]["細節"]
    assert rows[1]["狀態"] == "ready"
    assert "provider=browserless" in rows[1]["目前"]
    assert "token=optional" in rows[1]["細節"]
    assert "browser render fallback" in rows[2]["目前"]
    assert rows[2]["細節"] == "browser_or_playwright_render_lacks_captcha_unlocker"
    assert "mops.twse.com.tw" in rows[3]["目前"]
    assert provider_env in rows[4]["目前"]
    assert "# compose" in rows[4]["目前"]
    assert compose_render_url_env in rows[4]["目前"]
    assert "service DNS" in rows[4]["細節"]
    assert "https://mops.twse.com.tw/" in rows[5]["目前"]


def test_high_risk_filing_unlocker_rows_surface_missing_managed_token() -> None:
    helpers = load_report_helpers()
    provider_env = "COMPANY_FILING_BROWSER_RENDER_PROVIDER" + "=scrapingbee"
    render_url_env = "COMPANY_FILING_BROWSER_RENDER_URL" + "=https://app.scrapingbee.com/api/v1"
    token_env = "COMPANY_FILING_BROWSER_RENDER_TOKEN" + "=<token>"
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "missing token",
                "evidence": {
                    "configured_provider": "scrapingbee",
                    "provider_tier": "managed_unlocker",
                    "provider_capability": {
                        "provider": "scrapingbee",
                        "tier": "managed_unlocker",
                        "captcha_unlocker": True,
                    },
                    "unlocker_provider_ready": False,
                    "captcha_challenge_ready": False,
                    "configuration_ready": False,
                    "configuration_check": {
                        "ready": False,
                        "status": "missing_required_env",
                        "fallback_reason": "missing_browser_render_token",
                        "provider": "scrapingbee",
                        "provider_supported": True,
                        "missing_env_keys": ["COMPANY_FILING_BROWSER_RENDER_TOKEN"],
                        "configured_env_keys": [
                            "COMPANY_FILING_BROWSER_RENDER_ENABLED",
                            "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
                            "COMPANY_FILING_BROWSER_RENDER_URL",
                        ],
                        "token_required": True,
                        "token_configured": False,
                        "endpoint_configured": True,
                        "endpoint_valid": True,
                    },
                    "fallback_reason": "missing_browser_render_token",
                    "recommended_env": [
                        provider_env,
                        render_url_env,
                        token_env,
                    ],
                },
                "remediation": "設定 managed unlocker token。",
            }
        ]
    }

    rows = helpers["high_risk_filing_unlocker_rows"](audit)

    assert rows[1]["項目"] == "Configuration check"
    assert rows[1]["狀態"] == "missing_required_env"
    assert "missing=COMPANY_FILING_BROWSER_RENDER_TOKEN" in rows[1]["目前"]
    assert "token=required" in rows[1]["細節"]
    assert "token_configured=否" in rows[1]["細節"]
    assert "COMPANY_FILING_BROWSER_RENDER_TOKEN" in rows[1]["下一步"]


def test_local_unlocker_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "label": "MOPS/TWSE/TPEx 高風險文件 unlocker",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "needs unlocker",
                "evidence": {
                    "configured_provider": "browserless",
                    "provider_tier": "browser_render",
                    "browser_only_render_ready": True,
                    "unlocker_provider_ready": False,
                    "captcha_challenge_ready": False,
                    "fallback_reason": "browser_or_playwright_render_lacks_captcha_unlocker",
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
                        "--local-browser-render-defaults --prefer-unlocker "
                        "--url https://mops.twse.com.tw/ --json"
                    ),
                },
                "remediation": "設定 FlareSolverr 或 managed unlocker。",
            }
        ]
    }

    rows = helpers["local_unlocker_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "一鍵啟動",
        "本機稽核",
        "Fallback 判斷",
        "容器診斷",
        "MOPS smoke",
    ]
    assert rows[0]["狀態"] == "建議升級"
    assert "scripts/start_system.py --start-dependencies --prefer-unlocker" in rows[0]["指令"]
    assert "--wait-local-flaresolverr 20" in rows[1]["指令"]
    assert "Browserless/Playwright" in rows[2]["說明"]
    assert rows[2]["指令"] == "-"
    assert "docker compose logs flaresolverr" in rows[3]["指令"]
    assert "--local-browser-render-defaults --prefer-unlocker" in rows[4]["指令"]
    assert "https://mops.twse.com.tw/" in rows[4]["指令"]


def test_local_neo4j_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "missing Neo4j",
                "evidence": {
                    "ready": False,
                    "connection_ok": False,
                    "fallback_reason": "missing_settings:neo4j_uri",
                    "payload_export_ready": True,
                    "payload_node_count": 27,
                    "payload_structural_edge_count": 135,
                    "payload_peer_edge_count": 36,
                    "payload_statement_count": 5,
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                    "smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
                    ),
                    "import_smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
                    ),
                    "local_docker_defaults": {
                        "cli_start": ".venv/bin/python scripts/start_system.py --start-dependencies",
                    },
                },
            },
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "label": "GraphRAG guarded live Cypher query",
                "status": "degraded",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "Neo4j not configured",
                "evidence": {
                    "neo4j_ready": False,
                    "local_dry_run_status": "executed_dry_run",
                    "plan_validation": {"valid": True, "read_only": True},
                    "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                    "smoke_cli": (
                        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
                    ),
                },
            },
        ]
    }

    rows = helpers["local_neo4j_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "一鍵啟動",
        "本機稽核",
        "Payload dry-run",
        "Live query smoke",
        "Import-first smoke",
        "容器診斷",
    ]
    assert rows[0]["狀態"] == "待啟動"
    assert "scripts/start_system.py --start-dependencies" in rows[0]["指令"]
    assert "--local-neo4j-defaults --wait-local-neo4j 20" in rows[1]["指令"]
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in rows[2]["指令"]
    assert "nodes=27" in rows[2]["說明"]
    assert "neo4j_graphrag_smoke.py" in rows[3]["指令"]
    assert "--import-first" in rows[4]["指令"]
    assert "docker compose logs neo4j" in rows[5]["指令"]
    assert "missing_settings:neo4j_uri" in rows[5]["說明"]


def test_structured_filing_api_operation_rows_include_actionable_commands() -> None:
    helpers = load_report_helpers()
    audit = {
        "optional_warnings": [
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "detail": "configured=false",
                "evidence": {
                    "configured": False,
                    "provider": None,
                    "provider_profile_key": "custom",
                    "supported_provider_examples": [
                        "tej",
                        "scrapingbee_dataset",
                        "brightdata_dataset",
                        "custom",
                    ],
                    "required_document_fields": [
                        "title/name/headline/doc_title",
                        "text/content/body/abstract/summary",
                        "ticker_or_company_mention",
                        "document_type_match",
                    ],
                    "response_row_aliases": ["documents", "data", "results"],
                    "runtime": {
                        "configured": False,
                        "configuration_ready": False,
                        "configuration_check": {
                            "ready": False,
                            "status": "missing_required_env",
                            "missing_env_keys": [
                                "COMPANY_FILING_STRUCTURED_API_PROVIDER",
                                "COMPANY_FILING_STRUCTURED_API_URL",
                            ],
                            "configured_env_keys": [],
                            "token_required": False,
                            "endpoint_valid": False,
                        },
                        "fallback_reason": "missing_structured_api_provider_or_url",
                        "provider": None,
                        "provider_profile_key": "custom",
                        "provider_profile": {
                            "provider": "custom",
                            "profile_key": "custom",
                        },
                        "provider_decision_matrix": [
                            {
                                "provider": "tej",
                                "token_required": True,
                                "document_type_param": "document_type",
                            },
                            {
                                "provider": "scrapingbee_dataset",
                                "token_required": True,
                                "document_type_param": "document_types",
                            },
                            {
                                "provider": "brightdata_dataset",
                                "token_required": True,
                                "document_type_param": "document_types",
                            },
                            {
                                "provider": "custom",
                                "token_required": False,
                                "document_type_param": "document_types",
                            },
                        ],
                        "provider_selection_hint": (
                            "免費版先用 custom local fixture 驗證 HTTP/JSON contract。"
                        ),
                        "provider_setup_preview": {
                            "profile_key": "tej",
                            "provider": "tej",
                            "env_template": [
                                "COMPANY_FILING_STRUCTURED_API_PROVIDER=tej",
                                "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
                                "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>",
                            ],
                            "method": "GET",
                            "endpoint": "<provider-json-endpoint>",
                            "headers": {
                                "Accept": "application/json",
                                "Authorization": "Bearer <redacted>",
                            },
                            "params": {
                                "ticker": "2330",
                                "company_name": "台積電",
                                "limit": 3,
                                "document_type": "investor_presentation",
                            },
                            "auth_mode": "bearer",
                            "token_redacted": True,
                        },
                        "request_contract": {
                            "method": "GET",
                            "auth_mode": "bearer_optional",
                            "document_type_param": "document_types",
                            "query_param_keys": [
                                "ticker",
                                "company_name",
                                "limit",
                                "document_types",
                            ],
                            "response_rows": ["documents", "data", "results"],
                        },
                        "required_document_fields": [
                            "title/name/headline/doc_title",
                            "text/content/body/abstract/summary",
                            "ticker_or_company_mention",
                            "document_type_match",
                        ],
                        "response_row_aliases": ["documents", "data", "results"],
                        "sample_contract_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--sample-json examples/structured_company_filing_sample.json "
                            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
                        ),
                        "local_fixture_start_cli": (
                            ".venv/bin/python scripts/local_structured_company_filing_api.py "
                            "--sample-json examples/structured_company_filing_sample.json "
                            "--host 127.0.0.1 --port 8794"
                        ),
                        "local_fixture_smoke_cli": (
                            "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
                            "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings "
                            ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                        ),
                        "local_fixture_http_smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                            "--json --strict"
                        ),
                        "local_fixture_provider_profile_smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                            "--provider-profile tej --json --strict"
                        ),
                        "sample_contract": {
                            "status": "ready",
                            "ready": True,
                            "mode": "sample_json_contract",
                            "raw_row_count": 1,
                            "document_count": 1,
                            "error_count": 0,
                            "contract_diagnostics": {
                                "row_container": "documents",
                                "conversion_ratio": 1.0,
                                "field_coverage": {
                                    "title": 1,
                                    "text": 1,
                                    "ticker_or_company_mention": 1,
                                    "requested_document_type_match": 1,
                                },
                            },
                        },
                        "free_validation": {
                            "sample_contract_ready": True,
                            "local_fixture_available": True,
                            "provider_profile_fixture_available": True,
                            "provider_profile": "tej",
                            "local_fixture_url": "http://127.0.0.1:8794/filings",
                            "local_fixture_provider_profile_smoke_cli": (
                                ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                                "--provider-profile tej --json --strict"
                            ),
                            "purpose": (
                                "用本機 fixture 驗證 live HTTP fetch path，含 TEJ profile "
                                "auth/parameter smoke，不需要付費資料商 token。"
                            ),
                        },
                        "smoke_cli": (
                            ".venv/bin/python scripts/structured_company_filing_smoke.py "
                            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
                        ),
                    },
                },
                "remediation": "設定 TEJ 或專業資料 API。",
            }
        ]
    }

    rows = helpers["structured_filing_api_operation_rows"](audit)

    assert [row["項目"] for row in rows] == [
        "Configuration check",
        "Provider profile",
        "Provider decision matrix",
        "Provider setup preview",
        "Sample contract",
        "Local fixture HTTP",
        "Live smoke",
        "Request contract",
        "Required fields",
        "Fallback 判斷",
    ]
    assert rows[0]["狀態"] == "missing_required_env"
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=tej" in rows[0]["指令"]
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>" in rows[0]["指令"]
    assert "missing=COMPANY_FILING_STRUCTURED_API_PROVIDER" in rows[0]["說明"]
    assert "endpoint=missing/invalid" in rows[0]["說明"]
    assert rows[1]["狀態"] == "待設定"
    assert "supported=tej、scrapingbee_dataset、brightdata_dataset、custom" in rows[1]["說明"]
    assert rows[2]["狀態"] == "4 profiles / 3 token-required"
    assert "tej:token/document_type" in rows[2]["說明"]
    assert "custom:no-token/document_types" in rows[2]["說明"]
    assert "custom local fixture" in rows[2]["說明"]
    assert rows[3]["狀態"] == "tej / redacted"
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=tej" in rows[3]["指令"]
    assert "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>" in rows[3]["指令"]
    assert "Authorization" in rows[3]["說明"]
    assert "token=redacted" in rows[3]["說明"]
    assert "document_type" in rows[3]["說明"]
    assert rows[4]["狀態"] == "ready"
    assert "--sample-json examples/structured_company_filing_sample.json" in rows[4]["指令"]
    assert "raw_rows=1；documents=1；errors=0" in rows[4]["說明"]
    assert "row_container=documents" in rows[4]["說明"]
    assert "conversion_ratio=1.0" in rows[4]["說明"]
    assert "coverage=title=1,text=1" in rows[4]["說明"]
    assert rows[5]["狀態"] == "可執行"
    assert "structured_company_filing_fixture_smoke.py" in rows[5]["指令"]
    assert "--provider-profile tej" in rows[5]["指令"]
    assert "local_structured_company_filing_api.py" in rows[5]["指令"]
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in rows[5]["指令"]
    assert "http://127.0.0.1:8794/filings" in rows[5]["說明"]
    assert "provider_profile=tej local smoke" in rows[5]["說明"]
    assert "不需要付費資料商 token" in rows[5]["說明"]
    assert rows[6]["狀態"] == "待設定"
    assert "structured_company_filing_smoke.py" in rows[6]["指令"]
    assert rows[7]["狀態"] == "GET"
    assert "auth=bearer_optional" in rows[7]["說明"]
    assert "ticker,company_name,limit,document_types" in rows[7]["說明"]
    assert "title/name/headline/doc_title" in rows[8]["說明"]
    assert rows[9]["狀態"] == "not_configured"
    assert "missing_structured_api_provider_or_url" in rows[9]["說明"]


def test_upgrade_audit_html_is_readable_and_not_color_only() -> None:
    helpers = load_report_helpers()

    audit = {
        "overall_status": "ready",
        "strict_external": False,
        "summary": {
            "total_checks": 23,
            "ready": 18,
            "warnings": 0,
            "optional_warnings": 5,
            "total_warnings": 5,
            "failures": 0,
            "implementation_status": "ready",
            "deployment_status": "caution",
            "deployment_blocking_status": "ready",
            "deployment_optional_only": True,
        },
        "implementation": {
            "status": "ready",
            "ready": 18,
            "total_checks": 18,
            "warnings": 0,
            "failures": 0,
        },
        "deployment": {
            "status": "caution",
            "blocking_status": "ready",
            "optional_only": True,
            "ready": 0,
            "total_checks": 5,
            "warnings": 5,
            "failures": 0,
        },
        "areas": {
            "ai_rag": {"ready": 9, "warnings": 2, "failures": 0, "checks": 11},
            "architecture": {"ready": 4, "warnings": 0, "failures": 0, "checks": 4},
            "data_business_logic": {"ready": 5, "warnings": 3, "failures": 0, "checks": 8},
        },
        "checks": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "severity": "warn",
                "status": "degraded",
                "detail": "missing_settings:neo4j_uri",
                "remediation": "設定 NEO4J_URI。",
            },
            {
                "area": "ai_rag",
                "capability": "visual_rag",
                "label": "Visual RAG / VLM 財報解析",
                "severity": "warn",
                "status": "not_configured",
                "detail": "visual_rag_disabled",
                "remediation": "安裝 .[visual] 並設定 vision LLM。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_pdf_table_parser_runtime",
                "label": "PDF 表格 parser runtime",
                "severity": "warn",
                "status": "not_configured",
                "detail": "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured",
                "remediation": "安裝 .[pdf]。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_browser_or_proxy_fallback",
                "label": "公司文件 Proxy / Browser render / Playwright 後援",
                "severity": "warn",
                "status": "not_configured",
                "detail": "browser_or_proxy_fallback_configured=false",
                "remediation": "設定 COMPANY_FILING_PROXY_URLS。",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_structured_api_fallback",
                "label": "公司文件結構化 API 備援",
                "severity": "warn",
                "status": "not_configured",
                "detail": "configured=false",
                "remediation": "設定 TEJ 或專業資料 API。",
            },
        ],
    }

    html = helpers["upgrade_audit_html"](audit)
    rows = helpers["upgrade_audit_rows"](audit)

    assert "升級稽核" in html
    assert "核心升級" in html
    assert "外部整合" in html
    assert "外部選配" in html
    assert "注意" in html
    assert "通過" in html
    assert "一般檢查" in html
    assert "18/23" in html
    assert "核心 18/18 通過，外部 0/5 通過，blocking 通過" in html
    assert "外部選配 5 項" in html
    assert "沒有 blocking deployment 缺口" in html
    assert "AI / RAG" in html
    assert rows[0] == {
        "面向": "AI / RAG",
        "能力": "外部 Neo4j 匯入連線",
        "結果": "注意",
        "目前狀態": "degraded",
        "說明": "missing_settings:neo4j_uri",
        "處理方向": "設定 NEO4J_URI。",
    }
    assert rows[1]["能力"] == "Visual RAG / VLM 財報解析"
    assert rows[1]["處理方向"] == "安裝 .[visual] 並設定 vision LLM。"
    assert rows[2]["能力"] == "PDF 表格 parser runtime"
    assert rows[2]["處理方向"] == "安裝 .[pdf]。"
    assert rows[3]["能力"] == "公司文件 Proxy / Browser render / Playwright 後援"
    assert rows[3]["處理方向"] == "設定 COMPANY_FILING_PROXY_URLS。"
    assert rows[4]["能力"] == "公司文件結構化 API 備援"
