# 8-Minute Pre Talk Track: Agentic Interoperability for MiSArch via MCP

对应 PPT：

`/Users/wang/Desktop/TUB2025sose/outputs/misarch-mcp-ppt-20260603/Agentic_Interoperability_MiSArch_MCP_Implementation_Presentation.pptx`

使用方式：

```text
如果正式 presentation 用英文，就背 English script；中文是帮助你理解逻辑。
如果允许中文 presentation，就用中文稿；英文稿可以作为答辩时的关键词。
不要中英都念一遍，否则 8 分钟不够。
```

## 0. 总体思路

核心主线：

```text
MiSArch 原本通过 GraphQL 暴露电商微服务能力。
GraphQL 对开发者很好，但外部 agent 使用时要自己猜 query、判断副作用、理解业务风险。
我的重构是在 GraphQL 前面增加一个 Go MCP gateway，把 selected capabilities 变成 agent-facing tools。
实验结论是：MCP 保持和 GraphQL 一样的核心商品数据，同时提供 tool discovery、typed schema 和 side-effect metadata；代价是额外 latency。
```

English core message:

```text
MiSArch already exposes its e-commerce capabilities through GraphQL.
GraphQL is powerful for developers, but an external agent still has to infer query structure, business risk, and side effects.
My refactoring adds a Go-based MCP gateway in front of GraphQL and exposes selected capabilities as agent-facing tools.
The evaluation shows that MCP preserves the same core product data as GraphQL, while adding tool discovery, typed schemas, and side-effect metadata, with additional latency as the trade-off.
```

8 分钟时间分配：

| Slide | Topic | Time |
|---:|---|---:|
| 1 | Opening and goal | 0:35 |
| 2 | Quality goal definition | 0:50 |
| 3 | MiSArch context | 0:45 |
| 4 | MCP facade refactoring | 0:50 |
| 5 | Implementation state | 0:50 |
| 6 | Assumptions | 0:45 |
| 7 | Architecture principles | 0:40 |
| 8 | Baseline design | 1:00 |
| 9 | Baseline results | 1:10 |
| 10 | Cloud-native trade-offs | 0:45 |
| 11 | Outlook and closing | 0:35 |

一句话结论：

中文：

```text
MCP 不是替代 GraphQL，而是在 GraphQL 前面加一个更适合 agent 使用的、有边界、有 schema、有副作用说明的 facade。
```

English:

```text
MCP does not replace GraphQL; it adds an agent-facing facade with boundaries, schemas, and side-effect information.
```

## Slide 1: Quality Goal

要讲的重点：

```text
定义项目主题：不是重写 MiSArch，而是提升 agent-facing interoperability。
```

中文讲稿：

```text
大家好，我的项目主题是通过 MCP 提升 MiSArch 的 agent-facing interoperability。MiSArch 本身是一个电商微服务系统，当前主要通过 GraphQL gateway 暴露能力。我的目标不是替换 GraphQL，也不是重写 MiSArch，而是在现有系统前面增加一个适合外部 AI agent 使用的接口层。

这次 presentation 我会讲四部分：质量目标、MCP 重构、baseline 评估结果，以及 cloud-native 方向的后续工作。
```

English script:

```text
Hello everyone. My project is about improving agent-facing interoperability for MiSArch through MCP. MiSArch is an e-commerce microservice system, and its existing integration point is the GraphQL gateway. My goal is not to replace GraphQL or rewrite MiSArch, but to add an interface layer that is easier and safer for external AI agents to use.

I will cover four parts: the quality goal, the MCP refactoring, the baseline evaluation results, and the cloud-native outlook.
```

转场：

```text
First, I define what agent-facing interoperability means in this project.
```

## Slide 2: Quality Goal

要讲的重点：

```text
Agent-facing interoperability = discoverability + typed I/O + side effects + operations。
```

中文讲稿：

```text
这里我把 agent-facing interoperability 拆成四个方面。

第一是 discoverability。agent 应该能列出可用能力，而不是猜 endpoint 或 GraphQL operation。

第二是 typed I/O。工具输入输出应该是结构化的，方便校验。

第三是 side effects。agent 要知道一个调用是 read-only，还是会改变购物车或订单状态。

第四是 operations。adapter 需要 health 和 readiness endpoint，才能在部署后测试。

所以这个质量目标可以总结为：提高 agent 可用性，同时避免把整个 GraphQL supergraph 不受控制地暴露出去。
```

