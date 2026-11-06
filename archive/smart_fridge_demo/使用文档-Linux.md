# 食光冰箱 Smart Fridge Demo：Linux / Orange Pi 使用文档

本文适用于 Debian、Ubuntu、Armbian、Orange Pi OS 等 Linux 系统。自动安装脚本使用 `apt-get`；其他发行版请参照“手动安装”。

## 1. 环境要求

- 64 位 Python 3.10–3.12；
- 基础 Demo 约需 500 MB 可用磁盘空间；
- 如需让手机访问，Linux 设备和手机应连接同一局域网；
- Orange Pi 建议使用仍受支持的 64 位操作系统，以便安装 ONNX Runtime。

## 2. 首次安装

进入项目目录。下面只是示例，请替换为实际路径：

```bash
cd /home/orangepi/smart_fridge_demo
```

为脚本增加执行权限并安装：

```bash
chmod +x install.sh start.sh
./install.sh
```

脚本会安装 `python3`、`python3-venv` 和 `python3-pip`，创建 `.venv`，安装 `requirements.txt`，并创建数据目录。安装系统软件包时可能要求输入 sudo 密码。

### 其他 Linux 发行版手动安装

先使用系统包管理器安装 Python、venv 和 pip，再从项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
mkdir -p storage/uploads storage/processed storage/models storage/database storage/backups storage/logs
```

## 3. 启动与访问

```bash
./start.sh
```

脚本默认监听所有网卡的 `8000` 端口。查看设备局域网地址：

```bash
hostname -I
```

假设设备地址为 `192.168.1.50`，访问：

- 应用首页：`http://192.168.1.50:8000`
- API 文档：`http://192.168.1.50:8000/docs`
- 健康检查：`http://192.168.1.50:8000/api/health`

在运行脚本的终端按 `Ctrl+C` 可停止服务。

指定其他端口：

```bash
PORT=8080 ./start.sh
```

使用 UFW 且需要局域网访问时，可开放实际使用的端口：

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

只应在可信局域网中开放服务；本项目默认没有登录鉴权，不建议把端口直接暴露到公网。

## 4. 功能使用

启动网页后进入“识别”页面：

1. “食物拍照”：点击“运行食物照片 Demo”可体验内置番茄 Demo；上传 `yolo/test food.jpg` 可验证随附 YOLO 香蕉模型。
2. “条形码”：点击“运行条形码 Demo”，核对商品名称、条码、数量和日期。
3. “小票识别”：点击“使用 receipt.jpg 示例”，可一次生成多件商品候选。
4. “包装日期”：选择已有库存，上传包装上的生产日期、到期日期或保质期照片。
5. 所有识别结果均先进入候选确认页；检查并修改后，再点击确认入库。
6. 进入“库存”可查看、使用或丢弃库存；“今天”页面显示临期提醒、营养信息和食谱推荐。

内置 Demo 不需要 OCR 或条码扩展，也不需要外部 API。

### USB 摄像头与物理拍照按钮

1. 将 USB 摄像头接入开发板，确认设备节点：

```bash
ls -l /dev/video0
sudo usermod -aG video orangepi
```

修改 `video` 用户组后重新登录或重启。进入网页“摄像头”功能页即可查看实时画面。

2. Orange Pi 4 Pro 默认按钮引脚为物理 7 号脚（PL4、wPi 2）。普通两脚按钮连接 7 号脚和 9 号 GND，程序使用内部上拉，因此不需要连接 1 号 3.3V。若使用带 `VCC/GND/S` 标识的三针按钮模块，才将 VCC 接 1 号 3.3V、GND 接 9 号、S 接 7 号。

3. 查看 wiringOP 引脚编号：

```bash
gpio readall
```

官方 Orange Pi Linux 镜像通常已预装 wiringOP。服务启动后会自动将 wPi 2 配置为输入上拉并监听按键。网页中最后选定的识别类型会用于下一次物理按键拍照；默认识别“食物”。日期识别还必须在网页中选定对应库存批次。

4. 可通过状态接口排查硬件：

```bash
curl http://127.0.0.1:8000/api/camera/status
```

若摄像头或按钮未就绪，状态中的 `error` 会给出具体原因，原有图片上传与库存功能不会受到影响。

## 5. YOLO、真实条码与 OCR

