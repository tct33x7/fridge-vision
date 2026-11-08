#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无界面重放：拿一段录好的视频，跑 YOLO11s + ByteTrack，再用不同的计数参数各算一遍，
和真值比较"多计 / 漏计 / 类别跳变"。

YOLO 的检测结果会缓存成 .dets.json，换计数参数再跑时不用重新检测，
而且保证"优化前 / 优化后"用的是一模一样的检测结果，比较才公平。

例子：
  python replay.py test_videos/synthetic.mp4                         # 真值文件自动找 synthetic.truth.json
  python replay.py test_videos/my1.mp4 --truth test_videos/my1.truth.json --light gain
  python replay.py test_videos/my1.mp4 --ablate                      # 逐项开关每个优化，看各自作用
  python replay.py test_videos/my1.mp4 --save-video out.mp4 --preset default   # 导出带框的视频

真值文件（自己录的视频手写一个就行）：
  {"line": [0.5, 0.0, 0.5, 1.0],
   "expected": {"bottle": {"in": 3, "out": 2}, "apple": {"in": 1, "out": 1}}}
line 是归一化坐标 A(x,y)→B(x,y)，A→B 方向的左侧为 +1 "进入"，和网页上拖线一样。
网页上画好线后，访问 http://localhost:8020/api/state 可以看到 "line" 的数字，抄过来即可。
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace

import cv2

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from counter import PRESETS, LineCounter, make_gate, normalize_light  # noqa: E402

EXCLUDE_CLASSES = {"person"}


# ---------------- 第一步：检测（带缓存） ----------------

def apply_keep(frame, keep):
    """只保留 keep=(x0, y0, x1, y1)（归一化）这块区域，其余涂黑。用来模拟"看不到冰箱里面"。"""
    if not keep:
        return frame
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = int(keep[0] * W), int(keep[1] * H), int(keep[2] * W), int(keep[3] * H)
    out = frame.copy()
    out[:, :x0] = 0
    out[:, x1:] = 0
    out[:y0, :] = 0
    out[y1:, :] = 0
    return out


def detect(video, light, conf, imgsz, cache_dir, max_frames=None, quiet=False, keep=None):
    base = os.path.splitext(os.path.basename(video))[0]
    ktag = ".keep-" + "_".join(f"{v:g}" for v in keep) if keep else ""
    cache = os.path.join(cache_dir, f"{base}.light-{light}.conf-{conf}.img-{imgsz}{ktag}.dets.json")
    if os.path.isfile(cache) and os.path.getmtime(cache) >= os.path.getmtime(video):
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if max_frames is None or d["frames"] <= max_frames:
            return d

    import torch
    from ultralytics import YOLO
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model_path = os.path.join(ROOT, "models", "yolo11s.pt")
    model = YOLO(model_path)
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        sys.exit(f"打不开视频：{video}")
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok or (max_frames and len(frames) >= max_frames):
            break
        frame = normalize_light(apply_keep(frame, keep), light)
        r = model.track(frame, persist=True, tracker="bytetrack.yaml", conf=conf,
                        imgsz=imgsz, device=device, verbose=False)[0]
        dets = []
        if r.boxes is not None and r.boxes.id is not None:
            for (x1, y1, x2, y2), tid, cid, p in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.id.int().cpu().numpy(),
                                                     r.boxes.cls.int().cpu().numpy(), r.boxes.conf.cpu().numpy()):
                name = model.names[int(cid)]
                if name in EXCLUDE_CLASSES:
                    continue
                dets.append([int(tid), name, round(float(p), 3),
                             round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1)])
        frames.append(dets)
        if not quiet and len(frames) % 100 == 0:
            print(f"  检测中 {len(frames)}/{total} 帧 ({len(frames) / (time.time() - t0):.1f} 帧/秒)", file=sys.stderr)
    cap.release()
    d = {"video": os.path.basename(video), "light": light, "conf": conf, "imgsz": imgsz, "keep": keep,
         "w": W, "h": H, "fps": fps, "frames": len(frames), "dets": frames, "device": device,
         "sec_per_frame": round((time.time() - t0) / max(1, len(frames)), 4)}
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    return d


# ---------------- 第二步：计数 ----------------

