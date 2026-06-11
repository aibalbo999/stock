from __future__ import annotations

from app.ui.maintenance_deployment_view import (
    external_deployment_focus_banner_html,
    external_deployment_operator_summary_html,
)


def test_maintenance_deployment_view_renders_focus_banner() -> None:
    html = external_deployment_focus_banner_html(
        {
            "state": "attention",
            "title": "公司文件結構化 API 免費驗證",
            "detail": "先看 JSON/HTTP 格式。",
            "target_caption": "免費檢查",
        }
    )

    assert "maintenance-focus-banner is-attention" in html
    assert "目前焦點" in html
    assert "公司文件結構化 API 免費驗證" in html


def test_maintenance_deployment_view_escapes_operator_summary_values() -> None:
    html = external_deployment_operator_summary_html(
        {
            "state": 'ready" onclick="bad',
            "title": "<b>外部選配</b>",
            "detail": "目前 > 無 blocking",
            "local_action": "本機 defaults",
            "effective_remaining": "有效剩餘 1 項",
            "paid_external": "付費/API 選配 1 項",
            "next_step": "先驗證 <JSON>",
        }
    )

    assert "external-deployment-operator-summary" in html
    assert "<b>" not in html
    assert "&lt;b&gt;外部選配&lt;/b&gt;" in html
    assert "目前 &gt; 無 blocking" in html
    assert "先驗證 &lt;JSON&gt;" in html
