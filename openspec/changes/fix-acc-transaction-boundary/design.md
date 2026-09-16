# fix-acc-transaction-boundary · 设计文档

## Context

现状（只读核对于本仓库当前工作树）：

- `AccConfiguration.mapper(SqlSessionFactory, Class)` 目前是 `factory.openSession(true).getMapper(type)`——**启动期为 6 个 Mapper 各开一个自动提交会话并永久持有**（AccountMapper / RealnameRecordMapper / WalletFlowMapper / WalletBindingMapper / ReconcileTaskMapper / IdempotencyRecordMapper）；
- `DaoSupport.factory(DataSource)` 负责构建 `SqlSessionFactory`（`JdbcTransactionFactory` + `LocalCacheScope.STATEMENT` + `MonthlyShardingInterceptor` + `TableNameGuardInterceptor` + `EncryptedStringTypeHandler` 实例注册），本变更**不改变**这套构建内容；
- 依赖现状：ACC 只有 `mybatis` 3.5.16 与 `spring-tx` 6.2.7，**没有** `mybatis-spring`、`spring-jdbc`、`spring-boot-starter-jdbc`；
- 装配现状：Flow 与 Controller 全部**构造注入 Mapper 单例**（如 `new RegisterFlow(captchaPort, realnameChannelPort, accountMapper, realnameRecordMapper, ...)`）；
- 测试现状：6 个控制器测试类用 `@AutoConfigureMockMvc` + `@MockBean` 替换全部 Mapper（契约层不触库）；DAO 测试基类 `AbstractDbTest.openSession()` 用 `factory.openSession(true)`；真实库装配测试 `RealDbAssemblyTest` 用「嵌入 MariaDB + 真实 Tomcat + 真实 HTTP + 外部连接视角」核验；
- 数据源现状：`AccConfiguration.accDataSource()` 返回 `PlaceholderDataSource`——**任何连接请求即明确失败**，真实 DataSource 由部署环境以 `@Primary` 覆盖（演练桩与 `RealDbAssemblyTest` 即如此）。

问题与动机见 `proposal.md` — Why（当前只解决了「写不落库/读陈旧/持锁」，残留跨表无原子性、无事务边界、并发共享会话）。

## Goals / Non-Goals

**Goals:**

- 让「一个请求 = 一个事务」：成功提交、失败整体回滚、结束必关会话并归还连接；
- 让并发请求各持独立会话/连接（消除同一 `SqlSession`/`Connection` 被多线程并用的隐患）；
- 让提交结果对其它连接立即可见（跨请求不残留旧快照）；
- **保持全部既有外部契约与既有 253 用例不变绿**（不改接口、错误码、Envelope、openapi/er）；
- 不新增 Maven 依赖、不改变 `@Primary` 真实 DataSource 的装配方式。

**Non-Goals:**

- 不引入连接池实现或调整连接池水位（生产仍按《高并发架构演进设计》§2.5 的 HikariCP 规划，属部署/压测范畴）；
- 不实现 `REQUIRES_NEW`/嵌套独立事务、不实现跨服务/跨库分布式事务（《高并发》§2.2 已明确禁止跨分片事务）；
- 不改幂等键的业务语义（保留「首次执行、重复返回首次结果」），仅让**失败**的占位随事务释放；
- 不改分表路由（`MonthlyShardingInterceptor`）、表名守卫、字段加解密等既有数据层能力；
- 不动网关侧（GATEWAY）与会话令牌策略。

## Decisions

### D1 手写 session-per-request + 事务拦截（不引 starter / 不用 `DataSourceTransactionManager`）

**已定决策（用户 2026-09-15 裁决）**：以手写方式把 `SqlSession` 绑定到请求，由拦截环节在事务边界开启 → 提交/回滚。

理由：ACC 的既有风格是「不引 starter、显式装配」（`DaoSupport` 手动构建 `SqlSessionFactory`、`AccConfiguration` 显式 new 出所有组件）；引入 `spring-boot-starter-jdbc` + `DataSourceTransactionManager` 或 `mybatis-spring` 的 `SqlSessionTemplate` 会同时引入连接获取/释放与 `SqlSession` 生命周期的第二套语义，与既有装配风格冲突，且会把「谁持有连接」这一问题藏进框架。