# 压力测试用：相近类别（模拟 YOLO 在 bottle / cup 之间来回跳）
CONFUSABLE = {"bottle": "cup", "cup": "bottle", "vase": "bottle", "wine glass": "cup",
              "apple": "orange", "orange": "apple", "banana": "hot dog", "bus": "truck",
              "truck": "bus", "car": "truck", "tie": "umbrella", "umbrella": "tie"}


def add_class_noise(d, rate, seed=0):
    """把一部分检测框的类别换成相近类别（只在 --class-noise 时用，结果另列）。"""
    import random
    rnd = random.Random(seed)
    out = dict(d)
    out["dets"] = [[[x[0], CONFUSABLE.get(x[1], "other") if rnd.random() < rate else x[1], *x[2:]]
                    for x in dets] for dets in d["dets"]]
    return out


def run_counter(d, cfg, line):
    gate = make_gate(line, d["w"], d["h"])
    lc = LineCounter(cfg)
    events = []
    for i, dets in enumerate(d["dets"], start=1):
        ev, _ = lc.update([tuple(x) for x in dets], i, gate)
        events.extend(ev)
    events.extend(lc.finish(len(d["dets"])))      # 视频结束 = 关门：等确认的按最后一边算
    return events, lc.relinks


def raw_class_flips(d):
    """原始检测里，同一编号的类别前后不一样的次数（计数逻辑之前的"类别跳变"）。"""
    last, flips, tids = {}, 0, set()
    for dets in d["dets"]:
        for tid, cls, *_ in dets:
            tids.add(tid)
            if tid in last and last[tid] != cls:
                flips += 1
            last[tid] = cls
    return flips, len(tids)


def score(events, truth, slack=10):
    """
    有分段真值（合成视频）时逐段算：段内方向和类别都对的事件算"计对"，段内多出来的算"多计"，
    该有没有的算"漏计"。没有分段时（自己录的视频）按 类别×方向 的总数比较。
    """
    exp = truth.get("expected", {})
    n_exp = sum(v.get("in", 0) + v.get("out", 0) for v in exp.values())
    got = defaultdict(lambda: {"in": 0, "out": 0})
    for e in events:
        got[e["cls"]]["in" if e["delta"] > 0 else "out"] += 1
    net_ok = all(got[c]["in"] - got[c]["out"] == exp.get(c, {}).get("in", 0) - exp.get(c, {}).get("out", 0)
                 for c in set(got) | set(exp))
    segs = truth.get("segments")
    if segs:
        correct = over = miss = 0
        used = set()
        for s in segs:
            evs = [i for i, e in enumerate(events) if s["start"] <= e["frame"] <= s["end"] + slack]
            used.update(evs)
            need = abs(s["delta"])
            good = sum(1 for i in evs if events[i]["cls"] == s["cls"] and events[i]["delta"] == (1 if s["delta"] > 0 else -1))
            c = min(good, need)
            correct += c
            miss += need - c
            over += len(evs) - c
        over += len(events) - len(used)          # 不在任何段里的事件也算多计
    else:
        over = miss = 0
        for cls in set(got) | set(exp):
            for k in ("in", "out"):
                g, x = got[cls][k], exp.get(cls, {}).get(k, 0)
                over += max(0, g - x)
                miss += max(0, x - g)
        correct = n_exp - miss
    return {"events": len(events), "expected": n_exp, "correct": correct,
            "over": over, "miss": miss, "net_ok": net_ok, "got": {k: dict(v) for k, v in got.items()}}


def score_segments(events, truth, slack=10):
    """合成视频有分段真值时，逐段看对没对。"""
    rows = []
    for s in truth.get("segments", []):
        evs = [e for e in events if s["start"] <= e["frame"] <= s["end"] + slack]
        ok = len(evs) == abs(s["delta"]) and all(
            e["cls"] == s["cls"] and e["delta"] == (1 if s["delta"] > 0 else -1) for e in evs)
        rows.append({"name": s["name"], "cls": s["cls"], "truth": s["delta"],
                     "events": "".join(("+" if e["delta"] > 0 else "-") + e["cls"][:3] for e in evs) or "·",
                     "ok": ok})
    return rows


# ---------------- 导出带框视频（看哪里出错用） ----------------

