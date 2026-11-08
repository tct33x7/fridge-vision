from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import threading
import time
from collections.abc import Callable

from app.config import (
    GPIO_BUTTON_ACTIVE_LOW,
    GPIO_BUTTON_DEBOUNCE_MS,
    GPIO_BUTTON_ENABLED,
    GPIO_BUTTON_WPI_PIN,
)


class GPIOButtonMonitor:
    """Monitor an Orange Pi wiringOP pin without requiring a Python GPIO package."""

    INPUT = 0
    PUD_UP = 2
    PUD_DOWN = 1

    def __init__(self, on_press: Callable[[], None]) -> None:
        self.pin = GPIO_BUTTON_WPI_PIN
        self.active_low = GPIO_BUTTON_ACTIVE_LOW
        self.debounce_seconds = max(GPIO_BUTTON_DEBOUNCE_MS, 50) / 1000
        self.enabled = GPIO_BUTTON_ENABLED
        self._on_press = on_press
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._library = None
        self._ready = False
        self._error: str | None = None

    def start(self) -> None:
        if not self.enabled:
            self._error = "GPIO 按钮已通过配置关闭"
            return
        if not sys.platform.startswith("linux"):
            self._error = "GPIO 按钮仅在 Orange Pi Linux 上启用"
            return
        if self._thread and self._thread.is_alive():
            return
        # 预检查：wiringPi 在无法访问 /dev/gpiomem 或 /dev/mem 时会调用 abort()，
        # 直接杀掉整个进程。先检查权限，避免崩溃。
        gpiomem_ok = os.path.exists("/dev/gpiomem") and os.access("/dev/gpiomem", os.R_OK | os.W_OK)
        mem_ok = os.access("/dev/mem", os.R_OK | os.W_OK)
        if not gpiomem_ok and not mem_ok:
            self._error = "GPIO 按钮需要 root 权限访问 /dev/mem 或 /dev/gpiomem。请使用 sudo 运行或创建 /dev/gpiomem 设备。"
            return
        try:
            library_name = ctypes.util.find_library("wiringPi") or "libwiringPi.so"
            self._library = ctypes.CDLL(library_name)
            self._library.wiringPiSetup.restype = ctypes.c_int
            if self._library.wiringPiSetup() < 0:
                raise RuntimeError("wiringPiSetup 初始化失败")
            self._library.pinMode(self.pin, self.INPUT)
            self._library.pullUpDnControl(self.pin, self.PUD_UP if self.active_low else self.PUD_DOWN)
        except (OSError, AttributeError, RuntimeError) as exc:
            self._library = None
            self._error = f"无法初始化 wiringOP：{exc}"
            return

        self._ready = True
        self._error = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="gpio-capture-button", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._ready = False

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "ready": self._ready,
            "physical_pin": 7,
            "signal": "PL4",
            "wpi_pin": self.pin,
            "active_low": self.active_low,
            "error": self._error,
        }

    def _poll_loop(self) -> None:
        assert self._library is not None
        last_pressed = False
        last_triggered_at = 0.0
        while not self._stop_event.is_set():
            try:
                value = int(self._library.digitalRead(self.pin))
                pressed = value == 0 if self.active_low else value == 1
                now = time.monotonic()
                if pressed and not last_pressed and now - last_triggered_at >= self.debounce_seconds:
                    last_triggered_at = now
                    self._on_press()
                last_pressed = pressed
            except Exception as exc:
                self._error = f"GPIO 读取失败：{exc}"
                self._ready = False
                return
            self._stop_event.wait(0.03)
