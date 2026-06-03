# MiSArch Agent Gateway Go

A small Go MCP gateway for the G11 Agentic Interoperability project. It exposes selected MiSArch Catalog capabilities as agent-facing MCP tools.

## Learning guide

For the full Chinese walkthrough of the Google Cloud MiSArch deployment, MCP gateway deployment, and agent testing design, see:

- [docs/gcp-misarch-mcp-agent-testing.zh.md](docs/gcp-misarch-mcp-agent-testing.zh.md)
- [docs/presentation-prep.zh.md](docs/presentation-prep.zh.md)

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
- `create_pending_order`: creates one shopping cart item and one `PENDING` order for a selected product variant.

The catalog tools are read-only and report `side_effects: none (read-only)`.
`create_pending_order` is intentionally low-side-effect: it does not place the order, does not trigger payment, and returns an explicit `next_action`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `HTTP_ADDR` | `127.0.0.1:8001` | Address for the local gateway. |
| `MISARCH_GRAPHQL_URL` | `http://localhost:8080/graphql` | MiSArch GraphQL Gateway URL. |
| `MISARCH_GRAPHQL_TIMEOUT` | `3s` | Upstream request timeout. |
| `MISARCH_KEYCLOAK_TOKEN_URL` | unset | Optional Keycloak token endpoint for authenticated write tools. |
| `MISARCH_KEYCLOAK_CLIENT_ID` | unset | Optional Keycloak client ID, e.g. `frontend`. |
| `MISARCH_KEYCLOAK_USERNAME` | unset | Optional demo user for authenticated write tools. |
| `MISARCH_KEYCLOAK_PASSWORD` | unset | Optional demo user password. |

All four `MISARCH_KEYCLOAK_*` variables must be set together. If they are unset, read-only tools still work, but authenticated MiSArch write operations such as `create_pending_order` will fail upstream.

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
