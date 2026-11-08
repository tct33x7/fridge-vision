#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次比较多个追踪器：几段视频 × 几个追踪器 × 几套计数参数，多计 / 漏计按视频加总。

每段视频只检测一次（结果缓存在 .raw.npz），所有追踪器用同一份检测结果。

例子（在 demos/yolo_web_counter 下运行）：
  .venv/bin/python tools/compare_trackers.py test_videos/jitter1.mp4 test_videos/light1.mp4 test_videos/mix1.mp4
  .venv/bin/python tools/compare_trackers.py test_videos/synthetic*.mp4
  # 模拟看不到冰箱里面（线在 0.5，里侧只留 10%），比较 default 和 hidden 两套计数参数
  .venv/bin/python tools/compare_trackers.py test_videos/{jitter1,light1,mix1}.mp4 --keep 0.4,0,1,1 --presets default,hidden
"""
import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from counter import PRESETS  # noqa: E402
from replay import detect_raw, raw_class_flips, run_counter, score, track_many  # noqa: E402

DEFAULT_TRACKERS = ["bytetrack", "bytetrack+low", "ocsort", "ocsort-byte+low",
                    "botsort", "botsort-flow0", "botsort+low", "botsort-reid", "ocsort-flow", "deepocsort",
                    "bytetrack-oflow", "ocsort-oflow"]


def main():
    ap = argparse.ArgumentParser(description="比较多个追踪器的多计 / 漏计（按视频加总）")
    ap.add_argument("videos", nargs="+", help="视频；真值文件找 <视频名>.truth.json")
    ap.add_argument("--trackers", default=",".join(DEFAULT_TRACKERS), help="逗号分隔；名字后加 +low = 也用低分框")
    ap.add_argument("--presets", default="baseline,default", help="计数参数，逗号分隔")
    ap.add_argument("--keep", help="只保留画面 x0,y0,x1,y1（归一化），其余涂黑，模拟看不到冰箱里面")
    ap.add_argument("--light", default="off")
    ap.add_argument("--conf", type=float, default=0.35, help="分数 ≥ 这个才能新建轨迹")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--json", help="把每段视频的结果另存为 json")
    a = ap.parse_args()

    specs = a.trackers.split(",")
    presets = a.presets.split(",")
    keep = [float(v) for v in a.keep.split(",")] if a.keep else None
    total = defaultdict(lambda: {"over": 0, "miss": 0, "expected": 0, "relinks": 0})
    stats = defaultdict(lambda: {"ids": 0, "flips": 0, "ms": [], "frames": 0})
    rows = []
    for video in a.videos:
        truth_path = os.path.splitext(video)[0] + ".truth.json"
        if not os.path.isfile(truth_path):
            sys.exit(f"没有真值文件：{truth_path}")
        with open(truth_path, encoding="utf-8") as f:
            truth = json.load(f)
        print(f"[检测] {os.path.basename(video)} …", file=sys.stderr)
        raw = detect_raw(video, a.light, a.imgsz, os.path.dirname(os.path.abspath(video)), keep=keep)
        print(f"[追踪] {len(specs)} 个追踪器 …", file=sys.stderr)
        tracked = track_many(raw, specs, a.conf, video, a.light, keep, quiet=True)
        for s, d in tracked.items():
            flips, ntid = raw_class_flips(d)
            st = stats[s]
            st["ids"] += ntid
            st["flips"] += flips
            st["ms"].append(d["track_ms"])
            st["frames"] += d["frames"]
            for p in presets:
                events, relinks = run_counter(d, PRESETS[p], truth["line"])
                sc = score(events, truth)
                t = total[(s, p)]
                t["over"] += sc["over"]
                t["miss"] += sc["miss"]
                t["expected"] += sc["expected"]
                t["relinks"] += relinks
                rows.append({"video": os.path.basename(video), "tracker": s, "preset": p, "ids": ntid,
                             "flips": flips, "relinks": relinks, "track_ms": d["track_ms"],
                             "over": sc["over"], "miss": sc["miss"], "expected": sc["expected"],
                             "events": [(e["frame"], e["cls"], e["delta"]) for e in events]})

    vids = ", ".join(os.path.splitext(os.path.basename(v))[0] for v in a.videos)
    print()
    print(f"视频：{vids}" + (f"（只保留 {keep}，其余涂黑）" if keep else ""))
    print(f"应有进出：{total[(specs[0], presets[0])]['expected']} 次；多计 / 漏计按视频加总；"
          f"续接 = 计数逻辑替追踪器接上断掉的轨迹的次数（用 {presets[-1]} 时）")
    print()
    head = " | ".join(f"{p} 多计/漏计" for p in presets)
    print(f"| 追踪器 | {head} | 编号总数 | 类别跳变 | 续接 | 追踪每帧 ms |")
    print("| --- | " + " | ".join("---" for _ in presets) + " | --- | --- | --- | --- |")
    for s in specs:
        cells = " | ".join(f"{total[(s, p)]['over']} / {total[(s, p)]['miss']}" for p in presets)
        st = stats[s]
        ms = sum(st["ms"]) / len(st["ms"])
        print(f"| {s} | {cells} | {st['ids']} | {st['flips']} | {total[(s, presets[-1])]['relinks']} | {ms:.1f} |")

    print()
    print(f"逐段视频（{presets[-1]}）：")
    print("| 追踪器 | " + " | ".join(os.path.splitext(os.path.basename(v))[0] for v in a.videos) + " |")
    print("| --- | " + " | ".join("---" for _ in a.videos) + " |")
    for s in specs:
        cells = []
        for v in a.videos:
            r = next(r for r in rows if r["video"] == os.path.basename(v) and r["tracker"] == s
                     and r["preset"] == presets[-1])
            cells.append(f"{r['over']} / {r['miss']}（{r['ids']} 个编号）")
        print(f"| {s} | " + " | ".join(cells) + " |")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
