# 5 分钟部署验证视频：直接录制手册

> 目标：一条不剪辑、≤5 分钟的视频，真实展示“当前提交 → 测试 → 从源码构建 Docker
> 镜像 → 部署 → MCP/A2A 功能验证”。不需要口播，也不需要 OpenAI API Key。

## 先说清楚“从头构建”的边界

录制中从当前 Git 源码、使用 `docker compose build --no-cache` 重新构建并部署的是本项目
提交的 **MiSArch Agent Gateway**。MiSArch 微服务是上游运行依赖，源码不在本仓库内；它在
录制前启动并准备测试数据，和录制数据库、浏览器、操作系统无需在视频中重新编译是同一个
道理。

这样既真实满足 build/deploy 验证，也不会让上游 Keycloak/Mongo 冷启动占满 5 分钟。录制
脚本不会复用旧 Agent Gateway 容器、Docker 构建层或 Go 编译缓存；它只复用提前下载的第三方
模块，然后对当前源码做一次 `--no-cache` 完整编译。

## 一、录制前准备（不录屏）

只需在第一次录制前运行一次：

```bash
cd /Users/wang/agent_misarch/agent_mpv_misarch

MISARCH_INFRA_DIR=/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker \
  ./scripts/prepare_deployment.sh
```

该脚本会自动完成：

1. 检查 Docker、Compose、Go、Python、curl、jq；
2. 校验录制专用 Compose 文件；
3. 提前拉取镜像并启动录制需要的 MiSArch 服务；
4. 用显式 override 把 Dapr 的应用端口固定到真实的 8080（Keycloak 为 80），不再受
   `.env` 中 `EXPERIMENT_CONFIG_SIDECAR_PORT=5000` 污染；
5. 等待真实 GraphQL 查询和 Keycloak token 流程成功；
6. 预热 Go/Docker 缓存、跑测试、准备演示商品；
7. 只读发现购买 fixture，写入被 Git 忽略的 `tmp/video-demo/purchase.env`。

它不会创建订单或支付记录。最后看到 `VIDEO ENVIRONMENT READY` 才可以开始录屏。

## 二、正式录制

推荐用单个终端窗口，1920×1080、字号 16–18，先清屏，然后开始 QuickTime/iTerm 录屏。

### 方案 A：最稳妥，不写数据

```bash
./scripts/run_deployment.sh
```

它会真实展示：

- Git revision 与 `go test ./...`；
- 清理旧 Agent Gateway 部署；
- `docker compose build --no-cache` 从当前源码构建镜像；
- Docker Compose 部署并等待 `/readyz`；
- `/healthz`、`/readyz` 与 Agent Card；
- MCP 工具白名单、危险工具暴露为 0、5 个非法调用全部拒绝；
- A2A 确认边界 3/3 通过，且 `mutation_expected=false`。

### 方案 B：最强证据，额外完成一次真实本地购买

```bash
./scripts/run_deployment.sh --purchase
```

前五段与方案 A 完全相同，最后额外执行一次两阶段确认购买：

- 第一次消息只返回预览，不创建订单；
- 第二次续接消息明确确认后才创建购物车/订单；
- 最后画面显示 `order_status=PLACED`、`payment_status=SUCCEEDED`；
- `local_simulation_only=true`，不会连接真实支付网络。

该模式会在本地 MiSArch 中留下订单、支付、发票等测试记录。正式录制只跑一次，不要用它
反复排练。

## 三、API Key 和四窗格演示要不要展示

**不要放进这条部署验证视频。** `run_deployment.sh` 的健康、Agent Card、MCP、A2A 和本地
购买验证都不调用 LLM，不需要 `OPENAI_API_KEY`。把 API Key 导入和四窗格演示塞进同一条
视频会增加三类无关风险：密钥误显示、外部模型网络波动、八次模型调用挤占 5 分钟预算。

四窗格是另一条“架构效果对比”素材。只有你准备单独录它时，才在录制前检查当前 iTerm：

