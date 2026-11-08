# orangepi_app · OrangePi 上实际运行的程序

这是 OrangePi 4 Pro 上 `~/smart_fridge_demo/` 的代码。它在旧项目 `archive/smart_fridge_demo` 的基础上改出来，加了过线计数（11-08 老师接入）、NPU 识别（11-08 17:04 老师改）、开门检测与待机和第 2 步计数规则（11-08 晚）。
**以仓库为准**：在仓库里改，用 `deploy/opi.sh` 同步到板子。不要直接在板子上改代码；如果已经改了，先 `deploy/opi.sh pull` 拉回仓库。

不在仓库里、只在板子上的东西：`.env`（运行配置）、`.venv`、`storage/`（数据库、上传的图片、计数线）、模型权重、`config/api_settings.json`（含 DeepSeek 密钥）、日志。

## 运行方式

| 项 | 值 |
| --- | --- |
| 访问 | 同一 WiFi 下 `http://192.168.3.167:8080`；板子桌面开机自动用 Firefox 打开 `localhost:8080` |
| 服务 | systemd `smart-fridge.service`，开机自启，root 运行（GPIO 要求），失败自动重启；单元文件见 [smart-fridge.service.deployed](smart-fridge.service.deployed) |
| 配置 | 板子上的 `.env`；去掉密钥后的副本见 [.env.deployed.example](.env.deployed.example)。看、改用 `deploy/opi.sh env` |
| 识别 | `SMART_FRIDGE_COUNTER_ENGINE`：`npu` = 板载 NPU 跑 YOLOv5s（`/opt/yolov5/model/yolov5.nb`，640 输入，约 17 帧/秒，[npu_yolov5.py](app/services/npu_yolov5.py) + [bytetrack_lite.py](app/services/bytetrack_lite.py)）；`cpu` = ultralytics `models/yolo11s.pt`（约 2–3 帧/秒）；`auto` = NPU 优先 |
| 计数 | [line_counter.py](app/services/line_counter.py)（第 2 步的规则，`SMART_FRIDGE_COUNTER_PRESET`，默认 `default`）；摄像头 640×480、15 帧/秒 |
| 待机 | [door_watcher.py](app/services/door_watcher.py)，见下文 |
| 硬件 | UGREEN USB 相机；拍照按钮在物理 7 脚（PL4）；备用开关在物理 11 脚（PL9，接 GND，功能待定，可以当门磁用） |

## 怎么更新板子上的程序

都在 Mac 的仓库根目录运行。前提：配好了 SSH 密钥和 `~/.ssh/config` 里的 `Host opi`（见 [deploy/README.md](../deploy/README.md)）。

```bash
cd ~/Projects/bx-project && deploy/opi.sh status
```

先看状态：服务在不在跑、计数是待机还是识别中、两边代码哪里不一样。如果有"拉回"，说明有人直接在板子上改过，先 `deploy/opi.sh pull` 并提交，再继续。

```bash
cd ~/Projects/bx-project && deploy/opi.sh push
```

列出会推哪些文件（还没改）。没问题就真正推送，再重启（重启要输入板子的 sudo 密码）：

```bash
cd ~/Projects/bx-project && deploy/opi.sh push --yes && deploy/opi.sh restart
```

看实时日志（开门、待机以 `[door]` 开头；Ctrl+C 退出）：

```bash
cd ~/Projects/bx-project && deploy/opi.sh logs
```

改了坏了想退回：`git checkout <上一个版本> -- orangepi_app` 后再 push；或者用 `private/opi_backups/` 里的整包备份。

## 开门检测与待机

没有门磁，只能用画面判断"有没有人在动冰箱"。每读到一帧：

```text
            画面变化 > 3% 或 平均亮度变化 > 18，连续 2 次（约 0.4 秒）
   待机  ─────────────────────────────────────────────▶  识别中
 （不跑识别，                                          （跑识别 + 过线计数，
   每秒看 5 帧）  ◀─────────────────────────────────────    一次开门 = 一个会话）
            前后两帧变化 < 1% 持续 6 秒，或识别超过 300 秒
            （休眠时把还在等确认的过线算完，静止的新画面当新背景）
```

- **比的是什么**：缩到 160 像素宽的灰度图。待机时和"背景"比，识别中和上一帧比。比较前先扣掉整幅画面的平均亮度差，所以自动曝光、云遮太阳这种整体变亮变暗不算"动"。
- **背景**：摄像头刚打开的前 2 秒等曝光稳定，只学背景；待机且静止时，背景慢慢跟着画面变（适应早晚光线）；有动静时不跟。
- **为什么只看画面动不动、不看识别到几个东西**：台面上的瓶子会被一直识别到，按"有目标就不睡"会永远不待机。
- **误唤醒**：人从门口走过、开关厨房灯，会白跑 6 秒识别；只要东西没过线就不会多计。日志和网页上每次开门都有记录，**计数 0 个的开门就是误唤醒**，用它来调参数。
- **省了多少**：家里冰箱一天开几十次、每次十几秒，绝大部分时间在待机。
- 摄像头连续 3 秒读不到画面（被拔插过）会自动重新打开；之前这种情况会卡死直到重启服务。

