# A2A 互操作性实验 — 设计、代码计划与接口规范

> 状态:设计提案(尚未实现)
> 范围:在现有 MiSArch MCP 网关上扩展第三条架构 arm,做 A/B/C 三路对比。
> **不修改**现有 Arm A / Arm B 的代码路径。

---

## 1. 研究问题

> 在"帮我挑一个适合我的水杯"这类**个性化推荐**任务上,随着架构从单 agent 走向
> 多 agent A2A 编排,**延迟代价**与**互操作性 / 数据主权收益**之间的 trade-off
> 是什么?

核心立场:A2A 的冗余(多一层翻译、多一跳网络)**不是**设计失误,而是为
**可组合性**和**数据主权**付出的代价。这条 trade-off 曲线本身就是研究结论。

---

## 2. 最终架构(用户管家模型)

```
用户
 | 自然语言
+------------- 用户信任域 --------------+
|  用户管家 agent  (scripts/agent_a2a_loop) |
|   - 偏好模块(内部,非 A2A)          |  <- profile 是内部模块
|   - 读商家 Agent Card                 |
|   - 风险确认(拦截高风险动作)        |
+----------------------+----------------+
                       | A2A   <- 唯一真正的信任边界
                       |        发送:任务 + 最小化约束(不含原始 profile)
                       |        返回:未排序的候选商品
+----------------------+----- 商家信任域 -----+
|  store-agent  (internal/a2aserver)          |
|   skills: browse / purchase  (+ 风险元数据) |  <- 一个 agent,两个 skill
|   - 永不接触用户 profile(黑盒)            |
|   - 内部用 Go 调现有 catalog.Service /      |
|     order.Service,它们走 GraphQL            |
+----------------------+----------------------+
                       | (复用现有代码)
                  MiSArch GraphQL
```

### 关键决策

| 决策 | 结论 | 理由 |
|------|------|------|
| profile 放哪 | 用户侧 | 数据主权:偏好属于用户,不被平台锁住 |
| profile 独立成 agent 吗 | 否,合并进管家 | 用户侧内部无信任边界,硬叫 A2A 是摆拍 |
| 商家侧拆 browse/purchase agent 吗 | 否,一个 agent 两个 skill | 同一信任域,拆开徒增耦合、无 A2A 价值 |
| 风险分级放哪 | Agent Card 的 skill 元数据 + 用户侧确认 | 确认责任在用户侧(用户的钱用户决定) |
| 偏好排序在哪做 | 用户侧——管家在本地对候选排序 | 数据主权:store-agent 只返回候选,原始 profile 不跨界 |
| 什么东西跨 A2A 边界 | 任务 + 最小化白名单约束,记入 `profile_fields_disclosed` | 最小披露让 store-agent 保持黑盒,并把数据主权变成可度量的量 |

整个架构里只有**一条**真正的 A2A 边界:`用户管家 <-> store-agent`。其余都是
进程内调用。

**最小披露原则。** 跨这条唯一边界,管家只发送「任务 + 最小化、显式白名单的约束」,
绝不发送原始 profile。候选商品以未排序的形式返回,管家在本地用完整 profile 排序,
profile 始终留在用户信任域内。任何确实跨界的字段都被记入 `profile_fields_disclosed`——
因此数据主权不只是口头声称,而是可被度量的;store-agent 始终是一个看不到用户口味模型的黑盒。

---

## 3. 实验对比设计(四 Arm)

| Arm | 名称 | 架构 | 偏好来源 | 代码 |
|-----|------|------|---------|------|
| **A** | Direct GraphQL | Agent -> GraphQL | prompt 硬编码 | 已有 `scripts/agent_gcp_baseline_test.py` |
| **B** | Single MCP | Agent -> MCP -> GraphQL | prompt 硬编码 | 已有 `scripts/agent_mcp_loop.py` |
| **D** | MCP + 结构化 profile(控制组) | Agent -> MCP -> GraphQL | 喂给 LLM 的结构化 profile JSON | 已有 `scripts/agent_mcp_loop.py` + 新增 `--profile` 参数 |
| **C** | Multi-agent A2A | 管家 -> A2A -> store-agent -> GraphQL | 用户侧偏好模块 | 新建 `scripts/agent_a2a_loop.py` |

