from __future__ import annotations

from pathlib import Path

from app.ui.analysis_workspace_presenter import (
    analysis_submission_quota_pressure,
    analysis_submission_ready,
    analysis_submission_summary,
)


def test_analysis_workspace_presenter_is_streamlit_free() -> None:
    source = Path("app/ui/analysis_workspace_presenter.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_analysis_workspace_presenter_keeps_ready_submission_summary() -> None:
    summary = analysis_submission_summary(
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
        "quota_pressure": "額度壓力：很高",
        "quota_pressure_class": "very-high",
        "quota_advice": "適合收盤後或額度剛重置時執行；若免費額度緊張，先改用標準研究或降低引用上限。",
        "next_step": "按「執行分析」送出背景任務。",
        "disabled_reason": "",
    }


def test_analysis_workspace_presenter_keeps_free_tier_quota_guidance() -> None:
    light = analysis_submission_quota_pressure(
        analysis_mode_label="快速預覽",
        discovery_limit=2,
        evidence_limit=40,
        lookback_days=7,
        ai_discovery_mode=False,
        manual_tickers=["2330"],
    )
    default = analysis_submission_quota_pressure(
        analysis_mode_label="標準研究",
        discovery_limit=5,
        evidence_limit=120,
        lookback_days=14,
        ai_discovery_mode=True,
        manual_tickers=[],
    )

    assert light == {
        "level": "低",
        "class": "low",
        "advice": "適合快速試跑或額度偏緊時使用；完成後再視結果升級分析強度。",
    }
    assert default == {
        "level": "中",
        "class": "medium",
        "advice": "適合一般日常分析；若接近免費額度上限，可先降低資料抓取或引用量。",
    }


def test_analysis_workspace_presenter_blocks_missing_manual_tickers_and_quota() -> None:
    assert (
        analysis_submission_ready(
            "AI 產業鏈",
            True,
            ai_discovery_mode=False,
            manual_tickers=[],
        )
        is False
    )
    missing_tickers = analysis_submission_summary(
        topic="AI 伺服器供應鏈",
        analysis_mode_label="標準研究",
        discovery_limit=5,
        evidence_limit=120,
        lookback_days=14,
        ai_discovery_mode=False,
        manual_tickers=[],
        quota_confirmed=True,
    )
    quota_missing = analysis_submission_summary(
        topic="AI 伺服器供應鏈",
        analysis_mode_label="快速預覽",
        discovery_limit=2,
        evidence_limit=80,
        lookback_days=7,
        ai_discovery_mode=True,
        manual_tickers=[],
        quota_confirmed=False,
    )

    assert missing_tickers["disabled_reason"] == "手動模式尚未選擇股票"
    assert missing_tickers["next_step"] == "手動模式請先選擇至少一檔股票。"
    assert quota_missing["disabled_reason"] == "尚未確認 AI/API 額度消耗"
    assert quota_missing["next_step"] == "勾選額度確認後才能送出背景任務。"
