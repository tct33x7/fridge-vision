from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
FRONTEND_DIR = BASE_DIR / "frontend"
STORAGE_DIR = Path(os.getenv("SMART_FRIDGE_STORAGE_DIR", BASE_DIR / "storage"))
UPLOAD_DIR = STORAGE_DIR / "uploads"
PROCESSED_DIR = STORAGE_DIR / "processed"
DATABASE_DIR = STORAGE_DIR / "database"
BACKUP_DIR = STORAGE_DIR / "backups"
LOG_DIR = STORAGE_DIR / "logs"
DB_PATH = Path(os.getenv("SMART_FRIDGE_DB_PATH", DATABASE_DIR / "smart_fridge.db"))

MAX_FILE_SIZE = int(os.getenv("SMART_FRIDGE_MAX_UPLOAD_MB", "15")) * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

CAMERA_DEVICE = os.getenv("SMART_FRIDGE_CAMERA_DEVICE", "/dev/video0")
CAMERA_WIDTH = int(os.getenv("SMART_FRIDGE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("SMART_FRIDGE_CAMERA_HEIGHT", "720"))
CAMERA_FPS = int(os.getenv("SMART_FRIDGE_CAMERA_FPS", "15"))
CAMERA_JPEG_QUALITY = int(os.getenv("SMART_FRIDGE_CAMERA_JPEG_QUALITY", "82"))

GPIO_BUTTON_ENABLED = os.getenv("SMART_FRIDGE_GPIO_BUTTON_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
GPIO_BUTTON_WPI_PIN = int(os.getenv("SMART_FRIDGE_GPIO_BUTTON_WPI_PIN", "2"))
GPIO_BUTTON_ACTIVE_LOW = os.getenv("SMART_FRIDGE_GPIO_BUTTON_ACTIVE_LOW", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
GPIO_BUTTON_DEBOUNCE_MS = int(os.getenv("SMART_FRIDGE_GPIO_BUTTON_DEBOUNCE_MS", "500"))

API_SETTINGS_PATH = Path(
    os.getenv("SMART_FRIDGE_API_SETTINGS_FILE", BASE_DIR / "config" / "api_settings.json")
)


def _load_api_settings() -> dict[str, Any]:
    if not API_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(API_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"API 配置文件无法读取：{API_SETTINGS_PATH}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"API 配置文件根节点必须是 JSON 对象：{API_SETTINGS_PATH}")
    return data


API_SETTINGS = _load_api_settings()


def get_api_settings(service: str) -> dict[str, Any]:
    settings = API_SETTINGS.get(service, {})
    return dict(settings) if isinstance(settings, dict) else {}

for directory in (UPLOAD_DIR, PROCESSED_DIR, DATABASE_DIR, BACKUP_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
