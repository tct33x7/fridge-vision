from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["result"] = json.loads(item.pop("result_json"))
    item["image_url"] = f"/uploads/{item['saved_name']}"
    return item


def create_scan(connection: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO scans (
            file_id, scan_type, original_name, saved_name, processed_name,
            content_type, size_bytes, status, engine, batch_id,
            result_json, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["file_id"], data["scan_type"], data["original_name"],
            data["saved_name"], data.get("processed_name"), data["content_type"],
            data["size_bytes"], data.get("status", "pending_confirmation"),
            data.get("engine", "manual"), data.get("batch_id"),
            json.dumps(data["result"], ensure_ascii=False), data.get("uploaded_at") or now_iso(),
        ),
    )
    return get_scan(connection, int(cursor.lastrowid)) or {}


def get_scan(connection: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return _serialize(row) if row else None


def list_scans(connection: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
    ).fetchall()
    return [_serialize(row) for row in rows]


def confirm_scan(connection: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    connection.execute(
        "UPDATE scans SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
        (now_iso(), scan_id),
    )
    return get_scan(connection, scan_id)


def delete_scan(connection: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    scan = get_scan(connection, scan_id)
    if not scan:
        return None
    connection.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    return scan

