#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8501}"

sports-supermodel-worker &
worker_pid=$!

streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT}" \
  --server.headless=true &
web_pid=$!

shutdown() {
  kill "${worker_pid}" "${web_pid}" 2>/dev/null || true
  wait "${worker_pid}" "${web_pid}" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

wait -n "${worker_pid}" "${web_pid}"
exit_code=$?
shutdown
exit "${exit_code}"
