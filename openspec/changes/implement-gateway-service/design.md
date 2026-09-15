# implement-gateway-service · 设计文档

## Context

- 动机见 proposal.md - Why(用户裁决:网关先做、内容全集写入、优先级提高)。
- 现状:① `services/gateway/` 仅 `docs/README.md`(职责全集,PDD §5.16/高并发 §7 已收敛),无 pom/代码;② 网关级鉴权以「内嵌 Filter」形态存在于 `services/acc/infrastructure/auth/`(AuthFilter/JwtCodec/RevocationStore,手写 HS256、不引 JWT 库);③ `_common` 已有 Envelope/ErrorCode/traceId 口径(网关引用,不复制);④ ACC 是 M1 唯一已实现服务(Spring Boot 3.5、无 parent POM 显式锁版本、jacoco 行 80/分支 75 门禁);⑤ Nacos 按现行口径 M1 后期才引入。
- 约束:DEVELOPMENT_CONSTRAINTS §1(GATEWAY = Java 17 + SCG)、测试覆盖率 MUST ≥80%、依赖版本锁定入库、ADR-8/C14 为已定档决策(本次改写需走评审口径记录)。

## Goals / Non-Goals

**Goals:**

- GATEWAY 在 M1 初期**交付即接管**统一入口,成为平台唯一鉴权权威;
- 网关职责全集(路由/鉴权链/限流/超时熔断/traceId/Envelope/运维接口/高可用)在 `services/gateway/` 内完整落地,可独立构建、测试、部署;
- ACC 瘦身为"信任网关身份头 + 2002 越权校验"形态,不留第二套 JWT 验签实现。

**Non-Goals:**

- 不引入 Nacos(M1 后期)、Sentinel(M2)、K8s 金丝雀(M2);不做 BFF 协议聚合;不迁 K-02 AI 网关与 ACC 通道网关(见 proposal 不迁移清单);不改 `_common` 公共组件。

## Decisions

### D1 里程碑与口径改写(定档变更)

GATEWAY 里程碑由「M1 后期独立部署」改为「**M1 初期交付即接管**」;实施顺序提到全部业务域之前。同步改写:PDD §3.1/§5.16(v1.15)、高并发 §1/§7/ADR-8/§10(v0.6)、SSOT §1/§2.15/§4-C14、DEVELOPMENT_CONSTRAINTS §1、根 README、部署图 03、GATEWAY README、ACC README。**备选(否决)**:只提前实施顺序不动里程碑——口径与事实不符,评审链仍按"M1 后期"验收。ADR-1「先单体后拆分」针对业务域,不受影响;ADR-8 结论改写为"GATEWAY 作为基础设施横切服务先行"。

### D2 技术栈形态(与仓库惯例一致)

`services/gateway/pom.xml` 沿用仓库「无 parent、显式锁版本」惯例:Spring Boot 3.5.0 + `spring-cloud-gateway-server-webflux`(4.2.x,WebFlux 反应栈)+ `spring-boot-starter-data-redis-reactive`(吊销/限流)+ `spring-cloud-starter-circuitbreaker-reactor-resilience4j`(3.1.x,网关级熔断)+ actuator + `micrometer-registry-prometheus`(每路由 QPS/P95/错误率/限流次数)+ 测试栈(JUnit 5/AssertJ/Mockito/WireMock,与 acc 一致)。**JWT 不引库**:网关内实现 `JwtVerifier`(HS256 验签 + exp 校验 + 常数时间比较,与 `JwtCodec.verify` 同口径)——维持"手写不引库"的 SEC 口径,密钥单一把、KMS 注入、网关内验签不出网。

### D3 信任模型(网关唯一鉴权点)

