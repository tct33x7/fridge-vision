"""Inventory lot and stock-ledger endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import capture_library, repository
from app.repositories.inventory import InventoryRepository
from app.schemas import DiscardRequest, InventoryCreate, QuantityChange
from app.services.capture_library import CaptureLibrary


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("")
def list_inventory(
    state: Literal["active", "used", "discarded"] = "active",
    location_id: str | None = None,
    search: str | None = Query(default=None, max_length=100),
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    items = repo.list_lots(status=state, location_id=location_id, search=search)
    return {"items": items, "count": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_inventory(
    payload: InventoryCreate,
    repo: InventoryRepository = Depends(repository),
    library: CaptureLibrary = Depends(capture_library),
) -> dict[str, object]:
    if payload.source_capture_id:
        library.ensure(
            payload.source_capture_id,
            session_id=payload.intake_session_id,
        )
    item = repo.create_lot(
        name=payload.name,
        category=payload.category,
        barcode=payload.barcode,
        quantity=payload.quantity,
        unit=payload.unit,
        location_id=payload.location_id,
        purchased_on=payload.purchased_on.isoformat() if payload.purchased_on else None,
        expires_on=payload.expires_on.isoformat() if payload.expires_on else None,
        note=payload.note,
        source_capture_id=payload.source_capture_id,
        intake_session_id=payload.intake_session_id,
        primary_flavor=payload.primary_flavor,
        nutrition=payload.nutrition.model_dump() if payload.nutrition else None,
    )
    return item


@router.get("/{lot_id}")
def get_inventory(
    lot_id: str, repo: InventoryRepository = Depends(repository)
) -> dict[str, object]:
    item = repo.get_lot(lot_id)
    if item is None:
        from app.repositories.inventory import NotFoundError

        raise NotFoundError("inventory lot does not exist")
    return item


@router.get("/{lot_id}/events")
def inventory_events(
    lot_id: str, repo: InventoryRepository = Depends(repository)
) -> dict[str, object]:
    events = repo.events(lot_id)
    return {"items": events, "count": len(events)}


@router.post("/{lot_id}/consume")
def consume_inventory(
    lot_id: str,
    payload: QuantityChange,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return repo.consume(
        lot_id,
        amount=payload.amount,
        expected_version=payload.expected_version,
        reason=payload.reason,
        record_meal=payload.record_meal,
        meal_type=payload.meal_type,
        eaten_at=payload.eaten_at.isoformat() if payload.eaten_at else None,
    )


@router.post("/{lot_id}/discard")
def discard_inventory(
    lot_id: str,
    payload: DiscardRequest,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return repo.discard(
        lot_id,
        expected_version=payload.expected_version,
        reason=payload.reason,
    )


@router.get("/meta/locations")
def list_locations(repo: InventoryRepository = Depends(repository)) -> dict[str, object]:
    items = repo.locations()
    return {"items": items, "count": len(items)}
