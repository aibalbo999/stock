from pathlib import Path

from app.services.followup_actions import FOLLOW_UP_ACTION_LABELS, TRACKING_FRESHNESS_THRESHOLDS


def test_readme_documents_follow_up_freshness_thresholds() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    expected = {
        "股價/量能": "refresh_market",
        "月營收": "refresh_monthly_revenue",
        "估值": "refresh_valuations",
        "五年財務": "refresh_financial_metrics",
    }
    for label, action_type in expected.items():
        assert f"{label}：{TRACKING_FRESHNESS_THRESHOLDS[action_type]} 天" in readme


def test_readme_documents_follow_up_action_labels() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for label in FOLLOW_UP_ACTION_LABELS.values():
        assert f"- {label}" in readme
