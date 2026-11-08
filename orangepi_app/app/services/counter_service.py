from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections import defaultdict, deque
from typing import Any, Iterator

import numpy as np

from app.config import (
    CAMERA_DEVICE,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_JPEG_QUALITY,
    CAMERA_WIDTH,
    COUNTER_CONFIDENCE,
    COUNTER_ENABLED,
    COUNTER_IMGSZ,
    COUNTER_MODEL,
    STORAGE_DIR,
)
from app.database.connection import database
from app.database.repositories import counter_repository

try:
    import cv2
except ImportError:  # 开发机上无摄像头依赖时保持可导入
    cv2 = None  # type: ignore[assignment]

# 计数线持久化文件（方向翻转等设置在服务重启后保留）
LINE_FILE = STORAGE_DIR / "counter_line.json"

TRAIL_LEN = 40          # 轨迹保留点数
HYSTERESIS = 6.0         # 距线小于该像素数视为“在线上”，防止抖动重复计数
TRACK_TIMEOUT = 60       # 连续 N 帧未见则删除轨迹
EXCLUDE_CLASSES = {"person"}  # 递送物品的手/人不参与计数

# 默认计数线：画面中央垂直线（上→下），A→B 左侧为 +1 侧
DEFAULT_LINE = (0.5, 0.15, 0.5, 0.85)

CLASS_ZH = {
    "person": "人", "bicycle": "自行车", "car": "汽车", "motorcycle": "摩托车",
    "airplane": "飞机", "bus": "公交车", "train": "火车", "truck": "卡车",
    "boat": "船", "traffic light": "红绿灯", "fire hydrant": "消防栓",
    "stop sign": "停车标志", "bench": "长椅", "bird": "鸟", "cat": "猫",
    "dog": "狗", "horse": "马", "sheep": "羊", "cow": "牛", "elephant": "大象",
    "bear": "熊", "zebra": "斑马", "giraffe": "长颈鹿", "backpack": "背包",
    "umbrella": "雨伞", "handbag": "手提包", "tie": "领带", "suitcase": "行李箱",
    "frisbee": "飞盘", "sports ball": "球", "kite": "风筝", "baseball bat": "棒球棒",
    "skateboard": "滑板", "surfboard": "冲浪板", "tennis racket": "网球拍",
    "bottle": "瓶子", "wine glass": "酒杯", "cup": "杯子", "fork": "叉子",
    "knife": "刀", "spoon": "勺子", "bowl": "碗", "banana": "香蕉",
    "apple": "苹果", "sandwich": "三明治", "orange": "橙子", "broccoli": "西兰花",
    "carrot": "胡萝卜", "hot dog": "热狗", "pizza": "披萨", "donut": "甜甜圈",
    "cake": "蛋糕", "chair": "椅子", "couch": "沙发", "potted plant": "盆栽",
    "bed": "床", "dining table": "餐桌", "toilet": "马桶", "tv": "显示器",
    "laptop": "笔记本电脑", "mouse": "鼠标", "remote": "遥控器",
    "keyboard": "键盘", "cell phone": "手机", "microwave": "微波炉",
    "oven": "烤箱", "sink": "水槽", "refrigerator": "冰箱", "book": "书",
    "clock": "时钟", "vase": "花瓶", "scissors": "剪刀", "teddy bear": "玩具熊",
    "hair drier": "吹风机", "toothbrush": "牙刷",
}

PALETTE = [
    (60, 200, 60), (60, 160, 255), (200, 120, 60), (180, 60, 200),
    (60, 220, 220), (0, 140, 255), (255, 0, 140), (140, 255, 0),
    (255, 140, 0), (0, 200, 255),
]


def zh_name(name: str) -> str:
    return CLASS_ZH.get(name, name)


def draw_dashed(img, p1, p2, color, thickness=2, dash=18, gap=12):
    x1, y1 = p1
    x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 1:
        return
    ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
    t = 0.0
    while t < dist:
        t2 = min(t + dash, dist)
        cv2.line(img, (int(x1 + ux * t), int(y1 + uy * t)),
                 (int(x1 + ux * t2), int(y1 + uy * t2)), color, thickness)
        t = t2 + gap


