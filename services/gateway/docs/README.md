# 网关服务（GATEWAY · Gateway）

> 微服务说明文档 · 依据《产品需求文档》（PRD v2.3）与《产品设计文档》（PDD v1.16）编写
> 本文档用于明确该微服务的**功能与质量基线**，支持后续扩展开发。功能口径以 PDD §5.16 / §3.1 为准，网关职责详设以《高并发架构演进设计》v0.7 §7 为准。
> **2026-09-15 更新**：优先级提前为 **M1 初期交付即接管**（原「M1 后期独立部署 + 内嵌 Filter 过渡」口径作废），信任模型改为「网关为平台唯一鉴权点」。

## 1. 服务概述

- **服务标识**：`gateway`（网关服务）
- **服务定位**：平台**唯一统一入口（API 网关微服务）**与**唯一鉴权点**，承载接入层全部横切职责——路由转发、统一鉴权（JWT 验签 + Redis 吊销校验）、网关级限流、灰度分流、超时/熔断/降级、traceId 注入/透传、统一 Envelope 封装、HTTPS 终结（Nginx 侧）、运维接口。
- **对应模块**：平台级横切（无业务功能点；承载 PDD §3.1「API 网关与统一入口」拍板能力）。
- **里程碑**：**M1 初期交付即接管**（2026-09-15 裁决；实施顺序先于全部业务域，与 ACC 并行）。M1 后期 = Nacos 服务发现 + 配置热更新；M2 = 多实例全量 + Sentinel 链路级熔断 + K8s 金丝雀。
- **实现载体 / 技术栈**：Java 17 + Spring Boot 3.5 + Spring Cloud Gateway（WebFlux）+ Spring Data Redis（Reactive）+ Resilience4j（M1 熔断；Sentinel M2 全量）+ Prometheus 指标；Nacos 于 M1 后期引入。
- **三端分布**：消费端 / 经营端 / 监管端 / 运营端**全部流量统一入口**（各端不直连领域服务）。
- **依赖服务 / 外部依赖**：Redis（JWT 黑名单 + 限流计数，**必需**——不可用时 fail-closed 快速失败）、KMS / 环境变量（JWT 签名密钥注入，密钥不出网关）、云 WAF/高防（DDoS/SQLi/XSS 前置）、Nacos（M1 后期）、Prometheus + Alertmanager（网关指标与告警）。
- **核心链路**：TLS 终止（Nginx）→ 云 WAF/高防 → **入口净化**（剥离客户端伪造身份头 + 路径规范化）→ traceId 注入 → JWT 验签 + 吊销检查（Redis）→ 网关级限流 → 路由转发（`/api/v1/{svc}/**` 重写为 `/{svc}/**`）→ 超时/熔断 → 服务内越权校验（2002）与业务处理。

## 2. 背景条件

- **需求背景（解决什么问题）**：多端直连、多服务入口散乱、鉴权/限流口径不一、AI 链路成本失控与调用不可控——网关作为唯一入口统一收敛认证、鉴权、限流、签名、防重放与灰度分流（PRD §3.4、《非功能需求-信息安全与可靠性专项》§3.4；功能列表 J-12/K-02）。
- **前置条件（本服务运行前提）**：
  - Redis 就绪（哨兵/主从；`gateway.store=redis`），**依赖不可用时入口 fail-closed 返回 503**（不静默放行）；开发/测试可用 `gateway.store=memory`（内存实现兜底）；
  - JWT 签名密钥经环境变量 / KMS 注入（`GATEWAY_JWT_SECRET`），**密钥不出网关**；
  - 服务端间接口（各服务 x-external-interfaces）不暴露于网关（仅内网 + 内部 Token）；
  - **网络前提**：网关仅接受入口 Nginx 访问（客户端 IP 取 `X-Forwarded-For` 链尾）；运维接口 `/gateway/**` 仅内网可达（对外入口 Nginx 不暴露该前缀）。
