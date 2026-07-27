# MiSArch Agent Gateway 答辩 50 问学习文档

> 最后核对：2026-07-13  
> 范围：Direct GraphQL、MCP Gateway、MCP Agent、MCP + Profile、A2A、延迟、token、hop 与安全回归。

## 使用方法

每题先背“短答”，答辩时用 15–25 秒回答；老师继续追问时，再使用“展开”。不要把实验结果说成超出证据范围的普遍结论。

必须始终坚持六条口径：

1. MCP 是 GraphQL 上面的 agent-facing facade，不是 GraphQL 的替代品。
2. 183 ms vs 341 ms 是无 LLM 的确定性协议路径比较。
3. 5176/4143/1448 ms 是包含 LLM 的 Agent 路径结果。
4. A2A 在正式实验中更快，主要因为空 catalog 导致提前结束，不证明 A2A 天生更快。
5. `success=True` 表示流程成功返回受支持的结果，不等于用户购物目标已完成。
6. 4/4、1/1 等安全数字只代表选定回归样例，不代表系统“100% 安全”。

## 快速架构图

```text
Arm A: 测试脚本 → 固定 GraphQL query → MiSArch GraphQL

Arm B: 用户任务 → LLM/ReAct loop → MCP tools → Go MCP Gateway → GraphQL

Arm D: 用户任务 + Profile JSON → 同一个 LLM/ReAct loop → 同一个 MCP 路径

Arm C: 用户任务 → User-side Butler → A2A Store Agent → GraphQL
                                    └→ Profile 本地筛选/排序
```

---

# 一、项目目标与架构

## Q1. 这个项目一句话解决什么问题？

**短答：** 它把 MiSArch 面向开发者的 GraphQL 能力，通过一个受限、可发现、结构化的 MCP facade 暴露给外部 Agent，并进一步用 A2A 验证多 Agent、隐私和安全边界。

**展开：** 项目没有重写 MiSArch 的业务服务。Catalog、Order、数据库和 GraphQL gateway 仍是原来的业务系统；新增的 Go gateway 负责把选定能力包装成 MCP tools，同时暴露 A2A Agent Card 和任务接口。质量目标是 agent interoperability、可检查性和更明确的副作用边界。

## Q2. 已经有 GraphQL，为什么还需要 MCP？

**短答：** GraphQL 很适合开发者，但外部 Agent 还要理解 schema、生成正确 query、处理错误和判断副作用；MCP 把这些能力缩小为任务导向的工具合同。

**展开：** 使用 MCP 后，Agent 可以通过 `tools/list` 发现工具，并直接获得工具名、描述和 `inputSchema`，再通过标准 `tools/call` 调用。代价是多一层 adapter 和协议开销。项目的结论不是“MCP 更快”，而是“MCP 用额外开销换取更适合 Agent 的接口”。

## Q3. MCP 会替代 GraphQL 吗？

**短答：** 不会。当前 MCP Gateway 内部仍然调用 GraphQL；两者位于不同抽象层。

**展开：** GraphQL 继续承担微服务聚合和业务数据访问；MCP 只暴露少量经过选择的能力。开发者可以继续使用完整 GraphQL，外部 Agent 则使用更窄的 MCP surface。这个设计减少了 Agent 必须理解的业务和 schema 范围。

## Q4. 系统中有哪些核心组件？

**短答：** 核心组件是 Python Agent/测试脚本、Go MCP/A2A Gateway、MiSArch GraphQL Gateway，以及 Catalog/Order 等领域服务。

**展开：** `cmd/server/main.go` 组装 GraphQL client、catalog service、order service、MCP server、A2A handler 和 HTTP server。`internal/mcpserver` 负责工具合同；`internal/a2aserver` 负责 Agent Card 与 `/tasks`；`internal/catalog` 和 `internal/order` 负责真正的 GraphQL 映射。

## Q5. MCP Gateway 暴露了哪些工具？

**短答：** 服务端注册了 `list_products`、`get_product` 和 `create_pending_order`。

**展开：** 前两个是只读 catalog 工具；`create_pending_order` 有受控副作用，会创建 shopping-cart item 和 pending order，但不支付。正式的 B/D read-only Agent 又使用 allowlist，只向模型提供 `list_products` 和 `get_product`，因此服务端能力和特定 Agent 获得的能力并不相同。

