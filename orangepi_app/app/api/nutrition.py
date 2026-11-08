from __future__ import annotations

from fastapi import APIRouter

from app.database.connection import database
from app.database.repositories import inventory_repository
from app.services.nutrition_service import summarize_inventory


router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


@router.get("/summary")
def nutrition_summary() -> dict[str, object]:
    with database() as connection:
        batches = inventory_repository.list_batches(connection)
    return summarize_inventory(batches)

