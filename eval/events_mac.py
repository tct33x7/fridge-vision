#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac 路线：YOLO11s + ultralytics ByteTrack（检测结果缓存，和 replay.py 共用）+ demos/yolo_web_counter/counter.py，
按真值里每个动作的时间窗口分别计数，输出事件文件（*.events.json），给 eval/score_actions.py 打分。

  python eval/events_mac.py 录像.mp4 --truth 录像.truth.json                 # 默认 default 规则、只排除 person
  python eval/events_mac.py 录像.mp4 --truth 录像.truth.json --exclude board  # 用板子上的 61 类排除名单
  python eval/events_mac.py 录像.mp4 --truth 录像.truth.json --windows whole  # 整段一个窗口（和 replay.py 对照用）

要点：
- 时间按 eval/timebase.py：有 .frames.json 用真实时间，没有就按文件头（会提示）。
- 计数规则里按"帧"写的参数是在 30 帧/秒上定的，这里和板子一样按真实帧率等比例换算
  （relink_frames、track_timeout、cooldown_frames、confirm_frames、birth_frames）。
- 每个动作窗口单独新建计数器，窗口结束时按"关门"收尾（finish）。所以这条路线**假设开门检测是完美的**：
  动作之间不计数，不会有"窗口外的误计"。开门检测造成的误计要看板子路线（simulate_counter.py --events-json）。
