#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐个动作打分：拿"真值里的每个动作（带时间窗口）"和"某条识别路线输出的计数事件"对照。
和用哪条路线无关：Mac 上的 YOLO11s（eval/events_mac.py）、板子管线（orangepi_app/tools/simulate_counter.py
--events-json）、以后的类别无关路线，只要输出同样格式的事件文件，就能放在同一张表里比较。

  python eval/score_actions.py A_201500.truth.json A_201500.mac.events.json
  python eval/score_actions.py A.truth.json A.mac.events.json A.board.events.json --md A.score.md

打分规则（在看到任何 E03 / E04 数据之前写定，见 eval/README.md "打分规则"；改规则要记在实验记录里）：
- 事件归属：按动作开始时间排序；第 i 个动作管 [开始_i − 0.5 秒, 开始_{i+1} − 0.5 秒) 里的事件，最后一个动作管到录像结束。
  第一个动作之前的事件 = "窗口外的误计"；落在 ignore 时间段里的事件不算。
- 有物品的动作（真值 delta = +n 或 −n）：
    计数正确 = 方向对的事件正好 n 个，并且没有方向反的事件
    方向对   = 至少 1 个方向对的事件，并且没有方向反的事件
    净数对   = 所有事件加起来正好等于 delta（"只看最后"的口径：+1 −1 +1 也算对）
    类别也对 = 计数正确时，这些事件的类别都等于真值类别；真值类别为空（YOLO 不认识的东西）或计数不正确时不算这一项
    漏计 = n − 方向对的事件数（不小于 0）；多计 = 事件总数 − 算作正确的事件数
- 空开门（delta = 0）：没有任何事件才算对。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRE_S = 0.5


# ---------------- 读真值 ----------------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_windows(truth, truth_path):
    """给每个动作定 start_s / end_s：直接写的时间优先，否则用 "window" 编号去 <录像名>.windows.json 里查。"""
    windows = None
    if any("window" in a and "start_s" not in a for a in truth["actions"]) or truth.get("ignore_windows"):
        if truth.get("windows_file"):
            wpath = truth["windows_file"]
        elif truth.get("video"):
            wpath = os.path.splitext(truth["video"])[0] + ".windows.json"
        else:
            wpath = os.path.splitext(truth_path)[0].replace(".truth", "") + ".windows.json"
        if not os.path.isabs(wpath):
            wpath = os.path.join(os.path.dirname(os.path.abspath(truth_path)), wpath)
        if not os.path.isfile(wpath):
            raise SystemExit(f"真值里用了 \"window\" 编号，但找不到窗口文件 {wpath}（先运行 eval/propose_windows.py）")
        windows = {w["n"]: w for w in load_json(wpath)["windows"]}
    actions = []
    for a in truth["actions"]:
        a = dict(a)
        if "start_s" not in a:
            if "window" not in a:
                raise SystemExit(f"动作 {a.get('n')} 没有时间：写上 \"start_s\"/\"end_s\"，或者 \"window\": 窗口编号")
            ws = a["window"] if isinstance(a["window"], list) else [a["window"]]
            try:
                a["start_s"] = min(windows[w]["start_s"] for w in ws)
                a["end_s"] = max(windows[w]["end_s"] for w in ws)
            except KeyError as exc:
                raise SystemExit(f"动作 {a.get('n')} 的窗口 {exc} 在窗口文件里不存在")
        a.setdefault("end_s", a["start_s"])
        actions.append(a)
    ignore = [list(map(float, r)) for r in truth.get("ignore", [])]
    for w in truth.get("ignore_windows", []):
        ignore.append([windows[w]["start_s"], windows[w]["end_s"]])
    return actions, ignore


def tags_of(a):
    """动作属于哪些分组（汇总时每组一行）。真值里可以用 "tags" 再加，例如 ["快速", "一手两样"]。"""
    where = a.get("where") or ""
    if a["delta"] == 0:
        tags = ["不该计数（空开门等）"]
    else:
        tags = ["门格" if "门格" in where else "搁板" if "搁板" in where else "其他位置"]
        if not a.get("cls"):
            tags.append("YOLO 不认识")
        if abs(a["delta"]) >= 2:
            tags.append("一次多件")
    for t in a.get("tags", []):
        if t not in tags:
            tags.append(t)
    return tags


# ---------------- 规则 ----------------

def sign(x):
    return (x > 0) - (x < 0)