English script:

```text
I define agent-facing interoperability through four properties.

The first one is discoverability. The agent should be able to list available capabilities instead of guessing endpoints or GraphQL operations.

The second one is typed I/O. Tool inputs and outputs should be structured and easier to validate.

The third one is side effects. The agent should know whether a call is read-only or whether it changes shopping cart or order state.

The fourth one is operations. The adapter needs health and readiness endpoints so that it can be tested after deployment.

So the quality goal is to make MiSArch more usable by agents without exposing the whole GraphQL supergraph as an uncontrolled tool surface.
```

转场：

```text
Next, I show why this matters in the current MiSArch architecture.
```

## Slide 3: System Context

要讲的重点：

```text
MiSArch 当前是 Frontend -> GraphQL Gateway -> Domain Services -> Infrastructure。
GraphQL 是 developer-oriented API，但 agent 使用时仍要推断 query 和业务风险。
```

中文讲稿：

```text
这页是系统上下文。MiSArch 是一个电商微服务架构。客户端通过 frontend 进入，然后访问 GraphQL gateway。GraphQL gateway 再调用 catalog、shopping cart、order 和 user 等 domain services，底层还有认证、数据库和运行时基础设施。

GraphQL 对开发者非常灵活，因为开发者知道 schema，也知道业务语义。但 external agent 不一定知道应该写什么 query，也不一定知道哪些 mutation 是安全的。所以当前问题是：GraphQL 很强大，但它不是天然 agent-facing 的接口。
```

English script:

```text
This slide shows the system context. MiSArch is an e-commerce microservice architecture. The client enters through the frontend and then calls the GraphQL gateway. The GraphQL gateway coordinates domain services such as catalog, shopping cart, order, and user services, with authentication, databases, and runtime infrastructure underneath.

GraphQL is very flexible for developers because developers know the schema and the business semantics. But an external agent may not know which query to write or which mutations are safe. So the current issue is that GraphQL is powerful, but it is not naturally agent-facing.
```

转场：

```text
My refactoring adds a facade for this agent-facing access.
```

## Slide 4: Refactoring Goal

要讲的重点：

```text
Before: agent 直接访问 GraphQL。
After: agent 访问 MCP gateway，MCP gateway 再访问 GraphQL。
GraphQL 仍然是 system of record。
```

中文讲稿：

```text
这页是核心架构变化。

Before 的路径是 external agent 直接访问 MiSArch GraphQL。这样 agent 必须自己知道 GraphQL query，并且面对一个比较宽的 API surface。

After 的路径是 external agent 调用 /mcp。中间的 Go MCP gateway 暴露 selected tools、input schemas 和 side-effect metadata。真正的数据仍然来自 MiSArch GraphQL，所以 GraphQL 还是 system of record。

这个 refactoring 的边界很清楚：我没有改变 domain services，而是在现有 GraphQL 前面增加一个更窄、更明确的 agent-facing facade。
```

English script:

```text
This slide shows the main architectural change.

Before the refactoring, the external agent calls MiSArch GraphQL directly. This means the agent has to know how to write GraphQL and faces a broad API surface.

After the refactoring, the external agent calls /mcp. The Go MCP gateway exposes selected tools, input schemas, and side-effect metadata. The actual data still comes from MiSArch GraphQL, so GraphQL remains the system of record.

The refactoring boundary is clear: I did not change the domain services. I added a narrower and more explicit agent-facing facade in front of the existing GraphQL gateway.
```

转场：

```text
Now I briefly show the current implementation state.
```

## Slide 5: Implementation State

要讲的重点：

```text
已经实现 working prototype：Go MCP server、/mcp、/healthz、/readyz、catalog tools、order draft tool、GraphQL client。
```

中文讲稿：

```text
当前实现是一个 Go-based MCP prototype。

cmd/server/main.go 负责配置和启动。internal/httpserver 提供 /mcp、/healthz 和 /readyz。internal/mcpserver 负责 tool registration 和 schemas。internal/catalog 实现 list_products 和 get_product。internal/order 实现 create_pending_order。internal/misarch 负责 GraphQL client 和 token source。

现在暴露的工具有三个：list_products、get_product 和 create_pending_order。前两个是 read-only；create_pending_order 是受控的状态改变，只创建 pending order，不处理支付。

这个版本已经部署在 GCP VM 上用于课程评估，但我不会把它说成 production-ready。
```

