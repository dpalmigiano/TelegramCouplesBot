"""SQLite helpers for persistence."""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable, Optional

from .config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_CONNECTION: Optional[sqlite3.Connection] = None


def _ensure_connection(database_path: Optional[Path] = None) -> sqlite3.Connection:
    global _CONNECTION
    if _CONNECTION is None:
        settings = get_settings()
        db_path = Path(database_path or settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _CONNECTION = sqlite3.connect(db_path)
        _CONNECTION.row_factory = sqlite3.Row
        _CONNECTION.execute("PRAGMA foreign_keys = ON")
    return _CONNECTION


def get_conn(database_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a module-level SQLite connection."""

    return _ensure_connection(database_path)


@contextmanager
def get_cursor(database_path: Optional[Path] = None) -> Generator[sqlite3.Cursor, None, None]:
    conn = _ensure_connection(database_path)
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        cur.close()


def run_migrations(database_path: Optional[Path] = None) -> None:
    """Execute the SQL schema if the tables do not yet exist."""

    conn = _ensure_connection(database_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()


def upsert_advice(conn: sqlite3.Connection, couple_id: int, for_user_id: int, advice_text: str) -> None:
    conn.execute(
        """
        INSERT INTO advice (couple_id, for_user_id, advice_text, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(couple_id, for_user_id)
        DO UPDATE SET advice_text=excluded.advice_text, updated_at=CURRENT_TIMESTAMP
        """,
        (couple_id, for_user_id, advice_text),
    )
    conn.commit()


def write_stat(conn: sqlite3.Connection, couple_id: int, key: str, value: float) -> None:
    conn.execute(
        """
        INSERT INTO stats (couple_id, key, value, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(couple_id, key)
        DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """,
        (couple_id, key, value),
    )
    conn.commit()


def fetch_stats(conn: sqlite3.Connection, couple_id: int) -> dict[str, float]:
    cur = conn.execute("SELECT key, value FROM stats WHERE couple_id = ?", (couple_id,))
    return {row[0]: row[1] for row in cur.fetchall()}


def record_cooldown(
    conn: sqlite3.Connection,
    couple_id: int,
    user_id: int,
    metric_key: str,
    *,
    fired_at: Optional[str] = None,
) -> None:
    ts_value = fired_at or dt.datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn.execute(
        """
        INSERT INTO cooldowns (couple_id, user_id, metric_key, last_fired)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(couple_id, user_id, metric_key)
        DO UPDATE SET last_fired=excluded.last_fired
        """,
        (couple_id, user_id, metric_key, ts_value),
    )
    conn.commit()


def get_cooldown(
    conn: sqlite3.Connection,
    couple_id: int,
    user_id: int,
    metric_key: str,
) -> Optional[str]:
    cur = conn.execute(
        "SELECT last_fired FROM cooldowns WHERE couple_id = ? AND user_id = ? AND metric_key = ?",
        (couple_id, user_id, metric_key),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_prefs(conn: sqlite3.Connection, couple_id: int, user_id: int) -> sqlite3.Row:
    cur = conn.execute(
        """
        SELECT dnd_start, dnd_end, enable_alerts, max_neg_per_day, max_pos_per_day, sla_minutes
        FROM prefs WHERE couple_id = ? AND user_id = ?
        """,
        (couple_id, user_id),
    )
    row = cur.fetchone()
    if row:
        return row
    # Insert defaults if not present
    conn.execute(
        """
        INSERT INTO prefs (couple_id, user_id, enable_alerts, max_neg_per_day, max_pos_per_day, sla_minutes)
        VALUES (?, ?, 1, 5, 8, 60)
        """,
        (couple_id, user_id),
    )
    conn.commit()
    return get_prefs(conn, couple_id, user_id)


def iter_messages(conn: sqlite3.Connection, couple_id: int) -> Iterable[sqlite3.Row]:
    cur = conn.execute(
        "SELECT id, chat_id, sender_id, text, ts FROM messages WHERE couple_id = ? ORDER BY ts ASC",
        (couple_id,),
    )
    return cur.fetchall()


def log_message(
    conn: sqlite3.Connection,
    couple_id: int,
    chat_id: int,
    sender_id: int,
    text: str,
    ts: str,
) -> None:
    conn.execute(
        """
        INSERT INTO messages (chat_id, sender_id, text, ts, couple_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (chat_id, sender_id, text, ts, couple_id),
    )
    conn.commit()


__all__ = [
    "get_conn",
    "get_cursor",
    "run_migrations",
    "upsert_advice",
    "write_stat",
    "fetch_stats",
    "record_cooldown",
    "get_cooldown",
    "get_prefs",
    "iter_messages",
    "log_message",
]
