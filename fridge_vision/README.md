# fridge_vision · 冰箱门口纯视觉记账

摄像头看着冰箱门口，门一开就追踪手里的物品；物品穿过画面上的虚拟线，按方向判定"放入"或"拿出"，
保存关键帧并写事件。先在 Mac 上跑通，再搬到 Jetson Nano。

## 安装（Mac）

```bash
cd fridge_vision && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 接 Moertek 2.4G 摄像头

接收器插上 Mac 后先找编号（内置摄像头是 0，接收器一般是 1）：

```bash
.venv/bin/python list_cameras.py
```

然后把编号传给 `--source`：

```bash
.venv/bin/python door_demo.py --source 1 --trigger manual --model yolo11n.pt
```

## 跑 demo

笔记本摄像头，按 `o` 模拟开门/关门（桌面上没有冰箱灯，自动检测不好触发）：

```bash
.venv/bin/python door_demo.py --trigger manual
```

用 COCO 通用模型（瓶子、杯子、碗、香蕉、苹果、橙子都认，拿身边东西演示更方便；首次会下载 5 MB）：

```bash
.venv/bin/python door_demo.py --trigger manual --model yolo11n.pt
```

默认线是画面中间的水平线，**从下往上**过线算放入（摄像头装在冰箱顶部朝下看时，东西从门口进去就是这个方向）。
方向反了按 `l` 切换，或者加 `--in-dir down`。

过线后把关键帧发给大模型确认名字和数量（通义千问百炼的 OpenAI 兼容接口，其他兼容接口改 `VLM_BASE_URL`）：

```bash
VLM_API_KEY=sk-xxx .venv/bin/python door_demo.py --trigger manual --model yolo11n.pt --vlm
```

事件在 `runs/events.jsonl`，一行一条：

```json
{"time": "2026-11-04T20:15:03", "action": "in", "label": "banana", "label_zh": "香蕉", "confidence": 0.91, "track_id": 3, "keyframe": "runs/keyframes/20261104_201503_3_in_banana.jpg", "vlm": {"name": "香蕉", "category": "水果", "count": 3, "confidence": 0.95}}
```

## 不用摄像头的自检

```bash
.venv/bin/python make_synthetic_video.py runs/synthetic.mp4 && .venv/bin/python door_demo.py --source runs/synthetic.mp4 --trigger auto --headless --out runs/synthetic_events.jsonl
```

应该打印一次"开门"、一条"放入 香蕉"、一条"拿出 香蕉"、一次"关门"。

## 文件

| 文件 | 作用 |
| --- | --- |
| `door_demo.py` | 主脚本：开门检测、YOLO + ByteTrack 追踪、过线计数、关键帧、事件输出 |
| `vlm.py` | 可选的大模型命名，OpenAI 兼容接口 |
| `labels_zh.json` | 类别英文 → 中文（80 类食物模型 + COCO 里的食物/容器） |
| `make_synthetic_video.py` | 生成自检视频 |

## 搬到 Jetson Nano 4GB（老款）

老款 Nano 停在 JetPack 4.6（Ubuntu 18.04、Python 3.6），直接 `pip install ultralytics` 装不上。走 NVIDIA/Ultralytics 的
JetPack 4 容器：

```bash
sudo docker run -it --runtime nvidia --ipc=host --device /dev/video0 -v $PWD:/work ultralytics/ultralytics:latest-jetson-jetpack4
```

容器里把模型导成 TensorRT FP16 引擎再跑同一个脚本：

```bash
yolo export model=yolo11n.pt format=engine half=True imgsz=416 && python door_demo.py --model yolo11n.engine --imgsz 416 --headless
```

老款 Nano 上 416 分辨率的 n 模型大约十几帧每秒，追踪过线够用；不够就降到 320。