## Q6. Go MCP Gateway 是如何实现的？

**短答：** 它使用官方 Go MCP SDK 创建 Server，用强类型 Go 结构注册工具，再用 Streamable HTTP 暴露 `/mcp`。

**展开：** `internal/mcpserver/server.go` 调用 `mcp.NewServer` 和 `mcp.AddTool`。工具 handler 接收类型化输入，调用 catalog/order service，SDK生成 `inputSchema` 并返回 `structuredContent`。`mcp.NewStreamableHTTPHandler` 将协议挂载到 HTTP server。

## Q7. 为什么 Gateway 不直接把整个 GraphQL schema 暴露给 Agent？

**短答：** 小工具面更容易理解、测试和限制权限，也能减少 Agent 生成任意 query 或 mutation 的风险。

**展开：** 如果直接暴露完整 GraphQL，Agent 必须处理大量无关类型和 mutation。当前 facade 只暴露项目需要验证的 catalog 与 pending-order 能力，形成明确的 architecture boundary。缺点是功能覆盖更少，需要维护 GraphQL-to-tool adapter。

## Q8. 项目最重要的架构权衡是什么？

**短答：** 用额外的协议、adapter、LLM 和运维开销，换取可发现性、结构化合同、策略控制和更清楚的信任边界。

**展开：** Direct GraphQL 的路径最短；MCP 更适合工具互操作；A2A 又增加跨 Agent 协作、Profile 本地化和信任域，但带来更多安全问题。不存在一个在所有指标上都最优的 arm。

---

# 二、MCP 协议与基础对比

## Q9. 当前实现实际使用了 MCP 的哪些特性？

**短答：** 使用了 JSON-RPC、初始化握手、协议版本、session、`tools/list`、`tools/call`、输入 schema、structured content 和 Streamable HTTP。

**展开：** 客户端先发送 `initialize`，读取 `Mcp-Session-Id`，再发送 `notifications/initialized`。之后通过 `tools/list` 获取工具合同，通过 `tools/call` 调用工具。客户端兼容 JSON 和 SSE 形式的响应，并要求工具结果包含 `structuredContent`。

## Q10. 当前没有使用哪些 MCP 特性？

**短答：** 没有使用 MCP Resources、Prompts、Sampling、Roots、Elicitation、tool-list-changed notification，也没有用 MCP Resource 管理 Profile。

**展开：** 工具的“read-only”和“side effects”目前主要写在 description 和输出字段中，不是标准 `ToolAnnotations.readOnlyHint`。因此演讲时应说“项目通过工具描述和结构化输出表达副作用”，不要声称已经完整使用标准 annotation 能力。

## Q11. 为什么 MCP 不能像普通 REST 一样直接调用 `tools/list`？

**短答：** Streamable HTTP MCP 有 session 生命周期，必须先完成初始化和 initialized notification。

**展开：** 正确顺序是：

```text
initialize
→ 读取 Mcp-Session-Id
→ notifications/initialized
→ tools/list
→ tools/call
```

跳过初始化时，服务端会拒绝处于错误 session 状态的方法调用。这也是 MCP 与“给 REST endpoint 换一个工具名”的区别。

## Q12. Direct GraphQL vs MCP 的主要 baseline 有 LLM 参与吗？

**短答：** 没有。主要的 183 ms vs 341 ms baseline 是测试脚本的确定性执行，不是自主 Agent 对比。

**展开：** 虽然函数名包含 `agent`，Direct GraphQL 使用预写 query；MCP 使用预写的 `list_products`、`get_product` 调用计划。只有显式启用 `--use-llm-controller` 或 `--include-agent-generated-graphql` 时，模型才参与决策或 query 生成。

## Q13. Direct GraphQL baseline 具体执行什么？

**短答：** 它直接执行一个 list query，取第一个 product ID，再执行一个 detail query。

**展开：** `run_native_graphql_agent` 使用代码中的 `LIST_PRODUCTS_QUERY` 和 `GET_PRODUCT_QUERY`，通过 HTTP POST 到 `/graphql`，最后把结果标准化为 product ID、variant ID、name、price 和 categories。它测量的是已知 query 的最短路径。