Arm D 是插在 B 与 C **之间**的控制组:MCP 路径与 B 完全相同,但给 LLM 喂**同一份**
Arm C 存在用户侧的结构化 profile JSON。它把 B -> C 这一跳拆成两个干净的单变量对比:

| 比较 | 隔离的变量 |
|------|-----------|
| A vs B | 协议(GraphQL vs MCP) |
| B vs D | 偏好格式(硬编码 prompt vs 结构化 JSON) |
| D vs C | 架构(单 agent MCP vs 多 agent A2A) |

> **混淆变量已被控制。** 没有 Arm D 时,B -> C 会一次改两个变量(架构层数 *和* 偏好
> 格式)。Arm D 让偏好格式在 D 与 C 之间保持固定,于是 D -> C 干净地隔离出架构变量。
> 代价是多跑一组实验 + 给 `agent_mcp_loop.py` 加一个 `--profile` 参数——实现量小,
> 论证增益大。

### 测量指标

| 指标 | Schema 字段名 | 含义 | 预期方向 |
|------|-------------|------|---------|
| 端到端延迟 | `duration_ms` | 全程毫秒数 | A < B < C |
| A2A 跳数 | `hops` | A2A 往返次数 | A=0, B=0, C>=1 |
| 偏好采纳 | `preference_used` | 偏好是否被采纳(LLM-judge / 人工) | C 最高 |
| 偏好披露量 | `profile_fields_disclosed` | 跨 A2A 边界的 profile 字段(列表;画图用计数) | A、B:实际上全披露(偏好被烤进发往后端的查询);C:最小化且有日志,常为空 |
| 推荐相关度 | 事后 LLM-judge,不写入运行 schema | 推荐与偏好匹配度,1-5 | C >= D >= B ~= A |
| 风险拦截 | `risk` 对象(4 个布尔,见下) | 风险检测 + 确认 + 是否真的发出了 purchase Task | C 可靠/可审计;A、B、D 靠 LLM 自觉,记为 `null`(N/A) |
| 任务成功 | `success` | 任务是否完成 | — |

`N = 5` trials 每任务,沿用现有 trial 框架。

单个 `risk_intercepted` 布尔被替换为结构化的 `risk` 对象,以便区分"不适用"与
"该拦截却没拦截":

```json
"risk": {
  "detected": true,              // store-agent Card 里 risk_level != "none"
  "confirmation_required": true, // 命中的 skill 的 requires_confirmation == true
  "user_confirmed": null,        // null = N/A(非 purchase 任务);问过之后为 true/false
  "purchase_task_sent": false    // 管家是否真的发出了 purchase Task?
}
```

`null` 代表**不适用**(如纯 browse 任务根本走不到确认环节);`false` 代表
**应该发生却没有**。两者语义不同,绝不可混为一谈。A/B/D 没有 Agent Card、也没有
结构化风险元数据,因此整块 `risk` 设为 `null`——可视化时标注"N/A",而不是补 `false`
让图看起来像失败。

只有 Arm C 产出 `hops`、`profile_fields_disclosed` 和非空的 `risk` 块。合并数据
做可视化时,对 Arm A/B/D 补 `hops=0`、`risk=null`,并把它们的披露按"全披露"
作图(偏好被烤进发往后端的查询/prompt),而非字面的 `[]`。

`answer_relevance`(推荐相关度)是事后由 LLM judge 对 `answer` 字段打分,
**不**写入运行输出文件本身。

### 测试任务集

| 任务 | 测什么 |
|------|--------|
| "帮我挑一个水杯" | 有明确偏好被采纳 |
| "帮我挑一个水杯,要便宜的" | 任务覆盖偏好(软约束) |
| "帮我挑一个帐篷" | 偏好跨品类迁移 |
| "帮我下单买这个水杯" | 触发 `purchase` skill;测风险拦截(Phase 1:只测拦截,不真下单——见 §4.2) |

---

## 4. 各组件代码计划

### 4.1 `data/user_profile.json`(新增)

用户自有的偏好存储。位于用户侧,由管家的偏好模块读取。

```json
{
  "users": {
    "demo-user": {
      "categories": {
        "cup":  { "material": "stainless steel", "min_capacity_ml": 500, "price_sensitivity": "medium" },
        "tent": { "weight_preference": "light", "price_sensitivity": "low" }
      },
      "global": { "currency": "EUR", "max_single_item_cents": 8000 }
    }
  }
}
```

