from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.scans import _save_and_analyze
from app.config import DEFAULT_CAMERA_MODE
from app.services.camera_service import CameraService, CameraUnavailableError
from app.services.counter_service import counter_service
from app.services.gpio_button import GPIOButtonMonitor


router = APIRouter(prefix="/api/camera", tags=["camera"])
camera_service = CameraService()

# ---------------- 摄像头占用模式管理 ----------------
# 一颗 USB 摄像头（UGREEN /dev/video0）被两种功能互斥共用：
#   counter —— 默认：物品进出自动计数持续运行
#   manual  —— 手动拍照识别（进入“摄像头”页面才切换，离开自动恢复计数）

_CAMERA_MODES = {"counter", "manual"}
_mode_lock = threading.Lock()
camera_mode = DEFAULT_CAMERA_MODE if DEFAULT_CAMERA_MODE in _CAMERA_MODES else "counter"
_last_manual_activity = time.monotonic()
_MANUAL_IDLE_SECONDS = 20  # manual 模式下无状态轮询超过该秒数即自动恢复计数

# manual 模式下浏览器每 1.2s 轮询一次 /status；浏览器关闭后轮询消失，由看门狗自动切回 counter


def current_camera_mode() -> str:
    return camera_mode


def set_camera_mode(mode: str) -> dict[str, Any]:
    """切换摄像头占用模式，保证计数与手动拍照不同时占用摄像头。"""
    global camera_mode
    if mode not in _CAMERA_MODES:
        raise ValueError("模式必须是 counter 或 manual")
    with _mode_lock:
        if camera_mode == mode:
            return {"mode": camera_mode, "changed": False}
        if mode == "manual":
            counter_service.stop()   # 先暂停计数，释放摄像头
            camera_service.start()
            _touch_manual_activity()  # 切换瞬间刷新活跃时间，给看门狗一个全新窗口
        else:
            camera_service.stop()    # 先停手动读取，释放摄像头
            counter_service.start()  # 恢复自动计数
        camera_mode = mode
        print(f"[camera] 模式切换 -> {mode}", flush=True)
    return {"mode": camera_mode, "changed": True}


def _manual_watchdog() -> None:
    """浏览器关闭后自动恢复 counter 模式，避免计数永久暂停。"""
    global camera_mode
    while True:
        time.sleep(5)
        with _mode_lock:
            if camera_mode == "manual" and time.monotonic() - _last_manual_activity > _MANUAL_IDLE_SECONDS:
                camera_mode = "counter"  # 直接置位，避免递归加锁
                camera_service.stop()
                counter_service.start()
                print("[camera] manual 模式空闲超时，自动恢复计数", flush=True)


def _touch_manual_activity() -> None:
    global _last_manual_activity
    _last_manual_activity = time.monotonic()


class CameraCaptureRequest(BaseModel):
    scan_type: Literal["food", "barcode", "receipt", "expiry", "ocr"] | None = None
    batch_id: int | None = Field(default=None, gt=0)
    engine: str = "rapidocr"


