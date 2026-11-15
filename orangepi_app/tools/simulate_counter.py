"""用录像代替摄像头，跑一遍板子上的计数服务（同一份 counter_service 代码），看开门 / 待机时间线和计数结果。

不连摄像头、不写数据库，Mac 和板子上都能跑。例子（在仓库根目录）：

    fridge_vision/.venv/bin/python orangepi_app/tools/simulate_counter.py demos/yolo_web_counter/test_videos/jitter1.mp4 \\
        --model demos/yolo_web_counter/models/yolo11s.pt --imgsz 320

录像会被缩到 640 宽、抽帧到 --fps（默认 15，和板子摄像头一样）。真值默认找 <录像名>.truth.json（第 2 步的格式）。

三种识别引擎（--engine）：
  cpu       ultralytics 模型 + ultralytics 自带的 ByteTrack（Mac 上默认）。和板子不同：板子用的是 NPU + ByteTrackLite。
  cpu-lite  ultralytics 模型只做检测，追踪用板子上的 ByteTrackLite（app/services/bytetrack_lite.py）。
            检测器仍然和板子不同，但追踪和板子一样：改了 ByteTrackLite 以后，可以在 Mac 上先看前后差别。是"代理"，不是板子的数字。
  npu       板子上的 NPU YOLOv5s + ByteTrackLite，和板子实际运行的完全一样。只能在板子上跑；别处会直接报错退出。

时间：有 <录像名>.frames.json（新版录制工具记的每帧真实时刻）就按它算，抽帧也按真实帧率；
没有就按文件头帧率，并提示（旧版录制工具文件头固定写 30，相机实际可能只有 15）。

--events-json 输出每个计数事件的时间（录像里的秒）、方向、类别，格式和 eval/events_mac.py 一样，
可以直接交给 eval/score_actions.py 逐动作打分。

在板子上跑：deploy/opi.sh 同步时不带 tools/，要手动把这个文件和录像拷过去，例如
    scp orangepi_app/tools/simulate_counter.py opi:smart_fridge_demo/tools/
    scp 录像.mp4 录像.frames.json opi:/tmp/
    ssh opi 'cd smart_fridge_demo && .venv/bin/python tools/simulate_counter.py /tmp/录像.mp4 --engine npu \\
             --line 0,0.5,1,0.5 --events-json /tmp/录像.board-npu.events.json'
"""
from __future__ import annotations

import argparse
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


