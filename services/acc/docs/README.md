# 账户服务（ACC · Account）

> 微服务说明文档 · 依据《产品需求文档》（PRD v2.3）与《产品设计文档》（PDD v1.0（基线））编写
> 本文档用于明确该微服务的**功能与质量基线**，支持后续扩展开发。功能口径以 PDD §5.1 / §6.4.1 为准，需求口径以 PRD §5.11（I 组）为准。

## 1. 服务概述

- **服务标识**：`acc`（账户服务）
- **服务定位**：平台的**实名身份底座 + 纯记账簿**，为全平台提供可信身份与资金流水证据。
- **对应模块**：I1 实名账户 + 钱包记账（I-01）；I-06 强实名增强【M2，§5.14】。（I-02 劳务信用双向互评属 EMP 用工服务，本服务不承担。）
- **里程碑**：M1 交付。
- **实现载体 / 技术栈**：Java 17 + Spring Boot 3.5（模块化单体，属业务域，不随 Agent/AI 侧 Python 化）。
- **三端分布**：消费端（实名/流水）· 经营端（实名/流水）· 监管端（资金流水审计）。
- **依赖服务 / 外部依赖**：微信 / 支付宝实名回传（强依赖）、支付通道、**Redis（会话凭据存储，生产必需）**——会话族与网关吊销名单必须落在**同一个 Redis 实例**（`revoked:jti:{jti}` 契约：ACC 写、网关读）；被 ACC 依赖的下游包括 CRED、EMP、TICKET、TRACE、SETTLE、ASSIST 等。
- **核心状态机**：实名认证（未实名 → 实名中 → 已实名 / 暂停）；**会话凭据**（登录建族 → 轮换换发 → 重用检测整族吊销 / 登出吊销）。

## 2. 背景条件

- **需求背景（解决什么问题）**：消费信任缺失、维权取证难、劳资与预付费风险，均需要「人可信、账可查」。ACC 是全部信用 / 用工 / 交易 / 结算流程的可信身份与资金流水证据底座（PRD §2.1 问题 1/4）。
- **前置条件（本服务运行前提）**：
  - 实名唯一口径：**仅微信 / 支付宝实名回传**，平台不自建密码 / 证件核验体系；
  - 第三方实名不可用时，按红线**暂停**注册 / 入职 / 入驻流程并明示，不接受人工证件核验降级（R-02）。
- **平台红线约束（本服务需强落地）**：
  - R-01 记账与支付分离——平台只记账、不沉淀资金；
  - R-02 实名唯一口径（不降级）；
  - R-03 数据分级授权（本人 → 授权 → 脱敏公示）；
  - R-04 证据存证——流水只增不改、时间戳 + 哈希、可出证。
- **里程碑边界**：M1 交付实名、钱包记账、收款绑定；不做对外 OAuth2 IdP（开放平台为 M3 候选）。

## 3. 主要功能

### 3.1 实名注册与实名回传

用户通过微信 / 支付宝实名回传完成注册，获得平台账户与六方角色。流程：**人机验证（滑块拼图，失败降级图形验证码）→ 一键实名** → 授权协议 → 回传实名信息（姓名 / 身份证号）→ 返回 accountId + realNameStatus。异常处理：第三方不可用即暂停；信息不匹配报 3002；重复 open_id 幂等返回原账户。

### 3.2 钱包记账与流水查询

为每笔资金操作生成记账流水（通道交易号 / 时间戳 / 存证哈希），支持本人分页查询、按月分表路由、水平越权校验（2002 拦截）。

### 3.3 收款账户绑定

将本人收款账户绑定到持牌支付通道，供后续代付 / 分账收款使用。账号与实名不一致拒绝绑定（3002）；重复绑定幂等返回原绑定。

### 3.4 登录人机验证（防机器人）

