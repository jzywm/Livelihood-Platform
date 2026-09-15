# implement-gateway-service · 任务清单

## 1. 口径变更(文档同步)

- [x] 1.1 更新 PDD v1.15:§3.1 引入时点改「M1 初期交付即接管」、§5.16 标题/定位/5.16.3 演进节奏(删「内嵌 Filter 过渡」、增「网关唯一鉴权点」与 D3 信任模型)、版本史新增 v1.15 行;验证:grep PDD 无「M1 后期独立部署」现行口径残留(版本史保留)——实际落为 **PDD v1.16 行**(v1.15 已被骑手端占用),§2.4/§3.1/§5 引言/§5.16/§6.2/§6.4 同步
- [x] 1.2 更新高并发 v0.6:§1 路线图 P1/M1F 时点、§7.2/§7.7 兜底口径(503 快速失败替代直连降级)、ADR-8 结论改写、§10「网关就绪」验收时点改 M1 初期;验证:§7 与 ADR-8 口径一致、无「直连单体降级」残留——实际落为 **v0.7 行**(含 §4.1 限流口径改固定窗口计数)
- [x] 1.3 更新 SSOT:§1 表 GATEWAY 里程碑列、§2.15 演进节奏、§4-C14 追加 2026-09-14 变更记录;验证:SSOT 与 PDD/高并发三处口径互洽——实际落为 **v1.7 行** + §2.15 数据归属/演进节奏 + C14 变更记录(2026-09-15)
- [x] 1.4 更新 DEVELOPMENT_CONSTRAINTS §1 MUST 句、根 README 服务表与说明注、部署图 03(GATEWAY 双实例提前 M1 初期接入)、GATEWAY README(里程碑/信任模型/实现说明/运维接口)、ACC README 鉴权口径(网关唯一鉴权点+身份头透传);验证:grep「网关」现行口径处均指向 M1 初期接管口径——ACC README 无网关/鉴权口径段(grep 无命中,无需改);部署图 01/02/03 已同步;GATEWAY README 升 v1.1(含 §6 实现与部署要点)
- [x] 1.5 更新 `docs/待评审事项汇总.md` G-01/G-02 状态与 add-m1-core-capabilities tasks §9(标注 9.1/9.2 由本变更承接改写);验证:两处引用一致、无「M1 后期独立部署」未决残留——另同步 D-15 文档确档行与 `docs/接口与数据库一致性终审报告.md` 遗留③

## 2. 网关骨架

- [x] 2.1 创建 `services/gateway/pom.xml`(Boot 3.5.0 + SCG server-webflux 4.2.x + redis-reactive + R4J circuitbreaker + actuator + prometheus + 测试栈,显式锁版本);验证:`mvn -q dependency:tree` 解析成功、无版本冲突
- [x] 2.2 创建 `GatewayApplication`、`GatewayProperties`(F8 配置总表全部键位)与 `application.yml`(静态路由指向 acc、白名单、超时分级、Redis 连接、密钥 env 注入)、`.env.example`;验证:应用可启动、actuator health 返回 UP、配置缺失启动 fail-fast

## 3. 错误码与统一 Envelope

- [x] 3.1 `_common` 增补错误码 `2004 RATE_LIMITED`/`5003 GATEWAY_UNAVAILABLE`(ErrorCode.java + message 文案 + `services/_common/openapi.yaml` 权威源同步,D10);验证:ErrorCodeTest 通过、openapi.yaml 校验通过
- [x] 3.2 实现 TraceIdFilter:X-Request-Id 缺失时 UUID 兜底生成(与 acc TraceIds 同口径)、注入请求与响应、透传下游;验证:单测覆盖「已有/缺失」两分支,响应头含同一 traceId
- [x] 3.3 实现 GlobalErrorWebExceptionHandler 与 Envelope 输出(2001/2004/5002/5003,`_common` ErrorCode 口径,禁用 whitelabel);验证:WebTestClient 断言 401/429/503 响应体为五字段 Envelope 结构