## Q14. 确定性 MCP baseline 具体执行什么？

**短答：** 它创建新 MCP session、发现工具，然后固定调用 `list_products` 和 `get_product`。

**展开：** 每个 trial 都执行 initialize、initialized notification、`tools/list`、`tools/call(list_products)` 和 `tools/call(get_product)`。Gateway 再把两个 tool call 转换为 GraphQL。它验证协议兼容和数据一致性，不验证自主推理。

## Q15. 为什么 Direct GraphQL 是 183 ms，而 MCP 是 341 ms？

**短答：** MCP 多了 session 初始化、工具发现、JSON-RPC、Gateway 转换和结构化结果映射。

**展开：** 341/183 约等于 1.86，因此应说“MCP 完整 cold-session 路径耗时为 GraphQL 的 1.86 倍，约多 158 ms”，而不是模糊地说“GraphQL 1.86 倍更快”。如果复用 session，初始化和工具发现可以被摊薄，结果可能不同。

## Q16. 5/5 相同商品数据说明了什么？

**短答：** 它说明在这个 catalog lookup 中，MCP facade 保留了 GraphQL 的核心业务语义。

**展开：** 五次中 product ID、name 和 price 一致，说明 adapter 没有改变核心结果。但样本只有五次和一个读取任务，不能据此证明所有字段、所有 mutation 或所有错误场景都完全等价。

## Q17. 这个 Direct GraphQL vs MCP 对比公平吗？

**短答：** 对“同一个逻辑 lookup 的两条接口路径”是合理的，但不是同等网络请求数量，也不是 Agent 智能比较。

**展开：** GraphQL 执行两个直接 POST；MCP 还包含 control-plane setup 和 discovery。因此它刻意测量端到端 facade 开销。如果要测纯业务执行，应预热并复用 MCP session，单独比较两个业务调用的 latency。

---

# 三、MCP Agent、Profile 与 A2A

## Q18. Arm A、B、D、C 分别是什么？

**短答：** A 是固定 GraphQL；B 是单 Agent MCP；D 是 B 加结构化 Profile；C 是 user-side Butler 与 Store Agent 的 A2A。

**展开：** A 主要作为非 Agent latency/data reference。B/D 使用同一个 `agent_mcp_loop.py`；D 只增加 `--profile` 和 `--user-id`。C 使用 `agent_a2a_loop.py`，把 Profile 保留在用户侧并通过 A2A 与 Store Agent 协作。

## Q19. Arm B 的 ReAct loop 是如何工作的？

**短答：** 每轮 LLM 只能输出一个 `tool_call` 或 `final`，orchestrator 执行工具并把 observation 加入 history，再进入下一轮。

**展开：** 这是自定义 JSON decision loop，不是 Responses API 原生 tool calling。模型每轮重新接收用户任务、工具 schema 和完整 history。代码还规定至少一次成功工具调用后才接受 final，并使用 read-only allowlist 拒绝未授权工具。

## Q20. Arm D 的 Profile 是如何实现的？

**短答：** 从本地 `data/user_profile.json` 按 user ID 读取，再把 JSON 直接追加到 LLM 的任务 prompt。

**展开：** D 的 MCP 网络路径、工具、Gateway 和 GraphQL 路径与 B 完全相同。Profile 包括 cup 的材质、容量、价格敏感度和全局预算。它不是通过 MCP resource 读取，也不在 Gateway 中执行个性化逻辑。

## Q21. 为什么 B 的购买任务有时需要三次 LLM decision，而 D 只需要两次？

**短答：** B 第一次过早输出 final，被运行时策略拒绝；D 更容易先查 catalog，因此避免了这次浪费的 decision。

**展开：** B 的序列是 `final → rejected → list_products → final`，对应三次 LLM 调用。D 的序列是 `list_products → final`，对应两次。Profile 让“先找符合条件的商品”更像一个有用子目标，但这只是 prompt conditioning 造成的非确定性行为，不是代码规定。

## Q22. 为什么 B 的模型会直接输出 final？

