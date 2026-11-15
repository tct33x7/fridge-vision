# -*- coding: utf-8 -*-
"""对照检查：events_mac.py 整段一个窗口时，计数事件必须和 replay.py 完全一样（同一份检测缓存、同一套规则）。
需要本机 demos/yolo_web_counter/test_videos/ 里的录像和检测缓存（不进 git）；没有就跳过。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEMO = os.path.join(REPO, "demos", "yolo_web_counter")
VIDEOS = os.environ.get("BX_TEST_VIDEOS", os.path.join(DEMO, "test_videos"))
sys.path.insert(0, DEMO)


class TestParity(unittest.TestCase):
    def check(self, name, line):
        video = os.path.join(VIDEOS, f"{name}.mp4")
        cache = os.path.join(VIDEOS, f"{name}.light-off.conf-0.35.img-640.dets.json")
        if not (os.path.isfile(video) and os.path.isfile(cache)):
            self.skipTest(f"没有 {video} 或它的检测缓存")
        import replay
        from counter import PRESETS
        d = json.load(open(cache, encoding="utf-8"))
        want, _ = replay.run_counter(d, PRESETS["default"], line)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "e.json")
            subprocess.run([sys.executable, os.path.join(REPO, "eval", "events_mac.py"), video, "--windows", "whole",
                            "--line", ",".join(map(str, line)), "--out", out, "--cache-dir", VIDEOS],
                           check=True, capture_output=True)
            got = json.load(open(out, encoding="utf-8"))["events"]
        self.assertEqual([(e["frame"], e["tid"], e["cls"], e["delta"]) for e in got],
                         [(e["frame"], e["tid"], e["cls"], e["delta"]) for e in want])

    def test_jitter1(self):
        self.check("jitter1", [0.5, 0.0, 0.5, 1.0])

    def test_mix1(self):
        self.check("mix1", [0.5, 0.0, 0.5, 1.0])

    def test_synthetic(self):
        self.check("synthetic", [0.5, 0.0, 0.5, 1.0])


if __name__ == "__main__":
    unittest.main()
