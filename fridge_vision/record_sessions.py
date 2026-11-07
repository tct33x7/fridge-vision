#!/usr/bin/env python3
"""测量录制工具：先回答三个数，再决定怎么识别。

每次开门：
  1. 整段开门过程录成 mp4（研发期落盘，产品期再删）；
  2. 门口虚拟线附近只要"有东西穿过"（帧差，和类别无关）就存关键帧，并记录运动重心轨迹；
  3. 可选 --model 同时跑 YOLO，只为统计它对真实物品的召回率；
  4. 关门后在终端问你：刚才放入了什么、拿出了什么（真值）。

三天后用 analyze_sessions.py 得到：开门触发是否可靠、放入动作有没有被拍到可用画面、YOLO 召回多少、
家里到底有哪些东西（长尾清单）。这些数字决定后面的架构。

用法：
    python record_sessions.py                         # 本机摄像头，自动开门检测
    python record_sessions.py --source 1 --model yolo11n.pt
    python record_sessions.py --source runs/synthetic.mp4 --headless --no-truth   # 自检
按键：o 手动开/关门，q 退出。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
LABELS_ZH = json.loads((HERE / "labels_zh.json").read_text(encoding="utf-8")) if (HERE / "labels_zh.json").exists() else {}


# ---------------------------------------------------------------- 开门状态
class DoorState:
    """画面亮度跳变判开关门。修了两个问题：开门超过 max_open 秒视为厨房灯之类的持续亮光，强制关门并重设基线；
    关门态基线缓慢跟随，开门态不跟随。"""

    def __init__(self, mode: str, delta: float, confirm: int = 3, max_open: float = 180.0) -> None:
        self.mode = mode
        self.delta = delta
        self.confirm = confirm
        self.max_open = max_open
        self.open = False
        self.baseline: float | None = None
        self.brightness = 0.0
        self.opened_at = 0.0
        self.last_reason = ""
        self._streak = 0

    def update(self, frame: np.ndarray, now: float) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.brightness = float(gray.mean())
        if self.mode != "auto":
            return self.open
        if self.baseline is None:
            self.baseline = self.brightness
            return self.open
        if not self.open:
            if self.brightness > self.baseline + self.delta:
                self._streak += 1
                if self._streak >= self.confirm:
                    self.open, self._streak, self.opened_at, self.last_reason = True, 0, now, "亮度跳变"
            else:
                self._streak = 0
                self.baseline = 0.98 * self.baseline + 0.02 * self.brightness
        else:
            if now - self.opened_at > self.max_open:
                self.open, self._streak, self.last_reason = False, 0, "超时，疑似厨房灯"
                self.baseline = self.brightness
            elif self.brightness < self.baseline + self.delta * 0.5:
                self._streak += 1
                if self._streak >= self.confirm:
                    self.open, self._streak, self.last_reason = False, 0, "亮度回落"
            else:
                self._streak = 0
        return self.open

    def toggle(self, now: float) -> None:
        self.open = not self.open
        self.opened_at = now
        self.last_reason = "手动"


# ---------------------------------------------------------------- 真值解析
_SPLIT = re.compile(r"[,，;；、/\s]+")
_COUNT = re.compile(r"^(.*?)[x×X*]\s*(\d+(?:\.\d+)?)$")


def parse_truth(raw: str) -> list[dict]:
    items = []
    for token in _SPLIT.split(raw.strip()):
        if not token:
            continue
        m = _COUNT.match(token)
        if m:
            items.append({"name": m.group(1).strip(), "count": float(m.group(2))})
        else:
            items.append({"name": token, "count": 1.0})
    return items


def ask_truth(session_id: str, keyframes: int, yolo_labels: dict[str, float]) -> dict:
    seen = "、".join(f"{LABELS_ZH.get(k, k)}({v:.2f})" for k, v in sorted(yolo_labels.items(), key=lambda kv: -kv[1])[:6])
    print(f"\n==== 关门 {session_id}：关键帧 {keyframes} 张" + (f"，YOLO 看到：{seen}" if seen else "") + " ====")
    print("请记真值（逗号分隔，数量写 x3，没有直接回车）")
    try:
        raw_in = input("  放入了什么：").strip()
        raw_out = input("  拿出了什么：").strip()
        note = input("  备注（可空）：").strip()
    except EOFError:
        raw_in = raw_out = note = ""
    return {"in": parse_truth(raw_in), "out": parse_truth(raw_out), "raw_in": raw_in, "raw_out": raw_out, "note": note}


# ---------------------------------------------------------------- 会话
class Session:
    def __init__(self, root: Path, source: str, fps: float, size: tuple[int, int], trigger_reason: str) -> None:
        self.started = time.time()
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = root / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clip = self.dir / "clip.mp4"
        self.writer = cv2.VideoWriter(str(self.clip), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        self.frames = 0
        self.keyframes: list[dict] = []
        self.motion_track: list[list[float]] = []
        self.yolo_labels: dict[str, float] = {}
        self.detections: list[dict] = []
        self.source = source
        self.trigger_reason = trigger_reason
        self.last_keyframe_at = 0.0

    def write(self, frame: np.ndarray) -> None:
        self.writer.write(frame)
        self.frames += 1

    def maybe_keyframe(self, frame: np.ndarray, t: float, motion: float, cx: float, interval: float, limit: int) -> bool:
        if len(self.keyframes) >= limit or t - self.last_keyframe_at < interval:
            return False
        name = f"kf_{len(self.keyframes):02d}_{t:06.2f}s.jpg"
        cv2.imwrite(str(self.dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        self.keyframes.append({"file": name, "t": round(t, 2), "motion": round(motion, 2), "cx": round(cx, 3)})
        self.last_keyframe_at = t
        return True

    def close(self, truth: dict | None, door_reason: str, model_name: str) -> Path:
        self.writer.release()
        ended = time.time()
        payload = {
            "id": self.id,
            "source": self.source,
            "start": datetime.fromtimestamp(self.started).isoformat(timespec="seconds"),
            "end": datetime.fromtimestamp(ended).isoformat(timespec="seconds"),
            "duration_s": round(ended - self.started, 1),
            "trigger": self.trigger_reason,
            "closed_by": door_reason,
            "clip": self.clip.name,
            "frames": self.frames,
            "keyframes": self.keyframes,
            "motion_track": self.motion_track[::3],
            "yolo": {"model": model_name, "labels": self.yolo_labels, "detections": self.detections[:400]},
            "truth": truth or {"in": [], "out": [], "raw_in": "", "raw_out": "", "note": "", "skipped": True},
        }
        (self.dir / "session.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.dir


# ---------------------------------------------------------------- 主循环
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0")
    ap.add_argument("--trigger", choices=["auto", "manual"], default="auto")
    ap.add_argument("--door-delta", type=float, default=25.0)
    ap.add_argument("--max-open", type=float, default=180.0, help="开门超过多少秒强制关门并重设基线（防厨房灯）")
    ap.add_argument("--axis", choices=["x", "y"], default="x")
    ap.add_argument("--line", type=float, default=0.5)
    ap.add_argument("--band", type=float, default=0.14, help="过线检测带宽，占画面比例")
    ap.add_argument("--motion-threshold", type=float, default=6.0, help="带内平均帧差超过它算有东西穿过")
    ap.add_argument("--keyframe-interval", type=float, default=0.35)
    ap.add_argument("--max-keyframes", type=int, default=40)
    ap.add_argument("--model", default="", help="可选 YOLO 模型，只为统计召回")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--out-dir", default=str(HERE / "runs" / "sessions"))
    ap.add_argument("--no-truth", action="store_true", help="关门后不问真值（自检用）")
    ap.add_argument("--lock-exposure", action="store_true", help="尽量锁定自动曝光（部分摄像头/系统不支持）")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()

    model = None
    if args.model:
        from ultralytics import YOLO

        model = YOLO(args.model, task="detect")
        names = model.names if isinstance(model.names, dict) else dict(enumerate(model.names))

    source: int | str = int(args.source) if args.source.isdigit() else args.source
    is_stream = isinstance(source, str) and source.startswith(("rtsp://", "http://", "https://"))
    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG) if is_stream else cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"打不开视频源 {args.source}", file=sys.stderr)
        return 2
    if is_stream:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if args.lock_exposure:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    fps = fps if 1.0 <= fps <= 60.0 else 15.0

    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    door = DoorState(args.trigger, args.door_delta, max_open=args.max_open)
    session: Session | None = None
    prev_gray: np.ndarray | None = None
    frame_idx = 0
    closed_sessions = 0
    t0 = time.time()
    kernel = np.ones((3, 3), np.uint8)

    print(f"录制目录 {root}；源 {args.source}；触发 {args.trigger}；模型 {args.model or '无'}", flush=True)
    while True:
        ok, frame = cap.read()
        if not ok:
            if is_stream:
                continue
            break
        frame_idx += 1
        if args.max_frames and frame_idx > args.max_frames:
            break
        now = time.time()
        h, w = frame.shape[:2]
        was_open = door.open
        is_open = door.update(frame, now)

        if is_open and not was_open:
            session = Session(root, args.source, fps, (w, h), door.last_reason)
            prev_gray = None
            print(f"[{datetime.now():%H:%M:%S}] 开门（{door.last_reason}）→ 录制 {session.id}", flush=True)
        if not is_open and was_open and session is not None:
            truth = None if args.no_truth else ask_truth(session.id, len(session.keyframes), session.yolo_labels)
            path = session.close(truth, door.last_reason, args.model)
            closed_sessions += 1
            print(f"[{datetime.now():%H:%M:%S}] 关门（{door.last_reason}）→ 已保存 {path.name}：{session.frames} 帧，{len(session.keyframes)} 张关键帧", flush=True)
            session = None

        motion = 0.0
        cx = 0.5
        if session is not None:
            t = now - session.started
            session.write(frame)
            gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                lp = int(args.line * (w if args.axis == "x" else h))
                half = int(args.band * (w if args.axis == "x" else h) / 2)
                band = diff[:, max(0, lp - half):lp + half] if args.axis == "x" else diff[max(0, lp - half):lp + half, :]
                motion = float(band.mean())
                mask = cv2.morphologyEx((diff > 25).astype(np.uint8), cv2.MORPH_OPEN, kernel)
                moments = cv2.moments(mask, binaryImage=True)
                if moments["m00"] > 50:
                    cx = (moments["m10"] / moments["m00"]) / (w if args.axis == "x" else h)
                session.motion_track.append([round(t, 2), round(cx, 3), round(motion, 2)])
                if motion > args.motion_threshold:
                    session.maybe_keyframe(frame, t, motion, cx, args.keyframe_interval, args.max_keyframes)
            prev_gray = gray
            if model is not None and frame_idx % 2 == 0:
                r = model.predict(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
                if r.boxes is not None:
                    for c, cf, box in zip(r.boxes.cls.int().tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.int().tolist()):
                        label = names.get(c, str(c))
                        if label in {"person", "hand"}:
                            continue
                        session.yolo_labels[label] = max(session.yolo_labels.get(label, 0.0), float(cf))
                        session.detections.append({"t": round(t, 2), "label": label, "conf": round(cf, 3), "box": box})

        if not args.headless:
            lp = int(args.line * (w if args.axis == "x" else h))
            half = int(args.band * (w if args.axis == "x" else h) / 2)
            if args.axis == "x":
                cv2.rectangle(frame, (lp - half, 0), (lp + half, h), (255, 200, 0), 1)
            else:
                cv2.rectangle(frame, (0, lp - half), (w, lp + half), (255, 200, 0), 1)
            base = door.baseline if door.baseline is not None else 0.0
            status = f"DOOR {'OPEN' if is_open else 'closed'}  lum={door.brightness:.0f} base={base:.0f} +{args.door_delta:.0f}"
            if session is not None:
                status += f"  REC {session.id}  motion={motion:.1f}  kf={len(session.keyframes)}"
            cv2.putText(frame, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255) if is_open else (180, 180, 180), 2)
            cv2.putText(frame, f"sessions saved: {closed_sessions}   o=door  q=quit", (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            cv2.imshow("fridge session recorder", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("o"):
                door.mode = "manual"
                door.toggle(now)

    if session is not None:
        truth = None if args.no_truth else ask_truth(session.id, len(session.keyframes), session.yolo_labels)
        session.close(truth, "退出", args.model)
        closed_sessions += 1
    cap.release()
    if not args.headless:
        cv2.destroyAllWindows()
    print(f"共保存 {closed_sessions} 个开门会话到 {root}；运行 analyze_sessions.py 看统计。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
