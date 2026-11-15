#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按"画面在动"把一段长录像切成候选窗口，每个窗口出一张缩略图拼图，方便人对照着给真值里的动作填窗口编号。
它只是个方便工具：窗口可以不用它，直接在真值里手写 start_s / end_s。

  python eval/propose_windows.py 录像.mp4                       # 写 <录像名>.windows.json 和 <录像名>_windows/ 拼图
  python eval/propose_windows.py 录像.mp4 --boxes 录像.light-off.conf-0.35.img-640.dets.json   # 拼图上画检测框（勾"② 框到"用）
  python eval/propose_windows.py 录像.mp4 --plain                # 拼图上什么都不画（给同学盲标用）

然后在真值里给每个动作写 "window": 编号（一个动作跨两个窗口就写 [3, 4]），
秒表、筷子这些不算的窗口写进 "ignore_windows": [1, 2]。

怎么切：每 0.1 秒取一帧，缩成 160 像素宽的灰度图，和上一张比，变化超过 --diff 的像素占比 > --thresh 就算"在动"。
连续在动的段，间隔小于 --gap 秒的合并，短于 --min-len 秒的丢掉，前后各放宽 --pad 秒。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timebase  # noqa: E402


def motion_series(video, tb, step_s=0.1, diff=20, roi=None):
    cap = cv2.VideoCapture(video)
    prev, out = None, []
    next_t, i = 0.0, -1
    while True:
        ok = cap.grab()
        if not ok:
            break
        i += 1
        if i >= len(tb) or tb.t[i] < next_t:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        next_t = tb.t[i] + step_s
        h, w = frame.shape[:2]
        if roi:
            frame = frame[int(roi[1] * h):int(roi[3] * h), int(roi[0] * w):int(roi[2] * w)]
        small = cv2.resize(frame, (160, max(1, round(160 * frame.shape[0] / frame.shape[1]))))
        g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if prev is not None:
            out.append((tb.t[i], i, float((cv2.absdiff(g, prev) > diff).mean())))
        prev = g
    cap.release()
    return out


def segments(series, thresh, gap, min_len, pad, t_end):
    segs, cur = [], None
    for t, i, m in series:
        if m > thresh:
            if cur and t - cur[1] <= gap:
                cur[1] = t
                cur[2] = max(cur[2], m)
            else:
                if cur:
                    segs.append(cur)
                cur = [t, t, m]
    if cur:
        segs.append(cur)
    wins = []
    for s, e, peak in segs:
        if e - s < min_len:
            continue
        wins.append({"n": len(wins) + 1, "start_s": round(max(0.0, s - pad), 2),
                     "end_s": round(min(t_end, e + pad), 2), "peak_motion": round(peak, 3)})
    return wins


