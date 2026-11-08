# 交接文档（给下一个 chat / 下一个人）

更新：2026-11-08 中午（周日，你在机构）。仓库 `~/Projects/bx-project`，分支 `main`；GitHub 私有仓库 [tct33x7/fridge-vision](https://github.com/tct33x7/fridge-vision)。

## 一句话

冰箱门口自动记账：门洞上方的相机拍下手往里放、往外拿的东西，关门后判断"放入 / 拿出 · 什么 · 几件"，更新库存，并且能用数字说明有多准。
**真正目的是美国高中申请**：要有故事、有数据、经得起追问；把难点做好，不做全。可交付版本 11-22，打磨到 11-29。

## 先读什么

1. [docs/README.md](README.md)：文档目录。
2. [docs/ARCHITECTURE.md](ARCHITECTURE.md)：**v4 架构**（11-08），尤其 §3 机位的七个问题、§10 待定。
3. [docs/SCHEDULE.md](SCHEDULE.md)：今天下午和之后的安排。
4. [docs/DECISIONS.md](DECISIONS.md) 的 11-08 各行；[docs/experiments/E01_front_20261107.md](experiments/E01_front_20261107.md)。
5. [docs/PROPOSAL.md](PROPOSAL.md) 3.0 的 §2（对申请意味着什么）、§4（评测方法）：方法论仍然有效。

## 现在的状态

- **方向**：v4，11-08 你和老师定的。相机改装到门洞上方，只拍手和手里的东西；库存由用户初始化（手动输入或拍照），之后靠进出事件增减；主机 OrangePi 4 Pro，Mac 继续做开发机；界面在门边小屏和手机之间待定（Claude 建议同一套网页、手机先）。
- **数据**：E01 在 `fridge_vision/runs/e01_front_20261107/`（16 个会话，真值 11-07 21:35 已修正，原始输入在 `truth_original`）。
  **待你做**：`人工可见性.md`（27 行，新增"放在哪"一列）、11-07 日志（还是模板）。
- **工具**（`fridge_vision/`，用 `.venv/bin/python`）：`record_sessions.py`、`analyze_sessions.py`、`name_keyframes.py`（真实 API 没跑过，缺密钥）、`process_session.py`。
  **已知问题**：不支持横线方向（门洞上方机位必需）；"时长"含填真值的时间；YOLO 检测只存 400 条。见 [fridge_vision/README.md](../fridge_vision/README.md)。
- **后端** `smart_fridge_app/`：34 个测试通过（11-08 复核），已有门事件接口和拍照录入会话（可用于初始化库存）。
- **硬件**：UGREEN 有线相机在 Mac 上编号 0；OrangePi 4 Pro 已有（还没装机）；Moertek 2.4G 相机已下单；N100 退出主线；门磁待定。
- **GitHub**：推送靠 macOS 钥匙串里 `tct33x7` 账号的凭据，`git push` 直接可用。`gh` 命令行**没登录**：登录时报"账号 API 限额已用完"（user ID 326270814），原因不明；你另一个项目在用一把旧令牌。加协作者用网页（Settings → Collaborators）。
  公开接口查不到 `tct33x7` 这个账号，可能被 GitHub 标记了：加协作者前在无痕窗口打开 github.com/tct33x7 确认。

## 下一步

- **你**：见 [SCHEDULE 11-08 下午](SCHEDULE.md)：补日志、问老师四件事、做"假门洞"练识别、OrangePi 装机前几步、E01 人工表。
- **Claude（代码，走分支 + PR）**，按顺序：
  1. 横线方向：`record_sessions.py` 的 `--axis y` 重心；`process_session.py` 加 `--axis`。
  2. `import_clip.py`：手机录像 → 会话文件夹，给 E02 试机位用。
  3. 按"腿"判断手里有无和是什么（每腿 2–4 帧问大模型，带家庭词表）。
  4. 门磁触发、无窗口运行、环形缓冲、关门后自动分析。
  5. 后端：事件状态 `confirmed / wrong`、按大模型名字定类别和保质期、初始化向导、"刚才的变化"页。

## 铁律

- `fridge_vision/runs/`（家里录像）、`.env`、密钥、数据库，永远不提交、不推送。`.gitignore` 已覆盖。
- `archive/smart_fridge_demo/config/api_settings.json` 有真实 DeepSeek 密钥（不在 git 里），建议轮换。
- iCloud 和 `~/Downloads/HiddenadminAll/BX Project` 里的原件不动。
- 提交信息用中文，写清做了什么。改代码走分支 + PR，改文档可以直接提交到 `main`。
- 用户是中学生，所有文字用中文；每一步给可以直接照做的命令，并附替代方案；**不替用户写日志和报告正文**，只给结构。
- 录制在 macOS 自带的"终端"里跑（Claude 里的终端没有相机权限），外接相机 `SOURCE=0`。

## 在线资料

- 计划书在线版（Claude Docs，停在 3.0，**没有同步 v4**）：https://claude.ai/artifact/5FRAXpgANS4yXgAqxmwiwy（doc id `2267dbf5-dd37-4279-b08c-1c7de35ff548`）。
- GitHub CLI 装在 `~/.local/bin/gh`（Homebrew 目录属于别的账号，装不了）。

## 下一个 chat 开场 prompt（复制粘贴，补上方括号里的内容）

```text
我们在做 ~/Projects/bx-project（冰箱门口自动记账，真正目的是美国高中申请：有故事、有数据、把难点做好不做全）。
先读 docs/HANDOFF.md，再读 docs/ARCHITECTURE.md 和 docs/SCHEDULE.md，然后按 HANDOFF 的"下一步"继续，不要重新规划。
现在是 [时间]，我刚 [做完了什么 / 老师说了什么 / 拿到了什么]。
规则：所有文字中文；每一步给可直接照做的命令并附替代方案；录制在系统"终端"跑，外接相机 SOURCE=0；永远不提交 runs/、.env、密钥、数据库；不替我写日志和报告正文。
先告诉我接下来 30 分钟具体做什么。
```
