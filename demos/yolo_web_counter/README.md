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

## 使用方法

1. **选摄像头**：点"扫描设备"→ 下拉选择（自动识别 iPhone 连续互通相机，高亮标注）→ 点"切换摄像头"；
   或将网络流地址（http/rtsp，如 Camo/EpocCam 等 App 提供的）填入"网络流"→ 点"使用网络流"
2. **画计数线**：在视频画面上按住鼠标从 A 拖到 B。**A→B 方向的左侧为"+1 进入"方向**（画面黄色箭头所示）；画反了点"翻转正方向"
3. **计数**：物品沿箭头方向穿过虚线 +1，反向 -1；侧边栏显示净计数、分物品统计、进出事件流水
4. **调参**：置信度滑杆过滤误检；"计数清零"重置统计

## 目录结构

```
├── app.py               # 后端：YOLO11s + ByteTrack 追踪 + 方向线计数 + MJPEG 推流（FastAPI）
├── static/index.html    # 前端：视频画面、拖拽画线、统计栏
├── models/yolo11s.pt    # YOLO11s 预训练权重（COCO 80 类）
└── requirements.txt
```

## 关键配置（app.py 顶部）

| 参数 | 默认 | 说明 |
|---|---|---|
| `EXCLUDE_CLASSES` | `{"person"}` | 屏蔽的类别（人/手递送物品不计数），可加 "chair" 等 |
| `TRAIL_LEN` | 40 | 轨迹保留点数（画面上的运动轨迹长度）|
| `HYSTERESIS` | 6.0 px | 线附近抖动抑制，防重复计数 |
| `TRACK_TIMEOUT` | 60 帧 | 目标消失多久后删除轨迹 |
| `CAM_W/CAM_H` | 1280x720 | 请求的摄像头分辨率 |

## API 摘要

- `GET /video`：MJPEG 实时视频流
- `GET /api/state`：当前统计/事件/状态
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
