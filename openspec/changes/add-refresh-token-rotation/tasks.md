## 1. 口径与接口清单(先定稿对外契约,再动代码)

- [ ] 1.1 更新 `services/acc/docs/openapi.yaml`(接口权威源):新增 `POST /acc/auth/login`、`POST /acc/auth/refresh`、`POST /acc/auth/logout` 三路径与请求/响应 schema(LoginRequest/TokenPair/SessionView/LogoutRequest),标注短 token 在 body、长 token 仅 `Set-Cookie`(`HttpOnly; Secure; SameSite=Lax; Path=/api/v1/acc/auth`),错误码统一 `2001`;验证:yaml 解析通过(`node -e "require('js-yaml')..."` 或等价),三路径出现在文档中且与 spec `acc-session` 的场景一一对应
- [ ] 1.2 更新 PDD `docs/design/产品设计文档.md`:§6.4.1 接口清单 +3 行、§8.4.1 登录态段补"端点 + 轮换 + 重用检测 + Cookie 属性 + ACC 生产需 Redis"、§2.8/§3.1 存储与依赖注、§6.2 错误码注(复用 2001)、新增版本史行 **v1.18**;验证:grep 三处口径一致、index 表中 16→19 个前端接口
- [ ] 1.3 更新 `docs/design/高并发架构演进设计.md` §7.3 令牌策略段(补换发/轮换/重用检测、会话键容量口径)与 §2 缓存容量,追加版本注 **v0.9**;验证:与 PDD v1.18 口径互洽、无"待实现"残留
- [ ] 1.4 更新 `docs/design/微服务边界与职责基准.md`:§2.2 ACC 边界卡(新增会话凭据职责 + Redis 数据归属)、§2.15 GATEWAY 边界卡(白名单/Cookie 透传、**签发不属网关**)、C14 追加 2026-09-15 变更记录、版本 **v1.9**;验证:边界划分无歧义(签发=ACC、校验=网关)
- [ ] 1.5 更新 `docs/待评审事项汇总.md`:**G-07 关闭/定档**(换发接口实现形态已定);新增两条确认项(登录因子是否叠短信码、`SameSite` 取值与子域);验证:条目状态与实际实现一致
- [x] 1.6 承接标注:`openspec/changes/implement-gateway-service/design.md` D15 与 `tasks.md` §14.1 标注"由 `add-refresh-token-rotation` 承接";验证:两处交叉引用可跳转、原变更任务清单状态不变(除标注) —— **已由评审批次修复波执行(2026-09-15,提交 `12ac50e`)**:`design.md` D15 与 `tasks.md` §14.1 的承接注记均已落地,§14.1 行首仍为 `- [ ]`、§14.3 状态未变(只追加承接说明,不宣告任务状态变更)

## 2. ACC 会话存储与端口

- [ ] 2.1 定义会话存储端口(会话族 + refresh 映射 + 吊销写入),含键名/TTL 语义(`acc:session:{familyId}`、`acc:refresh:{jti}`、`revoked:jti:{jti}` = 网关共享契约);验证:单测覆盖键构造与 TTL 计算(用假实现)
- [ ] 2.2 提供 InMemory 实现(单元测试/演练兜底)与 Redis 实现(生产),由配置切换;验证:两实现通过同一套端口契约测试(InMemory 直跑、Redis 实现用假客户端)
- [ ] 2.3 装配接入 `AccConfiguration`,Redis 不可用时登录/换发/登出快速失败而非静默降级;验证:故障注入单测(存储抛错 → 5xx),且不产生任何 token 签发副作用

## 3. ACC 会话流程(核心)

- [ ] 3.1 实现登录流程:手机号 → 账号查询(不存在/已注销/冻结即拒)→ 人机验证票据消费 → 建会话族 → 签发短/长 token;验证:单测矩阵(成功/账号不存在/已注销/冻结/票据无效/票据重复消费)
- [ ] 3.2 实现换发流程:校验 refresh(签名 + 存在 + 未过期 + 未轮换)→ 轮换签发 → 写新映射并标记旧 jti;验证:单测(成功轮换、旧 token 失效、过期/未知被拒)
- [ ] 3.3 实现重用检测:命中"已轮换"标记 → 吊销该会话族全部短 token(写 `revoked:jti:{jti}`,TTL=剩余有效期)与长 token → 记审计事件;验证:单测断言整族吊销 + 审计日志字段(不含 token 原文)
- [ ] 3.4 实现并发宽限期(轮换后极短窗口内的重复换发不判泄露);验证:单测锁定窗口内/外两种行为
- [ ] 3.5 实现登出:短 token `jti` 入黑名单(TTL=剩余有效期)+ 会话族失效 + 幂等重复登出 + 清除 Cookie;验证:单测(首次登出/重复登出/仅凭 Cookie 登出 + 来源校验)
- [ ] 3.6 签发口径对齐网关策略:`exp - iat = 900s`、声明含 `sub/role/mfa/jti/iat/exp`,并以常量集中定义;验证:单测断言声明与有效期,且**签发的 token 能通过网关 `JwtVerifier` 的相同校验规则**(复用同一批断言)

