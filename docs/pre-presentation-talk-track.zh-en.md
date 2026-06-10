# Pre Presentation Talk Track: MiSArch MCP Agentic Interoperability

对应 PPT：

`/Users/wang/Downloads/Agentic_Interoperability_MiSArch_MCP_Implementation_Presentation.pptx`

这份文档按每一页 PPT 给出 presentation 思路、中文讲稿、英文讲稿、转场句和可预期追问。核心讲法是：

```text
MiSArch 原本通过 GraphQL 暴露能力。GraphQL 对开发者很强大，但对外部 agent 来说，它需要 agent 猜 query、理解业务副作用、判断哪些操作安全。

我的重构是在现有 GraphQL gateway 前面增加一个 Go 实现的 MCP gateway，把 selected MiSArch capabilities 暴露成 agent-facing tools。

评估不是证明 MCP 比 GraphQL 更快，而是证明 MCP 在保持核心数据一致的同时，增加 tool discovery、typed input schema、side-effect metadata 和 readiness observability。
```

English spine:

```text
MiSArch already exposes its capabilities through GraphQL. GraphQL is powerful for developers, but an external agent still has to infer query structure, business risk, and safe operations.

My refactoring adds a Go-based MCP gateway in front of the existing GraphQL gateway. It exposes selected MiSArch capabilities as agent-facing tools.

The evaluation does not try to show that MCP is faster than direct GraphQL. It shows that MCP preserves the core MiSArch data while adding discovery, typed inputs, side-effect metadata, and operational readiness.
```

## Overall Pre Structure

建议时间分配：

| Section | Slides | Time | Purpose |
|---|---:|---:|---|
| Motivation and quality goal | 1-2 | 1.5 min | 说明为什么 agent-facing interoperability 是质量目标 |
| Architecture context | 3-4 | 2 min | 说明 MiSArch 当前 GraphQL 架构和 MCP facade 重构边界 |
| Implementation state | 5 | 1.5 min | 说明代码实现到了哪里 |
| Assumptions and principles | 6-7 | 2 min | 说明为什么只暴露小工具面、为什么强调副作用和最小权限 |
| Evaluation and results | 8-9 | 3 min | 说明 baseline A/B/MCP 如何设计、结果如何解读 |
| Cloud-native outlook | 10-11 | 1.5 min | 说明当前不是生产硬化版本，下一步怎么走 |

最重要的一句话：

```text
MCP gateway is not replacing MiSArch GraphQL. It is an agent-facing facade that narrows, annotates, and observes selected MiSArch capabilities.
```

## Slide 1: Quality Goal

Slide title:

```text
Quality Goal: Agent-facing Interoperability for MiSArch
```

本页目标：

```text
告诉听众：这不是单纯做一个 API wrapper，而是在讨论一个软件架构质量目标：外部 AI agent 如何安全、可发现、可测试地使用 MiSArch。
```

中文讲稿：

```text
这一页我先给出整个项目的定位。MiSArch 是一个电商微服务系统，当前主要通过 GraphQL gateway 暴露能力。我的质量目标不是重写 MiSArch，也不是替换 GraphQL，而是让外部 AI agent 更容易、更安全地和 MiSArch 交互。

所以 presentation 会围绕四件事展开：第一，agent-facing interoperability 这个质量目标；第二，我做的 MCP gateway 重构；第三，如何通过 baseline A、baseline B 和 MCP path 做评估；第四，如果要走向 production，cloud-native 方向还需要补哪些东西。
```

English talk track:

```text
I start with the overall positioning of the project. MiSArch is an e-commerce microservice system, and its current integration point is the GraphQL gateway. My goal is not to rewrite MiSArch or replace GraphQL. The goal is to make selected MiSArch capabilities easier and safer for external AI agents to use.

The presentation is structured around four parts: the agent-facing interoperability quality goal, the MCP gateway refactoring, the evaluation through baseline A, baseline B, and MCP, and finally the cloud-native outlook for production hardening.
```

转场句：

```text
To make this quality goal concrete, the next slide defines what I mean by agent-facing interoperability.
```

可能追问：

