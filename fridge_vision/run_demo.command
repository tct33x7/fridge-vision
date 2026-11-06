#!/bin/bash
# 双击即可在"终端"里启动门口 demo（第一次会弹摄像头授权，点允许）。输出同时记到 runs/last_run.log。
cd "$(dirname "$0")"
mkdir -p runs
echo "按 o 模拟开门/关门，手拿东西从画面下方举到上方穿过黄线；l 切换方向；q 退出。"
.venv/bin/python door_demo.py --trigger manual --model yolo11n.pt "$@" 2>&1 | tee runs/last_run.log
echo "（窗口可以关闭）"
