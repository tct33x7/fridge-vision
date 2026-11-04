# 快速完成计划（14 天）

制定日期：2026-11-04。目标：**两周内拿出一套能演示的完整系统**：云端可访问的识别+库存+食谱应用，
Orange Pi 上跑通"实体按钮拍照 → 识别候选 → 确认入库"，扫码枪壳体打印装配完成。

## 原则

1. 不再重写。云端用 `smart_fridge_demo`，设备端用 `smart_fridge_app + camera_system`，第 4 阶段才把
   识别能力从 demo 搬进 app，而不是把 app 的会话机制搬进 demo。
2. 每个阶段都有可以当场演示的验收项，做不完的功能砍掉，不往后拖。
3. 所有改动在 `~/Projects/bx-project` 里做并提交，不碰 iCloud 和 Downloads 里的原件。

## 阶段 0 · 整理与环境（已完成，11-04）

- [x] 合并 iCloud 与 Downloads 两份副本，补回丢失的 `index.html`、`food_best.onnx`、`receipt.jpg`、STL/STEP
- [x] 建立 git 仓库，密钥、数据库、上传图全部排除
- [x] 重建两个 Python 3.11 虚拟环境；`smart_fridge_app` 23 个测试、`camera_system` 6 个测试全部通过
- [x] demo 在 macOS 上无摄像头启动成功；真实 YOLO 推理和 RapidOCR 小票识别验证通过
- [x] 写好 `Dockerfile` / `docker-compose.yml`，部署说明见 DEPLOY.md

## 阶段 1 · 云端上线（第 1–2 天）

| # | 任务 | 验收 |
| --- | --- | --- |
| 1.1 | 去 DeepSeek 控制台轮换密钥（旧密钥随压缩包流转过） | 旧 key 失效 |
| 1.2 | 建 GitHub 私有仓库并推送 `main`（本机没有 `gh`，用 HTTPS + Personal Access Token） | `git push` 成功 |
| 1.3 | 买/用一台 2 核 2 GB Linux 云主机，按 DEPLOY.md 方案 A 起容器 | `/api/health` 返回 ok |
| 1.4 | 域名 + Caddy 做 HTTPS 和访问口令 | 手机 4G 网络能打开并要求口令 |
| 1.5 | 手机走完"条码 Demo → 确认入库 → 今天页食谱"全流程 | 截图留档 |

风险：没有域名就先只放行 8000 并立刻做 1.4；没有云主机就先用 Railway 应急（DEPLOY.md 方案 B）。

## 阶段 2 · demo 补强（第 3–5 天）

| # | 任务 | 验收 |
| --- | --- | --- |
| 2.1 | 建识别验收集：10 张真实食材照片 + 3 张小票，记录模型版本、类别数、阈值和命中率（调研文档第 2 节要求） | `docs/recognition-acceptance.md` 有结果表 |
| 2.2 | 识别改成后台任务：OCR/YOLO 不占用事件循环（调研文档第 2 节已指出） | 上传小票时首页仍可操作 |
| 2.3 | 去掉"按文件名触发固定 demo 结果"的逻辑，改为显式 `/demo-*` 接口（已有）独占 | 把任意图改名 `receipt.jpg` 上传不再返回假结果 |
| 2.4 | 加最简登录：一个环境变量口令 + Cookie 会话（替代 Caddy Basic Auth，给 PWA 更好体验） | 无口令访问 API 返回 401 |
| 2.5 | 清理 `coze_client.py` 等未用代码，补一组 API 冒烟测试（用 `httpx2` TestClient） | `python -m unittest` 通过 |

## 阶段 3 · Orange Pi 设备端（第 6–9 天）

| # | 任务 | 验收 |
| --- | --- | --- |
| 3.1 | Orange Pi 4 Pro 刷 Ubuntu Jammy，装 `python3-opencv python3-libgpiod tesseract-ocr`，部署 `camera_system` systemd 服务 | `http://板子IP:8001/api/v1/health` 正常 |
| 3.2 | 部署 `smart_fridge_app` systemd 服务，`SMART_FRIDGE_DATA_DIR=/var/lib/smart-fridge` | 手机打开 8000 看到首页，拍照对话框有实时预览 |
| 3.3 | GPIO 按钮接 7 号脚 + 9 号 GND，连续拍 100 张 | 100 张全部进入图库，SHA-256 校验无失败 |
| 3.4 | 拔掉摄像头再插回 | 预览自动恢复，库存页面全程可用 |
| 3.5 | 跑一次备份包并在另一台机器还原 | `manifest.json` 全量校验通过 |

风险：ARM64 上 `onnxruntime` wheel 可能装不上，提前在板子上 `pip download onnxruntime` 试一次。

## 阶段 4 · 识别合流（第 10–12 天）

把 demo 已验证的三个识别服务（`yolo_food_detector.py`、`receipt_ocr_service.py`、`barcode_service.py`）
作为独立模块接入 `smart_fridge_app` 的录入会话，位置固定在"照片已安全保存"之后、"用户确认"之前：

| # | 任务 | 验收 |
| --- | --- | --- |
| 4.1 | 新建 `smart_fridge_app/app/services/recognition/`，复制三个服务并去掉对 demo 配置的依赖 | 单测覆盖 banana 照片和 `receipt.jpg` |
| 4.2 | 会话接口增加 `POST /intake-sessions/{id}/analyze`，结果写入 `draft_json`，前端表单预填候选 | 拍香蕉后名称自动填"香蕉"，用户仍需点确认 |
| 4.3 | 识别失败/低置信度只显示提示，不改库存、不删原图 | 删掉模型文件后流程不报错 |

## 阶段 5 · 硬件与演示（第 13–14 天）

| # | 任务 | 验收 |
| --- | --- | --- |
| 5.1 | 打印 V3 左右壳 + 支架（`hardware/scanner-gun-v3/exports/`），先用真实摄像头和按钮面板核孔距 | 面板四角螺丝能上，镜头穿过 13.9 mm 孔 |
| 5.2 | 装热熔螺母、走线、装配；USB 插头过不了 4.4 mm 孔则按交接文档做可拆盖板 | 单手持握，按钮触发拍照 |
| 5.3 | 写演示脚本：云端 PWA 演示 + 设备端扫码枪演示各 3 分钟，录屏备份 | 两段视频 |

## 砍掉 / 延后

- 多用户、账号体系、公网多设备同步；
- 餐食编辑撤销、多食材合并一餐；
- WebRTC/HLS 连续录像；
- 商品级"一盒 = 多少克"换算和完整营养数据库；
- 扫码枪 V4。

## 需要你决定的事

1. 云主机选哪家（国内演示用腾讯/阿里轻量；海外用 Hetzner/Railway）。
2. 是否要在演示前加登录（建议加，2.4 一天内能做完）。
3. Orange Pi 和摄像头、按钮模块是否已经在手；没有的话阶段 3 整体顺延，先把阶段 1、2、4 做完。
