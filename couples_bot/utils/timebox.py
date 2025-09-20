"""Time handling helpers for alerts and advice cadence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DNDWindow:
    start: time
    end: time

    @classmethod
    def parse(cls, value: str) -> "DNDWindow":
        start_s, end_s = value.split("-")
        return cls(_parse_time(start_s), _parse_time(end_s))

    def contains(self, when: datetime) -> bool:
        local = when.timetz()
        current = time(local.hour, local.minute)
        if self.start <= self.end:
            return self.start <= current < self.end
        # Overnight window
        return current >= self.start or current < self.end


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def ensure_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - zoneinfo raises KeyError
        return ZoneInfo("UTC")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_tz(dt: datetime, tz_name: str) -> datetime:
    tz = ensure_tz(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def is_within_dnd(now: datetime, dnd_window: Optional[str], tz_name: str) -> bool:
    if not dnd_window:
        return False
    window = DNDWindow.parse(dnd_window)
    local_now = to_tz(now, tz_name)
    return window.contains(local_now)


def minutes_between(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 60.0


def hours_between(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 3600.0


def within_cooldown(last: Optional[datetime], now: datetime, minutes: int) -> bool:
    if last is None:
        return False
    return (now - last) < timedelta(minutes=minutes)


def sla_breached(last_activity: datetime, now: datetime, sla_minutes: int) -> bool:
    if sla_minutes <= 0:
        return False
    return (now - last_activity) > timedelta(minutes=sla_minutes)


def window_elapsed(last: Optional[datetime], now: datetime, minutes: int) -> bool:
    if last is None:
        return True
    return (now - last) >= timedelta(minutes=minutes)


def daily_bucket(dt: datetime) -> str:
    local = dt.date()
    return local.isoformat()


def minute_bucket(dt: datetime) -> str:
    truncated = dt.replace(second=0, microsecond=0)
    return truncated.isoformat()

