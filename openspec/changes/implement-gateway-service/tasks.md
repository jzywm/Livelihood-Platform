# implement-gateway-service · 任务清单

## 1. 口径变更(文档同步)

- [ ] 1.1 更新 PDD v1.15:§3.1 引入时点改「M1 初期交付即接管」、§5.16 标题/定位/5.16.3 演进节奏(删「内嵌 Filter 过渡」、增「网关唯一鉴权点」与 D3 信任模型)、版本史新增 v1.15 行;验证:grep PDD 无「M1 后期独立部署」现行口径残留(版本史保留)
- [ ] 1.2 更新高并发 v0.6:§1 路线图 P1/M1F 时点、§7.2/§7.7 兜底口径(503 快速失败替代直连降级)、ADR-8 结论改写、§10「网关就绪」验收时点改 M1 初期;验证:§7 与 ADR-8 口径一致、无「直连单体降级」残留
- [ ] 1.3 更新 SSOT:§1 表 GATEWAY 里程碑列、§2.15 演进节奏、§4-C14 追加 2026-09-14 变更记录;验证:SSOT 与 PDD/高并发三处口径互洽
- [ ] 1.4 更新 DEVELOPMENT_CONSTRAINTS §1 MUST 句、根 README 服务表与说明注、部署图 03(GATEWAY 双实例提前 M1 初期接入)、GATEWAY README(里程碑/信任模型/实现说明/运维接口)、ACC README 鉴权口径(网关唯一鉴权点+身份头透传);验证:grep「网关」现行口径处均指向 M1 初期接管口径
- [ ] 1.5 更新 `docs/待评审事项汇总.md` G-01/G-02 状态与 add-m1-core-capabilities tasks §9(标注 9.1/9.2 由本变更承接改写);验证:两处引用一致、无「M1 后期独立部署」未决残留

## 2. 网关骨架

- [ ] 2.1 创建 `services/gateway/pom.xml`(Boot 3.5.0 + SCG server-webflux 4.2.x + redis-reactive + R4J circuitbreaker + actuator + prometheus + 测试栈,显式锁版本);验证:`mvn -q dependency:tree` 解析成功、无版本冲突
- [ ] 2.2 创建 `GatewayApplication` + `application.yml`(静态路由指向 acc、白名单、超时分级、Redis 连接、密钥 env 注入)与 `.env.example`;验证:应用可启动、actuator health 返回 UP

## 3. traceId 与统一 Envelope

- [ ] 3.1 实现 TraceIdFilter:X-Request-Id 缺失时兜底生成、注入请求与响应、透传下游;验证:单测覆盖「已有/缺失」两分支,响应头含同一 traceId
- [ ] 3.2 实现全局异常映射与 Envelope 输出(2001/429/503/超时,`_common` ErrorCode 口径);验证:WebTestClient 断言 401/429/503 响应体为统一 Envelope 结构

## 4. 统一鉴权链

- [ ] 4.1 实现 `JwtVerifier`(手写 HS256 验签 + exp 校验 + 常数时间比较,与 JwtCodec.verify 同口径);验证:单测覆盖合法/篡改/过期/格式非法四类
- [ ] 4.2 实现 JwtAuthFilter + Redis 吊销检查 + 白名单跳过 + 身份头注入(X-User-Id/X-User-Role/X-User-Mfa,保留原 Authorization 头);验证:鉴权矩阵单测(合法/吊销/无头/白名单),吊销命中 401+2001

## 5. 网关级限流

- [ ] 5.1 实现 Redis+Lua 令牌桶(IP/账号/接口三级 key,初值:读 1000 req/s/账号、写 100 req/s/账号、AI 10 次/分/账号);验证:内存 Redis 假实现单测断言超限 429、窗口回填后可放行
- [ ] 5.2 实现 RateLimitFilter 装配(资金路径优先级、Redis 故障 fail-closed 503);验证:单测断言 Redis 异常时网关快速失败不静默放行

## 6. 路由与超时

- [ ] 6.1 静态路由配置:业务路径 → acc、`/assist/*` `/aicore/*` 路由位预留、x-external-interfaces 不配路由;验证:集成测试(WireMock 下游)断言转发正确、内部路径 404/不可达
- [ ] 6.2 路由级超时分级(内部 1s / 支付 3s / AI 5s)与超时 503;验证:WireMock 延迟下游断言超时返回 503 且响应为 Envelope

## 7. 熔断与降级

- [ ] 7.1 R4J 网关级熔断装配(失败率/慢调用阈值,半开试探);验证:WireMock 连续失败断言熔断打开后快速失败 503、恢复后半开放行

## 8. 运维接口

- [ ] 8.1 实现 `GET /gateway/health`、`GET /gateway/routes`;验证:返回 liveness/依赖状态与当前路由表,无业务数据
- [ ] 8.2 编写 `services/gateway/docs/openapi.yaml`(仅运维接口,声明无业务接口例外口径);验证:`openspec`/yaml 校验通过、与实现一致

## 9. 测试与门禁

- [ ] 9.1 补齐测试至 jacoco 整体行 ≥80/分支 ≥75 并通过 `mvn verify`(含 `_common` 依赖构建);验证:verify 全绿 + jacoco 报告达标
- [ ] 9.2 提交前走 `commit-check` 技能门禁(DEVELOPMENT_CONSTRAINTS/agent-sdlc 五层门禁);验证:门禁通过、无违规项

## 10. ACC 瘦身(网关唯一鉴权点)

- [ ] 10.1 删除 ACC `AuthFilter`/`RevocationStore`/`NoopRevocationStore` 及装配(保留 JwtCodec 签发、AuthContext、FundsGuard、回调 Hmac 鉴权),新增信任头解析 Filter 组装 AuthContext;验证:ACC `mvn verify` 全绿(改造受影响测试:AuthMatrixTest/AuthFilterTest 迁移为信任头解析测试)
- [ ] 10.2 联调:gateway + acc 双进程,网关验签 → 透传身份头 → ACC 2002 越权校验全链路;验证:合法 token 全链路 200、非法 token 在网关 401、越权在 ACC 403

## 11. 部署形态与切换

- [ ] 11.1 docker-compose 样例(redis + gateway×2 + acc)与 Nginx 配置样例(upstream 指向网关双实例、TLS 终结、灰度 header/cookie/IP/百分比);验证:compose up 后经网关访问 acc 接口成功
- [ ] 11.2 生产切换步骤与回滚方案落地(过渡期双鉴权并存 → ACC 瘦身后下线直连;回滚=双 revert + Nginx 指回);验证:切换/回滚文档与演练步骤可执行

## 12. 验收演练(高并发 §10「网关就绪」提前至 M1 初期)

- [ ] 12.1 五用例演练:路由/鉴权/限流/超时/降级,对照 specs/platform-gateway 全部 Scenario 逐条验证;验证:每场景有演练记录、指标(每路由 QPS/P95/错误率/限流次数)可查
- [ ] 12.2 故障注入:单网关实例宕机(流量切到剩余实例)、双实例全挂(Nginx 503 快速失败)两条路径;验证:两条路径符合 specs「High availability and fast-fail fallback」场景
