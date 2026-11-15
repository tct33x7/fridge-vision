#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐个动作打分：拿"真值里的每个动作（带时间窗口）"和"某条识别路线输出的计数事件"对照。
和用哪条路线无关：Mac 上的 YOLO11s（eval/events_mac.py）、板子管线（orangepi_app/tools/simulate_counter.py
--events-json）、以后的其他路线，只要输出同样格式的事件文件，就能放在同一张表里比较。

  python eval/score_actions.py A.truth.json A_201500.mac-default-pc.events.json
  python eval/score_actions.py A.truth.json A.mac.events.json A.board-lite.events.json --md A.score.md --json A.score.json

打分规则（在看到任何 E03 / E04 数据之前写定，见 eval/README.md "打分规则"；改规则要记在实验记录里）：
- 事件时间 = 物品过线的那一刻（不是事件被确认的那一刻）。
- 事件归属：动作按开始时间排序。相邻两个动作之间，以"前一个的结束"和"后一个的开始"的中点为界；
  第一个动作从它开始前 2 秒算起，最后一个动作管到录像结束。第一个动作之前的事件 = "窗口外的误计"；落在 ignore 时间段里的事件不算。
- 有物品的动作（真值 delta = +n 或 −n）：
    计数正确 = 方向对的事件正好 n 个，并且没有方向反的事件
    方向对   = 至少 1 个方向对的事件，并且没有方向反的事件
    净数对   = 所有事件加起来正好等于 delta（"只看最后"的口径：+1 −1 +1 也算对）
    类别也对 = 计数正确时类别也对：cls 是一个名字 → 每个事件都是它；cls 是列表 → 每个事件都在列表里（同一样东西的几种叫法）；
               cls_multi（一次拿几样不同的东西）→ 事件的类别正好是这几样（不管顺序）。真值没有类别或计数不正确时，这一项不算
    漏计 = n − 方向对的事件数（不小于 0）；多计 = 事件总数 − 算作正确的事件数
- 不该计数的动作（delta = 0）：没有任何事件才算对。
- 会让结果悄悄出错的输入一律报错停下：动作时间重叠、两个动作用同一个窗口、ignore 时间段压到动作上、窗口文件里有没被用到的窗口、
  真值 / 窗口 / 事件文件不是同一段录像、时间基准或计数线对不上、动作时间超出录像。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEAD_S = 2.0       # 第一个动作从开始前多少秒算起
EPS = 1e-6

YES = {"✓", "√", "✔", "☑", "y", "yes", "true", "1", "是", "对", "有"}
NO = {"✗", "×", "x", "✘", "n", "no", "false", "0", "否", "错", "没有", "△", "—", "-"}

COCO = set("""person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign parking_meter
bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee skis snowboard
sports_ball kite baseball_bat baseball_glove skateboard surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl
banana apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv
laptop mouse remote keyboard cell_phone microwave oven toaster sink refrigerator book clock vase scissors teddy_bear
hair_drier toothbrush""".replace("_", " ").split()) | {"traffic light", "fire hydrant", "stop sign", "parking meter",
                                                        "sports ball", "baseball bat", "baseball glove", "tennis racket",
                                                        "wine glass", "hot dog", "potted plant", "dining table",
                                                        "cell phone", "teddy bear", "hair drier"}


class TruthError(SystemExit):
    pass


# ---------------- 读真值 ----------------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def windows_path(truth, truth_path):
    if truth.get("windows_file"):
        wpath = truth["windows_file"]
    elif truth.get("video"):
        wpath = os.path.splitext(truth["video"])[0] + ".windows.json"
    else:
        wpath = os.path.basename(truth_path).replace(".truth.json", "") + ".windows.json"
    if not os.path.isabs(wpath):
        wpath = os.path.join(os.path.dirname(os.path.abspath(truth_path)), wpath)
    return wpath


