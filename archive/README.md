# archive · 搁置与归档

2026-11-06 方案改为"门口纯视觉自动记账"后不再推进的部分，原样保留，不再维护。为什么搁置、哪些文件还会被复用，见
[docs/INVENTORY.md](../docs/INVENTORY.md)。

| 目录 | 原用途 | 状态 |
| --- | --- | --- |
| `smart_fridge_demo/` | 手机上传式识别 demo：条码、小票 OCR、包装日期 OCR、PWA、Docker | 搁置；`yolo/` 下的权重和类别表是指向 `fridge_vision/models/` 的符号链接 |
| `camera_system/` | Orange Pi 按钮拍照 + Tesseract OCR 守护进程 | 搁置，被 `fridge_vision/door_demo.py` 取代 |
| `hardware/` | 手持扫码枪壳体 V1–V3（OpenSCAD / STEP / STL） | 归档 |
| `reference/` | Orange Pi 手册、研究素材 PPT、早期截图 | 归档 |
| `yolov11训练-onnx/` | YOLO11 训练产物（类别表、测试结果图） | 归档 |

要跑归档里的 demo：`cd archive/smart_fridge_demo && ./install.sh`（它自己的 `.venv` 已失效，需重建）。
