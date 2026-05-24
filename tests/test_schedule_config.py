from pathlib import Path

import pytest

from app.services.schedule_config import ScheduleConfig, ScheduleConfigStore


def test_schedule_config_filters_non_whitelist_tickers() -> None:
    config = ScheduleConfig(tickers=["2330", "9999", "2382"])

    assert config.tickers == ["2330", "2382"]


def test_enabled_schedule_requires_whitelisted_ticker() -> None:
    with pytest.raises(ValueError, match="enabled schedule requires"):
        ScheduleConfig(enabled=True, tickers=["9999"])


def test_disabled_schedule_allows_empty_tickers() -> None:
    config = ScheduleConfig(enabled=False, tickers=[])

    assert config.tickers == []


def test_schedule_config_store_roundtrip(tmp_path: Path, monkeypatch) -> None:
    store = ScheduleConfigStore()
    monkeypatch.setattr(store, "path", tmp_path / "schedule.json")

    saved = store.save(
        ScheduleConfig(
            enabled=True,
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
        "topic": "AI 產業鏈",
        "tickers": ["2330"],
        "lookback_days": 21,
    }