网关验签后注入四头身份头并转发:`X-User-Id` / `X-User-Role` / `X-User-Mfa` / `X-User-Jti`(与 ACC AuthContext 四字段一一对应),同时**保留原始 Authorization 头**(过渡期兼容)。ACC 侧:删除 `AuthFilter`、`RevocationStore`、`NoopRevocationStore`;**保留 `JwtCodec`(签发用途,登录/注册签发属账户域职责)**、`AuthContext`、`FundsGuard`(2002 越权,服务内职责)、回调内部 Token 鉴权(`HmacSignatureVerifier`,回调不走网关);改为 `TrustedHeaderAuthFilter`(读 X-User-* 组装 AuthContext,无密码学验证;缺身份头 → 401 fail-closed)。服务只从内网 LB 收流量,直连不可达由网络层保证。**备选(否决)**:身份用内部二次签名头——多一跳开销与密钥管理复杂度,M1 不值。

**吊销写入方契约(评审 I7)**:网关只读、不写吊销名单;写入方为**签发侧**(账户域登录/登出/踢下线流程),键格式与 TTL 约定:
```
SET revoked:jti:{jti} 1 PX <token 剩余有效期毫秒>
```
网关在验签通过后查 `EXISTS revoked:jti:{jti}`(Redis 不可用时 fail-closed 503+5003)。
**当前状态**:ACC 暂无登出/踢下线接口(登录签发接口随 M1 登录页落地),故 M1 初期吊销链路「读侧已就绪、写侧待接口」;新增登出接口属**接口清单变更**(需同步 `services/acc/docs/openapi.yaml` 权威源与前端 `packages/api-client`),随账户域登录/登出功能一并交付,不在此变更内臆造接口。过渡期(网关接管但登出未上线)风险可控:token 时效短(概要初值),到期即失效。

### D4 高可用兜底重定义(取消"直连降级")

双实例 + 健康检查自动摘除;全挂 → Nginx 快速失败 503 + 告警,**不再"Nginx 直连单体降级"**(内嵌 Filter 已移除,无鉴权直连=安全破口;L1 可用性靠冗余,不靠降级)。**备选(否决)**:保留 ACC 兜底 Filter——引入第二套鉴权实现与配置漂移风险,违背"单一权威"裁决。

### D5 Filter 链与错误统一

GlobalFilter 顺序(实现口径,`FilterOrderTest` 锁定):`RequestSanitizerFilter`(**-20**,入口净化,见 D13)→ `TraceIdFilter`(-10)→ `JwtAuthFilter`(0,白名单跳过)→ `InternalPathGuardFilter`(5,内部接口 404)→ `RateLimitFilter`(10)→ `TimeoutFilter`(100,`metadata.timeout` 分级)→ 路由过滤器(RewritePath 等,**先于 order 5/10 执行**,故路径判断统一读 `RequestPaths` 落盘的「改写前原始路径」)→ R4J 熔断(按路由命名实例,见 D14)。

网关自产客户端错误(401/404/429)经 `EnvelopeResponses` **直接写出响应短路**(见 D12);基础设施类错误(超时/Redis 不可用)仍以异常抛出 → `GatewayErrorWebExceptionHandler` 统一 Envelope + traceId(错误码 2001/2004/3006/5000/5002/5003,见 D10)。白名单精确为三个公开接口且**段边界匹配**(`/registerAny` 不蹭白名单);内部接口经 `gateway.internal-paths` 前缀守卫拦截(见 D13——SCG 4.3 路由定义不支持 negate 谓词,原「不配路由」口径改为「广路由 + 显式守卫」)。

### D6 限流与熔断(初值沿用已定档口径)

Redis+Lua 令牌桶,key = `rl:{ip|account|api}:{key}`,原子计数;超限 429 + 友好提示。初值沿用 TBD-3 定档:读 1000 req/s/账号、写 100 req/s/账号、AI 10 次/分/账号(★压测标定);资金链路保护优先级最高。熔断 M1 用 Resilience4j(网关级),Sentinel 网关适配 M2(ADR-5 口径不变)。Redis 故障 → 网关 503 快速失败(吊销/限流 fail-closed,不静默放行)。

### D7 路由(初期静态,后期 Nacos)

