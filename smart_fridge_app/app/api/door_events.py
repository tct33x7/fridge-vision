"""Door-camera event ingestion, listing, undo, and correction."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import door_events
from app.repositories.door_events import DoorEventRepository
from app.schemas import DoorEventCorrection, DoorEventIn, ShelfLifeUpdate
from app.services.media_store import MediaStoreError


router = APIRouter(prefix="/api/v1/door-events", tags=["door-events"])

MAX_KEYFRAME_BYTES = 4 * 1024 * 1024


def _decode_keyframe(encoded: str | None) -> bytes | None:
    if not encoded:
        return None
    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="keyframe_base64 is not valid base64") from error
    if len(body) > MAX_KEYFRAME_BYTES:
        raise HTTPException(status_code=413, detail="keyframe exceeds 4 MB")
    return body


@router.post("", status_code=status.HTTP_201_CREATED)
def create_door_event(
    payload: DoorEventIn,
    repo: DoorEventRepository = Depends(door_events),
) -> dict[str, object]:
    keyframe = _decode_keyframe(payload.keyframe_base64)
    try:
        return repo.record(
            session_id=payload.session_id,
            occurred_at=payload.occurred_at_iso(),
            action=payload.action,
            label=payload.label,
            label_zh=payload.label_zh,
            confidence=payload.confidence,
            count=payload.count,
            vlm=payload.vlm,
            keyframe=keyframe,
        )
    except MediaStoreError as error:
        raise HTTPException(status_code=422, detail=f"keyframe rejected: {error}") from error


@router.get("")
def list_door_events(
    limit: int = Query(default=20, ge=1, le=100),
    repo: DoorEventRepository = Depends(door_events),
) -> dict[str, object]:
    items = repo.list(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/meta/shelf-life")
def shelf_life(repo: DoorEventRepository = Depends(door_events)) -> dict[str, object]:
    items = repo.shelf_life()
    return {"items": items, "count": len(items)}


@router.put("/meta/shelf-life/{category}")
def update_shelf_life(
    category: str,
    payload: ShelfLifeUpdate,
    repo: DoorEventRepository = Depends(door_events),
) -> dict[str, object]:
    return repo.set_shelf_life(category, default_days=payload.default_days, location_id=payload.location_id)


@router.get("/{event_id}")
def get_door_event(
    event_id: str, repo: DoorEventRepository = Depends(door_events)
) -> dict[str, object]:
    item = repo.get(event_id)
    if item is None:
        from app.repositories.inventory import NotFoundError

        raise NotFoundError("door event does not exist")
    return item


@router.post("/{event_id}/undo")
def undo_door_event(
    event_id: str, repo: DoorEventRepository = Depends(door_events)
) -> dict[str, object]:
    return repo.undo(event_id)


@router.patch("/{event_id}")
def correct_door_event(
    event_id: str,
    payload: DoorEventCorrection,
    repo: DoorEventRepository = Depends(door_events),
) -> dict[str, object]:
    return repo.correct(event_id, label_zh=payload.label_zh, count=payload.count)
