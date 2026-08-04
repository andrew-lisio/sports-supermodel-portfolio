#!/usr/bin/env sh
set -eu
sports-supermodel-public guard --service web
exec sports-supermodel-ui
