from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import replace
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
    COUNTER_ENGINE,
    COUNTER_IMGSZ,
    COUNTER_MODEL,
    COUNTER_NPU_MODEL,
    COUNTER_PRESET,
    DOOR_MAX_ACTIVE_SECONDS,
    DOOR_ROI,
    DOOR_SLEEP_RATIO,
    DOOR_SLEEP_SECONDS,
    DOOR_STANDBY_ENABLED,
    DOOR_WAKE_BRIGHTNESS,
    DOOR_WAKE_HITS,
    DOOR_WAKE_RATIO,
    STORAGE_DIR,
)
from app.database.connection import database
from app.database.repositories import counter_repository
from app.services.door_watcher import DoorConfig, DoorWatcher, parse_roi
from app.services.line_counter import PRESETS, LineCounter, make_gate

try:
    import cv2
except ImportError:  # 开发机上无摄像头依赖时保持可导入
    cv2 = None  # type: ignore[assignment]

# 计数线持久化文件（方向翻转等设置在服务重启后保留）
LINE_FILE = STORAGE_DIR / "counter_line.json"

TRAIL_LEN = 40          # 轨迹保留点数
EXCLUDE_CLASSES = {"person"}  # 递送物品的手/人不参与计数
READ_FAIL_REOPEN = 10   # 连续这么多次读不到画面（约 3 秒）就关掉摄像头重新打开（拔插后会这样）
STANDBY_FRAME_INTERVAL = 0.5  # 待机时网页画面每隔多少秒更新一次

# line_counter 的参数按"帧"写，是在 30 帧/秒的录像上定的；板子摄像头帧率不同时按比例换算成同样的秒数
_FRAME_FIELDS = ("relink_frames", "track_timeout", "cooldown_frames", "confirm_frames", "birth_frames")


