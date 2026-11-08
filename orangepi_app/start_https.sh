#!/bin/bash
# HTTPS 启动脚本（用于 iPhone 浏览器摄像头，getUserMedia 需要 HTTPS）
# 使用方法: bash start_https.sh

cd /Users/peng/Documents/同步空间/课题/26/Tommy/fridge/smart_fridge_demo

unset PYTHONPATH
unset PYTHONHOME
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/bin"

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
CERT_DIR="certs"
KEY_FILE="$CERT_DIR/key.pem"
CERT_FILE="$CERT_DIR/cert.pem"

# 生成证书（如不存在）
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
  echo "正在生成自签名证书…"
  mkdir -p "$CERT_DIR"
  openssl req -x509 -newkey rsa:2048 -keyout "$KEY_FILE" -out "$CERT_FILE" -days 365 -nodes \
    -subj "/CN=$LAN_IP" -addext "subjectAltName=IP:$LAN_IP,DNS:localhost,IP:127.0.0.1" 2>/dev/null
fi

echo "============================================"
echo "  Smart Fridge · HTTPS 模式"
echo "============================================"
echo ""
echo "  Mac 访问:    https://localhost:8443"
echo "  iPhone 访问: https://${LAN_IP}:8443"
echo ""
echo "  首次访问需信任自签名证书："
echo "  Safari → 显示详细信息 → 访问此网站"
echo "  Chrome → 高级 → 继续前往"
echo ""
echo "============================================"
echo ""

exec .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8443 \
  --ssl-keyfile "$KEY_FILE" \
  --ssl-certfile "$CERT_FILE"