def load_times(video: Path, n_frames: int, header_fps: float, override: float | None):
    """每帧的时刻（秒）和真实帧率。优先 .frames.json，其次 --video-fps，最后文件头。"""
    side = video.with_suffix(".frames.json")
    if side.exists() and not override:
        t = [float(x) for x in json.loads(side.read_text(encoding="utf-8"))["t"]]
        if len(t) != n_frames:
            print(f"！{side.name} 有 {len(t)} 帧，录像 {n_frames} 帧，不一致：按较短的算", file=sys.stderr)
        gaps = [b - a for a, b in zip(t, t[1:]) if 0 < b - a < 1.0]
        fps = 1.0 / statistics.median(gaps) if gaps else header_fps
        return t, fps, "sidecar"
    fps = override or header_fps or 30.0
    if not override:
        print(f"！没有 {side.name}，按文件头 {fps:g} 帧/秒算时间（可能不准）", file=sys.stderr)
    return [i / fps for i in range(n_frames)], fps, ("video_fps" if override else "header")


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
        r = model.predict(frame, conf=low, imgsz=svc.imgsz, device="cpu", verbose=False)[0]
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
    ap.add_argument("--fps", type=float, default=15.0, help="模拟的摄像头帧率（录像按它抽帧）")
    ap.add_argument("--video-fps", type=float, help="没有 .frames.json 时，录像的真实帧率（比如秒表测的）")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--truth", help="真值 json；默认 <录像名>.truth.json")
    ap.add_argument("--line", help="计数线 ax,ay,bx,by；默认用真值里的")
    ap.add_argument("--no-standby", action="store_true", help="关掉待机（一直识别），用来对比")
    ap.add_argument("--events-json", help="把计数事件（带录像里的时间）写成事件文件，给 eval/score_actions.py 打分")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    # 必须在导入 app.* 之前设好：不碰真实数据目录；帧率、模型、规则和板子一致
    os.environ["SMART_FRIDGE_STORAGE_DIR"] = tempfile.mkdtemp(prefix="sim_storage_")
    os.environ["SMART_FRIDGE_CAMERA_FPS"] = str(int(args.fps))
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

    import cv2
    from app.services import counter_service as cs
    from app.services.counter_service import CounterService

    video = Path(args.video).expanduser()
    truth_path = Path(args.truth) if args.truth else video.with_suffix(".truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else None
    line = [float(v) for v in args.line.split(",")] if args.line else (truth or {}).get("line")

    svc = CounterService(load_history=False, persist=False)
    # 板子程序在内存里只留最近 100 个事件、20 次开门（给网页看）；模拟要全部，换成不限长度的
    svc.events = deque()
    svc.sessions = deque()
    if line:
        svc.set_line(*line)
    if args.engine == "cpu-lite":
        detect = make_lite_detector(svc, str(Path(args.model).expanduser()))
    else:
        detect = svc._init_engine()
    if detect is None:
        msg = svc.status_text
        if args.engine == "npu":
            msg += "（NPU 引擎只能在板子上用）"
        print(msg)
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

    cap = cv2.VideoCapture(str(video))
    header_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_hdr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    times, vfps, time_source = load_times(video, n_hdr, header_fps, args.video_fps)
    step = max(1, round(vfps / args.fps))
    idx = active_frames = total_frames = 0
    t_active = 0.0
    log = []
    prev_state = None
    now = 0.0
    while True:
        ok, frame = cap.read()
        if not ok or idx >= len(times):
            break
        idx += 1
        if (idx - 1) % step:
            continue
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (args.width, round(h * args.width / w)))
        now = times[idx - 1]
        clock["now"] = now
        t0 = time.perf_counter()
        n_before = len(captured)
        svc.process_frame(detect, frame, now)
        total_frames += 1
        if svc.door.active:
            active_frames += 1
            t_active += time.perf_counter() - t0
        if svc.door.state != prev_state:
            log.append((now, "唤醒" if svc.door.active else "待机",
                        svc.door.wake_reason if svc.door.active else svc.door.sleep_reason))
            prev_state = svc.door.state
        for _, _, e in captured[n_before:]:
            log.append((now, "计数", f"{e['cls']} {'放入' if e['delta'] > 0 else '拿出'}"))
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
    print(f"\n== {video.name}  引擎 {args.engine}（{svc.engine_name}）  模型 {Path(args.model).name}@{args.imgsz}  "
          f"规则 {args.preset}  {'不待机' if args.no_standby else '待机开'}  抽帧到 {args.fps:g} 帧/秒"
          f"（录像 {vfps:.1f} 帧/秒，时间按 {time_source}）")
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

    if args.events_json:
        versions = {"python": platform.python_version()}
        for mod in ("ultralytics", "torch", "cv2", "numpy"):
            try:
                versions[mod] = __import__(mod).__version__
            except Exception:
                versions[mod] = "?"
        out = {
            "schema": "events-v1",
            "video": video.name,
            "route": f"board-sim-{args.engine}",
            "time_base": {"source": time_source, "fps": round(vfps, 3), "frames": len(times),
                          "note": f"抽帧到 {args.fps:g} 帧/秒"},
            "provenance": {
                "engine": args.engine, "engine_name": svc.engine_name,
                "model": f"{Path(args.model).name} imgsz={args.imgsz}" if args.engine != "npu" else "板子 NPU 模型",
                "counter": f"orangepi_app/app/services/line_counter.py + counter_service.py @ {git_rev()}",
                "preset": args.preset, "camera_fps_simulated": args.fps, "width": args.width,
                "door_standby": not args.no_standby, "line": line,
                "exclude": f"板子 EXCLUDE_CLASSES（{len(cs.EXCLUDE_CLASSES)} 类）",
                "assumes": "包括画面判断开门和待机；窗口外的误计会出现在这里",
                "versions": versions, "made_by": "orangepi_app/tools/simulate_counter.py",
                "made_at": datetime.now().isoformat(timespec="seconds"),
            },
            "sessions": [{k: s.get(k) for k in ("n", "seconds", "events", "wake", "sleep")} for s in svc.sessions],
            "events": [{"t": round(t, 3), "delta": e["delta"], "cls": e["cls"], "tid": e.get("tid"), "session": n}
                       for t, n, e in captured],
        }
        Path(args.events_json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写 {args.events_json}：{len(captured)} 个事件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
