"""Telethon client factory."""
from __future__ import annotations

from telethon import TelegramClient

from ..config import get_settings


def create_client() -> TelegramClient:
    settings = get_settings()
    client = TelegramClient("bot", settings.telegram_api_id, settings.telegram_api_hash)
    return client.start(bot_token=settings.telegram_bot_token)


__all__ = ["create_client"]
