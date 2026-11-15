#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录一段测试视频（给 replay.py 和评测工具用）。要在 macOS 自带的"终端"里运行（需要相机权限）。

  python tools/record.py test_videos/jitter1.mp4            # 外接相机，编号 0
  python tools/record.py test_videos/light1.mp4 --source 1  # 换相机

窗口里：空格 = 开始/暂停录制，q = 结束并保存（在终端按 Ctrl+C 也会保存）。
画面中间的竖线只是参考（实际计数线重放时再定）。录像只存在本机，已在 .gitignore 中，不会进 git。

为什么旁边多了一个 <录像名>.frames.json：
  相机实际给的帧率不一定等于要求的（E01 里这台相机在 Mac 上只有约 15 帧/秒），冰箱灯一亮还可能变。
  mp4 文件头只能写一个固定帧率，按它换算时间会错。所以每一帧被读到的时刻都记在 .frames.json 的 "t" 里
  （秒，从第一帧算起；暂停的那段体现为一个大于 1 秒的间隔），评测工具按它算时间。
  文件头的帧率用开始录之前预览时实测的帧率，只是个近似。

测试本工具（不用相机）：
  python tools/record.py /tmp/x.mp4 --source 某段录像.mp4 --autostart --no-window
"""
import argparse
import json
import os
import signal
import statistics
import time
from collections import deque
from datetime import datetime

import cv2


def sidecar_path(video_path):
    return os.path.splitext(video_path)[0] + ".frames.json"


def parse_source(s):
    return int(s) if s.isdigit() else s


def measured_fps(ts):
    """一串时刻（秒）→ 帧率：用相邻间隔的中位数，不受偶尔卡一下或暂停影响。"""
    ts = list(ts)
    if len(ts) < 10:
        return None
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    return 1.0 / statistics.median(gaps) if gaps else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--source", default="0", help="相机编号（0、1…）；也可以是一段录像的路径（只用来测试本工具）")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30, help="向相机要求的帧率；相机给不了时以实测为准")
    ap.add_argument("--autostart", action="store_true", help="测试用：一开始就录，不用按空格")
    ap.add_argument("--no-window", action="store_true", help="测试用：不开预览窗口")
    a = ap.parse_args()

    source = parse_source(a.source)
    from_file = isinstance(source, str) and os.path.isfile(source)
    cap = cv2.VideoCapture(source)
    if not from_file:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
        cap.set(cv2.CAP_PROP_FPS, a.fps)
    if not cap.isOpened():
        raise SystemExit(f"打不开相机 {a.source}：检查是否在系统'终端'里运行、相机权限、或换 --source 1")
    W, H = int(cap.get(3)), int(cap.get(4))
    file_fps = (cap.get(cv2.CAP_PROP_FPS) or 30.0) if from_file else None
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    print(f"相机 {a.source}：{W}x{H}，要求 {a.fps} 帧/秒（相机自己报的：{cap.get(cv2.CAP_PROP_FPS):g}）。"
          f"空格开始/暂停，q 结束。")

    vw = None               # 录到第 15 帧时才建：用实测帧率写文件头、用实际画面尺寸
    header_fps = None
    size = None             # 录像的 (宽, 高)：按第一张录下的画面定
    resized = 0             # 画面尺寸中途变了、被缩放成录像尺寸的帧数
    pending = []            # 文件建好之前先存在内存里的帧
    rec = False
    n = 0                   # 已录的帧数（含还在内存里的）
    t_written = []          # 每个录下的帧被读到的时刻（秒，相对第一帧）
    toggles = []            # [已录帧数, 时刻, "rec"/"pause"]
    t_first = None
    preview_ts = deque(maxlen=60)   # 预览时最近的读帧时刻，用来估计帧率
    idx = 0                 # 读到第几帧
    t_start = time.monotonic()
    stop_reason = "按了 q"

    def open_writer():
        nonlocal vw, header_fps
        header_fps = file_fps or measured_fps(t_written) or measured_fps(preview_ts) or float(a.fps)
        header_fps = max(1.0, round(header_fps, 2))
        vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), header_fps, size)
        if not vw.isOpened():
            raise SystemExit(f"建不了录像文件 {a.out}")
        for f in pending:
            vw.write(f)
        pending.clear()

    def put(frame):
        nonlocal size, resized
        h, w = frame.shape[:2]
        if size is None:
            size = (w, h)
            if size != (W, H):
                print(f"！相机报的是 {W}x{H}，实际画面是 {w}x{h}，按实际的录")
        elif (w, h) != size:
            frame = cv2.resize(frame, size)
            resized += 1
        if vw is None:
            pending.append(frame)
            if len(pending) >= 15:
                open_writer()
        else:
            vw.write(frame)

    def toggle(t):
        nonlocal rec
        rec = not rec
        toggles.append([n, round(t - t_first, 4) if t_first is not None else 0.0, "rec" if rec else "pause"])

    # Ctrl+C 只做个记号，等当前这一帧写完、记好时间再停，这样录像和时间戳的帧数一定对得上。
    # 连按两次才立刻中断，但也要等正在写的那一帧写完；录像和时间戳照样会存好。
    stop = {"n": 0, "busy": False, "late": False}

    def on_sigint(signum, frame_):
        stop["n"] += 1
        if stop["n"] >= 2:
            if stop["busy"]:
                stop["late"] = True
            else:
                raise KeyboardInterrupt

    signal.signal(signal.SIGINT, on_sigint)
    error = None

    try:
        while True:
            if stop["n"]:
                stop_reason = "按了 Ctrl+C"
                break
            ok, frame = cap.read()
            if not ok:
                stop_reason = "读不到画面了（录像放完 / 相机断开）"
                break
            idx += 1
            # 相机用真实时钟；读录像文件时按文件帧率（测试时读文件比实时快得多）
            t = (idx - 1) / file_fps if from_file else time.monotonic()
            if a.autostart and not toggles:
                toggle(t)
            if rec:
                stop["busy"] = True
                if t_first is None:
                    t_first = t
                put(frame)
                n += 1
                t_written.append(round(t - t_first, 4))
                stop["busy"] = False
                if stop["late"]:
                    raise KeyboardInterrupt
            else:
                preview_ts.append(t)
            if a.no_window:
                continue
            show = frame.copy()
            cv2.line(show, (W // 2, 0), (W // 2, H), (0, 140, 255), 2)
            txt = f"REC {t_written[-1]:5.1f}s  {n} frames" if rec else "PAUSED (space = record)"
            cv2.putText(show, txt, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 0, 255) if rec else (0, 255, 255), 2)
            cv2.imshow("record (space / q)", show)
            k = cv2.waitKey(1) & 0xFF
            if k == ord(" "):
                toggle(t)
            elif k == ord("q"):
                break
    except KeyboardInterrupt:
        stop_reason = "按了 Ctrl+C"
    except Exception as exc:          # 其他错误：先把录像和时间戳存好，最后再报出来
        error = exc
        stop_reason = f"出错了：{type(exc).__name__}: {exc}"
    finally:
        # 不管怎么退出（q、Ctrl+C、出错），都先把录像收尾存好；收尾时不再理会 Ctrl+C
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if n and vw is None:
                open_writer()
        finally:
            if vw is not None:
                vw.release()
            cap.release()
            if not a.no_window:
                cv2.destroyAllWindows()

    if vw is None or n == 0:
        print(f"没有录到任何画面（{stop_reason}；是不是没按空格开始录？），没有保存。")
        if error:
            raise error
        return

    # 旁边的时间戳文件：写失败也不影响录像本身
    gaps = [b - x for x, b in zip(t_written, t_written[1:])]
    paused = sum(g for g in gaps if g > 1.0)
    rec_time = max(1e-6, (t_written[-1] if t_written else 0.0) - paused)
    real_fps = measured_fps(t_written) or (n / rec_time)
    side = sidecar_path(a.out)
    try:
        with open(side, "w", encoding="utf-8") as f:
            json.dump({
                "video": os.path.basename(a.out),
                "source": str(a.source),
                "recorded_at": datetime.now().isoformat(timespec="seconds"),
                "size": list(size),
                "fps_requested": a.fps,
                "fps_header": header_fps,
                "fps_measured": round(real_fps, 2),
                "frames": n,
                "resized_frames": resized,
                "toggles": toggles,
                "t": t_written,
                "note": "t = 每个录下的帧被读到的时刻（秒，从第一帧算起）；暂停体现为一个大于 1 秒的间隔",
            }, f, ensure_ascii=False, separators=(",", ":"))
        side_msg = f"时间戳在 {os.path.basename(side)}"
    except OSError as exc:
        side_msg = f"！时间戳文件没写成（{exc}），录像本身不受影响"

    print(f"已保存 {a.out}：{n} 帧，录了约 {rec_time:.1f} 秒（不含暂停），"
          f"实测 {real_fps:.1f} 帧/秒，文件头写的是 {header_fps:g} 帧/秒；{side_msg}。"
          f"（{stop_reason}；从开始运行共 {time.monotonic() - t_start:.0f} 秒）")
    if abs(real_fps - header_fps) / header_fps > 0.15:
        print(f"！注意：实测帧率和文件头差了 {abs(real_fps - header_fps) / header_fps:.0%}。"
              f"按文件头播放时间会不准；评测工具按 {os.path.basename(side)} 里的时间算。")
    if resized:
        print(f"！有 {resized} 帧画面尺寸和开头不一样，已缩放成 {size[0]}x{size[1]}")
    if error:
        raise error


if __name__ == "__main__":
    main()
