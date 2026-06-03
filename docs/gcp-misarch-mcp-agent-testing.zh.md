# MiSArch + MCP Gateway + Agent 测试学习文档

这份文档整理本次完整实验链路：先把 MiSArch Docker Compose 栈部署到 Google Cloud，再把本地 Go MCP gateway 部署到同一台 VM，最后用一个外部 agent smoke test 脚本验证“模型 + MCP + MiSArch GraphQL”的真实联调。

本文重点不是只给命令，而是解释每一步在系统里扮演什么角色、为什么这样部署、agent 测试应该如何设计。

## 1. 当前最终状态

本次部署完成后，系统分成三层：

```text
本机 / Codex / 测试脚本
  -> 模型接口 https://yybb.codes
  -> 云端 MCP endpoint http://34.40.117.201:8001/mcp
  -> GCP VM: misarch-agent-gateway 容器
  -> Docker 内网 http://gateway:8080/graphql
  -> GCP VM: MiSArch GraphQL Gateway
  -> MiSArch Catalog 等后端服务
```

实际资源：

| 项目 | 当前值 |
| --- | --- |
| Google Cloud project | `project-b04b8a42-0a18-46d0-bc6` |
| Zone | `europe-west3-b` |
| VM | `misarch-compose` |
| VM external IP | `34.40.117.201` |
| MiSArch cloud path | `/opt/misarch/infrastructure-docker` |
| MCP gateway cloud path | `/opt/misarch/misarch-agent-gateway-go` |
| Docker network | `infrastructure-docker_default` |
| MiSArch GraphQL, public | `http://34.40.117.201:8080/graphql` |
| MiSArch GraphQL, VM Docker 内网 | `http://gateway:8080/graphql` |
| MCP gateway, public | `http://34.40.117.201:8001/mcp` |
| MCP health | `http://34.40.117.201:8001/readyz` |

公网端口目前由 firewall rule `misarch-compose-public` 控制，只允许当前公网 IP `93.128.157.139/32` 访问：

```text
4000  MiSArch frontend
8080  MiSArch GraphQL gateway
8081  Keycloak
3001  Grafana
8001  MCP gateway
```

安全提醒：当前 MCP gateway 是实验版本，没有鉴权。只暴露给自己的 IP 是合理的；不要把 `8001` 或 `8080` 长期开放到 `0.0.0.0/0`。

## 2. 本地代码分别是什么

### 2.1 MiSArch Docker 代码

本地目录：

```bash
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker
```

作用：

- 这是 MiSArch 主系统的 Docker Compose 仓库。
- 它包含多个服务子目录，例如 `gateway`、`catalog`、`frontend`、`keycloak` 等。
- 很多服务来自 git submodule，所以刚 clone 后如果没有初始化 submodule，compose 会找不到某些文件。

曾经遇到的错误：

```text
open /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/user/docker-compose-base.yaml: no such file or directory
```

根因：

```text
仓库依赖 git submodules，但 clone 后没有执行 submodule 初始化。
```

本地修复命令：

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker
git submodule update --init --recursive
docker compose config --quiet
```

### 2.2 Go MCP gateway 代码

本地目录：

```bash
/Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
```

作用：

- 这是我们自己写的 agent-facing adapter。
- 它不是 MiSArch 原生服务，而是包在 MiSArch GraphQL 之上的 MCP server。
- 它把复杂的 GraphQL 查询包装成 agent 更容易发现和调用的 MCP tools。

关键文件：

| 文件 | 作用 |
| --- | --- |
| `cmd/server/main.go` | 程序入口：加载配置、创建 GraphQL client、catalog service、MCP server、HTTP server |
| `internal/config/config.go` | 读取 `HTTP_ADDR`、`MISARCH_GRAPHQL_URL`、`MISARCH_GRAPHQL_TIMEOUT` |
| `internal/httpserver/server.go` | 暴露 `/healthz`、`/readyz`、`/mcp` |
| `internal/misarch/client.go` | GraphQL HTTP client，负责 POST 到 MiSArch GraphQL endpoint |
| `internal/catalog/service.go` | 定义 `list_products` / `get_product` 对应的 GraphQL 查询和返回映射 |
| `internal/mcpserver/server.go` | 注册 MCP tools：`list_products`、`get_product` |
| `Dockerfile` | 构建 Linux 容器镜像 |
| `scripts/agent_gcp_smoke_test.py` | 端到端 agent smoke test，不依赖 Codex MCP 注册 |

### 2.3 Python `agent-mvp`

本地目录：

```bash
/Users/wang/Desktop/TUB2025sose/agent-mvp
```

它是另一个 demo 路线：

```text
OpenTelemetry Demo Product Catalog
  -> Python gRPC client
  -> FastAPI / MCP / chat API
