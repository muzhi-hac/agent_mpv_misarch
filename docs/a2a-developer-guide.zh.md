# A2A 开发者文档

本文面向需要阅读、修改、测试和部署 A2A 功能的技术开发者。它假设读者知道基本的 HTTP、Go handler、JSON、GraphQL/MCP 概念，但不要求熟悉完整生产级 A2A 协议。

## 1. 当前实现定位

本仓库实现的是一个 **简化版 A2A store-agent**，用于验证 Agent-to-Agent 架构模式，而不是完整生产级 A2A JSON-RPC wire protocol。

当前目标是验证:

- 能通过 Agent Card 发现商家 agent 能力
- 能通过 Task API 调用商家能力
- 能区分只读能力和高风险能力
- 能让用户侧 agent 保留用户 profile，不把 profile 直接发给商家
- 能对 purchase 这类高风险动作做确认/拦截实验

当前没有使用:

- React 前端
- LangChain `ReActAgent`
- 完整 A2A JSON-RPC 2.0 协议
- streaming
- A2A 层认证

## 2. 代码结构

核心文件:

```text
internal/a2aserver/types.go       A2A JSON 数据结构
internal/a2aserver/server.go      Agent Card 和 /tasks handler
internal/a2aserver/server_test.go A2A server 单元测试
internal/httpserver/server.go     HTTP 路由挂载
internal/httpserver/contract_test.go 路由契约测试
cmd/server/main.go                服务组装入口
scripts/agent_a2a_loop.py         用户侧 butler agent / Arm C 实验脚本
a2aexperimentdesign.zh.md         实验设计说明
```

相关配置/部署文件:

```text
internal/config/config.go
Dockerfile
.github/workflows/deploy-main.yml
```

## 3. 架构概览

当前 A2A 边界只有一条:

```text
User Butler Agent  <---- simplified A2A over HTTP ---->  Store Agent
```

再往下，store-agent 内部调用已有 Go service:

```text
Store Agent
  |
  +-- catalog.Service -> GraphQL -> MiSArch catalog
  |
  +-- order.Service   -> GraphQL -> MiSArch order
```

完整请求链路:

```text
用户任务
  |
  v
scripts/agent_a2a_loop.py
  |
  | GET /.well-known/agent-card.json
  v
internal/a2aserver: Agent Card
  |
  | POST /tasks skill=browse
  v
internal/a2aserver: handleBrowse
  |
  v
catalog.Service.ListProducts / GetProduct
  |
  v
GraphQL / MiSArch
```

如果任务是 purchase 意图，用户侧 butler 会读取 Agent Card 中的风险元数据，并在当前 Phase 1 中拦截，不发送真实 purchase Task。

## 4. HTTP API

### 4.1 Agent Card

```text
GET /.well-known/agent-card.json
```

返回示例:

```json
{
  "name": "misarch-store-agent",
  "version": "0.1.0",
  "description": "MiSArch merchant store-agent exposing browse and purchase skills over A2A.",
  "endpoint": "http://34.40.117.201:8001",
  "skills": [
    {
      "id": "browse",
      "description": "Return candidate catalog products. Read-only; ranking is the caller's responsibility.",
      "risk_level": "none",
      "side_effects": false,
      "requires_confirmation": false
    },
    {
      "id": "purchase",
      "description": "Create a pending order for a selected product variant. High-risk; spends the user's money.",
      "risk_level": "high",
      "side_effects": true,
      "requires_confirmation": true
    }
  ],
  "capabilities": {
    "streaming": false
  },
  "auth": {
    "schemes": ["none"]
  }
}
```

关键字段:

| 字段 | 含义 |
|---|---|
| `endpoint` | Task API 基址，调用方应向 `{endpoint}/tasks` 发任务 |
| `skills` | store-agent 对外暴露的能力 |
| `risk_level` | 风险级别，当前使用 `none` / `high` |
| `side_effects` | 是否有副作用 |
| `requires_confirmation` | 调用前是否需要用户确认 |

### 4.2 Task API

```text
POST /tasks
Content-Type: application/json
```

请求结构:

