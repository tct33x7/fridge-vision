from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Scan:
    id: int
    scan_type: str
    status: str
    engine: str
    original_name: str

