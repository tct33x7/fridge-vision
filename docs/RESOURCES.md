# 纯视觉冰箱方案 · 所需资料清单

对应 [PLAN.md](../PLAN.md) v2（门口摄像头 + N100 迷你主机 + YOLO 追踪过线，自动记账）。
整理日期 2026-11-06。✅ 已有　🛒 要买　✍️ 要做　❓ 等你确认

## 1. 硬件

| 物品 | 规格要点 | 状态 |
| --- | --- | --- |
| N100 / N150 迷你主机 | 8 GB 内存、256 GB SSD、内置 Wi-Fi、≥ 2 个 USB-A；装 Ubuntu 24.04。11-06 定为第三步主机，替代原定老款 Jetson Nano | ✅ 11-06 已下单 |
| 摄像头 | **已选 Moertek 2.4G 无线款**（相机 → 2.4G → USB 接收器，接收器当 UVC 摄像头用，室内 20 m）。下单前核对：接收器免驱/UVC/支持 Mac 与 Linux；视角 ≥ 100°；延迟 < 300 ms；相机供电方式（电池还是电源线）；标称分辨率与帧率 | ✅ 11-06 已下单 |
| 相机供电 | 无线只省视频线，相机仍要供电：优先选能接 USB 电源线的款，避免每天充电 | ❓ 看商品页 |
| 摄像头支架 | 固定在冰箱顶部前沿朝下看门口，磁吸或 3M 胶；可 3D 打印 | ✍️ 阶段 3 |
| 磁簧门磁开关（可选） | 常开型 + USB 串口小板（N100 没有 GPIO），做开门兜底 | 🛒 可选 |
| 开发机 | 这台 Apple Silicon Mac，FaceTime 摄像头 | ✅ |

## 2. 软件与模型

| 项目 | 说明 | 状态 |
| --- | --- | --- |
| `fridge_vision/door_demo.py` | 开门检测、YOLO + ByteTrack、过线计数、关键帧、事件输出 | ✅ Mac 自检通过 |
| Mac 环境 | `fridge_vision/.venv`：ultralytics 8.4、torch（MPS）、OpenCV、onnxruntime | ✅ |
| 模型权重 | `fridge_vision/models/food_best.onnx`（80 类食物，自训）；`yolo11n.pt`（COCO，自动下载） | ✅ |
| 中文类别表 | `fridge_vision/labels_zh.json`，94 条 | ✅ |
| 库存后端 | `smart_fridge_app`（FastAPI + SQLite，23 个测试通过）；门事件接口尚未加 | ✍️ 阶段 2 |
| N100 系统与环境 | Ubuntu 24.04 + 和 Mac 同一份 `requirements.txt`；两个 systemd 单元 | ✍️ 阶段 3 |
| 微调后的权重 | 用门口关键帧训练的 YOLO11n | ✍️ 阶段 4 |
| 大模型命名（可选） | `fridge_vision/vlm.py`，OpenAI 兼容接口 | ✅ 代码就绪，缺 key |

## 3. 数据

| 数据 | 用途 | 状态 |
| --- | --- | --- |
| 合成自检视频 | 回归测试过线逻辑 | ✅ `make_synthetic_video.py` |
| 真实开门视频 10 段 | Mac 阶段验收、以后回归 | ✍️ 阶段 1.2 用摄像头录 |
| 家里常买食材清单 | 决定类别表、微调标签、默认保质期 | ❓ 你列一份，20–40 种 |
| 类别默认保质期表 | 纯视觉读不到日期，入库按类别算到期日 | ✍️ 阶段 2.3 |
| 门口关键帧数据集 200+ 张 | 微调 YOLO | ✍️ 阶段 3–4 自动攒 |
| 标注工具 | Roboflow（在线、免费档够用）或 Label Studio（本地） | 🛒 二选一 |

## 4. 账号与密钥

| 项目 | 用途 | 状态 |
| --- | --- | --- |
| 通义千问百炼 API key | `--vlm` 关键帧认名、数数 | ❓ 可选，要用就去开 |
| DeepSeek API key | 食谱文本生成（现有 key 随压缩包流转过，建议轮换） | ✅ 有，建议轮换 |
| GitHub | 仓库备份（本机无 `gh`，用 HTTPS + token） | ❓ 要不要 |

## 5. 参考资料

| 资料 | 为什么需要 |
| --- | --- |
| Ultralytics 文档：CPU 推理与 OpenVINO 导出 | N100 上帧率不够时的提速路径 |
| Ultralytics 文档：Track 模式 / ByteTrack 参数 | 调 `track_buffer`、`match_thresh` 解决漏跟 |
| 仓库内：`PLAN.md`、`fridge_vision/README.md`、`smart_fridge_app/ARCHITECTURE.md` | 计划、demo 用法、后端数据模型 |
| 不再需要：Orange Pi 手册、扫码枪 V1–V3、条码/小票 OCR 文档 | 方案已变，留档即可 |

## 6. 仓库里本方案真正用到的部分

```text
用到      fridge_vision/                      门口追踪 demo（核心）
用到      smart_fridge_app/                   库存后端 + 手机网页
用到      fridge_vision/models/             模型权重和类别表
用到      archive/smart_fridge_demo/app/services/yolo_food_detector.py   纯 onnxruntime 推理参考
搁置      archive/camera_system/              按钮拍照服务，被 door_demo 取代
搁置      archive/smart_fridge_demo/ 其余     条码、小票、OCR、PWA、Docker
归档      archive/hardware/                   扫码枪壳体
```

## 7. 还需要你给的四个答案

1. ~~Jetson 电源~~ 已改选 N100 迷你主机，内置 Wi-Fi，无此问题。
2. ~~N100 和摄像头下单日期~~ 11-06 已下单，到货日待定。
3. ~~摄像头是 USB 还是 CSI 排线？~~ 已选 Moertek 2.4G，到货后用 `fridge_vision/list_cameras.py` 找编号。
4. 家里常买的 20–40 种食材清单。
