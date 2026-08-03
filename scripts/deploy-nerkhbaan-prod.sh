#!/bin/sh

set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yaml}"
COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"

cd /opt/Nerkhbaan

echo "==> Step 1/4: pull repository"
git pull

echo "==> Step 2/4: pull images"
${COMPOSE_CMD} pull

echo "==> Step 3/4: rebuild and recreate stack"
${COMPOSE_CMD} up -d --build --force-recreate

echo "==> Step 4/4: show service states and recent logs"
${COMPOSE_CMD} ps
${COMPOSE_CMD} logs --tail 80 backend frontend redis postgres || true

echo "Deploy command finished. If a service is unhealthy, inspect service logs first."
