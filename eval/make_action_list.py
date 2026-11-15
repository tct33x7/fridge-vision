#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 E04 这类正式测试生成"抽签"后的动作清单和真值模板：每组（搁板、门格、YOLO 不认识的东西、一手两样、快速、
空开门、拿出又放回）要做多少个动作按配额定好，顺序随机，并且保证不会出现"东西不在冰箱里却要拿出来"。

  python eval/make_action_list.py --out fridge_vision/runs/e04_overhead_2026111x --sessions 3 --seed 7
  python eval/make_action_list.py --spec 我的物品和配额.json --out ...        # 换成自己家的东西和配额

输出（每一段录像一份）：
  s1_动作清单.md      打印出来贴在冰箱边，照着做（编号、拿什么、放进 / 拿出、放在哪、怎么做）
  s1.truth.json      真值模板：每个动作已经写好 item / cls / delta / where / tags，录完只要补 window（或时间）和 visible / boxed
  抽签记录.json       用的配额、物品、随机种子（以后能原样重新生成）

规则：
- 一开始所有测试物品都在冰箱外面；每段录像接着上一段结束时的状态。
- "拿出"只会抽到当前在冰箱里的东西；"放入"只会抽到在外面的东西。
- 种子（--seed）写进抽签记录，同一个种子、同一份配额，生成的清单完全一样。
"""
import argparse
import json
import os
import random
import sys

DEFAULT_SPEC = {
    "items": [
        {"name": "瓶 1（乌龙茶）", "cls": "bottle", "places": ["门格", "里面搁板"]},
        {"name": "瓶 2（可乐）", "cls": "bottle", "places": ["门格", "里面搁板"]},
        {"name": "苹果", "cls": "apple", "places": ["里面搁板"]},
        {"name": "香蕉", "cls": "banana", "places": ["里面搁板"]},
        {"name": "碗", "cls": "bowl", "places": ["里面搁板"]},
        {"name": "蓝莓盒", "cls": None, "places": ["里面搁板"]},
        {"name": "榨菜袋", "cls": None, "places": ["里面搁板"]},
        {"name": "辣椒酱瓶", "cls": None, "places": ["门格", "里面搁板"]},
    ],
    # 每组一共做多少个（所有段加起来）。"一手两样"会从同一类 COCO 物品里挑两样一起拿。
    "quota": {
        "搁板": 12,          # YOLO 认识的东西，放在里面搁板，平常速度
        "门格": 10,          # 放进 / 拿出门格（用 places 里有"门格"的东西）
        "YOLO 不认识": 10,   # cls 为 null 的东西
        "一手两样": 4,
        "快速": 4,           # YOLO 认识的东西，尽量快
        "空开门": 8,         # 一半"伸手摸一下搁板"，一半"只开门看一眼"
        "拿出又放回": 4,     # 拿出来看一眼又放回去（不该计数）
    },
}

HOW = {
    "搁板": "平常速度",
    "门格": "平常速度",
    "YOLO 不认识": "平常速度",
    "一手两样": "一只手同时拿两样",
    "快速": "尽量快",
    "空开门": "",
    "拿出又放回": "拿出来，在门口看一眼，再放回原处",
}


def plan(spec, sessions, seed):
    rnd = random.Random(seed)
    items = spec["items"]
    inside = {}                       # 名字 -> 放在哪（只记在冰箱里的）
    todo = []
    for group, k in spec["quota"].items():
        todo += [group] * int(k)
    rnd.shuffle(todo)

    def candidates(group):
        """这一组现在能做的动作：[(说明字典)]。"""
        out = []
        coco = [i for i in items if i["cls"]]
        if group in ("搁板", "快速"):
            for i in coco:
                if "里面搁板" in i["places"]:
                    out.append(("in" if i["name"] not in inside else "out", [i], "里面搁板"))
        elif group == "门格":
            for i in items:
                if "门格" in i["places"]:
                    out.append(("in" if i["name"] not in inside else "out", [i], "门格"))
        elif group == "YOLO 不认识":
            for i in items:
                if not i["cls"]:
                    place = inside.get(i["name"]) or rnd.choice(i["places"])
                    out.append(("in" if i["name"] not in inside else "out", [i], place))
        elif group == "一手两样":
            pool_in = [i for i in coco if i["name"] not in inside and "里面搁板" in i["places"]]
            pool_out = [i for i in coco if inside.get(i["name"]) == "里面搁板"]
            if len(pool_in) >= 2:
                out.append(("in", rnd.sample(pool_in, 2), "里面搁板"))
            if len(pool_out) >= 2:
                out.append(("out", rnd.sample(pool_out, 2), "里面搁板"))
        elif group == "拿出又放回":
            for name, place in inside.items():
                out.append(("peek", [next(i for i in items if i["name"] == name)], place))
        elif group == "空开门":
            out.append(("empty", [], "—"))
        # 门格 / 搁板："拿出"要拿它原来放的地方
        fixed = []
        for kind, its, place in out:
            if kind == "out" and len(its) == 1:
                place = inside[its[0]["name"]]
                if group == "门格" and place != "门格":
                    continue
                if group in ("搁板", "快速") and place != "里面搁板":
                    continue
            fixed.append((kind, its, place))
        return fixed

    actions = []
    empty_kind = 0
    guard = 0
    while todo:
        guard += 1
        if guard > 10000:
            raise SystemExit("配额和物品对不上，排不出来：减少某一组的配额，或者多加几样东西")
        group = todo[0]
        cands = candidates(group)
        if not cands:                 # 现在做不了（比如冰箱里空着却要"拿出又放回"），换到后面
            todo.append(todo.pop(0))
            rnd.shuffle(todo)
            continue
        todo.pop(0)
        kind, its, place = rnd.choice(cands)
        tags = [group] if group in ("一手两样", "快速", "拿出又放回") else []
        if kind == "empty":
            empty_kind += 1
            what = "伸手摸一下搁板，什么都不拿，门开着约 5 秒" if empty_kind % 2 else "只开门看 5 秒就关上"
            actions.append({"item": "空开门", "cls": None, "delta": 0, "where": "—", "how": what, "group": group,
                            "tags": tags})
            continue
        if kind == "peek":
            i = its[0]
            actions.append({"item": i["name"], "cls": i["cls"], "delta": 0, "where": place, "how": HOW[group],
                            "group": group, "tags": tags})
            continue
        sign = 1 if kind == "in" else -1
        for i in its:
            if kind == "in":
                inside[i["name"]] = place
            else:
                inside.pop(i["name"], None)
        same = len({i["cls"] for i in its}) == 1
        act = {"item": " + ".join(i["name"] for i in its), "cls": its[0]["cls"] if same else None,
               "delta": sign * len(its), "where": place, "how": HOW[group], "group": group, "tags": tags}
        if not same:
            act["cls_multi"] = [i["cls"] for i in its]   # 两样不同的东西：每样都要对，不是"叫哪个都行"
        actions.append(act)

    # 按顺序平均分到几段（每段接着上一段结束时冰箱里的状态）
    size = -(-len(actions) // sessions)
    return [actions[s * size:(s + 1) * size] for s in range(sessions)], inside


def write(out_dir, chunks, spec, seed, left_inside):
    os.makedirs(out_dir, exist_ok=True)
    for s, acts in enumerate(chunks, start=1):
        truth = {"schema": "actions-v1", "video": f"（录完填，如 s{s}_201500.mp4）", "line": None,
                 "ignore_windows": [], "note": f"由 eval/make_action_list.py 生成，种子 {seed}，第 {s} 段",
                 "actions": []}
        lines = [f"# E04 第 {s} 段动作清单（种子 {seed}）", "",
                 "每个动作从**关着门**开始：开门 → 做 → 关门 → 退后一步不动，慢慢数到 10。做错了不要停，关门数到 10 后重做这一个。",
                 "录像开头和结尾：关着门不动站 5 秒，把正在走的秒表举在画面边上 2 秒。", "",
                 "| # | 拿什么 | 放入 / 拿出 | 放在哪 | 怎么做 | 做错了记在这里 |", "| --- | --- | --- | --- | --- | --- |"]
        for n, a in enumerate(acts, start=1):
            verb = {1: "放入", -1: "拿出", 2: "放入两样", -2: "拿出两样", 0: "不放不拿"}[a["delta"]]
            lines.append(f"| {n} | {a['item']} | {verb} | {a['where']} | {a['how']} | |")
            row = {"n": n, "item": a["item"], "cls": a["cls"], "delta": a["delta"], "where": a["where"],
                   "group": a["group"], "tags": a["tags"]}
            if a.get("cls_multi"):
                row["cls_multi"] = a["cls_multi"]
            truth["actions"].append(row)
        with open(os.path.join(out_dir, f"s{s}_动作清单.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(out_dir, f"s{s}.truth.json"), "w", encoding="utf-8") as f:
            json.dump(truth, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "抽签记录.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": seed, "sessions": len(chunks), "spec": spec,
                   "left_inside_at_end": left_inside}, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description="生成抽签后的动作清单和真值模板")
    ap.add_argument("--out", required=True, help="输出文件夹（建议放在 fridge_vision/runs/ 下，不进 git）")
    ap.add_argument("--spec", help="物品和配额（json，格式见 DEFAULT_SPEC）；默认用文件里的")
    ap.add_argument("--sessions", type=int, default=3, help="分几段录")
    ap.add_argument("--seed", type=int, required=True, help="随机种子（抽签号），会写进抽签记录")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8")) if a.spec else DEFAULT_SPEC
    chunks, left = plan(spec, a.sessions, a.seed)
    write(a.out, chunks, spec, a.seed, left)
    total = sum(len(c) for c in chunks)
    print(f"共 {total} 个动作，分 {len(chunks)} 段（{'、'.join(str(len(c)) for c in chunks)}），种子 {a.seed}；写在 {a.out}/")
    groups = {}
    for c in chunks:
        for x in c:
            groups[x["group"]] = groups.get(x["group"], 0) + 1
    print("  分组：" + "，".join(f"{g} {k}" for g, k in groups.items()))
    if left:
        print("  全部做完后还在冰箱里的测试物品：" + "、".join(f"{k}（{v}）" for k, v in left.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
