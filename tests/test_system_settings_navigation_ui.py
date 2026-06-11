from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.ui.system_settings as system_settings
import app.ui.system_settings_scope as system_settings_scope
import app.ui.system_settings_maintenance as system_settings_maintenance
from app.ui.system_settings import (
    external_deployment_focus_from_pending_section,
    maintenance_focus_from_pending_section,
    settings_section_label,
)


def test_settings_section_label_routes_maintenance_and_ai_quota_to_maintenance_view() -> None:
    assert settings_section_label("maintenance") == "維護"
    assert settings_section_label("ai_quota") == "維護"
    assert settings_section_label("maintenance_local_defaults") == "維護"
    assert settings_section_label("maintenance_structured_api") == "維護"


def test_maintenance_focus_from_pending_section_preserves_ai_quota_route() -> None:
    assert maintenance_focus_from_pending_section("ai_quota") == "ai_quota"
    assert maintenance_focus_from_pending_section("maintenance_local_defaults") == (
        "external_deployment"
    )
    assert maintenance_focus_from_pending_section("maintenance_structured_api") == (
        "external_deployment"
    )
    assert maintenance_focus_from_pending_section("maintenance") is None
    assert maintenance_focus_from_pending_section("schedule") is None
    assert maintenance_focus_from_pending_section(None) is None


def test_external_deployment_focus_from_pending_section_preserves_structured_api_route() -> None:
    assert external_deployment_focus_from_pending_section("maintenance_structured_api") == (
        "structured_api"
    )
    assert external_deployment_focus_from_pending_section("maintenance_local_defaults") == (
        "local_defaults"
    )
    assert external_deployment_focus_from_pending_section("ai_quota") is None
    assert external_deployment_focus_from_pending_section(None) is None


def test_settings_section_label_defaults_to_scope_for_unknown_route() -> None:
    assert settings_section_label(None) == "股票範圍"
    assert settings_section_label("unknown") == "股票範圍"


def test_scope_source_summary_distinguishes_static_scope_from_report_candidates() -> None:
    whitelist = SimpleNamespace(
        path=Path("data/ai_supply_chain_whitelist.json"),
        segments=[
            SimpleNamespace(name="散熱", companies=[SimpleNamespace(), SimpleNamespace()]),
            SimpleNamespace(name="電源", companies=[]),
        ],
        risk_keywords=["毛利率", "匯率", "庫存"],
        companies=lambda: [SimpleNamespace(ticker="3017"), SimpleNamespace(ticker="2308")],
    )

    summary = system_settings_scope.scope_source_summary(whitelist)

    assert summary["state"] == "ready"
    assert summary["title"] == "系統靜態股票範圍"
    assert summary["detail"] == "目前可辨識 2 檔股票、2 個產業分類、3 個風險詞組。"
    assert summary["source"] == "來源：data/ai_supply_chain_whitelist.json"
    assert "不是本次報告的動態候選名單" in summary["next_step"]
    assert "若任務被白名單或輸入擋下" in summary["fallback_hint"]


def test_render_scope_tab_shows_static_scope_source_summary(monkeypatch) -> None:
    class FakeColumn:
        def __init__(self, sink: list[tuple[str, str, object]]) -> None:
            self.sink = sink

        def metric(self, label, value):
            self.sink.append(("metric", label, value))

    class FakeExpander:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def markdown(self, html, **_kwargs):
            self.calls.append(("markdown", html))

        def columns(self, count):
            return [FakeColumn(self.calls) for _ in range(count)]

        def selectbox(self, _label, options, **_kwargs):
            return options[0]

        def dataframe(self, rows, **_kwargs):
            self.calls.append(("dataframe", rows))

        def info(self, message):
            self.calls.append(("info", message))

        def expander(self, _label):
            return FakeExpander()

        def json(self, payload):
            self.calls.append(("json", payload))

    fake_st = FakeStreamlit()
    whitelist = SimpleNamespace(
        path=Path("data/ai_supply_chain_whitelist.json"),
        raw={"segments": [], "risk_keywords": []},
        segments=[
            SimpleNamespace(
                name="散熱",
                companies=[
                    SimpleNamespace(ticker="3017", name="奇鋐", evidence_keywords=["散熱"]),
                ],
            )
        ],
        risk_keywords=["毛利率"],
        companies=lambda: [SimpleNamespace(ticker="3017")],
    )

    monkeypatch.setattr(system_settings_scope, "st", fake_st)
    monkeypatch.setattr(system_settings_scope, "render_section_header", lambda *_args: None)

    system_settings_scope.render_scope_tab(whitelist)

    markdown_calls = [call[1] for call in fake_st.calls if call[0] == "markdown"]
    assert any('class="scope-source-summary is-ready"' in html for html in markdown_calls)
    assert any("系統靜態股票範圍" in html for html in markdown_calls)
    assert any("不是本次報告的動態候選名單" in html for html in markdown_calls)
    assert any("若任務被白名單或輸入擋下" in html for html in markdown_calls)


