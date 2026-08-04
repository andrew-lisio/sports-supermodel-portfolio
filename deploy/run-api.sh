#!/usr/bin/env sh
set -eu
exec sports-supermodel-api --host 0.0.0.0 --port "${PORT:-8080}"
