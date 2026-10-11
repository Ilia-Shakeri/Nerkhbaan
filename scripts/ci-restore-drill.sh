#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:?PGPORT is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${SOURCE_DATABASE:?SOURCE_DATABASE is required}"
: "${RESTORE_DATABASE:?RESTORE_DATABASE is required}"

if [[ "$SOURCE_DATABASE" == "$RESTORE_DATABASE" || ! "$RESTORE_DATABASE" =~ ^[a-zA-Z0-9_]+_restore(_[a-zA-Z0-9_]+)?$ ]]; then
  echo "Restore target must be a separate *_restore or *_restore_* database." >&2
  exit 1
fi

existing_target="$(psql -X -v ON_ERROR_STOP=1 --dbname="$SOURCE_DATABASE" --tuples-only --no-align \
  --command="SELECT 1 FROM pg_database WHERE datname='$RESTORE_DATABASE';")"
if [ -n "$existing_target" ]; then
  echo "Restore target already exists; choose a fresh isolated name. Existing data preserved." >&2
  exit 1
fi

fingerprint() {
  local database="$1" table order
  for table in users alerts canonical_quotes market_prices; do
    case "$table" in
      canonical_quotes) order='id,canonical_at' ;;
      market_prices) order='time,asset,region,source,row_to_json(t)::text' ;;
      *) order='id' ;;
    esac
    # COPY streams rows locally into a digest; customer values never reach logs.
    # Avoid string_agg's single-value limit for large historical datasets.
    psql -X -v ON_ERROR_STOP=1 --dbname="$database" \
      --command="COPY (SELECT row_to_json(t)::text FROM public.$table t ORDER BY $order) TO STDOUT;" |
      python3 -c 'import hashlib,sys; digest=hashlib.sha256(); count=0
for row in sys.stdin.buffer:
    digest.update(row); count+=1
print(sys.argv[1], count, digest.hexdigest())' "$table"
  done
}
source_fingerprint="$(fingerprint "$SOURCE_DATABASE")"
structure_sql="SELECT 'hypertables', count(*) FROM timescaledb_information.hypertables
UNION ALL SELECT 'chunks', count(*) FROM timescaledb_information.chunks
UNION ALL SELECT 'policies', count(*) FROM timescaledb_information.jobs WHERE proc_name LIKE 'policy_%'
UNION ALL SELECT 'continuous_aggregates', count(*) FROM timescaledb_information.continuous_aggregates ORDER BY 1;"
source_structure="$(psql -X -v ON_ERROR_STOP=1 --dbname="$SOURCE_DATABASE" --tuples-only --no-align --command="$structure_sql")"

dump_path="$(mktemp --suffix=.dump)"
restore_owned=false
cleanup() {
  rm -f -- "$dump_path"
  if [ "$restore_owned" = true ]; then
    dropdb --if-exists "$RESTORE_DATABASE"
  fi
}
trap cleanup EXIT

createdb "$RESTORE_DATABASE"
restore_owned=true
psql -X -v ON_ERROR_STOP=1 --dbname="$RESTORE_DATABASE" --command='CREATE EXTENSION IF NOT EXISTS timescaledb;'
psql -X -v ON_ERROR_STOP=1 --dbname="$RESTORE_DATABASE" --command='SELECT timescaledb_pre_restore();'
pg_dump --format=custom --no-owner --no-acl --file="$dump_path" "$SOURCE_DATABASE"
test -s "$dump_path"
pg_restore --exit-on-error --no-owner --no-acl --dbname="$RESTORE_DATABASE" "$dump_path"
# Keep restored cleanup and retention jobs idle. Releasing restore mode first
# can delete expired rows before the preserved snapshot is compared.
psql -X -v ON_ERROR_STOP=1 --dbname="$RESTORE_DATABASE" \
  --command='SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs WHERE job_id >= 1000;'
psql -X -v ON_ERROR_STOP=1 --dbname="$RESTORE_DATABASE" --command='SELECT timescaledb_post_restore();'

migration_count="$(psql --dbname="$RESTORE_DATABASE" --tuples-only --no-align --command='SELECT count(*) FROM schema_migrations;')"
user_table="$(psql --dbname="$RESTORE_DATABASE" --tuples-only --no-align --command="SELECT to_regclass('public.users');")"
test "$migration_count" -gt 0
test "$user_table" = "users"
restored_fingerprint="$(fingerprint "$RESTORE_DATABASE")"
restored_structure="$(psql -X -v ON_ERROR_STOP=1 --dbname="$RESTORE_DATABASE" --tuples-only --no-align --command="$structure_sql")"
test "$source_fingerprint" = "$restored_fingerprint"
test "$source_structure" = "$restored_structure"

if [ -n "${BACKUP_STATUS_FILE:-}" ]; then
  BACKUP_DUMP_BYTES="$(wc -c < "$dump_path")" python3 - <<'PY'
import json
import os
from datetime import UTC, datetime
from pathlib import Path
destination = Path(os.environ["BACKUP_STATUS_FILE"])
destination.parent.mkdir(parents=True, exist_ok=True)
now = datetime.now(UTC).isoformat()
record = {"last_backup_at": now, "last_restore_at": now, "backup_status": "ok", "restore_status": "ok", "verified": True, "size_bytes": int(os.environ["BACKUP_DUMP_BYTES"]), "source_database": os.environ["SOURCE_DATABASE"], "restore_database": os.environ["RESTORE_DATABASE"], "proof": "isolated-fingerprint-restore"}
temporary = destination.with_suffix(".tmp")
temporary.write_text(json.dumps(record), encoding="utf-8")
temporary.chmod(0o640)
temporary.replace(destination)
PY
fi

echo "RESTORE_DRILL_OK migrations=$migration_count data=equal hypertables=equal chunks=equal policies=equal"
