# BX Project · 冰箱门口自动记账

冰箱开门时，门洞上方的相机拍下手往里放、往外拿的东西；关门后自动判断"放入 / 拿出 · 什么 · 几件"，更新家里的库存。
不扫码、不拍小票、不用手动记，并且**能用数字说明自己有多准**。
（这是要做成的样子。实际做到了哪一步，看下面"现在到哪了"。）

原则：真实的问题、真实的测量、每个数字有出处；把最难的部分（门口识别）做好，不求功能全。可交付版本 11-22，打磨到 11-29。

## 现在到哪了（2026-11-25 收尾）

**11-25 项目发起人决定现在就收尾。** 这个仓库停在：方向定了，"判断"这一步写成了程序，没有在新录像上验证。从头到尾的经过见[开发故事](docs/STORY.md)；收尾时做完了什么、没做什么，见它的"收尾时停在哪"一节。
更早的进度总结在 [docs/progress/](docs/progress/)（最新：[2026-11-08](docs/progress/2026-11-08.md)）。

- **11-07** 第一次在真冰箱上测量（[实验 E01](docs/experiments/E01_front_20261107.md)，16 次真实开门 + 真值）：
  正面机位时人会挡住冰箱，亮度触发不可靠，YOLO 只认出 2/27（这几个数字的口径待复核，见 [CLAIMS_CHECK](docs/experiments/CLAIMS_CHECK.md)）。
- **11-08** 和老师定下 **v4**：相机改装到门洞上方，只拍手和手里的东西；库存由用户初始化，之后靠进出事件增减；主机用 OrangePi 4 Pro。
  见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
- **11-08 下午** 列出 7 步待办流程（[docs/SCHEDULE.md](docs/SCHEDULE.md)）。第 1、2 步完成；第 3 步第一版部署到板子（NPU 识别、画面判断开门、待机）。
- **11-12** E03 选机位的步骤准备好了。A / B / C 三个位置最后没有录。
- **11-15** 当时计划的下一步是：E03 → 定机位、做支架 → 冻结规则 → E04 冰箱实测。这条线没有走完。
- **11-21** 相机第一次装到冰箱冷藏室上方（计划外的位置 D），录了一段 10 个动作。开门检测 10 次都醒了；数过线，有物品的 8 个动作只数对 0–1 个（[E03 记录](docs/experiments/E03_position_20261112.md)；一段录像，开发数据）。
- **11-22** 同一段录像不数过线，改看"手伸进去之前和出来以后手里各是什么"（这个判法是项目发起人提的），交给没看过答案的视觉模型来判：两个较大的模型 8/8，最小的模型每个动作单独问 6/8。这是开发数据，判的是对话里的 AI 子代理，不是程序。当天想补录一段新的，没有录成。
- **11-23** 现有录像里没分析过的 7 次开门，交给最小的模型：冰箱里那台相机、一次只拿或只放一样、能定真值的 3 次都对；"拿出来又放回去"判不了。
- **11-24** 按这个判法定了方案（[决策日志](docs/DECISIONS.md)），换掉 11-08 的实时数过线；"判断"这一步写成了程序（[`fridge_vision/judge_door.py`](fridge_vision/README.md)）。
- **11-25 收尾时没有做的**：定下来的方案没有在新录像上验证（事先写定的那次测试没有做）；判断程序没有密钥，一次真的请求都没有发过；相机支架、"问一句"的界面、接进库存都没有做；这套判法没有上板子，板子上跑的仍然是 11-08 的过线计数。报告正文和演示视频由项目发起人来做。

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

**11-24 更新**：识别的主线改回上图这条路线：关门后由视觉大模型看"手伸进去之前和出来以后手里各是什么"，说不清的问人一句；实时过线计数不再是主线。
"判断"这一步 11-24 下午写成了程序（[`fridge_vision/judge_door.py`](fridge_vision/README.md)），但还没有密钥，一次真的请求都没有发过；有数据的只有"一次开门只拿或只放一样"这一种（能定真值的 3 次都判对，判的是对话里的子代理，不是这个程序）。11-21 以后的经过和数字见[开发故事](docs/STORY.md)，决定见[决策日志](docs/DECISIONS.md)。

