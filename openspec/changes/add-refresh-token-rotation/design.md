## Context

动机与范围见 `proposal.md`（Why / What Changes）。当前状态与约束：

- **已定档但未实现**：PDD v1.17 §8.4.1 定档双 token（access 15 分钟 / refresh 7 天 HttpOnly Cookie）；网关侧**校验**已落地（`JwtVerifier` 强制 `alg=HS256`、`sub` 非空白、`exp` ≤ `access-token-max-ttl`(15m) + `clock-skew`(60s)），见 `openspec/changes/implement-gateway-service/design.md` D15。
- **签发侧空白**：`services/acc/docs/openapi.yaml` 无任何 `/acc/auth/**`；ACC 的 `JwtCodec` 只有签发能力且无调用方；网关的吊销名单（`revoked:jti:{jti}`）**没有任何写入方**——契约已固化但悬空。
- **ACC 现状**：M1 模块化单体，`AccConfiguration` 显式装配（不引 starter）；Redis 目前只有 `InMemoryStringRedisOps` 兜底（M1 无 Redis 部署）；数据层 2026-09-15 刚由"长驻未提交会话"修为自动提交会话，事务边界问题由并行变更 `fix-acc-transaction-boundary` 收敛（本变更不依赖其完成，但两者都触碰 ACC 数据/装配层，落地时需避免同文件冲突）。
- **网关现状**：`gateway.auth.whitelist` 目前三条（captcha/register/realname-status），白名单按**改写前原始路径 + 路径段边界**匹配；Cookie 头目前既不读取也不改写（无相关代码）。
- **前端现状**：`apps/**` 只有脚手架（`apps/pc/src/{main.tsx,App.tsx}`），api-client 尚未实现，故本变更只固化接入约定。

## Goals / Non-Goals

**Goals:**

- 让定档的双 token 策略**可运行**：能签发、能换发、能吊销，且吊销对网关**立即生效**。
- 用**会话族 + 重用检测**把长 token 泄露的影响面收敛到"整族即时失效"，而不是"7 天内持续可用"。
- 把网关从"能校验但无写入方"补成"校验 + 有权威写入方"的完整闭环，且**不改变**网关作为唯一鉴权点的边界。
- 明确会话数据的 Redis 归属与容量口径，使 M1 部署形态（是否必需 Redis）有确定答案。

**Non-Goals:**

- 登录因子扩展（短信验证码、微信/支付宝 OAuth 换 code）——M2 及以后；本变更登录因子 = 手机号 + 人机验证票据。
- 管理端二次鉴权 / MFA 强化、多设备会话列表与单点下线界面。
- 前端 api-client 实现（脚手架未就绪），仅落接入约定。
- 不引入 JWT/JSON 第三方库（沿用 ACC 手写 `JwtCodec` 与网关手写 `JwtVerifier` 的既有取舍）。

## Decisions

### D1 签发端点归属 ACC，网关保持"只校验"

三个端点（login/refresh/logout）全部落在 ACC；网关只做 ①白名单放行 ②Cookie 原样透传 ③吊销名单读取。

- **理由**：登录需要业务数据（账号状态、注销/冻结、人机验证票据消费）与签名密钥，这些都在 ACC；网关无业务库，放进去就得回源 ACC，反而多一跳且打破"网关无业务数据"边界（SSOT §2.15）。
- **备选**：网关签发（密钥集中，但网关必须持业务状态校验 → 与边界冲突）；拆开（签发在 ACC、吊销由网关写）→ 见 D3。

### D2 refresh 单次使用 + 轮换 + 会话族重用检测

每次换发消费旧 refresh、签发新 refresh；旧 refresh 被再次使用时判定泄露 → 吊销整族。

