"""Home dashboard and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app import __version__
from app.api.dependencies import camera, database, repository
from app.database.connection import Database, utc_now
from app.repositories.inventory import InventoryRepository
from app.services.camera_gateway import CameraGateway


router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/dashboard")
def dashboard(repo: InventoryRepository = Depends(repository)) -> dict[str, object]:
    return repo.dashboard()


@router.get("/insights")
def insights(
    days: int = Query(default=7, ge=7, le=28),
    repo: InventoryRepository = Depends(repository),
) -> dict[str, object]:
    if days not in {7, 28}:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="days must be 7 or 28")
    return repo.insights(days=days)


@router.get("/locations")
def locations(repo: InventoryRepository = Depends(repository)) -> dict[str, object]:
    items = repo.locations()
    return {"items": items, "count": len(items)}


@router.get("/health")
def health(
    request: Request,
    db: Database = Depends(database),
    gateway: CameraGateway = Depends(camera),
) -> dict[str, object]:
    database_status = db.health()
    camera_status = gateway.status()
    camera_ready = bool(camera_status.get("connected")) and bool(
        isinstance(camera_status.get("camera"), dict)
        and camera_status["camera"].get("ready")
    )
    return {
        "status": "ok" if database_status["ready"] and camera_ready else "degraded",
        "version": __version__,
        "time": utc_now(),
        "database": database_status,
        "camera": {
            "connected": bool(camera_status.get("connected")),
            "ready": camera_ready,
        },
    }
