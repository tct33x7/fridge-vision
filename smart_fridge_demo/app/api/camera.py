from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.scans import _save_and_analyze
from app.services.camera_service import CameraService, CameraUnavailableError
from app.services.gpio_button import GPIOButtonMonitor


router = APIRouter(prefix="/api/camera", tags=["camera"])
camera_service = CameraService()


class CameraCaptureRequest(BaseModel):
    scan_type: Literal["food", "barcode", "receipt", "expiry"] | None = None
    batch_id: int | None = Field(default=None, gt=0)


class CaptureController:
    def __init__(self) -> None:
        self.scan_type = "food"
        self.batch_id: int | None = None
        self.sequence = 0
        self.last_scan_id: int | None = None
        self.last_trigger: str | None = None
        self.last_capture_at: str | None = None
        self.last_error: str | None = None
        self.busy = False
        self._state_lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self.button = GPIOButtonMonitor(self.capture_from_button)

    def start(self) -> None:
        camera_service.start()
        self.button.start()

    def stop(self) -> None:
        self.button.stop()
        camera_service.stop()

    def configure(self, scan_type: str, batch_id: int | None = None) -> dict[str, Any]:
        if scan_type not in {"food", "barcode", "receipt", "expiry"}:
            raise ValueError("不支持的识别类型")
        if scan_type == "expiry" and batch_id is None:
            raise ValueError("包装日期识别必须先选择库存批次")
        with self._state_lock:
            self.scan_type = scan_type
            self.batch_id = batch_id if scan_type == "expiry" else None
        return self.status()

    def capture(
        self,
        *,
        trigger: str,
        scan_type: str | None = None,
        batch_id: int | None = None,
    ) -> dict[str, Any]:
        if scan_type is not None:
            self.configure(scan_type, batch_id)
        with self._state_lock:
            selected_type = self.scan_type
            selected_batch = self.batch_id
        if selected_type == "expiry" and selected_batch is None:
            raise ValueError("包装日期识别必须先在网页选择库存批次")
        if not self._capture_lock.acquire(blocking=False):
            raise RuntimeError("摄像头正在拍照识别，请稍候")

        with self._state_lock:
            self.busy = True
            self.last_error = None
        try:
            content = camera_service.snapshot()
            now = datetime.now(timezone.utc)
            scan = _save_and_analyze(
                content=content,
                original_name=f"camera-{now.strftime('%Y%m%d-%H%M%S')}.jpg",
                content_type="image/jpeg",
                scan_type=selected_type,
                batch_id=selected_batch,
            )
            with self._state_lock:
                self.sequence += 1
                self.last_scan_id = int(scan["id"])
                self.last_trigger = trigger
                self.last_capture_at = now.isoformat()
            return scan
        except Exception as exc:
            with self._state_lock:
                self.last_error = str(getattr(exc, "detail", exc))
            raise
        finally:
            with self._state_lock:
                self.busy = False
            self._capture_lock.release()

    def capture_from_button(self) -> None:
        try:
            self.capture(trigger="gpio")
        except Exception:
            # The error is exposed through /api/camera/status; the GPIO thread must stay alive.
            return

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            capture = {
                "scan_type": self.scan_type,
                "batch_id": self.batch_id,
                "busy": self.busy,
                "sequence": self.sequence,
                "last_scan_id": self.last_scan_id,
                "last_trigger": self.last_trigger,
                "last_capture_at": self.last_capture_at,
                "error": self.last_error,
            }
        return {"camera": camera_service.status(), "button": self.button.status(), "capture": capture}


capture_controller = CaptureController()


def start_hardware() -> None:
    capture_controller.start()


def stop_hardware() -> None:
    capture_controller.stop()


@router.get("/status")
def camera_status() -> dict[str, Any]:
    return capture_controller.status()


@router.get("/stream")
def camera_stream() -> StreamingResponse:
    try:
        camera_service.snapshot(timeout=3)
    except CameraUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(
        camera_service.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.put("/config")
def configure_camera(payload: CameraCaptureRequest) -> dict[str, Any]:
    try:
        return capture_controller.configure(payload.scan_type or "food", payload.batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/capture")
def capture_camera(payload: CameraCaptureRequest) -> dict[str, Any]:
    try:
        return capture_controller.capture(
            trigger="web",
            scan_type=payload.scan_type,
            batch_id=payload.batch_id,
        )
    except CameraUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
