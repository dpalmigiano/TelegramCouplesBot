from __future__ import annotations

import asyncio
import contextlib
import logging

from .bot import handlers, telethon_client
from .config import get_settings
from .db import run_migrations
from workers import scheduler


async def _scheduler_loop() -> None:
    settings = get_settings()
    interval = max(settings.reag_silence_secs // 3, 30)
    while True:
        try:
            enqueued = scheduler.enqueue_if_calm()
            if enqueued:
                logging.info("Enqueued %s REAG jobs", enqueued)
        except Exception:  # pragma: no cover - defensive
            logging.exception("REAG scheduler tick failed")
        await asyncio.sleep(interval)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    run_migrations()
    client = telethon_client.create_client()
    handlers.register(client)

    print("Couples bot online. Key commands: /link, /consent, /status, /advice.")
    print("Ensure both partners DM /consent yes to start tracking.")
    print("Run `make worker` in another terminal to process REAG jobs after silence windows.")

    scheduler_task = asyncio.create_task(_scheduler_loop())
    try:
        await client.run_until_disconnected()
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task


if __name__ == "__main__":
    asyncio.run(main())
