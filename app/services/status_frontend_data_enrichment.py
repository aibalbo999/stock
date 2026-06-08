from __future__ import annotations

from pathlib import Path

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_data_enrichment_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    data_enrichment_runtime_source = ui_sources["data_enrichment_runtime.py"]
    data_enrichment_source = source_context.data_enrichment_source
    company_filing_runtime_rows_service_source = _read_text(
        root / "app" / "services" / "company_filing_runtime_rows.py"
    )
    return {
        "frontend_data_enrichment_status_extracted": True,
        "frontend_data_enrichment_status_path": (
            "app/services/status_frontend_data_enrichment.py"
        ),
        "ui_company_filing_runtime_panel_enabled": "def company_filing_runtime_rows("
        in data_enrichment_source
        and "from app.services.company_filing_runtime_rows import"
        in data_enrichment_runtime_source
        and "def company_filing_runtime_rows(" in company_filing_runtime_rows_service_source
        and (
            'api_get("/services/status"' in data_enrichment_source
            or 'load_api_json_or_default(\n        "/services/status"' in data_enrichment_source
        )
        and "API_TASK_PREFLIGHT_TIMEOUT_SECONDS" in data_enrichment_source
        and "公司文件補抓能力" in data_enrichment_source
        and "visual_rag_runtime_available" in company_filing_runtime_rows_service_source
        and "structured_api_configured" in company_filing_runtime_rows_service_source
        and "playwright_render_configured" in company_filing_runtime_rows_service_source,
        "ui_visual_rag_model_chain_panel_enabled": (
            "def company_filing_visual_rag_model_chain_rows(" in data_enrichment_source
        )
        and "def company_filing_visual_rag_model_chain_rows("
        in company_filing_runtime_rows_service_source
        and "visual_rag_model_chain" in company_filing_runtime_rows_service_source
        and "Visual RAG 模型鏈" in ui_source
        and "Visual RAG / PDF 圖片解析模型鏈" in ui_source,
        "ui_data_enrichment_tabs_extracted": (ui_dir / "data_enrichment_market.py").exists()
        and (ui_dir / "data_enrichment_manual.py").exists()
        and (ui_dir / "data_enrichment_rss.py").exists()
        and (ui_dir / "data_enrichment_runtime.py").exists()
        and "def render_market_data_tab(" in data_enrichment_source
        and "def render_manual_ingest_tab(" in data_enrichment_source
        and "def render_rss_ingest_tab(" in data_enrichment_source
        and "def company_filing_runtime_rows(" in data_enrichment_source
        and "render_market_data_tab(allowed_tickers)" in data_enrichment_source
        and "render_manual_ingest_tab(whitelist, allowed_tickers)" in data_enrichment_source
        and "render_rss_ingest_tab()" in data_enrichment_source,
        "ui_data_enrichment_module_paths": [
            "app/ui/data_enrichment_market.py",
            "app/ui/data_enrichment_manual.py",
            "app/ui/data_enrichment_rss.py",
            "app/ui/data_enrichment_runtime.py",
            "app/services/company_filing_runtime_rows.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
