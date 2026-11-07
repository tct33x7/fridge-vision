# 交接文档（给下一个 chat / 下一个人）

更新：2026-11-07 19:40（周六晚）。仓库 `~/Projects/bx-project`，分支 main，工作树干净。

## 一句话

家用纯视觉冰箱记账：门口相机，开门自动记录放进去、拿出来的食材，不扫码不拍照，能用数字说明自己多准。
**真正目的是美国高中申请**：要有故事、有数据、经得起追问；把难点做好，不做全。可交付版本 11-22，打磨 11-29。

## 先读什么

1. `docs/PROPOSAL.md` 3.0：§0 改了什么、§2 对申请意味着什么、§4 评测方法、§6 新构思、§9 日程与"今天 / 明天结束时应该有"。
2. `docs/SCHEDULE.md`：今晚按小时、明天机构 8 小时按小时、之后按周。
3. `docs/DECISIONS.md`：谁定的、依据、验证状态；`docs/BLIND_REVIEW.md`：独立盲审原文（方法论来源）。
4. `README.md`：快速启动与 GitHub 协作约定。

## 现在的状态

- **方法**：先测量后设计。今晚录真实开关门 + 手记真值；明天用数字拍板架构（倾向：类别无关过线 + 大模型认名 + 人工纠错，关门后离线分析；YOLO 退为辅助）。
- **工具已就绪并提交**（全在 `fridge_vision/`，用 `.venv/bin/python`）：
  - `record_sessions.py` / `run_record.command`：开门录整段 + 过线关键帧 + 关门后终端问真值 → `runs/sessions/<id>/{clip.mp4, kf_*.jpg, session.json}`。
  - `analyze_sessions.py --contact`：`runs/sessions/summary.md`（触发误/超时、可见率、YOLO 召回、物品清单）+ 每会话 `contact.jpg`。
  - `name_keyframes.py`：关键帧批量交大模型认名，与真值比 → `naming.json`、`naming_summary.md`（含待人工分类的失败表）。要 `VLM_API_KEY`；`--dry-run` 预览，`--fake` 离线跑通。**真实 API 路径未验证**（没密钥）。
  - `process_session.py`：离线链路，运动段 → 光流方向 → 往返配对 → 认名（naming.json → YOLO → 无）→ 事件 → `events.json`、`events_summary.md`（动作检出 / 次数一致 / 方向一致 / 空开门有动作）；`--post-url http://127.0.0.1:8000` 上报后端。合成夹具全对，**真实手部画面未验证**；`--fridge-side left|right` 按画面里冰箱在哪边。
  - 对照组：`door_demo.py`（YOLO + ByteTrack + 实时过线）与 `run_fridge.command`。
- **后端** `smart_fridge_app/`：FastAPI + SQLite，`door_events` 接口（POST/GET/undo/PATCH）、按类别保质期；34 个测试；`run_backend.command` 启动，手机同一 Wi-Fi 打开 `http://<Mac IP>:8000`。
- **硬件**：Mac 是唯一主机。外接相机 UGREEN UVC 1080p 已到手并可用，**今晚在 OpenCV 里的编号是 0**（`SOURCE=0`），自带相机编号可能变成 1；换口可能变，不对就试 1、2。Moertek 2.4G 相机和 N100 已下单未到，N100 退出主线。
- **数据**：`runs/sessions/` 截至 19:40 仍为空。

## 今晚剩余（按顺序）

录制一律在 macOS 自带"终端"App 里跑（Claude 里的终端没有相机权限）。

