# Presentation / Pre 准备文档：MiSArch + MCP Gateway + Agent Testing

这份文档用于准备课程 presentation / pre / 答辩。目标不是把所有命令背下来，而是形成一条清楚的讲述主线：

```text
为什么需要 agent-facing interface
  -> 为什么原生 MiSArch GraphQL 对 agent 不够友好
  -> 如何把 MiSArch 部署到 GCP
  -> 如何把本地 MCP gateway 部署到同一台云端 VM
  -> agent 如何通过 MCP 发现工具、调用工具、读取真实 MiSArch 数据
  -> 如何设计 baseline 比较原生 API 和 MCP 协议
  -> 实验结果说明了什么、没有说明什么
```

一句话核心结论：

```text
原生 MiSArch GraphQL 是强大的系统 API；MCP gateway 是更适合外部 agent 使用的安全、可发现、只读工具接口。
```

## 1. 你要讲的核心故事

### 1.1 Problem

现代 agent 不只是聊天，它需要调用外部系统。问题是：真实系统的 API 通常是给开发者写代码用的，不一定适合 agent 直接使用。

MiSArch 暴露 GraphQL API。GraphQL 很灵活，但 agent 直接使用 GraphQL 会遇到几个问题：

- agent 需要知道 schema 和 query 写法。
- agent 需要自己决定调用哪些字段。
- agent 不一定知道哪些操作是只读、哪些可能有副作用。
- agent 工具发现能力弱。
- 返回数据是系统原始结构，不一定是 agent-friendly。

### 1.2 Idea

我们在 MiSArch GraphQL 之上加一个 MCP gateway：

```text
MiSArch GraphQL API
  -> Go MCP Gateway
  -> MCP tools: list_products, get_product
  -> External Agent
```

这个 gateway 不替代 MiSArch，而是作为 agent-facing adapter。

### 1.3 Contribution

这个项目做了三件事：

- 把 MiSArch Docker Compose 栈真实部署到 Google Cloud。
- 把本地 Go MCP gateway 也部署到同一台 GCP VM，并通过 Docker 内网连接 MiSArch GraphQL。
- 设计并执行 agent smoke test，对比原生 GraphQL API 和 MCP gateway 的差异。

### 1.4 Evaluation Claim

实验不声称 MCP 比 GraphQL “数据更好”。底层数据应该一致。实验要证明的是：

```text
MCP 对 agent 更友好，因为它提供 tool discovery、typed input schema、read-only side-effect metadata、standardized output。
```

## 2. 推荐 Slide 结构

建议控制在 10 到 12 页。如果时间是 10 分钟，按下面节奏讲；如果时间更长，可以展开 Q&A bank。

### Slide 1: Title

标题建议：

```text
Agentic Interoperability for MiSArch via MCP Gateway
```

你要说：

- 我们把 MiSArch 部署到 Google Cloud。
- 在它前面加了一个 Go MCP gateway。
- 然后测试外部 agent 是否能通过 MCP 安全读取 MiSArch catalog 数据。

### Slide 2: Motivation

图：

```text
Agent wants to use real systems
But real systems expose developer-oriented APIs
```

你要说：

- Agent 需要和真实后端系统互操作。
- 原生 API 对人类开发者友好，不一定对 agent 友好。
- 所以需要一个 agent-facing interface。

### Slide 3: Why MiSArch

你要说：

- MiSArch 是真实微服务架构，有 frontend、gateway、catalog、keycloak、数据库等服务。
- 它比玩具 demo 更接近真实系统。
- 因此适合测试 agentic interoperability。

### Slide 4: Deployment Architecture

建议画这个图：

```text
Local machine / Codex
  -> http://34.40.117.201:8001/mcp
  -> GCP VM: misarch-agent-gateway container
  -> Docker network: infrastructure-docker_default
  -> http://gateway:8080/graphql
  -> MiSArch GraphQL Gateway
  -> Catalog Service
```

你要说：

- MiSArch 和 MCP gateway 都在同一台 GCP VM。
- MCP gateway 通过 Docker 内网访问 GraphQL，而不是绕公网。
- 这样网络更直接，也更接近生产中服务间通信。

### Slide 5: MiSArch Deployment

你要说：

- MiSArch 是 Docker Compose 项目。
- 初始 clone 后需要 `git submodule update --init --recursive`。
- 使用 Compute Engine VM 运行 Compose，是因为上游项目已经是 Compose 结构。
- VM 上路径是 `/opt/misarch/infrastructure-docker`。

