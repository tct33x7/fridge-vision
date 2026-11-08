# archive · 旧项目与参考资料

2026-11-06 方案改为"门口纯视觉自动记账"后不再推进的部分，原样保留，不再维护。
11-08 定下 v4（主机改回 OrangePi 4 Pro）后，其中两样又有用了，见"v4 会用到"一列。当时的盘点见 [docs/history/INVENTORY_20261106.md](../docs/history/INVENTORY_20261106.md)。

| 目录 | 原用途 | 状态 | v4 会用到 |
| --- | --- | --- | --- |
| `smart_fridge_demo/` | 手机上传式识别 demo（基于老师的 demo）：条码、小票 OCR、包装日期 OCR、PWA、Docker；云部署说明 [DEPLOY.md](smart_fridge_demo/DEPLOY.md) | 搁置；`yolo/` 下的权重和类别表是指向 `fridge_vision/models/` 的符号链接 | 食谱、小票 / 条码可作为"初始化库存"的备选做法 |
| `camera_system/` | OrangePi 上的相机守护进程：独占 USB 相机、GPIO 实体按钮、MJPEG 预览、OCR 归档 | 搁置 | **GPIO 读取**（libgpiod）可照搬给门磁；"相机由一个进程独占"的做法适合采集进程 |
| `hardware/` | 手持扫码枪外壳 V1–V3（OpenSCAD / STEP / STL） | 归档 | 建模和打印流程可用于相机支架（新的放在根目录 [hardware/](../hardware/)） |
| `reference/` | **OrangePi 4 Pro 用户手册 v1.4**、研究素材 PPT、早期截图 | 参考 | 手册：装机、GPIO、相机、屏幕，见 [deploy/](../deploy/) |
| `yolov11训练-onnx/` | YOLO11 训练产物（类别表、测试结果图） | 归档 | — |

要跑归档里的 demo：`cd archive/smart_fridge_demo && ./install.sh`（它自己的 `.venv` 已失效，需要重建）。