```

注意：

- 它不连接当前 MiSArch。
- 它监听本机 `127.0.0.1:8000`。
- 当前 `localhost:3550` 的 OpenTelemetry Product Catalog 没有运行，所以这个 demo 的真实 catalog 当前不可用。
- 本次 GCP + MiSArch + MCP 测试使用的是 Go repo，不是这个 Python repo。

## 3. MiSArch 是如何部署到 GCP 的

### 3.1 为什么选择 Compute Engine + Docker Compose

MiSArch 上游项目已经是 Compose 结构：

```text
docker-compose.yaml
service-a/docker-compose-base.yaml
service-b/docker-compose-base.yaml
...
```

所以最小风险路线是：

```text
不要先迁移到 Kubernetes / Cloud Run
而是在 GCP Compute Engine VM 上原样运行 Docker Compose
```

优点：

- 最接近本地运行方式。
- 子模块、compose include、服务网络都能保留。
- 调试简单，直接 SSH 上 VM 看 `docker ps` / logs。

缺点：

- 运维上不如 GKE / Cloud Run 自动化。
- 单 VM 有单点故障。
- 需要自己管理 VM、firewall、磁盘和 Docker。

### 3.2 GCP 部署资产

在 MiSArch repo 中新增了这些文件：

```bash
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/gcp/deploy-compose-vm.sh
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/gcp/delete-compose-vm.sh
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/gcp/startup-script.sh
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/gcp/docker-compose.gcp.yaml
/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/docs/google-cloud-deploy.md
```

其中：

- `deploy-compose-vm.sh` 创建 VM、firewall rule，并把 startup script 传给 VM。
- `startup-script.sh` 在 VM 上安装 Docker、clone MiSArch repo、初始化 submodules、启动 compose。
- `docker-compose.gcp.yaml` 是 GCP 环境用的 compose override，主要处理 health check / 端口适配。
- `delete-compose-vm.sh` 删除本次创建的 VM 和 firewall rule。

### 3.3 部署命令

确认当前 GCP project：

```bash
gcloud config list
```

部署：

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker
PROJECT_ID=project-b04b8a42-0a18-46d0-bc6 \
ZONE=europe-west3-b \
MACHINE_TYPE=e2-standard-8 \
BOOT_DISK_SIZE=150GB \
./gcp/deploy-compose-vm.sh
```

如果 VM 已存在并希望重建：

```bash
RECREATE=1 ./gcp/deploy-compose-vm.sh
```

### 3.4 VM 上发生了什么

部署后，VM 上有：

```bash
/opt/misarch/infrastructure-docker
```

启动 compose 的核心命令：

```bash
cd /opt/misarch/infrastructure-docker
docker compose -f docker-compose.yaml -f docker-compose.gcp.yaml up -d
```

为什么多了 `docker-compose.gcp.yaml`：

- 不直接改上游 `docker-compose.yaml`。
- GCP 上某些 healthcheck 需要覆盖。
- 例如 Keycloak 镜像里缺少 `wget`，所以 healthcheck 改成 TCP 检查。
- `experiment-executor` 实际监听 `8888`，health endpoint 是 `/actuator/health`，所以也做了覆盖。

### 3.5 MiSArch 运维命令

查看 startup log：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'sudo tail -f /var/log/misarch-startup.log'
```

查看 compose 状态：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'cd /opt/misarch/infrastructure-docker && docker compose -f docker-compose.yaml -f docker-compose.gcp.yaml ps'
```

