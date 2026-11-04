"""Validated HTTP request models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Flavor = Literal["light", "savory", "sour", "sweet", "spicy", "bitter", "rich"]
Unit = Literal["piece", "pack", "box", "bottle", "g", "kg", "ml", "l"]


class NutritionInput(StrictModel):
    basis_amount: float = Field(gt=0, le=1_000_000)
    basis_unit: Unit
    calories_kcal: float | None = Field(default=None, ge=0, le=100_000)
    protein_g: float | None = Field(default=None, ge=0, le=100_000)
    carbs_g: float | None = Field(default=None, ge=0, le=100_000)
    fat_g: float | None = Field(default=None, ge=0, le=100_000)
    fiber_g: float | None = Field(default=None, ge=0, le=100_000)
    sodium_mg: float | None = Field(default=None, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def require_a_value(self):
        values = (
            self.calories_kcal,
            self.protein_g,
            self.carbs_g,
            self.fat_g,
            self.fiber_g,
            self.sodium_mg,
        )
        if all(value is None for value in values):
            raise ValueError("nutrition needs at least one measured value")
        return self


class FoodDetails(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="other", min_length=1, max_length=50)
    barcode: str | None = Field(default=None, min_length=4, max_length=64)
    quantity: float = Field(gt=0, le=1_000_000)
    unit: Unit = "piece"
    location_id: str = Field(default="fridge", min_length=1, max_length=64)
    purchased_on: date | None = None
    expires_on: date | None = None
    note: str = Field(default="", max_length=500)
    primary_flavor: Flavor | None = None
    nutrition: NutritionInput | None = None

    @field_validator("barcode")
    @classmethod
    def normalize_barcode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        compact = "".join(value.split())
        if not compact.replace("-", "").isalnum():
            raise ValueError("barcode may only contain letters, numbers, and hyphens")
        return compact

    @model_validator(mode="after")
    def require_compatible_nutrition_unit(self):
        if self.nutrition is None:
            return self
        basis_unit = self.nutrition.basis_unit
        dimensions = {
            "g": "mass",
            "kg": "mass",
            "ml": "volume",
            "l": "volume",
        }
        compatible = self.unit == basis_unit or (
            dimensions.get(self.unit) is not None
            and dimensions.get(self.unit) == dimensions.get(basis_unit)
        )
        if not compatible:
            raise ValueError(
                "nutrition basis unit cannot be converted from the inventory unit"
            )
        return self


class InventoryCreate(FoodDetails):
    source_capture_id: str | None = Field(default=None, min_length=8, max_length=128)
    intake_session_id: str | None = Field(default=None, min_length=8, max_length=128)


class QuantityChange(StrictModel):
    amount: float = Field(gt=0, le=1_000_000)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=300)
    record_meal: bool = False
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None
    eaten_at: datetime | None = None

    @field_validator("eaten_at")
    @classmethod
    def normalize_eaten_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eaten_at must include a timezone")
        return value.astimezone(timezone.utc)


class IntakeConfirm(FoodDetails):
    pass


class DiscardRequest(StrictModel):
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=300)


class ProfileUpdate(StrictModel):
    display_name: str = Field(default="", max_length=80)
    diet_goal: Literal["balanced", "weight_loss", "muscle_gain", "other"] = "balanced"
    preferences: list[str] = Field(default_factory=list, max_length=50)
    allergies: list[str] = Field(default_factory=list, max_length=50)
    medications: list[str] = Field(default_factory=list, max_length=50)
    onboarding_completed: bool = False

    @field_validator("preferences", "allergies", "medications")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if not item:
                continue
            if len(item) > 80:
                raise ValueError("each item must be at most 80 characters")
            key = item.casefold()
            if key not in seen:
                cleaned.append(item)
                seen.add(key)
        return cleaned


CameraAction = Literal["capture", "retry"]
