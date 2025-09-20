"""Initialize the SQLite database."""

from __future__ import annotations

from couples_bot.db import run_migrations


def main() -> None:
    run_migrations()
    print("Database ready.")


if __name__ == "__main__":
    main()
