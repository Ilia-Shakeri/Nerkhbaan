#!/bin/sh

set -eu

: "${RELEASE_DIR:?Set the reviewed absolute release checkout}"
cd "$RELEASE_DIR"
if command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/deploy_application.py
fi
exec python scripts/deploy_application.py
