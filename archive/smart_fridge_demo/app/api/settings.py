from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def settings() -> dict[str, object]:
    return {"servings": 2, "reminder_days": 3, "ocr_mode": "auto", "storage": "local"}

