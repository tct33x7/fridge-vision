#!/bin/bash
# 管理 OrangePi 上的冰箱程序（板子上的 ~/smart_fridge_demo  ⇄  仓库里的 orangepi_app/）。
#
#   deploy/opi.sh status            服务、计数（待机/识别中）、硬盘、两边代码差异：只看不改
#   deploy/opi.sh diff              两边代码哪里不一样
#   deploy/opi.sh pull              板子 → 仓库（有人直接在板子上改过时用；之后 git diff 看改了什么）
#   deploy/opi.sh push [--yes]      仓库 → 板子；不加 --yes 只列出会改哪些文件；板子上有人改过时会停下
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
  --exclude .deployed
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

# 板子上记着上次部署的是哪个提交（~/smart_fridge_demo/.deployed）；没有记录时以 main 为准。
# 拿板子和那个版本比，列出部署之后被人直接在板子上改过的文件。
board_edits() {
  local base tmp
  base=$("${SSH[@]}" "head -1 ~/${REMOTE}.deployed 2>/dev/null" || true)
  git -C "$REPO" cat-file -e "${base:-main}^{commit}" 2>/dev/null || base=main
  tmp=$(mktemp -d)
  git -C "$REPO" archive "${base:-main}" orangepi_app | tar -x -C "$tmp"
  echo "  （对照的是上次部署的版本：$(git -C "$REPO" log -1 --format='%h %s' "${base:-main}" | cut -c1-60)）"
  "${RSYNC[@]}" --dry-run "$HOST:$REMOTE" "$tmp/orangepi_app/" | grep -E '^>f' | sed 's/^/  板子上被改过 /' || echo "  没有：部署之后没人在板子上改过代码"
  rm -rf "$tmp"
}

case "${1:-}" in
  status)
    echo "== 服务"
    "${SSH[@]}" 'printf "  smart-fridge：%s，开机自启：%s\n" "$(systemctl is-active smart-fridge)" "$(systemctl is-enabled smart-fridge)"; df -h / | awk "NR==2{print \"  硬盘剩余：\" \$4}"; ls ~/smart_fridge_demo/models/ | sed "s/^/  模型文件：/"'
    echo "== 计数"
    state_summary
    echo "== 板子上的代码有没有被人直接改过"
    board_edits
    echo "== push 会推过去的文件（当前分支：$(git -C "$REPO" branch --show-current)）"
    "${RSYNC[@]}" --dry-run "$LOCAL" "$HOST:$REMOTE" | grep -E '^<f' | sed 's/^/  /' || echo "  没有：板子和本地一样"
    ;;
  diff)
    echo "== push 会推过去的文件"
    "${RSYNC[@]}" --dry-run "$LOCAL" "$HOST:$REMOTE" | grep -E '^<f' || echo "  没有"
    echo "== 板子上被直接改过的文件（pull 会拉回来；对照上次部署的版本）"
    board_edits
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
    edits=$(board_edits | grep '板子上被改过' || true)
    if [ -n "$edits" ] && [ "${3:-}" != "--force" ]; then
      echo "$edits"
      echo "上次部署之后，有人直接在板子上改过上面这些文件。推送会覆盖它们，所以先停下。"
      echo "先 deploy/opi.sh pull 拉回来、提交、合并进当前分支，再推送（确定要覆盖就加 --force）。"
      exit 1
    fi
    if [ -n "$(git -C "$REPO" status --porcelain -- orangepi_app)" ]; then
      echo "提醒：orangepi_app/ 里有没提交的改动，这次也会推上去，但板子记录的版本里没有它们。"
    fi
    "${RSYNC[@]}" "$LOCAL" "$HOST:$REMOTE" | grep -E '^<f' || true
    "${SSH[@]}" "printf '%s\\n%s\\n' '$(git -C "$REPO" rev-parse HEAD)' '$(date '+%F %T') $(git -C "$REPO" branch --show-current)' > ~/${REMOTE}.deployed"
    echo "已推送代码（版本 $(git -C "$REPO" rev-parse --short HEAD)，记录在板子 .deployed 里）。重启服务后生效：deploy/opi.sh restart"
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
