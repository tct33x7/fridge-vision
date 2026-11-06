from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.database.connection import database
from app.database.repositories import product_repository
from app.schemas.product import ProductCreate
from app.services.openfoodfacts_client import OpenFoodFactsClient


router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products(q: str | None = None) -> dict[str, object]:
    with database() as connection:
        return {"items": product_repository.list_products(connection, q)}


@router.post("")
def create_product(payload: ProductCreate) -> dict[str, object]:
    with database() as connection:
        product = product_repository.get_or_create(connection, payload.model_dump())
    return product


@router.get("/barcode/{barcode}")
def lookup_barcode(barcode: str) -> dict[str, object]:
    if not barcode.isdigit() or not 7 <= len(barcode) <= 14:
        raise HTTPException(status_code=422, detail="条码应为 7–14 位数字")
    with database() as connection:
        existing = connection.execute("SELECT * FROM products WHERE barcode = ?", (barcode,)).fetchone()
        if existing:
            return {"found": True, "source": "local", "product": dict(existing)}
    result = OpenFoodFactsClient().lookup(barcode)
    if not result:
        return {"found": False, "source": "openfoodfacts", "product": None}
    return {"found": True, "source": "openfoodfacts", "product": result}

