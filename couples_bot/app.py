"""Entrypoint for the couples bot."""

from __future__ import annotations

import asyncio
import logging

from .bot import handlers, telethon_client
from .config import get_settings
from .db import run_migrations


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    run_migrations()
    client = telethon_client.create_client()
    handlers.register(client)

    print("Couples bot online. Key commands: /link, /consent, /status, /advice.")
    print("Ensure both partners DM /consent yes to start tracking.")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
