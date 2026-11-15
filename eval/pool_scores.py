#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把几段录像的打分合起来（E04 分三段录时用）：先对每段运行 score_actions.py --json，再把这些 json 合并。
同一条路线（route 名字相同）的动作放在一起重新汇总；某段缺了某条路线会提醒。

  python eval/pool_scores.py s1.score.json s2.score.json s3.score.json --md E04.score.md
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_actions as sa  # noqa: E402


def base_route(name):
    return re.sub(r"（[^（）]*）$", "", name)


def main():
    ap = argparse.ArgumentParser(description="把几段录像的打分合起来")
    ap.add_argument("scores", nargs="+", help="score_actions.py --json 的输出")
    ap.add_argument("--md", help="写成 markdown 文件（默认只打印）")
    a = ap.parse_args()

    parts = [(p, sa.load_json(p)) for p in a.scores]
    wilson, wilson_note = sa.load_wilson()
    routes = {}
    commits = set()
    for p, s in parts:
        commits.add(s.get("scorer_commit"))
        tag = os.path.basename(p).split(".")[0]
        for r in s["routes"]:
            d = routes.setdefault(base_route(r["route"]), {"actions": [], "results": [], "outside": 0, "files": []})
            for act, res in zip(s["actions"], r["results"]):
                d["actions"].append({**act, "n": f"{tag}#{act['n']}"})
                d["results"].append(res)
            d["outside"] += len(r["outside"])
            d["files"].append(p)
    warnings = []
    if len(commits) > 1:
        warnings.append(f"这几份打分用的打分程序版本不一样：{sorted(c or '?' for c in commits)}")
    for name, d in routes.items():
        if len(d["files"]) != len(parts):
            missing = [p for p, _ in parts if p not in d["files"]]
            warnings.append(f"路线 {name} 在 {missing} 里没有，合计里少了这几段")

    out = [f"# 合并打分（{len(parts)} 段）", "", f"- 来源：{'、'.join(f'`{p}`' for p, _ in parts)}", f"- 区间：{wilson_note}"]
    if warnings:
        out += ["", "**提醒**：", ""] + [f"- {sa.esc(w)}" for w in warnings]
    out.append("")
    for name, d in routes.items():
        rows, empty = sa.summarize(d["actions"], d["results"], wilson)
        out += [f"## 路线：{sa.esc(name)}", ""]
        out += sa.route_tables({"summary": rows, "empty": empty})
        out += [f"- 窗口外的误计：{d['outside']} 个（{len(d['files'])} 段合计）", ""]
    md = "\n".join(out) + "\n"
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已写 {a.md}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
