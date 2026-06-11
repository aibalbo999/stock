from __future__ import annotations

from pathlib import Path

from app.ui.report_panels import render_report_document


REPORT_PANELS_SOURCE = Path("app/ui/report_panels.py")


class FakeStreamlit:
    def __init__(self, has_iframe: bool = True) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        if has_iframe:
            self.iframe = self._iframe

    def _iframe(self, *args, **kwargs) -> None:
        self.calls.append(("iframe", args, kwargs))


class FakeComponents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def html(self, *args, **kwargs) -> None:
        self.calls.append(("html", args, kwargs))


def test_report_panels_does_not_import_legacy_components_at_module_load() -> None:
    source = REPORT_PANELS_SOURCE.read_text()

    assert "import streamlit.components.v1" not in source
    assert "def load_legacy_streamlit_components(" in source


def test_render_report_document_prefers_streamlit_iframe_without_loading_legacy_components() -> None:
    streamlit = FakeStreamlit(has_iframe=True)
    components = FakeComponents()

    def fail_if_loaded():
        raise AssertionError("legacy components should not load when st.iframe is available")

    render_report_document(
        "<!doctype html><html><body>報告</body></html>",
        height=720,
        streamlit_module=streamlit,
        components_importer=fail_if_loaded,
    )

    assert streamlit.calls == [
        (
            "iframe",
            ("<!doctype html><html><body>報告</body></html>",),
            {"height": 720, "width": "stretch"},
        )
    ]
    assert components.calls == []


def test_render_report_document_falls_back_to_components_html_for_old_streamlit() -> None:
    streamlit = FakeStreamlit(has_iframe=False)
    components = FakeComponents()

    render_report_document(
        "<!doctype html><html><body>報告</body></html>",
        height=720,
        streamlit_module=streamlit,
        components_importer=lambda: components,
    )

    assert components.calls == [
        (
            "html",
            ("<!doctype html><html><body>報告</body></html>",),
            {"height": 720, "scrolling": True},
        )
    ]
    assert streamlit.calls == []