- **理由**：refresh 生命周期 7 天，是攻击面最大的一件凭据；单次使用 + 重用检测是 OAuth 2.0 BCP 的推荐形态，能同时获得"泄露可检测"与"泄露影响可收敛"。
- **备选**：不轮换（最简，但 7 天内泄露即长期沦陷）；轮换但无重用检测（实现简单，重放窗口存在且不可发现）。
- **存储形态**：`acc:session:{familyId}` 存族元数据（账号、创建时间、状态、当前 refresh jti）；`acc:refresh:{jti}` → familyId 映射（TTL ≤ 7 天）。轮换 = 写新 jti 映射 + 把旧 jti 标记为"已轮换"（保留到原 TTL 结束，正是为了能识别重放）。**标记必须保留**，否则重放看起来只是"未知 token"，无法触发整族吊销。

### D3 吊销写入方 = ACC，网关只读（契约沿用已固化的键格式）

登出/整族吊销由 ACC 直接写 `revoked:jti:{jti}`（值占位、TTL = 该短 token 剩余有效期），网关继续只读该键。

- **理由**：契约（键格式 + TTL 语义）已在网关变更 D3 固化，写入方落在签发侧最自然；网关无需新增写接口。
- **代价（须显式接受）**：ACC 生产运行**必须能访问与网关同一个 Redis**——这把 ACC 从"M1 无 Redis 部署"推到"生产需 Redis"。兜底：无 Redis 环境（单元测试/演练）继续用 InMemory 实现，但**不得**用于有真实用户的部署（否则登出无效）。
- **备选**：网关暴露内部吊销接口由 ACC 调用（多一跳 + 网关需新增内部端点与鉴权）；网关订阅 ACC 事件（M1 无 MQ 依赖，过重）。

### D4 短 token 有效期与声明对齐网关策略

ACC 签发 `exp - iat = 900s`（15 分钟），声明含 `sub/role/mfa/jti/iat/exp`。**不新增配置项**，15 分钟作为 ACC 侧常量并在服务基线记录；网关侧上限（`gateway.auth.access-token-max-ttl`）仍是唯一可配的守门值——两侧不同源会漂移，故以"ACC 签发值 ≤ 网关上限 - 容差"为不变式，并用联调用例锁定。

### D5 错误码复用 2001，不新增错误码

登录因子失败、refresh 过期/非法/重放、登出参数缺失统一 `2001 未登录 / Token 失效`（HTTP 401）。

- **理由**：客户端对上述情形的处置完全相同（重新登录），区分只会泄露"该 token 是否存在/是否被重用"等攻击者可利用的信息；也避免改动 `_common` 错误码权威源与 `ErrorCodes` 表。
- **备选**：新增 `2005 会话已失效`/`2006 令牌重放`——增加对外接口面与文档同步面，收益（可观测性）可由**审计日志 + 安全指标**替代（重放事件记日志与计数，不进响应码）。

### D6 换发端点的 CSRF 与 Cookie 口径

长 token：`HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth`。换发校验 `Origin`/`Referer` 属于平台来源白名单；短 token 只走 `Authorization: Bearer`，不走 Cookie。

- **理由**：Cookie 自动携带 → 必须防 CSRF；把 Cookie 的 `Path` 限定在会话端点，使业务接口完全不受 Cookie 影响（也就不需要全站 CSRF Token）。`SameSite=Lax` 兼顾跨站回跳体验（严格模式会打断从外部链接进入的换发）。
- **备选**：`SameSite=Strict`（更严，但外部入口首跳不携带 Cookie，需额外引导）；双提交 CSRF Token（更复杂，收益在当前场景有限）。

### D7 网关白名单增项与"路径段边界"约束

白名单新增 `/api/v1/acc/auth/login`、`/api/v1/acc/auth/refresh`（**不含 logout**）。匹配沿用既有的段边界语义（网关变更 D13：`/registerAny` 不得蹭 `/register`），且路径规范化在先（`%2e`、`//`、`..` 一律拒绝）。

- **理由**：这两个端点是"无短 token 时的必经入口"；logout 有短 token 可用，白名单化只会削弱保护。近似路径与混淆路径必须在守卫层被拒，否则白名单就是绕过点。

### D8 会话数据归属与容量口径

