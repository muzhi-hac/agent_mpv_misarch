# Follow-up Implementation Log: MiSArch Agent / MCP Baseline

This is our follow-up note for the baseline presentation.  
We realized after the presentation that the slides did not show enough of what we actually implemented, deployed, debugged, and tested. The slides probably looked too generic, so this document is more concrete and closer to our real working notes.

## Starting Point / Question

Our original question was basically:

```text
How should an "agent-facing interface" look in a real microservice system?????
```

Before working directly with MiSArch, we first tried a smaller MVP to understand whether an external agent can:

- discover tools;
- call backend functions;
- get real product data;
- avoid manually inventing every API call.

That first MVP helped us understand the idea, but it was too simple. MiSArch is much heavier because it has Docker Compose services, GraphQL gateway, catalog/order services, Keycloak, databases, frontend/proxy setup, etc. So the main prototype became a Go MCP gateway connected to the real MiSArch GraphQL gateway.

## Deployment

We deployed MiSArch on a Google Cloud Compute Engine VM and ran the original MiSArch Docker Compose stack there.

Current deployment:

```text
VM: misarch-compose
MiSArch path: /opt/misarch/infrastructure-docker
MCP gateway path: /opt/misarch/misarch-agent-gateway-go
GraphQL endpoint: http://34.40.117.201:8080/graphql
MCP endpoint: http://34.40.117.201:8001/mcp
Readiness: http://34.40.117.201:8001/readyz
```

We first thought about Kubernetes, but for the baseline prototype we moved to Docker Compose on one VM because it was easier to debug and closer to the provided MiSArch setup.  
TODO maybe Kubernetes would be the better final deployment, but not for the first baseline.

## Deployment Problems We Had

### 1. Missing compose files

At some point the deployment failed because files such as `docker-compose-base.yaml` were missing. At first we thought maybe the repository was incomplete or our path was wrong.

Actual reason: MiSArch depends on git submodules.

Fix:

```bash
git submodule update --init --recursive
```

After this the missing service files were available.

### 2. Login / HTTPS / Keycloak problem

Login did not work at first.

We first suspected the frontend or nginx/proxy. Later we found the more important problem: Keycloak expected SSL for external login requests, but our GCP demo deployment only exposed HTTP ports. We did not have a domain and certificate ready.

Temporary prototype fix:

```text
Keycloak SSL Required -> none
```

??? This fixed login for the demo, but it is clearly only a workaround.

TODO for production:

- configure real HTTPS;
- use a domain/certificate;
- restore the stricter Keycloak SSL requirement.

### 3. nginx / old frontend behavior / cache-like problem

We also had a problem where the URL or frontend behavior did not update as expected. We first thought the backend was still broken, but after restarting/redeploying containers and checking nginx/frontend routing, it worked again.

We wrote "nginx cache" in our notes, but to be precise we are not 100% sure whether it was real nginx cache, browser cache, or an old container/frontend state.

??? Need to document this more carefully.

Practical fix we used:

- restart/redeploy affected containers;
- re-check nginx config;
- avoid assuming the new config is active before testing.

### 4. Firewall / network issue

When switching network settings, the public endpoint was not reachable again. We had to check the GCP firewall rules and exposed ports again.

This was a boring problem but cost time because from the app side it just looked like "can't access the URL".

### 5. Healthcheck problems

Some containers did not contain the tools expected by their healthcheck commands. Some services also had different actual health endpoints/ports than we first expected.

We did not want to modify the upstream MiSArch Compose files directly, so we used a GCP-specific override file.

TODO: include the exact override file in the final report appendix.

## Gateway Architecture

We implemented the actual MCP gateway in Go in `misarch-agent-gateway-go`.

The gateway is a separate container. It is not part of the original MiSArch services. It joins the same Docker network and calls the MiSArch GraphQL gateway internally:

```text
External Agent
  -> MCP endpoint on GCP VM
  -> Go MCP Gateway
  -> http://gateway:8080/graphql
  -> MiSArch GraphQL Gateway
  -> Catalog / Order services
```

We used the internal Docker URL instead of calling the public IP from inside the VM:

```text
http://gateway:8080/graphql
```

Reason: both containers are on the same Docker network, so internal calls do not need to leave the Docker network.

??? If we later deploy this with Kubernetes, this should become a Kubernetes Service instead of a Docker Compose service name.

## Code Design

The Go project is split into layers:

```text
cmd/server/main.go              starts the app and wires everything together
internal/config/config.go       reads environment variables
internal/httpserver/server.go   exposes /healthz, /readyz, /mcp
internal/misarch/client.go      sends GraphQL requests
internal/misarch/auth.go        handles Keycloak token logic
internal/catalog/service.go     maps GraphQL catalog data to tool output
internal/order/service.go       controlled pending order prototype
internal/mcpserver/server.go    registers MCP tools and tool schemas
```