**短答：** 用户要求下单，但模型只看到只读工具，于是判断查询也不能改变“无法下单”的结论，直接尝试拒绝。

**展开：** Prompt 明明要求至少成功调用一次工具，但 LLM 不保证完全遵循文字规则。因此代码仍需检查 `successful_tool_calls`。这个例子说明 prompt 是软约束，runtime policy 才是硬约束。

## Q23. Profile 是否必然减少 LLM 调用或延迟？

**短答：** 不必然。本次 D 少了一些 decision 是观察结果，不是稳定机制。

**展开：** Profile 会增加每次 prompt 的长度，也可能让模型执行更多详情查询。换模型、换任务或重复运行，第一步选择都可能变化。不能从一次平均值推出“Profile 是性能优化”。

## Q24. `preference_used=true` 能证明模型真的遵循了偏好吗？

**短答：** 不能。当前字段只等于 `bool(profile)`，证明 Profile 成功加载，不证明推荐满足每个偏好。

**展开：** 更严谨的 preference adoption 指标应该逐项检查材质、容量、预算和价格敏感度，并区分“Profile 被提供”“回答提到 Profile”“推荐实际满足 Profile”。

## Q25. Arm C 的 A2A 路径是如何实现的？

**短答：** Butler 先识别 category/purchase intent，再获取 Store Agent Card，发送 browse task，本地筛选排序，最后生成答案或执行风险拦截。

**展开：** A2A client 使用 `GET /.well-known/agent-card.json` 和 `POST /tasks`。Store Agent 扫描 catalog、按 query 过滤并返回未排序候选；完整 Profile 不进入 Store Agent。Butler 再执行价格筛选、Profile 排序和风险策略。

## Q26. Agent Card 的作用是什么？

**短答：** 它是 Store Agent 的能力和风险声明，描述 endpoint、browse/purchase skills、side effects 和 confirmation requirement。

**展开：** Agent Card 支持能力发现，但它来自另一个信任域，不能被无条件信任。当前防御会记录卡片信息，却不允许商家用自我声明降低用户侧购买风险策略。

## Q27. Arm C 如何保护 Profile 隐私？

**短答：** 完整 Profile 只保存在 Butler 本地；默认跨 A2A 边界发送的 constraints 是空对象。

**展开：** Store Agent 收到的是任务推导出的 query，例如 `cup`，以及白名单 constraints。正式结果中的 `profile_fields_disclosed=[]`。但“零 Profile 字段”不等于零信息泄露，因为任务本身和推导的 category 仍会跨界。

## Q28. Store Agent 和 Butler 为什么要分开排序？

**短答：** Store Agent 只返回候选，Butler 用私有偏好本地排序，可以减少 Profile 泄露并保留用户控制权。

**展开：** `PreferenceModule.screen_candidates` 先处理价格异常和预算，`rank` 再根据材质和价格敏感度计算顺序。代价是 Butler 必须判断来自 Store Agent 的候选数据是否可信。

## Q29. 当前 A2A 真的会下单吗？

**短答：** 不会。当前是 Phase 1 风险拦截，检测到购买意图后要求确认，但不会发送真实 purchase task。

**展开：** `purchase_task_sent` 保持 false。即使意图分类漏检，当前实现也没有真实付款或订单提交路径。因此安全测试主要验证分类、风险状态和 gate 逻辑，而不是已经部署的真实支付防护。

---

# 四、端到端延迟与成功率

## Q30. 四个 arm 的 `duration_ms` 从哪里开始、到哪里结束？

**短答：** A 从固定 GraphQL lookup 开始到标准化结果；B/D 从 MCP connect 开始到 LLM final；C 从 Butler 接收任务开始到答案或提前返回。

**展开：** B/D 包含 MCP setup、工具发现、所有 LLM decisions 和 tool calls。C 包含 intent LLM、Agent Card、browse，以及有候选时的 final-answer LLM。不同 arm 做的工作并不完全相同，必须结合执行路径解释数字。

## Q31. 5176、4143、1448 和 183 ms 是怎么生成的？

**短答：** A 是独立的 5 次固定 lookup 平均；B/D/C 分别是 4 个任务 × 5 次，即每个 arm 20 次的平均。