统一入口与重写:`/api/v1/{svc}/**` 经路径重写为 `/{svc}/**` 后转发(ACC 控制器真实路径 `/acc/...` 无 `/api/v1` 前缀,已核实;见 D11/F1)。M1 初期静态路由:业务路径 → `http://acc:8080`(可用 `${GATEWAY_ACC_URI}` 覆盖);`/assist/*`、`/aicore/*` 路由位随 Python 服务就绪注册(规范已含,实现留空位);内部接口不单独配路由,由 `InternalPathGuardFilter` 按 `gateway.internal-paths` 前缀拦截(见 D13)。M1 后期切换 Nacos 服务发现 + 配置热更新。灰度:M1 初期维持 Nginx(header/cookie/IP/百分比,口径不变);网关侧 `metadata.weight` 键位预留,权重分流 M1 后期启用(见 F6)。

### D8 运维接口与文档

`GET /gateway/health`(liveness/依赖状态)、`GET /gateway/routes`(当前路由表),写入新增 `services/gateway/docs/openapi.yaml`(G-02 遗留提前);actuator 仅开 health/prometheus。GATEWAY 无业务库,不设 er.md(不适用 db-design 七章模板,口径不变)。

### D9 测试策略(≥80% 门禁)

单测:WebTestClient 直测三个 GlobalFilter + 路由 + 异常映射(鉴权矩阵/限流/白名单/traceId/Envelope);Redis 依赖用内存假实现(同 acc `InMemoryStringRedisOps` 惯例);集成:WireMock 起下游,验证转发/超时/熔断半开。jacoco 沿用 acc 配置(整体行 ≥80/分支 ≥75);门禁沿用 `commit-check`。

### D10 网关错误码增补(权威源同步)

`_common` 现有错误码无「限流 / 网关不可用」(已核实无撞码):新增 `2004 RATE_LIMITED`(429「请求过于频繁」)与 `5003 GATEWAY_UNAVAILABLE`(503「网关暂不可用」);验签失败复用 `2001`、超时/熔断复用 `5002`。同步 `services/_common/openapi.yaml`(错误码权威源,口径不变)。**备选(否决)**:限流复用 2002/5002——语义混淆,破坏错误码分段约定(2xxx 鉴权、5xxx 系统)。

### D11 路径重写口径

统一入口 `api.example.com/api/v1/{svc}/…` 与服务内真实路径(如 `/acc/me`)不一致——网关统一重写 `/api/v1/{svc}` 前缀后转发(详 F1);服务内路径保持现状不动,避免全服务改映射。

## 功能实现设计(按网关职责逐个功能)

> 本章把 D1~D11 落为每个功能的实现细节:包结构、关键类、配置键、边界用例。包结构:`com.msz.gateway.{config,filter,auth,ratelimit,error,ops}`,resources 含 `application.yml`、`lua/rate-limit.lua`。

### F1 路由转发

- RouteLocator 配置驱动:`gateway.routes[].{id,path,uri,timeout,weight}`;谓词 Path=`/api/v1/acc/**` → uri `http://acc:8080`;`/api/v1/assist/**`、`/api/v1/aicore/**` 路由位预留(uri 占位,Python 服务就绪后启用)。
- 重写:`RewritePath=/api/v1/(?<svc>.*), /${svc}`(等价 StripPrefix=2);校验:网关收到 `/api/v1/acc/me` 转发到 `http://acc:8080/acc/me`。
- 不配路由:`/acc/internal/**`、`/acc/realname/callback` 无任何 Route → 网关 404(天然不可达)。
- 边界用例:未知服务前缀 → 404 Envelope;路由配置缺失/非法 → 启动校验失败(fail-fast)。

### F2 鉴权链

- `JwtVerifier.verify(token, secret) → Map<String,Object> claims`,失败抛 `AuthException`(口径同 `JwtCodec.verify`:格式非法/验签失败/过期统一 401+2001,不泄露失败细节)。
- `JwtAuthFilter`(order 0):白名单跳过 → Bearer 校验 → jti 吊销检查(Redis key `revoked:jti:{jti}`,短 TTL=JWT 剩余有效期)→ 注入四头:`X-User-Id`(sub)/`X-User-Role`(role)/`X-User-Mfa`(mfa)/`X-User-Jti`(jti),保留原 Authorization 头。
- 白名单(配置 `gateway.auth.whitelist`):`/api/v1/acc/captcha`、`/api/v1/acc/register`、`/api/v1/acc/realname/status`。
- 边界用例:无头/非 Bearer/篡改/过期/吊销 → 401+2001;白名单无 token → 放行;多值头取首个;Redis 吊销查询失败 → fail-closed 503(5003,同 F3)。

