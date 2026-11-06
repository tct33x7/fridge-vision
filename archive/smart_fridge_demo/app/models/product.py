from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Product:
    id: int
    name: str
    category: str
    barcode: str | None = None
    brand: str | None = None

