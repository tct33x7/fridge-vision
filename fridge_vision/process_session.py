#!/usr/bin/env python3
"""关门后的离线处理：从录好的会话里切出"手的动作"，判方向、配名字、生成放入/拿出事件，可选上报后端。

    python process_session.py                                   # 默认 runs/sessions，全部会话
    python process_session.py runs/sessions --session 20261107_101010 --dry-run   # 只算只打印，不写文件不上报
    python process_session.py --fridge-side left --unnamed skip --post-url http://127.0.0.1:8000   # 上报到 /api/v1/door-events

只用 record_sessions.py 落盘的数据和 name_keyframes.py 写的 naming.json，自己不调 VLM。每个会话四步：
  1. 运动段（burst）：motion_track 里带内帧差 > --motion-threshold 的连续样本为一段，间隔 < --gap 秒的段合并，不足 2 个样本的丢掉；
     会话首尾 --edge 秒和帧差 ≥ --motion-cap 的样本不算（开关门灯亮灯灭、自动曝光拉回是整幅画面在变，不是手）。
  2. 方向：从 clip.mp4 读该段的帧，缩到宽 320 算 Farneback 稠密光流，只看虚拟线两侧 ±band/2 的列，按幅值加权平均 x 分量：
     > 0 向右，否则向左；confidence = |加权均值| / 加权平均幅值（0..1）。帧号按样本序号定（录制时每帧记一个样本再 [::3] 抽稀，
     第 j 个样本≈第 1+3j 帧），不用壁钟 t×fps——拿视频文件自检时壁钟比视频快两三倍，真机上 YOLO 拖慢循环时也会漂。
     clip 打不开时退回 cx 随时间的斜率（direction_source = "cx"）。
  3. 往返（trip）：相邻两段方向相反且间隔 < --trip-gap 秒配成一次"伸手—收手"；配不上的单段也算一次往返。
     --fridge-side 说明画面哪边是冰箱内部，朝那边走的腿是 toward，另一条是 away。
  4. 事件：每条腿的窗口 [t0−0.3, t1+0.3] 内找名字——先 naming.json（置信度最高且不是 unknown 的关键帧），再 yolo.detections
     （离峰值最近的一条，labels_zh.json 翻中文），都没有就没名字。toward 有名 away 无名 → in；反之 → out；都有名 → 一 in 一 out；
     都无名 → --unnamed in（默认）且这次往返至少有 1 张关键帧时记一条 label=unknown 的 in，否则跳过；--unnamed skip 直接跳过。

输出：每个会话目录 events.json（bursts / trips / events / params，上报过的事件带 posted、door_event_id），
根目录 events_summary.md（同时打印；用了 --session 时只含那个会话）。对比真值的口径（明天讨论架构用的诊断数，不是最终指标）：
  有真值 = truth 没跳过且放入 + 拿出至少 1 件；动作检出 = 有真值且至少 1 次往返；次数一致 = 往返次数 == 真值件数（count 之和）；
  方向一致 = 真值只有放入或只有拿出的会话里，至少 1 条事件且所有事件方向都对；空开门有动作 = 真值为空（没跳过）却切出了往返。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
LABELS_ZH = json.loads((HERE / "labels_zh.json").read_text(encoding="utf-8")) if (HERE / "labels_zh.json").exists() else {}
UNKNOWN = {"", "unknown", "none", "未知", "看不清", "无"}
WINDOW = 0.3  # 腿的时间窗口向两边各放宽这么多秒，用来捞关键帧和 YOLO 检测


# ---------------------------------------------------------------- 运动段与方向
def find_bursts(track: list[list[float]], threshold: float, gap: float, edge: float = 0.0, cap: float = 1e9) -> list[dict]:
    """motion > threshold 的连续样本为一段；两段间隔 < gap 秒就合并；不足 2 个样本的丢掉。
    会话开头 / 结尾 edge 秒内的样本不算（开门灯亮、关门灯灭、自动曝光拉回都在这里），motion ≥ cap 的样本也不算（整幅画面在变，不是手）。"""
    runs: list[list[int]] = []
    t_end = track[-1][0] if track else 0.0
    for i, (t, _cx, motion) in enumerate(track):
        if threshold < motion < cap and edge <= t <= t_end - edge:
            if runs and t - track[runs[-1][1]][0] < gap:
                runs[-1][1] = i
            else:
                runs.append([i, i])
    bursts = []
    for i0, i1 in runs:
        seg = track[i0:i1 + 1]
        if len(seg) >= 2:
            peak = max(seg, key=lambda s: s[2])
            bursts.append({"i0": i0, "i1": i1, "t0": seg[0][0], "t1": seg[-1][0], "t_peak": peak[0], "samples": len(seg),
                           "peak": peak[2], "mean": round(sum(s[2] for s in seg) / len(seg), 2)})
    return bursts


def flow_directions(clip: Path, bursts: list[dict], track: list, frames: int, line: float, band: float) -> dict[int, tuple[float, float]]:
    """顺序读一遍 clip，对每段算带内光流的幅值加权平均 x 分量。返回 {段序号: (flow_x, confidence)}，算不出的段不在里面。"""
    cap = cv2.VideoCapture(str(clip))
    if not bursts or not cap.isOpened():
        return {}
    stride = max(1, round((frames - 1) / max(len(track), 1)))  # 样本序号 → 帧号
    spans = [b.setdefault("frames", [max(0, stride * b["i0"]), 1 + stride * b["i1"]]) for b in bursts]
    c0, c1 = int((line - band / 2) * 320), int((line + band / 2) * 320)  # 带的列范围（宽 320 下）
    acc = [[0.0, 0.0, 0.0] for _ in bursts]  # Σ|v|·vx, Σ|v|, Σ|v|²
    prev, idx, k = None, -1, 0
    while k < len(bursts):
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        while k < len(bursts) and idx > spans[k][1]:
            k, prev = k + 1, None
        if k == len(bursts) or idx < spans[k][0]:
            continue
        g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, max(1, round(frame.shape[0] * 320 / frame.shape[1]))))
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fx = flow[:, c0:c1, 0]
            mag = np.hypot(fx, flow[:, c0:c1, 1])
            acc[k] = [a + float(v) for a, v in zip(acc[k], ((mag * fx).sum(), mag.sum(), (mag * mag).sum()))]
        prev = g
    cap.release()
    return {k: (sx / sm, min(1.0, abs(sx) / sm2)) for k, (sx, sm, sm2) in enumerate(acc) if sm > 0}


def cx_direction(seg: list[list[float]]) -> tuple[float, float]:
    """没有视频时的退路：运动重心 cx 对时间的斜率当方向，|相关系数| 当置信度。"""
    ts, cs = np.array([s[0] for s in seg]), np.array([s[1] for s in seg])
    if len(seg) < 2 or np.ptp(ts) == 0 or cs.std() == 0:
        return 0.0, 0.0
    return float(np.polyfit(ts, cs, 1)[0]), float(abs(np.nan_to_num(np.corrcoef(ts, cs)[0, 1])))


# ---------------------------------------------------------------- 往返与事件
def make_trips(bursts: list[dict], trip_gap: float, fridge_side: str) -> list[dict]:
    trips, i = [], 0
    while i < len(bursts):
        legs = [i]
        if i + 1 < len(bursts) and bursts[i + 1]["direction"] != bursts[i]["direction"] and bursts[i + 1]["t0"] - bursts[i]["t1"] < trip_gap:
            legs.append(i + 1)
        toward = [k for k in legs if bursts[k]["direction"] == fridge_side]
        away = [k for k in legs if bursts[k]["direction"] != fridge_side]
        trips.append({"legs": legs, "t0": bursts[legs[0]]["t0"], "t1": bursts[legs[-1]]["t1"],
                      "toward": toward[0] if toward else None, "away": away[0] if away else None,
                      "keyframes": sorted({f for k in legs for f in bursts[k]["keyframes"]})})
        i += len(legs)
    return trips


def leg_item(burst: dict, naming: dict[str, dict], detections: list[dict], kf_t: dict[str, float]) -> dict | None:
    """这条腿带的东西：naming.json 里置信度最高且不是 unknown 的关键帧 → YOLO 里离峰值最近的检测 → 无。"""
    named = [e for f in burst["keyframes"] if (e := naming.get(f)) and not e.get("error")
             and str(e.get("name") or "").strip().lower() not in UNKNOWN]
    if named:
        best = max(named, key=lambda e: e.get("confidence") or 0)
        count = best.get("count")
        return {"label": best["name"], "label_zh": best["name"], "confidence": best.get("confidence"),
                "count": count if isinstance(count, (int, float)) and count > 0 else 1, "keyframe": best["file"],
                "source": "vlm", "vlm": best.get("raw")}
    dets = [d for d in detections if burst["t0"] - WINDOW <= d["t"] <= burst["t1"] + WINDOW]
    if dets:
        d = min(dets, key=lambda d: (abs(d["t"] - burst["t_peak"]), -d["conf"]))
        kf = min(burst["keyframes"], key=lambda f: abs(kf_t[f] - d["t"]), default=None)
        return {"label": d["label"], "label_zh": LABELS_ZH.get(d["label"], d["label"]), "confidence": d["conf"], "count": 1,
                "keyframe": kf, "source": "yolo"}
    return None


def process(sdir: Path, s: dict, args: argparse.Namespace) -> dict:
    """一个会话：运动段 → 方向 → 往返 → 事件。"""
    track, keyframes = s.get("motion_track", []), s.get("keyframes", [])
    kf_t = {k["file"]: k["t"] for k in keyframes}
    bursts = find_bursts(track, args.motion_threshold, args.gap, args.edge, args.motion_cap)
    flows = flow_directions(sdir / s.get("clip", "clip.mp4"), bursts, track, s.get("frames", 0), args.line, args.band)
    for k, b in enumerate(bursts):
        fx, conf = flows.get(k) or cx_direction(track[b["i0"]:b["i1"] + 1])
        b.update(direction="right" if fx > 0 else "left", flow_x=round(fx, 4), confidence=round(conf, 3),
                 direction_source="flow" if k in flows else "cx",
                 keyframes=[f for f, t in kf_t.items() if b["t0"] - WINDOW <= t <= b["t1"] + WINDOW])
        print(f"  段{k + 1} {b['t0']:.2f}–{b['t1']:.2f}s 峰值 {b['peak']:.1f} → {b['direction']}"
              f"（{b['direction_source']} {b['flow_x']:+.3f}，置信 {b['confidence']:.2f}）关键帧 {len(b['keyframes'])}")
    naming: dict[str, dict] = {}
    if (sdir / "naming.json").exists():
        try:
            naming = {k["file"]: k for k in json.loads((sdir / "naming.json").read_text(encoding="utf-8"))["keyframes"]}
        except (json.JSONDecodeError, KeyError, TypeError):
            print("  naming.json 损坏，忽略")
    trips, events = make_trips(bursts, args.trip_gap, args.fridge_side), []
    for trip in trips:
        items = {k: leg_item(bursts[k], naming, s.get("yolo", {}).get("detections", []), kf_t) for k in trip["legs"]}
        new = [dict(t=bursts[k]["t0"], action=action, **items[k])
               for k, action in ((trip["toward"], "in"), (trip["away"], "out")) if k is not None and items[k]]
        if not new and args.unnamed == "in" and trip["keyframes"]:
            kf = max(trip["keyframes"], key=lambda f: next(k["motion"] for k in keyframes if k["file"] == f))
            new = [dict(t=trip["t0"], action="in", label="unknown", label_zh="未知", confidence=None, count=1, keyframe=kf, source="none")]
        events += new
    params = {k: getattr(args, k) for k in ("motion_threshold", "gap", "edge", "motion_cap", "trip_gap", "fridge_side", "unnamed", "line", "band")}
    return {"id": s["id"], "bursts": bursts, "trips": trips, "events": events, "params": dict(params, window=WINDOW)}


# ---------------------------------------------------------------- 上报与汇总
def post_event(client, url: str, sdir: Path, s: dict, e: dict) -> None:
    """按 door_demo.EventPoster 的格式 POST 一条事件；结果记回事件本身。"""
    stamp = datetime.fromisoformat(s["start"]).replace(tzinfo=datetime.now().astimezone().tzinfo) + timedelta(seconds=e["t"])
    payload = {"session_id": s["id"], "occurred_at": stamp.isoformat(timespec="milliseconds"), "action": e["action"],
               "label": e["label"], "label_zh": e["label_zh"], "count": e["count"],
               "confidence": None if e["confidence"] is None else max(0.0, min(1.0, float(e["confidence"])))}
    if e["source"] == "vlm" and isinstance(e.get("vlm"), dict):
        payload["vlm"] = e["vlm"]
    if e.get("keyframe") and (sdir / e["keyframe"]).exists():
        payload["keyframe_base64"] = base64.b64encode((sdir / e["keyframe"]).read_bytes()).decode()
    try:
        r = client.post(url, json=payload)
    except Exception as exc:  # 后端不在线
        e.update(posted=False, post_error=str(exc)[:200])
        print(f"  上报失败 {e['action']} {e['label_zh']}：{exc}", flush=True)
        return
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    e.update(posted=r.status_code < 300, post_status=r.status_code, door_event_id=body.get("id") if isinstance(body, dict) else None)
    print(f"  POST {e['action']} {e['label_zh']} → {r.status_code}" + (f"，door_event {e['door_event_id']}" if e["door_event_id"] else ""), flush=True)


def fmt_items(items: list[dict], skipped: bool = False) -> str:
    return "、".join(f"{i['name']}×{i['count']:g}" for i in items) or ("（未记）" if skipped else "无")


def fmt_events(events: list[dict]) -> str:
    return "、".join(f"{e['action']}:{e['label']}" + (f"({e['confidence']:.2f})" if e["confidence"] is not None else "") for e in events) or "—"


def summarize(root: Path, results: list[tuple[dict, dict]], params: dict) -> list[str]:
    n_truth = detected = count_ok = dir_total = dir_ok = empty_total = empty_moved = 0
    rows = []
    for s, r in results:
        t = s["truth"]
        skipped, ins, outs = bool(t.get("skipped")), t.get("in", []), t.get("out", [])
        items = [] if skipped else ins + outs
        if items:
            same = len(r["trips"]) == sum(i["count"] for i in items)
            n_truth, detected, count_ok = n_truth + 1, detected + bool(r["trips"]), count_ok + same
            match = f"次数{'✓' if same else '✗'}"
            if not ins or not outs:  # 只放入或只拿出，才能单独评方向
                ok = bool(r["events"]) and all(e["action"] == ("in" if ins else "out") for e in r["events"])
                dir_total, dir_ok, match = dir_total + 1, dir_ok + ok, match + f" 方向{'✓' if ok else '✗'}"
        elif skipped:
            match = "—（没记真值）"
        else:
            empty_total, empty_moved = empty_total + 1, empty_moved + bool(r["trips"])
            match = "空开门：" + ("有动作 ✗" if r["trips"] else "无动作 ✓")
        rows.append(f"| {s['id']} | {fmt_items(ins, skipped)} | {fmt_items(outs, skipped)} | {len(r['bursts'])} | {len(r['trips'])} | {fmt_events(r['events'])} | {match} |")
    nb, nt, n = [len(r["bursts"]) for _, r in results], [len(r["trips"]) for _, r in results], max(len(results), 1)
    return [f"# 离线事件统计（{root}）", "", f"参数 {json.dumps(params, ensure_ascii=False)}；生成于 {datetime.now():%Y-%m-%d %H:%M}", "",
            "| 指标 | 值 |", "| --- | --- |", f"| 会话总数 | {len(results)} |", f"| 有真值的会话 | {n_truth} |",
            f"| 每会话运动段（均值 / 最大） | {sum(nb) / n:.1f} / {max(nb, default=0)} |",
            f"| 每会话往返（均值 / 最大） | {sum(nt) / n:.1f} / {max(nt, default=0)} |",
            f"| 动作检出（有真值且 ≥1 次往返） | {detected} / {n_truth} |",
            f"| 次数一致（往返数 == 真值件数） | {count_ok} / {n_truth} |",
            f"| 方向一致（只放入或只拿出的会话里，事件方向全对） | {dir_ok} / {dir_total} |",
            f"| 空开门有动作（真值为空却切出往返） | {empty_moved} / {empty_total} |",
            "", "## 逐会话", "", "| 会话 | 放入真值 | 拿出真值 | 运动段 | 往返 | 事件 | 对比 |", "| --- | --- | --- | --- | --- | --- | --- |", *rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=str(HERE / "runs" / "sessions"))
    ap.add_argument("--session", default="", help="只处理这一个会话 id")
    ap.add_argument("--motion-threshold", type=float, default=6.0, help="带内帧差超过它算有动作（同 record_sessions.py）")
    ap.add_argument("--gap", type=float, default=0.6, help="两段动作间隔小于多少秒合并成一段")
    ap.add_argument("--edge", type=float, default=0.4, help="会话开头和结尾这么多秒不算动作（灯亮灯灭、自动曝光）")
    ap.add_argument("--motion-cap", type=float, default=100.0, help="带内帧差超过它视为整幅画面在变（灯），不算动作")
    ap.add_argument("--trip-gap", type=float, default=4.0, help="方向相反的相邻两段间隔小于多少秒配成一次往返")
    ap.add_argument("--fridge-side", choices=["left", "right"], default="right", help="画面哪边是冰箱内部，朝它走的腿算 toward")
    ap.add_argument("--unnamed", choices=["in", "skip"], default="in", help="两条腿都没名字时：in=有关键帧就记一条 unknown 的放入，skip=跳过")
    ap.add_argument("--line", type=float, default=0.5, help="虚拟线位置，占画面宽度比例（同录制）")
    ap.add_argument("--band", type=float, default=0.14, help="光流只看虚拟线两侧这么宽的带，占画面比例（同录制）")
    ap.add_argument("--post-url", default="", help="smart_fridge_app 地址，例如 http://127.0.0.1:8000；设置后每条事件都上报")
    ap.add_argument("--dry-run", action="store_true", help="只算只打印，不写文件不上报")
    args = ap.parse_args()

    root, sessions = Path(args.root), []
    for path in sorted(root.glob("*/session.json")):
        try:
            sessions.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            print("跳过损坏的", path)
    todo = [(d, s) for d, s in sessions if not args.session or args.session in (s.get("id"), d.name)]
    if not todo:
        print(f"{root} 里没有会话{' ' + args.session if args.session else ''}。先跑 record_sessions.py。")
        return 1
    client = None
    if args.post_url and not args.dry_run:
        import httpx
        client = httpx.Client(timeout=10.0)
    results = []
    for d, s in todo:
        print(f"{s['id']}：", flush=True)
        r = process(d, s, args)
        print(f"  → {len(r['bursts'])} 段动作，{len(r['trips'])} 次往返，{len(r['events'])} 条事件：{fmt_events(r['events'])}", flush=True)
        for e in r["events"] if client is not None else []:
            post_event(client, args.post_url.rstrip("/") + "/api/v1/door-events", d, s, e)
        if not args.dry_run:
            (d / "events.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        results.append((s, r))
    lines = summarize(root, results, results[0][1]["params"])
    print("\n" + "\n".join(lines))
    if args.dry_run:
        print("\n--dry-run：没写 events.json / events_summary.md，也没上报。")
    else:
        (root / "events_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写入 {root / 'events_summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
