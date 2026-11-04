#!/usr/bin/env python3
"""Always-on camera, GPIO/web capture, OCR, and structured archiving.

Wiring used by this project:
  D -> PL4 (physical header pin 7)
  V -> 3.3V (physical header pin 1 or 17)
  G -> GND (physical header pin 9)

Capture is deliberately independent from recognition: the JPEG is committed
first, then a background worker performs OCR and structured extraction.  A
recognition failure never loses the original image or stops the camera.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from capture_repository import CaptureRepository
from recognition import RecognitionWorker, TesseractRecognizer


LOG = logging.getLogger("camera_capture")


PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>摄像头拍摄</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #10131a; color: #eef2f7; }
    main { width: min(1100px, 100%); margin: auto; padding: 18px; }
    h1 { margin: 0 0 14px; font-size: 1.35rem; }
    .preview { width: 100%; min-height: 240px; max-height: 72vh; object-fit: contain;
      display: block; border-radius: 12px; background: #050607; }
    .bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
    button { border: 0; border-radius: 10px; padding: 13px 28px; font-size: 1.05rem;
      font-weight: 700; cursor: pointer; color: white; background: #1976d2; }
    button:disabled { opacity: .55; cursor: wait; }
    .status { color: #aeb8c7; }
    .ok { color: #69d68b; }
    .warn { color: #ffbd66; }
    .last { display: none; margin-top: 14px; padding: 12px; border-radius: 10px;
      background: #191f2a; }
    .last img { width: 150px; max-height: 100px; object-fit: cover; border-radius: 7px;
      vertical-align: middle; margin-right: 12px; }
    a { color: #8dc5ff; }
  </style>
</head>
<body>
<main>
  <h1>USB 摄像头实时画面</h1>
  <img class="preview" src="/stream.mjpg" alt="实时摄像头画面">
  <div class="bar">
    <button id="capture" type="button">拍照</button>
    <span id="message" class="status">摄像头连接中……</span>
  </div>
  <div id="gpio" class="status"></div>
  <div id="ocr" class="status"></div>
  <div id="last" class="last">
    <a id="lastLink" target="_blank"><img id="lastImage" alt="最近拍摄"></a>
    <span id="lastName"></span>
  </div>
</main>
<script>
const button = document.getElementById('capture');
const message = document.getElementById('message');
const gpio = document.getElementById('gpio');
const ocr = document.getElementById('ocr');
const last = document.getElementById('last');
const lastLink = document.getElementById('lastLink');
const lastImage = document.getElementById('lastImage');
const lastName = document.getElementById('lastName');

function showLast(item) {
  if (!item) return;
  const url = item.image_url;
  lastLink.href = url;
  lastImage.src = url + '?t=' + Date.now();
  const recognition = item.recognition || {};
  const recognized = recognition.status === 'completed'
    ? `；${recognition.type || 'document'} / ${recognition.name || '未命名'}`
    : `；识别状态：${recognition.status || 'pending'}`;
  lastName.textContent = item.filename + '（' + item.trigger + recognized + '）';
  last.style.display = 'block';
}

async function status() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    const data = await response.json();
    message.textContent = data.camera.ready
      ? `摄像头运行中：${data.camera.width}×${data.camera.height}`
      : `摄像头异常：${data.camera.error || '尚无画面'}`;
    message.className = data.camera.ready ? 'status ok' : 'status warn';
    gpio.textContent = '实体按钮：' + data.gpio.message;
    gpio.className = data.gpio.available ? 'status ok' : 'status warn';
    ocr.textContent = data.recognition.enabled
      ? `识别：${data.recognition.available ? '可用' : '不可用'}；等待 ${data.recognition.queued} 项`
      : '识别：已停用';
    ocr.className = data.recognition.available ? 'status ok' : 'status warn';
    showLast(data.last_capture);
  } catch (error) {
    message.textContent = '无法读取服务状态';
    message.className = 'status warn';
  }
}

button.addEventListener('click', async () => {
  button.disabled = true;
  message.textContent = '正在保存当前画面……';
  try {
    const response = await fetch('/capture', {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '拍摄失败');
    message.textContent = '已保存，后台识别中：' + data.filename;
    message.className = 'status ok';
    showLast(data);
  } catch (error) {
    message.textContent = error.message;
    message.className = 'status warn';
  } finally {
    button.disabled = false;
  }
});

status();
setInterval(status, 3000);
</script>
</body>
</html>
""".encode("utf-8")


