# ACC 真机联调桩（drill）

> 用途：以**真实进程 + 真实数据库 + 真实 Redis**形态运行 ACC，供「网关 §10.2 真机双进程联调」、
> 「双 token 会话闭环演练（`add-refresh-token-rotation` 任务组 7）」与手工验证使用。
> 口径：`openspec/changes/implement-gateway-service/tasks.md` 任务组 10 /
> `openspec/changes/add-refresh-token-rotation/tasks.md` 任务组 7 / `services/gateway/deploy/README.md` §3 验证清单。
> **非生产代码**：`deploy/` 不在 Maven 源根下，不参与构建、不进入任何产物。

## 1. 为什么需要它

此前的下游是 `services/gateway/deploy/drill/downstream-stub.cjs`（Node 桩）。桩能证明**转发/改写/鉴权/限流**，
但不能证明 ACC 的 **SQL、字段加解密、业务错误码** 链路——ACC 的 M1 占位数据源（`PlaceholderDataSource`）
会让任何真实 DB 调用明确失败，因此「真机联调」在无数据库环境下无法进行。

本桩用 ACC 已有的 test 作用域依赖 `mariaDB4j`（嵌入式 MariaDB，与 `repository.AbstractDbTest` 同一底座）
起真实数据库，并让 ACC 以真实 DataSource 启动，从而把联调链路补全为：

```
curl → 网关(鉴权/限流/熔断/改写) → ACC(真实进程) → MyBatis → MariaDB(真实库) → 响应
```

**2026-09-16 增量（双 token 会话，任务组 7）**：桩内再起一个**内嵌真实 Redis**
（test 作用域依赖 `com.github.codemonstur:embedded-redis`，jar 内含 Windows 原生
`redis-server-5.0.14.1-windows-amd64.exe`），ACC 以 `acc.session.store=redis` 使用它——
跨进程吊销（**ACC 写、网关读**同一份 `revoked:jti:*`）是本变更最关键的安全行为，
内存假实现无法验证；自写 RESP 桩则要支持网关限流用的 Lua `EVAL`，脆弱且是假证据。链路补全为：

```
curl → 网关(验签/限流/吊销读 Redis) → ACC(登录签发/换发轮换/重用检测/登出吊销) → MariaDB + Redis(真实实例)
```

## 2. 前置

| 项 | 要求 |
|---|---|
| JDK / Maven | Java 17、Maven 3.8+（本仓库自定义本地仓库亦可，脚本自动探测） |
| 端口 | `8080`（ACC）、`33061`（嵌入式 MariaDB，可用外部 mysql 客户端直连核验）、**`6380`（嵌入式 Redis）**、`18081`（网关） |
| 不需要 | Docker、外部 MySQL、外部 Redis（Redis 由桩内嵌；`6380` 已有实例时桩会直接复用） |

## 3. 用法

