from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings
from app.services.entity_mapping import EntityMapper


class ScheduleConfig(BaseModel):
    enabled: bool = True
    task: Literal["latest_report_update", "configured_report"] = "latest_report_update"
    hour: int = Field(default=16, ge=0, le=23)
    minute: int = Field(default=30, ge=0, le=59)
    topic: str = "AI 產業鏈"
    tickers: list[str] = Field(default_factory=list)
    lookback_days: int = Field(default=120, ge=1, le=365)
    timezone: str = "Asia/Taipei"
    force_refresh: bool = True
    rerun_report: bool = True
    refresh_company_filings: bool = True
    news_limit: int = Field(default=30, ge=0, le=100)
    maintenance_cleanup_enabled: bool = True
    maintenance_cleanup_hour: int = Field(default=3, ge=0, le=23)
    maintenance_cleanup_minute: int = Field(default=20, ge=0, le=59)
    maintenance_cleanup_failed_runs: bool = False
    maintenance_cleanup_orphan_report_refs: bool = True
    maintenance_cleanup_latest_reports_only: bool = True
    maintenance_cleanup_stale_running_minutes: int = Field(default=240, ge=0, le=10080)

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, value: list[str]) -> list[str]:
        tickers = [str(ticker).strip() for ticker in value if str(ticker).strip()]
        return list(dict.fromkeys(tickers))

    @model_validator(mode="after")
    def validate_schedule_target(self) -> "ScheduleConfig":
        if self.task == "configured_report":
            self.tickers = EntityMapper().filter_allowed_tickers(self.tickers)
        if self.enabled and self.task == "configured_report" and not self.tickers:
            raise ValueError("enabled schedule requires at least one whitelisted ticker")
        return self


class ScheduleConfigStore:
    def __init__(self) -> None:
        self.path = get_settings().schedule_config_path

    def load(self) -> ScheduleConfig:
        if not self.path.exists():
            return ScheduleConfig()
        return ScheduleConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, config: ScheduleConfig) -> ScheduleConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config

    def celery_payload(self) -> dict:
        config = self.load()
        return {
            "task": config.task,
            "topic": config.topic,
            "tickers": config.tickers,
            "lookback_days": config.lookback_days,
            "force_refresh": config.force_refresh,
            "rerun_report": config.rerun_report,
            "refresh_company_filings": config.refresh_company_filings,
            "news_limit": config.news_limit,
        }

    def maintenance_cleanup_payload(self) -> dict:
        config = self.load()
        return {
            "failed_runs": config.maintenance_cleanup_failed_runs,
            "orphan_report_refs": config.maintenance_cleanup_orphan_report_refs,
            "latest_reports_only": config.maintenance_cleanup_latest_reports_only,
            "stale_running_minutes": config.maintenance_cleanup_stale_running_minutes,
        }
