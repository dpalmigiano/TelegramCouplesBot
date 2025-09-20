"""Windowing helpers for metric computation."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from . import classifiers


@dataclass
class MessageRecord:
    sender_id: int
    text: str
    ts: dt.datetime


def parse_ts(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def to_records(messages: Sequence[dict]) -> List[MessageRecord]:
    return [
        MessageRecord(sender_id=int(m["sender_id"]), text=str(m["text"]), ts=parse_ts(str(m["ts"]))
        )
        for m in messages
    ]


def conversation_hours(messages: Sequence[MessageRecord]) -> float:
    if not messages:
        return 0.0
    duration = (messages[-1].ts - messages[0].ts).total_seconds()
    return max(1 / 3600, duration / 3600)


def consecutive_pairs(records: Sequence[MessageRecord]) -> Iterable[tuple[MessageRecord, MessageRecord]]:
    prev = None
    for record in records:
        if prev is not None:
            yield prev, record
        prev = record


def cross_user_pairs(records: Sequence[MessageRecord]) -> List[tuple[MessageRecord, MessageRecord]]:
    return [
        (a, b)
        for a, b in consecutive_pairs(records)
        if a.sender_id != b.sender_id
    ]


def conflict_segments(records: Sequence[MessageRecord], gap_minutes: int = 45) -> List[List[MessageRecord]]:
    segments: List[List[MessageRecord]] = []
    current: List[MessageRecord] = []
    last_conflict_ts: dt.datetime | None = None
    for record in records:
        labels = classifiers.label_text(record.text)
        is_conflict = labels.negative or labels.boundary or labels.contempt
        if is_conflict:
            if not current:
                current.append(record)
            else:
                gap = (record.ts - current[-1].ts).total_seconds() / 60
                if gap > gap_minutes:
                    segments.append(current)
                    current = [record]
                else:
                    current.append(record)
            last_conflict_ts = record.ts
        else:
            if current and last_conflict_ts:
                gap = (record.ts - last_conflict_ts).total_seconds() / 60
                if gap > gap_minutes:
                    segments.append(current)
                    current = []
    if current:
        segments.append(current)
    return segments


__all__ = [
    "MessageRecord",
    "parse_ts",
    "to_records",
    "conversation_hours",
    "consecutive_pairs",
    "cross_user_pairs",
    "conflict_segments",
]
