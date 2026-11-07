#!/usr/bin/env python3
"""统计 record_sessions.py 录下的开门会话，输出决定架构的几个数。

    python analyze_sessions.py                 # 默认 runs/sessions
    python analyze_sessions.py runs/sessions --contact   # 同时为每个会话拼一张关键帧缩略图

输出 runs/sessions/summary.md：
  - 会话数、有真值的会话数、可疑误触发（< 2 秒）、超时关门
  - 可见率：有"放入"真值的会话里，拍到至少 1 张关键帧的比例
  - YOLO 召回：真值物品里有多少被 YOLO 在该会话里看到过（按中文名模糊匹配）
  - 长尾清单：真值里出现的所有物品及次数，以及 YOLO 完全没见过的那些
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS_ZH = json.loads((HERE / "labels_zh.json").read_text(encoding="utf-8")) if (HERE / "labels_zh.json").exists() else {}


def zh(label: str) -> str:
    return LABELS_ZH.get(label, label)


def matches(truth_name: str, yolo_labels: dict[str, float]) -> str | None:
    t = truth_name.strip().lower()
    for label in yolo_labels:
        name = zh(label).lower()
        if t and (t in name or name in t or t == label.lower()):
            return label
    return None


def contact_sheet(session_dir: Path, keyframes: list[dict], limit: int = 8) -> Path | None:
    try:
        import cv2
    except ImportError:
        return None
    tiles = []
    for kf in keyframes[:limit]:
        img = cv2.imread(str(session_dir / kf["file"]))
        if img is None:
            continue
        img = cv2.resize(img, (320, int(img.shape[0] * 320 / img.shape[1])))
        cv2.putText(img, f"{kf['t']}s m={kf['motion']}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        tiles.append(img)
    if not tiles:
        return None
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    rows = [cv2.hconcat(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, w - r.shape[1], cv2.BORDER_CONSTANT) for r in rows]
    sheet = cv2.vconcat(rows)
    out = session_dir / "contact.jpg"
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(HERE / "runs" / "sessions"))
    ap.add_argument("--contact", action="store_true")
    args = ap.parse_args()
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

    with_truth = [s for s in sessions if not s[1]["truth"].get("skipped")]
    short = [s for s in sessions if s[1]["duration_s"] < 2]
    timeouts = [s for s in sessions if "超时" in str(s[1].get("closed_by", ""))]
    in_sessions = [s for s in with_truth if s[1]["truth"]["in"]]
    visible = [s for s in in_sessions if s[1]["keyframes"]]
    kf_counts = [len(s[1]["keyframes"]) for s in sessions]

    truth_items: Counter[str] = Counter()
    recalled: Counter[str] = Counter()
    missed: Counter[str] = Counter()
    yolo_used = any(s[1]["yolo"]["model"] for s in sessions)
    for _, s in with_truth:
        labels = s["yolo"]["labels"]
        for item in s["truth"]["in"] + s["truth"]["out"]:
            truth_items[item["name"]] += 1
            if yolo_used:
                if matches(item["name"], labels):
                    recalled[item["name"]] += 1
                else:
                    missed[item["name"]] += 1

    lines = [f"# 会话统计（{root}）", ""]
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 会话总数 | {len(sessions)} |")
    lines.append(f"| 记了真值的会话 | {len(with_truth)} |")
    lines.append(f"| 可疑误触发（< 2 秒） | {len(short)} |")
    lines.append(f"| 超时强制关门（疑似厨房灯） | {len(timeouts)} |")
    lines.append(f"| 有\"放入\"真值的会话 | {len(in_sessions)} |")
    if in_sessions:
        lines.append(f"| 其中拍到至少 1 张关键帧（可见率） | {len(visible)} / {len(in_sessions)} = {100 * len(visible) / len(in_sessions):.0f}% |")
    if kf_counts:
        lines.append(f"| 每会话关键帧数（均值 / 最大） | {sum(kf_counts) / len(kf_counts):.1f} / {max(kf_counts)} |")
    if yolo_used:
        total = sum(truth_items.values())
        hit = sum(recalled.values())
        lines.append(f"| YOLO 召回（真值物品被看到的比例） | {hit} / {total} = {100 * hit / max(total, 1):.0f}% |")
    lines.append("")
    lines.append("## 真值里出现的物品（家里常进出的清单）")
    lines.append("")
    lines.append("| 物品 | 次数 | YOLO 看到过 |")
    lines.append("| --- | --- | --- |")
    for name, n in truth_items.most_common():
        seen = "—" if not yolo_used else (f"{recalled[name]}/{n}")
        lines.append(f"| {name} | {n} | {seen} |")
    if yolo_used and missed:
        lines.append("")
        lines.append("## YOLO 一次都没认出来的（长尾）")
        lines.append("")
        lines.append("、".join(f"{k}×{v}" for k, v in missed.most_common()))
    lines.append("")
    lines.append("## 逐会话")
    lines.append("")
    lines.append("| 会话 | 时长 s | 触发 | 关门原因 | 关键帧 | 放入 | 拿出 | YOLO 标签 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for d, s in sessions:
        t = s["truth"]
        ins = "、".join(f"{i['name']}×{i['count']:g}" for i in t.get("in", [])) or ("（未记）" if t.get("skipped") else "无")
        outs = "、".join(f"{i['name']}×{i['count']:g}" for i in t.get("out", [])) or ("（未记）" if t.get("skipped") else "无")
        labels = "、".join(zh(k) for k in sorted(s["yolo"]["labels"], key=lambda k: -s["yolo"]["labels"][k])[:5])
        lines.append(f"| {s['id']} | {s['duration_s']} | {s.get('trigger', '')} | {s.get('closed_by', '')} | {len(s['keyframes'])} | {ins} | {outs} | {labels} |")
        if args.contact:
            contact_sheet(d, s["keyframes"])

    out = root / "summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
