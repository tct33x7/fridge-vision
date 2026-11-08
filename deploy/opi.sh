#!/bin/bash
# 管理 OrangePi 上的冰箱程序（板子上的 ~/smart_fridge_demo  ⇄  仓库里的 orangepi_app/）。
#
#   deploy/opi.sh status            服务、计数（待机/识别中）、硬盘、两边代码差异：只看不改
#   deploy/opi.sh diff              两边代码哪里不一样
#   deploy/opi.sh pull              板子 → 仓库（有人直接在板子上改过时用；之后 git diff 看改了什么）
#   deploy/opi.sh push [--yes]      仓库 → 板子；不加 --yes 只列出会改哪些文件
#   deploy/opi.sh models            把 orangepi_app/models/ 里的模型传到板子（模型不进 git）
#   deploy/opi.sh env [KEY=VALUE…]  看板子 .env 里计数和待机的设置；带参数就修改（先自动备份 .env）
#   deploy/opi.sh deploy            = push --yes + models，然后提示重启
#   deploy/opi.sh restart           重启服务（会让你输入板子的 sudo 密码），再显示状态
#   deploy/opi.sh logs              实时日志（Ctrl+C 退出），开门 / 待机记录以 [door] 开头
#   deploy/opi.sh backup            整个程序（含数据库、配置，不含 .venv）打包到 private/opi_backups/
#
# 永远不同步：.env、.venv、storage（数据库、图片）、模型、config/api_settings.json（密钥）、日志。
# 不删除板子上多出来的文件。连接用 ~/.ssh/config 里的 Host opi；换主机时设 OPI_HOST。
set -euo pipefail

HOST="${OPI_HOST:-opi}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$REPO/orangepi_app/"
REMOTE="smart_fridge_demo/"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST")

EXCLUDES=(
  --exclude .venv --exclude storage --exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store
  --exclude .env --exclude '.env.*' --exclude config/api_settings.json
  --exclude '*.pt' --exclude '*.onnx' --exclude '*.db' --exclude '*.sqlite*'
  --exclude logs --exclude backups --exclude uploads --exclude processed --exclude 'test food.jpg'
  --exclude smart-fridge.service.deployed --exclude ORANGEPI.md --exclude tests --exclude tools
)
# -c 按内容比较（git 不保留修改时间，按时间比会把没改的文件也算进来）
RSYNC=(rsync -rlc --itemize-changes -e "ssh -o BatchMode=yes" "${EXCLUDES[@]}")

state_summary() {
  "${SSH[@]}" 'curl -s -m 5 http://127.0.0.1:8080/api/counter/state' | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("  计数接口没有响应（服务可能没在运行）"); sys.exit()
st = {"standby": "待机", "active": "识别中"}.get(d.get("door_state"), "?（旧版程序没有待机）")
if d.get("paused"):
    st = "已暂停（摄像头页面占用中）"
print("  状态：%s   %s" % (st, d.get("status")))
print("  模型：%s   规则：%s   帧率：%s   画面变化：%s" % (d.get("model"), d.get("preset"), d.get("fps"), d.get("motion")))
if d.get("error"):
    print("  错误：%s" % d["error"])
for s in (d.get("sessions") or [])[:5]:
    print("  开门 #%s %s–%s %s 秒 计数 %s（醒：%s；睡：%s）" % (
        s["n"], s["start"], s.get("end", ""), s.get("seconds"), s["events"], s["wake"], s.get("sleep")))
'
}