**备选与否决理由**：① 引入 `spring-boot-starter-jdbc` + `DataSourceTransactionManager` + `@Transactional`——自动化程度高，但新增 starter 与 Spring 事务基础设施，且需要 `mybatis-spring` 才能让 Mapper 参与事务，改造面反而更大；② 仅手写 AOP 环绕 Controller——仍需自管连接与会话，复杂度不降，且切面语义不如显式过滤器直观。

### D2 会话绑定用 `ThreadLocal`（不用 `RequestContextHolder` 属性）

MyBatis `SqlSession` 与 JDBC `Connection` **都不是线程安全的**；`RequestContextHolder` 暴露的是请求属性，同一请求派生的其它线程仍可读到它，隔离性弱于 `ThreadLocal`。故：持有器以 `ThreadLocal<SqlSession>` 绑定当前线程，请求结束时**必须 `remove()`**（Tomcat 线程复用，残留会导致跨请求串会话）。

### D3 Mapper Bean 改为「事务感知动态代理」（`java.lang.reflect.Proxy`）

Mapper Bean 仍以单例形式暴露（保持 20+ 处构造注入点与所有测试不变），但不再返回某个固定会话上的 Mapper 实例，而是返回一个实现了该 Mapper 接口的动态代理：每次方法调用时向持有器索取「当前请求的会话」，再 `session.getMapper(type)` 得到真实 Mapper 并转发调用。

**备选与否决理由**：① 把 Mapper 从 Bean 改为「用哪取哪」，逐个改造 Flow/Controller 调用方——改造面大、易漏、会污染业务代码；② 引入 `mybatis-spring` 的 `MapperFactoryBean`/`SqlSessionTemplate`——需要额外依赖与 spring-jdbc，违背 D1。

### D4 会话「惰性开启」是硬约束（不是优化）

会话在**本请求第一次真正访问数据库时**才开启，而不是请求进入时：

- **口径修订（2026-09-15，任务评审 F2 实证）**：本节原写「入口急切开启会让 6 个 `@MockBean` 控制器测试集体变红（`PlaceholderDataSource` 抛错）」——**该论证不成立**。评审用 `javap` 核实：MyBatis `openSession()` **不取连接**（`JdbcTransaction` 构造只赋值字段，`commit()` 在 `connection == null` 时直接返回），因此急切 `openSession()` 本身不会让任何用例变红。惰性开启的**真实依据**是 spec 的显式要求「Requests that perform no data access MUST NOT acquire a database connection」以及「不必要地创建会话/连接」的资源语义，其判据是单测断言「未触库时 `openSession` 调用次数为 0」（`RequestSqlSessionHolderTest` / `TransactionBoundaryFilterTest`），而非控制器测试的颜色；
- **资源收益**：验证码、纯计算型端点完全不占用连接，`/acc/captcha` 这类接口不需要数据库。

**备选与否决理由**：入口急切开启——实现更简单，但会让「不触库的请求不占数据库资源」这条契约失去保证（spec 明确要求），且会话/连接的生命周期与请求实际需求脱钩，被否。

### D5 事务边界放在 Servlet Filter（紧随鉴权过滤器，`urlPatterns = /acc/*`）

与既有 `trustedHeaderAuthFilterRegistration`（`FilterRegistrationBean`，order 1，`/acc/*`）保持同一装配风格，新过滤器 order 更大（在身份解析之后、控制器之前）承担「开启/提交/回滚/关闭」。

**备选与否决理由**：① AOP 环绕 Controller——同一请求可能调用多个 Flow，切在 Flow 层会把事务边界切碎；切在 Controller 层则需要代理语义与注解，收益不如显式过滤器；② 直接在 Flow 内部管理事务——会把事务边界扩散到每个业务流程，重复且易漏。

### D6 回滚口径：未捕获的异常一律回滚，正常返回提交

**实施期修订（2026-09-15，控制器裁定 R-7）**：本节原写「非受检异常回滚、**受检异常提交**」，与 spec「the transaction MUST be rolled back when the request fails with an unhandled exception」冲突。**spec 是约束权威**，实现取「未捕获的异常（含受检）一律回滚」，过滤器 Javadoc 已写明该口径。有意偏离 Spring 默认（受检异常返回时提交）的理由：ACC 现有异常全为非受检（`AccBusinessException extends RuntimeException`），而「受检异常默默提交半成品」是更危险的失败模式。

