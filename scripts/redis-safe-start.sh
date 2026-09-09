#!/bin/sh

set -eu

checked=0
for candidate in /data/appendonlydir/*.base.rdb /data/*.base.rdb; do
    [ -f "$candidate" ] || continue
    checked=$((checked + 1))
    if ! redis-check-rdb "$candidate" >/tmp/redis-rdb-check.log 2>&1; then
        echo "Redis: unreadable RDB base file; data kept untouched."
        echo "Inspect /tmp/redis-rdb-check.log and restore from a checked backup."
        exit 1
    fi
done

for candidate in /data/appendonlydir/*.base.aof /data/appendonlydir/*.incr.aof /data/*.aof; do
    [ -f "$candidate" ] || continue
    checked=$((checked + 1))
    if ! redis-check-aof "$candidate" >/tmp/redis-aof-check.log 2>&1; then
        echo "Redis: unreadable AOF file; data kept untouched."
        echo "Inspect /tmp/redis-aof-check.log and restore from a checked backup."
        exit 1
    fi
done

echo "Redis: checked $checked persisted data file(s)."
exec redis-server \
    --appendonly yes \
    --appendfsync everysec \
    --maxmemory "${REDIS_MAXMEMORY:-384mb}" \
    --maxmemory-policy noeviction
