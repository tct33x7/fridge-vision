"""Onboarding and user preference persistence."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import repository
from app.repositories.inventory import InventoryRepository
from app.schemas import ProfileUpdate


router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("")
def get_profile(repo: InventoryRepository = Depends(repository)) -> dict[str, object]:
    return repo.profile()


@router.put("")
def update_profile(
    payload: ProfileUpdate,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return repo.update_profile(**payload.model_dump())

