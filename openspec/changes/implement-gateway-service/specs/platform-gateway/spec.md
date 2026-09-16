# 平台网关规范

## Purpose

定义平台 API 网关（GATEWAY）：全部客户端流量的唯一统一入口，承载路由转发、统一鉴权链、网关级限流、超时/熔断降级、traceId 注入、统一 Envelope 与运维接口。它是平台唯一的鉴权点，业务越权校验仍留在各服务内部。

## ADDED Requirements

### Requirement: 统一路由与双语言转发
网关 SHALL 作为四端客户端的唯一入口，把 `api.example.com/api/v1/{svc}/...` 路由到对应领域服务。`/assist/*` 与 `/aicore/*` MUST 转发到 Python 服务，其余全部路径转发到 Java 领域。服务端间接口（x-external-interfaces）MUST NOT 经网关对外暴露。

#### Scenario: 业务请求路由到领域服务
- **WHEN** 客户端向 `/api/v1/{svc}/...` 发送请求
- **THEN** 网关匹配路由并转发到目标服务实例，响应经网关返回

#### Scenario: AI 路径路由到 Python 服务
- **WHEN** 客户端向 `/assist/*` 或 `/aicore/*` 发送请求
- **THEN** 网关先鉴权与限流，再转发到 Python 服务；客户端绝不直连 Python 服务

#### Scenario: 内部接口不可从外部到达
- **WHEN** 请求指向服务端间接口（x-external-interfaces）
- **THEN** 网关没有对应路由，该请求无法从公网入口到达内部接口

### Requirement: 统一鉴权链
网关 SHALL 在转发前校验 Bearer JWT（签名与有效期）并检查 Redis 吊销名单。白名单公开路径（如 captcha、register、status）MUST 无需令牌即可放行。签名失败、过期或已吊销 MUST 返回 401 与错误码 2001。签名密钥 MUST 由 KMS 注入，且 MUST NOT 离开网关。校验通过后网关 MUST 向下游服务透传已认证身份，业务级越权校验（2002）MUST 在服务内部执行，而非在网关。

#### Scenario: 有效令牌通过并透传身份
- **WHEN** 请求携带有效且未被吊销的 JWT
- **THEN** 网关校验通过、携带已认证身份转发请求，服务自行执行 2002 越权校验

#### Scenario: 无效或已吊销令牌被拒绝
- **WHEN** 受保护路径上的请求携带缺失、格式错误、已过期或已吊销的 JWT
- **THEN** 网关返回 401 与错误码 2001，请求不会到达服务

#### Scenario: 白名单公开路径无需令牌即可通过
- **WHEN** 请求指向白名单公开路径（captcha / register / status）
- **THEN** 网关不做 JWT 校验直接转发

### Requirement: 访问令牌策略（双 token 会话）
网关 SHALL 在业务链路上只接受短期访问令牌。令牌 MUST 携带 `alg=HS256`、非空白 `sub`，且 `exp` 既未过期、也未超过配置的访问令牌最大有效期（`gateway.auth.access-token-max-ttl`，默认 15 分钟）加上有界时钟容差（`gateway.auth.clock-skew`，默认 60 秒）。违反上述任一项的令牌 MUST 以 401 与错误码 2001 拒绝。长期刷新令牌（7 天，存于 HttpOnly + Secure + SameSite Cookie）MUST NOT 在业务链路上被接受，MUST NOT 被网关解析或信任；它仅用于换取新的访问令牌。访问令牌的吊销 MUST 通过 Redis 吊销名单持续生效。

#### Scenario: 有效期过长的令牌被拒绝
- **WHEN** 已签名令牌签名有效，但 `exp` 远超访问令牌最大有效期（例如 1 小时，或把 7 天的刷新令牌当作 Bearer 令牌出示）
- **THEN** 网关以 401 与错误码 2001 拒绝，因为密钥泄露的影响面被最大有效期所限定

#### Scenario: 不含身份的令牌被拒绝
- **WHEN** 已签名令牌省略 `sub` 或携带空白 `sub`
- **THEN** 网关以 401 与错误码 2001 拒绝，而不是把空身份透传到下游

#### Scenario: 最大有效期与容差可按环境配置
- **WHEN** 部署侧覆盖 `gateway.auth.access-token-max-ttl` / `gateway.auth.clock-skew`
- **THEN** 网关按覆盖后的取值执行；未配置时适用默认值（15 分钟 + 60 秒）

#### Scenario: 时钟容差绝不延长已过期令牌
- **WHEN** 令牌的 `exp` 已过去，但仍在配置的时钟容差之内
- **THEN** 网关仍按过期拒绝，因为容差只放宽上界检查

