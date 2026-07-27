# MiSArch Agent Gateway：2小时官方文档速学版

> 目标：用120分钟掌握本项目的核心原理，能够解释 GraphQL、MCP、Profile、A2A、延迟、token、hop 和安全结果。
>
> 原则：只读与当前实现直接相关的官方文档片段，不追求完整读完协议。
>
> 2026-07-27 实现更新：store-agent 主路径已升级为官方 `a2a-go/v2`
> SDK + A2A 1.0 JSON-RPC `SendMessage` / `GetTask`。本文后面“简化
> A2A / 自定义 `/tasks`”的判断是升级前快照。

## 一、两小时结束后必须会讲什么

你应该能够不看稿解释下面这张图：

```text
Arm A: 测试脚本 ───────────────────────→ GraphQL

Arm B: 用户任务 → LLM decision loop → MCP Client → MCP Gateway → GraphQL

Arm D: 用户任务 + 本地 Profile
                         ↓
                     同一个 LLM/MCP 路径 ───────────────→ GraphQL

Arm C: 用户任务 + 本地 Profile → Butler → 简化 A2A → Store Agent → GraphQL
```

同时记住：

1. GraphQL 是后端数据接口。
2. MCP 是面向 Agent 的工具合同和调用协议。
3. LLM 决定下一步动作，但 LLM 不是 MCP 的组成部分。
4. Profile 只是追加到 prompt，不是 MCP Resource。
5. 当前 A2A 是简化实现，不是完整 A2A 1.0。

## 二、120分钟安排

| 时间 | 主题 | 目标 |
| --- | --- | --- |
| 0–10分钟 | 项目总览 | 分清四个实验 Arm |
| 10–25分钟 | GraphQL | 理解真正的数据访问层 |
| 25–55分钟 | MCP 原理 | 掌握生命周期、transport 和 tools |
| 55–75分钟 | MCP Go 实现 | 把规范映射到项目代码 |
| 75–95分钟 | LLM、Profile、token | 理解决策轮数与成本来源 |
| 95–110分钟 | A2A 与安全 | 分清架构思想与标准协议 |
| 110–120分钟 | 实验指标与复述 | 会解释 latency、token、hop 和限制 |

---

## 0–10分钟：先理解四个 Arm

### 阅读

- 本项目 [`README.md`](../README.md) 的 Architecture、Tools 和 Baseline。
- 本项目 [`presentation-defense-50-questions.zh.md`](presentation-defense-50-questions.zh.md) 中的 Q1、Q2、Q17、Q19。

### 必须形成的认识

#### Arm A：Direct GraphQL

测试脚本执行预写 GraphQL query，直接访问 MiSArch GraphQL Gateway。默认没有 LLM，也不是 Agent 自己生成 query。

#### Arm B：MCP

LLM 根据 task、工具 schema 和 history 输出下一步 decision。Python MCP Client 再执行 MCP `tools/call`，MCP Gateway 最终访问 GraphQL。

#### Arm D：MCP + Profile

与 Arm B 使用相同 MCP Client、MCP Gateway 和 GraphQL backend。唯一主要变化是把用户 Profile 加进 LLM prompt。

#### Arm C：A2A

Butler 保留完整 Profile，通过 Agent Card 发现 Store Agent，再发送 browse task。Store Agent 返回候选，Butler 本地筛选和排序。

### 30秒复述

> 四个 Arm 比较的不是四种数据库，而是四种访问和编排方式。所有业务数据最终都来自 MiSArch GraphQL。差别在于前面是否增加 MCP 工具层、LLM decision loop、Profile 上下文或 Agent-to-Agent 信任边界。

---

## 10–25分钟：GraphQL 是真正的数据层

### 官方文档，只读这些部分

