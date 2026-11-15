# eval/：逐动作评测

**一句话**：录像里每一个真实动作（放入、拿出、空开门）单独打分，并且和用哪条识别路线无关。
Mac 上的 YOLO11s、板子的计数管线、以后的其他路线，只要输出同一种"事件文件"，就能放进同一张表里比较。

为什么要逐动作：按"总数"比（`replay.py` 对真实录像就是这样）会让多计和漏计互相抵消；
长尾物品（YOLO 不认识的东西）根本不在 `expected` 里，漏了也看不出来。

## 用到的文件

| 文件 | 做什么 |
| --- | --- |
| `timebase.py` | 第 i 帧是第几秒。优先用新版录制工具记的 `<录像名>.frames.json`，没有就按文件头（会提示） |
| `propose_windows.py` | 按"画面在动"把长录像切成候选窗口，每个窗口出一张缩略图拼图（可选画检测框，或什么都不画给盲标用） |
| `events_mac.py` | Mac 路线：YOLO11s + ultralytics ByteTrack + `demos/yolo_web_counter/counter.py`，按动作窗口计数，输出事件文件 |
| `../orangepi_app/tools/simulate_counter.py --events-json` | 板子路线：板子上同一份计数代码（含画面判断开门和待机）。`--engine cpu-lite` 在 Mac 上用板子的追踪器（代理），`--engine npu` 只能在板子上跑 |
| `score_actions.py` | 真值 + 一个或多个事件文件 → 逐动作表和分组汇总（markdown） |
| `sample_frames.py` | 按时间随机抽 40 帧拼成大图，数"有几帧拍到脸"这类是非题用（E03 选机位） |
| `make_action_list.py` | E04 抽签：按分组配额随机排动作顺序，出打印版动作清单和真值模板 |
| `wilson.py` | **还没有，由项目发起人自己写**：函数 `wilson(k, n)`，返回 95% 区间 `(下限, 上限)`（0–1 之间）。放在这里后，打分表自动带区间 |
| `tests/` | 打分规则、时间基准的单元测试；和 `replay.py` 的对照检查 |

用 `demos/yolo_web_counter/.venv/bin/python` 运行（`simulate_counter.py` 用 `fridge_vision/.venv/bin/python`，和以前一样）。

## 录完一段以后怎么做（例：E03 机位 A）

下面的命令都在仓库根目录运行；`R=fridge_vision/runs/e03_position_20261112`。

```bash
PY=demos/yolo_web_counter/.venv/bin/python; R=fridge_vision/runs/e03_position_20261112
```

**1. 切窗口、看拼图**（大约 1 分钟）

```bash
$PY eval/propose_windows.py $R/A_201500.mp4
open $R/A_201500_windows/
```

每个窗口一张图，图上有时间。对照动作清单，记下"哪个窗口是第几个动作"；秒表、筷子、做错重来这些不算的窗口也记下。
**每个窗口都要写进真值**（是动作就写到那个动作的 `window`，不算的写进 `ignore_windows`），漏了打分会停下来提醒，
因为没写的窗口里的事件会被算到前一个动作头上。
切得不对时可以加 `--recompute` 并调 `--thresh`（默认 0.02，越大越不敏感）和 `--gap`（默认 2.5 秒），或者干脆在真值里手写时间。
窗口文件已经有了，再运行 `propose_windows.py`（比如加 `--boxes`、`--plain` 出另一种拼图）不会重新切，窗口编号不变。
**手写时间用拼图上、窗口文件里的时间**（按 `.frames.json` 算的真实秒数），不要用播放器上显示的时间，两者在帧率变化时会对不上。

**2. 补真值**（`$R/A.truth.json`，每个动作加几项）

```json
{
 "video": "A_201500.mp4",
 "line": [1, 0.42, 0, 0.42],
 "ignore_windows": [1, 2],
 "actions": [
  {"n": 1, "item": "瓶 1", "cls": "bottle", "delta": 1, "where": "里面搁板·最上层", "window": 3,
   "visible": "✓", "boxed": "✓"},
  {"n": 5, "item": "生（YOLO 不认识）", "cls": null, "delta": 1, "where": "里面搁板·最下层", "window": 7,
   "visible": "✓", "boxed": "✗"}
 ]
}
```

