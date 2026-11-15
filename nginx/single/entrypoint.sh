#!/bin/sh
set -eu
: "${PUBLIC_HOST:?Set PUBLIC_HOST}"
: "${ADMIN_HOST:?Set ADMIN_HOST}"
: "${GATEWAY_CIDR:?Set the reviewed gateway address}"
for host in "$PUBLIC_HOST" "$ADMIN_HOST"; do
  case "$host" in *[!a-z0-9.-]*) exit 1;; esac
  [ "${#host}" -le 253 ] || exit 1
  printf '%s\n' "$host" | grep -Eq '^[a-z0-9][a-z0-9.-]*[a-z0-9]$' || exit 1
done
[ "$PUBLIC_HOST" != "$ADMIN_HOST" ] || exit 1
case "$GATEWAY_CIDR" in *[!0-9./]*) exit 1;; esac
printf '%s\n' "$GATEWAY_CIDR" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}/32$' || exit 1
printf '%s\n' "$GATEWAY_CIDR" | awk -F'[./]' '{for(i=1;i<=4;i++) if($i>255) exit 1}'
mkdir -p /tmp/nginx/client /tmp/nginx/proxy
envsubst '${PUBLIC_HOST} ${ADMIN_HOST} ${GATEWAY_CIDR}' \
  < /etc/nginx/single.conf.template > /tmp/nginx.conf
nginx -t -c /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
