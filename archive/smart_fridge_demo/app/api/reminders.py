from __future__ import annotations

from fastapi import APIRouter

from app.database.connection import database
from app.database.repositories import inventory_repository
from app.services.notification_service import build_expiry_message


router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("")
def reminders() -> dict[str, object]:
    with database() as connection:
        batches = inventory_repository.list_batches(connection)
    items = [
        {"batch_id": item["id"], "message": build_expiry_message(item["name"], item["days_until_expiry"])}
        for item in batches
        if item.get("days_until_expiry") is not None and item["days_until_expiry"] <= 3
    ]
    return {"items": items}

