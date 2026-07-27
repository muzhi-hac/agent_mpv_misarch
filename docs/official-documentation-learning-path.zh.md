# MiSArch Agent Gateway 官方文档学习路线

> 核对日期：2026-07-13
>
> 2026-07-27 实现更新：store-agent 主路径已升级为官方 `a2a-go/v2`
> SDK + A2A 1.0 JSON-RPC `SendMessage` / `GetTask`。本文后面把 `/tasks`
> 称为“简化 A2A”的段落是升级前快照；`/tasks` 现在仅为兼容入口。
>
> 项目范围：MiSArch GraphQL、Go MCP Gateway、OpenAI Responses API 控制器、MCP + Profile、A2A 1.0、Docker/GCP 部署、Keycloak 与安全评估。

## 1. 先建立正确的项目地图

这个项目不是“一个 LLM 直接调用 GraphQL”，而是包含几条不同的实验路径：

```text
Arm A: 测试脚本 ───────────────→ MiSArch GraphQL

Arm B: 用户任务 → LLM 控制器 → MCP Client → MCP Gateway → GraphQL

Arm D: 用户任务 + Profile
                    ↓
                LLM 控制器 → MCP Client → MCP Gateway → GraphQL

Arm C: 用户任务 + 本地 Profile → Butler → 简化 A2A → Store Agent → GraphQL
```

阅读外部文档前，先读本仓库中的以下材料：

1. [`README.md`](../README.md)：服务目标、工具、配置和运行方法。
2. [`docs/project-learning-guide-for-beginners.zh.md`](project-learning-guide-for-beginners.zh.md)：项目级入门说明。
3. [`docs/presentation-defense-50-questions.zh.md`](presentation-defense-50-questions.zh.md)：实现证据、实验解释和答辩问题。

随后按本文的顺序学习官方资料。

## 2. 最小必读清单

如果时间有限，先读下面 14 项。读完后应该能完整解释项目的主链路。

