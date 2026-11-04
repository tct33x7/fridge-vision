"""Create one verified backup bundle for the database and its evidence photos."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from app.config import load_settings
from app.database.connection import Database


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _copy_snapshot_media(
    *, database_path: Path, source_root: Path, destination_root: Path
) -> list[dict[str, object]]:
    """Copy only files referenced by the consistent database snapshot."""

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, local_relpath, sha256, byte_size
            FROM media_assets
            WHERE state='ready' AND local_relpath IS NOT NULL
            ORDER BY local_relpath
            """
        ).fetchall()

    source_root = source_root.resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for capture_id, relative_value, expected_sha, expected_size in rows:
        relative = Path(str(relative_value))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe media path in database: {capture_id}")
        source_candidate = source_root / relative
        source = source_candidate.resolve()
        if not source.is_relative_to(source_root) or source_candidate.is_symlink():
            raise RuntimeError(f"media path escapes the data directory: {capture_id}")
        if not source.is_file():
            raise RuntimeError(f"referenced media file is missing: {capture_id}")
        actual_sha = _digest(source)
        if expected_sha and actual_sha != str(expected_sha).lower():
            raise RuntimeError(f"media checksum mismatch: {capture_id}")
        actual_size = source.stat().st_size
        if expected_size is not None and actual_size != int(expected_size):
            raise RuntimeError(f"media size mismatch: {capture_id}")

        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        if _digest(destination) != actual_sha:
            raise RuntimeError(f"backup verification failed: {capture_id}")
        manifest.append(
            {
                "capture_id": capture_id,
                "path": f"media/{relative.as_posix()}",
                "bytes": actual_size,
                "sha256": actual_sha,
            }
        )
    return manifest


def create_bundle(output_dir: Path) -> Path:
    settings = load_settings()
    if not settings.database_path.is_file():
        raise RuntimeError(
            f"database does not exist; refusing to create an empty backup: {settings.database_path}"
        )
    database = Database(settings.database_path)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    destination = output_dir / f"smart_fridge_{stamp}"
    suffix = 1
    while destination.exists():
        destination = output_dir / f"smart_fridge_{stamp}_{suffix:02d}"
        suffix += 1

    temporary = Path(tempfile.mkdtemp(prefix=".smart_fridge_backup_", dir=output_dir))
    try:
        database_copy = database.backup_to(temporary / "smart_fridge.sqlite3")
        with sqlite3.connect(database_copy) as snapshot:
            schema_version = int(
                snapshot.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
            )
            media_columns = {
                str(row[1])
                for row in snapshot.execute("PRAGMA table_info(media_assets)")
            }
        if "local_relpath" not in media_columns:
            raise RuntimeError(
                "database schema predates application-owned media; create a legacy system snapshot before upgrading"
            )
        media = _copy_snapshot_media(
            database_path=database_copy,
            source_root=settings.media_dir,
            destination_root=temporary / "media",
        )
        manifest = {
            "format_version": 1,
            "app_version": __version__,
            "schema_version": schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": {
                "path": "smart_fridge.sqlite3",
                "bytes": database_copy.stat().st_size,
                "sha256": _digest(database_copy),
            },
            "media": media,
            "media_count": len(media),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a verified Smart Fridge database and media backup bundle"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    args = parser.parse_args()
    print(create_bundle(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
