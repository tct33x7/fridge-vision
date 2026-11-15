# -*- coding: utf-8 -*-
"""打分规则的单元测试：规则在看到 E03 / E04 数据之前写定，这些测试保证它照写的那样工作。

  python -m unittest discover -s eval/tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import score_actions as sa  # noqa: E402


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def ev(t, delta, cls="bottle"):
    return {"t": t, "delta": delta, "cls": cls}


def act(n, start, delta, cls="bottle", where="里面搁板", end=None, **kw):
    return {"n": n, "start_s": start, "end_s": end if end is not None else start + 3, "delta": delta,
            "cls": cls, "where": where, **kw}


class TestAssign(unittest.TestCase):
    def setUp(self):
        self.actions = [act(1, 10, 1), act(2, 30, -1), act(3, 50, 0)]

    def test_before_first_action_is_outside(self):
        per, outside, ignored = sa.assign_events(self.actions, [ev(5, 1)], [])
        self.assertEqual(len(outside), 1)
        self.assertEqual(sum(map(len, per)), 0)

    def test_pre_tolerance(self):
        per, outside, _ = sa.assign_events(self.actions, [ev(9.6, 1), ev(9.4, 1)], [])
        self.assertEqual(len(per[0]), 1)       # 9.6 >= 10 - 0.5
        self.assertEqual(len(outside), 1)      # 9.4 < 9.5

    def test_event_belongs_until_next_start(self):
        per, _, _ = sa.assign_events(self.actions, [ev(29.4, 1), ev(29.6, -1)], [])
        self.assertEqual(len(per[0]), 1)       # 29.4 < 30 - 0.5：还是第 1 个动作的
        self.assertEqual(len(per[1]), 1)

    def test_last_action_runs_to_end(self):
        per, _, _ = sa.assign_events(self.actions, [ev(999, 1)], [])
        self.assertEqual(len(per[2]), 1)

    def test_ignore_ranges(self):
        per, outside, ignored = sa.assign_events(self.actions, [ev(12, 1), ev(2, 1)], [[11, 13], [0, 3]])
        self.assertEqual(len(ignored), 2)
        self.assertEqual(sum(map(len, per)) + len(outside), 0)


class TestJudge(unittest.TestCase):
    def test_correct(self):
        r = sa.judge(act(1, 0, 1), [ev(1, 1)])
        self.assertTrue(r["event_ok"] and r["direction_ok"] and r["net_ok"] and r["class_ok"] and r["full_ok"])
        self.assertEqual((r["miss"], r["extra"]), (0, 0))

    def test_wrong_class(self):
        r = sa.judge(act(1, 0, 1), [ev(1, 1, "cup")])
        self.assertTrue(r["event_ok"])
        self.assertIs(r["class_ok"], False)
        self.assertFalse(r["full_ok"])

    def test_class_alias_list(self):
        r = sa.judge(act(1, 0, 1, cls=["bottle", "cup"]), [ev(1, 1, "cup")])
        self.assertTrue(r["class_ok"])

    def test_jitter_net_correct_but_not_event_correct(self):
        r = sa.judge(act(1, 0, 1), [ev(1, 1), ev(2, -1), ev(3, 1)])
        self.assertFalse(r["event_ok"])
        self.assertFalse(r["direction_ok"])
        self.assertTrue(r["net_ok"])
        self.assertIsNone(r["class_ok"])
        self.assertEqual((r["miss"], r["extra"]), (0, 2))

    def test_miss(self):
        r = sa.judge(act(1, 0, -1), [])
        self.assertFalse(r["event_ok"] or r["direction_ok"] or r["net_ok"])
        self.assertEqual((r["miss"], r["extra"]), (1, 0))

    def test_wrong_direction(self):
        r = sa.judge(act(1, 0, -1), [ev(1, 1)])
        self.assertFalse(r["direction_ok"])
        self.assertEqual((r["miss"], r["extra"]), (1, 1))

    def test_double_count(self):
        r = sa.judge(act(1, 0, 1), [ev(1, 1), ev(2, 1)])
        self.assertFalse(r["event_ok"])
        self.assertTrue(r["direction_ok"])
        self.assertFalse(r["net_ok"])
        self.assertEqual((r["miss"], r["extra"]), (0, 1))

    def test_two_items(self):
        self.assertTrue(sa.judge(act(1, 0, 2), [ev(1, 1), ev(2, 1)])["event_ok"])
        r = sa.judge(act(1, 0, 2), [ev(1, 1)])
        self.assertFalse(r["event_ok"])
        self.assertTrue(r["direction_ok"])
        self.assertEqual(r["miss"], 1)

    def test_long_tail_item_scored_on_direction_only(self):
        r = sa.judge(act(1, 0, 1, cls=None), [ev(1, 1, "sports ball")])
        self.assertTrue(r["event_ok"])
        self.assertIsNone(r["class_ok"])
        self.assertTrue(r["full_ok"])

    def test_empty_opening(self):
        self.assertTrue(sa.judge(act(1, 0, 0, cls=None), [])["ok"])
        r = sa.judge(act(1, 0, 0, cls=None), [ev(1, 1)])
        self.assertFalse(r["ok"])
        self.assertEqual(r["false_events"], 1)


class TestTags(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(sa.tags_of(act(1, 0, 1, where="门格·中间层")), ["门格"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, where="里面搁板·最上层")), ["搁板"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, cls=None, where="里面搁板")), ["搁板", "YOLO 不认识"])
        self.assertEqual(sa.tags_of(act(1, 0, -2, where="桌面")), ["其他位置", "一次多件"])
        self.assertEqual(sa.tags_of(act(1, 0, 0, cls=None, where="—")), ["不该计数（空开门等）"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, tags=["快速"])), ["搁板", "快速"])


class TestEndToEnd(unittest.TestCase):
    def test_windows_file_and_summary(self):
        with tempfile.TemporaryDirectory() as d:
            _dump({"windows": [{"n": 1, "start_s": 0, "end_s": 2}, {"n": 2, "start_s": 10, "end_s": 14},
                               {"n": 3, "start_s": 20, "end_s": 24}, {"n": 4, "start_s": 30, "end_s": 33}]},
                  os.path.join(d, "v.windows.json"))
            truth = {"video": "v.mp4", "ignore_windows": [1], "actions": [
                {"n": 1, "window": 2, "delta": 1, "cls": "bottle", "where": "里面搁板", "visible": "✓", "boxed": "✓"},
                {"n": 2, "window": 3, "delta": 1, "cls": None, "where": "门格", "visible": "✗", "boxed": "✗"},
                {"n": 3, "window": 4, "delta": 0, "cls": None, "where": "—"}]}
            tp = os.path.join(d, "v.truth.json")
            _dump(truth, tp)
            ep = os.path.join(d, "v.events.json")
            _dump({"route": "测试", "events": [ev(1, 1), ev(11, 1), ev(31, -1)]}, ep)
            s = sa.score(tp, [ep])
            r = s["routes"][0]
            self.assertEqual(r["ignored"], 1)                         # 第 1 个窗口被忽略
            self.assertEqual([x.get("event_ok") for x in r["results"][:2]], [True, False])
            self.assertFalse(r["results"][2]["ok"])                   # 空开门有误计
            rows = {row["group"]: row for row in r["summary"]}
            self.assertEqual(rows["全部有物品的动作"]["event_ok"], "1/2")
            self.assertEqual(rows["全部有物品的动作"]["visible"], "1/2")
            self.assertEqual(rows["门格"]["event_ok"], "0/1")
            md = sa.to_markdown(s)
            self.assertIn("| 全部有物品的动作 | 2 |", md)

    def test_missing_times_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "t.truth.json")
            _dump({"actions": [{"n": 1, "delta": 1, "cls": "bottle"}]}, tp)
            with self.assertRaises(SystemExit):
                sa.resolve_windows(sa.load_json(tp), tp)


if __name__ == "__main__":
    unittest.main()
