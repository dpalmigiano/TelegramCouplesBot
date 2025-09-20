"""App entrypoint for running the bot."""
from __future__ import annotations

import asyncio
import logging

from . import db
from .bot import handlers, telethon_client
from .config import get_settings


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    db.run_migrations(settings.database_path)
    client = telethon_client.create_client()
    await handlers.register_handlers(client)

    print("Couples coach bot running.")
    print("Commands:")
    print("  /link <user_a_id> <user_b_id>")
    print("  Partners DM /consent yes, then /status or /advice")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
