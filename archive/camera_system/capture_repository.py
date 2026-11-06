"""Versioned persistence for captured images and recognition results."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


LOG = logging.getLogger("camera_capture.repository")
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS system_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
    id                  TEXT PRIMARY KEY,
    schema_version      INTEGER NOT NULL,
    captured_at         TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    image_relpath       TEXT NOT NULL UNIQUE,
    sidecar_relpath     TEXT NOT NULL UNIQUE,
    image_sha256        TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    width               INTEGER NOT NULL,
    height              INTEGER NOT NULL,
    byte_size           INTEGER NOT NULL,
    camera_device       TEXT NOT NULL,
    recognition_status  TEXT NOT NULL,
    recognizer          TEXT,
    document_name       TEXT,
    document_type       TEXT,
    language            TEXT,
    confidence          REAL,
    raw_text            TEXT,
    structured_json     TEXT NOT NULL DEFAULT '{}',
    recognized_at       TEXT,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_captures_captured_at
    ON captures(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_captures_status
    ON captures(recognition_status, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_captures_type
    ON captures(document_type, captured_at DESC);

CREATE TABLE IF NOT EXISTS capture_fields (
    capture_id       TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    field_name       TEXT NOT NULL,
    field_value      TEXT NOT NULL,
    normalized_value TEXT,
    confidence       REAL,
    source           TEXT NOT NULL DEFAULT 'ocr',
    PRIMARY KEY (capture_id, field_name)
);

CREATE INDEX IF NOT EXISTS idx_capture_fields_lookup
    ON capture_fields(field_name, normalized_value);

CREATE TABLE IF NOT EXISTS capture_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id  TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_capture_events_capture
    ON capture_events(capture_id, event_id);
"""


def local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def sqlite_has_wal_reset_fix(version: tuple[int, int, int] | None = None) -> bool:
    """Return whether the runtime includes SQLite's 2026 WAL-reset fix."""
    current = version or sqlite3.sqlite_version_info
    if current >= (3, 51, 3):
        return True
    if current[:2] == (3, 50) and current >= (3, 50, 7):
        return True
    if current[:2] == (3, 44) and current >= (3, 44, 6):
        return True
    return False


