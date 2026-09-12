# Design: add-m1-core-capabilities

## Context

本变更的动机与范围见 proposal.md（Why / What Changes）。设计约束的当前状态：

- **设计基线已定档**：PDD v1.0（`docs/design/产品设计文档.md`，2026-09-11 定档）、《高并发架构演进设计》v1.0（`docs/design/高并发架构演进设计.md`，同批定档）、15 个服务的 README + 14 份 openapi.yaml + 14 份 er.md（`services/*/docs/`）均已评审定档——本设计**不产生新架构决策**，全部技术选择引用这些定档口径。
- **代码状态**：`services/*` 与 `apps/*` 目前只有文档、无实现代码；本变更是「先立规范、后按规范实现」的绿场落地。
- **M0 阻塞状态**：运营主体已定（国有企业，2026-09-11）；支付通道申请、大模型合规评估尚未完成（AC-M0.2/M0.6），实现排期须按 M0 解除顺序推进。
- **硬约束（不可妥协）**：R-01 不沉淀资金/不做二清；R-02 实名仅微信/支付宝回传、不可用即暂停；R-03 数据分级授权；R-05/C8 AI 只标记不决策；R-06 对话脱敏不出域、日志 ≤30 天；R-07 画像合规不杀熟；R-11 PC Web 优先、核心信息一屏可查、投诉 ≤3 步。

## Goals / Non-Goals

**Goals:**

- 为 M1 九能力给出「按已定档设计即可实施」的实现路径：服务落位、数据层、异步与幂等、限流降级、安全、可观测、前端形态，全部引用既有定档文档，不新增决策。
- 明确 M1 代码的**硬边界约束**（为 M2 拆分 SETTLE/TRADE 与 GATEWAY 独立部署铺路，拆分时是「切部署单元」而非重构）。
- 把验收口径（AC-M1.1~M1.11 / AC-C1~C8 / AC-NFR-1~11）映射到实现层检查点。

**Non-Goals:**

- 不改动任何已定档设计文档（PDD/高并发/er.md/openapi.yaml 是事实来源，若发现冲突按文档间既有裁决口径处理，不在此变更内修订）。
- 不设计 M2/M3 功能（B/F/E/H/L 交付、K-03~K-06、T-02~T-21、I-04/I-05、骑手端交付），仅保留 M1 硬边界与扩展位。
- 不产生新的架构决策：任何未定档细节（★ 阈值标定等）按文档既定「压测/试运行标定」流程处理，不进本设计。

## Decisions

### D1 架构形态：模块化单体 + 双语言 AI 服务 + M1 后期独立网关（引用 PDD §2.1/§5.16、ADR-1/ADR-8）

- 决策：Java 17 + Spring Boot 3 模块化单体承载 13 个业务域（ACC/SETTLE/CRED/EMP/TICKET/TRACE/PROD/TRADE/DASH/PROFILE/CIVIC/DELIVERY 中 M1 涉及的 7 个域 + 预留）；ASSIST/AICORE 为独立 Python 3.12 + FastAPI 服务（LangChain 仅做编排、硬护栏在编排之外）；GATEWAY（Spring Cloud Gateway + Nacos）M1 后期独立部署、M1 初期由应用内嵌统一 Filter + Nginx 过渡。
- 备选（已否决，PDD/ADR 定档）：一步微服务化（10~20 人团队不可承受的过早分布式复杂度）；AI 侧留 Java（高 IO 等待 + 外部 AI API 负载与 FastAPI/LangChain 生态不匹配）；网关 M2 才拆分（延迟统一入口收敛，灰度/限流能力晚到）。
- 落地要点：M1 起每域独立 package + 独立 DAO + **禁止跨域直接 JOIN/读表**，跨域走接口/事件；DB 按域 schema 前缀隔离（高并发 §6 优化点①）。

### D2 数据层：分表、分布式 ID、缓存与快照（引用高并发 §2、PDD §4）