关键命令可以展示：

```bash
docker compose -f docker-compose.yaml -f docker-compose.gcp.yaml up -d
```

### Slide 6: MCP Gateway Design

你要说：

- Gateway 是 Go 写的。
- 它暴露 `/healthz`、`/readyz`、`/mcp`。
- `/readyz` 会真实调用 MiSArch GraphQL `{ __typename }`。
- MCP tools 当前只有两个，只读：

```text
list_products
get_product
```

### Slide 7: Code Architecture

推荐展示文件结构：

```text
cmd/server/main.go
internal/config/config.go
internal/httpserver/server.go
internal/misarch/client.go
internal/catalog/service.go
internal/mcpserver/server.go
scripts/agent_gcp_smoke_test.py
```

你要说：

- `misarch/client.go` 只负责 GraphQL HTTP 请求。
- `catalog/service.go` 负责业务映射。
- `mcpserver/server.go` 负责把能力注册成 MCP tools。
- 这样每层职责清楚，方便测试。

### Slide 8: MCP Protocol Flow

你要说：

MCP Streamable HTTP 不是普通 REST。测试时必须：

```text
initialize
  -> read Mcp-Session-Id
  -> notifications/initialized
  -> tools/list
  -> tools/call
```

如果直接 `tools/list`，会被协议拒绝。

### Slide 9: Agent Testing Design

你要说测试分 5 层：

```text
Unit tests
Readiness test
MCP protocol test
Tool semantics test
LLM grounded report test
```

展示 smoke test 输出：

```text
tools=get_product, list_products
first_product=POP 2025
found=True
runtime=misarch-graphql-gateway
source_service=catalog
side_effects=none (read-only)
```

### Slide 10: Baseline Comparison

你要说：

Baseline A 是原生 MiSArch GraphQL：

```text
Agent -> http://34.40.117.201:8080/graphql
```

Baseline B 是 MCP Gateway：

```text
Agent -> http://34.40.117.201:8001/mcp
```

核心比较不是“数据谁更多”，而是“哪个接口更适合 agent 使用”。

### Slide 11: Results and Interpretation

你要说：

- 两条路径都能读取 MiSArch catalog 的真实商品。
- GraphQL 返回底层原始数据。
- MCP 返回标准化 agent-friendly 数据，并附带 runtime、source_service、side_effects。
- MCP 更适合让 agent 安全、可发现地使用有限能力。

### Slide 12: Limitations and Future Work

你要诚实说：

- 当前只暴露了 catalog 的两个只读工具。
- MCP endpoint 当前没有认证。
- 现在是单 VM 部署，不是高可用生产部署。
- baseline 还可以增加 latency、token usage、failure recovery 等指标。

未来：

- 加 auth / rate limiting / logging。
- 扩展更多只读工具。
- 添加负向测试。
- 用 Cloud Build / Artifact Registry / Terraform 管理部署。

## 3. Demo 流程

如果 presentation 允许现场 demo，推荐只 demo 两个命令，避免现场翻车。

### 3.1 检查云端 MCP ready

```bash
curl -sS http://34.40.117.201:8001/readyz
```

期望：

```json
{"status":"ready"}
```

解释：

```text
这不只是进程活着，还说明 gateway 能访问 MiSArch GraphQL。
```

