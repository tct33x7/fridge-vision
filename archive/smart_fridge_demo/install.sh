#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "错误：自动安装脚本目前支持 Debian、Ubuntu、Armbian 和 Orange Pi OS（apt 系列）。"
  echo "其他 Linux 发行版请手动安装 python3、python3-venv 和 python3-pip。"
  exit 1
fi

if command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
elif [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  echo "错误：需要 sudo 或 root 权限安装系统依赖。"
  exit 1
fi

"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y python3 python3-venv python3-pip

if [[ -d .venv && ! -x .venv/bin/python ]]; then
  echo "错误：现有 .venv 不是 Linux 虚拟环境。请删除它后重新运行 ./install.sh。"
  exit 1
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

mkdir -p storage/uploads storage/processed storage/models \
  storage/database storage/backups storage/logs

echo
echo "全部运行依赖安装完成（包括 YOLO、条码解码和 OCR）。"
echo "启动服务：./start.sh"
echo "查看局域网 IP：hostname -I"
echo "手机访问：http://<Linux-IP>:8000"
