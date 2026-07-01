# A2A 新特性学习文档

这份文档按“先能看懂，再能测试，再能改代码”的顺序写。你不需要先懂所有术语，先抓主线就行。

## 1. 这个特性有没有用 React?

没有。

当前仓库没有 React 前端代码，也没有常见的前端工程文件，比如:

- `package.json`
- `vite.config.*`
- `*.tsx`
- `*.jsx`
- `React`
- `useState`
- `createRoot`

这个项目现在主要是:

- Go 后端: 提供 MCP、A2A、健康检查等 HTTP 接口
- Python 脚本: 跑实验、模拟用户侧 agent
- Markdown 文档: 记录实验设计和部署说明

所以学习这个新特性时，不用先学 React。重点是 HTTP、Go handler、A2A 思路、agent 之间怎么通信。

## 2. 一句话理解 A2A

A2A 就是 Agent-to-Agent。

在这个项目里，它的意思是:

> 用户侧 agent 不直接乱调商店系统，而是先读取商家 agent 的能力说明，然后按任务调用商家 agent。

商家 agent 会告诉别人:

- 我是谁
- 我有哪些能力
- 哪些能力有风险
- 调用我应该发到哪个 endpoint

这个能力说明叫 Agent Card。

## 3. 当前项目里有几个 agent?

可以理解成两个。

### 3.1 商家侧 store-agent

代码位置:

- `internal/a2aserver/types.go`
- `internal/a2aserver/server.go`

它是商家系统对外暴露的 agent 壳。它不负责复杂思考，主要负责:

- 暴露 Agent Card
- 接收 task
- 根据 skill 调用已有的 catalog/order 能力
- 告诉用户侧哪些操作有风险

它更像一个“商店能力代理层”。

### 3.2 用户侧 butler agent

代码位置:

- `scripts/agent_a2a_loop.py`

它更像真正会“做决定”的 agent。它负责:

- 理解用户要买什么
- 读取商家的 Agent Card
- 调用商家的 browse skill
- 本地读取用户 profile
- 在用户侧排序商品
- 如果用户想下单，就根据风险信息拦截 purchase

重点: 用户 profile 不发给商家。

## 4. 两个核心接口

A2A 服务只暴露两个关键 HTTP 接口。

### 4.1 Agent Card

```text
GET /.well-known/agent-card.json
```

作用: 告诉其他 agent 我有哪些能力。

线上测试:

```bash
curl -s http://34.40.117.201:8001/.well-known/agent-card.json | python3 -m json.tool
```

你会看到类似:

```json
{
  "name": "misarch-store-agent",
  "endpoint": "http://34.40.117.201:8001",
  "skills": [
    {
      "id": "browse",
      "risk_level": "none",
      "side_effects": false,
      "requires_confirmation": false
    },
    {
      "id": "purchase",
      "risk_level": "high",
      "side_effects": true,
      "requires_confirmation": true
    }
  ]
}
```

先记住:

- `browse`: 只读，无风险
- `purchase`: 高风险，需要确认

### 4.2 Task 调用

```text
POST /tasks
```

作用: 让商家 agent 执行某个 skill。

测试 browse:

```bash
curl -s -X POST http://34.40.117.201:8001/tasks \
  -H 'content-type: application/json' \
  -d '{"task_id":"learn-browse","skill":"browse","input":{"top_k":2}}' \
  | python3 -m json.tool
```

测试 purchase 风险拦截:

```bash
curl -s -X POST http://34.40.117.201:8001/tasks \
  -H 'content-type: application/json' \
  -d '{"task_id":"learn-purchase","skill":"purchase","input":{"user_id":"demo"}}' \
  | python3 -m json.tool
```

当前 purchase 是 Phase 1，只做拦截和字段检查，不会创建真实订单。

## 5. 请求链路怎么走?

用户想买东西时，完整链路可以这样理解:

```text
用户输入
  |
  v
用户侧 butler agent
  |
  | 1. GET /.well-known/agent-card.json
  v
商家 store-agent 返回能力说明
  |
  | 2. POST /tasks, skill=browse
  v
商家 store-agent 返回候选商品
  |
  v
用户侧 butler agent 本地读取 profile 并排序
  |
  v
如果只是浏览: 返回推荐
如果是下单: 看 purchase 是否 high risk，需要确认则拦截
```

最重要的设计点:

- 商家只知道任务和少量参数
- 用户偏好 profile 留在用户侧
- 风险判断来自 Agent Card
- 下单这种高风险动作不能偷偷执行

## 6. Go 代码从哪里看?

建议按这个顺序看。

### 第一步: 看协议结构

文件:

```text
internal/a2aserver/types.go
```

重点看:

- `AgentCard`
- `Skill`
- `TaskRequest`
- `TaskResponse`
- `TaskState`

这些结构决定了 HTTP JSON 长什么样。

### 第二步: 看 Agent Card 怎么生成

文件:

```text
internal/a2aserver/server.go
```

重点函数:

