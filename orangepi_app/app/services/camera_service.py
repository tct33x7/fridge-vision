from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from typing import Iterator

from app.config import CAMERA_DEVICE, CAMERA_FPS, CAMERA_HEIGHT, CAMERA_JPEG_QUALITY, CAMERA_MODE, CAMERA_WIDTH

try:
    import cv2
except ImportError:  # Camera support stays optional on development machines.
    cv2 = None  # type: ignore[assignment]


class CameraUnavailableError(RuntimeError):
    pass


class CameraService:
    """Own a single camera reader shared by MJPEG streaming and snapshots."""

    # macOS 上最多探测 5 个摄像头索引
    _MAX_PROBE_INDEX = 5

    # Linux 下设备列表刷新间隔（秒）：支持热插拔，同时避免频繁扫描
    _LINUX_SCAN_INTERVAL = 10.0

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
        self._devices_cache: list[dict[str, object]] | None = None
        self._devices_scanned_at: float = 0.0

    @staticmethod
    def _is_macos() -> bool:
        return sys.platform == "darwin"

    def list_devices(self) -> list[dict[str, object]]:
        """枚举可用摄像头列表（macOS 用索引探测，Linux 解析 /dev/video*）。"""
        if cv2 is None:
            return []
        if self._is_macos():
            # macOS 探测需要逐个打开摄像头（昂贵且会占用设备），结果长期缓存
            if self._devices_cache is not None:
                return self._devices_cache
        elif (
            self._devices_cache is not None
            and time.monotonic() - self._devices_scanned_at < self._LINUX_SCAN_INTERVAL
        ):
            # Linux 扫描很轻量，定期刷新以支持摄像头热插拔
            return self._devices_cache

        devices: list[dict[str, object]] = []
        if self._is_macos():
            for idx in range(self._MAX_PROBE_INDEX):
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    # 读取一帧确认可用
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        h, w = frame.shape[:2]
                        label = "FaceTime 摄像头" if idx == 0 else f"外部摄像头 {idx}"
                        devices.append({
                            "index": idx,
                            "id": str(idx),
                            "name": label,
                            "resolution": f"{w}x{h}",
                        })
                cap.release()
        else:
            devices = self._list_linux_capture_devices()

        self._devices_cache = devices
        self._devices_scanned_at = time.monotonic()
        return devices

    @staticmethod
    def _list_linux_capture_devices() -> list[dict[str, object]]:
        """枚举 Linux 下支持视频采集的 /dev/video* 节点。

        一个 UVC 摄像头通常会创建两个节点（采集 + metadata），
        只有支持 V4L2_CAP_VIDEO_CAPTURE 的节点能真正出画面。
        """
        import glob
        import subprocess

        devices: list[dict[str, object]] = []
        for path in sorted(glob.glob("/dev/video*")):
            index = int(path.replace("/dev/video", ""))
            name = path
            try:
                with open(f"/sys/class/video4linux/video{index}/name", encoding="utf-8") as fh:
                    name = fh.read().strip() or path
            except OSError:
                pass

            is_capture = True
            try:
                info = subprocess.run(
                    ["v4l2-ctl", "-d", path, "--all"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                # "Capabilities" 是整张卡的描述（同一摄像头所有节点相同），
                # 真正的节点能力在 "Device Capabilities" 段落里。
                sections = info.stdout.split("Device Capabilities")
                is_capture = len(sections) > 1 and "Video Capture" in sections[1]
            except (OSError, subprocess.SubprocessError):
                # v4l2-ctl 不可用时保留全部节点，由打开阶段自然失败
                pass
            if not is_capture:
                continue

            devices.append({
                "index": index,
                "id": path,
                "name": name,
                "resolution": None,
            })
        return devices

    def switch_device(self, device_id: str) -> dict[str, object]:
        """切换到指定摄像头设备。"""
        devices = self.list_devices()
        match = next((d for d in devices if d["id"] == device_id), None)
        if match is None:
            raise ValueError(f"找不到摄像头设备: {device_id}")

        old_device = self.device
        # 停止当前读取
        self.stop()
        # 更新设备
        self.device = device_id
        self._frame = None
        self._error = None
        self._frame_id = 0
        self._last_frame_at = None
        # 重新启动
        self.start()
        return {
            "old_device": old_device,
            "new_device": device_id,
            "name": match.get("name", device_id),
        }

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
                "camera_mode": CAMERA_MODE,
                "available_devices": self.list_devices(),
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
        if self._is_macos():
            backend = cv2.CAP_AVFOUNDATION
        elif sys.platform.startswith("linux"):
            backend = cv2.CAP_V4L2
        else:
            backend = cv2.CAP_ANY
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