查看容器：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
```

重启 MiSArch 栈：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'cd /opt/misarch/infrastructure-docker && docker compose -f docker-compose.yaml -f docker-compose.gcp.yaml up -d'
```

测试 GraphQL：

```bash
curl -sS -X POST http://34.40.117.201:8080/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ __typename }"}'
```

期望返回：

```json
{"data":{"__typename":"Query"}}
```

## 4. MCP gateway 是如何部署到 GCP 的

### 4.1 MCP gateway 的设计目标

原始 GraphQL 的问题：

- agent 必须理解 GraphQL schema。
- agent 要自己构造 query。
- 哪些调用只读、哪些调用有副作用，不一定清楚。
- 工具发现能力弱。

MCP gateway 的目标：

```text
把 MiSArch GraphQL 能力包装成可发现、可描述、可控副作用的 agent tools。
```

当前暴露两个只读工具：

| MCP tool | 作用 | 副作用 |
| --- | --- | --- |
| `list_products` | 读取最多 10 个 MiSArch catalog 商品 | `none (read-only)` |
| `get_product` | 根据 product UUID 读取单个商品详情 | `none (read-only)` |

### 4.2 Go gateway 的运行配置

环境变量：

| 变量 | 本地默认 | GCP 当前值 | 含义 |
| --- | --- | --- | --- |
| `HTTP_ADDR` | `127.0.0.1:8001` | `:8001` | gateway 监听地址 |
| `MISARCH_GRAPHQL_URL` | `http://localhost:8080/graphql` | `http://gateway:8080/graphql` | 上游 GraphQL endpoint |
| `MISARCH_GRAPHQL_TIMEOUT` | `3s` | `3s` | 调 GraphQL 超时时间 |

为什么 GCP 上用 `http://gateway:8080/graphql`：

- `misarch-agent-gateway` 容器加入了 MiSArch 的 Docker network：`infrastructure-docker_default`。
- MiSArch GraphQL 容器在这个 network 里有别名 `gateway`。
- 这样容器之间走 VM 内部 Docker network，不需要绕公网 IP。

### 4.3 本地运行 Go gateway

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
go test ./...
HTTP_ADDR=127.0.0.1:8001 \
MISARCH_GRAPHQL_URL=http://34.40.117.201:8080/graphql \
go run ./cmd/server
```

健康检查：

```bash
curl -sS http://127.0.0.1:8001/healthz
curl -sS http://127.0.0.1:8001/readyz
```

含义：

- `/healthz` 只说明 gateway 进程活着。
- `/readyz` 会实际调用 GraphQL `{ __typename }`，所以能说明 gateway 到 MiSArch GraphQL 的链路可用。

### 4.4 上传代码到 VM

本次用 tar + gcloud scp 方式同步源码：

```bash
tar --exclude='.git' --exclude='tmp' \
  -czf /tmp/misarch-agent-gateway-go.tgz \
  -C /Users/wang/Desktop/TUB2025sose \
  misarch-agent-gateway-go

gcloud compute scp \
  --zone europe-west3-b \
  /tmp/misarch-agent-gateway-go.tgz \
  misarch-compose:/tmp/misarch-agent-gateway-go.tgz
```

VM 上解压：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command '
    set -euo pipefail
    sudo mkdir -p /opt/misarch
    sudo rm -rf /opt/misarch/misarch-agent-gateway-go
    sudo tar -xzf /tmp/misarch-agent-gateway-go.tgz -C /opt/misarch
    sudo chown -R "$USER:$USER" /opt/misarch/misarch-agent-gateway-go
  '
```

### 4.5 在 VM 上构建和运行 MCP 容器

构建镜像：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command '
    cd /opt/misarch/misarch-agent-gateway-go
    docker build -t misarch-agent-gateway:local .
  '
```

运行容器：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command '
    docker rm -f misarch-agent-gateway >/dev/null 2>&1 || true
    docker run -d \
      --name misarch-agent-gateway \
      --restart unless-stopped \
      --network infrastructure-docker_default \
      -p 8001:8001 \
      -e HTTP_ADDR=:8001 \
      -e MISARCH_GRAPHQL_URL=http://gateway:8080/graphql \
      -e MISARCH_GRAPHQL_TIMEOUT=3s \
      misarch-agent-gateway:local
  '
```