- 按月分表（M1 起）：ACC `wallet_flow`、SETTLE `payroll`、EMP `attendance`（C-02 打卡明细）、TICKET `ticket/ticket_flow`、TRACE `trace_event`、PROFILE `behavior_event`、AICORE `ai_task/ocr_result`；分片键 = 业务键（account_id/employment_id/merchant_id/batch_no）+ `created_at`，**禁止把雪花 ID 当 hash 分片键**；主数据（account/merchant/person/supplier/profile）不分片。
- 分布式 ID：统一组件 `infra-idgen`（雪花 + 号段双轨、时钟回拨三档预案 L1 退避→L2 切号段→L3 拒绝发号），全写库 Java 域 MUST 复用、禁止自研雪花；分表路由一律以业务字段 `created_at` 为准。
- 缓存：Caffeine + Redis 两级；空值缓存/布隆防穿透、逻辑过期+互斥重建防击穿、TTL 随机化防雪崩；档案/信用/溯源/红黑榜等公示数据走「版本化快照 + 定时刷新」只读快照模型。
- 读写分离：主库写、从库读（`@ReadOnly` 路由）；关键资金/工单「写后立即读」强制走主库。

### D3 资金合规：记账支付分离 + 幂等 + 状态机 + 对账（引用 PDD §5.1/§5.2/§7.3、高并发 §3.2）

- 决策：钱包 = 纯记账簿；代付/分账全走第三方持牌通道；资金接口强制 `Idempotency-Key`（落库唯一索引 `uk(idempotency_key)`，重复请求返回首次结果）；MQ 消费以消息业务键（如 `channel_tx_no`）查库幂等；代付状态机（待校验→代付中→已到账/预警）+ 超时自动查单兜底；每日对账 JOB 补差。
- 备选（已否决）：平台账户代收代付（触碰二清红线）；仅靠 MQ ack 防重（回调重放会重复入账）。

### D4 异步削峰：按 SLO 物理隔离队列（引用高并发 §3.1、PDD §6.3）

- 资金队列（`settle.pay.callback`/`settle.reconcile`）与 AI 队列（`assist.task`/`aicore.task`/`aicore.conclusion`）物理隔离，AI 积压不得占用资金链路资源；重试仅限幂等接口（指数退避 ≤5 次）、DLQ + 告警 + 人工介入；背压超阈值暂停非核心生产。
- 核心链路：工资代付 = 记账同步落库 → 通道异步 + 回调异步入账；投诉提交 = 先落库回执 → 证据 OSS 直传 → 图片异步审核 → 超时升级 JOB；AI 对话/OCR = 全异步任务化 + FAQ 规则库优先命中。

### D5 限流 / 熔断 / 降级（引用高并发 §4、PDD §8.2.4）

- 两级限流：网关级（IP/账号/接口令牌桶，M1 初期内嵌 Filter、后期 GATEWAY）→ 服务级（Redis+Lua 令牌桶起步、Sentinel 观察不承载熔断）；初值：读 1000 req/s/账号、写 100 req/s/账号、AI 对话 10 次/分/账号。
- 舱壁线程池：`core-pool`/`settle-pool`/`ai-pool`/`io-pool`/`mq-consumer` 隔离，非核心故障不得拖垮核心；降级开关：LLM→FAQ 规则库+人工入口、视觉/OCR→人工复核队列、支付通道→切备选+幂等重试（全不可用暂停并公告）、**实名不可降级（暂停并明示）**。

### D6 安全与合规落地（引用专项 §2/§3、PDD §7/§8.4）

- 认证：JWT（access 短时效 + refresh 轮换、Redis 可吊销、HttpOnly+Secure+SameSite）+ RBAC（六方角色）+ ABAC 数据域（本人/授权/脱敏公示 L1/L2/L3）；敏感操作（发薪/分账/申诉/执法/数据导出）强制 MFA；全接口 IDOR 校验（2002）。
- 数据：敏感字段 AES-256-GCM + MySQL TDE；展示脱敏；密钥 KMS/HSM、禁写库、轮换策略；审计日志独立（WORM/哈希链 ≥6 个月）、对话日志独立 ≤30 天自动清理。
- 等保三级：M0 定级备案+专家评审，M1 上线前测评整改闭环；上线前第三方渗透（高危 0 未闭环）；WAF/抗DDoS/SOC/SIEM M1 就绪。

### D7 双语言边界（引用 PDD §2.4 注、ADR-7）

- ASSIST/AICORE 不直连主站库：AICORE 独立库 `aicore`（M1 起）、ASSIST 不落业务库（Redis 会话 30min TTL + MQ + 脱敏审计日志 ≤30 天）；取数走 ACC/CRED/TRACE 内部接口（统一鉴权头 + traceId 透传）；权威数据事件同步、单一来源（`aicore.conclusion` 回写 CRED/DASH，幂等消费 + 对账兜底）；前端不直连 Python 服务（经 GATEWAY/主站鉴权转发）。

