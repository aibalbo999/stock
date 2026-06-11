from __future__ import annotations

from app.ui.maintenance_operation_controls import (
    render_post_run_diagnostic_actions,
    task_result_payload,
)


def test_maintenance_operation_controls_extract_nested_task_result_payload() -> None:
    assert task_result_payload(None) == {}
    assert task_result_payload({"result": "not-a-dict"}) == {}
    assert task_result_payload({"result": {"status": "success"}}) == {"status": "success"}
    assert task_result_payload(
        {"result": {"result": {"status": "success", "message": "done"}}}
    ) == {"status": "success", "message": "done"}


def test_maintenance_operation_controls_require_diagnostic_confirmation(monkeypatch) -> None:
    from app.ui import maintenance_operation_controls

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.checkboxes: list[dict] = []
            self.buttons: list[dict] = []
            self.captions: list[str] = []

        def caption(self, body: str) -> None:
            self.captions.append(str(body))

        def checkbox(self, label: str, *, value: bool = False, key: str) -> bool:
            self.checkboxes.append({"label": label, "value": value, "key": key})
            return False

        def button(self, label: str, **kwargs) -> bool:
            self.buttons.append({"label": label, **kwargs})
            return False

    fake_st = FakeStreamlit()
    submitted: list[tuple] = []
    monkeypatch.setattr(maintenance_operation_controls, "st", fake_st)
    monkeypatch.setattr(
        maintenance_operation_controls,
        "submit_api_task",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    render_post_run_diagnostic_actions(
        [
            {
                "項目": "升級稽核",
                "用途": "確認升級狀態",
                "可執行診斷": "upgrade_audit",
                "指令": "upgrade-audit --json",
            }
        ]
    )

    assert fake_st.checkboxes == [
        {
            "label": "我了解這會送出「升級稽核」後續診斷背景任務",
            "value": False,
            "key": "maintenance_post_run_diagnostic_confirm_upgrade_audit",
        }
    ]
    assert fake_st.buttons[0]["disabled"] is True
    assert any("避免誤觸後續診斷" in caption for caption in fake_st.captions)
    assert submitted == []