def resolve_windows(truth, truth_path):
    """给每个动作定 start_s / end_s：直接写的时间优先，否则用 "window" 编号去窗口文件里查。
    返回 (动作列表, ignore 时间段, 窗口文件内容或 None)。会让结果出错的情况直接报错。"""
    if not truth.get("actions"):
        raise TruthError(f"{truth_path} 里没有 actions")
    wfile = None
    uses_windows = any("window" in a and "start_s" not in a for a in truth["actions"]) or truth.get("ignore_windows")
    if uses_windows:
        wpath = windows_path(truth, truth_path)
        if not os.path.isfile(wpath):
            raise TruthError(f"真值里用了窗口编号，但找不到窗口文件 {wpath}（先运行 eval/propose_windows.py；"
                             f"真值里的 \"video\" 要写录像文件名，或者用 \"windows_file\" 指定）")
        wfile = load_json(wpath)
        wfile["_path"] = wpath
    windows = {w["n"]: w for w in (wfile or {}).get("windows", [])}
    actions, used = [], {}
    for k, a in enumerate(truth["actions"]):
        a = dict(a)
        a.setdefault("n", k + 1)
        if "delta" not in a:
            raise TruthError(f"动作 {a['n']} 没有 \"delta\"（+1 放入、−1 拿出、0 不该计数）")
        if "start_s" not in a:
            if "window" not in a:
                raise TruthError(f"动作 {a['n']} 没有时间：写上 \"start_s\"/\"end_s\"，或者 \"window\": 窗口编号")
            ws = a["window"] if isinstance(a["window"], list) else [a["window"]]
            for w in ws:
                if w not in windows:
                    raise TruthError(f"动作 {a['n']} 的窗口 {w} 在窗口文件里不存在")
                if w in used:
                    raise TruthError(f"窗口 {w} 同时给了动作 {used[w]} 和动作 {a['n']}：一个窗口只能属于一个动作"
                                     f"（一个窗口里做了两件事，就手写两个动作的 start_s / end_s）")
                used[w] = a["n"]
            a["start_s"] = min(windows[w]["start_s"] for w in ws)
            a["end_s"] = max(windows[w]["end_s"] for w in ws)
        a.setdefault("end_s", a["start_s"])
        if a["end_s"] < a["start_s"]:
            raise TruthError(f"动作 {a['n']} 的结束时间早于开始时间")
        actions.append(a)
    ignore = [[float(r[0]), float(r[1])] for r in truth.get("ignore", [])]
    for w in truth.get("ignore_windows", []):
        if w not in windows:
            raise TruthError(f"ignore_windows 里的窗口 {w} 在窗口文件里不存在")
        if w in used:
            raise TruthError(f"窗口 {w} 既是动作 {used[w]}，又写在 ignore_windows 里")
        used[w] = "ignore"
        ignore.append([windows[w]["start_s"], windows[w]["end_s"]])
    if windows:
        left = sorted(set(windows) - set(used))
        if left:
            raise TruthError(f"窗口文件里的窗口 {left} 没有被任何动作或 ignore_windows 用到。它们里面的事件会被算到前一个动作头上，"
                             f"所以必须写明：是某个动作就给那个动作写 \"window\"；做错重来、秒表、筷子这些不算的，写进 \"ignore_windows\"")
    actions.sort(key=lambda a: a["start_s"])
    for p, q in zip(actions, actions[1:]):
        if q["start_s"] < p["end_s"] - EPS:
            raise TruthError(f"动作 {p['n']}（{p['start_s']:.1f}–{p['end_s']:.1f}s）和动作 {q['n']}"
                             f"（{q['start_s']:.1f}–{q['end_s']:.1f}s）的时间重叠")
    for lo, hi in ignore:
        for a in actions:
            if lo < a["end_s"] - EPS and hi > a["start_s"] + EPS:
                raise TruthError(f"不算的时间段 {lo:.1f}–{hi:.1f}s 压到了动作 {a['n']}（{a['start_s']:.1f}–{a['end_s']:.1f}s），"
                                 f"会把这个动作的事件删掉；把两者的时间分开")
    return actions, ignore, wfile


def tags_of(a):
    """动作属于哪些分组（汇总时每组一行）。真值里的 "group"（抽签工具写的）和 "tags" 也算分组。"""
    where = a.get("where") or ""
    if a["delta"] == 0:
        tags = ["不该计数（全部）"]
    else:
        tags = ["门格" if "门格" in where else "搁板" if "搁板" in where else "其他位置"]
        if not a.get("cls") and not a.get("cls_multi"):
            tags.append("YOLO 不认识")
        if abs(a["delta"]) >= 2:
            tags.append("一次多件")
    for t in ([a["group"]] if a.get("group") else []) + list(a.get("tags", [])):
        t = f"抽签分组：{t}" if t == a.get("group") else t
        if t not in tags:
            tags.append(t)
    return tags


