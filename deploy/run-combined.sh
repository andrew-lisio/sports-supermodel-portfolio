#!/usr/bin/env bash
set -euo pipefail

sports-supermodel-public guard --service combined

PORT="${PORT:-8501}"

if [[ "${SPORTS_SUPERMODEL_STORAGE_BACKEND:-local}" == "postgres" ]]; then
  sports-supermodel-storage migrate
fi

sports-supermodel-worker --require-odds &
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
