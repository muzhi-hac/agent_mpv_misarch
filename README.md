# MiSArch Agent Gateway Go

A small Go MCP gateway for the G11 Agentic Interoperability project. It exposes selected MiSArch Catalog capabilities as agent-facing MCP tools.

## Architecture

```text
External Agent
  -> MCP Streamable HTTP /mcp
  -> Go Agent Gateway
  -> MiSArch GraphQL Gateway :8080/graphql
  -> MiSArch Catalog Service
```

## Tools

- `list_products`: lists up to 10 public catalog products.
- `get_product`: gets one product by MiSArch product UUID.

Both tools are read-only and report `side_effects: none (read-only)`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HTTP_ADDR` | `127.0.0.1:8001` | Address for the local gateway. |
| `MISARCH_GRAPHQL_URL` | `http://localhost:8080/graphql` | MiSArch GraphQL Gateway URL. |
| `MISARCH_GRAPHQL_TIMEOUT` | `3s` | Upstream request timeout. |

## Local Run

```bash
go test ./...
go vet ./...
go run ./cmd/server
```

Health checks:

```bash
curl -s http://127.0.0.1:8001/healthz
curl -s -i http://127.0.0.1:8001/readyz
```

If MiSArch is not running, `/healthz` should return `200`, while `/readyz` should return `503`.

## Docker

```bash
docker build -t misarch-agent-gateway:day1 .
docker run --rm -p 8001:8001 misarch-agent-gateway:day1
```

When running against MiSArch inside Docker Compose, set `MISARCH_GRAPHQL_URL` to the reachable gateway URL for that network.

## Baseline

The planned comparison is:

- Raw MiSArch GraphQL: fast and expressive, but not agent-discoverable without schema knowledge.
- MCP Gateway: slower due to an adapter layer, but tools are discoverable, inputs are self-describing, and side effects are explicit.