class CameraStream:
    """Continuously drains the camera and keeps the newest JPEG frame."""

    def __init__(
        self,
        device: str,
        width: int,
        height: int,
        jpeg_quality: int,
        preview_fps: float,
        max_frame_age_seconds: float = 3.0,
    ) -> None:
        self.device = device
        self.requested_width = width
        self.requested_height = height
        self.jpeg_quality = jpeg_quality
        self.preview_fps = preview_fps
        self.max_frame_age_seconds = max_frame_age_seconds
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self._width = 0
        self._height = 0
        self._sequence = 0
        self._last_error: str | None = None
        self._frame_monotonic: float | None = None
        self._frame_captured_at: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _set_error(self, message: str) -> None:
        with self._condition:
            self._last_error = message
            self._condition.notify_all()

    def _run(self) -> None:
        try:
            import cv2
        except ImportError:
            self._set_error("未安装 OpenCV，请安装 python3-opencv")
            return

        capture: Any | None = None
        encode_interval = 1.0 / self.preview_fps
        last_encoded = 0.0
        try:
            while not self._stop.is_set():
                if capture is None:
                    capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
                    if not capture.isOpened():
                        capture.release()
                        capture = None
                        self._set_error(f"无法打开摄像头 {self.device}，1 秒后重试")
                        self._stop.wait(1)
                        continue
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    LOG.info("摄像头已打开并保持运行：%s", self.device)

                ok, frame = capture.read()
                if not ok:
                    self._set_error("摄像头读取失败，正在重新连接")
                    capture.release()
                    capture = None
                    self._stop.wait(1)
                    continue

                now = time.monotonic()
                if now - last_encoded < encode_interval:
                    continue
                last_encoded = now
                ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                )
                if not ok:
                    self._set_error("无法将摄像头画面编码为 JPEG")
                    continue

                height, width = frame.shape[:2]
                with self._condition:
                    self._jpeg = encoded.tobytes()
                    self._width = int(width)
                    self._height = int(height)
                    self._sequence += 1
                    self._frame_monotonic = time.monotonic()
                    self._frame_captured_at = datetime.now().astimezone().isoformat(
                        timespec="milliseconds"
                    )
                    self._last_error = None
                    self._condition.notify_all()
        finally:
            if capture is not None:
                capture.release()
            LOG.info("摄像头已关闭")

    def wait_until_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._jpeg is None and time.monotonic() < deadline:
                self._condition.wait(deadline - time.monotonic())
            return self._jpeg is not None

    def current_frame(
        self, max_age_seconds: float | None = None
    ) -> tuple[bytes, int, int, int]:
        with self._condition:
            if self._jpeg is None:
                raise RuntimeError(self._last_error or "摄像头尚未产生画面")
            if self._last_error is not None:
                raise RuntimeError(self._last_error)
            if self._frame_monotonic is None:
                raise RuntimeError("摄像头画面没有有效时间戳")
            maximum_age = (
                self.max_frame_age_seconds
                if max_age_seconds is None
                else max_age_seconds
            )
            age = time.monotonic() - self._frame_monotonic
            if age > maximum_age:
                raise RuntimeError(
                    f"摄像头最新画面已过期（{age:.1f} 秒），拒绝保存旧画面"
                )
            return self._jpeg, self._width, self._height, self._sequence

    def frame_after(self, sequence: int, timeout: float = 2.0) -> tuple[bytes, int]:
        with self._condition:
            updated = self._condition.wait_for(
                lambda: self._sequence > sequence or self._stop.is_set(), timeout=timeout
            )
            if self._jpeg is None:
                raise RuntimeError(self._last_error or "摄像头尚未产生画面")
            if not updated:
                raise RuntimeError(self._last_error or "摄像头画面更新超时")
            if self._last_error is not None:
                raise RuntimeError(self._last_error)
            if self._frame_monotonic is None:
                raise RuntimeError("摄像头画面没有有效时间戳")
            age = time.monotonic() - self._frame_monotonic
            if age > self.max_frame_age_seconds:
                raise RuntimeError(f"摄像头预览画面已过期（{age:.1f} 秒）")
            return self._jpeg, self._sequence

    def status(self) -> dict[str, object]:
        with self._condition:
            frame_age_ms = (
                round((time.monotonic() - self._frame_monotonic) * 1000)
                if self._frame_monotonic is not None
                else None
            )
            fresh = (
                self._frame_monotonic is not None
                and (time.monotonic() - self._frame_monotonic)
                <= self.max_frame_age_seconds
            )
            derived_error = self._last_error
            if self._jpeg is not None and self._last_error is None and not fresh:
                derived_error = (
                    f"摄像头画面超过 {self.max_frame_age_seconds:g} 秒未更新"
                )
            return {
                "ready": self._jpeg is not None and derived_error is None and fresh,
                "width": self._width,
                "height": self._height,
                "sequence": self._sequence,
                "last_frame_at": self._frame_captured_at,
                "frame_age_ms": frame_age_ms,
                "error": derived_error,
            }

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3)


