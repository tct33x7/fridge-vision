"""SQLite setup with migrations, short transactions, and safe journaling."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


LOG = logging.getLogger("smart_fridge.database")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sqlite_has_wal_reset_fix(version: tuple[int, int, int] | None = None) -> bool:
    """Return whether this SQLite build contains the 2026 WAL-reset fix."""

    current = version or sqlite3.sqlite_version_info
    if current >= (3, 51, 3):
        return True
    if current[:2] == (3, 50) and current >= (3, 50, 7):
        return True
    if current[:2] == (3, 44) and current >= (3, 44, 6):
        return True
    return False


class Database:
    """Owns schema migrations and serializes all writes in this process."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.journal_mode = "delete"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def initialize(self) -> None:
        with self._write_lock, self.connect() as connection:
            requested_mode = "WAL" if sqlite_has_wal_reset_fix() else "DELETE"
            row = connection.execute(f"PRAGMA journal_mode={requested_mode}").fetchone()
            self.journal_mode = str(row[0]).lower() if row else requested_mode.lower()
            if requested_mode == "DELETE":
                LOG.warning(
                    "SQLite %s lacks the WAL-reset fix; using rollback journaling. "
                    "Upgrade to a fixed SQLite build before enabling WAL.",
                    sqlite3.sqlite_version,
                )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }

        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in applied:
                continue
            script = path.read_text(encoding="utf-8")
            with self._write_lock, self.connect() as connection:
                try:
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + script
                        + "\nINSERT INTO schema_migrations(version, name, applied_at) VALUES ("
                        + str(version)
                        + ", '"
                        + path.name.replace("'", "''")
                        + "', '"
                        + utc_now()
                        + "');\nCOMMIT;"
                    )
                except Exception:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
            LOG.info("Applied database migration %s", path.name)

        self._seed_defaults()

    def _seed_defaults(self) -> None:
        now = utc_now()
        defaults = (
            ("fridge", "冷藏", "fridge", 10),
            ("freezer", "冷冻", "freezer", 20),
            ("pantry", "常温", "pantry", 30),
            ("counter", "台面", "counter", 40),
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_profile(
                    id, created_at, updated_at
                ) VALUES (1, ?, ?)
                """,
                (now, now),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO locations(
                    id, name, kind, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(item_id, name, kind, order, now, now) for item_id, name, kind, order in defaults],
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_metadata(key, value) VALUES('sqlite_version', ?)",
                (sqlite3.sqlite_version,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO app_metadata(key, value) VALUES('journal_mode', ?)",
                (self.journal_mode,),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def health(self) -> dict[str, object]:
        with self.connect() as connection:
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            migration = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        return {
            "ready": integrity == "ok",
            "integrity": integrity,
            "schema_version": int(migration),
            "sqlite_version": sqlite3.sqlite_version,
            "journal_mode": self.journal_mode,
            "wal_reset_fix": sqlite_has_wal_reset_fix(),
        }

    def backup_to(self, destination: Path) -> Path:
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
        with self._write_lock, self.connect() as source:
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                target.commit()
                result = str(target.execute("PRAGMA integrity_check").fetchone()[0])
                if result != "ok":
                    raise RuntimeError(f"backup integrity check failed: {result}")
            finally:
                target.close()
        os.replace(temporary, destination)
        return destination