会话族/refresh 状态属 **ACC 的缓存类数据**（非业务库、非权威业务数据），落 Redis；不设 ACC 业务表，不写 `er.md`。容量口径：refresh 记录数 ≈ 7 天内活跃会话数，单条记录 < 200B（jti → family 映射 + 少量元数据）；按"注册用户 10 万 / 并发在线 1 万"的 M1 口径，量级在数十 MB，可在既有 Redis 内承载（写入 PDD §2.8/§3.1 与高并发 §2 的容量口径）。

## Risks / Trade-offs

- [ACC 生产被迫引入 Redis 依赖，M1 部署形态变化] → 显式写入 PDD/SSOT/部署件；无 Redis 环境仅允许测试兜底；Redis 不可用时登录/换发/登出**快速失败**，绝不签发"无法吊销"的 token。
- [轮换 + 重用检测在并发换发下可能误判泄露]（前端多标签页同时换发，第二发使用刚被轮换的 refresh） → 采用**短宽限期**：旧 refresh 在轮换后极短窗口（如 5 秒）内重复出现视为并发重试（返回同一新 token 对或直接失败但不吊销），超出窗口才判定泄露；前端侧约定**单飞（single-flight）换发**。
- [重放检测依赖"已轮换标记"保留 7 天，Redis 容量与淘汰策略互相牵制] → 标记 TTL 与原 refresh 一致（到期同消失，不会无限累积）；Redis 若配置 LRU 淘汰可能提前丢失标记 → 明确要求会话键所在实例**禁用易失淘汰**（或使用独立 DB/前缀隔离）。
- [登出需短 token，若短 token 已过期则登出请求被网关拦下] → 登出**同时接受**"有效短 token"或"有效长 token Cookie"两种凭据；仅凭 Cookie 的登出仍校验 `Origin`/`Referer`（与换发同口径）。
- [网关与 ACC 对 15 分钟的认知漂移] → 不变式"ACC 签发 ≤ 网关上限 − 容差"，由真机联调用例锁定（签发后立即过网关）。
- [与并行变更 `fix-acc-transaction-boundary` 同改 ACC 装配/数据层] → 两变更按序落地：先事务边界（数据层底座），后会话端点（新写入路径天然落在事务内）；若并行开发则先各自只读核对 `AccConfiguration` 改动点，避免同文件冲突。

## Migration Plan

1. **阶段 1（口径）**：PDD v1.18 §6.4.1/§8.4.1/§6.2、高并发 v0.9 §7.3、SSOT v1.9 §2.2/§2.15/C14、待评审汇总 G-07 关闭 + 新增确认项；承接标注 `implement-gateway-service` D15/§14.1。**先定稿接口清单再动代码**（openapi 权威源变更）。
2. **阶段 2（ACC 实现）**：Redis 会话端口（真实实现 + InMemory 测试兜底）→ `SessionFlow`（登录/换发/登出）→ 控制器 → 白名单接入 → 单测/组件测试（轮换、重用检测、并发宽限、登出幂等）。
3. **阶段 3（网关增量）**：白名单增项 + Cookie 透传与"仅 Cookie 不过鉴权"用例 + 限流不豁免用例；`deploy` 验证清单 +1 条换发链路。
4. **阶段 4（真机联调）**：沿用 `services/acc/deploy/drill` 真机桩（真实 MariaDB + 真实进程），新增 Redis（真实实例或同一桩内嵌），跑通"登录 → 访问业务接口 → 换发 → 旧 refresh 重放被拒且整族吊销 → 登出后短 token 立即 401"。
5. **回滚**：本变更为新增端点，回滚 = 撤回网关白名单两项 + 下线 ACC 会话端点（旧口径"无登录"恢复可用，不影响既有接口）；会话键可按前缀清理（`acc:session:*`、`acc:refresh:*`），网关吊销名单本就短 TTL，无需清理。

## 实施期修订：最终评审修复波（FIX-1，2026-09-16）

> 来源：最终整体评审（区间 `290d66e..5a08850`，1 Critical / 2 Important / 12 Minor）与控制器裁定清单
> `.superpowers/sdd/final-fix-wave.md`。逐条证据（RED/GREEN、文件:行、真机原始输出）见
> `.superpowers/sdd/final-fix-report.md`；本段只登记**对已生效决策的修订**与**新增的已知残留**。