## 目录地图

| 目录 | 是什么 | 状态 |
| --- | --- | --- |
| [`fridge_vision/`](fridge_vision/) | 门口视觉：录制工具、离线分析（方向、认名）、评测脚本。`runs/` 是本机数据 | **主线** |
| [`orangepi_app/`](orangepi_app/) | **OrangePi 上实际运行的程序**（11-08 从板子同步）：网页、拍照识别、过线计数、GPIO 按钮；用 `deploy/opi.sh` 管理和同步 | **主线**（部署中） |
| [`smart_fridge_app/`](smart_fridge_app/) | 库存后端和网页（手机 / 小屏）：批次、门事件、拍照录入、备份；34 个测试 | **主线** |
| [`docs/`](docs/) | 架构、日程、决策、实验记录、报告。[目录](docs/README.md) | **主线** |
| [`eval/`](eval/) | 逐动作评测：切动作窗口、Mac 路线和板子路线出事件、按动作打分（和用哪条识别路线无关）。[说明](eval/README.md) | **主线**（11-15 新增） |
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
- **GitHub**：公开仓库 [tct33x7/fridge-vision](https://github.com/tct33x7/fridge-vision)（11-21 起公开），老师和同学加为协作者。
  改代码走分支 + Pull Request；改文档可以直接提交到 `main`；提交前先 `git pull`；提交信息写清改了什么、为什么。
- **密钥**：`archive/smart_fridge_demo/config/api_settings.json` 里有一把真实的 DeepSeek 密钥（不在 git 里），它曾随压缩包流转，建议去控制台轮换。
  大模型密钥只通过环境变量传入（`VLM_API_KEY`）。
- **隐私**：只在家里局域网用，不把端口开到公网；报告和展示只用没有人脸的帧。

## 协作与 AI 使用

| 谁 | 做了什么 |
| --- | --- |
| 项目发起人（TCT37） | 提出问题和方向，做每一次方向决定（见 [DECISIONS](docs/DECISIONS.md) 的"谁提出"一列）；架设相机，录制 E01 并记真值；和老师讨论定下 v4；11-21、11-22 把相机装到冰箱冷藏室上方并录像；11-22 提出改看"手伸进去之前和出来以后手里有没有东西"这个判法；定下成本要在最小模型这一档、11-24 的方案和 11-25 收尾 |
| 老师 | 11-08 架构讨论（机位、主机、界面）；板子上的 NPU 计数引擎、轻量追踪器 `ByteTrackLite`、排除类别名单和静止物品筛选（11-08 17:04–17:23 直接在板子上改，之后收进 `orangepi_app/`，见提交 `f367e52`、`0c2a502`、`0504b6d`、`8269e11`）；第 1 步的网页计数 demo `demos/yolo_web_counter`（据 11-08 进度总结；请老师确认）；硬件和大模型密钥 |
| 同学 | （待补充） |
| Claude（Anthropic 的 AI，经 Claude Code） | 除上面写明是老师写的代码以外，11-04 起这个仓库里的代码和文档文字（每个提交都带 `Co-Authored-By: Claude`；"同步板子"的那几个提交是 Claude 把老师的改动收进仓库），以及分析和建议。11-22 以后拿来当评判的也是 Claude 的模型（在对话里另开的、没看过答案的子代理） |
| 更早的材料 | 2026 年 7–8 月的旧项目，11-04 第一次提交时整体导入：研究素材 PPT（选题、背景、接线、任务列表）、`smart_fridge_demo`（基于老师的 demo）、`smart_fridge_app`、`camera_system`、扫码枪外壳（交接文档显示在 OpenAI Codex 环境里生成） |

文档里的"你"指项目发起人，"我"指 Claude。
