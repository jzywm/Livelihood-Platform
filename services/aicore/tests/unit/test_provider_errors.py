"""`provider/errors.py` 的注册表与可分辨性用例（控制者自写，P 阶段收尾）。

## 本文件补的是哪两处缺口（都由 P 阶段独立评审指出）

**缺口一：`provider/errors.py` 初版**一条**直测用例都没有。**
三个子类的码值只被 `test_provider_guard.py` / `test_provider_real.py` **间接**断言，
而那些用例断言的是「行为抛了哪一类异常」，不是「这一类的码值是否登记正确」。
后果：控制者把熔断归错码（`4003` 而非平台码表的 `5002`）时，
**全部 1088 条用例照样绿**——评审用变异测试证实了这一点。

**缺口二：同码异常在日志侧不可分辨。**
`str(exc)` 只含平台用户文案（`core/errors.py` 的 `DEFAULT_MESSAGES`），
故 `ProviderChannelFailureError` 与（初版的）`ProviderCircuitOpenError` **完全同串**；
`reason` / `operation` 也不在 `args` 里。打日志的代码无法分辨发生了什么。

## 本文件的两条判据取向

1. **码值 MUST 与 `core/errors.py` 的注册表一致**——而 `core/errors.py` 的注册表又
   必须落在 `services/_common/openapi.yaml` 的 `ErrorCode` 枚举内（那条由
   `tests/unit/test_errors.py` 守着）。故本文件只需与 `core` 对齐，
   链路即闭合到平台码表；**从文档现读**的那一层在 `test_errors.py` 里。
2. **可分辨性 MUST 由结构化字段承担**（`reason` / `operation` / 异常类型），
   MUST NOT 依赖 `str(exc)`。这条把「同码不同因」变成可断言的事实。
"""

from __future__ import annotations

import pytest

from aicore.core.errors import (
    HTTP_STATUS_BY_ERROR_CODE,
    ChannelFailureError,
    DependencyTimeoutError,
)
from aicore.provider.errors import (
    ProviderChannelFailureError,
    ProviderCircuitOpenError,
    ProviderError,
    ProviderTimeoutError,
)

#: 三类异常 × 期望的 (码值, HTTP 状态, 应继承的 core 基类)。
#:
#: 熔断归 `5002` 的依据（控制者曾在此犯错，故把出处钉在判据旁边）：
#: `services/_common/openapi.yaml:208` 逐字 `- 5002 # 依赖超时 / 熔断`；
#: `:134` 逐字「依赖超时 / 熔断（code=5002）」；
#: `:135` 把「没等到响应」（含熔断）与「等到了失败」（4001~4004）划成两档。
EXPECTED = (
    (ProviderChannelFailureError, 4003, 502, ChannelFailureError),
    (ProviderTimeoutError, 5002, 504, DependencyTimeoutError),
    (ProviderCircuitOpenError, 5002, 504, DependencyTimeoutError),
)

_IDS = [cls.__name__ for cls, *_ in EXPECTED]


@pytest.mark.parametrize(("exc_cls", "code", "http_status", "core_base"), EXPECTED, ids=_IDS)
def test_code_and_http_status_match_the_core_registry(
    exc_cls: type, code: int, http_status: int, core_base: type
) -> None:
    """码值与 HTTP 状态 MUST 与 `core/errors.py` 的注册表一致。

    这条是**直接**断言（不再经由"行为抛了哪一类"间接推出），
    故它能在码值写错时立刻变红——这正是初版缺的那一层。
    """
    exc = exc_cls("some-provider", "some-op", "some-reason")

    assert exc.code == code, f"{exc_cls.__name__}.code 应为 {code}，实际 {exc.code}"
    assert HTTP_STATUS_BY_ERROR_CODE[exc.code] == http_status, (
        f"{exc_cls.__name__} 的码 {exc.code} 在 core 注册表里应映射 HTTP {http_status}"
    )


