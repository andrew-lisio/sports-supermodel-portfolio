#!/usr/bin/env sh
set -eu
sports-supermodel-public guard --service odds
while true; do
  sports-supermodel-odds
  sleep "${SPORTS_SUPERMODEL_ODDS_INTERVAL_SECONDS:-600}"
done