### 4.2 `internal/a2aserver/`(新增 — 商家 store-agent)

在**现有的** `catalog.Service` 和 `order.Service` 外面套一层薄薄的 A2A 壳。
现有服务**不改动**。

#### Wire format 说明

本实验实现的是一个 **A2A 架构模式的简化子集**,而非完整的 A2A 规范
(完整规范使用 JSON-RPC 2.0 的 `message/send`、`tasks/get` 等方法,
Agent Card 字段名也不同)。此处选用更简单的 REST 风格 `POST /tasks`
是课程项目范围内的合理取舍。

因此本实验验证的是 **A2A 架构模式的代价与收益**(独立信任域、Agent Card
能力发现、显式风险元数据),而**不是 wire 层面的协议兼容性**。
这一范围限制应在论文 limitation 部分明确说明。

#### `internal/a2aserver/types.go` — 协议结构体

```go
package a2aserver

// AgentCard 在 /.well-known/agent-card.json 暴露
type AgentCard struct {
    Name         string  `json:"name"`
    Version      string  `json:"version"`
    Description  string  `json:"description"`
    Endpoint     string  `json:"endpoint"`     // POST /tasks 的基址
    Skills       []Skill `json:"skills"`
    Capabilities struct {
        Streaming bool `json:"streaming"` // 暂为 false
    } `json:"capabilities"`
    Auth struct {
        Schemes []string `json:"schemes"` // demo 用 ["none"],或 ["oauth2"]
    } `json:"auth"`
}

// Skill 是带显式风险元数据的粗粒度能力。
type Skill struct {
    ID                   string `json:"id"`          // "browse" | "purchase"
    Description          string `json:"description"`
    RiskLevel            string `json:"risk_level"`  // "none" | "low" | "medium" | "high"
    SideEffects          bool   `json:"side_effects"`
    RequiresConfirmation bool   `json:"requires_confirmation"`
}

// TaskRequest 是 POST /tasks 的请求体。
type TaskRequest struct {
    TaskID string         `json:"task_id"`
    Skill  string         `json:"skill"`  // 必须匹配某个 Skill.ID
    Input  map[string]any `json:"input"`  // skill 相关载荷(见下表)
}

// TaskState 对齐 A2A 生命周期(最小子集)。
type TaskState string

const (
    StateWorking       TaskState = "working"
    StateInputRequired TaskState = "input-required"
    StateCompleted     TaskState = "completed"
    StateFailed        TaskState = "failed"
)

// TaskResponse 是 POST /tasks 的返回。
type TaskResponse struct {
    TaskID   string         `json:"task_id"`
    State    TaskState      `json:"state"`
    Message  string         `json:"message,omitempty"`  // 给人看的说明
    Artifact map[string]any `json:"artifact,omitempty"` // 最终产出
    Error    string         `json:"error,omitempty"`
}
```

#### `internal/a2aserver/server.go` — handler

```go
package a2aserver

type Service interface {
    ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error)
    GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error)
    CreatePendingOrder(ctx context.Context, in order.CreatePendingOrderInput) (order.CreatePendingOrderOutput, error)
}

// NewHandler 返回一个 http.Handler,暴露:
//   GET  /.well-known/agent-card.json
//   POST /tasks
func NewHandler(svc Service, card AgentCard) http.Handler
```

#### `POST /tasks` 分派逻辑与过滤说明

| `skill` | Input 字段 | 处理逻辑 | Artifact |
|---------|-----------|---------|---------|
| `browse` | `top_k`(int);`query`(string,任务派生词,如 "cup");`constraints`(object,可选,仅最小化白名单硬约束) | 调用 `ListProducts(ctx, top_k)`,把商品作为**未排序候选**返回。store-agent 永不接收用户 profile、也不按口味排序;反正 `catalog.Service.ListProducts` 只接受 `topK`。**偏好排序在候选返回后由管家本地完成**(见 §4.3)。`query` 派生自用户本就对商家说出口的词,而非私有 profile。 | `artifact.products=[...]`(未排序候选) |
| `purchase` | 对应 `order.CreatePendingOrderInput` 的字段(6 个 UUID) | **Phase 1(只测拦截):** 校验所有必填字段是否齐全;若有缺失,返回 `state=input-required` 并在 message 中列出缺失字段——**不创建任何订单**。**Phase 2(以后):** 用 fixtures / 预查到的 UUID 调用 `CreatePendingOrder`(仍是 *pending* 订单,不触发支付)。 | Phase 1:`state=input-required`、`message="需提供 variant_id/address_id/..."`。Phase 2:`artifact.order={...}` |

