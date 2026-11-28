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
| `judge_door.py`（11-24 定下来的主线，见下面一节） | 关门以后：一次开门的录像 → 每半秒一帧的拼图 → 最小一档的视觉模型 → 每样东西各记一笔；说不清的不记，问人 | `<录像名>_judge/door_NN/` 里的拼图和 `result.json`、`summary.json` |

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

## 关门以后判断这一次开门（`judge_door.py`）

2026-11-24 定下来的主线（[决策日志](../docs/DECISIONS.md)）：一次开门的录像 → 每半秒取一帧 → 每 4 帧拼成一张图 → 交给最小一档的视觉模型（`claude-haiku-5-5`）
→ 回答里每样东西各写一项（放入 / 拿出 / 没变 / 判断不了）→ 说得清的记账；说不清的不记，问人一句。

先不联网看一遍：只切图、说一共几张、粗估多少钱。

```bash
.venv/bin/python judge_door.py runs/e03_D2_20261122/D2_enroll_main.mp4 --windows runs/e03_D2_20261122/D2_enroll_main.windows.json
```

拼图看过没问题，再加 `--send` 真的发给模型：

```bash
.venv/bin/python judge_door.py runs/e03_D2_20261122/D2_enroll_main.mp4 --windows runs/e03_D2_20261122/D2_enroll_main.windows.json --send
```

- **密钥**：`--send` 要一个 Anthropic 的 API 密钥，放在环境变量 `ANTHROPIC_API_KEY` 里（在要运行的那个终端里先 `export ANTHROPIC_API_KEY=你的密钥`）。
  密钥不要写进任何文件，不要贴到聊天里，也不要提交。没有密钥时程序只说"没有找到密钥"，什么都不发。
- **发出去的是什么**：整幅画面的拼图，可能拍到人。发之前程序会说发到哪台主机、用哪个模型。
- **输出**：`<录像名>_judge/door_NN/` 里是这次开门的拼图和 `result.json`（模型的回答、记了哪些账、要问哪些话、用了多少 token、多少钱），
  `summary.json` 是整段的合计。拼图只留在本机（`.gitignore` 里排除了 `*_judge/`）。
- **只判一次**：判过的开门再运行不会重发；要重判加 `--again`，旧的回答会改名留着。
- **记账的规则**（程序里的 `decide()`，一共这几条）：放入、拿出 → 记；拿了又放回 → 不记也不问；判断不了 → 不记，问这一样；
  回答读不懂、回答自己前后矛盾、模型拒绝回答、一次开门超过 80 秒 → 整次都不记，问一句。
- **它不管的事**：哪一段算一次开门（现在靠 `eval/propose_windows.py` 切的窗口文件，或者用 `--start` / `--end` 手写秒数）；
  东西叫什么名字（等登记做好，现在名字一律是空的，只有"什么样的东西、多了还是少了几件"）；问人的界面；库存。
- **提示词**：`prompts/judge_items_v4_D.txt`，是照位置 D（冷藏室上方）的画面写的；换了机位要另写一份，用 `--prompt` 指定。
- 加 `--events-json 文件名` 会另写一份 `eval/score_actions.py` 能打分的事件文件（要问人的那些不出事件）。

自检（不联网，模型是假的，回答是事先写好的）：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

自检查的是"程序有没有照规则办"，不是"模型判得准不准"。**截至 2026-11-25 项目收尾，这个程序一次真的请求都没有发过（没有密钥），准不准没有测。**
以前的数字（[E03](../docs/experiments/E03_position_20261112.md)）是对话里的子代理判出来的，用的是上一版回答格式，不能直接算到这个程序头上。

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
- **待写**：`import_clip.py`（把手机录像导入成会话，用于 E03 试机位）、门磁触发、环形缓冲、无窗口运行、关门后自动分析。
  （11-24：关门后的判断有了 `judge_door.py`，但还要人来运行、告诉它哪一段是一次开门；"开门自动录、关门自动判"还没有接起来。11-25 项目收尾，这一步没有做。）

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