```powershell
# ① 构建 classpath（含 test 依赖：mariaDB4j / mariadb-java-client / embedded-redis）并编译演练桩
#    注意：本脚本必须是**带 BOM 的 UTF-8**，否则 Windows PowerShell 5.1 解析中文字符串失败
powershell -NoProfile -ExecutionPolicy Bypass -File services/acc/deploy/drill/build-drill-classpath.ps1

# ② 起 ACC 真机（工作目录必须是 services/acc：数据库落在 target/drill-mariadb、Redis 数据目录 target/drill-redis）
#    默认 8080；-Ddrill.acc.port / -Ddrill.db.port / -Ddrill.redis.port / -Ddrill.redis.host 可覆盖
#    会话存储口径由桩固定为 acc.session.store=redis + acc.redis.host=127.0.0.1（可用 -Ddrill.session.store 覆盖，
#    但**只允许 redis**：改成 memory 而 host 仍在 → 按 C1/R-A11 启动失败，这是有意为之的误配保护，不是桩的 bug）
cd services/acc
java -cp "target\classes;target\drill-classes;$(Get-Content target\drill-cp-final.txt -Raw)" drill.AccDrill

# ③ 用 ACC 自身 JwtCodec 签发演练 token（与 acc.jwt-secret 同密钥）
java -cp "target\classes;target\drill-classes;$(Get-Content target\drill-cp-final.txt -Raw)" drill.AccDrill token 1001 CONSUMER

# ④ **先起 ACC（含 Redis）再起网关**——网关启动即连 Redis，顺序颠倒会拿到 down 状态需重启
#    网关（A 实例）指向真实 ACC 与同一 Redis；密钥与 ACC 侧 acc.jwt-secret 一致
$env:GATEWAY_STORE='redis'; $env:GATEWAY_REDIS_HOST='127.0.0.1'; $env:GATEWAY_REDIS_PORT='6380'
$env:GATEWAY_ACC_URI='http://localhost:8080'
$env:GATEWAY_JWT_SECRET='acc-jwt-test-secret-0123456789abcdef'  # 演练 fixture:与 ACC 侧 acc.jwt-secret 一致
$env:GATEWAY_INSTANCE_ID='gateway-drill'
java -jar services/gateway/target/gateway-0.1.0-SNAPSHOT.jar --server.port=18081
#    就绪判据：curl http://127.0.0.1:18081/gateway/health → {"status":"UP","redis":"up",...}

# ⑤ 跑双 token 会话闭环演练（37 项断言，逐项原始输出落盘）
powershell -NoProfile -ExecutionPolicy Bypass -File services/acc/deploy/drill/session-drill.ps1
#    退出码 0 = 全绿；取证目录默认 D:\progrom\.superpowers\sdd\add-refresh-token-rotation\drill
#    R-A16（网关保留原始 Host）取证复跑示例（本次收口用，3.10/3.11/3.12 为新用例）：
#    powershell -NoProfile -ExecutionPolicy Bypass -File services/acc/deploy/drill/session-drill.ps1 `
#        -EvidenceDir D:\progrom\.superpowers\sdd\add-refresh-token-rotation\drill3
```

启动时桩会：起嵌入式 Redis（**6380**，端口被占则复用既有实例）→ 起嵌入式 MariaDB
（**每次演练 DROP DATABASE 重建**，结果可复现）→ Flyway 迁移 V1/V2 → 以 `@Primary` 真实 DataSource
覆盖占位数据源 → 启动 `AccApplication`（`acc.session.store=redis` + `acc.redis.host/port` 指向内嵌实例）
→ 用 ACC 自身 `DaoSupport`/`AccountMapper` 灌入夹具账户 `account_id=1001 / mobile=13800138000`
（明文进出、AES-GCM 加密落库，`mobile_hash` 由 `HmacFingerprint` 现算，与登录查询同源）。

### 3.1 会话闭环演练（`session-drill.ps1`）逐项内容

| 步 | 请求/动作 | 断言 |
|---|---|---|
| 0 | `/gateway/health` + Redis `PING` | 网关报 `redis=up`；Redis `PONG` |
| 1 | `GET /api/v1/acc/captcha?type=IMAGE` → 从真实 Redis 读回答案 → `POST /api/v1/acc/captcha/verify` → `POST /api/v1/acc/auth/login` | 200；**响应体只有短 token**（无 `refreshToken` 字段）；`Set-Cookie` 带 `HttpOnly/Secure/SameSite=Lax/Path=/api/v1/acc/auth` + `Max-Age=604800`；短 token `exp-iat=900s`；**1.5（A1 修复）**：族键 `acc:session:{fam}` TTL ≈ 7 天（1e5 秒量级，不是 900 量级） |
| 2 | `GET /api/v1/acc/me`（Bearer 短 token） | 200 且返回真实库账户 |
| 3 | `POST /api/v1/acc/auth/refresh`（Cookie 换发） | 200 + 新短 token + 新 `Set-Cookie`；Redis 族记录 `currentJti` 前移、旧 jti 进已轮换标记；**3.4/3.5（A1 修复）**：轮换后族键 TTL 仍 ≈ 7 天；族记录 `expiresAtMillis` 与族内短 token 到期时刻相差 > 1 天（族寿命按 refresh 计，未被 15 分钟污染） |
| 3b | 带 `Origin` 的换发（R-A15 同源默认放行 + R-A16 默认链路）：跨站 `https://evil.example.com` → 同源（**入口只透传 `Host`、无任何 `X-Forwarded-*`**，R-A16）→ 同源（入口转发原始 host 形态：网关 + `X-Forwarded-Proto/Host`）→ 同源（直连 ACC `http://127.0.0.1:8080`） | 跨站：401 + 2001 且**不轮换**（族 `currentJti` 未前移）；**R-A16 正向：`Host: api.example.com` + `Origin: http://api.example.com`、不带 `X-Forwarded-Host` → 200 且真轮换（网关 `PreserveHostHeader` 已生效 ⇒ 默认拓扑闭合）**；R-A16 反向：同样的保留 Host 形态 + `Origin: https://evil.example` → 401 + 2001 且不轮换；另两种同源形态：200（默认无需配 `acc.session.allowed-origins`） |
| 4 | **等 >5s（并发宽限窗口）**后重放旧 refresh，再用原短 token 访问 `/api/v1/acc/me` | 重放 401 + 2001；族 `status=REVOKED`；`revoked:jti:{jti}`=1 且 TTL∈[1,900]；**原短 token 与换发出的第二个短 token 都立即 401**（网关从 Redis 读吊销名单）；**4.6（A1 修复）**：重放后族记录仍 `REVOKED` **存在**且族键 TTL 仍 ≈ 7 天（记录寿命不被短 token 污染，重放长期可识别） |
| 5 | 重新登录（新挑战/新票据） | 200，新会话族与旧族不同；新短 token 可用（200） |
| 6 | `POST /api/v1/acc/auth/logout` → 再用该短 token 访问 `/api/v1/acc/me` → 直连 ACC 重复登出 | 登出 200 + `revoked=true` + `Max-Age=0`；随后 401（网关侧）；`revoked:jti` TTL∈[1,900]；重复登出仍 200（幂等，`revoked=false`） |
| 7 | Redis `KEYS/TYPE/TTL` 遍历 `acc:session:*`、`acc:refresh:*`、`revoked:jti:*` | `acc:refresh:{jti}` TTL ≤ 604800（7 天）；`revoked:jti:{jti}` TTL ≤ 900；三类键同实例；**7.4（A1 修复）**：`acc:session:*` 全部为 1e5 秒量级的族寿命（> 1e5 且 ≤ 604800）——**没有** 900 量级的族键 |
| 8 | 审计与网关日志抽取 | ACC `acc.session.audit` 记 `SESSION_REFRESH_REPLAY`/`SESSION_LOGOUT`（不含 token 原文）；网关 `鉴权失败 … reason=Token 已吊销` |

