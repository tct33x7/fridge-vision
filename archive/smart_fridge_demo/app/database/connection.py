from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import DB_PATH


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with database() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["name"]
            for row in connection.execute("SELECT name FROM schema_migrations").fetchall()
        }
        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration_path.name in applied:
                continue
            connection.executescript(migration_path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, datetime('now'))",
                (migration_path.name,),
            )

