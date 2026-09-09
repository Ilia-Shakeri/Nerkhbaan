#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:?PGPORT is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${SOURCE_DATABASE:?SOURCE_DATABASE is required}"
: "${RESTORE_DATABASE:?RESTORE_DATABASE is required}"

dump_path="$(mktemp --suffix=.dump)"
cleanup() {
  rm -f -- "$dump_path"
  dropdb --if-exists "$RESTORE_DATABASE"
}
trap cleanup EXIT

dropdb --if-exists "$RESTORE_DATABASE"
createdb "$RESTORE_DATABASE"
pg_dump --format=custom --no-owner --no-acl --file="$dump_path" "$SOURCE_DATABASE"
test -s "$dump_path"
pg_restore --exit-on-error --no-owner --no-acl --dbname="$RESTORE_DATABASE" "$dump_path"

migration_count="$(psql --dbname="$RESTORE_DATABASE" --tuples-only --no-align --command='SELECT count(*) FROM schema_migrations;')"
user_table="$(psql --dbname="$RESTORE_DATABASE" --tuples-only --no-align --command="SELECT to_regclass('public.users');")"
test "$migration_count" -gt 0
test "$user_table" = "users"

echo "Restore drill passed with $migration_count migrations."
