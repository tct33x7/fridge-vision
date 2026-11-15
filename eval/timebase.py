# -*- coding: utf-8 -*-
"""
时间基准：录像里第 i 帧是第几秒。所有评测工具都从这里取时间，不各算各的。

优先级：
1. <录像名>.frames.json（新版 tools/record.py 每一帧记下的真实时刻）
2. 命令行给的 --fps（例如用秒表测出来的真实帧率）
3. mp4 文件头的帧率（可能不准：旧版录制工具固定写 30，而相机实际可能只有 15）——会大声提示
"""
import bisect
import json
import os
import statistics
import sys

import cv2


def sidecar_path(video):
    return os.path.splitext(video)[0] + ".frames.json"


class TimeBase:
    def __init__(self, t, source, fps, note=""):
        self.t = t                  # t[i] = 第 i 帧（从 0 数）的时刻，秒
        self.source = source        # "sidecar" / "fps_override" / "header"
        self.fps = fps              # 真实帧率（中位数），计数参数按它换算
        self.note = note

    def __len__(self):
        return len(self.t)

    def frame_at(self, seconds):
        """第一个时刻 >= seconds 的帧号（从 0 数）。"""
        return bisect.bisect_left(self.t, seconds)

    def describe(self):
        return {"source": self.source, "fps": round(self.fps, 3), "frames": len(self.t), "note": self.note}


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
    if os.path.isfile(side) and not fps_override:
        with open(side, encoding="utf-8") as f:
            s = json.load(f)
        t = [float(x) for x in s["t"]]
        note = ""
        if len(t) != n:
            # 对不上时：多的截掉，少的按中位间隔往后补，并提示
            gaps = [b - a for a, b in zip(t, t[1:]) if b > a]
            step = statistics.median(gaps) if gaps else 1.0 / (fps_hdr or 30.0)
            note = f"时间戳 {len(t)} 帧，录像 {n} 帧，不一致：多的截掉、少的按 {1 / step:.1f} 帧/秒补齐"
            t = t[:n] + [t[-1] + step * (k + 1) for k in range(max(0, n - len(t)))] if t else [k * step for k in range(n)]
            if not quiet:
                print(f"！{os.path.basename(video)}：{note}", file=sys.stderr)
        gaps = [b - a for a, b in zip(t, t[1:]) if 0 < b - a < 1.0]
        fps = 1.0 / statistics.median(gaps) if gaps else float(s.get("fps_measured") or fps_hdr or 30.0)
        return TimeBase(t, "sidecar", fps, note)
    if fps_override:
        return TimeBase([i / fps_override for i in range(n)], "fps_override", float(fps_override),
                        f"按命令行给的 {fps_override} 帧/秒")
    fps = fps_hdr or 30.0
    note = f"没有 {os.path.basename(side)}，按文件头 {fps:g} 帧/秒算时间（旧版录制工具固定写 30，可能不准）"
    if not quiet:
        print(f"！{os.path.basename(video)}：{note}", file=sys.stderr)
    return TimeBase([i / fps for i in range(n)], "header", fps, note)
