"""`provider/guard.py`（超时 / 重试 / 熔断）的护栏用例（Task 4.3）。

## 两条测试纪律（工单 §2.2 与 `tests/conftest.py` 文件头）

1. **MUST NOT 真等**：`tests/conftest.py` 逐字「测试内 MUST NOT 出现任意 sleep；等待一律走
   轮询断言或注入的时钟」。本文件用 `FakeClock` 同时替换「读时间」与「睡眠」，
   并由 autouse 夹具 `_assert_no_real_sleep` 对**每条用例**断言墙钟耗时 < 0.5s
   ——整条重试链真睡一次就要 31s（1+2+4+8+16），真等根本跑不完，这断言就是「没真睡」的证据。
   唯一的例外是 `test_wait_for_timeout_is_enforced_by_the_real_loop`：它验证的正是
   `asyncio.wait_for` 这条**真实事件循环**路径，故用 0.01s 超时（而不是 5s）跑。
2. **每条断言都要有判别力**：熔断门的用例挂一个 `send` 计数器——「熔断打开后一次请求都
   没发出」是 Task 4.3「不发出真实计费调用」的可断言形态；退避用例断言**逐项相等**的
   睡眠序列（`[1.0, 2.0, 4.0, 8.0, 16.0]`），而不是「大概退避了」。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from aicore.core.config import Settings
from aicore.provider.errors import (
    ProviderChannelFailureError,
    ProviderCircuitOpenError,
    ProviderTimeoutError,
)
from aicore.provider.guard import (
    MIN_SAMPLES,
    CircuitBreaker,
    GuardConfig,
    guard_config_from,
    guarded_call,
    system_clock,
)

PROVIDER = "fake_provider"
OPERATION = "fake_operation"

#: 退避序列：base 1s、公比 2、上限 5 次重试（《高并发架构演进设计》L260 逐字
#: 「指数退避（1s→2s→4s… 上限 5 次）」）。写死成常量而不是现算：现算就等于
#: 把被测实现抄一遍，公式写错时用例跟着一起错。
EXPECTED_BACKOFF = [1.0, 2.0, 4.0, 8.0, 16.0]


class FakeClock:
    """可注入的假时钟：`monotonic()` 返回可控值，`sleep()` 只累加虚拟时间。

    实现 `guard.StepClock` 的两个成员（结构子类型，不需要继承）：
    - `sleep()` 把秒数记进 `sleeps` 并推进虚拟时间——断言因此可以「逐项相等」；
    - `advance()` 供用例手动推进时间（模拟冷却期过去），**不经过睡眠**。
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _assert_no_real_sleep() -> Iterator[None]:
    """每条用例的墙钟耗时 MUST < 0.5s —— 「没真睡」的可核证据（工单 §2.2）。"""
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, (
        f"用例墙钟耗时 {elapsed:.3f}s 超过 0.5s：本文件 MUST NOT 真等"
        f"（重试退避与冷却都必须走注入的 FakeClock）"
    )


def _config(**overrides: Any) -> GuardConfig:
    """护栏参数（默认值与 `Settings` 的定档初值一致，见 `core/config.py`）。"""
    base: dict[str, Any] = {
        "timeout_s": 5.0,
        "max_retries": 5,
        "error_ratio": 0.5,
        "cooldown_s": 10.0,
    }
    base.update(overrides)
    return GuardConfig(**base)