### 3.2 跑 agent smoke test

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
./scripts/agent_gcp_smoke_test.py
```

解释输出：

```text
[1/5] MCP initialize
[2/5] MCP tools/list
[3/5] MCP tools/call list_products
[4/5] MCP tools/call get_product
[5/5] LLM agent report
```

如果现场不能联网，就展示提前截图或复制输出。

## 4. Baseline 实验设计

### 4.1 Baseline A: 原生 MiSArch GraphQL

测试目标：

```text
agent 或测试脚本直接访问 MiSArch GraphQL API，读取 catalog product 数据。
```

GraphQL endpoint：

```text
http://34.40.117.201:8080/graphql
```

示例 query：

```graphql
query ListProducts($first: Int!) {
  products(first: $first) {
    nodes {
      id
      defaultVariant {
        id
        currentVersion {
          name
          description
          retailPrice
        }
      }
      categories(first: 10) {
        nodes {
          name
        }
      }
    }
  }
}
```

这个 baseline 的特点：

- 优点：底层能力强、字段灵活、表达力高。
- 缺点：agent 需要知道 GraphQL schema 和 query 写法。
- 缺点：没有显式 tool discovery。
- 缺点：没有直接告诉 agent 这个操作是否只读。

### 4.2 Baseline B: MCP Gateway

测试目标：

```text
agent 通过 MCP 协议发现 tools，再调用 list_products / get_product。
```

MCP endpoint：

```text
http://34.40.117.201:8001/mcp
```

调用顺序：

```text
initialize
notifications/initialized
tools/list
tools/call list_products
tools/call get_product
```

这个 baseline 的特点：

- 优点：agent 可以通过 `tools/list` 发现能力。
- 优点：输入 schema 简单。
- 优点：返回结构标准化。
- 优点：明确 `side_effects=none (read-only)`。
- 缺点：灵活性比 GraphQL 低，只能调用 gateway 暴露的能力。
- 缺点：多了一层 adapter，可能增加少量延迟。

### 4.3 公平比较方法

为了比较公平，两条路径应该做同一个任务：

```text
列出 MiSArch catalog 商品，读取第一个商品详情，并说明数据来源和副作用。
```

比较指标：

| 指标 | GraphQL baseline | MCP baseline |
| --- | --- | --- |
| 是否能读到真实商品 | 应该能 | 应该能 |
| 是否能发现可用能力 | 弱，需要 schema/query | 强，tools/list |
| 输入复杂度 | 高，需要 GraphQL query | 低，只传 JSON 参数 |
| 输出是否 agent-friendly | 原始嵌套结构 | 标准化结构 |
| 是否说明副作用 | 不显式 | 显式 `none (read-only)` |
| 是否说明数据来源 | 需要推断 | 显式 `runtime/source_service` |
| 灵活性 | 高 | 中低 |
| 安全边界 | 宽，需要额外限制 | 窄，只暴露允许工具 |

### 4.4 你可以得出的结论

不要说：

```text
MCP 返回的数据比 GraphQL 更真实。
```

应该说：

```text
MCP 和 GraphQL 读取的是同一套 MiSArch 后端数据。区别在于 MCP 将底层 API 能力封装成 agent 可发现、可约束、可解释的工具接口。
```

## 5. 可能被问到的问题：两层深入追问题库

下面每个点都准备了主问题、第一层追问、第二层更深追问，以及建议回答。

### Point 1: 为什么要做 MCP gateway

主问题：

```text
为什么不让 agent 直接调用 MiSArch GraphQL？
```

回答：

```text
GraphQL 很适合开发者，但 agent 直接使用时需要知道 schema、query 结构和安全边界。MCP gateway 的作用是把底层 API 包装成 agent 可发现、输入明确、只读副作用明确的工具。
```

第一层追问：

```text
GraphQL 不是也有 schema introspection 吗？agent 不能自己读 schema 吗？
```

回答：

```text
可以，但这会把 schema 理解、query 构造和安全判断都交给 agent。对于真实系统，这样风险更高。MCP gateway 通过暴露少量经过设计的 tools，把 agent 的操作空间限制在安全范围内。
```

第二层追问：

```text
那 MCP 是不是牺牲了 GraphQL 的灵活性？
```

回答：

```text
是的，MCP gateway 有意牺牲一部分灵活性，换来更清楚的能力边界、工具发现和安全性。对于 agentic interoperability，目标不是让 agent 任意查询系统，而是让 agent 使用被授权、可解释的能力。
```

### Point 2: 为什么只暴露两个工具

主问题：

```text
为什么当前只实现 list_products 和 get_product？
```

回答：

```text
这是 v1 最小可验证范围。catalog read-only 能力足以证明 agent 可以发现工具、读取真实 MiSArch 数据、基于结果回答，并且不会产生副作用。
```

第一层追问：

```text
为什么不实现 checkout、cart、payment？
```

回答：

```text
这些是写操作或业务副作用操作，需要认证、授权、审计、幂等和回滚设计。在没有这些安全机制之前，先暴露只读 catalog 能力更合理。
```

第二层追问：

```text
如果以后要支持写操作，你会怎么设计？
```

回答：

```text
我会先加身份认证和授权，再为每个写工具定义明确的 destructiveHint、idempotentHint、confirmation flow 和 audit logging。高风险操作还应要求人类确认，而不是让 agent 直接执行。
```

### Point 3: 为什么部署到 GCP Compute Engine

主问题：

```text
为什么不用 Cloud Run / Kubernetes，而是 Compute Engine VM？
```

回答：

```text
MiSArch 上游项目已经是 Docker Compose 多服务结构，并且包含很多服务和数据库。Compute Engine + Docker Compose 是最小迁移成本方案，可以保留原项目结构，快速完成真实联调。
```

第一层追问：

```text
这是不是不够 cloud-native？
```

回答：

```text
是的，它不是最 cloud-native 的最终方案。但对课程实验来说，目标是证明 agentic interoperability，而不是重构 MiSArch 的部署架构。VM + Compose 是合理的实验部署方式。
```

第二层追问：

```text
如果要生产化，你会怎么改？
```

回答：

```text
我会考虑 GKE 或 Kubernetes，将服务拆成 Deployment/Service，使用 Secret Manager 管理密钥，用 Cloud Build 和 Artifact Registry 构建镜像，并用 Terraform 管理基础设施。
```

### Point 4: 你的代码到底部署在哪里

主问题：

```text
你的 MCP gateway 现在运行在哪里？
```

回答：

```text
它运行在 GCP VM misarch-compose 上的 Docker 容器 misarch-agent-gateway 中，公网 endpoint 是 http://34.40.117.201:8001/mcp。源码同步在 /opt/misarch/misarch-agent-gateway-go。
```

第一层追问：

```text
它和 MiSArch 是同一个容器吗？
```

回答：

```text
不是。MiSArch 是一组 Compose 容器，MCP gateway 是另一个单独容器。它们在同一个 Docker network 里通信。
```

第二层追问：

```text
为什么不把 MCP gateway 直接写进 MiSArch gateway 服务？
```

回答：

```text
单独做 adapter 可以减少对上游 MiSArch 的侵入，方便独立开发、测试和删除。它也更清楚地表达了这是 agent-facing layer，而不是 MiSArch 核心业务服务。
```

### Point 5: 你的代码如何和 MiSArch 通信

主问题：

```text
MCP gateway 如何调用 MiSArch？
```

回答：

```text
Go gateway 通过 HTTP POST 调用 MiSArch GraphQL endpoint。在 GCP 容器里，MISARCH_GRAPHQL_URL 设置为 http://gateway:8080/graphql，其中 gateway 是 Docker network 中 MiSArch GraphQL 容器的别名。
```

第一层追问：

```text
为什么不用公网 GraphQL 地址？
```

回答：

```text
因为 MCP gateway 和 MiSArch GraphQL 在同一台 VM 的同一个 Docker network 中，使用内网容器名通信更直接，也避免服务间通信绕公网。
```

第二层追问：

```text
如果 gateway 容器名变化怎么办？
```

回答：

```text
这依赖 Docker Compose service name 和 network alias。如果未来部署方式变化，应该通过环境变量 MISARCH_GRAPHQL_URL 配置，而不是写死在代码里。当前代码已经通过环境变量注入。
```

### Point 6: `/healthz` 和 `/readyz` 的区别

主问题：

```text
为什么需要 healthz 和 readyz 两个 endpoint？
```

回答：

```text
healthz 表示进程活着；readyz 表示 gateway 已经能访问上游 MiSArch GraphQL。两者含义不同。
```

第一层追问：

```text
readyz 怎么验证上游可用？
```

回答：

```text
readyz 会调用 GraphQL query `{ __typename }`。如果 GraphQL endpoint 返回成功，则 ready。
```

第二层追问：

```text
为什么不用 list_products 作为 ready check？
```

回答：

```text
list_products 更重，也依赖 catalog 数据状态。`{ __typename }` 是轻量 GraphQL 可用性检查，更适合 readiness。
```

### Point 7: MCP 协议为什么要 initialize

主问题：

```text
为什么不能直接调用 tools/list？
```

回答：

```text
MCP Streamable HTTP 需要先 initialize 建立 session。服务端会返回 Mcp-Session-Id，后续 tools/list 和 tools/call 都要带这个 session id。
```

第一层追问：

```text
如果不 initialize 会怎样？
```

回答：

```text
会收到协议错误，例如 method "tools/list" is invalid during session initialization。
```

第二层追问：

```text
session id 有什么意义？
```

回答：

```text
它让服务端区分不同客户端会话，并确保客户端完成了能力协商。未来如果有上下文、权限或 session 状态，也可以通过 session 管理。
```

### Point 8: Agent 测试为什么要调用模型

主问题：

```text
为什么 smoke test 最后还要调用 LLM？只测试 MCP 不够吗？
```

回答：

```text
只测试 MCP 只能说明工具接口可用。调用 LLM 是为了验证 agent 能否基于工具结果生成 grounded answer，并正确说明数据来源和副作用。
```

第一层追问：

```text
这是不是只是让模型总结 JSON？
```

回答：

```text
是的，这是 smoke test 的设计。它不是复杂推理评测，而是验证工具发现、工具调用、证据输入和最终回答这条 agent pipeline 能跑通。
```

第二层追问：

```text
如何让这个测试更严格？
```

回答：

```text
可以加入多轮任务、负向测试、禁止编造检查、自动评分、latency/token 统计，以及让 agent 自己决定先 list 再 get，而不是脚本固定流程。
```

### Point 9: Baseline 是否公平

主问题：

```text
直接 GraphQL 和 MCP gateway 怎么公平比较？
```

回答：

```text
应该让它们完成同一个任务：列出商品并读取第一个商品详情。比较时不只看返回商品是否一致，还看工具发现、输入复杂度、副作用说明、输出标准化和 agent 可用性。
```

第一层追问：

```text
MCP 返回的数据是不是被你加工过，所以比较不公平？
```

回答：

```text
MCP 的目标就是做 adapter，所以它会标准化输出。底层商品数据应该和 GraphQL 一致；额外的 runtime/source_service/side_effects 是 MCP gateway 为 agent 增加的元信息。
```

第二层追问：

```text
如果 GraphQL 也加 prompt 描述 schema，agent 不也能用吗？
```

回答：

```text
可以，这是另一个 baseline。但那会增加 prompt complexity 和风险。MCP 的优势是把能力描述和 schema 放在协议级工具发现中，而不是完全依赖 prompt。
```

### Point 10: 数据一致性

主问题：

```text
如何证明 MCP 读取的是 MiSArch 真实数据，不是 mock？
```

回答：

```text
MCP gateway 的 MISARCH_GRAPHQL_URL 指向 http://gateway:8080/graphql，这是 VM Docker network 内的 MiSArch GraphQL。测试中返回 runtime=misarch-graphql-gateway，source_service=catalog，并读取到真实商品 POP 2025。
```

第一层追问：

```text
代码里有没有 fallback/mock 数据？
```

回答：

```text
Go MCP gateway 没有 mock fallback。它通过 GraphQL client 实时调用 MiSArch。如果 GraphQL 不可用，readyz 和工具调用会失败。
```

第二层追问：

```text
如何进一步证明？
```

回答：

```text
可以同时执行原生 GraphQL query 和 MCP list_products，对比 product id、variant id、name、price、category 是否一致。
```

### Point 11: 安全性

主问题：

```text
当前部署安全吗？
```

回答：

```text
这是课程实验部署，不是生产安全部署。Firewall 只允许我的当前公网 IP 访问相关端口，但 MCP endpoint 本身目前没有认证。
```

第一层追问：

```text
最大风险是什么？
```

回答：

```text
如果 8001 暴露给公网，任何人都可以调用只读 catalog 工具。当前工具只读，所以业务风险较低，但仍然不应该无认证长期公开。
```

第二层追问：

```text
生产化需要加什么？
```

回答：

```text
需要认证、授权、rate limiting、audit logging、secret management、TLS，以及对写操作增加 human confirmation。
```

### Point 12: 为什么工具是 read-only

主问题：

```text
为什么强调 side_effects=none？
```

回答：

```text
Agent 调用外部系统时，副作用很重要。只读工具更容易验证，也降低风险。返回 side_effects 可以让 agent 和 evaluator 明确知道这个工具不会改变系统状态。
```

第一层追问：

```text
这个 side_effects 是协议自带的吗？
```

回答：

```text
当前实现里 side_effects 是结构化输出字段，同时 tool description 也说明 read-only。更完整的 MCP 实现还可以使用 tool annotations 来表达 readOnlyHint 等语义。
```

第二层追问：

```text
如果工具实际不是只读但标成只读怎么办？
```

回答：

```text
那就是接口契约错误。需要通过代码审查、测试和审计保证 tool metadata 与真实行为一致。对于写工具尤其重要。
```

### Point 13: 为什么用 Go 写 MCP gateway

主问题：

```text
为什么 MCP gateway 用 Go？
```

回答：

```text
Go 适合写轻量 HTTP service，静态编译、容器镜像小、部署简单。MiSArch 侧通过 GraphQL HTTP 通信，所以语言选择不影响集成。
```

第一层追问：

```text
Python 不是更适合 agent 吗？
```

回答：

```text
Python 很适合快速原型，但 Go gateway 更像一个稳定 adapter service。我们也有 Python agent-mvp，但它连接的是 OpenTelemetry demo，不是当前 MiSArch 链路。
```

第二层追问：

```text
如果未来要快速扩展工具，Go 会不会慢？
```

回答：

```text
扩展工具主要是添加 GraphQL query、service mapping 和 MCP tool registration。Go 类型系统反而能帮助保持 schema 和输出结构清晰。
```

### Point 14: 为什么不使用 Codex MCP 注册来测试

主问题：

```text
为什么测试脚本不依赖 codex mcp add？
```

回答：

```text
为了让测试更独立、更可复现。脚本直接调用 MCP endpoint 和模型 API，不依赖 Codex CLI 是否加载了某个 MCP server 配置。
```

第一层追问：

```text
那 ~/.codex/config.toml 有什么用？
```

回答：

```text
它主要给 Codex CLI / Codex App 使用，告诉 Codex 使用哪个 model provider、base_url 和模型。独立测试脚本可以直接写这些参数，不一定读取 config.toml。
```

第二层追问：

```text
脚本为什么还读 ~/.codex/auth.json？
```

回答：

```text
因为模型 API 需要 API key。脚本读 auth.json 是为了避免把 key 写进代码。更好的方式也可以是读取环境变量 OPENAI_API_KEY。
```

### Point 15: 测试结果如何解释

主问题：

```text
你的测试结果证明了什么？
```

回答：

```text
证明了云端 MCP gateway 能通过 MCP 协议被初始化、能暴露工具、能调用 MiSArch GraphQL 读取真实 catalog 商品，并能把结果交给模型生成 grounded report。
```

第一层追问：

```text
它没有证明什么？
```

回答：

```text
它没有证明系统生产可用，也没有证明所有 MiSArch 服务都可通过 MCP 使用，更没有证明写操作安全。当前只是 catalog read-only path 的 end-to-end smoke test。
```

第二层追问：

```text
下一步如何让实验更强？
```

回答：

```text
可以加入更多工具、原生 GraphQL baseline 自动对比、latency/token 统计、负向测试、认证和日志，并让多个模型或 agent 框架重复执行同一任务。
```

### Point 16: 价格字段如何解释

主问题：

```text
retail_price_cents=20 是什么意思？
```

回答：

```text
当前 gateway 把 MiSArch 返回的 retailPrice 映射为 retail_price_cents，并标注 currency=EUR。展示时要说这是按代码当前解释的 price cents 字段，不要口头说成 20 欧元。
```

第一层追问：

```text
你确定 MiSArch 的 retailPrice 单位是 cents 吗？
```

回答：

```text
当前实现中按 cents 命名和处理。更严谨的做法是查 MiSArch schema 或数据模型文档，确认 retailPrice 的单位，然后调整字段名或转换逻辑。
```

第二层追问：

```text
如果单位理解错，会影响什么？
```

回答：

```text
会影响 agent 输出的价格解释，但不影响 MCP 协议联通性。实验报告中应把价格单位作为数据 mapping limitation 说明。
```

## 6. 你可以背的 30 秒版本

```text
我的项目目标是验证外部 agent 如何安全地访问真实微服务系统 MiSArch。MiSArch 原生提供 GraphQL API，但 agent 直接使用 GraphQL 需要理解 schema、构造 query，并且不容易知道副作用边界。所以我在 MiSArch GraphQL 前面实现了一个 Go MCP gateway，把 catalog 的只读能力封装成 list_products 和 get_product 两个 MCP tools。

