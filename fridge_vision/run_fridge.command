#!/bin/bash
# 实景模式：笔记本放冰箱旁对着门口。自动开门检测（冰箱灯亮）、竖直过线、事件上报本机后端。
# 画面上方会显示 lum（当前亮度）/ base（关门基线）/ +阈值；开门时 lum 应明显高于 base+阈值，否则调小 DELTA。
cd "$(dirname "$0")"
mkdir -p runs
DELTA="${DELTA:-25}"
IN_DIR="${IN_DIR:-left}"   # 画面里冰箱内部在左边就是 left，在右边改 right（运行中按 l 也能切）
echo "实景模式：开门自动触发；l 切换放入方向；o 可手动开/关门；q 退出。阈值 DELTA=$DELTA，放入方向=$IN_DIR"
.venv/bin/python door_demo.py --trigger auto --door-delta "$DELTA" --axis x --line 0.5 --in-dir "$IN_DIR" \
  --model yolo11n.pt --post-url http://127.0.0.1:8000 --out runs/fridge_events.jsonl --keyframes runs/fridge_keyframes "$@" 2>&1 | tee runs/last_run.log
echo "（窗口可以关闭）"