### F3 限流

- key:IP=`rl:ip:{ip}`、账号=`rl:acc:{tier}:{sub}`(验签通过才有)、接口=`rl:api:{tier}:{method}:{svcPath}`;`svcPath` 中路径变量(纯数字/UUID/长十六进制)归一为 `{id}`,防「换 ID」绕过接口级桶(评审 I10)。
- **算法口径(评审 I1)**:Redis+Lua **固定窗口计数**(`INCR` + `PEXPIRE` 原子判定),非严格令牌桶;令牌桶形态待 M2 Sentinel 全量(ADR-5 口径不变)。脚本 `lua/rate-limit.lua`:超限返回 0 → 429 + 2004。
- 初值(`gateway.rate-limit.*`):读 1000/s/账号、写 100/s/账号、AI(路径前缀 `/assist` `/aicore`)10/min/账号;IP 级 200/s(过渡值,压测标定);资金路径(`/api/v1/settle/**`、`/api/v1/acc/funds/**`)独立桶,保护优先级最高。
- 客户端 IP 信任边界(评审 I13):`gateway.rate-limit.trust-forwarded-for`(默认 true,仅入口只有可信代理时保持);取 XFF **链尾**;置 false 时改用 TCP 对端地址。
- 降级:Redis 不可用 → fail-closed 503(5003),不静默放行。

### F4 超时与熔断

- 超时:路由级 `gateway.routes[].timeout`——内部 1s、支付(`/api/v1/settle/**`)3s、AI(`/api/v1/assist|aicore/**`)5s;超时 → 503 + 5002。
- 熔断:R4J `CircuitBreaker` 过滤器,滑动窗口 10s、失败率 ≥50% 打开、半开允许 5 次试探、恢复探测间隔 12s;熔断中 → 快速失败 503 + 5002。

### F5 traceId 与统一 Envelope

- 头:`X-Request-Id`;缺失 → UUID 兜底(与 acc `TraceIds` 同口径);注入请求与响应,下游日志串链。
- Envelope:五字段 code/message/data/traceId/timestamp,复用 `_common` Envelope/ErrorCode;网关自产错误统一经 `GlobalErrorWebExceptionHandler` 输出,禁用默认 whitelabel。

### F6 灰度分流

- M1 初期:维持 Nginx header/cookie/IP/百分比分流(口径不变)。
- 网关侧:`gateway` 路由 `metadata.weight` **键位已预留**(默认全量 100);按权重分流的多实例逻辑 **M1 后期随 Nacos 配置热更启用**(评审 I15:`metadata.weight` 为占位,当前无 Weight 谓词/多目标分流实现)。

### F7 运维接口

- `GET /gateway/health`:status(UP/DOWN)、redis(连通状态)、version、instanceId;DOWN 时 HTTP 503(供 LB 摘除)。
- `GET /gateway/routes`:id/order/path/uri(脱敏,不含内网明文凭据)/timeout/weight 摘要数组。
- **访问控制(评审 I8)**:运维接口不经网关过滤器链(由网关自身 Controller 处理、不参与业务路由),故访问控制独立声明——`gateway.ops.allowed-networks`(默认回环 + 私有网段),非内网来源统一 404;对外入口 Nginx 亦不暴露 `/gateway/**`。
- openapi.yaml:两接口 + Envelope/ErrorCode(2001/2004/3006/5000/5002/5003)引用(`_common` 权威源)。

### F8 配置总表(评审 I2:与实现对齐)