> 说明：refresh Cookie 按生产口径带 `Secure`，curl 的 cookie 引擎不会在 http 链路回带，
> 故脚本从 `Set-Cookie` 头解析出长 token 并以**显式 `Cookie` 头**回放（等价浏览器行为，且不放松生产属性）；
> 重复登出经网关必被吊销名单拦下（401），故幂等语义**直连 ACC** 观测。
>
> **来源校验的可达形态（R-A16 收口后，务必知悉）**：ACC 的「同源默认放行」（裁定 R-A15）需要请求自身来源 =
> 浏览器看到的来源。**网关 acc 路由已启用 `PreserveHostHeader`（裁定 R-A16）**：入口按常规
> `proxy_set_header Host $host` 透传原始 `Host`，网关原样转给 ACC ⇒ **默认链路（浏览器 → 入口 → 网关 → ACC）
> 无需任何 `X-Forwarded-*` 头**，同源默认放行自动生效。本脚本 3.10 即验证该形态（`Host: api.example.com` +
> 同源 `Origin`，真机实测 200 且真轮换），3.11/3.12 验证「同一保留 Host 形态 + 跨站 `Origin`」仍 401 + 2001
> 且不轮换；3.8 验证入口另补 `X-Forwarded-Proto/Host` 的形态（**HTTPS 入口方案**：TLS 在入口终结时 scheme
> 仍需入口透传，`X-Forwarded-Host` 已降级为备案/双保险），3.9 验证直连形态。
>
> 历史约束（R-A16 之前，保留记录）：SCG 会把 `Host` 改写成 ACC 内网地址且默认不转发原始 `Host`，裸网关形态下
> ACC 推断不出对外来源 → 浏览器换发仍会 401，只能 ① 配 `acc.session.allowed-origins` 或 ② 让入口设置
> `X-Forwarded-Host $host`（见 `services/gateway/deploy/README.md` §1 前提表）。


