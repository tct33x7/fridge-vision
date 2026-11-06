# 食光冰箱 Smart Fridge Demo（Linux / Orange Pi）

> 完整安装与使用说明：[Windows 版本](使用文档-Windows.md) · [Linux / Orange Pi 版本](使用文档-Linux.md)

这是一个运行在 Linux 或 Orange Pi 上的本地食品库存 Demo，手机通过局域网拍摄食物、商品条码、购物小票和包装日期。

当前版本已经完成：

- 购物小票上传、OCR 候选、逐项编辑与确认入库；
- 食物照片与条形码独立入口，共用“候选确认后入库”流程；
- 内置可离线运行的番茄照片 Demo 和可真实解码的 EAN-13 条码 Demo；
- 包装日期第二次上传，识别生产日期、到期日期、最佳食用期和保质期；
- 商品、库存批次、库存流水三层数据闭环；
- 库存查看、手动录入、使用、丢弃与临期状态；
- 按库存估算的营养看板；
- 本地排除过期并按临期排序后，调用 DeepSeek 生成结构化食谱和具体做法；
- DeepSeek 未配置、超时或返回异常时自动降级为本地食谱规则；
- 手机优先、可安装为 PWA 的多巴胺风格界面。

详细架构与文件职责见 [ARCHITECTURE.md](ARCHITECTURE.md)。

DeepSeek、Open Food Facts 等外部服务统一在 `config/api_settings.json` 中配置；带真实密钥的文件已被 Git 忽略，模板见 `config/api_settings.example.json`。

## 1. 系统要求

推荐系统：

- Orange Pi OS、Armbian、Debian 或 Ubuntu；
- 64 位 Python 3.10–3.12；
- 设备和手机连接同一个局域网；
- 基础 Demo 约需要 500 MB 可用磁盘空间；
- 安装 RapidOCR 后还需要额外的模型与运行库空间。

安装脚本使用 `apt-get`。其他 Linux 发行版需要先用自己的包管理器安装 `python3`、`python3-venv` 和 `python3-pip`。

## 2. 首次安装

进入项目目录：

```bash
cd /home/orangepi/smart_fridge_demo
```

赋予脚本执行权限：

```bash
chmod +x install.sh start.sh
```

安装 Python、创建 Linux 虚拟环境并安装基础依赖：

```bash
./install.sh
```

安装脚本会依次执行：

```text
安装 python3 / python3-venv / python3-pip
→ 创建 .venv
→ 安装 requirements.txt
→ 创建 storage 下的数据目录
```

## 3. 启动服务

```bash
./start.sh
```

默认监听所有网卡的 `8000` 端口。需要修改端口时：

```bash
PORT=8080 ./start.sh
```

查看 Linux 设备的局域网 IP：

```bash
hostname -I
```

假设设备地址为 `192.168.1.50`，手机访问：

```text
http://192.168.1.50:8000
```

API 调试文档：

```text
http://192.168.1.50:8000/docs
```

如果本机防火墙阻止访问，可以在使用 UFW 的系统上开放端口：

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

## 4. YOLO 食物识别、OCR 与条码解码

`requirements.txt` 已包含 YOLO 推理所需的 `onnxruntime` 和 `numpy`；执行 `./install.sh` 后无需再安装 Ultralytics 或 OpenCV。默认模型和类别文件为：

```text
yolo/food_best.onnx
yolo/classes.txt
```

当前模型只训练了 `banana` 类别。上传食物照片后，后端会完成 640×640 letterbox、ONNX Runtime CPU 推理、置信度过滤和 NMS，再把 `banana` 映射为“香蕉”候选。处理图会写入检测框，候选仍需由用户确认后才能入库。

可在 `.env` 中覆盖模型位置和阈值：

```bash
SMART_FRIDGE_YOLO_MODEL=/home/orangepi/smart_fridge_demo/yolo/food_best.onnx
SMART_FRIDGE_YOLO_CLASSES=/home/orangepi/smart_fridge_demo/yolo/classes.txt
SMART_FRIDGE_YOLO_CONFIDENCE=0.25
SMART_FRIDGE_YOLO_IOU=0.45
```

