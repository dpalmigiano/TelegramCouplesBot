"""Scheduler helpers for REAG jobs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, List, Tuple

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.db_jobs import (
    enqueue_job,
    has_active_job,
    hash_payload,
    job_exists,
    last_run_for_couple,
    pending_context_slice,
)
from couples_bot.utils import timebox


def should_run(last_ts: int | None, silence_secs: int) -> bool:
    if last_ts is None:
        return False
    now_ts = int(timebox.utc_now().timestamp())
    return now_ts - last_ts >= silence_secs


def _enabled_tools_for_docs(docs: Iterable[dict]) -> Tuple[str, ...]:
    tools: List[str] = []
    for doc in docs:
        doc_type = doc.get("type")
        if doc_type in {"plan_confirmation", "call_summary"} and "calendar" not in tools:
            tools.append("calendar")
    return tuple(tools)


def collect_batches(now: datetime | None = None) -> List[Tuple[int, List[dict], bool, Tuple[str, ...]]]:
    settings = get_settings()
    now = now or timebox.utc_now()
    batches: List[Tuple[int, List[dict], bool, Tuple[str, ...]]] = []
    for couple in db.list_couples():
        couple_id = int(couple["id"])
        last_message_dt = db.fetch_last_message_ts(couple_id)
        if not last_message_dt:
            continue
        if not should_run(int(last_message_dt.timestamp()), settings.reag_silence_secs):
            continue
        last_completed = last_run_for_couple(couple_id)
        if last_completed is not None:
            if int(now.timestamp()) - last_completed < settings.reag_min_interval_secs:
                continue
        if has_active_job(couple_id):
            continue
        docs = pending_context_slice(couple_id)
        if not docs:
            continue
        use_tools = any(doc.get("type") != "message" for doc in docs)
        enabled_tools = _enabled_tools_for_docs(docs)
        batches.append((couple_id, docs, use_tools, enabled_tools))
    return batches


def enqueue_if_calm(now: datetime | None = None) -> int:
    now = now or timebox.utc_now()
    enqueued = 0
    for couple_id, docs, use_tools, enabled_tools in collect_batches(now):
        payload = {
            "couple_id": couple_id,
            "docs": docs,
            "use_tools": use_tools,
            "enabled_tools": list(enabled_tools),
            "created_ts": int(now.timestamp()),
        }
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        payload_hash = hash_payload(payload)
        if job_exists(couple_id, payload_hash):
            continue
        job_id = enqueue_job(couple_id, payload_json, payload_hash)
        if job_id is not None:
            enqueued += 1
    return enqueued


def tick(now: datetime | None = None) -> int:
    """Convenience alias for enqueue_if_calm to match app expectations."""

    return enqueue_if_calm(now)


__all__ = ["should_run", "collect_batches", "enqueue_if_calm", "tick"]
