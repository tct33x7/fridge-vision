# 项目资料盘点 · 新思路（门口纯视觉自动记账）要用哪些

盘点日期 2026-11-06。结论四档：**核心**（新思路的主体）、**复用**（直接拿来用或搬几个文件）、**搁置**（不动，留着参考）、
**归档**（和新思路无关，只为留档）。对应三步走计划见 [PLAN.md](../PLAN.md)。

## 一眼看结论

```text
核心   fridge_vision/                        门口追踪 demo：开门检测、YOLO+ByteTrack、过线、关键帧、VLM
核心   fridge_vision/models/                 80 类食物模型权重 + 类别表（正本）
核心   smart_fridge_app/                     库存后端 + 手机网页：批次、流水、首页、备份、23 个测试
复用   archive/smart_fridge_demo/app/services/yolo_food_detector.py   纯 onnxruntime 推理（不想装 ultralytics 时用）
复用   archive/smart_fridge_demo/app/services/food_classifier.py      80 类英文→中文别名表（已抽到 labels_zh.json）
复用   archive/smart_fridge_demo/app/services/deepseek_client.py      文本食谱生成（第二步之后可选）
搁置   archive/camera_system/                按钮拍照 + Tesseract OCR 服务，被 door_demo 取代
搁置   archive/smart_fridge_demo/ 其余       条码、小票 OCR、包装日期 OCR、PWA 前端、Docker
归档   archive/hardware/                     扫码枪壳体 V1–V3（32 MB STL/STEP）
归档   archive/reference/                    Orange Pi 手册、研究 PPT、截图
归档   archive/yolov11训练-onnx/             训练产物，权重是指向 fridge_vision/models 的符号链接
```

## fridge_vision/ —— 核心

| 文件 | 作用 | 新思路里的角色 |
| --- | --- | --- |
| `door_demo.py` | 开门检测（亮度跳变 / 手动 / 常开）、`model.track` + ByteTrack、虚拟线过线判放入拿出、关键帧裁图、`events.jsonl`、网络流重连 | 第一、二步的主程序；第三步原样搬到 N100 |
| `vlm.py` | OpenAI 兼容多模态接口，把关键帧发给大模型要 `{name, category, count, confidence}` | 可选，认名兜底 |
| `labels_zh.json` | 94 条英文类别 → 中文 | 事件中文名；以后微调后的类别要同步加 |
| `list_cameras.py` | 列出可用摄像头编号 | 接收器插上后找 `--source` |
| `make_synthetic_video.py` | 合成"开门 → 放入香蕉 → 拿出香蕉 → 关门"视频 | 回归测试，改过线逻辑后必跑 |
| `requirements.txt` | ultralytics、opencv、httpx、onnxruntime | Mac 和 N100 共用 |

缺的：把事件 POST 到后端的 `--post-url`；记录"一次开关门"为一个会话的汇总事件；参数文件化（线位置、阈值）。

## smart_fridge_app/ —— 核心

| 位置 | 作用 | 新思路里的角色 |
| --- | --- | --- |
| `app/repositories/inventory.py` | 1219 行：`create_lot`（商品去重 + 批次 + `receive` 流水）、`consume`、`discard`、`list_lots`、`events`、`dashboard`、`insights`、媒体索引、备份用快照 | **直接复用**。放入 = `create_lot(source="camera")`；拿出 = 找该商品最早到期的活动批次 `consume()` |
| `app/database/migrations/001–003.sql` | 商品、批次、流水、媒体、会话、餐食、营养表 | 直接复用；新加一张 `door_events` 表（时间、动作、标签、置信度、关键帧 media_id、关联批次、是否已撤销） |
| `app/api/inventory.py`、`dashboard.py`、`profile.py` | 库存增删查、首页聚合、健康、个人设置 | 直接复用 |
| `app/api/media.py`、`services/media_store.py` | 应用自有 JPEG 原子写入、SHA-256、按 capture ID 出图 | 直接复用：关键帧当 `media_assets(source='camera')` 存进去做证据 |
| `app/api/intake.py`、`api/camera.py`、`services/camera_gateway.py`、`services/capture_library.py` | 拍照会话、8001 摄像头代理、MJPEG | **搁置**：新思路没有"拍照会话"；路由先留着不删，首页入口隐藏 |
| `app/tasks/backup.py` | 数据库 + 引用图片一致性备份包 | 直接复用；第三步从 Mac 迁 N100 就靠它 |
| `frontend/index.html`、`app.js`、`styles.css` | 首页按真实数据显隐、库存页、图库、设置、拍照对话框 | 复用骨架；新增"刚才的变化"卡片 + 撤销；拍照对话框和相机预览隐藏 |
| `tests/`（23 个） | 迁移、库存流水、媒体契约、会话、餐食、离线相机 | 保留做回归；新增门事件测试 |
| `deploy/smart-fridge.service.example`、`install.sh`、`start.sh` | systemd、安装、启动 | 第三步 N100 上直接用，改路径 |
| `docs/RESEARCH_AND_DECISIONS.md`、`ARCHITECTURE.md` | 为什么这样设计、数据所有权、备份边界 | 继续有效，只有"摄像头 8001"那部分过时 |