> **最小披露。** `browse` Task 只携带任务派生的 `query`,以及可选的显式白名单
> `constraints` 子集——绝不含原始 profile。管家把每个跨界字段记入
> `profile_fields_disclosed`。因此 store-agent 在边界两侧都是黑盒:管家只看到
> Agent Card + 候选列表;store-agent 只看到任务 + 最小化约束,永远看不到用户口味模型。

> store-agent **不**自己弹确认提示。它在 Agent Card 里为 `purchase` 声明
> `requires_confirmation: true`。管家在发出 purchase Task 之前读到这个标志,
> 强制执行用户确认。确认责任始终留在用户侧。

> **purchase 分两阶段。** `order.CreatePendingOrderInput` 需要 6 个 UUID,真下单
> 要么 fixtures 要么先查。Phase 1 先落地,只验证风险拦截路径:管家看到
> `requires_confirmation: true`,记 `risk.purchase_task_sent = false` 即停——
> 足以测量风险拦截,不需要真的创建订单。Phase 2(用预置 UUID 真正创建 pending
> 订单)推迟。

#### `cmd/server/main.go` — 装配(仅新增,不破坏现有)

需新增环境变量 `PUBLIC_BASE_URL`(如 `http://34.40.117.201:8001`)用于填充
`AgentCard.Endpoint`。若未设置,从 `HTTP_ADDR` 推导。
需在 `internal/config/config.go` 中小幅新增:

```go
// Config struct 中新增:
PublicBaseURL string

// Load() 中新增:
cfg.PublicBaseURL = envOrDefault("PUBLIC_BASE_URL", "http://"+cfg.HTTPAddr)
```

`main.go` 装配:

```go
storeCard := a2aserver.DefaultCard(cfg.PublicBaseURL)
a2aHandler := a2aserver.NewHandler(storeAdapter, storeCard)
// storeAdapter 把 catalogService + orderService 打包到 Service 接口
```

`internal/httpserver/server.go` 扩展 `NewHandler` 签名以接收 a2aHandler。
注意:`graphQLClient` 目前以 `ReadinessChecker` 身份传入(不是普通 client),
扩展后签名为:

```go
func NewHandler(mcpHandler http.Handler, a2aHandler http.Handler, checker ReadinessChecker) http.Handler

// 新增路由:
mux.Handle("GET /.well-known/agent-card.json", a2aHandler)
mux.Handle("POST /tasks", a2aHandler)
```

### 4.3 `scripts/agent_a2a_loop.py`(新增 — 用户管家 / Arm C)

Arm C 的结果 schema 是 Arm A/B schema 的**超集**;A/B 没有的字段需在可视化时
补默认值(见 §4.4)。

