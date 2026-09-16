# 平台网关能力规范

## Purpose

平台唯一入口（网关服务 GATEWAY）接入层的行为契约：全量流量的路由与路径重写、以网关为唯一鉴权点的统一鉴权、访问令牌策略、网关级限流、超时／熔断／降级、traceId 与统一 Envelope、运维端点的访问控制，以及会话端点在入口处的可达性与防护边界。

## ADDED Requirements

### Requirement: 会话端点在入口处的可达性

网关 SHALL 允许 **登录** 与 **换发** 端点在**无有效访问令牌**的情况下通过入口（它们是在手中没有访问令牌时获取凭据的唯一途径），但 MUST NOT 因此放宽任何其他路径。**登出**端点 MUST 保持受保护（需要有效访问令牌），且 MUST NOT 加入白名单。会话端点的匹配 MUST 遵循**路径段边界**，因此形似路径如 `/api/v1/acc/auth/loginAny` MUST NOT 被放行。

#### Scenario: 登录与换发在无访问令牌时可达

- **WHEN** 一个不带访问令牌的请求指向登录端点或换发端点
- **THEN** 网关将其转发至下游服务

#### Scenario: 登出保持受保护

- **WHEN** 一个不带有效访问令牌的请求指向登出端点
- **THEN** 网关返回 401 与 `2001`，该请求不会到达下游服务

#### Scenario: 形似路径不得蹭用白名单

- **WHEN** 一个不带访问令牌的请求指向诸如 `/api/v1/acc/auth/loginAny` 或 `/api/v1/acc/auth/login/../me` 的路径
- **THEN** 网关不将其视为白名单路径，并按鉴权规则或路径规范化规则予以拒绝

### Requirement: 会话 Cookie 原样透传网关

网关 SHALL 将与会话端点相关的 `Cookie` 请求头与 `Set-Cookie` 响应头原样透传，且 MUST NOT 解析、改写或剥离刷新令牌 Cookie。网关 MUST NOT 基于 Cookie 作出任何鉴权判定（鉴权仅使用 `Authorization: Bearer` 中的访问令牌）。网关 MUST NOT 记录 Cookie 原文。

#### Scenario: 换发响应携带 Set-Cookie 回传

- **WHEN** 下游服务在换发响应上设置 `Set-Cookie`
- **THEN** 客户端收到该 `Set-Cookie`，其属性未被网关改动

#### Scenario: 仅有 Cookie 不构成鉴权

- **WHEN** 一个请求携带有效的刷新令牌 Cookie，但没有 `Authorization: Bearer` 头
- **THEN** 网关将其视为未认证（在受保护路径上返回 401 与 `2001`）

### Requirement: 会话端点仍受网关限流约束

登录与换发端点 SHALL 受网关级 IP 限流约束，且 MUST NOT 被加入任何限流豁免名单。被限流的请求 MUST 返回 429 与 `2004`，并 MUST NOT 到达下游服务。

#### Scenario: 反复登录尝试触发限流

- **WHEN** 单一来源 IP 在登录端点或换发端点上超出其限流窗口
- **THEN** 网关返回 429 与 `2004`，下游服务始终不会收到该请求
