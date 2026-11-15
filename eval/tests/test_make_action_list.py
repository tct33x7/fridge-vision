# -*- coding: utf-8 -*-
"""抽签动作清单：配额都满足、不会拿出不在冰箱里的东西、同一个种子结果一样。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import make_action_list as mal  # noqa: E402
import score_actions as sa  # noqa: E402


class TestPlan(unittest.TestCase):
    def test_quota_and_consistency(self):
        for seed in range(30):
            chunks, left = mal.plan(mal.DEFAULT_SPEC, 3, seed)
            acts = [a for c in chunks for a in c]
            groups = {}
            for a in acts:
                groups[a["group"]] = groups.get(a["group"], 0) + 1
            self.assertEqual(groups, mal.DEFAULT_SPEC["quota"], f"seed {seed}")
            inside = {}
            for a in acts:
                names = a["item"].split(" + ")
                if a["delta"] > 0:
                    for n in names:
                        self.assertNotIn(n, inside, f"seed {seed}: 已经在里面又放入 {n}")
                        inside[n] = a["where"]
                elif a["delta"] < 0:
                    for n in names:
                        self.assertIn(n, inside, f"seed {seed}: 拿出不在里面的 {n}")
                        self.assertEqual(inside.pop(n), a["where"], f"seed {seed}: 拿出的位置不对 {n}")
                elif a["group"] == "拿出又放回":
                    self.assertIn(a["item"], inside, f"seed {seed}")
            self.assertEqual(inside, left)

    def test_same_seed_same_list(self):
        self.assertEqual(mal.plan(mal.DEFAULT_SPEC, 3, 5), mal.plan(mal.DEFAULT_SPEC, 3, 5))

    def test_truth_templates_have_groups_the_scorer_understands(self):
        chunks, left = mal.plan(mal.DEFAULT_SPEC, 3, 1)
        with tempfile.TemporaryDirectory() as d:
            mal.write(d, chunks, mal.DEFAULT_SPEC, 1, left)
            t = sa.load_json(os.path.join(d, "s1.truth.json"))
            self.assertTrue(os.path.isfile(os.path.join(d, "s1_动作清单.md")))
            for a in t["actions"]:
                tags = sa.tags_of(a)
                if a["delta"] != 0 and "门格" in a["where"]:
                    self.assertIn("门格", tags)
                if a["delta"] != 0 and a["cls"] is None:
                    self.assertIn("YOLO 不认识", tags)


if __name__ == "__main__":
    unittest.main()
