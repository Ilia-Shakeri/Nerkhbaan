#!/bin/sh
set -eu

: "${CERTBOT_TOKEN:?missing challenge token}"
: "${CERTBOT_VALIDATION:?missing challenge value}"

docker exec dolphin-nginx-1 mkdir -p /var/www/nerkhbaan-acme/.well-known/acme-challenge
printf '%s' "$CERTBOT_VALIDATION" | docker exec -i \
  -e CERTBOT_TOKEN="$CERTBOT_TOKEN" \
  dolphin-nginx-1 sh -c 'umask 022; cat > "/var/www/nerkhbaan-acme/.well-known/acme-challenge/$CERTBOT_TOKEN"'
