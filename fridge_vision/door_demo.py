#!/usr/bin/env python3
"""冰箱门口纯视觉记账 demo。

流程：摄像头 → 开门检测 → YOLO + ByteTrack 追踪手里的物品 → 物品轨迹穿过虚拟线 → 判定"放入 / 拿出"
     → 保存关键帧 → （可选）调大模型 API 确认名字 → 写 events.jsonl。

用法：
    python door_demo.py                       # 笔记本摄像头，自动开门检测
    python door_demo.py --trigger manual      # 按 o 键模拟开门/关门
    python door_demo.py --source clip.mp4 --trigger always --headless
    python door_demo.py --source rtsp://user:pass@192.168.1.50:554/stream1   # 无线/网络摄像头
    python door_demo.py --source http://192.168.1.66:8080/video               # 手机 IP Webcam 应用
    python door_demo.py --model yolo11n.pt    # 用 COCO 通用模型（瓶子、杯子、香蕉、苹果……）
    VLM_API_KEY=... python door_demo.py --vlm # 过线后把关键帧发给大模型确认名字
    python door_demo.py --post-url http://127.0.0.1:8000   # 过线事件连同关键帧上报库存后端

按键（有窗口时）：q 退出，o 手动开/关门，l 切换过线方向。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = HERE / "models" / "food_best.onnx"
LABELS_ZH = json.loads((HERE / "labels_zh.json").read_text(encoding="utf-8")) if (HERE / "labels_zh.json").exists() else {}


# ---------------------------------------------------------------- 开门检测
class DoorDetector:
    """纯视觉开门检测：冰箱灯亮 → 画面平均亮度跳变。

    关门状态下用指数平均跟踪基线亮度；亮度高出基线 `delta` 连续 `confirm` 帧判开门，
    回落到基线附近连续 `confirm` 帧判关门。手动模式下由按键切换。
    """

    def __init__(self, mode: str, delta: float = 35.0, confirm: int = 3) -> None:
        self.mode = mode
        self.delta = delta
        self.confirm = confirm
        self.open = mode == "always"
        self.baseline: float | None = None
        self.brightness: float = 0.0
        self._streak = 0

    def update(self, frame: np.ndarray) -> bool:
        if self.mode != "auto":
            return self.open
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        self.brightness = brightness
        if self.baseline is None:
            self.baseline = brightness
            return self.open
        if not self.open:
            if brightness > self.baseline + self.delta:
                self._streak += 1
                if self._streak >= self.confirm:
                    self.open, self._streak = True, 0
            else:
                self._streak = 0
                self.baseline = 0.98 * self.baseline + 0.02 * brightness
        else:
            if brightness < self.baseline + self.delta * 0.5:
                self._streak += 1
                if self._streak >= self.confirm:
                    self.open, self._streak = False, 0
            else:
                self._streak = 0
        return self.open

    def toggle(self) -> None:
        self.open = not self.open


# ---------------------------------------------------------------- 轨迹与过线
@dataclass
class Track:
    label: str
    positions: deque = field(default_factory=lambda: deque(maxlen=30))
    best_conf: float = 0.0
    best_crop: np.ndarray | None = None
    age: int = 0
    crossed: bool = False
    last_seen: float = 0.0


class LineCounter:
    """物品中心点穿过虚拟线 → 事件。`axis` 为 y 时线是水平的，`in_dir` 指"放入"是往哪边走。"""

    def __init__(self, axis: str, position: float, in_dir: str, min_age: int = 3,
                 min_gap: float = 1.5, stale_after: float = 0.6) -> None:
        self.axis = axis
        self.position = position
        self.in_dir = in_dir
        self.min_age = min_age
        self.min_gap = min_gap          # 同一类别、同一方向两次事件的最小间隔（秒），防止轨迹 ID 跳变重复计数
        self.stale_after = stale_after  # 轨迹消失超过这么久再出现，视为新轨迹，清空位置历史
        self.tracks: dict[int, Track] = {}
        self.last_event: dict[tuple[str, str], float] = {}

    def line_px(self, w: int, h: int) -> int:
        return int(self.position * (h if self.axis == "y" else w))

    def side(self, cx: float, cy: float, w: int, h: int) -> int:
        coord = cy if self.axis == "y" else cx
        return 1 if coord > self.line_px(w, h) else 0

    def update(self, tid: int, label: str, conf: float, box: tuple[int, int, int, int], frame: np.ndarray) -> str | None:
        x1, y1, x2, y2 = box
        h, w = frame.shape[:2]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        now = time.time()
        tr = self.tracks.setdefault(tid, Track(label=label))
        if tr.last_seen and now - tr.last_seen > self.stale_after:
            tr.positions.clear()
            tr.age = 0
            tr.crossed = False
        tr.last_seen = now
        tr.age += 1
        if conf > tr.best_conf:
            tr.best_conf = conf
            tr.label = label
            tr.best_crop = frame[max(0, y1):y2, max(0, x1):x2].copy()
        prev_side = tr.positions[-1] if tr.positions else None
        cur_side = self.side(cx, cy, w, h)
        tr.positions.append(cur_side)
        if tr.crossed or prev_side is None or tr.age < self.min_age or prev_side == cur_side:
            return None
        tr.crossed = True
        moved = "down" if (cur_side == 1) else "up"
        if self.axis == "x":
            moved = "right" if cur_side == 1 else "left"
        action = "in" if moved == self.in_dir else "out"
        key = (tr.label, action)
        if now - self.last_event.get(key, 0.0) < self.min_gap:
            return None  # 刚记过同一件事，视为同一次动作的重复轨迹
        self.last_event[key] = now
        return action

    def reset(self) -> None:
        self.tracks.clear()
        self.last_event.clear()


# ---------------------------------------------------------------- 上报后端
class EventPoster:
    """把过线事件连同关键帧 POST 给 smart_fridge_app 的 /api/v1/door-events。失败只打印，不影响本地记账。"""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        import httpx

        self.url = base_url.rstrip("/") + "/api/v1/door-events"
        self.client = httpx.Client(timeout=timeout)

    def post(self, event: dict, crop: np.ndarray | None, stamp: datetime) -> dict:
        payload = {
            "session_id": event["session_id"],
            "occurred_at": stamp.astimezone().isoformat(timespec="milliseconds"),
            "action": event["action"],
            "label": event["label"],
            "label_zh": event["label_zh"],
            "confidence": event["confidence"],
            "count": 1,
        }
        vlm = event.get("vlm")
        if isinstance(vlm, dict):
            payload["vlm"] = vlm
            try:
                count = int(vlm.get("count") or 0)
                if count > 0:
                    payload["count"] = count
            except (TypeError, ValueError):
                pass
        if crop is not None and crop.size:
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                payload["keyframe_base64"] = base64.b64encode(buf.tobytes()).decode()
        try:
            response = self.client.post(self.url, json=payload)
        except Exception as exc:  # 后端不在线
            print(f"    上报失败：{exc}", flush=True)
            return {"ok": False, "error": str(exc)[:200]}
        if response.status_code >= 300:
            print(f"    上报被拒 {response.status_code}：{response.text[:160]}", flush=True)
            return {"ok": False, "status": response.status_code, "error": response.text[:200]}
        body = response.json()
        lot = body.get("lot") or {}
        print(f"    已入账 {body.get('status')}，批次余量 {lot.get('quantity')}", flush=True)
        return {"ok": True, "event_id": body.get("id"), "status": body.get("status")}


# ---------------------------------------------------------------- 主循环
def zh(label: str) -> str:
    return LABELS_ZH.get(label, label)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0", help="摄像头编号或视频文件")
    ap.add_argument("--model", default=str(DEFAULT_MODEL), help="YOLO 模型（.onnx / .pt / .engine）")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--trigger", choices=["auto", "manual", "always"], default="auto", help="开门检测方式")
    ap.add_argument("--door-delta", type=float, default=35.0, help="自动模式：亮度高出基线多少算开门")
    ap.add_argument("--axis", choices=["x", "y"], default="y", help="虚拟线方向：y=水平线，x=竖直线")
    ap.add_argument("--line", type=float, default=0.5, help="虚拟线位置，占画面比例 0–1")
    ap.add_argument("--in-dir", default="up", choices=["up", "down", "left", "right"], help="往哪个方向过线算放入")
    ap.add_argument("--ignore", default="person,hand", help="不计数的类别，逗号分隔")
    ap.add_argument("--min-gap", type=float, default=1.5, help="同一类别同一方向两次事件的最小间隔（秒）")
    ap.add_argument("--out", default=str(HERE / "runs" / "events.jsonl"))
    ap.add_argument("--keyframes", default=str(HERE / "runs" / "keyframes"))
    ap.add_argument("--vlm", action="store_true", help="过线后用大模型 API 确认名字（需 VLM_API_KEY）")
    ap.add_argument("--post-url", default="", help="smart_fridge_app 地址，例如 http://127.0.0.1:8000；设置后每次过线都上报")
    ap.add_argument("--headless", action="store_true", help="不开窗口（视频文件验证用）")
    ap.add_argument("--max-frames", type=int, default=0, help="最多处理多少帧，0 不限")
    args = ap.parse_args()

    from ultralytics import YOLO  # 延迟导入，--help 更快

    model = YOLO(args.model, task="detect")
    names = model.names if isinstance(model.names, dict) else dict(enumerate(model.names))
    ignore = {s.strip() for s in args.ignore.split(",") if s.strip()}

    source: int | str = int(args.source) if args.source.isdigit() else args.source
    is_stream = isinstance(source, str) and source.startswith(("rtsp://", "http://", "https://", "rtmp://"))

    def open_source() -> cv2.VideoCapture:
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG) if is_stream else cv2.VideoCapture(source)
        if is_stream:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 网络流只留最新一帧，降低延迟
        return cap

    cap = open_source()
    if not cap.isOpened():
        print(f"打不开视频源 {args.source}", file=sys.stderr)
        return 2
    read_failures = 0

    door = DoorDetector(args.trigger, delta=args.door_delta)
    counter = LineCounter(args.axis, args.line, args.in_dir, min_gap=args.min_gap)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kf_dir = Path(args.keyframes)
    kf_dir.mkdir(parents=True, exist_ok=True)
    vlm = None
    if args.vlm:
        from vlm import VisionNamer

        vlm = VisionNamer.from_env()

    recent: deque[str] = deque(maxlen=6)
    session_events: list[dict] = []
    session_id = uuid.uuid4().hex
    poster = EventPoster(args.post_url) if args.post_url else None
    was_open = door.open
    frame_idx = 0
    t_last = time.time()
    fps = 0.0

    while True:
        ok, frame = cap.read()
        if not ok:
            if not is_stream:
                break
            read_failures += 1
            if read_failures > 30:
                print("网络流断开，重连…", flush=True)
                cap.release()
                time.sleep(2)
                cap = open_source()
                read_failures = 0
            continue
        read_failures = 0
        frame_idx += 1
        if args.max_frames and frame_idx > args.max_frames:
            break
        h, w = frame.shape[:2]
        is_open = door.update(frame)

        if is_open and not was_open:
            print(f"[{datetime.now():%H:%M:%S}] 开门", flush=True)
            session_events = []
            session_id = uuid.uuid4().hex
        if not is_open and was_open:
            summary = "、".join(f"{'放入' if e['action']=='in' else '拿出'}{e['label_zh']}" for e in session_events) or "无变化"
            print(f"[{datetime.now():%H:%M:%S}] 关门：{summary}", flush=True)
            counter.reset()
            if model.predictor is not None and getattr(model.predictor, "trackers", None):
                for t in model.predictor.trackers:
                    t.reset()
        was_open = is_open

        if is_open:
            results = model.track(frame, persist=True, conf=args.conf, imgsz=args.imgsz, tracker="bytetrack.yaml", verbose=False)
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None:
                ids = r.boxes.id.int().tolist()
                clss = r.boxes.cls.int().tolist()
                confs = r.boxes.conf.tolist()
                xyxy = r.boxes.xyxy.int().tolist()
                for tid, c, cf, (x1, y1, x2, y2) in zip(ids, clss, confs, xyxy):
                    label = names.get(c, str(c))
                    if label in ignore:
                        continue
                    action = counter.update(tid, label, cf, (x1, y1, x2, y2), frame)
                    if not args.headless:
                        color = (0, 200, 0) if action is None else (0, 0, 255)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(frame, f"#{tid} {label} {cf:.2f}", (x1, max(12, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                    if action:
                        tr = counter.tracks[tid]
                        stamp = datetime.now()
                        kf_name = f"{stamp:%Y%m%d_%H%M%S}_{tid}_{action}_{tr.label.replace(' ', '_')}.jpg"
                        if tr.best_crop is not None and tr.best_crop.size:
                            cv2.imwrite(str(kf_dir / kf_name), tr.best_crop)
                        event = {
                            "time": stamp.isoformat(timespec="seconds"),
                            "session_id": session_id,
                            "action": action,
                            "label": tr.label,
                            "label_zh": zh(tr.label),
                            "confidence": round(tr.best_conf, 3),
                            "track_id": tid,
                            "keyframe": str(kf_dir / kf_name),
                        }
                        if vlm is not None and tr.best_crop is not None:
                            try:
                                event["vlm"] = vlm.name_item(tr.best_crop)
                            except Exception as exc:  # API 失败不影响本地记账
                                event["vlm_error"] = str(exc)[:200]
                        line = f"{'放入' if action == 'in' else '拿出'} {event['label_zh']} ({tr.best_conf:.2f})"
                        if "vlm" in event:
                            line += f" → 大模型: {event['vlm'].get('name')} x{event['vlm'].get('count')}"
                        print(f"[{stamp:%H:%M:%S}] {line}", flush=True)
                        if poster is not None:
                            event["posted"] = poster.post(event, tr.best_crop, stamp)
                        with out_path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(event, ensure_ascii=False) + "\n")
                        session_events.append(event)
                        recent.appendleft(f"{action.upper():3s} {tr.label}")

        now = time.time()
        fps = 0.9 * fps + 0.1 / max(now - t_last, 1e-6)
        t_last = now

        if not args.headless:
            lp = counter.line_px(w, h)
            if args.axis == "y":
                cv2.line(frame, (0, lp), (w, lp), (255, 200, 0), 2)
            else:
                cv2.line(frame, (lp, 0), (lp, h), (255, 200, 0), 2)
            status = f"DOOR {'OPEN' if is_open else 'closed'}  {fps:4.1f} fps  in={args.in_dir}"
            if door.mode == "auto":
                base = door.baseline if door.baseline is not None else 0.0
                status += f"  lum={door.brightness:.0f} base={base:.0f} +{args.door_delta:.0f}"
            cv2.putText(frame, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255) if is_open else (180, 180, 180), 2)
            for i, line in enumerate(recent):
                cv2.putText(frame, line, (10, 52 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.imshow("fridge door demo", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("o") and args.trigger != "always":
                door.mode = "manual"
                door.toggle()
            if key == ord("l"):
                flip = {"up": "down", "down": "up", "left": "right", "right": "left"}
                args.in_dir = counter.in_dir = flip[counter.in_dir]

    cap.release()
    if not args.headless:
        cv2.destroyAllWindows()
    print(f"事件写入 {out_path}；关键帧在 {kf_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
