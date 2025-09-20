"""Seed default metric thresholds."""

from __future__ import annotations

from couples_bot import db
from couples_bot.metrics import thresholds


def main() -> None:
    with db.get_conn() as conn:
        couples = conn.execute("SELECT id FROM couples").fetchall()
        defs = thresholds.default_thresholds()
        for couple in couples:
            couple_id = couple["id"]
            for item in defs:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO thresholds(couple_id, key, direction, warn, praise)
                    VALUES(?,?,?,?,?)
                    """,
                    (couple_id, item.key, item.direction, item.warn, item.praise),
                )
    print("Thresholds seeded.")


if __name__ == "__main__":
    main()
