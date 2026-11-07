#!/usr/bin/env python3
"""把录好的会话关键帧整帧发给多模态大模型认名，和真值对比：VLM 直接看画面能叫出多少东西。

    python name_keyframes.py                               # 默认 runs/sessions，每会话最多 6 张（运动量最大的几张）
    python name_keyframes.py runs/sessions --max-per-session 4 --session 20261107_101010
    python name_keyframes.py --dry-run                     # 不调 API，只列出会发哪些帧
    python name_keyframes.py --fake                        # 不联网，用固定假结果把流程和汇总跑一遍
    python name_keyframes.py --force                       # 已认过的也重认（默认只补缺的和出错的）

需要环境变量 VLM_API_KEY（可选 VLM_BASE_URL、VLM_MODEL，见 vlm.py）。
每个会话目录写 naming.json（逐关键帧 name/category/count/confidence/raw/error/latency_s），根目录写 naming_summary.md：
  - 会话数、认名关键帧数、API 错误数、平均耗时
  - 认名召回：真值物品里有多少被 VLM 在该会话里叫出来过（中文名模糊匹配，同 analyze_sessions.py）
  - 认名精确率：VLM 给出的名字里有多少对得上真值
  - 逐物品、逐会话表，以及"待人工分类的失败"：有真值但一个都没认出的会话，附关键帧文件名，明天人工填 看不清/遮挡/不在画面/认错
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
UNKNOWN = {"", "unknown", "none", "未知", "看不清", "无"}


class FakeNamer:
    """--fake 用的替身：不联网，固定返回一个结果，只为离线检查流程和汇总。"""

    model = "fake"

    def name_item(self, img) -> dict:
        return {"name": "测试物品", "category": "other", "count": 1, "confidence": 0.5}


def matches(truth_name: str, names: list[str]) -> bool:
    """同 analyze_sessions.matches：不分大小写、互为子串即算对上。"""
    t = truth_name.strip().lower()
    return bool(t) and any(t in n or n in t for n in (x.strip().lower() for x in names) if n)


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ratio(a: int, b: int) -> str:
    return f"{a} / {b} = {100 * a / b:.0f}%" if b else "—"


def fmt_items(items: list[dict], skipped: bool = False) -> str:
    return "、".join(f"{i['name']}×{i['count']:g}" for i in items) or ("（未记）" if skipped else "无")


def pick_keyframes(keyframes: list[dict], n: int) -> list[dict]:
    """运动量最大的 n 张，再按时间排回去。"""
    top = sorted(keyframes, key=lambda k: (-k["motion"], k["t"]))[:n]
    return sorted(top, key=lambda k: k["t"])


def reusable(sdir: Path, force: bool, fake: bool) -> dict[str, dict]:
    """上次 naming.json 里可直接复用的条目（按文件名）：只复用成功的；真实模式不复用 --fake 的假结果。"""
    path = sdir / "naming.json"
    if force or not path.exists():
        return {}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))["keyframes"]
    except (json.JSONDecodeError, KeyError, TypeError):
        print(f"  {sdir.name}/naming.json 损坏，忽略")
        return {}
    return {k["file"]: k for k in old if not k.get("error") and (fake or k.get("model") != "fake")}


def call_namer(namer, img, sleep: float) -> tuple[dict | None, str | None, float]:
    """调一次 VLM，异常时歇一下再试一次。返回 (raw, error, latency_s)。"""
    for attempt in range(2):
        t0 = time.perf_counter()
        try:
            return namer.name_item(img), None, round(time.perf_counter() - t0, 2)
        except Exception as e:  # 网络、HTTP、编码失败都算一次失败
            err, lat = f"{type(e).__name__}: {e}"[:200], round(time.perf_counter() - t0, 2)
            if attempt == 0:
                time.sleep(sleep)
    return None, err, lat


def name_session(sdir: Path, s: dict, picked: list[dict], prev: dict[str, dict], namer, sleep: float) -> int:
    """给选中的关键帧认名，写 naming.json，返回本次新调用次数。"""
    fake = isinstance(namer, FakeNamer)
    entries, calls = [], 0
    for kf in picked:
        if kf["file"] in prev:
            entries.append(prev[kf["file"]])
            continue
        e = dict(file=kf["file"], t=kf["t"], motion=kf["motion"], name=None, category=None, count=None,
                 confidence=None, raw=None, error=None, latency_s=None, model=namer.model)
        path = sdir / kf["file"]
        img = cv2.imread(str(path)) if path.exists() else None
        if img is None:
            e["error"] = "读不到关键帧图片"
        else:
            raw, e["error"], e["latency_s"] = call_namer(namer, img, sleep)
            calls += 1
            if isinstance(raw, dict):
                e.update(raw=raw, name=str(raw.get("name") or "unknown"), category=raw.get("category"),
                         count=_num(raw.get("count")), confidence=_num(raw.get("confidence")))
            elif e["error"] is None:
                e["error"] = f"返回的不是 JSON 对象：{str(raw)[:80]}"
            if not fake:
                time.sleep(sleep)
        conf = f"（{e['confidence']:.2f}）" if e["confidence"] is not None else ""
        print(f"  {kf['file']} → {e['name'] or '错误：' + e['error']}{conf}", flush=True)
        entries.append(e)
    naming = {"id": s["id"], "model": namer.model, "updated": datetime.now().isoformat(timespec="seconds"), "keyframes": entries}
    (sdir / "naming.json").write_text(json.dumps(naming, ensure_ascii=False, indent=1), encoding="utf-8")
    return calls


def summarize(root: Path, sessions: list[tuple[Path, dict]], model: str, new_calls: int) -> list[str]:
    """汇总根目录下所有已有 naming.json 的会话（不只是本次处理的）。指标只算有真值且已认名的会话。"""
    truth_items: Counter[str] = Counter()
    recalled: Counter[str] = Counter()
    ok = err = pred = pred_hit = judged = with_truth = named = 0
    lats: list[float] = []
    rows: list[str] = []
    failures: list[str] = []
    for d, s in sessions:
        t = s["truth"]
        items = [] if t.get("skipped") else t.get("in", []) + t.get("out", [])
        with_truth += bool(items)
        ins, outs = fmt_items(t.get("in", []), t.get("skipped")), fmt_items(t.get("out", []), t.get("skipped"))
        try:
            kfs = json.loads((d / "naming.json").read_text(encoding="utf-8"))["keyframes"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            rows.append(f"| {s['id']} | {ins} | {outs} | 未认名 | — | — |")
            continue
        named += 1
        good = [k for k in kfs if not k.get("error")]
        ok, err = ok + len(good), err + len(kfs) - len(good)
        lats += [k["latency_s"] for k in kfs if k.get("latency_s") is not None]
        seen: dict[str, float] = {}
        unk = 0
        for k in good:
            nm = str(k.get("name") or "unknown").strip()
            if nm.lower() in UNKNOWN:
                unk += 1
            else:
                seen[nm] = max(seen.get(nm, 0.0), k.get("confidence") or 0.0)
        shown = "、".join([f"{nm}({c:.2f})" for nm, c in seen.items()] + ([f"unknown×{unk}"] if unk else [])) or "—"
        hit = 0
        for item in items:
            truth_items[item["name"]] += 1
            if matches(item["name"], list(seen)):
                recalled[item["name"]] += 1
                hit += 1
        if items:
            judged += 1
            pred += len(seen)
            pred_hit += sum(any(matches(i["name"], [nm]) for i in items) for nm in seen)
        kf_col = f"{len(good)}" + (f"（错 {len(kfs) - len(good)}）" if len(kfs) > len(good) else "")
        status = (f"{hit}/{len(items)}" + ("" if hit else " 未命中")) if items else "—"
        rows.append(f"| {s['id']} | {ins} | {outs} | {kf_col} | {shown} | {status} |")
        if items and not hit:
            why = "无关键帧" if not kfs else ("全部出错" if not good else "")
            failures.append(f"| {s['id']} | {fmt_items(items)} | {shown} | {'、'.join(k['file'] for k in kfs) or '—'} | {why} |  |")
    total, hits = sum(truth_items.values()), sum(recalled.values())
    lines = [f"# VLM 认名统计（{root}）", "", f"模型 {model}；本次新调用 {new_calls} 次；生成于 {datetime.now():%Y-%m-%d %H:%M}", "",
             "| 指标 | 值 |", "| --- | --- |", f"| 会话总数 | {len(sessions)} |", f"| 已认名的会话 | {named} |",
             f"| 已认名的关键帧 | {ok} |", f"| API 错误（含读图失败） | {err} |",
             f"| 平均耗时 | {sum(lats) / len(lats):.2f} s |" if lats else "| 平均耗时 | — |",
             f"| 有真值的会话（已认名 / 全部） | {judged} / {with_truth} |",
             f"| 认名召回（真值物品被 VLM 叫出来过） | {ratio(hits, total)} |",
             f"| 认名精确率（VLM 给的名字对得上真值） | {ratio(pred_hit, pred)} |",
             "", "## 真值里出现的物品（已认名的会话）", "", "| 物品 | 次数 | VLM 认出 |", "| --- | --- | --- |"]
    lines += [f"| {name} | {n} | {recalled[name]}/{n} |" for name, n in truth_items.most_common()]
    lines += ["", "## 逐会话", "", "| 会话 | 放入 | 拿出 | 认名关键帧 | VLM 认出（最高置信度） | 命中 |",
              "| --- | --- | --- | --- | --- | --- |", *rows,
              "", "## 待人工分类的失败（有真值但 VLM 一个都没认出）", "",
              "逐个打开关键帧看一眼，在最后一列填：看不清 / 遮挡 / 不在画面 / 认错。", ""]
    if failures:
        lines += ["| 会话 | 真值 | VLM 说 | 关键帧 | 备注 | 人工分类 |", "| --- | --- | --- | --- | --- | --- |", *failures]
    else:
        lines.append("无。")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=str(HERE / "runs" / "sessions"))
    ap.add_argument("--max-per-session", type=int, default=6, help="每会话最多发几张关键帧（取运动量最大的）")
    ap.add_argument("--session", default="", help="只处理这一个会话 id")
    ap.add_argument("--force", action="store_true", help="已认名的也重认（默认只补缺的和出错的）")
    ap.add_argument("--dry-run", action="store_true", help="不调 API 不写文件，只列出会发哪些帧")
    ap.add_argument("--fake", action="store_true", help="不联网，用固定假结果跑通流程（结果标 model=fake，真实运行不会复用）")
    ap.add_argument("--sleep", type=float, default=0.5, help="两次调用之间歇几秒；出错重试前也歇这么久")
    args = ap.parse_args()

    namer = None
    if args.fake:
        namer = FakeNamer()
    elif not args.dry_run:
        if not os.getenv("VLM_API_KEY"):
            print("缺少环境变量 VLM_API_KEY，无法调用多模态模型。请先 export VLM_API_KEY=...（可选 VLM_BASE_URL、VLM_MODEL，"
                  "默认通义千问 qwen-vl-plus）；或者用 --dry-run 只看会发哪些帧、--fake 离线跑通流程。", file=sys.stderr)
            return 2
        from vlm import VisionNamer

        namer = VisionNamer.from_env()

    root = Path(args.root)
    sessions = []
    for path in sorted(root.glob("*/session.json")):
        try:
            sessions.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            print("跳过损坏的", path)
    if not sessions:
        print(f"{root} 里没有会话。先跑 record_sessions.py。")
        return 1
    todo = [(d, s) for d, s in sessions if not args.session or args.session in (s.get("id"), d.name)]
    if not todo:
        print(f"{root} 里没有会话 {args.session}")
        return 1

    new_calls = pending_total = 0
    for d, s in todo:
        picked = pick_keyframes(s["keyframes"], args.max_per_session)
        prev = reusable(d, args.force, args.fake)
        pending = [k for k in picked if k["file"] not in prev]
        print(f"{s['id']}：关键帧 {len(s['keyframes'])} 张，选 {len(picked)} 张，复用 {len(picked) - len(pending)}，待发 {len(pending)}"
              + ("：" + "、".join(k["file"] for k in pending) if pending and args.dry_run else ""), flush=True)
        pending_total += len(pending)
        if not args.dry_run:
            new_calls += name_session(d, s, picked, prev, namer, args.sleep)
    if args.dry_run:
        print(f"\n--dry-run：共 {len(todo)} 个会话，会发 {pending_total} 张关键帧；没有调 API，也没写文件。")
        return 0
    lines = summarize(root, sessions, namer.model, new_calls)
    out = root / "naming_summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
