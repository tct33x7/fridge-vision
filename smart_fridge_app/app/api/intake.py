"""Persistent photo-intake sessions."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import capture_library, repository
from app.repositories.inventory import ConflictError, InventoryRepository, NotFoundError
from app.schemas import IntakeConfirm
from app.services.capture_library import CaptureLibrary


router = APIRouter(prefix="/api/v1/intake-sessions", tags=["intake"])


def _public_session(item: dict[str, object]) -> dict[str, object]:
    result = dict(item)
    captures = result.get("captures")
    if isinstance(captures, list):
        result["captures"] = [
            {key: value for key, value in capture.items() if key != "local_relpath"}
            for capture in captures
            if isinstance(capture, dict)
        ]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return _public_session(repo.create_session())


@router.get("")
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    session_status: Literal["open", "review", "confirmed", "failed", "cancelled"]
    | None = Query(default=None, alias="status"),
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    items = repo.list_sessions(limit=limit, status=session_status)
    return {"items": [_public_session(item) for item in items], "count": len(items)}


@router.get("/{session_id}")
def get_session(
    session_id: str,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    item = repo.get_session(session_id)
    if item is None:
        raise NotFoundError("intake session does not exist")
    return _public_session(item)


@router.post("/{session_id}/capture", status_code=status.HTTP_201_CREATED)
def capture_for_session(
    session_id: str,
    library: CaptureLibrary = Depends(capture_library),
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    session = repo.get_session(session_id)
    if session is None:
        raise NotFoundError("intake session does not exist")
    if session["status"] not in {"open", "review"}:
        raise ConflictError("intake session can no longer accept captures")
    library.capture(session_id)
    item = repo.get_session(session_id)
    assert item is not None
    return _public_session(item)


@router.post("/{session_id}/select/{capture_id}")
def select_session_capture(
    session_id: str,
    capture_id: str,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return _public_session(repo.select_capture(session_id, capture_id))


@router.post("/{session_id}/attach/{capture_id}")
def attach_session_capture(
    session_id: str,
    capture_id: str,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    """Attach an already imported photo to a new or resumed intake session."""

    return _public_session(repo.attach_capture(session_id, capture_id))


@router.post("/{session_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_session(
    session_id: str,
    payload: IntakeConfirm,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    item = repo.create_lot(
        name=payload.name,
        category=payload.category,
        barcode=payload.barcode,
        quantity=payload.quantity,
        unit=payload.unit,
        location_id=payload.location_id,
        purchased_on=payload.purchased_on.isoformat() if payload.purchased_on else None,
        expires_on=payload.expires_on.isoformat() if payload.expires_on else None,
        note=payload.note,
        source_capture_id=None,
        intake_session_id=session_id,
        primary_flavor=payload.primary_flavor,
        nutrition=payload.nutrition.model_dump() if payload.nutrition else None,
    )
    session = repo.get_session(session_id)
    assert session is not None
    return {"inventory": item, "session": _public_session(session)}


@router.post("/{session_id}/cancel")
def cancel_session(
    session_id: str,
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    return _public_session(repo.cancel_session(session_id))
