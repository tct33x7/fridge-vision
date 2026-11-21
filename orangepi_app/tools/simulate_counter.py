"""用录像代替摄像头，跑一遍板子上的计数服务（同一份 counter_service 代码），看开门 / 待机时间线和计数结果。

不连摄像头、不写数据库，Mac 和板子上都能跑。例子（在仓库根目录）：

    fridge_vision/.venv/bin/python orangepi_app/tools/simulate_counter.py demos/yolo_web_counter/test_videos/jitter1.mp4 \\
        --model demos/yolo_web_counter/models/yolo11s.pt --imgsz 320

录像会被缩到 640 宽、按时间抽帧到 --fps（默认 15，和板子摄像头一样）。真值默认找 <录像名>.truth.json（第 2 步的格式）。

三种识别引擎（--engine）：
  cpu       ultralytics 模型 + ultralytics 自带的 ByteTrack（Mac 上默认）。和板子不同：板子用的是 NPU + ByteTrackLite。
  cpu-lite  ultralytics 模型只做检测（NMS 的 IoU 0.45、按类别，和板子 NPU 一样），追踪用板子上的 ByteTrackLite
            （app/services/bytetrack_lite.py）。检测器仍然和板子不同，但追踪和板子一样：改了 ByteTrackLite 以后，
            可以在 Mac 上先看前后差别。是"代理"，不是板子的数字。
  npu       板子上的 NPU YOLOv5s + ByteTrackLite，和板子实际运行的完全一样。只能在板子上跑；别处会直接报错退出。

时间（和 eval/timebase.py 同一套规则）：
  1. 有 <录像名>.frames.json（新版录制工具记的每帧真实时刻）就一定用它；这时 --video-fps 会被忽略并提示。
     它和录像的帧数差 1–2 帧：按较短的截掉、或按中位间隔在末尾补齐，并提示；差得更多直接报错退出。
  2. 没有 .frames.json 时用 --video-fps（例如秒表测的真实帧率）。
  3. 都没有就按文件头帧率，并提示（旧版录制工具文件头固定写 30，相机实际可能只有 15）。
抽帧按时间：每隔 1/帧率 秒处理一帧，所以帧率忽高忽低的录像也按真实时间抽。
录像本身比 --fps 慢时，就按录像的帧率模拟（计数规则里按帧写的参数也按这个帧率换算），并提示。

计数线：--line 给的，或者真值里的 "line"。都没有就报错退出；加 --default-line 才用板子的默认线。

--events-json 输出每个计数事件，格式和 eval/events_mac.py 一样，可以直接交给 eval/score_actions.py 逐动作打分：
  t       过线的时刻（录像里的秒，和 Mac 路线一样）
  t_emit  确认计数的时刻（规则要过线后待满确认时间才算，所以比 t 晚，最多约 3 秒）

退出码：0 正常；1 参数、录像、计数线、引擎初始化有问题；2 识别失败的帧超过一半（不写事件文件）。
（命令行选项写错时 argparse 自己也用退出码 2，但会先打印用法。）

在板子上跑：deploy/opi.sh 同步时不带 tools/，要手动把这个文件和录像拷过去，例如
    scp orangepi_app/tools/simulate_counter.py opi:smart_fridge_demo/tools/
    scp 录像.mp4 录像.frames.json opi:/tmp/
    ssh opi 'cd smart_fridge_demo && .venv/bin/python tools/simulate_counter.py /tmp/录像.mp4 --engine npu \\
             --line 0,0.5,1,0.5 --events-json /tmp/录像.board-npu.events.json'
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types
from collections import deque
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

MAX_MISMATCH = 2   # .frames.json 和录像的帧数最多差这么多帧（和 eval/timebase.py 一样）
PAUSE_GAP = 1.0    # 相邻两帧间隔超过 1 秒算暂停，不参与算帧率
RATE_WINDOW = 5.0  # 检查抽帧后帧率时，每段多少秒


def warn(msg: str) -> None:
    print(f"！{msg}", file=sys.stderr, flush=True)


def median_fps(ts, default: float = 30.0) -> float:
    gaps = [b - a for a, b in zip(ts, ts[1:]) if 0 < b - a < PAUSE_GAP]
    return 1.0 / statistics.median(gaps) if gaps else default


def count_frames(video: Path) -> int:
    """一帧一帧数录像里实际有多少帧（文件头记的帧数偶尔不准）。"""
    import cv2

    cap = cv2.VideoCapture(str(video))
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    return n


def load_times(video: Path, n_hdr: int, header_fps: float, override: float | None):
    """每帧的时刻（秒）、真实帧率（中位数）、来源、说明。规则和 eval/timebase.py 一样（见文件开头）。"""
    side = video.with_suffix(".frames.json")
    if side.exists():
        if override:
            warn(f"{video.name} 有 {side.name}，按它记的真实时间算，忽略 --video-fps {override:g}")
        t = [float(x) for x in json.loads(side.read_text(encoding="utf-8"))["t"]]
        n = n_hdr
        if len(t) != n:
            # 文件头的帧数偶尔不准：先实际数一遍再判断
            n = count_frames(video)
        note = ""
        if len(t) != n:
            if abs(len(t) - n) > MAX_MISMATCH or not t:
                raise SystemExit(f"{side.name} 记了 {len(t)} 帧，录像有 {n} 帧，对不上（差 {abs(len(t) - n)} 帧）："
                                 f"是不是拿错了文件？")
            step = 1.0 / median_fps(t, header_fps or 30.0)
            note = f"时间戳 {len(t)} 帧、录像 {n} 帧，差 {abs(len(t) - n)} 帧：按较短的截掉或在末尾补齐"
            t = t[:n] + [t[-1] + step * (k + 1) for k in range(max(0, n - len(t)))]
            warn(f"{video.name}：{note}")
        return t, median_fps(t, header_fps or 30.0), "sidecar", note
    n = n_hdr if n_hdr > 0 else count_frames(video)
    if override:
        return ([i / override for i in range(n)], float(override), "fps_override",
                f"没有 {side.name}，按命令行给的 {override:g} 帧/秒")
    fps = header_fps or 30.0
    note = f"没有 {side.name}，按文件头 {fps:g} 帧/秒算时间（旧版录制工具固定写 30，可能不准）"
    warn(f"{video.name}：{note}")
    return [i / fps for i in range(n)], fps, "header", note


def pick_frames(times, fps: float) -> list[int]:
    """按时间抽帧：返回要处理的帧号（从 0 数），让处理的帧大约每 1/fps 秒一帧。

    按一个固定的时间表走：到了下一个时刻（允许早到半个录像帧间隔，抵消时间戳的抖动）就处理这一帧，
    时间表往后挪 1/fps。落后超过一个间隔（录像暂停、掉帧）时从这一帧重新排，不连着补出一串帧。
    30 帧/秒的录像抽到 15 时正好是隔一帧取一帧（和以前按帧号跳一样）。
    """
    if not times:
        return []
    period = 1.0 / fps
    gaps = [b - a for a, b in zip(times, times[1:]) if 0 < b - a < PAUSE_GAP]
    tol = min(0.5 * statistics.median(gaps), 0.5 * period) if gaps else 0.5 * period
    keep, next_t = [], times[0]
    for i, t in enumerate(times):
        if t < next_t - tol:
            continue
        keep.append(i)
        next_t += period
        if next_t < t:
            next_t = t + period
    return keep


def rate_stats(ts, win: float = RATE_WINDOW):
    """处理过的帧的时刻 → (平均帧率, 按 win 秒分段的最低帧率, 最高帧率)；录像太短时分段的是 None。"""
    if len(ts) < 2 or ts[-1] <= ts[0]:
        return 0.0, None, None
    mean = (len(ts) - 1) / (ts[-1] - ts[0])
    rates, t0 = [], ts[0]
    while t0 + win <= ts[-1]:
        rates.append((bisect.bisect_left(ts, t0 + win) - bisect.bisect_left(ts, t0)) / win)
        t0 += win
    return mean, (min(rates) if rates else None), (max(rates) if rates else None)


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "-C", str(APP_DIR), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(APP_DIR), "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (rev or "?（不在 git 里，例如在板子上）") + ("+未提交改动" if dirty else "")
    except Exception:
        return "?"


def make_lite_detector(svc, model_path: str):
    """cpu-lite：ultralytics 只做检测，追踪交给板子的 ByteTrackLite，参数和板子 NPU 路径一样。"""
    from app.services.bytetrack_lite import ByteTrackLite
    from ultralytics import YOLO

    model = YOLO(model_path)
    tracker = ByteTrackLite()
    svc.engine_name = f"CPU {Path(model_path).name} + ByteTrackLite（代理）"

    def detect_lite(frame):
        low = max(0.10, svc.conf * 0.45)          # 和 NPU 路径一样：低分检测交给二级关联
        tracker.high_conf = svc.conf
        # NMS 和 NPU 路径一样：IoU 0.45、按类别（ultralytics 默认 agnostic_nms=False 就是按类别）
        r = model.predict(frame, conf=low, iou=0.45, imgsz=svc.imgsz, device="cpu", verbose=False)[0]
        dets = []
        if r.boxes is not None:
            for (x1, y1, x2, y2), cf, cid in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(),
                                                 r.boxes.cls.int().cpu().numpy()):
                dets.append((float(x1), float(y1), float(x2), float(y2), float(cf), int(cid)))
        return [(tid, model.names[int(cid)], x1, y1, x2, y2, conf)
                for tid, cid, x1, y1, x2, y2, conf in tracker.update(dets)]

    return detect_lite


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", default=str(APP_DIR / "models" / "yolo11s.pt"))
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--preset", default="default")
    ap.add_argument("--engine", default="cpu", choices=["cpu", "cpu-lite", "npu"])
    ap.add_argument("--fps", type=float, default=15.0, help="模拟的摄像头帧率（录像按时间抽帧到它）")
    ap.add_argument("--video-fps", type=float,
                    help="录像的真实帧率（比如秒表测的）；只在没有 .frames.json 时用，有的话忽略")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--truth", help="真值 json；默认 <录像名>.truth.json")
    ap.add_argument("--line", help="计数线 ax,ay,bx,by；默认用真值里的")
    ap.add_argument("--default-line", action="store_true",
                    help="没有 --line、真值里也没有 line 时，用板子的默认线（不加就报错退出）")
    ap.add_argument("--no-standby", action="store_true", help="关掉待机（一直识别），用来对比")
    ap.add_argument("--events-json", help="把计数事件（带录像里的时间）写成事件文件，给 eval/score_actions.py 打分")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.fps <= 0 or (args.video_fps is not None and args.video_fps <= 0):
        print("--fps、--video-fps 要大于 0", file=sys.stderr)
        return 1

    # ---- 录像和时间（不用 app.*，先做：模拟的帧率要在导入 app.* 之前定下来） ----
    import cv2

    video = Path(args.video).expanduser()   # 不 resolve：.frames.json、.truth.json 按录像（或它的链接）所在的文件夹找
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"打不开录像：{video}", file=sys.stderr)
        return 1
    header_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_hdr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    times, vfps, time_source, time_note = load_times(video, n_hdr, header_fps, args.video_fps)
    if not times:
        print(f"录像里没有帧：{video}", file=sys.stderr)
        return 1

    # 模拟的帧率：不能比录像本身快
    sim_fps = min(args.fps, vfps)
    if vfps < args.fps * 0.97:
        warn(f"录像只有 {vfps:.1f} 帧/秒，比 --fps {args.fps:g} 慢：按 {vfps:.1f} 帧/秒模拟（每帧都识别），"
             f"计数规则里按帧写的参数也按这个帧率换算。和板子摄像头 {args.fps:g} 帧/秒时的结果可能不一样")
    cfg_fps = max(1, round(sim_fps))      # app/config.py 用 int() 读，只能给整数
    picks = pick_frames(times, sim_fps)
    keep = [False] * len(times)
    for i in picks:
        keep[i] = True

    # ---- 真值和计数线 ----
    truth_path = Path(args.truth) if args.truth else video.with_suffix(".truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else None
    if args.line:
        try:
            line = [float(v) for v in args.line.split(",")]
        except ValueError:
            line = []
        if len(line) != 4:
            print(f"--line 要写成 ax,ay,bx,by 四个数（0–1），现在是：{args.line}", file=sys.stderr)
            return 1
        line_source = "--line"
    elif (truth or {}).get("line"):
        line = [float(v) for v in truth["line"]]
        line_source = f"真值 {truth_path.name}"
    elif args.default_line:
        line = None      # 导入 app.* 以后填板子的默认线
        line_source = "--default-line（板子的默认线）"
    else:
        print(f"没有计数线：没给 --line，真值 {truth_path.name} {'里没有 line' if truth else '不存在'}。\n"
              f"请加 --line ax,ay,bx,by（0–1，例如竖线 0.5,0,0.5,1）；确实想用板子的默认线就加 --default-line。",
              file=sys.stderr)
        return 1

    # 必须在导入 app.* 之前设好：不碰真实数据目录；帧率、模型、规则和板子一致
    os.environ["SMART_FRIDGE_STORAGE_DIR"] = tempfile.mkdtemp(prefix="sim_storage_")
    os.environ["SMART_FRIDGE_CAMERA_FPS"] = str(cfg_fps)
    os.environ["SMART_FRIDGE_COUNTER_MODEL"] = str(Path(args.model).expanduser())
    os.environ["SMART_FRIDGE_COUNTER_IMGSZ"] = str(args.imgsz)
    os.environ["SMART_FRIDGE_COUNTER_PRESET"] = args.preset
    os.environ["SMART_FRIDGE_DOOR_STANDBY"] = "false" if args.no_standby else "true"
    os.environ["SMART_FRIDGE_COUNTER_ENGINE"] = "npu" if args.engine == "npu" else "cpu"
    try:
        import dotenv  # noqa: F401
    except ImportError:  # 开发机上没装 python-dotenv 时，用一个空的替身（模拟时不读 .env）
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: False)
    sys.path.insert(0, str(APP_DIR))
    # app/__init__.py 会导入整个网站（FastAPI 和所有路由）；模拟只要计数部分，先放一个空的包占位
    pkg = types.ModuleType("app")
    pkg.__path__ = [str(APP_DIR / "app")]
    sys.modules["app"] = pkg

    from app.services import counter_service as cs
    from app.services.counter_service import CounterService

    svc = CounterService(load_history=False, persist=False)
    # 板子程序在内存里只留最近 100 个事件、20 次开门（给网页看）；模拟要全部，换成不限长度的
    svc.events = deque()
    svc.sessions = deque()
    if line is None:
        # 临时数据目录里没有板子保存的线，所以这里是代码里写的默认线（不是板子上网页画过的线）
        line = [float(v) for v in cs.DEFAULT_LINE]
    svc.set_line(*line)
    print(f"计数线 {','.join(f'{v:g}' for v in line)}（{line_source}）", flush=True)
    if svc.fps != cfg_fps:
        warn(f"计数服务读到的摄像头帧率是 {svc.fps}，不是 {cfg_fps}（.env 里设了 SMART_FRIDGE_CAMERA_FPS？）")

    if args.engine == "cpu-lite":
        detect = make_lite_detector(svc, str(Path(args.model).expanduser()))
    else:
        detect = svc._init_engine()
    if detect is None:
        msg = svc.status_text
        if args.engine == "npu":
            msg += "（NPU 引擎只能在板子上用）"
        print(msg, file=sys.stderr)
        return 1

    # 记下每个事件出现时的录像时间（事后改类别会直接改这个字典，所以最后写出的类别是改正后的）
    captured: list[tuple[float, int, dict]] = []
    clock = {"now": 0.0}
    orig_apply = svc._apply_events

    def apply_and_capture(events, corrections):
        for e in events:
            captured.append((clock["now"], svc.session["n"] if svc.session else 0, e))
        orig_apply(events, corrections)

    svc._apply_events = apply_and_capture

    # 计数器事件里的 "frame" 是这次开门里第几帧（服务的 frame_no，每次开门从 1 数）；
    # 这里记下 (第几次开门, 第几帧) → (录像里的秒, 录像第几帧)，用来查过线的时刻
    frame_at: dict[tuple[int, int], tuple[float, int]] = {}

    def crossing(n: int, e: dict):
        return frame_at.get((n, e.get("frame")))

    active_frames = total_frames = err_frames = n_read = 0
    last_err = ""
    t_active = 0.0
    proc_times: list[float] = []
    log = []
    prev_state = None
    now = 0.0
    for i in range(len(times)):
        if not keep[i]:
            if not cap.grab():
                break
            n_read += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        n_read += 1
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (args.width, round(h * args.width / w)))
        now = times[i]
        clock["now"] = now
        proc_times.append(now)
        # 识别失败时服务只是把 svc.error 设上、返回画面（不抛异常），成功的帧也不会把它清掉，
        # 所以每帧先清掉，处理完再看这一帧有没有出错
        svc.error = None
        t0 = time.perf_counter()
        n_before = len(captured)
        svc.process_frame(detect, frame, now)
        total_frames += 1
        if svc.door.active:
            active_frames += 1
            t_active += time.perf_counter() - t0
            if svc.error:
                err_frames += 1
                last_err = svc.error
            elif svc.session is not None and svc.frame_no > 0:
                frame_at.setdefault((svc.session["n"], svc.frame_no), (now, i + 1))
        if svc.door.state != prev_state:
            log.append((now, "唤醒" if svc.door.active else "待机",
                        svc.door.wake_reason if svc.door.active else svc.door.sleep_reason))
            prev_state = svc.door.state
        for _, n, e in captured[n_before:]:
            c = crossing(n, e)
            log.append((now, "计数", f"{e['cls']} {'放入' if e['delta'] > 0 else '拿出'}"
                                     + (f"（过线 {c[0]:.1f}s）" if c else "")))
    cap.release()
    if n_read < len(times):
        warn(f"录像只读出 {n_read} 帧，时间表有 {len(times)} 帧：后面的没处理")
    end_t = now + 1.0 / vfps
    clock["now"] = end_t
    svc._end_session(end_t, reason="录像结束")

    if not args.quiet:
        for t, kind, text in log:
            print(f"{t:7.1f}s  {kind}  {text}")
    got: dict[str, dict[str, int]] = {}
    for _, _, e in captured:
        d = got.setdefault(e["cls"], {"in": 0, "out": 0})
        d["in" if e["delta"] > 0 else "out"] += 1

    rate, rate_lo, rate_hi = rate_stats(proc_times)
    rate_text = f"抽帧后实际 {rate:.1f} 帧/秒（目标 {round(sim_fps, 2):g}"
    if rate_lo is not None:
        rate_text += f"；每 {RATE_WINDOW:g} 秒一段，最低 {rate_lo:.1f}、最高 {rate_hi:.1f}"
    rate_text += f"；计数规则按 {cfg_fps} 帧/秒换算）"
    print(f"\n== {video.name}  引擎 {args.engine}（{svc.engine_name}）  模型 {Path(args.model).name}@{args.imgsz}  "
          f"规则 {args.preset}  {'不待机' if args.no_standby else '待机开'}")
    print(f"录像 {vfps:.1f} 帧/秒（时间按 {time_source}）；{rate_text}")
    print(f"计数线 {','.join(f'{v:g}' for v in line)}（{line_source}）")
    if rate_lo is not None and rate_lo < 0.9 * sim_fps:
        print(f"！有一段只处理了 {rate_lo:.1f} 帧/秒（目标 {round(sim_fps, 2):g}）：录像那段帧率低、暂停或掉帧")
    print(f"开门会话 {len(svc.sessions)} 次；识别帧占比 {active_frames}/{total_frames} = "
          f"{active_frames / max(total_frames, 1):.0%}；本机每帧识别 {1000 * t_active / max(active_frames, 1):.0f} ms")
    for s in svc.sessions:
        print(f"  #{s['n']}  {s['seconds']:>5} 秒  事件 {s['events']}  醒：{s['wake']}  睡：{s['sleep']}")
    if truth and truth.get("expected"):
        exp = truth["expected"]
        err = 0
        for cls in sorted(set(exp) | set(got)):
            e_in, e_out = exp.get(cls, {}).get("in", 0), exp.get(cls, {}).get("out", 0)
            g_in, g_out = got.get(cls, {}).get("in", 0), got.get(cls, {}).get("out", 0)
            err += abs(g_in - e_in) + abs(g_out - e_out)
            print(f"  {cls:8s} 放入 {g_in}/{e_in}  拿出 {g_out}/{e_out}")
        print(f"  和真值的差（各类别放入、拿出次数之差的总和）：{err}")
    else:
        print(f"  计数：{got}")

    # 每个事件：t = 过线时刻（和 Mac 路线一样），t_emit = 确认计数的时刻
    rows, missing = [], 0
    for t_emit, n, e in captured:
        c = crossing(n, e)
        if c is None:
            missing += 1
        t_cross, vframe = c if c else (t_emit, None)
        rows.append({"t": round(t_cross, 3), "t_emit": round(t_emit, 3), "delta": e["delta"], "cls": e["cls"],
                     "tid": e.get("tid"), "frame": vframe, "session": n})
    if missing:
        warn(f"{missing} 个事件查不到过线时刻，t 用确认计数的时刻代替（会偏晚）")

    if err_frames:
        sys.stdout.flush()
        print(f"\n！！！识别失败 {err_frames} 帧（识别的帧一共 {active_frames} 帧）。最后一次：{last_err}",
              file=sys.stderr, flush=True)
        if err_frames * 2 > active_frames:
            print("！！！超过一半的帧识别失败，上面的计数不可信：不写事件文件，退出码 2", file=sys.stderr, flush=True)
            if args.events_json and Path(args.events_json).exists():
                warn(f"{args.events_json} 是以前的文件，不是这次的结果")
            return 2

    if args.events_json:
        versions = {"python": platform.python_version()}
        for mod in ("ultralytics", "torch", "cv2", "numpy"):
            try:
                versions[mod] = __import__(mod).__version__
            except Exception:
                versions[mod] = "?"
        note = (time_note + "；" if time_note else "") + rate_text
        out = {
            "schema": "events-v1",
            "video": video.name,
            "route": f"board-sim-{args.engine}",
            "time_base": {"source": time_source, "fps": round(vfps, 3), "frames": len(times),
                          "duration_s": round(times[-1], 3), "note": note,
                          "processed_fps": round(rate, 3), "processed_frames": len(proc_times)},
            "provenance": {
                "engine": args.engine, "engine_name": svc.engine_name,
                "model": f"{Path(args.model).name} imgsz={args.imgsz}" if args.engine != "npu" else "板子 NPU 模型",
                "counter": f"orangepi_app/app/services/line_counter.py + counter_service.py @ {git_rev()}",
                "preset": args.preset, "camera_fps_requested": args.fps, "camera_fps_simulated": round(sim_fps, 3),
                "counter_config_fps": cfg_fps, "width": args.width,
                "door_standby": not args.no_standby, "line": line, "line_source": line_source,
                "exclude": f"板子 EXCLUDE_CLASSES（{len(cs.EXCLUDE_CLASSES)} 类）",
                "event_times": "t = 过线时刻（录像里的秒，和 Mac 路线一样）；t_emit = 确认计数的时刻；"
                               "frame = 过线那一帧是录像第几帧（从 1 数）",
                "detector_error_frames": err_frames, "active_frames": active_frames,
                "events_without_crossing_time": missing,
                "assumes": "包括画面判断开门和待机；窗口外的误计会出现在这里",
                "versions": versions, "made_by": "orangepi_app/tools/simulate_counter.py",
                "made_at": datetime.now().isoformat(timespec="seconds"),
            },
            "sessions": [{k: s.get(k) for k in ("n", "seconds", "events", "wake", "sleep")} for s in svc.sessions],
            "events": rows,
        }
        Path(args.events_json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写 {args.events_json}：{len(rows)} 个事件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
