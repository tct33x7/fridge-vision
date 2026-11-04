from __future__ import annotations

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    barcode: str | None = None
    category: str = "其他"
    brand: str | None = None
    default_unit: str = "份"
    estimated_weight_g: float = Field(default=100, gt=0)
    calories_kcal: float = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    carbs_g: float = Field(default=0, ge=0)
    fat_g: float = Field(default=0, ge=0)