部分较旧的 ARM64 Orange Pi 系统或 Python 版本可能没有兼容的 ONNX Runtime wheel。如果 `pip install -r requirements.txt` 在 `onnxruntime` 处失败，需要为设备安装匹配 CPU 架构和 Python 版本的 wheel；Windows x64 和有官方 wheel 的 Linux 环境不需要额外系统库。

项目自带的 `receipt.jpg` 会稳定返回 8 个校准后的小票商品候选，可以先验证完整库存流程。

`requirements.txt` 已统一包含 RapidOCR 和 `zxing-cpp`。执行 `./install.sh` 后即可识别真实小票、包装日期和条形码，无需再安装其他 requirements 文件。

## 5. 使用步骤

1. 手机打开设备的 `http://<Linux-IP>:8000`；
2. 进入“识别”页面，选择“食物拍照”“条形码”“小票识别”或“包装日期”；
3. 首次体验建议选择“条形码”，点击“运行条形码 Demo”；也可拍摄真实图片；
4. 检查商品名称、条码、数量和到期日期，确认后再入库；
5. 进入“库存”，查看批次，也可以使用或丢弃库存；
6. 对某一批库存点击“拍日期”；
7. 第二次上传该商品包装上的生产日期或到期日期图片；
8. 核对日期候选并确认；
9. 回到“今天”，查看临期提醒、库存营养和今日推荐食谱。

## 6. 后台运行与开机自启

先根据实际用户名和项目目录修改 `smart-fridge.service.example` 中的：

```text
User
Group
WorkingDirectory
EnvironmentFile
ExecStart
```

然后安装 Systemd 服务：

```bash
sudo cp smart-fridge.service.example /etc/systemd/system/smart-fridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now smart-fridge
sudo systemctl status smart-fridge
```

查看实时日志：

```bash
journalctl -u smart-fridge -f
```

重启或停止：

```bash
sudo systemctl restart smart-fridge
sudo systemctl stop smart-fridge
```

### USB 摄像头与 GPIO 拍照按钮

项目默认使用 `/dev/video0`，并在网页功能栏提供“摄像头”页面。该页面可以查看实时画面、选择食物/条码/小票/日期识别类型，并点击“拍照并识别”。识别结果仍需人工确认后才会加入库存。

Orange Pi 4 Pro 的默认按钮配置为：物理 7 号脚（PL4、wPi 2）输入上拉，按下时连接 GND。普通两脚按钮只连接 **7 号脚与 9 号 GND**；不要用裸按钮直接短接 1 号 3.3V 与 9 号 GND。带 `VCC/GND/S` 的三针按钮模块可连接 1 号 3.3V、9 号 GND 和 7 号信号脚。

```bash
sudo usermod -aG video orangepi
gpio readall
```

修改用户组后需重新登录或重启。网页最后选择的识别类型会同步给物理按钮，默认类型为“食物”。摄像头和按钮配置可在 `.env` 中通过 `SMART_FRIDGE_CAMERA_*` 与 `SMART_FRIDGE_GPIO_BUTTON_*` 调整。

## 7. 数据位置

- SQLite 数据库：`storage/database/smart_fridge.db`；
- 原始图片：`storage/uploads/`；
- 图像预处理结果：`storage/processed/`；
- 数据库备份：`storage/backups/`；
- 日志预留目录：`storage/logs/`。

默认不上传图片或库存到云端。Open Food Facts 只有在主动调用条码查询 API 时才会访问网络。

## 8. 维护

执行维护任务：

```bash
.venv/bin/python -m app.tasks.expiry_check
.venv/bin/python -m app.tasks.backup
.venv/bin/python -m app.tasks.cleanup
```

## 9. 常见问题

### `./start.sh` 提示没有 Linux 虚拟环境

先执行：

```bash
./install.sh
```

不要把其他系统生成的 `.venv` 复制到 Linux；虚拟环境必须在目标 Linux 设备上重新创建。

### 手机打不开页面

检查：

```bash
hostname -I
ss -ltnp | grep 8000
sudo ufw status
```

确认手机和 Linux 设备连接的是同一个局域网，并使用设备 IP，而不是 `localhost`。

### 如何停止手动启动的服务

在运行 `./start.sh` 的终端按 `Ctrl+C`。
