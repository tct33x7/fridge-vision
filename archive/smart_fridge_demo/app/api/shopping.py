from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api/shopping", tags=["shopping"])


@router.get("")
def shopping_list() -> dict[str, object]:
    return {"items": [], "status": "reserved_for_next_phase"}