def counter_config(preset: str, fps: float):
    cfg = PRESETS.get(preset) or PRESETS["default"]
    k = max(float(fps), 1.0) / 30.0
    return replace(cfg, **{
        f: (max(1, round(getattr(cfg, f) * k)) if getattr(cfg, f) > 0 else 0) for f in _FRAME_FIELDS
    })

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
    """物品进出自动计数服务：独占摄像头，开门时识别 + 过线计数，平时待机。

    与 CameraService 共用同一颗 USB 摄像头，二者互斥运行：
    本服务运行时 CameraService 必须处于停止状态，反之亦然。

    识别引擎由 _init_engine 选（NPU yolov5 优先，CPU ultralytics 兜底），统一成 detect(frame)。
    每读到一帧：
      DoorWatcher 判断待机 / 工作（app/services/door_watcher.py）；
      待机：不跑识别，网页画面每 0.5 秒更新一次；
      唤醒：开始一次"开门会话"，新建过线计数器；
      工作：detect → LineCounter（app/services/line_counter.py，第 2 步的规则）→ 计数事件写库；
      休眠：把还在等确认的过线按最后所在一边确认，记下这次会话。
    摄像头连续读不到画面（拔插）时自动重新打开。
    """

    def __init__(self, load_history: bool = True, persist: bool = True) -> None:
        self.device = CAMERA_DEVICE
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        self.jpeg_quality = max(40, min(CAMERA_JPEG_QUALITY, 95))
        self.enabled = COUNTER_ENABLED
        self.model_path = COUNTER_MODEL
        self.imgsz = COUNTER_IMGSZ
        self.persist = persist
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
        self.engine_name = "未加载"
        self.status_text = "未启动"
        self.inference_fps = 0.0
        self.n_tracks = 0
        self.error: str | None = None
        # 过线计数规则与开门检测
        self.preset = COUNTER_PRESET if COUNTER_PRESET in PRESETS else "default"
        self.counter_cfg = counter_config(self.preset, self.fps)
        self.counter: LineCounter | None = None
        self.frame_no = 0
        self.door = DoorWatcher(DoorConfig(
            enabled=DOOR_STANDBY_ENABLED,
            wake_ratio=DOOR_WAKE_RATIO,
            wake_brightness=DOOR_WAKE_BRIGHTNESS,
            wake_hits=DOOR_WAKE_HITS,
            sleep_ratio=DOOR_SLEEP_RATIO,
            sleep_seconds=DOOR_SLEEP_SECONDS,
            max_active_seconds=DOOR_MAX_ACTIVE_SECONDS,
            roi=parse_roi(DOOR_ROI),
        ))
        self.session_seq = 0
        self.session: dict[str, Any] | None = None
        self.sessions: deque[dict[str, Any]] = deque(maxlen=20)
        self._fps_t = 0.0
        self._last_standby_frame = -1e9
        if load_history:
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
        if not self.persist:
            return
        try:
            with database() as connection:
                counter_repository.record_event(connection, cls, delta)
        except Exception as exc:
            print(f"[counter] 计数事件写库失败：{exc}", flush=True)

    # ---------------- 工作线程 ----------------

    def _init_engine(self):
        """构建 detect(frame) -> [(tid, cls_name, x1, y1, x2, y2), ...]; 失败返回 None"""
        # ---- NPU 引擎 (香橙派 VIPLite + yolov5.nb + 轻量 ByteTrack) ----
        if COUNTER_ENGINE in ("npu", "auto"):
            try:
                from app.services.bytetrack_lite import ByteTrackLite
                from app.services.npu_yolov5 import COCO_CLASSES, NpuYolov5

                det = NpuYolov5(COUNTER_NPU_MODEL)
                tracker = ByteTrackLite()
                det.infer(np.zeros((self.height, self.width, 3), "uint8"))  # 预热
                self.engine_name = "NPU yolov5"

                def detect_npu(frame):
                    det.conf_threshold = max(0.10, self.conf * 0.45)  # 低分检测交给二级关联
                    tracker.high_conf = self.conf
                    dets = det.infer(frame)
                    trk = tracker.update(
                        [(x1, y1, x2, y2, conf, cid) for x1, y1, x2, y2, conf, cid, _ in dets]
                    )
                    return [
                        (tid, COCO_CLASSES[cls_id], x1, y1, x2, y2, conf)
                        for tid, cls_id, x1, y1, x2, y2, conf in trk
                    ]

                return detect_npu
            except Exception as exc:
                if COUNTER_ENGINE == "npu":
                    self._set_status(f"NPU 引擎初始化失败：{exc}", error=True)
                    return None
                print(f"[counter] NPU 引擎不可用，回退 CPU：{exc}", flush=True)

        # ---- CPU 引擎 (ultralytics yolo11s + ByteTrack, 原有逻辑) ----
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            self._set_status(f"未安装 ultralytics，无法计数：{exc}", error=True)
            return None
        try:
            model = YOLO(self.model_path)
        except Exception as exc:
            self._set_status(f"计数模型加载失败（{self.model_path}）：{exc}", error=True)
            return None
        self._set_status("模型已加载，正在预热")
        try:
            model.predict(
                np.zeros((self.height, self.width, 3), "uint8"),
                device="cpu", verbose=False, imgsz=self.imgsz,
            )
        except Exception:
            pass
        self.engine_name = f"CPU {self.model_path}"

        def detect_cpu(frame):
            results = model.track(
                frame, persist=True, tracker="bytetrack.yaml",
                conf=self.conf, imgsz=self.imgsz, device="cpu",
                verbose=False,
            )
            r = results[0]
            if r.boxes is None or r.boxes.id is None:
                return []
            boxes = r.boxes.xyxy.cpu().numpy()
            ids = r.boxes.id.int().cpu().numpy()
            clss = r.boxes.cls.int().cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            return [
                (int(tid), model.names[int(cid)], *[float(v) for v in box], float(cf))
                for box, tid, cid, cf in zip(boxes, ids, clss, confs)
            ]

        return detect_cpu

    def _worker(self) -> None:
        detect = self._init_engine()
        if detect is None:
            return

        while not self._stop_event.is_set():
            capture = self._open_capture()
            if capture is None:
                self._stop_event.wait(3)
                continue
            with self._condition:
                self.frame_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.width
                self.frame_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.height
            self.door.reset(time.monotonic())
            if not self.door.cfg.enabled:
                self._begin_session(time.monotonic(), reason="待机已关闭，一直识别")
            self._set_status(f"摄像头 {self.device} 已打开（{self.engine_name}），等待画面稳定")

            fails = 0
            while not self._stop_event.is_set():
                ret, frame = capture.read()
                if not ret or frame is None:
                    fails += 1
                    if fails >= READ_FAIL_REOPEN:
                        self._set_status("摄像头读不到画面，正在重新连接（可能被拔插过）", error=True)
                        break
                    self._stop_event.wait(0.3)
                    continue
                fails = 0
                out = self.process_frame(detect, frame, time.monotonic())
                if out is not None:
                    self._publish(out)

            self._end_session(time.monotonic(), reason="摄像头断开或计数暂停")
            self._release_capture()
            if not self._stop_event.is_set():
                self._stop_event.wait(2)

    def process_frame(self, detect, frame, now: float):
        """处理一帧；返回要推给网页的画面（待机时大多返回 None，省掉 JPEG 编码）。"""
        change = self.door.observe(frame, now)
        if change == "wake":
            self._begin_session(now, reason=self.door.wake_reason)
        elif change == "sleep":
            self._end_session(now, reason=self.door.sleep_reason)

        if not self.door.active:
            self.n_tracks = 0
            self.inference_fps = 0.0
            if now - self._last_standby_frame < STANDBY_FRAME_INTERVAL:
                return None
            self._last_standby_frame = now
            self._set_status(f"待机（{self.engine_name}）：画面静止，有人开门、伸手时自动开始识别")
            with self._line_lock:
                gate = make_gate(self.line, frame.shape[1], frame.shape[0])
            self._draw_line(frame, gate)
            cv2.putText(frame, f"STANDBY  motion {self.door.motion:.1%}", (12, frame.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
            return frame
        return self._process_active(detect, frame, now)

    def _process_active(self, detect, frame, now: float):
        if self.counter is None:   # 保险：工作状态一定有计数器
            self._begin_session(now, reason="恢复识别")
        try:
            frame_tracks = detect(frame)
        except Exception as exc:
            self._set_status(f"推理失败：{exc}", error=True)
            return frame
        self.frame_no += 1
        H, W = frame.shape[:2]
        with self._line_lock:
            gate = make_gate(self.line, W, H)
            line_epoch = self.line_epoch

        # 引擎输出 (编号, 类别, x1, y1, x2, y2[, 置信度]) → 计数器要的 (编号, 类别, 置信度, x1, y1, x2, y2)
        dets = []
        for tr in frame_tracks:
            tid, cls_name, x1, y1, x2, y2 = tr[:6]
            if cls_name in EXCLUDE_CLASSES:
                continue
            conf = float(tr[6]) if len(tr) > 6 else 1.0
            dets.append((int(tid), cls_name, conf, float(x1), float(y1), float(x2), float(y2)))
        events, visible = self.counter.update(dets, self.frame_no, gate, line_epoch)
        self._apply_events(events, self.counter.corrections)
        self.n_tracks = len(dets)

        self._draw_tracks(frame, dets, visible)
        self._draw_line(frame, gate)
        inst = 1.0 / max(now - self._fps_t, 1e-6)
        self.inference_fps = self.inference_fps * 0.9 + inst * 0.1 if self.inference_fps else min(inst, 30.0)
        self._fps_t = now
        cv2.putText(frame, f"FPS:{self.inference_fps:4.1f}  Tracks:{self.n_tracks}  #{self.session_seq}",
                    (12, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return frame

    def _draw_tracks(self, frame, dets, visible) -> None:
        for tid, cls_name, _, x1, y1, x2, y2 in dets:
            t = visible.get(tid)
            label_cls = self.counter.label(t) if t is not None else cls_name
            color = PALETTE[tid % len(PALETTE)]
            ix1, iy1, ix2, iy2 = int(x1), int(y1), int(x2), int(y2)
            cv2.rectangle(frame, (ix1, iy1), (ix2, iy2), color, 2)
            label = f"{label_cls} #{tid}"   # OpenCV 写不了中文，画面上用英文类别名；网页上显示中文
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            ty = max(iy1, th + 6)
            cv2.rectangle(frame, (ix1, ty - th - 6), (ix1 + tw + 4, ty), color, -1)
            cv2.putText(frame, label, (ix1 + 2, ty - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            if t is not None and len(t.trail) > 1:
                pts = np.array(t.trail, np.int32).reshape(-1, 1, 2)
                cv2.polylines(frame, [pts], False, (255, 220, 80), 2, cv2.LINE_AA)

    def _draw_line(self, frame, gate) -> None:
        if gate is None:
            cv2.putText(frame, "counting line cleared",
                        (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            return
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

    def _publish(self, frame) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if ok:
            with self._condition:
                self.jpeg = buf.tobytes()
                self.seq += 1
                self._condition.notify_all()

    # ---------------- 开门会话 ----------------

    def _begin_session(self, now: float, reason: str) -> None:
        self.session_seq += 1
        self.counter = LineCounter(self.counter_cfg, trail_len=TRAIL_LEN)  # 每次开门一个新计数器
        self.frame_no = 0
        self._fps_t = now
        self.session = {"n": self.session_seq, "start": time.strftime("%H:%M:%S"),
                        "t0": now, "wake": reason, "events": 0}
        self._set_status(f"开门中：第 {self.session_seq} 次（{reason}，{self.engine_name}）")
        print(f"[door] 唤醒 #{self.session_seq}：{reason}", flush=True)

    def _end_session(self, now: float, reason: str) -> None:
        if self.counter is not None:
            self._apply_events(self.counter.finish(self.frame_no), [])  # 还在等确认的，按最后所在一边算
            self.counter = None
        if self.session is None:
            return
        sess, self.session = self.session, None
        sess.update(end=time.strftime("%H:%M:%S"), seconds=round(now - sess.pop("t0"), 1),
                    sleep=reason, frames=self.frame_no)
        self.sessions.append(sess)
        print(f"[door] 待机 #{sess['n']}：{reason}；用时 {sess['seconds']} 秒，"
              f"识别 {sess['frames']} 帧，计数事件 {sess['events']} 个", flush=True)

    def _apply_events(self, events, corrections) -> None:
        if not events and not corrections:
            return
        now_str = time.strftime("%H:%M:%S")
        with self._condition:
            for e in events:
                e["t"] = now_str   # 事件字典和计数器共用：事后改类别时，流水里也跟着改
                self.counts[e["cls"]] += e["delta"]
                self.events.append(e)
            for e, old, new in corrections:   # 事后改类别：把计数从旧类别挪到新类别
                self.counts[old] -= e["delta"]
                self.counts[new] += e["delta"]
                if self.counts[old] == 0:
                    del self.counts[old]
        if self.session is not None:
            self.session["events"] += len(events)
        for e in events:
            self._persist_event(e["cls"], e["delta"])
        for e, old, new in corrections:      # 数据库里补一对冲正记录，累计数保持正确
            self._persist_event(old, -e["delta"])
            self._persist_event(new, e["delta"])

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
            "engine": self.engine_name,
            # 开门检测与待机
            "standby_enabled": self.door.cfg.enabled,
            **self.door.snapshot(time.monotonic()),
            "session": self.session_seq if self.session is not None else None,
            "sessions": list(self.sessions)[::-1][:10],
            "preset": self.preset,
            "model": self.engine_name,
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
