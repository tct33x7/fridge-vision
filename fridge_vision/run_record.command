#!/bin/bash
# 测量录制：相机对着冰箱门口。开门自动录制 + 过线关键帧 + 关门后在这个终端里记真值。
# 可选环境变量：SOURCE（摄像头编号或流地址，默认 1=外接）、DELTA（亮度阈值，默认 25）、MODEL（YOLO 模型，默认 yolo11n.pt；填 none 不跑）
cd "$(dirname "$0")"
SOURCE="${SOURCE:-1}"
DELTA="${DELTA:-25}"
MODEL="${MODEL:-yolo11n.pt}"
EXTRA=""
[ "$MODEL" != "none" ] && EXTRA="--model $MODEL"
echo "测量录制：源=$SOURCE 阈值=$DELTA 模型=$MODEL。o 手动开/关门，q 退出。关门后按提示记真值。"
.venv/bin/python record_sessions.py --source "$SOURCE" --trigger auto --door-delta "$DELTA" --axis x --line 0.5 $EXTRA "$@"
echo "（窗口可以关闭。统计：.venv/bin/python analyze_sessions.py --contact）"