```python
class A2AClient:
    """最小 A2A 客户端:读 Agent Card + POST tasks。"""
    def __init__(self, base_url: str): ...
    def fetch_card(self) -> dict: ...                        # GET /.well-known/agent-card.json
    def send_task(self, skill: str, payload: dict) -> dict:  # POST /tasks -> TaskResponse
        ...

class PreferenceModule:
    """用户侧,进程内。非 A2A。读 data/user_profile.json。
    完整 profile 只在本地使用,绝不交给 A2A 客户端。"""
    def __init__(self, profile_path: str, user_id: str): ...
    def for_category(self, category: str) -> dict: ...        # 完整 profile(仅本地使用)
    def minimal_constraints(self, task: str, category: str) -> tuple[dict, list[str]]:
        ...   # -> (要披露的白名单硬约束, 被披露的字段名列表)
    def rank(self, candidates: list[dict], category: str) -> list[dict]:
        ...   # 用完整 profile 在本地排序;profile 不离开进程

class UserButler:
    def __init__(self, model: ResponsesModel, a2a: A2AClient, prefs: PreferenceModule): ...
    def run(self, task: str) -> dict:
        # 1. LLM 推断商品品类 + 是否为写/购买意图
        # 2. a2a.fetch_card()              -> 发现 skill + 风险元数据
        # 3. constraints, disclosed = prefs.minimal_constraints(task, category)
        #       -> 只有白名单硬约束可跨界;disclosed 记为 profile_fields_disclosed(常为空)
        # 4. a2a.send_task("browse", {"top_k": 10, "query": <任务派生>,
        #                             "constraints": constraints})
        #       -> store-agent 返回候选商品(无 profile、无口味)
        # 5. ranked = prefs.rank(candidates, category)
        #       -> 用完整 profile 在本地排序;profile 不离开用户侧
        # 6. risk = {detected, confirmation_required, user_confirmed, purchase_task_sent}
        #       若 purchase 意图 且 card skill.requires_confirmation == true:
        #          risk.detected = risk.confirmation_required = True
        #          等待显式确认;未确认则 purchase_task_sent 保持 False
        #          (Phase 1 到此为止——见 §4.2)
        #       非 purchase 任务 -> user_confirmed 保持 null(N/A)
        # 7. LLM 产出最终推荐,引用(本地应用的)偏好说明理由
        # 记录 duration_ms、hops、preference_used、profile_fields_disclosed、
        #      risk{detected, confirmation_required, user_confirmed, purchase_task_sent}
        ...
```

Arm C 结果 schema:

```json
{
  "success": true,
  "arm": "a2a",
  "task": "...",
  "answer": "...",
  "steps": 3,
  "hops": 2,
  "duration_ms": 0.0,
  "preference_used": true,
  "profile_fields_disclosed": [],
  "risk": {
    "detected": false,
    "confirmation_required": false,
    "user_confirmed": null,
    "purchase_task_sent": false
  },
  "trace": [
    { "event": "fetch_card", "duration_ms": 12.3 },
    { "event": "browse_task", "duration_ms": 340.1 }
  ]
}
```

Arm A/B 现有 schema(供参考):

```json
{ "success": true, "task": "...", "answer": "...", "steps": 2, "duration_ms": 0.0, "trace": [...] }
```

CLI:

```
python -m scripts.agent_a2a_loop \
  --task "帮我挑一个水杯" \
  --a2a-url http://<host>:8001 \
  --user-id demo-user \
  --profile data/user_profile.json \
  --output eval/a2a_trial.json
```

### 4.4 `scripts/visualize_agent_baselines.py`(修改)

加载四路结果时,对 A/B/D 缺失的字段补默认值:

```python
def normalise(result: dict) -> dict:
    result.setdefault("arm", "unknown")
    result.setdefault("hops", 0)
    result.setdefault("preference_used", False)
    result.setdefault("profile_fields_disclosed", [])   # A/B/D 按"全披露"作图
    result.setdefault("risk", None)                     # None = N/A;绝不强转成 False
    return result
```

新增输出:
- 延迟对比柱状图(A / B / D / C,使用 `duration_ms`)
- 偏好采纳率(B vs D vs C,使用 `preference_used`)——B 硬编码、D MCP 内结构化、C 用户侧
- 数据披露对比:跨信任边界的 profile 字段数(A/B/D = 全披露 vs C,使用
  `profile_fields_disclosed`)——可视化数据主权收益的那张图
- trade-off 散点:`duration_ms` vs `answer_relevance`(事后 judge 分)
- 风险拦截可靠性(使用 `risk` 块;A/B/D 渲染为 N/A,只有 C 产出真实的拦截记录)

---

## 5. 接口契约总览

| 边界 | 协议 | 接口面 |
|------|------|--------|
| 用户 -> 管家 | 自然语言(CLI `--task`) | — |
| 管家 -> 偏好模块 | 进程内 Python 调用 | `PreferenceModule.for_category(category)` |
| 管家 -> store-agent | **HTTP 上的简化 A2A** | `GET /.well-known/agent-card.json`, `POST /tasks`(仅任务 + 最小化约束) |
| store-agent -> MiSArch | Go 调用 -> GraphQL | 现有 `catalog.Service` / `order.Service`(不改动) |

唯一联网、跨信任域的契约就是那条 A2A 边界(Agent Card + Task)。
store-agent 内部对 GraphQL 的使用对管家是不透明的——这就是
"A2A 在外、GraphQL 在内"分层在协议边界上的体现。

