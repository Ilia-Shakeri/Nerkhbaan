FROM nginx:1.30.6-alpine3.24
RUN apk upgrade --no-cache
# Custom IPv4 listeners need no default-config rewrite or runtime package metadata.
RUN rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
