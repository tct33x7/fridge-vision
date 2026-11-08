#!/bin/bash
# 香橙派启动脚本 · Smart Fridge 食光冰箱
# 使用方法: bash start_orangepi.sh
# 需要 sudo 权限以访问 GPIO 按钮（物理脚 7 / PL4，按下高电平）

cd "$(dirname "$0")"

# 获取局域网 IP
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

# 优先使用 venv，否则使用系统 python3
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

# 后台启动服务（使用 sudo 以启用 GPIO 按钮）
sudo $PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port 8080 &
SERVER_PID=$!

echo "============================================"
echo "  Smart Fridge · 食光冰箱 (Orange Pi)"
echo "============================================"
echo ""
echo "  本机访问:   http://localhost:8080"
echo "  局域网访问: http://${LAN_IP}:8080"
echo ""
echo "  摄像头模式: USB Only (自动开启)"
echo "  GPIO 按钮:  物理脚 7 (PL4) · 按下高电平"
echo ""
echo "  正在等待服务启动…"
echo "============================================"
echo ""

# 等待服务就绪（最多等待 15 秒）
for i in $(seq 1 15); do
  if curl -s http://localhost:8080/api/health > /dev/null 2>&1; then
    echo "服务已启动，正在打开浏览器…"
    # 自动在香橙派桌面打开浏览器
    DISPLAY=:0 xdg-open http://localhost:8080 > /dev/null 2>&1 || \
    DISPLAY=:0 chromium-browser http://localhost:8080 > /dev/null 2>&1 || \
    DISPLAY=:0 firefox http://localhost:8080 > /dev/null 2>&1 || \
    echo "（浏览器未自动打开，请手动访问 http://localhost:8080）"
    break
  fi
  sleep 1
done

echo ""
echo "  按 Ctrl+C 停止服务"
echo ""

# 等待服务进程结束
wait $SERVER_PID
