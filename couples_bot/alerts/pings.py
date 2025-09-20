"""Instant DM feedback helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .. import db
from ..models import AlertKind
from ..utils import timebox

PING_COOLDOWN_MINUTES = 10
RED_BACKOFF_MINUTES = 60
RED_WINDOW_HOURS = 2


def _combine_dnd(pref_row) -> Optional[str]:
    if not pref_row:
        return None
    start = pref_row["dnd_start"]
    end = pref_row["dnd_end"]
    if start and end:
        return f"{start}-{end}"
    return None


async def maybe_ping(
    client,
    *,
    couple_id: int,
    user_id: int,
    metric_key: str,
    kind: AlertKind,
    text: str,
    tz_name: str = "UTC",
    now: Optional[datetime] = None,
) -> bool:
    """Send a DM if cooldown/DND/daily caps allow it."""

    now = now or timebox.utc_now()
    pref = db.fetch_pref(couple_id, user_id)
    if pref and pref["enable_alerts"] == 0:
        return False

    dnd = _combine_dnd(pref)
    if timebox.is_within_dnd(now, dnd, tz_name):
        return False

    last = db.fetch_cooldown(couple_id, user_id, metric_key)
    if timebox.within_cooldown(last, now, PING_COOLDOWN_MINUTES):
        return False

    if kind == AlertKind.RISK:
        backoff_last = db.fetch_cooldown(couple_id, user_id, "red_backoff")
        if timebox.within_cooldown(backoff_last, now, RED_BACKOFF_MINUTES):
            return False

    bucket = timebox.daily_bucket(now)
    cap_key = "max_neg_per_day" if kind == AlertKind.RISK else "max_pos_per_day"
    if kind == AlertKind.LOGISTICS:
        cap_key = "max_pos_per_day"
    cap = pref[cap_key] if pref else 5
    stat_key = f"ping_daily:{user_id}:{bucket}:{kind.value}"
    sent_today = int(db.get_stat(couple_id, stat_key, default=0))
    if sent_today >= cap:
        return False

    # Send the ping
    await client.send_message(user_id, text[:320])

    db.record_cooldown(couple_id, user_id, metric_key, now)
    db.upsert_stat(couple_id, stat_key, sent_today + 1)

    if kind == AlertKind.RISK:
        start_key = f"red_window_start:{user_id}"
        count_key = f"red_window_count:{user_id}"
        start_value = db.get_stat(couple_id, start_key, default=0)
        if start_value:
            start_dt = datetime.fromtimestamp(start_value)
        else:
            start_dt = now
            db.upsert_stat(couple_id, start_key, now.timestamp())
        if (now - start_dt) > timedelta(hours=RED_WINDOW_HOURS):
            db.upsert_stat(couple_id, start_key, now.timestamp())
            db.upsert_stat(couple_id, count_key, 1)
        else:
            count = int(db.get_stat(couple_id, count_key, default=0)) + 1
            db.upsert_stat(couple_id, count_key, count)
            if count >= 3:
                db.record_cooldown(couple_id, user_id, "red_backoff", now)
    return True


def format_ping(kind: AlertKind, metric_key: str, value: float | None = None) -> str:
    base = {
        AlertKind.PRAISE: "Nice move—",
        AlertKind.RISK: "Heads-up—",
        AlertKind.LOGISTICS: "Logistics note—",
    }[kind]
    tails = {
        "harsh_start_rate": "try a soft opener next time. Offer one feeling + one ask.",
        "repair_success": "that repair landed. Keep that tone going tonight.",
        "turn_toward": "you turned toward their bid. Repeat it later today.",
        "sla_miss": "a reply is running late. Send a quick timing update.",
    }
    detail = tails.get(metric_key, "take one concrete action now.")
    if value is not None:
        detail += f" Current level: {value:.2f}."
    return f"{base}{detail}"


__all__ = ["maybe_ping", "format_ping"]