def test_render_system_settings_preserves_ai_quota_focus(monkeypatch) -> None:
    class FakeWhitelist:
        def allowed_tickers(self) -> set[str]:
            return {"2330"}

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_settings_section": "ai_quota"}

        def radio(self, _label, options, **_kwargs):
            return self.session_state["settings_section"]

    fake_st = FakeStreamlit()
    rendered: list[str] = []
    monkeypatch.setattr(system_settings, "st", fake_st)
    monkeypatch.setattr(system_settings, "SupplyChainWhitelist", FakeWhitelist)
    monkeypatch.setattr(system_settings, "render_scope_tab", lambda _whitelist: rendered.append("scope"))
    monkeypatch.setattr(system_settings, "render_schedule_tab", lambda _tickers: rendered.append("schedule"))
    monkeypatch.setattr(system_settings, "render_maintenance_tab", lambda: rendered.append("maintenance"))

    system_settings.render_system_settings()

    assert fake_st.session_state["settings_section"] == "維護"
    assert fake_st.session_state["pending_maintenance_focus"] == "ai_quota"
    assert rendered == ["maintenance"]


def test_render_system_settings_preserves_structured_api_external_focus(monkeypatch) -> None:
    class FakeWhitelist:
        def allowed_tickers(self) -> set[str]:
            return {"2330"}

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {"pending_settings_section": "maintenance_structured_api"}

        def radio(self, _label, options, **_kwargs):
            return self.session_state["settings_section"]

    fake_st = FakeStreamlit()
    rendered: list[str] = []
    monkeypatch.setattr(system_settings, "st", fake_st)
    monkeypatch.setattr(system_settings, "SupplyChainWhitelist", FakeWhitelist)
    monkeypatch.setattr(system_settings, "render_scope_tab", lambda _whitelist: rendered.append("scope"))
    monkeypatch.setattr(system_settings, "render_schedule_tab", lambda _tickers: rendered.append("schedule"))
    monkeypatch.setattr(system_settings, "render_maintenance_tab", lambda: rendered.append("maintenance"))

    system_settings.render_system_settings()

    assert fake_st.session_state["settings_section"] == "維護"
    assert fake_st.session_state["pending_maintenance_focus"] == "external_deployment"
    assert fake_st.session_state["pending_external_deployment_focus"] == "structured_api"
    assert rendered == ["maintenance"]


def test_maintenance_incident_inbox_includes_latest_report_lifecycle(monkeypatch) -> None:
    class FakeStreamlit:
        session_state = {}

        def toggle(self, *_args, **_kwargs):
            return False

    payloads = {
        "/db/status": {"settings": {}, "integrity": {}, "tables": {}},
        "/services/status": {
            "task_queue": {"ready": True, "processing_ready": True, "worker_online": True}
        },
        "/llm/quota": {"recommended_model": "gemini-3.5-flash", "models": []},
        "/llm/usage/summary?days=7": {"totals": {}, "by_model": [], "by_operation": []},
        "/tasks/summary?days=7": {"totals": {"stale_running_count": 0}, "recent_failures": []},
        "/maintenance/diagnostics": {"actions": []},
        "/maintenance/operations": {"operations": []},
        "/services/external-deployment/env-check": {"status": "unknown", "checks": {}},
        "/reports/observability/summary?limit=20": {"status": "unknown", "totals": {}},
        "/reports/quality/summary?limit=20": {"status": "unknown", "totals": {}},
        "/services/upgrade-audit?strict_external=false": {
            "overall_status": "ready",
            "warnings": [],
            "failures": [],
        },
        "/reports?limit=1": [{"id": 18, "title": "散熱產業鏈"}],
        "/reports/18": {
            "id": 18,
            "topic": "散熱產業鏈",
            "quality_gate": {"status": "caution", "metrics": {"promoted_count": 0}},
            "candidate_whitelist": [{"ticker": "3017"}],
        },
        "/reports/18/follow-up/plan": {"summary": {"required_count": 0}},
    }
    captured_incidents: list[dict] = []
    called_urls: list[str] = []

    def fake_load(url, default, **_kwargs):
        called_urls.append(url)
        return payloads.get(url, default)

    def capture_incidents(incidents):
        captured_incidents.extend(incidents)

    monkeypatch.setattr(system_settings_maintenance, "st", FakeStreamlit())
    monkeypatch.setattr(system_settings_maintenance, "load_api_json_or_default", fake_load)
    monkeypatch.setattr(system_settings_maintenance, "_render_incident_inbox", capture_incidents)
    monkeypatch.setattr(system_settings_maintenance, "render_section_header", lambda *_args, **_kwargs: None)
    for name in (
        "render_ai_quota_panel",
        "render_ai_usage_panel",
        "render_background_task_observability_panel",
        "render_external_deployment_panel",
        "render_maintenance_cleanup_panel",
        "render_optimization_progress_panel",
        "render_report_generation_observability_panel",
        "render_report_quality_panel",
        "render_service_details_panel",
        "render_service_metrics_panel",
        "render_submission_guard_panel",
        "render_upgrade_audit_panel",
    ):
        monkeypatch.setattr(system_settings_maintenance, name, lambda *_args, **_kwargs: None)

    system_settings_maintenance.render_maintenance_tab()

    assert "/reports?limit=1" in called_urls
    assert "/reports/18" in called_urls
    assert "/reports/18/follow-up/plan" in called_urls
    assert captured_incidents[0]["category"] == "report_quality"
    assert captured_incidents[0]["severity"] == "critical"
    assert captured_incidents[0]["source"] == "report:18"