## 4. 统一鉴权链

- [x] 4.1 实现 `JwtVerifier`(手写 HS256 验签 + exp 校验 + 常数时间比较,与 JwtCodec.verify 同口径,失败抛 AuthException 不泄露细节);验证:单测覆盖合法/篡改/过期/格式非法四类
- [x] 4.2 实现 Redis RevocationStore(`revoked:jti:{jti}` 短 TTL)与 JwtAuthFilter 主体(验签 → 吊销 → 放行);验证:鉴权矩阵单测(合法/吊销/无头/非 Bearer),吊销命中 401+2001
- [x] 4.3 白名单配置与跳过(`gateway.auth.whitelist`:captcha/register/realname/status 三公开路径),多值 Authorization 头取首个;验证:白名单无 token 放行、非法头 401 用例
- [x] 4.4 四头透传:X-User-Id/X-User-Role/X-User-Mfa/X-User-Jti(与 AuthContext 四字段对齐),保留原 Authorization 头;验证:透传断言单测 + Redis 吊销查询失败 fail-closed 503 用例

## 5. 网关级限流

- [x] 5.1 实现 Redis+Lua 令牌桶脚本(`lua/rate-limit.lua`,INCR+PEXPIRE 原子)与三级 key 构造(`rl:ip:{ip}`/`rl:acc:{sub}`/`rl:api:{method}:{svcPath}`);验证:内存 Redis 假实现单测断言超限拒绝、窗口回填后可放行
- [x] 5.2 实现 RateLimitFilter 装配(初值:读 1000/s/账号、写 100/s/账号、AI 前缀 10/min/账号、IP 200/s;资金路径优先级;超限 429+2004);验证:超限/回填/资金路径用例
- [x] 5.3 Redis 故障 fail-closed:吊销与限流依赖不可用时网关快速失败 503+5003;验证:故障注入单测断言不静默放行

## 6. 路由与超时

- [x] 6.1 静态路由 + 路径重写:`/api/v1/{svc}/**` → `/{svc}/**`(RewritePath 正则,D11/F1),assist/aicore 路由位预留;验证:WireMock 下游断言 `/api/v1/acc/me` 转发到 `http://acc:8080/acc/me`、未知服务前缀 404
- [x] 6.2 callback/internal 不配路由(网关不可达 404,内部 Token 鉴权仍在服务内);验证:集成测试断言 `/api/v1/acc/internal/**`、`/api/v1/acc/realname/callback` 网关 404
- [x] 6.3 路由级超时分级(内部 1s / 支付 `/settle` 3s / AI `/assist|aicore` 5s),超时 503+5002;验证:WireMock 延迟下游断言超时返回 503 且响应为 Envelope

## 7. 熔断与降级

- [x] 7.1 R4J 网关级熔断装配(滑动窗口 10s、失败率 ≥50%、半开 5 次试探、恢复探测 12s);验证:WireMock 连续失败断言熔断打开后快速失败 503+5002、恢复后半开放行

## 8. 运维接口

- [x] 8.1 实现 `GET /gateway/health`(status/redis/version/instanceId,DOWN 时 HTTP 503);验证:正常与 Redis 断开两态断言
- [x] 8.2 实现 `GET /gateway/routes`(id/order/path/uri 脱敏/timeout/weight 摘要);验证:返回当前路由表、无内网明文凭据
- [x] 8.3 编写 `services/gateway/docs/openapi.yaml`(health/routes 两接口 + 2001/2004/5002/5003 错误码引用);验证:yaml 校验通过、与实现一致

## 9. 测试与门禁