def _status_error(status: int) -> httpx.HTTPStatusError:
    """构造一个带响应状态的 `HTTPStatusError`（真请求不会发出：这里只造异常对象）。"""
    request = httpx.Request("POST", "https://fake.invalid/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


class _Counter:
    """`send` 调用计数器：熔断用例的可断言点（「一次请求都没发出」）。"""

    def __init__(self, failure: Exception | None = None, value: Any = None) -> None:
        self.calls = 0
        self._failure = failure
        self._value = value

    async def __call__(self) -> Any:
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return self._value


async def _call(
    *,
    config: GuardConfig,
    breaker: CircuitBreaker,
    clock: FakeClock,
    send: Any,
    provider: str = PROVIDER,
    operation: str = OPERATION,
) -> Any:
    """把 `guarded_call` 的关键字参数收敛成一处（用例只需给出变动的部分）。"""
    return await guarded_call(
        provider=provider,
        operation=operation,
        config=config,
        breaker=breaker,
        send=send,
        clock=clock,
    )


async def _open_the_circuit(
    *,
    config: GuardConfig,
    breaker: CircuitBreaker,
    clock: FakeClock,
    failure: Exception | None = None,
) -> _Counter:
    """连续失败 `MIN_SAMPLES` 次把熔断打开，返回那个计数器（供后续断言「没再调用」）。

    用 `max_retries=0` 的配置：一次调用 = 一次尝试 = 一条失败样本，于是
    「连续失败 N 次」与「N 次调用」一一对应，用例的算术才看得懂。
    """
    send = _Counter(failure if failure is not None else httpx.ConnectError("boom"))
    # 熔断参数仍取传入的 config（阈值与冷却来自用例），只把重试压成 0。
    zero_retry = _config(
        max_retries=0, cooldown_s=config.cooldown_s, error_ratio=config.error_ratio
    )
    for _ in range(MIN_SAMPLES):
        with pytest.raises(ProviderChannelFailureError):
            await _call(config=zero_retry, breaker=breaker, clock=clock, send=send)
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"
    assert send.calls == MIN_SAMPLES
    return send


# ---------------------------------------------------------------------------
# 1. 熔断门在 send 之前
# ---------------------------------------------------------------------------


async def test_breaker_gate_runs_before_send() -> None:
    """用例 1：熔断打开后，第 6 次的 `send` 计数**不增加**（一次请求都没发出）。

    这是「不发出真实计费调用」在护栏层的可断言形态：熔断的意义就是**别再打对端**。
    """
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    send = await _open_the_circuit(config=config, breaker=breaker, clock=clock)
    calls_before = send.calls

    with pytest.raises(ProviderCircuitOpenError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert send.calls == calls_before, "熔断打开后 MUST NOT 再调用 send"
    assert excinfo.value.reason == "circuit-open"
    # 熔断归 5002：依据是 services/_common/openapi.yaml:208 的码表
    # `- 5002 # 依赖超时 / 熔断`，以及 :135 把「没等到响应」（含熔断）与
    # 「等到了失败」（4001~4004）划成两档。控制者初版曾归 4003（自造口径），
    # 由 P 阶段独立评审用变异测试抓到并修正——详见 provider/errors.py 的模块 docstring。
    assert excinfo.value.code == 5002, "熔断归平台码表的 5002（依赖超时 / 熔断），不是 4003"
    assert excinfo.value.provider == PROVIDER
    assert excinfo.value.operation == OPERATION


async def test_breaker_window_is_per_provider_and_operation() -> None:
    """熔断维度是 `(provider, operation)`：一个操作坏掉不该掐掉另一个。"""
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    await _open_the_circuit(config=config, breaker=breaker, clock=clock)

    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"
    assert breaker.state_of(PROVIDER, "another_operation") == "CLOSED"
    assert breaker.state_of("another_provider", OPERATION) == "CLOSED"

    send = _Counter(value="ok")
    assert (
        await _call(
            config=config,
            breaker=breaker,
            clock=clock,
            send=send,
            operation="another_operation",
        )
        == "ok"
    )
    assert send.calls == 1


# ---------------------------------------------------------------------------
# 2. 退避序列
# ---------------------------------------------------------------------------


async def test_backoff_sequence_is_exact() -> None:
    """用例 2：第 n 次失败后睡 `base * factor ** (n - 1)`，逐项相等。

    `max_retries=5` → 尝试 6 次、睡 5 次：`[1.0, 2.0, 4.0, 8.0, 16.0]`
    （断言「大概退避了」等于没测公比与上限）。
    """
    clock = FakeClock()
    config = _config()
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(httpx.ConnectError("boom"))

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert clock.sleeps == EXPECTED_BACKOFF
    assert send.calls == 6, "首次 + 5 次重试"
    assert excinfo.value.reason == "transport-error"
    assert excinfo.value.code == 4003


async def test_backoff_is_skipped_after_the_last_attempt() -> None:
    """重试耗尽后 MUST NOT 再多睡一次（否则最后一次失败后还要白等 16s 才抛）。"""
    clock = FakeClock()
    config = _config(max_retries=1)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(httpx.ConnectError("boom"))

    with pytest.raises(ProviderChannelFailureError):
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert clock.sleeps == [1.0]
    assert send.calls == 2


# ---------------------------------------------------------------------------
# 3~6. 失败分类与重试判据
# ---------------------------------------------------------------------------


async def test_timeout_raises_5002() -> None:
    """用例 3：超时 → `ProviderTimeoutError`（`code == 5002`，「没等到响应」）。"""
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(httpx.ReadTimeout("no response"))

    with pytest.raises(ProviderTimeoutError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert excinfo.value.code == 5002
    assert excinfo.value.reason == "timeout"


async def test_timeout_is_retried_then_exhausted_as_5002() -> None:
    """超时可重试，耗尽后抛的仍是 `5002`（最后一次失败的类别决定异常类型）。"""
    clock = FakeClock()
    config = _config(max_retries=2)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(httpx.ReadTimeout("no response"))

    with pytest.raises(ProviderTimeoutError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert clock.sleeps == [1.0, 2.0]
    assert send.calls == 3
    assert excinfo.value.code == 5002


async def test_wait_for_timeout_is_enforced_by_the_real_loop() -> None:
    """真超时路径：`asyncio.wait_for` 必须真掐断（0.01s 超时，故不违反「不真等」）。

    上游若是「等不到响应的通道」，`send` 会一直挂着；本用例用一个睡 30s 的 `send`
    证明超时护栏真的会把它掐掉，而不是靠通道自己抛 `TimeoutException`。
    """
    clock = FakeClock()
    config = _config(timeout_s=0.01, max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)

    async def never_returns() -> Any:
        await asyncio.sleep(30)
        return "unreachable"

    started = time.monotonic()
    with pytest.raises(ProviderTimeoutError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=never_returns)

    assert excinfo.value.code == 5002
    assert time.monotonic() - started < 0.5, "0.01s 的超时不该真的等 30s"


async def test_5xx_is_retried_then_exhausted_as_4003() -> None:
    """用例 4：5xx 会重试，耗尽后 `ProviderChannelFailureError`（`code == 4003`）。"""
    clock = FakeClock()
    config = _config(max_retries=2)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(_status_error(503))

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert clock.sleeps == [1.0, 2.0]
    assert send.calls == 3
    assert excinfo.value.code == 4003
    assert excinfo.value.reason == "http-503"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_error_is_not_retried(status: int) -> None:
    """用例 5：4xx（非 429）**不重试** —— `send` 只被调用 1 次。

    重试客户端错误只是把同一次失败重复 6 遍，还把一次计费调用放大成六次。
    """
    clock = FakeClock()
    config = _config(max_retries=5)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(_status_error(status))

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert send.calls == 1
    assert clock.sleeps == []
    assert excinfo.value.reason == f"http-{status}"
    assert excinfo.value.code == 4003


async def test_429_is_retried() -> None:
    """用例 6：429（限流）**会重试** —— 限流是临时状态，HTTP 语义就是「稍后重试」。"""
    clock = FakeClock()
    config = _config(max_retries=2)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(_status_error(429))

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert send.calls == 3
    assert clock.sleeps == [1.0, 2.0]
    assert excinfo.value.reason == "http-429"


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_server_error_statuses_are_retryable(status: int) -> None:
    """5xx 全档可重试（对端故障，重发有机会落到健康实例）。"""
    clock = FakeClock()
    config = _config(max_retries=1)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(_status_error(status))

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert send.calls == 2
    assert excinfo.value.reason == f"http-{status}"


async def test_success_after_a_retryable_failure_returns_the_value() -> None:
    """一失败一成功：退避后拿到结果，且熔断窗口里记的是「成功」。"""
    clock = FakeClock()
    config = _config(max_retries=2)
    breaker = CircuitBreaker(config, clock=clock)
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("boom")
        return "ok"

    assert await _call(config=config, breaker=breaker, clock=clock, send=flaky) == "ok"
    assert clock.sleeps == [1.0]
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED"


# ---------------------------------------------------------------------------
# 7. 编程错误 MUST NOT 被吞
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("error_type", [ValueError, TypeError, KeyError])
async def test_programming_error_is_raised_as_is(error_type: type[Exception]) -> None:
    """用例 7：`ValueError` / `TypeError` 之类**原样上抛**，不被转成通道失败、也不重试。

    吞掉它会让「调用点拼错了参数」伪装成「通道故障」：运维照着通道方向白查一天，
    而真正的 bug 一行都没改。故这里同时断言三件事：异常类型不变、`send` 只调 1 次、
    熔断窗口**不记**这次失败（bug 不是通道的表现，不该把熔断打开）。
    """
    clock = FakeClock()
    config = _config(max_retries=5)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(error_type("调用点写错了"))

    with pytest.raises(error_type) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert not isinstance(excinfo.value, (ProviderChannelFailureError, ProviderTimeoutError))
    assert send.calls == 1, "编程错误不重试"
    assert clock.sleeps == []
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED", "编程错误不进熔断窗口"


async def test_provider_error_from_send_is_recorded_but_not_retried() -> None:
    """`send` 自带的 `ProviderError`（如响应畸形）：记失败、**不重试**。

    它已经是「等到了失败」，重发拿不回不同的结果（重试判据只有超时 / 传输错误 / 5xx / 429）。
    但**要记进熔断窗口**：连续 5 次畸形响应说明通道契约已经坏了，熔断该开。
    """
    clock = FakeClock()
    config = _config(max_retries=5)
    breaker = CircuitBreaker(config, clock=clock)
    malformed = ProviderChannelFailureError(PROVIDER, OPERATION, reason="malformed-response")
    send = _Counter(malformed)

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert excinfo.value is malformed
    assert send.calls == 1
    assert clock.sleeps == []

    zero_retry = _config(max_retries=0)
    for _ in range(MIN_SAMPLES - 1):
        with pytest.raises(ProviderChannelFailureError):
            await _call(config=zero_retry, breaker=breaker, clock=clock, send=send)
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"


# ---------------------------------------------------------------------------
# 8. 最小样本数
# ---------------------------------------------------------------------------


async def test_single_failure_keeps_the_circuit_closed() -> None:
    """用例 8：只有 1 次失败时 `state_of(...) == "CLOSED"`（错误率 100% 但不熔断）。

    没有最小样本数，「首次抖动即熔断」会把一次瞬时故障放大成可用性事故
    （熔断的处置是转人工复核，代价远高于多试几次）。
    """
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    send = _Counter(httpx.ConnectError("boom"))

    with pytest.raises(ProviderChannelFailureError):
        await _call(config=config, breaker=breaker, clock=clock, send=send)

    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED"


async def test_threshold_is_strictly_greater_than_the_error_ratio() -> None:
    """错误率**严格大于**阈值才熔断（对齐 L316 的「>50%」）。

    构造一个「10 个样本里恰好 5 次失败 = 50%」且**任何前缀都没超过 50%** 的序列
    （`S,S,S,S,F,F,S,F,F,F`：前缀错误率依次为 0/0/0/0/20%/33%/29%/38%/44%/50%），
    于是第 10 个样本落地时状态 MUST 仍是 `CLOSED`——判据是 `>` 而不是 `>=`，
    只有「恰好等于阈值」的样本能测出这个差别。
    随后再失败一次（第 11 个样本挤掉最早的那个成功）→ 60% > 50% → `OPEN`。
    """
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    failing = _Counter(httpx.ConnectError("boom"))
    succeeding = _Counter(value="ok")

    for succeeded in (True, True, True, True, False, False, True, False, False, False):
        send = succeeding if succeeded else failing
        if succeeded:
            await _call(config=config, breaker=breaker, clock=clock, send=send)
        else:
            with pytest.raises(ProviderChannelFailureError):
                await _call(config=config, breaker=breaker, clock=clock, send=send)
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED", (
        "5/10 = 50% 恰好等于阈值，MUST NOT 熔断（判据是严格大于）"
    )

    with pytest.raises(ProviderChannelFailureError):
        await _call(config=config, breaker=breaker, clock=clock, send=failing)
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"


# ---------------------------------------------------------------------------
# 9~10. 半开探测
# ---------------------------------------------------------------------------


async def test_half_open_probe_success_closes_the_circuit() -> None:
    """用例 9：冷却到期 → `HALF_OPEN`；探测成功 → 回 `CLOSED` 并清窗口。"""
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    await _open_the_circuit(config=config, breaker=breaker, clock=clock)

    clock.advance(config.cooldown_s)
    assert breaker.state_of(PROVIDER, OPERATION) == "HALF_OPEN"

    send = _Counter(value="probe-ok")
    assert await _call(config=config, breaker=breaker, clock=clock, send=send) == "probe-ok"
    assert send.calls == 1
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED"

    # 窗口已清：再连续失败 MIN_SAMPLES - 1 次仍不熔断（证明「清窗口」不是口头承诺）。
    failing = _Counter(httpx.ConnectError("boom"))
    for _ in range(MIN_SAMPLES - 1):
        with pytest.raises(ProviderChannelFailureError):
            await _call(config=config, breaker=breaker, clock=clock, send=failing)
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED"


async def test_half_open_probe_failure_reopens_and_restarts_the_cooldown() -> None:
    """用例 10：探测失败 → 回 `OPEN`，且冷却**重新计时**（不是「刚半开过就继续放行」）。"""
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    await _open_the_circuit(config=config, breaker=breaker, clock=clock)

    clock.advance(config.cooldown_s)
    assert breaker.state_of(PROVIDER, OPERATION) == "HALF_OPEN"

    failing = _Counter(httpx.ConnectError("boom"))
    with pytest.raises(ProviderChannelFailureError):
        await _call(config=config, breaker=breaker, clock=clock, send=failing)
    assert failing.calls == 1
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"

    # 冷却重新计时：同一次调用之后（虚拟时间没走）仍拒；走满一个 cooldown 才再半开。
    with pytest.raises(ProviderCircuitOpenError):
        await _call(config=config, breaker=breaker, clock=clock, send=failing)
    assert failing.calls == 1

    clock.advance(config.cooldown_s - 1.0)
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"
    clock.advance(1.0)
    assert breaker.state_of(PROVIDER, OPERATION) == "HALF_OPEN"


def test_only_one_probe_is_let_through() -> None:
    """「放行**一次**探测」：探测在飞期间其余调用继续被拒（否则等于放行全部）。"""
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    for _ in range(MIN_SAMPLES):
        breaker.record_failure(PROVIDER, OPERATION)
    assert breaker.state_of(PROVIDER, OPERATION) == "OPEN"
    clock.advance(config.cooldown_s)

    breaker.before_call(PROVIDER, OPERATION)  # 探测被放行（尚未记账）
    with pytest.raises(ProviderCircuitOpenError) as excinfo:
        breaker.before_call(PROVIDER, OPERATION)
    assert excinfo.value.reason == "circuit-probe-in-flight"


async def test_abandoned_probe_does_not_lock_the_half_open_state() -> None:
    """探测没被记账（`send` 抛了编程错误）时，半开不能被永久锁死。

    编程错误不进熔断窗口（见用例 7），于是那次探测既没成功也没失败。若不给它一条
    退路，`probing` 会永远为真、后续所有调用都被拒 —— 一个调用点的 bug 会变成
    「该通道永久不可用」。故超过一个 `cooldown_s` 后视为该探测已放弃，放行新的探测。
    """
    clock = FakeClock()
    config = _config(max_retries=0)
    breaker = CircuitBreaker(config, clock=clock)
    await _open_the_circuit(config=config, breaker=breaker, clock=clock)
    clock.advance(config.cooldown_s)

    broken = _Counter(ValueError("payload 拼错了"))
    with pytest.raises(ValueError):
        await _call(config=config, breaker=breaker, clock=clock, send=broken)

    with pytest.raises(ProviderCircuitOpenError):
        await _call(config=config, breaker=breaker, clock=clock, send=broken)

    clock.advance(config.cooldown_s)
    send = _Counter(value="probe-ok")
    assert await _call(config=config, breaker=breaker, clock=clock, send=send) == "probe-ok"
    assert breaker.state_of(PROVIDER, OPERATION) == "CLOSED"


# ---------------------------------------------------------------------------
# 11. 时钟与配置映射
# ---------------------------------------------------------------------------


async def test_system_clock_is_monotonic_and_sleeps_through_asyncio() -> None:
    """`system_clock()`（生产实现）的两个成员都要真的能用。

    `sleep(0)` 只是让出一次事件循环、不产生等待——故它不违反「测试内 MUST NOT 真等」，
    却足以覆盖生产时钟的睡眠实现（否则那两行永远没被执行过）。
    """
    clock = system_clock()
    first = clock.monotonic()
    second = clock.monotonic()
    assert second >= first, "熔断冷却计时 MUST 走单调时钟（墙钟回拨会让熔断提前半开）"
    await clock.sleep(0)
    assert clock.monotonic() >= first


def test_guard_config_maps_the_four_settings_fields() -> None:
    """`guard_config_from` 的四项映射逐项相等（数值唯一来源是 `Settings`）。

    同时钉住退避基数与公比：它们不在 `Settings` 里（不是部署决策），
    取值来自 L260 的逐字序列。
    """
    settings = Settings(
        _env_file=None,
        ai_call_timeout_s=1.5,
        provider_max_retries=7,
        circuit_error_ratio=0.25,
        circuit_cooldown_s=3.5,
    )
    config = guard_config_from(settings)
    assert config.timeout_s == 1.5
    assert config.max_retries == 7
    assert config.error_ratio == 0.25
    assert config.cooldown_s == 3.5
    assert config.backoff_base_s == 1.0
    assert config.backoff_factor == 2.0


def test_guard_config_defaults_match_the_locked_platform_values() -> None:
    """`Settings` 的护栏默认值 MUST 是平台定档的那四个数（L317/L260/L316/L316）。

    默认值是「不配也有一份有依据的口径」的落点，改它等于悄悄改平台口径，
    故在这里用文档里的数字正面钉死。
    """
    settings = Settings(_env_file=None)
    assert settings.ai_call_timeout_s == 5.0
    assert settings.provider_max_retries == 5
    assert settings.circuit_error_ratio == 0.5
    assert settings.circuit_cooldown_s == 10.0
