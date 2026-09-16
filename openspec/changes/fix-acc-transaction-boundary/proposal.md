# fix-acc-transaction-boundary

## Why

ACC 的数据层当前是「**自动提交 + 长驻会话**」：6 个 Mapper Bean 在启动时各自 `factory.openSession(true)` 并永久持有，请求之间共享同一个 `SqlSession`/`Connection`。2026-09-15 的真机双进程联调已修掉最致命的三个症状（写不落库、读陈旧、持锁阻塞外部写入约 50s），但当时的处置只把会话改成自动提交，**残留三项风险必须在 M1 交付前收掉**：

1. **跨表写入无原子性**：`RealnameCallbackFlow` 的「建户 + 回写实名业务单」（`accountMapper.insert` → `realnameRecordMapper.updateCallback`）若第二步失败，会留下**已建户但业务单未回写的半成品数据**，且无人补偿；
2. **无事务边界**：任何一处失败都无法整体回滚，`IdempotencyGuard` 只能靠「把校验挪到占槽位之前」这种人工约定来维持「失败可重试」语义，脆弱且难以推广；
3. **并发下共享连接**：MyBatis `SqlSession` 与 JDBC `Connection` 都不是线程安全的，长驻会话被 Tomcat 多线程并发使用，存在串行化异常/结果错配的隐患（M1 单实例但多线程，属真实风险）。

现在做的理由：ACC 是网关接管后的首个业务域，M1 上线即承载实名/资金类写入；事务边界属于**数据正确性底座**，越晚收敛，后续依赖它的流程（资金流水、对账、绑定）越难改。

## What Changes

- **手写 session-per-request**：新增请求级会话持有器（`ThreadLocal<SqlSession>`），会话绑定到处理该请求的线程；请求结束（无论成功/异常）关闭会话并把连接归还数据源——**不再有长驻会话**。
- **引入请求级事务边界**：请求进入时**惰性**开启会话（首次真正访问数据库时才开），正常返回提交、未捕获异常回滚，`finally` 关闭；内层复用同一会话（等价 Spring 的 `REQUIRED` 传播）。
- **Mapper Bean 改为事务感知代理**：新增动态代理（`java.lang.reflect.Proxy`）实现 Mapper 接口，每次调用从当前请求会话取真实 Mapper；**无请求上下文**时退化为「单次自动提交会话 + 调用后立即关闭」，使既有 20+ 处构造注入点与 DAO/装配测试全部无需改动。
- **惰性开启是硬约束而非优化**：`PlaceholderDataSource` 在任何连接请求上都会明确失败，而 6 个控制器测试类全部用 `@MockBean` 替换 Mapper（不触库）；若在请求进入时急切开启会话，253 个既有用例会因占位数据源而变红。
- **回滚口径**：未捕获的 `RuntimeException`/`Error` 一律回滚；业务异常 `AccBusinessException`（继承 `RuntimeException`）同样回滚——由此**失败的业务操作不再占用幂等槽位**（`acc_idempotency_record` 的 `INSERT IGNORE` 随事务回滚），`IdempotencyGuard` 的「同 key 失败后可重试」语义由事务天然保证，不再依赖调用方把校验挪到前面。
- **不引入新依赖**：沿用 ACC「不引 starter、显式装配」的既有风格，不引入 `spring-boot-starter-jdbc`、不使用 `DataSourceTransactionManager`/`mybatis-spring`；`@Primary` 真实 DataSource 的覆盖装配方式保持不变。
- **回归防线扩展**：在既有真实库装配测试（真实库 + 真实 Tomcat + 真实 HTTP + 「外部连接视角」核验）基础上，新增跨表回滚、并发不共享连接、提交后外部立即可见、读路径可用四类用例；既有 253 用例保持全绿。

## Capabilities

### New Capabilities

- `acc-transactional-data-access`: ACC 数据访问的事务与会话语义——请求级事务边界（提交/回滚/关闭）、跨表写入原子性、成功后对外部连接的可见性、请求间连接隔离（并发安全）、失败事务对幂等槽位的释放，以及「不做数据访问的请求不占用数据库连接」。

### Modified Capabilities

（无。`openspec/specs/` 当前为空——该服务此前没有登记任何能力规格，本次为其建立第一个能力规格；`implement-gateway-service` 的 `platform-gateway` 规格仍是该变更内的 delta，尚未同步为基线，故不构成「修改既有能力」。）

## Impact

**代码（本变更实施时改动，规划阶段不动）**

