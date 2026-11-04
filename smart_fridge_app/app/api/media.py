"""Application-owned capture history and image delivery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import capture_library, repository
from app.repositories.inventory import InventoryRepository, NotFoundError
from app.services.capture_library import CaptureLibrary


router = APIRouter(prefix="/api/v1/media", tags=["media"])


def _public(item: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in item.items() if key != "local_relpath"}


@router.get("")
def list_media(
    limit: int = Query(default=30, ge=1, le=100),
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    items = repo.list_media(limit=limit)
    return {"items": [_public(item) for item in items], "count": len(items)}


@router.post("/sync")
def sync_media(
    limit: int = Query(default=24, ge=1, le=100),
    library: CaptureLibrary = Depends(capture_library),
) -> dict[str, object]:
    return library.sync_recent(limit=limit)


@router.get("/{capture_id}")
def get_media(
    capture_id: str,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    item = repo.get_media(capture_id)
    if item is None:
        raise NotFoundError("stored capture does not exist")
    return _public(item)


@router.get("/{capture_id}/image")
def media_image(
    capture_id: str,
    library: CaptureLibrary = Depends(capture_library),
) -> Response:
    return Response(
        library.image(capture_id),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