**展开：** 原始平均值是 A 182.94、B 5175.50、D 4142.91、C 1447.65 ms。A 与后三个 arm 的任务数和工作负载不同，因此 A 应标成 non-agent reference floor，而不是同条件 Agent competitor。

## Q32. 为什么 B/D 比协议级 MCP baseline 慢这么多？

**短答：** 主要时间花在重复 LLM decision，不是 MCP 网络协议。

**展开：** B 共 45 次 model decision，D 共 40 次。按 trace 汇总，模型时间约占 B 的 94% 和 D 的 93%；MCP connect、`tools/list` 和实际 tool call 通常合计只有约 250–300 ms。341 ms 与 4–5 秒测量的是不同层次。

## Q33. 为什么 D 的平均 latency 比 B 低？

**短答：** B 的购买任务多了一轮被拒绝的 premature final，并出现较大的 LLM latency outlier；不能解释为 Profile 天生提速。

**展开：** B 购买任务平均约 10.3 秒，出现 20.1 秒和 13.8 秒样本；D 对应平均约 5.0 秒。总体 median 反而是 B 约 3468 ms、D 约 3742 ms，进一步说明 mean 的差异受步骤数和 outlier 影响。

## Q34. 为什么 A2A 只有约 1448 ms？

**短答：** 所有正式 C runs 都只做一次 intent LLM、Agent Card 和 browse，然后因零候选提前返回，跳过 final-answer LLM。

**展开：** Store Agent 对 `cup` 和 `tent` query 没找到匹配商品，Butler 在 `inventory_shortfall` 分支返回固定结构化答案。它没有执行完整 Profile ranking、最终推荐和购买风险流程。因此结果不证明 A2A 架构本身更快。

## Q35. “All 60 trials succeeded”是什么意思？

**短答：** B/D/C 共 60 次流程都没有协议或 orchestration failure，并成功返回结果；不等于 60 次用户目标全部完成。

**展开：** “没有水杯”“库存不足”“只读 Agent 不能下单”都可以是 `success=True`。更准确的 slide 文案是 `60/60 runs completed without protocol or orchestration failure`，而不是 100% task fulfillment。

## Q36. 空 catalog 对结果造成了什么影响？

**短答：** 它缩短了 C 的路径、阻止了 Profile 和 purchase 流程被完整执行，也让多个成功结果实际上是“无候选”的安全退出。

**展开：** B/D 获取前十个无关商品后由 LLM判断没有目标；C 在 Store Agent 端按 category 过滤，直接得到零候选。不同过滤行为也意味着三条路径没有完成完全相同的内部工作。

## Q37. 当前 latency 结果有哪些统计限制？

**短答：** 样本小、arm 工作负载不完全一致、只报告 mean、存在明显 outlier，并混合 cold-session 与提前结束条件。

**展开：** A 只有 5 次，B/D/C 各 20 次；没有置信区间；LLM latency 高波动；C 的任务被空 catalog 简化。结果适合解释实现行为，不适合宣称普遍性能排名。

## Q38. 怎样设计更公平的下一轮 latency 实验？

**短答：** 固定相同任务和候选结果，分别测 cold/warm session，分解 LLM、协议和 backend 时间，并报告分布。

**展开：** 应增加 trial 数，报告 median、p95 和置信区间；保证每个 arm 都真正走完整推荐路径；分别记录 initialize、discovery、tool/A2A、GraphQL 和每次模型调用；对提前退出任务单独分组，而不是与完整任务混算。

---

# 五、Token 与 Hop

## Q39. LLM token 一般如何测量？

**短答：** 首选模型 API 返回的实际 usage；其次用匹配模型的 tokenizer；最粗略才使用字符数除以四。

**展开：** 应分别记录 input、output、cached input 和 reasoning tokens，并报告 total、per-run mean/median 和 LLM call count。不同测量方法的数据不能当成同精度数字直接计算倍数。

## Q40. 当前项目中的 token 数是实际值还是估算值？

**短答：** B/D 是 `ceil(character_count/4)` 的估算；后续 GraphQL/A2A probe 记录了 API actual usage。