- [x] 9.1 补齐测试至 jacoco 整体行 ≥80/分支 ≥75 并通过 `mvn verify`(含 `_common` 依赖构建);验证:verify 全绿 + jacoco 报告达标
- [x] 9.2 提交前走 `commit-check` 技能门禁(DEVELOPMENT_CONSTRAINTS/agent-sdlc 五层门禁);验证:门禁通过、无违规项——**已完成(2026-09-15)**:语义级清单 A~F 逐项执行(提交信息 Conventional Commits + 中文 subject + 无 `[AI]` 前缀 + `Co-authored-by` trailer;无硬编码密钥/真实 `.env`/大文件/冲突标记;新增 SQL 改参数化;新逻辑均有测试);物理 hook 层(`.githooks/pre-commit`、`commit-msg`)**在本沙箱无法执行**(`sh.exe` 报 `CreateFileMapping … Win32 error 5`),已按其规则**逐条等价复核**(冲突标记 / `git diff --cached --check` 行尾空白 / >1MB 大文件 / 私钥与云密钥 / 疑似凭据粗筛 / `.env` 真实文件)并把树改为 hook-clean(测试凭据统一到 `TestSecrets` fixture、`.env.example` 用 `changeme-placeholder-secret`、演练文档标注 fixture);**CI G2 仍为最终兜底**,建议本机重跑 hook 复核。提交按粒度拆分:`feat(gateway) 7fa8a6c`(services/** + openspec 变更工件)、`docs 4a7aa4e`(设计/基准/待评审/日志);工作区其余改动(`.githooks/**`、`AGENT_MEMORY.md`、`docs/agent-sdlc-standard/**`)与本变更无关,未纳入提交

## 10. ACC 瘦身(网关唯一鉴权点)

- [x] 10.1 删除 ACC `AuthFilter`/`RevocationStore`/`NoopRevocationStore` 及装配(保留 JwtCodec 签发、AuthContext、FundsGuard、回调 Hmac 鉴权),新增信任头解析 Filter(X-User-* 四头 → AuthContext 组装,无密码学验证);验证:ACC `mvn verify` 全绿(AuthMatrixTest/AuthFilterTest 迁移为信任头解析测试)——**已完成**:新增 `TrustedHeaderAuthFilter`(缺身份头 401 fail-closed)/ `TrustedHeaderAuthFilterTest`(5 用例),迁移 `ErrorMatrixTest`/`ContractTest`/`WireMockChannelTest`/`AuthMatrixTest` 鉴权断言(新增 `TestIdentity` 工具),**ACC 251 用例 0 失败 BUILD SUCCESS**
- [x] 10.2 联调:gateway + acc 双进程,网关验签 → 四头透传 → ACC 2002 越权校验全链路;验证:合法 token 全链路 200、非法 token 在网关 401、越权在 ACC 403、白名单路径直达 ACC——**已完成(真机双进程 + 真实数据库,2026-09-15)**:以 `services/acc/deploy/drill/AccDrill.java`(嵌入式 MariaDB + Flyway + `@Primary` 真实 DataSource)启动**真实 ACC 进程**(8080,库 33061),与网关 fat jar(18081)组成双进程,链路 `curl → 网关 → ACC → MyBatis → MariaDB`:① 15min 短 token → **200** 真实库行(`acc_1001`/`138****8000`/`张*丰`,路径已改写 `/acc/me`);② 1h 超长 token → **401+2001**;③ 无 `sub` token → **401+2001**;④ 伪造 `X-User-Id:9999` + 合法 token → 仍 `acc_1001`(伪造头被剥离);⑤ 白名单 `/api/v1/acc/captcha` 无 token → 200;缺参 `/api/v1/acc/realname/status` → **400+1001**(ACC 自身校验,证明请求确实到达 ACC);⑥ 内部接口 → **404**(且直连 ACC 同路径 200,证明是网关拦截);⑦ 路径混淆 7 变体(`%2e`/`.`/`//`/`..`/`%2E%2E`/`%2F`/混淆 callback)→ 全部 404;⑧ 直连 ACC:无身份头 401 fail-closed、带身份头 200、库内 `mobile` 为 AES-GCM 密文;根因见 design D16(本次联调发现并修复 ACC 数据层缺陷)

## 11. 部署形态与切换

- [~] 11.1 docker-compose 样例(redis + gateway×2 + acc)与 Nginx 配置样例(upstream 指向网关双实例、TLS 终结、灰度 header/cookie/IP/百分比);验证:compose up 后经网关访问 acc 接口成功、路径重写生效——**文件已交付**(`deploy/docker-compose.yml`、`deploy/nginx-gateway.conf.example`、`deploy/Dockerfile`、`deploy/drill/downstream-stub.cjs`),YAML 静态校验通过;**已用等价方式完成运行验证**(本沙箱无 docker:网关 fat jar 双实例 + Node 下游桩,13 项清单全绿,见 12.1)
- [x] 11.2 生产切换步骤与回滚方案落地(过渡期双鉴权并存 → ACC 瘦身后下线直连;回滚=双 revert + Nginx 指回);验证:切换/回滚文档与演练步骤可执行——**`services/gateway/deploy/README.md`**(部署形态/环境变量/切换 6 步/13 项验证清单/回滚/监控告警/已知约束)

## 12. 验收演练(高并发 §10「网关就绪」提前至 M1 初期)

- [x] 12.1 五用例演练:路由(含路径重写)/鉴权/限流/超时/降级,对照 specs/platform-gateway 全部 Scenario 逐条验证;验证:每场景有演练记录、指标(每路由 QPS/P95/错误率/限流次数)可查——**演练实证**(网关 jar 18081 + Node 下游桩 8080,2026-09-15):① health 200 UP;② routes 200(acc/1s/100);③ 无 token → 401;④ 合法 token → **200,路径重写 `/api/v1/acc/me`→`/acc/me`,身份头透传 `X-User-Id=1001/Role=CONSUMER/Mfa=true/Jti=jti-1001`、Authorization 保留**;⑤ 白名单路径伪造身份头 → **被剥离(null)**;⑥ 内部接口 → 404;⑦ 路径混淆 `%2e` → 404;⑧ 未知服务 → 404;⑨ 慢下游 2.5s(>路由 1s)→ 503+5002;⑩ 降级端点外部直访 → 404;⑪ 限流(IP 容量 3)3×200 → 2×429+2004;⑫ 演练后正常转发 200(熔断恢复);指标端点 `/actuator/prometheus` 已开放
- [x] 12.2 故障注入:单网关实例宕机(流量切到剩余实例)、双实例全挂(Nginx 503 快速失败)两条路径;验证:两条路径符合 specs「High availability and fast-fail fallback」场景——**单实例故障已实证**:双实例(18081 instanceId=local / 18082 gateway-b)同时服务 → 停止 A 后 A 不可达(超时)、**B 继续服务 health UP + routes 200**;「全实例不可用 → 入口 503」为 LB/Nginx 层行为(配置样例 `deploy/nginx-gateway.conf.example` 已给出,不做直连应用降级),真机需 Nginx/K8s 环境复演

## 13. 令牌策略与真机联调整改(2026-09-15 评审 I9 + 用户裁决)

- [x] 13.1 令牌策略落地(design D15 / spec「Access-token policy」):`JwtVerifier` 增 ① `sub` 必填且非空白 ② `exp` 必填、未过期、且 ≤ `access-token-max-ttl`(默认 15m)+ `clock-skew`(默认 60s);配置键 `gateway.auth.access-token-max-ttl` / `gateway.auth.clock-skew`(env 可覆盖);验证:单测 6 例(合法/超长/无 sub/空白 sub/无 exp/边界内放行/自定义策略)+ 配置绑定用例,**网关 139 用例 0 失败**(原 132),真机 1h token 与无 sub token 均 **401+2001**
- [x] 13.2 双 token 会话策略落档:短 token 15 分钟走业务链路、长 token 7 天存 HttpOnly+Secure+SameSite Cookie 且**不经网关业务链路**;PDD §8.4.1 由【建议初值,评审确认】改定档(PDD v1.17 行)、高并发 v0.8 §7.3/TBD-9、待评审汇总同步;验证:PDD/高并发/待评审/design/spec 五处口径一致,且**明确标注换发(refresh)接口尚未实现**(属接口清单变更,待确认后实现)
- [x] 13.3 真机联调桩交付(任务组 10.2 的前置):`services/acc/deploy/drill/{AccDrill.java, build-drill-classpath.ps1, README.md}`——嵌入式 MariaDB(mariaDB4j)+ Flyway V1/V2 + `@Primary` 真实 DataSource + 真实 `AccApplication` + 夹具账户 + `token` 模式(用 ACC 自身 `JwtCodec` 签发);验证:17 项校验矩阵全绿(见 10.2),非生产代码不参与构建
- [x] 13.4 ACC 数据层缺陷修复(联调发现,design D16):6 个 Mapper Bean 改 `openSession(true)`(自动提交)——原实现会话长驻且事务永不提交,真实库下读陈旧/写不落库/持锁阻塞(50s 锁等待);新增 `config.RealDbAssemblyTest`(真实库 + 真实 Tomcat + 真实 HTTP,2 用例)锁回归,反向验证(临时改回原实现)立刻 1 Failure + 1 Error;ACC **253 用例 0 失败**(原 251);残留限制(会话仍长驻、跨表无原子性、M2 收敛按请求会话 + 事务边界)已登记 `services/acc/docs/README.md`
- [x] 13.5 依赖钉版:`services/acc/pom.xml` 显式钉 `jakarta.annotation:jakarta.annotation-api:2.1.1`(test 作用域 mariaDB4j 传递 1.3.5 抢占调解 → 启动期 `NoClassDefFoundError: jakarta/annotation/PostConstruct`);验证:真实库装配测试内成功启动 Tomcat、演练桩正常起进程

## 14. 未完成 / 环境受限(如实登记)

- [ ] 14.1 换发(refresh)接口实现:路径/ Cookie 属性/CSRF 与 Origin 校验/轮换与重放防护;属**接口清单变更**(需 openapi 权威源 + 前端 api-client 同步),待策略确认(design Open Questions) —— **已由 `add-refresh-token-rotation` 承接(2026-09-15)**:该变更已落地登录签发/换发轮换/重用检测/登出吊销与网关白名单 + Cookie 透传增量,交付清单见其 `tasks.md` §1~§8;本行状态按 `add-refresh-token-rotation` tasks §1.6 同口径**保持不变**(仅加承接注记)
- [ ] 14.2 `docker compose up` 运行验证与「全实例不可用 → Nginx 503」复演:本沙箱无 docker/Nginx,已用等价方式(双实例 + Node 桩 + 真实 ACC)验证;需容器/K8s 环境
- [ ] 14.3 ACC 事务边界收敛(M2):按请求会话 + 显式事务边界,替代当前长驻自动提交会话 —— **已由 `fix-acc-transaction-boundary` 承接并落地(2026-09-15)**:`repository/RequestSqlSessionHolder`(ThreadLocal 请求级会话,首次触库惰性开启、结束关闭并清理)+ `infrastructure/tx/TransactionalMapperProxy`(6 个 Mapper Bean 的名称/类型/注入点不变)+ `infrastructure/tx/TransactionBoundaryFilter`(order 2、`/acc/*`;成功提交 / 未捕获异常含受检回滚 / `GlobalExceptionHandler` 置位的 `rollbackOnly` 标记回滚);ACC `mvn -f services/acc/pom.xml verify -nsu` = **280 用例 0 失败**,真机双进程联调复跑无回归;本行状态按 `add-refresh-token-rotation` tasks §1.6 同口径**保持不变**(仅加承接注记)
