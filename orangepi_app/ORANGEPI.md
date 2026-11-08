# orangepi_app · OrangePi 上实际运行的程序

这是 OrangePi 4 Pro 上 `~/smart_fridge_demo/` 的代码，2026-11-08 16:45 从板子同步过来。它在旧项目 `archive/smart_fridge_demo` 的基础上改出来，加了过线计数。
**从现在起以仓库为准**：在仓库里改，再同步到板子上。不要直接在板子上改代码；如果已经改了，先用 `pull` 拉回仓库。

不在仓库里、只在板子上的东西：`.env`（运行配置）、`.venv`、`storage/`（数据库、上传的图片、计数线配置）、模型权重（`models/yolo11s.pt`、`yolo/food_best.onnx`）、`config/api_settings.json`（含 DeepSeek 密钥）、日志。

## 运行方式

| 项 | 值 |
| --- | --- |
| 访问 | 同一 WiFi 下 `http://192.168.3.167:8080`；板子桌面开机自动用 Firefox 打开 `localhost:8080` |
| 服务 | systemd `smart-fridge.service`，开机自启，root 运行（GPIO 要求），失败自动重启；单元文件见 [smart-fridge.service.deployed](smart-fridge.service.deployed) |
| 配置 | 板子上的 `.env`；去掉密钥后的副本见 [.env.deployed.example](.env.deployed.example) |
| 计数 | 默认模式就是计数：YOLO11s（torch，CPU）+ ByteTrack，输入 320；摄像头 640×480、15 帧/秒 |
| 硬件 | UGREEN USB 相机；拍照按钮在物理 7 脚（PL4）；备用开关在物理 11 脚（PL9，接 GND，功能待定，可以当门磁用） |

## 和归档版的区别

新增：`app/services/counter_service.py`、`app/api/counter.py`、`app/database/migrations/002_counter_events.sql`、`app/database/repositories/counter_repository.py`、OCR 流水线（`ocr_*.py`）、`open_browser.sh`、几个启动脚本。
改过：`camera_service.py`（设备枚举、热插拔）、`gpio_button.py`、`api/camera.py`、`api/scans.py`、`config.py`、`main.py`、网页三件套、`requirements.txt`。
去掉：Docker 相关文件。

## 改代码、部署

先配好 SSH 密钥和 `~/.ssh/config` 里的 `Host opi`。

```bash
cd ~/Projects/bx-project && deploy/opi_sync.sh status
```

```bash
cd ~/Projects/bx-project && deploy/opi_sync.sh push
```

确认要推的文件没问题后，加 `--yes` 真正同步，再重启服务（需要 sudo，在终端里运行）：

```bash
cd ~/Projects/bx-project && deploy/opi_sync.sh push --yes
```

```bash
ssh -t opi 'sudo systemctl restart smart-fridge && systemctl is-active smart-fridge'
```

查看日志（过滤掉摄像头刷屏的警告）：

```bash
ssh opi "journalctl -u smart-fridge -f | grep -vE 'cap.cpp|VIDIOC'"
```

## 11-08 实测和已知问题

计数实测只有约 2 帧/秒。用一张静止图片测纯识别速度（板子 CPU，不含追踪和推流）：

| 模型 | 输入 | torch（现在用的） | ONNX Runtime |
| --- | --- | --- | --- |
| yolo11s | 320 | 2.9 帧/秒 | 6.0 帧/秒 |
| yolo11s | 416 | 2.1 帧/秒 | 3.1 帧/秒 |
| yolo11n | 320 | 6.3 帧/秒 | 14.5 帧/秒 |
| yolo11n | 416 | 4.6 帧/秒 | 8.4 帧/秒 |

torch 加线程数（2、4、8）没有变快。

- **计数逻辑还是第 1 步的原版**：第 2 步的改进在 `demos/yolo_web_counter/counter.py`，还没接进来。
- **摄像头重新插拔后计数会卡住**：`counter_service.py` 读不到画面时只等待，不会重新打开摄像头。
- 计数和手动拍照共用一个摄像头，靠切换模式避免冲突。
