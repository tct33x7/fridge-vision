from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.database.connection import database
from app.database.repositories import inventory_repository, product_repository
from app.schemas.inventory import ConsumeRequest, ManualInventoryCreate
from app.services.expiry_service import summarize_expiry


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("")
def list_inventory(include_inactive: bool = False) -> dict[str, object]:
    with database() as connection:
        items = inventory_repository.list_batches(connection, include_inactive)
    return {"items": items, "count": len(items), "expiry": summarize_expiry(items)}


@router.get("/transactions")
def list_transactions(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    with database() as connection:
        return {"items": inventory_repository.list_transactions(connection, limit)}


@router.post("")
def create_manual_inventory(payload: ManualInventoryCreate) -> dict[str, object]:
    with database() as connection:
        product_data = payload.product.model_dump()
        product_data["source"] = "manual"
        product = product_repository.get_or_create(connection, product_data)
        batch = inventory_repository.create_batch(
            connection,
            product_id=product["id"],
            quantity=payload.quantity,
            unit=payload.unit,
            purchase_date=payload.purchase_date or date.today().isoformat(),
            production_date=payload.production_date,
            expiry_date=payload.expiry_date,
            storage_location=payload.storage_location,
            unit_price=payload.unit_price,
        )
    return batch


@router.post("/{batch_id}/consume")
def consume_inventory(batch_id: int, payload: ConsumeRequest) -> dict[str, object]:
    with database() as connection:
        batch = inventory_repository.get_batch(connection, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="库存批次不存在")
        if batch["status"] != "active" or batch["quantity"] <= 0:
            raise HTTPException(status_code=409, detail="该库存已经用完或丢弃")
        updated = inventory_repository.consume(connection, batch_id, payload.quantity, payload.note)
    return updated or {}


@router.delete("/{batch_id}")
def discard_inventory(batch_id: int) -> dict[str, object]:
    with database() as connection:
        batch = inventory_repository.discard(connection, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="库存批次不存在")
    return batch