class CaptureStore:
    """Atomically saves JPEG first, then registers and queues recognition."""

    def __init__(
        self,
        output_dir: Path,
        camera: CameraStream,
        repository: CaptureRepository,
        recognition_worker: RecognitionWorker | None,
        recognition_enabled: bool,
        max_frame_age_seconds: float,
    ) -> None:
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.camera = camera
        self.repository = repository
        self.recognition_worker = recognition_worker
        self.recognition_enabled = recognition_enabled
        self.max_frame_age_seconds = max_frame_age_seconds
        self._lock = threading.Lock()
        self._last_capture_id: str | None = None

    def save_current(self, trigger: str) -> dict[str, object]:
        with self._lock:
            jpeg, width, height, _sequence = self.camera.current_frame(
                self.max_frame_age_seconds
            )
            now = datetime.now().astimezone()
            capture_id = self.repository.new_capture_id()
            date_directory = Path(now.strftime("%Y/%m/%d"))
            base = (
                now.strftime("capture_%Y%m%d_%H%M%S_")
                + f"{now.microsecond // 1000:03d}_{capture_id[:8]}"
            )
            relative_path = date_directory / f"{base}.jpg"
            destination = self.output_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)

            temporary = destination.with_suffix(".jpg.part")
            temporary.write_bytes(jpeg)
            temporary.replace(destination)
            try:
                result = self.repository.register_capture(
                    capture_id=capture_id,
                    captured_at=now.isoformat(timespec="milliseconds"),
                    trigger=trigger,
                    image_relpath=str(relative_path),
                    image_sha256=hashlib.sha256(jpeg).hexdigest(),
                    width=width,
                    height=height,
                    byte_size=len(jpeg),
                    camera_device=self.camera.device,
                    recognition_enabled=self.recognition_enabled,
                )
            except sqlite3.Error:
                quarantine = self.output_dir / "quarantine" / destination.name
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                try:
                    destination.replace(quarantine)
                except OSError:
                    LOG.exception("数据库登记失败，且照片无法移入隔离目录：%s", destination)
                else:
                    LOG.exception("数据库登记失败；照片已移入隔离目录：%s", quarantine)
                raise
            self._last_capture_id = capture_id
            if self.recognition_worker is not None:
                self.recognition_worker.submit(capture_id)
            LOG.info(
                "已保存照片（%s）：%s，ID=%s，%dx%d，%d bytes",
                trigger,
                destination,
                capture_id,
                width,
                height,
                len(jpeg),
            )
            return dict(result)

    def last_capture(self) -> dict[str, object] | None:
        with self._lock:
            capture_id = self._last_capture_id
        return self.repository.get(capture_id, include_raw_text=False) if capture_id else self.repository.latest()