- 另外记下每个窗口里"有没有任何轨迹（任意类别）从线的一边走到另一边"，作为"② 检测器框到"的自动参考（只是代理）。
"""
import argparse
import ast
import json
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEMO = os.path.join(REPO, "demos", "yolo_web_counter")
sys.path.insert(0, DEMO)
sys.path.insert(0, HERE)

import timebase  # noqa: E402
from counter import PRESETS, LineCounter, make_gate  # noqa: E402

FRAME_FIELDS = ("relink_frames", "track_timeout", "cooldown_frames", "confirm_frames", "birth_frames")
BOARD_SERVICE = os.path.join(REPO, "orangepi_app", "app", "services", "counter_service.py")


def board_exclude_classes():
    """从板子代码里直接读出 EXCLUDE_CLASSES（不导入整个程序），保证和板子一致。"""
    tree = ast.parse(open(BOARD_SERVICE, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "EXCLUDE_CLASSES" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise SystemExit(f"在 {BOARD_SERVICE} 里没找到 EXCLUDE_CLASSES")


def scaled_config(preset, fps):
    cfg = PRESETS[preset]
    k = max(float(fps), 1.0) / 30.0
    return replace(cfg, **{f: (max(1, round(getattr(cfg, f) * k)) if getattr(cfg, f) > 0 else 0)
                           for f in FRAME_FIELDS})


def git_rev(path):
    try:
        rev = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", path, "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return rev + ("+未提交改动" if dirty else "")
    except Exception:
        return "?"


def versions():
    v = {"python": platform.python_version()}
    for mod in ("ultralytics", "torch", "cv2", "numpy"):
        try:
            v[mod] = __import__(mod).__version__
        except Exception:
            v[mod] = "?"
    return v


def crossing_tracks(frames, gate, margin=6.0):
    """窗口里哪些轨迹（任意类别）的中心从线的一边到了另一边（离线都超过 margin 像素）。"""
    ax, ay, _, _, _, _, nx, ny = gate
    lo, hi, classes = {}, {}, defaultdict(Counter)
    for dets in frames:
        for tid, cls, p, x1, y1, x2, y2 in dets:
            proj = ((x1 + x2) / 2 - ax) * nx + ((y1 + y2) / 2 - ay) * ny
            lo[tid] = min(lo.get(tid, proj), proj)
            hi[tid] = max(hi.get(tid, proj), proj)
            classes[tid][cls] += 1
    return [{"tid": t, "cls": classes[t].most_common(1)[0][0]} for t in lo if lo[t] < -margin and hi[t] > margin]


def main():
    ap = argparse.ArgumentParser(description="Mac 路线：按动作窗口计数，输出事件文件")
    ap.add_argument("video")
    ap.add_argument("--truth", help="真值（要有每个动作的时间）；默认 <录像名>.truth.json")
    ap.add_argument("--line", help="计数线 ax,ay,bx,by（归一化，A→B 左侧为 +1 放入）；默认用真值里的")
    ap.add_argument("--preset", default="default", choices=sorted(PRESETS))
    ap.add_argument("--exclude", default="pc", choices=["pc", "board"],
                    help="pc = 只去掉 person（和 demo 一样）；board = 板子上的排除名单（61 类）")
    ap.add_argument("--windows", default="truth", choices=["truth", "whole"])
    ap.add_argument("--fps", type=float, help="没有 .frames.json 时，用这个真实帧率算时间（比如秒表测的）")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--pre", type=float, default=0.5, help="窗口开始前多算几秒")
    ap.add_argument("--post", type=float, default=1.0, help="窗口结束后多算几秒")
    ap.add_argument("--cache-dir", help="检测缓存放哪；默认和录像同一个文件夹")
    ap.add_argument("--out", help="事件文件；默认 <录像名>.mac-<preset>-<exclude>.events.json")
    a = ap.parse_args()

    import replay  # noqa: E402  （demos/yolo_web_counter/replay.py：检测 + 缓存）
    from score_actions import resolve_windows  # noqa: E402

    truth_path = a.truth or os.path.splitext(a.video)[0] + ".truth.json"
    truth = json.load(open(truth_path, encoding="utf-8")) if os.path.isfile(truth_path) else {}
    line = [float(v) for v in a.line.split(",")] if a.line else truth.get("line")
    if not line:
        sys.exit("需要计数线：--line ax,ay,bx,by，或在真值里写 \"line\"")

    cache_dir = a.cache_dir or os.path.dirname(os.path.abspath(a.video))
    d = replay.detect(a.video, "off", a.conf, a.imgsz, cache_dir)
    tb = timebase.load(a.video, fps_override=a.fps, n_frames=d["frames"])
    cfg = scaled_config(a.preset, tb.fps)
    excl = board_exclude_classes() if a.exclude == "board" else {"person"}
    frames = [[x for x in dets if x[1] not in excl] for dets in d["dets"]]
    raw_frames = d["dets"]   # 只去掉了 person 的（缓存里本来就没有 person）
    gate = make_gate(line, d["w"], d["h"])
    if gate is None:
        sys.exit(f"计数线太短：{line}")

    if a.windows == "whole":
        wins = [{"n": 1, "start_s": tb.t[0], "end_s": tb.t[-1]}]
        pre = post = 0.0
    else:
        if not truth.get("actions"):
            sys.exit(f"真值 {truth_path} 里没有 actions；整段跑请加 --windows whole")
        actions, _ = resolve_windows(truth, truth_path)
        wins = sorted(({"n": x.get("n", i + 1), "start_s": x["start_s"], "end_s": x["end_s"]}
                       for i, x in enumerate(actions)), key=lambda w: w["start_s"])
        pre, post = a.pre, a.post

    events, win_info = [], []
    N = len(frames)
    for w in wins:
        f0 = tb.frame_at(w["start_s"] - pre)
        f1 = min(N, tb.frame_at(w["end_s"] + post) + 1)
        lc = LineCounter(cfg)
        for i in range(f0, f1):
            ev, _ = lc.update([tuple(x) for x in frames[i]], i + 1, gate)
            events.extend((w["n"], e) for e in ev)
        events.extend((w["n"], e) for e in lc.finish(f1))
        win_info.append({**w, "frames": [f0, f1],
                         "crossing_tracks_any_class": crossing_tracks(raw_frames[f0:f1], gate)})

    out_events = [{"t": round(tb.t[min(e["frame"], N) - 1], 3), "delta": e["delta"], "cls": e["cls"],
                   "tid": e["tid"], "frame": e["frame"], "window": wn} for wn, e in events]
    for wi in win_info:
        for c in wi["crossing_tracks_any_class"]:
            c["excluded"] = c["cls"] in excl
    route = f"mac-yolo11s-{a.preset}-{a.exclude}" + ("-whole" if a.windows == "whole" else "")
    out = {
        "schema": "events-v1",
        "video": os.path.basename(a.video),
        "route": route,
        "time_base": tb.describe(),
        "provenance": {
            "detector": f"yolo11s.pt conf={a.conf} imgsz={a.imgsz} device={d.get('device')}",
            "detections_cache": f"{d['video']} light=off（replay.py 的缓存）",
            "tracker": "ultralytics bytetrack.yaml",
            "counter": f"demos/yolo_web_counter/counter.py @ {git_rev(DEMO)}",
            "preset": a.preset, "config_scaled_to_fps": round(tb.fps, 3), "config": asdict(cfg),
            "exclude": f"{a.exclude}（{len(excl)} 类）",
            "line": line, "windows": a.windows, "pre_s": pre, "post_s": post,
            "assumes": "开门检测完美：只在动作窗口里计数" if a.windows == "truth" else "整段连续计数",
            "versions": versions(), "made_by": f"eval/events_mac.py @ {git_rev(HERE)}",
            "made_at": datetime.now().isoformat(timespec="seconds"),
        },
        "windows": win_info,
        "events": out_events,
    }
    path = a.out or f"{os.path.splitext(a.video)[0]}.{route.replace('mac-yolo11s', 'mac')}.events.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已写 {path}：{len(wins)} 个窗口，{len(out_events)} 个计数事件；时间基准 {tb.source}（{tb.fps:.1f} 帧/秒）")


if __name__ == "__main__":
    main()
