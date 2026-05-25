from pathlib import Path

from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD
from app.services.followup_actions import FOLLOW_UP_ACTION_LABELS, TRACKING_FRESHNESS_THRESHOLDS
from app.services.llm_client import DEFAULT_MAX_RETRIES_PER_KEY, RETRYABLE_HTTP_STATUSES


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


def test_readme_documents_candidate_confidence_gate() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert f"證據信心低於 {HIGH_CONFIDENCE_THRESHOLD} 分" in readme
    assert f"證據信心分數達 {HIGH_CONFIDENCE_THRESHOLD} 分" in readme
    assert f"CANDIDATE_CONFIDENCE_HIGH_THRESHOLD={HIGH_CONFIDENCE_THRESHOLD}" in readme
    assert "候選證據信心" in readme
    assert "證據篇數、來源家數、來源日期覆蓋與最新證據日期" in readme


def test_readme_documents_llm_retry_statuses() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for status in sorted(RETRYABLE_HTTP_STATUSES):
        assert str(status) in readme
    assert "輪調下一把 key" in readme
    assert f"LLM_MAX_RETRIES_PER_KEY={DEFAULT_MAX_RETRIES_PER_KEY}" in readme
    assert "LLM_BASE_RETRY_DELAY_SECONDS=0.5" in readme
    assert "LLM_MAX_RETRY_DELAY_SECONDS=5.0" in readme
