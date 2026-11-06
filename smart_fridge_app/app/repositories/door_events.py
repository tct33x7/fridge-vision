"""Door-camera events: automatic receive / consume with evidence and undo.

一条 door_event = 门口摄像头看到的一次过线。放入自动建批次并写 receive 流水；拿出自动扣该商品最早到期的
活动批次并写 consume 流水；两者都可撤销，撤销写反向流水而不删除任何记录。关键帧作为 media_assets 存进
应用自有图库，文件先落盘再写库，写库失败则文件进隔离区。
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import date, timedelta
from typing import Any

from app.database.connection import Database, utc_now
from app.repositories.inventory import (
    InventoryRepository,
    NotFoundError,
    RepositoryError,
    _expiry,
    normalize_product_name,
)
from app.services.media_store import MediaStore
from app.services.shelf_life import category_for, label_override_days


class DoorEventRepository:
    def __init__(self, inventory: InventoryRepository, media_store: MediaStore) -> None:
        self.inventory = inventory
        self.media_store = media_store

    @property
    def database(self) -> Database:
        return self.inventory.database

    # ------------------------------------------------------------ shelf life
    def shelf_life(self) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT category, label_zh, default_days, location_id, updated_at
                FROM category_shelf_life ORDER BY category
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def set_shelf_life(self, category: str, *, default_days: int, location_id: str | None = None) -> dict[str, object]:
        if default_days <= 0:
            raise RepositoryError("default_days must be positive")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT location_id FROM category_shelf_life WHERE category=?", (category,)
            ).fetchone()
            if row is None:
                raise NotFoundError("shelf-life category does not exist")
            location = location_id or str(row["location_id"])
            if connection.execute("SELECT 1 FROM locations WHERE id=? AND active=1", (location,)).fetchone() is None:
                raise NotFoundError("storage location does not exist")
            connection.execute(
                "UPDATE category_shelf_life SET default_days=?, location_id=?, updated_at=? WHERE category=?",
                (default_days, location, utc_now(), category),
            )
        return next(item for item in self.shelf_life() if item["category"] == category)

    @staticmethod
    def _shelf_life_for(connection: sqlite3.Connection, label: str, category: str) -> tuple[int, str]:
        row = connection.execute(
            "SELECT default_days, location_id FROM category_shelf_life WHERE category=?", (category,)
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT default_days, location_id FROM category_shelf_life WHERE category='other'"
            ).fetchone()
        days = label_override_days(label)
        if days is None:
            days = int(row["default_days"]) if row is not None else 7
        location = str(row["location_id"]) if row is not None else "fridge"
        return days, location

    # ------------------------------------------------------------ media
    def _store_keyframe(self, keyframe: bytes, occurred_at: str) -> tuple[str, str, str, bool]:
        media_id = str(uuid.uuid4())
        record = {"id": media_id, "captured_at": occurred_at, "trigger": "door"}
        relative_path, digest, created = self.media_store.write_capture(record, keyframe)
        return media_id, relative_path, digest, created

    @staticmethod
    def _insert_media(
        connection: sqlite3.Connection,
        *,
        media_id: str,
        occurred_at: str,
        digest: str,
        byte_size: int,
        relative_path: str,
        record_json: str,
    ) -> None:
        now = utc_now()
        connection.execute(
            """
            INSERT INTO media_assets(
                id, source, captured_at, trigger, sha256, mime_type, byte_size,
                recognition_status, record_json, state, created_at, updated_at,
                local_relpath, imported_at, verified_at
            ) VALUES (?, 'camera', ?, 'door', ?, 'image/jpeg', ?, 'door_event', ?, 'ready', ?, ?, ?, ?, ?)
            """,
            (media_id, occurred_at, digest, byte_size, record_json, now, now, relative_path, now, now),
        )

    # ------------------------------------------------------------ record
    def record(
        self,
        *,
        session_id: str,
        occurred_at: str,
        action: str,
        label: str,
        label_zh: str | None,
        confidence: float | None,
        count: float,
        vlm: dict[str, Any] | None,
        keyframe: bytes | None,
        existing_media_id: str | None = None,
    ) -> dict[str, object]:
        if action not in {"in", "out"}:
            raise RepositoryError("action must be 'in' or 'out'")
        if count <= 0:
            raise RepositoryError("count must be positive")
        name = (label_zh or label).strip()
        if not normalize_product_name(name):
            raise RepositoryError("label is empty after normalization")
        category = category_for(label)
        event_id = str(uuid.uuid4())
        now = utc_now()

        media_id = existing_media_id
        relative_path: str | None = None
        created = False
        digest = ""
        if keyframe:
            media_id, relative_path, digest, created = self._store_keyframe(keyframe, occurred_at)

        try:
            with self.database.transaction() as connection:
                if keyframe and media_id and relative_path:
                    self._insert_media(
                        connection,
                        media_id=media_id,
                        occurred_at=occurred_at,
                        digest=digest,
                        byte_size=len(keyframe),
                        relative_path=relative_path,
                        record_json=self.inventory._json(
                            {"id": media_id, "trigger": "door", "label": label, "session_id": session_id}
                        ),
                    )
                elif media_id:
                    exists = connection.execute(
                        "SELECT 1 FROM media_assets WHERE id=? AND state='ready'", (media_id,)
                    ).fetchone()
                    if exists is None:
                        raise NotFoundError("evidence image does not exist")

                lot_id: str | None = None
                inventory_event_id: int | None = None
                applied = 0.0
                status = "applied"

                if action == "in":
                    product_id = self.inventory._get_or_create_product(
                        connection,
                        name=name,
                        category=category,
                        default_unit="piece",
                        barcode=None,
                        primary_flavor=None,
                        nutrition=None,
                    )
                    days, location_id = self._shelf_life_for(connection, label, category)
                    expires_on = (date.today() + timedelta(days=days)).isoformat()
                    lot_id = str(uuid.uuid4())
                    connection.execute(
                        """
                        INSERT INTO inventory_lots(
                            id, product_id, location_id, quantity, unit,
                            purchased_on, expires_on, status, source,
                            source_capture_id, note, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'piece', ?, ?, 'active', 'camera', ?, ?, ?, ?)
                        """,
                        (
                            lot_id, product_id, location_id, count,
                            date.today().isoformat(), expires_on, media_id,
                            "门口摄像头自动入库", now, now,
                        ),
                    )
                    cursor = connection.execute(
                        """
                        INSERT INTO inventory_events(
                            lot_id, event_type, delta_quantity, quantity_after,
                            reason, source_capture_id, details_json, occurred_at
                        ) VALUES (?, 'receive', ?, ?, 'door camera: in', ?, ?, ?)
                        """,
                        (lot_id, count, count, media_id, self.inventory._json({"door_event_id": event_id}), occurred_at),
                    )
                    inventory_event_id = int(cursor.lastrowid)
                    applied = float(count)
                else:
                    row = connection.execute(
                        """
                        SELECT l.id, l.quantity FROM inventory_lots l
                        JOIN products p ON p.id=l.product_id
                        WHERE p.normalized_name=? AND l.status='active' AND l.quantity > 0
                        ORDER BY CASE WHEN l.expires_on IS NULL THEN 1 ELSE 0 END,
                                 l.expires_on, l.created_at
                        LIMIT 1
                        """,
                        (normalize_product_name(name),),
                    ).fetchone()
                    if row is None:
                        status = "unmatched"
                    else:
                        lot_id = str(row["id"])
                        quantity = float(row["quantity"])
                        applied = min(float(count), quantity)
                        after = max(0.0, quantity - applied)
                        lot_status = "used" if after <= 1e-9 else "active"
                        connection.execute(
                            """
                            UPDATE inventory_lots
                            SET quantity=?, status=?, version=version+1, updated_at=?
                            WHERE id=?
                            """,
                            (after, lot_status, now, lot_id),
                        )
                        cursor = connection.execute(
                            """
                            INSERT INTO inventory_events(
                                lot_id, event_type, delta_quantity, quantity_after,
                                reason, source_capture_id, details_json, occurred_at
                            ) VALUES (?, 'consume', ?, ?, 'door camera: out', ?, ?, ?)
                            """,
                            (
                                lot_id, -applied, after, media_id,
                                self.inventory._json({"recorded_as_meal": False, "door_event_id": event_id}),
                                occurred_at,
                            ),
                        )
                        inventory_event_id = int(cursor.lastrowid)

                connection.execute(
                    """
                    INSERT INTO door_events(
                        id, session_id, occurred_at, action, label, label_zh, category,
                        confidence, count, vlm_json, media_id, lot_id, inventory_event_id,
                        applied_quantity, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, session_id, occurred_at, action, label, name, category,
                        confidence, count, self.inventory._json(vlm or {}), media_id, lot_id,
                        inventory_event_id, applied, status, now,
                    ),
                )
        except Exception:
            if created and relative_path:
                self.media_store.quarantine(relative_path)
            raise

        item = self.get(event_id)
        assert item is not None
        return item

    # ------------------------------------------------------------ undo / correct
    def undo(self, event_id: str) -> dict[str, object]:
        now = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM door_events WHERE id=?", (event_id,)).fetchone()
            if row is None:
                raise NotFoundError("door event does not exist")
            if row["status"] == "undone":
                return self._get(connection, event_id)
            lot_id = row["lot_id"]
            applied = float(row["applied_quantity"] or 0)
            if row["status"] == "applied" and lot_id:
                lot = connection.execute(
                    "SELECT quantity, status FROM inventory_lots WHERE id=?", (lot_id,)
                ).fetchone()
                if lot is None:
                    raise NotFoundError("inventory lot for this event is missing")
                quantity = float(lot["quantity"])
                details = self.inventory._json({"door_event_id": event_id, "undo": True})
                if row["action"] == "in":
                    if lot["status"] == "active" and quantity > 0:
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
                                reason, details_json, occurred_at
                            ) VALUES (?, 'discard', ?, 0, 'door event undone', ?, ?)
                            """,
                            (lot_id, -quantity, details, now),
                        )
                else:
                    restored = quantity + applied
                    connection.execute(
                        """
                        UPDATE inventory_lots
                        SET quantity=?, status='active', version=version+1, updated_at=?
                        WHERE id=?
                        """,
                        (restored, now, lot_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO inventory_events(
                            lot_id, event_type, delta_quantity, quantity_after,
                            reason, details_json, occurred_at
                        ) VALUES (?, 'adjust', ?, ?, 'door event undone', ?, ?)
                        """,
                        (lot_id, applied, restored, details, now),
                    )
            connection.execute(
                "UPDATE door_events SET status='undone', undone_at=? WHERE id=?", (now, event_id)
            )
            return self._get(connection, event_id)

    def correct(self, event_id: str, *, label_zh: str | None, count: float | None) -> dict[str, object]:
        """改名字或数量：撤销原事件，再按新值重记一条，复用同一张证据图。"""
        original = self.get(event_id)
        if original is None:
            raise NotFoundError("door event does not exist")
        self.undo(event_id)
        return self.record(
            session_id=str(original["session_id"]),
            occurred_at=str(original["occurred_at"]),
            action=str(original["action"]),
            label=str(original["label"]),
            label_zh=label_zh or str(original["label_zh"]),
            confidence=original["confidence"],
            count=float(count if count is not None else original["count"]),
            vlm=original["vlm"] if isinstance(original["vlm"], dict) else None,
            keyframe=None,
            existing_media_id=str(original["media_id"]) if original.get("media_id") else None,
        )

    # ------------------------------------------------------------ read
    _SELECT = """
        SELECT d.*, m.local_relpath AS media_relpath, m.state AS media_state,
               l.quantity AS lot_quantity, l.status AS lot_status, l.expires_on AS lot_expires_on,
               l.unit AS lot_unit, l.version AS lot_version
        FROM door_events d
        LEFT JOIN media_assets m ON m.id=d.media_id
        LEFT JOIN inventory_lots l ON l.id=d.lot_id
    """

    def _row_dict(self, row: sqlite3.Row) -> dict[str, object]:
        item = dict(row)
        item["vlm"] = self.inventory._load_json(str(item.pop("vlm_json")), {})
        relpath = item.pop("media_relpath", None)
        media_state = item.pop("media_state", None)
        media_id = item.get("media_id")
        item["image_url"] = (
            f"/api/v1/media/{media_id}/image" if media_id and relpath and media_state == "ready" else None
        )
        expiry_status, days_remaining = _expiry(item.get("lot_expires_on"))
        item["lot"] = (
            {
                "id": item["lot_id"],
                "quantity": item.pop("lot_quantity"),
                "status": item.pop("lot_status"),
                "expires_on": item.pop("lot_expires_on"),
                "unit": item.pop("lot_unit"),
                "version": item.pop("lot_version"),
                "expiry_status": expiry_status,
                "days_remaining": days_remaining,
            }
            if item.get("lot_id")
            else None
        )
        for key in ("lot_quantity", "lot_status", "lot_expires_on", "lot_unit", "lot_version"):
            item.pop(key, None)
        item["can_undo"] = item["status"] in {"applied", "unmatched"}
        return item

    def _get(self, connection: sqlite3.Connection, event_id: str) -> dict[str, object]:
        row = connection.execute(self._SELECT + " WHERE d.id=?", (event_id,)).fetchone()
        if row is None:
            raise NotFoundError("door event does not exist")
        return self._row_dict(row)

    def get(self, event_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(self._SELECT + " WHERE d.id=?", (event_id,)).fetchone()
        return self._row_dict(row) if row else None

    def list(self, *, limit: int = 20) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                self._SELECT + " ORDER BY d.occurred_at DESC, d.created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_dict(row) for row in rows]

    @staticmethod
    def sha256(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()
