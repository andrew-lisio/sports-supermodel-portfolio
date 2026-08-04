#!/usr/bin/env sh
set -eu
while true; do
  sports-supermodel-odds
  sleep "${SPORTS_SUPERMODEL_ODDS_INTERVAL_SECONDS:-600}"
done
