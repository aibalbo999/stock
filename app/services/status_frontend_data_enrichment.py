from __future__ import annotations

from app.services.status_frontend_data_enrichment_runtime import (
    frontend_data_enrichment_runtime_status,
)
from app.services.status_frontend_data_enrichment_tabs import (
    frontend_data_enrichment_tabs_status,
)
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_data_enrichment_status(source_context: FrontendSourceContext) -> dict:
    operator_decisions_source = source_context.ui_sources["operator_decisions.py"]
    operator_decision_support_source = source_context.ui_sources[
        "operator_decision_support.py"
    ]
    data_gap_actions_source = source_context.ui_sources["data_gap_actions.py"]
    operator_routes_source = source_context.ui_sources["operator_routes.py"]
    data_enrichment_source = source_context.ui_sources["data_enrichment.py"]
    data_enrichment_common_source = source_context.ui_sources["data_enrichment_common.py"]
    data_enrichment_common_view_source = source_context.ui_sources[
        "data_enrichment_common_view.py"
    ]
    data_enrichment_market_source = source_context.ui_sources["data_enrichment_market.py"]
    data_enrichment_market_cache_source = source_context.ui_sources[
        "data_enrichment_market_cache.py"
    ]
    data_enrichment_market_presenter_source = source_context.ui_sources[
        "data_enrichment_market_presenter.py"
    ]
    data_enrichment_market_view_source = source_context.ui_sources[
        "data_enrichment_market_view.py"
    ]
    data_enrichment_manual_source = source_context.ui_sources["data_enrichment_manual.py"]
    data_enrichment_manual_presenter_source = source_context.ui_sources[
        "data_enrichment_manual_presenter.py"
    ]
    data_enrichment_rss_source = source_context.ui_sources["data_enrichment_rss.py"]
    return {
        "frontend_data_enrichment_status_extracted": True,
        "frontend_data_enrichment_status_path": (
            "app/services/status_frontend_data_enrichment.py"
        ),
        "ui_data_enrichment_common_view_extracted": (
            "from app.ui.data_enrichment_common_view import ("
            in data_enrichment_common_source
            and "import streamlit" not in data_enrichment_common_view_source
            and "def allowlist_scope_summary_html(" in data_enrichment_common_view_source
            and "def data_task_followup_summary_html(" in data_enrichment_common_view_source
            and "def data_ingest_submission_summary_html("
            in data_enrichment_common_view_source
            and 'class="allowlist-scope-summary' in data_enrichment_common_view_source
            and 'class="data-task-followup-summary' in data_enrichment_common_view_source
            and 'class="data-ingest-submission-summary' in data_enrichment_common_view_source
            and 'class="allowlist-scope-summary' not in data_enrichment_common_source
            and 'class="data-ingest-submission-summary' not in data_enrichment_common_source
        ),
        "ui_operator_data_gap_prefill_enabled": (
            "from app.ui.data_gap_actions import data_gap_action_items"
            in operator_decision_support_source
            and "def primary_data_gap_action(" in operator_decision_support_source
            and "from app.ui.operator_decision_support import ("
            in operator_decisions_source
            and 'data_gap_action.get("route_hint")' in operator_decisions_source
            and 'f"data_enrichment:{operation}:{ticker_suffix}"' in data_gap_actions_source
            and "def _data_enrichment_route_hint(" in data_gap_actions_source
            and '"pending_data_enrichment_operation": operation' in operator_routes_source
            and '"pending_data_enrichment_tickers"' in operator_routes_source
            and "pending_data_enrichment_operation" in data_enrichment_market_source
            and "pending_data_enrichment_tickers" in data_enrichment_market_source
        ),
        "ui_data_enrichment_market_presenter_extracted": (
            "from app.ui.data_enrichment_market_presenter import (" in data_enrichment_market_source
            and "import streamlit" not in data_enrichment_market_presenter_source
            and "def market_operation_readiness_rows(" in data_enrichment_market_presenter_source
            and "def market_submission_preflight_summary("
            in data_enrichment_market_presenter_source
            and "def market_cache_operator_summary(" in data_enrichment_market_presenter_source
        ),
        "ui_data_enrichment_market_view_extracted": (
            "from app.ui.data_enrichment_market_view import ("
            in data_enrichment_market_source
            and "import streamlit" not in data_enrichment_market_view_source
            and "def data_gap_action_map_html(" in data_enrichment_market_view_source
            and "def data_gap_action_controls_html(" in data_enrichment_market_view_source
            and "def market_operation_readiness_html(" in data_enrichment_market_view_source
            and "def market_submission_summary_html(" in data_enrichment_market_view_source
            and "def market_action_impact_grid_html(" in data_enrichment_market_view_source
            and "def market_allowlist_warning_html(" in data_enrichment_market_view_source
            and "def market_cache_operator_summary_html("
            in data_enrichment_market_view_source
            and 'class="action-impact-grid' in data_enrichment_market_view_source
            and 'class="data-gap-action-controls' in data_enrichment_market_view_source
            and 'class="market-allowlist-warning' in data_enrichment_market_view_source
            and 'class="action-impact-grid' not in data_enrichment_market_source
            and 'class="market-allowlist-warning' not in data_enrichment_market_source
            and "def _data_gap_action_card_html(" not in data_enrichment_market_source
            and "def _market_operation_readiness_card_html("
            not in data_enrichment_market_source
            and "def _market_cache_card_html(" not in data_enrichment_market_source
        ),
        "ui_data_enrichment_market_cache_panel_extracted": (
            "from app.ui.data_enrichment_market_cache import render_market_cache_panel"
            in data_enrichment_market_source
            and "def render_market_cache_panel(" in data_enrichment_market_cache_source
            and "render_market_cache_panel(allowed_tickers)" in data_enrichment_market_source
            and '"/market/cache-summary?tickers="' in data_enrichment_market_cache_source
            and '"/market/cache-summary?tickers="' not in data_enrichment_market_source
            and 'st.tabs(["股價快取", "估值快取", "公司文件"])'
            in data_enrichment_market_cache_source
            and 'st.tabs(["股價快取", "估值快取", "公司文件"])'
            not in data_enrichment_market_source
        ),
        "ui_data_enrichment_manual_presenter_extracted": (
            "from app.ui.data_enrichment_manual_presenter import ("
            in data_enrichment_manual_source
            and "import streamlit" not in data_enrichment_manual_presenter_source
            and "def manual_news_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "def company_filing_text_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "def company_filing_url_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "def company_filing_type_label(" in data_enrichment_manual_presenter_source
            and "def manual_news_preflight_summary(" not in data_enrichment_manual_source
            and "def company_filing_text_preflight_summary(" not in data_enrichment_manual_source
            and "def company_filing_url_preflight_summary(" not in data_enrichment_manual_source
        ),
        "ui_data_enrichment_pending_operation_button_priority_enabled": (
            "def market_data_operation_button_type(" in data_enrichment_market_presenter_source
            and "MARKET_DATA_OPERATIONS = {" in data_enrichment_market_presenter_source
            and "type=market_data_operation_button_type(pending_operation, \"market_refresh\")"
            in data_enrichment_market_source
            and (
                "type=market_data_operation_button_type("
                "pending_operation, \"company_filings_fetch\""
            )
            in data_enrichment_market_source
            and "return \"primary\" if pending == operation else \"secondary\""
            in data_enrichment_market_presenter_source
        ),
        "ui_data_enrichment_pending_handoff_banner_enabled": (
            "def pending_market_handoff_summary(" in data_enrichment_market_presenter_source
            and "def _render_pending_market_handoff(" in data_enrichment_market_source
            and "def pending_market_handoff_html(" in data_enrichment_market_view_source
            and "pending_market_handoff_summary(" in data_enrichment_market_source
            and 'class="market-handoff-banner' in data_enrichment_market_view_source
            and "補強導引" in data_enrichment_market_view_source
            and "先處理白名單提醒，再" in data_enrichment_market_presenter_source
            and '"next_step": f"{next_prefix}確認背景任務後按'
            in data_enrichment_market_presenter_source
        ),
        "ui_data_enrichment_operation_readiness_enabled": (
            "def market_operation_readiness_rows(" in data_enrichment_market_presenter_source
            and "def _render_market_operation_readiness(" in data_enrichment_market_source
            and "def market_operation_readiness_card_html("
            in data_enrichment_market_view_source
            and 'class="market-operation-readiness"' in data_enrichment_market_view_source
            and "執行前檢查" in data_enrichment_market_view_source
            and "可送出背景任務" in data_enrichment_market_presenter_source
            and "disabled_reason" in data_enrichment_market_presenter_source
        ),
        "ui_data_enrichment_submission_preflight_summary_enabled": (
            "def market_submission_preflight_summary(" in data_enrichment_market_presenter_source
            and "def _render_market_submission_summary(" in data_enrichment_market_source
            and "def market_submission_summary_html(" in data_enrichment_market_view_source
            and "market_submission_preflight_summary(" in data_enrichment_market_source
            and 'class="market-submission-summary' in data_enrichment_market_view_source
            and "送出前摘要" in data_enrichment_market_view_source
            and "避免重複送出" in data_enrichment_market_presenter_source
            and "外部資料額度" in data_enrichment_market_presenter_source
            and "market_operation_confirmed" in data_enrichment_market_source
        ),
        "ui_data_enrichment_task_queue_guard_enabled": (
            "task_queue_status = _task_queue_status_from_service_snapshot(service_snapshot)"
            in data_enrichment_market_source
            and "task_queue=task_queue_status" in data_enrichment_market_source
            and "task_queue_blocks_submission = bool(_task_queue_block_reason(task_queue_status))"
            in data_enrichment_market_source
            and "def _task_queue_status_from_service_snapshot("
            in data_enrichment_market_presenter_source
            and "def _task_queue_block_reason(" in data_enrichment_market_presenter_source
            and "背景任務未就緒，請先到維護頁檢查背景執行器"
            in data_enrichment_market_presenter_source
            and "背景任務未就緒，請先到維護頁檢查背景任務佇列"
            in data_enrichment_market_presenter_source
            and "背景任務未就緒，請先到維護頁檢查 Worker"
            not in data_enrichment_market_presenter_source
            and "背景任務未就緒，請先到維護頁檢查 Redis/Celery"
            not in data_enrichment_market_presenter_source
        ),
        "ui_data_enrichment_market_submission_confirmation_enabled": (
            "market_operation_confirmed = st.checkbox(" in data_enrichment_market_source
            and 'key="confirm_market_data_operation_submission"'
            in data_enrichment_market_source
            and "我了解這會送出資料補強背景任務" in data_enrichment_market_source
            and "避免誤觸刷新" in data_enrichment_market_source
            and "or not market_operation_confirmed" in data_enrichment_market_source
        ),
        "ui_manual_news_import_confirmation_enabled": (
            "manual_news_confirmed = st.checkbox(" in data_enrichment_manual_source
            and 'key="confirm_manual_news_import"' in data_enrichment_manual_source
            and "我了解這會直接寫入新聞/研究摘要資料庫" in data_enrichment_manual_source
            and "避免誤觸手動匯入" in data_enrichment_manual_source
            and "disabled=not manual_news_ready or not manual_news_confirmed"
            in data_enrichment_manual_source
            and 'api_post(\n                "/ingest/manual"' in data_enrichment_manual_source
        ),
        "ui_manual_company_filing_import_confirmation_enabled": (
            "filing_text_confirmed = st.checkbox(" in data_enrichment_manual_source
            and 'key="confirm_manual_company_filing_import"'
            in data_enrichment_manual_source
            and "我了解這會直接寫入公司文件資料庫" in data_enrichment_manual_source
            and "避免誤觸公司文件匯入" in data_enrichment_manual_source
            and "disabled=not filing_text_ready or not filing_text_confirmed"
            in data_enrichment_manual_source
            and 'api_post(\n            "/company-filings/manual"'
            in data_enrichment_manual_source
        ),
        "ui_company_filing_url_import_confirmation_enabled": (
            "filing_url_confirmed = st.checkbox(" in data_enrichment_manual_source
            and 'key="confirm_company_filing_url_import"' in data_enrichment_manual_source
            and "我了解這會送出 URL 公司文件匯入背景任務" in data_enrichment_manual_source
            and "避免誤觸 URL 匯入" in data_enrichment_manual_source
            and "disabled=not filing_url_ready or not filing_url_confirmed"
            in data_enrichment_manual_source
            and 'submit_data_operation_task(\n            "company_filing_from_url"'
            in data_enrichment_manual_source
        ),
        "ui_manual_data_ingest_preflight_summary_enabled": (
            "def render_data_ingest_submission_summary(" in data_enrichment_common_source
            and 'class="data-ingest-submission-summary'
            in data_enrichment_common_view_source
            and "資料送出前摘要" in data_enrichment_common_view_source
            and "def manual_news_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "def company_filing_text_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "def company_filing_url_preflight_summary("
            in data_enrichment_manual_presenter_source
            and "render_data_ingest_submission_summary(" in data_enrichment_manual_source
            and "不會消耗 AI 額度" in data_enrichment_manual_presenter_source
            and "背景任務會排隊執行" in data_enrichment_manual_presenter_source
        ),
        "ui_rss_fetch_confirmation_enabled": (
            "rss_fetch_confirmed = st.checkbox(" in data_enrichment_rss_source
            and 'key="confirm_rss_fetch_submission"' in data_enrichment_rss_source
            and "我了解這會送出 RSS 抓取背景任務" in data_enrichment_rss_source
            and "避免誤觸 RSS 抓取" in data_enrichment_rss_source
            and "disabled=not feed_ready or not rss_fetch_confirmed"
            in data_enrichment_rss_source
            and 'submit_data_operation_task(\n            "feed_fetch"'
            in data_enrichment_rss_source
        ),
        "ui_rss_data_ingest_preflight_summary_enabled": (
            "def render_data_ingest_submission_summary(" in data_enrichment_common_source
            and "def rss_fetch_preflight_summary(" in data_enrichment_rss_source
            and "render_data_ingest_submission_summary(" in data_enrichment_rss_source
            and "背景任務會排隊抓取與匯入文本" in data_enrichment_rss_source
            and "完成前不要重複送出同一個 RSS" in data_enrichment_rss_source
        ),
        "ui_data_enrichment_allowlist_scope_summary_enabled": (
            "from app.ui.data_enrichment_common import render_allowlist_scope_summary"
            in data_enrichment_source
            and "render_allowlist_scope_summary(whitelist, allowed_tickers)"
            in data_enrichment_source
            and "def allowlist_scope_summary(" in data_enrichment_common_source
            and "def render_allowlist_scope_summary(" in data_enrichment_common_source
            and 'class="allowlist-scope-summary' in data_enrichment_common_view_source
            and "目前使用靜態白名單" in data_enrichment_common_source
            and "目前使用動態候選白名單" in data_enrichment_common_source
            and "系統設定的股票範圍" in data_enrichment_common_source
            and '"route_hint": "settings:scope"' in data_enrichment_common_source
        ),
        "ui_data_enrichment_pending_ticker_allowlist_guard_enabled": (
            "def pending_market_selection_state(" in data_enrichment_market_presenter_source
            and "def _normalized_pending_tickers(" in data_enrichment_market_presenter_source
            and "pending_market_selection_state(pending_tickers, allowed_tickers)"
            in data_enrichment_market_source
            and '"pending_market_selection_state"' in data_enrichment_market_source
            and "建議股票未在目前白名單" in data_enrichment_market_presenter_source
            and '"route_hint": "settings:scope"' in data_enrichment_market_presenter_source
            and 'class="market-allowlist-warning' in data_enrichment_market_view_source
            and 'key="market_pending_allowlist_route"' in data_enrichment_market_source
            and 'if route == "settings:scope":' in operator_routes_source
        ),
        "ui_market_cache_operator_summary_enabled": (
            "def market_cache_operator_summary(" in data_enrichment_market_presenter_source
            and "def render_market_cache_operator_summary("
            in data_enrichment_market_cache_source
            and "market_cache_operator_summary(cache_summary"
            in data_enrichment_market_cache_source
            and 'class="market-cache-readiness"' in data_enrichment_market_view_source
            and "cached-stale" in data_enrichment_market_presenter_source
            and "市場快取新鮮度" in data_enrichment_market_view_source
        ),
        **frontend_data_enrichment_tabs_status(source_context),
        **frontend_data_enrichment_runtime_status(source_context),
    }