参数都在板子的 `.env` 里，不写就用默认值，改完要重启：

| 设置 | 默认 | 调大 / 调小 |
| --- | --- | --- |
| `SMART_FRIDGE_DOOR_STANDBY` | `true` | `false` = 不待机，一直识别（和以前一样） |
| `SMART_FRIDGE_DOOR_WAKE_RATIO` | `0.03` | 误唤醒多就调大；开门醒得慢、漏掉第一下就调小 |
| `SMART_FRIDGE_DOOR_WAKE_BRIGHTNESS` | `18` | 冰箱灯不够亮、开门不醒就调小 |
| `SMART_FRIDGE_DOOR_WAKE_HITS` | `2` | 连续几次才醒；1 = 最快，也最容易误醒 |
| `SMART_FRIDGE_DOOR_SLEEP_RATIO` | `0.01` | 手停着不动也被当成静止就调小 |
| `SMART_FRIDGE_DOOR_SLEEP_SECONDS` | `6` | 犹豫、找东西时被打断就调大 |
| `SMART_FRIDGE_DOOR_MAX_ACTIVE_SECONDS` | `300` | 一次识别最长多久 |
| `SMART_FRIDGE_DOOR_ROI` | 空（整幅） | 只看画面的一块，如 `0.2,0,0.8,1`：门口外有人走动、误唤醒多时用 |
| `SMART_FRIDGE_COUNTER_PRESET` | `default` | `hidden` = 门洞上方、看不到冰箱里面时；`baseline` = 第 1 步原版 |

例子：

```bash
cd ~/Projects/bx-project && deploy/opi.sh env SMART_FRIDGE_DOOR_SLEEP_SECONDS=8 && deploy/opi.sh restart
```

**第一版有意没做的**：

- **预录缓冲**：醒来前那一小段不回头补识别。实测醒来约 0.4 秒，一般比"开门到伸手"快；冰箱上测完再决定要不要加。
- **门磁**：物理 11 脚的备用开关可以接干簧管门磁，接上后比画面判断可靠。
- **区分门和人**：现在整幅画面任何地方动都算，误唤醒多时再用 `DOOR_ROI` 缩小范围。

## 测试（不用板子）

开门检测的单元测试（合成画面）：

```bash
cd ~/Projects/bx-project && fridge_vision/.venv/bin/python -m unittest orangepi_app/tests/test_door_watcher.py -v
```

用录像代替摄像头，跑一遍同一份计数服务代码（Mac 上用 CPU 引擎），看开门 / 待机时间线和计数是否和真值一致：

```bash
cd ~/Projects/bx-project && fridge_vision/.venv/bin/python orangepi_app/tools/simulate_counter.py demos/yolo_web_counter/test_videos/jitter1.mp4 --model demos/yolo_web_counter/models/yolo11s.pt
```

11-08 晚用第 2 步的三段桌面录像（缩到 640 宽、抽到 15 帧/秒）对比：待机开和关，计数结果完全一样；识别只跑了 59–92% 的帧（桌面录像一直有人在动，真冰箱上省得更多）。yolo11n 比 yolo11s 差很多（jitter1 一次都没计到），所以不用 yolo11n。

## 和归档版的区别

新增：`app/services/counter_service.py`、`app/api/counter.py`、`app/database/migrations/002_counter_events.sql`、`app/database/repositories/counter_repository.py`、`npu_yolov5.py`、`bytetrack_lite.py`、`door_watcher.py`、`line_counter.py`、OCR 流水线（`ocr_*.py`）、`open_browser.sh`、几个启动脚本。
改过：`camera_service.py`（设备枚举、热插拔）、`gpio_button.py`、`api/camera.py`、`api/scans.py`、`config.py`、`main.py`、网页三件套、`requirements.txt`。
去掉：Docker 相关文件。

## 11-08 实测

纯识别速度（静止图片，不含追踪和推流）：

| 引擎 | 模型 | 输入 | 帧/秒 |
| --- | --- | --- | --- |
| CPU torch | yolo11s | 320 | 2.9 |
| CPU ONNX Runtime | yolo11s | 320 | 6.0 |
| CPU ONNX Runtime | yolo11n | 320 | 14.5 |
| **NPU（老师 17:04 接入）** | **YOLOv5s** | **640** | **约 17（含追踪，实测计数 14.5）** |

计数和手动拍照共用一个摄像头，靠切换模式避免冲突（进"摄像头"页面会暂停计数）。