登录 / 注册页（页面码 G-01）人机验证：默认滑块拼图，滑块失败降级图形验证码；校验通过下发一次性凭证 verifyToken，注册接口回填 captchaToken 完成防机器人校验（登录爆破限速）。接口：`GET /acc/captcha`（下发挑战，正确结果仅存服务端）、`POST /acc/captcha/verify`（校验，挑战一次性消费防暴力枚举）。异常处理：答案错误 / 过期 → success=false，前端重取或降级图形验证码。

### 3.5 会话凭据（双 token：签发 / 换发轮换 / 重用检测 / 登出吊销，2026-09-16）

免密登录签发**短 token（access，15 分钟，走 `Authorization: Bearer`）**与**长 token（refresh，7 天，仅 `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth` Cookie）**；换发**单次使用 + 轮换**，旧长 token 再次出现即判泄露并**吊销整个会话族**（含未过期短 token）；登出把短 token 的 `jti` 写入网关共享吊销名单并清 Cookie。**长 token 原文只经 `Set-Cookie` 下发，永不进响应体与日志**。

| 接口（openapi v1.2.0，网关对外路径） | 说明 | 关键口径 |
|---|---|---|
| `POST /api/v1/acc/auth/login` | 手机号 + 一次性人机验证票据换双 token | 200 响应体只含短 token；长 token 仅 `Set-Cookie`；失败统一 401 + 2001（不区分原因） |
| `POST /api/v1/acc/auth/refresh` | 以 Cookie 换发新 token 对 | 单次使用 + 轮换；超出 5s 并发宽限窗口的旧 token 重放 → 401 + 2001 且**整族吊销**；来源校验：**同源默认放行**（`Origin` 与请求自身 scheme+host 一致，无需配置），仅**跨源**才要求出现在 `acc.session.allowed-origins`（默认空） |
| `POST /api/v1/acc/auth/logout` | 吊销当前会话族（幂等） | 短 token `jti` 入 `revoked:jti:{jti}`（TTL = 剩余有效期）；族置 `REVOKED`；`Max-Age=0` 清 Cookie |

- **数据归属**：会话族 `acc:session:{familyId}`、refresh 映射 `acc:refresh:{jti}`（TTL ≤ 7 天 = 其有效期）、
  已轮换标记（保留至族到期，重放因此可识别）与吊销名单 `revoked:jti:{jti}`（TTL = 短 token 剩余有效期）
  **全部在 Redis**；ACC **不设会话业务表**（非权威业务数据，`er.md` 不新增实体）。
- **网关协作**：`revoked:jti:{jti}` 是**跨服务契约**——ACC 写、网关读；两侧必须同一 Redis 实例，
  否则登出/踢人失效。网关侧白名单放行 login/refresh（**不含 logout**），Cookie 原样透传、不解析。

## 4. 非功能性需求要求

### 4.1 全平台通用基线（所有服务共同遵守）

- **规模**：覆盖石家庄全体市民及常住人口 75%（≈840 万），注册 ≥600 万、MAU ≥200 万、商户/机构 ≥10 万、DAU 峰值 ≈120 万。
- **性能**：核心读首屏 P95 ≤2s；核心写 P95 ≤3s；API P95 ≤500ms / P99 ≤1s。
- **可用性分级 SLO**：L1 ≥99.95% / L2 ≥99.9% / L3 ≥99.5%。
- **容灾**：同城双活 + 异地灾备（两地三中心），RPO ≤15min、RTO ≤30min（L1）。
- **安全**：等保三级（GB/T 22239-2019，S3A3G3）+ OWASP ASVS L2；全链路 TLS 1.2+；密钥 KMS/HSM。
- **数据**：流水/交易按月分表；审计日志 ≥6 个月（WORM/哈希链）。

### 4.2 本服务专项要求

- **可用性等级：L1（≥99.95%）**——实名认证属核心链路，是 L1 停机预算与容灾 RPO/RTO 覆盖对象。
- **实名不可降级**：第三方实名回传为强依赖，回调异步落库 + 状态机 + 超时重查 JOB；第三方不可用一律暂停相关流程并明示，不静默降级（PRD §7.3 / PDD §8.2.4）。
- **数据安全**：实名（姓名 / 身份证号）属 L1 高敏感，应用层 AES-256-GCM 加密存储、脱敏输出（如 138****）；流水只增不改 + 存证哈希链。
- **幂等与越权**：实名 / 绑定接口幂等（重复 open_id / 同账号幂等返回）；全接口水平 / 垂直越权（IDOR）校验。
- **性能**：实名回传第三方强依赖不计入同步预算（异步化 + 状态机）；流水按月分表、跨月查询走分表路由。

