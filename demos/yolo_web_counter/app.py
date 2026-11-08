#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLO11s 物体轨迹方向计数 Web Demo
- 打开 USB 摄像头，YOLO11s + ByteTrack 检测并追踪物体
- 用户在画面上拖拽画一条"计数线"，拖拽方向决定正方向（线的左侧为 +1 方向）
- 物体沿正方向穿过计数线 → 该物品 +1；反方向 → -1
- 侧边栏实时统计各物品净数量与进出事件
"""
import math
import os
import threading
import time
from collections import deque, defaultdict

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ultralytics import YOLO

ROOT = os.path.dirname(os.path.abspath(__file__))
# 模型查找顺序：包内 models/ → 上级 yolo_pretrained/（原工程位置）
_CANDIDATES = [
    os.path.join(ROOT, "models", "yolo11s.pt"),
    os.path.abspath(os.path.join(ROOT, "..", "yolo_pretrained", "yolo11s.pt")),
]
MODEL_PATH = next((p for p in _CANDIDATES if os.path.isfile(p)), _CANDIDATES[0])

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
TRAIL_LEN = 40          # 轨迹保留点数
HYSTERESIS = 6.0        # 距线小于该像素数视为"在线上"，防止抖动重复计数
TRACK_TIMEOUT = 60      # 连续 N 帧未见则删除轨迹
CAM_W, CAM_H = 1280, 720

# 屏蔽的识别类别：递送物品的手/人不应参与计数，只统计物品本身
EXCLUDE_CLASSES = {"person"}

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


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame_cond = threading.Condition(self.lock)
        self.cam_change = threading.Event()
        self.jpeg = None
        self.seq = 0
        self.frame_w, self.frame_h = CAM_W, CAM_H
        self.counts = defaultdict(int)          # 类别名 -> 净数量
        self.events = deque(maxlen=100)         # 事件流水
        self.line = None                        # 归一化 (ax, ay, bx, by)，A→B 方向的左侧为 +1 侧
        self.line_epoch = 0                     # 方向线版本，变更后静默刷新各轨迹所在侧
        self.conf = 0.35
        self.camera_source = 0            # int 索引（本地/虚拟摄像头）或 str URL（网络流）
        self.camera_status = "初始化中..."
        self.fps = 0.0
        self.n_tracks = 0


S = State()
app = FastAPI(title="YOLO11s 物体轨迹方向计数")


# ---------------- 检测 / 追踪 / 计数 工作线程 ----------------

def zh_name(name):
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


def worker():
    model = YOLO(MODEL_PATH)
    print(f"[init] 模型已加载: {MODEL_PATH} (推理设备: {DEVICE})")
    # 预热，避免首帧卡顿
    try:
        model.predict(np.zeros((CAM_H, CAM_W, 3), np.uint8), device=DEVICE,
                      verbose=False, imgsz=640)
    except Exception as e:
        print(f"[warn] 预热失败(忽略): {e}")

    tracks = {}   # track_id -> {cls, trail, side, last_seen, line_epoch}
    frame_no = 0
    fps_t = time.time()

    while True:
        src = S.camera_source
        if isinstance(src, str) and src.lower().startswith(("http://", "https://", "rtsp://")):
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            src_desc = src
        else:
            cap = cv2.VideoCapture(int(src))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
            cap.set(cv2.CAP_PROP_FPS, 30)
            src_desc = f"摄像头 {src}"
        if not cap.isOpened():
            with S.lock:
                S.camera_status = f"无法打开 {src_desc}（检查权限/被占用，或换个设备）"
            S.cam_change.wait(timeout=5)
            S.cam_change.clear()
            continue

        with S.lock:
            S.camera_status = f"{src_desc} 运行中"
            S.frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or CAM_W
            S.frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or CAM_H
        print(f"[camera] 已打开 {src_desc} ({S.frame_w}x{S.frame_h})")

        while True:
            if S.camera_source != src:
                break
            ret, frame = cap.read()
            if not ret:
                with S.lock:
                    S.camera_status = f"{src_desc} 读取失败，重连中..."
                time.sleep(0.5)
                break

            frame_no += 1
            results = model.track(frame, persist=True, tracker="bytetrack.yaml",
                                  conf=S.conf, imgsz=640, device=DEVICE,
                                  verbose=False)
            r = results[0]
            now_str = time.strftime("%H:%M:%S")

            with S.lock:
                line_norm = S.line
                line_epoch = S.line_epoch

            # 计数线像素坐标与正方向法向量（A→B 左侧为 +）
            gate = None
            if line_norm is not None:
                H, W = frame.shape[:2]
                ax, ay = line_norm[0] * W, line_norm[1] * H
                bx, by = line_norm[2] * W, line_norm[3] * H
                dx, dy = bx - ax, by - ay
                L = math.hypot(dx, dy)
                if L > 10:
                    ux, uy = dx / L, dy / L
                    nx, ny = -uy, ux          # 左法线 = 正方向
                    gate = (ax, ay, bx, by, ux, uy, nx, ny)

            seen_ids = set()
            if r.boxes is not None and r.boxes.id is not None:
                boxes = r.boxes.xyxy.cpu().numpy()
                ids = r.boxes.id.int().cpu().numpy()
                clss = r.boxes.cls.int().cpu().numpy()
                names = model.names

                for (x1, y1, x2, y2), tid, cid in zip(boxes, ids, clss):
                    tid = int(tid)
                    # 屏蔽人/手等类别：不追踪、不绘制、不计数
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
                        ax, ay, _, _, _, _, nx, ny = gate
                        proj = (cx - ax) * nx + (cy - ay) * ny
                        side = 1 if proj > HYSTERESIS else (-1 if proj < -HYSTERESIS else 0)
                        if t["line_epoch"] != line_epoch:
                            t["side"] = side if side != 0 else t["side"]
                            t["line_epoch"] = line_epoch
                        elif side != 0 and side != t["side"] and t["side"] != 0:
                            delta = 1 if side > t["side"] else -1
                            with S.lock:
                                S.counts[t["cls"]] += delta
                                S.events.append({"t": now_str, "cls": t["cls"], "delta": delta})
                            t["side"] = side
                        elif side != 0:
                            t["side"] = side

                    # ---- 绘制 ----
                    color = PALETTE[cid % len(PALETTE)]
                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    label = f"{zh_name(t['cls'])} #{tid}"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                    ty = max(y1, th + 6)
                    cv2.rectangle(frame, (x1, ty - th - 6), (x1 + tw + 4, ty), color, -1)
                    cv2.putText(frame, label, (x1 + 2, ty - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                    if len(t["trail"]) > 1:
                        pts = np.array(t["trail"], np.int32).reshape(-1, 1, 2)
                        cv2.polylines(frame, [pts], False, (255, 220, 80), 2, cv2.LINE_AA)
                S.n_tracks = len(seen_ids)
            else:
                S.n_tracks = 0

            # 清理长期未见的轨迹
            stale = [k for k, v in tracks.items() if frame_no - v["last_seen"] > TRACK_TIMEOUT]
            for k in stale:
                del tracks[k]

            # ---- 绘制计数线与正方向箭头 ----
            if gate is not None:
                ax, ay, bx, by, ux, uy, nx, ny = gate
                H, W = frame.shape[:2]
                far = 2000.0
                draw_dashed(frame, (ax - ux * far, ay - uy * far),
                            (ax + ux * far, ay + uy * far), (0, 140, 255), 2)
                cv2.line(frame, (int(ax), int(ay)), (int(bx), int(by)), (0, 140, 255), 3)
                # 中点处画正方向箭头（指向 +1 一侧）
                mx, my = (ax + bx) / 2, (ay + by) / 2
                tip = (int(mx + nx * 70), int(my + ny * 70))
                cv2.arrowedLine(frame, (int(mx), int(my)), tip, (0, 255, 255), 4,
                                tipLength=0.3, line_type=cv2.LINE_AA)
                cv2.putText(frame, "+1", (int(tip[0] + nx * 10), int(tip[1] + ny * 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 3, cv2.LINE_AA)
                cv2.putText(frame, f"-1 ->", (int(mx - nx * 70 - 30), int(my - ny * 70)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)
            else:
                cv2.putText(frame, "Draw a line on the video to count  (drag: A -> B, left side = +1)",
                            (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            # HUD
            now = time.time()
            if now - fps_t > 0:
                inst = 1.0 / max(now - fps_t, 1e-6)
                S.fps = S.fps * 0.9 + inst * 0.1 if S.fps else inst
            fps_t = now
            hud = f"FPS:{S.fps:4.1f}  Tracks:{S.n_tracks}  {DEVICE.upper()}"
            cv2.putText(frame, hud, (12, frame.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                with S.frame_cond:
                    S.jpeg = buf.tobytes()
                    S.seq += 1
                    S.frame_cond.notify_all()

        cap.release()
        if S.camera_source == src and S.cam_change.is_set():
            S.cam_change.clear()


threading.Thread(target=worker, daemon=True).start()


# ---------------- API ----------------

class LineReq(BaseModel):
    ax: float
    ay: float
    bx: float
    by: float


class CameraReq(BaseModel):
    index: int | None = None
    url: str | None = None


class ConfReq(BaseModel):
    value: float


def list_system_cameras():
    """用 system_profiler 枚举 macOS 摄像头设备名（含连续互通相机/Camo 等虚拟摄像头）"""
    import json as _json
    import subprocess
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType", "-json"],
                             capture_output=True, timeout=6)
        data = _json.loads(out.stdout)
        items = (data.get("SPCameraDataType") or [])
        return [it.get("_name", "未知设备") for it in items]
    except Exception:
        return []


@app.get("/api/cameras")
def cameras():
    """列出摄像头设备名（system_profiler 顺序与 OpenCV/AVFoundation 索引一致，不实际打开设备避免抢占）"""
    def looks_like_phone(name):
        low = name.lower()
        if "iphone" in low or "continuity" in low or "连续互通" in name or "camo" in low or "epoccam" in low:
            return True
        # 连续互通相机命名格式：“iPhone名称”的相机（带引号）；内置摄像头如 "MacBook Pro的相机"（不带引号）
        if "的相机" in name and ("\u201c" in name or "\u201d" in name):
            return True
        return False

    names = list_system_cameras()
    usable = [{"index": i, "name": n, "is_phone": looks_like_phone(n)}
              for i, n in enumerate(names[:10])]
    return {"cameras": usable, "all_names": names}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


@app.get("/video")
def video():
    def gen():
        last = -1
        while True:
            with S.frame_cond:
                while S.seq == last:
                    S.frame_cond.wait(timeout=5)
                    if S.seq == last:
                        break
                data, last = S.jpeg, S.seq
            if data is None:
                time.sleep(0.1)
                continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/state")
def state():
    with S.lock:
        counts = dict(sorted(S.counts.items(), key=lambda kv: -abs(kv[1])))
        return {
            "fps": round(S.fps, 1),
            "camera_source": str(S.camera_source),
            "camera_status": S.camera_status,
            "frame_w": S.frame_w,
            "frame_h": S.frame_h,
            "line_set": S.line is not None,
            "conf": S.conf,
            "n_tracks": S.n_tracks,
            "counts": counts,
            "events": list(S.events)[-30:][::-1],
        }


@app.post("/api/line")
def set_line(req: LineReq):
    with S.lock:
        S.line = (req.ax, req.ay, req.bx, req.by)
        S.line_epoch += 1
    return {"ok": True}


@app.post("/api/line/flip")
def flip_line():
    with S.lock:
        if S.line:
            ax, ay, bx, by = S.line
            S.line = (bx, by, ax, ay)
            S.line_epoch += 1
    return {"ok": True}


@app.post("/api/line/clear")
def clear_line():
    with S.lock:
        S.line = None
        S.line_epoch += 1
    return {"ok": True}


@app.post("/api/camera")
def set_camera(req: CameraReq):
    if req.url:
        url = req.url.strip()
        if not url.lower().startswith(("http://", "https://", "rtsp://")):
            return {"ok": False, "msg": "URL 需以 http://、https:// 或 rtsp:// 开头"}
        with S.lock:
            S.camera_source = url
    elif req.index is not None:
        if not (0 <= req.index <= 9):
            return {"ok": False, "msg": "摄像头编号需在 0-9"}
        with S.lock:
            S.camera_source = int(req.index)
    else:
        return {"ok": False, "msg": "需提供 index 或 url"}
    S.cam_change.set()
    return {"ok": True}


@app.post("/api/conf")
def set_conf(req: ConfReq):
    with S.lock:
        S.conf = min(0.9, max(0.05, req.value))
    return {"ok": True, "conf": S.conf}


@app.post("/api/reset")
def reset():
    with S.lock:
        S.counts.clear()
        S.events.clear()
    return {"ok": True}


if __name__ == "__main__":
    print("=" * 60)
    print(" YOLO11s 物体轨迹方向计数 Demo")
    print(f" 推理设备: {DEVICE}   模型: {os.path.basename(MODEL_PATH)}")
    print(" 打开浏览器访问: http://localhost:8020")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8020, log_level="warning")
