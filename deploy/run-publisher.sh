#!/usr/bin/env sh
set -eu
sports-supermodel-public guard --service publisher
exec sports-supermodel-worker
