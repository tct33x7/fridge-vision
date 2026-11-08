"""开门检测与待机（app/services/door_watcher.py）的单元测试，用合成画面，不需要摄像头。

在仓库根目录运行：
    fridge_vision/.venv/bin/python -m unittest orangepi_app/tests/test_door_watcher.py -v
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

import numpy as np

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
if "app" not in sys.modules:  # 不导入整个网站（app/__init__.py 会加载 FastAPI）
    pkg = types.ModuleType("app")
    pkg.__path__ = [str(APP_DIR / "app")]
    sys.modules["app"] = pkg

from app.services.door_watcher import DoorConfig, DoorWatcher, parse_roi  # noqa: E402

FPS = 15


class Scene:
    """640×480 的灰色背景 + 噪点，可以加一个移动的方块、整体调亮。"""

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)
        y, x = np.mgrid[0:480, 0:640]
        self.base = (90 + 40 * np.sin(x / 50.0) + 30 * np.cos(y / 40.0)).astype(np.float32)

    def frame(self, box_x=None, gain=0.0):
        img = self.base + gain + self.rng.normal(0, 3, self.base.shape)
        if box_x is not None:
            img[150:330, int(box_x):int(box_x) + 120] = 230
        img = np.clip(img, 0, 255).astype(np.uint8)
        return np.dstack([img, img, img])


def run(watcher, scene, seconds, start, **kw):
    """喂 seconds 秒的画面，返回 (结束时间, 这段里发生的切换列表)。"""
    changes = []
    n = int(seconds * FPS)
    for i in range(n):
        t = start + i / FPS
        args = {k: (v(i) if callable(v) else v) for k, v in kw.items()}
        c = watcher.observe(scene.frame(**args), t)
        if c:
            changes.append((round(t, 2), c))
    return start + n / FPS, changes


class DoorWatcherTest(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.w = DoorWatcher(DoorConfig())
        self.w.reset(now=0.0)

    def test_still_scene_stays_standby(self):
        t, ch = run(self.w, self.scene, 30, 0.0)
        self.assertEqual(ch, [])
        self.assertEqual(self.w.state, DoorWatcher.STANDBY)

    def test_global_brightening_is_not_motion(self):
        t, _ = run(self.w, self.scene, 4, 0.0)
        # 自动曝光：整幅画面在 1 秒里慢慢亮 15 —— 不算画面变化，也没超过亮度阈值
        t, ch = run(self.w, self.scene, 1, t, gain=lambda i: i)
        self.assertEqual(ch, [])

    def test_fridge_light_wakes(self):
        t, _ = run(self.w, self.scene, 4, 0.0)
        t, ch = run(self.w, self.scene, 1, t, gain=40)
        self.assertEqual([c for _, c in ch][:1], ["wake"])
        self.assertIn("亮度", self.w.wake_reason)

    def test_moving_object_wakes_fast_then_sleeps(self):
        t, _ = run(self.w, self.scene, 4, 0.0)
        t_move = t
        t, ch = run(self.w, self.scene, 3, t, box_x=lambda i: 100 + 12 * i)
        wakes = [tt for tt, c in ch if c == "wake"]
        self.assertTrue(wakes, "有东西动时应唤醒")
        self.assertLess(wakes[0] - t_move, 0.6, "唤醒应在 0.6 秒内")
        # 方块停在画面里不动：sleep_seconds 后待机，并且停着的方块成为新背景
        t, ch = run(self.w, self.scene, 8, t, box_x=400)
        sleeps = [tt for tt, c in ch if c == "sleep"]
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0] - t + 8, 6.0, delta=0.5)
        t, ch = run(self.w, self.scene, 10, t, box_x=400)
        self.assertEqual(ch, [], "静止的新样子不应再唤醒")

    def test_hesitation_shorter_than_sleep_keeps_active(self):
        t, _ = run(self.w, self.scene, 4, 0.0)
        t, _ = run(self.w, self.scene, 1, t, box_x=lambda i: 100 + 12 * i)
        t, ch = run(self.w, self.scene, 4, t, box_x=280)          # 停 4 秒（犹豫）
        self.assertEqual(ch, [])
        self.assertTrue(self.w.active)
        t, ch = run(self.w, self.scene, 1, t, box_x=lambda i: 280 - 12 * i)
        self.assertEqual(ch, [])

    def test_max_active_forces_standby(self):
        w = DoorWatcher(DoorConfig(max_active_seconds=5))
        w.reset(now=0.0)
        t, _ = run(w, self.scene, 4, 0.0)
        reasons = []
        for i in range(int(7 * FPS)):
            c = w.observe(self.scene.frame(box_x=100 + 5 * (i % 60)), t + i / FPS)
            if c == "sleep":
                reasons.append(w.sleep_reason)
        self.assertTrue(reasons and "超过" in reasons[0], reasons)
        self.assertTrue(w.active, "还在动：超时待机后应马上开始新的一次")

    def test_settle_period_ignores_changes(self):
        t, ch = run(self.w, self.scene, 1.5, 0.0, gain=lambda i: 3 * i)  # 刚开摄像头时亮度乱跳
        self.assertEqual(ch, [])

    def test_disabled_is_always_active(self):
        w = DoorWatcher(DoorConfig(enabled=False))
        w.reset(now=0.0)
        t, ch = run(w, self.scene, 10, 0.0)
        self.assertTrue(w.active)
        self.assertEqual(ch, [])

    def test_parse_roi(self):
        self.assertIsNone(parse_roi(""))
        self.assertIsNone(parse_roi("full"))
        self.assertIsNone(parse_roi("a,b"))
        self.assertEqual(parse_roi("0.6,0,0.2,1"), (0.2, 0.0, 0.6, 1.0))


if __name__ == "__main__":
    unittest.main()
