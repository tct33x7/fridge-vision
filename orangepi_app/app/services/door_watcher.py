"""开门检测与待机：只用摄像头画面判断"现在有没有人在动冰箱"。

没有门磁，所以把"开门"定义成"门口这块画面动起来了"。两种状态：

  待机（standby） 不跑 YOLO。每秒只分析约 5 帧缩小到 160 像素宽的灰度图，和"背景"（门关着、没人时的样子）比较。
  工作（active）  跑 YOLO + 过线计数。每帧和上一帧比较，看画面还在不在动。

待机 → 工作（唤醒），满足任一条、并且连续 wake_hits 次检查都满足：
  1. 画面变化：和背景相比，变了的像素占比 > wake_ratio（手、门、物品进入画面）。
     比较前先扣掉整幅画面的平均亮度差，所以"整体变亮 / 变暗"（自动曝光、云遮太阳）不算变化。
  2. 亮度跳变：平均亮度比背景高或低了 > wake_brightness（冰箱灯亮了、柜门挡住了光）。
  连续多次才唤醒，是为了不被单帧噪点、闪烁触发。

工作 → 待机（休眠），满足任一条：
  1. 静止：连续 sleep_seconds 秒，前后两帧之间变了的像素占比都 < sleep_ratio。
     只看画面动不动，不看 YOLO 有没有检测到东西——台面上的瓶子会被一直检测到，不能因为它不睡。
  2. 超时：一次工作超过 max_active_seconds 秒（开着灯忘关、相机被碰歪、门一直开着），强制休眠。
  休眠时把"当前画面"设成新背景：开灯后、门没关严时，静止的新样子不会再反复唤醒。

背景怎么来、怎么跟：
  - 刚开摄像头的 settle_seconds 秒里自动曝光还在调，只快速学背景，不判断。
  - 待机且画面没动时，背景每次检查都慢慢跟着当前画面走一点（bg_alpha），适应早晚光线的慢变化。
  - 有动静时背景不跟，免得把伸进来的手学进背景里。

误唤醒（比如人从门口走过、开关厨房灯）的代价只是跑 sleep_seconds 秒的 YOLO；只要没过线就不会多计数。
每次工作记一次"会话"（第几次、为什么醒、为什么睡、多久），没有计数事件的会话就是误唤醒，方便统计和调参。

没做的（第一版有意不做，原因写在 orangepi_app/ORANGEPI.md）：预录缓冲、门磁输入、按区域区分"门"和"人"。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError:  # 开发机上无 OpenCV 时保持可导入
    cv2 = None  # type: ignore[assignment]


@dataclass
class DoorConfig:
    enabled: bool = True              # 关掉 = 一直工作（和原来一样）
    check_hz: float = 5.0             # 待机时每秒分析几次
    analyze_width: int = 160          # 缩小到这个宽度再比较（省 CPU、抗噪点）
    pixel_diff: int = 25              # 单个像素灰度差超过它算"变了"（0–255）
    wake_ratio: float = 0.03          # 待机时：和背景比，变了的像素占比超过它算"有动静"
    wake_brightness: float = 18.0     # 待机时：平均亮度和背景差超过它算"有动静"
    wake_hits: int = 2                # 连续几次检查都有动静才唤醒
    sleep_ratio: float = 0.01         # 工作时：前后两帧变了的像素占比低于它算"静止"
    sleep_seconds: float = 6.0        # 连续静止这么久就待机
    max_active_seconds: float = 300.0 # 一次工作最长时间
    settle_seconds: float = 2.0       # 摄像头刚打开时等自动曝光稳定
    bg_alpha: float = 0.05            # 待机且静止时，背景跟随当前画面的速度
    roi: tuple[float, float, float, float] | None = None  # 只看这块（归一化 x0,y0,x1,y1）；None = 整幅画面


def parse_roi(text: str | None) -> tuple[float, float, float, float] | None:
    """"x0,y0,x1,y1"（0–1）→ 元组；空、"full"、格式不对 → None（整幅画面）。"""
    if not text or text.strip().lower() in {"full", "none", "all"}:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError:
        return None
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        return None
    return (x0, y0, x1, y1)


class DoorWatcher:
    STANDBY = "standby"
    ACTIVE = "active"

    def __init__(self, cfg: DoorConfig | None = None) -> None:
        self.cfg = cfg or DoorConfig()
        self.reset(now=0.0)

    # ---------------- 状态 ----------------

    def reset(self, now: float) -> None:
        """摄像头（重新）打开时调用：清掉背景，重新等曝光稳定。"""
        self.state = self.STANDBY if self.cfg.enabled else self.ACTIVE
        self.opened_at = now
        self.bg: np.ndarray | None = None      # float32 背景
        self.prev: np.ndarray | None = None    # 工作时的上一帧
        self.last_check = -1e9
        self.hits = 0
        self.active_since = now
        self.standby_since = now
        self.last_motion = now
        self.wake_reason = ""
        self.sleep_reason = ""
        self.motion = 0.0                      # 最近一次的变化比例（给网页和日志看）
        self.brightness_delta = 0.0

    @property
    def active(self) -> bool:
        return self.state == self.ACTIVE

    # ---------------- 主入口 ----------------

    def observe(self, frame_bgr: np.ndarray, now: float) -> str | None:
        """每读到一帧调用一次。返回 "wake" / "sleep" 表示这一帧发生了状态切换，否则 None。"""
        cfg = self.cfg
        if not cfg.enabled:
            return None
        if self.state == self.STANDBY and now - self.last_check < 1.0 / cfg.check_hz:
            return None                                   # 待机时不用每帧都算
        self.last_check = now
        small = self._prepare(frame_bgr)

        if self.bg is None or now - self.opened_at < cfg.settle_seconds:
            self.bg = small.astype(np.float32) if self.bg is None else self.bg * 0.5 + small * 0.5
            self.prev = small
            return None

        if self.state == self.STANDBY:
            ratio, bdelta = self._compare(small, self.bg)
            self.motion, self.brightness_delta = ratio, bdelta
            moving = ratio > cfg.wake_ratio or abs(bdelta) > cfg.wake_brightness
            if moving:
                self.hits += 1
            else:
                self.hits = 0
                cv2.accumulateWeighted(small.astype(np.float32), self.bg, cfg.bg_alpha)
            if self.hits >= cfg.wake_hits:
                self.state = self.ACTIVE
                self.active_since = self.last_motion = now
                self.wake_reason = (f"画面变化 {ratio:.0%}" if ratio > cfg.wake_ratio
                                    else f"亮度变化 {bdelta:+.0f}")
                self.sleep_reason = ""
                self.hits = 0
                self.prev = small
                return "wake"
            return None

        # 工作中：和上一帧比，看还在不在动
        ratio, _ = self._compare(small, self.prev.astype(np.float32))
        self.motion = ratio
        self.prev = small
        if ratio > cfg.sleep_ratio:
            self.last_motion = now
        reason = ""
        if now - self.last_motion >= cfg.sleep_seconds:
            reason = f"静止 {cfg.sleep_seconds:g} 秒"
        elif now - self.active_since >= cfg.max_active_seconds:
            reason = f"超过 {cfg.max_active_seconds:g} 秒"
        if reason:
            self.state = self.STANDBY
            self.sleep_reason = reason
            self.standby_since = now
            self.bg = small.astype(np.float32)            # 静止的新样子就是新背景
            self.hits = 0
            return "sleep"
        return None

    # ---------------- 计算 ----------------

    def _prepare(self, frame_bgr: np.ndarray) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        x0, y0, x1, y1 = self.cfg.roi or (0.0, 0.0, 1.0, 1.0)
        crop = frame_bgr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        ch, cw = gray.shape[:2]
        aw = max(16, min(self.cfg.analyze_width, cw))
        small = cv2.resize(gray, (aw, max(8, int(ch * aw / cw))), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(small, (5, 5), 0)

    def _compare(self, small: np.ndarray, ref: np.ndarray) -> tuple[float, float]:
        """返回 (扣掉整体亮度差后变了的像素占比, 平均亮度差)。"""
        cur = small.astype(np.float32)
        bdelta = float(cur.mean() - ref.mean())
        diff = np.abs(cur - ref - bdelta)
        return float((diff > self.cfg.pixel_diff).mean()), bdelta

    def snapshot(self, now: float) -> dict:
        return {
            "door_state": self.state,
            "motion": round(self.motion, 3),
            "brightness_delta": round(self.brightness_delta, 1),
            "wake_reason": self.wake_reason,
            "sleep_reason": self.sleep_reason,
            "state_seconds": round(now - (self.active_since if self.active else self.standby_since), 1),
        }
