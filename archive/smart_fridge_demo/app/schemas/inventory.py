from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.product import ProductCreate


class ManualInventoryCreate(BaseModel):
    product: ProductCreate
    quantity: float = Field(default=1, gt=0)
    unit: str = Field(default="份", min_length=1, max_length=12)
    purchase_date: str | None = None
    production_date: str | None = None
    expiry_date: str | None = None
    storage_location: str = "冷藏室"
    unit_price: float | None = Field(default=None, ge=0)


class ConsumeRequest(BaseModel):
    quantity: float = Field(default=1, gt=0)
    note: str | None = Field(default=None, max_length=200)

