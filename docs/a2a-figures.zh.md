# 四臂对比

| 臂 | 名字 | 路径 | 偏好来源 |
|----|------|------|----------|
| **A** | 直连 GraphQL | Agent → GraphQL | prompt 硬编码 |
| **B** | 单一 MCP | Agent → MCP → GraphQL | prompt 硬编码 |
| **D** | MCP + 结构化 profile（对照组） | Agent → MCP → GraphQL | 结构化 JSON → LLM |
| **C** | 多 Agent A2A | butler → A2A → store-agent → GraphQL | 用户侧模块（本地） |

| 对比 | 被隔离的单一变量 |
|------|------------------|
| A vs B | 协议（GraphQL vs MCP） |
| B vs D | 偏好格式（prompt vs 结构化 JSON） |
| D vs C | 架构（单 Agent vs 多 Agent A2A） |

# 架构 · 唯一的 A2A 信任边界

```mermaid title="架构 · 唯一的 A2A 信任边界" page=landscape
flowchart LR
  subgraph USER["用户信任域"]
    PROFILE["user_profile.json<br/>(材质, 预算 80€)<br/>仅本地 · 绝不跨界"]
    BUTLER["butler 管家 Agent<br/>agent_a2a_loop.py"]
    RANK["PreferenceModule.rank()<br/>本地排序"]
    PROFILE --> BUTLER --> RANK
  end
  subgraph MERCHANT["商家信任域 (可能恶意)"]
    STORE["store-agent 店员<br/>internal/a2aserver"]
    GRAPHQL[("MiSArch<br/>GraphQL 后端")]
    STORE --> GRAPHQL
  end
  BUTLER == "A2A 边界" ==> STORE
  STORE -. "① Agent Card (能力 + 风险)" .-> BUTLER
  STORE -. "② POST /tasks → 候选商品" .-> RANK
```

# 攻击流程 A · 价格投毒 → 排序劫持

```mermaid title="攻击流程 A · 价格投毒 → 排序劫持"
flowchart TD
  A["butler 推断类别 'cup'"] --> B["① 读 Agent Card"]
  B --> C{"名片诚实?"}
  C -->|"是 · browse = 无风险"| D["② POST /tasks browse"]
  D --> E["store 对抗模式:<br/>每个价格改写成 1 分<br/>(server.go:177-181)"]
  E --> F["rank(): 两个不锈钢杯打平<br/>价格信号被抹掉"]
  F --> G["sorted() 稳定排序<br/>→ 保留商家列表顺序"]
  G --> H["诱饵(列在第一) → 排第 1"]
  H --> I["推荐诱饵 ·<br/>报价 €0.01 (真实 €150) ·<br/>预算 €80 被击穿"]
```

# 攻击流程 B · 名片风险降级 → 护栏失效

```mermaid title="攻击流程 B · 名片风险降级 → 护栏失效"
flowchart TD
  A["攻击者提供一张<br/>对自己 purchase 技能撒谎的名片"] --> B{"butler 读取<br/>声明的元数据"}
  B -->|"risk_level: high → none"| C["护栏: '未检测到风险'"]
  B -->|"requires_confirmation: false"| C
  B -->|"purchase 技能被省略<br/>→ 默认 none"| C
  C --> D["确认护栏从不触发"]
  D --> E["有副作用的下单<br/>在确认缺席下直接执行"]
```
</content>
