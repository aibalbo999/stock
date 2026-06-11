from __future__ import annotations

from datetime import date
from typing import Any

from app.ui.data_enrichment import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)
from app.ui import data_enrichment_manual
from app.ui import data_enrichment_market
from app.ui import data_enrichment_rss
from app.ui import data_enrichment_common
from app.ui.data_enrichment_market import market_data_operation_button_type
from app.ui.data_enrichment_market import market_cache_operator_summary


def test_data_task_followup_summary_routes_success_to_latest_report() -> None:
    assert hasattr(data_enrichment_common, "data_task_followup_summary")

    summary = data_enrichment_common.data_task_followup_summary(
        {
            "task_id": "task-data",
            "status": "SUCCESS",
            "ready": True,
            "successful": True,
            "result": {"report_id": 15},
        }
    )

    assert summary == {
        "state": "ready",
        "title": "資料補強完成",
        "detail": "資料任務已完成；回報告中心確認最新版生命週期是否仍需重跑。",
        "next_step": "開啟報告中心確認資料、品質、補強、重跑與可讀狀態。",
        "action_label": "查看報告中心",
        "route_hint": "report:15",
    }


def test_data_task_followup_summary_explains_running_and_failed_tasks() -> None:
    running = data_enrichment_common.data_task_followup_summary(
        {
            "task_id": "task-running",
            "status": "STARTED",
            "ready": False,
            "successful": False,
        }
    )
    failed = data_enrichment_common.data_task_followup_summary(
        {
            "task_id": "task-failed",
            "status": "FAILURE",
            "ready": True,
            "successful": False,
            "error_summary": "公司文件補抓失敗",
            "next_action": "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry",
        }
    )

    assert running == {
        "state": "attention",
        "title": "等待資料補強完成",
        "detail": "資料任務仍在處理中；完成前不要重複送出同類補強。",
        "next_step": "保持本頁狀態輪詢，完成後回報告中心確認是否需要重跑。",
        "action_label": "查看任務進度",
        "route_hint": "task:task-running",
    }
    assert failed == {
        "state": "blocked",
        "title": "資料補強未完成",
        "detail": "公司文件補抓失敗",
        "next_step": "可從維護頁重試，或呼叫 POST /tasks/task-failed/retry",
        "action_label": "查看任務診斷",
        "route_hint": "task:task-failed",
    }


def test_render_last_data_task_status_shows_followup_summary(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"last_data_task_id": "task-data"}
            self.expanders: list[dict[str, Any]] = []
            self.markdowns: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def expander(self, label: str, *, expanded: bool = False):
            self.expanders.append({"label": label, "expanded": expanded})
            return self

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdowns.append(str(body))

        def text_input(self, _label: str, *, value: str, key: str) -> str:
            return value

    fake_st = FakeStreamlit()
    routed: list[tuple[dict, dict]] = []

    monkeypatch.setattr(data_enrichment_common, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_common,
        "render_task_status_panel",
        lambda **_kwargs: {
            "task_id": "task-data",
            "status": "SUCCESS",
            "successful": True,
            "result": {"report_id": 15},
        },
    )
    monkeypatch.setattr(
        data_enrichment_common,
        "render_operator_route_button",
        lambda action, **kwargs: routed.append((action, kwargs)),
    )

    data_enrichment_common.render_last_data_task_status(
        label="refresh_data_task_status",
        key="data_task_id_lookup",
        expanded=True,
    )

    assert fake_st.expanders == [{"label": "背景資料任務狀態", "expanded": True}]
    assert any(
        'class="data-task-followup-summary is-ready"' in markdown
        and "資料補強完成" in markdown
        and "回報告中心確認最新版生命週期" in markdown
        for markdown in fake_st.markdowns
    )
    assert routed == [
        (
            {"action_label": "查看報告中心", "route_hint": "report:15"},
            {
                "key": "refresh_data_task_status_followup_action",
                "primary": True,
                "show_caption": True,
            },
        )
    ]


def test_pending_market_handoff_summary_surfaces_selected_operation_and_next_step() -> None:
    assert hasattr(data_enrichment_market, "pending_market_handoff_summary")

    summary = data_enrichment_market.pending_market_handoff_summary(
        selected_market_tickers=["2330", "2382"],
        pending_operation="market_refresh",
        selection_state={
            "selected": ["2330", "2382"],
            "rejected": [],
            "state": "ready",
        },
    )

    assert summary == {
        "state": "ready",
        "title": "已帶入刷新股價",
        "detail": "股票：2330、2382｜更新最新版報告的股價與成交量判讀。",
        "next_step": "確認背景任務後按「刷新股價」。",
        "action_label": "刷新股價",
        "rejected_detail": "",
    }


