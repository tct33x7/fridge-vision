#!/usr/bin/env python3
"""列出本机能打开的摄像头编号，用来找 2.4G 接收器 / USB 摄像头对应的 --source 值。

    python list_cameras.py          # 探测 0–5
    python list_cameras.py 10       # 探测 0–9
"""
from __future__ import annotations

import platform
import subprocess
import sys

import cv2


def system_names() -> None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["system_profiler", "SPCameraDataType"], capture_output=True, text=True, timeout=20).stdout
            names = [line.strip().rstrip(":") for line in out.splitlines() if line.endswith(":") and "Camera:" not in line]
            print("macOS 识别到的摄像头：", "、".join(names) or "无")
        elif platform.system() == "Linux":
            out = subprocess.run(["v4l2-ctl", "--list-devices"], capture_output=True, text=True, timeout=20).stdout
            print(out or "v4l2-ctl 没有输出（可能未安装 v4l-utils）")
    except Exception as exc:  # 只是辅助信息
        print("读取系统摄像头列表失败：", exc)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    system_names()
    print(f"逐个探测编号 0–{limit - 1}（每个最多等 3 秒）…")
    found = []
    for idx in range(limit):
        cap = cv2.VideoCapture(idx)
        ok = cap.isOpened()
        if ok:
            ret, frame = cap.read()
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  --source {idx}: 可用  {w}x{h} @ {fps:.0f} fps  首帧{'正常' if ret and frame is not None else '读取失败'}")
            found.append(idx)
        cap.release()
    if not found:
        print("没有能打开的摄像头。macOS 请在 系统设置 → 隐私与安全性 → 摄像头 里给终端或 Claude 授权。")
    else:
        print(f"建议：内置摄像头通常是 0，外接接收器/USB 摄像头通常是 {found[-1]}。")


if __name__ == "__main__":
    main()