def draw_boxes(frame, dets, line):
    for tid, cls, p, x1, y1, x2, y2 in dets:
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (60, 220, 60), 3)
        cv2.putText(frame, f"{cls} #{tid}", (int(x1), max(20, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (60, 220, 60), 2)
    if line:
        h, w = frame.shape[:2]
        cv2.line(frame, (int(line[0] * w), int(line[1] * h)), (int(line[2] * w), int(line[3] * h)), (0, 140, 255), 3)


def contact_sheets(video, tb, wins, out_dir, per_sheet=8, boxes=None, line=None, plain=False):
    os.makedirs(out_dir, exist_ok=True)
    want = {}
    for w in wins:
        f0, f1 = tb.frame_at(w["start_s"]), max(tb.frame_at(w["start_s"]) + 1, tb.frame_at(w["end_s"]))
        idx = sorted(set(np.linspace(f0, f1 - 1, per_sheet).round().astype(int).tolist()))
        w["_frames"] = idx
        for k in idx:
            want.setdefault(k, []).append(w["n"])
    grabbed = {}
    cap = cv2.VideoCapture(video)
    i = -1
    last = max(want) if want else -1
    while i < last:
        if not cap.grab():
            break
        i += 1
        if i in want:
            ok, frame = cap.retrieve()
            if ok:
                if boxes is not None and i < len(boxes) and not plain:
                    draw_boxes(frame, boxes[i], line)
                elif line and not plain:
                    draw_boxes(frame, [], line)
                th = cv2.resize(frame, (480, round(480 * frame.shape[0] / frame.shape[1])))
                cv2.putText(th, f"{tb.t[i]:.1f}s", (8, th.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                            (0, 255, 255), 2)
                grabbed[i] = th
    cap.release()
    paths = []
    for w in wins:
        tiles = [grabbed[k] for k in w.pop("_frames") if k in grabbed]
        if not tiles:
            continue
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[r:r + 4]) for r in range(0, len(tiles), 4)]
        sheet = np.vstack(rows)
        bar = np.zeros((44, sheet.shape[1], 3), np.uint8)
        cv2.putText(bar, f"window {w['n']}: {w['start_s']:.1f}-{w['end_s']:.1f}s", (10, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        name = f"w{w['n']:02d}_{w['start_s']:.1f}-{w['end_s']:.1f}s.jpg"
        cv2.imwrite(os.path.join(out_dir, name), np.vstack([bar, sheet]), [cv2.IMWRITE_JPEG_QUALITY, 80])
        w["sheet"] = name
        paths.append(name)
    return paths


def main():
    ap = argparse.ArgumentParser(description="把长录像切成候选动作窗口，并出缩略图拼图")
    ap.add_argument("video")
    ap.add_argument("--truth", help="真值（只用来取计数线画在图上）；默认 <录像名>.truth.json")
    ap.add_argument("--fps", type=float, help="没有 .frames.json 时的真实帧率")
    ap.add_argument("--thresh", type=float, default=0.02, help="变化像素占比超过它算在动（默认 0.02）")
    ap.add_argument("--diff", type=int, default=20, help="灰度差超过它算这个像素变了")
    ap.add_argument("--gap", type=float, default=2.5, help="间隔小于这么多秒的两段合并")
    ap.add_argument("--min-len", type=float, default=0.6, help="短于这么多秒的段丢掉")
    ap.add_argument("--pad", type=float, default=0.5, help="每段前后各放宽这么多秒")
    ap.add_argument("--roi", help="只看画面里 x0,y0,x1,y1（归一化）这块")
    ap.add_argument("--boxes", help="检测缓存（*.dets.json），拼图上画框")
    ap.add_argument("--plain", action="store_true", help="拼图上什么都不画（盲标用）")
    ap.add_argument("--out", help="窗口文件；默认 <录像名>.windows.json")
    a = ap.parse_args()

    tb = timebase.load(a.video, fps_override=a.fps)
    roi = [float(v) for v in a.roi.split(",")] if a.roi else None
    series = motion_series(a.video, tb, diff=a.diff, roi=roi)
    wins = segments(series, a.thresh, a.gap, a.min_len, a.pad, tb.t[-1])
    truth_path = a.truth or os.path.splitext(a.video)[0] + ".truth.json"
    line = None
    if os.path.isfile(truth_path):
        line = json.load(open(truth_path, encoding="utf-8")).get("line")
    boxes = json.load(open(a.boxes, encoding="utf-8"))["dets"] if a.boxes else None
    stem = os.path.splitext(a.video)[0]
    out_dir = stem + ("_windows_plain" if a.plain else "_windows")
    contact_sheets(a.video, tb, wins, out_dir, boxes=boxes, line=line, plain=a.plain)
    out = {"video": os.path.basename(a.video), "time_base": tb.describe(),
           "params": {"thresh": a.thresh, "diff": a.diff, "gap": a.gap, "min_len": a.min_len, "pad": a.pad,
                      "roi": roi, "step_s": 0.1},
           "windows": wins}
    path = a.out or stem + ".windows.json"
    if a.plain and os.path.isfile(path) and not a.out:
        path = stem + ".windows_plain.json"     # 盲标用的不要盖掉正式的窗口文件
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write(f"# {os.path.basename(a.video)} 的候选窗口（{len(wins)} 个）\n\n")
        f.write("| 窗口 | 开始 | 结束 | 时长 | 图 |\n| --- | --- | --- | --- | --- |\n")
        for w in wins:
            f.write(f"| {w['n']} | {w['start_s']:.1f}s | {w['end_s']:.1f}s | {w['end_s'] - w['start_s']:.1f}s | "
                    f"![]({w.get('sheet', '')}) |\n")
    print(f"时间基准：{tb.source}（{tb.fps:.1f} 帧/秒）。找到 {len(wins)} 个窗口，写在 {path}，拼图在 {out_dir}/")
    for w in wins:
        print(f"  窗口 {w['n']:2d}：{w['start_s']:7.1f} – {w['end_s']:7.1f} 秒（{w['end_s'] - w['start_s']:.1f} 秒）")


if __name__ == "__main__":
    main()
