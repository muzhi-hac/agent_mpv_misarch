# Real A2A Store Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the store-agent's custom-only `/tasks` wire format with an official A2A 1.0 JSON-RPC interaction while preserving the current experiment's domain behavior and a temporary legacy compatibility endpoint.

**Architecture:** The Go store-agent uses the official `github.com/a2aproject/a2a-go/v2` server, Agent Card, message, task, and artifact types. An `AgentExecutor` translates an incoming A2A DataPart (`skill` plus `input`) into the existing browse/purchase domain request and emits standard task lifecycle events. The Python butler discovers the JSON-RPC interface from the Agent Card, calls A2A 1.0 `SendMessage`, and adapts the returned standard Task/Artifact into the experiment's existing `TaskResponse` shape.

**Tech Stack:** Go 1.25, official A2A Go SDK v2.3.1 (A2A protocol 1.0), JSON-RPC 2.0 over HTTP, Python 3 standard library, Go `httptest`, Python `unittest`.

---

### Task 1: Pin the official A2A server SDK

**Files:**
- Modify: `go.mod`
- Modify: `go.sum`

- [ ] **Step 1: Add the official SDK**

Run:

```bash
go get github.com/a2aproject/a2a-go/v2@v2.3.1
```

Expected: `go.mod` contains `github.com/a2aproject/a2a-go/v2 v2.3.1` and `go.sum` contains its module checksums.

- [ ] **Step 2: Normalize module dependencies**

Run:

```bash
go mod tidy
```

Expected: command exits successfully without changing the module's Go version from `1.25.6`.

### Task 2: Publish an A2A 1.0 Agent Card

**Files:**
- Modify: `internal/a2aserver/types.go`
- Modify: `internal/a2aserver/server.go`
- Test: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Write the failing card contract test**

Add a test that decodes the public card as `a2a.AgentCard` and asserts:

```go
if got := card.SupportedInterfaces[0].ProtocolBinding; got != a2a.TransportProtocolJSONRPC {
	t.Fatalf("protocol binding = %q, want JSONRPC", got)
}
if got := card.SupportedInterfaces[0].ProtocolVersion; got != a2a.Version {
	t.Fatalf("protocol version = %q, want %q", got, a2a.Version)
}
if got := card.SupportedInterfaces[0].URL; got != "http://example.test:8001/a2a" {
	t.Fatalf("interface URL = %q, want /a2a endpoint", got)
}
```

- [ ] **Step 2: Run the test and verify the custom card fails**

Run:

```bash
go test ./internal/a2aserver -run TestAgentCardServed -v
```

Expected: FAIL because the current card exposes `endpoint` instead of `supportedInterfaces`.

- [ ] **Step 3: Build the official card**

Change `DefaultCard` to return `*a2a.AgentCard` with:

```go
SupportedInterfaces: []*a2a.AgentInterface{
	a2a.NewAgentInterface(strings.TrimRight(baseURL, "/")+"/a2a", a2a.TransportProtocolJSONRPC),
},
Capabilities:       a2a.AgentCapabilities{Streaming: false, Extensions: riskExtensions()},
DefaultInputModes:  []string{"application/json"},
DefaultOutputModes: []string{"application/json"},
```

Define browse and purchase as standard `a2a.AgentSkill` values. Publish the experiment-specific confirmation metadata through a declared A2A extension URI and `AgentExtension.Params`, not as undeclared top-level protocol fields.

- [ ] **Step 4: Run the card test**

Run:

```bash
go test ./internal/a2aserver -run TestAgentCardServed -v
```

Expected: PASS.

### Task 3: Execute browse and purchase through official A2A tasks

**Files:**
- Create: `internal/a2aserver/executor.go`
- Modify: `internal/a2aserver/server.go`
- Test: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Write a failing JSON-RPC browse test**

POST this request to `/a2a`:

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-1",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-1",
      "role": "ROLE_USER",
      "parts": [
        {
          "data": {
            "skill": "browse",
            "input": {"query": "cup", "top_k": 5}
          }
        }
      ]
    }
  }
}
```

Assert HTTP 200, the matching JSON-RPC ID, a `result.task.status.state` of `TASK_STATE_COMPLETED`, and a structured `products` DataPart in the task artifacts.

- [ ] **Step 2: Run the test and verify `/a2a` is missing**

Run:

```bash
go test ./internal/a2aserver -run TestA2AMessageSendBrowse -v
```

Expected: FAIL because `/a2a` is not registered.

- [ ] **Step 3: Implement the SDK executor**

Implement:

```go
type storeAgentExecutor struct {
	service Service
	options options
}

