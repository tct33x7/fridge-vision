#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录一段测试视频（给 replay.py 重放用）。要在 macOS 自带的"终端"里运行（需要相机权限）。

  python tools/record.py test_videos/jitter1.mp4            # 外接相机，编号 0
  python tools/record.py test_videos/light1.mp4 --source 1  # 换相机

窗口里：空格 = 开始/暂停录制，q = 结束并保存。画面中间的竖线只是参考（实际计数线重放时再定）。
录像只存在本机 test_videos/ 里，已在 .gitignore 中，不会进 git。
"""
import argparse
import os
import time

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--source", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
    cap.set(cv2.CAP_PROP_FPS, a.fps)
    if not cap.isOpened():
        raise SystemExit(f"打不开相机 {a.source}：检查是否在系统'终端'里运行、相机权限、或换 --source 1")
    W, H = int(cap.get(3)), int(cap.get(4))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (W, H))
    rec, n, t0 = False, 0, time.time()
    print(f"相机 {a.source}：{W}x{H}。空格开始/暂停，q 结束。")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if rec:
            vw.write(frame)
            n += 1
        show = frame.copy()
        cv2.line(show, (W // 2, 0), (W // 2, H), (0, 140, 255), 2)
        txt = f"REC {n / a.fps:5.1f}s" if rec else "PAUSED (space = record)"
        cv2.putText(show, txt, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255) if rec else (0, 255, 255), 2)
        cv2.imshow("record (space / q)", show)
        k = cv2.waitKey(1) & 0xFF
        if k == ord(" "):
            rec = not rec
        elif k == ord("q"):
            break
    vw.release()
    cap.release()
    cv2.destroyAllWindows()
    print(f"已保存 {a.out}：{n} 帧，约 {n / a.fps:.1f} 秒（实际用时 {time.time() - t0:.0f} 秒）")


if __name__ == "__main__":
    main()