1. 启动：`SOURCE=0 ~/Projects/bx-project/fridge_vision/run_record.command`。触发不跟就加 `DELTA=12`；再不行画面窗口按 `o` 手动开/关。
2. 录到 20:30，目标 15–25 次、底线 10 次：自然使用 + 空开门 3 次（两次回车）+ 只拿出 3 次 + 只放入 5 次（备注"练习"）+ 一次两样 2 次。按键在画面窗口，打字在终端窗口。
3. 统计：`cd ~/Projects/bx-project/fridge_vision && .venv/bin/python analyze_sessions.py --contact`，然后让助手读 `runs/sessions/summary.md` 分析，并跑 `process_session.py --dry-run` 看方向数字（先确认 `--fridge-side`）。
4. 日志 `docs/journal/2026-11-07.md`，三个问题各两三句，自己的话。
5. GitHub（可挪到明天）：`~/.local/bin/gh auth login --web`，然后 `cd ~/Projects/bx-project && ~/.local/bin/gh repo create fridge-vision --private --source=. --remote=origin --push`；设私有，老师同学加协作者。

明天之前的底线：≥ 10 个有真值的会话 + `summary.md` + 日志 5 句。

## 明天（11-08，机构 8 小时）

带 Mac、充电器、有线相机；录像在 Mac 里。开场问老师：多模态大模型 API 密钥（通义千问百炼或任何 OpenAI 兼容接口，设 `VLM_API_KEY` / `VLM_BASE_URL` / `VLM_MODEL`）；N100 到没到；有没有门磁 + ESP32/Arduino。逐小时安排见 `docs/SCHEDULE.md`：定架构 → 认名正确率与失败分类 → 离线链路跑通一次并入库 → 报告 1–3 节 → 录屏 → 下周计划。

## 铁律

- `runs/`（家里录像）、`.env`、`archive/smart_fridge_demo/config/api_settings.json`（含真实 DeepSeek 密钥，建议轮换）、数据库，永远不提交、不推送。`.gitignore` 已覆盖。
- iCloud 里和 `~/Downloads/HiddenadminAll/BX Project` 里的原件不动。
- 提交信息中文，说明"做了什么"；文档直接提交，代码改动以后走分支。
- 用户是中学生，所有文字中文；给出的每一步要可直接照做，并给替代方案；不替用户写日志和报告正文，只给结构。

## 已知问题（盲审指出、已核对，11-08 架构定了再改）

大模型名字未真正用作 `label_zh` 和商品名；改名后类别/保质期仍按原英文标签；`door_events.status` 缺 `confirmed/wrong`；证据图 RESTRICT 与清理冲突；"拿出"自动扣减应先隐藏；类别表要按家里清单重做；`door_demo.py` 的开门检测在厨房灯下会锁死（`record_sessions.py` 已有超时重置，`door_demo.py` 没有）。

## 在线资料

- 计划书在线版（与 `docs/PROPOSAL.md` 同步，可导出 Word/PDF）：https://claude.ai/artifact/5FRAXpgANS4yXgAqxmwiwy（Claude Docs，doc id `2267dbf5-dd37-4279-b08c-1c7de35ff548`，tab `6acd8b36-a9d0`，正文节点 `5accd51a-7c50`，rev 48）。
- GitHub CLI 装在 `~/.local/bin/gh`（Homebrew 目录属于别的账号，装不了）。

## 下一个 chat 开场 prompt（复制粘贴，补上方括号里的内容）

```text
我们在做 ~/Projects/bx-project（家用纯视觉冰箱记账，真正目的是美国高中申请：有故事、有数据、把难点做好不做全）。
先读 docs/HANDOFF.md，再读 docs/SCHEDULE.md 和 docs/PROPOSAL.md 的 §0、§4、§9，然后按 HANDOFF 的"今晚剩余"或"明天"继续，不要重新规划。
现在是 [时间]，我刚 [录完 N 次会话 / 在机构，老师给了密钥 / …]。
规则：所有文字中文；每一步给可直接照做的命令并附替代方案；录制在系统"终端"跑，外接相机 SOURCE=0；永远不提交 runs/、.env、密钥、数据库；不替我写日志和报告正文。
先告诉我接下来 30 分钟具体做什么。
```