def test_pending_market_handoff_summary_flags_rejected_tickers() -> None:
    summary = data_enrichment_market.pending_market_handoff_summary(
        selected_market_tickers=["2330"],
        pending_operation="company_filings_fetch",
        selection_state={
            "selected": ["2330"],
            "rejected": ["9999"],
            "state": "attention",
            "detail": "建議股票未在目前白名單：9999。已先選取可用股票：2330。",
        },
    )

    assert summary == {
        "state": "attention",
        "title": "已帶入補抓公司文件",
        "detail": "股票：2330｜補齊公司文件、法說會或公開資訊缺口。",
        "next_step": "先處理白名單提醒，再確認背景任務後按「補抓公司文件」。",
        "action_label": "補抓公司文件",
        "rejected_detail": "建議股票未在目前白名單：9999。已先選取可用股票：2330。",
    }


def test_company_filing_runtime_rows_surface_pdf_visual_and_external_fallbacks() -> None:
    rows = company_filing_runtime_rows(
        {
            "company_filings": {
                "pdf_parser": "auto",
                "pdf_extract_tables": True,
                "pdf_parser_available": True,
                "pdf_table_parser_available": True,
                "pdf_table_quality_provenance_enabled": True,
                "pdf_table_quality_provenance_prefix": "[PDF 表格品質]",
                "pdf_parser_dependencies": {"fallback_reason": None},
                "visual_rag_runtime_available": False,
                "visual_rag_model": "gemini-3.5-flash",
                "visual_rag_runtime": {"fallback_reason": "missing_vision_llm_key_or_gateway"},
                "playwright_render_configured": True,
                "playwright_render_browser": "chromium",
                "playwright_render_runtime": {"fallback_reason": None, "browser_available": True},
                "browser_render_configured": False,
                "browser_render_provider": "flaresolverr",
                "browser_render_runtime": {"fallback_reason": "browser_render_disabled"},
                "official_material_information_openapi_ready": True,
                "official_material_information_openapi_provider": "twse_tpex_official_openapi",
                "official_material_information_openapi_runtime": {"ready": True},
                "structured_api_configured": False,
                "structured_api_provider": None,
                "structured_api_runtime": {"fallback_reason": "missing_structured_api_provider_or_url"},
            }
        }
    )

    assert rows == [
        {
            "能力": "PDF parser",
            "狀態": "ready",
            "目前": "auto",
            "細節": "-",
            "下一步": "可處理文字型 PDF。",
        },
        {
            "能力": "PDF 表格抽取",
            "狀態": "ready",
            "目前": "enabled",
            "細節": "quality=[PDF 表格品質]",
            "下一步": "可抽取財報表格，並標記表格品質風險。",
        },
        {
            "能力": "Visual RAG",
            "狀態": "not_ready",
            "目前": "gemini-3.5-flash",
            "細節": "missing_vision_llm_key_or_gateway",
            "下一步": "檢查 PyMuPDF、COMPANY_FILING_VISUAL_RAG_MODEL 與 vision LLM key/gateway。",
        },
        {
            "能力": "Playwright render",
            "狀態": "ready",
            "目前": "chromium",
            "細節": "-",
            "下一步": "可處理動態 IR/公開文件頁。",
        },
        {
            "能力": "Browser / unlocker",
            "狀態": "not_ready",
            "目前": "flaresolverr",
            "細節": "browser_render_disabled",
            "下一步": "設定 Browserless、FlareSolverr、ScrapingBee 或 BrightData render URL。",
        },
        {
            "能力": "重大訊息 OpenAPI",
            "狀態": "ready",
            "目前": "twse_tpex_official_openapi",
            "細節": "-",
            "下一步": "可補近期官方重大訊息。",
        },
        {
            "能力": "結構化文件 API",
            "狀態": "optional",
            "目前": "-",
            "細節": "missing_structured_api_provider_or_url",
            "下一步": "若 MOPS/IR 常被擋，可串接 TEJ 或專業文件 API。",
        },
    ]


