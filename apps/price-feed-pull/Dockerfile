# syntax=docker/dockerfile:1.7
FROM golang:1.25.1-alpine3.22 AS builder
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/price-feed-pull ./main.go

FROM alpine/git:2.49.1
COPY --from=builder /out/price-feed-pull /usr/local/bin/price-feed-pull
ENTRYPOINT ["/usr/local/bin/price-feed-pull"]
