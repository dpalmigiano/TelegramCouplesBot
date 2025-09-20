from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from .config import get_settings

_CONN: Optional[sqlite3.Connection] = None


def _ensure_connection() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        settings = get_settings()
        path: Path = settings.database_path
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(path)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA foreign_keys = ON")
    return _CONN


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with automatic commit/rollback."""

    conn = _ensure_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _ensure_job_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    alters = {
        "chat_id": "INTEGER",
        "job_kind": "TEXT NOT NULL DEFAULT 'analysis'",
        "priority": "TEXT NOT NULL DEFAULT 'normal'",
        "window_start_ts": "INT",
        "window_end_ts": "INT",
        "retry_after_ts": "INT",
    }
    for name, ddl in alters.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")


def run_migrations() -> None:
    """Apply schema migrations from the packaged SQL file."""

    schema_path = Path(__file__).with_name("schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(sql)
        _ensure_job_columns(conn)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS graph_node_fts USING fts5(node_id, content, tokenize='unicode61')"
            )
        except sqlite3.OperationalError:
            pass


def list_couples() -> List[sqlite3.Row]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM couples").fetchall()
    return list(rows)


def link_couple(
    user_a_id: int,
    user_b_id: int,
    group_chat_id: int,
    tz: str,
) -> int:
    """Create or update the couple row for the given group."""

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO couples(user_a_id, user_b_id, group_chat_id, tz, created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(group_chat_id) DO UPDATE SET
                user_a_id=excluded.user_a_id,
                user_b_id=excluded.user_b_id,
                tz=excluded.tz
            """,
            (user_a_id, user_b_id, group_chat_id, tz, now),
        )
        couple_id = conn.execute(
            "SELECT id FROM couples WHERE group_chat_id = ?",
            (group_chat_id,),
        ).fetchone()[0]
    return int(couple_id)


def update_couple_tz(couple_id: int, tz: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE couples SET tz = ? WHERE id = ?",
            (tz, couple_id),
        )


def fetch_couple_by_group(group_chat_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM couples WHERE group_chat_id = ?",
            (group_chat_id,),
        ).fetchone()
    return row


def fetch_couple_by_user(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM couples WHERE user_a_id = ? OR user_b_id = ?",
            (user_id, user_id),
        ).fetchone()
    return row


def fetch_couple(couple_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM couples WHERE id = ?", (couple_id,)).fetchone()


def fetch_last_message_ts(couple_id: int) -> Optional[datetime]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ts FROM messages WHERE couple_id = ? ORDER BY ts DESC LIMIT 1",
            (couple_id,),
        ).fetchone()
    if not row:
        return None
    return datetime.fromisoformat(row["ts"])


def fetch_messages_since(
    couple_id: int,
    since: Optional[datetime],
    *,
    limit: Optional[int] = None,
) -> List[sqlite3.Row]:
    query = ["SELECT * FROM messages WHERE couple_id = ?"]
    params: List[object] = [couple_id]
    if since is not None:
        query.append("AND ts > ?")
        params.append(since.isoformat())
    query.append("ORDER BY ts ASC")
    if limit is not None:
        query.append("LIMIT ?")
        params.append(limit)
    sql = " ".join(query)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return list(rows)


def upsert_advice(couple_id: int, for_user_id: int, advice_text: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO advice(couple_id, for_user_id, advice_text, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(couple_id, for_user_id) DO UPDATE SET
                advice_text=excluded.advice_text,
                updated_at=excluded.updated_at
            """,
            (couple_id, for_user_id, advice_text, now),
        )


def fetch_advice(couple_id: int, for_user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT advice_text FROM advice WHERE couple_id = ? AND for_user_id = ?",
            (couple_id, for_user_id),
        ).fetchone()
    return row[0] if row else None


def log_message(
    couple_id: int,
    chat_id: int,
    sender_id: int,
    text: str,
    ts: datetime,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages(couple_id, chat_id, sender_id, text, ts)
            VALUES(?,?,?,?,?)
            """,
            (couple_id, chat_id, sender_id, text, ts.isoformat()),
        )


def fetch_recent_messages(couple_id: int, limit: int = 200) -> Iterable[sqlite3.Row]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE couple_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (couple_id, limit),
        ).fetchall()
    return list(reversed(rows))


