# 食光冰箱 Smart Fridge Demo：Windows 使用文档

本文适用于 Windows 10/11 和 PowerShell。所有命令都从项目根目录执行。

## 1. 环境要求

- 64 位 Python 3.10–3.12；
- PowerShell 5.1 或更高版本；
- 基础 Demo 约需 500 MB 可用磁盘空间；
- 如需让手机访问，电脑和手机应连接同一局域网。

检查 Python：

```powershell
py -3 --version
```

如果没有 `py` 命令，也可尝试 `python --version`。两者都不可用时，请先安装 Python，并在安装程序中启用“Add Python to PATH”。

## 2. 首次安装

打开 PowerShell，进入项目目录。下面只是示例，请替换为实际路径：

```powershell
cd "C:\path\to\smart_fridge_demo"
```

创建独立虚拟环境并安装基础依赖：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果电脑没有 `py` 命令，将第一行改成：

```powershell
python -m venv .venv
```

本文直接调用虚拟环境中的 Python，无需执行激活脚本，也不需要修改 PowerShell 执行策略。

## 3. 启动与访问

仅供本机访问时：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 后打开：

- 应用首页：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

在运行服务的窗口按 `Ctrl+C` 可停止服务。

后续再次启动时，只需进入项目目录并重新执行本节的 Uvicorn 命令。

## 4. 局域网手机访问

让服务监听电脑的所有网卡：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

另开 PowerShell 查询电脑地址：

```powershell
ipconfig
```

找到当前网卡的 IPv4 地址。假设地址为 `192.168.1.50`，手机访问：

```text
http://192.168.1.50:8000
```

首次监听局域网地址时，Windows 防火墙可能询问是否允许 Python 访问网络。只在可信的家庭或办公专用网络中允许“专用网络”访问，不建议对公用网络开放。

## 5. 功能使用

启动网页后进入“识别”页面：

1. “食物拍照”：点击“运行食物照片 Demo”可体验内置番茄 Demo；上传 `yolo\test food.jpg` 可验证随附 YOLO 香蕉模型。
2. “条形码”：点击“运行条形码 Demo”，核对商品名称、条码、数量和日期。
3. “小票识别”：点击“使用 receipt.jpg 示例”，可一次生成多件商品候选。
4. “包装日期”：选择已有库存，上传包装上的生产日期、到期日期或保质期照片。
5. 所有识别结果均先进入候选确认页；检查并修改后，再点击确认入库。
6. 进入“库存”可查看、使用或丢弃库存；“今天”页面显示临期提醒、营养信息和食谱推荐。

内置 Demo 不需要 OCR 或条码扩展，也不需要外部 API。

## 6. 识别能力与依赖

`requirements.txt` 已包含基础服务、YOLO、条码解码和 OCR 的全部运行依赖。完成首次安装后，可直接使用：

```text
yolo\food_best.onnx
yolo\classes.txt
```

当前随附模型只包含 `banana` 类别，应用会将其显示为“香蕉”。它不需要安装 Ultralytics。真实条形码由 `zxing-cpp` 解码，真实小票和包装日期由 RapidOCR 识别。RapidOCR 依赖和模型较大，首次安装及首次识别可能较慢。

## 7. 配置文件与 DeepSeek 食谱

不配置外部 API 也可使用基础功能，食谱会自动采用本地规则。

需要启用 DeepSeek 时，如果 `config\api_settings.json` 不存在，先复制模板：

```powershell
Copy-Item .\config\api_settings.example.json .\config\api_settings.json
notepad .\config\api_settings.json
```

在完整 JSON 结构中填写 `deepseek.api_key`，并保持 `deepseek.enabled` 为 `true`。保存后重启服务。不要把真实 API Key 提交到 Git 或发到聊天记录中；`config/api_settings.json` 已被 Git 忽略。

也可复制环境变量模板并按需修改：

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

环境变量的优先级高于 JSON 配置。YOLO 模型路径、识别阈值、上传大小和部署密钥都可在 `.env` 中覆盖；默认值通常无需修改。

## 8. 数据与备份

默认数据位置：

- SQLite 数据库：`storage\database\smart_fridge.db`
- 上传原图：`storage\uploads\`
- 处理后图片：`storage\processed\`
- 数据库备份：`storage\backups\`
- 日志目录：`storage\logs\`

备份时至少复制 `storage\database\smart_fridge.db`；需要保留识别图片时，再同时复制 `storage\uploads\` 和 `storage\processed\`。

维护命令：

```powershell
.\.venv\Scripts\python.exe -m app.tasks.expiry_check
.\.venv\Scripts\python.exe -m app.tasks.backup
.\.venv\Scripts\python.exe -m app.tasks.cleanup
```

## 9. 常见问题

### 找不到 `.venv\Scripts\python.exe`

虚拟环境尚未创建，或 `.venv` 来自 Linux。删除错误的虚拟环境后，按“首次安装”重新创建；不要跨系统复制 `.venv`。

### 端口 8000 已被占用

改用其他端口：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

浏览器地址也应改为 <http://127.0.0.1:8080>。

### 手机打不开页面

确认启动参数是 `--host 0.0.0.0`，手机和电脑位于同一局域网，并使用电脑的 IPv4 地址而不是 `localhost`。同时检查 Windows 防火墙的专用网络权限。

### 修改前端后仍显示旧页面

按 `Ctrl+F5` 强制刷新。若已安装为 PWA，请关闭后重新打开，或清除该站点缓存。

### `onnxruntime` 或 OCR 安装失败

确认使用的是受支持的 64 位 Python 3.10–3.12，先升级 pip 后重新执行 `pip install -r requirements.txt`。基础页面和内置 Demo 不依赖真实 OCR，但统一依赖文件会一次安装所有运行能力。