def boundaries(actions, lead=LEAD_S):
    """每个动作管的时间段 [b_i, b_{i+1})：相邻两个动作之间取中点；第一个从开始前 lead 秒起；最后一个到无穷。"""
    b = [actions[0]["start_s"] - lead] if actions else []
    for p, q in zip(actions, actions[1:]):
        b.append((p["end_s"] + q["start_s"]) / 2)
    b.append(float("inf"))
    return b


# ---------------- 规则 ----------------

def sign(x):
    return (x > 0) - (x < 0)


def assign_events(actions, events, ignore, lead=LEAD_S):
    """返回 (每个动作的事件列表, 窗口外的事件, 被忽略的事件)。actions 需按 start_s 排好序。"""
    b = boundaries(actions, lead)
    per = [[] for _ in actions]
    outside, ignored = [], []
    for e in sorted(events, key=lambda e: e["t"]):
        t = e["t"]
        if any(lo - EPS <= t <= hi + EPS for lo, hi in ignore):
            ignored.append(e)
            continue
        i = None
        for k in range(len(actions)):
            if b[k] - EPS <= t < b[k + 1] - EPS:
                i = k
                break
        (outside if i is None else per[i]).append(e)
    return per, outside, ignored


def class_ok_of(action, right):
    if action.get("cls_multi"):
        return sorted(e.get("cls") or "" for e in right) == sorted(action["cls_multi"])
    c = action.get("cls")
    if not c:
        return None
    if isinstance(c, list):
        return all(e.get("cls") in c for e in right)
    return all(e.get("cls") == c for e in right)


def judge(action, evs):
    """一个动作 + 归给它的事件 → 结果字典（规则见文件开头）。"""
    d = action["delta"]
    r = {"events": len(evs), "seq": " ".join(f"{'+' if e['delta'] > 0 else '-'}{e.get('cls') or '?'}" for e in evs)}
    if d == 0:
        r.update(ok=len(evs) == 0, false_events=len(evs))
        return r
    need, s = abs(d), sign(d)
    right = [e for e in evs if sign(e["delta"]) == s]
    wrong = [e for e in evs if sign(e["delta"]) == -s]
    good = min(len(right), need)
    event_ok = len(right) == need and not wrong
    class_ok = class_ok_of(action, right) if event_ok else None
    r.update(
        event_ok=event_ok,
        direction_ok=bool(right) and not wrong,
        net_ok=sum(e["delta"] for e in evs) == d,
        class_ok=class_ok,
        full_ok=event_ok and class_ok is not False,
        miss=need - good,
        extra=len(evs) - good,
    )
    return r


# ---------------- 汇总 ----------------