- **平台红线约束（本服务需强落地）**：
  - 密钥不出网关——JWT 签名密钥 env/KMS 注入，网关内验签，不下发服务（R-03 数据分级口径）；
  - **客户端伪造身份头必须在入口剥离**：`X-User-Id/Role/Mfa/Jti` 仅由网关验签后写入，服务内只信任这些头；
  - 管理端二次鉴权与业务越权校验（2002）在服务内完成，网关不越俎代庖；
  - 资金链路保护优先级最高（网关级限流/熔断先保资金接口）；
  - 前端不直连 Python 服务（AI 入口经网关/主站鉴权后转发，PDD §6.2 口径）。

## 3. 主要功能（网关承载职责全集）

> 本节把散落在 PDD §3.1 / §6.2、高并发 v0.7 §7 的网关职责收敛为 GATEWAY 的完整承载清单；**不承载**项见 §5 边界。

### 3.1 统一路由与双语言转发

- 统一入口 `api.example.com/api/v1/{svc}/…`；Nginx → GATEWAY → 各域实例。**路径重写**：`/api/v1/{svc}/**` 经 RewritePath 重写为 `/{svc}/**` 后转发（服务内真实路径无 `/api/v1` 前缀）。
- 双语言路由：`/assist/*`、`/aicore/*` → Python 服务；其余 → Java 域。
- M1 初期**静态路由**（配置于 `application.yml`，目标可用 `GATEWAY_ACC_URI` 等环境变量覆盖）；M1 后期切 Nacos 服务发现 + 配置热更新。
- **内部接口不可达**：命中 `gateway.internal-paths` 前缀（如 `/api/v1/acc/internal/`、`/api/v1/acc/realname/callback`）即 404，不转发。

### 3.2 统一鉴权链（网关为唯一鉴权点）

① TLS 终止（Nginx）→ ② 云 WAF/高防 → ③ **入口净化**（剥离客户端伪造的 `X-User-*`、拒绝路径混淆 `./ ../ // %2e`）→ ④ 网关 JWT 验签（HS256，硬校验 `alg`）+ Redis 吊销检查（`revoked:jti:{jti}`）+ 限流 → ⑤ 透传身份头 `X-User-Id/Role/Mfa/Jti` → ⑥ 服务内越权校验（2002）。

- **白名单**（无 token 放行，**段边界匹配**，`/registerAny`、`/auth/loginAny` 不蹭白名单）：
  `/api/v1/acc/captcha`、`/api/v1/acc/register`、`/api/v1/acc/realname/status`、
  **`/api/v1/acc/auth/login`**、**`/api/v1/acc/auth/refresh`**（2026-09-16 会话增量；**`/api/v1/acc/auth/logout` 刻意不在白名单**——
  登出需有效短 token 或有效长 token Cookie，白名单化只会削弱保护）。白名单请求同样经过入口净化与 IP 级限流，**不获限流豁免**。
- **Cookie 透传与非解析（2026-09-16 会话增量）**：网关**不读、不写、不解析** `Cookie`/`Set-Cookie`，
  请求头与响应头**原样透传**（换发响应下发的 `refresh_token` 逐字到达客户端）；鉴权**只看 `Authorization: Bearer`**，
  「仅带 Cookie 无 Bearer」访问受保护路径一律 401 + 2001（Cookie 不构成认证），因此业务接口不受 Cookie 影响、也无需全站 CSRF Token。
- 验签失败/过期/已吊销 → 401 + 2001（不泄露失败细节，吊销命中记 `鉴权失败 reason=Token 已吊销`）；Redis 吊销查询不可用 → **fail-closed 503 + 5003**。

**令牌策略（双 token，2026-09-15 用户裁决 + 审查 I9 加固；2026-09-16 签发侧落地）**：

