# -*- coding: utf-8 -*-
"""时间基准的单元测试：有 .frames.json 时用真实时间，帧数对不上时补齐 / 截掉，没有时按文件头并提示。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import timebase  # noqa: E402


def make_video(path, n, fps=30):
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for i in range(n):
        vw.write(np.full((48, 64, 3), i * 5 % 255, np.uint8))
    vw.release()


class TestTimeBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.d.name, "v.mp4")
        make_video(self.video, 20, fps=30)

    def tearDown(self):
        self.d.cleanup()

    def write_side(self, t):
        with open(timebase.sidecar_path(self.video), "w", encoding="utf-8") as f:
            json.dump({"t": t, "frames": len(t), "fps_measured": 15}, f)

    def test_header_fallback_warns(self):
        err = io.StringIO()
        with redirect_stderr(err):
            tb = timebase.load(self.video)
        self.assertEqual(tb.source, "header")
        self.assertAlmostEqual(tb.t[3], 0.1)
        self.assertIn("没有", err.getvalue())

    def test_sidecar_15fps_in_30fps_header(self):
        self.write_side([i / 15 for i in range(20)])
        tb = timebase.load(self.video, quiet=True)
        self.assertEqual(tb.source, "sidecar")
        self.assertAlmostEqual(tb.fps, 15, places=3)
        self.assertAlmostEqual(tb.t[15], 1.0)          # 按文件头会算成 0.5 秒

    def test_sidecar_with_pause_keeps_real_gap_and_fps(self):
        t = [i / 15 for i in range(10)] + [10 + i / 15 for i in range(10)]
        self.write_side(t)
        tb = timebase.load(self.video, quiet=True)
        self.assertAlmostEqual(tb.fps, 15, places=3)   # 暂停的大间隔不影响帧率
        self.assertAlmostEqual(tb.t[10], 10.0)
        self.assertEqual(tb.frame_at(5.0), 10)

    def test_small_mismatch_pads_or_truncates(self):
        self.write_side([i / 15 for i in range(18)])
        err = io.StringIO()
        with redirect_stderr(err):
            tb = timebase.load(self.video)
        self.assertEqual(len(tb), 20)
        self.assertAlmostEqual(tb.t[19] - tb.t[18], 1 / 15)
        self.assertIn("差 2 帧", err.getvalue())
        self.write_side([i / 15 for i in range(22)])
        self.assertEqual(len(timebase.load(self.video, quiet=True)), 20)

    def test_big_mismatch_is_an_error(self):
        self.write_side([i / 15 for i in range(10)])
        with self.assertRaises(SystemExit):
            timebase.load(self.video, quiet=True)

    def test_fps_override_without_sidecar(self):
        tb = timebase.load(self.video, fps_override=15)
        self.assertEqual(tb.source, "fps_override")
        self.assertAlmostEqual(tb.t[15], 1.0)

    def test_sidecar_beats_fps_override(self):
        self.write_side([i / 12 for i in range(20)])
        err = io.StringIO()
        with redirect_stderr(err):
            tb = timebase.load(self.video, fps_override=30)
        self.assertEqual(tb.source, "sidecar")
        self.assertAlmostEqual(tb.fps, 12, places=3)
        self.assertIn("忽略 --fps", err.getvalue())

    def test_fps_between(self):
        t = [i / 30 for i in range(20)]
        t += [t[-1] + (i + 1) / 15 for i in range(20)]
        tb = timebase.TimeBase(t, "sidecar", timebase.median_fps(t))
        self.assertAlmostEqual(tb.fps_between(0, 20), 30, places=3)
        self.assertAlmostEqual(tb.fps_between(20, 40), 15, places=3)


if __name__ == "__main__":
    unittest.main()