English script:

```text
The current implementation is a Go-based MCP prototype.

cmd/server/main.go handles configuration and startup. internal/httpserver exposes /mcp, /healthz, and /readyz. internal/mcpserver handles tool registration and schemas. internal/catalog implements list_products and get_product. internal/order implements create_pending_order. internal/misarch contains the GraphQL client and token source.

The exposed tools are list_products, get_product, and create_pending_order. The first two are read-only. create_pending_order is a controlled state change: it creates a pending order, but it does not handle payment.

This version is deployed on a GCP VM for course evaluation, but I do not claim it is production-ready.
```

转场：

```text
The small tool surface is intentional, because it follows the use-case assumptions.
```

## Slide 6: Assumptions

要讲的重点：

```text
只允许 catalog exploration 和 controlled order draft。
最小权限比暴露全部能力更重要。
```

中文讲稿：

```text
这一页解释架构取舍。

我的 use case 不是让 agent 控制整个电商系统，而是两个有限任务。第一个是 catalog exploration，也就是查找和查看公开商品，这是 read-only。第二个是 order draft，也就是在选择商品后创建 pending order，但不支付、不最终下单。

agent 只能通过 tool discovery 和 tool calls 访问系统，没有 admin 或 database access。这样符合 least privilege。

所以关键假设是：在这个 use case 里，安全和可解释性比暴露所有 MiSArch 能力或追求最低 latency 更重要。
```

English script:

```text
This slide explains the architectural trade-offs.

The use case is not to let the agent control the whole e-commerce system. It is limited to two tasks. The first one is catalog exploration: finding and inspecting public products, which is read-only. The second one is order draft: creating a pending order after product selection, but without payment or final order placement.

The agent can only use tool discovery and tool calls. It has no admin or database access, which follows least privilege.

So the key assumption is that, for this use case, safety and explainability are more important than exposing every MiSArch capability or minimizing latency.
```

转场：

```text
These assumptions connect to established architecture principles.
```

## Slide 7: Scientific Basis

要讲的重点：

```text
MCP 新，但架构思想不新：facade/API gateway、typed contracts、least privilege。
```

中文讲稿：

```text
MCP 本身是新协议，但我这里使用它的架构思想是成熟的。

Facade 或 API gateway 的思想是，用一个窄的、面向任务的外部 contract 隐藏内部 API 的复杂性。Typed contracts 让调用可以被机器校验，减少自由 query 的歧义。Least privilege 则要求只暴露 use case 需要的能力。

所以我的原则是：agent 应该拿到 explicit tools，包括名字、input schema、source metadata 和 side-effect information，而不是直接解释一个宽泛的 application API。
```

English script:

```text
MCP is a new protocol, but the architectural ideas behind my use of it are established.

The facade or API gateway idea is to hide internal API complexity behind a narrow, task-specific external contract. Typed contracts make calls machine-checkable and reduce ambiguity from free-form queries. Least privilege means exposing only the capabilities required by the use case.

So my principle is that the agent should receive explicit tools, including names, input schemas, source metadata, and side-effect information, instead of interpreting a broad application API directly.
```

转场：

```text
The next two slides are the evaluation: first the baseline design, then the results.
```

## Slide 8: Baseline Design

要讲的重点：

```text
三条路径都让 LLM 参与决策，但只有 Baseline B 要 LLM 写 GraphQL。
```

中文讲稿：

```text
这是评估设计里最关键的一页。我把 planning 和 API execution 分开比较。

三条路径都有 LLM decision step。

Baseline A 是 fixed GraphQL。LLM 读任务，但只选择 fixed_graphql_catalog_lookup。真正执行的是预写好的 LIST_PRODUCTS_QUERY 和 GET_PRODUCT_QUERY。这个 baseline 用来验证数据正确性。

Baseline B 是 agent-generated GraphQL。LLM 不仅理解任务，还要自己生成 GraphQL list 和 detail query。这个 baseline 用来测试 raw GraphQL 对 agent 是否友好。

MCP path 是 agent 先通过 tools/list 看到 list_products 和 get_product，再规划 tools/call。这里 LLM 不写 GraphQL，只做工具规划。

我还做了两种条件：schema experiment 给 LLM 一个简短 schema excerpt；minimal experiment 不给 GraphQL 字段文档，用来测试 agent 猜字段时的脆弱性。
```