def test_market_data_operation_button_type_prioritizes_pending_operation() -> None:
    assert market_data_operation_button_type(None, "market_refresh") == "primary"
    assert market_data_operation_button_type(None, "valuation_refresh") == "secondary"
    assert (
        market_data_operation_button_type("company_filings_fetch", "company_filings_fetch")
        == "primary"
    )
    assert market_data_operation_button_type("company_filings_fetch", "market_refresh") == (
        "secondary"
    )
    assert market_data_operation_button_type("valuation_refresh", "valuation_refresh") == (
        "primary"
    )


def test_pending_market_selection_state_reports_tickers_outside_allowlist() -> None:
    assert hasattr(data_enrichment_market, "pending_market_selection_state")
    state = data_enrichment_market.pending_market_selection_state(
        ["2330", "9999", "  "], ["2330", "2382"]
    )

    assert state == {
        "selected": ["2330"],
        "rejected": ["9999"],
        "state": "attention",
        "detail": "建議股票未在目前白名單：9999。已先選取可用股票：2330。",
        "action_label": "檢查股票範圍",
        "route_hint": "settings:scope",
    }


def test_market_operation_readiness_rows_show_pending_operation_and_ready_state() -> None:
    assert hasattr(data_enrichment_market, "market_operation_readiness_rows")
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330", "2382"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation="valuation_refresh",
    )

    assert [row["operation"] for row in rows] == [
        "market_refresh",
        "fundamentals_refresh",
        "valuation_refresh",
        "company_filings_fetch",
    ]
    assert rows[0] == {
        "operation": "market_refresh",
        "label": "刷新股價",
        "state": "ready",
        "selected": "no",
        "caption": "2 檔｜2026-06-01 → 2026-06-10",
        "disabled_reason": "可送出背景任務",
        "impact": "更新最新版報告的股價與成交量判讀。",
        "post_action_hint": "完成後回報告中心確認是否需要重跑。",
        "button_type": "secondary",
    }
    assert rows[2]["operation"] == "valuation_refresh"
    assert rows[2]["selected"] == "yes"
    assert rows[2]["button_type"] == "primary"
    assert rows[2]["disabled_reason"] == "可送出背景任務"


def test_market_operation_readiness_rows_explain_missing_tickers() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=[],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation=None,
    )

    assert {row["state"] for row in rows} == {"attention"}
    assert {row["disabled_reason"] for row in rows} == {"請先選擇至少一檔股票"}
    assert rows[0]["button_type"] == "primary"
    assert rows[1]["button_type"] == "secondary"


def test_market_operation_readiness_rows_explain_invalid_date_range_only_where_needed() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 10),
        market_end=date(2026, 6, 1),
        pending_operation="market_refresh",
    )

    by_operation = {row["operation"]: row for row in rows}
    assert by_operation["market_refresh"]["state"] == "attention"
    assert by_operation["market_refresh"]["disabled_reason"] == "起始日期不可晚於結束日期"
    assert by_operation["valuation_refresh"]["state"] == "attention"
    assert by_operation["valuation_refresh"]["disabled_reason"] == "起始日期不可晚於結束日期"
    assert by_operation["fundamentals_refresh"]["state"] == "ready"
    assert by_operation["fundamentals_refresh"]["disabled_reason"] == "可送出背景任務"
    assert by_operation["company_filings_fetch"]["state"] == "ready"
    assert by_operation["company_filings_fetch"]["disabled_reason"] == "可送出背景任務"


def test_market_operation_readiness_rows_block_when_worker_offline() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation="market_refresh",
        task_queue={"ready": True, "processing_ready": False, "worker_online": False},
    )

    assert {row["state"] for row in rows} == {"blocked"}
    assert {row["disabled_reason"] for row in rows} == {
        "背景任務未就緒，請先到維護頁檢查 Worker"
    }
    assert rows[0]["selected"] == "yes"
    assert rows[0]["button_type"] == "primary"


def test_market_operation_readiness_rows_show_queue_status_when_unavailable() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation=None,
        task_queue={"ready": False, "worker_online": True},
    )

    assert {row["state"] for row in rows} == {"blocked"}
    assert {row["disabled_reason"] for row in rows} == {
        "背景任務未就緒，請先到維護頁檢查 Redis/Celery"
    }