```json
{
  "task_id": "task-001",
  "skill": "browse",
  "input": {
    "top_k": 5
  }
}
```

响应结构:

```json
{
  "task_id": "task-001",
  "state": "completed",
  "message": "...",
  "artifact": {},
  "error": "..."
}
```

`state` 当前支持:

| 状态 | 含义 |
|---|---|
| `working` | 预留，当前 handler 不返回 |
| `input-required` | 需要更多输入，例如 purchase 缺少字段 |
| `completed` | 任务完成 |
| `failed` | 任务失败 |

## 5. Skill 行为

### 5.1 browse

输入:

```json
{
  "top_k": 2
}
```

可选输入:

```json
{
  "product_id": "..."
}
```

行为:

- 如果传入 `product_id`，调用 `GetProduct`
- 否则调用 `ListProducts(ctx, topK)`
- 返回未排序候选商品
- 不读取用户 profile
- 不做个性化排序

示例:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"dev-browse","skill":"browse","input":{"top_k":2}}' \
  | python3 -m json.tool
```

期望:

```json
{
  "state": "completed",
  "artifact": {
    "products": [],
    "returned_count": 2
  }
}
```

### 5.2 purchase

输入字段:

```json
{
  "user_id": "...",
  "product_variant_id": "...",
  "shipment_method_id": "...",
  "shipment_address_id": "...",
  "invoice_address_id": "...",
  "payment_information_id": "..."
}
```

当前 Phase 1 行为:

- 校验必填字段是否存在
- 缺字段返回 `input-required`
- 字段齐全返回 dry-run success
- 不调用 `CreatePendingOrder`
- 不创建真实订单

缺字段示例:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"dev-purchase-guard","skill":"purchase","input":{"user_id":"demo"}}' \
  | python3 -m json.tool
```

期望:

```json
{
  "state": "input-required",
  "artifact": {
    "missing_fields": [
      "product_variant_id",
      "shipment_method_id",
      "shipment_address_id",
      "invoice_address_id",
      "payment_information_id"
    ]
  }
}
```

完整字段 dry-run 示例:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{
    "task_id":"dev-purchase-dry-run",
    "skill":"purchase",
    "input":{
      "user_id":"u1",
      "product_variant_id":"v1",
      "shipment_method_id":"s1",
      "shipment_address_id":"sa1",
      "invoice_address_id":"ia1",
      "payment_information_id":"p1"
    }
  }' | python3 -m json.tool
```

期望:

```json
{
  "state": "completed",
  "artifact": {
    "validated": true,
    "order_created": false
  }
}
```

## 6. Go 实现细节

### 6.1 Protocol structs

文件:

```text
internal/a2aserver/types.go
```

主要结构:

```go
type AgentCard struct { ... }
type Skill struct { ... }
type TaskRequest struct { ... }
type TaskResponse struct { ... }
```

这些结构直接决定 HTTP JSON contract。新增字段时要同步测试和文档。

### 6.2 Service interface

文件:

```text
internal/a2aserver/server.go
```

接口:

```go
type Service interface {
    ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error)
    GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error)
    CreatePendingOrder(ctx context.Context, in order.CreatePendingOrderInput) (order.CreatePendingOrderOutput, error)
}
```

`a2aserver` 不直接依赖具体 catalog/order 实现，而是依赖这个接口，方便单测中使用 fake service。

### 6.3 Store adapter

文件:

```text
cmd/server/main.go
```

`storeAdapter` 把已有的 `catalog.Service` 和 `order.Service` 合并成 `a2aserver.Service`。

这样 A2A 层可以复用已有业务能力，不需要复制 GraphQL 调用逻辑。

### 6.4 Route mounting

文件:

```text
internal/httpserver/server.go
```

挂载:

```go
mux.Handle("GET /.well-known/agent-card.json", a2aHandler)
mux.Handle("POST /tasks", a2aHandler)
```

注意: 当前使用 Go 1.22+ 的 method-aware ServeMux pattern。如果 Go 版本过低，这类 pattern 不可用。

## 7. 用户侧 butler agent

文件:

```text
scripts/agent_a2a_loop.py
```

核心类:

| 类 | 作用 |
|---|---|
| `A2AClient` | 读取 Agent Card，发送 Task |
| `PreferenceModule` | 本地读取用户 profile，本地排序 |
| `UserButler` | 串联 LLM 意图判断、A2A 调用、风险拦截、最终回答 |

关键隐私设计:

- 完整 profile 只在 `PreferenceModule` 内本地使用
- `minimal_constraints()` 默认返回空对象和空披露字段列表
- A2A `browse` task 只发送任务派生的 `query`、`top_k`、`constraints`
- store-agent 返回候选商品，不知道用户偏好

关键风险设计:

```python
risk = {
    "detected": False,
    "confirmation_required": False,
    "user_confirmed": None,
    "purchase_task_sent": False,
}
```

当用户任务是 purchase 意图，并且 Agent Card 显示 `purchase.requires_confirmation = true` 时:

- `risk.detected = true`
- `risk.confirmation_required = true`
- `risk.user_confirmed = false`
- `risk.purchase_task_sent = false`

当前非交互式实验中不会真正发送 purchase task。

## 8. 本地测试

完整 Go 测试:

```bash
go test ./...
```

只测 A2A:

```bash
go test ./internal/a2aserver
```

只测 HTTP route contract:

```bash
go test ./internal/httpserver
```

静态检查:

```bash
go vet ./...
```

## 9. 线上 smoke test

设置:

```bash
export A2A_URL=http://34.40.117.201:8001
```

Agent Card:

```bash
curl -s "$A2A_URL/.well-known/agent-card.json" | python3 -m json.tool
```

browse:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-browse","skill":"browse","input":{"top_k":2}}' \
  | python3 -m json.tool
```