## 4. 校验矩阵（2026-09-15 实测，gateway 18081 + ACC 8080 + MariaDB 33061）

| # | 用例 | 期望 | 实测 |
|---|---|---|---|
| 1 | 直连 `/acc/captcha` | 200 真实验证码 | ✅ `cap_93303153893576704` |
| 2 | 直连 `/acc/me` 不带身份头 | 401 fail-closed | ✅ 401 |
| 3 | 直连 `/acc/me` 带可信身份头 | 200 真实库行 | ✅ `acc_1001 / 138****8000 / 张*丰`（脱敏来自真实解密） |
| 4 | 库内落盘形态（外部 mysql 客户端） | L1 字段密文 | ✅ `mobile=DhilFEmhI7wNOkv/:0biuCPQ`（AES-GCM 密文，非明文） |
| 5 | 网关 `/api/v1/acc/me` 无 token | 401 + 2001 | ✅ |
| 6 | 网关 `/api/v1/acc/me` 合法 token | 200 真实 ACC 数据 | ✅ `accountId=acc_1001`（路径已改写为 `/acc/me`） |
| 7 | 网关伪造身份头 + 合法 token（`X-User-Id:9999`） | 伪造头被剥离，仍为 1001 | ✅ 返回 `acc_1001`（若透传则查 999 → 3006） |
| 8 | 网关白名单 `/api/v1/acc/captcha` 无 token | 200 真实 ACC | ✅ |
| 9 | 网关白名单缺参 `/api/v1/acc/realname/status` | 400 + **1001**（ACC 自身校验） | ✅ 证明请求确实到达 ACC |
| 10 | 网关内部接口 `/api/v1/acc/internal/**` | 404 + 3006 | ✅（且**直连 ACC 同路径 200**，证明是网关拦截） |
| 11 | 路径混淆 7 变体（`%2e` / `.` / `//` / `..` / `%2E%2E` / `%2F` / 混淆 callback） | 全部 404 + 3006 | ✅ 7/7 拦截（真实下游可服务 `/acc/internal/**` 仍无法绕过） |
| 12 | `/api/v1/acc/%2e/me`（归一后即同一端点） | 放行 | ✅ 200（端点等价，未跨越权限边界） |

## 5. 演练发现（2026-09-15，任务组 10.2 的产出）

### F-1 `jakarta.annotation-api` 版本遮蔽（演练桩自限，非生产缺陷）

test 作用域的 `mariaDB4j` 把 javax 时代的 `jakarta.annotation-api:1.3.5` 拉到依赖调解最前，
用 test classpath 启动 Web 容器时报 `NoClassDefFoundError: jakarta/annotation/PostConstruct`。
`build-drill-classpath.ps1` 已剔除 1.3.5 并前置本地仓库的 2.1.1。
生产产物走 runtime classpath（不含 test 依赖）不受影响；建议后续在 `services/acc/pom.xml` 显式钉版本。

### F-2 数据层会话缺陷（**真实缺陷，需裁决**）

`AccConfiguration` 的 6 个 Mapper Bean 均为 `factory.openSession().getMapper(...)`：
会话永久存活、`autoCommit=false`、事务**永不提交**。真实库下实测：

| 证据 | 现象 |
|---|---|
| 外部连接 `UPDATE wallet_status='FROZEN'` 已提交 → 再查 `/acc/me` | 仍返回 `ACTIVE`（**读陈旧**，REPEATABLE READ 长事务快照） |
| `POST /acc/account/close` 返回 200 + `closedAt` → 外部 `SELECT` | `closed_at = NULL`（**写未落库**，接口报成功但数据丢失） |
| 之后再次查询 `/acc/me` | 返回 `FROZEN`（同事务内发生写之后快照被刷新）→ 行为**随调用顺序漂移** |

影响：真实数据库下 ACC 的读可能长期陈旧、写可能整体丢失。既有无测试覆盖原因：控制器测试全部 mock Mapper，
DAO 测试用 `openSession(true)`（自动提交），装配层的会话语义从未被真实库验证过。
修复方案与影响面见 change 记录（待裁决）。

## 5.1 演练发现（2026-09-16，双 token 会话任务组 7 的产出）

