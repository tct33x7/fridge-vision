from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Recipe:
    title: str
    minutes: int
    ingredients: list[str] = field(default_factory=list)