### Requirement: 网关级限流
网关 SHALL 以 Redis + Lua 固定窗口计数器执行 IP / 账号 / 接口三级限流（原子 INCR + 过期；严格令牌桶语义保留给 M2 的 Sentinel 阶段）。接口级 key 中的路径变量 MUST 做聚合，使更换对象 id 无法绕过限流。超限请求 MUST 返回 429（网关降级时为 503）并给出友好提示。AI 链路 MUST 按账号强限（10 次/分钟初值），资金链路保护 MUST 优先级最高。

#### Scenario: 超限请求被拒绝
- **WHEN** 某个 IP、账号或接口超过其限额
- **THEN** 网关返回 429 与友好提示，请求不会到达服务

#### Scenario: AI 链路按账号强限
- **WHEN** 某账号在一分钟内超过 10 次 AI 请求
- **THEN** 网关在该窗口重置前拒绝该账号的后续 AI 请求

#### Scenario: 路径变量无法绕过接口级限流
- **WHEN** 调用方在同一路径模板上把请求分散到大量对象 id（例如 `/acc/orders/1`、`/acc/orders/2`……）
- **THEN** 它们共享同一个接口级桶，调用方被按单一桶同样限流

#### Scenario: Redis 不可用即快速失败（fail-closed）
- **WHEN** 限流存储（Redis）不可用
- **THEN** 网关以 503 快速失败，绝不静默放行流量

### Requirement: 超时、熔断与降级
网关 SHALL 按路由施加分级超时（内部 1s / 第三方支付 3s / AI 5s 初值），并在下游持续失败时 MUST 打开熔断，以统一的 503 与友好提示快速失败，且不破坏业务状态。恢复后熔断 MUST 允许半开探测。

#### Scenario: 下游超时返回 503
- **WHEN** 下游服务超过其路由超时
- **THEN** 网关返回统一的 503 与友好提示

#### Scenario: 熔断打开与恢复
- **WHEN** 下游服务持续失败、熔断打开
- **THEN** 请求以 503 快速失败；服务恢复后，半开探测重新放行流量

### Requirement: traceId 注入与统一 Envelope
网关 SHALL 在缺失时注入 `X-Request-Id`、向下游透传，并把响应包装为使用平台错误码（2001/429/503）的统一 Envelope。网关自身产生的错误 MUST 使用与服务一致的 Envelope 与错误码约定。

#### Scenario: 请求 id 被注入并透传
- **WHEN** 请求到达时未携带 X-Request-Id
- **THEN** 网关生成一个并注入请求与响应，全链路以同一 trace id 记录日志

#### Scenario: 网关错误使用统一 Envelope
- **WHEN** 网关自身拒绝请求（401/429/503）
- **THEN** 错误响应使用统一 Envelope，并携带对应的平台错误码与 traceId

### Requirement: 灰度发布路由
网关 SHALL 支持灰度分流。M1 初期的灰度分流由 Nginx 承担（按 header/cookie/IP/百分比）；自 M1 后期起，网关 MUST 支持按路由权重分流，K8s 金丝雀（5%~10% 起步、指标劣化自动回滚）保留给 M2。

#### Scenario: 灰度流量到达预期版本
- **WHEN** 配置了灰度标记（header/cookie/IP/百分比）或路由权重
- **THEN** 命中的流量被转发到灰度目标版本，其余流量保持在稳定版本

### Requirement: 运维接口
网关 SHALL 暴露用于健康检查与路由状态查询的运维接口，并在自己的 openapi.yaml 中描述。运维接口 MUST 仅允许来自白名单内部网段（网络白名单，默认 loopback + 私网网段），且 MUST 由网关自身直接提供，而不是经其路由过滤器代理。网关 MUST 无业务数据库：Redis 仅存放 JWT 黑名单（短 TTL）与限流计数，路由/限流配置一律外置。

#### Scenario: 查询健康与路由状态
- **WHEN** 运维人员从允许的内部网段查询网关健康或路由状态接口
- **THEN** 网关返回自身存活状态与当前路由表，且不含任何业务数据

#### Scenario: 白名单网段之外的调用者被拒绝
- **WHEN** 从 `gateway.ops.allowed-networks` 之外的来源调用运维接口
- **THEN** 网关返回 404，既不暴露健康载荷也不暴露路由表

#### Scenario: 不健康实例上报 DOWN
- **WHEN** 网关的 Redis 依赖不可达
- **THEN** 健康接口返回 HTTP 503 与状态 DOWN，以便负载均衡摘除该实例

### Requirement: 高可用与快速失败兜底
网关 MUST 无状态运行且至少两个实例，并自动摘除故障实例。由于网关是唯一鉴权点，当已无健康网关实例时，入口 MUST 以 503 快速失败，而不得绕过网关直连各服务。

#### Scenario: 故障实例被摘除，流量继续
- **WHEN** 其中一个网关实例故障
- **THEN** 其余实例继续提供服务，故障实例被移出实例池

#### Scenario: 无健康网关时快速失败
- **WHEN** 已无健康网关实例
- **THEN** 入口快速返回 503，而不是把客户端在无鉴权的情况下直连到各服务