class GpioButton:
    """libgpiod 1.x edge reader supporting global and chip-local numbers."""

    def __init__(
        self,
        line_name: str,
        gpio_number: int,
        gpio_chip: str | None,
        gpio_offset: int | None,
        active_low: bool,
    ) -> None:
        self.line_name = line_name
        self.gpio_number = gpio_number
        self.gpio_chip = gpio_chip
        self.gpio_offset = gpio_offset
        self.active_low = active_low
        self.chip: Any | None = None
        self.line: Any | None = None
        self.description = f"GPIO {gpio_number}"

    @staticmethod
    def _device_node(chip_directory: Path) -> str | None:
        """Map a sysfs gpiochip directory to its /dev/gpiochipN node."""
        for uevent_path in (chip_directory / "uevent", chip_directory / "device" / "uevent"):
            try:
                fields = dict(
                    line.split("=", 1)
                    for line in uevent_path.read_text().splitlines()
                    if "=" in line
                )
            except OSError:
                continue
            devname = fields.get("DEVNAME")
            if devname and Path("/dev", devname).exists():
                return str(Path("/dev", devname))

        # Kernel versions differ in how the sysfs chip is named.  Matching the
        # device major/minor numbers is reliable when DEVNAME is absent.
        try:
            expected_device = (chip_directory / "dev").read_text().strip()
        except OSError:
            expected_device = ""
        if expected_device:
            for candidate in sorted(glob.glob("/dev/gpiochip*")):
                try:
                    stat_result = os.stat(candidate)
                except OSError:
                    continue
                actual_device = f"{os.major(stat_result.st_rdev)}:{os.minor(stat_result.st_rdev)}"
                if actual_device == expected_device:
                    return candidate

        same_name = Path("/dev") / chip_directory.name
        return str(same_name) if same_name.exists() else None

    @classmethod
    def _resolve_global_gpio(cls, gpio_number: int) -> tuple[str, int]:
        """Resolve legacy/global GPIO 356 to a character device and offset."""
        for raw_path in sorted(glob.glob("/sys/class/gpio/gpiochip*")):
            chip_directory = Path(raw_path)
            try:
                base = int((chip_directory / "base").read_text().strip())
                line_count = int((chip_directory / "ngpio").read_text().strip())
            except (OSError, ValueError):
                continue
            if base <= gpio_number < base + line_count:
                device_node = cls._device_node(chip_directory)
                if device_node is None:
                    break
                return device_node, gpio_number - base
        raise RuntimeError(
            f"无法自动映射全局 GPIO {gpio_number}；"
            "请用 --gpio-chip 和 --gpio-offset 明确指定"
        )

    def open(self) -> None:
        try:
            import gpiod
        except ImportError as error:
            raise RuntimeError("未安装 python3-libgpiod") from error
        if not hasattr(gpiod, "LINE_REQ_EV_FALLING_EDGE"):
            raise RuntimeError("需要 python3-libgpiod 1.x，当前 API 版本不兼容")

        if self.gpio_chip is not None:
            if self.gpio_offset is None:
                raise RuntimeError("使用 --gpio-chip 时必须同时指定 --gpio-offset")
            chip_path = self.gpio_chip
            offset = self.gpio_offset
            try:
                chip = gpiod.Chip(chip_path)
            except PermissionError as error:
                raise PermissionError(
                    f"没有 {chip_path} 权限；网页按钮仍可使用"
                ) from error
            if not 0 <= offset < chip.num_lines():
                chip.close()
                raise RuntimeError(f"{chip_path} 没有 offset {offset}")
            self.chip = chip
            self.line = chip.get_line(offset)
            self.description = f"{chip_path} offset {offset}"
        else:
            resolution_error: RuntimeError | None = None
            try:
                chip_path, offset = self._resolve_global_gpio(self.gpio_number)
                try:
                    chip = gpiod.Chip(chip_path)
                except PermissionError as error:
                    raise PermissionError(
                        f"没有 {chip_path} 权限；网页按钮仍可使用"
                    ) from error
                self.chip = chip
                self.line = chip.get_line(offset)
                self.description = f"GPIO {self.gpio_number}（{chip_path} offset {offset}）"
            except RuntimeError as error:
                resolution_error = error

            # Older device trees sometimes expose PL4 by name but do not
            # publish legacy/global GPIO bases.  Keep name lookup as fallback.
            if self.line is None:
                permission_denied = False
                for chip_path in sorted(glob.glob("/dev/gpiochip*")):
                    try:
                        chip = gpiod.Chip(chip_path)
                    except PermissionError:
                        permission_denied = True
                        continue
                    line = chip.find_line(self.line_name)
                    if line is not None:
                        self.chip = chip
                        self.line = line
                        self.description = f"{self.line_name}（{chip_path}）"
                        break
                    chip.close()

                if self.line is None:
                    if permission_denied:
                        raise PermissionError(
                            "没有 /dev/gpiochip* 权限；网页按钮仍可使用"
                        )
                    if resolution_error is not None:
                        raise resolution_error
                    raise RuntimeError(
                        f"找不到 GPIO {self.gpio_number} 或线路名 {self.line_name}"
                    )

        edge = (
            gpiod.LINE_REQ_EV_FALLING_EDGE
            if self.active_low
            else gpiod.LINE_REQ_EV_RISING_EDGE
        )
        flags = (
            getattr(gpiod, "LINE_REQ_FLAG_BIAS_PULL_UP", 0)
            if self.active_low
            else 0
        )
        try:
            self.line.request(consumer="camera-capture", type=edge, flags=flags)
        except OSError as error:
            if flags == 0:
                raise
            LOG.warning("GPIO 不支持内部上拉，改用按钮模块自身电平：%s", error)
            self.line.request(consumer="camera-capture", type=edge)

    def wait_for_press(self, timeout_seconds: float) -> bool:
        assert self.line is not None
        if not self.line.event_wait(sec=timeout_seconds):
            return False
        self.line.event_read()
        return True

    def close(self) -> None:
        if self.line is not None:
            self.line.release()
            self.line = None
        if self.chip is not None:
            self.chip.close()
            self.chip = None


