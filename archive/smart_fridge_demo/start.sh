#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "错误：未找到 Linux 虚拟环境，请先运行 ./install.sh。"
  exit 1
fi

PORT="${PORT:-8000}"
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "错误：PORT 必须是 1 到 65535 之间的整数。"
  exit 1
fi

UVICORN_ARGS=(app.main:app --host 0.0.0.0 --port "$PORT")
if [[ -f .env ]]; then
  UVICORN_ARGS+=(--env-file .env)
fi

exec .venv/bin/python -m uvicorn "${UVICORN_ARGS[@]}"