## 5. 参考文档

- 《产品需求文档》PRD §2 背景与目标、§3.4 红线 R-01~R-16、§5.11（I 组）、§7 非功能需求
- 《产品设计文档》PDD §2.4 模块与服务映射、§5.1 账户服务、§6.4.1 接口清单、§8 非功能设计
- 接口文档（**唯一可手改源**）：`services/acc/docs/openapi.yaml`（OpenAPI 3.0，**v1.2.0：前端接口 18 个**，含会话三接口 `/acc/auth/{login,refresh,logout}`；公共组件引用 `services/_common/openapi.yaml`，勿复制内联）
- 数据库设计说明书（ER + 分库分表 + 数据字典 + 表设计）：`services/acc/docs/er.md`（6 实体：account / realname_record / wallet_flow / wallet_binding / reconcile_task + captcha_challenge(Redis)；口径对齐 openapi.yaml v1.1.0 与《高并发架构演进设计》v1.0 §2）；**会话族/refresh 映射/吊销名单在 Redis，不新增业务表，故 er.md 不变**
- Apifox 导入产物（**自动生成，禁止手改**）：`services/acc/docs/openapi.apifox.json`（用 `.dsh/regen-apifox.cjs acc --write` 由 openapi.yaml 重打包）
- 流程时序：`docs/design/diagrams/05-实名认证流程-I1.md`

## 6. 已知限制与实现要点（2026-09-15 真机联调补录；2026-09-16 会话增量补录）

- **数据层会话语义（已修 + 残余限制）**：`AccConfiguration` 的 Mapper Bean 原为 `factory.openSession().getMapper(...)`——会话长驻、`autoCommit=false`、**事务永不提交**。真实数据库下出现三个症状：
  1. **读陈旧**：外部连接已提交 `wallet_status='FROZEN'`，接口仍返回 `ACTIVE`（REPEATABLE READ 长事务快照）；
  2. **写不落库**：`POST /acc/account/close` 返回 200，但外部 `SELECT` 得到 `closed_at` 仍为 `NULL`——接口报成功而数据丢失；
  3. **持锁阻塞外部写入**：外部 `UPDATE` 撞上未提交事务持有的行锁，报 `Lock wait timeout exceeded`（约 50s）。
  **已修复**：改为 `factory.openSession(true)`（自动提交，与 `repository` 层 DAO 测试同口径）；修复后实测外部提交后接口读到 `FROZEN`，`close` 后外部 `SELECT` 得到 `closed_at=2026-09-15 19:52:29.212, close_reason=drill-fixed`。