| 键 | 说明 | 初值 |
|---|---|---|
| `spring.cloud.gateway.server.webflux.routes[].{id,uri,predicates,filters,metadata.timeout,metadata.weight}` | 路由表(SCG 原生键位;路由目标可用占位符 env 覆盖,如 `${GATEWAY_ACC_URI}`) | acc:1s/100 |
| `gateway.store` | 存储模式 | `redis`(生产)/`memory`(开发兜底) |
| `gateway.auth.whitelist` | 公开路径(段边界匹配) | 三路径(见 F2) |
| `gateway.auth.jwt-secret` | HS256 密钥 | env `GATEWAY_JWT_SECRET`(生产 KMS 注入,不出网关) |
| `gateway.auth.access-token-max-ttl` | 短 token(access)有效期**上限**;网关只认短 token,超长一律 401+2001 | `15m`(env `GATEWAY_ACCESS_TOKEN_MAX_TTL`) |
| `gateway.auth.clock-skew` | 有效期上限的时钟容差(**不放宽过期判定**) | `60s`(env `GATEWAY_CLOCK_SKEW`) |
| `gateway.internal-paths` | 网关不可达的内部接口前缀 | acc internal / realname callback |
| `gateway.ops.allowed-networks` | 运维接口来源网段白名单 | 回环 + 私有网段 |
| `gateway.rate-limit.{ip,read,write,ai,funds}.{capacity,window-seconds}` | 三级 + 资金桶初值 | 200/s、1000/s、100/s、10/min、100/s |
| `gateway.rate-limit.trust-forwarded-for` | 是否信任 XFF 链尾为客户端 IP | `true`(仅入口为可信代理时) |
| `gateway.version` / `gateway.instance-id` | 运维标识(health 返回) | `GATEWAY_VERSION` / `GATEWAY_INSTANCE_ID` |
| `resilience4j.circuitbreaker.configs.default.*` | R4J 参数(`minimumNumberOfCalls` 必须显式配) | 时间窗 10s / 失败率 50% / 半开 5 / 恢复 12s / 最小调用 4 |
| `spring.data.redis.{host,port,username,password,timeout,connect-timeout}` | 吊销/限流存储(支持 AUTH) | 环境注入;超时 2s/1s |
| `management.endpoints.web.exposure.include` | 指标端点 | `health,prometheus` |

### D12 客户端错误短路写出(实现期新增)

401/404/429 由过滤器经 `EnvelopeResponses` 直接写出响应,**不抛异常**:网关级熔断(CircuitBreaker 过滤器)会把链上任何异常视为下游失败并转入 fallback,若客户端错误走异常路径,4xx 将被误报为 5xx 降级(503+5002)并污染熔断统计。基础设施类错误(路由超时、Redis 不可用)仍抛异常——超时/连接失败计入熔断统计是期望行为。**测试锁定**:每个 fail-closed 用例均含「链上不挂错误处理器仍返回 5003」的短路断言。

### D13 入口净化与内部接口守卫(实现期新增)

- `RequestSanitizerFilter`(order **-20**,链最前端):① **无条件剥离客户端自带的 `X-User-Id/Role/Mfa/Jti`**(含白名单与未命中路由的请求)——网关是唯一鉴权点,服务内只信任网关写入的身份头;② **路径规范化**:拒绝含 `/./`、`/../`、`//`、`%2e` 的入口(404),并把规范化后的路径落盘供下游判断——WebFlux `getPath()` 保留这些形态而 SCG `Path` 谓词仍命中路由,不规范化则内部接口守卫与白名单边界可被绕过;
- `InternalPathGuardFilter`(order 5,读规范化路径 + **段边界匹配**):命中 `gateway.internal-paths` 即 404+3006;因 SCG 4.3 路由定义**不支持 negate 谓词**(yml `negate` 被静默忽略、`args.patterns` 列表被摊平为索引键),「内部接口不配路由」无法用声明式实现,故改为显式守卫;
- 身份头写入同时做 remove-then-set(纵深防御);白名单/内部路径均段边界匹配,`/registerAny`、`/api/v1/acc/internalX` 不会被误放行。

### D14 熔断实例与运维接口访问控制(实现期新增)