部署上，我把 MiSArch Docker Compose 栈部署到 Google Cloud Compute Engine VM，然后把 MCP gateway 也部署成同一台 VM 上的 Docker 容器，并加入 MiSArch 的 Docker network，通过 http://gateway:8080/graphql 内网访问 GraphQL。

测试上，我做了 unit test、readyz 测试、MCP protocol 测试和 agent smoke test。agent 通过 MCP initialize、tools/list、tools/call 读取真实商品 POP 2025，并返回 runtime=misarch-graphql-gateway、source_service=catalog、side_effects=none read-only。baseline 是直接访问原生 GraphQL，与 MCP gateway 比较工具发现、输入复杂度、输出标准化和安全边界。
```

## 7. 你可以背的 2 分钟版本

```text
这个项目围绕 agentic interoperability：也就是外部 agent 如何使用真实后端系统。我们选择 MiSArch，因为它是一个微服务电商架构，有 GraphQL gateway、catalog service、frontend、Keycloak 等，复杂度比玩具 demo 更接近真实系统。

第一步是部署 MiSArch。因为上游项目已经是 Docker Compose 结构，我选择 GCP Compute Engine VM，而不是马上迁移到 Kubernetes。VM 名是 misarch-compose，MiSArch 源码在 /opt/misarch/infrastructure-docker，使用 docker compose 启动。公网 GraphQL endpoint 是 http://34.40.117.201:8080/graphql。