Q: Why is this a quality goal rather than just a feature?

A:

```text
Because it changes architectural properties of the system: discoverability, bounded side effects, typed contracts, and observability. Those are not one endpoint's behavior; they affect how external agents can safely use the system.
```

Q: Are you replacing the existing GraphQL gateway?

A:

```text
No. GraphQL remains the system of record and developer-facing API. MCP is an additional facade for agent-facing access.
```

## Slide 2: Quality Goal Definition

Slide title:

```text
Quality goal: agent-facing interoperability
```

本页目标：

```text
把抽象质量目标拆成四个可评估属性：discoverability、typed I/O、side effects、operations。
```

中文讲稿：

```text
这里我把 agent-facing interoperability 拆成四个方面。

第一是 discoverability。agent 不应该靠猜 endpoint 或猜 GraphQL query 来完成任务，它应该能通过 tools/list 看到有哪些能力。

第二是 typed I/O。工具输入输出应该是结构化的，比如 product_id 是 string，quantity 有范围限制，而不是让 agent 自己拼一个任意 GraphQL 字符串。

第三是 side effects。agent 必须知道一个调用是 read-only，还是会改变购物车、订单或者支付状态。

第四是 operations。一个 adapter 要能部署和测试，所以我加了 healthz 和 readyz，其中 readyz 会真实检查 MiSArch GraphQL 是否可用。

这一页的 quality claim 是：MCP refactoring 应该提升 MiSArch 对外部 agent 的可用性，但不能把整个 GraphQL supergraph 无限制地暴露给 agent。
```

English talk track:

```text
I split agent-facing interoperability into four concrete properties.

The first is discoverability. An agent should not have to guess endpoints or GraphQL operations. It should be able to list available capabilities through tools/list.

The second is typed I/O. Inputs and outputs should be structured and validateable. For example, product_id is a string and quantity can be bounded, instead of asking the agent to construct arbitrary GraphQL strings.

The third is side effects. The agent must know whether a call is read-only or whether it changes shopping cart or order state.

The fourth is operations. The adapter must be deployable and testable, so I added healthz and readyz. The readiness endpoint checks the real MiSArch GraphQL gateway.

The quality claim is that the refactoring should make MiSArch more usable by external agents without exposing the full GraphQL supergraph as an uncontrolled tool surface.
```

转场句：

```text
Now that the quality goal is defined, I will show where this sits in the original MiSArch architecture.
```

可能追问：

Q: Why is GraphQL not enough for discoverability?

A:

```text
GraphQL has introspection, but an agent still needs to interpret a large developer-facing schema and decide which operation is safe for a user task. MCP presents a smaller task-oriented tool surface with explicit metadata.
```

Q: Why is side-effect metadata important?

A:

```text
Because an autonomous agent may call tools without a human reading every request. It needs to distinguish safe read operations from state-changing operations such as order creation.
```

## Slide 3: System Context

Slide title:

```text
System context: MiSArch is the target architecture
```

本页目标：

```text
说明原始系统是什么：Frontend/Client -> GraphQL Gateway -> domain services -> infrastructure。指出 raw GraphQL 对 agent 的问题。
```

中文讲稿：

```text
这页是系统上下文。MiSArch 当前是一个电商微服务系统。用户或客户端通过 frontend 进入，后面是 GraphQL gateway。GraphQL gateway 再调用 catalog、shopping cart、order、user 等 domain services，底层还有数据库、认证和运行时基础设施。

对开发者来说，GraphQL 很灵活，因为可以精确查询需要的字段。但对 agent 来说，问题是它要自己推断 query shape，理解哪些 mutation 有业务风险，还要知道哪些操作是安全的。

所以我这里的 current issue 是：GraphQL 是 developer-oriented API，但 agent-facing 的交互还缺少边界、说明和操作可观测性。
```

English talk track:

```text
This slide gives the system context. MiSArch is an e-commerce microservice architecture. A user or client enters through the frontend, then calls the GraphQL gateway. The gateway coordinates domain services such as catalog, shopping cart, order, and user services, with authentication, databases, and runtime infrastructure underneath.

For developers, GraphQL is flexible because it allows precise field selection. For agents, the problem is different. The agent has to infer the query shape, understand the business risk of mutations, and decide which operations are safe.

So the current issue is that GraphQL is a developer-oriented API, while an agent-facing integration needs boundaries, explanations, and operational observability.
```