| 字段 | 意思 |
| --- | --- |
| `video` | 录像文件名（找 `.windows.json` 用） |
| `line` | 计数线 `[ax, ay, bx, by]`，归一化坐标；**A→B 方向的左侧是 +1（放入）**。画面上边对着冰箱里面、线是横线时，写成从右到左 `[1, y, 0, y]` |
| `actions[].window` | 这个动作对应的窗口编号；跨两个窗口写 `[3, 4]`。一个窗口只能属于一个动作。也可以不用窗口，直接写 `"start_s"` / `"end_s"`（秒，用拼图上的时间） |
| `actions[].delta` | +1 放入、−1 拿出、0 = 不该计数（空开门、只碰到线、拿出又放回）；一次拿两样写 +2 / −2 |
| `actions[].cls` | 真值类别（COCO 名）；YOLO 不认识的东西写 `null`，这一项只按方向打分。写成列表表示"同一样东西叫哪个都算对"，如 `["bottle", "cup"]` |
| `actions[].cls_multi` | 一次拿几样**不同**的东西时用（这时 `cls` 写 `null`），如 `["apple", "banana"]`：事件的类别要正好是这几样 |
| `actions[].where` | 含"门格"→ 门格组；含"搁板"→ 搁板组；否则"其他位置" |
| `actions[].tags` / `group` | 额外分组，例如 `["快速"]`；抽签工具会写上 `group`（抽签时的分组），汇总里显示为"抽签分组：…" |
| `actions[].visible` | ① 人眼看录像能不能认出手里是什么：`✓` / `△` / `✗` / `—`（拍不到）。只有 `✓`（也认 `√`、`✔`、`y`、`是`）算是；空着不进分母 |
| `actions[].boxed` | ② 东西过线时检测器有没有在它上面画出框（任意类别都算）：`✓` / `✗`。看第 3 步带框的拼图来勾；空着不进分母 |
| `ignore` / `ignore_windows` | 不算的时间段 `[[开始, 结束], …]` / 不算的窗口编号 |

**3. 跑路线、出事件文件**

```bash
# Mac 路线（检测结果会缓存，第二次很快）
$PY eval/events_mac.py $R/A_201500.mp4 --truth $R/A.truth.json
# 同一份检测，换成板子上的排除名单（61 类）
$PY eval/events_mac.py $R/A_201500.mp4 --truth $R/A.truth.json --exclude board
# 板子代码的代理（Mac 上；检测器不同，追踪器和计数代码和板子一样）
fridge_vision/.venv/bin/python orangepi_app/tools/simulate_counter.py $R/A_201500.mp4 --engine cpu-lite \
    --model demos/yolo_web_counter/models/yolo11s.pt --truth $R/A.truth.json \
    --events-json $R/A_201500.board-lite.events.json
# 带检测框的拼图（勾 ② 用；沿用第 1 步的窗口，图在 A_201500_windows_boxes/）
$PY eval/propose_windows.py $R/A_201500.mp4 --boxes $R/A_201500.light-off.conf-0.35.img-640.dets.json
```

**4. 打分**

```bash
$PY eval/score_actions.py $R/A.truth.json $R/A_201500.mac-default-pc.events.json \
    $R/A_201500.board-lite.events.json --md $R/A.score.md
open $R/A.score.md
```

表里每个分组一行：① 人眼能认出、② 检测器框到、③ 计数正确、方向对、净数对、类别也对，都写成 k/n。
有 `eval/wilson.py` 时自动加 95% 区间（`wilson.py` 出错或返回的不是 0–1 之间的数时，表里会写明，照样出表）。

**几段合起来**（E04 分三段录）：每段打分时加 `--json`，再合并：

```bash
$PY eval/pool_scores.py $R/s1.score.json $R/s2.score.json $R/s3.score.json --md $R/E04.score.md
```

## 打分规则

这些规则在看到 E03 / E04 数据之前写定，`tests/test_score_actions.py` 逐条检查。要改规则，先在实验记录里写清为什么改，再重新跑所有录像。

- **事件时间** = 物品过线的那一刻（两条路线都是），不是事件被确认的那一刻（确认要再等约 3 秒）。
- **事件归属**：动作按开始时间排序。相邻两个动作之间，以"前一个的结束"和"后一个的开始"的**中点**为界；
  第一个动作从它开始前 2 秒算起，最后一个动作管到录像结束。第一个动作之前的事件算"窗口外的误计"；落在 `ignore` 时间段里的事件不算。
  Mac 路线按同样的分段计数（每段一个新计数器），所以两边一致。