@pytest.mark.parametrize(("exc_cls", "code", "http_status", "core_base"), EXPECTED, ids=_IDS)
def test_subclass_is_catchable_as_its_core_business_error(
    exc_cls: type, code: int, http_status: int, core_base: type
) -> None:
    """每个子类 MUST 可被 `core/errors.py` 的对应业务异常捕获。

    意义：`register_exception_handlers` 挂在 `AiCoreError` 上做信封映射，
    故「被 core 基类捕获」= 「会被映射成平台信封」。若某个 provider 异常
    **不**继承任何 `AiCoreError` 子类，它会掉进未预期异常分支变成 `5000`，
    而任务 4.11 要求 4003/5002 必须能被区分返回。
    """
    exc = exc_cls("p", "op", "reason")
    assert isinstance(exc, core_base)
    assert isinstance(exc, ProviderError), "通道异常必须都能被 except ProviderError 兜住"


@pytest.mark.parametrize(("exc_cls", "code", "http_status", "core_base"), EXPECTED, ids=_IDS)
def test_message_comes_from_the_platform_default_table(
    exc_cls: type, code: int, http_status: int, core_base: type
) -> None:
    """用户文案 MUST 取自平台默认表，不自行编造。

    依据：`core/errors.py` 的 `AiCoreError.__init__` 在 `message is None` 时取
    `DEFAULT_MESSAGES[code]`。本层刻意不传 `message`，保证用户文案与平台口径逐字一致
    （`services/aicore/docs/openapi.yaml:101` 的 4003 文案是「OCR 通道失败，已转人工核验」，
    属**路由层**的覆盖，不是本层的职责）。
    """
    from aicore.core.errors import DEFAULT_MESSAGES

    assert str(exc_cls("p", "op", "r")) == DEFAULT_MESSAGES[code]


def test_reason_and_operation_distinguish_same_code_failures() -> None:
    """**同码不同因 MUST 可用结构化字段分辨**（本文件存在的第二个理由）。

    这是评审指出的缺口：初版 `str(ProviderCircuitOpenError(...))` 与
    `str(ProviderChannelFailureError(...))` 完全同串，故「熔断」与「通道失败」
    在日志里分不出来——而 Task 4.11 的验收项正是「两者不混用且**分别计数**」。

    判据三件套：
    1. **类型**不同（`type(exc)` 是首要判据，`except` 分支据此分流）；
    2. `reason` 不同且可读；
    3. `operation` 指出发生在哪个方法上。

    MUST NOT 用 `str(exc)` 做分流——它在同码时必然同串，这是平台文案表决定的，
    不是本层的缺陷；本层的责任是把结构化字段补齐。
    """
    circuit = ProviderCircuitOpenError("deepseek", "complete", "circuit-open")
    timeout = ProviderTimeoutError("deepseek", "complete", "timeout")
    channel = ProviderChannelFailureError("deepseek", "complete", "http-500")

    # 1. 类型可分
    assert type(circuit) is not type(timeout)
    assert type(circuit) is not type(channel)
    # 2. reason 可分
    assert circuit.reason == "circuit-open"
    assert timeout.reason == "timeout"
    assert channel.reason == "http-500"
    assert len({circuit.reason, timeout.reason, channel.reason}) == 3
    # 3. operation 与 provider 可读
    assert (circuit.provider, circuit.operation) == ("deepseek", "complete")

    # 熔断与超时**同码**是刻意的（平台把它们划在同一档，见模块 docstring 的出处），
    # 故这里显式断言同码，防后人"顺手"改回 4003 而没人发现。
    assert circuit.code == timeout.code == 5002
    assert channel.code == 4003


def test_same_code_failures_share_the_platform_user_message() -> None:
    """同码两个子类的 `str()` **必然**相同——这是事实，不是缺陷，故显式钉住。

    为什么要为一件"看起来是问题"的事写断言：评审把它当成缺口报上来是对的
    （可分辨性确实缺失），但**修法不是改文案**（文案归平台表），
    而是补结构化字段。把「str 相同」写成断言，可以防止后人为了"让日志能区分"
    去改用户文案，从而与平台口径分叉。
    """
    a = str(ProviderCircuitOpenError("p", "op", "circuit-open"))
    b = str(ProviderTimeoutError("p", "op", "timeout"))
    assert a == b == "依赖超时或熔断"
