#!/bin/bash
# 双击启动库存后端；手机在同一 Wi-Fi 下打开 http://<Mac IP>:8000
cd "$(dirname "$0")"
echo "本机局域网地址："; ipconfig getifaddr en0 2>/dev/null || true
./start.sh
