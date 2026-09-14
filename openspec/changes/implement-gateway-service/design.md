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

网关验签后注入身份头并转发:`X-User-Id` / `X-User-Role` / `X-User-Mfa`,同时**保留原始 Authorization 头**(过渡期兼容)。ACC 侧:删除 `AuthFilter`、`RevocationStore`、`NoopRevocationStore`;**保留 `JwtCodec`(签发用途,登录/注册签发属账户域职责)**、`AuthContext`、`FundsGuard`(2002 越权,服务内职责)、回调内部 Token 鉴权(`HmacSignatureVerifier`,回调不走网关);新增轻量「信任头解析」Filter 把 X-User-* 组装为 AuthContext(无密码学验证)。服务只从内网 LB 收流量,直连不可达由网络层保证。**备选(否决)**:身份用内部二次签名头——多一跳开销与密钥管理复杂度,M1 不值。

### D4 高可用兜底重定义(取消"直连降级")

双实例 + 健康检查自动摘除;全挂 → Nginx 快速失败 503 + 告警,**不再"Nginx 直连单体降级"**(内嵌 Filter 已移除,无鉴权直连=安全破口;L1 可用性靠冗余,不靠降级)。**备选(否决)**:保留 ACC 兜底 Filter——引入第二套鉴权实现与配置漂移风险,违背"单一权威"裁决。

### D5 Filter 链与错误统一

GlobalFilter 顺序:`TraceIdFilter`(-10)→ `JwtAuthFilter`(0,白名单跳过)→ `RateLimitFilter`(10)→ 路由 → 超时(路由级 1s/3s/5s)→ R4J 熔断 → 全局异常映射。网关自产错误(2001/429/503/超时)统一走 Envelope + traceId(`_common` 依赖);白名单路径(captcha/register/status 等公开接口)配置化,初期 application.yml、M1 后期 Nacos 热更。

### D6 限流与熔断(初值沿用已定档口径)

Redis+Lua 令牌桶,key = `rl:{ip|account|api}:{key}`,原子计数;超限 429 + 友好提示。初值沿用 TBD-3 定档:读 1000 req/s/账号、写 100 req/s/账号、AI 10 次/分/账号(★压测标定);资金链路保护优先级最高。熔断 M1 用 Resilience4j(网关级),Sentinel 网关适配 M2(ADR-5 口径不变)。Redis 故障 → 网关 503 快速失败(吊销/限流 fail-closed,不静默放行)。

### D7 路由(初期静态,后期 Nacos)

M1 初期静态路由:业务路径 → `http://acc:8080`(唯一已实现服务);`/assist/*`、`/aicore/*` 路由位随 Python 服务就绪注册(规范已含,实现留空位);x-external-interfaces 不配路由(天然不可达)。M1 后期切换 Nacos 服务发现 + 配置热更新。灰度:M1 初期维持 Nginx(header/cookie/IP/百分比,口径不变);网关路由权重分流能力实现、M1 后期启用。

### D8 运维接口与文档

`GET /gateway/health`(liveness/依赖状态)、`GET /gateway/routes`(当前路由表),写入新增 `services/gateway/docs/openapi.yaml`(G-02 遗留提前);actuator 仅开 health/prometheus。GATEWAY 无业务库,不设 er.md(不适用 db-design 七章模板,口径不变)。

### D9 测试策略(≥80% 门禁)

单测:WebTestClient 直测三个 GlobalFilter + 路由 + 异常映射(鉴权矩阵/限流/白名单/traceId/Envelope);Redis 依赖用内存假实现(同 acc `InMemoryStringRedisOps` 惯例);集成:WireMock 起下游,验证转发/超时/熔断半开。jacoco 沿用 acc 配置(整体行 ≥80/分支 ≥75);门禁沿用 `commit-check`。

## Risks / Trade-offs

- [网关成为单点安全权威] → 双实例 + 摘除 + 503 快速失败 + Prometheus 告警(P0~P2 分级);密钥不出网关(KMS)。
- [Redis 故障即全网不可用(fail-closed)] → Redis 哨兵/主从(M1 地基已有)承载;网关级故障属 L1 停机预算范围,接受。
- [ACC 鉴权测试改造面(AuthMatrixTest 等)] → tasks 内单列"ACC 瘦身 + 测试迁移"任务,验证以联调用例为准(路由/鉴权/限流/超时/降级五用例)。
- [与 ADR-8 定档冲突] → 显式作为"定档变更"记录在 SSOT §4-C14 追加变更行 + 待评审事项汇总 G-01 状态更新,不静默改口径。
- [WebFlux 反应栈与既有 servlet 栈并存] → 网关独立进程部署,栈隔离,无冲突;网关依赖仅 `_common`(纯 POJO 无 servlet 耦合)。

## Migration Plan

1. **阶段 1 口径变更**:9 处文档同步(见 proposal Impact),评审通过后进入代码阶段。
2. **阶段 2 网关落地**:`services/gateway/` pom + 源码 + 测试,`mvn verify` 全绿(独立于 ACC,不侵入)。
3. **阶段 3 过渡联调**:网关部署、Nginx upstream 切到网关,此时 ACC 内嵌 Filter 仍在(网关转发保留 Authorization 头,双鉴权并存仅过渡期),观察验签失败率/限流指标。
4. **阶段 4 ACC 瘦身**:删除 ACC 验签三件套 + 新增信任头解析,`mvn verify` 全绿后发布;随后下线 Nginx 直连路径。
5. **回滚**:阶段 3 期间 → Nginx 指回 ACC(一分钟级,内嵌 Filter 兜底);阶段 4 后 → 双 revert(ACC 改造 revert + Nginx 指回 ACC),不做"网关故障直连"路径(503 兜底为常态口径)。

## Open Questions

- 六方角色枚举在 X-User-Role 头中的具体取值与 ACC AuthContext 映射细节(实施阶段 4 时对齐,不影响规格与任务分解)。
- KMS 注入的开发/测试环境形态(env 密钥起步、生产 KMS,已定口径,接入方式实施时定)。
- 白名单最终路径清单(实施时按各服务 openapi 公开接口收敛,配置可热更,不阻塞)。
