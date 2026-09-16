# 网关服务 GATEWAY · 部署与切换手册

> 口径:PDD v1.16 §5.16 / 高并发 v0.7 §7 / `services/gateway/docs/README.md`。
> 网关是平台**唯一统一入口与唯一鉴权点**,M1 初期**交付即接管**;不提供「Nginx 直连应用」降级路径。

## 1. 部署形态

| 项 | 值 |
|---|---|
| 运行物 | `gateway-0.1.0-SNAPSHOT.jar`(可执行 fat jar,`mvn -f services/gateway/pom.xml verify` 产出) |
| 运行时 | Java 17(JRE 即可) |
| 实例数 | **双实例起步**(A/B),无状态、可水平扩展 |
| 端口 | `8081`(业务入口 + 运维接口;运维接口另有网段白名单) |
| 依赖 | **Redis(必需)** — JWT 吊销名单 + 限流计数;不可用时入口 fail-closed 503。**该 Redis 必须与 ACC 的会话存储同一实例**(`revoked:jti:{jti}` = ACC 写、网关读,2026-09-16 双 token 会话增量)。**该实例必须禁用易失淘汰**(`maxmemory-policy noeviction`;会话族/refresh/吊销键全部带 TTL,`allkeys-lru` 与 `volatile-*` 都会淘汰它们) |
| 密钥 | `GATEWAY_JWT_SECRET`(env / KMS 注入;**密钥不出网关**);与 ACC 的 `acc.jwt-secret` **同值**(否则 acc 签发的短 token 一律验签失败) |
| 配置 | `gateway.*`(白名单/内部路径/限流初值/运维网段/**令牌策略** `auth.access-token-max-ttl` + `auth.clock-skew`)、`spring.cloud.gateway.server.webflux.routes`(路由)、`resilience4j.circuitbreaker.configs.default.*`(熔断) |
| 入口 | Nginx(LB + TLS 终结 + `/gateway/**` 不对外) → 网关双实例 |
| 容器 | `deploy/Dockerfile`(多阶段构建)、`deploy/docker-compose.yml`(本地一键起:redis + mariadb + **acc** + 网关双实例 + nginx)、`deploy/nginx-gateway.conf.example`(入口样例) |

### 环境变量(生产)

```
GATEWAY_STORE=redis
GATEWAY_JWT_SECRET=<KMS 注入,勿明文入库>   # 与 ACC acc.jwt-secret 同值
GATEWAY_ACCESS_TOKEN_MAX_TTL=15m            # 短 token(access)有效期上限,超长 token 一律 401+2001
GATEWAY_CLOCK_SKEW=60s                     # 时钟容差(只放宽有效期上限判定,不放宽过期判定)
GATEWAY_REDIS_HOST / GATEWAY_REDIS_PORT / GATEWAY_REDIS_USERNAME / GATEWAY_REDIS_PASSWORD
                                           # 必须与 ACC 的 acc.redis.host/port 指向同一实例(吊销名单共享)
GATEWAY_ACC_URI=http://acc:8080            # 各域路由目标(逐个环境覆盖)
GATEWAY_INSTANCE_ID=gateway-a              # 双实例区分
GATEWAY_VERSION=0.1.0-SNAPSHOT
GATEWAY_TRUST_XFF=true                     # 仅当入口只有可信代理时保持 true
```

### 对端(ACC)必须同时满足的部署前提(2026-09-16 会话增量)

| ACC 配置 | 生产取值 | 不满足的后果 |
|---|---|---|
| `acc.session.store` | **`redis`** | 默认 `memory` 只允许测试/演练;生产取 memory 时会话族与吊销名单只在进程内,**登出/踢人静默失效**;两方向错配都启动 fail-fast(`redis` 缺 host、`memory` 却配了 host) |
| `acc.redis.host` / `acc.redis.port` | 与网关同一 Redis 实例 | 取 `redis` 而缺 `host` → **启动 fail-fast**(`IllegalStateException`,裁定 R-A8);指向别的实例 → 吊销名单不共享 |
| `acc.session.allowed-origins` | 默认留空即可（**同源放行**，裁定 R-A15）；**跨源前端**或**入口未转发原始 host** 时必须填前端入口 origin（逗号分隔） | 漏配的后果只发生在「来源 ≠ ACC 看到的请求自身来源」时:浏览器发起的换发/仅凭 Cookie 登出被来源校验拒为 **401 + 2001**（登录可用、换发不可用）。⚠️ **本手册的拓扑（浏览器 → Nginx → 网关 → ACC）必须显式配置**：SCG 会把 Host 改写成 ACC 内网地址，默认**不**转发原始 Host，故 ACC 推断不出浏览器看到的来源；两种解法任选——① 在此列出前端入口 origin（本表默认做法），② 让入口代理设置 `X-Forwarded-Host $host`（`nginx-gateway.conf.example` 已给出该行；真机演练已验证「入口转发原始 host 时同源默认放行生效」） |
| `acc.session.cookie-secure` | `true`(HTTPS 入口) | 明文链路下发长 token;置 `false` 时 ACC 启动打 WARN(仅本地/测试) |
| Redis 淘汰策略 | **`noeviction`**(禁用易失淘汰) | `allkeys-lru`/`volatile-*` 会淘汰 `revoked:jti:*` 与会话族键 → 登出后 token 又能用(**静默 fail-open**),refresh 也会提前失效 |
| `acc.jwt-secret` | 与 `GATEWAY_JWT_SECRET` 同值 | 短 token 验签失败 |

> 会话端点白名单与 Cookie 透传口径见 `services/gateway/docs/README.md` §3.2;
> 一键起的 compose 已把上述 ACC 依赖与环境变量写成 `acc` 服务的 `depends_on: redis(healthy)` + `environment`。

## 2. 上线切换步骤(首次接管)

> 前置:ACC(或首个域服务)已部署;Redis 就绪;Nginx 配置可回滚。

1. **预检**:`java -jar gateway.jar --gateway.store=redis ...` 起 A 实例,验证 `/gateway/health` 返回 `{"status":"UP","redis":"up"}`;
2. **灰度接入**:Nginx 新增 upstream 指向网关 A(保留原直连应用 upstream);将**1 个低风险接口**(如 `/api/v1/acc/me`)按路径切到网关,观察 5~10 分钟:401 比例、P95、错误率、限流次数;
3. **双实例**:起 B 实例,Nginx upstream 同时挂 A/B(健康检查自动摘除);
4. **全量切换**:`/api/v1/**` 全部指向网关;**保持应用侧原直连入口不变**(过渡期双通道并存),观察 1 个工作日;
5. **收敛**:确认无回退需求后,下线应用侧的直连入口(仅保留内网调用);
6. **域服务接入**:后续 CRED/EMP/TICKET/TRACE 等域在各环境加入路由(各自命名熔断实例),不再各自实现鉴权 Filter。

> 说明:ACC 侧内嵌鉴权 Filter 的移除(任务组 10)在网关接管稳定后执行;在移除前,网关透传身份头的同时**保留原始 `Authorization` 头**,ACC 内嵌 Filter 仍可工作(过渡期双鉴权并存,双保险)。

## 3. 验证清单(接管前必须全绿)

| # | 用例 | 期望 |
|---|---|---|
| 1 | 无 token 访问受保护接口 | 401 + 2001 |
| 2 | 合法 token 访问 | 200/业务响应;下游收到 `X-User-Id/Role/Mfa/Jti` |
| 3 | 伪造身份头 + 合法 token | 下游只见到验签身份(伪造头被剥离) |
| 4 | 白名单接口(`/api/v1/acc/captcha`)无 token | 放行(直连下游),且不携带任何 `X-User-*` |
| 5 | 路径混淆(`/api/v1/acc/./internal/x`、`//`、`%2e`) | 404 + 3006 |
| 6 | 内部接口(`/api/v1/acc/internal/**`、`/acc/realname/callback`) | 404(不可达) |
| 7 | 超限请求(AI 路径 10/min/账号) | 429 + 2004 |
| 8 | 下游超时(>路由 1s) | 503 + 5002 |
| 9 | 下游连续失败(≥4 次/失败率 ≥50%) | 熔断打开 → 503 + 5002 且带 `X-Gateway-Fallback`;恢复后半开放行 |
| 10 | **Redis 停机** | `/gateway/health` 503 DOWN;业务请求 503 + 5003(fail-closed,不静默放行) |
| 11 | 停掉一个网关实例 | 流量自动切至剩余实例,无中断 |
| 12 | 停掉全部网关实例 | 入口快速失败 503(不直连应用) |
| 13 | 运维接口非内网来源访问 | 404 |
| 14 | 超长有效期 token(如 1 小时)/ 无 `sub` 的 token | 401 + 2001(网关只认短 token;`sub` 必填) |
| 15 | **会话换发链路(2026-09-16 增量,真机实测见 `services/acc/deploy/drill/README.md` §3.1)** | — |
| 15.1 | 无 token `POST /api/v1/acc/auth/login`(白名单) | 放行直达 ACC;200 且响应体**只有短 token**,`Set-Cookie` 带 `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth` |
| 15.2 | 短 token 访问 `/api/v1/acc/me` | 200(网关验签 + 透传身份头) |
| 15.3 | 带 refresh Cookie `POST /api/v1/acc/auth/refresh` | 200 + 新短 token + 新 `Set-Cookie`(Cookie 原样透传,网关不解析) |
| 15.4 | 重放已轮换的旧 refresh(超出 5s 并发宽限窗口) | 401 + 2001,且**整族吊销**——随后原短 token 访问业务接口 → 401(`鉴权失败 reason=Token 已吊销`,证明网关从 Redis 读到吊销名单) |
| 15.5 | `POST /api/v1/acc/auth/logout`(带短 token) | 200 + 清 Cookie(`Max-Age=0`);随后该短 token → 401;**logout 不在白名单**,无 token 时 401 |
| 15.6 | 会话端点限流 | 不获豁免(落 WRITE 档),超限 429 + 2004 且下游零调用 |

## 4. 回滚

- **切换前**:改 Nginx upstream 指回原入口(分钟级);
- **全量后**:同样以 Nginx upstream 回退即可(网关无状态,回退不影响数据);
- **注意**:回滚期间若应用侧直连入口已下线,需同步恢复(第 5 步之前不要下线直连入口)。

## 5. 监控与告警

- 指标:每路由 QPS / P95 / 错误率 / 限流次数(`/actuator/prometheus`);建议对 401 率、429 次数、503(5002/5003)计数设告警;
- 日志:鉴权失败(401)、限流(429)、内部接口拦截(404)、Redis 不可用(5003)、熔断降级(5002)均有结构化日志输出;
- 健康:`/gateway/health` 供 LB 摘除;Redis 不可用 → DOWN(503)。

## 6. 已知约束 / 待办

- 路由目标 M1 初期为静态配置(改配置需重启或走配置刷新);Nacos 服务发现与配置热更新在 M1 后期;
- 吊销名单写入方 = **ACC(已落地,2026-09-16)**:登出/重用检测写 `SET revoked:jti:{jti} 1 EX <剩余有效期>`,
  网关只读;两侧**必须同一 Redis 实例**(口径见 §1 与 `services/gateway/docs/README.md` §3.2);
- 限流初值为定档初值(★压测标定):IP 200/s、读 1000/s、写 100/s、AI 10/min、资金 100/s;
- 熔断实例按路由命名(当前 `accCircuitBreaker`),新增路由须各自命名;
- **换发(refresh)链路已落地(2026-09-16)**:长 token 存 **HttpOnly + Secure + SameSite Cookie**、**7 天**,
  只经 `POST /api/v1/acc/auth/refresh` 换短 token、**不经网关业务链路**(网关不解析 Cookie);
  网关侧白名单 +2(`/api/v1/acc/auth/login`、`/api/v1/acc/auth/refresh`,**不含 logout**)。
  真机闭环(登录/换发/重放整族吊销/登出)实测见 `services/acc/deploy/drill/README.md` §3.1 与本文件 §3 第 15 组;
- **ACC 容器化未闭环(M1 已知限制)**:`services/acc/deploy/Dockerfile` 可产出镜像(classes + 运行期依赖),
  但 ACC 的 `AccConfiguration` 仍是**占位 DataSource**,容器内触库路径不可用——真实数据源注入落地前,
  compose 中的 `acc` 服务只用于固化**部署拓扑与配置口径**(Redis 依赖 + 会话存储环境变量),**不是**联调路径;
  真机联调走 `services/acc/deploy/drill`(真实 ACC 进程 + 真实 MariaDB + 内嵌真实 Redis);
- 沙箱无 Docker,`docker compose up` 的运行验证未在本机执行(仅做 compose YAML 解析校验);有 Docker 的环境可直接跑。
