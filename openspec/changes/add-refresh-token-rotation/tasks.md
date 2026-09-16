## 1. 口径与接口清单(先定稿对外契约,再动代码)

- [x] 1.1 更新 `services/acc/docs/openapi.yaml`(接口权威源):新增 `POST /acc/auth/login`、`POST /acc/auth/refresh`、`POST /acc/auth/logout` 三路径与请求/响应 schema(LoginRequest/TokenPair/SessionView/LogoutRequest),标注短 token 在 body、长 token 仅 `Set-Cookie`(`HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth`),错误码统一 `2001`;验证:yaml 解析通过(`node -e "require('js-yaml')..."` 或等价),三路径出现在文档中且与 spec `acc-session` 的场景一一对应 —— **实测:YAML 解析 OK / paths 18 / 三路径均在册 / 前端操作 19;提交 `5c92aff`;重打包产物 `openapi.apifox.json` 亦含三路径(2026-09-16 会话 11 复核)**
- [x] 1.2 更新 PDD `docs/design/产品设计文档.md`:§6.4.1 接口清单 +3 行、§8.4.1 登录态段补"端点 + 轮换 + 重用检测 + Cookie 属性 + ACC 生产需 Redis"、§2.8/§3.1 存储与依赖注、§6.2 错误码注(复用 2001)、新增版本史行 **v1.18**;验证:grep 三处口径一致、index 表中 16→19 个前端接口 —— **实测:版本史 v1.18 追加、前端接口 16→19、diff 为纯追加(历史行未改);提交 `5c92aff`**
- [x] 1.3 更新 `docs/design/高并发架构演进设计.md` §7.3 令牌策略段(补换发/轮换/重用检测、会话键容量口径)与 §2 缓存容量,追加版本注 **v0.9**;验证:与 PDD v1.18 口径互洽、无"待实现"残留 —— **实测:§7.3 换发/轮换/重用检测 + 新增 §2.4.4 会话凭据容量 + 版本注 v0.9;提交 `5c92aff`**
- [x] 1.4 更新 `docs/design/微服务边界与职责基准.md`:§2.2 ACC 边界卡(新增会话凭据职责 + Redis 数据归属)、§2.15 GATEWAY 边界卡(白名单/Cookie 透传、**签发不属网关**)、C14 追加 2026-09-15 变更记录、版本 **v1.9**;验证:边界划分无歧义(签发=ACC、校验=网关) —— **实测:标题与版本表 v1.9、ACC/GATEWAY 两卡 + 交叉职责矩阵「会话凭据生命周期」行 + C14 变更记录;提交 `5c92aff`**
- [x] 1.5 更新 `docs/待评审事项汇总.md`:**G-07 关闭/定档**(换发接口实现形态已定);新增两条确认项(登录因子是否叠短信码、`SameSite` 取值与子域);验证:条目状态与实际实现一致 —— **实测:G-07 改「✅ 已定档(关闭)」+ 新增 G-08(登录因子)/G-09(SameSite 与子域);提交 `5c92aff`**
- [x] 1.6 承接标注:`openspec/changes/implement-gateway-service/design.md` D15 与 `tasks.md` §14.1 标注"由 `add-refresh-token-rotation` 承接";验证:两处交叉引用可跳转、原变更任务清单状态不变(除标注) —— **已由评审批次修复波执行(2026-09-15,提交 `12ac50e`)**:`design.md` D15 与 `tasks.md` §14.1 的承接注记均已落地,§14.1 行首仍为 `- [ ]`、§14.3 状态未变(只追加承接说明,不宣告任务状态变更)

## 2. ACC 会话存储与端口

