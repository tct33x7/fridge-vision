#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ ! -x .venv/bin/python ]; then
  echo "未找到 .venv；请先运行 ./install.sh" >&2
  exit 1
fi

host=${SMART_FRIDGE_HOST:-0.0.0.0}
port=${SMART_FRIDGE_PORT:-8000}

exec .venv/bin/python -m uvicorn app.main:app \
  --host "$host" \
  --port "$port" \
  --workers 1