**展开：** B 约 46,227、D 约 45,304 是各自 20 runs 的累计估算。正式 A2A empty-inventory intent 的后续 actual usage 是 1,560/20，约 78 tokens/run。Direct GraphQL 无 LLM 时 token 为 0；fixed GraphQL controller 是 773/5，约 155 tokens/run。

## Q41. 为什么 MCP + Profile 少一次 reasoning round，总 token 却只比 MCP 低一点？

**短答：** D 的调用次数更少，但每次 prompt 因 Profile 更长，两个效应大部分互相抵消。

**展开：** B 有 45 次 decisions，平均约 1,027 estimated tokens/call；D 有 40 次，平均约 1,133 tokens/call。两者都在第二轮重发工具 schema、完整 history 和十个商品结果，这些共同上下文比 Profile 本身更大。

## Q42. Slide 上 GraphQL 4931 和 A2A 3412 应怎样解释？

**短答：** 它们是不同 probe suite 的累计 actual tokens，不是与 B/D 完全同条件的单一 arm 数字。

**展开：** 4931 合并了 fixed GraphQL controller、schema-guided GraphQL generation 和 minimal GraphQL generation 三组；不能标成“Direct GraphQL”。3412 合并了正式 empty-inventory intent 与额外 dog-treat positive case。正式比较应统一任务数、调用数和统计方法。

## Q43. Hop 在这个项目里是什么意思？

**短答：** 对 Arm C，hop 是一次 Butler 与 Store Agent 之间完成的 request-response round trip，不是网络路由器 hop。

**展开：** C 的两个 hops 是 Agent Card discovery 和 browse task。LLM 调用、本地 Profile、local ranking 和 Store 内部 GraphQL 不计入这个 `hops` 字段。代码在两个 A2A 请求完成后各执行一次 `hops += 1`。

## Q44. 为什么不能直接说 MCP 1 hop、A2A 2 hops？

**短答：** 因为图中的 MCP“1”其实是一次 business tool invocation，而 A2A“2”是两次协议 round trips，口径不同。

**展开：** 如果统计 cross-agent round trips，B/D 为 0、C 为 2；如果统计业务调用，B/D 各 1 个 tool call、C 为 1 个 browse task；如果统计完整协议交换，MCP 还有 initialize、initialized notification 和 `tools/list`。必须先定义边界再计数。

---

# 六、安全结果

## Q45. 安全实验主要保护哪些资产、假设哪些攻击者？

**短答：** 保护推荐完整性、价格真实性、用户预算和购买同意；攻击者可以是恶意 Store Agent，也可以是被植入后门的 Butler。

**展开：** 恶意 Store 可以控制 Agent Card 和 browse artifact；后门 Butler 可以在特定 trigger 下改变推荐或内部风险状态。Profile 留在本地减少了泄露，但不能自动解决对外部数据和本地 Agent 本身的信任问题。

## Q46. Purchase Risk 的 8/10 到底表示什么？

**短答：** 它是总体分类正确率 80%，不是“十个危险请求抓住八个”；八个危险表达中实际抓住六个，两个正常 control 也正确放行。

**展开：** 两个 false negatives 是 `dry_run_but_submit` 和 `cart_like_language`。LLM把“dry-run”“pending order”“later”解释成非立即购买。危险请求 recall 是 6/8=75%。一旦 `is_purchase=true`，本地 confirmation policy 是确定性的。

## Q47. 为什么 Fake Agent Card 能 4/4 defended？

**短答：** 因为购买风险由 Butler 本地策略决定，Store Agent 不能通过自我声明降低 confirmation gate。

**展开：** 四个 case 包含一个 honest control 和三个恶意变体：风险降为 none、删除 confirmation flag、完全省略 purchase skill。三个攻击都被阻止，所以更准确是“3/3 attacks blocked + 1 control”。这是 backend-free、model-stubbed 的确定性回归。

## Q48. 为什么 Fake Price 能 1/1 defended？

**短答：** 测试把所有价格改成 €0.01，而本地规则拒绝低于 €1 的价格并执行 €80 预算检查，所以没有候选进入排序。

**展开：** 系统选择“拒绝推荐”，而不是相信异常低价。这个 100% 只覆盖一个固定攻击样例；看起来合理但仍然伪造的价格可能绕过固定 floor。未来需要可信来源重新获取价格，而不只依赖阈值。

