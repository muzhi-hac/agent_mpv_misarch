how an “agent-facing interface” should look in a real microservice system?????

Kubernetes?? with bug when deploying the system-----> to docker

Google Cloud Compute Engine and ran the original MiSArch Docker Compose stack on one VM.

deployment：Problem: login did not work at first. We thought maybe frontend or nginx was broken, but the real reason was Keycloak + HTTPS. Keycloak expected SSL for external login requests, but our GCP deployment only exposed HTTP ports. We did not have a domain/certificate ready, so for the demo we changed SSL Required to `none`.

??? This fixed the demo, but it is clearly a temporary workaround.



TODO: configure real HTTPS and restore Keycloak SSL requirement.  
The idea was simple: before touching MiSArch, we wanted to test whether an external agent can discover tools, call a backend service, and get real product data.

target system: MiSArch. MiSArch is much heavier than Telescope Store because it has many Docker Compose services, GraphQL gateway, catalog, order, Keycloak, databases, etc.

？can't access the url



TODO:  
solved: restart all conatiners, nginx has cache

 again？  
solved: wenn switching the net, the firewall shoud be set again

??? maybe nginx/browser cache: after frontend/proxy config changes, old page or old route behavior could still appear, so we had to re-check nginx config and redeploy/reload instead of assuming code did not change.

POST [https://yybb.codes/v1/responses](https://yybb.codes/v1/responses) failed: nodename nor servname provided, or not known  

 solved.llm api has some problems

can not find some service files, for example files under `user/`. The error looked like some `docker-compose-base.yaml` files were missing.  
solves: git submodules. MiSArch depends on submodules, so after cloning we had to run:

```bash
git submodule update --init --recursive
```

works  

Another issue was health checks. Some containers did not contain the tools expected by their healthcheck commands`t`.  
 some services had different actual health endpoints .

 We did not want to modify the upstream MiSArch Compose file directly, so we created a GCP-specific override file.  

The MiSArch system was deployed on a GCP VM, `misarch-compose`. The important runtime path on the VM was:

```text
/opt/misarch/infrastructure-docker
```

we implemented the actual MCP gateway in Go in `misarch-agent-gateway-go`. The gateway is a separate container, not part of the original MiSArch services. It connects to the MiSArch GraphQL gateway through Docker internal networking:

```text
MCP Gateway container
  -> http://gateway:8080/graphql
  -> MiSArch GraphQL Gateway
```

We used this internal URL instead of the public IP because both containers are on the same Docker network. This avoids sending internal service calls through the internet. ??? If we later deploy this with Kubernetes, this part needs to become a Kubernetes Service instead of a Docker Compose service name.  

The Go project was split into layers:

```text
cmd/server/main.go              starts the app
internal/config/config.go       reads env vars
internal/httpserver/server.go   exposes /healthz, /readyz, /mcp
internal/misarch/client.go      sends GraphQL requests
internal/catalog/service.go     maps GraphQL catalog data
internal/mcpserver/server.go    registers MCP tools
internal/order/service.go       controlled pending order prototype
```

The first real tools were:

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

This was important because the agent should not only get data, but also understand whether the tool changed anything. Raw GraphQL does not clearly tell the agent this.

implemented `create_pending_order`（not the main safe demo tool）.  
 It creates a shopping cart item and a pending order, but does not place the order or trigger payment.  
 TODO: the token should be dealed with to pass the problem( the GraphQL rejectes our request)  

A surprisingly annoying problem was MCP protocol handling. At first we thought we could just call `tools/list` directly, like a REST API. That failed. MCP Streamable HTTP needs this flow:

```text
initialize
-> read Mcp-Session-Id
-> notifications/initialized
-> tools/list
-> tools/call
```

If we skipped initialization, the server rejected the call. So we wrote smoke test scripts that do the full MCP session properly. This is one of the main things we learned: MCP is not just “REST with tool names”; the session lifecycle matters.

compared three access styles:

```text
Baseline A: fixed GraphQL executor
Baseline B: agent generates GraphQL query itself
MCP: agent discovers tools and calls MCP tools
```

Result: direct GraphQL is faster and more flexible, but the agent needs schema knowledge and has to generate the correct query. MCP is slower because it adds protocol and adapter overhead, but it gives the agent tool discovery, input schema, standardized output, and side-effect metadata.

One important issue: sometimes in the minimal GraphQL experiment, the agent-generated GraphQL path failed because the model generation timed out. This does not prove GraphQL is bad in general, but it shows that asking the model to generate raw GraphQL adds another failure point. With MCP, the agent does not need to invent the GraphQL query; it only needs to call `list_products` and `get_product`.

POST [https://yybb.codes/v1/responses](https://yybb.codes/v1/responses) failed: nodename nor servname provided, or not known  

.llm api sometimes has some problems

One real product returned by native MiSArch GraphQL

{

  "product_id": "0418eaa4-4621-427a-824b-0051097bd602",

  "variant_id": "934b29e0-4280-4c04-af2d-59d4625f8f3f",

  "name": "HomeLink Smart Plug Twin Pack",

  "description": "Two Wi-Fi smart plugs with scheduling and energy monitoring.",

  "retail_price_cents": 2799,

  "currency": "EUR",

  "categories": ["Electronics & Gadgets"]

}

The MCP gateway returned the same product through list_products(topK=2) and get_product:

`{`  
  `"products": [`  
    `{`  
      `"product_id": "0418eaa4-4621-427a-824b-0051097bd602",`  
      `"variant_id": "934b29e0-4280-4c04-af2d-59d4625f8f3f",`  
      `"name": "HomeLink Smart Plug Twin Pack",`  
      `"retail_price_cents": 2799,`  
      `"currency": "EUR",`  
      `"categories": ["Electronics & Gadgets"]`  
    `}`  
  `],`  
  `"returned_count": 2,`  
  `"runtime": "misarch-graphql-gateway",`  
  `"source_service": "catalog",`  
  `"side_effects": "none (read-only)"`  
`}`

second product， same real query :

`{`  
  `"product_id": "057fcca5-149d-4de8-ac46-ab836e57400d",`  
  `"name": "Crunchy Chicken Dog Treats 500g",`  
  `"description": "Oven-baked chicken treats for training rewards.",`  
  `"retail_price_cents": 799,`  
  `"currency": "EUR",`  
  `"categories": ["Pet Supplies"]`  
`}`

Current limitations / TODO:

```text
TODO: MCP endpoint still needs authentication.
TODO: add rate limiting before exposing this wider.
TODO: add audit logs for every tool call.
TODO: write negative tests for unsafe operations.
TODO: maybe expose more read-only MiSArch data, e.g. categories or inventory.
TODO: create_pending_order should require a stronger confirmation flow.
??? Need to decide whether order tools should be shown in final demo or only mentioned as future extension.
```

The final system :

```text
External Agent
  -> MCP endpoint on GCP VM
  -> Go MCP Gateway
  -> MiSArch GraphQL Gateway
  -> Catalog / Order services
```