class ButtonMonitor:
    """Best-effort physical button worker; failures never stop the web UI."""

    def __init__(
        self,
        button: GpioButton,
        store: CaptureStore,
        stop: threading.Event,
        debounce_ms: int,
    ) -> None:
        self.button = button
        self.store = store
        self.stop = stop
        self.debounce_seconds = debounce_ms / 1000
        self._lock = threading.Lock()
        self._available = False
        self._message = "正在连接"
        self._thread = threading.Thread(target=self._run, name="gpio-button", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _set_status(self, available: bool, message: str) -> None:
        with self._lock:
            self._available = available
            self._message = message

    def _run(self) -> None:
        try:
            self.button.open()
            self._set_status(True, f"已连接 {self.button.description}，可以按下拍照")
            LOG.info("实体按钮已监听：%s", self.button.description)
            last_press = 0.0
            while not self.stop.is_set():
                if not self.button.wait_for_press(1):
                    continue
                now = time.monotonic()
                if now - last_press < self.debounce_seconds:
                    continue
                last_press = now
                try:
                    self.store.save_current("实体按钮")
                except (OSError, RuntimeError, sqlite3.Error) as error:
                    LOG.error("实体按钮拍摄失败：%s", error)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self._set_status(False, str(error))
            LOG.warning("实体按钮不可用：%s", error)
        finally:
            self.button.close()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {"available": self._available, "message": self._message}

    def join(self) -> None:
        self._thread.join(timeout=2)


def build_handler(
    camera: CameraStream,
    store: CaptureStore,
    repository: CaptureRepository,
    recognition_worker: RecognitionWorker | None,
    gpio_status: Callable[[], dict[str, object]],
) -> type[BaseHTTPRequestHandler]:
    class CameraHandler(BaseHTTPRequestHandler):
        server_version = "CameraCapture/3.0"

        def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            self._send_bytes(
                status,
                "application/json; charset=utf-8",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            request = urlsplit(self.path)
            path = request.path
            if path.startswith("/api/v1/"):
                path = "/api/" + path.removeprefix("/api/v1/")
            if path == "/":
                self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", PAGE_HTML)
                return
            if path == "/api/status":
                recognition_status = (
                    {"enabled": True, **recognition_worker.status()}
                    if recognition_worker is not None
                    else {
                        "enabled": False,
                        "available": False,
                        "recognizer": None,
                        "languages": "",
                        "warning": None,
                        "current_capture_id": None,
                        "queued": 0,
                    }
                )
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "camera": camera.status(),
                        "gpio": gpio_status(),
                        "recognition": recognition_status,
                        "counts": repository.counts(),
                        "last_capture": store.last_capture(),
                    },
                )
                return
            if path == "/api/latest":
                latest = repository.latest(include_raw_text=True)
                if latest is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "尚无拍摄记录"})
                else:
                    self._send_json(HTTPStatus.OK, latest)
                return
            if path == "/api/captures":
                query = parse_qs(request.query)
                try:
                    limit = max(1, min(int(query.get("limit", ["50"])[0]), 200))
                    offset = max(0, int(query.get("offset", ["0"])[0]))
                except ValueError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "limit 或 offset 无效"})
                    return
                items = repository.list(
                    limit=limit,
                    offset=offset,
                    status=query.get("status", [None])[0],
                    document_type=query.get("type", [None])[0],
                )
                self._send_json(
                    HTTPStatus.OK,
                    {"items": items, "limit": limit, "offset": offset, "count": len(items)},
                )
                return
            if path.startswith("/api/captures/"):
                capture_id = unquote(path.removeprefix("/api/captures/")).strip("/")
                record = repository.get(capture_id, include_raw_text=True)
                if record is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "拍摄记录不存在"})
                else:
                    self._send_json(HTTPStatus.OK, record)
                return
            if path == "/stream.mjpg":
                self._stream_mjpeg()
                return
            if path.startswith("/captures/"):
                self._serve_capture(unquote(path.removeprefix("/captures/")))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path.startswith("/api/v1/"):
                path = "/api/" + path.removeprefix("/api/v1/")
            if path in {"/capture", "/api/capture"}:
                try:
                    result = store.save_current("网页按钮")
                except (OSError, RuntimeError, sqlite3.Error) as error:
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
                    return
                self._send_json(HTTPStatus.CREATED, result)
                return
            if path.startswith("/api/captures/") and path.endswith("/retry"):
                capture_id = unquote(path.removeprefix("/api/captures/").removesuffix("/retry")).strip("/")
                if recognition_worker is None:
                    self._send_json(HTTPStatus.CONFLICT, {"error": "识别功能已停用"})
                    return
                if not recognition_worker.retry(capture_id):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "记录不存在或当前不可重试"})
                    return
                record = repository.get(capture_id, include_raw_text=False)
                assert record is not None
                self._send_json(HTTPStatus.ACCEPTED, record)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})

        def _stream_mjpeg(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            sequence = -1
            try:
                while True:
                    jpeg, sequence = camera.frame_after(sequence)
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                return

        def _serve_capture(self, identifier: str) -> None:
            capture_id = identifier.removesuffix(".jpg").strip("/")
            if not capture_id or "/" in capture_id or "\\" in capture_id:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "拍摄编号无效"})
                return
            path = repository.image_path(capture_id)
            if path is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "照片不存在"})
                return
            try:
                body = path.read_bytes()
            except FileNotFoundError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "照片不存在"})
                return
            self._send_bytes(HTTPStatus.OK, "image/jpeg", body)

        def log_message(self, format_string: str, *args: object) -> None:
            LOG.debug("网页 %s - %s", self.client_address[0], format_string % args)

    return CameraHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="常开摄像头、按钮拍照、OCR 与结构化归档")
    parser.add_argument("--device", default="/dev/video0", help="USB 摄像头设备")
    parser.add_argument("--output-dir", type=Path, default=Path("captures"), help="JPEG 保存目录")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/capture_catalog.sqlite3"),
        help="结构化记录 SQLite 文件",
    )
    parser.add_argument(
        "--no-ocr",
        "--no-recognition",
        dest="no_recognition",
        action="store_true",
        help="保存照片但不进行识别",
    )
    parser.add_argument("--ocr-languages", default="chi_sim+eng", help="Tesseract 语言组合")
    parser.add_argument("--ocr-timeout", type=int, default=45, help="单张 OCR 超时秒数")
    parser.add_argument("--ocr-page-mode", type=int, default=6, help="Tesseract 页面布局模式")
    parser.add_argument("--gpio-number", type=int, default=356, help="按钮 D 的全局 GPIO 编号")
    parser.add_argument("--gpio-line", default="PL4", help="全局编号无法映射时使用的线路名")
    # Confirmed on this Orange Pi 4 Pro: physical pin 7 / GPIO 356 is the
    # fourth line of the second pin controller (352 + 4 = 356).
    parser.add_argument("--gpio-chip", default="/dev/gpiochip1", help="按钮所在 GPIO 芯片")
    parser.add_argument("--gpio-offset", type=int, default=4, help="芯片内按钮线路偏移")
    parser.add_argument("--no-gpio", action="store_true", help="完全停用实体按钮")
    parser.add_argument("--active-high", action="store_true", help="按钮按下时 D 输出高电平")
    parser.add_argument("--width", type=int, default=1920, help="请求画面宽度")
    parser.add_argument("--height", type=int, default=1080, help="请求画面高度")
    parser.add_argument("--jpeg-quality", type=int, default=90, choices=range(1, 101), metavar="1-100")
    parser.add_argument("--preview-fps", type=float, default=15, help="网页预览最大帧率")
    parser.add_argument(
        "--max-frame-age",
        type=float,
        default=3.0,
        help="拍照允许使用的最新画面最大年龄（秒）",
    )
    parser.add_argument("--debounce-ms", type=int, default=250, help="实体按钮去抖时间")
    parser.add_argument("--host", default="0.0.0.0", help="网页监听地址")
    parser.add_argument("--port", type=int, default=8000, help="网页端口")
    parser.add_argument("--capture-once", action="store_true", help="保存一张到目录后退出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("宽度和高度必须大于 0")
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在 1 到 65535 之间")
    if not 0 < args.preview_fps <= 60:
        raise SystemExit("preview-fps 必须大于 0 且不超过 60")
    if args.max_frame_age <= 0:
        raise SystemExit("max-frame-age 必须大于 0")
    if args.debounce_ms < 0:
        raise SystemExit("debounce-ms 不能小于 0")
    if args.ocr_timeout <= 0:
        raise SystemExit("ocr-timeout 必须大于 0")
    if not 0 <= args.ocr_page_mode <= 13:
        raise SystemExit("ocr-page-mode 必须在 0 到 13 之间")
    if args.gpio_number < 0:
        raise SystemExit("gpio-number 不能小于 0")
    if (args.gpio_chip is None) != (args.gpio_offset is None):
        raise SystemExit("gpio-chip 和 gpio-offset 必须同时指定")

    stop = threading.Event()
    camera = CameraStream(
        args.device,
        args.width,
        args.height,
        args.jpeg_quality,
        args.preview_fps,
        args.max_frame_age,
    )
    repository = CaptureRepository(args.database, args.output_dir)
    recognizer = TesseractRecognizer(
        args.ocr_languages,
        args.ocr_timeout,
        args.ocr_page_mode,
    )
    recognition_worker: RecognitionWorker | None = None
    if not args.no_recognition:
        recognition_worker = RecognitionWorker(repository, recognizer, stop)
        recognition_worker.start()
    store = CaptureStore(
        args.output_dir,
        camera,
        repository,
        recognition_worker,
        recognition_enabled=not args.no_recognition,
        max_frame_age_seconds=args.max_frame_age,
    )
    server: ThreadingHTTPServer | None = None
    button_monitor: ButtonMonitor | None = None

    def request_stop(_signal: int, _frame: Any) -> None:
        stop.set()
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    camera.start()

    try:
        if not camera.wait_until_ready(15):
            error = camera.status().get("error") or "15 秒内没有取得摄像头画面"
            raise RuntimeError(str(error))

        if args.capture_once:
            result = store.save_current("命令行测试")
            if recognition_worker is not None:
                final_record = recognition_worker.wait_for(
                    str(result["id"]), timeout=args.ocr_timeout + 5
                )
                status = (
                    final_record.get("recognition", {}).get("status")
                    if isinstance(final_record, dict)
                    else "unknown"
                )
                LOG.info("单张识别结束：%s", status)
            return 0

        if args.no_gpio:
            gpio_status = lambda: {"available": False, "message": "已通过 --no-gpio 停用"}
        else:
            button_monitor = ButtonMonitor(
                GpioButton(
                    args.gpio_line,
                    args.gpio_number,
                    args.gpio_chip,
                    args.gpio_offset,
                    active_low=not args.active_high,
                ),
                store,
                stop,
                args.debounce_ms,
            )
            button_monitor.start()
            gpio_status = button_monitor.status

        handler = build_handler(
            camera,
            store,
            repository,
            recognition_worker,
            gpio_status,
        )
        server = ThreadingHTTPServer((args.host, args.port), handler)
        server.daemon_threads = True
        LOG.info("网页已启动：http://%s:%d", args.host, args.port)
        LOG.info("照片保存目录：%s", args.output_dir.resolve())
        LOG.info("结构化数据库：%s", args.database.resolve())
        if recognition_worker is not None:
            LOG.info("识别器状态：%s", recognition_worker.status())
        server.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        if server is not None:
            server.server_close()
        if button_monitor is not None:
            button_monitor.join()
        if recognition_worker is not None:
            recognition_worker.join()
        camera.stop()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, sqlite3.Error) as error:
        LOG.error("启动失败：%s", error)
        raise SystemExit(1)