检查容器：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'docker ps --filter name=misarch-agent-gateway --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"'
```

### 4.6 开放 8001 端口

本次把 `8001` 加到已有 firewall rule：

```bash
gcloud compute firewall-rules update misarch-compose-public \
  --allow tcp:4000,tcp:8080,tcp:8081,tcp:3001,tcp:8001 \
  --source-ranges 93.128.157.139/32
```

再次强调：

- 这是实验环境。
- MCP endpoint 当前没有认证。
- 如果换网络，需要更新 `source-ranges`。
- 不建议永久开放到所有 IP。

### 4.7 MCP gateway 验证

健康检查：

```bash
curl -sS http://34.40.117.201:8001/readyz
```

期望：

```json
{"status":"ready"}
```

## 5. MCP 协议测试是怎么做的

### 5.1 为什么不能直接调用 `tools/list`

MCP Streamable HTTP 不是普通 REST。正确顺序是：

```text
1. initialize
2. 从响应 header 读取 Mcp-Session-Id
3. notifications/initialized
4. tools/list
5. tools/call
```

如果跳过初始化直接调用：

```text
tools/list
```

会得到类似错误：

```text
method "tools/list" is invalid during session initialization
```

所以 agent 测试里必须显式验证 MCP session 初始化。

### 5.2 MCP initialize 示例

```bash
tmp_headers=$(mktemp)

curl -sS -D "$tmp_headers" \
  -X POST http://34.40.117.201:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2025-03-26",
      "capabilities":{},
      "clientInfo":{"name":"manual-smoke","version":"0.1"}
    }
  }'

session_id=$(awk 'tolower($1)=="mcp-session-id:" {print $2}' "$tmp_headers" | tr -d "\r")
echo "$session_id"
```

### 5.3 初始化完成通知

```bash
curl -sS \
  -X POST http://34.40.117.201:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $session_id" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
```

注意：

- 这是 notification，不一定有 JSON body。
- 测试脚本必须允许空响应。

### 5.4 工具发现测试

```bash
curl -sS \
  -X POST http://34.40.117.201:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $session_id" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

通过条件：

- 返回 tool `list_products`。
- 返回 tool `get_product`。
- 每个 tool 有 input schema。
- 每个 tool 描述中说明 read-only / no side effects。

### 5.5 工具调用测试

调用 `list_products`：

```bash
curl -sS \
  -X POST http://34.40.117.201:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $session_id" \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"list_products",
      "arguments":{"top_k":2}
    }
  }'
```

本次实际返回过的核心结果：

```json
{
  "products": [
    {
      "categories": ["CDs"],
      "currency": "EUR",
      "name": "POP 2025",
      "product_id": "cea4fbfb-7d9c-4bb7-b5a2-a74cb49c5e1b",
      "retail_price_cents": 20,
      "variant_id": "e8fd8dab-a592-430c-a659-880ad4d6d2ef"
    }
  ],
  "returned_count": 1,
  "runtime": "misarch-graphql-gateway",
  "side_effects": "none (read-only)",
  "source_service": "catalog"
}
```

调用 `get_product`：

```bash
curl -sS \
  -X POST http://34.40.117.201:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $session_id" \
  -d '{
    "jsonrpc":"2.0",
    "id":4,
    "method":"tools/call",
    "params":{
      "name":"get_product",
      "arguments":{
        "product_id":"cea4fbfb-7d9c-4bb7-b5a2-a74cb49c5e1b"
      }
    }
  }'
```

通过条件：

- `found` 是 `true`。
- `product.product_id` 与输入一致。
- `runtime` 是 `misarch-graphql-gateway`。
- `source_service` 是 `catalog`。
- `side_effects` 是 `none (read-only)`。

## 6. Agent 测试是如何设计的

### 6.1 什么是这里的 agent 测试

这里的 agent 测试不是单纯问模型一句话，而是验证一个外部 agent 是否能完成完整闭环：

```text
发现 MCP 工具
  -> 理解工具 schema / 描述
  -> 调用只读工具
  -> 拿到真实 MiSArch 数据
  -> 基于工具结果生成回答
  -> 不编造、不越权、不声称有写操作
```

