# Reproduction Guide

This guide reproduces the Group 11 MiSArch Agent Gateway, its controlled
shopping scenario, and the evaluation artifacts. Commands are intended to be
run from the repository root unless stated otherwise.

## Scope and safety

The normal reproduction path is read-only. It exercises catalog discovery,
product inspection, MCP/A2A interoperability, and policy regressions. Do not
enable `--include-order-test`, `--execute`, or the exact purchase confirmation
text unless you intentionally want to create persistent test orders in a
disposable MiSArch environment.

Never place API keys, Keycloak passwords, bearer tokens, or CVC values in this
repository. The experiment manifest records the model and sanitized endpoint
URLs, but never records credentials.

## Prerequisites

- Git
- Go 1.25.6, as declared by `go.mod`
- Python 3.11 or newer
- Docker Engine and Docker Compose v2 for a local MiSArch deployment
- `curl`
- Optional: a Responses API-compatible model endpoint for Arms B, D, and C

For resource sampling and chart generation, create a virtual environment and
install the evaluation-only dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-eval.txt
```

The protocol clients and offline tests otherwise use the Python standard
library. If `psutil` is absent, client CPU/RSS fields are reported as unavailable.

## 1. Check out the exact revision

```bash
git clone https://github.com/muzhi-hac/agent_mpv_misarch.git
cd agent_mpv_misarch
git checkout main
git rev-parse HEAD
```

Record the printed revision with the report artifacts. Every experiment also
writes it to `run_manifest.json`.

## 2. Start MiSArch

The gateway requires a reachable MiSArch GraphQL Gateway. For a fresh local
deployment, use the upstream Compose repository and initialize its submodules:

```bash
git clone --recurse-submodules https://github.com/MiSArch/infrastructure-docker.git
cd infrastructure-docker
docker compose config --quiet
docker compose up -d
```

Wait until the GraphQL Gateway is reachable at
`http://127.0.0.1:8080/graphql`. The detailed GCP deployment used by the group
is documented in `docs/gcp-misarch-mcp-agent-testing.zh.md`. Reproduction does
not require the original GCP VM; any equivalent MiSArch deployment is valid.

Verify GraphQL before starting the adapter:

```bash
curl -fsS http://127.0.0.1:8080/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"{ __typename }"}'
```

## 3. Build and test the Go gateway

```bash
go mod download
go test ./...
go vet ./...
mkdir -p tmp
go build -o ./tmp/misarch-agent-gateway ./cmd/server
```

The same build is encoded in `Dockerfile`. No generated Go source is required.

Run the backend-free Python tests:

```bash
python -m unittest \
  scripts.test_guardrail \
  scripts.test_duration_experiment \
  scripts.test_experiment_manifest \
  scripts.test_report_aligned_security_summary \
  scripts.test_run_metrics \
  scripts.test_visualize_arms \
  scripts.test_demo_four_arms \
  scripts.test_openai_demo_agent \
  scripts.test_a2a_purchase_e2e
```

`scripts.test_agent_mcp_loop_live` is deliberately excluded here because it
requires both a live MiSArch gateway and a real model API key.

## 4. Run the gateway locally

In terminal 1:

```bash
export HTTP_ADDR=127.0.0.1:8001
export PUBLIC_BASE_URL=http://127.0.0.1:8001
export MISARCH_GRAPHQL_URL=http://127.0.0.1:8080/graphql
export MISARCH_GRAPHQL_TIMEOUT=3s
go run ./cmd/server
```

In terminal 2:

```bash
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:8001/readyz
curl -fsS http://127.0.0.1:8001/.well-known/agent-card.json
```

`/healthz` proves the process is alive. `/readyz` additionally probes MiSArch
GraphQL and must return HTTP 200 before live experiments are started.

## 5. Reproduce the deterministic GraphQL vs MCP baseline

This command uses no LLM and performs no order mutation:

```bash
python -m scripts.agent_gcp_baseline_test \
  --graphql-url http://127.0.0.1:8080/graphql \
  --mcp-url http://127.0.0.1:8001/mcp \
  --trials 5 \
  --top-k 2 \
  --skip-llm \
  --skip-agent-reports \
  --results-dir eval/reproduction-baseline
```

Expected: native GraphQL and MCP both return MiSArch catalog data. Direct
GraphQL should generally be faster; this project does not claim MCP is a
latency optimization.

## 6. Reproduce the controlled agent scenario

Load model credentials without putting the key in shell history:

```bash
read -rs OPENAI_API_KEY
export OPENAI_API_KEY
printf '\n'
export OPENAI_MODEL='<available-model>'
export OPENAI_BASE_URL='https://api.openai.com'
```

Run the MCP agent and the A2A butler separately:

```bash
python -m scripts.agent_mcp_loop \
  --task 'List products, inspect one real product, and summarize it.' \
  --mcp-url http://127.0.0.1:8001/mcp \
  --output eval/reproduction-agent/mcp.json

python -m scripts.agent_a2a_loop \
  --task 'Help me pick a water cup.' \
  --a2a-url http://127.0.0.1:8001 \
  --profile data/user_profile.json \
  --user-id demo-user \
  --output eval/reproduction-agent/a2a.json
```

