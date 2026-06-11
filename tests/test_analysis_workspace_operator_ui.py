from __future__ import annotations

import app.ui.analysis_workspace as analysis_workspace


def test_analysis_submission_ready_requires_topic_and_quota_confirmation() -> None:
    assert analysis_workspace.analysis_submission_ready("AI 產業鏈", True) is True
    assert analysis_workspace.analysis_submission_ready("AI 產業鏈", False) is False
    assert analysis_workspace.analysis_submission_ready("  ", True) is False
    assert (
        analysis_workspace.analysis_submission_ready(
            "AI 產業鏈",
            True,
            ai_discovery_mode=False,
            manual_tickers=[],
        )
        is False
    )
    assert (
        analysis_workspace.analysis_submission_ready(
            "AI 產業鏈",
            True,
            ai_discovery_mode=False,
            manual_tickers=["2330"],
        )
        is True
    )


def test_analysis_submission_summary_shows_ready_configuration() -> None:
    assert hasattr(analysis_workspace, "analysis_submission_summary")

    summary = analysis_workspace.analysis_submission_summary(
        topic="AI 伺服器供應鏈",
        analysis_mode_label="深度研究",
        discovery_limit=12,
        evidence_limit=180,
        lookback_days=30,
        ai_discovery_mode=True,
        manual_tickers=[],
        quota_confirmed=True,
    )

    assert summary == {
        "state": "ready",
        "title": "可送出分析背景任務",
        "detail": "AI 伺服器供應鏈｜深度研究｜資料抓取 12｜引用上限 180｜回看 30 天",
        "next_step": "按「執行分析」送出背景任務。",
        "disabled_reason": "",
    }


def test_analysis_submission_summary_explains_missing_manual_tickers() -> None:
    summary = analysis_workspace.analysis_submission_summary(
        topic="AI 伺服器供應鏈",
        analysis_mode_label="標準研究",
        discovery_limit=5,
        evidence_limit=120,
        lookback_days=14,
        ai_discovery_mode=False,
        manual_tickers=[],
        quota_confirmed=True,
    )

    assert summary == {
        "state": "attention",
        "title": "先補齊送出條件",
        "detail": "AI 伺服器供應鏈｜手動個股 0 檔｜標準研究｜資料抓取 5｜引用上限 120｜回看 14 天",
        "next_step": "手動模式請先選擇至少一檔股票。",
        "disabled_reason": "手動模式尚未選擇股票",
    }


def test_analysis_submission_summary_explains_quota_confirmation() -> None:
    summary = analysis_workspace.analysis_submission_summary(
        topic="AI 伺服器供應鏈",
        analysis_mode_label="快速預覽",
        discovery_limit=2,
        evidence_limit=80,
        lookback_days=7,
        ai_discovery_mode=True,
        manual_tickers=[],
        quota_confirmed=False,
    )

    assert summary["state"] == "attention"
    assert summary["title"] == "先確認額度消耗"
    assert summary["next_step"] == "勾選額度確認後才能送出背景任務。"
    assert summary["disabled_reason"] == "尚未確認 AI/API 額度消耗"


def test_operator_decision_card_uses_readable_target_caption() -> None:
    html = analysis_workspace._operator_decision_html(
        {
            "title": "等待額度或查看 fallback",
            "reason": "目前建議模型額度不足或不可用。",
            "risk": "新報告可能排隊等待。",
            "impact": "查看可用 fallback 模型。",
            "action_label": "查看 AI 額度",
            "route_hint": "settings:ai_quota",
            "source_ids": ["gemini-3.5-flash"],
            "state": "attention",
        },
        [],
    )

    assert "開啟系統設定的 AI 額度區" in html
    assert "settings:ai_quota" not in html


def test_operator_secondary_actions_use_readable_target_captions() -> None:
    html = analysis_workspace._operator_decision_html(
        {
            "title": "閱讀最新版",
            "reason": "最新版報告可閱讀。",
            "risk": "低",
            "impact": "可以進入報告中心。",
            "action_label": "閱讀報告",
            "route_hint": "report:15",
            "source_ids": ["report:15"],
            "state": "ready",
        },
        [
            {
                "title": "查看報告生命週期",
                "detail": "可閱讀",
                "state": "ready",
                "route_hint": "report:15",
            },
            {
                "title": "補強資料",
                "detail": "補抓公司文件",
                "state": "attention",
                "route_hint": "data_enrichment:company_filings_fetch:2330",
            },
        ],
    )

    assert "開啟報告中心並選取報告 #15" in html
    assert "開啟資料補強，準備補抓公司文件：2330" in html
    assert "report:15" not in html
    assert "data_enrichment:" not in html


