# fridge_vision · 门口视觉

开门时录像，关门后离线分析出"放入 / 拿出 · 什么 · 几件"，并且能和真值对比算准确率。v4 设计见 [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)。

## 主线工具

| 脚本 | 做什么 | 输出（在会话文件夹或实验文件夹里） |
| --- | --- | --- |
| `record_sessions.py`（双击用 `run_record.command`） | 开门录整段 + 过线关键帧 + 关门后在终端问真值 | `<会话>/clip.mp4`、`kf_*.jpg`、`session.json` |
| `analyze_sessions.py` | 统计：触发、可见率（脚本口径）、YOLO 召回、物品清单；`--contact` 每会话一张拼图 | `summary.md`、`<会话>/contact.jpg` |
| `name_keyframes.py`（调用 `vlm.py`） | 关键帧交给多模态大模型认名，和真值比 | `<会话>/naming.json`、`naming_summary.md` |
| `process_session.py` | 离线链路：运动段 → 光流方向 → 往返配对 → 认名 → 事件；可上报后端 | `<会话>/events.json`、`events_summary.md` |
| `list_cameras.py` | 列出摄像头编号 | — |

## 常用命令

都在这个目录里运行。录制必须在 macOS 自带的"终端" App 里跑（要相机权限），外接相机编号是 0。

```bash
SOURCE=0 ~/Projects/bx-project/fridge_vision/run_record.command --trigger manual --out-dir runs/e03_overhead_20261114
```

开门前、关门后在画面窗口各按一次 `o`，关门后切到终端填三行真值；`q` 退出。参数（`--line`、`--band`、`--axis`）记在实验记录里，分析时要传同样的值。

```bash
.venv/bin/python analyze_sessions.py runs/e01_front_20261107 --contact
```

```bash
.venv/bin/python process_session.py runs/e01_front_20261107 --dry-run --line 0.55 --band 0.50
```

认名需要密钥（通义千问百炼或任何 OpenAI 兼容接口）：设 `VLM_API_KEY`，可选 `VLM_BASE_URL`、`VLM_MODEL`。先用 `--dry-run` 看会发多少张，没有密钥时用 `--fake` 跑通流程。

```bash
.venv/bin/python name_keyframes.py runs/e01_front_20261107 --dry-run
```

`process_session.py` 加 `--post-url http://127.0.0.1:8000` 会把事件上报给后端（先启动 `smart_fridge_app/run_backend.command`）。

## 数据布局（`runs/`，只在本机，永不进 git）

| 目录 | 是什么 |
| --- | --- |
| `e01_front_20261107/` | 实验 E01：正面机位 16 个会话、`summary.md`、`人工可见性.md`；`_test_sessions/` 是调试时的测试会话 |
| `eNN_短名_日期/` | 以后的实验，录制时用 `--out-dir` 指定 |
| `sessions_selftest/`、`synthetic.mp4` | 合成视频自检 |
| `_legacy_door_demo_1104-1106/` | 11-04～06 桌面 demo 的输出 |

每个实验的说明在 [docs/experiments/](../docs/experiments/)。

## 已知问题（v4 要改，代码改动走分支）

- **横线方向不支持**：相机装在门洞上方时，门洞截面在画面里是横线。`record_sessions.py` 在 `--axis y` 时重心算成了 x 坐标；`process_session.py` 只算左右方向的光流。临时办法：相机转 90° 装。
- **亮度触发在 Mac 上不可用**：自动曝光 1–7 秒内把亮度拉回（E01）。现在用手动 `o`；v4 倾向门磁。
- **"时长"含填真值的时间**：`session.json` 的结束时间取在问完真值之后，`summary.md` 的时长偏大；准确时长 = 帧数 ÷ 帧率。
- `session.json` 里的 YOLO 检测只存前 400 条。
- **待写**：`import_clip.py`（把手机录像导入成会话，用于 E02 试机位）、门磁触发、环形缓冲、无窗口运行、关门后自动分析。

## 对照组（保留，不再开发）

`door_demo.py`（YOLO + ByteTrack 实时过线，11-04 PLAN v2 的方案）及其启动脚本 `run_demo.command`、`run_fridge.command`、`run_acceptance.command`，
加上合成视频生成 `make_synthetic_video.py`。E00 的桌面验收用的就是它。不用摄像头的自检：

```bash
.venv/bin/python make_synthetic_video.py runs/synthetic.mp4 && .venv/bin/python door_demo.py --source runs/synthetic.mp4 --trigger auto --headless --out runs/synthetic_events.jsonl
```

模型：`models/food_best.onnx`（80 类食物，正本）、`yolo11n.pt`（COCO，首次运行自动下载，不进 git）。

## 安装（Mac）

```bash
cd ~/Projects/bx-project/fridge_vision && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
