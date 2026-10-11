# syntax=docker/dockerfile:1.7
FROM golang:1.26.9-alpine3.24 AS builder
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/price-feed-pull ./main.go

FROM alpine:3.24
RUN apk upgrade --no-cache && apk add --no-cache git ca-certificates
COPY --from=builder /out/price-feed-pull /usr/local/bin/price-feed-pull
ENTRYPOINT ["/usr/local/bin/price-feed-pull"]
