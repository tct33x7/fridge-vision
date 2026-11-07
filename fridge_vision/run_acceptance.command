#!/bin/bash
# M1 正式验收轮：同一批东西分别用 COCO 通用模型和自训 80 类食物模型各跑一轮，输出分开记录。
# 用法：双击；或在"终端"里 open run_acceptance.command
cd "$(dirname "$0")"
mkdir -p runs/acceptance
STAMP=$(date +%Y%m%d_%H%M)
cat <<'TXT'
================ 正式验收轮 ================
每样东西：从下往上穿过黄线 10 次（放入），再从上往下 10 次（拿出），动作之间停 1 秒。
顺序建议：香蕉 → 苹果 → 水瓶（或任何三样）。做完一样在终端里按回车记一下。
第 1 轮：COCO 通用模型 yolo11n.pt      按 o 开门，q 结束本轮
第 2 轮：自训食物模型 food_best.onnx  同上
============================================
TXT
echo "--- 第 1 轮：yolo11n.pt ---"
.venv/bin/python door_demo.py --trigger manual --model yolo11n.pt \
  --out "runs/acceptance/${STAMP}_coco.jsonl" --keyframes "runs/acceptance/${STAMP}_coco_kf" 2>&1 | tee "runs/acceptance/${STAMP}_coco.log"
echo "--- 第 2 轮：models/food_best.onnx ---"
.venv/bin/python door_demo.py --trigger manual --model models/food_best.onnx \
  --out "runs/acceptance/${STAMP}_food.jsonl" --keyframes "runs/acceptance/${STAMP}_food_kf" 2>&1 | tee "runs/acceptance/${STAMP}_food.log"
echo "两轮都结束。结果在 runs/acceptance/${STAMP}_*.jsonl（窗口可以关闭）"