def upsert_stat(couple_id: int, key: str, value: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO stats(couple_id, key, value, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(couple_id, key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (couple_id, key, value, now),
        )


def get_stats(couple_id: int) -> Dict[str, float]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM stats WHERE couple_id = ?",
            (couple_id,),
        ).fetchall()
    return {row["key"]: float(row["value"]) for row in rows}


def get_stat(couple_id: int, key: str, default: float = 0.0) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM stats WHERE couple_id = ? AND key = ?",
            (couple_id, key),
        ).fetchone()
    return float(row["value"]) if row else default


def record_cooldown(couple_id: int, user_id: int, metric_key: str, ts: datetime) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO cooldowns(couple_id, user_id, metric_key, last_fired)
            VALUES(?,?,?,?)
            ON CONFLICT(couple_id, user_id, metric_key) DO UPDATE SET
                last_fired=excluded.last_fired
            """,
            (couple_id, user_id, metric_key, ts.isoformat()),
        )


def fetch_cooldown(
    couple_id: int,
    user_id: int,
    metric_key: str,
) -> Optional[datetime]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_fired FROM cooldowns WHERE couple_id=? AND user_id=? AND metric_key=?",
            (couple_id, user_id, metric_key),
        ).fetchone()
    return datetime.fromisoformat(row["last_fired"]) if row else None


def set_pref(
    couple_id: int,
    user_id: int,
    *,
    dnd_start: Optional[str] = None,
    dnd_end: Optional[str] = None,
    enable_alerts: Optional[bool] = None,
    max_neg_per_day: Optional[int] = None,
    max_pos_per_day: Optional[int] = None,
    sla_minutes: Optional[int] = None,
) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM prefs WHERE couple_id = ? AND user_id = ?",
            (couple_id, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE prefs
                SET dnd_start=COALESCE(?, dnd_start),
                    dnd_end=COALESCE(?, dnd_end),
                    enable_alerts=COALESCE(?, enable_alerts),
                    max_neg_per_day=COALESCE(?, max_neg_per_day),
                    max_pos_per_day=COALESCE(?, max_pos_per_day),
                    sla_minutes=COALESCE(?, sla_minutes)
                WHERE couple_id = ? AND user_id = ?
                """,
                (
                    dnd_start,
                    dnd_end,
                    int(enable_alerts) if enable_alerts is not None else None,
                    max_neg_per_day,
                    max_pos_per_day,
                    sla_minutes,
                    couple_id,
                    user_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO prefs(
                    couple_id, user_id, dnd_start, dnd_end,
                    enable_alerts, max_neg_per_day, max_pos_per_day, sla_minutes
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    couple_id,
                    user_id,
                    dnd_start,
                    dnd_end,
                    int(enable_alerts) if enable_alerts is not None else 1,
                    max_neg_per_day or 5,
                    max_pos_per_day or 5,
                    sla_minutes or 120,
                ),
            )


def fetch_pref(couple_id: int, user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM prefs WHERE couple_id = ? AND user_id = ?",
            (couple_id, user_id),
        ).fetchone()


def purge_user_data(couple_id: int, user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM messages WHERE couple_id = ? AND sender_id = ?",
            (couple_id, user_id),
        )
        conn.execute(
            "DELETE FROM advice WHERE couple_id = ? AND for_user_id = ?",
            (couple_id, user_id),
        )
        conn.execute(
            "DELETE FROM cooldowns WHERE couple_id = ? AND user_id = ?",
            (couple_id, user_id),
        )
        conn.execute(
            "DELETE FROM prefs WHERE couple_id = ? AND user_id = ?",
            (couple_id, user_id),
        )
        conn.execute(
            "DELETE FROM stats WHERE couple_id = ?",
            (couple_id,),
        )


def wipe_couple(couple_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM advice WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM stats WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM thresholds WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM cooldowns WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM prefs WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM jobs WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM reag_runs WHERE couple_id = ?", (couple_id,))
        conn.execute("DELETE FROM couples WHERE id = ?", (couple_id,))


__all__ = [
    "get_conn",
    "run_migrations",
    "list_couples",
    "link_couple",
    "fetch_couple_by_group",
    "fetch_couple_by_user",
    "fetch_couple",
    "update_couple_tz",
    "fetch_last_message_ts",
    "fetch_messages_since",
    "upsert_advice",
    "fetch_advice",
    "log_message",
    "fetch_recent_messages",
    "upsert_stat",
    "get_stats",
    "get_stat",
    "record_cooldown",
    "fetch_cooldown",
    "set_pref",
    "purge_user_data",
    "fetch_pref",
    "wipe_couple",
]
