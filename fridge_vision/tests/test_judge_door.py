# -*- coding: utf-8 -*-
"""judge_door.py 的自检：取帧、拼图、回答怎么变成记账和问人、整条流程。全部不联网：模型是假的，回答是事先写好的。

  fridge_vision/.venv/bin/python -m unittest discover -s fridge_vision/tests -v

这里查的是"程序有没有照规则办"，不是"模型判得准不准"。准不准只能拿真的录像、真的模型去测。
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
import judge_door as jd  # noqa: E402


def make_video(path, seconds=6.0, fps=30):
    """一段假的录像：每一帧的灰度不一样，另写一份 .frames.json 记每一帧的时刻。"""
    n = int(seconds * fps)
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (128, 72))
    for i in range(n):
        vw.write(np.full((72, 128, 3), i % 250, np.uint8))
    vw.release()
    with open(os.path.splitext(path)[0] + ".frames.json", "w", encoding="utf-8") as f:
        json.dump({"t": [round(i / fps, 4) for i in range(n)]}, f)


def item(result="放入", desc="一瓶绿色的茶饮料", cls="bottle", count=1, where="门格"):
    return {"desc": desc, "cls": cls, "result": result, "count": count, "where": where, "frames": "#3-#6"}


def answer(items=(), reach="门格"):
    return {"timeline": "01：空手开门。02：手伸向门格。", "reach": reach, "hand_in": "一瓶饮料",
            "hand_out": "空手", "items": list(items), "confidence": "中"}


class TestFrames(unittest.TestCase):
    def test_every_half_second(self):
        ts = [i / 30 for i in range(90)]
        self.assertEqual(jd.pick_frames(ts, 1.0, 2.0), [(30, 0.0), (45, 0.5), (60, 1.0)])

    def test_same_frame_is_not_used_twice(self):
        # 录像中间停了几秒：0.5 秒和 1.0 秒那两下离得最近的都是第 2 帧，只取一次
        ts = [0.0, 0.1, 0.2, 5.0]
        self.assertEqual(jd.pick_frames(ts, 0.0, 1.0), [(0, 0.0), (2, 0.5)])

    def test_blank_stretch_is_measured(self):
        ts = [0.0, 0.1, 0.2, 5.0, 5.1]
        self.assertAlmostEqual(jd.longest_blank(ts, 0.0, 0.2), 0.1)
        self.assertAlmostEqual(jd.longest_blank(ts, 0.1, 5.1), 4.8)     # 录像中间停了 4.8 秒
        self.assertAlmostEqual(jd.longest_blank(ts, 1.0, 4.0), 3.0)     # 整段都没有画面
        self.assertAlmostEqual(jd.longest_blank(ts, 5.0, 9.0), 3.9)     # 时间写到了录像外面

    def test_sheets_are_2x2_and_padded_with_grey(self):
        cells = [(np.full((360, 640, 3), 200, np.uint8), k * 0.5) for k in range(5)]
        sheets = jd.make_sheets(cells)
        self.assertEqual(len(sheets), 2)
        for s in sheets:
            self.assertEqual(s.shape, (720, 1280, 3))
        self.assertEqual(sheets[0][700, 1200].tolist(), [200, 200, 200])   # 第一张四格都有画面
        self.assertEqual(sheets[1][100, 300].tolist(), [200, 200, 200])    # 第二张只有左上有画面
        for y, x in ((100, 900), (500, 300), (500, 900)):
            self.assertEqual(sheets[1][y, x].tolist(), [40, 40, 40])       # 别的三格是灰的
        self.assertEqual(sheets[0][2, 165].tolist(), [0, 0, 0])            # 左上角有一块黑底，上面写第几帧
        self.assertEqual(sheets[0][35, 165].tolist(), [200, 200, 200])     # 黑底只占左上角一小块


class TestSameSheetsAsBlindTest(unittest.TestCase):
    """程序发给模型的图，和 11-23 盲测时给评判看的图是不是同一批。要本机有那段录像才查，没有就跳过。"""
    RUNS = os.path.join(REPO, "fridge_vision", "runs")
    VIDEO = os.path.join(RUNS, "e03_position_20261112", "test_155907.mp4")
    KEY = os.path.join(RUNS, "e03_existing_20261123", "check", "key_T_main.json")
    SHEETS = os.path.join(RUNS, "e03_existing_20261123", "sheets", "T_main", "clip_A")

    def test_same_frames_and_same_pictures(self):
        if not (os.path.isfile(self.VIDEO) and os.path.isfile(self.KEY) and os.path.isdir(self.SHEETS)):
            self.skipTest("本机没有 11-23 那批录像和拼图")
        clip = jd.load_json(self.KEY)["clips"]["A"]
        ts = jd.timebase.load(self.VIDEO, quiet=True).t
        picks = jd.pick_frames(ts, clip["start_s"], clip["end_s"])
        self.assertEqual([i for i, _ in picks], clip["frames"])
        cells = jd.read_cells(self.VIDEO, [i for i, _ in picks])
        jpegs = [jd.to_jpeg(s) for s in jd.make_sheets([(cells[i], dt) for i, dt in picks])]
        self.assertEqual(len(jpegs), clip["sheets"])
        for k, jpg in enumerate(jpegs, 1):
            with open(os.path.join(self.SHEETS, f"{k:02d}.jpg"), "rb") as f:
                self.assertEqual(jpg, f.read(), f"第 {k} 张图和盲测时的不一样")


class TestAnswerRules(unittest.TestCase):
    def test_good_answer_passes(self):
        self.assertEqual(jd.check_answer(answer([item()])), [])
        self.assertEqual(jd.check_answer(answer([], reach="没有伸手")), [])

    def test_bad_answers_are_caught(self):
        self.assertTrue(jd.check_answer("放入一瓶"))
        self.assertTrue(jd.check_answer({"items": []}))
        for bad in (item(result="放进去"), item(count=0), item(count=True), item(count="1"),
                    item(where="冷冻室"), item(cls="饮料"), item(desc="")):
            self.assertTrue(jd.check_answer(answer([bad])), bad)
        self.assertTrue(jd.check_answer({**answer(), "items": "没有"}))
        self.assertTrue(jd.check_answer({**answer(), "reach": "伸了"}))

    def test_put_one_in(self):
        d = jd.decide(answer([item("放入")]))
        self.assertEqual([(b["delta"], b["cls"], b["where"]) for b in d["book"]], [(1, "bottle", "门格")])
        self.assertEqual((d["unchanged"], d["ask"]), ([], []))

    def test_take_one_out(self):
        d = jd.decide(answer([item("拿出", where="里面搁板")]))
        self.assertEqual([b["delta"] for b in d["book"]], [-1])

    def test_nothing_happened(self):
        d = jd.decide(answer([], reach="没有伸手"))
        self.assertEqual(d, {"book": [], "unchanged": [], "ask": []})
        self.assertEqual(jd.describe(d), "没有东西放入或拿出")

    def test_put_one_in_and_take_another_out(self):
        # 11-24 定的要做的情况：一次开门里放进一样、拿出另一样。两样各记各的，不能只记成"净变化 0"
        d = jd.decide(answer([item("放入", desc="一盒剩菜", cls="bowl", where="里面搁板"),
                              item("拿出", desc="一瓶可乐", cls="bottle", where="门格")]))
        self.assertEqual([(b["desc"], b["delta"]) for b in d["book"]], [("一盒剩菜", 1), ("一瓶可乐", -1)])
        self.assertEqual(d["ask"], [])

    def test_taken_out_and_put_back_is_not_booked(self):
        d = jd.decide(answer([item("没变")]))
        self.assertEqual((d["book"], d["ask"]), ([], []))
        self.assertEqual(len(d["unchanged"]), 1)

    def test_unclear_item_is_asked_not_booked(self):
        d = jd.decide(answer([item("判断不了", desc="一瓶深色的瓶子")]))
        self.assertEqual(d["book"], [])
        self.assertEqual(len(d["ask"]), 1)
        self.assertIn("一瓶深色的瓶子", d["ask"][0]["question"])

    def test_clear_items_are_booked_even_if_another_is_unclear(self):
        d = jd.decide(answer([item("放入", desc="一个苹果", cls="apple"), item("判断不了", desc="一瓶深色的瓶子")]))
        self.assertEqual([b["desc"] for b in d["book"]], ["一个苹果"])
        self.assertEqual(len(d["ask"]), 1)

    def test_two_of_the_same(self):
        d = jd.decide(answer([item("拿出", count=2)]))
        self.assertEqual(d["book"][0]["delta"], -2)

    def test_self_contradicting_answer_books_nothing(self):
        d = jd.decide(answer([item("放入")], reach="没有伸手"))
        self.assertEqual(d["book"], [])
        self.assertEqual(d["ask"][0]["question"], jd.ASK_WHOLE_DOOR)

    def test_unreadable_answer_books_nothing(self):
        d = jd.decide(answer([item(result="大概放进去了")]))
        self.assertEqual(d["book"], [])
        self.assertEqual(d["ask"][0]["why"], "回答读不懂")

    def test_names_are_empty_until_registration_exists(self):
        self.assertIsNone(jd.decide(answer([item()]))["book"][0]["name"])


class TestPromptAndSchemaAgree(unittest.TestCase):
    """提示词里说的填法，和程序认的填法，是不是同一套。改了一边忘了另一边，这里会报。"""

    def setUp(self):
        with open(jd.PROMPT_FILE, encoding="utf-8") as f:
            self.prompt = f.read()

    def test_every_field_is_explained(self):
        for key in list(jd.ANSWER_SCHEMA["properties"]) + list(jd.ANSWER_SCHEMA["properties"]["items"]["items"]["properties"]):
            self.assertIn(f"- {key}：", self.prompt)

    def test_every_allowed_word_is_in_the_prompt(self):
        for word in jd.RESULTS + jd.WHERES + jd.REACH + jd.CONFIDENCE:
            self.assertIn(f'"{word}"', self.prompt)
        for cls in jd.CLASSES:
            self.assertIn(cls, self.prompt)

    def test_schema_follows_the_interface_rules(self):
        # 接口的要求：每个对象都写明 additionalProperties: false，并且每一项都必填
        top, one = jd.ANSWER_SCHEMA, jd.ANSWER_SCHEMA["properties"]["items"]["items"]
        for obj in (top, one):
            self.assertIs(obj["additionalProperties"], False)
            self.assertEqual(sorted(obj["required"]), sorted(obj["properties"]))

    def test_example_line_in_prompt_is_valid_json_with_the_same_fields(self):
        line = next(ln for ln in self.prompt.splitlines() if ln.startswith('{"timeline"'))
        example = json.loads(line)
        self.assertEqual(list(example), list(jd.ANSWER_SCHEMA["properties"]))
        self.assertEqual(list(example["items"][0]), list(jd.ANSWER_SCHEMA["properties"]["items"]["items"]["properties"]))


class FakeModel:
    """假的模型：不联网。走的是真的 anthropic 库，只把最底下那层"发出去"换成这里的函数。"""

    def __init__(self, replies):
        import anthropic
        import httpx2
        from anthropic import DefaultHttpxClient
        self.replies, self.requests = list(replies), []
        self.client = anthropic.Anthropic(
            api_key="test-not-a-real-key", base_url="http://model.test", max_retries=0,
            http_client=DefaultHttpxClient(transport=httpx2.MockTransport(self._handle)))
        self._httpx2 = httpx2

    def _handle(self, request):
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, int):
            return self._httpx2.Response(reply, json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}})
        return self._httpx2.Response(200, headers={"request-id": "req_test"}, json=reply)


def reply(answer_obj=None, stop_reason="end_turn", text=None):
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]   # 模型先"想"了一块，文字在后面
    if answer_obj is not None or text is not None:
        content.append({"type": "text", "text": text if text is not None else json.dumps(answer_obj, ensure_ascii=False)})
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 9000, "output_tokens": 800}}


class TestWholeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.tmp.name, "door.mp4")
        make_video(self.video)
        self.windows = os.path.join(self.tmp.name, "door.windows.json")
        jd.save_json(self.windows, {"windows": [{"n": 1, "start_s": 0.5, "end_s": 2.5}, {"n": 2, "start_s": 3.0, "end_s": 5.4}]})
        self.out = os.path.join(self.tmp.name, "door_judge")
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_program(self, model, *flags):
        args = jd.parse_args([self.video, "--windows", self.windows, *flags])
        return jd.run(args, client=model.client, say=self.said.append)

    def result(self, door):
        return jd.load_json(os.path.join(self.out, f"door_{door:02d}", "result.json"))

    def test_without_send_nothing_leaves_the_machine(self):
        model = FakeModel([])
        results = self.run_program(model)
        self.assertEqual(model.requests, [])
        self.assertEqual([r["sent"] for r in results], [False, False])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "door_01", "01.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "door_01", "result.json")))
        self.assertIn("没有联网", " ".join(self.said))

    def test_send_asks_once_per_door_and_books(self):
        model = FakeModel([reply(answer([item("放入")])), reply(answer([], reach="没有伸手"))])
        self.run_program(model, "--send")
        self.assertEqual(len(model.requests), 2)
        req = model.requests[0]
        self.assertEqual(req["model"], "claude-haiku-5-5")
        self.assertEqual(req["output_config"], {"effort": "medium", "format": {"type": "json_schema", "schema": jd.ANSWER_SCHEMA}})
        for banned in ("temperature", "top_p", "top_k", "thinking", "fallbacks"):
            self.assertNotIn(banned, req)                      # 这个模型不收这些，或者用默认的
        self.assertEqual(len(req["messages"]), 1)
        blocks = req["messages"][0]["content"]
        with open(jd.PROMPT_FILE, encoding="utf-8") as f:
            self.assertEqual(blocks[0], {"type": "text", "text": f.read()})
        images = [b for b in blocks if b["type"] == "image"]
        r1 = self.result(1)
        self.assertEqual(len(images), r1["sheets"])
        self.assertEqual(len(r1["frames"]), 5)                  # 0.5–2.5 秒，每半秒一帧
        for k, im in enumerate(images, 1):                      # 发出去的图就是存在盘上的那几张
            self.assertEqual(im["source"]["media_type"], "image/jpeg")
            with open(os.path.join(self.out, "door_01", f"{k:02d}.jpg"), "rb") as f:
                self.assertEqual(base64.standard_b64decode(im["source"]["data"]), f.read())
        self.assertIn(f"全部 {len(images)} 张图", blocks[-1]["text"])
        self.assertTrue(r1["sent"])
        self.assertEqual([b["delta"] for b in r1["book"]], [1])
        self.assertEqual(r1["call"]["request_id"], "req_test")
        self.assertEqual((r1["call"]["input_tokens"], r1["call"]["output_tokens"]), (9000, 800))
        self.assertAlmostEqual(r1["call"]["cost_usd"], 0.0013)  # 9000×0.10 + 800×0.50，除以一百万
        self.assertEqual(self.result(2)["book"], [])
        summary = jd.load_json(os.path.join(self.out, "summary.json"))
        self.assertEqual((summary["sent"], summary["booked_items"], summary["questions"]), (2, 1, 0))
        self.assertIn("model.test", " ".join(self.said))        # 发之前说了发到哪

    def test_already_judged_doors_are_not_sent_again(self):
        model = FakeModel([reply(answer([item("放入")])), reply(answer([])), reply(answer([item("拿出")])), reply(answer([]))])
        self.run_program(model, "--send")
        self.run_program(model, "--send")
        self.assertEqual(len(model.requests), 2)                # 第二遍一张图都没发
        self.run_program(model, "--send", "--again")
        self.assertEqual(len(model.requests), 4)
        self.assertEqual([b["delta"] for b in self.result(1)["book"]], [-1])
        old = jd.load_json(os.path.join(self.out, "door_01", "result.prev-1.json"))
        self.assertEqual([b["delta"] for b in old["book"]], [1])   # 旧的回答留着

    def test_refusal_and_cut_off_answers_become_questions(self):
        model = FakeModel([reply(stop_reason="refusal"), reply(text='{"timeline": "01：', stop_reason="max_tokens")])
        self.run_program(model, "--send")
        for door, why in ((1, "模型拒绝回答"), (2, "回答太长，被截断了")):
            r = self.result(door)
            self.assertEqual(r["book"], [])
            self.assertEqual((r["ask"][0]["why"], r["ask"][0]["question"]), (why, jd.ASK_WHOLE_DOOR))

    def test_text_that_is_not_json_becomes_a_question(self):
        model = FakeModel([reply(text="我看不出来。"), reply(answer([]))])
        self.run_program(model, "--send")
        self.assertEqual(self.result(1)["ask"][0]["why"], "回答不是能读的 JSON")

    def test_wrong_key_stops_with_a_plain_message(self):
        model = FakeModel([401])
        with self.assertRaises(jd.JudgeError) as cm:
            self.run_program(model, "--send")
        self.assertIn("密钥", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.out, "door_01", "result.json")))

    def test_no_key_at_all_is_said_before_anything_is_sent(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
        with mock.patch.dict(os.environ, {**clean, "HOME": self.tmp.name}, clear=True):
            with self.assertRaises(jd.JudgeError) as cm:
                jd.make_client()
        self.assertIn("没有找到密钥", str(cm.exception))

    def test_very_long_door_opening_is_not_sent(self):
        model = FakeModel([reply(answer([]))])
        with mock.patch.object(jd, "MAX_SHEETS", 1):
            self.run_program(model, "--send")                  # 两次开门都要 2 张图，超过上限 1 张
        self.assertEqual(model.requests, [])
        self.assertEqual(self.result(1)["ask"][0]["why"], "开门太久")

    def test_events_file_is_accepted_by_the_scorer(self):
        model = FakeModel([reply(answer([item("放入")])), reply(answer([item("拿出", count=2, cls="other")]))])
        events_path = os.path.join(self.tmp.name, "door.items-v4.events.json")
        self.run_program(model, "--send", "--events-json", events_path)
        ev = jd.load_json(events_path)
        self.assertEqual([(e["delta"], e["cls"], e["door"]) for e in ev["events"]],
                         [(1, "bottle", 1), (-1, None, 2), (-1, None, 2)])
        truth = os.path.join(self.tmp.name, "door.truth.json")
        jd.save_json(truth, {"video": "door.mp4", "actions": [
            {"n": 1, "item": "茶饮料", "cls": "bottle", "delta": 1, "where": "门格", "window": 1},
            {"n": 2, "item": "两盒别的", "cls": None, "delta": -2, "where": "里面搁板", "window": 2}]})
        md = os.path.join(self.tmp.name, "score.md")
        done = subprocess.run([sys.executable, os.path.join(REPO, "eval", "score_actions.py"), truth, events_path, "--md", md],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(md, encoding="utf-8") as f:
            self.assertIn("2/2", f.read())                      # 两个动作都算计数正确

    def test_time_span_without_pictures_is_refused(self):
        args = jd.parse_args([self.video, "--start", "4.0", "--end", "30.0", "--send"])   # 录像只有 6 秒
        model = FakeModel([])
        with self.assertRaises(jd.JudgeError) as cm:
            jd.run(args, client=model.client, say=self.said.append)
        self.assertIn("没有画面", str(cm.exception))
        self.assertEqual(model.requests, [])

    def test_events_file_is_not_written_before_the_model_was_asked(self):
        events_path = os.path.join(self.tmp.name, "door.items-v4.events.json")
        self.run_program(FakeModel([]), "--events-json", events_path)
        self.assertFalse(os.path.exists(events_path))


if __name__ == "__main__":
    unittest.main()