- **已落地：请求级事务边界 + session-per-request（`fix-acc-transaction-boundary`，2026-09-15）**：上条止血留下的三项残留已全部收敛——① `AccConfiguration` 的 6 个 Mapper Bean 改为**事务感知动态代理**（`infrastructure/tx/TransactionalMapperProxy`），每次调用转发到**当前请求会话**上的真实 Mapper，一个请求内的全部数据访问落在同一会话/连接；② `repository/RequestSqlSessionHolder` 以 `ThreadLocal` 绑定**请求级会话**，首次真正访问数据库时才惰性 `openSession(false)`，请求结束必 `close()`（归还连接）并 `remove()`，不再有长驻会话，并发请求各持独立会话/连接；③ `infrastructure/tx/TransactionBoundaryFilter`（order 2，`urlPatterns=/acc/*`）承担**请求级事务边界**——正常返回提交、未捕获异常（含受检）回滚、错误 Envelope 经 `GlobalExceptionHandler` 置位的 `acc.transaction.rollbackOnly` 标记同样回滚、`finally` 关会话。由此**跨表写入具备原子性**（失败请求不留半成品）、提交结果对其它连接立即可见、失败的幂等占位随事务释放（同 `Idempotency-Key` 可立即重试）。回归防线：`config/RealDbAssemblyTest` 扩展至跨表回滚 / 并发隔离 / 提交可见性 / 幂等槽位释放 / 读路径契约 / 连接释放 / 并发同 key 竞态 / 未提交写隔离（tasks 3.8 `uncommittedExternalWriteStaysInvisibleToConcurrentRead`，**守卫用例，未观测到 RED**）等真实库用例。**验证**：`mvn -f services/acc/pom.xml verify -nsu` = **280 用例 0 失败**（原 253）；真机双进程联调复跑（网关 18081 + 真实 ACC 8080 + 嵌入式 MariaDB 33061）与 2026-09-15 记录一致——短 token 200 / 超长与无 `sub` token 401+2001 / 白名单 200 / 网关内部接口 404（直连 ACC 同路径 200，证明拦截在网关）/ 直连 ACC 四身份头 200，并复验写后读：`POST /acc/account/close` 返回 200 后外部连接立即读到 `closed_at=2026-09-15 21:02:16.391, close_reason=g4-drill-recheck`，无「写不落库 / 读陈旧」回归。
- **回归防线**：新增 `services/acc/src/test/java/com/msz/acc/config/RealDbAssemblyTest.java`（真实库 + 真实 Tomcat + 真实 HTTP，2 用例，分别拦「读陈旧」与「写不落库」）。反向验证：把修复临时改回原实现，该测试立刻 **1 Failure**（`closed_at` 为 NULL）+ **1 Error**（`Lock wait timeout exceeded`）→ 证明能拦住回归。ACC `mvn verify` = **253 用例 0 失败**（原 251）。
- **`jakarta.annotation-api` 钉版缘由**：`services/acc/pom.xml` 显式钉 `jakarta.annotation:jakarta.annotation-api:2.1.1`——test 作用域的 mariaDB4j 会传递 javax 时代的 `1.3.5` 抢占依赖调解，令 Web 容器启动抛 `NoClassDefFoundError: jakarta/annotation/PostConstruct`（真机联调发现；真实库装配层测试与演练桩均依赖该钉版）。
- **真机联调桩入口**：`services/acc/deploy/drill/README.md`（嵌入式 MariaDB（mariaDB4j，test 作用域）+ **内嵌真实 Redis（embedded-redis，默认 6380）** + Flyway V1/V2 + `@Primary` 真实 DataSource 覆盖 M1 占位数据源 + 真实 `AccApplication` 进程；夹具账户 `account_id=1001 / mobile=13800138000`（`mobile_hash` 由 `HmacFingerprint` 现算，与登录查询同源），`token` 模式用 ACC 自身 `JwtCodec` 签发演练 token；`session-drill.ps1` 为双 token 会话闭环断言脚本；**非生产代码、不参与构建**）。
- **会话存储装配（L1 修复 + 裁定 R-A8；C1 加严 裁定 R-A11，2026-09-16）**：新增显式开关 **`acc.session.store = memory|redis`（默认 `memory`）**——
  ① 取 `redis` 而 `acc.redis.host` 为空 → **启动 fail-fast**（`IllegalStateException`，提示「acc.session.store=redis 需配置 acc.redis.host（生产会话存储）」），取代原「host 为空即静默退化为内存」的静默降级；
  ② 取 `memory` 而 `acc.redis.host` **已配置** → 同样 **启动 fail-fast**（`IllegalStateException`，提示「检测到 acc.redis.host 已配置但 acc.session.store=memory（默认）：会话存储会退化为进程内实现，登出/踢人将失效。请显式设置 acc.session.store=redis（生产）或清空 acc.redis.host（本地/测试）」）——**C1 补漏**：仅有 R-A8 单向校验时，「配了 Redis host 却漏设 `store=redis`」会照常启动并静默走内存，登出/踢人静默失效（安全洞）；
  ③ 取 `memory` 且 host 为空 → 进程内实现且**绝不触碰 Redis**（本地/测试）；
  ④ 取值非法同样启动失败（拼错不放行）。
  **合法组合只有两个（校验两方向对称）**：`store=redis` + 非空 `acc.redis.host`（生产）、`store=memory` + 空 `acc.redis.host`（本地/测试）。
  **生产必须设 `acc.session.store=redis` + 指向网关同一实例的 `acc.redis.host`**，否则登出/踢人静默失效；该前提已写入 PDD v1.18 §8.4.1、
  网关部署手册 §1、`services/gateway/deploy/docker-compose.yml`（acc 服务 `depends_on: redis(healthy)` + 环境变量）、`services/acc/deploy/Dockerfile`（`ACC_SESSION_STORE=redis` + `ACC_REDIS_HOST` 同设）。
  回归防线：`SessionStoreAssemblyTest` 覆盖 2×2 组合（默认/显式 memory × host 空/非空）+ 非法取值 + fail-closed。
