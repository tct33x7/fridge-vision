"""Move camera captures into application-owned storage and sessions."""

from __future__ import annotations

import hashlib
import hmac
import threading
from typing import Any

from app.repositories.inventory import InventoryRepository
from app.services.camera_gateway import CameraGateway
from app.services.media_store import MediaStore, MediaStoreError


class CaptureLibrary:
    def __init__(
        self,
        gateway: CameraGateway,
        media_store: MediaStore,
        repository: InventoryRepository,
    ) -> None:
        self.gateway = gateway
        self.media_store = media_store
        self.repository = repository
        self._write_lock = threading.RLock()

    def _ingest(
        self, record: dict[str, Any], *, session_id: str | None = None
    ) -> dict[str, object]:
        capture_id = str(record.get("id") or "")
        with self._write_lock:
            existing = self.repository.get_media(capture_id)
            if existing and self.media_store.exists(str(existing.get("local_relpath") or "")):
                if session_id:
                    self.repository.attach_capture(session_id, capture_id)
                return existing

            body, _content_type = self.gateway.image(capture_id)
            relative_path, digest, created = self.media_store.write_capture(record, body)
            enriched = dict(record)
            enriched["image_sha256"] = digest
            enriched["image_verified"] = True
            try:
                self.repository.upsert_media(
                    enriched,
                    local_relpath=relative_path,
                    session_id=session_id,
                )
            except Exception:
                if created:
                    self.media_store.quarantine(relative_path)
                raise
            item = self.repository.get_media(capture_id)
            assert item is not None
            return item

    def capture(self, session_id: str | None = None) -> dict[str, object]:
        record = self.gateway.capture()
        return self._ingest(record, session_id=session_id)

    def ensure(self, capture_id: str, *, session_id: str | None = None) -> dict[str, object]:
        existing = self.repository.get_media(capture_id)
        if existing and self.media_store.exists(str(existing.get("local_relpath") or "")):
            if session_id:
                self.repository.attach_capture(session_id, capture_id)
            return existing
        return self._ingest(self.gateway.get_capture(capture_id), session_id=session_id)

    def sync_recent(self, *, limit: int = 24) -> dict[str, object]:
        payload = self.gateway.list_captures(limit=limit, offset=0)
        records = payload.get("items")
        imported = 0
        failed = 0
        if not isinstance(records, list):
            records = []
        for record in reversed(records):
            if not isinstance(record, dict):
                continue
            try:
                before = self.repository.get_media(str(record.get("id") or ""))
                self._ingest(record)
                if before is None:
                    imported += 1
            except Exception:
                failed += 1
        return {"seen": len(records), "imported": imported, "failed": failed}

    def image(self, capture_id: str) -> bytes:
        item = self.repository.get_media(capture_id)
        if item is None or not self.media_store.exists(
            str(item.get("local_relpath") or "")
        ):
            item = self.ensure(capture_id)
        relative_path = str(item.get("local_relpath") or "")
        body = self.media_store.read(relative_path)
        expected = str(item.get("sha256") or "").lower()
        if expected and not hmac.compare_digest(hashlib.sha256(body).hexdigest(), expected):
            raise MediaStoreError("stored capture failed its SHA-256 verification")
        return body
