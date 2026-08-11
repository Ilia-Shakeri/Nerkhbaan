#!/bin/sh

set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yaml}"
DEPLOY_WAIT_SECONDS="${DEPLOY_WAIT_SECONDS:-240}"
PREVIOUS_COMMIT="unknown"

cd /opt/Nerkhbaan

deploy_logs() {
    docker compose -f "$COMPOSE_FILE" ps || true
    docker compose -f "$COMPOSE_FILE" logs --tail 120 backend frontend redis postgres migrate || true
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo "Deploy failed. Prior commit: $PREVIOUS_COMMIT"; deploy_logs; fi; exit "$status"' EXIT

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Deploy stopped: tracked worktree changes exist."
    exit 1
fi

PREVIOUS_COMMIT="$(git rev-parse HEAD)"
echo "==> Step 1/5: pull fast-forward source"
git pull --ff-only

echo "==> Step 2/5: validate production Compose"
docker compose -f "$COMPOSE_FILE" config --quiet

echo "==> Step 3/5: pull service images"
docker compose -f "$COMPOSE_FILE" pull --ignore-buildable

echo "==> Step 4/5: rebuild, recreate, and wait for health"
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate --wait --wait-timeout "$DEPLOY_WAIT_SECONDS"

echo "==> Step 5/5: show healthy service state"
docker compose -f "$COMPOSE_FILE" ps
docker compose -f "$COMPOSE_FILE" logs --tail 80 backend frontend redis postgres

trap - EXIT
echo "Deploy passed. Commit: $(git rev-parse HEAD)"