English script:

```text
This is the key evaluation design slide. I separate planning from API execution.

All three paths include an LLM decision step.

Baseline A is fixed GraphQL. The LLM reads the task, but it only selects fixed_graphql_catalog_lookup. The executor runs prewritten LIST_PRODUCTS_QUERY and GET_PRODUCT_QUERY. This baseline is used to validate data correctness.

Baseline B is agent-generated GraphQL. The LLM has to understand the task and generate GraphQL list and detail queries itself. This baseline tests whether raw GraphQL is friendly for an agent.

The MCP path asks the agent to inspect tools/list first, then plan tools/call. Here the LLM does not write GraphQL. It only performs tool planning.

I also use two documentation conditions. In the schema experiment, the LLM receives a short GraphQL schema excerpt. In the minimal experiment, no GraphQL field documentation is provided, which tests the fragility of field guessing.
```

转场：

```text
Now we can interpret the results with this distinction in mind.
```

## Slide 9: Baseline Results

要讲的重点：

```text
Schema 条件下三条路径都成功，但 Baseline B 最慢，因为它要生成 query。
MCP 的结论不是最快，而是保留数据一致性并降低 agent 使用接口的难度。
```

中文讲稿：

```text
结果显示，在 schema experiment 里，Baseline A、Baseline B 和 MCP 都是 5/5 成功，并且返回相同的核心商品数据。

但是耗时不同。Baseline A 平均大约 5927 ms，因为它只选择固定 executor。MCP 平均大约 8198 ms，因为它需要 tools/list 和 tools/call 的规划。Baseline B 平均大约 21125 ms，是最慢的，因为 LLM 需要自己写 GraphQL query。

所以这里的结论不是 MCP 比 GraphQL 更快。直接 GraphQL 当然路径更短。我的结论是：MCP 让 LLM 停留在 tool-planning level，而不是 query-writing level。

minimal mode 的例子也说明了这个问题。如果没有 schema 字段文档，agent 可能猜出 productList 这样的字段，但真实 schema 里是 products。GraphQL 会返回错误，agent 还需要再修复。MCP 通过 tools/list 和 input schema 避免了这类猜字段问题。
```

English script:

```text
The result shows that, in the schema experiment, Baseline A, Baseline B, and MCP all succeed in five out of five trials, and they return the same core product data.

But the durations are different. Baseline A takes about 5927 milliseconds on average because it only selects a fixed executor. MCP takes about 8198 milliseconds because it includes tools/list and tools/call planning. Baseline B takes about 21125 milliseconds, which is the highest, because the LLM has to write GraphQL queries.

So the conclusion is not that MCP is faster than GraphQL. Direct GraphQL is expected to be shorter. My conclusion is that MCP keeps the LLM at the tool-planning level instead of the query-writing level.

The minimal mode example shows the same issue. Without schema field documentation, the agent may guess a field like productList, but the real schema uses products. GraphQL returns an error, and the agent has to repair the query. MCP avoids this field-guessing problem through tools/list and input schemas.
```

可背的关键句：

中文：

```text
Baseline B 证明 raw GraphQL 可以工作，但它依赖 schema 文档和 query generation；MCP 的价值是把 query-writing 问题转化成 tool-planning 问题。
```

English:

```text
Baseline B shows that raw GraphQL can work, but it depends on schema documentation and query generation. MCP turns the query-writing problem into a tool-planning problem.
```

转场：

```text
After this prototype-level result, the next question is how to make the system production-ready.
```

## Slide 10: Cloud-Native Trade-Offs

要讲的重点：

```text
当前是 GCP VM + Docker Compose prototype；生产方向是 GKE、ingress/API gateway、OIDC、network policy、CI/CD、observability。
```

中文讲稿：