- **真实 Redis 缺陷修复（L4，2026-09-16 会话闭环演练暴露）**：`AccLettuceStringRedisOps.eval` 原用 `ScriptOutputType.VALUE`，
  而 `RedisSessionStore` 的 5 个 Lua 脚本一律 `return 1`（整数回复）→ 真实 Redis 上抛
  `UnsupportedOperationException: ValueOutput does not support set(long)`，登录直接 503 + 5003。已改用 `ScriptOutputType.INTEGER`；
  回归防线 `AccLettuceStringRedisOpsRealRedisTest`（内嵌真实 Redis 上跑真实脚本：建族双键/单次使用/轮换标记/吊销 TTL，先 RED 后 GREEN）。
  教训：会话存储的单测用「回放期望语义」的假客户端，**真实 Lua 行为必须由真实 Redis 用例或真机演练覆盖**。
- **会话闭环真机演练（2026-09-16，任务组 7）**：网关 18081 + 真实 ACC 8080 + 内嵌真实 Redis 6380 双进程，
  `session-drill.ps1` 25 项断言全绿——登录 200（体只含短 token、Cookie 四属性齐备）/ 短 token 业务 200 /
  Cookie 换发 200 且轮换 / 旧 refresh 重放 401+2001 且**整族吊销**（原短 token 立即 401，网关日志 `reason=Token 已吊销`）/
  重新登录 200 / 登出 200 后立即 401；Redis 键路径与 TTL 逐键核验（`acc:refresh:*` ≤ 7 天、`revoked:jti:*` ≤ 短 token 有效期）。
  **ACC `mvn -f services/acc/pom.xml verify -nsu` = 385 用例 0 失败**（基线 381，+2 L1 装配用例 +2 真实 Redis 用例）。
- **C1 加严（裁定 R-A11，2026-09-16）**：`acc.session.store=memory`（含默认）而 `acc.redis.host` 已配置 → **启动 fail-fast**，
  与 R-A8 方向对称（见上「会话存储装配」②）；回归防线 `SessionStoreAssemblyTest` 现覆盖 2×2 组合。
  桩侧口径未变（`AccDrill` 固定 `store=redis` + `host=127.0.0.1`）：先 RED（2 个新用例「Expecting code to raise a throwable」）
  后 GREEN（9/9），全量 `mvn -f services/acc/pom.xml verify -nsu` = **387 用例 0 失败**（基线 385，+2 C1 装配用例）。
  **本波复核（FIX-1）**：该改动由并行代理产出、未提交；本波复跑 `SessionStoreAssemblyTest`=9/9 绿，并补做反向验证
  （把校验临时改回「仅告警」→ `defaultStoreWithConfiguredHostFailsFast`、`storeMemoryWithConfiguredHostFailsFast`
  两条立即 FAIL；改回后 9/9 绿，留档 `.superpowers/sdd/final-fix-wave/c1-red.txt`），已随本波提交入库。
