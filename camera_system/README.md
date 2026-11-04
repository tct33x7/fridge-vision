# USB 摄像头、OCR 与结构化归档系统

系统会持续保持 USB 摄像头开启，并提供局域网实时画面。按实体按钮或点击网页“拍照”后，原始 JPEG 会先安全落盘，再由后台 OCR 识别、判断单据类型、提取名称/日期/金额等字段，并写入 SQLite 与同名 JSON。识别失败不会影响原始图片或下一次拍摄。

部署时请复制整个 `camera_system` 目录；运行需要这三个核心文件：

- `capture_service.py`：摄像头、GPIO、网页及 API；
- `capture_repository.py`：SQLite 和 JSON 持久化；
- `recognition.py`：本地 OCR、分类和字段提取。

## 接线

| 按钮模块 | 40 针排针物理针脚 | 图中名称 |
|---|---:|---|
| D（信号） | 7 | GPIO 356 / PL4 / wPi 2 |
| V（供电） | 1 或 17 | 3.3V |
| G（地） | 9 | GND |

V 不可接到 5V。

## 安装

Orange Pi 的 Ubuntu Jammy 可使用系统软件包：

```bash
sudo apt update
sudo apt install python3-opencv python3-libgpiod gpiod \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim
```

本程序的网页功能使用 Python 自带组件，不需要安装 FastAPI、Flask 或 Uvicorn。

确认中英文 OCR 语言包：

```bash
tesseract --list-langs
```

输出应至少包含 `chi_sim` 和 `eng`。

## 运行

进入实际存放 `capture_service.py` 的目录。根据截图，文件位于 `~/pythontest` 时应这样运行：

```bash
cd ~/pythontest
sudo python3 capture_service.py
```

终端会显示网页端口和照片目录。查看开发板 IP：

```bash
hostname -I
```

然后在同一局域网的电脑或手机上打开：

```text
http://开发板IP:8000
```

例如开发板 IP 是 `192.168.1.50`，就打开 `http://192.168.1.50:8000`。网页会显示实时画面、拍照按钮、实体按钮状态和 OCR 队列状态。

常用选项：

```bash
# 摄像头不是 /dev/video0
python3 capture_service.py --device /dev/video2

# 保存到指定目录
sudo python3 capture_service.py \
  --output-dir /home/orangepi/Pictures/captures \
  --database /home/orangepi/Pictures/capture_catalog.sqlite3

# 暂时不使用实体按钮，只测试实时画面和网页拍照
python3 capture_service.py --no-gpio

# 只拍一张到 captures/，然后退出
python3 capture_service.py --capture-once

# 临时停用 OCR，但仍保存图片和数据库记录
sudo python3 capture_service.py --no-ocr

# 与主软件集成：仅监听本机 8001，由主软件统一代理
sudo python3 capture_service.py --host 127.0.0.1 --port 8001 --no-ocr
```

`--max-frame-age` 默认是 3 秒。摄像头断线或最新帧超过这个时间时，
拍照接口会返回错误，而不是把断线前缓存的旧画面再次保存。

## 保存位置和处理流程

默认目录结构：

```text
camera_system/
├── captures/
│   └── 2026/08/06/
│       ├── capture_..._<uuid>.jpg
│       └── capture_..._<uuid>.json
└── data/
    └── capture_catalog.sqlite3
```

处理顺序固定为：

1. 将当前摄像头画面原子写入 JPEG；
2. 在 SQLite 登记 UUID、时间、触发来源、尺寸和 SHA-256；
3. 后台单线程 OCR，避免 Orange Pi 同时处理多个任务而影响预览；
4. 分类为 `receipt`、`invoice`、`label` 或 `document`；
5. 提取 `name`、`date`、`total`、`currency`、票据编号、税号、电话等可确认字段；
6. 更新 SQLite，并在 JPEG 旁写入完整同名 JSON。

详细字段契约和数据库说明见 [DATA_FORMAT.md](DATA_FORMAT.md)。

## 后续程序调用

建议后续程序使用版本化 HTTP API，而不是直接依赖内部代码：

