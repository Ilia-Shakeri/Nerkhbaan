# Redis data safety and deploy runbook

This project uses compose `redis` with AOF persistence.
Keep data safe by avoiding destructive cleanup by default.

## Why Redis is not optional

Redis holds the distributed refresh leases, the per-provider request budgets,
the WebSocket fan-out and the persistence outbox. It is not a cache you can drop
and degrade gracefully around: with Redis down, price refreshes are suspended
and the API reports `degraded`. Stored values keep serving; new ones do not
arrive.

## Memory policy

The eviction policy is `noeviction` on purpose. Evicting a budget counter or an
outbox entry would silently lose writes, so the deployment prefers to fail
loudly instead.

That makes `used_memory` an operational signal, not a curiosity:

```bash
docker compose exec redis redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'
```

Alert at 80% of `REDIS_MAXMEMORY` (default `384mb`). The dominant consumer is
the short volatility history, bounded by
`PRICING_SHORT_HISTORY_RETENTION_HOURS` (6) and
`PRICING_SHORT_HISTORY_MAX_ENTRIES` (240) per instrument. Durable history lives
in TimescaleDB, so lengthening the Redis window buys nothing and costs memory.

## Normal deploy (safe)

Use the checked deploy script. It rejects tracked local edits, requires current operator evidence, pulls by fast-forward only, validates production Compose, starts two API replicas by default, and waits for health:

```bash
cd /opt/Nerkhbaan && OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json COMPOSE_FILE=docker-compose.prod.yaml sh scripts/deploy-nerkhbaan-prod.sh
```

If backend and frontend are healthy, no recovery actions are needed.

## Redis startup check logic (current behavior)

- `docker-compose.yaml` and `docker-compose.prod.yaml` check every base RDB and base/incremental AOF file under `/data` and `/data/appendonlydir`.
- If any persisted file is unreadable, Redis exits with an error.
- This keeps `/data` untouched and prevents silent data-loss startup paths.

## Recovery path when Redis fails (data important)

If Redis fails with a format error:

```bash
docker compose -f docker-compose.prod.yaml logs -f redis --tail 120
```

Check the active volume name:

```bash
docker volume ls | grep redis
```

Validate the AOF file from a safe temporary container:

```bash
docker run --rm --name redis-aof-check \
  -v <redis_volume_name>:/data \
  redis:7.4-alpine \
  sh -lc 'for f in /data/appendonlydir/*.base.rdb /data/*.base.rdb; do [ ! -f "$f" ] || redis-check-rdb "$f"; done'
```

If corruption is confirmed, do a backup of current volume **before any cleanup**:

```bash
mkdir -p /opt/Nerkhbaan/backups/redis
docker run --rm \
  -v nerkhbaan_redis_data:/data \
  -v /opt/Nerkhbaan/backups/redis:/backup \
  alpine:3 \
  sh -lc 'tar -czf /backup/redis-data-$(date +%F_%H%M%S).tar.gz -C /data .'
```

Do not reset from this runbook. Restore the checked archive into a new volume, validate it, then switch volumes during a maintenance window with explicit data-owner approval.

After reset, monitor readiness:

```bash
docker compose -f docker-compose.prod.yaml logs -f redis --tail 80
```

## Recommended daily workflow

1. Check `git status --short` and resolve tracked server edits.
2. Run the deploy with a current `OPERATOR_EVIDENCE_PATH`.
3. If one service is unhealthy, inspect only that service log first.
4. Keep Redis recovery manual only; do not auto-delete data on normal deploy.

## One command for VPS deploy

Use this helper script:

```bash
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json sh scripts/deploy-nerkhbaan-prod.sh
```

You can keep it in crontab/CI with:

```bash
cd /opt/Nerkhbaan && OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json COMPOSE_FILE=docker-compose.prod.yaml sh scripts/deploy-nerkhbaan-prod.sh
```
