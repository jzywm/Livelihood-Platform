"""通道层异常（Task 4.1 / 4.3）。

三个子类各对应一档，语义**逐字承接** `services/_common/openapi.yaml:132-146` 的区分：

> 与第三方业务失败（4001/4002/4003/4004）严格区分：前者是「**没等到响应**」，
> 后者是「**等到了失败**」，两者计数与告警口径不同，运维据此区分「通道故障」与「依赖劣化」。

| 异常 | 业务码 | 语义 | 谁产生 |
|---|---|---|---|
| `ProviderChannelFailureError` | `4003` | 等到了失败 | 真实通道、合规门 |
| `ProviderTimeoutError` | `5002` | 没等到响应（超时） | 超时护栏 |
| `ProviderCircuitOpenError` | `5002` | 熔断打开，未发请求 | 熔断器 |

「等到了失败」的具体形态：HTTP 5xx、返回体被判为失败、通道未就绪（缺凭据或合规前置）。

## 熔断归 `5002`：控制者的一处**已修正错误**（如实留在文档里）

本模块初版把熔断归 `4003`，理由写的是「熔断的成因是通道已坏，处置与通道失败一致」。
**这个理由是我的自造口径，与平台码表正面冲突**（违反我自己的自约束 C7：改码值前
MUST 先读权威定义处并核对语义）。第 4 组 P 阶段的独立评审用变异测试抓到，控制者复核原文：

```
services/_common/openapi.yaml:208   - 5002 # 依赖超时 / 熔断
services/_common/openapi.yaml:134          依赖超时 / 熔断（code=5002）。
services/_common/openapi.yaml:135          与第三方业务失败（4001/4002/4003/4004）严格区分：
                                           前者是「没等到响应」，后者是「等到了失败」
services/_common/openapi.yaml:204   - 4003 # 大模型 / 视觉 API 失败
services/aicore/src/aicore/core/errors.py:252   DEPENDENCY_TIMEOUT_CODE: 依赖超时或熔断
services/aicore/src/aicore/core/errors.py:396   依赖超时 / 熔断（5002，HTTP 504）
```

**平台的定义是：熔断属「没等到响应」档，与「通道失败」是两个码。** 我原先的"语义直觉"
之所以错，是因为我只想了「熔断的成因」，没想平台是按**调用方的观测**分档的——
熔断时调用方**根本没等到任何响应**（请求压根没发出去），所以它天然落在
`_common/openapi.yaml:135` 定义的「没等到响应」那一侧。

**`spec.md:72` 与平台码表冲突**（spec 说「通道失败返回 `4003`…依赖超时 `5002`」，
未提熔断；而 `:82` 又说「返回 `5002` 而非 `4003`」）。按事实源优先级
（`_common/openapi.yaml` 的 `ErrorCode` 枚举是平台码表的唯一定义处），取 `5002`。
该冲突已按自约束 C2 登记进 ledger，**spec 未改**（C5：spec 不是权威源，改动需另走流程）。

## 为什么熔断仍要单独一个类（不因为同码就合并）

`ProviderTimeoutError` 与 `ProviderCircuitOpenError` 现在**同码 `5002`**，
但两者仍 MUST 分开，理由是 Task 4.11 的验收项「两者不混用且**分别计数**」：

- 超时 = **发出了请求但没等到响应**（对端慢）；
- 熔断 = **压根没发请求**（本端主动拒绝，避免继续打一个已知坏掉的通道）。

两者的运维处置不同（前者看对端 SLO，后者看本端熔断器状态与冷却时间），
计数也必须能分开。**保证「可分辨」的机制不是码值，而是 `reason` 与 `operation`**
（见下）—— 这正是评审指出的第二个问题：初版 `str(exc)` 与通道失败**完全同串**，
打日志的代码分辨不出熔断与通道失败。

## `reason` 与 `operation` 是日志侧的可分辨性来源

三个子类的 `str()` **只含平台用户文案**（`core/errors.py` 的 `DEFAULT_MESSAGES`），
故 `str()` 同码时必然同串。可分辨性由结构化字段承担：

- `exc.reason`：判别依据（`timeout` / `circuit-open` / `http-500` / `compliance-missing` …）
- `exc.operation`：发生在哪个方法上（`complete` / `analyze` / `recognize`）

调用方 MUST 用这两个字段做日志与计数，MUST NOT 从 `str(exc)` 反推类别。
`tests/unit/test_provider_errors.py` 把这条钉成判据。
"""

from __future__ import annotations

from aicore.core.errors import ChannelFailureError, DependencyTimeoutError

__all__ = [
    "ProviderChannelFailureError",
    "ProviderCircuitOpenError",
    "ProviderError",
    "ProviderTimeoutError",
]


class ProviderError(Exception):
    """通道层错误基类。

    本类存在只为一件事：让调用方用 `except ProviderError` 一次兜住所有通道问题，
    再按子类细分。**MUST NOT 被直接抛出**——它不带业务码，抛出去会落到 `5000`。
    """

    def __init__(self, provider: str, operation: str, reason: str) -> None:
        self.provider = provider
        self.operation = operation
        self.reason = reason
        super().__init__(f"[{provider}.{operation}] {reason}")


class ProviderChannelFailureError(ProviderError, ChannelFailureError):
    """等到了失败（`4003`）。三方失败 / 通道未就绪 / 合规门拒绝。

    `reason` 是**给运维看的判别依据**（如 `http-500`、`compliance-missing`），
    不是用户文案：用户文案由 `core/errors.py` 的 `DEFAULT_MESSAGES[4003]` 决定
    （「大模型 / 视觉 API 失败」），本类只在需要覆盖时传 `message`。

    多重继承的两个父类各司其职：`ProviderError` 提供 `provider`/`operation`/`reason`，
    `ChannelFailureError` 提供业务码 `4003` 与信封映射；本类显式调用前者的
    `__init__`，再调后者的无参 `__init__`（走平台默认文案），歧义不存在。
    """

    def __init__(self, provider: str, operation: str, reason: str) -> None:
        ProviderError.__init__(self, provider, operation, reason)
        # 不传 message：走 DEFAULT_MESSAGES[4003]，保证用户文案与平台口径逐字一致。
        ChannelFailureError.__init__(self)


class ProviderTimeoutError(ProviderError, DependencyTimeoutError):
    """没等到响应（`5002`）——**请求已发出**，对端没在时限内回应。"""

    def __init__(self, provider: str, operation: str, reason: str) -> None:
        ProviderError.__init__(self, provider, operation, reason)
        DependencyTimeoutError.__init__(self)


class ProviderCircuitOpenError(ProviderError, DependencyTimeoutError):
    """熔断打开（`5002`），**未发出任何请求**。

    码值依据见模块 docstring（`_common/openapi.yaml:208`）。与 `ProviderTimeoutError`
    同码但不同类，区别在「请求发没发出去」——由 `reason` 与计数区分。
    """

    def __init__(self, provider: str, operation: str, reason: str) -> None:
        ProviderError.__init__(self, provider, operation, reason)
        DependencyTimeoutError.__init__(self)
