from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.schedule_config import ScheduleConfig, ScheduleConfigStore
from app.tasks.celery_app import build_beat_schedule


def test_schedule_config_filters_non_whitelist_tickers() -> None:
    config = ScheduleConfig(task="configured_report", tickers=["2330", "9999", "2382"])

    assert config.tickers == ["2330", "2382"]


def test_configured_report_schedule_requires_whitelisted_ticker() -> None:
    with pytest.raises(ValueError, match="enabled schedule requires"):
        ScheduleConfig(enabled=True, task="configured_report", tickers=["9999"])


def test_latest_report_update_allows_dynamic_or_empty_tickers() -> None:
    config = ScheduleConfig(enabled=True, task="latest_report_update", tickers=["9999", "9999"])

    assert config.tickers == ["9999"]


def test_disabled_schedule_allows_empty_tickers() -> None:
    config = ScheduleConfig(enabled=False, task="configured_report", tickers=[])

    assert config.tickers == []


def test_schedule_config_store_roundtrip(tmp_path: Path, monkeypatch) -> None:
    store = ScheduleConfigStore()
    monkeypatch.setattr(store, "path", tmp_path / "schedule.json")

    saved = store.save(
        ScheduleConfig(
            enabled=True,
            task="configured_report",
            hour=8,
            minute=15,
            topic="AI 產業鏈",
            tickers=["2330", "9999"],
            lookback_days=21,
        )
    )
    loaded = store.load()

    assert saved.tickers == ["2330"]
    assert loaded.hour == 8
    assert loaded.minute == 15
    assert store.celery_payload() == {
        "task": "configured_report",
        "topic": "AI 產業鏈",
        "tickers": ["2330"],
        "lookback_days": 21,
        "force_refresh": True,
        "rerun_report": True,
        "refresh_company_filings": True,
        "news_limit": 30,
    }
    assert store.maintenance_cleanup_payload() == {
        "failed_runs": False,
        "orphan_report_refs": True,
        "latest_reports_only": True,
        "stale_running_minutes": 240,
    }


def test_schedule_config_can_disable_maintenance_cleanup() -> None:
    config = ScheduleConfig(maintenance_cleanup_enabled=False)

    assert config.maintenance_cleanup_enabled is False
    assert config.maintenance_cleanup_hour == 3
    assert config.maintenance_cleanup_minute == 20


def test_celery_beat_schedule_includes_daily_maintenance_cleanup() -> None:
    store = SimpleNamespace(
        celery_payload=lambda: {"task": "latest_report_update"},
        maintenance_cleanup_payload=lambda: {
            "orphan_report_refs": True,
            "latest_reports_only": True,
            "stale_running_minutes": 240,
        },
    )
    schedule = build_beat_schedule(ScheduleConfig(), store)

    assert schedule["daily-stock-report-update"]["task"] == (
        "app.tasks.tasks.after_close_report_update_task"
    )
    assert schedule["daily-maintenance-cleanup"]["task"] == "app.tasks.tasks.maintenance_cleanup_task"
    assert schedule["daily-maintenance-cleanup"]["args"] == (
        {
            "orphan_report_refs": True,
            "latest_reports_only": True,
            "stale_running_minutes": 240,
        },
    )