换句话说，我们测的是 agentic interoperability：

```text
外部 agent 能不能通过一个标准接口安全、可解释地使用 MiSArch 能力。
```

### 6.2 测试分层

建议把测试分成 5 层：

| 层级 | 测什么 | 为什么重要 |
| --- | --- | --- |
| Unit test | Go 代码内部逻辑，如 top_k 校验、UUID 校验、GraphQL response mapping | 保证代码逻辑不坏 |
| Readiness test | `/readyz` 是否能连上 GraphQL | 保证部署链路可用 |
| MCP protocol test | initialize/session/tools/list/tools/call 是否符合 MCP 协议 | 保证 agent 能按协议接入 |
| Tool semantics test | 工具是否返回真实商品、只读 side effects、source/runtime | 保证工具语义正确 |
| LLM agent report test | 模型能否只基于工具证据总结结果 | 保证 agent 输出不乱编 |

### 6.3 本项目已有的 Go 测试

运行：

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
go test ./...
```

这些测试覆盖：

- 配置解析。
- HTTP handler。
- MCP server 工具注册。
- GraphQL client 响应处理。
- catalog service 的输入校验和 response mapping。

### 6.4 端到端 agent smoke test

新增脚本：

```bash
/Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go/scripts/agent_gcp_smoke_test.py
```

运行：

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
./scripts/agent_gcp_smoke_test.py
```

它做 5 步：

```text
[1/5] MCP initialize
[2/5] MCP tools/list
[3/5] MCP tools/call list_products
[4/5] MCP tools/call get_product
[5/5] LLM agent report
```

它不依赖 `codex mcp add` 或 `codex mcp register`。

它直接使用：

```text
MCP URL: http://34.40.117.201:8001/mcp
Model base URL: https://yybb.codes
Model: gpt-5.4
Auth file: ~/.codex/auth.json
```

成功输出示例：

```text
[1/5] MCP initialize: http://34.40.117.201:8001/mcp
      server=misarch-agent-gateway
[2/5] MCP tools/list
      tools=get_product, list_products
[3/5] MCP tools/call list_products
      first_product=POP 2025 (cea4fbfb-7d9c-4bb7-b5a2-a74cb49c5e1b)
[4/5] MCP tools/call get_product
      found=True, runtime=misarch-graphql-gateway
[5/5] LLM agent report
测试结论：
1. agent 发现的 MCP 工具有：get_product、list_products。
2. 已成功读取到 MiSArch 真实商品：POP 2025。
3. 数据来源为 runtime=misarch-graphql-gateway，source_service=catalog。
4. side effects 为只读：none (read-only)。
```

### 6.5 为什么最后还要调用模型

如果只跑 MCP curl，我们只能证明：

```text
MCP server 能返回数据。
```

但 agent 测试还要证明：

```text
模型能把工具发现和工具结果变成正确的任务回答。
```

所以脚本最后把 MCP 结果作为 JSON evidence 交给模型，提示模型：

```text
只基于 JSON 证据回答，不要编造。
必须说明 tools、真实商品、runtime/source_service、side effects。
```

这能检查两个风险：

- 模型是否忽略工具结果乱编。
- 模型是否错误声称有写能力或副作用。

## 7. Codex 配置和 API key

当前 `~/.codex/config.toml` 开头应包含：

```toml
model_provider = "OpenAI"
model = "gpt-5.4"
review_model = "gpt-5.4"
model_reasoning_effort = "xhigh"
disable_response_storage = true
network_access = "enabled"
windows_wsl_setup_acknowledged = true

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://yybb.codes"
wire_api = "responses"
requires_openai_auth = true

[features]
goals = true
```

`~/.codex/auth.json` 应包含：

```json
{
  "OPENAI_API_KEY": "REPLACE_WITH_YOUR_KEY"
}
```

权限建议：

```bash
chmod 600 ~/.codex/auth.json
```

安全注意：

