"""Bot command helpers."""
from __future__ import annotations

import sqlite3
from typing import Optional

from .. import db
from ..advice import advice_engine
from ..metrics import compute as metrics_compute


def _couple_by_group(conn: sqlite3.Connection, group_chat_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM couples WHERE group_chat_id = ?", (group_chat_id,))
    return cur.fetchone()


def _couple_by_id(conn: sqlite3.Connection, couple_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM couples WHERE id = ?", (couple_id,))
    return cur.fetchone()


def link_command(conn: sqlite3.Connection, group_chat_id: int, user_a_id: int, user_b_id: int, tz: str) -> str:
    existing = _couple_by_group(conn, group_chat_id)
    if existing:
        return "Group already linked to a couple."
    conn.execute(
        "INSERT INTO couples (user_a_id, user_b_id, group_chat_id, tz) VALUES (?, ?, ?, ?)",
        (user_a_id, user_b_id, group_chat_id, tz),
    )
    conn.commit()
    return "Couple linked. Ask each partner to DM /consent yes."


def consent_command(conn: sqlite3.Connection, couple_id: int, user_id: int, accepted: bool) -> str:
    status_key = f"consent:{user_id}"
    db.write_stat(conn, couple_id, status_key, 1.0 if accepted else 0.0)
    partner_key = f"consent_status:{couple_id}"
    stats = db.fetch_stats(conn, couple_id)
    consent_a = stats.get(f"consent:{user_id}")
    consent_b = stats.get(f"consent:{_other_partner(conn, couple_id, user_id)}")
    if consent_a and consent_b:
        conn.execute(
            "UPDATE couples SET tz = tz WHERE id = ?",
            (couple_id,),
        )
        conn.commit()
        return "Consent received from both partners. Tracking is live."
    return "Consent recorded. Waiting for your partner."


def _other_partner(conn: sqlite3.Connection, couple_id: int, user_id: int) -> int:
    couple = _couple_by_id(conn, couple_id)
    if not couple:
        return user_id
    if couple["user_a_id"] == user_id:
        return couple["user_b_id"]
    return couple["user_a_id"]


def status_command(conn: sqlite3.Connection, couple_id: int) -> str:
    messages = [dict(row) for row in db.iter_messages(conn, couple_id)]
    metrics = metrics_compute.compute_metrics(messages)
    tracked = (
        metrics.get("p_to_n_conflict_ratio"),
        metrics.get("harsh_start_rate"),
        metrics.get("median_reply_seconds"),
    )
    return (
        "Metrics — P:N ratio: {:.2f}, harsh starts: {:.2f}, median reply: {:.0f}s".format(
            tracked[0] or 0.0, tracked[1] or 0.0, tracked[2] or 0.0
        )
    )


def advice_command(conn: sqlite3.Connection, couple_id: int, user_id: int) -> str:
    return advice_engine.build_advice_for_user(couple_id, user_id, conn=conn)


def simple_ack(text: str) -> str:
    return text


def pause_command(_: sqlite3.Connection, __: int) -> str:
    return "Paused tracking for this couple (placeholder)."


def resume_command(_: sqlite3.Connection, __: int) -> str:
    return "Resumed tracking for this couple (placeholder)."


def export_command(_: sqlite3.Connection, __: int) -> str:
    return "Export not yet implemented."


def admin_couples(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT id, user_a_id, user_b_id FROM couples")
    rows = cur.fetchall()
    if not rows:
        return "No couples linked."
    return "\n".join(f"#{row['id']}: {row['user_a_id']} & {row['user_b_id']}" for row in rows)


def unlink_command(conn: sqlite3.Connection, group_chat_id: int) -> str:
    conn.execute("DELETE FROM couples WHERE group_chat_id = ?", (group_chat_id,))
    conn.commit()
    return "Couple unlinked."


def wipe_command(conn: sqlite3.Connection, couple_id: int) -> str:
    conn.execute("DELETE FROM couples WHERE id = ?", (couple_id,))
    conn.commit()
    return "Couple wiped."


__all__ = [
    "link_command",
    "consent_command",
    "status_command",
    "advice_command",
    "pause_command",
    "resume_command",
    "export_command",
    "admin_couples",
    "unlink_command",
    "wipe_command",
    "simple_ack",
]