def assign_events(actions, events, ignore, pre=PRE_S):
    """返回 (每个动作的事件列表, 窗口外的事件, 被忽略的事件)。actions 需按 start_s 排好序。"""
    starts = [a["start_s"] - pre for a in actions]
    per = [[] for _ in actions]
    outside, ignored = [], []
    for e in sorted(events, key=lambda e: e["t"]):
        t = e["t"]
        if any(lo <= t <= hi for lo, hi in ignore):
            ignored.append(e)
            continue
        i = None
        for k, s in enumerate(starts):
            if t >= s:
                i = k
            else:
                break
        (outside if i is None else per[i]).append(e)
    return per, outside, ignored


def cls_matches(truth_cls, got):
    if isinstance(truth_cls, list):
        return got in truth_cls
    return got == truth_cls


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
    class_ok = None
    if event_ok and action.get("cls"):
        class_ok = all(cls_matches(action["cls"], e.get("cls")) for e in right)
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
    """学生自己写的 eval/wilson.py（函数 wilson(k, n) → (下限, 上限)，0–1 之间）。没有就不算区间。"""
    path = os.path.join(HERE, "wilson.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("student_wilson", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "wilson", None)


def frac(k, n, wilson):
    if n == 0:
        return "—"
    s = f"{k}/{n}"
    if wilson:
        try:
            lo, hi = wilson(k, n)
            s += f"（{lo * 100:.0f}–{hi * 100:.0f}%）"
        except Exception as exc:  # 学生的函数出错时照样出表
            s += f"（区间出错：{exc}）"
    return s


def label_yes(v):
    return v in ("✓", True, "y", "yes", 1)


def summarize(actions, results, wilson):
    groups = {"全部有物品的动作": [i for i, a in enumerate(actions) if a["delta"] != 0]}
    for i, a in enumerate(actions):
        if a["delta"] == 0:
            continue
        for t in tags_of(a):
            groups.setdefault(t, []).append(i)
    rows = []
    for g, idx in groups.items():
        rs = [results[i] for i in idx]
        vis = [actions[i].get("visible") for i in idx]
        box = [actions[i].get("boxed") for i in idx]
        cls_rs = [r for r in rs if r["class_ok"] is not None]
        rows.append({
            "group": g, "n": len(idx),
            "visible": frac(sum(label_yes(v) for v in vis), sum(v is not None for v in vis), wilson),
            "boxed": frac(sum(label_yes(v) for v in box), sum(v is not None for v in box), wilson),
            "event_ok": frac(sum(r["event_ok"] for r in rs), len(rs), wilson),
            "direction_ok": frac(sum(r["direction_ok"] for r in rs), len(rs), wilson),
            "net_ok": frac(sum(r["net_ok"] for r in rs), len(rs), wilson),
            "class_ok": frac(sum(r["class_ok"] for r in cls_rs), len(cls_rs), wilson),
        })
    empties = [results[i] for i, a in enumerate(actions) if a["delta"] == 0]
    empty = {"n": len(empties), "with_events": frac(sum(not r["ok"] for r in empties), len(empties), wilson),
             "false_events": sum(r["false_events"] for r in empties)}
    return rows, empty


def git_rev():
    try:
        rev = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", HERE, "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return rev + ("（有未提交的改动）" if dirty else "")
    except Exception:
        return "?"


def score(truth_path, events_paths, pre=PRE_S):
    truth = load_json(truth_path)
    actions, ignore = resolve_windows(truth, truth_path)
    order = sorted(range(len(actions)), key=lambda i: actions[i]["start_s"])
    actions = [actions[i] for i in order]
    wilson = load_wilson()
    routes = []
    for p in events_paths:
        ev = load_json(p)
        per, outside, ignored = assign_events(actions, ev["events"], ignore, pre)
        results = [judge(a, e) for a, e in zip(actions, per)]
        rows, empty = summarize(actions, results, wilson)
        routes.append({"file": p, "route": ev.get("route", os.path.basename(p)), "provenance": ev.get("provenance", {}),
                       "time_base": ev.get("time_base"), "results": results, "summary": rows, "empty": empty,
                       "outside": outside, "ignored": len(ignored)})
    return {"truth": truth_path, "video": truth.get("video"), "actions": actions, "ignore": ignore,
            "routes": routes, "wilson": bool(wilson), "scorer_commit": git_rev(), "pre_s": pre}


def mark(v):
    return "—" if v is None else ("✓" if v else "✗")


def to_markdown(s):
    out = [f"# 逐动作打分：{s.get('video') or os.path.basename(s['truth'])}", ""]
    out.append(f"- 真值：`{s['truth']}`；打分程序版本 {s['scorer_commit']}；事件归属提前量 {s['pre_s']} 秒")
    if s["ignore"]:
        out.append(f"- 不算的时间段：{', '.join(f'{a:.1f}–{b:.1f}s' for a, b in s['ignore'])}")
    out.append("- 区间：" + ("用 eval/wilson.py 算的 95% 区间" if s["wilson"] else "没有 eval/wilson.py，只列 k/n"))
    for r in s["routes"]:
        tb = r.get("time_base") or {}
        out.append(f"- 路线 **{r['route']}**：`{r['file']}`；时间基准 {tb.get('source', '?')}"
                   f"（{tb.get('fps', '?')} 帧/秒）{('；' + tb['note']) if tb.get('note') else ''}")
    out.append("")
    for r in s["routes"]:
        out.append(f"## 路线：{r['route']}")
        out.append("")
        out.append("| 分组 | 动作数 | ① 人眼能认出 | ② 检测器框到 | ③ 计数正确 | 方向对 | 净数对 | 类别也对 |")
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in r["summary"]:
            out.append(f"| {row['group']} | {row['n']} | {row['visible']} | {row['boxed']} | {row['event_ok']} | "
                       f"{row['direction_ok']} | {row['net_ok']} | {row['class_ok']} |")
        e = r["empty"]
        out.append("")
        out.append(f"- 不该计数的动作（空开门、只碰到线、拿出又放回等，真值 delta = 0）：{e['n']} 次，"
                   f"其中有误计的 {e['with_events']}，误计事件共 {e['false_events']} 个")
        out.append(f"- 窗口外的误计：{len(r['outside'])} 个" +
                   (("（" + "；".join(f"{x['t']:.1f}s {'+' if x['delta'] > 0 else '-'}{x.get('cls')}"
                                     for x in r["outside"]) + "）") if r["outside"] else ""))
        if r["ignored"]:
            out.append(f"- 落在不算的时间段里的事件：{r['ignored']} 个（没计入）")
        out.append("")
    out.append("## 每个动作")
    out.append("")
    head = "| # | 物品 | 放在哪 | 真值 | 时间 | ① | ② | " + " | ".join(
        f"{r['route']}：事件 / ③ / 方向 / 类别" for r in s["routes"]) + " |"
    out.append(head)
    out.append("|" + " --- |" * (7 + len(s["routes"])))
    for i, a in enumerate(s["actions"]):
        cells = []
        for r in s["routes"]:
            x = r["results"][i]
            if a["delta"] == 0:
                cells.append(f"{x['seq'] or '·'} / {mark(x['ok'])}")
            else:
                cells.append(f"{x['seq'] or '·'} / {mark(x['event_ok'])} / {mark(x['direction_ok'])} / {mark(x['class_ok'])}")
        cls = a.get("cls")
        cls = "/".join(cls) if isinstance(cls, list) else (cls or "（不认识）")
        out.append(f"| {a.get('n', i + 1)} | {a.get('item', '')} {cls} | {a.get('where', '')} | {a['delta']:+d} | "
                   f"{a['start_s']:.1f}–{a['end_s']:.1f}s | {a.get('visible') or ''} | {a.get('boxed') or ''} | "
                   + " | ".join(cells) + " |")
    out.append("")
    out.append("说明：① ② 来自真值里人工填的 visible / boxed；③ 计数正确 = 方向对的事件正好 n 个且没有反向事件；"
               "净数对 = 事件加起来等于真值；类别只在计数正确且真值有类别时才算。规则见 eval/README.md。")
    for r in s["routes"]:
        prov = r.get("provenance") or {}
        if prov:
            out.append("")
            out.append(f"<details><summary>{r['route']} 的来历（模型、参数、版本）</summary>")
            out.append("")
            out.append("```json")
            out.append(json.dumps(prov, ensure_ascii=False, indent=1))
            out.append("```")
            out.append("</details>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="逐个动作打分（和识别路线无关）")
    ap.add_argument("truth")
    ap.add_argument("events", nargs="+", help="一个或多个事件文件（*.events.json），每个一条路线")
    ap.add_argument("--md", help="把结果写成 markdown 文件（默认只打印）")
    ap.add_argument("--json", help="把完整结果另存为 json")
    ap.add_argument("--pre", type=float, default=PRE_S, help="动作开始前多少秒的事件也算这个动作（默认 0.5）")
    a = ap.parse_args()
    s = score(a.truth, a.events, a.pre)
    md = to_markdown(s)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已写 {a.md}")
    else:
        print(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
