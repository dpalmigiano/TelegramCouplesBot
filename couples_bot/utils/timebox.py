"""Time-related helpers for cooldowns, DND windows, and reply SLAs."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Optional
from zoneinfo import ZoneInfo


@dataclass
class Window:
    start: dt.time
    end: dt.time


def parse_time_window(window_str: str) -> Optional[Window]:
    if not window_str:
        return None
    try:
        start_str, end_str = window_str.split("-")
        start = dt.time.fromisoformat(start_str)
        end = dt.time.fromisoformat(end_str)
    except ValueError:
        return None
    return Window(start=start, end=end)


def now_in_tz(tz: str | ZoneInfo) -> dt.datetime:
    zone = ZoneInfo(str(tz)) if not isinstance(tz, ZoneInfo) else tz
    return dt.datetime.now(zone)


def is_within_window(now: dt.datetime, window: Window) -> bool:
    if window.start <= window.end:
        return window.start <= now.timetz().replace(tzinfo=None) <= window.end
    # overnight
    return now.timetz().replace(tzinfo=None) >= window.start or now.timetz().replace(tzinfo=None) <= window.end


def in_dnd(now: dt.datetime, dnd_start: Optional[str], dnd_end: Optional[str]) -> bool:
    if not (dnd_start and dnd_end):
        return False
    window = parse_time_window(f"{dnd_start}-{dnd_end}")
    if not window:
        return False
    return is_within_window(now, window)


def seconds_between(ts_a: dt.datetime, ts_b: dt.datetime) -> float:
    return abs((ts_b - ts_a).total_seconds())


def hours_between(ts_a: dt.datetime, ts_b: dt.datetime) -> float:
    return seconds_between(ts_a, ts_b) / 3600


def iter_pairs(items: Iterable[dt.datetime]) -> Iterable[tuple[dt.datetime, dt.datetime]]:
    previous: Optional[dt.datetime] = None
    for item in items:
        if previous is not None:
            yield previous, item
        previous = item


def window_minutes_ago(now: dt.datetime, minutes: int) -> dt.datetime:
    return now - dt.timedelta(minutes=minutes)


__all__ = [
    "Window",
    "parse_time_window",
    "now_in_tz",
    "is_within_window",
    "in_dnd",
    "seconds_between",
    "hours_between",
    "iter_pairs",
    "window_minutes_ago",
]
