from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

RESET_MARKER = "__reset__"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_reset_id(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(id), 0) FROM counter_events WHERE cls = ?",
        (RESET_MARKER,),
    ).fetchone()
    return int(row[0]) if row else 0


def record_event(connection: sqlite3.Connection, cls: str, delta: int) -> None:
    connection.execute(
        "INSERT INTO counter_events (cls, delta, created_at) VALUES (?, ?, ?)",
        (cls, delta, now_iso()),
    )


def record_reset(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO counter_events (cls, delta, created_at) VALUES (?, 0, ?)",
        (RESET_MARKER, now_iso()),
    )


def load_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """汇总最后一个清零标记之后的净计数。"""
    rows = connection.execute(
        """
        SELECT cls, SUM(delta) AS total
        FROM counter_events
        WHERE id > ? AND cls <> ?
        GROUP BY cls
        """,
        (_last_reset_id(connection), RESET_MARKER),
    ).fetchall()
    return {row["cls"]: int(row["total"] or 0) for row in rows}


def list_events(connection: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT cls, delta, created_at
        FROM counter_events
        WHERE id > ? AND cls <> ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (_last_reset_id(connection), RESET_MARKER, max(1, min(limit, 200))),
    ).fetchall()
    return [
        {"cls": row["cls"], "delta": int(row["delta"]), "created_at": row["created_at"]}
        for row in rows
    ]