def test_render_market_data_tab_requires_confirmation_before_submit(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_data_enrichment_operation": "market_refresh"}
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []
            self.infos: list[str] = []
            self.markdowns: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def error(self, body: str) -> None:
            raise AssertionError(f"unexpected error: {body}")

        def info(self, body: str) -> None:
            self.infos.append(str(body))

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdowns.append(str(body))

        def metric(self, *_args, **_kwargs) -> None:
            return None

        def multiselect(self, _label: str, *, options: list[str], key: str):
            return list(self.session_state.get(key) or options[:1])

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "刷新股價" and not kwargs.get("disabled")

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_market, "st", fake_st)
    monkeypatch.setattr(data_enrichment_market, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(
        data_enrichment_market,
        "load_api_json_or_default",
        lambda endpoint, default, **_kwargs: (
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": True,
                    "worker_online": True,
                }
            }
            if endpoint == "/services/status"
            else default
        ),
    )
    monkeypatch.setattr(data_enrichment_market, "company_filing_runtime_rows", lambda _status: [])
    monkeypatch.setattr(
        data_enrichment_market,
        "company_filing_visual_rag_model_chain_rows",
        lambda _status: [],
    )
    monkeypatch.setattr(data_enrichment_market, "_latest_report_follow_up_context", lambda: ({}, {}))
    monkeypatch.setattr(data_enrichment_market, "_render_data_gap_action_map", lambda _items: None)
    monkeypatch.setattr(data_enrichment_market, "_render_cache_summary", lambda _tickers: None)
    monkeypatch.setattr(data_enrichment_market, "render_last_data_task_status", lambda **_kwargs: None)
    monkeypatch.setattr(
        data_enrichment_market,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_market.render_market_data_tab(["2330", "2382"])

    assert any(
        'class="market-handoff-banner is-ready"' in markdown
        and "已帶入刷新股價" in markdown
        and "確認背景任務後按「刷新股價」" in markdown
        for markdown in fake_st.markdowns
    )
    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出資料補強背景任務",
            "value": False,
            "key": "confirm_market_data_operation_submission",
        }
    ]
    assert any("避免誤觸刷新" in caption for caption in fake_st.captions)
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["刷新股價"]["disabled"] is True
    assert by_label["刷新 5 年財報"]["disabled"] is True
    assert by_label["刷新估值"]["disabled"] is True
    assert by_label["補抓公司文件"]["disabled"] is True
    assert submitted == []