def test_operator_workbench_renders_decision_detail_before_primary_button(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    def fake_load(endpoint: str, default, **_kwargs):
        if endpoint == "/reports?limit=5":
            return []
        return default

    monkeypatch.setattr(analysis_workspace, "load_api_json_or_default", fake_load)
    monkeypatch.setattr(
        analysis_workspace,
        "operator_next_best_action",
        lambda *_args, **_kwargs: {
            "title": "建立第一份分析",
            "reason": "目前尚未有最新版報告。",
            "risk": "沒有可讀報告。",
            "impact": "建立分析後才能閱讀。",
            "action_label": "建立分析",
            "route_hint": "analysis",
            "source_ids": [],
            "state": "attention",
        },
    )
    monkeypatch.setattr(analysis_workspace, "operator_secondary_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        analysis_workspace,
        "operator_status_overall",
        lambda *_args, **_kwargs: {
            "label": "尚未有最新版報告",
            "detail": "先建立分析。",
            "state": "attention",
        },
    )
    monkeypatch.setattr(analysis_workspace, "operator_status_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        analysis_workspace.st,
        "markdown",
        lambda body, **_kwargs: events.append(("markdown", str(body))),
    )
    monkeypatch.setattr(
        analysis_workspace,
        "render_operator_route_button",
        lambda action, **_kwargs: events.append(("button", str(action.get("action_label")))),
    )

    analysis_workspace._render_operator_workbench()

    primary_button_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "button" and body == "建立分析"
    )
    decision_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "markdown" and "operator-decision-card" in body
    )
    assert decision_index < primary_button_index


def test_operator_workbench_renders_primary_recommendation_before_status_overview(
    monkeypatch,
) -> None:
    events: list[tuple[str, str]] = []

    def fake_load(endpoint: str, default, **_kwargs):
        if endpoint == "/reports?limit=5":
            return []
        return default

    monkeypatch.setattr(analysis_workspace, "load_api_json_or_default", fake_load)
    monkeypatch.setattr(
        analysis_workspace,
        "operator_next_best_action",
        lambda *_args, **_kwargs: {
            "title": "建立第一份分析",
            "reason": "目前尚未有最新版報告。",
            "risk": "沒有可讀報告。",
            "impact": "建立分析後才能閱讀。",
            "action_label": "建立分析",
            "route_hint": "analysis",
            "source_ids": [],
            "state": "attention",
        },
    )
    monkeypatch.setattr(analysis_workspace, "operator_secondary_actions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        analysis_workspace,
        "operator_status_overall",
        lambda *_args, **_kwargs: {
            "label": "尚未有最新版報告",
            "detail": "先建立分析。",
            "state": "attention",
        },
    )
    monkeypatch.setattr(analysis_workspace, "operator_status_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        analysis_workspace.st,
        "markdown",
        lambda body, **_kwargs: events.append(("markdown", str(body))),
    )
    monkeypatch.setattr(
        analysis_workspace,
        "render_operator_route_button",
        lambda action, **_kwargs: events.append(("button", str(action.get("action_label")))),
    )

    analysis_workspace._render_operator_workbench()

    decision_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "markdown" and "operator-decision-card" in body
    )
    primary_button_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "button" and body == "建立分析"
    )
    status_overview_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "markdown" and "operator-workbench" in body
    )
    assert decision_index < primary_button_index < status_overview_index


def test_operator_workbench_renders_primary_button_between_decision_and_secondary_cards(
    monkeypatch,
) -> None:
    events: list[tuple[str, str]] = []

    def fake_load(endpoint: str, default, **_kwargs):
        if endpoint == "/reports?limit=5":
            return []
        return default

    monkeypatch.setattr(analysis_workspace, "load_api_json_or_default", fake_load)
    monkeypatch.setattr(
        analysis_workspace,
        "operator_next_best_action",
        lambda *_args, **_kwargs: {
            "title": "處理任務失敗",
            "reason": "最近任務需要確認。",
            "risk": "可能阻塞補強。",
            "impact": "先查看事件。",
            "action_label": "查看事件",
            "route_hint": "settings:maintenance",
            "source_ids": ["task:123"],
            "state": "attention",
        },
    )
    monkeypatch.setattr(
        analysis_workspace,
        "operator_secondary_actions",
        lambda *_args, **_kwargs: [
            {
                "title": "閱讀最新版",
                "detail": "可閱讀",
                "state": "ready",
                "route_hint": "report_center",
            }
        ],
    )
    monkeypatch.setattr(
        analysis_workspace,
        "operator_status_overall",
        lambda *_args, **_kwargs: {
            "label": "有待處理紀錄",
            "detail": "先處理事件。",
            "state": "attention",
        },
    )
    monkeypatch.setattr(analysis_workspace, "operator_status_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        analysis_workspace.st,
        "markdown",
        lambda body, **_kwargs: events.append(("markdown", str(body))),
    )
    monkeypatch.setattr(
        analysis_workspace,
        "render_operator_route_button",
        lambda action, **_kwargs: events.append(("button", str(action.get("action_label")))),
    )

    analysis_workspace._render_operator_workbench()

    primary_button_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "button" and body == "查看事件"
    )
    decision_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "markdown" and "operator-decision-card" in body
    )
    secondary_cards_index = next(
        index
        for index, (kind, body) in enumerate(events)
        if kind == "markdown" and "operator-secondary-actions" in body
    )
    assert decision_index < primary_button_index < secondary_cards_index
