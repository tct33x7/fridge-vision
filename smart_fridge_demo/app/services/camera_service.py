from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from typing import Iterator

from app.config import CAMERA_DEVICE, CAMERA_FPS, CAMERA_HEIGHT, CAMERA_JPEG_QUALITY, CAMERA_WIDTH

try:
    import cv2
except ImportError:  # Camera support stays optional on development machines.
    cv2 = None  # type: ignore[assignment]


class CameraUnavailableError(RuntimeError):
    pass


class CameraService:
    """Own a single USB camera reader shared by MJPEG streaming and snapshots."""

    def __init__(self) -> None:
        self.device = CAMERA_DEVICE
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        self.jpeg_quality = max(40, min(CAMERA_JPEG_QUALITY, 95))
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._frame: bytes | None = None
        self._frame_id = 0
        self._last_frame_at: str | None = None
        self._error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._reader_loop, name="usb-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._release_capture()

    def status(self) -> dict[str, object]:
        with self._condition:
            return {
                "device": self.device,
                "online": self._frame is not None and self._error is None,
                "last_frame_at": self._last_frame_at,
                "frame_id": self._frame_id,
                "error": self._error,
                "resolution": f"{self.width}x{self.height}",
                "fps": self.fps,
            }

    def snapshot(self, timeout: float = 4.0) -> bytes:
        self.start()
        deadline = time.monotonic() + timeout
        with self._condition:
            while (self._frame is None or self._error is not None) and time.monotonic() < deadline:
                self._condition.wait(timeout=max(0.05, deadline - time.monotonic()))
            if self._frame is None or self._error is not None:
                raise CameraUnavailableError(self._error or f"无法从摄像头 {self.device} 获取画面")
            return bytes(self._frame)

    def mjpeg_frames(self) -> Iterator[bytes]:
        self.start()
        last_frame_id = -1
        while not self._stop_event.is_set():
            with self._condition:
                self._condition.wait_for(
                    lambda: self._frame_id != last_frame_id or self._stop_event.is_set(), timeout=5
                )
                if self._stop_event.is_set():
                    return
                frame = self._frame
                last_frame_id = self._frame_id
            if frame is None:
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"

    def _reader_loop(self) -> None:
        if cv2 is None:
            self._set_error("未安装 OpenCV（cv2），摄像头功能不可用")
            return

        while not self._stop_event.is_set():
            capture = self._open_capture()
            if capture is None:
                self._stop_event.wait(3)
                continue
            consecutive_failures = 0
            while not self._stop_event.is_set():
                ok, image = capture.read()
                if not ok or image is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 8:
                        self._set_error(f"摄像头 {self.device} 读取失败，正在重连")
                        break
                    self._stop_event.wait(0.08)
                    continue
                consecutive_failures = 0
                ok, encoded = cv2.imencode(
                    ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
                )
                if not ok:
                    continue
                with self._condition:
                    self._frame = encoded.tobytes()
                    self._frame_id += 1
                    self._last_frame_at = datetime.now(timezone.utc).isoformat()
                    self._error = None
                    self._condition.notify_all()
            self._release_capture()

    def _open_capture(self):
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        source: int | str = int(self.device) if self.device.isdigit() else self.device
        capture = cv2.VideoCapture(source, backend)
        if not capture.isOpened():
            capture.release()
            self._set_error(f"无法打开摄像头 {self.device}")
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._capture = capture
        return capture

    def _release_capture(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()

    def _set_error(self, message: str) -> None:
        with self._condition:
            self._error = message
            self._condition.notify_all()