转场句：

```text
The refactoring answers this issue by adding an MCP facade rather than changing the domain services.
```

可能追问：

Q: Could the agent simply use GraphQL introspection?

A:

```text
It could in theory, and that is exactly what baseline B tests. But introspection or schema text still leaves the agent responsible for choosing the right operation and understanding side effects. MCP reduces that burden by exposing selected capabilities as named tools.
```

Q: Why not modify the GraphQL schema directly?

A:

```text
Changing the GraphQL schema would affect the developer-facing API and service ownership. A facade keeps the existing GraphQL contract stable while adding an agent-specific boundary.
```

## Slide 4: Refactoring Goal

Slide title:

```text
Refactoring goal: MCP facade for MiSArch
```

本页目标：

```text
画清楚 before/after：before 是 agent 直连 GraphQL；after 是 agent 调 MCP gateway，MCP gateway 再调 GraphQL。
```

中文讲稿：

```text
这页是核心架构变化。

Before 的路径是 external agent 直接访问 MiSArch GraphQL。这样 agent 必须知道 GraphQL 怎么写，而且会面对比较宽的 API surface。

After 的路径是 external agent 调用 /mcp。中间的 Go MCP gateway 暴露 selected tools、input schemas 和 side-effect metadata。真正的数据仍然来自 MiSArch GraphQL，所以 GraphQL 还是 system of record。

重构边界很重要：我没有改 domain services，也没有把 MCP 做成新的业务系统。它是一个 facade，它把能力变窄、标注清楚，并且让 agent 更容易安全调用。
```

English talk track:

```text
This slide shows the core architectural change.

In the before path, the external agent calls MiSArch GraphQL directly. The agent must know how to write GraphQL and faces a broad API surface.

In the after path, the external agent calls /mcp. The Go MCP gateway exposes selected tools, input schemas, and side-effect metadata. The actual data still comes from MiSArch GraphQL, so GraphQL remains the system of record.

The refactoring boundary is important. I did not modify the domain services, and I did not turn MCP into a new business system. It is a facade that narrows and annotates capabilities for agent use.
```

转场句：

```text
Next I will show what has already been implemented in this facade.
```

可能追问：

Q: What does "selected tools" mean?

A:

```text
It means the gateway intentionally exposes only a small set of capabilities required by the use case, such as list_products, get_product, and create_pending_order.
```

Q: Does MCP add a single point of failure?

A:

```text
It adds an adapter component, so yes, it becomes part of the request path for agent access. That is why readiness checks, deployment health, authentication, and observability are part of the production outlook.
```

## Slide 5: Implementation State

Slide title:

```text
Current implementation state: working MCP prototype
```

本页目标：

```text
说明代码已经实现了什么，不夸大为 production-ready。
```

中文讲稿：

```text
这页对应具体实现。

cmd/server/main.go 负责配置、服务 wiring 和启动。internal/httpserver 提供 /mcp、/healthz 和 /readyz。internal/mcpserver 负责 tool registration 和 schema。internal/catalog 实现 list_products 和 get_product。internal/order 实现 create_pending_order workflow。internal/misarch 是 GraphQL client 和 Keycloak token source。

现在的 tool surface 有三个工具：list_products、get_product、create_pending_order。前两个是 read-only catalog tools，第三个会创建 pending order，但不做 payment，也不真正 place order。

当前成熟度我会明确说是 course-project prototype，已经部署在 GCP VM 上用于测试，但 production hardening 还在 outlook 部分。
```

English talk track:

```text
This slide maps the architecture to the implementation.

cmd/server/main.go handles configuration, service wiring, and startup. internal/httpserver exposes /mcp, /healthz, and /readyz. internal/mcpserver handles tool registration and schemas. internal/catalog implements list_products and get_product. internal/order implements the create_pending_order workflow. internal/misarch contains the GraphQL client and the Keycloak token source.

The current tool surface contains three tools: list_products, get_product, and create_pending_order. The first two are read-only catalog tools. The third creates a pending order, but it does not perform payment and does not place a final order.

I would describe the maturity clearly as a course-project prototype deployed on a GCP VM for evaluation. Production hardening is part of the outlook.
```

