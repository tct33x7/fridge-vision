# YOLO11s 物体轨迹方向计数 Web Demo

基于 AI 视觉的物品进出计数工具：打开摄像头，YOLO11s 检测物体并用 ByteTrack 追踪轨迹；
在画面上拖拽一条"计数线"设定正方向，物品沿正方向穿过 +1，反方向 -1，侧边栏实时统计各类物品净数量与进出事件。

## 环境要求

- Python 3.10+
- macOS（Apple Silicon 走 MPS 加速）/ Linux / Windows 均可；Windows 需替换 `system_profiler` 设备名枚举（见下文"已知平台差异"）
- USB 摄像头（或 iPhone 连续互通相机 / 网络流）

## 安装

```bash
pip install -r requirements.txt
```

> torch 建议按目标平台官网命令安装（如 macOS: `pip install torch`；CUDA 环境按 pytorch.org 对应命令）。

## 运行

```bash
python app.py
```

浏览器打开：http://localhost:8020 （同局域网设备访问 http://<本机IP>:8020）

用摄像头要在 macOS 自带的"终端"里运行（其他终端可能没有相机权限）。常用启动参数（第 2 步新增）：

```bash
python app.py                                   # 默认：摄像头 0，第 2 步优化后的计数逻辑
python app.py --preset baseline                 # 第 1 步原版逻辑，做对比用
python app.py --source test_videos/jitter1.mp4 --line 0.5,0,0.5,1   # 播放录好的视频（默认循环），启动就画好线
python app.py --light gain                      # 软件拉平亮度（off / gain / clahe）
python app.py --lock-exposure --exposure -6     # 尝试关自动曝光（Linux/OrangePi 一般可以，macOS 大多不行）
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--source` | `0` | 摄像头编号、视频文件路径，或 http/rtsp 网络流 |
| `--preset` | `default` | 计数逻辑：`default`（第 2 步）/ `baseline`（第 1 步原版） |
| `--light` | `off` | 软件亮度处理：`off` / `gain` / `clahe`。合成视频上没有改善，默认关 |
| `--lock-exposure` / `--exposure` | 关 | 尝试锁定曝光；结果打印在终端，并显示在 `/api/state` 的 `exposure` 里 |
| `--line` | 无 | 启动时的计数线 `ax,ay,bx,by`（归一化 0~1） |
| `--no-loop` | 关 | 视频文件放完就停 |
| `--port` | 8020 | 端口 |

## 使用方法

1. **选摄像头**：点"扫描设备"→ 下拉选择（自动识别 iPhone 连续互通相机，高亮标注）→ 点"切换摄像头"；
   或将网络流地址（http/rtsp，如 Camo/EpocCam 等 App 提供的）填入"网络流"→ 点"使用网络流"
2. **画计数线**：在视频画面上按住鼠标从 A 拖到 B。**A→B 方向的左侧为"+1 进入"方向**（画面黄色箭头所示）；画反了点"翻转正方向"
3. **计数**：物品沿箭头方向穿过虚线 +1，反向 -1；侧边栏显示净计数、分物品统计、进出事件流水
4. **调参**：置信度滑杆过滤误检；"计数清零"重置统计

## 目录结构

```
├── app.py               # 后端：YOLO11s + ByteTrack 追踪 + MJPEG 推流（FastAPI）
├── counter.py           # 过线计数逻辑（app.py 和 replay.py 共用）：滞回、平滑、冷却、类别投票、丢失续接
├── replay.py            # 无界面重放：同一段视频比较不同计数参数的多计 / 漏计
├── tools/record.py      # 录测试视频（只录像，不识别）
├── tools/make_test_video.py  # 生成合成测试视频 + 真值
├── test_videos/         # 录像、真值、检测缓存（不进 git）
├── static/index.html    # 前端：视频画面、拖拽画线、统计栏
├── models/yolo11s.pt    # YOLO11s 预训练权重（COCO 80 类）
└── requirements.txt
```

## 关键配置

`app.py` 顶部：

| 参数 | 默认 | 说明 |
|---|---|---|
| `EXCLUDE_CLASSES` | `{"person"}` | 屏蔽的类别（人/手递送物品不计数），可加 "chair" 等 |
| `TRAIL_LEN` | 40 | 轨迹保留点数（画面上的运动轨迹长度）|
| `CAM_W/CAM_H` | 1280x720 | 请求的摄像头分辨率 |

计数逻辑在 `counter.py` 的 `PRESETS` 里（第 2 步，依据见 [E02 实验记录](../../docs/experiments/E02_light_jitter_20261108.md)）：

| 参数 | `baseline` | `default` | 说明 |
|---|---|---|---|
| `confirm_frames` | 0 | 90 | **确认时间**：过线后要在新的一边待满 90 帧（3 秒）或在那边消失，才算一次；没待满就回来了（拿出又放回、晃动）不计。网页上等待确认的物体名字后面带"?"。**实拍里消多计的主力** |
| `hysteresis_px` | 6 | 6 | 离线多少像素以内算"在线上" |
| `hysteresis_box` | 0 | 0.5 | 再加上 框宽（沿过线方向）× 这个比例；0.5 = 整个框过了线才算换边。**消多计的主力** |
| `relink_frames` / `relink_dist` | 0 / 0 | 20 / 2.0 | 目标丢失 20 帧内，附近（2 倍框对角线）出现的新编号接上老轨迹。**和滞回带配合，防漏计** |
| `class_vote` | 否 | 是 | 计数用整条轨迹的置信度加权投票类别，防 bottle / cup 来回跳 |
| `revote` | 否 | 是 | 计数之后继续投票，类别变了就改正已记下的事件（网页计数也跟着改） |
| `smooth_alpha` | 1.0 | 0.5 | 中心点平滑（1.0 = 不平滑） |
| `min_frames` | 0 | 3 | 轨迹至少看到几帧才允许计数 |
| `cooldown_frames` | 0 | 15 | 同一物体计数后多少帧内不再计数 |
| `track_timeout` | 60 | 60 | 多少帧没看到就删除轨迹 |
| `birth_zone` | 0 | 0 | 出现在线边时推断来向（试过，会多计，默认关） |

