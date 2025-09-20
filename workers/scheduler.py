"""Scheduler helpers for REAG jobs."""

from __future__ import annotations

import json
import random
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
    pending_jobs_count,
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


def _silence_for_couple(couple_id: int, default: int) -> int:
    override = int(db.get_stat(couple_id, "reag:silence_override_secs", default=0))
    if override:
        db.upsert_stat(couple_id, "reag:silence_override_secs", 0)
        return override
    return default


def _retry_after_ok(couple_id: int, now_ts: int) -> bool:
    retry_at = db.get_stat(couple_id, "reag:retry_after_ts", default=0.0)
    return retry_at == 0.0 or now_ts >= int(retry_at)


def collect_batches(
    now: datetime | None = None,
) -> List[Tuple[int, int, List[dict], bool, Tuple[str, ...], str, str]]:
    settings = get_settings()
    now = now or timebox.utc_now()
    batches: List[Tuple[int, int, List[dict], bool, Tuple[str, ...], str, str]] = []
    for couple in db.list_couples():
        couple_id = int(couple["id"])
        chat_id = int(couple["group_chat_id"])
        last_message_dt = db.fetch_last_message_ts(couple_id)
        if not last_message_dt:
            continue
        silence_secs = _silence_for_couple(couple_id, settings.reag_silence_secs)
        if not should_run(int(last_message_dt.timestamp()), silence_secs):
            continue
        if not _retry_after_ok(couple_id, int(now.timestamp())):
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
        job_kind = "analysis" if use_tools else "sync"
        priority = "high" if use_tools else "normal"
        batches.append((couple_id, chat_id, docs, use_tools, enabled_tools, job_kind, priority))
    return batches


def enqueue_if_calm(now: datetime | None = None) -> int:
    now = now or timebox.utc_now()
    enqueued = 0
    settings = get_settings()
    for couple_id, chat_id, docs, use_tools, enabled_tools, job_kind, priority in collect_batches(now):
        queue_len = pending_jobs_count()
        if queue_len >= settings.reag_queue_high_watermark and priority != "high":
            jitter = random.randint(60, 180)
            db.upsert_stat(couple_id, "reag:retry_after_ts", int(now.timestamp()) + jitter)
            continue
        db.upsert_stat(couple_id, "reag:retry_after_ts", 0.0)
        payload = {
            "couple_id": couple_id,
            "chat_id": chat_id,
            "docs": docs,
            "use_tools": use_tools,
            "enabled_tools": list(enabled_tools),
            "created_ts": int(now.timestamp()),
            "job_kind": job_kind,
            "priority": priority,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        payload_hash = hash_payload(payload)
        if job_exists(couple_id, payload_hash):
            continue
        window_start = min(int(doc.get("ts_int", int(now.timestamp()))) for doc in docs)
        window_end = max(int(doc.get("ts_int", window_start)) for doc in docs)
        job_id = enqueue_job(
            couple_id=couple_id,
            chat_id=chat_id,
            payload_json=payload_json,
            payload_hash=payload_hash,
            job_kind=job_kind,
            priority=priority,
            window_start_ts=window_start,
            window_end_ts=window_end,
        )
        if job_id is not None:
            enqueued += 1
    return enqueued


def tick(now: datetime | None = None) -> int:
    """Convenience alias for enqueue_if_calm to match app expectations."""

    return enqueue_if_calm(now)


__all__ = ["should_run", "collect_batches", "enqueue_if_calm", "tick"]
