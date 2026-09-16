# fix-acc-transaction-boundary · 任务清单

> 口径：`proposal.md`(Why/What/Impact)、`specs/acc-transactional-data-access/spec.md`(行为契约)、`design.md`(D1~D10 决策)。
> 原则：**先加基础设施不动装配(阶段 1 零行为变化) → 再切装配 → 再补真实库用例 → 最后文档同步**。
> 验证命令统一为 `mvn -f services/acc/pom.xml verify`(含 jacoco 门禁)；真实库用例依赖 test 作用域 `mariaDB4j`(无需 Docker/外部 MySQL)。

## 1. 基础设施(此阶段不改变装配,行为应与现状完全一致)

- [ ] 1.1 新增请求级会话持有器(路径 `services/acc/src/main/java/com/msz/acc/repository/` 下):`ThreadLocal<SqlSession>` 绑定/获取/清理;无请求上下文时降级为「单次自动提交会话 + 调用后立即关闭」(design D2/D7);验证:单元测试覆盖「绑定后取回同一会话」「未绑定时的降级路径不抛错且会话被关闭」「清理后再次获取不复用旧会话」
- [ ] 1.2 新增 Mapper 事务感知代理工厂(同包或 `infrastructure/`):`java.lang.reflect.Proxy` 实现 Mapper 接口,每次调用向持有器索取当前会话的 Mapper 并转发,`InvocationTargetException` 解包后原样抛出(design D3);验证:单元测试断言「代理调用落在当前绑定会话上」「异常类型与消息不被包装改变」
- [ ] 1.3 新增事务边界过滤器(`FilterRegistrationBean`,order 大于鉴权过滤器的 1,`urlPatterns = /acc/*`):**惰性**开启会话(首次真正访问数据库时)→ 正常返回提交 → 未捕获异常回滚(`RuntimeException`/`Error`)→ `finally` 关闭会话并 `remove()` ThreadLocal(design D1/D4/D5/D6);验证:单元测试覆盖「成功路径提交并关闭」「异常路径回滚并关闭」「未触库的请求不开启会话」
- [ ] 1.4 阶段 1 回归:在**尚未切换 Mapper 装配**的前提下跑 `mvn -f services/acc/pom.xml verify`;验证:既有 253 用例全绿(证明新增基础设施零行为变化)

## 2. 装配切换(事务生效)

- [ ] 2.1 将 `AccConfiguration.mapper(SqlSessionFactory, Class)` 由 `factory.openSession(true).getMapper(type)` 改为返回 1.2 的代理;6 个 Mapper Bean(AccountMapper / RealnameRecordMapper / WalletFlowMapper / WalletBindingMapper / ReconcileTaskMapper / IdempotencyRecordMapper)的 Bean 名称、返回类型与全部构造注入点保持不变(design D3);验证:`mvn -f services/acc/pom.xml verify` 编译通过且 253 用例全绿。**实施期更正(2026-09-15,任务评审 F2)**:原写「控制器测试用 `@MockBean` 替换 Mapper、不触库,即 D4 惰性开启的判据」**不成立**——MyBatis `openSession()` 不取连接(`JdbcTransaction` 构造只赋字段),急切开启不会让这些用例变红;惰性开启的真实判据是单测「未触库时 `openSession` 调用次数为 0」(`RequestSqlSessionHolderTest` / `TransactionBoundaryFilterTest`)
- [ ] 2.2 更新 `AccConfiguration.mapper(...)` 的注释:删除「已知限制:会话仍为长驻…M2 收敛为按请求会话 + 显式事务边界」表述,改为请求级事务语义说明(保留 2026-09-15 真机联调缺陷的历史记录,历史不得改写);验证:grep 该文件无「M2 收敛」「会话仍为长驻」现行口径残留
- [ ] 2.3 复核既有幂等实现与用例的兼容性:`IdempotencyGuard`(INSERT IGNORE 抢占槽位 → 执行 → 回填)在请求级事务下的语义变化,确认 `repository` 层 `IdempotencyGuardTest`(DAO 层用自动提交会话)不受影响;验证:该测试类全绿,且其语义与 spec「Idempotency claims follow transaction outcome」不冲突(冲突则以 spec 为准调整用例,并记录)

## 3. 真实库装配测试扩展(复用 `config/RealDbAssemblyTest` 与 `testsupport/EmbeddedMariaDb`)