第二步是部署我写的 Go MCP gateway。它运行在同一台 VM 的 Docker 容器 misarch-agent-gateway 中，公网 MCP endpoint 是 http://34.40.117.201:8001/mcp。它加入 MiSArch 的 Docker network，通过 http://gateway:8080/graphql 访问 GraphQL gateway，所以服务间通信走 Docker 内网。

代码上，cmd/server/main.go 负责组装服务；internal/misarch/client.go 负责 GraphQL POST；internal/catalog/service.go 负责把 GraphQL product 数据映射成 agent-friendly 输出；internal/mcpserver/server.go 注册 MCP tools。当前暴露 list_products 和 get_product，都是 read-only。

测试上，我先跑 go test ./...，然后用 /readyz 验证 gateway 到 GraphQL 的连通性。端到端 agent smoke test 不依赖 Codex MCP 注册，而是直接调用 MCP endpoint：initialize、tools/list、tools/call list_products、tools/call get_product，最后把工具结果给模型生成 grounded report。测试证明 agent 能发现 get_product 和 list_products，读取真实商品 POP 2025，并得到 runtime、source_service 和 side_effects。

baseline 比较分两条路径：一条是 agent 直接访问原生 GraphQL，一条是 agent 访问 MCP gateway。两者底层数据应该一致；差异在于 MCP 提供工具发现、typed input schema、标准化输出和只读副作用说明，更适合 agent 使用。
```

## 8. Presentation 时不要踩的坑

- 不要说 MCP 替代了 GraphQL；应该说 MCP 是 GraphQL 之上的 agent-facing adapter。
- 不要说 MCP 数据比 GraphQL 更真实；底层真实数据来自同一个 MiSArch。
- 不要说当前系统生产安全；当前只是实验部署，MCP endpoint 没有认证。
- 不要把 API key 展示在 slide、terminal、截图里。
- 不要把 `retail_price_cents=20` 口头说成 20 欧元，除非确认单位。
- 不要说所有 MiSArch 功能都被 agent 可用；当前只暴露 catalog read-only 能力。
- 不要现场临时重启整个 MiSArch Compose 栈；demo 只跑 `/readyz` 和 smoke test。

## 9. 如果时间不够，优先讲什么

优先级：

```text
1. Problem: GraphQL is developer-facing, not ideal agent-facing.
2. Solution: Go MCP gateway exposes read-only tools.
3. Deployment: both MiSArch and MCP run on GCP VM, same Docker network.
4. Testing: MCP initialize -> tools/list -> tools/call -> LLM grounded report.
5. Baseline: raw GraphQL vs MCP in discoverability, schema, side effects, output.
```

可以跳过：

```text
具体 startup script 细节
所有 firewall 命令
所有 Go unit test 文件名
所有 Docker healthcheck override 细节
```

## 10. 最后一页总结

建议最后一页只放三句话：

```text
1. MiSArch was deployed as a real cloud microservice backend on GCP.
2. A Go MCP gateway exposes selected MiSArch Catalog capabilities as read-only agent tools.
3. Compared with raw GraphQL, MCP improves agent discoverability, safety metadata, and output structure while preserving access to real backend data.
```

中文版本：

```text
1. MiSArch 已作为真实微服务后端部署到 GCP。
2. Go MCP gateway 将 MiSArch Catalog 的只读能力暴露为 agent 可调用工具。
3. 相比原生 GraphQL，MCP 提升了工具发现、安全边界说明和输出结构化程度，同时仍然访问真实后端数据。
```
