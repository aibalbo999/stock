from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./stock_ai.db"
    redis_url: str = "redis://localhost:6379/0"
    vector_db_path: Path = Path(".chroma")
    use_chroma: bool = False
    report_dir: Path = Path("reports")
    api_base_url: str = "http://127.0.0.1:8000"
    schedule_config_path: Path = Path("data/schedule_config.json")
    news_sources_path: Path = Path("data/news_sources.json")
    whitelist_path: Path = Path("data/ai_supply_chain_whitelist.json")
    primary_llm_model: str = "gemini-2.5-flash"
    local_llm_model: str = "gemma-4-31b"
    google_api_key: Optional[str] = None
    google_api_keys: str = ""
    fugle_api_key: Optional[str] = None
    finmind_token: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def gemini_api_keys(self) -> list[str]:
        keys = [key.strip() for key in self.google_api_keys.split(",") if key.strip()]
        if self.google_api_key:
            keys.append(self.google_api_key.strip())
        return list(dict.fromkeys(keys))


@lru_cache
def get_settings() -> Settings:
    return Settings()