- [x] 2.1 定义会话存储端口(会话族 + refresh 映射 + 吊销写入),含键名/TTL 语义(`acc:session:{familyId}`、`acc:refresh:{jti}`、`revoked:jti:{jti}` = 网关共享契约);验证:单测覆盖键构造与 TTL 计算(用假实现) —— **实测:`AbstractSessionStoreContractTest` 11 例(键前缀常量/建族双键/TTL ≤ 有效期/单次使用/轮换/族到期/吊销契约/TTL≥1/标记保留)全绿;提交 `d1e4ffb`**
- [x] 2.2 提供 InMemory 实现(单元测试/演练兜底)与 Redis 实现(生产),由配置切换;验证:两实现通过同一套端口契约测试(InMemory 直跑、Redis 实现用假客户端) —— **实测:同一抽象基类被两实现继承——`InMemorySessionStoreContractTest` 11 例 + `RedisSessionStoreContractTest` 19 例全绿(端口签名不变,ACC 内新增 `AccLettuceStringRedisOps`,未改 `_common`);提交 `d1e4ffb`**
- [x] 2.3 装配接入 `AccConfiguration`,Redis 不可用时登录/换发/登出快速失败而非静默降级;验证:故障注入单测(存储抛错 → 5xx),且不产生任何 token 签发副作用 —— **实测:`SessionStoreAssemblyTest` 原 5 例(故障端口上抛 `SessionStoreUnavailableException`、无写入副作用);**2026-09-16 会话 11 追加 L1 修复(裁定 R-A8)**:`acc.session.store=memory|redis` 显式开关 + 取 redis 缺 `acc.redis.host` 启动 fail-fast + 非法取值 fail-fast + 显式 memory 绝不触碰 Redis,该测试 7 例全绿;提交 `d1e4ffb` + 本单元**

## 3. ACC 会话流程(核心)

- [x] 3.1 实现登录流程:手机号 → 账号查询(不存在/已注销/冻结即拒)→ 人机验证票据消费 → 建会话族 → 签发短/长 token;验证:单测矩阵(成功/账号不存在/已注销/冻结/票据无效/票据重复消费) —— **实测:`SessionFlowTest#loginIssuesBothTokens`、`loginFailuresAreUniformlyUnauthorized`(4 类失败统一 401/2001)、`invalidCaptchaShortCircuitsBeforeAccountLookup`(票据失败不查账户);真机演练登录 200(提交 `0fe0454`)**
- [x] 3.2 实现换发流程:校验 refresh(签名 + 存在 + 未过期 + 未轮换)→ 轮换签发 → 写新映射并标记旧 jti;验证:单测(成功轮换、旧 token 失效、过期/未知被拒) —— **实测:`refreshRotatesAndInvalidatesOldToken`、`unknownOrExpiredRefreshRejected`、`accessTokenCannotBeUsedAsRefresh`(typ 区分);真机演练换发 200 + Redis 族记录 currentJti 前移 + 旧 jti 进已轮换标记(提交 `0fe0454`)**
- [x] 3.3 实现重用检测:命中"已轮换"标记 → 吊销该会话族全部短 token(写 `revoked:jti:{jti}`,TTL=剩余有效期)与长 token → 记审计事件;验证:单测断言整族吊销 + 审计日志字段(不含 token 原文) —— **实测:`replayOutsideGraceRevokesWholeFamily`(族 REVOKED + `revoked:jti` 命中 + TTL∈[1,900] + 审计含族/账户、不含 token 原文)、`revokedFamilyRejectsEverything`;真机演练重放 401+2001 且原短 token 网关侧立即 401(提交 `0fe0454`)**
- [x] 3.4 实现并发宽限期(轮换后极短窗口内的重复换发不判泄露);验证:单测锁定窗口内/外两种行为 —— **实测:`replayInsideGraceIsTreatedAsConcurrentRetry`、`graceRetryDoesNotIssueSecondRefresh`(无写放大)、`graceBoundaryIsFiveSeconds`(4s 放行 / 累计 6s 判泄露);真机演练第 4 步刻意等待 6s 越窗后重放(提交 `0fe0454`)**
- [x] 3.5 实现登出:短 token `jti` 入黑名单(TTL=剩余有效期)+ 会话族失效 + 幂等重复登出 + 清除 Cookie;验证:单测(首次登出/重复登出/仅凭 Cookie 登出 + 来源校验) —— **实测:`logoutWithAccessTokenRevokesFamily`(TTL=请求侧精确剩余)、`repeatedLogoutIsIdempotent`、`logoutWithRefreshCookieOnly`、`logoutWithoutCredentialsRejected`、`logoutWithExpiredFamilyStillRevokesOwnJti`;真机演练登出 200 + `Max-Age=0` + 随后 401 + 直连 ACC 重复登出 200(提交 `0fe0454`)**
- [x] 3.6 签发口径对齐网关策略:`exp - iat = 900s`、声明含 `sub/role/mfa/jti/iat/exp`,并以常量集中定义;验证:单测断言声明与有效期,且**签发的 token 能通过网关 `JwtVerifier` 的相同校验规则**(复用同一批断言) —— **实测:`AccessTokenIssuerTest` 7 例:`exp-iat=900s` 严格、声明齐全、jti 唯一、网关同批判定通过 + 反向守卫(1000s 超长被拒/过期被拒);真机演练短 token 声明 ttl=900 且网关放行(提交 `0fe0454`)**

