# BX Project · 冰箱门口自动记账

冰箱开门时，门洞上方的相机拍下手往里放、往外拿的东西；关门后自动判断"放入 / 拿出 · 什么 · 几件"，更新家里的库存。
不扫码、不拍小票、不用手动记，并且**能用数字说明自己有多准**。

原则：真实的问题、真实的测量、每个数字有出处；把最难的部分（门口识别）做好，不求功能全。可交付版本 11-22，打磨到 11-29。

## 现在到哪了（2026-11-08）

- **11-07** 第一次在真冰箱上测量（[实验 E01](docs/experiments/E01_front_20261107.md)，16 次真实开门 + 真值）：
  正面机位时人会挡住冰箱，亮度触发不可靠，YOLO 只认出 2/27。
- **11-08** 和老师定下 **v4**：相机改装到门洞上方，只拍手和手里的东西；库存由用户初始化，之后靠进出事件增减；主机用 OrangePi 4 Pro。
  见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
- **11-08 下午** 列出 7 步待办流程（[docs/SCHEDULE.md](docs/SCHEDULE.md)）。第 1 步"电脑端初步的物品进出统计"已完成：
  [`demos/yolo_web_counter`](demos/yolo_web_counter/)，YOLO11s + ByteTrack，网页上拖线按方向计数。
- **下一步**：第 2 步，针对光线、物品抖动优化识别；同时尽早在 OrangePi 上测一次帧率。

## 系统怎么拼起来

```text
门磁 / 画面触发 + 门洞上方相机
        │ 开门：录像落盘
        ▼
fridge_vision/      关门后离线分析：切动作 → 判方向 → 手里有什么（大模型）→ 事件
        │ HTTP
        ▼
smart_fridge_app/   库存后端（FastAPI + SQLite）：初始化、事件、纠错、对账、保质期
        │ 同一套网页
        ▼
手机浏览器 / 门边小屏（可选）
```

开发在 Mac 上，运行在 OrangePi 4 Pro 上，两边是同一套代码。

上图是 v4 架构里"关门后离线分析"的路线。按 11-08 下午的 7 步计划，识别先用 [`demos/yolo_web_counter`](demos/yolo_web_counter/) 的实时 YOLO11s + ByteTrack 过线计数，两条路线的关系见 [ARCHITECTURE](docs/ARCHITECTURE.md) 开头。

## 目录地图

| 目录 | 是什么 | 状态 |
| --- | --- | --- |
| [`fridge_vision/`](fridge_vision/) | 门口视觉：录制工具、离线分析（方向、认名）、评测脚本。`runs/` 是本机数据 | **主线** |
| [`orangepi_app/`](orangepi_app/) | **OrangePi 上实际运行的程序**（11-08 从板子同步）：网页、拍照识别、过线计数、GPIO 按钮；用 `deploy/opi_sync.sh` 同步 | **主线**（部署中） |
| [`smart_fridge_app/`](smart_fridge_app/) | 库存后端和网页（手机 / 小屏）：批次、门事件、拍照录入、备份；34 个测试 | **主线** |
| [`docs/`](docs/) | 架构、日程、决策、实验记录、报告。[目录](docs/README.md) | **主线** |
| [`demos/`](demos/) | 独立的小 demo。`yolo_web_counter/`：网页版 YOLO11s + ByteTrack，拖一条计数线，按方向统计物品进出（11-08） | 演示 / 练习 |
| [`hardware/`](hardware/) | 相机支架、门磁、主机外壳 | 预留（v4 新增） |
| [`deploy/`](deploy/) | 连接 OrangePi、同步代码、重启服务 | 在用 |
| [`archive/`](archive/) | 旧项目：拍照 / 扫码 demo、OrangePi 相机服务、扫码枪外壳、OrangePi 手册 | 归档；相机服务的 GPIO 代码和手册 v4 还会用到 |

## 快速开始（Mac）

虚拟环境已经建好（Python 3.11）。录制要在 macOS 自带的"终端" App 里运行（Claude 里的终端没有相机权限），外接相机编号是 0。

录制一次实验（新实验用自己的文件夹，开门前、关门后各按一次 `o`）：

```bash
SOURCE=0 ~/Projects/bx-project/fridge_vision/run_record.command --trigger manual --out-dir runs/e03_overhead_20261114
```

统计、离线链路试跑（把文件夹换成要分析的实验）：

```bash
cd ~/Projects/bx-project/fridge_vision && .venv/bin/python analyze_sessions.py runs/e01_front_20261107 --contact
```

```bash
cd ~/Projects/bx-project/fridge_vision && .venv/bin/python process_session.py runs/e01_front_20261107 --dry-run --line 0.55 --band 0.50
```

启动后端（手机在同一个 Wi-Fi 下打开 `http://<Mac 的 IP>:8000`）、跑测试：

```bash
open ~/Projects/bx-project/smart_fridge_app/run_backend.command
```

```bash
cd ~/Projects/bx-project/smart_fridge_app && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

虚拟环境丢了就重建：

```bash
cd ~/Projects/bx-project/fridge_vision && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd ~/Projects/bx-project/smart_fridge_app && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt -r requirements-dev.txt
```

## 规矩

- **永不进 git**：`fridge_vision/runs/`（家里的录像）、`.env`、任何密钥、数据库。`.gitignore` 已覆盖；提交前看一眼 `git status`。
- **GitHub**：私有仓库 [tct33x7/fridge-vision](https://github.com/tct33x7/fridge-vision)，老师和同学加为协作者。
  改代码走分支 + Pull Request；改文档可以直接提交到 `main`；提交前先 `git pull`；提交信息写清改了什么、为什么。
- **密钥**：`archive/smart_fridge_demo/config/api_settings.json` 里有一把真实的 DeepSeek 密钥（不在 git 里），它曾随压缩包流转，建议去控制台轮换。
  大模型密钥只通过环境变量传入（`VLM_API_KEY`）。
- **隐私**：只在家里局域网用，不把端口开到公网；报告和展示只用没有人脸的帧。

## 协作与 AI 使用

| 谁 | 做了什么 |
| --- | --- |
| 项目发起人（TCT37） | 提出问题和方向，做每一次方向决定（见 [DECISIONS](docs/DECISIONS.md) 的"谁提出"一列）；架设相机，录制 E01 并记真值；和老师讨论定下 v4 |
| 老师 | 11-08 架构讨论（机位、主机、界面）；硬件和大模型密钥 |
| 同学 | （待补充） |
| Claude（Anthropic 的 AI，经 Claude Code） | 11-04 起这个仓库所有提交里的代码和文档文字（每个提交都带 `Co-Authored-By: Claude`），以及分析和建议 |
| 更早的材料 | 2026 年 7–8 月的旧项目，11-04 第一次提交时整体导入：研究素材 PPT（选题、背景、接线、任务列表）、`smart_fridge_demo`（基于老师的 demo）、`smart_fridge_app`、`camera_system`、扫码枪外壳（交接文档显示在 OpenAI Codex 环境里生成） |

文档里的"你"指项目发起人，"我"指 Claude。