func (e *storeAgentExecutor) Execute(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error]
func (e *storeAgentExecutor) Cancel(ctx context.Context, execCtx *a2asrv.ExecutorContext) iter.Seq2[a2a.Event, error]
```

`Execute` must:

1. emit `a2a.NewSubmittedTask` for a new task;
2. parse the request from an A2A structured DataPart;
3. dispatch to the existing `handleBrowse` or `handlePurchase`;
4. emit the domain artifact with `a2a.NewArtifactEvent`;
5. map the domain state to the corresponding standard A2A task state;
6. emit the terminal/interrupted status event.

Malformed inputs and unknown skills must become `TASK_STATE_FAILED` status events. Purchase requests missing fields must become `TASK_STATE_INPUT_REQUIRED`. `Cancel` must emit `TASK_STATE_CANCELED`.

- [ ] **Step 4: Register the official JSON-RPC handler**

Construct:

```go
requestHandler := a2asrv.NewHandler(&storeAgentExecutor{service: svc, options: cfg})
mux.Handle("POST /a2a", a2asrv.NewJSONRPCHandler(requestHandler))
```

Keep `POST /tasks` as a deprecated compatibility route so existing regression scripts remain runnable during migration.

- [ ] **Step 5: Run all store-agent tests**

Run:

```bash
go test ./internal/a2aserver -v
```

Expected: PASS, covering standard browse, input-required purchase, unknown skill failure, legacy `/tasks`, and adversarial pricing.

### Task 4: Route the JSON-RPC endpoint through the gateway

**Files:**
- Modify: `internal/httpserver/server.go`
- Modify: `internal/httpserver/contract_test.go`

- [ ] **Step 1: Add the failing route contract**

Add:

```go
{"a2a json-rpc delegates", http.MethodPost, "/a2a", nil, a2aStatus, false, true},
```

- [ ] **Step 2: Run the contract test**

Run:

```bash
go test ./internal/httpserver -run TestRouteContract -v
```

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Delegate `/a2a`**

Register:

```go
mux.Handle("POST /a2a", a2aHandler)
```

Add `A2A-Version` to the CORS allowed-header list so browser A2A clients can negotiate protocol 1.0.

- [ ] **Step 4: Run HTTP server tests**

Run:

```bash
go test ./internal/httpserver -v
```

Expected: PASS.

### Task 5: Make the butler use the A2A wire protocol

**Files:**
- Modify: `scripts/agent_a2a_loop.py`
- Create: `scripts/test_a2a_protocol.py`

- [ ] **Step 1: Write failing client protocol tests**

Use a local `ThreadingHTTPServer` fixture that serves a standard card and captures POST bodies. Assert that `A2AClient.send_task`:

```python
self.assertEqual(request["jsonrpc"], "2.0")
self.assertEqual(request["method"], "SendMessage")
self.assertEqual(request["params"]["message"]["role"], "ROLE_USER")
self.assertEqual(
    request["params"]["message"]["parts"][0]["data"]["skill"],
    "browse",
)
self.assertEqual(headers["A2A-Version"], "1.0")
```

Also assert that a completed A2A Task artifact is adapted to:

```python
{"task_id": "...", "state": "completed", "artifact": {"products": [...]}}
```

- [ ] **Step 2: Run the test and verify it observes `/tasks`**

Run:

```bash
python3 -m unittest scripts.test_a2a_protocol -v
```

Expected: FAIL because the client posts the legacy task envelope to `/tasks`.

- [ ] **Step 3: Implement Card-driven JSON-RPC**

Cache the fetched card, select a `supportedInterfaces` entry whose `protocolBinding` is `JSONRPC`, and send:

```python
{
    "jsonrpc": "2.0",
    "id": request_id,
    "method": "SendMessage",
    "params": {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"data": {"skill": skill, "input": payload}}],
        }
    },
}
```

Set `Content-Type: application/json`, `Accept: application/json`, and `A2A-Version` from the selected interface. Reject JSON-RPC error responses, direct Message responses where a Task is required, missing task artifacts, and unsupported card transports with actionable exceptions.

- [ ] **Step 4: Update debug transcript URLs and payloads**

Record `/a2a`, `SendMessage`, standard message IDs, and A2A task responses rather than claiming the request went to `/tasks`.

- [ ] **Step 5: Run Python tests**

Run:

```bash
python3 -m unittest scripts.test_a2a_protocol scripts.test_guardrail -v
```

Expected: PASS.

### Task 6: End-to-end verification and documentation correction

**Files:**
- Modify: `README.md`
- Modify: `docs/a2a-developer-guide.zh.md`
- Modify: `a2aexperimentdesign.en.md`
- Modify: `a2aexperimentdesign.zh.md`

- [ ] **Step 1: Correct the implementation status**

Document that the active store-agent path uses A2A 1.0 JSON-RPC and the official Go SDK, with `/tasks` retained only as a deprecated compatibility endpoint. State the implemented scope (Agent Card, `SendMessage`, task lifecycle, structured artifacts, task retrieval supplied by the SDK) and still-unimplemented optional capabilities (streaming, push notifications, production authentication, signed cards).

- [ ] **Step 2: Run formatting**

Run:

```bash
gofmt -w internal/a2aserver internal/httpserver
```

Expected: no formatting errors.

- [ ] **Step 3: Run the complete local verification suite**

Run:

```bash
go test ./...
python3 -m unittest scripts.test_a2a_protocol scripts.test_guardrail scripts.test_duration_experiment -v
```

Expected: all tests PASS.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; pre-existing user changes remain present and the A2A changes are limited to the files listed above plus module checksums.