class CaptureController:
    def __init__(self) -> None:
        self.scan_type = "food"
        self.batch_id: int | None = None
        self.engine = "rapidocr"
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
        self.button.start()
        if camera_mode == "manual":
            camera_service.start()
        else:
            counter_service.start()
        self._watchdog = threading.Thread(target=_manual_watchdog, name="camera-mode-watchdog", daemon=True)
        self._watchdog.start()

    def stop(self) -> None:
        self.button.stop()
        camera_service.stop()
        counter_service.stop()

    def configure(
        self,
        scan_type: str,
        batch_id: int | None = None,
        engine: str = "rapidocr",
    ) -> dict[str, Any]:
        if scan_type not in {"food", "barcode", "receipt", "expiry", "ocr"}:
            raise ValueError("不支持的识别类型")
        if scan_type == "expiry" and batch_id is None:
            raise ValueError("包装日期识别必须先选择库存批次")
        with self._state_lock:
            self.scan_type = scan_type
            self.batch_id = batch_id if scan_type == "expiry" else None
            self.engine = engine
        return self.status()

    def capture(
        self,
        *,
        trigger: str,
        scan_type: str | None = None,
        batch_id: int | None = None,
        engine: str | None = None,
    ) -> dict[str, Any]:
        if scan_type is not None:
            self.configure(scan_type, batch_id, engine or self.engine)
        with self._state_lock:
            selected_type = self.scan_type
            selected_batch = self.batch_id
            selected_engine = self.engine
        if selected_type == "expiry" and selected_batch is None:
            raise ValueError("包装日期识别必须先在网页选择库存批次")
        if camera_mode != "manual":
            raise RuntimeError("自动计数正在占用摄像头；请先打开「摄像头」页面切换到手动模式")
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
                engine=selected_engine,
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

    def status(self, touch: bool = False) -> dict[str, Any]:
        # 只有「摄像头」页面的轮询才刷新 manual 活跃时间，
        # 避免停在首页的浏览器（如香橙派自启 Firefox）让看门狗永远不触发
        if touch and camera_mode == "manual":
            _touch_manual_activity()
        with self._state_lock:
            capture = {
                "scan_type": self.scan_type,
                "batch_id": self.batch_id,
                "engine": self.engine,
                "busy": self.busy,
                "sequence": self.sequence,
                "last_scan_id": self.last_scan_id,
                "last_trigger": self.last_trigger,
                "last_capture_at": self.last_capture_at,
                "error": self.last_error,
            }
        return {
            "mode": camera_mode,
            "camera": camera_service.status(),
            "button": self.button.status(),
            "capture": capture,
            "counter": counter_service.state(paused=camera_mode != "counter"),
        }


capture_controller = CaptureController()


def start_hardware() -> None:
    capture_controller.start()


def stop_hardware() -> None:
    capture_controller.stop()


@router.get("/devices")
def list_camera_devices() -> dict[str, Any]:
    """列出所有可用摄像头设备。"""
    return {"devices": camera_service.list_devices()}


@router.post("/switch")
def switch_camera(payload: dict[str, Any]) -> dict[str, Any]:
    """切换到指定摄像头设备。"""
    if camera_mode != "manual":
        raise HTTPException(status_code=509, detail="自动计数正在占用摄像头；请先切换到手动模式")
    device_id = payload.get("device_id")
    if not device_id:
        raise HTTPException(status_code=422, detail="缺少 device_id 参数")
    try:
        result = camera_service.switch_device(str(device_id))
        return {"status": "ok", **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/status")
def camera_status(view: str | None = None) -> dict[str, Any]:
    """view=camera 表示轮询方正处于摄像头页面，用于 manual 模式活跃判定。"""
    return capture_controller.status(touch=view == "camera")


@router.post("/mode")
def switch_camera_mode(payload: dict[str, Any]) -> dict[str, Any]:
    """切换摄像头占用模式：counter=自动计数（默认），manual=手动拍照识别。"""
    mode = str(payload.get("mode", ""))
    try:
        result = set_camera_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "ok",
        **result,
        "counter": counter_service.state(paused=result["mode"] != "counter"),
    }


@router.get("/stream")
def camera_stream() -> StreamingResponse:
    if camera_mode != "manual":
        raise HTTPException(status_code=509, detail="自动计数正在占用摄像头；请先切换到手动模式")
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
        return capture_controller.configure(
            payload.scan_type or "food",
            payload.batch_id,
            payload.engine,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/capture")
def capture_camera(payload: CameraCaptureRequest) -> dict[str, Any]:
    try:
        return capture_controller.capture(
            trigger="web",
            scan_type=payload.scan_type,
            batch_id=payload.batch_id,
            engine=payload.engine,
        )
    except CameraUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
