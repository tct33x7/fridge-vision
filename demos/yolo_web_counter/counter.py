# -*- coding: utf-8 -*-
"""
过线计数逻辑（app.py 和 replay.py 共用，不依赖 YOLO，方便重放对比）。

输入：每帧的追踪结果 [(track_id, 类别名, 置信度, x1, y1, x2, y2), ...]
输出：计数事件 [{"frame", "tid", "cls", "delta"}]，delta=+1 进入 / -1 拿出

两套参数：
- PRESETS["baseline"]：第 1 步原版逻辑（6 像素滞回，看到换边就计）。
- PRESETS["default"]：第 2 步优化后（平滑、最短轨迹、滞回带、冷却、类别投票、丢失后续接）。
"""
import math
from collections import Counter, deque
from dataclasses import dataclass, replace

import cv2
import numpy as np


@dataclass
class CounterConfig:
    hysteresis_px: float = 6.0       # 离线小于这个距离算"在线上"（像素，固定部分）
    hysteresis_box: float = 0.0      # 再加上 目标框沿过线方向的宽度 × 这个比例（0.5 = 整个框都过了线）
    smooth_alpha: float = 1.0        # 中心点平滑：1.0=不平滑；0.5=新位置占一半
    min_frames: int = 0              # 轨迹至少被看到几帧才允许计数
    cooldown_frames: int = 0         # 同一目标计数后，这么多帧内不再计数
    class_vote: bool = False         # 类别用整条轨迹的置信度加权投票，而不是当前帧
    relink_frames: int = 0           # 目标丢失后多少帧内，附近出现的新编号算同一个目标（接上它的"从哪边来"和类别票）
    relink_dist: float = 0.0         # 续接距离上限 = 目标框对角线 × 这个倍数
    track_timeout: int = 60          # 连续多少帧没看到就删掉轨迹


PRESETS = {
    "baseline": CounterConfig(),
    "default": CounterConfig(
        hysteresis_px=6.0,
        hysteresis_box=0.5,
        smooth_alpha=0.5,
        min_frames=3,
        cooldown_frames=15,
        class_vote=True,
        relink_frames=20,
        relink_dist=1.5,
    ),
}


def get_config(name="default", **overrides):
    return replace(PRESETS[name], **{k: v for k, v in overrides.items() if v is not None})


class _Track:
    __slots__ = ("cls_now", "votes", "trail", "pos", "side", "seen", "last_seen",
                 "last_count", "line_epoch", "box", "lost_at")

    def __init__(self, trail_len):
        self.cls_now = None
        self.votes = Counter()
        self.trail = deque(maxlen=trail_len)
        self.pos = None
        self.side = 0
        self.seen = 0
        self.last_seen = 0
        self.last_count = -10 ** 9
        self.line_epoch = -1
        self.box = (0.0, 0.0)            # 宽、高
        self.lost_at = None


