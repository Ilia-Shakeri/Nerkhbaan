FROM golang:1.26.10-alpine3.24 AS privilege_builder
RUN apk add --no-cache git
WORKDIR /src
RUN git init && git remote add origin https://github.com/tianon/gosu.git \
    && git fetch --depth=1 origin 29b939aa5bd4dc588af765b8248f6e39150d2565 \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = 29b939aa5bd4dc588af765b8248f6e39150d2565 \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -o /out/gosu .

FROM timescale/timescaledb@sha256:61f891691050da6032023c01ea885730eeeba06b7c17b403e7d0b9c49c37dfe9
RUN apk upgrade --no-cache
COPY --from=privilege_builder /out/gosu /usr/local/bin/gosu
# This deployment sets PostgreSQL budgets explicitly and restores through stdin.
# Omit unused bundled Go utilities rather than shipping their old runtimes.
RUN rm /usr/local/bin/timescaledb-tune /usr/local/bin/timescaledb-parallel-copy \
    && gosu postgres id -u
