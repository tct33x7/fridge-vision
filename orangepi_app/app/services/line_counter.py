# 复制自 demos/yolo_web_counter/counter.py（第 2 步的过线计数逻辑），内容保持一致；那边改了就重新复制过来。
# -*- coding: utf-8 -*-
"""
过线计数逻辑（app.py 和 replay.py 共用，不依赖 YOLO，方便重放对比）。

输入：每帧的追踪结果 [(track_id, 类别名, 置信度, x1, y1, x2, y2), ...]
输出：计数事件 [{"frame", "tid", "cls", "delta"}]，delta=+1 进入 / -1 拿出

两套参数：
- PRESETS["baseline"]：第 1 步原版逻辑（6 像素滞回，看到换边就计）。
- PRESETS["default"]：第 2 步优化后（确认时间、滞回带、丢失后续接、类别投票 + 事后改类别、平滑、最短轨迹、冷却）。
- PRESETS["hidden"]：门洞上方机位、看不到冰箱里面时用（default + 出现/消失按中心所在边、只续接动过的、要求移动）。
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
    revote: bool = False             # 计数之后继续投票，类别变了就改正已经记下的事件（要配合 class_vote）
    confirm_frames: int = 0          # 确认时间：过线后要在新的一边待满这么多帧（或在那边消失）才计数；
                                     # 没待满就回来了 = 拿出又放回 / 晃动，不计。0 = 一过线马上计
    # 看不到冰箱里面时（门洞上方机位）：出现、消失的那一刻按中心在线的哪一边算，不要求整个框过线
    endpoints: bool = False          # 第一次出现就压在线上：按中心在哪边定它从哪来；消失时：按最后的中心在哪边定它去了哪
    end_margin: float = 6.0          # 上一条里，中心离线这么多像素以内算"正好在线上"，不判断
    min_travel: float = 0.0          # 轨迹总共要移动 这么多倍框宽 才允许计数（原地不动的误检不算）。0 = 不要求
    relink_moved_only: bool = False  # 只续接"动过"的轨迹，不把新物体接到原地不动的误检上
    # 出生推断（试过，默认关）：在 E02 的合成视频和 mix1 上各多计 1–2 次，也没救回 jitter1 的快速苹果
    birth_zone: float = 0.0          # 新目标第一次出现时离线很近（滞回带外 这么多倍框宽以内）……
    birth_frames: int = 8            # ……并且在这么多帧内继续往远离线的方向走，
    birth_move: float = 0.3          # ……走了 这么多倍框宽，就推断它是从线另一边快速穿过来的，补计一次。0=关


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
        relink_dist=2.0,
        revote=True,
        confirm_frames=90,
    ),
}


# 门洞上方机位（看不到冰箱里面）用：在 default 上再打开三条规则。
# E02 模拟（把里侧涂黑）：里侧只留 10% 画面宽时，多计/漏计 1/8 → 2/4；桌面（里面看得见）时和 default 一样。
PRESETS["hidden"] = replace(PRESETS["default"], endpoints=True, relink_moved_only=True, min_travel=0.5)


def get_config(name="default", **overrides):
    return replace(PRESETS[name], **{k: v for k, v in overrides.items() if v is not None})


class _Track:
    __slots__ = ("cls_now", "votes", "trail", "pos", "side", "seen", "last_seen",
                 "last_count", "line_epoch", "box", "lost_at", "relinked",
                 "birth_side", "birth_proj", "birth_frame", "pend_side", "pend_since",
                 "first_pos", "travel", "last_proj", "wn")

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
        self.relinked = False
        self.birth_side = 0              # 出生推断：等待中的那一侧（0 = 没在等）
        self.birth_proj = 0.0
        self.birth_frame = 0
        self.pend_side = 0               # 确认时间：已经过线、还没确认的那一侧（0 = 没有）
        self.pend_since = 0
        self.first_pos = None            # 第一次看到的位置
        self.travel = 0.0                # 离第一次位置最远走了多少像素
        self.last_proj = 0.0             # 最近一次中心到线的有符号距离（正 = +1 那边）
        self.wn = 1.0                    # 框沿过线方向的宽度


class LineCounter:
    def __init__(self, cfg: CounterConfig, trail_len=40):
        self.cfg = cfg
        self.trail_len = trail_len
        self.tracks = {}          # 当前编号 -> _Track
        self.line_epoch = 0
        self.relinks = 0
        self.open_events = []     # [(事件, 轨迹)]：轨迹还活着，类别可能还会被改正
        self.corrections = []     # 本帧改正了类别的事件 [(事件, 旧类别, 新类别)]
        self.birth_counts = 0
        self.cancelled = 0        # 过了线但没待满确认时间就回来了（没计）的次数

    # ---------- 工具 ----------
    def label(self, t):
        if self.cfg.class_vote and t.votes:
            return t.votes.most_common(1)[0][0]
        return t.cls_now

    def _moved(self, t):
        return self.cfg.min_travel <= 0 or t.travel >= self.cfg.min_travel * t.wn

    def _emit(self, events, t, tid, cross_frame, frame_no):
        """确认一次过线：从 t.side 到 t.pend_side。"""
        delta = 1 if t.pend_side > t.side else -1
        ev = {"frame": cross_frame, "tid": tid, "cls": self.label(t), "delta": delta, "confirmed_at": frame_no}
        events.append(ev)
        self.open_events.append((ev, t))
        t.last_count = frame_no
        t.side, t.pend_side = t.pend_side, 0

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
            if c.relink_moved_only and t.travel < 0.5 * t.wn:
                continue                   # 原地不动的（多半是误检，比如架子、鞋）不接
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
                    t.relinked = True
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
            if t.first_pos is None:
                t.first_pos = t.pos
            t.travel = max(t.travel, math.hypot(t.pos[0] - t.first_pos[0], t.pos[1] - t.first_pos[1]))
            visible[tid] = t

            if gate is None:
                continue
            ax, ay, _, _, _, _, nx, ny = gate
            proj = (t.pos[0] - ax) * nx + (t.pos[1] - ay) * ny
            wn = abs(w * nx) + abs(h * ny)            # 框沿过线方向的宽度
            hyst = c.hysteresis_px + c.hysteresis_box * wn
            side = 1 if proj > hyst else (-1 if proj < -hyst else 0)
            t.last_proj, t.wn = proj, max(wn, 1.0)

            if t.line_epoch != line_epoch:            # 新画了线 / 新目标：只记录在哪一侧，不计数
                t.line_epoch = line_epoch
                if (c.birth_zone > 0 and t.seen == 1 and not t.relinked and side != 0
                        and abs(proj) <= hyst + c.birth_zone * wn):
                    # 新目标第一次出现就在线边上：先不定它在哪一侧，看接下来往哪走
                    t.birth_side, t.birth_proj, t.birth_frame = side, abs(proj), frame_no
                elif side != 0:
                    t.side = side
                elif c.endpoints and abs(proj) > c.end_margin:
                    t.side = 1 if proj > 0 else -1   # 出现时压在线上：按中心在哪边定它从哪来
                continue
            if t.birth_side:
                if side == t.birth_side and abs(proj) >= t.birth_proj + c.birth_move * wn:
                    # 出现在线边、又继续远离线：推断是从另一边快速穿过来的（检测器没赶上）
                    delta = t.birth_side
                    ev = {"frame": frame_no, "tid": tid, "cls": self.label(t), "delta": delta, "inferred": True}
                    events.append(ev)
                    self.open_events.append((ev, t))
                    self.birth_counts += 1
                    t.last_count = frame_no
                    t.side, t.birth_side = side, 0
                    continue
                if side == -t.birth_side or frame_no - t.birth_frame > c.birth_frames:
                    t.side, t.birth_side = t.birth_side, 0   # 往线走 / 停住了：当作普通目标
                else:
                    continue
            if side == 0:
                continue
            if c.confirm_frames > 0:
                if t.side == 0 or side == t.side:
                    if t.pend_side:               # 没待满确认时间就回到原来那边：拿出又放回 / 晃动，不计
                        self.cancelled += 1
                        t.pend_side = 0
                    t.side = side
                    continue
                if t.pend_side != side:
                    t.pend_side, t.pend_since = side, frame_no
                ready = t.seen >= c.min_frames and frame_no - t.last_count >= c.cooldown_frames and self._moved(t)
                if ready and frame_no - t.pend_since >= c.confirm_frames:
                    self._emit(events, t, tid, t.pend_since, frame_no)
                continue
            if t.side != 0 and side != t.side:
                ready = t.seen >= c.min_frames and frame_no - t.last_count >= c.cooldown_frames
                if ready:
                    delta = 1 if side > t.side else -1
                    ev = {"frame": frame_no, "tid": tid, "cls": self.label(t), "delta": delta}
                    events.append(ev)
                    self.open_events.append((ev, t))
                    t.last_count = frame_no
                    t.side = side
                # 没准备好（太短/冷却中）：不计数，也不更新所在侧，等它稳定后再判断
            else:
                t.side = side

        # 标记丢失、删除过期
        done = set()
        for tid, t in list(self.tracks.items()):
            if t not in seen_now:
                if t.lost_at is None:
                    t.lost_at = frame_no
                # 确认时间：过线后在新的一边消失了（放进去 / 拿走了），续接窗口过了也没回来 → 确认
                gone = t not in done and frame_no - t.last_seen > c.relink_frames and t.seen >= c.min_frames
                if gone and c.endpoints and abs(t.last_proj) > c.end_margin:
                    final = 1 if t.last_proj > 0 else -1     # 消失时中心在线的哪一边
                    if t.pend_side and final == t.side:
                        t.pend_side = 0                       # 消失前已经回到原来那边：拿出又放回，不计
                        self.cancelled += 1
                    elif not t.pend_side and t.side and final != t.side:
                        t.pend_side, t.pend_since = final, t.last_seen   # 压着线消失在另一边：算它过去了
                if gone and t.pend_side and self._moved(t):
                    self._emit(events, t, tid, t.pend_since, frame_no)
                    done.add(t)
                if frame_no - t.last_seen > c.track_timeout:
                    del self.tracks[tid]

        # 事后改类别：轨迹还活着时继续投票，票数变了就改正已记下的事件
        self.corrections = []
        if c.revote and c.class_vote and self.open_events:
            alive = set(self.tracks.values())
            keep = []
            for ev, t in self.open_events:
                new = self.label(t)
                if new != ev["cls"]:
                    self.corrections.append((ev, ev["cls"], new))
                    ev.setdefault("cls_at_cross", ev["cls"])
                    ev["cls"] = new
                if t in alive:
                    keep.append((ev, t))
            self.open_events = keep
        return events, visible


    def finish(self, frame_no):
        """视频结束 / 关门：还在等确认的过线，按最后所在的一边确认。返回补上的事件。"""
        events, done = [], set()
        for tid, t in list(self.tracks.items()):
            if t.pend_side and t not in done and t.seen >= self.cfg.min_frames and self._moved(t):
                self._emit(events, t, tid, t.pend_since, frame_no)
                done.add(t)
        return events


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