转场句：

```text
To explain why the tool surface is intentionally small, the next slide states the use-case assumptions.
```

可能追问：

Q: Where is the MCP protocol behavior implemented?

A:

```text
The HTTP entry point is in internal/httpserver, and tool registration, tool schemas, and tool call dispatch are handled in internal/mcpserver.
```

Q: Why include create_pending_order if order operations are risky?

A:

```text
Because the project should show both read-only and controlled state-changing access. The tool is bounded: it creates a pending order after selection, but it does not perform payment or final placement.
```

## Slide 6: Assumptions

Slide title:

```text
Business and use case assumptions shape the trade-offs
```

本页目标：

```text
告诉听众：架构取舍依赖业务假设。不是所有 MiSArch 能力都应该给 agent。
```

中文讲稿：

```text
这一页解释为什么我的 MCP tool surface 是小的。

第一个 use case 是 catalog exploration，允许 agent 查询公开商品，这是 read-only，业务风险低。

第二个是 order draft，允许在用户选择后创建 pending order，但不支付、不最终下单。这是受控的状态改变。

第三个是假设 external agent 只能通过 tool discovery 和 tool calls 使用系统，没有 admin 或 database access，这符合 least privilege。

第四个是部署假设。当前是 course evaluation on GCP，所以我会明确它是 restricted public endpoint，不说成生产系统。

关键假设是：在这个 use case 里，安全和可解释性比暴露所有功能或追求最低 latency 更重要。
```

English talk track:

```text
This slide explains why the MCP tool surface is intentionally small.

The first use case is catalog exploration. The agent can inspect public products, which is read-only and low risk.

The second use case is an order draft. After a user has selected an item, the agent may create a pending order, but it does not perform payment and does not place a final order. This is a controlled state change.

The third assumption is that the external agent only uses tool discovery and tool calls. It has no admin or database access, which follows least privilege.

The fourth assumption is the deployment context. This is a course evaluation on GCP with a restricted public endpoint, not a production claim.

The key assumption is that, for this use case, safety and explainability are more important than exposing every MiSArch capability or minimizing latency.
```

转场句：

```text
These assumptions connect directly to established architecture principles, which are summarized on the next slide.
```

可能追问：

Q: Why not expose all read-only GraphQL queries?

A:

```text
Even read-only access can leak unnecessary data or overwhelm the agent with irrelevant capabilities. A task-specific surface is easier to validate, document, and monitor.
```

Q: Is latency not important?

A:

```text
Latency is still measured, but it is not the primary quality goal. The expected trade-off is extra adapter overhead in exchange for a safer and more discoverable agent contract.
```

## Slide 7: Scientific Basis

Slide title:

```text
Scientific basis: established architecture principles
```

本页目标：

```text
把 MCP 这个新协议和成熟架构思想连接起来：facade/API gateway、typed contracts、least privilege。
```

中文讲稿：

```text
这一页是理论基础。MCP 本身比较新，但我使用它的架构理由并不新。

Facade 或 API gateway 的思想是：在复杂内部 API 前面放一个窄的、面向任务的外部 contract。这里 MCP gateway 隐藏了 GraphQL 复杂性，只暴露 agent 需要的能力。

Typed contracts 的思想是：结构化 schema 可以让调用机器可检查，减少自然语言或自由 query 带来的歧义。

Least privilege 的思想是：只给 agent 用例需要的能力，不给 admin、database 或 payment access。

所以技术原则是：agent 应该收到显式 tools，包括 name、input schema、output shape、source metadata 和 side-effect information，而不是直接解释一个大的 application API。
```

English talk track:

```text
This slide gives the architectural basis. MCP itself is new, but the architectural reasoning behind this refactoring is not new.

The facade or API gateway principle says that we can put a narrow, task-oriented external contract in front of a complex internal API. Here, the MCP gateway hides GraphQL complexity and exposes only the capabilities needed by the agent.

Typed contracts make calls machine-checkable and reduce ambiguity compared with free-form queries.

Least privilege means the agent receives only the capabilities required by the use case, not admin, database, or payment access.

The technical principle is that the agent should receive explicit tools with names, input schemas, output shape, source metadata, and side-effect information instead of interpreting a broad application API directly.
```

转场句：

```text
The next question is how to evaluate whether this refactoring actually improves the quality goal.
```

可能追问：

Q: Is MCP just another API gateway?

A:

```text
Architecturally it behaves like a facade, but it is specialized for agent-tool interaction. The important difference is the protocol-level tool discovery and structured tool metadata.
```

Q: What is the scientific contribution?

A:

```text
The project applies established architecture principles to an agent interoperability problem and evaluates whether the facade preserves data correctness while adding agent-facing properties.
```

## Slide 8: Evaluation Design

Slide title:

```text
Evaluation design: measure the quality goal in architecture
```

本页目标：

```text
说明评估维度：correctness、reliability、performance、interoperability、safety。这里要引入 baseline A/B/MCP 三条路径。
```

中文讲稿：

```text
这一页是评估设计。我不只测能不能跑，而是把质量目标拆成几个可观测指标。

Correctness 用 same core product data 来衡量，也就是 GraphQL 和 MCP 是否返回同一个商品核心字段。

Reliability 用 5-trial runs 的 success rate 来衡量。

Performance 用 timed HTTP calls 的 average latency 来衡量。

Interoperability 通过 MCP tools/list、input schemas 和 tool call flow 来检查。

Safety 通过输入校验和 negative tests 来检查，例如 bad UUID 或 excessive quantity。

这里我建议在讲的时候补充三条 baseline 路径。Baseline A 是 fixed GraphQL：LLM 读任务，但只能选择固定 executor，executor 执行预写 query。Baseline B 是 agent-generated GraphQL：LLM 自己生成 GraphQL query，再执行生成的 query。MCP path 是 agent 先 tools/list，再 tools/call。
```

English talk track:

```text
This slide describes the evaluation design. I do not only test whether the system runs. I break the quality goal into observable dimensions.

Correctness is measured by same core product data: whether GraphQL and MCP return the same core product fields.

Reliability is measured by success rate across five-trial runs.

Performance is measured by average latency from timed HTTP calls.

Interoperability is checked through MCP tools/list, input schemas, and the tool-call flow.

Safety is checked through validation and negative tests, for example bad UUIDs or excessive quantity.

In the oral presentation I would add the three baseline paths. Baseline A is fixed GraphQL: the LLM reads the task but can only select a fixed executor, and the executor runs prewritten queries. Baseline B is agent-generated GraphQL: the LLM generates GraphQL queries, and the executor runs those generated queries. The MCP path asks the agent to inspect tools/list and then use tools/call.
```

转场句：

```text
With this evaluation design, the next slide shows the measured result and how I interpret it.
```

可对照的现有文件：

```text
scripts/agent_gcp_smoke_test.py
scripts/manual_minimal_baseline_eval.py
scripts/visualize_agent_baselines.py
docs/pre-test-results.zh.md
```

建议在本页口头补充的 baseline 表：

| Path | LLM decision? | What the LLM does | What the executor does |
|---|---|---|---|
| Baseline A | Yes | Selects fixed GraphQL executor | Runs prewritten GraphQL list/detail queries |
| Baseline B | Yes | Generates native GraphQL query | Runs generated query and records errors |
| MCP | Yes | Reads tools/list and plans tools/call | Executes MCP tool calls |

可能追问：

Q: Why do you need baseline A and baseline B?

A:

```text
Baseline A separates data correctness from query generation. It answers whether direct GraphQL and MCP can return the same data. Baseline B tests whether raw GraphQL is friendly for an agent that has to generate queries itself.
```

Q: Why is latency not the main success criterion?

A:

```text
Direct GraphQL is expected to be faster because it has the shortest path. MCP is successful if it preserves data while adding the agent contract. The latency cost is measured as a trade-off.
```