- **A1 修复（最终整体评审 Critical，2026-09-16 修复波 FIX-1）**：族记录寿命曾被**短 token 的到期时刻**污染——
  `FamilyRecord.withAccessJti` 把形参（短 token 到期时刻）同时写进了族记录第 6 个分量 `expiresAtMillis`，
  于是「已轮换标记」与「已吊销族」记录的寿命从 7 天**塌缩为 ≈15 分钟**：轮换 15 分钟后重放旧 refresh
  落入「未知 token」分支，**不整族吊销、不记审计**（spec `acc-session` R3 场景 1 的安全承诺在常见时序下失效）；
  宽限重试路径下族键本身也会 15 分钟后消失（7 天 refresh 随之失效）。
  **改法**：`withAccessJti` 只更新 `accessJtis` 条目，族 `expiresAtMillis` 只由 refresh 有效期决定；
  `RedisSessionStore`/`InMemorySessionStore` 的族键 TTL 一律取**更新后**记录的族到期时刻（原 Redis 实现用更新前的值，是同一污染的传播点）。
  **三条回归防线**：① `SessionFlowTest#familyAndRotationMarkerLifetimeFollowRefreshTtl`（族/标记寿命 = refresh TTL）
  + `#replayLongAfterRotationStillRevokesWholeFamily`（**可注入时钟**推到 >15 分钟后重放 → 仍判重用：族 REVOKED +
  未过期短 token 进 `revoked:jti:*` + 审计事件）；② 端口契约 `AbstractSessionStoreContractTest#bindAccessJtiKeepsFamilyLifetime`
  （两实现同跑：绑定前后族键 TTL 只随时间流逝，且 > 短 token 有效期）；③ 真机演练 `session-drill.ps1` 新增
  `1.5 / 3.4 / 3.5 / 4.6 / 7.4` 断言（族键 TTL ≈ 7 天、族 `expiresAtMillis` 与短 token 到期时刻相差 > 1 天、
  重放后族记录仍 REVOKED 且 TTL 仍 ≈ 7 天）。
- **A2 修复（最终整体评审 Important I1，裁定 R-A15「同源默认放行」）**：`acc.session.allowed-origins` 默认空
  曾等于「拒绝所有带 Origin 的请求」，而浏览器对 POST **一定**发送 `Origin` ⇒ 按原部署件配起来
  **登录可用、第一次换发必 401**（每 15 分钟强制重登）。**改法**：`OriginValidator.isAllowed(origin, referer, requestOrigin)`
  先与**请求自身来源**比对（同源直接放行；`AuthController#requestOrigin` 优先取入口/网关写入的
  `X-Forwarded-Proto/Host/Port`，直连时取请求本身），仅**跨源**才要求命中允许列表；无来源头（curl/移动端/服务间）保持放行；
  给不出请求自身来源时按跨站处置（fail-closed）。默认端口与省略写法等价（`https://a:443` == `https://a`）。
  **回归**：`OriginValidatorTest`（同源放行 / 跨源拒绝 / 无来源头放行 / 端口参与比对 / 无请求上下文 fail-closed）
  + `AuthControllerTest#sameOriginOriginPassesWithoutAllowListConfiguration` 与
  `#sameOriginBehindProxyUsesForwardedOrigin`（含「同样的转发头 + 跨站 Origin 仍拒绝」）。
  **部署口径**：`services/gateway/deploy/README.md` §1 前提表与 `services/gateway/deploy/docker-compose.yml`
  （`ACC_SESSION_ALLOWED_ORIGINS` 默认留空并注明同源无需配置）。
  **R-A16 收口（2026-09-16，Important I1 闭环）**：同源判定的 host 部分**依赖入口保留原始 Host**——
  网关 acc 路由已启用 `PreserveHostHeader`（部署件默认生效，入口按常规 `proxy_set_header Host $host` 即可，
  ACC 由 `Host` 推断出浏览器看到的 host；**链路中若还有其它代理需自行透传 Host**，HTTPS 入口另需
  `X-Forwarded-Proto`，建议同时透传 `X-Forwarded-Host` 作备案）。无此保留时 ACC 只能看到网关改写后的内网
  Host，同源默认放行不会自动生效（正是 I1 的成因，已在网关侧解决）。真机取证见
  `services/acc/deploy/drill/README.md` §3.1 的 3.10/3.11/3.12 与 `.superpowers/sdd/add-refresh-token-rotation/drill3/`。
