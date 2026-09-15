# implement-gateway-service

## Why

GATEWAY 是平台唯一统一入口,但当前 `services/gateway/` 仅有文档基线(README)、无任何代码,实施顺序排在全部业务域之后(M1 后期,add-m1-core-capabilities tasks §9),而网关级鉴权职责目前以「内嵌 Filter」形态散落在 `services/acc/infrastructure/auth/`。用户裁决(2026-09-14):**网关微服务先做**、把项目中所有接入层网关内容写入该微服务、优先级提到 M1 初期交付即接管。本变更将 GATEWAY 从「M1 后期独立部署」提前为「M1 初期交付即接管统一入口」,并以能力规范固化其行为。

## What Changes

- **优先级提高(里程碑口径变更)**:GATEWAY 里程碑由「M1 后期独立部署(M1 初期内嵌 Filter + Nginx 过渡)」改为「**M1 初期交付即接管统一入口**」;实施顺序提前到全部业务域之前(与 ACC 并行、先于 CRED/EMP/TICKET/TRACE)。涉及 PDD §3.1/§5.16、高并发 §1/§7/ADR-8/§10、SSOT §1/§2.15/§4-C14、DEVELOPMENT_CONSTRAINTS §1、根 README、部署图 03、GATEWAY README。
- **新增 `services/gateway/` 代码**(Java 17 + Spring Boot 3.5 + Spring Cloud Gateway WebFlux + Redis Reactive + Resilience4j):路由转发、traceId 注入、JWT 验签 + Redis 吊销、IP/账号/接口三级限流(Redis+Lua 令牌桶)、超时分级、网关级熔断、统一 Envelope(2001/429/503)、运维接口(health/routes)。
- **网关唯一鉴权点(信任模型变更)**:ACC 删除 AuthFilter/JwtCodec/RevocationStore,信任网关透传身份头,保留 FundsGuard(2002 越权)与内部回调 Token 鉴权。**BREAKING**:内网直连 ACC 不再自带鉴权——兜底口径由「GATEWAY 故障 → Nginx 直连单体降级」改为「GATEWAY 双实例冗余 + 故障摘除,故障期 Nginx 快速失败 503」。
- **新增运维接口 openapi.yaml**(G-02 遗留项提前到 M1 初期):`GET /gateway/health`、`GET /gateway/routes`。
- **不迁移清单(明确范围)**:① AI 网关底座 K-02(模型路由)留在 AICORE(Python,分层不同,C14 定档不变);② `services/acc/infrastructure/gateway/*` 通道网关(支付/实名通道适配器,S5 端口)不属于接入层网关,不迁不动;③ `_common` 的 Envelope/ErrorCode/traceId 公共口径留在 `services/_common/`(网关引用,不复制)。
- 非目标(Non-Goals):Sentinel 网关适配与控制台(M2,ADR-5 口径不变)、Nacos 服务发现(M1 后期,初期静态路由直连 ACC)、K8s 金丝雀(M2)、AI 网关 K-02 并入、协议聚合(BFF)。

## Capabilities

### New Capabilities

- `platform-gateway`:平台统一入口网关(路由转发与双语言转发、统一鉴权链 JWT 验签 + Redis 吊销、网关级限流 IP/账号/接口、超时分级与熔断降级、traceId 注入透传、统一 Envelope、运维接口、高可用与故障快速失败兜底)。

### Modified Capabilities

(无——`openspec/specs/` 当前为空,无既有主能力规范需修改;add-m1-core-capabilities 的 delta 规范未覆盖网关行为。)

## Impact

- **代码**:新增 `services/gateway/`(pom.xml + src + docs/openapi.yaml);改造 `services/acc`(删除 auth Filter 三件套,新增身份头解析,调整 AuthMatrixTest 等鉴权相关测试);`services/_common` 仅增补 2004/5003 错误码(ErrorCode + openapi.yaml 同步),Envelope/traceId 口径不动。
- **文档口径同步**(约 9 处):PDD v1.14→v1.15(§3.1/§5.16/版本史)、高并发 v0.5→v0.6(§1/§7/ADR-8/§10)、SSOT(§1/§2.15/§4-C14 追加变更记录)、DEVELOPMENT_CONSTRAINTS §1 MUST 句、根 README、部署图 03、GATEWAY README 升级、ACC docs README 鉴权口径、待评审事项汇总 G-01/G-02 状态更新。
- **外部依赖**:Redis(JWT 黑名单 + 限流计数,M1 地基已有)、KMS(JWT 签名密钥注入,密钥不出网关);Nacos 不提前(M1 后期)。
- **验证门禁**:单测覆盖率 ≥80%(DEVELOPMENT_CONSTRAINTS MUST);路由/鉴权/限流/超时/降级五用例演练 + ACC 联调;提交前走 commit-check 门禁。