```bash
[[ -n "$OPENAI_API_KEY" ]] \
  && echo "API Key 已导入" \
  || echo "API Key 未导入"
```

如果显示“API Key 已导入”，无需重复操作。若显示“未导入”，应在**开始录屏之前**执行：

```bash
read -rs OPENAI_API_KEY
export OPENAI_API_KEY
```

粘贴密钥时终端不会回显。导入后清屏，再开始一条独立、无剪辑的四窗格录制，只展示：

```bash
[[ -n "$OPENAI_API_KEY" ]] && echo "API Key 已导入"
export OPENAI_BASE_URL=https://yybb.dog
export OPENAI_MODEL=gpt-5.5
./scripts/open_iterm_four_arm_demo.sh
```

不要在成片中展示 `read -rs`、粘贴动作、密钥长度或任何密钥内容。`yybb.dog` 是第三方
Responses API 兼容端点，只有在你确认信任它处理该密钥时才使用。

进入四窗格后，开启 iTerm 当前标签页的 Broadcast Input，统一输入：

```text
I want a cheap cup under EUR 25
```

四个窗格都会把这句完整原文先交给各自的 OpenAI Agent。Agent 自己调用严格定义的
`search_catalog(query, max_price_eur)`；应用收到调用后，才分别经 GraphQL、MCP、MCP+
本地画像或 A2A 执行真实检索，再把工具结果交回同一个 Agent 生成最终答案。画面会明确显示
Agent 产生的 `query=cup` 和 `max_price_eur=25`，不再使用“取问题最后一个词”的规则。

两条素材的边界：

- **部署验证视频**：构建、Compose 部署、健康检查、Agent Card、MCP/A2A 边界、可选本地
  购买；不需要 API Key。
- **四窗格对比视频**：A/B/D/C 四个独立模型 Agent 的工具调用、选择与协议轨迹；每个
  窗格两次 Responses API 请求，需要 API Key，但不属于部署验收。

## 四、画面时间线

| 时间 | 画面 |
|---|---|
| 0:00–0:20 | revision + Go 测试通过 |
| 0:20–1:30 | 当前源码的 Docker `--no-cache` 构建 |
| 1:30–2:00 | Compose 部署、ready、容器 healthy |
| 2:00–3:00 | health/readiness、Agent Card、MCP、A2A 边界 |
| 3:00–4:30 | 可选真实本地购买 |
| 4:30–5:00 | 最终 JSON、`elapsed_seconds`、`VIDEO DEMO PASS` |

正常缓存状态下目标是 240 秒以内，留 60 秒余量。脚本超过
`VIDEO_MAX_SECONDS`（默认 300）会明确报出时间超预算；功能结果仍保留在
`tmp/video-demo/`，方便判断是构建慢还是功能失败。

## 五、录制前最后检查

- 终端中不要 `echo` 密钥；本流程完全不需要 `OPENAI_API_KEY`。
- 不要运行 `docker compose down -v`，购买 fixture 与预置数据都依赖现有本地卷。
- 看到基础设施错误时停止并重新录一条完整视频，不要把两条视频剪接起来。
- 允许对等待/构建段加速，但不要跳切。
- 正式购买录制前先用无写入版本排练一次：

```bash
./scripts/run_deployment.sh
```

- 确认最终画面同时出现：
  `success: true`、`dangerous_tools_exposed: []`、A2A 三个 `passed: true`、
  `VIDEO DEMO PASS`。购买版还必须出现 `PLACED` 与 `SUCCEEDED`。

## 六、文件位置

- 录制前准备：[prepare_deployment.sh](../scripts/prepare_deployment.sh)
- 正式录制：[run_deployment.sh](../scripts/run_deployment.sh)
- Agent Gateway 部署：[compose.gateway.yaml](../deploy/video/compose.gateway.yaml)
- MiSArch 端口覆盖：[compose.infrastructure.override.yaml](../deploy/video/compose.infrastructure.override.yaml)
- 自动合约测试：[test_deployment_video.py](../scripts/test_deployment_video.py)
- 生成证据：`tmp/video-demo/`
