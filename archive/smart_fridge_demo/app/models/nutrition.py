from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NutritionTotals:
    calories_kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0