def test_render_market_data_tab_submits_after_confirmation(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_data_enrichment_operation": "market_refresh"}
            self.buttons: list[dict[str, Any]] = []
            self.checkboxes: list[dict[str, Any]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def caption(self, _body: str) -> None:
            return None

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def error(self, body: str) -> None:
            raise AssertionError(f"unexpected error: {body}")

        def info(self, _body: str) -> None:
            return None

        def markdown(self, _body: str, **_kwargs) -> None:
            return None

        def metric(self, *_args, **_kwargs) -> None:
            return None

        def multiselect(self, _label: str, *, options: list[str], key: str):
            return list(self.session_state.get(key) or options[:1])

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return key == "confirm_market_data_operation_submission"

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "刷新股價" and not kwargs.get("disabled")

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_market, "st", fake_st)
    monkeypatch.setattr(data_enrichment_market, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(
        data_enrichment_market,
        "load_api_json_or_default",
        lambda endpoint, default, **_kwargs: (
            {
                "task_queue": {
                    "ready": True,
                    "processing_ready": True,
                    "worker_online": True,
                }
            }
            if endpoint == "/services/status"
            else default
        ),
    )
    monkeypatch.setattr(data_enrichment_market, "company_filing_runtime_rows", lambda _status: [])
    monkeypatch.setattr(
        data_enrichment_market,
        "company_filing_visual_rag_model_chain_rows",
        lambda _status: [],
    )
    monkeypatch.setattr(data_enrichment_market, "_latest_report_follow_up_context", lambda: ({}, {}))
    monkeypatch.setattr(data_enrichment_market, "_render_data_gap_action_map", lambda _items: None)
    monkeypatch.setattr(data_enrichment_market, "_render_cache_summary", lambda _tickers: None)
    monkeypatch.setattr(data_enrichment_market, "render_last_data_task_status", lambda **_kwargs: None)
    monkeypatch.setattr(
        data_enrichment_market,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_market.render_market_data_tab(["2330", "2382"])

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["刷新股價"]["disabled"] is False
    today = data_enrichment_market.today_taipei()
    assert submitted == [
        (
            (
                "market_refresh",
                {
                    "tickers": ["2330"],
                    "start_date": today.replace(day=1).isoformat(),
                    "end_date": today.isoformat(),
                },
            ),
            {
                "status_state_keys": data_enrichment_market.DATA_TASK_STATUS_STATE_KEYS,
                "success_message": "已送出股價刷新背景任務",
                "error_message": "股價刷新任務送出失敗",
            },
        )
    ]


def test_manual_news_import_requires_confirmation_before_submit(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "匯入新聞/研究摘要" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def date_input(self, _label: str, *, value):
            return value

        def success(self, body: str) -> None:
            raise AssertionError(f"unexpected success: {body}")

        def text_area(self, label: str, **_kwargs):
            return "台積電法說會摘要" if label == "內文" else ""

        def text_input(self, label: str, *, value: str = ""):
            if label == "標題":
                return "法說會摘要"
            return value

    fake_st = FakeStreamlit()
    posted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "api_post",
        lambda *args, **kwargs: posted.append((args, kwargs)) or {"document_id": 99},
    )

    data_enrichment_manual._render_manual_news_form()

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會直接寫入新聞/研究摘要資料庫",
            "value": False,
            "key": "confirm_manual_news_import",
        }
    ]
    assert any("避免誤觸手動匯入" in caption for caption in fake_st.captions)
    assert fake_st.buttons == [
        {"label": "匯入新聞/研究摘要", "type": "primary", "disabled": True}
    ]
    assert posted == []


def test_manual_news_import_submits_after_confirmation(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.successes: list[str] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "匯入新聞/研究摘要" and not kwargs.get("disabled")

        def caption(self, _body: str) -> None:
            return None

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key == "confirm_manual_news_import"

        def date_input(self, _label: str, *, value):
            return value

        def error(self, body: str) -> None:
            raise AssertionError(f"unexpected error: {body}")

        def success(self, body: str) -> None:
            self.successes.append(str(body))

        def text_area(self, label: str, **_kwargs):
            return "台積電法說會摘要" if label == "內文" else ""

        def text_input(self, label: str, *, value: str = ""):
            if label == "標題":
                return "法說會摘要"
            if label == "URL":
                return "https://example.com/news"
            return value

    fake_st = FakeStreamlit()
    posted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "api_post",
        lambda *args, **kwargs: posted.append((args, kwargs)) or {"document_id": 99},
    )

    data_enrichment_manual._render_manual_news_form()

    assert fake_st.buttons == [
        {"label": "匯入新聞/研究摘要", "type": "primary", "disabled": False}
    ]
    assert posted == [
        (
            (
                "/ingest/manual",
                {
                    "title": "法說會摘要",
                    "text": "台積電法說會摘要",
                    "publisher": "manual",
                    "published_at": data_enrichment_manual.today_taipei().isoformat(),
                    "url": "https://example.com/news",
                },
            ),
            {},
        )
    ]
    assert fake_st.successes == ["已匯入：99"]


def test_manual_company_filing_import_requires_confirmation(monkeypatch) -> None:
    class Company:
        ticker = "2330"
        name = "台積電"

    class Whitelist:
        def companies(self):
            return [Company()]

    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "匯入公司文件" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def selectbox(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

        def success(self, body: str) -> None:
            raise AssertionError(f"unexpected success: {body}")

        def text_area(self, label: str, **_kwargs):
            return "公司文件文字" if label == "文件文字" else ""

        def text_input(self, label: str, *, value: str = "", key: str | None = None):
            if label == "文件標題":
                return "法說會簡報"
            return value

        def warning(self, body: str) -> None:
            raise AssertionError(f"unexpected warning: {body}")

    fake_st = FakeStreamlit()
    posted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "api_post",
        lambda *args, **kwargs: posted.append((args, kwargs)) or {"document_id": 100},
    )

    data_enrichment_manual._render_company_filing_form(Whitelist(), ["2330"])

    assert {
        "label": "我了解這會直接寫入公司文件資料庫",
        "value": False,
        "key": "confirm_manual_company_filing_import",
    } in fake_st.checkboxes
    assert any("避免誤觸公司文件匯入" in caption for caption in fake_st.captions)
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["匯入公司文件"]["disabled"] is True
    assert posted == []


def test_manual_company_filing_import_submits_after_confirmation(monkeypatch) -> None:
    class Company:
        ticker = "2330"
        name = "台積電"

    class Whitelist:
        def companies(self):
            return [Company()]

    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.successes: list[str] = []
            self.captions: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "匯入公司文件" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key == "confirm_manual_company_filing_import"

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def error(self, body: str) -> None:
            raise AssertionError(f"unexpected error: {body}")

        def selectbox(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

        def success(self, body: str) -> None:
            self.successes.append(str(body))

        def text_area(self, label: str, **_kwargs):
            return "公司文件文字" if label == "文件文字" else ""

        def text_input(self, label: str, *, value: str = "", key: str | None = None):
            if label == "文件標題":
                return "法說會簡報"
            return value

        def warning(self, body: str) -> None:
            raise AssertionError(f"unexpected warning: {body}")

    fake_st = FakeStreamlit()
    posted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "api_post",
        lambda *args, **kwargs: posted.append((args, kwargs))
        or {"document_id": 100, "source_tier": "manual", "quality_score": 80},
    )

    data_enrichment_manual._render_company_filing_form(Whitelist(), ["2330"])

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["匯入公司文件"]["disabled"] is False
    assert posted == [
        (
            (
                "/company-filings/manual",
                {
                    "ticker": "2330",
                    "company_name": "台積電",
                    "document_type": "annual_report",
                    "title": "法說會簡報",
                    "text": "公司文件文字",
                    "publisher": "公司 IR / MOPS",
                    "published_at": data_enrichment_manual.today_taipei().isoformat(),
                    "url": None,
                },
            ),
            {},
        )
    ]
    assert fake_st.successes == ["已匯入公司文件：100"]
    assert any("來源分級：manual；品質分數：80" in caption for caption in fake_st.captions)


def test_company_filing_url_import_requires_confirmation(monkeypatch) -> None:
    class Company:
        ticker = "2330"
        name = "台積電"

    class Whitelist:
        def companies(self):
            return [Company()]

    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def selectbox(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

        def text_area(self, label: str, **_kwargs):
            return "" if label == "文件文字" else ""

        def text_input(self, label: str, *, value: str = "", key: str | None = None):
            if label == "文件 URL":
                return "https://example.com/ir.pdf"
            return value

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "從 URL 抓取並匯入" and not kwargs.get("disabled")

        def success(self, body: str) -> None:
            raise AssertionError(f"unexpected success: {body}")

        def warning(self, body: str) -> None:
            raise AssertionError(f"unexpected warning: {body}")

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_manual._render_company_filing_form(Whitelist(), ["2330"])

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出 URL 公司文件匯入背景任務",
            "value": False,
            "key": "confirm_company_filing_url_import",
        }
    ]
    assert any("避免誤觸 URL 匯入" in caption for caption in fake_st.captions)
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["從 URL 抓取並匯入"]["disabled"] is True
    assert submitted == []


