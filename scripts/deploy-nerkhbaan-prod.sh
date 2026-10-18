#!/bin/sh

set -eu

: "${RELEASE_DIR:?Set the reviewed absolute release checkout}"
GUARD_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$RELEASE_DIR"
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$GUARD_SCRIPT_DIR/deploy_application.py"
fi
exec python "$GUARD_SCRIPT_DIR/deploy_application.py"