| 路径 | 影响 |
|---|---|
| `services/acc/src/main/java/com/msz/acc/config/AccConfiguration.java` | `mapper(...)` 装配由「启动期固定会话」改为「事务感知代理」；新增事务过滤器注册（紧随 `TrustedHeaderAuthFilter`，order 大于 1，`urlPatterns` = `/acc/*`） |
| `services/acc/src/main/java/com/msz/acc/repository/DaoSupport.java` | 暴露会话工厂的复用入口（工厂构建逻辑不变：sharding 拦截器、表名守卫、加密 typeHandler 保持） |
| `services/acc/src/main/java/com/msz/acc/repository/`（新增） | 请求级会话持有器（ThreadLocal 绑定 + 无上下文降级） |
| `services/acc/src/main/java/com/msz/acc/infrastructure/`（新增） | 事务边界过滤器（开启/提交/回滚/关闭）与 Mapper 代理工厂 |

**测试**：`services/acc/src/test/java/com/msz/acc/config/RealDbAssemblyTest.java`（扩展 4 类用例）、`services/acc/src/test/java/com/msz/acc/testsupport/EmbeddedMariaDb.java`（复用，必要时补并发核验支撑）；DAO 基类 `AbstractDbTest`（`openSession(true)`）与 6 个 `@MockBean` 控制器测试**不需要改动**，并作为「不破坏既有行为」的判据。

**契约与依赖**：接口签名、Envelope、错误码、`openapi.yaml`、`er.md` 均无变化；无新增 Maven 依赖（`spring-tx` 已在依赖中，本次不使用其事务管理器）。**需注意的行为变化**：失败的业务操作不再在 `acc_idempotency_record` 留下占位记录（对客户端表现为：同一 `Idempotency-Key` 失败后可重试，而非等待 2s 轮询后拿到空 payload）。

**需同步的文档（本变更只规划、不动手，实施阶段一并更新）**

| 文档 | 现状口径 | 需同步为 |
|---|---|---|
| `services/acc/docs/README.md` §6「已知限制与实现要点」 | 记录数据层会话三症状、已改自动提交、残留「跨表无原子性 + 并发串行化风险」、M2 收敛方向 | 改为「已落地请求级事务边界 + session-per-request」，移除残留限制条款，保留历史缺陷记录 |
| `docs/待评审事项汇总.md` E-10 | 「ACC 数据层事务边界收敛」登记为 **M2** 收敛项 | 标记由本变更承接并落地（不再是 M2 待办） |
| `openspec/changes/implement-gateway-service/design.md` D16 | 「残留限制：会话仍为长驻…M2 收敛为按请求会话 + 显式事务边界」 | 追加上承接注记（由 `fix-acc-transaction-boundary` 承接落地） |
| `openspec/changes/implement-gateway-service/tasks.md` §14.3 | 「ACC 事务边界收敛(M2)：按请求会话 + 显式事务边界」未勾选 | 标注由本变更承接（勾选/转引用） |
| `services/acc/src/main/java/com/msz/acc/config/AccConfiguration.java` 内注释（`mapper(...)` 的「已知限制」段） | 代码内写明「会话仍为长驻…M2 收敛」 | 随实现更新为事务语义说明 |
| `AI_DEV_LOG/2026-09-15.md`（会话 7 的「下一步」）、`PROJECT_LOG/2026-09-15.md`（明日计划） | 把事务边界列为后续待办 | 追加「已由本变更承接」 |

**grep 结论（事务/连接池/会话口径）**

- `docs/design/高并发架构演进设计.md`：**建议补一句（非必须）**——§2.5 连接池规划与 TBD-6 现有「HikariCP 20~50 连接/实例」口径是按「连接随用随还」估算的；session-per-request 会把连接持有时间拉长到**整个请求时长**，同一水位假设下需要复核（该文档也已在 §2.2 写明「禁止跨分片事务」，与本变更的「请求级本地事务」不冲突，无需改）。结论：口径不冲突，**建议在压测标定 TBD-6 时把「请求级连接持有」计入**，可在实施阶段补一句注解。
- `docs/design/微服务边界与职责基准.md`：**无需改动**——全文无「事务边界/连接池/SqlSession/会话持有」相关口径（命中的「会话」均为 ASSIST 会话 TTL 与前端登录态，和本变更无关）。
- `docs/design/产品设计文档.md`：**无需改动**——无 ACC 数据层事务/连接口径（§8 非功能设计只到连接池水位，属高并发文档范围）。