### R1（A1，Critical）族寿命与「已轮换标记」寿命**只由 refresh 有效期决定**——修订 D2 的落地口径

D2 的原实施把**短 token 的到期时刻**写进了族记录的 `expiresAtMillis`（`FamilyRecord.withAccessJti`），
使「已轮换标记」与「已吊销族」记录的寿命从 7 天塌缩为 ≈15 分钟：**轮换 15 分钟后重放旧 refresh 落入
「未知 token」分支，不整族吊销、不记审计**——D2 的重用检测承诺在常见时序下失效（宽限重试路径下族键
也会 15 分钟后消失，7 天 refresh 随之失效）。

**已生效口径（本波修订后）**：`withAccessJti` 只更新 `accessJtis` 条目中的到期时刻；族 `expiresAtMillis`
（以及两个实现写入的族键 TTL）**只由 refresh 有效期决定**，任何 access jti 的绑定/轮换都不得缩短它。
回归防线三条：`SessionFlowTest`（可注入时钟推到 >15 分钟重放 → 仍整族吊销 + 审计）、端口契约
`AbstractSessionStoreContractTest#bindAccessJtiKeepsFamilyLifetime`（两实现同跑）、真机演练族键 TTL 断言
（`acc:session:*` 必须为 1e5 秒量级）。

### R2（A2，Important I1，裁定 R-A15）来源校验改为「**同源默认放行**」——修订 D6 的 CSRF 口径

D6 原口径「`acc.session.allowed-origins` 为空 = 任何带来源头的请求一律拒绝」与浏览器现实冲突：浏览器对
POST **一定**发送 `Origin`，按现部署件配起来就是「登录可用、第一次换发必 401」（每 15 分钟强制重登）。

**已生效口径（本波修订后）**：带来源头时先与**请求自身来源**（`scheme://host[:port]`，默认端口与省略写法
等价）比对——**同源直接放行**；仅**跨源**才要求命中 `acc.session.allowed-origins`。无来源头（curl/移动端/
服务间调用）保持放行；**给不出请求自身来源时按跨站处置（fail-closed，不放宽）**。请求自身来源优先取入口/
网关写入的 `X-Forwarded-Proto/Host/Port`（`AuthController#requestOrigin`）。跨站攻击者无法用受害者站点的
`Origin` 伪造请求（Origin 由浏览器按真实发起方设置），故本修订不削弱 CSRF 防护。

**已知残留（本波真机实测，需控制器/后续波次处置）**：Spring Cloud Gateway **会改写 `Host`**（指向 ACC 内网
地址）且**默认不转发原始 `Host`** ⇒ 在「浏览器 → Nginx → 网关 → ACC」拓扑下，ACC 推断不出浏览器看到的
来源，同源默认放行**不会自动生效**，必须二选一：① 配 `acc.session.allowed-origins`；② 让入口代理设置
`X-Forwarded-Host $host`（`services/gateway/deploy/nginx-gateway.conf.example` 已给出该行；真机演练 3.8 已
验证「入口转发原始 host ⇒ 200」，3.9 验证直连形态 200，3.6/3.7 验证跨站仍 401 且不轮换）。若希望**不改
入口**也无需维护白名单，需要网关侧保留原始 `Host`（或由网关自行补 `X-Forwarded-Host`）——属
`services/gateway/src/main/**`（本波允许清单之外），已登记待控制器裁定。