class CounterService:
    """物品进出自动计数服务：独占摄像头运行 YOLO + ByteTrack 方向线计数。

    与 CameraService 共用同一颗 USB 摄像头，二者互斥运行：
    本服务运行时 CameraService 必须处于停止状态，反之亦然。
    """

    def __init__(self) -> None:
        self.device = CAMERA_DEVICE
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        self.jpeg_quality = max(40, min(CAMERA_JPEG_QUALITY, 95))
        self.enabled = COUNTER_ENABLED
        self.model_path = COUNTER_MODEL
        self.imgsz = COUNTER_IMGSZ
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._line_lock = threading.Lock()
        self.jpeg: bytes | None = None
        self.seq = 0
        self.frame_w, self.frame_h = self.width, self.height
        self.counts: dict[str, int] = defaultdict(int)
        self.events: deque[dict[str, Any]] = deque(maxlen=100)
        self.line: tuple[float, float, float, float] | None = self._load_line()
        self.line_epoch = 0
        self.conf = COUNTER_CONFIDENCE
        self.status_text = "未启动"
        self.inference_fps = 0.0
        self.n_tracks = 0
        self.error: str | None = None
        self._load_initial_counts()

    # ---------------- 生命周期 ----------------

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if not self.enabled:
            self.status_text = "计数功能已通过配置关闭"
            return
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, name="yolo-counter", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._release_capture()
        if not self.running:
            self.status_text = "计数已暂停（摄像头释放）"

    def _open_capture(self):
        if cv2 is None:
            self._set_status("未安装 OpenCV（cv2），计数功能不可用", error=True)
            return None
        if sys.platform == "darwin":
            backend = cv2.CAP_AVFOUNDATION
        elif sys.platform.startswith("linux"):
            backend = cv2.CAP_V4L2
        else:
            backend = cv2.CAP_ANY
        source: int | str = int(self.device) if self.device.isdigit() else self.device
        capture = cv2.VideoCapture(source, backend)
        if not capture.isOpened():
            capture.release()
            self._set_status(f"无法打开摄像头 {self.device}（可能被手动拍照功能占用）", error=True)
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

    # ---------------- 持久化 ----------------

    def _load_line(self) -> tuple[float, float, float, float] | None:
        try:
            data = json.loads(LINE_FILE.read_text(encoding="utf-8"))
            line = tuple(float(v) for v in data["line"])
            if len(line) == 4:
                return line  # type: ignore[return-value]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return DEFAULT_LINE

    def _save_line(self) -> None:
        try:
            LINE_FILE.write_text(
                json.dumps({"line": self.line}), encoding="utf-8"
            )
        except OSError:
            pass

    def _load_initial_counts(self) -> None:
        """服务启动时从数据库加载累计净计数，保证重启后统计延续。"""
        try:
            with database() as connection:
                counts = counter_repository.load_counts(connection)
                events = counter_repository.list_events(connection, limit=30)
            self.counts = defaultdict(int, counts)
            self.events.extend(reversed(events))
        except Exception as exc:
            self.error = f"加载历史计数失败：{exc}"

    def _persist_event(self, cls: str, delta: int) -> None:
        try:
            with database() as connection:
                counter_repository.record_event(connection, cls, delta)
        except Exception as exc:
            print(f"[counter] 计数事件写库失败：{exc}", flush=True)

    # ---------------- 工作线程 ----------------

    def _worker(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            self._set_status(f"未安装 ultralytics，无法计数：{exc}", error=True)
            return
        try:
            model = YOLO(self.model_path)
        except Exception as exc:
            self._set_status(f"计数模型加载失败（{self.model_path}）：{exc}", error=True)
            return

        device = "cpu"
        self._set_status("模型已加载，正在预热")
        try:
            model.predict(
                np.zeros((self.height, self.width, 3), "uint8"),
                device=device, verbose=False, imgsz=self.imgsz,
            )
        except Exception:
            pass

        tracks: dict[int, dict[str, Any]] = {}
        frame_no = 0
        fps_t = time.time()

        while not self._stop_event.is_set():
            capture = self._open_capture()
            if capture is None:
                self._stop_event.wait(3)
                continue
            self._set_status(f"摄像头 {self.device} 计数运行中")
            with self._condition:
                self.frame_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.width
                self.frame_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.height

            while not self._stop_event.is_set():
                ret, frame = capture.read()
                if not ret or frame is None:
                    self._stop_event.wait(0.3)
                    continue
                frame_no += 1
                try:
                    results = model.track(
                        frame, persist=True, tracker="bytetrack.yaml",
                        conf=self.conf, imgsz=self.imgsz, device=device,
                        verbose=False,
                    )
                except Exception as exc:
                    self._set_status(f"推理失败：{exc}", error=True)
                    self._stop_event.wait(1)
                    continue
                r = results[0]
                now_str = time.strftime("%H:%M:%S")

                with self._line_lock:
                    line_norm = self.line
                    line_epoch = self.line_epoch

                gate = None
                if line_norm is not None:
                    H, W = frame.shape[:2]
                    ax, ay = line_norm[0] * W, line_norm[1] * H
                    bx, by = line_norm[2] * W, line_norm[3] * H
                    dx, dy = bx - ax, by - ay
                    L = math.hypot(dx, dy)
                    if L > 10:
                        ux, uy = dx / L, dy / L
                        nx, ny = -uy, ux  # 左法线 = +1 侧
                        gate = (ax, ay, bx, by, ux, uy, nx, ny)

                seen_ids = set()
                if r.boxes is not None and r.boxes.id is not None:
                    boxes = r.boxes.xyxy.cpu().numpy()
                    ids = r.boxes.id.int().cpu().numpy()
                    clss = r.boxes.cls.int().cpu().numpy()
                    names = model.names

                    for (x1, y1, x2, y2), tid, cid in zip(boxes, ids, clss):
                        tid = int(tid)
                        if names[cid] in EXCLUDE_CLASSES:
                            continue
                        seen_ids.add(tid)
                        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                        t = tracks.get(tid)
                        if t is None:
                            t = {"cls": names[cid], "trail": deque(maxlen=TRAIL_LEN),
                                 "side": 0, "last_seen": frame_no, "line_epoch": -1}
                            tracks[tid] = t
                        t["last_seen"] = frame_no
                        t["trail"].append((cx, cy))

                        # ---- 方向计数 ----
                        if gate is not None:
                            g_ax, g_ay, _, _, _, _, nx, ny = gate
                            proj = (cx - g_ax) * nx + (cy - g_ay) * ny
                            side = 1 if proj > HYSTERESIS else (-1 if proj < -HYSTERESIS else 0)
                            if t["line_epoch"] != line_epoch:
                                t["side"] = side if side != 0 else t["side"]
                                t["line_epoch"] = line_epoch
                            elif side != 0 and side != t["side"] and t["side"] != 0:
                                delta = 1 if side > t["side"] else -1
                                cls_name = t["cls"]
                                with self._condition:
                                    self.counts[cls_name] += delta
                                    self.events.append(
                                        {"t": now_str, "cls": cls_name, "delta": delta}
                                    )
                                self._persist_event(cls_name, delta)
                                t["side"] = side
                            elif side != 0:
                                t["side"] = side

                        # ---- 绘制 ----
                        color = PALETTE[cid % len(PALETTE)]
                        ix1, iy1, ix2, iy2 = int(x1), int(y1), int(x2), int(y2)
                        cv2.rectangle(frame, (ix1, iy1), (ix2, iy2), color, 2)
                        label = f"{zh_name(t['cls'])} #{tid}"
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                        ty = max(iy1, th + 6)
                        cv2.rectangle(frame, (ix1, ty - th - 6), (ix1 + tw + 4, ty), color, -1)
                        cv2.putText(frame, label, (ix1 + 2, ty - 4),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                        if len(t["trail"]) > 1:
                            pts = np.array(t["trail"], np.int32).reshape(-1, 1, 2)
                            cv2.polylines(frame, [pts], False, (255, 220, 80), 2, cv2.LINE_AA)
                    self.n_tracks = len(seen_ids)
                else:
                    self.n_tracks = 0

                stale = [k for k, v in tracks.items() if frame_no - v["last_seen"] > TRACK_TIMEOUT]
                for k in stale:
                    del tracks[k]

                # ---- 绘制计数线与正方向箭头 ----
                if gate is not None:
                    g_ax, g_ay, bx, by, ux, uy, nx, ny = gate
                    far = 2000.0
                    draw_dashed(frame, (g_ax - ux * far, g_ay - uy * far),
                                (g_ax + ux * far, g_ay + uy * far), (0, 140, 255), 2)
                    cv2.line(frame, (int(g_ax), int(g_ay)), (int(bx), int(by)), (0, 140, 255), 3)
                    mx, my = (g_ax + bx) / 2, (g_ay + by) / 2
                    tip = (int(mx + nx * 70), int(my + ny * 70))
                    cv2.arrowedLine(frame, (int(mx), int(my)), tip, (0, 255, 255), 4,
                                    tipLength=0.3, line_type=cv2.LINE_AA)
                    cv2.putText(frame, "+1", (int(tip[0] + nx * 10), int(tip[1] + ny * 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 3, cv2.LINE_AA)
                else:
                    cv2.putText(frame, "counting line cleared",
                                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                now = time.time()
                inst = 1.0 / max(now - fps_t, 1e-6)
                self.inference_fps = self.inference_fps * 0.9 + inst * 0.1 if self.inference_fps else inst
                fps_t = now
                cv2.putText(frame, f"FPS:{self.inference_fps:4.1f}  Tracks:{self.n_tracks}",
                            (12, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (255, 255, 255), 2)

                ok, buf = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
                )
                if ok:
                    with self._condition:
                        self.jpeg = buf.tobytes()
                        self.seq += 1
                        self._condition.notify_all()

            self._release_capture()

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_text = text
        self.error = text if error else None

    # ---------------- 外部接口 ----------------

    def mjpeg_frames(self) -> Iterator[bytes]:
        last_seq = -1
        while not self._stop_event.is_set() and self.running:
            with self._condition:
                self._condition.wait_for(
                    lambda: self.seq != last_seq or self._stop_event.is_set(), timeout=5
                )
                if self._stop_event.is_set() or not self.running:
                    return
                data, last_seq = self.jpeg, self.seq
            if data is None:
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + data + b"\r\n"

    def state(self, paused: bool = False) -> dict[str, Any]:
        with self._condition:
            counts = {
                zh_name(cls): net
                for cls, net in sorted(self.counts.items(), key=lambda kv: -abs(kv[1]))
            }
            events = [
                {"t": ev["t"], "cls": zh_name(ev["cls"]), "delta": ev["delta"]}
                for ev in list(self.events)[-30:][::-1]
            ]
        return {
            "enabled": self.enabled,
            "running": self.running,
            "paused": paused or not self.running,
            "status": self.status_text,
            "error": self.error,
            "device": self.device,
            "fps": round(self.inference_fps, 1),
            "n_tracks": self.n_tracks,
            "line_set": self.line is not None,
            "conf": self.conf,
            "counts": counts,
            "events": events,
        }

    def set_line(self, ax: float, ay: float, bx: float, by: float) -> None:
        with self._line_lock:
            self.line = (ax, ay, bx, by)
            self.line_epoch += 1
            self._save_line()

    def flip_line(self) -> None:
        with self._line_lock:
            if self.line is not None:
                ax, ay, bx, by = self.line
                self.line = (bx, by, ax, ay)
                self.line_epoch += 1
                self._save_line()

    def clear_line(self) -> None:
        with self._line_lock:
            self.line = None
            self.line_epoch += 1
            self._save_line()

    def set_conf(self, value: float) -> float:
        self.conf = min(0.9, max(0.05, value))
        return self.conf

    def reset(self) -> None:
        with self._condition:
            self.counts.clear()
            self.events.clear()
        try:
            with database() as connection:
                counter_repository.record_reset(connection)
        except Exception as exc:
            print(f"[counter] 写入清零标记失败：{exc}", flush=True)


counter_service = CounterService()