case "${1:-}" in
  status)
    echo "== 服务"
    "${SSH[@]}" 'printf "  smart-fridge：%s，开机自启：%s\n" "$(systemctl is-active smart-fridge)" "$(systemctl is-enabled smart-fridge)"; df -h / | awk "NR==2{print \"  硬盘剩余：\" \$4}"; ls ~/smart_fridge_demo/models/ | sed "s/^/  模型文件：/"'
    echo "== 计数"
    state_summary
    echo "== 代码（> 仓库会推到板子 / < 板子比仓库新）"
    { "${RSYNC[@]}" --dry-run "$LOCAL" "$HOST:$REMOTE" | grep -v '/$' | sed 's/^/  推送 /'; \
      "${RSYNC[@]}" --dry-run "$HOST:$REMOTE" "$LOCAL" | grep -v '/$' | sed 's/^/  拉回 /'; } || true
    ;;
  diff)
    echo "== 仓库 → 板子（push 会推过去）"
    "${RSYNC[@]}" --dry-run "$LOCAL" "$HOST:$REMOTE" | grep -v '/$' || true
    echo "== 板子 → 仓库（pull 会拉回来）"
    "${RSYNC[@]}" --dry-run "$HOST:$REMOTE" "$LOCAL" | grep -v '/$' || true
    ;;
  pull)
    "${RSYNC[@]}" "$HOST:$REMOTE" "$LOCAL" | grep -v '/$' || true
    echo "已拉回。用 git status / git diff orangepi_app 看改了什么。"
    ;;
  push)
    if [ "${2:-}" != "--yes" ]; then
      echo "== 将推送到板子的文件（还没改动；确认后加 --yes）"
      "${RSYNC[@]}" --dry-run "$LOCAL" "$HOST:$REMOTE" | grep -v '/$' || true
      exit 0
    fi
    "${RSYNC[@]}" "$LOCAL" "$HOST:$REMOTE" | grep -v '/$' || true
    echo "已推送代码。重启服务后生效：deploy/opi.sh restart"
    ;;
  models)
    shopt -s nullglob
    files=("$REPO"/orangepi_app/models/*.onnx "$REPO"/orangepi_app/models/*.pt)
    [ ${#files[@]} -eq 0 ] && { echo "orangepi_app/models/ 里没有模型文件"; exit 1; }
    rsync -c --progress -e "ssh -o BatchMode=yes" "${files[@]}" "$HOST:${REMOTE}models/"
    ;;
  env)
    shift
    if [ $# -eq 0 ]; then
      "${SSH[@]}" "grep -E '^SMART_FRIDGE_(COUNTER|DOOR|CAMERA_DEVICE|CAMERA_FPS)' ~/${REMOTE}.env || true"
      exit 0
    fi
    ts=$(date +%Y%m%d_%H%M%S)
    "${SSH[@]}" "cp ~/${REMOTE}.env ~/${REMOTE}.env.bak.$ts"
    for kv in "$@"; do
      key="${kv%%=*}"; val="${kv#*=}"
      [[ "$key" =~ ^SMART_FRIDGE_[A-Z0-9_]+$ ]] || { echo "只允许改 SMART_FRIDGE_ 开头的设置：$key"; exit 1; }
      "${SSH[@]}" "f=~/${REMOTE}.env; if grep -q '^$key=' \$f; then sed -i 's|^$key=.*|$key=$val|' \$f; else echo '$key=$val' >> \$f; fi"
      echo "已设置 $key=$val"
    done
    echo "原来的 .env 备份在板子上：~/${REMOTE}.env.bak.$ts 。重启服务后生效：deploy/opi.sh restart"
    ;;
  deploy)
    "$0" push --yes
    "$0" models
    echo "代码和模型都已上传。下一步：deploy/opi.sh restart"
    ;;
  restart)
    echo "重启 smart-fridge（输入的是板子的 sudo 密码）…"
    ssh -t "$HOST" 'sudo systemctl restart smart-fridge'
    echo "等 15 秒让模型加载…"; sleep 15
    "$0" status
    ;;
  logs)
    ssh "$HOST" "journalctl -u smart-fridge -f -n 50 | grep --line-buffered -vE 'cap.cpp|VIDIOC|GET /api/(camera|counter)/(status|state)'"
    ;;
  backup)
    mkdir -p "$REPO/private/opi_backups"
    f="$REPO/private/opi_backups/smart_fridge_demo_$(date +%Y%m%d_%H%M).tar.gz"
    "${SSH[@]}" "cd ~ && tar czf - --exclude=${REMOTE}.venv --exclude='*/__pycache__' ${REMOTE%/}" > "$f"
    echo "已备份：$f（$(du -h "$f" | cut -f1)）"
    ;;
  *)
    sed -n '2,17p' "$0"
    exit 1
    ;;
esac