**已解决（R-A16，2026-09-16）**：控制器裁定「网关侧保留原始 Host 为主，入口头为备」，网关 acc 路由启用
SCG 的 `PreserveHostHeader` 过滤器（`services/gateway/src/main/resources/application.yml`，预留路由同口径），
原始 `Host` 原样到达 ACC ⇒ 上述约束①/②**不再是默认拓扑的必备项**：入口按常规 `proxy_set_header Host $host`
透传即可，同源默认放行自动生效（ACC 侧 `Host` 未带端口时按 scheme 取默认端口，归一化后与浏览器 `Origin`
等值）。**保留的部署约束**：链路中若还有其它代理需自行透传 `Host`；HTTPS 入口（TLS 在入口终结）仍需入口
透传 `X-Forwarded-Proto $scheme`（scheme 不能由 `Host` 推断）；`X-Forwarded-Host $host` 降级为**备案/双保险**
（`nginx-gateway.conf.example` 保留该行并注明）。回归防线：网关集成用例
`GatewayPreserveHostIntegrationTest`（下游收到的 `Host` = 客户端 `Host`，含带端口形态；重写/白名单/伪造头剥离
不受影响）+ 真机演练 3.10（只带同源 `Origin`、无 `X-Forwarded-*` → 200 且真轮换）/3.11+3.12（`Origin:
https://evil.example` → 401 + 2001 且不轮换），原始输出见
`.superpowers/sdd/add-refresh-token-rotation/drill3/` 与 `services/acc/deploy/drill/README.md` §3.1。

### R3（B11）族记录读-改-写原子化——修订 D2/D8 的存储实现口径

族记录是整条 JSON 覆写：`bindAccessJti`/`markRevoked`/`rotate` 的朴素「读-改-写」在并发下会丢
`accessJtis`（**丢掉的短 token 因此逃过整族吊销**）或丢轮换标记。**已生效口径**：Redis 实现用一段
**Lua CAS（比较并写入）+ 有界重试**（快照被并发改过即返回 0 → 重读重算；轮换写回前与最新记录合并
`accessJtis`），InMemory 实现对族记录更新加互斥并同样合并；CAS 重试耗尽抛
`SessionStoreUnavailableException`（fail-closed，绝不静默丢绑定）。回归：端口契约新增「8 线程 × 8 轮并发
绑定后族内 jti 无丢失」与「轮换按旧快照写回不丢并发绑定的 jti」（两实现同跑）。

### R4（B6/B7/B8/B9/M1/M2/M3/F5/F6）其余顺修（口径级）

- **B6**：`acc.session.access-token-ttl-seconds` 由「可配却被忽略」改为**真正生效并夹紧 `[60, 900]`**
  （越界启动 WARN；上限 = 网关策略，保持 D4 的「ACC 签发 ≤ 网关上限 − 容差」不变式）；同一有效值同时驱动
  签发与族内 jti 绑定，`SessionView.expiresIn` 随之回报有效值。
- **B7**：openapi 前端接口计数更正为 **18**（本文件 §8 的 `tasks` 与 PDD §6.4.1 说明同步）。
- **B8**：`acc.session.cookie-secure=false` 启动 WARN（D6 的 Cookie 口径不变，仍要求生产 `Secure`）。
- **B9**：部署件 Redis 淘汰策略由 `allkeys-lru` 改为 **`noeviction`**（会话族/refresh/吊销键全带 TTL，
  `volatile-*` 同样会淘汰它们；吊销键被淘汰 = 登出静默 fail-open），并写入前提表——落实 Risks 中
  「会话键所在实例禁用易失淘汰」。
- **F5/F6**：两个 `FilterRegistrationBean` 显式 `DispatcherType.REQUEST`；`beginRequest` 重入显式拒绝；
  「提交发生在响应写出之后」登记进过滤器 Javadoc 与 `fix-acc-transaction-boundary/design.md` D6 残留段。
- **M1/M2/M3**：修掉一条恒真断言与一条空转契约用例（`Assumptions.abort`），删除死类型
  `ConsumeResult.RetryableRace`。

## Open Questions

- 登录是否必须叠加短信验证码（当前口径为免密 + 人机验证）：若要求短信，则需新增短信通道接口与频控口径 —— 已登记 `docs/待评审事项汇总.md`，不改变本变更的规格与任务分解（登录因子实现细节）。
- `SameSite` 最终取值（Lax / Strict）与是否使用独立子域承载会话端点：影响跨站回跳体验，实现时可切，不影响本变更的决策与场景。
- 会话端点是否单独使用更严的限流档位（如登录 5 次/分/IP）：当前规格只要求"受 IP 限流约束且不豁免"，档位可由 `gateway.rate-limit.*` 后续标定。
