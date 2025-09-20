"""SQLite-backed REAG job queue helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from . import db
from .config import get_settings

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

_CHAOS_CLAIM_TRIPPED = False


def _utc_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _maybe_fail_once() -> None:
    global _CHAOS_CLAIM_TRIPPED
    settings = get_settings()
    if not settings.chaos_mode:
        return
    if _CHAOS_CLAIM_TRIPPED:
        return
    _CHAOS_CLAIM_TRIPPED = True
    raise RuntimeError("CHAOS: simulated queue failure")


def enqueue_job(
    *,
    couple_id: int,
    chat_id: int,
    payload_json: str,
    payload_hash: str,
    job_kind: str,
    priority: str,
    window_start_ts: Optional[int],
    window_end_ts: Optional[int],
    retry_after_ts: Optional[int] = None,
) -> Optional[int]:
    """Insert a pending job keyed by window metadata if it does not yet exist."""

    created_ts = _utc_timestamp()
    with db.get_conn() as conn:
        try:
            conn.execute(
                """
                INSERT INTO jobs(
                    couple_id,
                    chat_id,
                    job_kind,
                    priority,
                    payload_json,
                    payload_hash,
                    window_start_ts,
                    window_end_ts,
                    retry_after_ts,
                    created_ts,
                    status
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    couple_id,
                    chat_id,
                    job_kind,
                    priority,
                    payload_json,
                    payload_hash,
                    window_start_ts,
                    window_end_ts,
                    retry_after_ts,
                    created_ts,
                    STATUS_PENDING,
                ),
            )
        except sqlite3.IntegrityError:
            return None
        job_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return int(job_id)


def job_exists(couple_id: int, payload_hash: str) -> bool:
    """Return True if a matching pending or running job exists."""

    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE couple_id = ?
              AND payload_hash = ?
              AND status IN (?, ?)
            LIMIT 1
            """,
            (couple_id, payload_hash, STATUS_PENDING, STATUS_RUNNING),
        ).fetchone()
    return bool(row)


def has_active_job(couple_id: int) -> bool:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE couple_id = ? AND status IN (?, ?)
            LIMIT 1
            """,
            (couple_id, STATUS_PENDING, STATUS_RUNNING),
        ).fetchone()
    return bool(row)


def pending_jobs_count(include_future: bool = False) -> int:
    """Count pending jobs that are ready to run (respecting retry_after)."""

    clause = "status = ?"
    params: List[object] = [STATUS_PENDING]
    if not include_future:
        clause += " AND (retry_after_ts IS NULL OR retry_after_ts <= ?)"
        params.append(_utc_timestamp())
    with db.get_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(1) AS cnt FROM jobs WHERE {clause}",
            params,
        ).fetchone()
    return int(row["cnt"]) if row else 0


def _fetch_job_by_id(job_id: int):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def claim_job() -> Optional[Mapping[str, Any]]:
    """Claim the highest-priority pending job and mark it as running."""

    _maybe_fail_once()
    now_ts = _utc_timestamp()
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = ?
              AND (retry_after_ts IS NULL OR retry_after_ts <= ?)
            ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END,
                     created_ts ASC
            LIMIT 1
            """,
            (STATUS_PENDING, now_ts),
        ).fetchone()
        if not row:
            return None
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, started_ts = ?, retry_after_ts = NULL
            WHERE id = ? AND status = ?
            """,
            (STATUS_RUNNING, now_ts, row["id"], STATUS_PENDING),
        )
        if cursor.rowcount == 0:
            return None
    return _fetch_job_by_id(int(row["id"]))


def complete_job(
    job_id: int,
    *,
    couple_id: int,
    token_in: int,
    token_out: int,
    model: str,
    window_start_ts: int,
    window_end_ts: int,
) -> None:
    now_ts = _utc_timestamp()
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, finished_ts = ?, error = NULL
            WHERE id = ?
            """,
            (STATUS_DONE, now_ts, job_id),
        )
        conn.execute(
            """
            INSERT INTO reag_runs(
                couple_id,
                window_start_ts,
                window_end_ts,
                token_in,
                token_out,
                model,
                created_ts
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                couple_id,
                window_start_ts,
                window_end_ts,
                token_in,
                token_out,
                model,
                now_ts,
            ),
        )


def fail_job(job_id: int, error_msg: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, finished_ts = ?, error = ?
            WHERE id = ?
            """,
            (STATUS_FAILED, _utc_timestamp(), error_msg[:512], job_id),
        )


def last_run_for_couple(couple_id: int) -> Optional[int]:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT window_end_ts FROM reag_runs
            WHERE couple_id = ?
            ORDER BY created_ts DESC
            LIMIT 1
            """,
            (couple_id,),
        ).fetchone()
    return int(row["window_end_ts"]) if row else None


def pending_context_slice(couple_id: int) -> List[Dict[str, Any]]:
    last_ts = last_run_for_couple(couple_id)
    since_dt = datetime.fromtimestamp(last_ts, timezone.utc) if last_ts else None
    rows = db.fetch_messages_since(couple_id, since_dt)
    docs: List[Dict[str, Any]] = []
    for row in rows:
        ts_str = row["ts"]
        ts_obj = datetime.fromisoformat(ts_str)
        docs.append(
            {
                "type": "message",
                "role": f"user:{row['sender_id']}",
                "sender_id": int(row["sender_id"]),
                "text": row["text"],
                "ts": ts_str,
                "ts_int": int(ts_obj.timestamp()),
            }
        )
    return docs


def hash_payload(payload: Mapping[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def reset_chaos_state() -> None:
    global _CHAOS_CLAIM_TRIPPED
    _CHAOS_CLAIM_TRIPPED = False


__all__ = [
    "enqueue_job",
    "job_exists",
    "pending_jobs_count",
    "claim_job",
    "complete_job",
    "fail_job",
    "last_run_for_couple",
    "pending_context_slice",
    "hash_payload",
    "reset_chaos_state",
    "has_active_job",
]
