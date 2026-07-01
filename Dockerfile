FROM golang:1.25-alpine AS builder

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/misarch-agent-gateway ./cmd/server

FROM alpine:3.22

RUN adduser -D -H -s /sbin/nologin appuser

COPY --from=builder /out/misarch-agent-gateway /usr/local/bin/misarch-agent-gateway

USER appuser
EXPOSE 8001

ENV HTTP_ADDR=:8001
ENV PUBLIC_BASE_URL=http://127.0.0.1:8001
ENV MISARCH_GRAPHQL_URL=http://host.docker.internal:8080/graphql
ENV MISARCH_GRAPHQL_TIMEOUT=3s

ENTRYPOINT ["/usr/local/bin/misarch-agent-gateway"]
