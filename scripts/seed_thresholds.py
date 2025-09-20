"""Populate default metric thresholds."""
from __future__ import annotations

from couples_bot import db
from couples_bot.config import get_settings
from couples_bot.metrics.thresholds import DEFAULT_THRESHOLDS


def main() -> None:
    settings = get_settings()
    conn = db.get_conn(settings.database_path)
    db.run_migrations(settings.database_path)
    for metric, values in DEFAULT_THRESHOLDS.items():
        conn.execute(
            """
            INSERT INTO thresholds (couple_id, key, direction, warn, praise)
            VALUES (0, ?, 'static', ?, ?)
            ON CONFLICT(couple_id, key) DO UPDATE SET warn=excluded.warn, praise=excluded.praise
            """,
            (metric, values.get("warn"), values.get("praise")),
        )
    conn.commit()
    print("Seeded default thresholds for metric templates.")


if __name__ == "__main__":
    main()