## 4. ACC 控制器与鉴权接入

- [x] 4.1 新增会话控制器(login/refresh/logout),响应统一 Envelope,日志脱敏(不落 token/Cookie 原文);验证:组件测试断言响应结构、`Set-Cookie` 属性、日志断言无敏感字段 —— **实测:`AuthControllerTest` 16 例(body 只含短 token、`jsonPath("$.data.refreshToken").doesNotExist()`、Set-Cookie 四属性、登出 `Max-Age=0`、store 故障 503+5003)+ `SessionEndToEndTest` 4 例;真机演练响应体与 Cookie 属性复核(提交 `68508ae`)**
- [x] 4.2 `TrustedHeaderAuthFilter` 白名单加入 `/acc/auth/login`、`/acc/auth/refresh`(**不含 logout**);验证:单测(无身份头可访问登录/换发、logout 无身份头 401、近似路径 `/acc/auth/loginAny` 不被放行) —— **实测:`TrustedHeaderAuthFilterTest` 9 例(白名单精确集合 7 项、login/refresh 放行、**logout 401**、`loginAny`/`login/../me`/`refreshAny` 全 401);真机演练登录/换发经网关白名单直达 ACC(提交 `68508ae`)**
- [x] 4.3 换发/仅 Cookie 登出的来源校验(`Origin`/`Referer` 白名单);验证:单测(合法来源通过、跨站来源 403/2001 且不产生轮换副作用) —— **实测:`OriginValidatorTest` 8 例 + `AuthControllerTest` 跨站分支(401 + 2001、`Set-Cookie` 不存在、流程**零调用**);提交 `68508ae`**

## 5. 网关增量

- [x] 5.1 `application.yml` 白名单增补登录与换发路径(段边界匹配,不含 logout);验证:集成测试(无 token 登录/换发放行、logout 401、`/api/v1/acc/auth/loginAny` 与混淆路径 404/401) —— **实测:`GatewaySessionEndpointsIntegrationTest` 10 例(无 token 登录/换发直达下游;logout 401+2001 且下游零调用;`loginAny` 不蹭白名单;混淆路径被拒);提交 `da2f98f`**
- [x] 5.2 Cookie 透传与非解析:确认网关不改写 `Cookie`/`Set-Cookie` 且不据 Cookie 鉴权;验证:集成测试(换发响应 `Set-Cookie` 原样到达客户端;仅 Cookie 无 Bearer 时受保护路径 401) —— **实测:下游 `Set-Cookie` 逐字相等(`valueEquals` 全属性断言)、请求 Cookie 原样到下游、**仅 Cookie 无 Bearer → 401+2001**;真机演练换发 Cookie 显式回放成功(提交 `da2f98f`)**
- [x] 5.3 会话端点不获限流豁免;验证:集成测试(IP 容量置小后登录端点返回 429 + 2004,下游未收到请求) —— **实测:`GatewaySessionRateLimitIntegrationTest`(独立上下文,容量=1):第二次会话请求 **429 + 2004** 且下游 `verify(0)`;提交 `da2f98f`**

## 6. 测试与门禁

