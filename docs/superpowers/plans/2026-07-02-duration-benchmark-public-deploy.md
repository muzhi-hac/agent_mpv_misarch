# Duration Benchmark Public Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a duration-based, non-rate-limited benchmark mode with a safe concurrency cap, then deploy the gateway and verify local plus public functionality.

**Architecture:** Keep the existing fixed-trial experiment path intact for old results. Add a Python duration runner that continuously schedules benchmark runs until a time deadline, bounded by a worker count, and records the actual number of completed runs. The existing shell wrapper delegates to the duration runner only when a duration is requested.

**Tech Stack:** Go HTTP gateway, Python 3 standard library, existing A2A/MCP experiment scripts, GCP VM deployment workflow.

---

### Task 1: Add Duration-Based Experiment Runner

**Files:**
- Create: `scripts/run_duration_experiment.py`
- Test: `scripts/test_duration_experiment.py`

- [ ] **Step 1: Implement runner arguments**

Add `--duration-seconds`, `--concurrency`, `--outdir`, `--a2a-url`, `--mcp-url`, `--profile`, `--user-id`, and `--tasks` arguments. Validate that duration is positive and concurrency is between 1 and 8.

- [ ] **Step 2: Implement bounded scheduling**

Use a `queue.Queue` of task/arm jobs and `threading.Thread` workers. Workers start no new job after the deadline, but completed in-flight jobs are recorded. Each completed job writes a JSON file and appends one CSV row.

- [ ] **Step 3: Preserve existing arms**

Run the existing commands:

```bash
python -m scripts.agent_mcp_loop --task "$TASK" --mcp-url "$MCP_URL"
python -m scripts.agent_mcp_loop --task "$TASK" --mcp-url "$MCP_URL" --profile "$PROFILE" --user-id "$USER_ID"
python -m scripts.agent_a2a_loop --task "$TASK" --a2a-url "$A2A_URL" --profile "$PROFILE" --user-id "$USER_ID"
```

Map them to arms `B`, `D`, and `C`, matching `scripts/run_experiment.sh`.

- [ ] **Step 4: Unit-test scheduler math**

Add tests for validation, round-robin job selection, CSV row extraction from result JSON, and the guarantee that completed count comes from finished jobs rather than a preset request count.

- [ ] **Step 5: Run Python tests**

Run:

```bash
python3 -m unittest scripts.test_duration_experiment
```

Expected: all tests pass.

### Task 2: Wire Shell Wrapper

**Files:**
- Modify: `scripts/run_experiment.sh`

- [ ] **Step 1: Add duration environment switch**

If `DURATION_SECONDS` is set, call:

```bash
python -m scripts.run_duration_experiment \
  --duration-seconds "$DURATION_SECONDS" \
  --concurrency "${CONCURRENCY:-2}" \
  --outdir "$OUTDIR" \
  --a2a-url "$A2A_URL" \
  --mcp-url "$MCP_URL" \
  --profile "$PROFILE" \
  --user-id "$USER_ID"
```

- [ ] **Step 2: Keep fixed-trial default**

Leave the existing `N` loop unchanged when `DURATION_SECONDS` is unset.

### Task 3: Local Verification

**Files:**
- No source edits.

- [ ] **Step 1: Run Go tests**

Run:

```bash
go test ./...
go vet ./...
```

Expected: both pass.

- [ ] **Step 2: Start local gateway**

Run the gateway with `HTTP_ADDR=127.0.0.1:8001` and the configured MiSArch GraphQL URL.

- [ ] **Step 3: Verify local endpoints**

Check:

```bash
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:8001/readyz
curl -fsS http://127.0.0.1:8001/.well-known/agent-card.json
curl -fsS -X POST http://127.0.0.1:8001/tasks -H 'Content-Type: application/json' -d '{"task_id":"local-browse","skill":"browse","input":{"top_k":3,"query":"cup"}}'
```

- [ ] **Step 4: Run local duration benchmark**

Run a short smoke window with `DURATION_SECONDS=30 CONCURRENCY=2` and the provided OpenAI API key loaded only as an environment variable.

### Task 4: Public Deploy And Verification

**Files:**
- No source edits unless deployment config is missing.

- [ ] **Step 1: Deploy**

Use the existing GCP deployment path or GitHub Actions workflow to update the VM container.

- [ ] **Step 2: Verify public endpoints**

Check the public base URL for `/healthz`, `/readyz`, `/.well-known/agent-card.json`, `/tasks`, and `/mcp` initialize/tool discovery.

- [ ] **Step 3: Run public duration benchmark**

Run the same duration benchmark against the public base URL with `CONCURRENCY=2`, recording actual completions and failures in `eval/`.

