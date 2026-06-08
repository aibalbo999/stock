from __future__ import annotations

from streamlit_ui_test_helpers import load_report_helpers


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
    assert action_rows == [
        {
            "處理路徑": "一鍵重試",
            "數量": 1,
            "說明": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
            "代表任務": "report_generation｜task-failed",
        },
        {
            "處理路徑": "外部配置缺失",
            "數量": 2,
            "說明": "先修復 Redis/Celery、資料源 token、Visual RAG 或文件後援設定，再重送任務。",
            "代表任務": "data_operation｜task-queue；company_filings_fetch｜task-filing",
        },
        {
            "處理路徑": "需人工處理",
            "數量": 1,
            "說明": "payload、輸入範圍或取消狀態需人工檢查，修正後從原工作流程重送。",
            "代表任務": "after_close_report_update｜task-after-close",
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
            "action_route_detail": "先修復 Redis/Celery、資料源 token、Visual RAG 或文件後援設定，再重送任務。",
            "retry_guarded": True,
            "retry_guard_message": "先修配置再重試：先修復 Redis/Celery、資料源 token、Visual RAG 或文件後援設定，再重送任務。",
        },
    ]


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
                        "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json",
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
    assert "missing_browser_render_url" in rows[1]["說明"]
    assert "structured_company_filing_smoke.py" in rows[3]["診斷指令"]
    assert len(rows) == 4
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
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json",
        ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
    ]
    service_snapshot = {
        "local_dependencies": {
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

    assert readiness_with_local_status[0]["項目"] == "外部 Neo4j 匯入連線"
    assert readiness_with_local_status[0]["本機動作"] == "已啟動"
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

    assert rows_by_item["外部 Neo4j 匯入連線"]["本機動作"] == "驗證失敗"
    assert "--wait-local-neo4j 20" in rows_by_item["外部 Neo4j 匯入連線"]["本機指令"]
    assert rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["本機動作"] == "已啟動"
    assert (
        "--wait-local-flaresolverr 20"
        in rows_by_item["MOPS/TWSE/TPEx 高風險文件 unlocker"]["本機指令"]
    )
    assert rows_by_item["公司文件結構化 API 備援"]["本機動作"] == "需外部設定"
    assert rows_by_item["公司文件結構化 API 備援"]["本機指令"] == "-"


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
                    "fallback_reason": "browser_or_playwright_render_lacks_captcha_unlocker",
                    "domains": ["mops.twse.com.tw", "doc.twse.com.tw"],
                    "recommended_env": [provider_env, render_url_env],
                    "compose_recommended_env": [provider_env, compose_render_url_env],
                    "smoke_cli": (
                        ".venv/bin/python scripts/company_filing_render_smoke.py "
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
        "高風險防護",
        "高風險網域",
        "建議 env",
        "MOPS smoke",
    ]
    assert rows[0]["狀態"] == "待配置"
    assert rows[0]["目前"] == "browserless"
    assert "captcha_unlocker=否" in rows[0]["細節"]
    assert "browser render fallback" in rows[1]["目前"]
    assert rows[1]["細節"] == "browser_or_playwright_render_lacks_captcha_unlocker"
    assert "mops.twse.com.tw" in rows[2]["目前"]
    assert provider_env in rows[3]["目前"]
    assert "# compose" in rows[3]["目前"]
    assert compose_render_url_env in rows[3]["目前"]
    assert "service DNS" in rows[3]["細節"]
    assert "https://mops.twse.com.tw/" in rows[4]["目前"]


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
                        "fallback_reason": "missing_structured_api_provider_or_url",
                        "provider": None,
                        "provider_profile_key": "custom",
                        "provider_profile": {
                            "provider": "custom",
                            "profile_key": "custom",
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
                        "sample_contract": {
                            "status": "ready",
                            "ready": True,
                            "mode": "sample_json_contract",
                            "raw_row_count": 1,
                            "document_count": 1,
                            "error_count": 0,
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
        "Provider profile",
        "Sample contract",
        "Live smoke",
        "Request contract",
        "Required fields",
        "Fallback 判斷",
    ]
    assert rows[0]["狀態"] == "待設定"
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in rows[0]["指令"]
    assert "supported=tej、scrapingbee_dataset、brightdata_dataset、custom" in rows[0]["說明"]
    assert rows[1]["狀態"] == "ready"
    assert "--sample-json examples/structured_company_filing_sample.json" in rows[1]["指令"]
    assert "raw_rows=1；documents=1；errors=0" in rows[1]["說明"]
    assert rows[2]["狀態"] == "待設定"
    assert "structured_company_filing_smoke.py" in rows[2]["指令"]
    assert rows[3]["狀態"] == "GET"
    assert "auth=bearer_optional" in rows[3]["說明"]
    assert "ticker,company_name,limit,document_types" in rows[3]["說明"]
    assert "title/name/headline/doc_title" in rows[4]["說明"]
    assert rows[5]["狀態"] == "not_configured"
    assert "missing_structured_api_provider_or_url" in rows[5]["說明"]


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
    assert "注意" in html
    assert "通過" in html
    assert "一般檢查" in html
    assert "18/23" in html
    assert "核心 18/18 通過，外部 0/5 通過" in html
    assert "外部選配 5 項" in html
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