def save_video(video, d, cfg, line, out, light, keep=None):
    cap = cv2.VideoCapture(video)
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), d["fps"], (d["w"], d["h"]))
    gate = make_gate(line, d["w"], d["h"])
    lc = LineCounter(cfg)
    counts = Counter()
    for i, dets in enumerate(d["dets"], start=1):
        ok, frame = cap.read()
        if not ok:
            break
        frame = normalize_light(apply_keep(frame, keep), light)
        ev, vis = lc.update([tuple(x) for x in dets], i, gate)
        for e in ev:
            counts[e["cls"]] += e["delta"]
        for tid, cls, p, x1, y1, x2, y2 in dets:
            t = vis.get(tid)
            lab = f"{lc.label(t) if t else cls} #{tid} {p:.2f}"
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (60, 200, 60), 2)
            cv2.putText(frame, lab, (int(x1), max(15, int(y1) - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 200, 60), 2)
        if gate:
            ax, ay, bx, by, ux, uy, nx, ny = gate
            cv2.line(frame, (int(ax - ux * 2000), int(ay - uy * 2000)),
                     (int(ax + ux * 2000), int(ay + uy * 2000)), (0, 140, 255), 2)
        txt = f"#{i}  " + "  ".join(f"{k}:{v:+d}" for k, v in counts.items())
        cv2.putText(frame, txt, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        for e in ev:
            cv2.putText(frame, f"{'+1' if e['delta'] > 0 else '-1'} {e['cls']}", (12, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        vw.write(frame)
    vw.release()
    cap.release()


# ---------------- 主程序 ----------------

ABLATE_KEYS = {
    "滞回带随目标变宽": {"hysteresis_box": 0.0},
    "中心点平滑": {"smooth_alpha": 1.0},
    "最短轨迹": {"min_frames": 0},
    "冷却": {"cooldown_frames": 0},
    "类别投票": {"class_vote": False},
    "丢失后续接": {"relink_frames": 0},
    "事后改类别": {"revote": False},
    "确认时间": {"confirm_frames": 0},
}
# 不在 default 里、单独试的规则：--try-rules 时在 default 上逐个打开
TRY_RULES = {
    "出现消失按中心所在边": {"endpoints": True},
    "只续接动过的": {"relink_moved_only": True},
    "要求移动半个框宽": {"min_travel": 0.5},
    "三条都开": {"endpoints": True, "relink_moved_only": True, "min_travel": 0.5},
}


def main():
    ap = argparse.ArgumentParser(description="重放视频，比较不同计数参数的多计/漏计")
    ap.add_argument("video")
    ap.add_argument("--truth", help="真值 json；默认找 <视频名>.truth.json")
    ap.add_argument("--line", help="计数线 ax,ay,bx,by（归一化）；默认用真值文件里的")
    ap.add_argument("--preset", default="baseline,default", help="逗号分隔，默认 baseline,default")
    ap.add_argument("--light", default="off", help="亮度处理 off/gain/clahe，逗号分隔可一次比较多个")
    ap.add_argument("--keep", help="只保留画面里 x0,y0,x1,y1（归一化）这块，其余涂黑再检测。"
                                   "模拟看不到冰箱里面，例如线在 0.5、里侧只留 0.1：--keep 0.4,0,1,1")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--cache-dir", help="检测缓存放哪；默认和视频同一个文件夹")
    ap.add_argument("--max-frames", type=int)
    ap.add_argument("--ablate", action="store_true", help="逐项关掉 / 单独打开每个优化，看各自作用")
    ap.add_argument("--try-rules", action="store_true", help="在 default 上逐个试 看不到冰箱里面时用的规则")
    ap.add_argument("--segments", action="store_true", help="逐段显示结果（真值里有 segments 时）")
    ap.add_argument("--save-video", help="导出带框和计数的视频（用第一个 preset 和第一个 light）")
    ap.add_argument("--class-noise", type=float, default=0.0,
                    help="压力测试：随机把这个比例的检测框换成相近类别（如 0.2），模拟类别跳变")
    ap.add_argument("--json", help="把结果另存为 json")
    a = ap.parse_args()

    truth_path = a.truth or os.path.splitext(a.video)[0] + ".truth.json"
    truth = {}
    if os.path.isfile(truth_path):
        with open(truth_path, encoding="utf-8") as f:
            truth = json.load(f)
    else:
        print(f"（没找到真值 {truth_path}，只列出计数事件，不算多计/漏计）")
    line = [float(v) for v in a.line.split(",")] if a.line else truth.get("line")
    if not line:
        sys.exit("需要计数线：--line ax,ay,bx,by 或在真值文件里写 \"line\"")
    cache_dir = a.cache_dir or os.path.dirname(os.path.abspath(a.video))
    keep = [float(v) for v in a.keep.split(",")] if a.keep else None
    if keep:
        print(f"（只保留画面 {keep}，其余涂黑）")

    runs = []   # (名字, light, cfg)
    lights = a.light.split(",")
    for light in lights:
        for p in a.preset.split(","):
            runs.append((p if len(lights) == 1 else f"{p}+{light}", light, PRESETS[p]))
    if a.ablate:
        base, full = PRESETS["baseline"], PRESETS["default"]
        for name, off in ABLATE_KEYS.items():
            on = {k: getattr(full, k) for k in off}
            if name == "丢失后续接":
                on["relink_dist"] = full.relink_dist
            if name == "事后改类别":
                on["class_vote"] = True
            runs.append((f"baseline + 只开「{name}」", lights[0], replace(base, **on)))
        for name, off in ABLATE_KEYS.items():
            runs.append((f"default − 关掉「{name}」", lights[0], replace(full, **off)))

    if a.try_rules:
        for name, on in TRY_RULES.items():
            runs.append((f"default + 「{name}」", lights[0], replace(PRESETS["default"], **on)))

    dets = {}
    for light in lights:
        print(f"[检测] light={light} …", file=sys.stderr)
        dets[light] = detect(a.video, light, a.conf, a.imgsz, cache_dir, a.max_frames, keep=keep)
        if a.class_noise > 0:
            dets[light] = add_class_noise(dets[light], a.class_noise)
            print(f"[压力测试] 已把 {a.class_noise:.0%} 的检测框换成相近类别", file=sys.stderr)

    results = []
    print()
    print(f"视频：{a.video}   帧数：{dets[lights[0]]['frames']}   计数线：{line}")
    if truth.get("expected"):
        print(f"真值：{json.dumps(truth['expected'], ensure_ascii=False)}")
    for light in lights:
        flips, ntid = raw_class_flips(dets[light])
        print(f"原始检测（light={light}）：{ntid} 个追踪编号，类别跳变 {flips} 次，"
              f"每帧 {dets[light]['sec_per_frame'] * 1000:.0f} ms（{dets[light]['device']}）")
    print()
    if truth.get("segments"):
        print("（有分段真值：按段计分，类别错也算多计 + 漏计）")
    print("| 方案 | 计数事件 | 应有 | 计对 | 多计 | 漏计 | 净数正确 | 续接 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, light, cfg in runs:
        events, relinks = run_counter(dets[light], cfg, line)
        s = score(events, truth) if truth.get("expected") else {"events": len(events)}
        results.append({"name": name, "light": light, "cfg": asdict(cfg), "score": s,
                        "events": events, "relinks": relinks,
                        "segments": score_segments(events, truth)})
        if truth.get("expected"):
            print(f"| {name} | {s['events']} | {s['expected']} | {s['correct']} | {s['over']} | {s['miss']} | "
                  f"{'是' if s['net_ok'] else '否'} | {relinks} |")
        else:
            print(f"| {name} | {len(events)} | | | | | | {relinks} |")

    if a.segments and truth.get("segments"):
        main_runs = [r for r in results if not r["name"].startswith(("baseline +", "default −", "default +"))]
        print()
        print("| 段 | 物品 | 真值 | " + " | ".join(r["name"] for r in main_runs) + " |")
        print("| --- | --- | --- | " + " | ".join("---" for _ in main_runs) + " |")
        for i, s in enumerate(truth["segments"]):
            cells = [("✓ " if r["segments"][i]["ok"] else "✗ ") + r["segments"][i]["events"] for r in main_runs]
            print(f"| {i + 1}. {s['name']} | {s['cls']} | {s['delta']:+d} | " + " | ".join(cells) + " |")

    if not truth.get("expected"):
        for r in results:
            print(f"\n[{r['name']}] 事件：")
            for e in r["events"]:
                print(f"  第 {e['frame']} 帧  {'+1' if e['delta'] > 0 else '-1'}  {e['cls']}  (#{e['tid']})")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    if a.save_video:
        name, light, cfg = runs[0]
        save_video(a.video, dets[light], cfg, line, a.save_video, light, keep)
        print(f"\n已导出 {a.save_video}（{name}）")


if __name__ == "__main__":
    main()