- [ ] 3.1 跨表回滚用例:构造「实名回调建户 + 回写业务单」路径,在第二步注入失败,断言**两表均无变化**(用外部 `acc_app` 连接核验,沿用既有「外部视角」手法);验证:该用例在修复前(自动提交会话)必须**失败**、修复后通过——反向验证一次以证明用例有效(spec「Cross-table atomicity」/「Failed request leaves no partial writes」)
- [ ] 3.2 并发隔离用例:并发发起 N(N≥8)个混合读写请求(如 `/acc/me` 读 + `/acc/account/close` 写),断言每个请求各自返回正确结果、无串行化/串扰异常;验证:该用例通过,且日志中无连接/会话级异常(spec「Per-request connection isolation」)
- [ ] 3.3 提交可见性用例:写请求返回成功后,立即用外部连接读取该行并断言已是新值(把既有「读陈旧」用例扩展为「写后读」闭环);验证:该用例通过(spec「Successful write request is committed and externally visible」)
- [ ] 3.4 幂等槽位释放用例:同 `Idempotency-Key` 第一次失败(下游不可用或注入失败)→ 断言 `acc_idempotency_record` 无残留行 → 用同 key 重试 → 断言**真正执行**并返回结果;再断言成功后的重复请求返回首次结果且不重复执行;验证:该用例通过(spec「Idempotency claims follow transaction outcome」)
- [ ] 3.5 读路径契约用例:请求不存在的对象(如 `/acc/me` 对不存在账户、`/acc/realname/status` 对不存在 bizId),断言返回既有业务错误与 HTTP 状态(3006 等)而**非**事务机制导致的 5xx;验证:该用例通过(spec「Read request failing with a business error keeps its contract」)
- [ ] 3.6 连接释放用例:连续发起多次失败请求(数量大于场景②的并发度),随后发起正常请求,断言仍成功(无连接泄漏/耗尽);验证:该用例通过(spec「Connections are released after repeated failures」)
- [ ] 3.7 并发同 key 竞态用例:两个并发请求携带**同一** `Idempotency-Key`,首个在写入后失败回滚;断言 ①等待方不会拿到悬空占位/半成品 ②该组合下的最终语义与 spec「Idempotency claims follow transaction outcome」一致(失败后同 key 重试真正执行),并把观测口径写进用例注释;验证:该用例通过;若观测语义与 spec 不符,先改 spec 再改实现(不得反向迁就)
- [x] 3.8 「未提交写对其它请求不可见」定向用例(2026-09-15 任务评审 F3 补齐):外部连接 `setAutoCommit(false)` 写入不提交 → 真实 HTTP `/acc/me` 断言仍读旧值 → 外部 `commit()` → 再断言读到新值;验证:用例 `uncommittedExternalWriteStaysInvisibleToConcurrentRead` 通过(定向 10/10、全量 **280 用例 0 失败** BUILD SUCCESS;提交 `5a7d0b8`)。**如实说明**:本用例为**守卫用例**,未观测到 RED(当前实现已满足该场景),其判别力在于锁定此类回归;spec 该 Scenario 由此用例直接覆盖

## 4. 门禁与端到端验证

- [ ] 4.1 全量门禁:`mvn -f services/acc/pom.xml verify -nsu`;验证:全部用例(253 + 新增)0 失败、BUILD SUCCESS。**实施期核实(2026-09-15)**:`services/acc/pom.xml` **未配置 jacoco 插件**(全文无 `jacoco-maven-plugin`),故「BUNDLE 行 ≥80/分支 ≥75、domain 90/90」的覆盖率门禁在 ACC 上**实际不生效**——本清单与 proposal 此前表述有误;本变更按「无覆盖率门禁」执行,并把「写库服务是否统一补配 jacoco 门禁」登记为仓库级待决项(见 §6.2,不在本变更范围)
- [ ] 4.2 真机联调复跑:按 `services/acc/deploy/drill/README.md` 起「网关 18081 + 真实 ACC 8080 + 真实 MariaDB」双进程,复跑关键矩阵(短 token 200、超长/无 sub token 401、白名单直达 ACC、内部接口 404、直连 ACC 身份头 200、库内密文);验证:与 2026-09-15 记录一致,无因事务改造引入的回归
- [ ] 4.3 提交门禁与提交:执行 `commit-check` 技能门禁(语义清单 + 物理 hook 等价复核),本变更**单独提交**(不与其它变更混提);验证:门禁通过、提交信息符合 Conventional Commits(中文 subject、无 `[AI]` 前缀、`Co-authored-by` trailer)

## 5. 文档同步(按 proposal Impact 清单;不改接口与 openapi/er)

- [ ] 5.1 `services/acc/docs/README.md` §6「已知限制与实现要点」:改为已落地「请求级事务边界 + session-per-request」,移除残留限制条款,保留 2026-09-15 缺陷历史;验证:该文档无「跨表无原子性」「M2 收敛」现行口径残留
- [ ] 5.2 `docs/待评审事项汇总.md` E-10:由「M2 收敛」改为「已由 `fix-acc-transaction-boundary` 承接并落地」;验证:状态与 `docs/design/*` 口径一致
- [ ] 5.3 `openspec/changes/implement-gateway-service/{design.md,tasks.md}`:D16 残留限制段与 §14.3 待办追加「由本变更承接」注记(不改该变更已完成任务的既有结论);验证:两处注记存在且指向本变更
- [ ] 5.4 `docs/design/高并发架构演进设计.md` §2.5/TBD-6:补一句「ACC 请求级事务使连接持有时间等于请求时长,压测标定时计入」(口径不冲突,属标定说明);验证:该句落地且未改动既有连接池初值
- [ ] 5.5 开发日志:`AI_DEV_LOG/`(当日文件新增会话)与 `PROJECT_LOG/`(当日活动)登记本变更的「需求 → 方案 → 产出物 → 验证」;验证:日志条目含真实命令与结果,不改既有历史条目措辞

## 6. 明确不在本变更范围(登记,避免被误认为已完成)

- [ ] 6.1 唯一键冲突的错误码翻译:MyBatis 手写装配下 `PersistenceException`(含唯一键冲突)不经 Spring 异常翻译,客户端拿到 500+5000 而**非** `3008`(`GlobalExceptionHandler` 里的 DuplicateKeyException→3008 映射在该装配下不会被触发)。本变更为事务边界改造,不触碰错误映射;spec 对应场景已改为只断言「无半成品残留」。验证:本条以「已登记 + spec 已对齐」为准,如需 3008 需另立变更(补 PersistenceExceptionTranslator 或异常后处理器)
- [ ] 6.2 ACC 覆盖率门禁缺失:`services/acc/pom.xml` 未配 jacoco,门禁形同虚设。验证:本条以「已登记」为准;建议 M1 交付前把写库服务的构建门禁统一(与 `services/gateway/pom.xml` 的 jacoco 配置对齐),属仓库级决策
