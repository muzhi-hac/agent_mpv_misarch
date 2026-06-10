# Follow-up Note: What We Actually Implemented for the Baseline Prototype

Dear [Tutor's Name],

thank you for listening to our baseline presentation.

After the presentation we noticed that our slides probably looked too generic and did not show enough of our own implementation work. We want to clarify what we actually built, deployed, tested, and where we had problems.

This note is not meant as a polished final report. It is more like our current implementation log, because during the prototype we changed direction a few times and had several deployment problems.

## 1. What We Tried First

At the beginning we built a small Python MVP agent service around a product catalog.

The idea was:

- expose a chat endpoint;
- expose MCP-style product tools;
- query real product data instead of only hardcoded demo answers;
- test whether an agent can use structured tools instead of manually writing API calls.

In that first MVP we used:

- FastAPI for the backend;
- product catalog access;
- MCP-like tools such as `list_products`, `search_products`, and `get_product`;
- deployment on Google Cloud Run.

This was useful to understand the general idea, but it was not close enough to MiSArch yet. So we later moved the main prototype to a Go-based MCP gateway connected to MiSArch GraphQL.

TODO maybe explain this better in the final report: the Python MVP was our learning step, not the final baseline.

## 2. MiSArch Deployment

For the actual baseline prototype we deployed MiSArch on a Google Cloud VM.

Current deployment setup:

- VM name: `misarch-compose`
- MiSArch infrastructure path on VM: `/opt/misarch/infrastructure-docker`
- MCP gateway path on VM: `/opt/misarch/misarch-agent-gateway-go`
- public GraphQL endpoint: `http://34.40.117.201:8080/graphql`
- public MCP endpoint: `http://34.40.117.201:8001/mcp`
- MCP readiness endpoint: `http://34.40.117.201:8001/readyz`

The MCP gateway container joins the MiSArch Docker Compose network and calls GraphQL internally through:

```text
http://gateway:8080/graphql
```

This part was not smooth. Some problems we had:

- The MiSArch Docker repository needed submodules. At first some `docker-compose-base.yaml` files were missing, and we only understood later that we needed:

```bash
git submodule update --init --recursive
```

- Some healthchecks did not work in the GCP VM environment. For example, the Keycloak image did not have the command we expected for the healthcheck. We had to adjust the GCP compose override.

- Login / Keycloak HTTPS problem: during the deployment, login needed HTTPS because Keycloak had SSL required. But our demo deployment did not have a real TLS certificate configured. For the prototype we changed the Keycloak SSL requirement to `none` so login could work over HTTP.

  ??? This is okay only for the prototype. For production this is obviously not acceptable.

  TODO production version: configure HTTPS properly and restore stricter SSL settings.

- nginx / frontend proxy issues: we also spent time checking whether some responses were caused by nginx fallback/cache/old frontend behavior. We are still not 100% sure which part was browser cache vs nginx behavior vs old container state, so we should document this more carefully in the final report.

## 3. Why We Built a Go MCP Gateway

Our baseline comparison is:

1. Native MiSArch GraphQL access.
2. Our Go-based MCP gateway wrapping selected MiSArch GraphQL operations.

We did not want to replace GraphQL. The point was to test whether MCP gives a better interface for agentic interoperability.

Native GraphQL gives direct access, but the agent still needs to know:

- which query to write;
- what parameters are valid;
- whether the operation is read-only or has side effects;
- which service/runtime the query belongs to.

The MCP gateway exposes this more explicitly as tools.

Implemented tools:

- `list_products`
- `get_product`
- `create_pending_order`

For the baseline result we mainly used the read-only catalog tools, especially `list_products` and `get_product`. `create_pending_order` exists as a controlled side-effect prototype, but we did not use it as the main success metric.

## 4. Code Design

The final gateway is split into small Go packages instead of putting everything into one file.

Important files:

- `cmd/server/main.go`
  - starts the service;
  - loads config;
  - wires GraphQL client, catalog service, order service, MCP server, and HTTP server.

- `internal/config/config.go`
  - reads environment variables;
  - configures GraphQL URL, port, auth, and other runtime settings.

- `internal/httpserver/server.go`
  - exposes `/healthz`;
  - exposes `/readyz`;
  - exposes `/mcp`.

- `internal/misarch/client.go`
  - sends GraphQL requests to MiSArch;
  - keeps the MCP gateway independent from the concrete HTTP details.

- `internal/misarch/auth.go`
  - handles Keycloak token logic;
  - caches token instead of requesting a new one for every call.

- `internal/catalog/service.go`
  - implements catalog operations;
  - validates `top_k`;
  - validates product UUIDs;
  - maps GraphQL data into MCP tool output.

- `internal/order/service.go`
  - implements the controlled pending-order prototype;
  - creates cart item + pending order;
  - does not place or pay the order.

- `internal/mcpserver/server.go`
  - registers MCP tools;
  - defines tool input schemas;
  - defines side-effect/read-only information.

Design choice:

We kept MiSArch-specific GraphQL logic in service/client packages and kept MCP registration separate. This made it easier to compare "native GraphQL" vs "MCP gateway" without rewriting the business logic every time.

## 5. MCP Protocol Problem We Hit

One problem was that MCP over Streamable HTTP is not just a simple REST call.

At first we expected something like:

```text
POST /mcp -> tool result
```

But the correct flow needs session initialization:

1. send `initialize`;
2. read the `Mcp-Session-Id`;
3. send `notifications/initialized`;
4. call `tools/list`;
5. call `tools/call`.

This confused us for a while because a normal HTTP test did not behave like a normal REST endpoint.

## 6. Real Data Used

We seeded MiSArch with realistic catalog data.

Seed summary:

- categories: 10
- products: 100
- inventory items created: 12225

Example product returned by both native GraphQL and MCP:

```json
{
  "product_id": "0418eaa4-4621-427a-824b-0051097bd602",
  "name": "HomeLink Smart Plug Twin Pack",
  "description": "Two Wi-Fi smart plugs with scheduling and energy monitoring.",
  "retail_price_cents": 2799,
  "currency": "EUR",
  "categories": ["Electronics & Gadgets"]
}
```

A second product from the same real query was:

```json
{
  "product_id": "057fcca5-149d-4de8-ac46-ab836e57400d",
  "name": "Crunchy Chicken Dog Treats 500g",
  "description": "Oven-baked chicken treats for training rewards.",
  "retail_price_cents": 799,
  "currency": "EUR",
  "categories": ["Pet Supplies"]
}
```

Small note: the MCP `list_products` result returns the product summary fields. The full description is available from the native query/detail data, so we should be precise about this in the final version.

## 7. Baseline Result

We ran 5 trials comparing:

- native MiSArch GraphQL;
- Go MCP gateway.

Result:

| Metric | Native MiSArch GraphQL | Go MCP Gateway |
|---|---:|---:|
| Successful runs | 5/5 | 5/5 |
| Same core product data | 5/5 | 5/5 |
| Same product id | 5/5 | 5/5 |
| Same product name | 5/5 | 5/5 |
| Same price | 5/5 | 5/5 |
| Average latency | 147.76 ms | 318.37 ms |

Our interpretation:

MCP did not improve success rate in this simple catalog task, because direct GraphQL already worked. The useful part of MCP is that the interface is more self-describing for an agent:

- tool discovery;
- input schema;
- explicit read-only / side-effect information;
- runtime/source-service metadata.

The cost is latency overhead. In our 5-trial test, MCP was slower than direct GraphQL.

So our current result is not "MCP is faster". It is:

```text
MCP gives a more agent-friendly interface, but with overhead.
```

## 8. What Failed / What Is Still Weak

This is the part we probably did not explain well enough in the presentation.

Problems / weak points:

- The presentation slides looked too generic and did not show enough implementation evidence.
- The first MVP and final MiSArch gateway were mixed in our explanation, which made the story unclear.
- The raw test CSV also contains an exploratory agent-generated GraphQL run that failed because the external model endpoint could not be resolved:

```text
POST https://yybb.codes/v1/responses failed: nodename nor servname provided
```

This failed exploratory run should not be confused with the main native GraphQL vs MCP comparison.

- We need better screenshots/logs of the deployment itself.
- We should show the exact tool schemas and one real `tools/call` response in the final presentation.
- We should be more honest that our current test is small: 5 trials, catalog query only.

TODO:

- Add deployment screenshot.
- Add one MCP `tools/list` screenshot.
- Add one GraphQL request/response screenshot.
- Add clean appendix table instead of raw noisy CSV.
- In the final report, separate:
  - learning MVP;
  - MiSArch deployment;
  - final Go MCP gateway;
  - baseline evaluation.

## 9. What We Want To Discuss

We would like to discuss whether this baseline setup is acceptable:

- native MiSArch GraphQL as baseline;
- Go MCP gateway as our prototype;
- comparison based on same product task, same real data, success rate, returned fields, and latency;
- interpretation focused on agent interoperability instead of speed.

If helpful, we can bring:

- source code snippets;
- deployment commands/logs;
- clean 5-trial result table;
- raw logs, but only as backup because they are noisy.