The main read-only tools are:

```text
list_products
get_product
```

Both are read-only. We added metadata in the response, for example:

```text
runtime = misarch-graphql-gateway
source_service = catalog
side_effects = none (read-only)
```

This is one reason why MCP is interesting for us. The agent does not only get raw data; it can also discover what tools exist, what inputs they need, and whether they have side effects.

Native GraphQL is more direct, but the agent needs more schema knowledge and has to construct the query correctly.

## Side-Effect Tool Prototype

We also implemented:

```text
create_pending_order
```

This is not the main safe demo tool.

It creates a shopping cart item and a pending order, but it does not place the order or trigger payment. We added it to understand how MCP could describe a tool with side effects.

TODO:

- stronger confirmation flow;
- better negative tests;
- maybe hide this from the final demo and only mention it as extension;
- check auth/token handling carefully for this workflow.

## MCP Protocol Problem

A surprisingly annoying problem was MCP Streamable HTTP.

At first we thought we could call `tools/list` directly like a REST API:

```text
POST /mcp -> tool result
```

This failed.

The actual flow needs session initialization:

```text
initialize
-> read Mcp-Session-Id
-> notifications/initialized
-> tools/list
-> tools/call
```

If we skipped initialization, the server rejected the call. So we wrote smoke test scripts that do the full MCP session properly.

This was one of the main implementation lessons:

```text
MCP is not just REST with tool names. The session lifecycle matters.
```

## Baseline Comparison

We compared:

```text
Baseline A: native MiSArch GraphQL access
MCP: Go MCP gateway wrapping selected MiSArch GraphQL operations
```

We also tried an exploratory path where an LLM generates GraphQL queries itself. That failed in one minimal experiment because the external model endpoint could not be resolved:

```text
POST https://yybb.codes/v1/responses failed:
nodename nor servname provided, or not known
```

Important: this failed LLM-generated GraphQL run is not the main baseline result. It only shows that asking the model to generate raw GraphQL adds another failure point. The main reported comparison is native GraphQL vs MCP gateway.

## Result

We ran 5 trials for the main baseline comparison.

| Metric | Native MiSArch GraphQL | Go MCP Gateway |
|---|---:|---:|
| Successful runs | 5/5 | 5/5 |
| Same core product data | 5/5 | 5/5 |
| Same product id | 5/5 | 5/5 |
| Same product name | 5/5 | 5/5 |
| Same price | 5/5 | 5/5 |
| Average latency | 147.76 ms | 318.37 ms |

Our current interpretation:

```text
Direct GraphQL is faster.
MCP adds overhead.
MCP gives a more agent-friendly and self-describing interface.
```

So we do not claim that MCP is faster. Our claim is that MCP makes the interface easier for agents to discover and use, especially because of tool schemas, side-effect metadata, and standardized tool calls.

## Real Product Data

One real product returned by native MiSArch GraphQL:

```json
{
  "product_id": "0418eaa4-4621-427a-824b-0051097bd602",
  "variant_id": "934b29e0-4280-4c04-af2d-59d4625f8f3f",
  "name": "HomeLink Smart Plug Twin Pack",
  "description": "Two Wi-Fi smart plugs with scheduling and energy monitoring.",
  "retail_price_cents": 2799,
  "currency": "EUR",
  "categories": ["Electronics & Gadgets"]
}
```

The MCP gateway returned the same core product through `list_products(top_k=2)` and `get_product`.

Shortened MCP example:

```json
{
  "products": [
    {
      "product_id": "0418eaa4-4621-427a-824b-0051097bd602",
      "variant_id": "934b29e0-4280-4c04-af2d-59d4625f8f3f",
      "name": "HomeLink Smart Plug Twin Pack",
      "retail_price_cents": 2799,
      "currency": "EUR",
      "categories": ["Electronics & Gadgets"]
    }
  ],
  "returned_count": 2,
  "runtime": "misarch-graphql-gateway",
  "source_service": "catalog",
  "side_effects": "none (read-only)"
}
```

Note: this example is shortened. `returned_count = 2` because the actual call returned two products.

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

## Current Limitations / TODO

TODO: MCP endpoint still needs stronger authentication.

TODO: add rate limiting before exposing this wider.

TODO: add audit logs for every tool call.

TODO: write negative tests for unsafe operations.

TODO: expose more read-only MiSArch data, for example categories or inventory.

TODO: decide whether `create_pending_order` should be shown in the final demo or only mentioned as a future extension.

TODO: add screenshots:

- VM / Docker containers running;
- GraphQL request;
- MCP `tools/list`;
- MCP `tools/call`;
- clean result table.

