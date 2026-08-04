#!/usr/bin/env sh
set -eu
sports-supermodel-public guard --service api
exec sports-supermodel-api --host 0.0.0.0 --port "${PORT:-8080}"