- [x] 6.1 ACC 测试补齐(会话族/轮换/重用/宽限/登出/并发单飞),`mvn -f services/acc/pom.xml verify` 全绿且 jacoco 门禁不降;验证:用例数与覆盖率报告 —— **实测(2026-09-16 会话 11):`mvn -f services/acc/pom.xml verify -nsu` = Tests run **385**, Failures 0, Errors 0, BUILD SUCCESS(基线 381:+2 L1 装配用例、+2 真实 Redis 用例);ACC 模块**无 jacoco 插件**(已知事项,门禁「不降」以用例数不减 + 既有用例零弱化兑现,未新增门禁)**
- [x] 6.2 网关测试补齐(白名单/Cookie/限流),`mvn -f services/gateway/pom.xml verify` 全绿;验证:用例数与 jacoco 报告 —— **实测(2026-09-16 会话 11):`mvn -f services/gateway/pom.xml verify -nsu` = Tests run **150**, Failures 0, Errors 0, BUILD SUCCESS(`jacoco:check` 通过;本单元未改网关用例,与组 5 的 150 一致)**
- [x] 6.3 提交前执行 `commit-check` 门禁(语义清单 + hook 等价复核,与上一变更同口径);验证:门禁通过并记录执行方式 —— **实测(2026-09-16 会话 11):按 `commit-check` 技能清单 A~F 对本单元暂存 diff 逐项复核(提交信息格式/粒度/无 `[AI]` 前缀 + `Co-authored-by` trailer、无硬编码密钥、中文注释与标识符英文、无 SQL 拼接与会话 token 落日志、新增关键安全逻辑均有测试、无冲突标记、`git diff --cached --check` 无行尾空白);本机 `sh.exe` 崩溃致 `.githooks` 不生效,由控制器统一执行最终复核**

## 7. 真机联调(沿用 ACC 真机桩)

- [x] 7.1 扩展 `services/acc/deploy/drill`(真实 Redis 或桩内嵌 Redis + 会话断言脚本);验证:一条命令起"真实 ACC + 真实 MariaDB + Redis" —— **实测(2026-09-16):`AccDrill` 内嵌**真实 Redis**(test 作用域 `com.github.codemonstur:embedded-redis:1.4.3`,默认 6380,`-Ddrill.redis.port` 可覆盖,占用则复用)+ 嵌入式 MariaDB,ACC 以 `acc.session.store=redis` 启动,启动日志打印 `嵌入式 Redis 已启动: 127.0.0.1:6380`;会话断言脚本 `services/acc/deploy/drill/session-drill.ps1`(25 项断言,原始报头/体逐项落盘)**
- [x] 7.2 跑通闭环链:登录 → 带短 token 访问业务接口 200 → 换发 → **旧 refresh 重放被拒且整族吊销** → 原短 token 立即 401 → 重新登录取新对 → 登出后短 token 立即 401;验证:演练记录逐项输出(含网关侧 401 证据) —— **实测(2026-09-16):`session-drill.ps1` **25 项断言全绿(exit 0)**——①登录 200(体只含短 token、Cookie 四属性)②业务 200 ③换发 200 且轮换 ④重放 401+2001 + 族 REVOKED + 原短 token 与换发出的第二个短 token 均 401(网关日志 `鉴权失败 … reason=Token 已吊销`)⑤重新登录 200 ⑥登出 200 后立即 401 + 幂等;**并核验 Redis 键 `acc:session:*`/`acc:refresh:*`(TTL≤7 天)/`revoked:jti:*`(TTL≤900)与 L4(Lua 真机行为)**;取证目录 `.superpowers/sdd/add-refresh-token-rotation/drill/`;演练后四端口(8080/18081/6380/33061)全部释放**
- [x] 7.3 更新 `services/gateway/deploy/README.md` 验证清单(新增换发链路条目)与 `docker-compose.yml`(ACC 服务补 Redis 依赖);验证:compose 文件 yaml 校验通过、清单条目与演练一致 —— **实测(2026-09-16):部署手册 §3 新增第 15 组(换发链路 6 项,与演练逐项一致)+ §1/§6 补 ACC 侧 Redis 前提与吊销名单同实例约束;`docker-compose.yml` 新增 `acc` 服务(`depends_on: redis(healthy)` + `ACC_SESSION_STORE=redis`/`ACC_REDIS_HOST`/`ACC_REDIS_PORT` 等)+ `mariadb` 服务 + `services/acc/deploy/Dockerfile`;`node js-yaml` 解析通过(6 服务、依赖与环境变量核对一致);沙箱无 Docker,`compose up` 未运行(已知事项,已登记)**

## 8. 收口

