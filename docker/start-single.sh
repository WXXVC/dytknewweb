#!/bin/sh
set -eu

mkdir -p /run/nginx /app/data

python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 &
BACKEND_PID="$!"

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup INT TERM

nginx -g 'daemon off;' &
NGINX_PID="$!"

wait "$NGINX_PID"
