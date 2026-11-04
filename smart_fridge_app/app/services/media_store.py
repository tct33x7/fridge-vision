"""Application-owned immutable JPEG storage."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path


class MediaStoreError(RuntimeError):
    pass


class MediaStore:
    """Keep the main application's evidence copy outside SQLite."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.capture_root = self.root / "captures"
        self.quarantine_root = self.root / "quarantine"
        self.capture_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _capture_date(value: object) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return datetime.now().astimezone()
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed.astimezone()

    @staticmethod
    def _validate_jpeg(body: bytes) -> str:
        if len(body) < 4 or not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
            raise MediaStoreError("camera returned an invalid JPEG")
        return hashlib.sha256(body).hexdigest()

    def _relative_path(self, record: dict[str, object]) -> Path:
        capture_id = str(record.get("id") or "")
        if not capture_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for character in capture_id):
            raise MediaStoreError("capture id is unsafe for local storage")
        captured = self._capture_date(record.get("captured_at"))
        return Path("captures") / captured.strftime("%Y/%m/%d") / f"{capture_id}.jpg"

    def write_capture(
        self, record: dict[str, object], body: bytes
    ) -> tuple[str, str, bool]:
        digest = self._validate_jpeg(body)
        expected_value = record.get("image_sha256")
        if expected_value and str(expected_value).lower() != digest:
            raise MediaStoreError("capture JPEG does not match its SHA-256 record")

        relative = self._relative_path(record)
        destination = (self.root / relative).resolve()
        if not destination.is_relative_to(self.root):
            raise MediaStoreError("capture path escaped the media directory")
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            existing = destination.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise MediaStoreError("stored capture conflicts with the same capture id")
            return relative.as_posix(), digest, False

        temporary = destination.with_suffix(".jpg.part")
        try:
            with temporary.open("wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return relative.as_posix(), digest, True

    def read(self, relative_path: str) -> bytes:
        if not relative_path:
            raise MediaStoreError("stored capture has no application-owned path")
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise MediaStoreError("stored media path is invalid")
        if not path.is_file():
            raise MediaStoreError("stored capture is missing")
        try:
            body = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, OSError) as error:
            raise MediaStoreError("stored capture is missing") from error
        self._validate_jpeg(body)
        return body

    def exists(self, relative_path: str | None) -> bool:
        if not relative_path:
            return False
        path = (self.root / relative_path).resolve()
        return path.is_relative_to(self.root) and path.is_file()

    def quarantine(self, relative_path: str) -> Path | None:
        source = (self.root / relative_path).resolve()
        if not source.is_relative_to(self.root) or not source.exists():
            return None
        destination = self.quarantine_root / source.name
        os.replace(source, destination)
        return destination