def load_wilson():
    """学生自己写的 eval/wilson.py（函数 wilson(k, n) → (下限, 上限)，0–1 之间）。
    返回 (函数或 None, 说明文字)。"""
    path = os.path.join(HERE, "wilson.py")
    if not os.path.isfile(path):
        return None, "没有 eval/wilson.py，只列 k/n"
    try:
        spec = importlib.util.spec_from_file_location("student_wilson", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        return None, f"eval/wilson.py 运行出错（{type(exc).__name__}: {exc}），这次只列 k/n"
    fn = getattr(mod, "wilson", None)
    if not callable(fn):
        return None, "eval/wilson.py 里没有叫 wilson 的函数（要写成 def wilson(k, n): ...），这次只列 k/n"
    return fn, "用 eval/wilson.py 算的 95% 区间"


def frac(k, n, wilson):
    if n == 0:
        return "—"
    s = f"{k}/{n}"
    if wilson:
        try:
            lo, hi = wilson(k, n)
            if not (0 <= lo <= k / n + EPS and k / n - EPS <= hi <= 1):
                hint = "（是不是返回了百分数？要 0–1 之间）" if hi > 1 else ""
                s += f"（区间不对：{lo:.3g}–{hi:.3g}{hint}）"
            else:
                s += f"（{lo * 100:.0f}–{hi * 100:.0f}%）"
        except Exception as exc:  # 学生的函数出错时照样出表
            s += f"（区间出错：{exc}）"
    return s


def parse_label(v, warnings, field, n):
    """人工勾选 → True / False / None（没勾）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s == "":
        return None
    if s in YES:
        return True
    if s in NO:
        return False
    warnings.append(f"动作 {n} 的 {field} 写的是 \"{v}\"，认不出，当作没勾（用 ✓ 或 ✗）")
    return None


def summarize(actions, results, wilson, warnings=None):
    warnings = [] if warnings is None else warnings
    groups = {"全部有物品的动作": [i for i, a in enumerate(actions) if a["delta"] != 0]}
    empties = {}
    for i, a in enumerate(actions):
        for t in tags_of(a):
            (groups if a["delta"] != 0 else empties).setdefault(t, []).append(i)
    rows = []
    for g, idx in groups.items():
        rs = [results[i] for i in idx]
        vis = [parse_label(actions[i].get("visible"), warnings, "visible", actions[i]["n"]) for i in idx]
        box = [parse_label(actions[i].get("boxed"), warnings, "boxed", actions[i]["n"]) for i in idx]
        cls_rs = [r for r in rs if r["class_ok"] is not None]
        rows.append({
            "group": g, "n": len(idx),
            "visible": frac(sum(v is True for v in vis), sum(v is not None for v in vis), wilson),
            "boxed": frac(sum(v is True for v in box), sum(v is not None for v in box), wilson),
            "event_ok": frac(sum(r["event_ok"] for r in rs), len(rs), wilson),
            "direction_ok": frac(sum(r["direction_ok"] for r in rs), len(rs), wilson),
            "net_ok": frac(sum(r["net_ok"] for r in rs), len(rs), wilson),
            "class_ok": frac(sum(r["class_ok"] for r in cls_rs), len(cls_rs), wilson),
        })
    empty_rows = []
    for g, idx in empties.items():
        rs = [results[i] for i in idx]
        empty_rows.append({"group": g, "n": len(idx),
                           "with_events": frac(sum(not r["ok"] for r in rs), len(rs), wilson),
                           "false_events": sum(r["false_events"] for r in rs)})
    return rows, empty_rows


def git_rev():
    try:
        rev = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", HERE, "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return rev + ("（有未提交的改动）" if dirty else "")
    except Exception:
        return "?"


def check_inputs(truth, actions, wfile, ev, path, warnings):
    """真值、窗口文件、事件文件是不是同一段录像、同一个时间基准、同一条线。对不上就报错。"""
    name = os.path.basename(path)
    tv, ev_v = truth.get("video"), ev.get("video")
    if tv and ev_v and os.path.basename(tv) != os.path.basename(ev_v):
        raise TruthError(f"{name} 是录像 {ev_v} 的事件，真值写的是 {tv}")
    if wfile and wfile.get("video") and ev_v and os.path.basename(wfile["video"]) != os.path.basename(ev_v):
        raise TruthError(f"窗口文件是录像 {wfile['video']} 的，{name} 是录像 {ev_v} 的")
    tb_e, tb_w = ev.get("time_base") or {}, (wfile or {}).get("time_base") or {}
    if tb_e and tb_w:
        if tb_e.get("source") != tb_w.get("source"):
            raise TruthError(f"窗口文件按 {tb_w.get('source')} 算时间，{name} 按 {tb_e.get('source')} 算，时间对不上")
        if tb_e.get("frames") and tb_w.get("frames") and abs(tb_e["frames"] - tb_w["frames"]) > 2:
            raise TruthError(f"窗口文件按 {tb_w['frames']} 帧算时间，{name} 按 {tb_e['frames']} 帧算，不是同一份时间基准")
        if tb_e.get("fps") and tb_w.get("fps") and abs(tb_e["fps"] - tb_w["fps"]) / tb_w["fps"] > 0.01:
            raise TruthError(f"窗口文件的帧率 {tb_w['fps']} 和 {name} 的 {tb_e['fps']} 不一样，时间对不上")
    elif tb_e and tb_e.get("source") != "sidecar":
        warnings.append(f"{name} 的时间不是按 .frames.json 算的（{tb_e.get('source')}），手写的动作时间要和它用同一个钟")
    line_e = (ev.get("provenance") or {}).get("line")
    if truth.get("line") and line_e and any(abs(float(x) - float(y)) > 1e-6 for x, y in zip(truth["line"], line_e)):
        raise TruthError(f"{name} 用的计数线 {line_e} 和真值里的 {truth['line']} 不一样")
    dur = tb_e.get("duration_s")
    if dur is not None:
        for a in actions:
            if a["start_s"] > dur + 1.0:
                raise TruthError(f"动作 {a['n']} 从 {a['start_s']:.1f}s 开始，但 {name} 对应的录像只有 {dur:.1f} 秒")


def lint_truth(actions, warnings):
    for a in actions:
        w = a.get("where") or ""
        if a["delta"] != 0 and not any(k in w for k in ("门格", "搁板")):
            warnings.append(f"动作 {a['n']} 的 where \"{w}\" 里没有\"门格\"或\"搁板\"，分到\"其他位置\"")
        cs = a.get("cls_multi") or (a["cls"] if isinstance(a.get("cls"), list) else [a.get("cls")])
        for c in cs:
            if c and c not in COCO:
                warnings.append(f"动作 {a['n']} 的类别 \"{c}\" 不是 YOLO 的 80 类之一，计数事件永远对不上它（YOLO 不认识的东西写 null）")
        if a.get("cls_multi") and len(a["cls_multi"]) != abs(a["delta"]):
            warnings.append(f"动作 {a['n']} 的 cls_multi 有 {len(a['cls_multi'])} 样，delta 是 {a['delta']}")


def score(truth_path, events_paths):
    truth = load_json(truth_path)
    actions, ignore, wfile = resolve_windows(truth, truth_path)
    warnings = []
    lint_truth(actions, warnings)
    wilson, wilson_note = load_wilson()
    routes, seen = [], {}
    for p in events_paths:
        ev = load_json(p)
        check_inputs(truth, actions, wfile, ev, p, warnings)
        per, outside, ignored = assign_events(actions, ev["events"], ignore)
        results = [judge(a, e) for a, e in zip(actions, per)]
        rows, empty = summarize(actions, results, wilson, warnings)
        name = ev.get("route", os.path.basename(p))
        if name in seen:
            name = f"{name}（{os.path.basename(p)}）"
        seen[name] = True
        routes.append({"file": p, "route": name, "provenance": ev.get("provenance", {}),
                       "time_base": ev.get("time_base"), "results": results, "summary": rows, "empty": empty,
                       "outside": outside, "ignored": len(ignored)})
    return {"truth": truth_path, "video": truth.get("video"), "actions": actions, "ignore": ignore,
            "windows_file": (wfile or {}).get("_path"), "routes": routes, "wilson_note": wilson_note,
            "scorer_commit": git_rev(), "lead_s": LEAD_S, "warnings": list(dict.fromkeys(warnings))}


def mark(v):
    return "—" if v is None else ("✓" if v else "✗")


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def route_tables(r):
    out = ["| 分组 | 动作数 | ① 人眼能认出 | ② 检测器框到 | ③ 计数正确 | 方向对 | 净数对 | 类别也对* |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in r["summary"]:
        out.append(f"| {esc(row['group'])} | {row['n']} | {row['visible']} | {row['boxed']} | {row['event_ok']} | "
                   f"{row['direction_ok']} | {row['net_ok']} | {row['class_ok']} |")
    out += ["", "*类别也对的分母 = 计数正确、并且真值有类别的动作。", ""]
    if r["empty"]:
        out += ["不该计数的动作（真值 delta = 0）：", "", "| 分组 | 次数 | 有误计的 | 误计事件数 |", "| --- | --- | --- | --- |"]
        for e in r["empty"]:
            out.append(f"| {esc(e['group'])} | {e['n']} | {e['with_events']} | {e['false_events']} |")
        out.append("")
    return out


def to_markdown(s):
    out = [f"# 逐动作打分：{esc(s.get('video') or os.path.basename(s['truth']))}", ""]
    out.append(f"- 真值：`{s['truth']}`；打分程序版本 {s['scorer_commit']}；第一个动作从开始前 {s['lead_s']} 秒算起，相邻动作之间按中点分")
    if s.get("windows_file"):
        out.append(f"- 窗口文件：`{s['windows_file']}`")
    if s["ignore"]:
        out.append(f"- 不算的时间段：{', '.join(f'{a:.1f}–{b:.1f}s' for a, b in s['ignore'])}")
    out.append(f"- 区间：{s['wilson_note']}")
    for r in s["routes"]:
        tb = r.get("time_base") or {}
        out.append(f"- 路线 **{esc(r['route'])}**：`{r['file']}`；时间基准 {tb.get('source', '?')}"
                   f"（{tb.get('fps', '?')} 帧/秒）{('；' + esc(tb['note'])) if tb.get('note') else ''}")
    if s["warnings"]:
        out += ["", "**提醒**：", ""] + [f"- {esc(w)}" for w in s["warnings"]]
    out.append("")
    for r in s["routes"]:
        out += [f"## 路线：{esc(r['route'])}", ""]
        out += route_tables(r)
        out.append(f"- 窗口外的误计：{len(r['outside'])} 个" +
                   (("（" + "；".join(f"{x['t']:.1f}s {'+' if x['delta'] > 0 else '-'}{x.get('cls')}"
                                     for x in r["outside"]) + "）") if r["outside"] else ""))
        if r["ignored"]:
            out.append(f"- 落在不算的时间段里的事件：{r['ignored']} 个（没计入）")
        out.append("")
    out += ["## 每个动作", ""]
    out.append("| # | 物品 | 放在哪 | 真值 | 时间 | ① | ② | " + " | ".join(
        f"{esc(r['route'])}：事件 / ③ / 方向 / 类别" for r in s["routes"]) + " |")
    out.append("|" + " --- |" * (7 + len(s["routes"])))
    for i, a in enumerate(s["actions"]):
        cells = []
        for r in s["routes"]:
            x = r["results"][i]
            if a["delta"] == 0:
                cells.append(f"{esc(x['seq']) or '·'} / {mark(x['ok'])}")
            else:
                cells.append(f"{esc(x['seq']) or '·'} / {mark(x['event_ok'])} / {mark(x['direction_ok'])} / {mark(x['class_ok'])}")
        cls = a.get("cls_multi") or a.get("cls")
        cls = "+".join(cls) if isinstance(cls, list) else (cls or "（不认识）")
        out.append(f"| {a['n']} | {esc(a.get('item', ''))} {esc(cls)} | {esc(a.get('where', ''))} | {a['delta']:+d} | "
                   f"{a['start_s']:.1f}–{a['end_s']:.1f}s | {esc(a.get('visible') or '')} | {esc(a.get('boxed') or '')} | "
                   + " | ".join(cells) + " |")
    out += ["", "说明：① ② 来自真值里人工填的 visible / boxed（只有 ✓ 算是，没填的不进分母）；"
                "③ 计数正确 = 方向对的事件正好 n 个且没有反向事件；净数对 = 事件加起来等于真值；"
                "类别只在计数正确且真值有类别时才算。规则见 eval/README.md。"]
    for r in s["routes"]:
        prov = r.get("provenance") or {}
        if prov:
            out += ["", f"<details><summary>{esc(r['route'])} 的来历（模型、参数、版本）</summary>", "", "```json",
                    json.dumps(prov, ensure_ascii=False, indent=1), "```", "</details>"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="逐个动作打分（和识别路线无关）")
    ap.add_argument("truth")
    ap.add_argument("events", nargs="+", help="一个或多个事件文件（*.events.json），每个一条路线")
    ap.add_argument("--md", help="把结果写成 markdown 文件（默认只打印）")
    ap.add_argument("--json", help="把完整结果另存为 json（几段录像合起来算时给 eval/pool_scores.py 用）")
    a = ap.parse_args()
    try:
        s = score(a.truth, a.events)
    except TruthError as exc:
        print(f"停下了：{exc}", file=sys.stderr)
        return 2
    md = to_markdown(s)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已写 {a.md}" + (f"（有 {len(s['warnings'])} 条提醒，见文件开头）" if s["warnings"] else ""))
    else:
        print(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