缺的：`door_events` 表与接口、撤销逻辑、按类别默认保质期表（**全仓库没有现成的**，要新写）、首页卡片。

## archive/smart_fridge_demo/ —— 大部分搁置，几个文件复用

| 位置 | 作用 | 结论 |
| --- | --- | --- |
| `yolo/food_best.onnx`、`classes.txt` | 自训 80 类 YOLO11 权重（10.7 MB）和类别表 | **复用**：door_demo 默认模型 |
| `yolo/food_best.previous.onnx`、`test food.jpg` | 旧权重、测试图 | 留着，不入库（`.gitignore` 已排除旧权重） |
| `app/services/yolo_food_detector.py` | letterbox、onnxruntime CPU 推理、NMS，不依赖 ultralytics | **复用**：不想装 ultralytics 时的轻量推理路径 |
| `app/services/food_classifier.py` | 80 类英文→中文别名、demo 固定结果 | 别名表已抽成 `labels_zh.json`；其余不用 |
| `app/services/deepseek_client.py`、`recipe_service.py` | DeepSeek 结构化食谱 + 本地规则降级 | **可复用**（之后阶段），只发文本库存清单 |
| `app/services/nutrition_service.py` | 库存营养汇总、每日参考值 | 可参考，app 里已有自己的营养逻辑 |
| `app/services/barcode_service.py`、`receipt_ocr_service.py`、`expiry_ocr_service.py`、`openfoodfacts_client.py`、`coze_client.py` | 条码、小票 OCR、包装日期 OCR、商品库查询、未用的 Coze 客户端 | **搁置**：新思路不扫码不拍小票 |
| `app/services/camera_service.py`、`gpio_button.py`、`api/camera.py` | 设备摄像头、GPIO 按钮 | 搁置 |
| `frontend/`（PWA）、`Dockerfile`、`docker-compose.yml`、`使用文档*.md`、`receipt*.jpg` | 手机上传式前端、云部署、文档、小票样图 | 搁置；Docker 文件留着以防又想上云 |
| `config/api_settings.json` | 含真实 DeepSeek key，已 gitignore | 轮换后只走环境变量 |

## archive/camera_system/ —— 搁置

`capture_service.py`（980 行，摄像头独占 + GPIO + MJPEG + 内置 HTTP 服务）、`recognition.py`（Tesseract OCR 分类提取）、
`capture_repository.py`（SQLite + JSON sidecar）、`DATA_FORMAT.md`（拍摄记录契约）。新思路由 `door_demo.py` 直接读摄像头，
不需要独立的拍照守护进程。值得借鉴的只有两点：原子写 JPEG + SHA-256 登记的做法（app 的 media_store 已有），以及
`--max-frame-age` 拒绝旧帧的思路（网络流重连时可用）。

## archive/hardware/ —— 归档

扫码枪壳体 V1–V3 的 OpenSCAD、CadQuery、STEP、STL、3MF，共 32 MB。新思路没有手持设备。以后如果要给冰箱顶上的相机和
接收器做一个支架，可以复用 V3 的 CadQuery 参数化建模方式，但几何完全不同。

## archive/reference/ 与 archive/yolov11训练-onnx/ —— 归档

| 文件 | 结论 |
| --- | --- |
| `OrangePi_4_Pro_A733_User Manual_v1.4.pdf`（14 MB） | 不再需要，主机已改为 N100 迷你主机 |
| `T-L研究素材.pptx` | 立项时的调研，讲思路时还能用 |
| 4 张截图（7–8 月） | 早期界面/接线留档 |
| `yolov11训练-onnx/class.txt`、`test_result.jpg`、`food_best.onnx`（符号链接） | 训练产物，权重以 fridge_vision/models 为准 |

## 新思路还缺什么（都不在现有资料里）

1. `door_events` 表、`POST /api/v1/door-events`、撤销接口（第二步 2.3）
2. 首页"刚才的变化"卡片（2.4）
3. 按类别默认保质期表（2.5），全仓库没有，要结合你家常买清单新写
4. `door_demo.py --post-url`，以及把一次开关门汇总成一条会话记录
5. N100 上的 systemd 单元与安装脚本（第三步）
6. 门口关键帧标注集与微调权重（之后）

## 目录已搬动（2026-11-06）

搁置和归档的目录已全部移入 `archive/`：`archive/smart_fridge_demo`、`archive/camera_system`、`archive/hardware`、
`archive/reference`、`archive/yolov11训练-onnx`。模型权重和类别表的正本改在 `fridge_vision/models/`，archive 里原位置
留的是指向它的符号链接；测试图在 `fridge_vision/samples/test_food.jpg`。根目录现在只剩 `fridge_vision/`、`smart_fridge_app/`、
`docs/` 和 `archive/`。