- [x] 8.1 同步服务基线:`services/acc/docs/README.md`(接口/依赖/数据归属 + 生产需 Redis)、`services/gateway/docs/README.md`(白名单与 Cookie 透传);验证:两份基线与 PDD/openapi 口径一致 —— **实测(2026-09-16):ACC 基线新增 §3.5 会话凭据(三接口清单 + Redis 数据归属 + 网关协作契约)+ §1 依赖/状态机 + §5 openapi v1.2.0(前端接口 19)+ §6 会话存储装配与演练记录;网关基线 §3.2 白名单 5 项(login/refresh 放行、logout 不放行)与 Cookie 透传非解析 + §6 双 token 落地与演练 + 质量基线 150;口径与 PDD v1.18/openapi v1.2.0 一致**
- [x] 8.2 `openapi.apifox.json` 重打包(自动产物,禁手改);验证:重打包产物包含三条新路径 —— **实测(2026-09-16):仓库既有脚本 `.dsh/regen-apifox.cjs` 可用(裁定 R-A9 无需回报缺失)——`node .dsh/regen-apifox.cjs acc --write` 重打包,重生成比对 `MATCH`;产物 `info.version=1.2.0`、paths=18、`/acc/auth/{login,refresh,logout}` 三路径均在册;未手改该文件**
- [x] 8.3 `openspec validate add-refresh-token-rotation` 通过、按粒度拆分提交(建议:接口清单+文档 / ACC 实现 / 网关增量 三个提交);验证:校验输出与提交历史 —— **实测(2026-09-16):`openspec validate add-refresh-token-rotation` → `Change 'add-refresh-token-rotation' is valid`(exit 0);本单元按组拆分 5 个提交(L1 修复 / L4 修复 + 真实 Redis 回归 / 组 7 演练与部署件 / 组 8 服务基线与重打包 / 本任务清单与日志索引),均为 Conventional Commits 且带 `Co-authored-by` trailer,详见 `.superpowers/sdd/add-refresh-token-rotation/task-u2-report.md`**

## 9. 最终评审修复波（FIX-1，2026-09-16）

> 来源:`.superpowers/sdd/final-review.md`(区间 290d66e..5a08850,1 Critical / 2 Important / 12 Minor)与
> 控制器裁定清单 `.superpowers/sdd/final-fix-wave.md`。逐条证据见 `.superpowers/sdd/final-fix-report.md`。

