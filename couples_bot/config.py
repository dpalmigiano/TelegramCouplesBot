"""Configuration utilities for the couples bot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
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
    groq_fallback_model: str = Field(
        default="llama-3.3-70b-versatile", alias="GROQ_FALLBACK_MODEL"
    )

    default_tz: str = Field(default="UTC", alias="DEFAULT_TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_path: Path = Field(default=Path("couples.sqlite"), alias="DATABASE_PATH")

    reag_silence_secs: int = Field(default=180, alias="REAG_SILENCE_SECS")
    reag_min_interval_secs: int = Field(default=300, alias="REAG_MIN_INTERVAL_SECS")
    reag_queue_high_watermark: int = Field(
        default=12, alias="REAG_QUEUE_HIGH_WATERMARK"
    )
    reag_max_out_tokens: int = Field(default=4096, alias="REAG_MAX_OUT_TOKENS")

    graph_enabled: bool = Field(default=False, alias="GRAPH_ENABLED")
    chaos_mode: int = Field(default=0, alias="CHAOS_MODE")
    chaos_llm_p: float = Field(default=0.2, alias="CHAOS_LLM_P")

    onboarding_deep_links: bool = Field(default=True, alias="ONBOARDING_DEEP_LINKS")
    onboarding_brand_name: str = Field(
        default="Couples Coach", alias="ONBOARDING_BRAND_NAME"
    )
    onboarding_emoji_style: str = Field(
        default="🎯💬❤️", alias="ONBOARDING_EMOJI_STYLE"
    )
    onboarding_tz_suggestions: List[str] = Field(
        default_factory=lambda: [
            "America/Los_Angeles",
            "America/New_York",
            "Europe/London",
            "Europe/Paris",
            "Asia/Kolkata",
        ],
        alias="ONBOARDING_TZ_SUGGESTIONS",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True

    @field_validator("onboarding_tz_suggestions", mode="before")
    @classmethod
    def _parse_tz_suggestions(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings for reuse."""

    return Settings()


__all__ = ["Settings", "get_settings"]
