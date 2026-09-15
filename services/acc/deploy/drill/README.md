# ACC 真机联调桩（drill）

> 用途：以**真实进程 + 真实数据库**形态运行 ACC，供「网关 §10.2 真机双进程联调」与手工验证使用。
> 口径：`openspec/changes/implement-gateway-service/tasks.md` 任务组 10 / `services/gateway/deploy/README.md` §3 验证清单。
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

## 2. 前置

| 项 | 要求 |
|---|---|
| JDK / Maven | Java 17、Maven 3.8+（本仓库自定义本地仓库亦可，脚本自动探测） |
| 端口 | `8080`（ACC）、`33061`（嵌入式 MariaDB，可用外部 mysql 客户端直连核验） |
| 不需要 | Docker、外部 MySQL、Redis（限流/吊销用 `--gateway.store=memory` 兜底） |

## 3. 用法

```powershell
# ① 构建 classpath（含 test 依赖）并编译演练桩
powershell -NoProfile -ExecutionPolicy Bypass -File services/acc/deploy/drill/build-drill-classpath.ps1

# ② 起 ACC 真机（工作目录必须是 services/acc：数据库落在 target/drill-mariadb）
cd services/acc
java -cp "target\classes;target\drill-classes;$(Get-Content target\drill-cp-final.txt -Raw)" drill.AccDrill

# ③ 用 ACC 自身 JwtCodec 签发演练 token（与 acc.jwt-secret 同密钥）
java -cp "target\classes;target\drill-classes;$(Get-Content target\drill-cp-final.txt -Raw)" drill.AccDrill token 1001 CONSUMER

# ④ 起网关（A 实例）指向真实 ACC；密钥与 ③ 一致
$env:GATEWAY_ACC_URI='http://localhost:8080'; $env:GATEWAY_STORE='memory'
$env:GATEWAY_JWT_SECRET='acc-jwt-test-secret-0123456789abcdef'  # 演练 fixture:与 ACC 侧 acc.jwt-secret 一致
$env:GATEWAY_INSTANCE_ID='gateway-drill'
java -jar services/gateway/target/gateway-0.1.0-SNAPSHOT.jar --server.port=18081
```

启动时桩会：起嵌入式 MariaDB（**每次演练 DROP DATABASE 重建**，结果可复现）→ Flyway 迁移 V1/V2
→ 以 `@Primary` 真实 DataSource 覆盖占位数据源 → 启动 `AccApplication`
→ 用 ACC 自身 `DaoSupport`/`AccountMapper` 灌入夹具账户 `account_id=1001`（明文进出、AES-GCM 加密落库）。

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

## 6. 注意

- 桩会 `DROP DATABASE acc`，**禁止指向任何真实数据库**；端口与库目录均可通过 `-Ddrill.acc.port` / `-Ddrill.db.port` 调整；
- token 由 ACC 自身 `JwtCodec` 签发（M1 尚无登录接口，签发路径与未来登录一致），仅用于演练；
- 外部核验库内容：`mysql -h 127.0.0.1 -P 33061 -u root acc -e "SELECT * FROM account"`（root 空口令，仅本机演练库）。
