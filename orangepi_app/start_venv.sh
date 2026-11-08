#!/bin/bash
# 在 macOS 上使用虚拟环境启动 Smart Fridge 应用
# 清除可能干扰虚拟环境的 TRAE 环境变量

cd /Users/peng/Documents/同步空间/课题/26/Tommy/fridge/smart_fridge_demo

# 清除干扰变量
unset PYTHONPATH
unset PYTHONHOME
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/bin"

# 获取局域网 IP
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

echo "============================================"
echo "  Smart Fridge · 食光冰箱"
echo "============================================"
echo ""
echo "  Mac 访问:    http://localhost:8000"
echo "  iPhone 访问: http://${LAN_IP}:8000"
echo ""
echo "  Mac 浏览器摄像头（getUserMedia）在 localhost 上可直接使用"
echo "  iPhone 如需浏览器摄像头，需 HTTPS（运行 start_https.sh）"
echo ""
echo "============================================"
echo ""

# 使用 venv 的 Python 启动（HTTP，绑定 0.0.0.0 允许局域网设备访问）
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