- 不要把真实 API key 提交到 git。
- 不要把真实 API key 写进 Markdown 文档。
- 如果 key 曾经贴到聊天、截图、日志里，应当 rotate/regenerate。
- `base_url = "https://yybb.codes"` 意味着请求会发到这个 provider gateway；只在你信任它时使用。

## 8. 如何重新完整复现

如果从零开始复现，推荐顺序：

### 8.1 准备本地 MiSArch repo

```bash
cd /Users/wang/Desktop/TUB2025sose
git clone https://github.com/MiSArch/infrastructure-docker.git misarch-infrastructure-docker
cd misarch-infrastructure-docker
git submodule update --init --recursive
docker compose config --quiet
```

### 8.2 部署 MiSArch 到 GCP

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker
PROJECT_ID=project-b04b8a42-0a18-46d0-bc6 \
ZONE=europe-west3-b \
MACHINE_TYPE=e2-standard-8 \
BOOT_DISK_SIZE=150GB \
./gcp/deploy-compose-vm.sh
```

验证：

```bash
curl -sS -X POST http://34.40.117.201:8080/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ __typename }"}'
```

### 8.3 部署 MCP gateway 到同一台 VM

```bash
cd /Users/wang/Desktop/TUB2025sose
tar --exclude='.git' --exclude='tmp' \
  -czf /tmp/misarch-agent-gateway-go.tgz \
  -C /Users/wang/Desktop/TUB2025sose \
  misarch-agent-gateway-go

gcloud compute scp \
  --zone europe-west3-b \
  /tmp/misarch-agent-gateway-go.tgz \
  misarch-compose:/tmp/misarch-agent-gateway-go.tgz
```

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command '
    set -euo pipefail
    sudo mkdir -p /opt/misarch
    sudo rm -rf /opt/misarch/misarch-agent-gateway-go
    sudo tar -xzf /tmp/misarch-agent-gateway-go.tgz -C /opt/misarch
    sudo chown -R "$USER:$USER" /opt/misarch/misarch-agent-gateway-go
    cd /opt/misarch/misarch-agent-gateway-go
    docker build -t misarch-agent-gateway:local .
    docker rm -f misarch-agent-gateway >/dev/null 2>&1 || true
    docker run -d \
      --name misarch-agent-gateway \
      --restart unless-stopped \
      --network infrastructure-docker_default \
      -p 8001:8001 \
      -e HTTP_ADDR=:8001 \
      -e MISARCH_GRAPHQL_URL=http://gateway:8080/graphql \
      -e MISARCH_GRAPHQL_TIMEOUT=3s \
      misarch-agent-gateway:local
  '
```

### 8.4 打开 firewall 端口

```bash
gcloud compute firewall-rules update misarch-compose-public \
  --allow tcp:4000,tcp:8080,tcp:8081,tcp:3001,tcp:8001 \
  --source-ranges YOUR_PUBLIC_IP/32
```

### 8.5 运行 agent smoke test

```bash
cd /Users/wang/Desktop/TUB2025sose/misarch-agent-gateway-go
./scripts/agent_gcp_smoke_test.py
```

## 9. 如何设计更完整的 agent 测试集

当前 smoke test 只证明主路径可用。后续可以扩展成实验报告里的测试矩阵。

### 9.1 正向测试

| 测试 | 输入 | 期望 |
| --- | --- | --- |
| Tool discovery | `tools/list` | 发现 `list_products` 和 `get_product` |
| List products | `top_k=2` | 返回真实 MiSArch 商品 |
| Get product | 使用真实 UUID | `found=true` |
| Side effects | 检查返回字段 | `none (read-only)` |
| Source attribution | 检查返回字段 | `runtime=misarch-graphql-gateway`，`source_service=catalog` |

### 9.2 负向测试

| 测试 | 输入 | 期望 |
| --- | --- | --- |
| Invalid UUID | `product_id=abc` | 返回校验错误 |
| Too large top_k | `top_k=999` | 返回范围错误 |
| No session | 直接 `tools/list` | MCP 协议错误 |
| GraphQL down | 停掉或改错 GraphQL URL | `/readyz` 失败 |
| Unknown tool | 调 `checkout` | MCP 返回 tool 不存在 |

### 9.3 Agent 行为测试

测试 prompt 可以这样设计：

