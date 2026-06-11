from __future__ import annotations

from typing import Any

from app.ui import report_follow_up_controls


def _planned_follow_up_response() -> dict[str, Any]:
    return {
        "actions": [
            {
                "label": "補新聞",
                "action_type": "news",
                "tickers": ["2330"],
                "purpose": "required",
                "priority": "high",
                "frequency": "once",
                "reason": "缺資料",
            }
        ],
        "next_actions": [],
        "freshness": {},
    }


def test_follow_up_submission_preflight_summary_warns_before_confirmation() -> None:
    assert hasattr(report_follow_up_controls, "follow_up_submission_preflight_summary")

    summary = report_follow_up_controls.follow_up_submission_preflight_summary(
        executable_actions=[
            {"purpose": "required"},
            {"purpose": "tracking"},
        ],
        markdown_rows=[],
        manual_tracking_selected=False,
        selected_purpose="all",
        rerun_report=True,
        news_limit=30,
        button_label="執行全部補強並重跑",
        confirmed=False,
    )

    assert summary == {
        "state": "attention",
        "title": "準備送出自動補強",
        "detail": "範圍：全部任務｜資料缺口 1 項｜追蹤更新 1 項｜補抓資料量 30｜完成後重跑",
        "next_step": "勾選確認後，再按「執行全部補強並重跑」送出背景任務。",
        "quota_hint": "會使用背景任務、外部資料來源與可能的 AI 額度；送出後請等待狀態輪詢，避免重複送出。",
    }


def test_follow_up_submission_preflight_summary_allows_confirmed_submission() -> None:
    summary = report_follow_up_controls.follow_up_submission_preflight_summary(
        executable_actions=[{"purpose": "required"}],
        markdown_rows=[],
        manual_tracking_selected=False,
        selected_purpose="required",
        rerun_report=True,
        news_limit=20,
        button_label="補資料缺口並重跑",
        confirmed=True,
    )

    assert summary == {
        "state": "ready",
        "title": "可以送出自動補強",
        "detail": "範圍：只補資料缺口｜資料缺口 1 項｜追蹤更新 0 項｜補抓資料量 20｜完成後重跑",
        "next_step": "按「補資料缺口並重跑」送出背景任務；完成後套用補強結果並查看最新版生命週期。",
        "quota_hint": "送出後會排隊執行；完成前不要重複送出同一份報告的補強。",
    }


def test_follow_up_submission_preflight_summary_blocks_empty_scope() -> None:
    summary = report_follow_up_controls.follow_up_submission_preflight_summary(
        executable_actions=[],
        markdown_rows=[],
        manual_tracking_selected=False,
        selected_purpose="required",
        rerun_report=False,
        news_limit=30,
        button_label="補資料缺口並重跑",
        confirmed=True,
    )

    assert summary == {
        "state": "attention",
        "title": "目前沒有可送出的補強任務",
        "detail": "範圍：只補資料缺口｜資料缺口 0 項｜追蹤更新 0 項｜補抓資料量 30｜完成後不重跑",
        "next_step": "切換執行範圍，或回資料補強頁手動刷新資料。",
        "quota_hint": "尚未送出背景任務；先確認範圍可避免空任務與額度浪費。",
    }


