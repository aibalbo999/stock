from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings
from app.services.entity_mapping import EntityMapper


class ScheduleConfig(BaseModel):
    enabled: bool = True
    hour: int = Field(default=7, ge=0, le=23)
    minute: int = Field(default=30, ge=0, le=59)
    topic: str = "AI 產業鏈"
    tickers: list[str] = Field(default_factory=list)
    lookback_days: int = Field(default=14, ge=1, le=180)
    timezone: str = "Asia/Taipei"

    @field_validator("tickers")
    @classmethod
    def tickers_must_be_whitelisted(cls, value: list[str]) -> list[str]:
        return EntityMapper().filter_allowed_tickers(value)

    @model_validator(mode="after")
    def enabled_schedule_requires_tickers(self) -> "ScheduleConfig":
        if self.enabled and not self.tickers:
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
            "topic": config.topic,
            "tickers": config.tickers,
            "lookback_days": config.lookback_days,
        }
