#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从一段录像里按时间随机抽 N 帧（默认 40），拼成几张大图，给人数"有几帧拍到了脸"这类是非题用（E03 选机位）。

  python eval/sample_frames.py 录像.mp4                         # 整段里抽 40 帧
  python eval/sample_frames.py 录像.mp4 --start 30 --end 250    # 只在 30–250 秒之间抽（去掉开头结尾的秒表、筷子）
  python eval/sample_frames.py 录像.mp4 --seed 2                # 换一组

先在每秒一帧里随机挑（不重复），再按时间排好，每帧左下角写编号和时间。种子写进输出文件名，可以重现。
数之前先写好"什么算有脸"（例如：能看到眼睛或嘴的任何一部分就算）。
"""
import argparse
import os
import random
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timebase  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="随机抽帧拼图（数脸、看门格用）")
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--start", type=float, help="从第几秒开始抽")
    ap.add_argument("--end", type=float, help="抽到第几秒")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fps", type=float, help="没有 .frames.json 时的真实帧率")
    ap.add_argument("--per-sheet", type=int, default=20, help="每张大图放几帧（4 列）")
    a = ap.parse_args()

    tb = timebase.load(a.video, fps_override=a.fps)
    t0 = a.start if a.start is not None else tb.t[0]
    t1 = a.end if a.end is not None else tb.t[-1]
    # 每个"真的录到了画面"的整秒取第一帧当候选（暂停的那几秒没有画面，不算）
    first = {}
    for i, t in enumerate(tb.t):
        if t0 <= t <= t1:
            first.setdefault(int(t), i)
    if len(first) < a.n:
        sys.exit(f"{t0:.0f}–{t1:.0f} 秒里只有 {len(first)} 个整秒录到了画面，不够抽 {a.n} 帧")
    picks = sorted(random.Random(a.seed).sample(sorted(first), a.n))
    want = {first[s]: s for s in picks}

    tiles = []
    cap = cv2.VideoCapture(a.video)
    i = -1
    last = max(want)
    while i < last:
        if not cap.grab():
            break
        i += 1
        if i in want:
            ok, frame = cap.retrieve()
            if not ok:
                continue
            th = cv2.resize(frame, (400, round(400 * frame.shape[0] / frame.shape[1])))
            k = len(tiles) + 1
            cv2.putText(th, f"#{k}  {tb.t[i]:.0f}s", (8, th.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 255, 255), 2)
            tiles.append(th)
    cap.release()
    stem = os.path.splitext(a.video)[0]
    out = []
    for s in range(0, len(tiles), a.per_sheet):
        chunk = tiles[s:s + a.per_sheet]
        while len(chunk) % 4:
            chunk.append(np.zeros_like(chunk[0]))
        sheet = np.vstack([np.hstack(chunk[r:r + 4]) for r in range(0, len(chunk), 4)])
        path = f"{stem}.sample{a.n}-seed{a.seed}-{s // a.per_sheet + 1}.jpg"
        cv2.imwrite(path, sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        out.append(path)
    print(f"从 {t0:.0f}–{t1:.0f} 秒随机抽了 {len(tiles)} 帧（种子 {a.seed}，时间基准 {tb.source}），拼成 {len(out)} 张：")
    for p in out:
        print(f"  {p}")


if __name__ == "__main__":
    main()