purchase guard:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-purchase-guard","skill":"purchase","input":{"user_id":"demo"}}' \
  | python3 -m json.tool
```

invalid skill:

```bash
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-invalid","skill":"unknown","input":{}}' \
  | python3 -m json.tool
```

健康检查:

```bash
curl -s "$A2A_URL/healthz"
curl -s "$A2A_URL/readyz"
```

## 10. 用户侧完整链路测试

以下命令需要从项目根目录运行，因为 `python3 -m scripts.agent_a2a_loop`
依赖当前目录能解析到仓库里的 `scripts` package:

```bash
cd /Users/wang/agent_misarch/agent_mpv_misarch
```

Browse 场景:

```bash
python3 -m scripts.agent_a2a_loop \
  --task "帮我挑一个适合我的水杯" \
  --a2a-url http://34.40.117.201:8001 \
  --profile data/user_profile.json \
  --user-id demo-user
```

Purchase 风险场景:

```bash
python3 -m scripts.agent_a2a_loop \
  --task "帮我下单买这个水杯" \
  --a2a-url http://34.40.117.201:8001 \
  --profile data/user_profile.json \
  --user-id demo-user
```

关键断言:

| 字段 | 期望 |
|---|---|
| `success` | `true` |
| `arm` | `"a2a"` |
| `hops` | 通常为 `2`，一次 card，一次 browse |
| `profile_fields_disclosed` | `[]` |
| `risk.detected` | purchase 场景为 `true` |
| `risk.confirmation_required` | purchase 场景为 `true` |
| `risk.purchase_task_sent` | purchase 场景为 `false` |

## 11. 新增 skill 的开发步骤

假设要新增 `reserve` skill。

### 11.1 更新数据结构

通常不用改 `TaskRequest` / `TaskResponse`，因为 `input` 和 `artifact` 都是 flexible map。

如果需要强 contract，可以新增 typed helper 或新的 input struct。

### 11.2 更新 Agent Card

在 `DefaultCard` 中增加 skill:

```go
{
    ID:                   "reserve",
    Description:          "...",
    RiskLevel:            "medium",
    SideEffects:          true,
    RequiresConfirmation: true,
}
```

### 11.3 更新 dispatch

在 `handleTasks` 中增加 case:

```go
case "reserve":
    writeJSON(w, http.StatusOK, handleReserve(r.Context(), svc, req))