- [x] 9.1 **A1(Critical)** 族记录寿命只由 refresh 有效期决定(`FamilyRecord.withAccessJti` 不再把短 token 到期时刻写进族 `expiresAtMillis`;两个存储实现的族键 TTL 取更新后记录的族到期时刻);验证:三条回归防线 —— **实测:①`SessionFlowTest#familyAndRotationMarkerLifetimeFollowRefreshTtl`(族键 TTL=604800、标记=refresh 原始到期)与 `#replayLongAfterRotationStillRevokesWholeFamily`(可注入时钟推到 +901s 重放 → 仍判重用:族 REVOKED + 未过期短 token 入 `revoked:jti:*` + `SESSION_REFRESH_REPLAY` 审计)=**先 RED(2 条 FAIL)后 GREEN**;②端口契约 `AbstractSessionStoreContractTest#bindAccessJtiKeepsFamilyLifetime`(InMemory/Redis 同跑);③真机演练新增 1.5/3.4/3.5/4.6/7.4:族键 TTL 实测 **604800/604793**(旧缺陷为 864~900),族 `expiresAtMillis` 与短 token 到期差值 **603899999ms**,重放后族记录仍 REVOKED 且 TTL 604794**
- [x] 9.2 **A2(Important I1,裁定 R-A15 同源默认放行)** `OriginValidator.isAllowed(origin, referer, requestOrigin)`:同源(Origin 与请求自身 scheme+host[:port] 一致,默认端口等价)直接放行,仅跨源查 `acc.session.allowed-origins`;无来源头放行;给不出请求自身来源时按跨站处置;`AuthController#requestOrigin` 优先取入口/网关的 `X-Forwarded-Proto/Host/Port`;**实测:先 RED(`sameOriginOriginPassesWithoutAllowListConfiguration`/`sameOriginBehindProxyUsesForwardedOrigin` 401)后 GREEN;默认端口归一化让 `http://localhost:80` == `http://localhost`;真机演练 3.6/3.7/3.8/3.9 全绿(跨站 401 且不轮换;入口转发原始 host 形态 200;直连形态 200)**;部署口径同步 `gateway/deploy/README.md` §1 + `docker-compose.yml` + `nginx-gateway.conf.example`(`X-Forwarded-Host $host`);**已知约束(实测):SCG 改写 Host 且默认不转发原始 Host ⇒ 裸网关形态必须配 allowed-origins 或让入口设置该头**
- [x] 9.3 **B 段顺修 11 项** F5 派发类型显式 REQUEST + `beginRequest` 重入显式拒绝 / F6 登记进过滤器 Javadoc 与 `fix-acc-transaction-boundary/design.md` D6 / M1 存储故障用例改用合法 token(原恒真断言) / M2 契约用例改 `Assumptions.abort`(不再空转计绿) / M3 删 `ConsumeResult.RetryableRace` / M7 `access-token-ttl-seconds` 生效并夹紧 `[60,900]`(+`SessionView.expiresIn` 同源)/ openapi 计数 19→18 / cookie-secure 启动 WARN / compose 淘汰策略 `noeviction` + 前提表 / 登出 Bearer 校验 `typ=access` / **B11 族记录原子性:Lua CAS + 有界重试(Redis)与族记录互斥(InMemory),轮换写回合并并发绑定的 jti**;验证:每条均有定向用例(先 RED 后 GREEN),含 8 线程 × 8 轮并发绑定无丢失与「轮换按旧快照写回不丢 jti」
- [x] 9.4 **C1(并行代理产出、本波验证并提交)** `acc.session.store=memory`(含默认)而 `acc.redis.host` 已配置 → 启动 fail-fast(裁定 R-A11);**本波复跑 `SessionStoreAssemblyTest` = 9/9 绿,并做反向验证(临时改回「仅告警」→ 2 条 FAIL,改回后复绿,留档 `.superpowers/sdd/final-fix-wave/c1-red.txt`)**
- [x] 9.5 **验证** `mvn -f services/acc/pom.xml verify -nsu` = Tests run **410**, Failures 0, Errors 0, Skipped 1(M2 显式跳过)→ BUILD SUCCESS;`mvn -f services/gateway/pom.xml verify -nsu` = Tests run **150**, Failures 0 + `jacoco:check` → BUILD SUCCESS;真机演练 `session-drill.ps1` = **34 项断言 0 失败**(原始输出 `.superpowers/sdd/add-refresh-token-rotation/drill2/`),演练后 8080/18081/6380/33061 全部释放
- [x] 9.6 `openspec/changes/**` 两变更工件由控制器在提交阶段统一入库(A3);本波按 A3 允许范围仅追加登记本 `tasks.md` 与 `design.md` 的 FIX-1 段

## 10. 最终复评残余(登记,下一波处置)

- [ ] 10.1 [Important · 定向复评 2026-09-16] **族记录「status 语义」竞态**:`rotate` 以调用方**陈旧快照**(ACTIVE)为基底,`mergedWithAccessJtisOf(...)` 只合并 `accessJtis`——若**登出/整族吊销恰好发生在 `SessionFlow.refresh` 的 consume 与 rotate 之间**,轮换会把族写回 `ACTIVE` 并写入新 `currentJti`,导致「登出对该条 refresh 失效、仍可继续换发(每次续 7 天)」。A1 修复把族寿命从 ≈15 分钟恢复到 7 天后,该窗口从「会被短 TTL 自愈」变成持续整个 refresh 有效期。验证:交错用例(可注入时钟或并发钩子)证明「登出后该 refresh 不可再换发」;修法需端口层返回「已吊销族拒绝轮换」信号并调整 `SessionStore` 契约,故**未在合并前仓促修改**(评审结论:可合并,该项登记后另立一波)
- [ ] 10.2 [Minor] HTTPS 入口必须透传 `X-Forwarded-Proto`(否则 ACC 推断 `http://` 与浏览器 `https://` 不同源 → 换发 401):已写入部署手册/nginx 样例/ACC 基线三处,待部署环境复核