def test_company_filing_url_import_submits_after_confirmation(monkeypatch) -> None:
    class Company:
        ticker = "2330"
        name = "台積電"

    class Whitelist:
        def companies(self):
            return [Company()]

    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def caption(self, _body: str) -> None:
            return None

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key == "confirm_company_filing_url_import"

        def columns(self, count: int):
            return [self for _ in range(count)]

        def date_input(self, _label: str, *, value, key: str):
            return value

        def selectbox(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

        def text_area(self, label: str, **_kwargs):
            return "" if label == "文件文字" else ""

        def text_input(self, label: str, *, value: str = "", key: str | None = None):
            if label == "文件 URL":
                return "https://example.com/ir.pdf"
            return value

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "從 URL 抓取並匯入" and not kwargs.get("disabled")

        def success(self, body: str) -> None:
            raise AssertionError(f"unexpected success: {body}")

        def warning(self, body: str) -> None:
            raise AssertionError(f"unexpected warning: {body}")

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_manual, "st", fake_st)
    monkeypatch.setattr(
        data_enrichment_manual,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_manual._render_company_filing_form(Whitelist(), ["2330"])

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["從 URL 抓取並匯入"]["disabled"] is False
    assert submitted == [
        (
            (
                "company_filing_from_url",
                {
                    "url": "https://example.com/ir.pdf",
                    "ticker": "2330",
                    "company_name": "台積電",
                    "document_type": "annual_report",
                    "publisher": "公司 IR / MOPS",
                    "published_at": data_enrichment_manual.today_taipei().isoformat(),
                },
            ),
            {
                "status_state_keys": data_enrichment_manual.DATA_TASK_STATUS_STATE_KEYS,
                "success_message": "已送出 URL 公司文件匯入背景任務",
                "error_message": "URL 公司文件匯入任務送出失敗",
            },
        )
    ]


def test_rss_fetch_requires_confirmation_before_submit(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "抓取 RSS" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def dataframe(self, *_args, **_kwargs) -> None:
            return None

        def number_input(self, *_args, **_kwargs):
            return 10

        def text_input(self, label: str, *, value: str = ""):
            if label == "RSS URL":
                return "https://example.com/rss.xml"
            return value

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_rss, "st", fake_st)
    monkeypatch.setattr(data_enrichment_rss, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(data_enrichment_rss, "load_api_json_or_default", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(data_enrichment_rss, "render_last_data_task_status", lambda **_kwargs: None)
    monkeypatch.setattr(
        data_enrichment_rss,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_rss.render_rss_ingest_tab()

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出 RSS 抓取背景任務",
            "value": False,
            "key": "confirm_rss_fetch_submission",
        }
    ]
    assert any("避免誤觸 RSS 抓取" in caption for caption in fake_st.captions)
    assert fake_st.buttons == [
        {"label": "抓取 RSS", "type": "primary", "disabled": True}
    ]
    assert submitted == []


def test_rss_fetch_submits_after_confirmation(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.buttons: list[dict[str, Any]] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "抓取 RSS" and not kwargs.get("disabled")

        def caption(self, _body: str) -> None:
            return None

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key == "confirm_rss_fetch_submission"

        def dataframe(self, *_args, **_kwargs) -> None:
            return None

        def number_input(self, *_args, **_kwargs):
            return 10

        def text_input(self, label: str, *, value: str = ""):
            if label == "RSS URL":
                return "https://example.com/rss.xml"
            return value

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(data_enrichment_rss, "st", fake_st)
    monkeypatch.setattr(data_enrichment_rss, "render_section_header", lambda *_args: None)
    monkeypatch.setattr(data_enrichment_rss, "load_api_json_or_default", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(data_enrichment_rss, "render_last_data_task_status", lambda **_kwargs: None)
    monkeypatch.setattr(
        data_enrichment_rss,
        "submit_data_operation_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    data_enrichment_rss.render_rss_ingest_tab()

    assert fake_st.buttons == [
        {"label": "抓取 RSS", "type": "primary", "disabled": False}
    ]
    assert submitted == [
        (
            (
                "feed_fetch",
                {
                    "url": "https://example.com/rss.xml",
                    "publisher": "rss",
                    "limit": 10,
                },
            ),
            {
                "status_state_keys": data_enrichment_rss.DATA_TASK_STATUS_STATE_KEYS,
                "success_message": "已送出 RSS 抓取背景任務",
                "error_message": "RSS 抓取任務送出失敗",
            },
        )
    ]


def test_market_cache_operator_summary_flags_stale_and_missing_cache() -> None:
    rows = market_cache_operator_summary(
        {
            "tickers": ["2330", "2382"],
            "market_snapshots": [
                {
                    "ticker": "2330",
                    "trade_date": "2026-06-05",
                    "source": "FinMind TaiwanStockPrice; cached-stale",
                }
            ],
            "valuations": [
                {"ticker": "2330", "trade_date": "2026-06-04", "source": "FinMind"},
                {"ticker": "2382", "trade_date": "2026-06-04", "source": "FinMind"},
            ],
            "company_filings": [],
            "financial_metric_count": 0,
        }
    )

    assert rows == [
        {
            "title": "股價快取",
            "value": "1 / 2 檔",
            "state": "attention",
            "caption": "含快取救援資料，缺 1 檔；建議刷新股價。",
            "action_label": "刷新股價",
        },
        {
            "title": "估值快取",
            "value": "2 / 2 檔",
            "state": "ready",
            "caption": "最新交易日 2026-06-04。",
            "action_label": "可沿用",
        },
        {
            "title": "財報快取",
            "value": "0 筆",
            "state": "attention",
            "caption": "尚無財報三表科目快取；建議刷新 5 年財報。",
            "action_label": "刷新 5 年財報",
        },
        {
            "title": "公司文件",
            "value": "0 筆",
            "state": "attention",
            "caption": "尚無公司文件快取；若報告缺法說或公開資訊，請補抓公司文件。",
            "action_label": "補抓公司文件",
        },
    ]


def test_company_filing_runtime_rows_hide_when_service_status_missing() -> None:
    assert company_filing_runtime_rows({}) == []


def test_company_filing_runtime_rows_show_visual_rag_runtime_model() -> None:
    rows = company_filing_runtime_rows(
        {
            "company_filings": {
                "pdf_parser": "auto",
                "pdf_extract_tables": True,
                "pdf_parser_available": True,
                "pdf_table_parser_available": True,
                "pdf_parser_dependencies": {},
                "visual_rag_runtime_available": True,
                "visual_rag_model": "gemini-3.5-flash",
                "visual_rag_runtime_model": "openai/gpt-4o-mini",
                "visual_rag_runtime": {
                    "runtime_model": "openai/gpt-4o-mini",
                    "fallback_reason": None,
                },
            }
        }
    )

    visual_row = next(row for row in rows if row["能力"] == "Visual RAG")
    assert visual_row["狀態"] == "ready"
    assert visual_row["目前"] == "openai/gpt-4o-mini"


def test_company_filing_visual_rag_model_chain_rows_surface_quota_and_rejections() -> None:
    rows = company_filing_visual_rag_model_chain_rows(
        {
            "company_filings": {
                "visual_rag_runtime_model": "gemini-3.5-flash",
                "visual_rag_model_chain": {
                    "quota_hard_routing_enabled": True,
                    "candidate_rows": [
                        {
                            "rank": 1,
                            "model": "gemini-3.5-flash",
                            "model_key": "gemini-3.5-flash",
                            "vision_supported": True,
                            "key_configured": True,
                            "request_budget": 250,
                            "token_budget": None,
                            "routing_tier": "preferred_visual_rag_model",
                        },
                        {
                            "rank": 2,
                            "model": "imagen-4-ultra-generate",
                            "model_key": "imagen-4-ultra-generate",
                            "vision_supported": False,
                            "key_configured": None,
                            "request_budget": None,
                            "token_budget": None,
                            "routing_tier": "fallback",
                        },
                        {
                            "rank": 3,
                            "model": "gemma-4-31b-it",
                            "model_key": "gemma-4-31b-it",
                            "vision_supported": False,
                            "key_configured": None,
                            "request_budget": 14400,
                            "token_budget": None,
                            "routing_tier": "high_quota_text_fallback_excluded_from_vision",
                        },
                    ],
                    "rejected_candidates": [
                        {
                            "rank": 2,
                            "model": "imagen-4-ultra-generate",
                            "model_key": "imagen-4-ultra-generate",
                            "rejection_reason": "non_vision_media_embedding_or_live_model",
                        },
                        {
                            "rank": 3,
                            "model": "gemma-4-31b-it",
                            "model_key": "gemma-4-31b-it",
                            "rejection_reason": "text_only_gemma_fallback",
                        },
                    ],
                }
            }
        }
    )

    assert rows == [
        {
            "順位": 1,
            "模型": "gemini-3.5-flash",
            "Vision": "yes",
            "Runtime": "selected",
            "Key": "ready",
            "每日請求額度": 250,
            "Token 額度": "-",
            "類型": "preferred_visual_rag_model",
            "額度治理": "hard_routing",
            "狀態/排除原因": "vision_candidate",
        },
        {
            "順位": 2,
            "模型": "imagen-4-ultra-generate",
            "Vision": "excluded",
            "Runtime": "-",
            "Key": "-",
            "每日請求額度": "-",
            "Token 額度": "-",
            "類型": "fallback",
            "額度治理": "hard_routing",
            "狀態/排除原因": "non_vision_media_embedding_or_live_model",
        },
        {
            "順位": 3,
            "模型": "gemma-4-31b-it",
            "Vision": "excluded",
            "Runtime": "-",
            "Key": "-",
            "每日請求額度": 14400,
            "Token 額度": "-",
            "類型": "high_quota_text_fallback_excluded_from_vision",
            "額度治理": "hard_routing",
            "狀態/排除原因": "text_only_gemma_fallback",
        },
    ]


def test_company_filing_visual_rag_model_chain_rows_hide_when_missing() -> None:
    assert company_filing_visual_rag_model_chain_rows({}) == []