```

### 11.4 实现 handler

新增:

```go
func handleReserve(ctx context.Context, svc Service, req TaskRequest) TaskResponse {
    ...
}
```

建议保持:

- 输入校验显式
- 错误状态明确
- 高风险动作先 dry-run 或 input-required
- 不在 handler 中偷偷读取用户 profile

### 11.5 补测试

至少增加:

- Agent Card 包含新 skill
- 正常 task 返回 expected state
- 缺字段返回 `input-required` 或 `failed`
- 未知 skill 仍然返回 400
- HTTP route contract 不回退

### 11.6 更新用户侧 butler

在 `scripts/agent_a2a_loop.py` 中决定:

- 什么时候触发新 skill
- 是否需要 confirmation
- 哪些字段可以跨 A2A 边界
- 输出中如何记录 risk / trace

## 12. 部署注意事项

### 12.1 PUBLIC_BASE_URL

Agent Card 的 `endpoint` 来自配置 `PUBLIC_BASE_URL`。

线上必须是外部可访问地址，例如:

```text
http://34.40.117.201:8001
```

如果配置错误，调用方可能拿到类似 `http://:8001` 的坏 endpoint。

### 12.2 GitHub Actions

部署 workflow:

```text
.github/workflows/deploy-main.yml
```

部署后建议至少跑:

```bash
curl -s "$A2A_URL/.well-known/agent-card.json" | python3 -m json.tool
curl -s "$A2A_URL/readyz"
```

### 12.3 Docker

Dockerfile 中也设置了默认 `PUBLIC_BASE_URL`，但生产部署应由环境变量覆盖。

## 13. 常见问题

### 13.1 为什么 store-agent 不做个性化排序?

因为实验要验证数据主权。用户 profile 留在用户侧，商家只返回候选商品。

### 13.2 为什么 purchase 不创建订单?

当前是 Phase 1 风险拦截实验。目标是测:

- 能否识别高风险动作
- 是否需要确认
- 是否阻止未经确认的下单

真实 `CreatePendingOrder` 留到 Phase 2。

### 13.3 为什么没有认证?

这是实验实现。当前 Agent Card 中:

```json
"auth": { "schemes": ["none"] }
```

生产化时应增加认证、授权、审计日志和 rate limit。

### 13.4 这是完整 A2A 协议吗?

不是。当前是 REST-style 简化实现:

```text
GET  /.well-known/agent-card.json
POST /tasks
```

它验证 A2A 架构思想，不保证与生产级 A2A agent wire protocol 兼容。

## 14. 开发者检查清单

改 A2A 相关代码后，建议跑:

```bash
go test ./...
go vet ./...
```

线上部署后，建议检查:

```bash
export A2A_URL=http://34.40.117.201:8001

curl -s "$A2A_URL/.well-known/agent-card.json" | python3 -m json.tool
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"check-browse","skill":"browse","input":{"top_k":2}}' \
  | python3 -m json.tool
curl -s -X POST "$A2A_URL/tasks" \
  -H 'content-type: application/json' \
  -d '{"task_id":"check-purchase","skill":"purchase","input":{"user_id":"demo"}}' \
  | python3 -m json.tool
```

用户侧实验链路:

```bash
python3 -m scripts.agent_a2a_loop \
  --task "帮我下单买这个水杯" \
  --a2a-url "$A2A_URL" \
  --profile data/user_profile.json \
  --user-id demo-user
```

检查输出中的:

```json
{
  "profile_fields_disclosed": [],
  "risk": {
    "detected": true,
    "confirmation_required": true,
    "user_confirmed": false,
    "purchase_task_sent": false
  }
}
```

## 15. 当前技术边界

当前实现适合:

- 课程/实验展示
- 架构对比实验
- A2A 最小可行路径验证
- 数据主权和风险拦截演示

当前不适合直接当生产 A2A 平台:

- 没有 auth
- 没有 request signing
- 没有 rate limit
- 没有 durable task store
- 没有 async task polling
- 没有 streaming
- purchase 没有真实落单
- 没有跨 agent trace id 标准化

如果要生产化，建议优先补:

1. Auth / authorization
2. Request id / trace id / audit log
3. Durable task state
4. 标准 A2A protocol compatibility
5. Interactive confirmation flow
6. Real pending order Phase 2