## Slide 9: Current Results

Slide title:

```text
Current results: same data, stronger agent contract
```

本页目标：

```text
用结果证明：MCP 保持数据一致，同时增加 agent contract。再补充 Baseline B 的意义。
```

重要提醒：

```text
PPT 第 9 页当前显示的 Native GraphQL 152.8 ms / MCP 296.68 ms 是早期 A/MCP smoke 对比数字。

pre 时可以保留它作为“直接 GraphQL vs MCP adapter overhead”的直观结果，但不要把它和后面 LLM-controller baseline 数字混在同一个 latency 表里。

如果讲 Baseline A/B/MCP，请明确说：下面是 extended evaluation results，包含 LLM controller 或 manual simulation，因此 latency 条件不同。
```

中文讲稿：

```text
这一页是核心结果。最重要的结论不是 MCP 更快，而是 MCP 在保持核心商品数据一致的同时，提供了更强的 agent contract。

从基础 GraphQL vs MCP 对比来看，Native GraphQL 5/5 成功，MCP 也是 5/5 成功；same core product data 也是 5/5。说明 MCP 没有改变 MiSArch 的核心 catalog 数据。

延迟上，GraphQL 更快，这是预期内的，因为 MCP 多了 adapter、tools/list 和 tools/call 的协议开销。所以我会把它解释成 architecture trade-off：用额外开销换取 discoverability、schema、side-effect metadata 和更清楚的 agent boundary。

如果老师问 baseline B，我会补充两组结果：有 schema 文档时，Baseline B 5/5 成功，但平均耗时最高，因为它要让 LLM 生成 GraphQL query。minimal 条件下，不给 schema 字段文档时，真实 LLM Baseline B 0/5 成功，失败在 model_generation timeout。手工 minimal simulation 则展示了另一种 raw GraphQL 问题：agent 先猜错字段，收到 GraphQL error，再恢复。
```

English talk track:

```text
This is the main result slide. The key result is not that MCP is faster. The key result is that MCP preserves the core product data while adding a stronger agent contract.

In the direct GraphQL versus MCP comparison, native GraphQL succeeds in five out of five trials, and MCP also succeeds in five out of five trials. The same core product data metric is also five out of five. This means the MCP gateway does not change the core MiSArch catalog result.

For latency, direct GraphQL is faster, which is expected because MCP adds an adapter and protocol steps such as tools/list and tools/call. I interpret this as an architectural trade-off: extra overhead in exchange for discoverability, schemas, side-effect metadata, and a clearer agent boundary.

If asked about baseline B, I would add two results. With a schema excerpt, baseline B succeeds in five out of five trials, but it has the highest average duration because the model has to generate GraphQL queries. Under the minimal condition, where no GraphQL field documentation is provided, the real LLM baseline B succeeds in zero out of five trials and fails at model generation timeout. The manual minimal simulation shows another raw GraphQL issue: the agent first guesses a wrong field, receives a GraphQL error, and then recovers.
```

转场句：

```text
After showing that the prototype works, the next slide discusses what is missing for a production cloud-native version.
```

推荐更新/口头补充的结果表：

| Experiment | Baseline A | Baseline B | MCP | Interpretation |
|---|---:|---:|---:|---|
| Schema experiment | 5/5 | 5/5 | 5/5 | With schema context, agent-generated GraphQL can work, but is slow |
| Minimal LLM experiment | 5/5 | 0/5 | 5/5 | Without schema fields, raw GraphQL path depends on model generation and timed out |
| Manual minimal simulation | 5/5 | 5/5 after recovery | 5/5 | Raw GraphQL can require guessing, error interpretation, and repair |

可引用的现有结果：

```text
Schema experiment:
eval/pre_llm_controller_schema_5_trials_20260604.json
Baseline A 5/5, Baseline B 5/5, MCP 5/5
Average duration: A 5926.54 ms, B 21124.56 ms, MCP 8197.66 ms

Minimal LLM experiment:
eval/pre_llm_controller_minimal_retest_20260604.json
Baseline A 5/5, Baseline B 0/5, MCP 5/5
Failure stage: model_generation 5

Manual minimal simulation:
eval/manual_minimal_baseline_b_5_trials_20260604.json
Baseline A 5/5, manual B 5/5 after recovery, MCP 5/5
Initial GraphQL field error: 5/5
Average duration: A 177.82 ms, manual B 237.94 ms, MCP 391.64 ms
```

