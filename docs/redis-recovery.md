# Redis data safety and deploy runbook

This project uses compose `redis` with AOF persistence.
Keep data safe by avoiding destructive cleanup by default.

## Normal deploy (safe)

Use this command flow each time after `git pull`:

```bash
cd /opt/Nerkhbaan
git pull
git status --short
docker compose -f docker-compose.prod.yaml pull
docker compose -f docker-compose.prod.yaml up -d --build --force-recreate
docker compose -f docker-compose.prod.yaml ps
docker compose -f docker-compose.prod.yaml logs -f backend frontend | sed -n '1,120p'
```

If backend and frontend are healthy, no recovery actions are needed.

## Redis startup check logic (current behavior)

- `docker-compose.yaml` and `docker-compose.prod.yaml` run a startup check for:
  - `/data/appendonly.aof.13.base.rdb`
- If that file exists and is unreadable, Redis exits with an error.
- This keeps `/data` untouched and prevents silent data-loss startup paths.

## Recovery path when Redis fails (data important)

If Redis fails with a format error:

```bash
docker compose -f docker-compose.prod.yaml logs -f nerkhbaan-redis --tail 120
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
  sh -lc 'redis-check-rdb /data/appendonly.aof.13.base.rdb'
```

Example:

```bash
docker run --rm --name redis-aof-check \
  -v nerkhbaan_redis_data:/data \
  redis:7.4-alpine \
  sh -lc 'redis-check-rdb /data/appendonly.aof.13.base.rdb'
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

Then do one controlled reset only if you accept losing Redis cache/state:

```bash
docker run --rm -v nerkhbaan_redis_data:/data alpine:3 sh -lc 'rm -f /data/appendonly.aof* /data/*.rdb /data/dump.rdb'
docker compose -f docker-compose.prod.yaml up -d redis
```

After reset, monitor readiness:

```bash
docker compose -f docker-compose.prod.yaml logs -f nerkhbaan-redis --tail 80
```

## Recommended daily workflow

1. `git pull`
2. `docker compose -f docker-compose.prod.yaml up -d --build --force-recreate`
3. if one service is unhealthy, inspect only that service log first.
4. keep Redis recovery manual only; do not auto-delete data on normal deploy.

## One command for VPS deploy

Use this helper script:

```bash
sh scripts/deploy-nerkhbaan-prod.sh
```

You can keep it in crontab/CI with:

```bash
cd /opt/Nerkhbaan && COMPOSE_FILE=docker-compose.prod.yaml sh scripts/deploy-nerkhbaan-prod.sh
```