### F-3 夹具账户 `mobile_hash` 为占位串 → 登录必 401（**演练桩自限，已修**）

夹具账户原写死 `mobile_hash = "drill-mobile-hash-1001"`，而登录按
`HmacFingerprint.hmacSha256Hex(mobile)` 查 `mobile_hash` 列（`SessionFlow#login`），
故首次登录**必然** 401 + 2001（日志 reason=账户不存在）——旧矩阵只需签发 token，从未走登录，
缺陷一直不可见。**已修**：夹具改取运行中的 `HmacFingerprint` Bean 现算指纹（与
`AccConfiguration` 密钥同源，密钥轮换无需改桩）。

### F-4 真实 Redis 上 `EVAL` 整数回复解码失败 → 建族/轮换/全失效（**真实生产缺陷，已修**）

`AccLettuceStringRedisOps.eval` 原用 `ScriptOutputType.VALUE` 解码，而 `RedisSessionStore` 的
5 个 Lua 脚本（ISSUE/ROTATE/CONSUME/SET/REVOKE）一律 `return 1`（Redis 整数回复），真实 Redis 下抛：

```
java.lang.UnsupportedOperationException: io.lettuce.core.output.ValueOutput does not support set(long)
→ SessionStoreUnavailableException → 登录 503 + 5003（fail-closed 兜住了「不可吊销的 token」，但功能不可用）
```

**为什么单测没拦住**：`RedisSessionStoreContractTest` 用「假装执行脚本」的假客户端**回放期望语义**，
从未真正执行过脚本——L4 风险「真实 Redis 上 Lua 行为」正是本次演练要覆盖的。
**已修**：`eval` 改用 `ScriptOutputType.INTEGER`（并写明「本端口只支持返回整数的脚本」契约），
新增回归用例 `AccLettuceStringRedisOpsRealRedisTest`（内嵌真实 Redis 上跑真实脚本：建族双键 /
单次使用 / 轮换标记 / 吊销 TTL）——先 RED（同一 `UnsupportedOperationException`）后 GREEN。

> 复跑指引：`mvn -f services/acc/pom.xml test -Dtest=AccLettuceStringRedisOpsRealRedisTest`。

## 6. 注意

- 桩会 `DROP DATABASE acc`，**禁止指向任何真实数据库**；端口与库目录均可通过 `-Ddrill.acc.port` / `-Ddrill.db.port` 调整；
- token 由 ACC 自身 `JwtCodec` 签发（M1 尚无登录接口，签发路径与未来登录一致），仅用于演练；
- 外部核验库内容：`mysql -h 127.0.0.1 -P 33061 -u root acc -e "SELECT * FROM account"`（root 空口令，仅本机演练库）；
- **Redis 由桩内嵌**（默认 6380，`-Ddrill.redis.port` 可改；该端口已有实例则复用）；
  ACC 侧组合**固定**为 `acc.session.store=redis` + `acc.redis.host/port`（桩的默认值，见 `AccDrill#main`），
  即启动校验的合法组合之一；L1/R-A8 + C1/R-A11 的两方向 fail-fast 都不会触发：
  - 取 `redis` 而缺 `host` → **启动失败**（不会静默退化为内存会话存储）；
  - 取 `memory`（含默认）而 `host` 已配置 → **同样启动失败**（防止「配了 Redis 却忘设开关」导致登出/踢人静默失效）。
  故用 `-Ddrill.session.store=memory` 覆盖本桩的启动参数会**故意**启动失败——要跑内存会话请同时清空
  `-Ddrill.redis.host=`，且此时跨进程吊销语义已不成立，不适用于本演练；
- **启动顺序**：先 ACC（含 Redis）→ 起网关（网关启动即连 Redis，顺序颠倒会拿到 `redis=down`，需重启网关）；
- **收尾必须停掉全部进程**（ACC 桩、网关、内嵌 Redis、内嵌 MariaDB），确认 `8080/18081/6380/33061` 全部释放
  （`netstat -ano | findstr "LISTENING"` + 四端口连接探测）；桩退出时会经 shutdown hook 停掉内嵌实例；
- MariaDB 目录若处于半安装状态（上次被强杀），删 `target/drill-mariadb` 后重起即可。
