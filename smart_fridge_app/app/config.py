"""Environment-only configuration with safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def _port(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not 1 <= value <= 65535:
        raise RuntimeError(f"{name} must be between 1 and 65535")
    return value


def _camera_url() -> str:
    value = os.getenv("SMART_FRIDGE_CAMERA_URL", "http://127.0.0.1:8001").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("SMART_FRIDGE_CAMERA_URL must be an http(s) base URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeError("SMART_FRIDGE_CAMERA_URL must not contain a path, query, or fragment")
    return value


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    database_path: Path
    media_dir: Path
    camera_url: str
    camera_timeout_seconds: float
    frontend_dir: Path


def load_settings() -> Settings:
    raw_data_dir = Path(os.getenv("SMART_FRIDGE_DATA_DIR", "runtime"))
    data_dir = raw_data_dir if raw_data_dir.is_absolute() else PROJECT_ROOT / raw_data_dir
    data_dir = data_dir.resolve()
    return Settings(
        host=os.getenv("SMART_FRIDGE_HOST", "0.0.0.0"),
        port=_port("SMART_FRIDGE_PORT", 8000),
        data_dir=data_dir,
        database_path=data_dir / "database" / "smart_fridge.sqlite3",
        media_dir=data_dir / "media",
        camera_url=_camera_url(),
        camera_timeout_seconds=_positive_float(
            "SMART_FRIDGE_CAMERA_TIMEOUT_SECONDS", 3.0
        ),
        frontend_dir=PROJECT_ROOT / "frontend",
    )
