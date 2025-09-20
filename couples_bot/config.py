"""Configuration utilities for the couples bot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    telegram_api_id: int = Field(..., alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(..., alias="TELEGRAM_API_HASH")
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    bot_owner_user_id: int = Field(..., alias="BOT_OWNER_USER_ID")

    enable_llm: bool = Field(True, alias="ENABLE_LLM")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="o4-mini", alias="OPENAI_MODEL")
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")

    default_tz: str = Field(default="UTC", alias="DEFAULT_TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_path: Path = Field(default=Path("couples.sqlite"), alias="DATABASE_PATH")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for reuse."""

    return Settings()


__all__ = ["Settings", "get_settings"]
