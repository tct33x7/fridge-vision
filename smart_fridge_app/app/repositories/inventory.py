"""Transactional product, lot, stock-event, profile, and media persistence."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.database.connection import Database, utc_now


FLAVOR_LABELS = {
    "light": "清淡",
    "savory": "咸鲜",
    "sour": "酸爽",
    "sweet": "甜味",
    "spicy": "香辣",
    "bitter": "苦味",
    "rich": "浓郁",
}

RECIPE_RULES = (
    {
        "title": "番茄炒蛋",
        "aliases": (("番茄", "西红柿"), ("鸡蛋", "蛋")),
        "minutes": 15,
        "reason": "现有食材可以直接组合",
    },
    {
        "title": "香蕉牛奶",
        "aliases": (("香蕉",), ("牛奶", "鲜奶")),
        "minutes": 5,
        "reason": "适合作为快速加餐",
    },
    {
        "title": "蘑菇鸡肉快炒",
        "aliases": (("蘑菇", "香菇", "口蘑"), ("鸡肉", "鸡胸")),
        "minutes": 20,
        "reason": "两种现有食材可以优先使用",
    },
    {
        "title": "蔬菜豆腐汤",
        "aliases": (("豆腐",), ("青菜", "白菜", "菠菜")),
        "minutes": 20,
        "reason": "现有食材满足基础组合",
    },
)


class RepositoryError(RuntimeError):
    pass


class NotFoundError(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


def normalize_product_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _expiry(expires_on: str | None) -> tuple[str, int | None]:
    if not expires_on:
        return "unknown", None
    try:
        remaining = (date.fromisoformat(expires_on) - date.today()).days
    except ValueError:
        return "unknown", None
    if remaining < 0:
        return "expired", remaining
    if remaining <= 3:
        return "expiring", remaining
    return "fresh", remaining


def _nutrition_scale(
    amount: float,
    unit: str,
    basis_amount: float | None,
    basis_unit: str | None,
) -> float | None:
    if basis_amount is None or basis_amount <= 0 or not basis_unit:
        return None
    if unit == basis_unit:
        return amount / basis_amount
    conversions = {
        "g": ("mass", 1.0),
        "kg": ("mass", 1000.0),
        "ml": ("volume", 1.0),
        "l": ("volume", 1000.0),
    }
    source = conversions.get(unit)
    basis = conversions.get(basis_unit)
    if source is None or basis is None or source[0] != basis[0]:
        return None
    return (amount * source[1]) / (basis_amount * basis[1])


class InventoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load_json(value: str, default: object) -> object:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def locations(self) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, kind, sort_order
                FROM locations WHERE active=1 ORDER BY sort_order, name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _upsert_media(
        self,
        connection: sqlite3.Connection,
        record: dict[str, Any],
        *,
        local_relpath: str | None,
    ) -> str:
        capture_id = str(record.get("id") or "").strip()
        if not capture_id:
            raise RepositoryError("camera record does not contain an id")
        recognition = record.get("recognition")
        if not isinstance(recognition, dict):
            recognition = {}
        now = utc_now()
        connection.execute(
            """
            INSERT INTO media_assets(
                id, source, captured_at, trigger, sha256, mime_type,
                width, height, byte_size, camera_device,
                recognition_status, record_json, state, created_at, updated_at,
                local_relpath, imported_at, verified_at
            ) VALUES (?, 'camera', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                captured_at=excluded.captured_at,
                trigger=excluded.trigger,
                sha256=excluded.sha256,
                mime_type=excluded.mime_type,
                width=excluded.width,
                height=excluded.height,
                byte_size=excluded.byte_size,
                camera_device=excluded.camera_device,
                recognition_status=excluded.recognition_status,
                record_json=excluded.record_json,
                local_relpath=COALESCE(excluded.local_relpath, media_assets.local_relpath),
                imported_at=COALESCE(media_assets.imported_at, excluded.imported_at),
                verified_at=excluded.verified_at,
                state='ready',
                updated_at=excluded.updated_at
            """,
            (
                capture_id,
                record.get("captured_at"),
                record.get("trigger"),
                record.get("image_sha256"),
                record.get("mime_type", "image/jpeg"),
                record.get("width"),
                record.get("height"),
                record.get("bytes"),
                record.get("camera_device"),
                recognition.get("status"),
                self._json(record),
                now,
                now,
                local_relpath,
                now,
                now,
            ),
        )
        return capture_id

    @staticmethod
    def _media_dict(row: sqlite3.Row) -> dict[str, object]:
        item = dict(row)
        capture_id = str(item["id"])
        item["image_url"] = f"/api/v1/media/{capture_id}/image"
        item["record"] = InventoryRepository._load_json(
            str(item.pop("record_json")), {}
        )
        return item

    def upsert_media(
        self,
        record: dict[str, Any],
        *,
        local_relpath: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        with self.database.transaction() as connection:
            capture_id = self._upsert_media(
                connection, record, local_relpath=local_relpath
            )
            if session_id:
                self._attach_capture(connection, session_id, capture_id)
        item = self.get_media(capture_id)
        assert item is not None
        return item

    def get_media(self, capture_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT m.*, p.name AS linked_name, l.id AS linked_lot_id
                FROM media_assets m
                LEFT JOIN inventory_lots l ON l.source_capture_id=m.id
                LEFT JOIN products p ON p.id=l.product_id
                WHERE m.id=?
                ORDER BY l.created_at DESC
                LIMIT 1
                """,
                (capture_id,),
            ).fetchone()
        return self._media_dict(row) if row else None

    def list_media(self, *, limit: int = 40) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.*, p.name AS linked_name, l.id AS linked_lot_id
                FROM media_assets m
                LEFT JOIN inventory_lots l ON l.source_capture_id=m.id
                LEFT JOIN products p ON p.id=l.product_id
                WHERE m.state='ready' AND m.local_relpath IS NOT NULL
                GROUP BY m.id
                ORDER BY COALESCE(m.captured_at, m.created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._media_dict(row) for row in rows]

    def create_session(self) -> dict[str, object]:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO intake_sessions(id, status, created_at, updated_at)
                VALUES (?, 'open', ?, ?)
                """,
                (session_id, now, now),
            )
        item = self.get_session(session_id)
        assert item is not None
        return item

    @staticmethod
    def _session_row(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM intake_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("intake session does not exist")
        return row

    def _attach_capture(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        capture_id: str,
    ) -> None:
        session = self._session_row(connection, session_id)
        if session["status"] not in {"open", "review"}:
            raise ConflictError("intake session can no longer accept captures")
        media = connection.execute(
            "SELECT id FROM media_assets WHERE id=? AND state='ready'", (capture_id,)
        ).fetchone()
        if media is None:
            raise NotFoundError("capture is not stored in the main application")
        next_position = int(
            connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM intake_session_captures WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
        )
        now = utc_now()
        connection.execute(
            """
            INSERT OR IGNORE INTO intake_session_captures(
                session_id, media_id, position, added_at
            ) VALUES (?, ?, ?, ?)
            """,
            (session_id, capture_id, next_position, now),
        )
        connection.execute(
            """
            UPDATE intake_sessions
            SET status='review', selected_media_id=?, updated_at=?, version=version+1
            WHERE id=?
            """,
            (capture_id, now, session_id),
        )

    def attach_capture(self, session_id: str, capture_id: str) -> dict[str, object]:
        with self.database.transaction() as connection:
            self._attach_capture(connection, session_id, capture_id)
        item = self.get_session(session_id)
        assert item is not None
        return item

    def select_capture(self, session_id: str, capture_id: str) -> dict[str, object]:
        with self.database.transaction() as connection:
            session = self._session_row(connection, session_id)
            if session["status"] not in {"open", "review"}:
                raise ConflictError("intake session can no longer be edited")
            linked = connection.execute(
                """
                SELECT 1 FROM intake_session_captures
                WHERE session_id=? AND media_id=?
                """,
                (session_id, capture_id),
            ).fetchone()
            if linked is None:
                raise ConflictError("capture does not belong to this intake session")
            connection.execute(
                """
                UPDATE intake_sessions
                SET selected_media_id=?, status='review', updated_at=?, version=version+1
                WHERE id=?
                """,
                (capture_id, utc_now(), session_id),
            )
        item = self.get_session(session_id)
        assert item is not None
        return item

    def get_session(self, session_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM intake_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            captures = connection.execute(
                """
                SELECT m.*, isc.position, p.name AS linked_name,
                       l.id AS linked_lot_id
                FROM intake_session_captures isc
                JOIN media_assets m ON m.id=isc.media_id
                LEFT JOIN inventory_lots l ON l.source_capture_id=m.id
                LEFT JOIN products p ON p.id=l.product_id
                WHERE isc.session_id=?
                ORDER BY isc.position
                """,
                (session_id,),
            ).fetchall()
            lots = connection.execute(
                """
                SELECT l.id, p.name, l.quantity, l.unit
                FROM intake_session_lots isl
                JOIN inventory_lots l ON l.id=isl.lot_id
                JOIN products p ON p.id=l.product_id
                WHERE isl.session_id=? ORDER BY isl.line_index
                """,
                (session_id,),
            ).fetchall()
        item = dict(row)
        item["draft"] = self._load_json(str(item.pop("draft_json")), {})
        item["result"] = self._load_json(str(item.pop("result_json")), {})
        item["captures"] = [self._media_dict(capture) for capture in captures]
        item["lots"] = [dict(lot) for lot in lots]
        return item

    def list_sessions(
        self, *, limit: int = 20, status: str | None = None
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if status:
            clauses.append("status=?")
            values.append(status)
        values.append(limit)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM intake_sessions {where} ORDER BY updated_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [item for row in rows if (item := self.get_session(str(row["id"]))) is not None]

    def cancel_session(self, session_id: str) -> dict[str, object]:
        with self.database.transaction() as connection:
            session = self._session_row(connection, session_id)
            if session["status"] == "confirmed":
                raise ConflictError("confirmed intake session cannot be cancelled")
            if session["status"] != "cancelled":
                connection.execute(
                    """
                    UPDATE intake_sessions
                    SET status='cancelled', updated_at=?, version=version+1
                    WHERE id=?
                    """,
                    (utc_now(), session_id),
                )
        item = self.get_session(session_id)
        assert item is not None
        return item

    def _get_or_create_product(
        self,
        connection: sqlite3.Connection,
        *,
        name: str,
        category: str,
        default_unit: str,
        barcode: str | None,
        primary_flavor: str | None,
        nutrition: dict[str, object] | None,
    ) -> str:
        normalized_name = normalize_product_name(name)
        if not normalized_name:
            raise RepositoryError("product name is empty after normalization")

        row = None
        if barcode:
            row = connection.execute(
                """
                SELECT p.id FROM products p
                JOIN product_barcodes b ON b.product_id=p.id
                WHERE b.barcode=?
                """,
                (barcode,),
            ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT id FROM products
                WHERE normalized_name=? ORDER BY created_at LIMIT 1
                """,
                (normalized_name,),
            ).fetchone()

        now = utc_now()
        if row is None:
            product_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO products(
                    id, name, normalized_name, category, default_unit,
                    primary_flavor, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    name,
                    normalized_name,
                    category,
                    default_unit,
                    primary_flavor,
                    now,
                    now,
                ),
            )
        else:
            product_id = str(row["id"])
            connection.execute(
                """
                UPDATE products SET
                    category=CASE WHEN category='other' THEN ? ELSE category END,
                    default_unit=CASE WHEN default_unit='piece' THEN ? ELSE default_unit END,
                    primary_flavor=COALESCE(?, primary_flavor),
                    updated_at=?
                WHERE id=?
                """,
                (category, default_unit, primary_flavor, now, product_id),
            )

        if barcode:
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO product_barcodes(barcode, product_id, created_at) VALUES (?, ?, ?)",
                    (barcode, product_id, now),
                )
            except sqlite3.IntegrityError as error:
                raise ConflictError("barcode already belongs to another product") from error

        if nutrition:
            connection.execute(
                """
                INSERT INTO product_nutrition(
                    product_id, basis_amount, basis_unit, calories_kcal,
                    protein_g, carbs_g, fat_g, fiber_g, sodium_mg,
                    source, verified_by_user, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    basis_amount=excluded.basis_amount,
                    basis_unit=excluded.basis_unit,
                    calories_kcal=excluded.calories_kcal,
                    protein_g=excluded.protein_g,
                    carbs_g=excluded.carbs_g,
                    fat_g=excluded.fat_g,
                    fiber_g=excluded.fiber_g,
                    sodium_mg=excluded.sodium_mg,
                    source='manual',
                    verified_by_user=1,
                    updated_at=excluded.updated_at
                """,
                (
                    product_id,
                    nutrition["basis_amount"],
                    nutrition["basis_unit"],
                    nutrition.get("calories_kcal"),
                    nutrition.get("protein_g"),
                    nutrition.get("carbs_g"),
                    nutrition.get("fat_g"),
                    nutrition.get("fiber_g"),
                    nutrition.get("sodium_mg"),
                    now,
                ),
            )
        return product_id

    def create_lot(
        self,
        *,
        name: str,
        category: str,
        barcode: str | None,
        quantity: float,
        unit: str,
        location_id: str,
        purchased_on: str | None,
        expires_on: str | None,
        note: str,
        source_capture_id: str | None = None,
        intake_session_id: str | None = None,
        primary_flavor: str | None = None,
        nutrition: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        lot_id = str(uuid.uuid4())
        existing_lot_id: str | None = None
        with self.database.transaction() as connection:
            session = None
            if intake_session_id:
                session = self._session_row(connection, intake_session_id)
                if session["status"] == "confirmed":
                    linked = connection.execute(
                        """
                        SELECT lot_id FROM intake_session_lots
                        WHERE session_id=? ORDER BY line_index LIMIT 1
                        """,
                        (intake_session_id,),
                    ).fetchone()
                    if linked is None:
                        raise ConflictError("confirmed session has no linked inventory")
                    existing_lot_id = str(linked["lot_id"])
                elif session["status"] not in {"open", "review"}:
                    raise ConflictError("intake session can no longer be confirmed")

            if existing_lot_id is None:
                location = connection.execute(
                    "SELECT id FROM locations WHERE id=? AND active=1", (location_id,)
                ).fetchone()
                if location is None:
                    raise NotFoundError("storage location does not exist")

                capture_id = source_capture_id
                if session is not None:
                    selected = str(session["selected_media_id"] or "")
                    if not selected:
                        raise ConflictError("select a photo before confirming the session")
                    if capture_id and capture_id != selected:
                        raise ConflictError("selected photo does not match the intake session")
                    capture_id = selected
                if capture_id:
                    media = connection.execute(
                        """
                        SELECT id FROM media_assets
                        WHERE id=? AND state='ready' AND local_relpath IS NOT NULL
                        """,
                        (capture_id,),
                    ).fetchone()
                    if media is None:
                        raise NotFoundError("capture is not stored in the main application")

                product_id = self._get_or_create_product(
                    connection,
                    name=name,
                    category=category,
                    default_unit=unit,
                    barcode=barcode,
                    primary_flavor=primary_flavor,
                    nutrition=nutrition,
                )
                source = "camera" if capture_id else "manual"
                connection.execute(
                    """
                    INSERT INTO inventory_lots(
                        id, product_id, location_id, quantity, unit,
                        purchased_on, expires_on, status, source,
                        source_capture_id, note, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                    """,
                    (
                        lot_id,
                        product_id,
                        location_id,
                        quantity,
                        unit,
                        purchased_on,
                        expires_on,
                        source,
                        capture_id,
                        note,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO inventory_events(
                        lot_id, event_type, delta_quantity, quantity_after,
                        reason, source_capture_id, occurred_at
                    ) VALUES (?, 'receive', ?, ?, 'initial receipt', ?, ?)
                    """,
                    (lot_id, quantity, quantity, capture_id, now),
                )
                connection.execute(
                    """
                    INSERT INTO inventory_lot_nutrition(
                        lot_id, basis_amount, basis_unit, calories_kcal,
                        protein_g, carbs_g, fat_g, fiber_g, sodium_mg,
                        source, verified_by_user, captured_at
                    )
                    SELECT ?, basis_amount, basis_unit, calories_kcal,
                           protein_g, carbs_g, fat_g, fiber_g, sodium_mg,
                           source, verified_by_user, ?
                    FROM product_nutrition WHERE product_id=?
                    """,
                    (lot_id, now, product_id),
                )
                if intake_session_id:
                    connection.execute(
                        """
                        INSERT INTO intake_session_lots(session_id, lot_id, line_index)
                        VALUES (?, ?, 0)
                        """,
                        (intake_session_id, lot_id),
                    )
                    result = {
                        "schema_version": 1,
                        "confirmed_name": name,
                        "lot_id": lot_id,
                    }
                    connection.execute(
                        """
                        UPDATE intake_sessions
                        SET status='confirmed', result_json=?, confirmed_at=?,
                            updated_at=?, version=version+1
                        WHERE id=?
                        """,
                        (self._json(result), now, now, intake_session_id),
                    )
        item = self.get_lot(existing_lot_id or lot_id)
        assert item is not None
        return item

    @staticmethod
    def _lot_dict(row: sqlite3.Row) -> dict[str, object]:
        expiry_status, days_remaining = _expiry(row["expires_on"])
        result = dict(row)
        result["expiry_status"] = expiry_status
        result["days_remaining"] = days_remaining
        capture_id = result.get("source_capture_id")
        capture_local_path = result.pop("capture_local_relpath", None)
        capture_state = result.pop("capture_state", None)
        result["image_url"] = (
            f"/api/v1/media/{capture_id}/image"
            if capture_id and capture_local_path and capture_state == "ready"
            else None
        )
        if result.get("nutrition_basis_amount") is not None:
            result["nutrition"] = {
                "basis_amount": result.pop("nutrition_basis_amount"),
                "basis_unit": result.pop("nutrition_basis_unit"),
                "calories_kcal": result.pop("calories_kcal"),
                "protein_g": result.pop("protein_g"),
                "carbs_g": result.pop("carbs_g"),
                "fat_g": result.pop("fat_g"),
                "fiber_g": result.pop("fiber_g"),
                "sodium_mg": result.pop("sodium_mg"),
            }
        else:
            for key in (
                "nutrition_basis_amount",
                "nutrition_basis_unit",
                "calories_kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
                "fiber_g",
                "sodium_mg",
            ):
                result.pop(key, None)
            result["nutrition"] = None
        return result

    def get_lot(self, lot_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT l.*, p.name, p.category, p.primary_flavor,
                       loc.name AS location_name, loc.kind AS location_kind,
                       m.local_relpath AS capture_local_relpath,
                       m.state AS capture_state,
                       n.basis_amount AS nutrition_basis_amount,
                       n.basis_unit AS nutrition_basis_unit,
                       n.calories_kcal, n.protein_g, n.carbs_g, n.fat_g,
                       n.fiber_g, n.sodium_mg
                FROM inventory_lots l
                JOIN products p ON p.id=l.product_id
                JOIN locations loc ON loc.id=l.location_id
                LEFT JOIN media_assets m ON m.id=l.source_capture_id
                LEFT JOIN inventory_lot_nutrition n ON n.lot_id=l.id
                WHERE l.id=?
                """,
                (lot_id,),
            ).fetchone()
        return self._lot_dict(row) if row else None

    def list_lots(
        self,
        *,
        status: str = "active",
        location_id: str | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        clauses = ["l.status=?"]
        values: list[object] = [status]
        if location_id:
            clauses.append("l.location_id=?")
            values.append(location_id)
        if search:
            clauses.append("(p.name LIKE ? OR p.category LIKE ?)")
            pattern = f"%{search}%"
            values.extend((pattern, pattern))
        values.append(limit)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT l.*, p.name, p.category, p.primary_flavor,
                       loc.name AS location_name, loc.kind AS location_kind,
                       m.local_relpath AS capture_local_relpath,
                       m.state AS capture_state,
                       n.basis_amount AS nutrition_basis_amount,
                       n.basis_unit AS nutrition_basis_unit,
                       n.calories_kcal, n.protein_g, n.carbs_g, n.fat_g,
                       n.fiber_g, n.sodium_mg
                FROM inventory_lots l
                JOIN products p ON p.id=l.product_id
                JOIN locations loc ON loc.id=l.location_id
                LEFT JOIN media_assets m ON m.id=l.source_capture_id
                LEFT JOIN inventory_lot_nutrition n ON n.lot_id=l.id
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    CASE WHEN l.expires_on IS NULL THEN 1 ELSE 0 END,
                    l.expires_on,
                    l.created_at DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [self._lot_dict(row) for row in rows]

    def consume(
        self,
        lot_id: str,
        *,
        amount: float,
        expected_version: int | None,
        reason: str,
        record_meal: bool = False,
        meal_type: str | None = None,
        eaten_at: str | None = None,
    ) -> dict[str, object]:
        meal_id: str | None = None
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT l.quantity, l.status, l.version, l.unit, l.product_id,
                       p.name, p.category, p.primary_flavor,
                       n.basis_amount, n.basis_unit, n.calories_kcal,
                       n.protein_g, n.carbs_g, n.fat_g, n.fiber_g,
                       n.sodium_mg, n.source AS nutrition_source
                FROM inventory_lots l
                JOIN products p ON p.id=l.product_id
                LEFT JOIN inventory_lot_nutrition n ON n.lot_id=l.id
                WHERE l.id=?
                """,
                (lot_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("inventory lot does not exist")
            if row["status"] != "active":
                raise ConflictError("inventory lot is no longer active")
            if expected_version is not None and int(row["version"]) != expected_version:
                raise ConflictError("inventory lot changed; refresh before trying again")
            quantity = float(row["quantity"])
            if amount > quantity + 1e-9:
                raise ConflictError("consume amount exceeds current quantity")
            after = max(0.0, quantity - amount)
            status = "used" if after <= 1e-9 else "active"
            now = utc_now()
            connection.execute(
                """
                UPDATE inventory_lots
                SET quantity=?, status=?, version=version+1, updated_at=?
                WHERE id=?
                """,
                (after, status, now, lot_id),
            )
            connection.execute(
                """
                INSERT INTO inventory_events(
                    lot_id, event_type, delta_quantity, quantity_after,
                    reason, details_json, occurred_at
                ) VALUES (?, 'consume', ?, ?, ?, ?, ?)
                """,
                (
                    lot_id,
                    -amount,
                    after,
                    reason,
                    self._json({"recorded_as_meal": record_meal}),
                    now,
                ),
            )
            if record_meal:
                meal_id = str(uuid.uuid4())
                meal_time = eaten_at or now
                connection.execute(
                    """
                    INSERT INTO meal_logs(id, eaten_at, meal_type, source, note, created_at)
                    VALUES (?, ?, ?, 'inventory', ?, ?)
                    """,
                    (meal_id, meal_time, meal_type, reason, now),
                )
                scale = _nutrition_scale(
                    amount,
                    str(row["unit"]),
                    float(row["basis_amount"]) if row["basis_amount"] is not None else None,
                    str(row["basis_unit"]) if row["basis_unit"] is not None else None,
                )

                def nutrient(name: str) -> float | None:
                    value = row[name]
                    return round(float(value) * scale, 4) if value is not None and scale is not None else None

                flavors = [str(row["primary_flavor"])] if row["primary_flavor"] else []
                connection.execute(
                    """
                    INSERT INTO meal_items(
                        meal_id, lot_id, product_id, name_snapshot,
                        category_snapshot, amount, unit, taste_tags_json,
                        calories_kcal, protein_g, carbs_g, fat_g, fiber_g,
                        sodium_mg, nutrition_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        meal_id,
                        lot_id,
                        row["product_id"],
                        row["name"],
                        row["category"],
                        amount,
                        row["unit"],
                        self._json(flavors),
                        nutrient("calories_kcal"),
                        nutrient("protein_g"),
                        nutrient("carbs_g"),
                        nutrient("fat_g"),
                        nutrient("fiber_g"),
                        nutrient("sodium_mg"),
                        row["nutrition_source"] if scale is not None else None,
                        now,
                    ),
                )
        item = self.get_lot(lot_id)
        assert item is not None
        item["recorded_meal_id"] = meal_id
        return item

    def discard(
        self,
        lot_id: str,
        *,
        expected_version: int | None,
        reason: str,
    ) -> dict[str, object]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT quantity, status, version FROM inventory_lots WHERE id=?", (lot_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("inventory lot does not exist")
            if row["status"] != "active":
                raise ConflictError("inventory lot is no longer active")
            if expected_version is not None and int(row["version"]) != expected_version:
                raise ConflictError("inventory lot changed; refresh before trying again")
            quantity = float(row["quantity"])
            now = utc_now()
            connection.execute(
                """
                UPDATE inventory_lots
                SET quantity=0, status='discarded', version=version+1, updated_at=?
                WHERE id=?
                """,
                (now, lot_id),
            )
            connection.execute(
                """
                INSERT INTO inventory_events(
                    lot_id, event_type, delta_quantity, quantity_after,
                    reason, occurred_at
                ) VALUES (?, 'discard', ?, 0, ?, ?)
                """,
                (lot_id, -quantity, reason, now),
            )
        item = self.get_lot(lot_id)
        assert item is not None
        return item

    def events(self, lot_id: str) -> list[dict[str, object]]:
        if self.get_lot(lot_id) is None:
            raise NotFoundError("inventory lot does not exist")
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, lot_id, event_type, delta_quantity, quantity_after,
                       reason, source_capture_id, details_json, occurred_at
                FROM inventory_events WHERE lot_id=? ORDER BY id
                """,
                (lot_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = self._load_json(str(item.pop("details_json")), {})
            result.append(item)
        return result

    @staticmethod
    def _recipe_suggestions(active: list[dict[str, object]]) -> list[dict[str, object]]:
        usable = [item for item in active if item["expiry_status"] != "expired"]
        named = [(normalize_product_name(str(item["name"])), item) for item in usable]
        suggestions: list[dict[str, object]] = []
        for rule in RECIPE_RULES:
            matched: list[dict[str, object]] = []
            for alias_group in rule["aliases"]:
                found = next(
                    (
                        item
                        for normalized, item in named
                        if any(alias in normalized for alias in alias_group)
                    ),
                    None,
                )
                if found is None:
                    matched = []
                    break
                matched.append(found)
            if matched:
                suggestions.append(
                    {
                        "title": rule["title"],
                        "minutes": rule["minutes"],
                        "reason": rule["reason"],
                        "ingredients": [str(item["name"]) for item in matched],
                    }
                )
        return suggestions[:3]

    def dashboard(self) -> dict[str, object]:
        active = self.list_lots(status="active", limit=500)
        expired = [item for item in active if item["expiry_status"] == "expired"]
        expiring = [item for item in active if item["expiry_status"] == "expiring"]
        unknown = [item for item in active if item["expiry_status"] == "unknown"]
        priority = sorted(
            expired + expiring,
            key=lambda item: int(item["days_remaining"] or 0),
        )[:6]
        recent_media = self.list_media(limit=6)
        sessions = self.list_sessions(limit=5)
        open_session = next(
            (item for item in sessions if item["status"] in {"open", "review"}),
            None,
        )
        recipes = self._recipe_suggestions(active)
        actions: list[dict[str, object]] = []
        if expired:
            actions.append(
                {
                    "kind": "expired",
                    "title": f"检查 {len(expired)} 批已过期食材",
                    "target": "inventory",
                }
            )
        if expiring:
            actions.append(
                {
                    "kind": "expiring",
                    "title": f"优先使用 {len(expiring)} 批临期食材",
                    "target": "inventory",
                }
            )
        if unknown:
            actions.append(
                {
                    "kind": "missing_date",
                    "title": f"为 {len(unknown)} 批食材补充日期",
                    "target": "inventory",
                }
            )
        if open_session:
            actions.insert(
                0,
                {
                    "kind": "open_session",
                    "title": "继续刚才的拍照录入",
                    "target": "capture",
                    "session_id": open_session["id"],
                },
            )
        return {
            "availability": {
                "inventory": bool(active),
                "expiry": bool(priority),
                "missing_expiry": bool(unknown),
                "recent_captures": bool(recent_media),
                "recipes": bool(recipes),
                "open_session": open_session is not None,
            },
            "counts": {
                "active_lots": len(active),
                "distinct_products": len({item["product_id"] for item in active}),
                "expired": len(expired),
                "expiring": len(expiring),
                "unknown_expiry": len(unknown),
            },
            "priority_items": priority,
            "recent_captures": recent_media,
            "actions": actions,
            "recipe_suggestions": recipes,
            "safety_notice": "营养与口味仅统计明确记录为已食用的内容。",
        }

    def insights(self, *, days: int) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT ml.eaten_at, mi.category_snapshot, mi.taste_tags_json,
                       mi.calories_kcal, mi.protein_g, mi.carbs_g, mi.fat_g,
                       mi.fiber_g, mi.sodium_mg
                FROM meal_logs ml
                JOIN meal_items mi ON mi.meal_id=ml.id
                WHERE julianday(ml.eaten_at) >= julianday(?)
                  AND julianday(ml.eaten_at) <= julianday(?)
                ORDER BY ml.eaten_at
                """,
                (
                    cutoff.isoformat(),
                    now.isoformat(),
                ),
            ).fetchall()

        nutrients = (
            "calories_kcal",
            "protein_g",
            "carbs_g",
            "fat_g",
            "fiber_g",
            "sodium_mg",
        )
        daily: dict[str, dict[str, float | int | str]] = defaultdict(
            lambda: {"records": 0, **{name: 0.0 for name in nutrients}}
        )
        flavor_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        nutrition_samples = 0
        meal_days: set[str] = set()

        for row in rows:
            try:
                recorded = datetime.fromisoformat(str(row["eaten_at"]).replace("Z", "+00:00"))
                day = recorded.astimezone().date().isoformat()
            except ValueError:
                continue
            meal_days.add(day)
            has_nutrition = False
            values: dict[str, float] = {}
            for name in nutrients:
                value = row[name]
                if value is not None:
                    values[name] = float(value)
                    has_nutrition = True
            if has_nutrition:
                nutrition_samples += 1
                daily[day]["date"] = day
                daily[day]["records"] = int(daily[day]["records"]) + 1
                for name, value in values.items():
                    daily[day][name] = float(daily[day][name]) + value
            category_counts[str(row["category_snapshot"])] += 1
            tags = self._load_json(str(row["taste_tags_json"]), [])
            if isinstance(tags, list):
                flavor_counts.update(str(tag) for tag in tags if str(tag) in FLAVOR_LABELS)

        daily_items = []
        for day in sorted(daily):
            item = daily[day]
            for name in nutrients:
                item[name] = round(float(item[name]), 2)
            daily_items.append(item)
        totals = {
            name: round(sum(float(item[name]) for item in daily_items), 2)
            for name in nutrients
        }
        total_samples = len(rows)
        return {
            "days": days,
            "sample_size": total_samples,
            "recorded_days": len(meal_days),
            "availability": {
                "nutrition": nutrition_samples > 0,
                "nutrition_trend": nutrition_samples > 0 and len(daily_items) >= 2,
                "flavors": bool(flavor_counts),
                "flavor_trend": sum(flavor_counts.values()) >= 3,
                "categories": bool(category_counts),
            },
            "nutrition": {
                "sample_size": nutrition_samples,
                "coverage_percent": round(
                    nutrition_samples / total_samples * 100, 1
                )
                if total_samples
                else 0,
                "totals": totals,
                "daily": daily_items,
            },
            "flavors": [
                {"key": key, "label": FLAVOR_LABELS[key], "count": count}
                for key, count in flavor_counts.most_common()
            ],
            "categories": [
                {"key": key, "count": count}
                for key, count in category_counts.most_common()
            ],
        }

    def profile(self) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        assert row is not None
        return {
            "display_name": row["display_name"],
            "diet_goal": row["diet_goal"],
            "preferences": self._load_json(row["preferences_json"], []),
            "allergies": self._load_json(row["allergies_json"], []),
            "medications": self._load_json(row["medications_json"], []),
            "onboarding_completed": bool(row["onboarding_completed"]),
            "updated_at": row["updated_at"],
        }

    def update_profile(
        self,
        *,
        display_name: str,
        diet_goal: str,
        preferences: list[str],
        allergies: list[str],
        medications: list[str],
        onboarding_completed: bool,
    ) -> dict[str, object]:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE user_profile SET
                    display_name=?, diet_goal=?, preferences_json=?,
                    allergies_json=?, medications_json=?,
                    onboarding_completed=?, updated_at=?
                WHERE id=1
                """,
                (
                    display_name,
                    diet_goal,
                    self._json(preferences),
                    self._json(allergies),
                    self._json(medications),
                    int(onboarding_completed),
                    utc_now(),
                ),
            )
        return self.profile()