计数规则是"只看最后"：物品最后停在哪一边才算数，拿出又马上放回、晃动时来回过线都不算。
实拍效果（3 段桌面录像，11 次真实进出）：旧逻辑多计 12、漏计 5 → 新逻辑多计 0、漏计 2；剩下的漏计都是 YOLO 没检测到。详见 E02。

## 重放测试（第 2 步）

先录视频（只录像，不识别），再用 `replay.py` 让旧逻辑、新逻辑跑同一段视频，比较多计、漏计。

**1. 录视频**（在 macOS 自带的"终端"里）：

```bash
cd ~/Projects/bx-project/demos/yolo_web_counter
.venv/bin/python tools/record.py test_videos/jitter1.mp4     # 空格 开始/暂停，q 保存；相机打不开就加 --source 1
```

画面中间的竖线代表"冰箱门口"：右边 = 冰箱外，左边 = 冰箱里，从右往左过线 = 放入。每个动作之间，手完全移出画面停 2 秒，记下实际做了什么。

- **jitter1（抖动）**：瓶子放入；瓶子拿出；瓶子在线上晃 3 秒后放入；杯子伸过线一点马上缩回（不算）；苹果快速放入；杯子在左边远处晃（不算）。
- **light1（光线）**：关大灯只留小灯，瓶子放入再拿出；过线时开关一次大灯；逆光放入苹果。
- **mix1（复杂情况）**：一只手同时拿两样东西放入；过线时用另一只手挡住；放进去马上拿出来；在线附近换手。

**2. 写真值**：和视频同名的 `.truth.json`，例如 `test_videos/jitter1.truth.json`：

```json
{"line": [0.5, 0.0, 0.5, 1.0],
 "expected": {"bottle": {"in": 2, "out": 1}, "apple": {"in": 1, "out": 0}}}
```

`expected` 按"只看最后"写：拿出又马上放回、晃一晃最后放进去，只记最后的结果。
`line` 是 A(x,y)→B(x,y) 的归一化坐标，A→B 方向的左侧为 +1（进入），和网页上拖线一样。网页上画好线以后，`/api/state` 里的 `line` 可以直接抄过来。

**3. 重放**：

```bash
.venv/bin/python replay.py test_videos/jitter1.mp4                     # 旧逻辑 vs 新逻辑
.venv/bin/python replay.py test_videos/jitter1.mp4 --ablate            # 每项优化单独开 / 单独关
.venv/bin/python replay.py test_videos/light1.mp4 --light off,gain,clahe   # 比较亮度处理
.venv/bin/python replay.py test_videos/jitter1.mp4 --preset default --save-video test_videos/jitter1_boxes.mp4  # 导出带框视频，看错在哪
```

模拟"看不到冰箱里面"（门洞上方机位）：`--keep 0.4,0,1,1` 只保留画面 x 从 0.4 到 1 这一块，其余涂黑再检测（线在 0.5 时，里侧只剩 0.1 宽）。
`--try-rules` 会在新逻辑上试"压线消失也算 / 压线出现也算"两条规则（`edge_in` / `edge_out`，默认关，还在测试）。

第一次跑会做 YOLO 检测，结果缓存成 `*.dets.json`。之后换参数再跑只要几秒，而且所有方案用的是同一份检测结果。

没有录像时，可以先用合成视频：`.venv/bin/python tools/make_test_video.py test_videos/synthetic.mp4`，然后 `replay.py test_videos/synthetic.mp4 --segments`。

## API 摘要

- `GET /video`：MJPEG 实时视频流
- `GET /api/state`：当前统计/事件/状态（含 `line` 计数线坐标、`preset`、`light`、`exposure`）
- `GET /api/cameras`：枚举摄像头设备名
- `POST /api/camera`：`{"index": 0}` 或 `{"url": "http://..."}` 切换摄像头
- `POST /api/line`：`{"ax","ay","bx","by"}`（归一化坐标）设置计数线
- `POST /api/line/flip | /api/line/clear | /api/reset`：翻转方向 / 清除线 / 计数清零
- `POST /api/conf`：`{"value": 0.35}` 置信度阈值

## 已知平台差异

- `/api/cameras` 设备名枚举依赖 macOS `system_profiler`；Windows/Linux 下可去掉该调用，
  直接用索引 0-3 逐个尝试（macOS 上不要在运行中逐个试开设备，会与取帧线程抢占摄像头）
- Apple Silicon 自动使用 MPS 加速（约 15ms/帧）；无 MPS 时回退 CPU（约 41ms/帧，仍可实时）
- 模型查找顺序：包内 `models/yolo11s.pt` → 上级目录 `../yolo_pretrained/yolo11s.pt`

## 验证环境

macOS (Apple Silicon, MPS) / Python 3.13 / ultralytics 8.4.87 / torch 2.6.0，实测 USB 摄像头与 iPhone 连续互通相机均约 30 FPS。
