# BX Project · 饮食均衡助手 / 食光冰箱

> **2026-11-04 方向变更**：改为纯视觉家用方案——冰箱内摄像头 + Jetson Nano 本地 YOLO，开门触发关键帧自动记账，
> 不拍照、不扫码、不拍小票、不上云。项目计划书见 [docs/PROPOSAL.md](docs/PROPOSAL.md)，执行计划见 [PLAN.md](PLAN.md)，所需资料见 [docs/RESOURCES.md](docs/RESOURCES.md)，
> 哪些旧资料还要用见 [docs/INVENTORY.md](docs/INVENTORY.md)；下面的子项目说明仍描述现状。

一个"拍照识别 → 人工确认 → 入库 → 营养与食谱"的本地优先食品库存系统，目标设备是 Orange Pi 4 Pro +
USB 摄像头 + 手持扫码枪，手机或触摸屏通过浏览器使用。

本仓库是整理后的唯一工作区（`~/Projects/bx-project`）。iCloud 和 `~/Downloads` 里的原始副本保持原样，
不要再在 iCloud 目录里开发：iCloud 会同步 `.venv`、丢文件（这次就丢了两个 `index.html` 和模型权重）。

## 子项目一览

| 目录 | 是什么 | 状态（2026-11-04） |
| --- | --- | --- |
| [`archive/smart_fridge_demo/`](archive/smart_fridge_demo/) | 功能最全的单体 Web 应用 v0.4.0：食物照片 YOLO、条码、小票 OCR、包装日期 OCR、库存、营养看板、DeepSeek 食谱、PWA。手机上传图片即可，不依赖设备摄像头。 | 可运行；已加 Docker，是**云端部署主线** |
| [`smart_fridge_app/`](smart_fridge_app/) | 重写的"本地优先主软件"：持久化拍照会话、应用自有图库、库存流水、真实摄入统计、备份包。识别能力尚未接入，依赖 `camera_system` 提供摄像头。 | 23 个单元测试全部通过；是**设备端主线** |
| [`archive/camera_system/`](archive/camera_system/) | Orange Pi 上的摄像头守护进程：USB 摄像头独占、GPIO 实体按钮、MJPEG 预览、本地 OCR 归档，HTTP API 供主软件调用。 | 6 个测试通过；只能在 Linux 设备上完整运行 |
| [`archive/hardware/`](archive/hardware/) | 手持扫码枪外壳 V1–V3：OpenSCAD 源文件、CadQuery/Fusion 360 STEP、可打印 STL/3MF。V3 是当前版本，见 [交接文档](archive/hardware/scanner-gun-v3/PROJECT_HANDOFF.md)。 | 建模完成，未打印验证 |
| [`archive/yolov11训练-onnx/`](archive/yolov11训练-onnx/) | YOLO11 食物检测模型的类别表（80 类）和测试结果图；权重统一放在 `fridge_vision/models/food_best.onnx`（此处是符号链接）。 | 模型可用，80 类已有中文名映射；缺真实照片验收集 |
| [`archive/reference/`](archive/reference/) | Orange Pi 4 Pro 用户手册、研究素材 PPT、历史截图。 | 参考资料 |

两个 Web 应用的关系：`smart_fridge_demo` 是老师 demo 基础上做出来的完整功能版；`smart_fridge_app` 是按
[调研与决策文档](smart_fridge_app/docs/RESEARCH_AND_DECISIONS.md) 重做的更稳的底座。短期内两者并行：
demo 负责云端演示和识别能力，app 负责设备端；合流计划见 [PLAN.md](PLAN.md)。

## 快速开始（本机 macOS）

两个应用各自的虚拟环境已经建好（Python 3.11）。

启动 demo（打开 http://127.0.0.1:8000 ）：

```bash
cd archive/smart_fridge_demo && SMART_FRIDGE_GPIO_BUTTON_ENABLED=false .venv/bin/python -m uvicorn app.main:app --port 8000
```

启动主软件（无摄像头时首页会提示相机离线，库存等功能可用）：

```bash
cd smart_fridge_app && ./start.sh
```

跑测试：

```bash
cd smart_fridge_app && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

```bash
cd archive/camera_system && PYTHONPATH=. ../smart_fridge_app/.venv/bin/python -m unittest discover -s tests -v
```

如果虚拟环境丢了，重建：

```bash
cd archive/smart_fridge_demo && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt httpx2
```

```bash
cd smart_fridge_app && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt -r requirements-dev.txt
```

## 部署到云

见 [DEPLOY.md](DEPLOY.md)。一句话版本：任意一台装了 Docker 的 Linux 云主机上

```bash
DEEPSEEK_API_KEY=sk-xxx docker compose -f archive/smart_fridge_demo/docker-compose.yml up -d --build
```

## 密钥与数据边界

- `archive/smart_fridge_demo/config/api_settings.json` 里有一把真实的 DeepSeek 密钥，已被 `.gitignore` 排除。它曾随压缩包
  在多台机器间流转，**建议去 DeepSeek 控制台轮换一次**，新密钥只通过环境变量 `DEEPSEEK_API_KEY` 注入。
- 数据库、上传图、运行目录、备份都不入库（见 [`.gitignore`](.gitignore)）。
- 两个应用都没有登录鉴权，只适合可信局域网。公网部署前必须加访问口令，DEPLOY.md 给了最省事的做法。

## 仓库约定

- 一个 git 仓库管全部子项目，`main` 分支；提交前确认 `git status` 没有 `.env`、`api_settings.json`、`*.db`。
- 模型权重只跟踪当前使用的 `fridge_vision/models/food_best.onnx`（10.7 MB），其余 `.onnx` 不入库。
- 3D 打印导出件（STL/3MF/STEP，共约 25 MB）入库，方便直接下载切片。
