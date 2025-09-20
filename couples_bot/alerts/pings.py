"""Instant DM feedback helpers."""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from zoneinfo import ZoneInfo

from .. import db
from ..models import AlertKind
from ..utils import timebox

DEFAULT_COOLDOWN_MINUTES = 10

PREFIX = {
    AlertKind.PRAISE: "Green light",
    AlertKind.RISK: "Heads-up",
    AlertKind.LOGISTICS: "Logistics",
}


def _format(kind: AlertKind, text: str) -> str:
    prefix = PREFIX[kind]
    body = f"{prefix}: {text.strip()}"
    return body[:320]


def _daily_key(user_id: int, kind: AlertKind, today: dt.date) -> str:
    return f"alerts:{user_id}:{kind.value}:{today.isoformat()}"


def maybe_ping(
    conn,
    *,
    couple_id: int,
    user_id: int,
    metric_key: str,
    kind: AlertKind,
    text: str,
    send_func: Optional[Callable[[str], None]] = None,
    now: Optional[dt.datetime] = None,
    tz: str = "UTC",
) -> bool:
    """Trigger an alert if cooldowns, caps, and DND allow."""

    send = send_func or (lambda _: None)
    moment = now or dt.datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    if moment.tzinfo is None:
        moment_utc = moment.replace(tzinfo=ZoneInfo("UTC"))
    else:
        moment_utc = moment.astimezone(ZoneInfo("UTC"))
    moment_naive = moment_utc.replace(tzinfo=None)

    prefs = db.get_prefs(conn, couple_id, user_id)
    if not prefs["enable_alerts"]:
        return False

    zoned_now = moment_utc.astimezone(ZoneInfo(tz))
    if timebox.in_dnd(zoned_now, prefs["dnd_start"], prefs["dnd_end"]):
        return False

    last_fired = db.get_cooldown(conn, couple_id, user_id, metric_key)
    if last_fired:
        try:
            last_dt = dt.datetime.fromisoformat(last_fired)
        except ValueError:
            last_dt = moment_naive - dt.timedelta(minutes=DEFAULT_COOLDOWN_MINUTES + 1)
        if (moment_naive - last_dt) < dt.timedelta(minutes=DEFAULT_COOLDOWN_MINUTES):
            return False

    stats = db.fetch_stats(conn, couple_id)
    today_key = _daily_key(user_id, kind, moment_utc.date())
    count = float(stats.get(today_key, 0.0))
    limit = prefs["max_pos_per_day"] if kind != AlertKind.RISK else prefs["max_neg_per_day"]
    if count >= limit:
        return False

    send(_format(kind, text))

    fired_at = moment_naive.isoformat(sep=" ", timespec="seconds")
    db.record_cooldown(conn, couple_id, user_id, metric_key, fired_at=fired_at)
    db.write_stat(conn, couple_id, today_key, count + 1)
    return True


__all__ = ["maybe_ping"]