The MCP agent exposes only its read-only allowlist to the model. A purchase
request in the A2A butler is intercepted and held for confirmation rather than
automatically sent as a purchase task.

## 7. Run the fixed-trial experiment

```bash
./scripts/run_experiment.sh 5 eval/reproduction-fixed
```

This runs Arms B, D, and C over four tasks with five trials per arm/task. It
writes per-run JSON, `summary.csv`, `errors.log`, and `run_manifest.json`.

Generate aggregate statistics and charts:

```bash
python -m scripts.visualize_arms \
  eval/reproduction-fixed \
  --out eval/reproduction-fixed
```

The aggregate contains sample count, mean, median, nearest-rank p95, standard
deviation, minimum, and maximum latency. Failed runs are retained in the sample
count but excluded from the latency distribution.

## 8. Run the duration experiment

```bash
DURATION_SECONDS=120 \
CONCURRENCY=2 \
./scripts/run_experiment.sh ignored eval/reproduction-duration
```

The runner caps concurrency at 8. Under concurrency greater than one,
server-side allocation and GC counters are measured once for the entire
benchmark window so overlapping tasks are not double-counted. The result is in
`run_summary.json` under `server_metric_scope=benchmark_window`.

## 9. Metric definitions

- `duration_ms`: client monotonic wall-clock time for the complete agent run.
- `token_source=responses_api_usage`: token counts returned by the model API;
  missing or partial usage is labelled explicitly instead of estimated.
- `hops`: completed cross-agent request-response round trips. B/D are zero; C
  normally has Agent Card discovery plus one browse task.
- `business_calls`: agent-facing business capability invocations.
- `protocol_round_trips`: completed application-protocol request-response
  exchanges, including MCP initialization and discovery where applicable.
- Server runtime deltas are not comparable per task during concurrent runs;
  use the benchmark-window value in that mode.

These fields intentionally prevent business calls and protocol hops from being
reported as if they were the same metric.

## 10. Reproduce the offline security regressions

```bash
mkdir -p eval/reproduction-security
python -m scripts.a2a_card_regression \
  --output eval/reproduction-security/card.json
python -m scripts.a2a_price_regression \
  --output eval/reproduction-security/price.json
python -m scripts.a2a_backdoor_regression \
  --output eval/reproduction-security/backdoor.json
```

The purchase-intent risk suite additionally requires the live gateway and model
credentials configured in step 6:

```bash
python -m scripts.a2a_risk_regression \
  --a2a-url http://127.0.0.1:8001 \
  --include-controls \
  --output eval/reproduction-security/purchase-risk.json
```

Aggregate all four categories with explicit defense semantics:

```bash
python -m scripts.report_aligned_security_summary \
  --purchase-risk eval/reproduction-security/purchase-risk.json \
  --agent-card eval/reproduction-security/card.json \
  --price eval/reproduction-security/price.json \
  --backdoor eval/reproduction-security/backdoor.json \
  --output eval/reproduction-security/summary.json
```

Omit `--purchase-risk` for an offline-only partial summary; in that case
`complete` is expected to be `false`.

For the backdoor suite, `passed=true` means an attack behavior was reproduced;
it does not mean the system blocked that attack. The summary reports attacks
blocked and attacks reproduced separately.

## 11. Docker deployment of the adapter

If MiSArch runs on the host:

```bash
docker build -t misarch-agent-gateway:reproduction .
docker run --rm --name misarch-agent-gateway \
  -p 8001:8001 \
  -e HTTP_ADDR=:8001 \
  -e PUBLIC_BASE_URL=http://127.0.0.1:8001 \
  -e MISARCH_GRAPHQL_URL=http://host.docker.internal:8080/graphql \
  misarch-agent-gateway:reproduction
```

On Linux, use `--add-host=host.docker.internal:host-gateway` or attach the
container to the MiSArch Compose network and use
`MISARCH_GRAPHQL_URL=http://gateway:8080/graphql`.

## 12. Expected artifact layout

```text
eval/reproduction-fixed/
  run_manifest.json
  summary.csv
  aggregate.csv
  charts.png
  errors.log
  B_*.json
  D_*.json
  C_*.json

eval/reproduction-duration/
  run_manifest.json
  run_summary.json
  summary.csv
  commands.log
  *.json
```

Archive the raw JSON/CSV files together with plotting code. Do not submit an
API key, local `.env` file, temporary auth file, or a real payment credential.

## Troubleshooting

- `/healthz` is 200 but `/readyz` is 503: fix `MISARCH_GRAPHQL_URL` or wait for
  MiSArch GraphQL to become ready.
- MCP initialization fails: confirm `/mcp` is used and the same session ID is
  retained after `initialize`.
- Agent runs fail before MCP/A2A calls: verify `OPENAI_API_KEY`, model access,
  and `OPENAI_BASE_URL`.
- Charts are unavailable: install `requirements-eval.txt` and rerun the
  visualizer; raw JSON and CSV remain valid without charts.
- Write tools fail while reads work: all four `MISARCH_KEYCLOAK_*` variables
  must be configured together. They are not needed for the read-only scenario.
