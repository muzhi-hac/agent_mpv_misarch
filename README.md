# MiSArch Agent Gateway Go

A Go MCP and A2A gateway for the G11 Agentic Interoperability project. It
exposes selected MiSArch Catalog capabilities as MCP tools and as a merchant
store-agent over the official A2A 1.0 JSON-RPC protocol.

## Learning guide

For the full Chinese walkthrough of the Google Cloud MiSArch deployment, MCP gateway deployment, and agent testing design, see:

- [docs/gcp-misarch-mcp-agent-testing.zh.md](docs/gcp-misarch-mcp-agent-testing.zh.md)
- [docs/presentation-prep.zh.md](docs/presentation-prep.zh.md)
- [REPRODUCTION.md](REPRODUCTION.md) for build, deployment, and evaluation steps
- [CONTRIBUTION.md](CONTRIBUTION.md) for the Group 11 work allocation

## Architecture

```text
External Agent
  -> MCP Streamable HTTP /mcp
     or A2A 1.0 JSON-RPC /a2a
  -> Go Agent Gateway
  -> MiSArch GraphQL Gateway :8080/graphql
  -> MiSArch Catalog / Shopping Cart / Order / Payment / Simulation services
```

## Why MCP for MiSArch?

MCP is not introduced as a faster replacement for GraphQL. Direct GraphQL is
the better choice for simple internal calls and latency-critical
service-to-service communication. The adapter exists because an external agent
benefits from a smaller, typed, discoverable capability surface with explicit
input validation and side-effect metadata.

The primary scenario is a controlled shopping assistant: discover catalog
products, inspect real product details, and, through a separately authorized
client, create a pending order without exposing the entire MiSArch schema. The
small tool set is an intentional least-privilege boundary, not an attempt to
mirror every GraphQL operation.

Use cases where MCP makes sense include external catalog assistants, product
exploration followed by a pending-order draft, and future read-only order
status, policy, recommendation, or observability capabilities. It is not a good
fit for exposing the whole GraphQL schema, direct database or internal event
access, administrative APIs, or automatic payment, refund, and shipment actions.

## Capability boundary

The MCP server does not expose payment processing, refund creation, shipment
dispatch, inventory administration, Keycloak administration, direct database
access, internal event publishing, or a generic `execute_graphql(query)` tool.
The evaluated MCP LLM agent applies an additional read-only allowlist and does
not offer `create_pending_order` to the model.

The A2A purchase flow described below is a separate experimental path. It has
an explicit two-message confirmation gate and is excluded from the normal
read-only benchmark. It should only be used against disposable local test data.

## A2A store-agent

The public Agent Card is served at `GET /.well-known/agent-card.json` and
advertises a `JSONRPC` interface at `POST /a2a`. The Go server uses the official
`github.com/a2aproject/a2a-go/v2` SDK and supports the standard `SendMessage`
task flow, structured DataPart artifacts, and `GetTask`. The Python Arm C butler
discovers the interface from the card and sends real A2A messages.

The A2A `purchase` skill uses a two-message confirmation flow. A complete first
request returns `TASK_STATE_INPUT_REQUIRED` without side effects. A continuation
for the same task/context with `confirmed=true` creates the cart item and
`PENDING` order, calls `placeOrder`, and waits for MiSArch's local Simulation
service to finish payment. Success means `Order.orderStatus=PLACED` and
`Payment.status=SUCCEEDED`; MiSArch does not define a `PAID` order status. No
external payment provider or real card network is contacted.

`POST /tasks` remains temporarily available only for compatibility with older
experiment/regression scripts. New callers should use the advertised `/a2a`
interface. Streaming, push notifications, durable task storage, signed cards,
and production A2A authentication are not enabled.

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
| `CORS_ALLOWED_ORIGINS` | `http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:6274,http://localhost:6274` | Comma-separated browser origins allowed to call the gateway directly. Defaults cover a local UI on `8080` and MCP Inspector UI on `6274`. |
| `MISARCH_KEYCLOAK_TOKEN_URL` | unset | Optional Keycloak token endpoint for authenticated write tools. |
| `MISARCH_KEYCLOAK_CLIENT_ID` | unset | Optional Keycloak client ID, e.g. `frontend`. |
| `MISARCH_KEYCLOAK_USERNAME` | unset | Optional demo user for authenticated write tools. |
| `MISARCH_KEYCLOAK_PASSWORD` | unset | Optional demo user password. |

All four `MISARCH_KEYCLOAK_*` variables must be set together. If they are unset, read-only tools still work, but authenticated MiSArch write operations such as `create_pending_order` will fail upstream.

## Complete local purchase E2E