```go
func DefaultCard(baseURL string) AgentCard
```

这里定义了两个 skill:

- `browse`
- `purchase`

也在这里定义了它们的风险等级。

### 第三步: 看 task 怎么分发

重点函数:

```go
func handleTasks(svc Service) http.HandlerFunc
```

它会根据请求里的 `skill` 分发:

```text
skill=browse    -> handleBrowse
skill=purchase  -> handlePurchase
其他 skill       -> failed
```

### 第四步: 看 browse

重点函数:

```go
func handleBrowse(ctx context.Context, svc Service, req TaskRequest) TaskResponse
```

它会调用已有的 catalog 服务:

- 如果传了 `product_id`，查单个商品
- 否则按 `top_k` 返回商品列表

注意: 它返回的是未排序候选商品。偏好排序不在商家侧做。

### 第五步: 看 purchase

重点函数:

```go
func handlePurchase(req TaskRequest) TaskResponse
```

当前逻辑:

- 检查下单需要的字段是否齐全
- 缺字段就返回 `input-required`
- 字段齐全也只是 dry-run
- 不会调用 `CreatePendingOrder`
- 不会产生真实订单

这就是风险拦截实验。

## 7. Python 用户侧 agent 从哪里看?

文件:

```text
scripts/agent_a2a_loop.py
```

建议按这个顺序看。

### 第一步: A2AClient

```python
class A2AClient
```

它只有两个动作:

- `fetch_card()`: 读取 Agent Card
- `send_task()`: POST `/tasks`

### 第二步: PreferenceModule

```python
class PreferenceModule
```

它负责用户偏好。

重点:

- 用户 profile 只在本地读
- `minimal_constraints()` 默认不披露任何 profile 字段
- `rank()` 在本地给候选商品排序

### 第三步: UserButler

```python
class UserButler
```

它是用户侧 agent 主逻辑。

主要流程:

1. 判断用户请求属于什么类别
2. 判断是不是下单意图
3. 读取 Agent Card
4. 发送 browse task
5. 本地排序商品
6. 如果是 purchase，检查风险并拦截
7. 输出最终结果

## 8. 和 MCP 有什么区别?

简单理解:

| 项目 | MCP | A2A |
|---|---|---|
| 面向谁 | 模型/工具调用 | agent 和 agent 通信 |
| 当前用途 | 给模型暴露工具 | 给用户侧 agent 暴露商家能力 |
| 风险信息 | 不一定显式 | Agent Card 里显式写出 |
| 用户 profile | 可能由调用方控制 | 本实验明确留在用户侧 |
| 典型接口 | `/mcp` | `/.well-known/agent-card.json`, `/tasks` |

本项目里 MCP 和 A2A 都存在，不是二选一。

## 9. 你应该怎么学习?

建议路线:

1. 先跑 Agent Card curl，确认你能看到 `browse` 和 `purchase`
2. 再跑 browse curl，确认能拿到商品
3. 再跑 purchase curl，确认它返回 `input-required`
4. 打开 `internal/a2aserver/types.go`，对照 JSON 看结构体
5. 打开 `internal/a2aserver/server.go`，看请求怎么被处理
6. 最后看 `scripts/agent_a2a_loop.py`，理解用户侧 agent 怎么串起来

不要一上来就看所有文件。先把这两个接口和两个 skill 搞懂，后面会顺很多。

## 10. 最小测试命令合集

先进入项目根目录。否则 Python 找不到 `scripts` 包:

```bash
cd /Users/wang/agent_misarch/agent_mpv_misarch
```

本地 Go 测试:

```bash
go test ./...
```

线上 Agent Card:

```bash
curl -s http://34.40.117.201:8001/.well-known/agent-card.json | python3 -m json.tool
```

线上 browse:

```bash
curl -s -X POST http://34.40.117.201:8001/tasks \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-browse","skill":"browse","input":{"top_k":2}}' \
  | python3 -m json.tool
```

线上 purchase 拦截:

```bash
curl -s -X POST http://34.40.117.201:8001/tasks \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-purchase","skill":"purchase","input":{"user_id":"demo"}}' \
  | python3 -m json.tool
```

## 11. 现在还没做什么?

当前 A2A 是实验版，不是完整生产级 A2A。

还没做的包括:

- 没有 React 页面
- 没有完整 A2A JSON-RPC 协议
- 没有 streaming
- 没有认证
- purchase 还没有真实创建 pending order
- 用户确认流程现在是实验拦截，不是交互式 UI

这不是坏事。当前目标是先验证 A2A 架构模式:

- 能发现能力
- 能跨 agent 调用
- 能最小化披露用户 profile
- 能显式识别高风险动作
- 能阻止未经确认的下单

## 12. 最后记这一句话

这个新特性不是 React 前端功能，而是一个后端 A2A 实验功能:

> 商家把能力以 Agent Card + Task API 暴露出来，用户侧 agent 读取能力、调用 browse、本地排序，并在 purchase 时根据风险元数据进行拦截。
