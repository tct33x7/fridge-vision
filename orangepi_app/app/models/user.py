from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UserPreferences:
    servings: int = 2
    allergens: list[str] = field(default_factory=list)
    reminder_days: int = 3

