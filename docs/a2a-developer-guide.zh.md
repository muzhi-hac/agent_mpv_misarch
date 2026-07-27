# A2A 开发者文档

本文面向需要阅读、修改、测试和部署 A2A 功能的技术开发者。它假设读者知道基本的 HTTP、Go handler、JSON、GraphQL/MCP 概念，但不要求熟悉完整生产级 A2A 协议。

## 1. 当前实现定位

本仓库的 store-agent 已接入官方 `github.com/a2aproject/a2a-go/v2`
SDK，主路径使用 **A2A 1.0 JSON-RPC wire protocol**。它发布标准 Agent
Card，并支持 `SendMessage`、Task 生命周期、结构化 Artifact/DataPart 和
`GetTask`。旧的 `POST /tasks` 仅作为迁移期兼容入口。

当前目标是验证:

- 能通过 Agent Card 发现商家 agent 能力
- 能通过 A2A Message/Task API 调用商家能力
- 能区分只读能力和高风险能力
- 能让用户侧 agent 保留用户 profile，不把 profile 直接发给商家
- 能对 purchase 这类高风险动作做确认/拦截实验

当前仍未启用:

- React 前端
- LangChain `ReActAgent`
- streaming
- push notification
- durable task store
- Agent Card 签名和生产级 A2A 认证
- A2A TCK 合规认证

## 2. 代码结构

核心文件:

```text
internal/a2aserver/types.go       store-agent 领域请求/响应结构
internal/a2aserver/executor.go    官方 A2A Message/Task 与领域逻辑适配
internal/a2aserver/server.go      标准 Agent Card、/a2a 和兼容 /tasks handler
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
User Butler Agent  <---- A2A 1.0 JSON-RPC/HTTP ---->  Store Agent
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
  | POST /a2a  JSON-RPC SendMessage
  | DataPart: {"skill":"browse","input":{...}}
  v
internal/a2aserver: handleBrowse
  |
  v
catalog.Service.ListProducts / GetProduct
  |
  v
GraphQL / MiSArch
```

如果任务是 purchase 意图，用户侧 butler 会执行本地风险策略，并把 Agent
Card 的自定义风险 extension 只作为审计信息。普通实验脚本仍默认停在确认门；
受控 E2E 运行器则先发送未确认任务，再使用相同 task/context 发送确认
continuation，触发真实的本地模拟购买。

## 4. HTTP API

### 4.1 Agent Card

```text
GET /.well-known/agent-card.json
```

关键结构:

```json
{
  "name": "misarch-store-agent",
  "version": "1.0.0",
  "description": "MiSArch merchant store-agent exposing browse and purchase skills over A2A.",
  "supportedInterfaces": [
    {
      "url": "http://34.40.117.201:8001/a2a",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    {
      "id": "browse",
      "name": "Browse catalog",
      "description": "Return candidate catalog products.",
      "tags": ["catalog", "browse", "shopping"]
    },
    {
      "id": "purchase",
      "name": "Complete purchase",
      "description": "After explicit confirmation, create and place an order and complete payment through MiSArch's local simulator.",
      "tags": ["order", "purchase", "shopping"]
    }
  ],
  "capabilities": {
    "extensions": [
      {
        "uri": "https://misarch.dev/a2a/extensions/risk/v1",
        "params": {"skills": {"purchase": {"risk_level": "high"}}}
      }
    ]
  }
}
```

关键字段:

| 字段 | 含义 |
|---|---|
| `supportedInterfaces` | 标准协议绑定、版本和调用 URL；客户端必须从这里发现 `/a2a` |
| `skills` | store-agent 对外暴露的能力 |
| `capabilities.extensions` | 非标准风险元数据的显式扩展容器 |

### 4.2 A2A JSON-RPC API

```text
POST /a2a
Content-Type: application/json
A2A-Version: 1.0
```

请求结构:

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-001",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "message-001",
      "role": "ROLE_USER",
      "parts": [
        {"data": {"skill": "browse", "input": {"top_k": 5}}}
      ]
    }
  }
}
```

响应结构:

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-001",
  "result": {
    "task": {
      "id": "...",
      "contextId": "...",
      "status": {"state": "TASK_STATE_COMPLETED"},
      "artifacts": [
        {"artifactId": "...", "parts": [{"data": {"products": []}}]}
      ]
    }
  }
}
```

主要状态映射:

| 状态 | 含义 |
|---|---|
| `TASK_STATE_SUBMITTED` / `TASK_STATE_WORKING` | 已提交 / 执行中 |
| `TASK_STATE_INPUT_REQUIRED` | 需要更多输入，例如 purchase 缺少字段 |
| `TASK_STATE_COMPLETED` | 任务完成 |
| `TASK_STATE_FAILED` | 任务失败 |

可用标准方法还包括 `GetTask`、`ListTasks` 和 `CancelTask`。`POST /tasks`
返回旧的 `{task_id,state,artifact}` 结构，只供兼容测试使用，不是新的 A2A
主路径。

## 5. Skill 行为

