#!/bin/sh
set -eu

: "${CERTBOT_TOKEN:?missing challenge token}"

docker exec \
  -e CERTBOT_TOKEN="$CERTBOT_TOKEN" \
  dolphin-nginx-1 sh -c 'rm -f "/var/www/nerkhbaan-acme/.well-known/acme-challenge/$CERTBOT_TOKEN"'