The guarded runner requires an explicit execution flag and exact confirmation
text. It creates persistent test data, reserves inventory, and triggers the
order/payment/invoice saga, so use a disposable local test account and run one
purchase at a time:

```bash
python3 -m scripts.a2a_purchase_e2e \
  --a2a-url http://127.0.0.1:8001 \
  --user-id "$TEST_USER_ID" \
  --product-variant-id "$TEST_PRODUCT_VARIANT_ID" \
  --shipment-method-id "$TEST_SHIPMENT_METHOD_ID" \
  --shipment-address-id "$TEST_SHIPMENT_ADDRESS_ID" \
  --invoice-address-id "$TEST_INVOICE_ADDRESS_ID" \
  --payment-information-id "$TEST_PAYMENT_INFORMATION_ID" \
  --quantity 1 \
  --execute \
  --confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER" \
  --output tmp/a2a_purchase_e2e.json
```

For credit-card test data, add `--payment-cvc 123`. The CVC is sent to MiSArch
but is excluded from the JSON audit output. The repository has no verified
transactional cleanup for the downstream saga records.

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

Browser-based MCP clients send CORS preflight requests before calling `/mcp`,
especially when they include `Authorization`, `Content-Type`, or MCP session
and protocol headers. The gateway handles `OPTIONS` preflight requests and exposes
`Mcp-Session-Id` so a Streamable HTTP browser client can read the session ID.

For a custom browser UI origin:

```bash
CORS_ALLOWED_ORIGINS=http://127.0.0.1:8080,http://localhost:8080 \
go run ./cmd/server
```

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

## Four-pane iTerm video demo

With the local MiSArch stack and Agent Gateway running, load an OpenAI API key
into the current shell without echoing it:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY
export OPENAI_MODEL=gpt-5.5
export OPENAI_BASE_URL=https://yybb.dog
./scripts/open_iterm_four_arm_demo.sh
```

`OPENAI_MODEL` is optional and defaults to `gpt-5.5`.
`OPENAI_BASE_URL` is optional and defaults to the configured compatible gateway
at `https://yybb.dog`; only use that gateway if you trust it with the API key.
If that model is unavailable to the project, select another Structured
Outputs-compatible model, for example `OPENAI_MODEL=gpt-4o-mini`. Reasoning
effort defaults to `low` for GPT-5/o-series models and is omitted for other
models; set `OPENAI_REASONING_EFFORT` explicitly to override it.

In iTerm, choose **Shell → Broadcast Input → Broadcast Input to All Panes in
Current Tab**. Type the same English question and press Enter:

```text
Help me choose an inexpensive cup
```

The four panes make live, read-only protocol requests and then invoke four
independent OpenAI decision agents. Every pane stays active after a response,
so the presenter can broadcast additional questions. Enter `quit` or `exit` to
stop the panes. Each pane displays a summarized real protocol exchange, an
audit-friendly public decision trace, the final answer, the OpenAI response ID,
model, token usage, and protocol/model latency. It does not display private
chain-of-thought. The catalog query is extracted from each question and shown
in the trace; a query with no inventory returns an explicit no-match result
instead of substituting unrelated cup products.

- **A · Direct GraphQL** uses a schema-explorer agent that returns all four cup
  candidates without making one recommendation. Its trace highlights that the
  client must know the GraphQL schema in advance and performs no discovery.
- **B · MCP** uses a budget agent that discovers the available tools and selects
  the cheapest product. Its trace shows `initialize`, the session ID,
  `tools/list`, `tools/call`, and the structured tool result,
  `Budget Plastic Cup` at EUR 7.99.
- **D · MCP + Structured Profile** uses a profile-aware agent that applies the
  local stainless-steel preference and selects `Stainless Steel Cup 500ml` at
  EUR 24.99. Its trace also shows that the profile is applied locally and is
  absent from the store-facing `tools/call`.
- **C · A2A** discovers the Store Agent through its Agent Card, receives
  unranked candidates over the official A2A JSON-RPC interface, and uses a
  privacy-aware Butler policy to select the cheapest reusable non-plastic,
  non-premium option, `Borosilicate Glass Cup` at EUR 12.99, without sending
  those private preferences across the A2A boundary. Its trace shows the Agent
  Card read, advertised skills and binding, `SendMessage`, task/context IDs,
  artifact return, and local Butler decision.

The launcher idempotently ensures the four demo catalog products exist. The
interactive comparison itself does not create an order or trigger payment. It
makes four Responses API calls and therefore incurs the normal, small model
usage for the selected OpenAI model. The key is copied into a mode-0600
per-pane temporary environment file, deleted immediately after the pane loads
it, never printed, and never written to the repository.
