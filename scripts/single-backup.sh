#!/bin/sh
# Write only to the new, ownership-marked backup filesystem. Never prune backups.
set -eu
: "${BACKUP_OWNER_ID:?Set the reviewed backup owner}"
printf '%s\n' "$BACKUP_OWNER_ID" | grep -Eq '^[a-f0-9]{32}$' || exit 1
cd /backups
if [ -f .nerkhbaan-owner ]; then
  [ "$(cat .nerkhbaan-owner)" = "$BACKUP_OWNER_ID" ] || exit 1
else
  [ -z "$(ls -A .)" ] || exit 1
  printf '%s\n' "$BACKUP_OWNER_ID" > .nerkhbaan-owner
fi
while :; do
  # Keep host free space and this bounded filesystem separate from old backups.
  available=$(df -Pk . | awk 'NR==2 {print $4}')
  used=$(du -sk . | awk '{print $1}')
  [ "$available" -ge 262144 ] && [ "$used" -lt 786432 ] || exit 1
  name="nerkhbaan-$(date -u +%Y%m%dT%H%M%SZ)-${BACKUP_OWNER_ID}.dump"
  [ ! -e "$name" ] && [ ! -e "$name.partial" ] || exit 1
  PGOPTIONS='-c jit=off' pg_dump -Fc --no-owner --no-acl -f "$name.partial"
  pg_restore -l "$name.partial" > /tmp/backup-toc.txt
  grep -q ' TABLE public ' /tmp/backup-toc.txt
  mv "$name.partial" "$name"
  sha256sum "$name" > "$name.sha256"
  date -u +%s > .last-success.tmp
  mv .last-success.tmp last-success
  printf 'Checked project backup completed.\n'
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
