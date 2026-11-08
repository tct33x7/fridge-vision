from __future__ import annotations

from pydantic import BaseModel, Field


class ReceiptItemConfirm(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    barcode: str | None = None
    quantity: float = Field(default=1, gt=0)
    unit: str = Field(default="件", min_length=1, max_length=12)
    unit_price: float | None = Field(default=None, ge=0)
    total_price: float | None = Field(default=None, ge=0)
    category: str | None = None
    expiry_date: str | None = None


class ReceiptConfirmRequest(BaseModel):
    purchase_date: str | None = None
    items: list[ReceiptItemConfirm] = Field(min_length=1)


class ExpiryConfirmRequest(BaseModel):
    batch_id: int = Field(gt=0)
    production_date: str | None = None
    expiry_date: str | None = None
    best_before_date: str | None = None
    shelf_life_days: int | None = Field(default=None, ge=0, le=3650)

