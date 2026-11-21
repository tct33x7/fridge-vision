# -*- coding: utf-8 -*-
"""
时间基准：录像里第 i 帧是第几秒。所有评测工具都从这里取时间，不各算各的。

规则（orangepi_app/tools/simulate_counter.py 用同一套）：
1. 有 <录像名>.frames.json（新版 tools/record.py 每一帧记下的真实时刻）就**一定用它**；这时命令行的 --fps 会被忽略并提示。
2. 没有 .frames.json 时，用命令行给的 --fps（例如用秒表测出来的真实帧率）。
3. 都没有时按 mp4 文件头的帧率（可能不准：旧版录制工具固定写 30，而相机实际可能只有 15）——会大声提示。

.frames.json 和录像的帧数差 1–2 帧（录的时候连按两次 Ctrl+C 可能出现）：按较短的截掉、或按中位间隔往后补齐，并提示；
差得更多说明文件不配套，直接报错。
"""
import bisect
import json
import os
import statistics
import sys

import cv2

MAX_MISMATCH = 2
PAUSE_GAP = 1.0   # 相邻两帧间隔超过 1 秒算暂停，不参与算帧率


def sidecar_path(video):
    return os.path.splitext(video)[0] + ".frames.json"


def median_fps(ts, default=30.0):
    gaps = [b - a for a, b in zip(ts, ts[1:]) if 0 < b - a < PAUSE_GAP]
    return 1.0 / statistics.median(gaps) if gaps else default


class TimeBase:
    def __init__(self, t, source, fps, note=""):
        self.t = t                  # t[i] = 第 i 帧（从 0 数）的时刻，秒
        self.source = source        # "sidecar" / "fps_override" / "header"
        self.fps = fps              # 整段的真实帧率（中位数）
        self.note = note

    def __len__(self):
        return len(self.t)

    def frame_at(self, seconds):
        """第一个时刻 >= seconds 的帧号（从 0 数）。"""
        return bisect.bisect_left(self.t, seconds - 1e-9)

    def fps_between(self, f0, f1):
        """第 f0 到 f1 帧之间的真实帧率（中位数；暂停不算）。帧太少时用整段的。"""
        return median_fps(self.t[max(0, f0):max(0, f1)], self.fps) if f1 - f0 >= 10 else self.fps

    def describe(self):
        return {"source": self.source, "fps": round(self.fps, 3), "frames": len(self.t),
                "duration_s": round(self.t[-1], 3) if self.t else 0.0, "note": self.note}


def _video_info(video):
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"打不开录像：{video}")
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    cap.release()
    return n, fps


def load(video, fps_override=None, n_frames=None, quiet=False):
    """返回 TimeBase。n_frames：实际解码出的帧数（文件头的帧数有时不准，知道的话传进来）。"""
    n_hdr, fps_hdr = _video_info(video)
    n = n_frames if n_frames is not None else n_hdr
    side = sidecar_path(video)
    if os.path.isfile(side):
        if fps_override and not quiet:
            print(f"！{os.path.basename(video)} 有 {os.path.basename(side)}，按它记的真实时间算，忽略 --fps {fps_override}",
                  file=sys.stderr)
        with open(side, encoding="utf-8") as f:
            t = [float(x) for x in json.load(f)["t"]]
        note = ""
        if len(t) != n:
            if abs(len(t) - n) > MAX_MISMATCH or not t:
                raise SystemExit(f"{os.path.basename(side)} 记了 {len(t)} 帧，录像有 {n} 帧，对不上（差 {abs(len(t) - n)} 帧）："
                                 f"是不是拿错了文件？")
            step = 1.0 / median_fps(t, fps_hdr or 30.0)
            note = f"时间戳 {len(t)} 帧、录像 {n} 帧，差 {abs(len(t) - n)} 帧：按较短的截掉或在末尾补齐"
            t = t[:n] + [t[-1] + step * (k + 1) for k in range(max(0, n - len(t)))]
            if not quiet:
                print(f"！{os.path.basename(video)}：{note}", file=sys.stderr)
        return TimeBase(t, "sidecar", median_fps(t, fps_hdr or 30.0), note)
    if fps_override:
        return TimeBase([i / fps_override for i in range(n)], "fps_override", float(fps_override),
                        f"没有 {os.path.basename(side)}，按命令行给的 {fps_override} 帧/秒")
    fps = fps_hdr or 30.0
    note = f"没有 {os.path.basename(side)}，按文件头 {fps:g} 帧/秒算时间（旧版录制工具固定写 30，可能不准）"
    if not quiet:
        print(f"！{os.path.basename(video)}：{note}", file=sys.stderr)
    return TimeBase([i / fps for i in range(n)], "header", fps, note)
