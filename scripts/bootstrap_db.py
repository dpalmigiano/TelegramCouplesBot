"""Create the SQLite database and run migrations."""
from __future__ import annotations

from couples_bot import db
from couples_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    db.run_migrations(settings.database_path)
    conn = db.get_conn(settings.database_path)
    conn.commit()
    print(f"Database initialised at {settings.database_path}")


if __name__ == "__main__":
    main()
