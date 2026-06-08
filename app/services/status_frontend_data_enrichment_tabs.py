from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext

DATA_ENRICHMENT_MODULE_PATHS = [
    "app/ui/data_enrichment_market.py",
    "app/ui/data_enrichment_manual.py",
    "app/ui/data_enrichment_rss.py",
    "app/ui/data_enrichment_runtime.py",
    "app/services/company_filing_runtime_rows.py",
]


def frontend_data_enrichment_tabs_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    data_enrichment_source = source_context.data_enrichment_source
    return {
        "frontend_data_enrichment_tabs_status_extracted": True,
        "frontend_data_enrichment_tabs_status_path": (
            "app/services/status_frontend_data_enrichment_tabs.py"
        ),
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
        "ui_data_enrichment_module_paths": DATA_ENRICHMENT_MODULE_PATHS,
    }