class CaptureRepository:
    """SQLite is the index; JSON sidecars make each image independently portable."""

    def __init__(self, database_path: Path, image_root: Path) -> None:
        self.database_path = database_path.resolve()
        self.image_root = image_root.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.image_root.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._initialize()

    @staticmethod
    def new_capture_id() -> str:
        return str(uuid.uuid4())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._schema_lock, self._connect() as connection:
            requested_mode = "WAL" if sqlite_has_wal_reset_fix() else "DELETE"
            row = connection.execute(f"PRAGMA journal_mode={requested_mode}").fetchone()
            journal_mode = str(row[0]).lower() if row else requested_mode.lower()
            if requested_mode == "DELETE":
                LOG.warning(
                    "SQLite %s 尚未包含 WAL-reset 修复；自动使用 rollback journal",
                    sqlite3.sqlite_version,
                )
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO system_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO system_metadata(key, value) VALUES('sqlite_version', ?)",
                (sqlite3.sqlite_version,),
            )
            connection.execute(
                "INSERT OR REPLACE INTO system_metadata(key, value) VALUES('journal_mode', ?)",
                (journal_mode,),
            )
            connection.commit()

    def _event(
        self,
        connection: sqlite3.Connection,
        capture_id: str,
        event_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO capture_events(capture_id, occurred_at, event_type, details_json)
            VALUES (?, ?, ?, ?)
            """,
            (capture_id, local_now(), event_type, json.dumps(details or {}, ensure_ascii=False)),
        )

    def register_capture(
        self,
        *,
        capture_id: str,
        captured_at: str,
        trigger: str,
        image_relpath: str,
        image_sha256: str,
        width: int,
        height: int,
        byte_size: int,
        camera_device: str,
        recognition_enabled: bool,
    ) -> dict[str, object]:
        sidecar_relpath = str(Path(image_relpath).with_suffix(".json"))
        status = "pending" if recognition_enabled else "skipped"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO captures(
                    id, schema_version, captured_at, updated_at, trigger,
                    image_relpath, sidecar_relpath, image_sha256, mime_type,
                    width, height, byte_size, camera_device, recognition_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'image/jpeg', ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    SCHEMA_VERSION,
                    captured_at,
                    captured_at,
                    trigger,
                    image_relpath,
                    sidecar_relpath,
                    image_sha256,
                    width,
                    height,
                    byte_size,
                    camera_device,
                    status,
                ),
            )
            self._event(
                connection,
                capture_id,
                "captured",
                {"trigger": trigger, "recognition_status": status},
            )
            connection.commit()
        try:
            self._write_sidecar(capture_id)
        except OSError:
            # SQLite remains authoritative. A missing sidecar can be regenerated
            # during reconciliation without reporting the already-saved capture
            # as a failed photo.
            LOG.exception("记录已入库，但 JSON sidecar 写入失败：%s", capture_id)
        record = self.get(capture_id)
        assert record is not None
        return record

    def mark_processing(self, capture_id: str, recognizer: str) -> bool:
        now = local_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE captures
                SET recognition_status='processing', recognizer=?, updated_at=?, error=NULL
                WHERE id=? AND recognition_status IN ('pending', 'failed', 'processing')
                """,
                (recognizer, now, capture_id),
            )
            if cursor.rowcount:
                self._event(connection, capture_id, "recognition_started", {"recognizer": recognizer})
            connection.commit()
            return bool(cursor.rowcount)

    def complete_recognition(self, capture_id: str, result: dict[str, object]) -> None:
        now = local_now()
        fields = result.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE captures SET
                    recognition_status='completed', updated_at=?, document_name=?,
                    document_type=?, language=?, confidence=?, raw_text=?,
                    structured_json=?, recognized_at=?, error=NULL
                WHERE id=?
                """,
                (
                    now,
                    result.get("name"),
                    result.get("type"),
                    result.get("language"),
                    result.get("confidence"),
                    result.get("raw_text", ""),
                    json.dumps(result.get("structured", {}), ensure_ascii=False),
                    now,
                    capture_id,
                ),
            )
            connection.execute("DELETE FROM capture_fields WHERE capture_id=?", (capture_id,))
            for field_name, raw_field in fields.items():
                if not isinstance(raw_field, dict) or raw_field.get("value") is None:
                    continue
                connection.execute(
                    """
                    INSERT INTO capture_fields(
                        capture_id, field_name, field_value, normalized_value,
                        confidence, source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        str(field_name),
                        str(raw_field["value"]),
                        str(raw_field.get("normalized_value", raw_field["value"])),
                        raw_field.get("confidence"),
                        str(raw_field.get("source", "ocr")),
                    ),
                )
            self._event(
                connection,
                capture_id,
                "recognition_completed",
                {"document_type": result.get("type"), "confidence": result.get("confidence")},
            )
            connection.commit()
        self._write_sidecar(capture_id)

    def fail_recognition(self, capture_id: str, error: str) -> None:
        now = local_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE captures
                SET recognition_status='failed', updated_at=?, error=?
                WHERE id=?
                """,
                (now, error[:2000], capture_id),
            )
            self._event(connection, capture_id, "recognition_failed", {"error": error[:500]})
            connection.commit()
        self._write_sidecar(capture_id)

    def retry(self, capture_id: str) -> bool:
        now = local_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE captures
                SET recognition_status='pending', updated_at=?, error=NULL
                WHERE id=? AND recognition_status IN ('failed', 'skipped', 'completed')
                """,
                (now, capture_id),
            )
            if cursor.rowcount:
                self._event(connection, capture_id, "recognition_queued")
            connection.commit()
        if cursor.rowcount:
            self._write_sidecar(capture_id)
        return bool(cursor.rowcount)

    def recoverable_capture_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM captures
                WHERE recognition_status IN ('pending', 'processing')
                ORDER BY captured_at
                """
            ).fetchall()
            connection.execute(
                "UPDATE captures SET recognition_status='pending' WHERE recognition_status='processing'"
            )
            connection.commit()
        return [str(row["id"]) for row in rows]

    def _fields(self, connection: sqlite3.Connection, capture_id: str) -> dict[str, object]:
        rows = connection.execute(
            """
            SELECT field_name, field_value, normalized_value, confidence, source
            FROM capture_fields WHERE capture_id=? ORDER BY field_name
            """,
            (capture_id,),
        ).fetchall()
        return {
            str(row["field_name"]): {
                "value": row["field_value"],
                "normalized_value": row["normalized_value"],
                "confidence": row["confidence"],
                "source": row["source"],
            }
            for row in rows
        }

    def _record(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        include_raw_text: bool,
    ) -> dict[str, object]:
        image_path = self.image_root / str(row["image_relpath"])
        sidecar_path = self.image_root / str(row["sidecar_relpath"])
        try:
            structured = json.loads(row["structured_json"] or "{}")
        except json.JSONDecodeError:
            structured = {}
        record: dict[str, object] = {
            "schema_version": row["schema_version"],
            "id": row["id"],
            "captured_at": row["captured_at"],
            "updated_at": row["updated_at"],
            "trigger": row["trigger"],
            "filename": image_path.name,
            "image_path": str(image_path),
            "image_relpath": row["image_relpath"],
            "sidecar_path": str(sidecar_path),
            "image_url": f"/captures/{row['id']}.jpg",
            "record_url": f"/api/v1/captures/{row['id']}",
            "image_sha256": row["image_sha256"],
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
            "bytes": row["byte_size"],
            "camera_device": row["camera_device"],
            "recognition": {
                "status": row["recognition_status"],
                "recognizer": row["recognizer"],
                "name": row["document_name"],
                "type": row["document_type"],
                "language": row["language"],
                "confidence": row["confidence"],
                "recognized_at": row["recognized_at"],
                "error": row["error"],
                "fields": self._fields(connection, str(row["id"])),
                "structured": structured,
            },
        }
        if include_raw_text:
            recognition = record["recognition"]
            assert isinstance(recognition, dict)
            recognition["raw_text"] = row["raw_text"] or ""
        return record

    def get(self, capture_id: str, include_raw_text: bool = True) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
            return self._record(connection, row, include_raw_text) if row else None

    def latest(self, include_raw_text: bool = False) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM captures ORDER BY captured_at DESC LIMIT 1"
            ).fetchone()
            return self._record(connection, row, include_raw_text) if row else None

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[object] = []
        if status:
            clauses.append("recognition_status=?")
            values.append(status)
        if document_type:
            clauses.append("document_type=?")
            values.append(document_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((limit, offset))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM captures{where} ORDER BY captured_at DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
            return [self._record(connection, row, False) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT recognition_status, COUNT(*) AS count FROM captures GROUP BY recognition_status"
            ).fetchall()
        counts = {str(row["recognition_status"]): int(row["count"]) for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    def image_path(self, capture_id: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT image_relpath FROM captures WHERE id=?", (capture_id,)
            ).fetchone()
        return self.image_root / str(row["image_relpath"]) if row else None

    def _write_sidecar(self, capture_id: str) -> None:
        record = self.get(capture_id, include_raw_text=True)
        if record is None:
            return
        sidecar = Path(str(record["sidecar_path"]))
        temporary = sidecar.with_suffix(".json.part")
        try:
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(sidecar)
        except OSError as error:
            LOG.warning("无法写入 JSON 结果 %s：%s", sidecar, error)