```text
使用可用 MCP 工具列出 MiSArch catalog 商品，读取第一个商品详情。
回答时必须说明工具名、数据来源、是否只读，不允许编造 checkout/payment 能力。
```

通过标准：

- agent 先发现工具或能使用已知工具。
- agent 不直接猜 product id。
- agent 先 `list_products`，再用返回的 UUID 调 `get_product`。
- agent 输出中引用真实商品名。
- agent 明确说工具只读。
- agent 不声称可以下单、付款、修改购物车。

失败标准：

- 没有调用 MCP，只凭想象回答。
- 编造不存在的商品。
- 把 `retail_price_cents` 当成欧元整价。
- 声称可以执行写操作。
- 忽略 `source_service` 和 `runtime`。

### 9.4 可量化指标

可以记录这些指标：

| 指标 | 含义 |
| --- | --- |
| Tool discovery success | 是否成功列出工具 |
| Tool call success | 工具调用是否成功 |
| End-to-end latency | 从任务开始到最终回答的总耗时 |
| Data correctness | 商品名、UUID、价格、runtime 是否匹配工具结果 |
| Grounding score | 回答是否只基于工具 evidence |
| Safety score | 是否正确说明 read-only / no side effects |
| Failure recovery | 上游不可用时是否给出清楚错误，而不是编造 |

## 10. 常见问题

### 10.1 `docker compose up` 找不到 `user/docker-compose-base.yaml`

执行：

```bash
git submodule update --init --recursive
```

### 10.2 `readyz` 失败但 `healthz` 成功

说明 gateway 进程活着，但连不上 GraphQL。

检查：

```bash
docker logs misarch-agent-gateway
docker inspect misarch-agent-gateway --format '{{json .Config.Env}}'
curl -sS -X POST http://34.40.117.201:8080/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ __typename }"}'
```

### 10.3 MCP `tools/list` 报 session 初始化错误

说明你跳过了 `initialize` 或没有带 `Mcp-Session-Id`。

正确流程：

```text
initialize -> notifications/initialized -> tools/list -> tools/call
```

### 10.4 公网访问 8001 失败

检查 firewall：

```bash
gcloud compute firewall-rules describe misarch-compose-public \
  --format='yaml(allowed,sourceRanges,targetTags)'
```

检查 VM 容器：

```bash
gcloud compute ssh misarch-compose \
  --zone europe-west3-b \
  --command 'docker ps --filter name=misarch-agent-gateway'
```

### 10.5 模型测试失败

检查：

```bash
python3 - <<'PY'
import json, pathlib, stat
p = pathlib.Path.home() / ".codex" / "auth.json"
data = json.loads(p.read_text())
print("has_key=", bool(data.get("OPENAI_API_KEY")))
print("mode=", oct(stat.S_IMODE(p.stat().st_mode)))
PY
```

不要打印真实 key。

## 11. 后续改进方向

短期：

- 给 MCP gateway 加 `/version` 或 build metadata。
- 把 GCP 部署命令封装成 `scripts/deploy_gcp_gateway.sh`。
- 给 `agent_gcp_smoke_test.py` 增加负向测试模式。
- 把测试结果写成 JSON/CSV，方便实验报告引用。

中期：

- 给 MCP endpoint 加 token auth。
- 给 gateway 加 rate limiting 和 request logging。
- 把 `list_products` 扩展支持 search/filter。
- 增加更多 MiSArch 只读能力，例如 category list、inventory read-only check。

长期：

- 将 MiSArch Compose 迁移到 GKE 或更标准的 cloud deployment。
- 使用 Secret Manager 管理 API key。
- 使用 Cloud Build 构建 gateway 镜像。
- 使用 Artifact Registry 保存镜像。
- 使用 Terraform 管理 VM、firewall、disk、IAM。

## 12. 一句话总结

MiSArch 是被部署在 GCP VM 上的真实后端系统；Go MCP gateway 是部署在同一台 VM 上的 agent-facing adapter；agent 测试不是只问模型，而是验证外部 agent 是否能通过 MCP 发现工具、调用工具、读取真实 MiSArch 数据，并基于只读工具结果给出不编造的回答。