与 Spring 默认口径基本一致，便于团队理解。`AccBusinessException` **继承 `RuntimeException`**（已核对），因此业务失败同样回滚——这正是目标语义：**失败的业务操作不在 `acc_idempotency_record` 留下占位**，`IdempotencyGuard` 的「同 key 失败可重试」不再依赖「把校验挪到占槽位之前」这一人工约定（现有代码注释即体现了这种将就）。

**备选与否决理由**：仅对基础设施异常回滚、业务异常照常提交——需要逐异常分类白名单，且会丢失上述收益，被否。

**实施期补漏（2026-09-15，控制器裁定 R-6；原 D5/D6 未覆盖）**：Spring MVC 的 `@RestControllerAdvice` 会把控制器抛出的异常**就地**转成错误 Envelope——异常不会抵达过滤器，`catch` 分支看不到它，失败请求会被当成功提交（这正是组 3 用例首次切换后仍红的根因）。补法：`GlobalExceptionHandler` 在写出错误 Envelope 时显式调用 `TransactionBoundaryFilter.markRollbackOnly(request)`（请求属性标记），边界见标记即回滚。**否决**替代方案「过滤器按 `response.getStatus() >= 400` 回滚」：那会把事务语义绑死在 HTTP 状态码这一启发式上（200+错误 Envelope、重定向、过滤器后置改写都会失真）；显式信号语义清晰且可测。

**已知残留（2026-09-15，任务评审 F4，接受并登记）**：显式失败信号只覆盖 `@RestControllerAdvice` 产出的错误响应；**Spring 默认异常解析器**产出的 5xx（如响应体序列化失败 `HttpMessageNotWritableException`）不置位，那条路径上的写会被提交。当前不可达（写端点响应体小、无自定义 `ResponseBodyAdvice`），故不补 `@ExceptionHandler`；代价：将来引入大响应体写端点或自定义响应处理时需重新评估（已登记 tasks §6）。

**已知残留（2026-09-16，最终整体评审 F6，接受并登记；与上条 F4 并列）**：本边界在 `chain.doFilter` **返回之后**提交，而 Servlet 容器可能在链内就向客户端刷出响应（响应缓冲写满即刷，或链内显式 `flushBuffer()`）——即存在「响应已写出、提交却失败」的时序：此时回滚无法收回已写出的响应体。当前不可达（ACC 写端点响应体小，远小于容器响应缓冲；失败路径已由 `GlobalExceptionHandler` 置位 `rollbackOnly` 提前转为回滚）。**代价/触发条件**：将来新增流式或大响应体写端点时必须重新评估——改为「先缓冲响应、后提交、再刷出」，或把该端点移出本边界自行管理事务（写端点响应体须小于容器响应缓冲，或改为缓冲后提交再刷出）。该残留同时写入 `TransactionBoundaryFilter` 类 Javadoc（FIX-1/B2 顺修），使新增写端点的人在不读本文件时也能看到。

### D7 无请求上下文时降级为「单次自动提交会话，调用后立即关闭」

非 Web 调用路径（测试夹具、脚本、将来的定时任务）不在过滤器边界内。此时每次 Mapper 调用开一个自动提交会话、调用结束即关闭：既保持这些调用可用（如 `RealDbAssemblyTest.seedAccount` 的写法同理），又不再产生「长驻会话」这一缺陷根源。

**备选与否决理由**：无上下文直接 fail-fast——会破坏既有非 Web 用法，且收益不明，被否。

### D8 内层复用同一会话（隐式 `REQUIRED` 传播）

持有器已绑定会话时直接复用，不重复开启；不实现 `REQUIRES_NEW`（需要双连接与挂起语义，M1 无此需求）。

### D9 连接归还与数据源

会话 `close()` 即由 `JdbcTransactionFactory` 归还连接；本变更**不引入连接池**，生产仍由部署环境注入池化 DataSource（`@Primary` 覆盖方式不变）。需注意：session-per-request 把连接持有时间从「单条语句」拉长到「整个请求」，连接池水位假设需在压测标定 TBD-6（`HikariCP 20~50/实例`）时把这一点计入——**口径不冲突，仅需在标定时复核**（见 proposal Impact 的 grep 结论）。

### D10 测试策略：扩展真实库装配测试，不改造既有测试

在 `RealDbAssemblyTest` 既有的「嵌入 MariaDB + 真实 Tomcat + 真实 HTTP + 外部连接视角」手法上扩展用例（跨表回滚、并发隔离、提交可见、幂等槽位释放、读路径契约、连接释放、并发同 key 竞态、未提交写不可见，共 8 类，对应 tasks 3.1~3.8）。DAO 基类 `AbstractDbTest`（autocommit 会话）与 6 个 `@MockBean` 控制器测试**保持原样**，它们本身是「未破坏既有行为」的判据。

