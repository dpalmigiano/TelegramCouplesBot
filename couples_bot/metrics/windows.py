"""Windowing helpers for metric computation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Iterator, List, Sequence

import sqlite3


MessageRow = sqlite3.Row


def rolling_messages(messages: Sequence[MessageRow], window_minutes: int) -> Iterator[List[MessageRow]]:
    """Yield slices of messages within the trailing window."""

    window: List[MessageRow] = []
    for msg in messages:
        ts = datetime.fromisoformat(msg["ts"])
        window.append(msg)
        cutoff = ts - timedelta(minutes=window_minutes)
        window = [m for m in window if datetime.fromisoformat(m["ts"]) >= cutoff]
        yield list(window)


def conflict_segments(messages: Sequence[MessageRow], gap_minutes: int = 30) -> List[List[MessageRow]]:
    segments: List[List[MessageRow]] = []
    current: List[MessageRow] = []
    last_ts: datetime | None = None
    for msg in messages:
        ts = datetime.fromisoformat(msg["ts"])
        if last_ts is not None and ts - last_ts > timedelta(minutes=gap_minutes):
            if current:
                segments.append(current)
            current = []
        current.append(msg)
        last_ts = ts
    if current:
        segments.append(current)
    return segments


__all__ = ["rolling_messages", "conflict_segments"]
