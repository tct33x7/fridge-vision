#!/bin/bash
# 仓库 orangepi_app/ 和 OrangePi 上 ~/smart_fridge_demo/ 之间同步代码。
#
#   deploy/opi_sync.sh status        看两边哪些文件不一样（只看，不改）
#   deploy/opi_sync.sh pull          板子 → 仓库（老师在板子上直接改过时用；拉完用 git diff 看改了什么）
#   deploy/opi_sync.sh push          仓库 → 板子，只列出会改哪些文件
#   deploy/opi_sync.sh push --yes    仓库 → 板子，真正同步；之后需要重启服务才生效
#
# 永远不碰：.env、.venv、storage（数据库、上传的图片）、模型权重、config/api_settings.json、日志。
# 不删除板子上多出来的文件（不用 --delete）。
# 需要先配好 SSH 密钥和 ~/.ssh/config 里的 Host opi；换主机名或 IP 时设 OPI_HOST。
set -euo pipefail

HOST="${OPI_HOST:-opi}"
REMOTE_DIR="smart_fridge_demo/"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/orangepi_app/"

EXCLUDES=(
  --exclude .venv --exclude storage --exclude __pycache__ --exclude '*.pyc'
  --exclude .env --exclude .env.orangepi --exclude config/api_settings.json
  --exclude '*.pt' --exclude '*.onnx' --exclude '*.db' --exclude '*.sqlite*'
  --exclude logs --exclude backups --exclude uploads --exclude processed
  --exclude 'test food.jpg' --exclude .DS_Store
  --exclude smart-fridge.service.deployed --exclude .env.deployed.example --exclude ORANGEPI.md
)
RSYNC=(rsync -a --itemize-changes -e "ssh -o BatchMode=yes" "${EXCLUDES[@]}")

case "${1:-}" in
  status)
    echo "== 板子上比仓库新、或仓库里没有的（pull 会拉回来）"
    "${RSYNC[@]}" --dry-run "$HOST:$REMOTE_DIR" "$LOCAL_DIR" | grep -v '/$' || true
    echo "== 仓库比板子新、或板子上没有的（push 会推过去）"
    "${RSYNC[@]}" --dry-run "$LOCAL_DIR" "$HOST:$REMOTE_DIR" | grep -v '/$' || true
    ;;
  pull)
    "${RSYNC[@]}" "$HOST:$REMOTE_DIR" "$LOCAL_DIR" | grep -v '/$' || true
    echo "已拉回。用 git status / git diff orangepi_app 看改了什么。"
    ;;
  push)
    if [ "${2:-}" != "--yes" ]; then
      echo "== 将推送到 $HOST:$REMOTE_DIR 的文件（没有真正改动；确认后加 --yes）"
      "${RSYNC[@]}" --dry-run "$LOCAL_DIR" "$HOST:$REMOTE_DIR" | grep -v '/$' || true
      exit 0
    fi
    "${RSYNC[@]}" "$LOCAL_DIR" "$HOST:$REMOTE_DIR" | grep -v '/$' || true
    echo "已推送。重启服务才生效（需要 sudo，在终端里运行）："
    echo "  ssh -t $HOST 'sudo systemctl restart smart-fridge && systemctl is-active smart-fridge'"
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
