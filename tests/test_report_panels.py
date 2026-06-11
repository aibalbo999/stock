from __future__ import annotations

from app.ui.report_panels import render_report_document


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


def test_render_report_document_prefers_streamlit_iframe() -> None:
    streamlit = FakeStreamlit(has_iframe=True)
    components = FakeComponents()

    render_report_document(
        "<!doctype html><html><body>報告</body></html>",
        height=720,
        streamlit_module=streamlit,
        components_module=components,
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
        components_module=components,
    )

    assert components.calls == [
        (
            "html",
            ("<!doctype html><html><body>報告</body></html>",),
            {"height": 720, "scrolling": True},
        )
    ]
    assert streamlit.calls == []