- **短 token（access，15 分钟）**：走 `Authorization: Bearer`，由网关验签校验。网关**只认短 token**——`exp` 必须存在、未过期且**不超过 `access-token-max-ttl`（默认 15 分钟）+ `clock-skew`（默认 60 秒）** 的绝对时间上界，超长有效期一律 401 + 2001（密钥泄漏时爆炸半径受控）；`sub` 必须存在且非空白（否则下游会收到空身份）；签名算法 `alg` 必须为 HS256。
- **长 token（refresh，7 天）**：存 **HttpOnly + Secure + SameSite=Lax Cookie，Path 限定 `/api/v1/acc/auth`**，**不经网关业务链路**（不进 `Authorization` 头、不被网关验签、网关不解析 Cookie），仅用于 `POST /api/v1/acc/auth/refresh` 换发短 token。
- **签发与吊销写入方 = ACC（2026-09-16 已落地）**：`POST /api/v1/acc/auth/{login,refresh,logout}` 由 ACC 提供并签发；
  登出/重用检测写 `revoked:jti:{jti}`（TTL = 该短 token 剩余有效期），网关只读该键——
  两侧**必须同一 Redis 实例**（网关 `spring.data.redis.host/port` 与 ACC `acc.redis.host/port`），
  ACC 侧生产必须 `acc.session.store=redis`（取 memory 则吊销名单不共享、登出/踢人静默失效；缺 `host` 启动即失败）。
  真机闭环实证见 `services/acc/deploy/drill/README.md` §3.1 与 `services/gateway/deploy/README.md` §3 第 15 组。
- 判定口径：**过期判定严格**（不留容差），容差只用于放宽「有效期上限」，避免过期 token 被额外接受。

### 3.3 网关级限流

- 三级固定窗口计数（Redis+Lua 原子）：**IP**（`rl:ip:{ip}`）→ **账号**（`rl:acc:{tier}:{sub}`，验签通过才有）→ **接口**（`rl:api:{tier}:{method}:{svcPath}`）。
- 分级与初值（TBD-3 定档）：读 1000/s/账号、写 100/s/账号、AI 10/min/账号（路径前缀 `/api/v1/assist`、`/api/v1/aicore`）、资金 100/s（`/api/v1/settle`、`/api/v1/acc/funds`，独立桶优先保护）、IP 200/s（★压测标定）。
- 超限 → 429 + 2004；**AI 链路只做 IP + 账号级**（不做接口级全局桶，避免 10/min 全局阈值误伤多账号流量——AI 强限口径是「按账号」）；Redis 不可用 → fail-closed 503 + 5003。
- 两级体系：网关级（本服务）→ 服务级（Sentinel 热点参数/系统自适应，M2 全量）。

### 3.4 灰度分流

- M1 初期：Nginx 按 header/cookie/IP/百分比分流（网关侧 `metadata.weight` 键位已预留，默认全量 100）。
- M1 后期起：GATEWAY 路由权重分流；M2：K8s 金丝雀（5%~10% 起步，指标劣化自动切回）。

### 3.5 超时 / 熔断 / 降级

- **路由级超时**：`metadata.timeout`（内部服务 1s / 第三方支付 3s / AI 5s 初值）；非法值（非数字 / ≤0）回退默认 1s；超时 → 503 + 5002。
- **网关级熔断**：Resilience4j（时间窗口 10s、失败率 ≥50% 打开、半开 5 次试探、恢复探测 12s、`minimumNumberOfCalls=4`）；熔断打开 → 快速失败到降级端点（503 + 5002，带 `X-Gateway-Fallback` 标记头；该端点仅接受网关内部回退请求，外部直访 404）。
- **客户端错误不参与熔断统计**：401/404/429 由过滤器直接写出响应（短路），不抛异常。

### 3.6 traceId 与统一响应

- HTTP `X-Request-Id` 注入/透传（客户端值需匹配 `[A-Za-z0-9._-]{1,64}`，否则重新生成——防日志投毒）、MQ header 透传（SkyWalking/OTel）。
- 统一 Envelope + 错误码（`services/_common/openapi.yaml` 权威源）：2001 未登录 / 2004 请求过于频繁 / 3006 对象不存在 / 5000 内部错误 / 5002 依赖超时与熔断 / 5003 网关暂不可用。

### 3.7 高可用与运维

- 网关**无状态**、双实例起步 + 健康检查自动摘除故障实例；**全部实例不可用 → 入口快速失败 503**（不提供「Nginx 直连单体」降级路径——网关是唯一鉴权点，无鉴权直连即安全破口；可用性靠冗余）。
- **运维接口**（`services/gateway/docs/openapi.yaml`）：`GET /gateway/health`（status/redis/version/instanceId，Redis 不可用或依赖 DOWN → HTTP 503 供 LB 摘除）、`GET /gateway/routes`（路由表摘要，uri 已脱敏）；仅内网可达。
- 指标：每路由 QPS / P95 / 错误率 / 限流次数 → Prometheus；告警分级沿用 P0~P2 渠道；鉴权失败/限流/内部接口拦截/熔断降级均有结构化日志。