- **熔断实例按路由命名**(当前 `accCircuitBreaker`,路由级 filters 声明):避免任一后端劣化打开全路由熔断;
- **运维接口访问控制**:`/gateway/**` 由网关自身 Controller 处理、不经过滤器链,故访问控制独立声明 `gateway.ops.allowed-networks`(默认回环 + 私有网段),非内网来源统一 404;对外入口 Nginx 不暴露该前缀(部署样例已含);原白名单中的 `/gateway/` 条目为无效配置,已移除;
- **其他加固**:JWT 硬校验 `alg=HS256`(防算法混淆;**`sub` 必填 + `exp` 上界校验已随 D15 落地**)、traceId 客户端值需匹配 `[A-Za-z0-9._-]{1,64}`(防日志投毒)、降级端点仅接受网关内部回退请求(外部直访 404)、Redis 连接支持 AUTH 且命令/连接超时有界(2s/1s,故障快速 fail-closed)。

### D15 令牌与会话策略:双 token(2026-09-15 用户裁决,审查 I9 收口)

- **短 token(access)= 15 分钟**:`Authorization: Bearer` 走业务链路,由网关校验。网关新增两条硬校验:① `sub` 必须存在且非空白(否则下游收到空身份、鉴权点失守);② `exp` 必须存在、未过期,**且不超过 `access-token-max-ttl`(15m)+ `clock-skew`(60s)**——超出即 401+2001。意义:签名密钥泄漏时爆炸半径受 clock-skew 上限约束,而不是"签发方自律";容差只用于放宽上限判定,**过期判定保持严格**(不给过期 token 额外存活期)。
- **长 token(refresh)= 7 天**:存 **HttpOnly + Secure + SameSite** Cookie,**不经网关业务链路**,只用于换发短 token。网关侧因此不解析 Cookie、不为其开放业务白名单位。
- **落地边界(重要)**:本次只落地**校验侧**(网关策略 + 配置键 + 用例 + 真机实证)。**换发(refresh)接口尚未实现**——M1 尚无登录接口,新增 `/acc/auth/**` 属**接口清单变更**(需 openapi 权威源 + 前端 api-client 同步),已登记 `docs/待评审事项汇总.md`;换发端点将来需要:白名单位(无有效短 token 时仍可通过网关)、HttpOnly Cookie 属性、CSRF/Origin 校验(敏感写请求非 Cookie 鉴权)。
- **配置绑定陷阱(实现期踩坑,已固化)**:`@ConfigurationProperties` 的记录绑定**只允许唯一构造器**;给嵌套记录 `Auth` 加第二构造器会让 Spring 找不到绑定入口,实测 `gateway.auth` 整段绑定为 `null`(12 个上下文用例同时变红)。缺省值改用**静态工厂** `Auth.of(whitelist, jwtSecret)` + 紧凑构造器归一 null。

### D16 真机联调(任务组 10.2)发现并修复 ACC 数据层缺陷

- **联调形态**:`services/acc/deploy/drill/AccDrill.java` 以嵌入式 MariaDB(mariaDB4j)+ Flyway + `@Primary` 真实 DataSource 启动**真实 ACC 进程**,与网关 fat jar 组成双进程,链路为 `curl → 网关(鉴权/限流/熔断/改写) → ACC → MyBatis → MariaDB`——此前 Node 下游桩只能证明转发,不能证明 SQL 与字段加解密。
- **发现缺陷(ACC,非网关切面)**:6 个 Mapper Bean 原为 `factory.openSession().getMapper(...)`,会话长驻、`autoCommit=false`、事务永不提交,真实库下三症状:①读陈旧(外部已提交的 `wallet_status` 查不到)②写不落库(`POST /acc/account/close` 返 200 但 `closed_at` 仍 NULL)③持锁阻塞外部写入(`Lock wait timeout exceeded`,约 50s)。
- **修复**:改为 `factory.openSession(true)`(自动提交,与 DAO 测试同口径),新增 `config.RealDbAssemblyTest`(真实库 + 真实 Tomcat + 真实 HTTP)锁死两条回归;反向验证:临时改回原实现,该测试立刻 1 Failure + 1 Error。
- **残留限制(已登记 → 已承接)**:会话仍为长驻(非按请求),跨表写入无原子性、无事务边界,原计划 M2 收敛为「按请求会话 + 显式事务边界」;`services/acc/docs/README.md` 已记录。**该三项残留已由 `fix-acc-transaction-boundary` 承接并于 2026-09-15 落地**(session-per-request + 请求级事务边界,提前至 M1,`implement-gateway-service` tasks §14.3 因此关闭)。
- **依赖修正**:`services/acc/pom.xml` 钉 `jakarta.annotation-api:2.1.1`(test 作用域 mariaDB4j 传递 1.3.5 抢占调解 → Web 容器启动 `NoClassDefFoundError`)。

