"""通道护栏三件套：超时 / 重试 / 熔断（Task 4.3，三个真实通道共用）。

## 数值口径的唯一来源（MUST NOT 在本文件另选）

四项护栏参数由 `Settings` 承载（Task 4.3 由控制者定档，见 `core/config.py` 的
「通道护栏」一节），本模块只做映射，替换 `guard_config_from()` 之外不写任何数字：

| `Settings` 字段 | 默认 | 权威出处 |
|---|---|---|
| `ai_call_timeout_s` | `5.0` | 《高并发架构演进设计》§4.4 L317 / §7.6 L423「AI 5s」 |
| `provider_max_retries` | `5` | 同文档 L260 / L318「幂等接口 ≤5 次指数退避」 |
| `circuit_error_ratio` | `0.5` | 同文档 L316「错误率 >50% … 熔断」 |
| `circuit_cooldown_s` | `10.0` | 同文档 L316「半开探测间隔 10s」 |

退避基数 `1s`、公比 `2`：L260 逐字「指数退避（1s→2s→4s… 上限 5 次）」。

## 失败分类：与 `provider/errors.py` 的三类逐条对应

本模块是 `core/errors.py` 那两档语义**在通道侧的落点**（`openapi.yaml:132-146`：
「没等到响应」`5002` 与「等到了失败」`4003` 计数与告警口径不同）：

| 底层形态 | 归类 | 码 | 是否重试 |
|---|---|---|---|
| `asyncio.wait_for` 超时 / `httpx.TimeoutException` | `ProviderTimeoutError` | `5002` | 是 |
| `httpx.TransportError`（连接失败、读错误…） | `ProviderChannelFailureError` | `4003` | 是 |
| `httpx.HTTPStatusError` 5xx | `ProviderChannelFailureError` | `4003` | 是 |
| `httpx.HTTPStatusError` 429 | `ProviderChannelFailureError` | `4003` | 是 |
| `httpx.HTTPStatusError` 4xx（非 429） | `ProviderChannelFailureError` | `4003` | **否** |
| `send` 自己抛的 `ProviderError`（如响应解析失败） | 原样上抛 | 原码 | **否** |
| `ValueError` / `TypeError` 等编程错误 | **原样上抛** | — | **否** |

**4xx 不重试**的理由：4xx 是「客户端错误」——请求本身或凭据不对，重发 5 次只是把
同一次失败重复 6 遍，还把一次计费调用放大成六次；`429` 是例外（限流是**临时**状态，
`Retry-After` 语义就是「稍后重试」）。

**编程错误 MUST 原样上抛**（工单 §2.1.3 的硬要求）：把 `ValueError` 吞成
`ProviderChannelFailureError` 会让「payload 拼错了」这类 bug 伪装成「通道故障」，
运维会照着通道方向白查一天，而真正的调用点一行都没改。编程错误同样**不计入熔断窗口**：
熔断的输入只允许是「通道的表现」，不能是「我方的 bug」。

**`send` 抛 `ProviderError` 时记失败但不重试**：通道实现自己已经把底层形态归一
（例如响应体畸形 → `malformed-response`），那属于「等到了失败」；但畸形响应不是
瞬时抖动，重发拿不回不同的结果（工单 §3.3 也只要求显式失败，未要求重试）。
一句话：**重试判据只有上表里写「是」的四类**。

## 熔断窗口口径（工单 §2.1.7，MUST 写进 docstring）

1. **最小样本数 `MIN_SAMPLES = 5`**：窗口内样本不足 5 次时**永不**熔断。
   没有这条，1 次失败的错误率就是 100%，等于「首次抖动即熔断」——把一次瞬时故障
   放大成可用性事故（`产品设计文档.md:1088` 的降级动作是「转人工复核队列」，
   代价远高于多试几次）。
2. **错误率严格大于阈值**（`> config.error_ratio`，不是 `>=`）：对齐 L316 的
   「错误率 >50%」。5 次全失败时 100% > 50% → 熔断；10 次里 5 次失败时 50% 不熔断。
3. **窗口长度 `WINDOW_SIZE = 10`**：平台文档只给了触发条件、没给窗口大小，本实现取
   `MIN_SAMPLES` 的 2 倍，理由是它同时满足两头——下界够小（连续 5 次失败即可触发
   `5/5 = 100% > 50%`），上界够小（否则旧的成功记录会被无限期保留，错误率退化成
   「历史平均」，「连续触发」的语义就没了）。
4. **半开只放行一次探测**：`cooldown_s` 内所有调用在**发请求之前**被拒
   （`ProviderCircuitOpenError`，`4003`：熔断的成因是「通道已经坏了」，与
   `errors.py` 的归属口径一致）；冷却到期后放行**一次**探测，成功 → `CLOSED`
   并清空窗口，失败 → `OPEN` 并**重置冷却计时**。
5. **探测在飞期间的判定**：同一 (provider, operation) 上已有探测在飞时，其余调用继续被拒
   （否则「放行一次探测」会退化成「放行全部」）。若探测**没有**被记账（`send` 抛了
   编程错误，见上表最后一行），半开状态不会被永久锁死：超过一个 `cooldown_s` 后
   视为该探测已放弃，放行新的探测。

## 并发口径

熔断状态是**进程内的纯内存结构**，且在 asyncio 单线程下读写；`before_call` /
`record_*` 之间没有 `await`，故不需要锁。多实例部署时熔断是**每实例各自计**的
（与 `core/config.py` 里「domain 侧熔断保护本服务发出的计费调用」的分工一致）；
跨实例的全局熔断属于网关侧 Resilience4j 的职责，本模块不重复实现。

## 时钟注入

`system_clock()` 用 `time.monotonic()` + `asyncio.sleep`；测试 MUST 注入假时钟
（`tests/conftest.py` 文件头逐字：「测试内 MUST NOT 出现任意 sleep；等待一律走
轮询断言或注入的时钟」）。故 `guarded_call` 的退避**只**经 `clock.sleep`，
MUST NOT 直接调用 `asyncio.sleep`。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from aicore.core.config import Settings
from aicore.provider.errors import (
    ProviderChannelFailureError,
    ProviderCircuitOpenError,
    ProviderError,
    ProviderTimeoutError,
)

__all__ = [
    "MIN_SAMPLES",
    "WINDOW_SIZE",
    "BreakerState",
    "CircuitBreaker",
    "GuardConfig",
    "StepClock",
    "guard_config_from",
    "guarded_call",
    "system_clock",
]

#: 判定熔断所需的**最小样本数**（见模块 docstring §3 的第 1 条）。
MIN_SAMPLES = 5

#: 滑动窗口保留的最近调用次数（见模块 docstring §3 的第 3 条）。
WINDOW_SIZE = 10

#: 熔断状态（工单 §2 里逐字写出的那个 Literal）。
type BreakerState = Literal["CLOSED", "OPEN", "HALF_OPEN"]

#: 429：限流是临时状态，重试有意义（HTTP 语义即「稍后重试」）。
TOO_MANY_REQUESTS = 429

#: 服务端错误的起点：`>= 500` 一律可重试（对端故障，重发有机会落到健康实例）。
SERVER_ERROR_MIN = 500


@dataclass(frozen=True, slots=True)
class GuardConfig:
    """护栏参数（全通道共用）。取值只从 `Settings` 来，见 `guard_config_from()`。"""

    timeout_s: float
    max_retries: int  # 不含首次
    error_ratio: float  # 熔断阈值
    cooldown_s: float  # 半开探测间隔
    backoff_base_s: float = 1.0
    backoff_factor: float = 2.0


class StepClock(Protocol):
    """可注入时钟。**测试里 MUST NOT 真等**，故时钟与睡眠都必须可替换。

    两个成员分工不同、MUST NOT 互相替代：

    - `monotonic()` 只服务熔断的冷却计时。**必须单调**：墙钟（`time.time()`）会因
      NTP 校时回拨，回拨会让「刚打开的熔断」看起来已经冷却完毕而提前半开；
    - `sleep()` 是重试退避的**唯一**睡眠入口。`guarded_call` 里 MUST NOT 出现
      `asyncio.sleep`，否则测试就只能真等 1s + 2s + 4s + 8s + 16s。
    """

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class _SystemClock:
    """`system_clock()` 的实现（生产用；测试 MUST 注入假时钟）。"""

    __slots__ = ()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def system_clock() -> StepClock:
    """生产时钟：`time.monotonic()` + `asyncio.sleep`（依据见 `StepClock`）。"""
    return _SystemClock()


def guard_config_from(settings: Settings) -> GuardConfig:
    """把 `Settings` 的四项护栏参数映射成 `GuardConfig`。

    三个通道共用这一份映射（而不是各自拼一遍）：口径只有一处，`Settings` 字段改名
    或单位变化时只改这里。**退避基数与公比不在 `Settings` 里**——平台文档给的是
    确定的序列（1s→2s→4s…），它不是部署决策，故留在 `GuardConfig` 的默认值上。
    """
    return GuardConfig(
        timeout_s=settings.ai_call_timeout_s,
        max_retries=settings.provider_max_retries,
        error_ratio=settings.circuit_error_ratio,
        cooldown_s=settings.circuit_cooldown_s,
    )


@dataclass(slots=True)
class _Window:
    """单个 `(provider, operation)` 维度的熔断状态。

    `samples` 只存「成功 / 失败」两个布尔值：熔断判据只需要错误率，
    存耗时或异常对象会让窗口随时钟漂移（并且异常对象会持有请求，进而持有请求头里的密钥）。
    """

    samples: deque[bool] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    #: 熔断打开的时刻（`None` = 未打开）。冷却计时以它为基准。
    opened_at: float | None = None
    #: 半开状态下游离在外的探测是否已被放行（见模块 docstring §3 的第 4/5 条）。
    probing: bool = False
    probe_started_at: float = 0.0


@dataclass(frozen=True, slots=True)
class _Failure:
    """一次尝试的失败归类：决定重试耗尽后抛哪一类（`5002` vs `4003`）与 `reason`。

    `cause` 是最后一次的底层异常，仅用于 `raise ... from cause` 的因果链——
    排障要能看到「是哪个 URL 的 503」「超时发生在哪一次尝试」；`reason` 才是判别依据。
    因果链 MUST NOT 携带密钥：`httpx` 的异常消息只有方法与 URL，而密钥只进请求头
    （见 `_http.py` 的约束 2）。
    """

    kind: Literal["timeout", "channel"]
    reason: str
    cause: BaseException | None = None

    def to_error(self, provider: str, operation: str) -> ProviderError:
        """渲染成 `errors.py` 里的对应异常（`reason` 是给运维看的判别依据）。"""
        if self.kind == "timeout":
            return ProviderTimeoutError(provider, operation, reason=self.reason)
        return ProviderChannelFailureError(provider, operation, reason=self.reason)


class CircuitBreaker:
    """按 (provider, operation) 维度计的滑动窗口熔断器。

    维度是 `(provider, operation)` 而不是只有 provider：`cloud_ocr` 的 `recognize`
    坏掉不该连带掐掉它的其他操作（反之亦然）。这也是 Task 4.11「降级状态可观测」
    的最小可观测单位（`state_of` 就是那份可查询的状态）。
    """

    def __init__(self, config: GuardConfig, *, clock: StepClock | None = None) -> None:
        self._config = config
        self._clock: StepClock = system_clock() if clock is None else clock
        self._windows: dict[tuple[str, str], _Window] = {}

    def state_of(self, provider: str, operation: str) -> BreakerState:
        """当前状态：`CLOSED` / `OPEN` / `HALF_OPEN`。

        `HALF_OPEN` 是**推导出来**的（打开已满一个 `cooldown_s`），不是另存的状态位：
        这样「冷却到期」只有一条判定路径，不存在「状态位说 CLOSED、时间说已到期」的分叉。
        """
        window = self._windows.get((provider, operation))
        if window is None or window.opened_at is None:
            return "CLOSED"
        if self._clock.monotonic() - window.opened_at >= self._config.cooldown_s:
            return "HALF_OPEN"
        return "OPEN"

    def before_call(self, provider: str, operation: str) -> None:
        """在**发请求之前**过熔断门：打开态直接抛 `ProviderCircuitOpenError`。

        本方法由 `guarded_call` 在调用 `send` 之前调用，故「熔断时一次请求都没发出」
        是可断言的（用例挂一个计数在 `send` 上）。
        """
        state = self.state_of(provider, operation)
        if state == "CLOSED":
            return
        window = self._windows[(provider, operation)]
        if state == "OPEN":
            raise ProviderCircuitOpenError(provider, operation, reason="circuit-open")
        now = self._clock.monotonic()
        if window.probing and now - window.probe_started_at < self._config.cooldown_s:
            # 已有探测在飞：不放行第二次（否则「放行一次探测」等于放行全部）。
            raise ProviderCircuitOpenError(provider, operation, reason="circuit-probe-in-flight")
        # 放行一次探测；若上一次探测既没成功也没失败（调用方代码抛了编程错误，
        # 不该记进熔断窗口），超过一个冷却周期后视为已放弃，这里重新放行。
        window.probing = True
        window.probe_started_at = now

    def record_success(self, provider: str, operation: str) -> None:
        """记一次成功。半开探测成功 → 回 `CLOSED` 并清窗口。"""
        window = self._window(provider, operation)
        if window.probing:
            window.probing = False
            window.opened_at = None
            window.samples.clear()
            return
        window.samples.append(True)

    def record_failure(self, provider: str, operation: str) -> None:
        """记一次失败。样本足够且错误率 **严格大于** 阈值 → 打开熔断。

        打开时清空窗口：下次半开探测成功即「干净地」回到 `CLOSED`——残留的失败样本
        会让刚恢复的通道被一次抖动立刻重新熔断，等于把「半开」做成「几乎没有恢复」。
        """
        window = self._window(provider, operation)
        if window.probing:
            # 探测失败：回 OPEN 并**重置冷却计时**（下一次半开要再等一个 cooldown_s）。
            window.probing = False
            window.opened_at = self._clock.monotonic()
            window.samples.clear()
            return
        window.samples.append(False)
        if len(window.samples) < MIN_SAMPLES:
            return
        if self._failure_ratio(window) > self._config.error_ratio:
            window.opened_at = self._clock.monotonic()
            window.samples.clear()

    def _failure_ratio(self, window: _Window) -> float:
        """窗口内的失败占比（调用方已保证窗口非空）。"""
        failures = sum(1 for ok in window.samples if not ok)
        return failures / len(window.samples)

    def _window(self, provider: str, operation: str) -> _Window:
        """取（必要时创建）该维度窗口。"""
        return self._windows.setdefault((provider, operation), _Window())


async def guarded_call(
    *,
    provider: str,
    operation: str,
    config: GuardConfig,
    breaker: CircuitBreaker,
    send: Callable[[], Awaitable[Any]],
    clock: StepClock | None = None,
) -> Any:
    """超时 + 指数退避重试 + 熔断；把底层异常归一为 `provider/errors.py` 的三类。

    执行顺序（顺序本身是契约，见模块 docstring 的分类表）：

    1. `breaker.before_call()`——**熔断门在最前**，打开时 `send` 一次都不会被调用；
    2. 每次尝试 `await asyncio.wait_for(send(), timeout=config.timeout_s)`；
    3. 失败分类（可重试的四类 → 记失败 + 退避重试；4xx → 立即失败；编程错误 → 原样上抛）；
    4. 退避睡眠走注入时钟：第 n 次失败后睡 `backoff_base_s * backoff_factor ** (n - 1)`，
       n 从 1 起（`max_retries = 5` → 睡 `[1, 2, 4, 8, 16]`，尝试共 6 次）；
    5. 重试耗尽 → 抛**最后一次**的异常类型（超时 → `5002`；其余 → `4003`），
       并把最后一次的底层异常挂进因果链（`raise ... from`）：排障要看得到是哪个 URL
       的 503 或哪一次超时，而**判别依据仍然只有 `reason`**。

    **本调用内已开始的尝试不因熔断中途打开而中断**（有意边界）：重试次数受
    `max_retries` 硬约束，中途打断会让「最后一次的异常类型」不可预测；熔断的效力
    体现在**后续调用**的 `before_call` 上，而那正是可断言的部分（用例 1）。

    **调用侧超时与平台护栏的关系**：本函数只认 `config.timeout_s`；通道实现把
    「调用侧声明的 `timeout_s`」与 `Settings.ai_call_timeout_s` 取较小值后传进来
    （见 `deepseek.py` 的 `_effective_timeout_s`）——两者都是上限，都要成立。
    """
    step_clock: StepClock = system_clock() if clock is None else clock
    breaker.before_call(provider, operation)

    attempts = config.max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            value = await asyncio.wait_for(send(), timeout=config.timeout_s)
        except TimeoutError as exc:
            # `asyncio.wait_for` 超时抛的是内建 TimeoutError
            # （3.11+ 起与 asyncio.TimeoutError 是同一个对象）。
            failure = _Failure(kind="timeout", reason="timeout", cause=exc)
        except httpx.TimeoutException as exc:
            failure = _Failure(kind="timeout", reason="timeout", cause=exc)
        except ProviderError:
            # 通道实现自己归一过的失败（如 malformed-response）：记失败但**不重试**。
            breaker.record_failure(provider, operation)
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == TOO_MANY_REQUESTS or status >= SERVER_ERROR_MIN:
                failure = _Failure(kind="channel", reason=f"http-{status}", cause=exc)
            else:
                # 4xx（非 429）：客户端错误重试无意义 → 立即失败，MUST NOT 重试。
                breaker.record_failure(provider, operation)
                raise ProviderChannelFailureError(
                    provider, operation, reason=f"http-{status}"
                ) from exc
        except httpx.TransportError as exc:
            failure = _Failure(kind="channel", reason="transport-error", cause=exc)
        else:
            breaker.record_success(provider, operation)
            return value

        breaker.record_failure(provider, operation)
        if attempt == attempts:
            # 因果链挂上最后一次的底层异常（排障要看得到 URL 与状态），但**判别依据**
            # 仍是 reason：运维按 reason 分流，按 exception 链定位。
            raise failure.to_error(provider, operation) from failure.cause
        # 退避走注入时钟：第 n 次失败后睡 base * factor ** (n - 1)。
        await step_clock.sleep(config.backoff_base_s * config.backoff_factor ** (attempt - 1))

    # 结构上不可达（attempts >= 1 保证循环体内必 return 或 raise）。显式抛出只为满足
    # mypy strict 的「所有路径都有返回」，而不是让函数静默返回 None。
    raise AssertionError("unreachable: guarded_call 的循环必然 return 或 raise")
