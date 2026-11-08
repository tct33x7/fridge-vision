from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.camera import current_camera_mode
from app.services.counter_service import counter_service


router = APIRouter(prefix="/api/counter", tags=["counter"])


class LineReq(BaseModel):
    ax: float
    ay: float
    bx: float
    by: float


class ConfReq(BaseModel):
    value: float


@router.get("/video")
def counter_video() -> Any:
    """计数模式的 MJPEG 推流（带检测框、轨迹和计数线标注）。"""
    if not counter_service.enabled:
        raise HTTPException(status_code=503, detail="计数功能未启用")
    if current_camera_mode() != "counter":
        raise HTTPException(status_code=509, detail="自动计数已暂停：摄像头正被手动拍照功能占用")
    return StreamingResponse(
        counter_service.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/state")
def counter_state() -> dict[str, Any]:
    return counter_service.state(paused=current_camera_mode() != "counter")


@router.post("/line")
def set_line(req: LineReq) -> dict[str, Any]:
    counter_service.set_line(req.ax, req.ay, req.bx, req.by)
    return {"ok": True}


@router.post("/line/flip")
def flip_line() -> dict[str, Any]:
    counter_service.flip_line()
    return {"ok": True}


@router.post("/line/clear")
def clear_line() -> dict[str, Any]:
    counter_service.clear_line()
    return {"ok": True}


@router.post("/conf")
def set_conf(req: ConfReq) -> dict[str, Any]:
    return {"ok": True, "conf": counter_service.set_conf(req.value)}


@router.post("/reset")
def reset_counter() -> dict[str, Any]:
    counter_service.reset()
    return {"ok": True}
