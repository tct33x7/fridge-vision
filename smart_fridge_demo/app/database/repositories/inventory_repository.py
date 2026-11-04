from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_status(expiry_date: str | None, quantity: float, status: str) -> tuple[str, int | None]:
    if status != "active" or quantity <= 0:
        return status, None
    if not expiry_date:
        return "unknown", None
    try:
        days = (date.fromisoformat(expiry_date[:10]) - date.today()).days
    except ValueError:
        return "unknown", None
    if days < 0:
        return "expired", days
    if days <= 3:
        return "expiring", days
    return "fresh", days


def _serialize(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    state, days = _expiry_status(item.get("expiry_date"), item["quantity"], item["status"])
    item["expiry_status"] = state
    item["days_until_expiry"] = days
    return item


def create_batch(
    connection: sqlite3.Connection,
    *,
    product_id: int,
    quantity: float,
    unit: str,
    purchase_date: str | None = None,
    production_date: str | None = None,
    expiry_date: str | None = None,
    best_before_date: str | None = None,
    shelf_life_days: int | None = None,
    storage_location: str = "冷藏室",
    unit_price: float | None = None,
    source_scan_id: int | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO inventory_batches (
            product_id, quantity, original_quantity, unit, purchase_date,
            production_date, expiry_date, best_before_date, shelf_life_days,
            storage_location, unit_price, source_scan_id, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            product_id, quantity, quantity, unit, purchase_date, production_date,
            expiry_date, best_before_date, shelf_life_days, storage_location,
            unit_price, source_scan_id, timestamp, timestamp,
        ),
    )
    batch_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO inventory_transactions (
            batch_id, product_id, transaction_type, quantity_delta,
            quantity_after, note, created_at
        ) VALUES (?, ?, 'receive', ?, ?, ?, ?)
        """,
        (batch_id, product_id, quantity, quantity, "确认入库", timestamp),
    )
    return get_batch(connection, batch_id) or {}


def get_batch(connection: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT b.*, p.name, p.barcode, p.category, p.brand,
               p.estimated_weight_g, p.calories_kcal, p.protein_g, p.carbs_g, p.fat_g
        FROM inventory_batches b JOIN products p ON p.id = b.product_id
        WHERE b.id = ?
        """,
        (batch_id,),
    ).fetchone()
    return _serialize(row) if row else None


def list_batches(connection: sqlite3.Connection, include_inactive: bool = False) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE b.status = 'active' AND b.quantity > 0"
    rows = connection.execute(
        f"""
        SELECT b.*, p.name, p.barcode, p.category, p.brand,
               p.estimated_weight_g, p.calories_kcal, p.protein_g, p.carbs_g, p.fat_g
        FROM inventory_batches b JOIN products p ON p.id = b.product_id
        {where}
        ORDER BY CASE WHEN b.expiry_date IS NULL THEN 1 ELSE 0 END,
                 b.expiry_date ASC, b.created_at DESC
        """
    ).fetchall()
    return [_serialize(row) for row in rows]


def consume(
    connection: sqlite3.Connection,
    batch_id: int,
    quantity: float,
    note: str | None = None,
) -> dict[str, Any] | None:
    batch = get_batch(connection, batch_id)
    if not batch:
        return None
    new_quantity = max(0.0, float(batch["quantity"]) - quantity)
    actual_delta = new_quantity - float(batch["quantity"])
    new_status = "used" if new_quantity == 0 else "active"
    timestamp = now_iso()
    connection.execute(
        "UPDATE inventory_batches SET quantity = ?, status = ?, updated_at = ? WHERE id = ?",
        (new_quantity, new_status, timestamp, batch_id),
    )
    connection.execute(
        """
        INSERT INTO inventory_transactions (
            batch_id, product_id, transaction_type, quantity_delta,
            quantity_after, note, created_at
        ) VALUES (?, ?, 'consume', ?, ?, ?, ?)
        """,
        (batch_id, batch["product_id"], actual_delta, new_quantity, note or "使用库存", timestamp),
    )
    return get_batch(connection, batch_id)


def discard(connection: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    batch = get_batch(connection, batch_id)
    if not batch:
        return None
    timestamp = now_iso()
    remaining = float(batch["quantity"])
    connection.execute(
        "UPDATE inventory_batches SET quantity = 0, status = 'discarded', updated_at = ? WHERE id = ?",
        (timestamp, batch_id),
    )
    connection.execute(
        """
        INSERT INTO inventory_transactions (
            batch_id, product_id, transaction_type, quantity_delta,
            quantity_after, note, created_at
        ) VALUES (?, ?, 'discard', ?, 0, '删除/丢弃库存', ?)
        """,
        (batch_id, batch["product_id"], -remaining, timestamp),
    )
    return get_batch(connection, batch_id)


def update_expiry(
    connection: sqlite3.Connection,
    batch_id: int,
    *,
    production_date: str | None,
    expiry_date: str | None,
    best_before_date: str | None,
    shelf_life_days: int | None,
) -> dict[str, Any] | None:
    if not get_batch(connection, batch_id):
        return None
    connection.execute(
        """
        UPDATE inventory_batches
        SET production_date = COALESCE(?, production_date),
            expiry_date = COALESCE(?, expiry_date),
            best_before_date = COALESCE(?, best_before_date),
            shelf_life_days = COALESCE(?, shelf_life_days),
            updated_at = ?
        WHERE id = ?
        """,
        (production_date, expiry_date, best_before_date, shelf_life_days, now_iso(), batch_id),
    )
    return get_batch(connection, batch_id)


def list_transactions(connection: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT t.*, p.name, b.unit
        FROM inventory_transactions t
        JOIN products p ON p.id = t.product_id
        JOIN inventory_batches b ON b.id = t.batch_id
        ORDER BY t.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]