def test_render_follow_up_submission_summary_outputs_operator_card(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.markdowns: list[str] = []

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdowns.append(str(body))

    fake_st = FakeStreamlit()
    monkeypatch.setattr(report_follow_up_controls, "st", fake_st)

    report_follow_up_controls.render_follow_up_submission_summary(
        {
            "state": "attention",
            "title": "準備送出自動補強",
            "detail": "範圍：全部任務｜資料缺口 1 項",
            "next_step": "勾選確認後再送出。",
            "quota_hint": "會使用背景任務、外部資料來源與可能的 AI 額度。",
        }
    )

    assert any(
        'class="follow-up-submission-summary is-attention"' in markdown
        and "準備送出自動補強" in markdown
        and "可能的 AI 額度" in markdown
        for markdown in fake_st.markdowns
    )


def test_follow_up_run_requires_confirmation_before_submit(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, Any] = {}
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []
            self.markdowns: list[str] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "補資料缺口並重跑" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str):
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return key == "followup_rerun_report_7"

        def columns(self, count_or_spec):
            count = count_or_spec if isinstance(count_or_spec, int) else len(count_or_spec)
            return [self for _ in range(count)]

        def dataframe(self, *_args, **_kwargs) -> None:
            return None

        def info(self, body: str) -> None:
            raise AssertionError(f"unexpected info: {body}")

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdowns.append(str(body))

        def number_input(self, *_args, **_kwargs):
            return 30

        def radio(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(report_follow_up_controls, "st", fake_st)
    monkeypatch.setattr(report_follow_up_controls, "markdown_table_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        report_follow_up_controls,
        "load_api_json_or_default",
        lambda *_args, **_kwargs: _planned_follow_up_response(),
    )
    monkeypatch.setattr(
        report_follow_up_controls,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    report_follow_up_controls.render_follow_up_controls(7, "", scope="report")

    assert {
        "label": "我了解這會送出自動補強背景任務",
        "value": False,
        "key": "followup_run_confirm_report_7",
    } in fake_st.checkboxes
    assert any("避免誤觸補強" in caption for caption in fake_st.captions)
    assert any(
        'class="follow-up-submission-summary is-attention"' in markdown
        and "準備送出自動補強" in markdown
        and "會使用背景任務、外部資料來源與可能的 AI 額度" in markdown
        for markdown in fake_st.markdowns
    )
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["補資料缺口並重跑"]["disabled"] is True
    assert submitted == []


def test_follow_up_run_submits_after_confirmation(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, Any] = {}
            self.buttons: list[dict[str, Any]] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "補資料缺口並重跑" and not kwargs.get("disabled")

        def caption(self, _body: str) -> None:
            return None

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key in {"followup_rerun_report_7", "followup_run_confirm_report_7"}

        def columns(self, count_or_spec):
            count = count_or_spec if isinstance(count_or_spec, int) else len(count_or_spec)
            return [self for _ in range(count)]

        def dataframe(self, *_args, **_kwargs) -> None:
            return None

        def info(self, body: str) -> None:
            raise AssertionError(f"unexpected info: {body}")

        def markdown(self, *_args, **_kwargs) -> None:
            return None

        def number_input(self, *_args, **_kwargs):
            return 30

        def radio(self, _label: str, *, options, index: int = 0, **_kwargs):
            return list(options)[index]

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(report_follow_up_controls, "st", fake_st)
    monkeypatch.setattr(report_follow_up_controls, "markdown_table_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        report_follow_up_controls,
        "load_api_json_or_default",
        lambda *_args, **_kwargs: _planned_follow_up_response(),
    )
    monkeypatch.setattr(
        report_follow_up_controls,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    report_follow_up_controls.render_follow_up_controls(7, "", scope="report")

    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["補資料缺口並重跑"]["disabled"] is False
    assert submitted == [
        (
            (
                "/reports/7/follow-up/run_async",
                {
                    "rerun_report": True,
                    "news_limit": 30,
                    "purpose": "required",
                    "force_refresh": False,
                },
            ),
            {
                "task_state_key": "last_follow_up_task_id",
                "status_state_keys": ("refresh_followup_task_report_7_status",),
                "success_message": "已送出補強背景任務",
                "error_message": "自動補強任務送出失敗",
            },
        )
    ]


def test_follow_up_run_does_not_use_markdown_rows_when_plan_scope_is_empty(
    monkeypatch,
) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, Any] = {}
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.markdowns: list[str] = []

        def button(self, label: str, **kwargs):
            self.buttons.append({"label": label, **kwargs})
            return label == "執行追蹤更新並重跑" and not kwargs.get("disabled")

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, _label: str, *, value: bool = False, key: str):
            return key in {"followup_rerun_report_7", "followup_run_confirm_report_7"}

        def columns(self, count_or_spec):
            count = count_or_spec if isinstance(count_or_spec, int) else len(count_or_spec)
            return [self for _ in range(count)]

        def dataframe(self, *_args, **_kwargs) -> None:
            return None

        def info(self, body: str) -> None:
            raise AssertionError(f"unexpected info: {body}")

        def markdown(self, body: str, **_kwargs) -> None:
            self.markdowns.append(str(body))

        def number_input(self, *_args, **_kwargs):
            return 30

        def radio(self, _label: str, *, options, **_kwargs):
            assert "只做追蹤更新" in options
            return "只做追蹤更新"

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []

    monkeypatch.setattr(report_follow_up_controls, "st", fake_st)
    monkeypatch.setattr(
        report_follow_up_controls,
        "markdown_table_rows",
        lambda *_args, **_kwargs: [["補新聞", "2330", "追蹤更新"]],
    )
    monkeypatch.setattr(
        report_follow_up_controls,
        "load_api_json_or_default",
        lambda *_args, **_kwargs: _planned_follow_up_response(),
    )
    monkeypatch.setattr(
        report_follow_up_controls,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    report_follow_up_controls.render_follow_up_controls(7, "", scope="report")

    assert any("目前選擇的範圍沒有可執行任務" in caption for caption in fake_st.captions)
    assert any(
        'class="follow-up-submission-summary is-attention"' in markdown
        and "目前沒有可送出的補強任務" in markdown
        and "追蹤更新 0 項" in markdown
        for markdown in fake_st.markdowns
    )
    by_label = {button["label"]: button for button in fake_st.buttons}
    assert by_label["執行追蹤更新並重跑"]["disabled"] is True
    assert submitted == []
