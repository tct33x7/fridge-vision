> 2026-11-06：方案已改为家用纯视觉，不再需要云部署。本文和 Docker 文件随 demo 一起归档在 `archive/smart_fridge_demo/`，留作以后参考。

# 云端部署（smart_fridge_demo）

云端只部署 `smart_fridge_demo`：它靠手机浏览器上传图片工作，不需要 USB 摄像头和 GPIO。`smart_fridge_app`
和 `camera_system` 必须跟摄像头在同一台 Orange Pi 上，不上云。

镜像内容：Python 3.11 slim + FastAPI + ONNX Runtime（YOLO）+ RapidOCR + zxing-cpp，约 1.5 GB，运行时内存
峰值约 800 MB（OCR 首次推理时）。**主机至少 2 GB 内存**，1 核够用。

## 方案 A（推荐）：一台 Linux 云主机 + Docker

适用：阿里云 / 腾讯云轻量应用服务器、任何 VPS。选 Ubuntu 22.04 或 24.04，2 核 2 GB 起。

1. 装 Docker：

```bash
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER && newgrp docker
```

2. 把仓库放到主机上（有 GitHub 时 `git clone`，没有就 `scp -r` 整个 `smart_fridge_demo` 目录），然后：

```bash
cd archive/smart_fridge_demo && DEEPSEEK_API_KEY=sk-你的新密钥 docker compose up -d --build
```

3. 云厂商安全组放行 TCP 8000，手机打开 `http://主机IP:8000`，PWA 可"添加到主屏幕"。

4. 看日志 / 更新 / 停止：

```bash
docker compose logs -f
```

```bash
git pull && docker compose up -d --build
```

```bash
docker compose down
```

数据都在 Docker 卷 `fridge-data`（容器内 `/data/storage`），重建镜像不会丢。备份：

```bash
docker run --rm -v smart_fridge_demo_fridge-data:/data -v "$PWD":/out alpine tar czf /out/fridge-backup-$(date +%F).tgz /data
```

### 加访问口令和 HTTPS（公网必做）

应用本身没有登录。最省事的是在前面放一个 Caddy，它自动申请证书并做 Basic Auth。有域名指向主机后：

```bash
sudo apt install -y caddy && sudo caddy hash-password --plaintext '你的口令'
```

把输出的哈希填进 `/etc/caddy/Caddyfile`：

```text
fridge.example.com {
    basic_auth {
        fridge <上面得到的哈希>
    }
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

然后安全组只放行 80/443，不再放行 8000。

## 方案 B：Railway / Render / Fly.io（免运维，按量付费）

三家都能直接识别仓库里的 `archive/smart_fridge_demo/Dockerfile`。共同要点：

- 根目录设为 `smart_fridge_demo`；
- 环境变量：`DEEPSEEK_API_KEY`、`SMART_FRIDGE_GPIO_BUTTON_ENABLED=false`、`SMART_FRIDGE_STORAGE_DIR=/data/storage`；
- 挂一个持久卷到 `/data`（不挂的话每次重新部署库存就清空）；
- 端口用平台注入的 `PORT`，Dockerfile 已经处理；
- 内存档位选 2 GB，免费档（512 MB）跑不起 OCR。

从国内访问这三家平台的延迟和可达性不稳定，演示用可以，长期用建议方案 A。

## 方案 C：没有 Docker 的 Linux 主机

直接用项目自带脚本和 systemd 模板，和 Orange Pi 上的做法一样：

```bash
cd archive/smart_fridge_demo && ./install.sh && cp .env.example .env
```

编辑 `.env` 填 `DEEPSEEK_API_KEY` 并把 `SMART_FRIDGE_GPIO_BUTTON_ENABLED` 改成 `false`，然后按
[README 第 6 节](archive/smart_fridge_demo/README.md) 安装 `smart-fridge.service`。

## 部署后验收清单

1. `curl http://主机:8000/api/health` 返回 `{"status":"ok",...}`；
2. 手机打开首页，"识别"页点"运行条形码 Demo"能得到候选并确认入库；
3. "小票识别"用 `receipt.jpg` 能返回 8 条候选（证明 OCR 正常）；
4. "今天"页出现 DeepSeek 食谱（证明密钥和出网正常；失败会降级为本地规则，页面会标注来源）；
5. `docker compose restart` 后库存还在（证明卷挂对了）。