## 4. 非功能性需求要求

### 4.1 全平台通用基线（所有服务共同遵守）

- **规模**：覆盖 ≈840 万；注册 ≥600 万、MAU ≥200 万、商户/机构 ≥10 万、DAU 峰值 ≈120 万。
- **性能**：核心读首屏 P95 ≤2s；核心写 P95 ≤3s；API P95 ≤500ms / P99 ≤1s（网关/应用预算 150ms，PDD §8.1.2）。
- **可用性分级 SLO**：L1 ≥99.95% / L2 ≥99.9% / L3 ≥99.5%。
- **容灾**：同城双活 + 异地灾备，RPO ≤15min、RTO ≤30min（L1）。
- **安全**：等保三级 + OWASP ASVS L2；TLS 1.2+；密钥 KMS/HSM。
- **数据**：审计日志 ≥6 个月；存证只增不改。

### 4.2 本服务专项要求

- **可用性等级：L1（≥99.95%）**——全平台流量唯一入口，是 L1 停机预算与容灾覆盖对象；靠双实例冗余 + 快速摘除达成，不依赖降级路径。
- **性能**：多一跳开销 ms 级（路由/验签/限流全内存 + Redis Lua 原子）；网关双实例 + 无状态水平扩展。
- **数据安全**：**无业务数据库**——不落业务数据；Redis 仅存 JWT 黑名单（短 TTL）与限流计数；JWT 密钥 env/KMS 注入、网关内验签；日志脱敏。
- **可观测**：每路由 QPS / P95 / 错误率 / 限流次数指标 + 告警分级（P0~P2）；traceId 注入/透传。

## 5. 职责边界（承载 vs 不承载）

| 承载（GATEWAY） | 不承载（服务内） |
|---|---|
| 路由转发、统一鉴权（JWT 验签 + Redis 可吊销校验）、网关级限流（IP/账号/接口）、灰度分流、HTTPS 终结（Nginx 侧）、traceId 注入/透传、统一 Envelope 封装、超时/熔断/降级、运维接口 | 业务权限细粒度校验（水平/垂直越权 2002）、资金幂等（Idempotency-Key）、业务状态机、协议聚合（不做 BFF 聚合层） |

- **与 AI 网关底座（K-02）的边界**：AI 网关底座是 AICORE 内面向大模型的**应用级网关**（模型路由/任务队列/置信度分级/全链路审计，Python 侧），**不并入 GATEWAY**；GATEWAY 是面向全部流量的**接入层网关**（Java 侧）。两者分层不同：`/aicore/*`、`/assist/*` 经 GATEWAY 鉴权/限流后转发至 Python 服务。
- **不迁移清单（防误伤）**：① AI 网关底座 K-02（模型路由）留在 AICORE；② `services/acc/infrastructure/gateway/*`（支付/实名**通道网关**，六边形架构端口适配器）不属于接入层网关，不迁不动；③ `_common` 的 Envelope/ErrorCode/traceId 公共口径留在 `services/_common/`（网关引用，不复制）。
- **接口与数据库口径**：GATEWAY 无前端业务接口与业务数据库，不设业务 openapi/er.md（业务接口 14 份以 `services/*/docs/openapi.yaml` 为唯一可手改源）；**运维接口 openapi 见 `services/gateway/docs/openapi.yaml`**。

## 6. 实现与部署要点（2026-09-15 交付）

