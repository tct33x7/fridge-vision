"""Typed access to application-owned services."""

from __future__ import annotations

from fastapi import Request

from app.database.connection import Database
from app.repositories.door_events import DoorEventRepository
from app.repositories.inventory import InventoryRepository
from app.services.camera_gateway import CameraGateway
from app.services.capture_library import CaptureLibrary
from app.services.media_store import MediaStore


def repository(request: Request) -> InventoryRepository:
    return request.app.state.repository


def database(request: Request) -> Database:
    return request.app.state.database


def camera(request: Request) -> CameraGateway:
    return request.app.state.camera


def capture_library(request: Request) -> CaptureLibrary:
    return request.app.state.capture_library


def media_store(request: Request) -> MediaStore:
    return request.app.state.media_store


def door_events(request: Request) -> DoorEventRepository:
    return request.app.state.door_events
