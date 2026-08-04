#!/usr/bin/env sh
set -eu
while true; do
  sports-supermodel-settle
  sleep "${SPORTS_SUPERMODEL_SETTLEMENT_INTERVAL_SECONDS:-1800}"
done
