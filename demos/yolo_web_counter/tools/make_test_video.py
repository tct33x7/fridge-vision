#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成一段"合成测试视频" + 真值文件，用来在没有真实录像时重放对比计数逻辑。

物体图片取自 ultralytics 自带的两张示例图（bus.jpg 里的公交车、zidane.jpg 里的领带），
YOLO 能认出来，但会在相近类别之间跳、在暗光/模糊时漏检——正好拿来考验计数逻辑。
物品种类和冰箱无关，只考"过线计数"这一步；真实效果以自己录的视频为准。

用法：
  python tools/make_test_video.py test_videos/synthetic.mp4 [--seed 1]
会同时写出 test_videos/synthetic.truth.json
"""
import argparse
import json
import os

import cv2
import numpy as np
import ultralytics

W, H, FPS = 1280, 720, 30
LINE = [0.5, 0.0, 0.5, 1.0]        # 竖线，A 在上 B 在下 → 左侧(画面左边)为 +1 "进入"
LX = int(W * 0.5)
CY = H // 2


def load_objects():
    d = os.path.join(os.path.dirname(ultralytics.__file__), "assets")
    bus = cv2.imread(os.path.join(d, "bus.jpg"))[200:760, 0:810]
    bus = cv2.resize(bus, (300, 207))
    tie = cv2.imread(os.path.join(d, "zidane.jpg"))[400:720, 400:560]
    tie = cv2.resize(tie, (120, 240))
    return {"bus": bus, "tie": tie}


def background(rng):
    yy, xx = np.mgrid[0:H, 0:W]
    base = (90 + 40 * xx / W + 20 * yy / H).astype(np.float32)
    bg = np.stack([base * 0.95, base, base * 1.05], -1)
    bg += rng.normal(0, 6, (H, W, 1)).astype(np.float32)
    bg = cv2.GaussianBlur(bg, (0, 0), 3)
    # 画几块"门框/搁板"一样的条纹，让画面不至于太空
    for x in (120, 1120):
        cv2.rectangle(bg, (x, 0), (x + 30, H), (70, 70, 75), -1)
    cv2.rectangle(bg, (0, 640), (W, 660), (150, 150, 140), -1)
    return bg


def paste(frame, patch, cx, cy, scale=1.0):
    ph, pw = patch.shape[:2]
    if scale != 1.0:
        patch = cv2.resize(patch, (max(4, int(pw * scale)), max(4, int(ph * scale))))
        ph, pw = patch.shape[:2]
    x1, y1 = int(cx - pw / 2), int(cy - ph / 2)
    x2, y2 = x1 + pw, y1 + ph
    sx1, sy1 = max(0, -x1), max(0, -y1)
    x1c, y1c, x2c, y2c = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    if x2c <= x1c or y2c <= y1c:
        return
    frame[y1c:y2c, x1c:x2c] = patch[sy1:sy1 + (y2c - y1c), sx1:sx1 + (x2c - x1c)]


def lerp(a, b, n):
    return [a + (b - a) * i / max(1, n - 1) for i in range(n)]


def build_script(rng):
    """
    返回 (段落列表)。每段: name, obj, truth(+1/-1/0), frames=[(x, y, scale, brightness, visible, blur)]
    x 是物体中心横坐标；线在 LX。"进入" = 从右往左过线。
    """
    R, Lf = LX + 330, LX - 330       # 线右侧、左侧的起止点
    segs = []

    def seg(name, obj, truth, xs, bright=None, vis=None, blur=None, shake=4.0):
        n = len(xs)
        bright = bright or [1.0] * n
        vis = vis or [True] * n
        blur = blur or [0] * n
        frames = []
        for i in range(n):
            frames.append((xs[i] + rng.normal(0, shake), CY + rng.normal(0, shake),
                           1.0 + rng.normal(0, 0.03), bright[i], vis[i], blur[i]))
        segs.append({"name": name, "obj": obj, "truth": truth, "frames": frames})

    for rnd in range(2):
        o1, o2 = ("bus", "tie") if rnd == 0 else ("tie", "bus")
        # 1 正常进入、正常拿出
        seg("正常进入", o1, +1, lerp(R, Lf, 45))
        seg("正常拿出", o2, -1, lerp(Lf, R, 45))
        # 2 在线附近犹豫晃动 2 秒，最后放进去
        n = 60
        wob = [LX + 25 * np.sin(i / 3.0) + rng.normal(0, 6) for i in range(n)]
        seg("线上晃动后进入", o1, +1, lerp(R, LX + 20, 20) + wob + lerp(LX - 20, Lf, 20))
        # 3 伸过线一点又缩回（没放进去）
        seg("伸过线又缩回", o2, 0, lerp(R, LX - 22, 25) + [LX - 22] * 10 + lerp(LX - 22, R, 25))
        # 4 快速穿过（每帧移动 ~70 像素，带运动模糊）
        seg("快速穿过", o1, +1, lerp(R + 100, Lf - 100, 12), blur=[11] * 12, shake=1.0)
        # 5 过线时光线一明一暗（自动曝光来回调）
        n = 50
        br = [(0.35 if (i // 4) % 2 else 1.35) for i in range(n)]
        seg("过线时光线闪烁", o2, +1, lerp(R, Lf, n), bright=br)
        # 6 过线时被手挡住 12 帧，停顿后再出现（同一个物品）
        xs = lerp(Lf, LX - 60, 20) + [LX - 60 + 10 * i for i in range(12)] + [LX + 70] * 8 + lerp(LX + 70, R, 20)
        vis = [True] * 20 + [False] * 12 + [True] * 28
        seg("过线时被挡住", o1, -1, xs, vis=vis)
        # 7 整体很暗（晚上厨房只开一盏小灯）
        seg("暗光下进入", o2, +1, lerp(R, Lf, 45), bright=[0.2] * 45)
        # 8 离线较远处来回晃（不该计数）
        seg("远离线晃动", o1, 0, [Lf - 60 + 40 * np.sin(i / 4.0) for i in range(45)])
    return segs


def main():
    ap = argparse.ArgumentParser(description="生成合成测试视频和真值")
    ap.add_argument("out", help="输出 .mp4 路径，例如 test_videos/synthetic.mp4")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    objs = load_objects()
    bg = background(rng)
    segs = build_script(rng)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    fno = 0
    truth_segs = []
    gap = 20
    for s in segs:
        start = fno + 1
        for (x, y, sc, br, vis, blur) in s["frames"]:
            f = bg.copy()
            if vis:
                fr = f.astype(np.uint8)
                paste(fr, objs[s["obj"]], x, y, sc)
                f = fr.astype(np.float32)
                if blur:
                    k = np.zeros((1, blur), np.float32)
                    k[0, :] = 1.0 / blur
                    f = cv2.filter2D(f, -1, k)
            # 不可见的帧：物体被手挡住 / 检测器没认出来，画面上就没有它
            f = f * br + rng.normal(0, 4, f.shape)
            vw.write(np.clip(f, 0, 255).astype(np.uint8))
            fno += 1
        end = fno
        for _ in range(gap):                      # 段与段之间空几帧
            f = bg + rng.normal(0, 4, bg.shape)
            vw.write(np.clip(f, 0, 255).astype(np.uint8))
            fno += 1
        truth_segs.append({"name": s["name"], "cls": s["obj"], "start": start, "end": end,
                           "delta": s["truth"]})
    vw.release()

    expected = {}
    for t in truth_segs:
        if t["delta"]:
            k = "in" if t["delta"] > 0 else "out"
            expected.setdefault(t["cls"], {"in": 0, "out": 0})[k] += 1
    truth = {"video": os.path.basename(a.out), "line": LINE, "fps": FPS, "frames": fno,
             "expected": expected, "segments": truth_segs,
             "note": "合成视频：物体来自 ultralytics 示例图；+1=从右往左过线(进入)"}
    tpath = os.path.splitext(a.out)[0] + ".truth.json"
    with open(tpath, "w", encoding="utf-8") as fp:
        json.dump(truth, fp, ensure_ascii=False, indent=1)
    print(f"已写出 {a.out}（{fno} 帧，{fno / FPS:.1f} 秒）和 {tpath}")
    print("真值：", expected)


if __name__ == "__main__":
    main()
