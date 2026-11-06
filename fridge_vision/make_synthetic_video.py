"""生成一段合成视频验证 door_demo.py：黑屏（关门）→ 变亮（开门）→ 香蕉从下往上穿过中线（放入）
→ 停一会 → 从上往下穿回（拿出）→ 变暗（关门）。

    python make_synthetic_video.py out.mp4 [--sprite path.jpg]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_SPRITE = HERE / "samples" / "test_food.jpg"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sprite", default=str(DEFAULT_SPRITE))
    ap.add_argument("--size", default="640x480")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.split("x"))

    sprite = cv2.imread(args.sprite)
    if sprite is None:
        raise SystemExit(f"读不到 {args.sprite}")
    sh = 220
    sw = int(sprite.shape[1] * sh / sprite.shape[0])
    sprite = cv2.resize(sprite, (sw, sh))

    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), 15, (w, h))

    def blank(level: int) -> np.ndarray:
        return np.full((h, w, 3), level, dtype=np.uint8)

    def paste(bg: np.ndarray, cx: int, cy: int) -> np.ndarray:
        frame = bg.copy()
        x1, y1 = cx - sw // 2, cy - sh // 2
        x2, y2 = x1 + sw, y1 + sh
        sx1, sy1 = max(0, -x1), max(0, -y1)
        sx2, sy2 = sw - max(0, x2 - w), sh - max(0, y2 - h)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 > x1 and y2 > y1:
            frame[y1:y2, x1:x2] = sprite[sy1:sy2, sx1:sx2]
        return frame

    for _ in range(20):            # 关门：暗
        writer.write(blank(40))
    for _ in range(10):            # 开门：亮，空画面
        writer.write(blank(200))
    for cy in range(h + sh // 2, -sh // 2, -12):   # 放入：自下而上
        writer.write(paste(blank(200), w // 2, cy))
    for _ in range(10):
        writer.write(blank(200))
    for cy in range(-sh // 2, h + sh // 2, 12):    # 拿出：自上而下
        writer.write(paste(blank(200), w // 2, cy))
    for _ in range(10):
        writer.write(blank(200))
    for _ in range(20):            # 关门：暗
        writer.write(blank(40))
    writer.release()
    print("写入", args.out)


if __name__ == "__main__":
    main()