可能追问：

Q: Why are the latency numbers different between old A/MCP comparison and LLM-controller experiments?

A:

```text
They measure different conditions. The plain A/MCP smoke path measures HTTP execution directly. The LLM-controller experiments include model planning or query generation, so the numbers are larger and should be interpreted separately.
```

Q: Does Baseline B failure prove MCP is always better?

A:

```text
No. It proves a narrower claim: raw GraphQL requires additional agent work such as query generation, schema understanding, and error repair. MCP reduces that work by presenting explicit tools and schemas.
```

Q: If Baseline B works with schema, why need MCP?

A:

```text
Because success depends on schema context and correct query generation. MCP gives the agent a smaller, task-oriented interface and includes metadata about input structure and side effects.
```

## Slide 10: Cloud-Native Outlook

Slide title:

```text
Cloud-native technologies and acceptable trade-offs
```

本页目标：

```text
说明当前 GCP VM + Docker Compose 是 prototype 部署，production 方向是 GKE、ingress/API gateway、OIDC、network policy、CI/CD、observability。
```

中文讲稿：

```text
这一页我会明确区分 prototype 和 production。

当前实现是 Docker Compose on a GCP VM。MCP gateway 作为 container 运行，通过 Docker 内部网络访问 MiSArch GraphQL，也支持 optional Keycloak token source。

如果要变成生产级 cloud-native 架构，候选平台是 Kubernetes 或 GKE。入口层可以是 ingress 或 API gateway。认证授权需要 OIDC。网络层需要 network policy。部署需要 CI/CD。

Observability 方面，我建议加入 OpenTelemetry traces、Prometheus metrics、Grafana dashboards，以及每一次 tool call 的 audit logs。

Trade-off 上，小的 MCP tool surface 更安全但功能少；schema 和 metadata 让 agent 更可预测但增加 adapter overhead；cloud-native hardening 提升安全和可观测性，但也增加运维复杂度。
```

English talk track:

```text
This slide separates the current prototype from a production direction.

The current implementation runs with Docker Compose on a GCP VM. The MCP gateway runs as a container and reaches MiSArch GraphQL through Docker-internal networking. It also supports an optional Keycloak token source.

For a production cloud-native architecture, the candidate platform would be Kubernetes or GKE. The entry layer would use ingress or an API gateway. Authentication and authorization should use OIDC. The network layer should use network policies, and deployment should be handled through CI/CD.

For observability, I would add OpenTelemetry traces, Prometheus metrics, Grafana dashboards, and audit logs for every tool call.

The trade-offs are clear: a small MCP tool surface is safer but exposes less functionality; schemas and metadata make agent use more predictable but add adapter overhead; cloud-native hardening improves security and observability but adds operational complexity.
```

转场句：

```text
The final slide turns this outlook into concrete next implementation steps.
```

可能追问：

Q: Why did you not deploy directly to GKE?

A:

```text
For the course prototype, a GCP VM with Docker Compose was sufficient to validate the architecture and run real integration tests. GKE is the production direction once authentication, policy, and observability requirements are clearer.
```

Q: What is the most important production hardening step?

A:

```text
Authentication and authorization for MCP tool calls. Without that, a public agent-facing endpoint would be too risky.
```

## Slide 11: Outlook

Slide title:

```text
Outlook: what will be implemented next
```

本页目标：

```text
收束项目：Harden、Extend、Evaluate。最后回到 quality goal。
```

中文讲稿：

```text
最后一页是后续工作。

第一步是 harden：为 gateway 增加 authentication、authorization、rate limiting 和每次 tool call 的 audit logs。

第二步是 extend：增加更多 read-only MiSArch capabilities，给 state-changing tools 增加更强的 confirmation gates，并可以考虑一个 trace_summary tool，让 agent 或 evaluator 查看调用路径。

第三步是 evaluate：补充 negative tests、failure cases、latency distribution，并比较 GCP VM 和 GKE 部署。

最后我会回到最初的 quality goal：这个项目展示了如何把一个 developer-facing GraphQL architecture，通过一个 bounded MCP facade，变成更适合 external agent 使用的 architecture boundary。
```