## 4. ACC 控制器与鉴权接入

- [ ] 4.1 新增会话控制器(login/refresh/logout),响应统一 Envelope,日志脱敏(不落 token/Cookie 原文);验证:组件测试断言响应结构、`Set-Cookie` 属性、日志断言无敏感字段
- [ ] 4.2 `TrustedHeaderAuthFilter` 白名单加入 `/acc/auth/login`、`/acc/auth/refresh`(**不含 logout**);验证:单测(无身份头可访问登录/换发、logout 无身份头 401、近似路径 `/acc/auth/loginAny` 不被放行)
- [ ] 4.3 换发/仅 Cookie 登出的来源校验(`Origin`/`Referer` 白名单);验证:单测(合法来源通过、跨站来源 403/2001 且不产生轮换副作用)

## 5. 网关增量

- [ ] 5.1 `application.yml` 白名单增补登录与换发路径(段边界匹配,不含 logout);验证:集成测试(无 token 登录/换发放行、logout 401、`/api/v1/acc/auth/loginAny` 与混淆路径 404/401)
- [ ] 5.2 Cookie 透传与非解析:确认网关不改写 `Cookie`/`Set-Cookie` 且不据 Cookie 鉴权;验证:集成测试(换发响应 `Set-Cookie` 原样到达客户端;仅 Cookie 无 Bearer 时受保护路径 401)
- [ ] 5.3 会话端点不获限流豁免;验证:集成测试(IP 容量置小后登录端点返回 429 + 2004,下游未收到请求)

## 6. 测试与门禁

- [ ] 6.1 ACC 测试补齐(会话族/轮换/重用/宽限/登出/并发单飞),`mvn -f services/acc/pom.xml verify` 全绿且 jacoco 门禁不降;验证:用例数与覆盖率报告
- [ ] 6.2 网关测试补齐(白名单/Cookie/限流),`mvn -f services/gateway/pom.xml verify` 全绿;验证:用例数与 jacoco 报告
- [ ] 6.3 提交前执行 `commit-check` 门禁(语义清单 + hook 等价复核,与上一变更同口径);验证:门禁通过并记录执行方式

## 7. 真机联调(沿用 ACC 真机桩)

- [ ] 7.1 扩展 `services/acc/deploy/drill`(真实 Redis 或桩内嵌 Redis + 会话断言脚本);验证:一条命令起"真实 ACC + 真实 MariaDB + Redis"
- [ ] 7.2 跑通闭环链:登录 → 带短 token 访问业务接口 200 → 换发 → **旧 refresh 重放被拒且整族吊销** → 原短 token 立即 401 → 重新登录取新对 → 登出后短 token 立即 401;验证:演练记录逐项输出(含网关侧 401 证据)
- [ ] 7.3 更新 `services/gateway/deploy/README.md` 验证清单(新增换发链路条目)与 `docker-compose.yml`(ACC 服务补 Redis 依赖);验证:compose 文件 yaml 校验通过、清单条目与演练一致

## 8. 收口

- [ ] 8.1 同步服务基线:`services/acc/docs/README.md`(接口/依赖/数据归属 + 生产需 Redis)、`services/gateway/docs/README.md`(白名单与 Cookie 透传);验证:两份基线与 PDD/openapi 口径一致
- [ ] 8.2 `openapi.apifox.json` 重打包(自动产物,禁手改);验证:重打包产物包含三条新路径
- [ ] 8.3 `openspec validate add-refresh-token-rotation` 通过、按粒度拆分提交(建议:接口清单+文档 / ACC 实现 / 网关增量 三个提交);验证:校验输出与提交历史
