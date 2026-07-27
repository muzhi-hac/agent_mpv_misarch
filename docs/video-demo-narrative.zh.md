# 视频展示思路 —— CNAE 报告配套演示

> 目标：用一段 5–7 分钟的视频，让评委在不读论文的情况下看懂四臂架构的权衡，并亲眼看到
> 论文里三个 RQ 的证据。已有更细的分幕稿在 `docs/a2a-demo-talk.zh.md`（三幕：正常/失败/
> 危险场景，围绕单个 butler CLI），这份文档不重复它，而是把**当前已经跑通的、更完整的
> 四窗格实时对比 demo**（`scripts/open_iterm_four_arm_demo.sh`，README 已描述）组织成一条
> 跟论文修订版严格对齐的主线。如果时间只够选一个 demo 素材，选这份文档里的四窗格版本——
> 它是唯一一个把 A/B/D/C 四臂并排跑给观众看的素材，直接对应论文 Table I 的实验设计。

## 0. 一条主线

> "同一个问题，四种架构分别怎么回答；同一个店铺，诚实和使坏分别会发生什么；
> 同一笔购买，从预览到真正的订单和支付，链路是完整的。"

三段分别对应论文的三个研究问题（RQ1 效率 vs 可发现性、RQ2 元数据不可信、RQ3 信任边界
要留在本地），外加一段"新增证据"（完整购买闭环 + 公网 Cloudflare 部署），呼应本次报告
修订新增的 III-D / III-E 两节。

| 时间 | 段落 | 对应论文位置 | 素材 |
|---|---|---|---|
| 0:00–0:40 | 开场 + 架构一句话 | Sec. I 贡献点 | 标题页 + 架构图（`docs/a2a-figures.en.md` 的 mermaid 图） |
| 0:40–3:30 | 四窗格实时对比（核心） | Sec. III-B / V-A / V-B | `open_iterm_four_arm_demo.sh` |
| 3:30–4:30 | 安全红队（诚实 vs 使坏） | Sec. IV-C / V-C | `--adversarial` + `scripts/a2a_*_regression.py` |
| 4:30–5:40 | 完整购买闭环 + 公网部署（新增） | Sec. III-D / III-E | `scripts/a2a_purchase_e2e.py` + Cloudflare Worker URL |
| 5:40–6:30 | 收尾：把画面翻译回论文的表和结论 | Sec. VI / VIII | 端到端延迟箱线图 + 安全回归柱状图 |

## 1. 开场（40 秒）

- 标题卡：论文标题 + "MiSArch 之上的四臂对比"。
- 一张架构图（直接用 `docs/a2a-figures.en.md` 里已经写好的 mermaid：USER TRUST DOMAIN /
  MERCHANT TRUST DOMAIN 那张），口播只说一句话："同一个后端，四种把能力暴露给 agent 的
  方式，我们控制其他变量，只换这一个。"
- 不要在这里讲术语细节（MCP/A2A 是什么），把术语解释留到第二段边跑边讲。

## 2. 四窗格实时对比（核心，约 3 分钟）

这是整个视频的证据核心，直接对应论文 Table I 的四臂设计和 Fig. 2/Fig. 3 的数据。