- **代码位置**：`services/gateway/`（包 `com.msz.gateway`：`config` / `filter` / `auth` / `ratelimit` / `redis` / `error` / `ops`）。
- **过滤器顺序（契约，测试锁定）**：`RequestSanitizerFilter(-20)` → `TraceIdFilter(-10)` → `JwtAuthFilter(0)` → `InternalPathGuardFilter(5)` → `RateLimitFilter(10)` → `TimeoutFilter(100)` → 路由过滤器（RewritePath 等）→ R4J 熔断。
- **配置键**：`gateway.{store,auth.whitelist,auth.jwt-secret,auth.access-token-max-ttl,auth.clock-skew,internal-paths,rate-limit.*,version,instance-id}`；其中 `auth.access-token-max-ttl`（默认 `15m`，env `GATEWAY_ACCESS_TOKEN_MAX_TTL`）与 `auth.clock-skew`（默认 `60s`，env `GATEWAY_CLOCK_SKEW`）为**令牌策略**（见 §3.2）；路由 `spring.cloud.gateway.server.webflux.routes`（含 `metadata.timeout`、`metadata.weight`）；熔断 `resilience4j.circuitbreaker.configs.default.*`；Redis `spring.data.redis.{host,port,username,password,timeout,connect-timeout}`。环境变量模板见 `.env.example`。
- **部署**：`mvn -f services/gateway/pom.xml verify` 产出可执行 fat jar（`java -jar gateway-*.jar`）；双实例 + Nginx upstream 指向；`gateway.store=redis` 为生产模式（`memory` 仅开发兜底）。
- **质量基线**：150 用例（含 Redis 故障 fail-closed、熔断打开/半开恢复、路径改写、伪造头剥离、令牌策略等集成用例；2026-09-15 令牌策略加固新增 6 用例 + 配置绑定 1 用例，2026-09-15 会话端点增量新增 11 用例——白名单/近似路径/Cookie 透传/仅 Cookie 不构成认证/限流不豁免，原 139）；jacoco 行 ≥80% / 分支 ≥75%（实测 94%/84%，`verify` 一次通过）。
- **配置绑定陷阱（实测记录）**：`@ConfigurationProperties` 的记录绑定**只允许唯一构造器**——给嵌套记录再加一个构造器会让 Spring 找不到绑定入口，实测 `gateway.auth` 绑定为 `null`（12 个上下文用例同时变红）；需要默认值时应使用**静态工厂**（如 `Auth.of(...)`），不要加第二构造器。
- **真机双进程联调（2026-09-15，任务组 10.2）**：`curl → 网关(18081，鉴权/限流/熔断/改写) → ACC 真实进程(8080) → MyBatis → MariaDB(33061)` 全链路实测——15 分钟 token 200 / 1 小时 token 401+2001 / 无 `sub` token 401+2001 / 伪造 `X-User-Id:9999` 仍按验签身份 `acc_1001` / 白名单 200 / 内部接口 404（直连 ACC 同路径 200，证明拦截发生在网关）/ 路径混淆 7 变体全部 404。演练桩见 `services/acc/deploy/drill/README.md`。
- **会话闭环真机演练（2026-09-16，`add-refresh-token-rotation` 任务组 7）**：网关(18081, `GATEWAY_STORE=redis`) + 真实 ACC(8080, `acc.session.store=redis`) + **内嵌真实 Redis(6380)** 三进程，
  换发链路与跨进程吊销全绿——登录 200（体只含短 token + Cookie 四属性）/ 短 token 业务 200 / Cookie 换发 200 且长 token 轮换 /
  旧 refresh 重放 401+2001 且整族吊销（原短 token 立即 401，网关日志 `鉴权失败 … reason=Token 已吊销` → 证明网关读的是 Redis 吊销名单）/
  重新登录 200 / 登出 200 后立即 401；Redis 键路径与 TTL 逐键核验。断言脚本 `services/acc/deploy/drill/session-drill.ps1`（25 项断言），
  网关侧验证清单见 `services/gateway/deploy/README.md` §3 第 15 组。

## 7. 参考文档

- 《产品设计文档》PDD v1.16 §2.4 模块与服务映射、§3.1 非功能性设计组件候选、§5.16 网关服务、§6.2 API 约定与错误码、§6.4 按服务接口清单（GATEWAY 无业务接口）
- 《高并发架构演进设计》v0.7 §7「API 网关详设」（职责边界/路由/鉴权链/限流/灰度/超时/高可用，TBD-12）
- 《微服务边界与职责基准》v1.7 §2.15 边界卡与 §4-C14 拆分决策（含 2026-09-15 变更记录）
- 公共组件（统一 Envelope/错误码/分页/鉴权）：`services/_common/openapi.yaml`
- 网关运维接口：`services/gateway/docs/openapi.yaml`
- 演进路线：`docs/design/diagrams/03-部署架构.md`（M1 初期 GATEWAY 双实例接入）
