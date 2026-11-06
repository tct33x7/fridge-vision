from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InventoryBatch:
    id: int
    product_id: int
    quantity: float
    unit: str
    expiry_date: str | None = None
    status: str = "active"