| 顺序 | 官方资料 | 需要掌握的内容 | 对应项目代码 |
| --- | --- | --- | --- |
| 1 | [MiSArch Project Overview](https://misarch.github.io/docs/) | MiSArch 是什么、微服务和统一 GraphQL Gateway 的位置 | `internal/misarch`、`internal/catalog`、`internal/order` |
| 2 | [GraphQL Learn: Queries](https://graphql.org/learn/queries/) | query、mutation、variables、字段选择 | `internal/catalog/service.go`、`internal/order/service.go` |
| 3 | [GraphQL Response](https://graphql.org/learn/response/) | `data`、`errors`、部分成功 | `internal/misarch/client.go` |
| 4 | [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture) | host、client、server、tools/resources/prompts 的职责 | `/mcp` 整体链路 |
| 5 | [MCP Lifecycle 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle) | `initialize`、版本协商、`notifications/initialized` | `scripts/agent_mcp_loop.py` |
| 6 | [MCP Streamable HTTP 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) | HTTP endpoint、session、GET/POST、SSE | `internal/mcpserver/server.go`、`internal/httpserver` |
| 7 | [MCP Tools 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | `tools/list`、`tools/call`、input schema、tool result | `internal/mcpserver/server.go` |
| 8 | [官方 MCP Go SDK v1.6.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.6.0) | `mcp.NewServer`、`mcp.AddTool`、Streamable HTTP handler | `go.mod`、`internal/mcpserver/server.go` |
| 9 | [OpenAI Responses API：Create a response](https://developers.openai.com/api/reference/resources/responses/methods/create) | `POST /v1/responses`、`model`、`input`、`max_output_tokens`、`usage` | `scripts/agent_gcp_baseline_test.py` |
| 10 | [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | 如何让模型稳定输出符合 schema 的 JSON | 当前自定义 JSON decision loop 的升级方向 |
| 11 | [OpenAI Counting tokens](https://developers.openai.com/api/docs/guides/token-counting) | API usage 与输入 token 预估的区别 | `eval/llm-token-retest-*`、旧 token estimate |
| 12 | [A2A 1.0 Specification](https://a2a-protocol.org/latest/specification/) | Agent Card、Message、Task、Artifact、版本和安全 | 用来对照项目的简化 A2A |
| 13 | [Docker Compose Networking](https://docs.docker.com/compose/how-tos/networking/) | Docker DNS、服务名、external network | `MISARCH_GRAPHQL_URL=http://gateway:8080/graphql` |
| 14 | [Keycloak OIDC](https://www.keycloak.org/securing-apps/oidc-layers) | token endpoint、grant type、Bearer token | `internal/misarch/auth.go` |

## 3. MiSArch 与 GraphQL

### 3.1 必读

- [MiSArch 官方文档首页](https://misarch.github.io/docs/)：先理解 MiSArch 的目标、服务组成和基础设施。
- [MiSArch Architecture](https://misarch.github.io/docs/category/architecture/)：理解微服务边界和组件关系。
- [MiSArch GraphQL Schema](https://misarch.github.io/docs/graphql/schema/)：查询实际类型、query、mutation、input 和 enum。
- [GraphQL Learn](https://graphql.org/learn/)：面向开发者的入门材料。
- [GraphQL September 2025 Specification](https://spec.graphql.org/September2025/)：规范性参考，答辩时用于准确解释 selection set、variables、validation 和 execution。
- [GraphQL over HTTP Working Draft](https://graphql.github.io/graphql-over-http/draft/)：理解项目为什么向 `/graphql` POST `{query, variables}`，以及 HTTP status 与 GraphQL `errors` 不完全等价。注意它仍是 working draft。

### 3.2 对照代码阅读

按以下顺序查看：

1. `internal/misarch/client.go`：把 query 和 variables 编码为 JSON，经 HTTP POST 发送，并处理 `data` 与 `errors`。
2. `internal/catalog/service.go`：商品列表和详情 query，以及到 MCP 输出的转换。
3. `internal/order/service.go`：mutation 和 pending order 流程。

读完应能回答：

- Direct GraphQL 为什么不需要 LLM？
- GraphQL HTTP 200 是否一定代表业务成功？
- MCP Gateway 是否替代了 GraphQL？
- 为什么 Gateway 只暴露少量工具，而不是暴露整个 GraphQL schema？

正确结论是：GraphQL 仍然是后端数据接口；MCP Gateway 是面向 Agent 的受控适配层。

## 4. Go 服务实现

### 4.1 必读

- [How to Write Go Code](https://go.dev/doc/code)：package、module 和代码组织。
- [`go.mod` reference](https://go.dev/doc/modules/gomod-ref)：理解项目依赖和版本固定。
- [`net/http`](https://pkg.go.dev/net/http)：HTTP client、server、handler、request context。
- [`context`](https://pkg.go.dev/context)：超时、取消和请求生命周期。
- [`encoding/json`](https://pkg.go.dev/encoding/json)：结构体 tag、marshal/unmarshal。
- [`testing`](https://pkg.go.dev/testing)：单元测试和 table-driven tests。

### 4.2 对照代码阅读

- `cmd/server/main.go`：依赖组装和服务启动。
- `internal/httpserver/server.go`：路由、health/readiness、CORS 和 MCP/A2A handler 挂载。
- `internal/config/config.go`：环境变量解析和配置校验。
- `internal/misarch/client.go`：带 context 和 timeout 的 HTTP client。
- `internal/*/*_test.go`：用 `httptest` 验证协议和业务行为。

项目的 `go.mod` 固定了 `github.com/modelcontextprotocol/go-sdk v1.6.0`，因此学习 SDK 时优先阅读 [v1.6.0 tag](https://github.com/modelcontextprotocol/go-sdk/tree/v1.6.0)，不要直接照抄 main 分支未来版本的 API。

## 5. MCP：本项目的核心协议

### 5.1 先理解四层

```text
LLM：决定下一步想做什么
MCP Client：执行 initialize、tools/list、tools/call
MCP Server：声明工具合同并分发调用
GraphQL Client：执行真正的 MiSArch 后端请求
```

LLM 不是 MCP 协议的一部分；MCP 也不要求每一次工具调用必须由 LLM 决定。项目的 direct MCP latency probe 可以用确定性脚本调用 MCP，而 Arm B/D 的 end-to-end agent loop 才加入 LLM。

### 5.2 与当前代码严格匹配的规范版本

`scripts/agent_mcp_loop.py` 默认在 initialize 中声明 `2025-06-18`，因此复现实验时先读该版本：

- [Base protocol](https://modelcontextprotocol.io/specification/2025-06-18/basic/)
- [Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)
- [Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)

然后阅读当前稳定版以了解升级差异：

- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/)
- [2025-11-25 Key Changes](https://modelcontextprotocol.io/specification/2025-11-25/changelog)

### 5.3 官方 Go SDK

- [Go SDK v1.6.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.6.0)
- [Go SDK `mcp` package v1.6.0](https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.6.0/mcp)
- [Go SDK examples v1.6.0](https://github.com/modelcontextprotocol/go-sdk/tree/v1.6.0/examples)

对照 `internal/mcpserver/server.go` 重点找：

- `mcp.NewServer`：创建 MCP Server。
- `mcp.AddTool`：注册强类型工具。
- Go input struct 的 JSON/schema tag：生成输入 schema。
- handler 返回类型：形成 tool result 和 structured output。
- `mcp.NewStreamableHTTPHandler`：把 MCP Server 挂到 HTTP。

### 5.4 调试工具

- [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector)：查看 initialize、工具 schema 和调用结果。
- [MCP Debugging Guide](https://modelcontextprotocol.io/docs/tools/debugging)：按 transport、server 和 client 分层排错。
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)：理解 `jsonrpc`、`id`、`method`、`params`、result/error 和 notification。

### 5.5 本项目用了和没用哪些 MCP 能力

| MCP 能力 | 当前是否使用 | 说明 |
| --- | --- | --- |
| JSON-RPC request/response/notification | 是 | initialize、initialized、tools/list、tools/call |
| Lifecycle 与版本协商 | 是 | 客户端必须先 initialize |
| Streamable HTTP | 是 | 暴露在 `/mcp` |
| Session ID | 是 | 客户端保存 `Mcp-Session-Id` |
| Tools 与 input schema | 是 | 三个业务工具 |
| Structured tool result | 是 | Go 类型化 output |
| Resources | 否 | Profile 不是 MCP Resource |
| Prompts | 否 | decision prompt 写在 Python 脚本里 |
| Sampling | 否 | MCP Server 不请求 MCP Client 代为调用模型 |
| Roots | 否 | 没有文件系统 roots |
| Elicitation | 否 | 没有通过 MCP 向用户追问信息 |
| 标准 ToolAnnotations | 未实质使用 | read-only/side-effect 主要写在 description 和项目输出字段中 |

选读未使用能力的官方文档：

- [Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)
- [Sampling](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)
- [Elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

这些材料用于说明“还可以做什么”，不应在答辩中描述为已经实现。

## 6. OpenAI Responses API 与 Agent 决策循环

### 6.1 当前实现

`scripts/agent_gcp_baseline_test.py` 使用 Python 标准库直接发 HTTP 请求：

```text
POST {base_url}/v1/responses
Authorization: Bearer ...

{
  "model": "...",
  "input": "完整 prompt 字符串",
  "max_output_tokens": 700
}
```

`scripts/agent_mcp_loop.py` 要求模型返回两种自定义 JSON decision 之一：

```json
{"type":"tool_call","name":"list_products","arguments":{"top_k":10}}
```

或：

```json
{"type":"final","answer":"..."}
```

Python 控制器解析这个 JSON，才真正调用 MCP。也就是说，当前实现：

- 使用了 Responses API 的文本生成；
- 没有把 MCP tools 作为 OpenAI `tools` 参数提交；
- 没有使用原生 function calling；
- 没有使用 OpenAI Agents SDK；
- 没有让 OpenAI API 直接连接 MCP Server。

### 6.2 必读官方资料

- [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)：与当前 HTTP 请求最直接对应。
- [Text generation](https://developers.openai.com/api/docs/guides/text)：理解 `input` 和生成输出。
- [Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)：理解 Responses 的对象模型和状态管理。
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：减少 JSON parse retry 的升级方向。
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)：把自定义 `type=tool_call` 迁移为原生 tool call 时再使用。
- [Reasoning best practices](https://developers.openai.com/api/docs/guides/reasoning-best-practices)：理解为什么 prompt、任务和历史会影响决策轮数。
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)：理解重复发送 tool schema/history 时的缓存与计费问题。

### 6.3 Profile 的正确理解

Arm D 只是把本地 JSON Profile 追加到同一个 decision prompt：

```text
User task
+ offered MCP tools
+ history
+ User preference profile
→ Responses API
```

它不是：

- MCP Resource；
- MCP prompt template；
- 服务端 personalization；
- A2A Profile 传输；
- 一条保证减少 LLM 调用次数的规则。

Profile 只改变模型看到的上下文，所以可能改变第一次 decision。实验中少一轮是观察到的模型行为，不是 MCP 或 Responses API 的固定机制。

## 7. Token、延迟与评估

### 7.1 Token

官方资料：

- [Counting tokens](https://developers.openai.com/api/docs/guides/token-counting)
- [Responses API response object](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Organization Usage API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage)

项目中存在两种口径，不能混为一谈：

1. 旧估算：`ceil(character_count / 4)`，见 `eval/full-abcd-c2-20260702/token_estimate/token_estimate_summary.json`。这是近似值。
2. 后续复测：保存 Responses API 返回的 `usage.input_tokens`、`usage.output_tokens` 和 `usage.total_tokens`，见 `eval/llm-token-retest-*`。这是更应优先报告的 API 口径。

### 7.2 延迟

建议区分：

- protocol/backend latency：单次 GraphQL、MCP 或 A2A HTTP 请求；
- LLM latency：每次 Responses API 调用；
- end-to-end latency：从用户任务开始到最终答案；
- warm-up、网络波动和 outlier：必须单独记录。

官方评估资料：

- [OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [Go `time` package](https://pkg.go.dev/time)
- [Python `time.perf_counter`](https://docs.python.org/3/library/time.html#time.perf_counter)
- [Python `statistics`](https://docs.python.org/3/library/statistics.html)

### 7.3 Hop

Hop 不是 MCP 或 A2A 自动生成的统一指标。当前项目把 hop 定义为跨组件的显式网络请求：

- MCP/Arm B、D：MCP Gateway 到 GraphQL backend 记作一个 backend hop；
- A2A/Arm C：Agent Card discovery 和 task request 各记作一个 A2A hop；
- LLM decision、本地 Profile 排序和进程内函数调用不计入该字段。

因此必须把操作性定义和计数位置一起报告；不能把 hop 直接当成 LLM 调用次数、HTTP 往返总数或微服务总跳数。

## 8. A2A：标准与项目简化实现的区别

### 8.1 官方资料

- [A2A Documentation](https://a2a-protocol.org/latest/)
- [A2A 1.0 Specification](https://a2a-protocol.org/latest/specification/)
- [A2A 官方 GitHub 组织](https://github.com/a2aproject)
- [A2A 官方 Go SDK](https://github.com/a2aproject/a2a-go)
- [A2A 官方 samples](https://github.com/a2aproject/a2a-samples)
- [A2A Inspector](https://github.com/a2aproject/a2a-inspector)
- [A2A Technology Compatibility Kit](https://github.com/a2aproject/a2a-tck)

重点学习：

- Agent Card discovery；
- Agent Card 中的 identity、interfaces、capabilities、skills 和 security；
- Message、Part、Task、TaskState、Artifact；
- blocking、streaming、push notification；
- protocol binding 和版本协商；
- OAuth/TLS、输入验证和外部 Agent 不可信原则。

### 8.2 当前项目是什么

当前 `internal/a2aserver` 自己定义 Go struct，并暴露：

```text
GET  /.well-known/agent-card.json
POST /tasks
```

它验证的是以下架构思想：

- Butler 与 Store Agent 分处不同信任域；
- 通过 Agent Card 发现能力；
- 通过 task 委派 browse/purchase；
- 完整 Profile 留在 Butler 本地；
- 外部 Agent 的 card 和 artifact 可能恶意。

但它不是完整 A2A 1.0 实现，因为没有使用官方 SDK/schema、标准 message/task operations、版本 header、标准 binding、streaming/push 和 TCK conformance。项目自定义的 `risk_level`、`side_effects`、`requires_confirmation` 也不应自动宣称为 A2A 标准字段。

如果以后需要声称“A2A compatible”，应使用官方 Go SDK重构，并通过 Inspector/TCK 验证。

## 9. Docker、GCP 与 CI/CD

### 9.1 Docker

- [Dockerfile overview](https://docs.docker.com/reference/dockerfile/)
- [Multi-stage builds](https://docs.docker.com/build/building/multi-stage/)
- [Compose services](https://docs.docker.com/reference/compose-file/services/)
- [Compose networking](https://docs.docker.com/compose/how-tos/networking/)
- [Environment variables](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
- [Healthcheck](https://docs.docker.com/reference/dockerfile/#healthcheck)

对照项目重点理解：

- 为什么容器内不能用宿主机的 `localhost` 找另一个容器；
- 为什么加入 `infrastructure-docker_default` 后可以用 `gateway:8080`；
- Dockerfile 为什么分 build 和 runtime stage；
- `/healthz` 与 `/readyz` 的区别。

### 9.2 Google Cloud Compute Engine

- [Compute Engine documentation](https://cloud.google.com/compute/docs)
- [Create and start a VM](https://cloud.google.com/compute/docs/instances/create-start-instance)
- [SSH connections](https://cloud.google.com/compute/docs/instances/ssh)
- [VPC firewall rules](https://cloud.google.com/firewall/docs/using-firewalls)
- [Service accounts for VMs](https://cloud.google.com/compute/docs/access/service-accounts)
- [Cloud Logging](https://cloud.google.com/logging/docs)

本项目当前是 VM + Docker 部署，不是 Kubernetes、GKE 或 Cloud Run。除非准备迁移，否则不必优先学习这些平台。

### 9.3 GitHub Actions

- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [Using secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [Security hardening for GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)

对照 `.github/workflows/deploy-main.yml` 学习 checkout、test/build、SSH、环境 secrets、容器替换和 health check。

## 10. Keycloak、OAuth 与 MCP Authorization

### 10.1 必读

- [Keycloak: Planning for securing applications](https://www.keycloak.org/securing-apps/overview)
- [Keycloak OIDC endpoints and grant types](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [MCP Authorization 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [RFC 9700: OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700)
- [RFC 9728: OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728)

### 10.2 当前项目的限制

`internal/misarch/auth.go` 使用 `grant_type=password`，把演示用户名和密码换成 access token，并缓存 token。这个实现主要用于 MiSArch demo write operation，不等于已经实现 MCP Authorization。

学习时要分清：

- Keycloak token 用于 Gateway 调用 MiSArch GraphQL；
- MCP endpoint 自身当前没有完整 OAuth protected-resource discovery；
- password grant 适合受控 demo 的兼容场景，但不应作为新生产系统的默认设计；
- 生产升级应研究 Authorization Code + PKCE、Client Credentials、最小权限和 secret management。

## 11. 安全评估

### 11.1 官方资料

- [OWASP Top 10 for LLM and GenAI Applications](https://genai.owasp.org/llm-top-10/)
- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [OpenAI Safety best practices](https://developers.openai.com/api/docs/guides/safety-best-practices)
- [A2A Specification: Security Considerations](https://a2a-protocol.org/latest/specification/#security-considerations)
- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)

### 11.2 映射到项目攻击

| 项目测试 | 应学习的安全概念 | 主要防御位置 |
| --- | --- | --- |
| Fake Agent Card | 信任发现、能力声明不可自证、签名/TLS | Butler 验证和 allowlist |
| Fake price | unsafe consumption、业务数据完整性、异常值检测 | Butler 本地验证和交叉检查 |
| Disguised purchase | intent classification、human confirmation、least privilege | Butler policy gate |
| Backdoor hidden intent | prompt injection、模型/控制器被污染、独立 policy enforcement | 模型外的确定性控制层 |

最重要的原则是：模型判断只能作为一层信号。涉及花钱、账户或写操作时，最终授权应由模型外的确定性 policy 和用户确认决定。

## 12. 暂时不需要优先学习的内容

以下技术经常与 Agent 项目一起出现，但当前项目没有使用：

| 技术 | 当前状态 | 何时再学 |
| --- | --- | --- |
| OpenAI Agents SDK | 未使用 | 希望用 SDK 替换手写 loop 时 |
| OpenAI 原生 MCP tool | 未使用 | 希望让 Responses API 直接连接 remote MCP 时 |
| OpenAI function calling | 未使用 | 希望替换自定义 JSON decision 时 |
| MCP Resources/Prompts/Sampling | 未使用 | 希望把 Profile/模板/模型调用纳入 MCP 时 |
| 官方 A2A Go SDK | 未使用 | 准备做线级协议兼容时 |
| Kubernetes/GKE | 未部署 | 准备从单 VM 扩展到集群时 |
| LangChain/LangGraph | 未使用 | 准备用框架替换 Python 手写编排时 |

## 13. 七天学习安排

### Day 1：系统和 GraphQL

阅读 MiSArch overview、architecture、GraphQL queries/response；沿着 `internal/misarch → catalog/order` 追一遍数据流。

产出：手画一张 GraphQL 请求和响应图，并能解释 Direct GraphQL baseline。

### Day 2：Go HTTP Gateway

阅读 Go module、`net/http`、`context` 和 JSON；阅读 `cmd/server`、`internal/httpserver`、`internal/misarch`。

产出：能解释服务如何启动、如何超时、如何检查 readiness。

### Day 3：MCP 基础协议

阅读 architecture、lifecycle、Streamable HTTP 和 JSON-RPC；手动写出 initialize → initialized → tools/list → tools/call。

产出：能解释为什么不能直接把 `/mcp` 当普通 REST endpoint。

### Day 4：MCP Go SDK 与工具

阅读 Go SDK v1.6.0、tools spec 和 Inspector；对照 `internal/mcpserver/server.go`。

产出：能说明 schema 怎样生成、工具怎样映射到 GraphQL、哪些 MCP feature 没有使用。

### Day 5：LLM controller、Profile 与评估

阅读 Responses API、structured outputs、token counting 和 evaluation best practices；阅读 `agent_mcp_loop.py`。

产出：能解释三次 decision 与两次 decision、Profile 机制、token/latency 测量口径。

### Day 6：A2A 与安全

阅读 A2A Agent Card、task/message/artifact 和 security；对照 `internal/a2aserver` 与 `agent_a2a_loop.py`。

产出：列出项目实现与官方 A2A 的至少五项差异，并能解释四类安全测试。

### Day 7：部署和总复习

阅读 Docker network、GCP VM/firewall/service account、GitHub Actions secrets 和 Keycloak OIDC。

产出：从用户请求开始，完整讲出 Arm A/B/C/D 的组件、协议、数据、信任边界和实验限制。

## 14. 学习完成检查表

如果下面的问题都能在一分钟内回答，说明资料已经掌握：

- [ ] 为什么在 GraphQL 上再加 MCP？
- [ ] MCP Server、MCP Client 和 LLM 各负责什么？
- [ ] `initialize` 为什么必须先于 `tools/list`？
- [ ] Streamable HTTP 与普通 REST 有什么区别？
- [ ] `list_products` 的 schema 从哪里来？
- [ ] Direct GraphQL benchmark 中是否有 LLM？
- [ ] Arm B/D 的 LLM 为什么会出现不同 decision 轮数？
- [ ] Profile 为什么不是 MCP Resource？
- [ ] Responses API 当前是否使用 function calling？
- [ ] API token usage 和 `chars/4` 有什么区别？
- [ ] hop 的项目定义是什么？
- [ ] 为什么当前 A2A 只能称为简化实现？
- [ ] 完整 Profile 在 A2A 路径中留在哪里？
- [ ] Fake Card、Fake Price、Disguised Purchase、Backdoor 分别攻击什么？
- [ ] 为什么 100% run success 不等于 100% task correctness？
- [ ] 为什么 A2A 的低延迟不能直接说明协议更快？
- [ ] Docker 中为什么使用 `gateway:8080` 而不是 `localhost:8080`？
- [ ] Keycloak token 保护的是哪一段调用？
- [ ] 当前 MCP endpoint 是否已经完成标准 OAuth authorization？
- [ ] 如果要升级为真正 A2A compatible，下一步是什么？

## 15. 最后记住的四句话

1. **GraphQL 是后端数据接口，MCP 是 Agent 可发现、可检查的工具合同。**
2. **LLM 决定是否调用工具，但 MCP 本身不等于 LLM，也不强制使用 LLM。**
3. **MCP + Profile 只是 prompt conditioning；Profile 没有通过 MCP Resource 传输。**
4. **项目 A2A 验证了架构和安全思想，但当前 REST `/tasks` 不是完整 A2A 1.0 线级实现。**