两个方向上披露都保持最小:`browse` Task 跨界时只带任务派生的 query 与最小化白名单约束,
而用户 profile 与最终排序永不离开用户信任域。`profile_fields_disclosed` 精确记录到底
有什么(如果有的话)离开了——使 store-agent 成为真正的黑盒,数据主权可审计而非仅靠声称。

---

## 6. 阶段与工作量

| Phase | 内容 | 难度 | 估时 |
|-------|------|------|------|
| 1 | `data/user_profile.json` | 低 | 0.5d |
| 2 | `internal/config`:新增 `PUBLIC_BASE_URL` 字段 | 低 | 含在 P3 |
| 3 | `internal/a2aserver/{server,types}.go`(复用 catalog/order;壳层内存过滤) | 低 | 0.5d |
| 4 | `internal/httpserver`:扩展 `NewHandler` 签名;挂载 A2A 路由 | 低 | 含在 P3 |
| 5 | `scripts/agent_a2a_loop.py`(管家 + 偏好 + card + 风险确认 + LLM 排序) | 中 | 1d |
| 6 | Arm D 控制组:给 `agent_mcp_loop.py` 加可选 `--profile` 参数(把结构化 profile JSON 喂给 LLM;MCP 路径不变) | 低 | 0.5d |
| 7 | 跑实验(4 arm)、收数据 | 低 | 0.5d |
| 8 | 扩展 `visualize_agent_baselines.py`(4 arm;补默认字段;`risk=null` → N/A) | 低 | 0.5d |

**总计约 3.5 天**,全部新增;Arm A 行为不变,Arm B 默认行为不变(Arm D 只是同一脚本上的可选 `--profile` 参数)。

---

## 7. 已知局限性

1. **本地排序是设计而非将就**:`catalog.Service.ListProducts` 只接受 `topK`、
   没有偏好过滤参数——这与数据主权设计一致:store-agent 返回未排序候选,
   管家在本地用完整 profile 排序。代价是每次 browse 管家要拉回最多 `topK` 个候选
   (跨边界多几 KB),而非服务端过滤后的短名单;收益是 profile 永不跨信任边界。
   这个 trade-off 被显式化,并通过 `profile_fields_disclosed` 记录。

2. **简化的 A2A wire format**:本实验用 REST 风格 `POST /tasks`,
   而非完整 A2A 规范(JSON-RPC 2.0)。验证的是 **A2A 架构模式**的代价/收益,
   不是与生产级 A2A agent 的 wire 层兼容性。

3. **混淆变量由 Arm D 控制**:单看 B -> C 会同时改变架构与偏好格式两个变量。
   插入 Arm D(MCP + 结构化 profile)作为控制组后,B -> D 隔离偏好格式、
   D -> C 隔离架构。残留 caveat:D 通过 prompt 喂 profile,而 C 把 profile 放在
   用户侧模块并走最小披露,所以 D -> C 仍把"架构"与"profile 放哪"捆在一起——
   可接受,因为这两点本就是 A2A arm 的定义性特征。

4. **Schema 不对称**:A/B/D 缺少 `hops`、`profile_fields_disclosed` 和 `risk` 块
   (只有 Arm C 产出)。可视化默认 `hops=0`、`risk=null`;`null`("不适用")
   必须与 `false`("该拦截却没拦截")渲染区分,A/B/D 的披露按"全披露"作图而非 `[]`。

5. **purchase 仅测拦截(Phase 1)**:`purchase` skill 当前只校验字段并返回
   `input-required`,不真正创建 pending 订单(那需要 6 个预置 UUID)。这足以测量
   风险拦截;用 fixtures 真下单的 Phase 2 推迟。

---

## 8. 论文 / 答辩论点(一句话)

> 我们用同一个个性化购物任务,对比四条 arm:裸 GraphQL、单 MCP、
> 喂结构化 profile 的 MCP(控制组)、多 agent A2A。
> A2A 在延迟上最贵,但换来三样东西:偏好的数据主权(存在并排序于用户侧、
> 永不披露给商家、并由 `profile_fields_disclosed` 度量)、基于 Agent Card 的
> 能力发现、以及可审计的风险确认责任链。通用性不是出发点,
> 而是分层后的结果。
