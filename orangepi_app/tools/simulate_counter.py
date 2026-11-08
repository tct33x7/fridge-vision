"""用录像代替摄像头，跑一遍板子上的计数服务（同一份 counter_service 代码），看开门 / 待机时间线和计数结果。

不连摄像头、不写数据库，Mac 和板子上都能跑。例子（在仓库根目录）：

    fridge_vision/.venv/bin/python orangepi_app/tools/simulate_counter.py demos/yolo_web_counter/test_videos/jitter1.mp4 \
        --model ~/某处/yolo11n_320.onnx --imgsz 320

录像会被缩到 640 宽、抽帧到 --fps（默认 15，和板子摄像头一样）。真值默认找 <录像名>.truth.json（第 2 步的格式）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", default=str(APP_DIR / "models" / "yolo11s.pt"))
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--preset", default="default")
    ap.add_argument("--fps", type=float, default=15.0, help="模拟的摄像头帧率（录像按它抽帧）")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--truth", help="真值 json；默认 <录像名>.truth.json")
    ap.add_argument("--line", help="计数线 ax,ay,bx,by；默认用真值里的")
    ap.add_argument("--no-standby", action="store_true", help="关掉待机（一直识别），用来对比")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    # 必须在导入 app.* 之前设好：不碰真实数据目录；帧率、模型、规则和板子一致
    os.environ["SMART_FRIDGE_STORAGE_DIR"] = tempfile.mkdtemp(prefix="sim_storage_")
    os.environ["SMART_FRIDGE_CAMERA_FPS"] = str(int(args.fps))
    os.environ["SMART_FRIDGE_COUNTER_MODEL"] = str(Path(args.model).expanduser())
    os.environ["SMART_FRIDGE_COUNTER_IMGSZ"] = str(args.imgsz)
    os.environ["SMART_FRIDGE_COUNTER_PRESET"] = args.preset
    os.environ["SMART_FRIDGE_DOOR_STANDBY"] = "false" if args.no_standby else "true"
    os.environ["SMART_FRIDGE_COUNTER_ENGINE"] = "cpu"   # 开发机没有 NPU；在板子上跑时可改成 npu
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
    from app.services.counter_service import CounterService

    video = Path(args.video).expanduser()
    truth_path = Path(args.truth) if args.truth else video.with_suffix(".truth.json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else None
    line = [float(v) for v in args.line.split(",")] if args.line else (truth or {}).get("line")

    svc = CounterService(load_history=False, persist=False)
    if line:
        svc.set_line(*line)
    detect = svc._init_engine()
    if detect is None:
        print(svc.status_text); return 1

    cap = cv2.VideoCapture(str(video))
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(vfps / args.fps))
    idx = active_frames = total_frames = 0
    t_active = 0.0
    log = []
    prev_state = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if (idx - 1) % step:
            continue
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (args.width, round(h * args.width / w)))
        now = (idx - 1) / vfps
        t0 = time.perf_counter()
        n_events_before = len(svc.events)
        svc.process_frame(detect, frame, now)
        total_frames += 1
        if svc.door.active:
            active_frames += 1
            t_active += time.perf_counter() - t0
        if svc.door.state != prev_state:
            log.append((now, "唤醒" if svc.door.active else "待机",
                        svc.door.wake_reason if svc.door.active else svc.door.sleep_reason))
            prev_state = svc.door.state
        for e in list(svc.events)[n_events_before:]:
            log.append((now, "计数", f"{e['cls']} {'放入' if e['delta'] > 0 else '拿出'}"))
    end_t = idx / vfps
    svc._end_session(end_t, reason="录像结束")

    if not args.quiet:
        for t, kind, text in log:
            print(f"{t:7.1f}s  {kind}  {text}")
    got: dict[str, dict[str, int]] = {}
    for e in svc.events:
        d = got.setdefault(e["cls"], {"in": 0, "out": 0})
        d["in" if e["delta"] > 0 else "out"] += 1
    print(f"\n== {video.name}  模型 {Path(args.model).name}@{args.imgsz}  规则 {args.preset}  "
          f"{'不待机' if args.no_standby else '待机开'}  抽帧到 {args.fps:g} 帧/秒")
    print(f"开门会话 {len(svc.sessions)} 次；识别帧占比 {active_frames}/{total_frames} = "
          f"{active_frames / max(total_frames, 1):.0%}；本机每帧识别 {1000 * t_active / max(active_frames, 1):.0f} ms")
    for s in svc.sessions:
        print(f"  #{s['n']}  {s['seconds']:>5} 秒  事件 {s['events']}  醒：{s['wake']}  睡：{s['sleep']}")
    if truth:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