- **FIX-1 顺修（评审 Minor，2026-09-16）**：
  ① **F5/F6 事务边界防御**：两个 `FilterRegistrationBean` 显式 `setDispatcherTypes(REQUEST)`（不再依赖 Spring Boot
  「是 `OncePerRequestFilter` 就给全部派发类型」的启发式），`RequestSqlSessionHolder.beginRequest()` 对重入**显式拒绝**
  （抛 `IllegalStateException`，防止静默丢弃外层会话/连接）；「提交发生在响应写出之后」（F6）登记进
  `TransactionBoundaryFilter` Javadoc 与 `fix-acc-transaction-boundary/design.md` D6 残留段（与 F4 并列）。
  ② **M1 假证据**：`SessionFlowTest` 的「存储不可用快速失败」原用非法 JWT（触存储前就抛 `AuthException`，断言恒真）——
  改为**合法签名 + 合法 typ** 的 refresh，并 `verify(find)` 证明确实触达存储，另加「非法 token 不触存储」的反向对照。
  ③ **M2 空转用例**：`AbstractSessionStoreContractTest#unavailableStoreFailsFast` 在内存实现下改为
  `Assumptions.abort`（显式跳过，不再「什么也不断言却计为通过」）。
  ④ **M3 死类型**：删除 `ConsumeResult.RetryableRace`（从未构造/匹配）并同步 `SessionFlow#refresh` Javadoc。
  ⑤ **M7 配置误导**：`acc.session.access-token-ttl-seconds` 改为**真正生效**并夹紧到 `[60, 900]`（越界启动 WARN，
  上限 = 网关策略），同一有效值同时驱动**签发**与**族内 jti 绑定**；`SessionView.expiresIn` 随之回报有效值。
  ⑥ **openapi 口径**：前端接口计数由 19 更正为 **18**（本文件、`openapi.yaml` 与 PDD §6.4.1 说明）。
  ⑦ **cookie-secure 守门**：`acc.session.cookie-secure=false` 启动 WARN（写明仅本地/测试、生产必须 true；不做 fail-fast）。
  ⑧ **Redis 淘汰策略**：`docker-compose.yml` 由 `allkeys-lru` 改为 `noeviction`（会话族/refresh/吊销键全带 TTL，
  `volatile-*` 同样会淘汰它们；`revoked:jti:*` 被淘汰 = 登出静默 fail-open），前提表加「会话键不得被淘汰」一行。
  ⑨ **Bearer `typ` 校验**：登出解析 `Authorization` 时要求 `typ=access`（把 refresh 当 Bearer 不再写 7 天冗余吊销键）。
  ⑩ **族记录读写原子性（B11）**：`RedisSessionStore` 的 `bindAccessJti`/`markRevoked`/`rotate` 改为
  **Lua CAS（比较并写入）+ 有界重试**（快照被并发改过即返回 0 → 重读重算；轮换写回前合并最新记录的 `accessJtis`），
  `InMemorySessionStore` 对族记录更新加互斥、轮换同样合并；CAS 重试耗尽即抛 `SessionStoreUnavailableException`
  （fail-closed，绝不静默丢掉 jti 绑定）。回归：端口契约新增「8 线程 × 8 轮并发绑定后族内 jti 无丢失」与
  「轮换按旧快照写回不丢并发绑定的 jti」（两实现同跑）+ `RedisSessionStoreContractTest` 的 CAS 冲突重试取证。
  **验证**：`mvn -f services/acc/pom.xml verify -nsu` 与网关 `verify` 结果见 `.superpowers/sdd/final-fix-report.md`；
  真机演练原始输出见 `.superpowers/sdd/add-refresh-token-rotation/drill2/`。
