#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关门以后，判断这一次开门放进了什么、拿出了什么（2026-11-24 定下来的主线，见 docs/DECISIONS.md）。

一次开门的录像 → 每半秒取一帧 → 每 4 帧拼成一张图 → 交给最小一档的视觉模型
→ 回答里每样东西各写一项（放入 / 拿出 / 没变 / 判断不了）→ 说得清的记账，说不清的不记、问人一句。

  python judge_door.py 录像.mp4                               # 只切图、算一下大概多少钱，不联网
  python judge_door.py 录像.mp4 --send                        # 真的发给模型（要有密钥，见 README）
  python judge_door.py 录像.mp4 --windows 录像.windows.json   # 一段录像里有好几次开门（窗口文件来自 eval/propose_windows.py）
  python judge_door.py 录像.mp4 --start 49.1 --end 58.8       # 只判这一段（秒）

输出在 <录像名>_judge/ 里：每次开门一个文件夹，放拼图和 result.json；整段一份 summary.json。
拼图是整幅画面，可能拍到人，只留在本机，不要提交。

这个程序不管三件事：哪一段算"一次开门"（靠窗口文件或者手写时间）、东西叫什么名字（等登记做好）、问人的界面和库存。
"""
from __future__ import annotations

import argparse
import base64
import bisect
import datetime
import hashlib
import json
import os
import sys
from urllib.parse import urlparse

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "eval"))
import timebase  # noqa: E402  录像里第 i 帧是第几秒，全仓库用同一套

MODEL = "claude-haiku-5-5"            # 最小的一档；11-21 到 11-23 的数据都是在它上面得的
PROMPT_FILE = os.path.join(HERE, "prompts", "judge_items_v4_D.txt")
FRAMES_PER_SECOND = 2.0               # 每半秒一帧
CELL = (640, 360)                     # 拼图里每一格的宽、高
JPEG_QUALITY = 88
MAX_SHEETS = 40                       # 一次开门最多发 40 张图（80 秒）。再长就不发，直接问人
MAX_TOKENS = 16000                    # 回答的上限。模型会先想一想，想的部分也算在里面
EFFORT = "medium"                     # 让模型想多少。medium 是这个模型默认的那一档，这里写明白；没有比过别的档
TIMEOUT_S = 120.0
MAX_BLANK_S = 1.0                     # 一次开门里不许有超过 1 秒没有画面（录像暂停过、时间写错）
# 价目：美元 / 一百万 token（输入, 输出）。2026-11-03 的版本，提示不超过 10 万 token 时。别的模型不估价。
PRICE_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}
ROUGH_TOKENS_PER_SHEET = 1300         # 粗估用：一张 1280×720 的图大约这么多（11-22 按用量反推的）
ROUGH_OUTPUT_TOKENS = 1000

RESULTS = ("放入", "拿出", "没变", "判断不了")
WHERES = ("里面搁板", "门格", "看不清")
REACH = ("里面搁板", "门格", "两处都有", "没有伸手", "看不清")
CONFIDENCE = ("高", "中", "低")
CLASSES = ("bottle", "cup", "bowl", "wine glass", "fork", "knife", "spoon", "banana", "apple", "orange",
           "sandwich", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "other")

# 回答必须长成这样。发请求时交给接口，接口保证回来的是照这个格式写的 JSON；回来以后程序自己再查一遍。
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "timeline": {"type": "string"},
        "reach": {"type": "string", "enum": list(REACH)},
        "hand_in": {"type": "string"},
        "hand_out": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "desc": {"type": "string"},
                    "cls": {"type": "string", "enum": list(CLASSES)},
                    "result": {"type": "string", "enum": list(RESULTS)},
                    "count": {"type": "integer"},
                    "where": {"type": "string", "enum": list(WHERES)},
                    "frames": {"type": "string"},
                },
                "required": ["desc", "cls", "result", "count", "where", "frames"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
    },
    "required": ["timeline", "reach", "hand_in", "hand_out", "items", "confidence"],
    "additionalProperties": False,
}

ASK_WHOLE_DOOR = "这一次开门没有判出来。你放进了什么、拿出了什么？"


class JudgeError(Exception):
    """做不下去了（录像读不了、连不上、密钥不对……）。话是写给用的人看的。"""


# ---------- 第一步：取帧、拼图（和 11-21 到 11-23 盲测用的做法一样） ----------

def nearest(ts, t):
    """时刻表 ts 里离 t 最近的那一帧的帧号。"""
    i = bisect.bisect_left(ts, t)
    if i <= 0:
        return 0
    if i >= len(ts):
        return len(ts) - 1
    return i if ts[i] - t < t - ts[i - 1] else i - 1


def pick_frames(ts, start_s, end_s, fps=FRAMES_PER_SECOND):
    """从 start_s 到 end_s 每 1/fps 秒取一帧。返回 [(帧号, 离这一段开头几秒), …]。"""
    picks, k = [], 0
    while start_s + k / fps <= end_s + 1e-6:
        t = start_s + k / fps
        i = nearest(ts, t)
        if not picks or picks[-1][0] != i:
            picks.append((i, round(t - start_s, 2)))
        k += 1
    return picks


def longest_blank(ts, start_s, end_s):
    """start_s 到 end_s 之间，最长连续多少秒没有画面（录像暂停过、或者时间写到了录像外面，这个数就大）。"""
    inside = [t for t in ts[bisect.bisect_left(ts, start_s):bisect.bisect_right(ts, end_s)]]
    marks = [start_s] + inside + [end_s]
    return max(b - a for a, b in zip(marks, marks[1:]))


def read_cells(video, frame_numbers, cell=CELL):
    """把要用的那些帧读出来，缩成拼图里一格的大小。返回 {帧号: 图}。"""
    need = set(frame_numbers)
    if not need:
        return {}
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise JudgeError(f"打不开录像：{video}")
    got, idx, last = {}, 0, max(need)
    while idx <= last:
        if not cap.grab():
            break
        if idx in need:
            ok, frame = cap.retrieve()
            if not ok:
                break
            got[idx] = cv2.resize(frame, cell, interpolation=cv2.INTER_AREA)
        idx += 1
    cap.release()
    missing = sorted(need - set(got))
    if missing:
        raise JudgeError(f"录像里有 {len(missing)} 帧没读到，比如第 {missing[0]} 帧")
    return got


def make_sheets(cells, cell=CELL):
    """cells = [(一格的图, 离开头几秒), …]，按时间顺序。每 4 格拼成一张 2×2 的图，左上角写第几帧、第几秒。"""
    labelled = []
    for j, (image, dt) in enumerate(cells, 1):
        im = image.copy()
        cv2.rectangle(im, (0, 0), (170, 30), (0, 0, 0), -1)
        cv2.putText(im, f"#{j}  +{dt:.1f}s", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        labelled.append(im)
    blank = np.full((cell[1], cell[0], 3), 40, np.uint8)
    sheets = []
    for s in range((len(labelled) + 3) // 4):
        four = labelled[s * 4:s * 4 + 4]
        four += [blank] * (4 - len(four))
        sheets.append(np.vstack([np.hstack(four[:2]), np.hstack(four[2:])]))
    return sheets


def to_jpeg(image):
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise JudgeError("拼图存不成 JPEG")
    return buf.tobytes()


# ---------- 第二步：问模型 ----------

def build_content(prompt_text, jpegs):
    """发给模型的那一条消息：先是说明，然后一张一张的图，最后一句话收尾。"""
    n = len(jpegs)
    content = [{"type": "text", "text": prompt_text}]
    for k, jpg in enumerate(jpegs, 1):
        content.append({"type": "text", "text": f"第 {k} 张图（共 {n} 张）："})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.standard_b64encode(jpg).decode("ascii")}})
    content.append({"type": "text", "text": f"以上是这一段的全部 {n} 张图。请按【要判断什么】回答，只写 JSON。"})
    return content


def make_client():
    """连模型用的客户端。密钥从环境里取（ANTHROPIC_API_KEY 等），程序里不写密钥。"""
    try:
        import anthropic
    except ImportError:
        raise JudgeError("还没有装 anthropic 这个库：在 fridge_vision 目录里运行 .venv/bin/pip install -r requirements.txt")
    client = anthropic.Anthropic(timeout=TIMEOUT_S)
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise JudgeError("没有找到密钥：先设好环境变量 ANTHROPIC_API_KEY 再运行（怎么设见 fridge_vision/README.md）")
    return client


def ask_model(client, content, model=MODEL, effort=EFFORT):
    """发一次请求。返回 (回答, 附带信息)。回答是 dict；模型没给出能用的回答时是 None，原因写在附带信息的 problem 里。"""
    import anthropic

    output_config = {"effort": effort, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}}
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
            output_config=output_config,
        )
    except anthropic.AuthenticationError:
        raise JudgeError("密钥不对，或者没有密钥：检查环境变量 ANTHROPIC_API_KEY")
    except anthropic.PermissionDeniedError:
        raise JudgeError("这个密钥没有权限用这个模型")
    except anthropic.NotFoundError:
        raise JudgeError(f"找不到模型 {model}，或者接口地址不对")
    except anthropic.BadRequestError as e:
        raise JudgeError(f"请求被退回来了：{e.message}")
    except anthropic.RateLimitError:
        raise JudgeError("请求太频繁，过一会儿再试")
    except anthropic.APIStatusError as e:
        raise JudgeError(f"模型那边出错了（{e.status_code}），过一会儿再试")
    except anthropic.APIConnectionError:
        raise JudgeError("连不上模型（网络不通或者等太久）")
    except anthropic.AnthropicError as e:
        raise JudgeError(f"没有发出去：{e}")

    usage = response.usage
    info = {
        "model": response.model,
        "stop_reason": response.stop_reason,
        "request_id": response._request_id,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": cost_usd(model, usage.input_tokens, usage.output_tokens),
        "problem": None,
    }
    if response.stop_reason == "refusal":
        info["problem"] = "模型拒绝回答"
        return None, info
    if response.stop_reason == "max_tokens":
        info["problem"] = "回答太长，被截断了"
        return None, info
    # 回答里可能先有几块"想的过程"，要找的是文字那一块
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        info["problem"] = "回答里没有文字"
        return None, info
    try:
        return json.loads(text), info
    except json.JSONDecodeError:
        info["problem"] = "回答不是能读的 JSON"
        info["raw"] = text[:500]
        return None, info


def cost_usd(model, input_tokens, output_tokens):
    price = PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1e6, 6)


# ---------- 第三步：回答 → 记账，还是问人 ----------

def check_answer(answer):
    """回答的格式对不对。返回毛病的列表；空列表就是没毛病。"""
    if not isinstance(answer, dict):
        return ["回答不是一个 JSON 对象"]
    problems = []
    for key in ("timeline", "hand_in", "hand_out"):
        if not isinstance(answer.get(key), str):
            problems.append(f"{key} 应该是一段文字")
    if answer.get("reach") not in REACH:
        problems.append("reach 不是规定的五个词之一")
    if answer.get("confidence") not in CONFIDENCE:
        problems.append("confidence 不是 高 / 中 / 低")
    items = answer.get("items")
    if not isinstance(items, list):
        return problems + ["items 应该是一个列表"]
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"第 {n} 样东西不是一个对象")
            continue
        if not isinstance(item.get("desc"), str) or not item.get("desc"):
            problems.append(f"第 {n} 样东西没有描述")
        if item.get("cls") not in CLASSES:
            problems.append(f"第 {n} 样东西的类别不在名单里")
        if item.get("result") not in RESULTS:
            problems.append(f"第 {n} 样东西的 result 不是规定的四个词之一")
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            problems.append(f"第 {n} 样东西的件数不是正整数")
        if item.get("where") not in WHERES:
            problems.append(f"第 {n} 样东西的位置不是规定的三个词之一")
    return problems


def decide(answer):
    """回答 → {"book": 要记的账, "unchanged": 拿了又放回的, "ask": 要问人的话}。

    规则（11-24 定的）：说得清的记；说不清的不记，问一句。
    - 回答读不懂、或者自己前后矛盾（说手没伸进去，又列了放入或拿出），整次开门都不记，问一句。
    - 每样东西各看各的：放入、拿出 → 记；没变 → 不记也不问；判断不了 → 不记，问这一样。
    名字现在一律是空的（等登记做好）；所以这里记的账只有"什么样的东西、多了还是少了几件"。
    """
    out = {"book": [], "unchanged": [], "ask": []}
    problems = check_answer(answer)
    if problems:
        out["ask"].append({"why": "回答读不懂", "detail": problems, "question": ASK_WHOLE_DOOR})
        return out
    items = answer["items"]
    if answer["reach"] == "没有伸手" and any(it["result"] in ("放入", "拿出") for it in items):
        out["ask"].append({"why": "回答前后矛盾", "detail": ["说手没有伸进冰箱，又列了放入或拿出的东西"],
                           "question": ASK_WHOLE_DOOR})
        return out
    for item in items:
        entry = {"name": None, "desc": item["desc"], "cls": item["cls"], "where": item["where"], "count": item["count"]}
        if item["result"] == "放入":
            out["book"].append({**entry, "delta": item["count"]})
        elif item["result"] == "拿出":
            out["book"].append({**entry, "delta": -item["count"]})
        elif item["result"] == "没变":
            out["unchanged"].append(entry)
        else:
            out["ask"].append({"why": "判断不了", "item": entry,
                               "question": f"有一样东西没看清最后去了哪：{item['desc']}。它是放进去了、拿走了，还是没动？"})
    return out


def describe(decision):
    """一句话说这次开门的结果，给终端看。"""
    parts = []
    for b in decision["book"]:
        parts.append(f"{'放入' if b['delta'] > 0 else '拿出'} {abs(b['delta'])} 件：{b['desc']}（{b['where']}）")
    for u in decision["unchanged"]:
        parts.append(f"拿了又放回：{u['desc']}")
    for a in decision["ask"]:
        parts.append(f"要问：{a['question']}")
    return "；".join(parts) if parts else "没有东西放入或拿出"


def to_events(video_name, time_base, results, route):
    """换成 eval/score_actions.py 能打分的事件文件（events-v1）。只有记了账的才出事件；要问人的不出。"""
    events = []
    for r in results:
        mid = round((r["start_s"] + r["end_s"]) / 2, 3)
        for b in r["book"]:
            for _ in range(abs(b["delta"])):
                events.append({"t": mid, "delta": 1 if b["delta"] > 0 else -1,
                               "cls": None if b["cls"] == "other" else b["cls"], "door": r["door"]})
    first = results[0] if results else {}
    return {
        "schema": "events-v1",
        "video": video_name,
        "route": route,
        "time_base": time_base,
        "provenance": {
            "method": "关门以后看手里东西的前后状态：每次开门每 1/fps 秒取一帧拼成图，交给视觉模型，每样东西各记一笔",
            "program": "fridge_vision/judge_door.py",
            "model": first.get("model"),
            "prompt": first.get("prompt"),
            "frames_per_second": FRAMES_PER_SECOND,
            "cell": list(CELL),
            "assumes": "哪一段算一次开门是事先给定的（窗口文件或手写时间）",
            "asked_instead_of_booked": sum(len(r["ask"]) for r in results),
            "made_at": now_text(),
        },
        "judgements": [{k: r.get(k) for k in ("door", "start_s", "end_s", "answer", "problem", "book", "unchanged", "ask")}
                       for r in results],
        "events": events,
    }


# ---------- 把上面三步串起来 ----------

def now_text():
    """北京时间（这个项目的记录都用北京时间）。"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_doors(args, time_base):
    """这段录像里要判哪几次开门：[{"door": 编号, "start_s": 开始, "end_s": 结束}, …]。"""
    if args.windows:
        windows = load_json(args.windows)["windows"]
        return [{"door": w["n"], "start_s": w["start_s"], "end_s": w["end_s"]} for w in windows]
    start = args.start if args.start is not None else 0.0
    end = args.end if args.end is not None else time_base.t[-1]
    if end <= start:
        raise JudgeError("结束时间要比开始时间晚")
    return [{"door": 1, "start_s": start, "end_s": end}]


