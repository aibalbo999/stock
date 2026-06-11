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


def test_follow_up_run_requires_confirmation_before_submit(monkeypatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, Any] = {}
            self.buttons: list[dict[str, Any]] = []
            self.captions: list[str] = []
            self.checkboxes: list[dict[str, Any]] = []

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

    assert {
        "label": "我了解這會送出自動補強背景任務",
        "value": False,
        "key": "followup_run_confirm_report_7",
    } in fake_st.checkboxes
    assert any("避免誤觸補強" in caption for caption in fake_st.captions)
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
