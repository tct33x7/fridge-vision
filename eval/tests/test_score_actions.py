# -*- coding: utf-8 -*-
"""打分规则的单元测试：规则在看到 E03 / E04 数据之前写定，这些测试保证它照写的那样工作，
并且会让结果悄悄出错的输入一律报错停下。

  python -m unittest discover -s eval/tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
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
    # 动作 1：10–13s，动作 2：30–33s，动作 3：50–53s → 分界 8、21.5、41.5
    def setUp(self):
        self.actions = [act(1, 10, 1), act(2, 30, -1), act(3, 50, 0)]

    def test_boundaries(self):
        self.assertEqual(sa.boundaries(self.actions)[:3], [8.0, 21.5, 41.5])

    def test_before_first_action_is_outside(self):
        per, outside, _ = sa.assign_events(self.actions, [ev(7.9, 1), ev(8.0, 1)], [])
        self.assertEqual(len(outside), 1)
        self.assertEqual(len(per[0]), 1)

    def test_midpoint_between_actions(self):
        per, _, _ = sa.assign_events(self.actions, [ev(21.4, 1), ev(21.6, -1)], [])
        self.assertEqual(len(per[0]), 1)
        self.assertEqual(len(per[1]), 1)

    def test_late_event_of_previous_action_is_not_charged_to_next(self):
        # 板子路线以前用"确认时刻"，过线后几秒才出来；现在按过线时刻，且分界在中点
        per, _, _ = sa.assign_events(self.actions, [ev(16.0, 1)], [])
        self.assertEqual(len(per[0]), 1)

    def test_last_action_runs_to_end(self):
        per, _, _ = sa.assign_events(self.actions, [ev(999, 1)], [])
        self.assertEqual(len(per[2]), 1)

    def test_ignore_ranges_inclusive(self):
        per, outside, ignored = sa.assign_events(self.actions, [ev(15.5, 1), ev(16.0, 1), ev(2, 1)],
                                                 [[15, 16], [0, 3]])
        self.assertEqual(len(ignored), 3)
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
        self.assertTrue(sa.judge(act(1, 0, 1, cls=["bottle", "cup"]), [ev(1, 1, "cup")])["class_ok"])

    def test_two_different_items_need_each_class(self):
        a = act(1, 0, 2, cls=None, cls_multi=["apple", "banana"])
        self.assertTrue(sa.judge(a, [ev(1, 1, "banana"), ev(2, 1, "apple")])["class_ok"])
        self.assertFalse(sa.judge(a, [ev(1, 1, "apple"), ev(2, 1, "apple")])["class_ok"])

    def test_jitter_net_correct_but_not_event_correct(self):
        r = sa.judge(act(1, 0, 1), [ev(1, 1), ev(2, -1), ev(3, 1)])
        self.assertFalse(r["event_ok"] or r["direction_ok"])
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
        self.assertFalse(r["event_ok"] or r["net_ok"])
        self.assertTrue(r["direction_ok"])
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


class TestTagsAndLabels(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(sa.tags_of(act(1, 0, 1, where="门格·中间层")), ["门格"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, where="里面搁板·最上层")), ["搁板"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, cls=None, where="里面搁板")), ["搁板", "YOLO 不认识"])
        self.assertEqual(sa.tags_of(act(1, 0, -2, where="桌面")), ["其他位置", "一次多件"])
        self.assertEqual(sa.tags_of(act(1, 0, 0, cls=None, where="—")), ["不该计数（全部）"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, tags=["快速"])), ["搁板", "快速"])
        self.assertEqual(sa.tags_of(act(1, 0, 1, group="搁板")), ["搁板", "抽签分组：搁板"])

    def test_labels(self):
        w = []
        for v in ("✓", "√", "✔", "Y ", "yes", True, "是"):
            self.assertIs(sa.parse_label(v, w, "visible", 1), True, v)
        for v in ("✗", "×", "x", "N", "△", False):
            self.assertIs(sa.parse_label(v, w, "visible", 1), False, v)
        for v in (None, "", "  "):
            self.assertIsNone(sa.parse_label(v, w, "visible", 1))
        self.assertEqual(w, [])
        self.assertIsNone(sa.parse_label("好像有", w, "visible", 7))
        self.assertEqual(len(w), 1)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        _dump({"video": "v.mp4", "time_base": {"source": "sidecar", "fps": 15.0, "frames": 900},
               "windows": [{"n": k, "start_s": 10.0 * k, "end_s": 10.0 * k + 4} for k in range(1, 6)]},
              os.path.join(self.d.name, "v.windows.json"))
        self.tp = os.path.join(self.d.name, "v.truth.json")

    def tearDown(self):
        self.d.cleanup()

    def resolve(self, truth):
        truth = {"video": "v.mp4", **truth}
        _dump(truth, self.tp)
        return sa.resolve_windows(sa.load_json(self.tp), self.tp)

    def base_actions(self):
        return [{"n": 1, "window": 2, "delta": 1, "cls": "bottle", "where": "搁板"},
                {"n": 2, "window": [3, 4], "delta": -1, "cls": "bottle", "where": "搁板"}]

    def test_ok(self):
        actions, ignore, _ = self.resolve({"ignore_windows": [1, 5], "actions": self.base_actions()})
        self.assertEqual([(a["start_s"], a["end_s"]) for a in actions], [(20.0, 24.0), (30.0, 44.0)])
        self.assertEqual(ignore, [[10.0, 14.0], [50.0, 54.0]])

    def test_unused_window_is_an_error(self):
        with self.assertRaises(SystemExit) as cm:
            self.resolve({"ignore_windows": [1], "actions": self.base_actions()})
        self.assertIn("[5]", str(cm.exception))

    def test_same_window_twice(self):
        acts = self.base_actions() + [{"n": 3, "window": 2, "delta": 0, "cls": None}]
        with self.assertRaises(SystemExit):
            self.resolve({"ignore_windows": [1, 5], "actions": acts})

    def test_window_both_action_and_ignored(self):
        with self.assertRaises(SystemExit):
            self.resolve({"ignore_windows": [1, 2, 5], "actions": self.base_actions()})

    def test_overlapping_actions(self):
        acts = [act(1, 10, 1, end=20), act(2, 15, -1, end=25)]
        with self.assertRaises(SystemExit):
            self.resolve({"actions": acts})

    def test_ignore_overlapping_action(self):
        with self.assertRaises(SystemExit):
            self.resolve({"ignore": [[8, 11]], "actions": [act(1, 10, 1)]})

    def test_missing_times(self):
        with self.assertRaises(SystemExit):
            self.resolve({"actions": [{"n": 1, "delta": 1, "cls": "bottle"}]})

    def test_events_from_another_video_or_line_or_clock(self):
        truth = {"video": "v.mp4", "line": [1, 0.4, 0, 0.4], "ignore_windows": [1, 5], "actions": self.base_actions()}
        _dump(truth, self.tp)
        ep = os.path.join(self.d.name, "e.json")
        good = {"video": "v.mp4", "route": "r", "time_base": {"source": "sidecar", "fps": 15.0, "frames": 900},
                "provenance": {"line": [1, 0.4, 0, 0.4]}, "events": []}
        _dump(good, ep)
        sa.score(self.tp, [ep])
        for bad in ({"video": "w.mp4"}, {"provenance": {"line": [0.5, 0, 0.5, 1]}},
                    {"time_base": {"source": "header", "fps": 30.0, "frames": 900}},
                    {"time_base": {"source": "sidecar", "fps": 15.0, "frames": 450}}):
            _dump({**good, **bad}, ep)
            with self.assertRaises(SystemExit, msg=str(bad)):
                sa.score(self.tp, [ep])


class TestEndToEnd(unittest.TestCase):
    def test_summary_markdown_and_pool(self):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "s1.truth.json")
            _dump({"actions": [
                act(1, 10, 1, visible="✓", boxed="√"),
                act(2, 20, 1, cls=None, where="门格|上层", visible="✗", boxed=""),
                act(3, 30, 0, cls=None, where="—", group="空开门")]}, tp)
            ep = os.path.join(d, "s1.e.json")
            _dump({"route": "测试", "events": [ev(11, 1), ev(21, 1, "sports ball"), ev(31, -1)]}, ep)
            s = sa.score(tp, [ep])
            r = s["routes"][0]
            rows = {row["group"]: row for row in r["summary"]}
            self.assertEqual(rows["全部有物品的动作"]["event_ok"], "2/2")
            self.assertEqual(rows["全部有物品的动作"]["visible"], "1/2")
            self.assertEqual(rows["全部有物品的动作"]["boxed"], "1/1")      # 空着的不进分母
            self.assertEqual(rows["门格"]["event_ok"], "1/1")
            empties = {e["group"]: e for e in r["empty"]}
            self.assertEqual(empties["抽签分组：空开门"]["with_events"], "1/1")
            md = sa.to_markdown(s)
            self.assertIn("门格\\|上层", md)                                # 表格里的 | 被转义
            j1, j2 = os.path.join(d, "s1.score.json"), os.path.join(d, "s2.score.json")
            for j in (j1, j2):
                _dump(s, j)
            out = subprocess.run([sys.executable, os.path.join(HERE, "..", "pool_scores.py"), j1, j2],
                                 capture_output=True, text=True, check=True).stdout
            self.assertIn("| 全部有物品的动作 | 4 |", out)

    def test_wilson_hook_guards(self):
        with tempfile.TemporaryDirectory() as d:
            old = sa.HERE
            sa.HERE = d
            try:
                self.assertIsNone(sa.load_wilson()[0])
                with open(os.path.join(d, "wilson.py"), "w") as f:
                    f.write("import 不存在的模块\n")
                fn, note = sa.load_wilson()
                self.assertIsNone(fn)
                self.assertIn("出错", note)
                with open(os.path.join(d, "wilson.py"), "w") as f:
                    f.write("def wilsen(k, n):\n    return 0, 1\n")
                self.assertIn("没有叫 wilson", sa.load_wilson()[1])
                self.assertIn("百分数", sa.frac(1, 2, lambda k, n: (10.0, 90.0)))
                self.assertIn("（10–90%）", sa.frac(1, 2, lambda k, n: (0.1, 0.9)))
            finally:
                sa.HERE = old


if __name__ == "__main__":
    unittest.main()