- **有物品的动作**（真值 `delta = ±n`）：
  - ③ **计数正确** = 方向对的事件正好 n 个，并且没有方向反的事件
  - **方向对** = 至少 1 个方向对的事件，并且没有方向反的事件
  - **净数对** = 所有事件加起来正好等于 delta（"只看最后"的口径：+1 −1 +1 也算对）
  - **类别也对** = 计数正确时，这些事件的类别都等于真值类别。真值类别为 `null`（YOLO 不认识的东西），或计数不正确时，不算这一项
  - 漏计 = n − 方向对的事件数（不小于 0）；多计 = 事件总数 − 算作正确的事件数
- **不该计数的动作**（`delta = 0`：空开门、只碰到线、拿出又放回）：没有任何事件才算对。
- **① ②** 来自人工勾选，分母是勾了的动作数（没勾的不算进分母）。
- **会让结果悄悄出错的输入一律报错停下**（`tests/test_score_actions.py` 的 `TestValidation`）：两个动作时间重叠；
  一个窗口给了两个动作；`ignore` 时间段压到动作上；窗口文件里有没被用到的窗口；真值、窗口文件、事件文件不是同一段录像；
  时间基准（`.frames.json` / 文件头）、帧数或计数线对不上；动作时间超出录像。

## 三条路线有什么不同（写报告时要标清楚每个数字来自哪条）

| 路线 | 检测 | 追踪 | 计数代码 | 开门检测 | 能在哪跑 |
| --- | --- | --- | --- | --- | --- |
| `mac-yolo11s-*`（`events_mac.py`） | YOLO11s @640（Mac） | ultralytics ByteTrack | `demos/.../counter.py` | **假设完美**：第一个动作前 2 秒才开始计数，每个动作一个新计数器，不会被人走过唤醒 | Mac |
| `board-sim-cpu` | 同上 @320 | ultralytics ByteTrack | 板子的 `line_counter.py` + `counter_service.py` | 板子的画面判断开门和待机 | Mac / 板子 |
| `board-sim-cpu-lite` | 同上 @320 | **板子的 ByteTrackLite** | 同上 | 同上 | Mac / 板子（代理） |
| `board-sim-npu` | **板子 NPU YOLOv5s** | 板子的 ByteTrackLite | 同上 | 同上 | **只有板子**：这是部署版本的真实数字 |

- 计数规则里按"帧"写的参数是在 30 帧/秒上定的；Mac 路线和板子一样按真实帧率等比例换算，Mac 路线每个动作那一段用那一段自己的帧率。
- 板子路线按**时间**抽帧到 `--fps`（默认 15，和板子摄像头一样）；录像本身慢于这个帧率时按录像的帧率，并提示。
- `cpu-lite` 的检测器参数尽量和板子一样（NMS 的 IoU 0.45、低分框门槛），但模型不同。
- `events_mac.py` 每个窗口另外记下"有没有任何轨迹（任意类别）从线的一边到了另一边"（`crossing_tracks_any_class`），
  可以当 ② 的自动参考，但它只看有追踪编号的框，追踪编号在线上断了（正好是遮挡的时候）就看不到，以人工勾选为准。

## 自检

```bash
BX_TEST_VIDEOS=demos/yolo_web_counter/test_videos $PY -m unittest discover -s eval/tests -v
```

- `test_score_actions.py`：上面每条打分规则；会报错停下的输入；人工勾选的写法；`wilson.py` 出错时；几段合并。
- `test_timebase.py`：15 帧/秒的录像配 30 帧/秒的文件头时按真实时间算；暂停；帧数差 1–2 帧和差得更多；`.frames.json` 优先于 `--fps`；一段一段的帧率。
- `test_make_action_list.py`：抽签配额、不会拿出不在冰箱里的东西、同一个种子结果一样、两样不同的东西用 `cls_multi`。
- `test_parity_with_replay.py`：整段一个窗口时，`events_mac.py` 的计数事件和 `replay.py` 完全一样（jitter1、mix1、synthetic）。
  需要本机的测试录像和检测缓存，没有就跳过。

## 已知局限

- Mac 路线和 `cpu-lite` 用的检测器不是板子上的 NPU YOLOv5s；部署版本的数字只能在板子上用 `--engine npu` 得到。
- 窗口切分只看"画面在动"，人走过、开关灯也会切出窗口；它只是帮忙找时间，最后以人对照拼图填的为准。
- ② "框到"是人看拼图判断的，判断标准要在勾之前写下来（例如：框和手里的东西重叠一半以上才算）。