`requirements.txt` 已包含基础服务、YOLO、条码解码和 OCR 的全部运行依赖。默认模型文件为：

```text
yolo/food_best.onnx
yolo/classes.txt
```

当前随附模型只包含 `banana` 类别，应用会将其显示为“香蕉”。它不需要安装 Ultralytics。真实条形码由 `zxing-cpp` 解码，真实小票和包装日期由 RapidOCR 识别。RapidOCR 依赖和模型较大，首次安装及首次识别可能较慢。

部分 ARM64 设备或较旧 Python 版本没有兼容的 ONNX Runtime wheel。如果基础依赖在 `onnxruntime` 处安装失败，请确认操作系统为 64 位，并为当前 CPU 架构和 Python 版本安装匹配的 wheel。内置规则 Demo 仍可用于验证页面和库存流程。

## 6. 配置文件与 DeepSeek 食谱

不配置外部 API 也可使用基础功能，食谱会自动采用本地规则。

需要启用 DeepSeek 时，如果配置文件不存在，先复制模板：

```bash
cp config/api_settings.example.json config/api_settings.json
nano config/api_settings.json
```

在完整 JSON 结构中填写 `deepseek.api_key`，并保持 `deepseek.enabled` 为 `true`。保存后重启服务。不要把真实 API Key 提交到 Git 或发到聊天记录中；`config/api_settings.json` 已被 Git 忽略。

也可复制环境变量模板：

```bash
cp .env.example .env
nano .env
```

环境变量的优先级高于 JSON 配置。部署时可在 `.env` 中覆盖存储目录、数据库位置、YOLO 参数、上传大小和 API 设置。使用其他项目路径时，不要直接照抄模板中的 `/home/orangepi/...` 绝对路径。

## 7. Systemd 后台运行与开机自启

先复制示例文件，并按实际用户名和绝对路径修改 `User`、`Group`、`WorkingDirectory`、`EnvironmentFile` 和 `ExecStart`：

```bash
cp smart-fridge.service.example smart-fridge.service
nano smart-fridge.service
```

确认内容正确后安装服务：

```bash
sudo cp smart-fridge.service /etc/systemd/system/smart-fridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now smart-fridge
sudo systemctl status smart-fridge
```

查看实时日志：

```bash
journalctl -u smart-fridge -f
```

重启、停止或取消开机自启：

```bash
sudo systemctl restart smart-fridge
sudo systemctl stop smart-fridge
sudo systemctl disable smart-fridge
```

## 8. 数据与备份

默认数据位置：

- SQLite 数据库：`storage/database/smart_fridge.db`
- 上传原图：`storage/uploads/`
- 处理后图片：`storage/processed/`
- 数据库备份：`storage/backups/`
- 日志目录：`storage/logs/`

备份时至少复制 `storage/database/smart_fridge.db`；需要保留识别图片时，再同时复制 `storage/uploads/` 和 `storage/processed/`。执行备份前可先停止写入或停止服务，以获得一致的数据文件。

维护命令：

```bash
.venv/bin/python -m app.tasks.expiry_check
.venv/bin/python -m app.tasks.backup
.venv/bin/python -m app.tasks.cleanup
```

## 9. 常见问题

### `./start.sh` 提示未找到 Linux 虚拟环境

先执行 `./install.sh`。不要从 Windows 或其他系统复制 `.venv`；必须在目标 Linux 设备上重新创建。

### 脚本提示 `Permission denied`

```bash
chmod +x install.sh start.sh
```

然后重新执行脚本。

### 手机打不开页面

检查服务、监听端口和防火墙：

```bash
hostname -I
ss -ltnp | grep 8000
sudo ufw status
```

确认手机和 Linux 设备连接同一局域网，并使用设备 IP 而不是 `localhost`。若使用了自定义端口，请同步修改检查命令和手机访问地址。

### 端口 8000 已被占用

```bash
PORT=8080 ./start.sh
```

### 修改前端后仍显示旧页面

在浏览器中强制刷新。若已安装为 PWA，请关闭后重新打开，或清除该站点缓存。

### 查看启动失败原因

手动运行时直接查看终端输出；Systemd 模式执行：

```bash
sudo systemctl status smart-fridge
journalctl -u smart-fridge -n 100 --no-pager
```
