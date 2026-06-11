from __future__ import annotations

import importlib
from pathlib import Path


def _cache_module():
    return importlib.import_module("app.ui.data_enrichment_market_cache")


def test_market_cache_panel_module_owns_cache_endpoint_and_tabs() -> None:
    module = _cache_module()
    source = Path("app/ui/data_enrichment_market_cache.py").read_text()

    assert callable(module.render_market_cache_panel)
    assert callable(module.render_market_cache_operator_summary)
    assert '"/market/cache-summary?tickers="' in source
    assert 'st.tabs(["股價快取", "估值快取", "公司文件"])' in source
    assert "cached_snapshots = cache_summary.get(" in source
    assert "market_cache_operator_summary(cache_summary" in source


def test_market_tab_delegates_cache_panel_without_owning_cache_tables() -> None:
    _cache_module()
    source = Path("app/ui/data_enrichment_market.py").read_text()

    assert "from app.ui.data_enrichment_market_cache import render_market_cache_panel" in source
    assert "render_market_cache_panel(allowed_tickers)" in source
    assert '"/market/cache-summary?tickers="' not in source
    assert 'st.tabs(["股價快取", "估值快取", "公司文件"])' not in source
    assert "cached_snapshots = cache_summary.get(" not in source