def rough_cost(model, prompt_text, n_sheets):
    tokens_in = n_sheets * ROUGH_TOKENS_PER_SHEET + len(prompt_text) + 200
    return tokens_in, cost_usd(model, tokens_in, ROUGH_OUTPUT_TOKENS)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def keep_old(path):
    """已经有一份真的回答了：把它改名留着，不盖掉。"""
    k = 1
    while os.path.exists(f"{path[:-5]}.prev-{k}.json"):
        k += 1
    os.rename(path, f"{path[:-5]}.prev-{k}.json")


def run(args, client=None, say=print):
    """主流程。client 可以从外面给（测试时用假的）；不给就在要发的时候自己建。返回每次开门的结果列表。"""
    if not os.path.isfile(args.video):
        raise JudgeError(f"找不到录像：{args.video}")
    with open(args.prompt, encoding="utf-8") as f:
        prompt_text = f.read()
    prompt_info = {"file": os.path.basename(args.prompt), "sha256": sha256_text(prompt_text)}
    time_base = timebase.load(args.video)
    doors = load_doors(args, time_base)
    out_dir = args.out or os.path.splitext(args.video)[0] + "_judge"

    for d in doors:
        d["picks"] = pick_frames(time_base.t, d["start_s"], d["end_s"])
        blank = longest_blank(time_base.t, d["start_s"], d["end_s"])
        if not d["picks"] or blank > MAX_BLANK_S:
            raise JudgeError(f"第 {d['door']} 次开门（{d['start_s']:.1f}–{d['end_s']:.1f} 秒）里有 {blank:.1f} 秒没有画面："
                             "录像在这一段停过，或者时间写错了")
    cells = read_cells(args.video, [i for d in doors for i, _ in d["picks"]])

    results, announced = [], False
    for d in doors:
        door_dir = os.path.join(out_dir, f"door_{d['door']:02d}")
        os.makedirs(door_dir, exist_ok=True)
        jpegs = [to_jpeg(s) for s in make_sheets([(cells[i], dt) for i, dt in d["picks"]])]
        for k, jpg in enumerate(jpegs, 1):
            with open(os.path.join(door_dir, f"{k:02d}.jpg"), "wb") as f:
                f.write(jpg)
        result = {
            "schema": "door-judgement-v1", "video": os.path.basename(args.video), "door": d["door"],
            "start_s": d["start_s"], "end_s": d["end_s"], "frames": [i for i, _ in d["picks"]], "sheets": len(jpegs),
            "prompt": prompt_info, "model": args.model, "sent": False, "answer": None, "problem": None,
            "book": [], "unchanged": [], "ask": [], "call": None, "made_at": now_text(),
        }
        head = f"第 {d['door']} 次开门（{d['start_s']:.1f}–{d['end_s']:.1f} 秒，{len(d['picks'])} 帧，{len(jpegs)} 张图）"
        result_path = os.path.join(door_dir, "result.json")
        old = load_json(result_path) if os.path.exists(result_path) else None
        judged_before = bool(old and old.get("sent"))

        if len(jpegs) > MAX_SHEETS:
            result["problem"] = f"这次开门太长（{len(jpegs)} 张图，上限 {MAX_SHEETS} 张），没有发给模型"
            result["ask"] = [{"why": "开门太久", "detail": [result["problem"]], "question": ASK_WHOLE_DOOR}]
            say(f"{head}：{result['problem']}。要问：{ASK_WHOLE_DOOR}")
        elif not args.send:
            tokens_in, rough = rough_cost(args.model, prompt_text, len(jpegs))
            say(f"{head}：没有发。粗估输入 {tokens_in} 个 token" + (f"，约 {rough:.4f} 美元" if rough is not None else ""))
            results.append(result)
            continue
        elif judged_before and not args.again:
            say(f"{head}：以前判过了，没有重发（要重判加 --again）。上次的结果：{describe(old)}")
            results.append(old)
            continue
        else:
            if client is None:
                client = make_client()
            if not announced:
                host = urlparse(str(client.base_url)).hostname or "?"
                say(f"下面会把拼图（整幅画面，可能拍到人）发到 {host}，模型 {args.model}。")
                announced = True
            answer, call = ask_model(client, build_content(prompt_text, jpegs), args.model, args.effort)
            decision = decide(answer) if answer is not None else {
                "book": [], "unchanged": [], "ask": [{"why": call["problem"], "detail": [], "question": ASK_WHOLE_DOOR}]}
            result.update(sent=True, answer=answer, problem=call["problem"], model=call["model"], call=call, **decision)
            say(f"{head}：{describe(decision)}")

        if judged_before:
            keep_old(result_path)
        save_json(result_path, result)
        results.append(result)

    sent = [r for r in results if r["sent"]]
    costs = [r["call"]["cost_usd"] for r in sent]
    summary = {
        "video": os.path.basename(args.video), "time_base": time_base.describe(), "prompt": prompt_info,
        "doors": len(results), "sent": len(sent),
        "booked_items": sum(len(r["book"]) for r in results), "questions": sum(len(r["ask"]) for r in results),
        "input_tokens": sum(r["call"]["input_tokens"] for r in sent),
        "output_tokens": sum(r["call"]["output_tokens"] for r in sent),
        "cost_usd": None if None in costs else round(sum(costs), 6), "made_at": now_text(),
    }
    save_json(os.path.join(out_dir, "summary.json"), summary)
    if sent:
        money = f"，一共约 {summary['cost_usd']:.4f} 美元" if summary["cost_usd"] is not None else ""
        say(f"这段录像问过模型的开门一共 {len(sent)} 次：记账 {summary['booked_items']} 笔，要问 {summary['questions']} 句{money}。")
    else:
        say("这一遍没有联网。确认拼图没问题以后，加 --send 才会发给模型。")
    say(f"拼图和结果在：{out_dir}")
    if args.events_json and any(not r["sent"] and not r["problem"] for r in results):
        say("有的开门还没有问过模型，所以没有写事件文件。")
    elif args.events_json:
        if os.path.exists(args.events_json):
            raise JudgeError(f"已存在，不覆盖：{args.events_json}")
        save_json(args.events_json, to_events(os.path.basename(args.video), time_base.describe(), results, args.route))
        say(f"事件文件：{args.events_json}")
    return results


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="关门以后判断这一次开门放进了什么、拿出了什么")
    ap.add_argument("video", help="录像文件")
    ap.add_argument("--windows", help="窗口文件（一段录像里有好几次开门时用）")
    ap.add_argument("--start", type=float, help="只判一段：开始的秒数")
    ap.add_argument("--end", type=float, help="只判一段：结束的秒数")
    ap.add_argument("--send", action="store_true", help="真的发给模型（不加就只切图、估价）")
    ap.add_argument("--again", action="store_true", help="以前判过的也重新发（旧的回答会留着）")
    ap.add_argument("--out", help="输出目录（默认 <录像名>_judge）")
    ap.add_argument("--prompt", default=PROMPT_FILE, help="提示词文件（换了机位要换一份）")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high", "xhigh", "max"], help="让模型想多少（默认 medium）")
    ap.add_argument("--events-json", help="另外写一份 eval/score_actions.py 能打分的事件文件")
    ap.add_argument("--route", default="handstate-items-v4", help="事件文件里的路线名")
    args = ap.parse_args(argv)
    if args.windows and (args.start is not None or args.end is not None):
        ap.error("--windows 和 --start / --end 只能用一种")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except JudgeError as e:
        sys.exit(f"没做成：{e}")


if __name__ == "__main__":
    main()