本节中的领域输入/输出对 `/a2a` 和兼容 `/tasks` 相同；示例若使用
`/tasks`，只是在演示兼容入口。

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
  "payment_information_id": "...",
  "quantity": 1,
  "payment_cvc": 123,
  "confirmed": false
}
```

当前行为:

- 校验必填字段是否存在
- 缺字段返回 `input-required`
- 字段齐全但 `confirmed=false` 时返回 `input-required`，不产生副作用
- 客户端必须使用相同 `taskId` 和 `contextId` 发送 continuation，并设置 `confirmed=true`
- 确认后依次创建购物车项、创建 `PENDING` 订单并调用 `placeOrder`
- `placeOrder` 发布订单事件，Payment 服务通过本地 Simulation 完成模拟支付
- 成功条件是订单状态 `PLACED` 且支付状态 `SUCCEEDED`
- MiSArch 没有 `PAID` 订单状态；是否已支付由独立的 Payment 状态表达
- 不连接外部支付服务，不产生真实扣款

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

完整字段但未确认时，服务返回订单预览和 `input-required`，不会创建数据。
`confirmed=true` 只有在引用该任务的标准 A2A continuation 中才有效；第一条消息
直接携带 `confirmed=true`，或通过兼容接口 `/tasks` 提交，都不能绕过确认门。

完整购买使用受控运行器：

```bash
python3 -m scripts.a2a_purchase_e2e \
  --a2a-url "$A2A_URL" \
  --user-id "$TEST_USER_ID" \
  --product-variant-id "$TEST_PRODUCT_VARIANT_ID" \
  --shipment-method-id "$TEST_SHIPMENT_METHOD_ID" \
  --shipment-address-id "$TEST_SHIPMENT_ADDRESS_ID" \
  --invoice-address-id "$TEST_INVOICE_ADDRESS_ID" \
  --payment-information-id "$TEST_PAYMENT_INFORMATION_ID" \
  --execute \
  --confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER" \
  --output tmp/a2a_purchase_e2e.json
```

成功审计结果包含：

```json
{
  "success": true,
  "local_simulation_only": true,
  "purchase": {
    "order_status": "PLACED",
    "payment_status": "SUCCEEDED"
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
mux.Handle("POST /a2a", a2aHandler)
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
| `A2AClient` | 读取 Agent Card，发现 JSONRPC interface，发送标准 `SendMessage` |
| `PreferenceModule` | 本地读取用户 profile，本地排序 |
| `UserButler` | 串联 LLM 意图判断、A2A 调用、风险拦截、最终回答 |

关键隐私设计:

- 完整 profile 只在 `PreferenceModule` 内本地使用
- `minimal_constraints()` 默认返回空对象和空披露字段列表
- A2A `browse` Message 的 DataPart 只发送任务派生的 `query`、`top_k`、`constraints`
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
curl -s -X POST "$A2A_URL/a2a" \
  -H 'content-type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"smoke-browse","method":"SendMessage","params":{"message":{"messageId":"smoke-message-1","role":"ROLE_USER","parts":[{"data":{"skill":"browse","input":{"top_k":2}}}]}}}' \
  | python3 -m json.tool
```

读取刚返回的 Task（把 `<TASK_ID>` 替换为响应中的 `result.task.id`）:

```bash
curl -s -X POST "$A2A_URL/a2a" \
  -H 'content-type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"smoke-get","method":"GetTask","params":{"id":"<TASK_ID>"}}' \
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
- 高风险动作先返回预览和 input-required，再通过同一 A2A task/context 确认
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

### 13.2 purchase 是否会创建和支付订单?

会，但只在显式确认后。第一次请求用于建立确认门，不创建任何数据；同一
A2A task/context 的确认 continuation 会执行完整本地流程：

```text
ShoppingCartItem -> Order(PENDING) -> Order(PLACED)
-> Payment(PENDING) -> Payment(SUCCEEDED)
```

Payment 的最终结果由 MiSArch 本地 Simulation 服务产生，不会连接真实银行或
信用卡网络。测试会留下订单、支付、发票及下游 saga 数据，并可能消耗/预留库存。

### 13.3 为什么没有认证?

这是实验实现。当前 Agent Card 没有声明 `securitySchemes` /
`securityRequirements`。

生产化时应增加认证、授权、审计日志和 rate limit。

### 13.4 这是真实 A2A 协议吗?

是，主路径已经是 A2A 1.0 的标准 wire 交互:

```text
GET  /.well-known/agent-card.json
POST /a2a  JSON-RPC SendMessage / GetTask
```

服务端使用官方 Go SDK，Task/Message/Artifact/DataPart 也使用 SDK 类型。但这
不等于“生产完备”或“TCK 已认证”：streaming、push、持久化 task store、认证、
签名和 TCK 验证仍未完成。

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
curl -s -X POST "$A2A_URL/a2a" \
  -H 'content-type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"check","method":"SendMessage","params":{"message":{"messageId":"check-message","role":"ROLE_USER","parts":[{"data":{"skill":"browse","input":{"top_k":2}}}]}}}' \
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
- 没有 streaming
- purchase 使用进程内任务状态；容器重启后不能继续旧的确认任务
- 支付与订单在 federated GraphQL 中没有直接 Payment ID 关联字段，因此测试账号应串行购买
- 没有跨 agent trace id 标准化

如果要生产化，建议优先补:

1. Auth / authorization
2. Request id / trace id / audit log
3. Durable task state
4. A2A TCK / Inspector 验证
5. Durable idempotency key
6. 可关联订单与支付的审计字段