```text
这一页我区分 prototype 和 production。

当前版本是 Docker Compose 部署在 GCP VM 上，MCP gateway 作为 container 运行，并通过 Docker 内部网络访问 MiSArch GraphQL。

生产方向可以是 Kubernetes 或 GKE，加 ingress 或 API gateway，使用 OIDC 做认证授权，用 network policy 控制服务间访问，并通过 CI/CD 部署。

observability 方面，我会加入 OpenTelemetry traces、Prometheus metrics、Grafana dashboards，以及每次 tool call 的 audit logs。

这里的 trade-off 是：小的 tool surface 更安全但功能少；schema 和 metadata 让 agent 使用更可预测，但会带来 adapter overhead；cloud-native hardening 提升安全和可观测性，但增加运维复杂度。
```

English script:

```text
This slide separates the prototype from the production direction.

The current version runs with Docker Compose on a GCP VM. The MCP gateway runs as a container and reaches MiSArch GraphQL through Docker-internal networking.

The production direction could use Kubernetes or GKE, with ingress or an API gateway, OIDC for authentication and authorization, network policies for service-to-service access, and CI/CD for deployment.

For observability, I would add OpenTelemetry traces, Prometheus metrics, Grafana dashboards, and audit logs for every tool call.

The trade-off is that a small tool surface is safer but exposes less functionality; schemas and metadata make agent use more predictable but add adapter overhead; cloud-native hardening improves security and observability but increases operational complexity.
```

转场：

```text
Finally, I summarize the next implementation steps.
```

## Slide 11: Outlook

要讲的重点：

```text
Harden, Extend, Evaluate。最后回到质量目标。
```

中文讲稿：

```text
最后，后续工作分成三步。

第一是 harden：增加 gateway auth、authorization、rate limiting 和 tool call audit logs。

第二是 extend：增加更多 read-only MiSArch capabilities，为 state-changing tools 加 confirmation gates，也可以增加 trace_summary tool。

第三是 evaluate：补充 negative tests、failure cases、latency distribution，并比较 VM 和 GKE 部署。

总结来说，这个项目不是用 MCP 替代 GraphQL，而是在 GraphQL 前面加一个 bounded agent-facing facade，让 MiSArch 对 external agents 更可发现、更结构化，也更清楚地表达副作用。
```

English script:

```text
Finally, the next steps are grouped into three parts.

First, harden the gateway with authentication, authorization, rate limiting, and audit logs for tool calls.

Second, extend the tool surface with more read-only MiSArch capabilities, stronger confirmation gates for state-changing tools, and possibly a trace_summary tool.

Third, evaluate more deeply with negative tests, failure cases, latency distributions, and a comparison between the VM deployment and GKE.

To summarize, this project does not replace GraphQL with MCP. It adds a bounded agent-facing facade in front of GraphQL, so that MiSArch becomes more discoverable, more structured, and clearer about side effects for external agents.
```

最后一句：

中文：

```text
这就是我在 MiSArch 上做 MCP adapter 的主要思路和当前结果。谢谢。
```

English:

```text
This is the main idea and current result of my MCP adapter for MiSArch. Thank you.
```

## 最容易被问的 6 个问题

| Question | Short answer |
|---|---|
| Is MCP replacing GraphQL? | No. GraphQL remains the system of record; MCP is an agent-facing facade. |
| Why is MCP slower? | It adds adapter and protocol steps such as tools/list and tools/call. The benefit is a stronger agent contract. |
| Why do you need Baseline A? | It isolates data correctness from query generation. It proves MCP returns the same core product data as direct GraphQL. |
| Why do you need Baseline B? | It tests whether an agent can use raw GraphQL by generating queries itself. |
| Why did Baseline B become slow? | The LLM has to generate list/detail GraphQL queries, so query generation dominates. |
| What is production work? | Auth, authorization, rate limiting, audit logs, observability, and possibly GKE deployment. |

## 8 分钟版背诵策略

```text
前 4 页讲 motivation 和 architecture，不要陷入代码细节。
第 5 页只讲模块和三个 tools，不要逐个函数解释。
第 6-7 页讲为什么 tool surface 小，这是你的安全性理由。
第 8-9 页认真讲 baseline，这是核心贡献。
第 10-11 页明确 prototype 和 production 的区别，避免被认为夸大完成度。
```

English memory guide:

```text
Slides 1 to 4 explain motivation and architecture.
Slide 5 gives the implementation state, but do not go too deep into code.
Slides 6 and 7 justify the small tool surface through safety and architecture principles.
Slides 8 and 9 are the core evaluation contribution.
Slides 10 and 11 separate the current prototype from production hardening.
```

