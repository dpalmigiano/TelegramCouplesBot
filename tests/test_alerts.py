from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from couples_bot import db
from couples_bot.alerts import pings
from couples_bot.config import get_settings
from couples_bot.models import AlertKind


class DummyClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, user_id, text):
        self.sent.append((user_id, text))


def _setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_OWNER_USER_ID", "1")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DEFAULT_TZ", "UTC")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("REAG_SILENCE_SECS", "180")
    monkeypatch.setenv("REAG_MIN_INTERVAL_SECS", "300")
    monkeypatch.setenv("REAG_QUEUE_HIGH_WATERMARK", "12")
    monkeypatch.setenv("REAG_MAX_OUT_TOKENS", "4096")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("ENABLE_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    if hasattr(db, "_CONN"):
        db._CONN = None  # type: ignore[attr-defined]
    db.run_migrations()
    couple_id = db.link_couple(1, 2, 1234, "UTC")
    db.set_pref(couple_id, 1, enable_alerts=True, sla_minutes=60, max_neg_per_day=3, max_pos_per_day=3)
    db.set_pref(couple_id, 2, enable_alerts=True, sla_minutes=60, max_neg_per_day=3, max_pos_per_day=3)
    return couple_id


@pytest.mark.asyncio
async def test_cooldown_and_dnd(monkeypatch, tmp_path):
    couple_id = _setup_env(monkeypatch, tmp_path)
    client = DummyClient()
    now = datetime(2024, 1, 1, 12, 0, 0)

    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="test",
        tz_name="UTC",
        now=now,
    )
    assert sent
    assert len(client.sent) == 1

    # Cooldown should block immediate repeat
    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="test",
        tz_name="UTC",
        now=now + timedelta(minutes=5),
    )
    assert not sent
    assert len(client.sent) == 1

    # After cooldown
    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="test",
        tz_name="UTC",
        now=now + timedelta(minutes=11),
    )
    assert sent
    assert len(client.sent) == 2

    # DND window should block
    db.set_pref(couple_id, 1, dnd_start="11:00", dnd_end="23:00")
    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="test",
        tz_name="UTC",
        now=now + timedelta(hours=1),
    )
    assert not sent


@pytest.mark.asyncio
async def test_red_backoff(monkeypatch, tmp_path):
    couple_id = _setup_env(monkeypatch, tmp_path)
    client = DummyClient()
    base = datetime(2024, 1, 1, 8, 0, 0)
    db.set_pref(couple_id, 1, max_neg_per_day=5)

    for idx in range(3):
        sent = await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=1,
            metric_key="harsh_start_rate",
            kind=AlertKind.RISK,
            text="risk",
            tz_name="UTC",
            now=base + timedelta(minutes=idx * 30),
        )
        assert sent

    # Backoff window triggers
    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="risk",
        tz_name="UTC",
        now=base + timedelta(minutes=100),
    )
    assert not sent

    # After backoff expires
    sent = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="harsh_start_rate",
        kind=AlertKind.RISK,
        text="risk",
        tz_name="UTC",
        now=base + timedelta(minutes=190),
    )
    assert sent


@pytest.mark.asyncio
async def test_daily_caps_for_new_triggers(monkeypatch, tmp_path):
    couple_id = _setup_env(monkeypatch, tmp_path)
    client = DummyClient()
    start = datetime(2024, 1, 2, 9, 0, 0)

    # Risk cap
    for idx in range(3):
        sent = await pings.maybe_ping(
            client,
            couple_id=couple_id,
            user_id=1,
            metric_key="neg_affect_reciprocity",
            kind=AlertKind.RISK,
            text="risk",
            tz_name="UTC",
            now=start + timedelta(minutes=idx * 15),
        )
        assert sent
    blocked = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="neg_affect_reciprocity",
        kind=AlertKind.RISK,
        text="risk",
        tz_name="UTC",
        now=start + timedelta(hours=3),
    )
    assert not blocked

    # Praise cap
    db.set_pref(couple_id, 1, max_pos_per_day=1)
    first = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="soft_start",
        kind=AlertKind.PRAISE,
        text="praise",
        tz_name="UTC",
        now=start,
    )
    assert first
    second = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="soft_start",
        kind=AlertKind.PRAISE,
        text="praise",
        tz_name="UTC",
        now=start + timedelta(minutes=20),
    )
    assert not second

    # Logistics cap follows positive allowance
    db.set_pref(couple_id, 1, max_pos_per_day=2)
    log_base = start + timedelta(hours=5)
    assert await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="median_reply_seconds",
        kind=AlertKind.LOGISTICS,
        text="log",
        tz_name="UTC",
        now=log_base,
    )
    assert await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="median_reply_seconds",
        kind=AlertKind.LOGISTICS,
        text="log",
        tz_name="UTC",
        now=log_base + timedelta(minutes=30),
    )
    blocked_log = await pings.maybe_ping(
        client,
        couple_id=couple_id,
        user_id=1,
        metric_key="median_reply_seconds",
        kind=AlertKind.LOGISTICS,
        text="log",
        tz_name="UTC",
        now=log_base + timedelta(hours=2),
    )
    assert not blocked_log
