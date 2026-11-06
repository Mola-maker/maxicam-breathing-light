#!/bin/sh
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1
exec python3 -u main.py "$@"
