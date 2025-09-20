"""SQLite-backed REAG job queue helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import db


def _utc_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def enqueue_job(couple_id: int, payload_json: str, payload_hash: str) -> Optional[int]:
    with db.get_conn() as conn:
        try:
            conn.execute(
                """
                INSERT INTO jobs(couple_id, payload_json, payload_hash, created_ts, status)
                VALUES(?,?,?,?, 'pending')
                """,
                (couple_id, payload_json, payload_hash, _utc_timestamp()),
            )
        except sqlite3.IntegrityError:
            return None
        job_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return int(job_id)


def job_exists(couple_id: int, payload_hash: str) -> bool:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE couple_id = ? AND payload_hash = ?",
            (couple_id, payload_hash),
        ).fetchone()
    return bool(row and row["status"] in {"pending", "started", "done"})


def pending_jobs_count() -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(1) AS cnt FROM jobs WHERE status = 'pending'",
        ).fetchone()
    return int(row["cnt"]) if row else 0


def claim_job() -> Optional[sqlite3.Row]:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'pending'
            ORDER BY created_ts ASC
            LIMIT 1
            """,
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'started', started_ts = ? WHERE id = ?",
            (_utc_timestamp(), row["id"]),
        )
    return row


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
            "UPDATE jobs SET status = 'done', finished_ts = ?, error = NULL WHERE id = ?",
            (now_ts, job_id),
        )
        conn.execute(
            """
            INSERT INTO reag_runs(couple_id, window_start_ts, window_end_ts, token_in, token_out, model, created_ts)
            VALUES(?,?,?,?,?,?,?)
            """,
            (couple_id, window_start_ts, window_end_ts, token_in, token_out, model, now_ts),
        )


def fail_job(job_id: int, error_msg: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', finished_ts = ?, error = ? WHERE id = ?",
            (_utc_timestamp(), error_msg[:512], job_id),
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
        ts_str = str(row["ts"])
        ts_obj = datetime.fromisoformat(ts_str)
        docs.append(
            {
                "type": "message",
                "id": int(row["id"]) if "id" in row.keys() else None,
                "chat_id": int(row["chat_id"]),
                "sender_id": int(row["sender_id"]),
                "text": row["text"],
                "ts": ts_str,
                "ts_int": int(ts_obj.timestamp()),
            }
        )
    return docs


__all__ = [
    "enqueue_job",
    "job_exists",
    "pending_jobs_count",
    "claim_job",
    "complete_job",
    "fail_job",
    "last_run_for_couple",
    "pending_context_slice",
]