**开场前准备好**（不要现场配置，提前起好本地 MiSArch + gateway）：

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY
export OPENAI_MODEL=gpt-5.5
export OPENAI_BASE_URL=https://yybb.dog   # 只在你信任这个网关时使用
./scripts/open_iterm_four_arm_demo.sh
```

- iTerm 打开后用 **Shell → Broadcast Input → Broadcast Input to All Panes in Current Tab**，
  四个窗格同时收到同一句话：`Help me choose an inexpensive cup`。
- 镜头/口播节奏（每个窗格停留 15–20 秒，指着屏幕念出关键字段，不要念整段 JSON）：
  1. **A · Direct GraphQL**：指出它一次性把 4 个候选全部返回、不做推荐——"这是效率
     下界，但客户端得自己懂 schema"。
  2. **B · MCP**：指出 trace 里的 `initialize` → `tools/list` → `tools/call`，最终选中
     `Budget Plastic Cup`——"协议帮它发现了能力，但推理步骤让延迟变高"。
  3. **D · MCP + Profile**：指出同样的协议，换了本地画像后选出
     `Stainless Steel Cup 500ml`——"隔离变量：只换偏好表示方式，不换架构"。
  4. **C · A2A**：指出 Agent Card 读取 → `SendMessage` → task/context ID → artifact，
     选中 `Borosilicate Glass Cup`，并且强调"贵金属/环保偏好从来没有出现在发给商店的
     `tools/call` 里"——这是 Sec. III-C 的 data sovereignty 论点的可视化证据。
- 收尾一句话把四个窗格的选择和论文 Fig. 2 的延迟数字对上："A 最快，B/D 因为推理步骤最
  慢，C 虽然多一跳协议但比 B/D 快，因为它推理步骤更少——这跟论文图 2 完全一致。"
- 现场可以再广播一句新问题（README 已说明面板保持存活，可反复提问），展示这不是一次性
  脚本而是可交互的系统。

## 3. 安全红队：诚实 vs 使坏（约 1 分钟）

对应论文 Sec. IV-C / V-C 六类攻击中最适合"现场演示"的两类（价格操纵 + Agent Card 操纵，
都是 100% 防御成功，适合演示；backdoor 只有 50%，适合口播提一句"最难的一类"，不适合现场
演示失败案例，容易显得系统不安全）。

```bash
# 终端切到使坏模式（同一条命令，末尾加 --adversarial）
go run ./cmd/server --adversarial
```

- 现场跑一次带 `--adversarial` 的 browse，展示店铺把真实价格改写成 1 分钱。
- 切到 butler 侧的独立价格校验，展示它没有被这个假价格带偏——"协议元数据不可信，本地
  校验才是安全边界，这是论文 RQ2 的结论。"
- 如果时间够，快速展示一次 `python3 -m scripts.a2a_price_regression` 或
  `a2a_card_regression` 跑出的 JSON（`passed`/`total` 字段），把"现场演示"和"可重复的
  回归脚本"对上，说明这不是一次性表演。

## 4. 新增证据：完整购买闭环 + 公网部署（约 1 分钟）

这是本次报告修订相对原论文新增的两块内容（Sec. III-D / III-E），值得单独给一段，证明
"这不只是论文修订，代码也确实往前走了"。

- **完整购买闭环**：展示两阶段确认——第一条消息返回 `input-required` 和 purchase
  preview，且没有任何副作用；第二条带 `confirmed=true` 的续接消息才真正创建购物车、
  下单、等待本地支付，最终 `Order.orderStatus=PLACED` 且 `Payment.status=SUCCEEDED`。
  可以直接展示 `docs/report-aligned-test-scenarios.zh.md` 第 8 节里 2026-07-27 跑出的
  真实订单/支付 ID 作为"这不是 mock"的证据。
- **公网部署**：切一个浏览器/`curl` 到
  `https://misarch-store-agent.young-math-5a26.workers.dev/.well-known/agent-card.json`，
  展示 Agent Card 能在公网 HTTPS 上被发现——"信任边界不只是本地进程之间画的框，
  在真实网络边界上同样成立"。

## 5. 收尾（约 1 分钟）

- 切回论文的 Fig. 2（延迟箱线图）和 Fig. 4（安全回归柱状图），一句话把刚才看到的画面
  翻译回图表："刚才 A 最快、C 比 B/D 快，就是这张图；刚才价格操纵和 Card 操纵被挡住，
  就是这两根 100% 的柱子。"
- 用论文 Sec. VIII 的最后一句话收尾："agent interoperability 不该只看性能，更该问的是
  ——系统有没有把对的能力，通过对的边界暴露出去。"
- 片尾字幕给出复现方式：仓库地址 + `README.md` 的 "Four-pane iTerm video demo" 一节 +
  这份报告的 `docs/cnae-report-v2-overleaf.tex`。

## 拍摄/录屏建议（技术细节，非叙事）

- 用 iTerm 内置录屏或 QuickTime 屏幕录制，分辨率建议 1920×1080，字号调大（demo 脚本的
  输出本身信息密度高，观众隔着视频读小字很吃力）。
- 第 2 段（四窗格）是唯一必须"现场跑"的部分；第 3、4 段如果直播录制风险大（模型延迟、
  网络波动），可以录制两遍取最顺畅的一条剪进去，但不要用假数据替换真实输出。
- 全程不要把 `OPENAI_API_KEY` 留在终端历史或画面里；README 已经说明面板加载后立刻删除
  临时环境文件，录屏前确认没有残留的 key 明文闪过。