English talk track:

```text
The final slide summarizes the next steps.

The first step is hardening: add authentication, authorization, rate limiting, and audit logs for every tool call.

The second step is extension: expose more read-only MiSArch capabilities, add stronger confirmation gates for state-changing tools, and possibly add a trace_summary tool so that an agent or evaluator can inspect the call path.

The third step is evaluation: add negative tests, failure cases, latency distributions, and compare the current GCP VM deployment with a GKE deployment.

I would close by returning to the original quality goal: the project shows how a developer-facing GraphQL architecture can be exposed to external agents through a bounded MCP facade that is more discoverable, structured, and observable.
```

收尾句：

```text
So the main contribution is not a new business capability in MiSArch, but an agent-facing architectural boundary around selected MiSArch capabilities.
```

可能追问：

Q: What would you implement first after this presentation?

A:

```text
I would implement authentication and audit logs first, because they are required before exposing state-changing tools more broadly.
```

Q: How would you evaluate the next version?

A:

```text
I would keep the existing baseline A/B/MCP design, add negative tests for invalid or risky tool calls, record latency distributions rather than only averages, and add traces to explain where time is spent.
```

## Baseline Explanation For Q&A

如果被问到 baseline，建议这样讲：

中文：

```text
我这里有三条路径。

Baseline A 是 fixed GraphQL。LLM 可以理解任务，但不自己写 GraphQL；它只能选择 fixed executor。这个 baseline 的作用是证明数据正确性：如果 GraphQL 和 MCP 返回同一个商品，说明 MCP 没有改变业务数据。

Baseline B 是 agent-generated GraphQL。LLM 需要自己生成 GraphQL query，然后 executor 执行它。这个 baseline 的作用是测试 raw GraphQL 对 agent 是否友好。

MCP path 是 agent 先通过 tools/list 发现工具，再通过 tools/call 调用 list_products 和 get_product。它不要求 agent 写 GraphQL，而是使用工具名、input schema 和 side-effect metadata。
```

English:

```text
I use three paths.

Baseline A is fixed GraphQL. The LLM can understand the task, but it does not write GraphQL. It only selects a fixed executor. This baseline proves data correctness: if GraphQL and MCP return the same product, then MCP preserves the business data.

Baseline B is agent-generated GraphQL. The LLM has to generate the GraphQL query itself, and the executor runs the generated query. This baseline tests whether raw GraphQL is friendly for an agent.

The MCP path asks the agent to discover tools through tools/list and then call list_products and get_product through tools/call. It does not require the agent to write GraphQL. Instead, it exposes tool names, input schemas, and side-effect metadata.
```

结果解释：

| Result | How to explain |
|---|---|
| A and MCP both 5/5 | MCP preserves the core MiSArch catalog data |
| MCP slower than A | Expected adapter/protocol overhead |
| Schema B 5/5 but slow | Agent can use GraphQL when schema context is provided, but query generation is expensive |
| Minimal B 0/5 | Raw GraphQL path depends on model generation and schema knowledge |
| Manual minimal B recovered 5/5 | Raw GraphQL may require guess -> error -> repair, which MCP avoids |

## Strong Closing Version

中文结尾：

```text
总结来说，我的项目不是要证明 MCP 替代 GraphQL，而是证明在 agent interoperability 这个质量目标下，一个 bounded MCP facade 可以让 MiSArch 的能力更可发现、更结构化、更能表达副作用，并且仍然保持和原始 GraphQL 相同的核心业务数据。
```

English closing:

```text
To summarize, my project does not argue that MCP replaces GraphQL. It argues that, for the quality goal of agent interoperability, a bounded MCP facade can make MiSArch capabilities more discoverable, more structured, and clearer about side effects, while still preserving the same core business data as the original GraphQL gateway.
```
