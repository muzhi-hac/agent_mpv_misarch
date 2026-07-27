# Cloudflare Free Front Door Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing Go A2A store-agent through a Cloudflare Workers Free `workers.dev` endpoint without enabling any paid Cloudflare product.

**Architecture:** A small TypeScript Worker is a stateless HTTPS front door for the existing publicly reachable Go origin. It forwards health and A2A JSON-RPC requests, rewrites the public Agent Card interface URL to the Worker URL, and does not use Containers, Durable Objects, KV, D1, R2, Queues, paid routes, or a custom domain. The Go origin remains responsible for the official A2A protocol and MiSArch GraphQL calls.

**Tech Stack:** Cloudflare Workers Free, TypeScript, Wrangler, Vitest, existing Go A2A server.

---

### Task 1: Scaffold a free-only Worker

**Files:**
- Create: `cloudflare/a2a-front-door/package.json`
- Create: `cloudflare/a2a-front-door/tsconfig.json`
- Create: `cloudflare/a2a-front-door/wrangler.jsonc`
- Create: `cloudflare/a2a-front-door/src/index.ts`
- Create: `cloudflare/a2a-front-door/src/index.test.ts`
- Modify: `.gitignore`

- [ ] **Step 1: Add the failing route tests**

Test that only these routes are accepted:

```text
GET  /.well-known/agent-card.json
POST /a2a
GET  /healthz
GET  /readyz
```

Assert all other routes return 404 and `/tasks` is not exposed publicly.

- [ ] **Step 2: Run the tests**

Run:

```bash
npm --prefix cloudflare/a2a-front-door test
```

Expected: FAIL because the Worker entrypoint does not exist.

- [ ] **Step 3: Add the free-only Wrangler configuration**

Use:

```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "misarch-a2a-store-agent",
  "main": "src/index.ts",
  "compatibility_date": "2026-07-27",
  "workers_dev": true,
  "preview_urls": false,
  "vars": {
    "ORIGIN_BASE_URL": "https://replace-with-public-go-origin.example"
  }
}
```

Do not configure `containers`, `durable_objects`, `kv_namespaces`, `d1_databases`, `r2_buckets`, `queues`, `routes`, or a custom domain.

- [ ] **Step 4: Implement strict route forwarding**

Forward the allowed method/path pairs to `ORIGIN_BASE_URL`, preserve `A2A-Version`, `A2A-Extensions`, authorization, content type, and request body, and copy the origin status/body/content type back to the caller.

- [ ] **Step 5: Run unit tests and dry-run bundling**

Run:

```bash
npm --prefix cloudflare/a2a-front-door test
npx --prefix cloudflare/a2a-front-door wrangler deploy --dry-run
```

Expected: PASS and a Worker bundle below the Workers Free 3 MB compressed limit.

### Task 2: Rewrite Agent Card discovery safely

**Files:**
- Modify: `cloudflare/a2a-front-door/src/index.ts`
- Modify: `cloudflare/a2a-front-door/src/index.test.ts`

- [ ] **Step 1: Add a failing card rewrite test**

Given an origin card advertising `https://origin.example/a2a`, assert the public response advertises:

```json
{
  "supportedInterfaces": [
    {
      "url": "https://misarch-a2a-store-agent.example.workers.dev/a2a",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ]
}
```

Preserve every other standard card field and set `Cache-Control: public, max-age=60`.

- [ ] **Step 2: Implement request-origin rewrite**

Build the public interface URL from `new URL(request.url).origin + "/a2a"`; do not hard-code the account subdomain.

- [ ] **Step 3: Run tests**

Run:

```bash
npm --prefix cloudflare/a2a-front-door test
```

Expected: PASS.

### Task 3: Verify the no-billing deployment gate

**Files:**
- Create: `cloudflare/a2a-front-door/DEPLOY.md`

- [ ] **Step 1: Authenticate without sharing tokens**

The account owner runs:

```bash
npx --prefix cloudflare/a2a-front-door wrangler login
```

Alternatively, place a scoped `CLOUDFLARE_API_TOKEN` only in the local environment. Never paste the token into chat or commit it.

- [ ] **Step 2: Verify account and plan in the dashboard**

Before deployment, confirm:

```text
Workers plan: Free
Workers Paid subscription: absent
Cloudflare Containers: not enabled
Worker target: *.workers.dev
Custom domain purchase: none
```

If the account is on Workers Paid, stop and use a separate Workers Free account; do not deploy under a paid account.

- [ ] **Step 3: Re-run the configuration audit**

Run:

```bash
rg -n '"(containers|durable_objects|kv_namespaces|d1_databases|r2_buckets|queues|routes)"' cloudflare/a2a-front-door/wrangler.jsonc
npx --prefix cloudflare/a2a-front-door wrangler deploy --dry-run
```

Expected: `rg` finds no paid/extra resource bindings and the dry run succeeds.

### Task 4: Deploy and verify through workers.dev

**Files:**
- Modify: `cloudflare/a2a-front-door/wrangler.jsonc`
- Create: `scripts/cloudflare_a2a_smoke.py`

- [ ] **Step 1: Set the confirmed public origin**

Replace `ORIGIN_BASE_URL` with the existing HTTPS Go origin. The origin must already be reachable from the public Internet and its separate hosting cost must be accepted by the owner.

- [ ] **Step 2: Deploy only the Worker**

Run:

```bash
npx --prefix cloudflare/a2a-front-door wrangler deploy
```

Expected: a production URL of the form `https://misarch-a2a-store-agent.<account>.workers.dev`.

- [ ] **Step 3: Run read-only smoke tests**

Run:

```bash
python3 -m scripts.cloudflare_a2a_smoke \
  --base-url "https://misarch-a2a-store-agent.<account>.workers.dev"
```

Assert health, readiness, standard Agent Card, `JSONRPC` protocol 1.0, and one browse `SendMessage`.

- [ ] **Step 4: Run the authorized purchase E2E once**

Use the command from the A2A purchase plan with `--a2a-url` set to the Worker URL. Expected: exactly one pending order and no payment.

- [ ] **Step 5: Record deployment and free-plan evidence**

Document the Worker URL, UTC deployment time, Worker name, bundle size, test result, and a screenshot/reference showing the account is on Workers Free. Do not record secrets.
