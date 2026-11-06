from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name: str) -> str:
    value = re.sub(r"^[A-Za-z]{1,3}", "", name.strip())
    return re.sub(r"[\s·,，。./\\_-]+", "", value).lower()


def find_by_id(connection: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def list_products(connection: sqlite3.Connection, query: str | None = None) -> list[dict[str, Any]]:
    if query:
        needle = f"%{query.strip()}%"
        rows = connection.execute(
            "SELECT * FROM products WHERE name LIKE ? OR barcode LIKE ? ORDER BY updated_at DESC",
            (needle, needle),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM products ORDER BY updated_at DESC").fetchall()
    return [dict(row) for row in rows]


def create_product(connection: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO products (
            name, normalized_name, barcode, category, brand, default_unit,
            estimated_weight_g, calories_kcal, protein_g, carbs_g, fat_g,
            source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"].strip(),
            normalize_name(data["name"]),
            data.get("barcode") or None,
            data.get("category") or "其他",
            data.get("brand") or None,
            data.get("default_unit") or data.get("unit") or "份",
            float(data.get("estimated_weight_g") or 100),
            float(data.get("calories_kcal") or 0),
            float(data.get("protein_g") or 0),
            float(data.get("carbs_g") or 0),
            float(data.get("fat_g") or 0),
            data.get("source") or "manual",
            timestamp,
            timestamp,
        ),
    )
    return find_by_id(connection, int(cursor.lastrowid)) or {}


def get_or_create(connection: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    row = None
    barcode = data.get("barcode")
    if barcode:
        row = connection.execute("SELECT * FROM products WHERE barcode = ?", (barcode,)).fetchone()
    if row is None:
        row = connection.execute(
            "SELECT * FROM products WHERE normalized_name = ? ORDER BY id LIMIT 1",
            (normalize_name(data["name"]),),
        ).fetchone()
    if row:
        connection.execute(
            "UPDATE products SET updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        return dict(row)
    return create_product(connection, data)