### D8 前端形态（引用 PDD §2.4 前端模块划分）

- 三端合一单 React 18 + TypeScript + Vite 应用（AntD 5），消费/经营/监管端按「角色 + 权限路由」区分；Monorepo：`apps/web` + `packages/ui|assistant|api-client|shared`；`packages/api-client` 由后端 OpenAPI 生成 TS 类型；助手侧边栏三端复用。

### D9 可观测（引用 PDD §8.5、专项 §4.5）

- 日志：JSON 结构化双语言同 schema，必含 traceId/spanId/uid（脱敏）/bizType/opCode/code；审计/对话/应用日志分通道。
- 追踪：SkyWalking（Java agent + Python agent/OTel 同一后端）；错误与慢调用 100% 采样 + 正常链路抽样。
- 指标：Prometheus + Grafana + Alertmanager；告警分级 P0~P3 + 值班；业务指标含助手意图命中率/跳转成功率/推荐采纳率（脱敏）。

## Risks / Trade-offs

- [双语言栈（Java+Python）维护成本、双 CI/CD 与双依赖扫描] → 边界已定档：仅 ASSIST/AICORE 为 Python、画像业务留 Java；护栏（脱敏前置/白名单路由/内容安全/全链路审计）在 LangChain 编排之外强制执行，不开放自由工具调用；密钥 KMS 注入。
- [M0 阻塞：支付通道/大模型合规未完成] → 实现顺序按 PDD §9.3「基建先行」推进，通道依赖的功能（I3 代付）以 mock 通道开发 + 通道就绪后联调；AC-M0.2/M0.6 未解除前 M1 上线验收不启动。
- [等保三级测评周期 2~4 月可能拉长 M1 上线] → M0 即启动定级备案，测评与开发并行（专项 §10）。
- [840 万级容量设计过度/不足] → 容量触发式演进（高并发 §1.2 触发阈值），压测分层验证（试点峰值 3x + 规划峰值 1.5x），避免一次性超配。
- [第三方依赖（实名/支付/AI）故障拖垮核心链路] → 降级开关清单 + 舱壁隔离 + 对账补偿；实名按红线暂停不降级。
- [Python 服务数据一致性（AI 结论回写主站）] → `aicore.conclusion` 事件幂等消费 + 每日对账兜底（ADR-7）。
- [M1 后期 GATEWAY 独立部署的切换风险] → M1 初期内嵌 Filter + Nginx 过渡、独立部署后 Filter 降级为故障兜底；GATEWAY 故障 → Nginx 直连单体降级路径（高并发 §7.7）。

## Migration Plan

- **无存量系统迁移**：全部为绿场新建（services/apps 无既有代码），数据层按 expand-migrate-contract 规则从第一张表开始落地（双写→回灌→切读→收缩仅用于后续演进，不涉及历史数据）。
- **实施顺序**（PDD §9.3）：基建（_common 错误码/存证/幂等、infra-idgen、分表路由、鉴权 Filter、可观测三件套）→ ACC 账户内核 → CRED 信用档案 → EMP 用工与互评 → TICKET 工单 → TRACE 溯源 → ASSIST/AICORE（并行）→ DASH 费率公示 → GATEWAY 独立部署（M1 后期）。
- **发布与回滚**：功能开关默认关 → Nginx/网关灰度（header/cookie/IP/百分比）→ 金丝雀 5%~10% → 逐步放量；指标劣化自动切回，回滚 ≤10 分钟；DB 变更向后兼容（expand-migrate-contract），不兼容变更禁止灰度直发。
- **验收门禁**：每个服务上线前过 agent-sdlc-standard 门禁（单元/安全/依赖扫描）+ 五词自检 + AC-M1.x 对应证据。

## Open Questions

无。本变更涉及的阈值初值（TBD-1~13、限流/熔断/超时/连接池初值、J-03 权重与阈值、A-07/I-02/T-05 权重、D2 48h、G1 7 个工作日）均已于 2026-09-11 评审定档；仅标注 ★ 的项待压测/试运行标定回填实测值，不影响本设计的规范与任务拆分（标定属于 tasks.md 中的验证步骤）。