| 方法与地址 | 用途 |
|---|---|
| `POST /api/v1/capture` | 拍照并返回 UUID；识别通常处于 `pending` |
| `GET /api/v1/status` | 摄像头、GPIO、OCR 队列和记录数量 |
| `GET /api/v1/latest` | 最近一条完整记录 |
| `GET /api/v1/captures?limit=50` | 分页列出记录 |
| `GET /api/v1/captures/{id}` | 获取原文和所有结构化字段 |
| `POST /api/v1/captures/{id}/retry` | 重新识别失败或已完成记录 |
| `GET /captures/{id}.jpg` | 获取原始 JPEG |

查询支持 `status=completed` 和 `type=receipt` 等过滤条件。项目还提供无第三方依赖的 [capture_client.py](capture_client.py)：

```python
from capture_client import CaptureClient

client = CaptureClient("http://192.168.1.50:8000")
pending = client.capture()
record = client.wait_until_recognized(pending["id"], timeout=60)

print(record["recognition"]["name"])
print(record["recognition"]["type"])
print(record["recognition"]["fields"])
```

识别是本地规则化 OCR，不会把图片上传到云端。低清晰度、反光、倾斜或特殊版式会降低准确率；因此系统始终保留 `raw_text`、置信度、原图和失败原因，后续可以替换为其他 OCR/视觉模型而不改变拍照、数据库和 API 契约。

## 截图中无法运行的原因

截图里的摄像头测试其实已经成功，日志显示它保存了 1920×1080 的照片。完整模式失败在这里：

```text
PermissionError: [Errno 13] Permission denied
```

这是普通用户 `orangepi` 无权打开 `/dev/gpiochip*`，不是摄像头故障。新版程序遇到这个问题时不会退出：实时页面和网页拍照仍然可用，页面会提示实体按钮权限不足。

Orange Pi 4 Pro 的 `gpio readall` 表显示物理针脚 7 是全局 GPIO **356**。程序现在默认使用 GPIO 356，不再要求内核必须提供 `PL4` 线路名称。

已在此开发板的 `gpiodetect` / `gpioinfo` 输出中确认：默认按钮地址为 **`/dev/gpiochip1` 的 offset `4`**。

先检查系统的 GPIO 芯片：

```bash
sudo gpiodetect
sudo gpioinfo
```

如果 root 可以读取 GPIO 信息，可为普通用户配置 GPIO 权限：

```bash
sudo groupadd -f gpio
sudo usermod -aG gpio orangepi
echo 'SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"' | sudo tee /etc/udev/rules.d/60-gpiochip.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio
```

完成后注销并重新登录，再检查：

```bash
python3 capture_service.py
```

如更换开发板或更换接线，可手动指定 GPIO 地址：

```bash
python3 capture_service.py --gpio-chip /dev/gpiochip1 --gpio-offset 4
```

上面的 `gpiochip1` 只是示例；PL4 在芯片内的 offset 是 4，但实际 `gpiochipN` 编号必须以开发板的 `sudo gpioinfo` 输出为准。

## 开机自动运行（可选）

把整个 `camera_system` 目录复制到 `/opt/camera-system`，然后安装示例服务：

```bash
sudo groupadd -f gpio
sudo usermod -aG video,gpio orangepi
sudo cp /opt/camera-system/camera-capture.service.example /etc/systemd/system/camera-capture.service
sudo systemctl daemon-reload
sudo systemctl enable --now camera-capture.service
```

示例服务以普通用户 `orangepi` 运行；`StateDirectory=camera-capture` 会让 systemd
创建并授权 `/var/lib/camera-capture`。修改用户名称时，要同步修改服务文件并确保该用户
有 `video` 与 `gpio` 设备组权限。

示例服务只监听 `127.0.0.1:8001`，供主软件调用；浏览器访问主软件的
8000 端口。需要独立调试摄像头网页时，可手动使用
`--host 0.0.0.0 --port 8001`，且只应在可信局域网内短时开放。查看日志：

```bash
journalctl -u camera-capture.service -f
```

网页没有登录功能，只应在可信任的局域网中使用。
