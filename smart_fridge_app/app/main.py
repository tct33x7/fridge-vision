"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import camera, dashboard, door_events, intake, inventory, media, profile
from app.config import load_settings
from app.database.connection import Database
from app.repositories.door_events import DoorEventRepository
from app.repositories.inventory import (
    ConflictError,
    InventoryRepository,
    NotFoundError,
    RepositoryError,
)
from app.services.camera_gateway import (
    CameraConflict,
    CameraGateway,
    CameraGatewayError,
    CameraNotFound,
)
from app.services.capture_library import CaptureLibrary
from app.services.media_store import MediaStore, MediaStoreError


LOG = logging.getLogger("smart_fridge")
settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = Database(settings.database_path)
    database.initialize()
    app.state.database = database
    app.state.repository = InventoryRepository(database)
    app.state.camera = CameraGateway(
        settings.camera_url, timeout_seconds=settings.camera_timeout_seconds
    )
    app.state.media_store = MediaStore(settings.media_dir)
    app.state.capture_library = CaptureLibrary(
        app.state.camera,
        app.state.media_store,
        app.state.repository,
    )
    app.state.door_events = DoorEventRepository(app.state.repository, app.state.media_store)
    LOG.info("Smart Fridge ready; data=%s camera=%s", settings.data_dir, settings.camera_url)
    yield


app = FastAPI(
    title="饮食均衡助手",
    version=__version__,
    description="Local-first food inventory and camera integration foundation.",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if not request.url.path.startswith(("/docs", "/openapi.json")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        )
    return response


@app.exception_handler(NotFoundError)
async def repository_not_found(_request: Request, error: NotFoundError):
    return JSONResponse(status_code=404, content={"error": str(error)})


@app.exception_handler(ConflictError)
async def repository_conflict(_request: Request, error: ConflictError):
    return JSONResponse(status_code=409, content={"error": str(error)})


@app.exception_handler(RepositoryError)
async def repository_failure(_request: Request, error: RepositoryError):
    return JSONResponse(status_code=400, content={"error": str(error)})


@app.exception_handler(CameraNotFound)
async def camera_not_found(_request: Request, error: CameraNotFound):
    return JSONResponse(status_code=404, content={"error": str(error)})


@app.exception_handler(CameraConflict)
async def camera_conflict(_request: Request, error: CameraConflict):
    return JSONResponse(status_code=409, content={"error": str(error)})


@app.exception_handler(CameraGatewayError)
async def camera_unavailable(_request: Request, error: CameraGatewayError):
    return JSONResponse(status_code=503, content={"error": str(error)})


@app.exception_handler(MediaStoreError)
async def media_storage_failure(_request: Request, error: MediaStoreError):
    return JSONResponse(status_code=503, content={"error": str(error)})


app.include_router(dashboard.router)
app.include_router(inventory.router)
app.include_router(camera.router)
app.include_router(intake.router)
app.include_router(media.router)
app.include_router(profile.router)
app.include_router(door_events.router)
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