1. [GraphQL Queries and Mutations](https://graphql.org/learn/queries/)：
   - Fields
   - Arguments
   - Variables
   - Mutations
2. [GraphQL Response](https://graphql.org/learn/response/)：
   - Data
   - Errors
3. [MiSArch Project Overview](https://misarch.github.io/docs/)：只看 project purpose 和 documentation overview。

### 对照代码

- `internal/misarch/client.go`
- `internal/catalog/service.go`
- `internal/order/service.go`

### 需要看懂的实现

`internal/misarch/client.go` 向 `/graphql` POST：

```json
{
  "query": "query or mutation text",
  "variables": {}
}
```

GraphQL 返回：

```json
{
  "data": {},
  "errors": []
}
```

项目再把 GraphQL 数据转换成稳定的 Go output，交给 MCP tool handler。

### 必须会回答

**为什么还需要 MCP？**

GraphQL 对程序很灵活，但 Agent 必须理解完整 schema 并构造 query。MCP Gateway 把允许的能力缩小成 `list_products`、`get_product`、`create_pending_order`，输入 schema 更小、行为更容易检查，也更容易控制写操作。

**MCP 是否替代 GraphQL？**

没有。MCP 是 GraphQL 前面的适配和治理层，真正的商品和订单数据仍由 GraphQL 提供。

### 30秒复述

> GraphQL 是统一的数据 API。Direct GraphQL 使用预写 query，路径最短。MCP Gateway 没有替换 GraphQL，而是把复杂 schema 包装成少量 Agent 可发现的工具，因此增加了一层开销，但提供了更稳定和受控的接口。

---

## 25–55分钟：MCP 原理

这是两小时中最重要的30分钟。

### 官方文档，只读这些部分

1. [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)：
   - Host、Client、Server
   - Tools、Resources、Prompts
2. [MCP Lifecycle 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)：
   - Initialization
   - Version Negotiation
   - Capability Negotiation
3. [MCP Transports 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)：
   - Streamable HTTP
   - Session ID
4. [MCP Tools 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)：
   - `tools/list`
   - `tools/call`
   - input schema
   - tool result

项目客户端声明的是 `2025-06-18`，因此先学这个版本，不要在速学阶段混入其他版本。

### MCP 四层职责

```text
LLM
  决定下一步：tool_call 或 final

MCP Client
  initialize、tools/list、tools/call、维护 session

MCP Server
  声明工具名称、描述、input schema，执行 handler

GraphQL Client
  调用真正的 MiSArch backend
```

### MCP 生命周期

```text
1. POST initialize
   客户端声明协议版本和能力

2. Server 返回 initialize result
   返回协商版本、server info、server capabilities 和 session ID

3. notifications/initialized
   客户端表示初始化完成

4. tools/list
   发现工具合同

5. tools/call
   按 schema 调用工具
```

这就是为什么不能把 `/mcp` 当成普通 REST endpoint，直接先发 `tools/list`。

### 项目使用的 MCP 特性

| 特性 | 使用情况 |
| --- | --- |
| JSON-RPC | 使用 |
| initialize/initialized | 使用 |
| 协议版本与 capability negotiation | 使用 |
| Streamable HTTP `/mcp` | 使用 |
| session ID | 使用 |
| `tools/list`、`tools/call` | 使用 |
| input schema、structured result | 使用 |
| Resources | 未使用 |
| Prompts | 未使用 |
| Sampling | 未使用 |
| Roots、Elicitation | 未使用 |

### 必须会回答

**MCP 中一定有 LLM 吗？**

不一定。确定性测试程序也可以作为 MCP Client 直接调用工具。LLM 只在 Arm B/D 的 end-to-end decision loop 中参与。

**MCP + Profile 使用了什么特殊 MCP feature？**

没有。它仍然只使用 MCP Tools。Profile 在进入 MCP 前已经被加到 LLM prompt 中。

### 45秒复述

> MCP 把 Agent 和业务工具之间的通信标准化。本项目使用 JSON-RPC 和 Streamable HTTP。客户端先 initialize，完成版本和能力协商，再通过 tools/list 发现工具，通过 tools/call 调用工具。服务器端把调用转成 GraphQL。项目没有使用 Resources、Prompts 或 Sampling，所以 Profile 也不是通过 MCP 管理的。

---

## 55–75分钟：MCP Go 实现

### 官方文档

- [MCP 官方 Go SDK v1.6.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.6.0)
- [Go SDK `mcp` package](https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.6.0/mcp)

只看 server、tool 和 Streamable HTTP 示例。

### 对照代码

集中阅读 `internal/mcpserver/server.go`。

### 看懂四个调用

#### 1. `mcp.NewServer`

创建 MCP Server，并声明 server name 和 version。

#### 2. `mcp.AddTool`

注册三个工具：

- `list_products`
- `get_product`
- `create_pending_order`

#### 3. Go input struct

例如 `ListProductsInput` 和 `GetProductInput` 的 JSON/schema tag 会参与生成工具的 input schema。

#### 4. `mcp.NewStreamableHTTPHandler`

把 MCP Server 暴露为 Streamable HTTP handler，最后挂载到 `/mcp`。

### 一次工具调用的内部路径

```text
tools/call list_products
        ↓
MCP SDK 校验/解析 arguments
        ↓
handleListProducts
        ↓
catalog.Service.ListProducts
        ↓
misarch.Client.Do
        ↓
GraphQL POST
        ↓
类型化 tool result
```

### 一个容易说错的点

项目在 tool description 中写了 read-only 或 controlled side effect，但没有完整依赖标准 `ToolAnnotations` 表达所有风险语义。因此更准确的说法是：

> 风险和副作用目前主要通过工具描述、工具边界和业务输出显式表达。

---

## 75–95分钟：LLM、Profile 和 token

### 官方文档，只读这些部分

1. [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)：看 `model`、`input`、`max_output_tokens` 和 response usage。
2. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：了解当前自定义 JSON decision 的改进方向。
3. [Counting tokens](https://developers.openai.com/api/docs/guides/token-counting)：理解 API usage 与字符估算的区别。

### 对照代码

- `scripts/agent_gcp_baseline_test.py` 中的 `responses_api_call`
- `scripts/agent_mcp_loop.py` 中的：
  - `build_decision_prompt`
  - `parse_model_decision`
  - `load_profile_for_user`

### 当前 LLM 机制

项目向 Responses API 发送一个完整文本 prompt，要求模型输出：

```json
{"type":"tool_call","name":"list_products","arguments":{"top_k":10}}
```

或者：

```json
{"type":"final","answer":"..."}
```

Python 解析这个 JSON 后，才调用 MCP。

因此当前没有使用：

- OpenAI 原生 function calling；
- OpenAI Agents SDK；
- OpenAI API 直接连接 MCP；
- MCP Sampling。

### 为什么 B 是三次 decision，D 常见两次？

Arm B 的一次观察序列：

```text
Decision 1: final
→ 控制器发现此前没有成功工具调用
→ final_rejected

Decision 2: list_products
→ 获得 catalog observation

Decision 3: final
```

Arm D 的一次观察序列：

```text
任务 + 材质/容量/预算 Profile
→ 模型更容易把“先获取候选商品”判断成有用的第一步

Decision 1: list_products
Decision 2: final
```

关键点：控制器只强制“final 前至少成功调用一次工具”，没有规定第一步必须是什么。Profile 改变的是模型上下文，所以少一次调用是实验观察，不是协议保证。

### 为什么少一轮但 token 只少一点？

因为 D 每轮 prompt 更长，而且后续轮次仍会重新发送：

- system/rules；
- offered tool schema；
- task；
- Profile；
- 完整 history；
- catalog observation。

调用次数减少和单次 prompt 变长互相抵消。

### Token 测量口径

优先级从高到低：

1. Responses API 返回的 `usage.input_tokens`、`usage.output_tokens`、`usage.total_tokens`。
2. 对准确输入使用官方 token counting 方法。
3. `ceil(characters/4)` 只能称为粗略估算。

### 45秒复述

> LLM 只负责输出下一步 decision，Python 控制器负责验证并真正执行 MCP。Profile 只是额外 prompt context，所以可能让模型更早调用 catalog，但不保证减少轮数。即使少一轮，Profile、工具 schema、history 和商品结果仍会反复进入上下文，因此总 token 可能只下降一点。

---

## 95–110分钟：A2A 与安全

### 官方文档，只读这些部分

- [A2A 1.0 Specification](https://a2a-protocol.org/latest/specification/)：搜索并阅读 Agent Card、Task、Artifact、Security。
- [A2A 官方项目说明](https://github.com/a2aproject)：看协议目标和官方 SDK 列表。
- [OWASP LLM/GenAI Top 10](https://genai.owasp.org/llm-top-10/)：重点看 Prompt Injection 和 Sensitive Information Disclosure。

### 对照代码

- `internal/a2aserver/server.go`
- `scripts/agent_a2a_loop.py`

### 当前 A2A 路径

```text
Butler
  ↓ GET /.well-known/agent-card.json
发现 Store Agent 的 browse/purchase skill

Butler
  ↓ POST /tasks, skill=browse
Store Agent
  ↓ GraphQL list/get product
返回候选 artifact

Butler
  ↓
用本地完整 Profile 过滤、排序和执行风险检查
```

### Profile 隐私机制

完整 Profile 保存在 Butler 本地。Store Agent 默认只收到从任务推导出的 query 和白名单 constraints。

这减少了字段泄露，但不能说成零信息泄露，因为 query 本身仍可能暴露用户意图。

### 为什么不是完整 A2A？

当前项目：

- 自己定义 Agent Card 和 Task struct；
- 使用自定义 REST `POST /tasks`；
- 没有使用官方 Go SDK；
- 没有实现完整标准 message/task operations；
- 没有版本协商、streaming、push notification 和 TCK 验证。

因此应表述为：

> 这是受 A2A 启发的简化实验实现，用于研究 Agent discovery、task delegation、Profile 本地化和跨信任域安全。

### 四类安全测试

| 测试 | 攻击对象 | 为什么出现对应结果 |
| --- | --- | --- |
| Fake Agent Card | Agent 自报的风险和能力 | Butler 有独立风险规则时容易阻止 |
| Fake Price | Store 返回的数据完整性 | 明显异常值容易被阈值规则捕获 |
| Disguised Purchase | 浏览和购买意图边界 | 自然语言分类不稳定，所以不是100% |
| Backdoor Hidden Intent | Butler/模型自身可信度 | 触发器可绕过同一控制器中的检查，因此最难防 |

### 安全结论

Profile 留在本地只解决部分隐私问题，不能自动保证外部 Agent 数据可信，也不能防止本地 Butler 自身被植入后门。高风险操作必须使用模型外的确定性 policy 和用户确认。

---

## 110–120分钟：指标、结果和最后复述

### Latency

需要区分：

- per-read latency：一次确定性 GraphQL/MCP read；
- LLM latency：一次 Responses API 请求；
- end-to-end latency：从用户 task 到最终回答；
- backend latency：GraphQL 实际执行时间。

MCP end-to-end 较慢的主要原因通常不是单个 GraphQL read，而是重复 LLM decision 和不断增长的上下文。

### Hop

项目中的 hop 是人为定义的跨组件网络步骤，不是协议自动统计值：

- MCP/D：Gateway → GraphQL backend，记一个 backend hop；
- A2A：Agent Card discovery 和 task request，各记一个 A2A hop；
- LLM 调用、本地 ranking、进程内函数不计入当前 hop。

所以 hop 不能直接等同于 LLM 调用次数或全部 HTTP 请求数。

### Reliability

“60个 runs 全部成功”只说明程序完成并返回了符合格式的结果，不自动证明：

- 找到了正确商品；
- Profile 被正确采用；
- 订单真的创建；
- 安全攻击被阻止；
- 各 Arm 执行了相同工作量。

### A2A 为什么看起来更快？

部分任务因为 catalog 没有匹配商品而提前进入 inventory shortfall 分支，没有执行完整推荐、排序和购买流程。因此这个结果不能直接证明 A2A 协议天然更快。

## 三、最后两分钟背诵稿

> 本项目的后端数据统一来自 MiSArch GraphQL。Arm A 使用预写 GraphQL query，主要作为最短路径基线。Arm B 在 GraphQL 前增加 MCP Gateway，并由 LLM decision loop 决定调用哪个 MCP tool。MCP 提供初始化、能力协商、工具发现、输入 schema 和结构化结果，但额外的 LLM 轮次增加了端到端延迟和 token 成本。
>
> Arm D 沿用完全相同的 MCP 路径，只把本地 Profile 加入 prompt。Profile 可能让模型第一步直接查询 catalog，所以实验中少了一次 decision，但这属于 prompt conditioning，不是 MCP 的固定机制，也不是 MCP Resource。
>
> Arm C 把完整 Profile 保留在 Butler 本地，通过简化 A2A 与 Store Agent 协作。这改善了信任域分离和 Profile 最小披露，但当前 `/tasks` 是自定义 REST 接口，不是完整 A2A 1.0。实验结果还受到空 catalog、提前终止和不同任务工作量影响，因此延迟、token、hop、成功率和安全率必须结合执行路径解释。

## 四、如果只剩10分钟

只做下面五件事：

1. 背下四个 Arm 的架构图。
2. 背下 MCP 流程：`initialize → initialized → tools/list → tools/call`。
3. 记住 Profile 只是 prompt，不是 MCP Resource。
4. 记住当前 OpenAI 调用是文本 Responses API + 自定义 JSON，不是 function calling。
5. 记住当前 A2A 是简化架构实验，不是完整协议实现。

## 五、速学后自测

不看文档回答：

- Direct GraphQL 中有没有 LLM？
- MCP 和 GraphQL 分别负责什么？
- 为什么不能直接调用 `tools/list`？
- MCP Gateway 使用了哪些协议特性？
- Profile 在哪里加载、发给谁、是否经过 MCP？
- 为什么 B 三次 decision、D 两次？
- 为什么 D 少一轮但 token 只少一点？
- 当前 Responses API 是否使用 function calling？
- hop 在这个实验里如何定义？
- 为什么 A2A 有两个 hop？
- 为什么 A2A 较快不能证明协议更快？
- 为什么当前实现不能宣称完整 A2A compatible？
- 四类安全攻击分别攻击哪一层？
- 为什么100% run success不等于100% correctness？

如果这些问题都能用两三句话回答，两小时学习目标就完成了。
