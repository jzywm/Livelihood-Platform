## Why

平台登录态已于 2026-09-15 定档为**双 token**（access 15 分钟 + refresh 7 天 HttpOnly Cookie，PDD v1.17 §8.4.1、高并发 v0.8 §7.3），网关侧**校验策略**也已落地（`alg=HS256`、`sub` 必填、`exp` ≤ 15m + 60s 容差）。

但**签发侧一个端点都没有**：`services/acc/docs/openapi.yaml` 的 16 个前端接口里没有 `/acc/auth/**`，ACC 的 `JwtCodec` 只具备签发能力却无任何调用方，网关的 Redis 吊销名单也没有写入方。后果是定档的策略实际上无法上线——用户拿不到 token（前一轮真机联调只能用演练桩代签）、登出与踢人无效、refresh 轮换无从验证。

本变更补齐**会话凭据的完整生命周期**（登录签发 → 换发轮换 → 登出吊销），使既定策略从"口径与校验"走到"可用闭环"。

## What Changes

- **新增 ACC 会话端点**（接口清单变更，权威源 `services/acc/docs/openapi.yaml`）：
  - `POST /api/v1/acc/auth/login`：mobile + captchaToken 免密登录（短信验证码登录 M2），首次签发 access(15min) + refresh(7d)
  - `POST /api/v1/acc/auth/refresh`：以 Cookie 中的 refresh 换发新 token 对，**单次使用 + 每次轮换**
  - `POST /api/v1/acc/auth/logout`：吊销当前会话（access 立即进黑名单；refresh 族标记失效）
- **refresh 轮换 + 重用检测（会话族）**：refresh 单次使用；重放一个已轮换过的 refresh 视为泄露信号 → **吊销整条会话族**（含该族所有 access `jti`）并记安全事件
- **Redis 结构新增/明确**：`acc:session:{familyId}`（会话族元数据）、`acc:refresh:{jti}` → family（7 天 TTL）、`revoked:jti:{jti}`（网关读取的黑名单键，**契约沿用 `implement-gateway-service` D3**：`SET revoked:jti:{jti} 1 PX <剩余 TTL>`）
- **网关侧增量（不改变"唯一鉴权点"）**：白名单新增登录/换发路径（无有效短 token 时的必经入口）；登出**不**进白名单（需短 token）；`Cookie` / `Set-Cookie` 原样透传且网关不解析 Cookie
- **BREAKING（部署/依赖口径）**：ACC 由「M1 无 Redis 部署（InMemory 兜底）」变为「**生产需 Redis**」——会话族与吊销写入必须与网关读写同一个 Redis；无 Redis 环境仅保留测试/演练兜底
- **错误码口径**：登录因子错误、refresh 失效/过期/重放统一复用 `2001 未登录 / Token 失效`（不新增错误码；客户端处置一致 = 重新登录），重用检测额外产出审计日志与安全指标

**非目标**：短信验证码登录、微信/支付宝 OAuth 换 code 登录（复用 I1 实名链路的第三方登录）、管理端二次鉴权与 MFA 强化、多设备会话列表/单点下线界面、前端 api-client 实现（前端脚手架尚未落地）。

## Capabilities

### New Capabilities

- `acc-session`: ACC 会话凭据生命周期——登录签发（登录因子与失败口径）、refresh 单次使用与轮换、会话族与重用检测、登出/踢人吊销、Cookie 属性与 CSRF 口径、Redis 数据归属与容量口径
- `platform-gateway`: 网关对会话端点的入口口径增量——`/api/v1/acc/auth/**` 白名单边界（登录/换发放行、登出受保护）、Cookie 透传与非解析、吊销名单读取契约不变。**沿用 `implement-gateway-service` 已建立的 capability 路径**（该变更尚未归档，故本变更同样以 ADDED 形式增量，不另立近义路径）

### Modified Capabilities

（无。`openspec/specs/` 目前尚无已归档 capability，本变更两份 delta 均为增量。）

## Impact

**代码（规划范围内，实施在 apply 阶段）**
- ACC：新增 `controller/AuthController`、`application/SessionFlow`（登录/换发/登出）、`infrastructure/auth/{SessionFamilyStore, RefreshTokenStore}`（Redis 端口 + InMemory 测试兜底）；`AccConfiguration` 增装配；`TrustedHeaderAuthFilter` 的白名单加入 `/acc/auth/login`、`/acc/auth/refresh`
- 网关：`application.yml` 白名单增项；Cookie 透传与白名单边界需补测试（无业务代码改动）
- 依赖：ACC 生产运行需真实 Redis 客户端（现有 `InMemoryStringRedisOps` 保留为测试兜底）

**接口权威源与接口文档**
- `services/acc/docs/openapi.yaml`：+3 路径 + 登录/换发/登出 schema + `Set-Cookie` 响应头描述（HttpOnly/Secure/SameSite/Path）
- `services/_common/openapi.yaml`：无新增错误码（复用 2001），仅一致性核对
- `openapi.apifox.json`：定稿后需重打包（自动产物，禁手改）

**设计口径文档（需同步，含版本行）**
- PDD：§6.4.1 ACC 接口清单 +3 行；§8.4.1 登录态段补端点与轮换/重用检测语义、Cookie 属性、**ACC 需 Redis**；§6.2 错误码注（复用 2001）；§2.8/§3.1 存储与依赖；版本史 **v1.18**
- 高并发：§7.3 令牌策略补换发/轮换/重用检测与容量口径（refresh 存储量 ≈ 7 天内活跃会话数）、§2 缓存容量同步；版本注 **v0.9**
- 边界基准 SSOT：§2.2 ACC 边界卡（新增会话凭据职责 + Redis 数据归属）、§2.15 GATEWAY 边界卡（白名单与 Cookie 透传，**签发不属网关**）、C14 变更记录；版本 **v1.9**
- `docs/待评审事项汇总.md`：**G-07（换发接口实现形态）定档/关闭**；新增登记「登录因子（免密 vs 短信码）」与「Cookie 属性（SameSite 取值）」确认项
- 服务基线：`services/acc/docs/README.md`（接口清单/依赖/数据归属 + 生产需 Redis）、`services/gateway/docs/README.md`（白名单与 Cookie 透传、验证清单 +1 条换发链路）
- 部署件：`services/gateway/deploy/{docker-compose.yml,README.md}`（ACC 增 Redis 依赖与验证项）
- 承接标注：`openspec/changes/implement-gateway-service/design.md` D15「换发接口尚未实现」与 `tasks.md` §14.1 标注由本变更承接

**前端约定（本次仅落口径，无代码）**
- `apps/**` 目前只有脚手架（`apps/pc/src/{main.tsx,App.tsx}`），api-client 未实现；本变更只固化接入约定：refresh 由浏览器经 HttpOnly Cookie 自动携带、前端**不得**把 refresh 存入 localStorage、access 过期后单飞（single-flight）换发一次并重试原请求、换发失败即跳登录

**验收影响**
- ACC 用例新增会话族/轮换/重用检测/并发单飞换发；网关新增白名单与 Cookie 透传用例；真机联调矩阵新增"登录 → 换发 → 旧 refresh 重放被拒 → 登出后 access 立即 401"链