**口径更正（2026-09-15，复评 N5）**：本节原写这 6 个控制器测试「尤其验证 D4 的惰性开启」——与 D4 的口径修订矛盾（MyBatis `openSession()` 不取连接，它们**不构成**惰性开启的判据）；惰性开启的判据是单测「未触库时 `openSession` 调用次数为 0」。

## Risks / Trade-offs

- [请求级连接持有时间变长 → 连接池水位假设变化] → 部署按《高并发》§2.5 规划池化数据源；压测标定 TBD-6 时把「连接持有 = 请求时长」计入；M1 单实例 + 读路径惰性开启，实际占用远低于并发数。
- [`ThreadLocal` 未清理 → Tomcat 线程复用导致跨请求串会话] → 过滤器 `finally` 中无条件 `remove()`；回归用例②（并发读写全部正确）覆盖。
- [跨线程/异步使用 Mapper] → `ThreadLocal` 语义下异步线程拿不到会话，会退化为 D7 的单次会话（正确但非事务）。M1 无异步数据访问；将来若引入，需显式传播会话（列入 Open Questions）。
- [惰性开启让「非持久化请求不占连接」成为可观察行为] → 这是有意为之的契约（spec 已写明）；若将来某端点偷偷依赖占位数据源可用，那本身即缺陷。**副作用（须留意）**：6 个控制器测试用 `@MockBean` 替换全部 Mapper 且数据源是 `PlaceholderDataSource`，因此将来**任何在 MockMvc 测试里真实触库的新路径都会立刻踩到占位数据源**——这是既有测试装配事实（非本变更引入），实施时按此判据排查。
- [`RealDbAssemblyTest.seedAccount` 等直连 `openSession(true)` 的写法不受本变更影响] → 它们仍是自动提交会话，**不能**用来验证事务语义；组 3 的新用例一律以 HTTP 请求为入口（tasks 已如此要求），避免"用非事务路径证明事务行为"的假证据。
- [幂等语义变化：失败不再留占位记录] → 对客户端是改善（失败可立即重试）；需在文档与用例中明确，并复核 `IdempotencyGuardTest`（DAO 层用 autocommit 会话，预计不受影响）。
- [内部接口 `/acc/internal/**` 同样进入事务边界] → 符合期望（内部接口同样是写路径），但会与「内部 Token 校验失败」交互：校验失败抛错 → 回滚（无写入，无副作用）。
- [读请求长事务在 REPEATABLE READ 下的快照语义] → 单请求内快照一致是期望行为；跨请求可见性由「每请求新事务」保证（用例①/③覆盖）。
- [回滚后残留限制恢复] → 若实施后回滚本次变更，会回到「自动提交 + 长驻会话」，proposal Impact 列出的文档需一并回滚。

## Migration Plan

1. **阶段 1 基础设施（行为不变）**：新增请求级会话持有器（ThreadLocal + 无上下文降级）与事务边界过滤器，先不改变 Mapper 装配；跑全量 253 用例，确认零行为变化。
2. **阶段 2 切换装配**：`AccConfiguration.mapper(...)` 改为事务感知代理，6 个 Mapper Bean 的对外类型与注入点不变；跑全量用例 + 新增的真实库装配用例。
3. **阶段 3 验证**：`mvn -f services/acc/pom.xml verify` 全绿（含 jacoco 门禁）；真机联调桩（`services/acc/deploy/drill/`）重跑，确认网关→ACC 链路与库内核验不变。
4. **阶段 4 文档同步**：按 proposal Impact 清单更新 `services/acc/docs/README.md` §6、`docs/待评审事项汇总.md` E-10、`implement-gateway-service` 的 design D16 / tasks §14.3、`AccConfiguration` 内注释、开发日志。
5. **回滚策略**：无数据迁移、无接口变更 → 单次 revert 即回到现状（自动提交 + 长驻会话）；同步回滚上述文档条目。

## Open Questions

- 将来引入异步/定时任务数据访问时，会话如何显式传播（显式传参 vs 可传播的持有器 vs 每任务一事务）——M1 无此场景，不影响本变更的规格、方案与任务分解，实施期可另行决策。