## Risks / Trade-offs

- [网关成为单点安全权威] → 双实例 + 摘除 + 503 快速失败 + Prometheus 告警(P0~P2 分级);密钥不出网关(KMS)。
- [Redis 故障即全网不可用(fail-closed)] → Redis 哨兵/主从(M1 地基已有)承载;网关级故障属 L1 停机预算范围,接受。
- [ACC 鉴权测试改造面(AuthMatrixTest 等)] → tasks 内单列"ACC 瘦身 + 测试迁移"任务,验证以联调用例为准(路由/鉴权/限流/超时/降级五用例)。
- [与 ADR-8 定档冲突] → 显式作为"定档变更"记录在 SSOT §4-C14 追加变更行 + 待评审事项汇总 G-01 状态更新,不静默改口径。
- [WebFlux 反应栈与既有 servlet 栈并存] → 网关独立进程部署,栈隔离,无冲突;网关依赖仅 `_common`(纯 POJO 无 servlet 耦合)。

## Migration Plan

1. **阶段 1 口径变更**:9 处文档同步(见 proposal Impact)——**已完成**(2026-09-15,PDD v1.16 / 高并发 v0.7 / SSOT v1.7 / CONSTRAINTS / 根 README / 部署图 01~03 / GATEWAY README v1.1 / 待评审汇总 G-01/G-02)。
2. **阶段 2 网关落地**:`services/gateway/` pom + 源码 + 测试,`mvn verify` 全绿——**已完成**(**139 用例**,jacoco 行 ≥80/分支 ≥75,可执行 fat jar;令牌策略用例见 D15)。
3. **阶段 3 过渡联调**:网关部署、Nginx upstream 切到网关;**过渡期 ACC 内嵌 Filter 保留**(网关转发保留原 `Authorization` 头,双鉴权并存无冲突),观察验签失败率/限流指标;切换清单见 `services/gateway/deploy/README.md`(13 项验证)。**真机双进程联调已完成**(任务组 10.2,见 D16):网关 18081 + 真实 ACC 8080 + 真实 MariaDB 33061。
4. **阶段 4 ACC 瘦身**:删除 ACC 验签三件套 + 新增信任头解析(FundsGuard 2002 与回调 Hmac 保留),`mvn verify` 全绿后发布;随后下线 Nginx 直连路径。**已完成**(ACC **253 用例**全绿,含新增真实库装配回归测试)。
5. **回滚**:阶段 3 期间 → Nginx 指回原入口(分钟级);阶段 4 后 → 双 revert(ACC 改造 revert + Nginx 指回)。**不做「网关故障直连」路径**:网关全部实例不可用时入口快速失败 503(无鉴权直连=安全破口,可用性靠双实例冗余)。

## Open Questions

- 六方角色枚举在 X-User-Role 头中的具体取值与 ACC AuthContext 映射细节(实施阶段 4 时对齐,不影响规格与任务分解)——**已对齐**:网关透传 `X-User-Id/Role/Mfa/Jti`,ACC `TrustedHeaderAuthFilter` 组装 `AuthContext`(真机联调实测)。
- KMS 注入的开发/测试环境形态(env 密钥起步、生产 KMS,已定口径,接入方式实施时定)。
- 白名单最终路径清单(实施时按各服务 openapi 公开接口收敛,配置可热更,不阻塞)。
- **换发(refresh)接口落地形态**(D15):路径命名(`/acc/auth/refresh`?)、Cookie 属性取值(SameSite=Lax/Strict)、是否经网关白名单、轮换与重放防护——属接口清单变更,需先确认再实现。