class LineCounter:
    def __init__(self, cfg: CounterConfig, trail_len=40):
        self.cfg = cfg
        self.trail_len = trail_len
        self.tracks = {}          # 当前编号 -> _Track
        self.line_epoch = 0
        self.relinks = 0

    # ---------- 工具 ----------
    def label(self, t):
        if self.cfg.class_vote and t.votes:
            return t.votes.most_common(1)[0][0]
        return t.cls_now

    def _try_relink(self, cls, cx, cy, w, h, frame_no):
        """新编号出现时，在刚丢失的轨迹里找一个同类、距离近的接上。"""
        c = self.cfg
        if c.relink_frames <= 0:
            return None
        # 候选：刚丢失、同类、距离够近。多个候选时优先接"看到得最久"的那条——
        # 物体在线附近晃时 ByteTrack 会冒出好几个短命的新编号，真正带着"从哪边来"记忆的是最老的那条。
        best, best_key = None, None
        diag = math.hypot(w, h)
        for t in set(self.tracks.values()):
            if t.lost_at is None or frame_no - t.lost_at > c.relink_frames:
                continue
            d = math.hypot(cx - t.pos[0], cy - t.pos[1])
            if d > c.relink_dist * max(diag, math.hypot(*t.box)):
                continue
            # 类别不要求一样（YOLO 本来就会跳类），但同类的优先
            key = (cls in t.votes, t.seen, -d)
            if best_key is None or key > best_key:
                best, best_key = t, key
        return best

    # ---------- 主入口 ----------
    def update(self, dets, frame_no, gate, line_epoch=0):
        """
        dets: [(tid, cls, conf, x1, y1, x2, y2)]
        gate: None 或 (ax, ay, bx, by, ux, uy, nx, ny)，像素坐标，n 为 +1 方向的法向量
        返回 (本帧事件列表, {tid: 轨迹信息 用于绘制})
        """
        c = self.cfg
        events, visible = [], {}
        seen_now = set()
        for tid, cls, conf, x1, y1, x2, y2 in dets:
            w, h = x2 - x1, y2 - y1
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            t = self.tracks.get(tid)
            if t is None:
                t = self._try_relink(cls, cx, cy, w, h, frame_no)
                if t is not None:
                    self.relinks += 1
                else:
                    t = _Track(self.trail_len)
                self.tracks[tid] = t
            if t in seen_now:          # 同一帧两个框续接到同一条轨迹：第二个另开
                t = _Track(self.trail_len)
                self.tracks[tid] = t
            seen_now.add(t)

            t.cls_now = cls
            t.votes[cls] += float(conf)
            t.lost_at = None
            t.last_seen = frame_no
            t.seen += 1
            t.box = (w, h)
            if t.pos is None:
                t.pos = (cx, cy)
            else:
                a = c.smooth_alpha
                t.pos = (t.pos[0] + a * (cx - t.pos[0]), t.pos[1] + a * (cy - t.pos[1]))
            t.trail.append(t.pos)
            visible[tid] = t

            if gate is None:
                continue
            ax, ay, _, _, _, _, nx, ny = gate
            proj = (t.pos[0] - ax) * nx + (t.pos[1] - ay) * ny
            hyst = c.hysteresis_px + c.hysteresis_box * (abs(w * nx) + abs(h * ny))
            side = 1 if proj > hyst else (-1 if proj < -hyst else 0)

            if t.line_epoch != line_epoch:            # 新画了线：只记录在哪一侧，不计数
                t.side = side if side != 0 else t.side
                t.line_epoch = line_epoch
                continue
            if side == 0:
                continue
            if t.side != 0 and side != t.side:
                ready = t.seen >= c.min_frames and frame_no - t.last_count >= c.cooldown_frames
                if ready:
                    delta = 1 if side > t.side else -1
                    events.append({"frame": frame_no, "tid": tid, "cls": self.label(t), "delta": delta})
                    t.last_count = frame_no
                    t.side = side
                # 没准备好（太短/冷却中）：不计数，也不更新所在侧，等它稳定后再判断
            else:
                t.side = side

        # 标记丢失、删除过期
        for tid, t in list(self.tracks.items()):
            if t not in seen_now:
                if t.lost_at is None:
                    t.lost_at = frame_no
                if frame_no - t.last_seen > c.track_timeout:
                    del self.tracks[tid]
        return events, visible


# ---------------- 光线：软件亮度归一化 ----------------

_clahe = None


def normalize_light(frame, mode):
    """
    mode:
      "off"   不处理
      "gain"  整体亮度拉到固定目标（抵消自动曝光一明一暗）
      "clahe" 亮度通道做局部直方图均衡（逆光、局部暗）
    """
    global _clahe
    if mode == "off" or mode is None:
        return frame
    if mode == "gain":
        mean = float(frame.mean())
        if mean < 1:
            return frame
        g = min(3.0, max(0.33, 115.0 / mean))
        return cv2.convertScaleAbs(frame, alpha=g, beta=0)
    if mode == "clahe":
        if _clahe is None:
            _clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = _clahe.apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    raise ValueError(f"未知的 light 模式: {mode}")


def make_gate(line_norm, W, H):
    """归一化线 (ax, ay, bx, by) → 像素 gate；A→B 左侧为 +1 方向。"""
    if line_norm is None:
        return None
    ax, ay = line_norm[0] * W, line_norm[1] * H
    bx, by = line_norm[2] * W, line_norm[3] * H
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L <= 10:
        return None
    ux, uy = dx / L, dy / L
    return (ax, ay, bx, by, ux, uy, -uy, ux)


def lock_exposure(cap, value=None):
    """
    尽量锁定摄像头曝光。macOS 的 AVFoundation 后端大多不支持，返回说明文字。
    value=None 时只关自动曝光。
    """
    msgs = []
    ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # V4L2(Linux/OrangePi) 里 0.25=手动
    if not ok:
        ok = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 有的后端 1=手动
    msgs.append(f"关自动曝光: {'成功' if ok else '后端不支持'}")
    if value is not None:
        ok2 = cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        msgs.append(f"曝光={value}: {'成功' if ok2 else '后端不支持'}")
    return "；".join(msgs)


__all__ = ["CounterConfig", "PRESETS", "get_config", "LineCounter",
           "normalize_light", "make_gate", "lock_exposure", "np"]