## Q49. Backdoor 的 2/4 应怎样正确解释？

**短答：** 不能解释为“2/4 被阻止”。四个 case 中一个是 benign control，三个是真实攻击；query 和 observation 两个攻击被价格/预算 guardrail 间接挡住，thought attack 成功。

**展开：** 正确的防御结果是 2/3 attacks blocked，1/3 stealth attack succeeded。原 JSON 的 `passed=2/4` 表示“行为符合该回归的预期”：benign case 保持 dormant，thought attack 被成功复现。Thought attack 将 `risk.user_confirmed` 伪造为 true，同时保持最终推荐不变，因此暴露了确认状态缺少可信 provenance 的问题。该测试通过 subclass 模拟 runtime 后门行为，并非训练了被投毒模型。

## Q50. 综合来看，系统安全结论和下一步是什么？

**短答：** 本地确定性 guardrail 对已知结构化攻击有效，但语义分类、可信价格和内部确认状态仍是主要风险；下一步应把“信任”变成可验证机制。

**展开：** 优先事项包括：

1. 用规则与模型组合识别所有有副作用的语言，包括 dry-run、pending order 和 delayed action。
2. 通过可信 catalog/MCP `get_product` 带外重新获取价格，并记录 price provenance。
3. 让 `user_confirmed` 绑定真实用户事件、签名或不可伪造的 confirmation token。
4. 为 MCP tool calls 增加 authentication、authorization、rate limit 和审计。
5. 使用 actual API token usage，统一任务与样本数，报告 latency/token 分布而非只报平均值。
6. 增加 plausible-price、adaptive attacker、真实候选商品、warm-session 和完整 purchase workflow 测试。

---

# 数字速记卡

| 指标 | 数值 | 正确解释 |
| --- | ---: | --- |
| Direct GraphQL baseline | 182.94 ms, 5 runs | 无 LLM、固定 query 的 reference floor |
| Deterministic MCP baseline | 340.65 ms, 5 runs | fresh session + discovery + 两个固定 tool calls |
| Arm B MCP Agent | 5175.50 ms, 20 runs | 45 次 LLM decisions；约 94% 时间来自模型 |
| Arm D MCP+Profile | 4142.91 ms, 20 runs | 40 次 decisions；mean 受 B 的额外步骤/outlier 影响 |
| Arm C A2A | 1447.65 ms, 20 runs | 全部正式 runs 因空 catalog 提前结束 |
| Agent runs completed | 60/60 | 无协议/orchestration failure，不等于目标完成 |
| B token | ~46,227 estimated / 20 | ~2,311/run；字符数/4 |
| D token | ~45,304 estimated / 20 | ~2,265/run；字符数/4 |
| Formal C token probe | 1,560 actual / 20 | ~78/run；仅 intent，空 catalog early stop |
| Purchase intent | 8/10 overall | 6/8 risky caught + 2/2 controls correct |
| Malicious card | 4/4 regression | 3/3 attacks blocked + 1 control |
| Fake price | 1/1 blocked | 单一 €0.01 确定性样例 |
| Backdoor | 2/3 attacks blocked | thought attack 仍成功；不是“2/4 blocked” |

# 关键证据文件

- `README.md`
- `internal/mcpserver/server.go`
- `internal/a2aserver/server.go`
- `internal/catalog/service.go`
- `scripts/agent_gcp_baseline_test.py`
- `scripts/agent_mcp_loop.py`
- `scripts/agent_a2a_loop.py`
- `scripts/run_experiment.sh`
- `eval/full-abcd-c2-20260702/a_baseline/direct_graphql_A.json`
- `eval/full-abcd-c2-20260702/bdc/summary.csv`
- `eval/full-abcd-c2-20260702/c2/risk_regression_live.json`
- `eval/full-abcd-c2-20260702/c2/card_regression.json`
- `eval/full-abcd-c2-20260702/c2/price_regression.json`
- `eval/full-abcd-c2-20260702/c2/backdoor_regression.json`
- `eval/full-abcd-c2-20260702/token_estimate/token_estimate_summary.json`
- `eval/llm-token-retest-20260710-020345/summary.json`
