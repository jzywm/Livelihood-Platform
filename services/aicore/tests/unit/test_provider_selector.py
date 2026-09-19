"""Provider 选择器（Task 4.4）的契约用例。

分工：`selector.py` 只做**装配**（按 `Settings.provider` 把三个通道槽位选出来），
启动校验那两条（`env=prod` + `mock` 被拒、真实通道缺密钥被拒）属 Task 2.2 的
`core/config.py`，本文件只在用例 2 里**引用**它们的结果——见
`test_three_environments_select_or_are_rejected_at_settings_construction` 的 docstring。

隔离：所有 `Settings` 都显式传 `_env_file=None`（只让开发者本地 `.env` 失效，
其余取 `conftest.py` 注入的 `test_*` 占位值），口径同 `tests/unit/test_provider_real.py`。
不碰 `get_settings()` 的进程级缓存，故用例之间不通过进程状态互相影响。

零网络：本文件自带的 `socket_guard` 拦住**对外**建连并逐用例断言「一次都没发生」。
环回例外是必须的（Windows 上事件循环自管道会真发一次环回 connect），理由见 `_SocketGuard`。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from pydantic import ValidationError

from aicore.core import config as config_module
from aicore.core.config import Settings
from aicore.provider import selector as selector_module
from aicore.provider.base import TextProvider
from aicore.provider.guard import CircuitBreaker, GuardConfig, guard_config_from
from aicore.provider.selector import Providers, select_providers

#: 选择器源码路径（AST 用例与常量表用例用）。
SELECTOR_PATH = Path(selector_module.__file__).resolve()
#: 通道表所在的包目录（用于 `provider/__init__.py` 的门面用例）。
PROVIDER_DIR = SELECTOR_PATH.parent

#: 真实通道的 `test_*` 占位密钥（MUST NOT 使用真实密钥）。
FAKE_API_KEY = "test_deepseek_placeholder"
#: 选择器错误消息里点名的环境变量（写死字面量而不是从实现拼出来：
#: 拼出来的话「消息里到底写了哪个名字」就跟着实现一起漂移，断言失去意义）。
API_KEY_ENV_VAR = "AICORE_DEEPSEEK_API_KEY"

#: R4 的负向标识符清单（tasks.md 4.4 的验收项「选择逻辑不读取业务参数」，逐字取自工单 §3.3）。
FORBIDDEN_IDENTIFIERS = (
    "account_id",
    "task_id",
    "merchant_id",
    "doc_type",
    "image_key",
    "request",
    "headers",
    "trace_id",
    "idem_key",
)

#: 选择矩阵的四行（顺序即文档里的矩阵顺序）。
PROVIDER_CASES = ("mock", "deepseek", "cloud_vision", "cloud_ocr")


# ---------------------------------------------------------------------------
# 配置构造
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    """测试配置：`_env_file=None` 隔离本地 `.env`，凭据用 `test_*` 占位值。

    `deepseek_api_key` 走**构造参数**而不是环境变量：环境变量在 `Settings` 侧会走
    「未识别 `AICORE_*`」检查源，而构造参数路径更直接地表达「本用例要的是这个取值」。
    """
    base: dict[str, Any] = {"provider": "mock", "deepseek_api_key": FAKE_API_KEY}
    base.update(overrides)
    return Settings(_env_file=None, **base)


# ---------------------------------------------------------------------------
# 零网络探针（自证判别力见 test_socket_guard_has_discriminating_power）
# ---------------------------------------------------------------------------


class _RealSocketBlockedError(AssertionError):
    """测试期出现**对外**真实 socket 建连时抛出（继承 AssertionError，pytest 直接呈现）。"""


#: 允许通过 `socket.connect` 的环回地址（例外只针对本机机制，理由见 `_SocketGuard`）。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback(address: Any) -> bool:
    """连接目标是不是本机环回（`address` 可能是 `(host, port)`，也可能是别的形态）。"""
    host = address[0] if isinstance(address, tuple) and address else address
    return isinstance(host, str) and host in _LOOPBACK_HOSTS


class _SocketGuard:
    """socket 建连探针：记录每一次 `connect`，**拦住所有对外建连**。

    ## 为什么环回必须放行（实测结论，非推断；两个实现者各自独立撞到过）

    Windows 上事件循环构造时会 `_make_self_pipe()` → `socket.socketpair()`；
    Windows 没有原生 socketpair，走 `socket._fallback_socketpair`，它**真的
    `connect((127.0.0.1, <临时端口>))`**。即：每条 async 用例在事件循环创建时都会产生
    **恰好一条**环回建连。这也正是「MUST NOT 无差别拦 `socket.socket.connect`」的原因——
    那样会让全部 async 用例 ERROR。

    环回不产生任何外部流量、更不可能产生计费调用，故显式放行——但依旧记录进 `attempts`：
    「放行」不等于「看不见」。
    """

    def __init__(self, real_connect: Any) -> None:
        self._real_connect = real_connect
        self.attempts: list[Any] = []

    @property
    def external(self) -> list[Any]:
        """本次用例里发生过的**对外**建连目标（teardown 断言它必须为空）。"""
        return [address for address in self.attempts if not _is_loopback(address)]

    def connect(self, sock: socket.socket, address: Any) -> None:
        """拦一次 connect：环回放行（并记录），其余一律抛错。"""
        self.attempts.append(address)
        if _is_loopback(address):
            self._real_connect(sock, address)
            return
        raise _RealSocketBlockedError(f"测试禁止对外建连：{address!r}")


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SocketGuard]:
    """全程禁止**对外** socket 建连，并在用例结束时断言「一次都没发生」。"""
    guard = _SocketGuard(socket.socket.connect)

    def _spy(self: socket.socket, address: Any) -> None:
        guard.connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _spy)
    yield guard
    assert guard.external == [], (
        f"用例期间发生了对外 socket 建连（目标 {guard.external!r}）：违反「选择器不发真实调用」"
    )


def test_socket_guard_has_discriminating_power(socket_guard: _SocketGuard) -> None:
    """判别力自证：桩真的拦得住对外建连，且例外**只**给环回（两向都测）。

    只测「拦住」不够：一个「什么都不拦」的桩也能让「对外建连为空」恒真。
    ① 对外目标必须被拦（`192.0.2.1` 是 RFC 5737 的文档专用网段，不可路由）；
    ② 环回目标必须放行（事件循环自管道要走它），但同样被记录在案。

    最后清空 `attempts` 是**自证所需**：这两次建连是探针的受试对象，
    不是「用例偷偷发了真实请求」。
    """
    with pytest.raises(_RealSocketBlockedError):
        socket.create_connection(("192.0.2.1", 9), timeout=0.05)

    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    finally:
        probe.close()
    with pytest.raises(OSError):  # 端口刚被释放 → 连接被拒；关键是这里**没有**抛探针异常
        socket.create_connection(("127.0.0.1", closed_port), timeout=0.5)

    assert len(socket_guard.attempts) == 2, "两次建连都必须被记录（放行 ≠ 不记录）"
    assert len(socket_guard.external) == 1, "只有非环回的那次算对外建连"
    socket_guard.attempts.clear()


# ---------------------------------------------------------------------------
# 网络替身：只换传输层，不碰 `provider/_http.py`（那是 Task 4.3 的交付物）
# ---------------------------------------------------------------------------


class _Transport:
    """`httpx.MockTransport` 的安装器：记录外发请求、并把 `_http.build_client` 换成替身。

    为什么在测试侧替换 `build_client` 而不是让通道支持注入 `transport`：
    通道签名由 Task 4.3 的工单逐字钉死（`(config, *, breaker, clock)`），
    为测试加参数会改契约；而 `_http` 是本模块的同包依赖，替换它不动任何对外接口。
    """

    def __init__(self, responder: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _Transport:
        """装上替身并返回自身（供用例取 `requests`）。"""
        from aicore.provider import _http

        transport = httpx.MockTransport(self._handle)

        def _fake_build_client(
            *, base_url: str, api_key: str, timeout_s: float
        ) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(timeout_s),
                headers=_http.auth_headers(api_key),
                transport=transport,
            )

        monkeypatch.setattr(_http, "build_client", _fake_build_client)
        return self

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    @property
    def count(self) -> int:
        """handler 被调用的次数 = 真实外发次数。"""
        return len(self.requests)


def _json_responder(payload: Any) -> Any:
    """固定 200 JSON 响应。"""

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return _respond


def _hanging_responder(seconds: float = 10.0) -> Any:
    """「等不到响应」的 handler：**真的挂住**（不是立刻抛超时异常）。

    为什么必须是 async 且真的 `await asyncio.sleep`：若 handler 立刻抛
    `httpx.ReadTimeout`，`guarded_call` 会走「底层超时异常」分支立刻归类为 timeout——
    那条路径**完全不经过 `asyncio.wait_for` 的 deadline**，于是「超时值来自 config」
    这件事根本没被验到（测试会假通过）。真挂住才能让 deadline 成为唯一的终结者。

    挂 10 秒是刻意的钝器：任何小于它的 deadline 都会先到期，故断言「耗时远小于它」
    直接证明 deadline 生效。`asyncio.wait_for` 超时时会取消本协程，故不会真等 10 秒。
    """

    async def _respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(seconds)
        raise AssertionError(f"deadline 未生效：请求挂满 {seconds}s 都没被取消（{request.url}）")

    return _respond


DEEPSEEK_OK: dict[str, Any] = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "结论"}}],
}


class _FakeClock:
    """`guard.StepClock` 的结构子类型实现：`monotonic()` 可控、`sleep()` 只累加虚拟时间。"""

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


# ---------------------------------------------------------------------------
# 1. 选择矩阵逐格（含 None 的格子）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDER_CASES)
def test_selection_matrix_matches_the_table_cell_by_cell(provider: str) -> None:
    """四行选择矩阵逐格断言：已选槽位非 `None`、**其余恰好为 `None`**。

    「其余恰好为 `None`」用的是本模块的 `_SELECTABLE_SLOTS` 登记表，而每一行登记在
    源码里紧挨着它的构造调用——所以本用例同时是「表里没漏写槽位」的守卫。
    `None` 的格子**显式断言**（不是只断言非 `None` 的那些）：本任务的核心决定就是
    「选不中的通道返回 `None` 而不是回落 mock」，只断言非 None 等于把这条决定漏测。
    为什么 MUST NOT 回落，见 `selector.py` 模块 docstring 与用例 9。
    """
    providers = select_providers(_settings(provider=provider))

    expected_selected = set(selector_module._SELECTABLE_SLOTS[provider])
    slot_values = {slot: getattr(providers, slot) for slot in selector_module._SLOT_NAMES}

    for slot, value in slot_values.items():
        if slot in expected_selected:
            assert value is not None, f"provider={provider} 的 {slot} 槽位应当被装配，实际是 None"
        else:
            assert value is None, (
                f"provider={provider} 的 {slot} 槽位必须是 None（MUST NOT 回落 mock / 其他通道），"
                f"实际是 {type(value).__name__}"
            )

    # 每个被选中的通道都必须真的满足它那个 Protocol（结构子类型，`base.py` D3）。
    # 只断言「不是 None」会让一个装错的实现（例如给 TEXT 槽位塞了 OCR 通道）蒙混过关。
    if providers.text is not None:
        assert isinstance(providers.text, TextProvider)
    if providers.vision is not None:
        assert providers.vision.model_meta()["channel"] == "VISION"
    if providers.ocr is not None:
        assert providers.ocr.model_meta()["channel"] == "OCR"


def test_mock_covers_all_three_slots_with_distinct_instances() -> None:
    """`mock` 是唯一覆盖三个槽位的 provider，且三个槽位**各一个实例**。

    共用实例会让「TEXT 被调用了几次」与「OCR 被调用了几次」在计数上不可分
    （`provider/mock.py` 的 `call_count` 是实例级的）。
    """
    providers = select_providers(_settings(provider="mock"))

    instances = [providers.text, providers.vision, providers.ocr]
    assert all(instance is not None for instance in instances)
    assert len({id(instance) for instance in instances}) == 3, "三个槽位 MUST 各一个实例"


def test_unregistered_channel_name_raises_instead_of_returning_empty_providers() -> None:
    """表与 `Settings.provider` 字面量必须**恰好互相覆盖**，否则选择器不静默成功。

    这条同时是「新增通道」的双向守卫：只加 `core/config.py` 的密钥表、忘了改本模块的
    通道表时，这里立刻变红；反之亦然。
    """
    declared = set(selector_module._REAL_PROVIDER_TABLE) | {selector_module.PROVIDER_MOCK}
    literal = set(get_args(Settings.model_fields["provider"].annotation))
    registered = set(selector_module._SELECTABLE_SLOTS)

    assert declared == literal, (
        f"selector 的通道表与 Settings.provider 字面量不一致："
        f"表里多出 {sorted(declared - literal)}、缺少 {sorted(literal - declared)}"
    )
    assert registered == literal, (
        f"槽位登记表必须覆盖全部 provider，缺 {sorted(literal - registered)}"
    )
    # 独立的第二锚点：**单看 selector 这一侧**，通道表里的每个 provider 名都必须是
    # `Settings.provider` 认得的（不只是「两边集合相等」）。这条拦的是「有人直接改了
    # `Settings.provider` 注解、或多写/写错一个 provider 名」这类两侧一起漂移的形态。
    assert set(selector_module._REAL_PROVIDER_TABLE) <= literal, (
        f"通道表里有 Settings.provider 不认得的名字："
        f"{sorted(set(selector_module._REAL_PROVIDER_TABLE) - literal)}"
    )

    # 绕过 Literal 的路径（`model_copy` 改字段）也必须得到一条**带名字**的错误，
    # 而不是一个三槽皆 None 的 Providers —— 后者会让「新增通道」安静地"成功"。
    rogue = _settings().model_copy(update={"provider": "future_channel"})
    with pytest.raises(ValueError, match="future_channel"):
        select_providers(rogue)


# ---------------------------------------------------------------------------
# 2. 三环境（tasks.md 4.4 的验收项）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_three_environments_select_or_are_rejected_at_settings_construction(env: str) -> None:
    """`dev` / `test` / `prod` × `mock` / `deepseek` 五格：四格选择成功、一格在构造期被拒。

    **分工 MUST 写清**（避免后人以为选择器也该拦 `prod` + `mock`）：

    - `dev` / `test` + `mock` → 选择成功（Mock 是 D3 定档的开发/测试默认通道）；
    - `prod` + `mock` → `Settings(...)` **构造期**就抛 `ValidationError`（`[跨字段：env-mock]`）。
      这条断言的是 **Task 2.2 的启动校验**，不是选择器：选择器**刻意不重复实现**它
      （重复实现会造出第二套会漂移的口径，见 `selector.py` 模块 docstring）。
      本用例顺带钉住「错误仍来自启动校验」——消息里有跨字段代号、`loc == ()`。
    - `prod` + `deepseek`（带密钥）→ 选择成功。

    三个环境的**期望槽位**取自选择矩阵登记表（`_SELECTABLE_SLOTS`）而不是在这里再抄一遍：
    抄一份就多了一个会与实现一起漂移的副本（槽位断言的权威在用例 1）。
    """
    if env == "prod":
        with pytest.raises(ValidationError) as excinfo:
            _settings(env=env, provider="mock")
        errors = excinfo.value.errors()
        assert any("[跨字段：env-mock]" in str(error["msg"]) for error in errors), (
            f"prod+mock 必须由启动校验拒绝，实际错误：{errors!r}"
        )
        assert all(error["loc"] == () for error in errors), "跨字段错误的 loc 必须是空元组"

    provider = "mock" if env != "prod" else "deepseek"
    providers = select_providers(_settings(env=env, provider=provider))
    expected_selected = set(selector_module._SELECTABLE_SLOTS[provider])

    assert providers.text is not None, f"env={env} + provider={provider} 应当选出一个 TEXT 通道"
    for slot in selector_module._SLOT_NAMES:
        value = getattr(providers, slot)
        if slot in expected_selected:
            assert value is not None, f"env={env} + provider={provider} 的 {slot} 槽位应当选中"
        else:
            assert value is None, f"env={env} + provider={provider} 的 {slot} 槽位必须是 None"


@pytest.mark.parametrize("env", ["dev", "test"])
def test_non_prod_mock_is_allowed_and_warned(
    env: str, caplog: pytest.LogCaptureFixture
) -> None:
    """`dev` / `test` 降级 `mock` 是**放行 + 告警**（规则 3，不阻断）。

    告警由 `core/config.py` 发出（选择器不产生任何环境相关行为，故这里只顺带核对
    「放行不是静默的」）。日志器名取自模块本身，避免与实现漂移。
    """
    with caplog.at_level("WARNING", logger=config_module.__name__):
        settings = _settings(env=env, provider="mock")

    assert settings.provider == "mock"
    assert "[告警：env-mock]" in caplog.text, (
        "非生产的 mock 降级必须留痕（规则 3：放行但告警，不是静默放行）"
    )


# ---------------------------------------------------------------------------
# 3. 不读业务参数（tasks.md 4.4 的核心结构断言）
# ---------------------------------------------------------------------------


def test_signature_has_no_business_parameters() -> None:
    """**强断言**：`select_providers` 的参数名集合恰为 `{config, breaker, clock}`。

    比 AST 扫描强，因为「没有这些参数」是代码结构事实，改名也绕不过去。
    """
    parameters = inspect.signature(select_providers).parameters
    assert set(parameters) == {"config", "breaker", "clock"}, (
        f"选择器只允许接收 config / breaker / clock，实际：{sorted(parameters)}"
    )
    assert parameters["breaker"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["clock"].kind is inspect.Parameter.KEYWORD_ONLY


def test_selector_source_has_no_business_identifiers() -> None:
    """AST 扫描 `selector.py`：不出现清单里的任一业务标识符。

    **这条断言的边界（MUST 写进 docstring，否则后人会高估它）**：AST 扫标识符是**弱断言**
    ——把 `account_id` 改名成 `aid` 就能绕过扫描，`getattr(config, "task" + "_id")` 之类的
    动态取属性也扫不到。真正的保证是
    `test_signature_has_no_business_parameters`：**签名里根本没有这些参数**，
    所以函数体无处可取。

    为什么仍然保留这一条：它拦的是「有人给 `select_providers` 加了参数之外的旁路」
    （读全局、读请求上下文、读环境变量里塞的业务字段）这类**增量的**错误写法，
    成本低、误报低。两层一起才是「不读业务参数」的可核证据。
    """
    source = SELECTOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.arg):
            used.add(node.arg)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            used.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 字符串键（`payload["task_id"]` 那种写法）同样要算进来。
            used.add(node.value)

    leaked = sorted(set(FORBIDDEN_IDENTIFIERS) & used)
    assert not leaked, f"selector.py 出现了业务参数标识符 {leaked}：选择 MUST 只读 config"


# ---------------------------------------------------------------------------
# 4. 护栏配置真的透传（§2.3）
# ---------------------------------------------------------------------------

_CUSTOM_GUARD_VALUES: dict[str, Any] = {
    "ai_call_timeout_s": 0.25,
    "provider_max_retries": 2,
    "circuit_error_ratio": 0.75,
    "circuit_cooldown_s": 3.5,
}


@pytest.mark.parametrize("provider", ["deepseek", "cloud_vision", "cloud_ocr"])
def test_guard_config_is_built_from_the_settings_not_hardcoded(provider: str) -> None:
    """四个护栏字段逐项等于 `Settings` 里的新值——**四项都由 `guard_config_from` 映射**。

    做法（工单 §3.4 让我二选一）：直接读被选中通道的 `_guard_config`（私有属性，
    Task 4.3 的通道实现持有它）。**为什么选它**：工单允许「没有读取入口就用假时钟反推」，
    而这里两个口径都可用——直读能一次断言**四个**字段（反推只能反推出 `timeout_s`
    与 `max_retries`），而 `error_ratio` / `cooldown_s` 恰恰是熔断那一对、最难从外部反推的。
    代价只是绑定一个私有名，而 `_guard_config` 是**被测行为本身**在实现里的落点
    （改名会让本用例 AttributeError 而不是假通过）。

    「不是只断言对象存在」这一点由下面的既有值对照保证：先断言默认值派生的
    `GuardConfig` 与新值派生的**不相等**，再断言实例等于后者。若选择器写死了模块常量，
    第二条断言必红。
    """
    settings = _settings(provider=provider, **_CUSTOM_GUARD_VALUES)
    expected = GuardConfig(
        timeout_s=_CUSTOM_GUARD_VALUES["ai_call_timeout_s"],
        max_retries=_CUSTOM_GUARD_VALUES["provider_max_retries"],
        error_ratio=_CUSTOM_GUARD_VALUES["circuit_error_ratio"],
        cooldown_s=_CUSTOM_GUARD_VALUES["circuit_cooldown_s"],
    )
    defaults = guard_config_from(_settings(provider=provider))
    assert defaults != expected, "两者相等时本用例失去判别力：新值必须先与默认值不同"

    providers = select_providers(settings)
    channel = next(
        value for value in (providers.text, providers.vision, providers.ocr) if value is not None
    )

    assert channel._guard_config == expected, (
        f"{provider} 的护栏参数不是从 config 映射来的（可能被写死在 selector 里）："
        f"{channel._guard_config!r} != {expected!r}"
    )


def test_selector_hands_the_config_itself_to_the_channel_constructor() -> None:
    """选择器 MUST 把**同一个 `config` 对象**交给通道构造函数（不只是把值抄进去）。

    为什么单独一条：通道从 `config` 里读的是两类东西——四项护栏参数（`_guard_config`）
    与**凭据**（`deepseek_api_key`）。凭据只在真实调用时经 `config` 读取，故「抄一份值出来」
    的实现可能让护栏那几条断言照样绿，却在真实调用时拿不到密钥。本用例用 spy 换掉通道表
    的构造入口，直接核对实参身份。

    spy 用 `_ChannelEntry` 造（而不是给 `_REAL_PROVIDER_TABLE` 里塞裸函数）：
    表的值类型是冻结 dataclass，替换后 `select_providers` 走的仍是同一条代码路径。
    """
    captured: dict[str, Any] = {}
    entry = selector_module._REAL_PROVIDER_TABLE["deepseek"]
    settings = _settings(provider="deepseek", **_CUSTOM_GUARD_VALUES)

    def _spy_build(
        config: Settings, breaker: CircuitBreaker, clock: Any
    ) -> Providers:
        captured["config"] = config
        captured["breaker"] = breaker
        captured["clock"] = clock
        return entry.build(config, breaker, clock)

    replacement = selector_module._ChannelEntry(
        build=_spy_build,
        slots=entry.slots,
        api_key_field=entry.api_key_field,
        provider_name=entry.provider_name,
    )
    monkey = pytest.MonkeyPatch()
    monkey.setitem(selector_module._REAL_PROVIDER_TABLE, "deepseek", replacement)
    try:
        providers = select_providers(settings)
    finally:
        monkey.undo()

    assert captured["config"] is settings, "通道构造函数必须收到同一个 config 对象（含凭据）"
    assert isinstance(captured["breaker"], CircuitBreaker)
    assert providers.text is not None
    assert providers.text._config is settings, "通道实例持有的 config 必须就是那一份"


async def test_timeout_from_config_cancels_the_call_at_the_new_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ai_call_timeout_s` 真的生效：把它压到 0.2s，一次**真挂住**的调用必须在 0.2s 被取消。

    这是直读 `_guard_config`（上一条用例）之外的**行为证据**（工单 §2.3 要求「通过把
    `MockTransport` 的行为与超时值关联起来断言」）：`guard.guarded_call` 用
    `config.timeout_s` 包 `asyncio.wait_for`，而 handler 会挂 10 秒——**能终结它的只有
    deadline**。若选择器没把配置值透传，通道会用它自带的 5s 默认值，本用例的耗时断言
    立刻变红（0.2s vs 5s 差 25 倍，不受 CI 抖动影响）。

    注意**调用侧声明的 `timeout_s` 也是 0.2**：`deepseek.py` 取
    `min(声明值, config.ai_call_timeout_s)`，两边都压住才使「耗时为 0.2s 级」
    只可能来自本用例显式给的那两个 0.2。`max_retries=0` 使超时直接终结
    （否则会真睡 1+2+4+8+16 秒，`conftest.py` 禁止任意 sleep）。
    """
    from aicore.provider.errors import ProviderTimeoutError

    transport = _Transport(_hanging_responder(10.0)).install(monkeypatch)
    settings = _settings(
        provider="deepseek",
        ai_call_timeout_s=0.2,
        provider_max_retries=0,
        deepseek_api_key=FAKE_API_KEY,
    )
    providers = select_providers(settings, clock=_FakeClock())
    assert providers.text is not None

    started = time.monotonic()
    with pytest.raises(ProviderTimeoutError):
        await providers.text.complete(prompt="p", payload={"k": "v"}, timeout_s=0.2)
    elapsed = time.monotonic() - started

    assert transport.count == 1, "只应外发一次（max_retries=0）"
    assert elapsed < 1.0, (
        f"调用在 {elapsed:.2f}s 后才终结：deadline 不是来自 config 的 ai_call_timeout_s"
        f"（handler 会挂 10s，唯一可能的终结者是 deadline）"
    )


# ---------------------------------------------------------------------------
# 5. `mock` 不构造任何 HTTP 客户端
# ---------------------------------------------------------------------------


def test_mock_selection_constructs_no_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """`provider=mock` 时选出的三个实例**不含** httpx 客户端属性。

    两向断言：
    ① 用 `httpx.AsyncClient` 的类做 `isinstance` 扫描实例的 `__dict__` 值，
       并用**阳性对照**证明这次扫描有判别力（往一个同样形态的 Mock 实例的 `__dict__` 里
       塞一个真客户端 → 同一段扫描必须能看见它）；
    ② 把 `httpx.AsyncClient` 换成一个**一构造就炸**的哨兵——句柄级证据：
       只要选择器（或 Mock 通道）真的建了一个客户端，本用例必红，而不是等到
       「值恰好不是 httpx 类型」才被动发现。
    """
    calls = 0

    def _forbidden_client(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError("provider=mock 的装配 MUST NOT 构造 httpx 客户端")

    # 先抓下真实的类再替换：替换之后 `isinstance(x, httpx.AsyncClient)` 的第二个参数
    # 已经是个函数，`isinstance` 会抛 TypeError（实测踩过），断言就失去意义。
    real_client_class = httpx.AsyncClient

    def _clients_of(instance: Any) -> list[Any]:
        """实例 `__dict__` 里的 httpx 客户端（扫描口径的唯一实现）。"""
        return [value for value in vars(instance).values() if isinstance(value, real_client_class)]

    # 阳性对照：同一段扫描在一个 Mock 实例被塞进客户端后必须报出来。
    probe_instance = selector_module.MockTextProvider()
    assert _clients_of(probe_instance) == []
    probe_instance.__dict__["_injected_client"] = real_client_class(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    assert len(_clients_of(probe_instance)) == 1, (
        "扫描没有判别力：塞进去的客户端都没被看见，断言①等于没测"
    )

    monkeypatch.setattr(httpx, "AsyncClient", _forbidden_client)
    providers = select_providers(_settings(provider="mock"))

    for slot in selector_module._SLOT_NAMES:
        instance = getattr(providers, slot)
        assert instance is not None
        assert _clients_of(instance) == [], (
            f"provider=mock 的 {slot} 槽位持有 httpx 客户端：{_clients_of(instance)!r}"
        )
    assert calls == 0


# ---------------------------------------------------------------------------
# 6. 真实通道缺密钥 fail fast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_missing_deepseek_key_raises_value_error(blank: str | None) -> None:
    """`provider=deepseek` 且密钥为 `None` / 空串 / 纯空白 → 抛 `ValueError` 并点名环境变量。

    **必须是 `ValueError` 而不是 `ProviderChannelFailureError`**：这属**装配期配置错误**，
    应在启动/装配阶段炸，而不是伪装成一次「通道调用失败」让任务转人工。
    这三种值走的是 `core/config.py` 的 `_is_blank` 同一口径（「没配」只有一种判定）。

    绕过 `Settings` 的路径用 `model_copy` 造（`Settings` 的跨字段校验会先拦下空密钥，
    故这条 fail fast 在正常构造路径上不可达，它的存在意义正是兜住 `model_copy` 这类路径）。
    """
    settings = _settings(provider="deepseek").model_copy(update={"deepseek_api_key": blank})

    with pytest.raises(ValueError) as excinfo:
        select_providers(settings)

    assert API_KEY_ENV_VAR in str(excinfo.value), (
        f"错误消息必须点名 {API_KEY_ENV_VAR}（运维一眼知道改哪一行）：{excinfo.value}"
    )
    assert not isinstance(excinfo.value, ValidationError), "这里要的是装配期 ValueError"


def test_blank_key_check_does_not_echo_the_value() -> None:
    """错误消息 MUST NOT 回显取值本身（凭据安全，同 `core/config.py` 的硬约束）。

    做法：先断言「非空取值不报错」（前提对照：本用例测的是**空白**分支），
    再用一个一眼假的哨兵确认错误消息里没有把取值写出来。
    """
    settings = _settings(provider="deepseek")
    assert select_providers(settings).text is not None, "非空密钥必须装配成功（前提对照）"

    # `_is_blank` 的定义是 `not (isinstance(value, str) and value.strip())`：
    # 只要取值不是空白串就会放行，故「哨兵被回显」只可能发生在错误消息里。
    blank = _settings(provider="deepseek").model_copy(update={"deepseek_api_key": "   "})
    with pytest.raises(ValueError) as excinfo:
        select_providers(blank)

    message = str(excinfo.value)
    assert API_KEY_ENV_VAR in message
    assert FAKE_API_KEY not in message
    assert "   " not in message, f"错误消息回显了空白取值本身：{message!r}"


# ---------------------------------------------------------------------------
# 7. `cloud_*` 不查不存在的字段
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["cloud_vision", "cloud_ocr"])
def test_cloud_channels_do_not_probe_a_missing_key_field(provider: str) -> None:
    """`cloud_vision` / `cloud_ocr` 尚无密钥字段：选择器 MUST NOT 抛 `AttributeError`。

    两件事一起断言：
    ① `select_providers` 正常返回（若为它们凭空查了 `getattr(config, "…api_key")`，这里
       会是 `AttributeError`）；
    ② 通道表里登记的 `api_key_field` 与 `core/config.py` 的
       `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 一致——这是「不查」的**结构性**证据，
       而不只是「碰巧没炸」。
    """
    assert provider in config_module._REAL_PROVIDERS_WITHOUT_KEY_FIELD, (
        "本用例的前提是这两个通道尚无密钥字段；前提变了就要改用例，而不是让它假通过"
    )
    entry = selector_module._REAL_PROVIDER_TABLE[provider]
    assert entry.api_key_field is None, (
        f"{provider} 在 selector 里登记了密钥字段 {entry.api_key_field!r}，"
        f"但 core/config.py 明确标注它尚无密钥字段"
    )

    providers = select_providers(_settings(provider=provider))
    selected = [
        value for value in (providers.text, providers.vision, providers.ocr) if value is not None
    ]
    assert len(selected) == 1, f"{provider} 只应选出一个通道，实际 {len(selected)} 个"


# ---------------------------------------------------------------------------
# 8. 熔断器共享
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["deepseek", "cloud_vision", "cloud_ocr"])
def test_breaker_is_shared_within_one_selection_and_not_a_module_singleton(provider: str) -> None:
    """同一次选择的通道共享一个 `CircuitBreaker`；两次选择**不同实例**（无模块级单例）。

    两条都必要：只测「同一次共享」会让模块级单例假通过；只测「两次不同」会漏掉
    「每个通道各造一个」这种让熔断状态互相不可见的写法（`selector.py` 的 docstring）。
    """
    settings = _settings(provider=provider)
    first = select_providers(settings)
    second = select_providers(settings)

    first_channel = next(
        value for value in (first.text, first.vision, first.ocr) if value is not None
    )
    second_channel = next(
        value for value in (second.text, second.vision, second.ocr) if value is not None
    )

    assert isinstance(first_channel._breaker, CircuitBreaker)
    assert first_channel._breaker is not second_channel._breaker, (
        "两次选择共享了同一个熔断器：说明用了模块级单例（会让用例之间互相污染）"
    )
    assert selector_module.CircuitBreaker is CircuitBreaker, "熔断器类型必须来自 provider.guard"


def test_injected_breaker_and_clock_reach_the_selected_channel() -> None:
    """调用方传入 `breaker` / `clock` 时 MUST 原样用它们（而不是另建一套）。

    两个注入点是同一件事的两面：`breaker` 决定「什么时候熔断」、`clock` 决定「退避睡多久、
    冷却怎么计时」，都属**调用方**的决策（用例注入假时钟即可零成本可测）。
    只要有一个被忽略，Task 4.11 的降级可观测就没有可注入的时间基准。
    """
    clock = _FakeClock()
    injected = CircuitBreaker(
        GuardConfig(timeout_s=1.0, max_retries=0, error_ratio=0.5, cooldown_s=1.0), clock=clock
    )

    providers = select_providers(_settings(provider="deepseek"), breaker=injected, clock=clock)

    assert providers.text is not None
    assert providers.text._breaker is injected, "传入的 breaker MUST 被使用（不得另建一个）"
    assert providers.text._clock is clock, "注入的时钟必须原样传给通道"


def test_injected_clock_reaches_the_channel_even_with_the_default_breaker() -> None:
    """只注入 `clock`（不传 `breaker`）时，时钟仍要到底：它同时要用于**自建的**熔断器。

    这条单独存在是因为它是最容易漏的一格：`clock` 有**两个**去处（自建熔断器的冷却计时、
    通道的重试退避），漏掉后者在「传了 breaker」的用例里看不出来。
    """
    clock = _FakeClock()

    providers = select_providers(_settings(provider="deepseek"), clock=clock)

    assert providers.text is not None
    assert providers.text._clock is clock
    assert providers.text._breaker._clock is clock, (
        "自建熔断器也必须用注入的时钟，否则冷却计时会走真实时钟（用例只能真等 10 秒）"
    )


def test_shared_breaker_keeps_its_state_keys_isolated() -> None:
    """共享一个熔断器是安全的：状态按 `(provider, operation)` 维度隔离。

    「共用安全」这句话在本任务里是一句**依赖**（`selector.py` 的 4.4 §2.4 裁定），
    故在这里把它钉成可核事实：不同 `(provider, operation)` 的窗口互不影响。
    """
    settings = _settings(provider="deepseek")
    providers = select_providers(settings)
    assert providers.text is not None
    breaker = providers.text._breaker

    breaker.record_failure("cloud_ocr", "recognize")
    assert breaker.state_of("cloud_ocr", "recognize") == "CLOSED", "样本不足 5 次时不得熔断"
    assert breaker.state_of("deepseek", "complete") == "CLOSED", "另一维度必须完全不受影响"


# ---------------------------------------------------------------------------
# 9. `None` 不回落（本任务的核心负向证据 + 判别力自证）
# ---------------------------------------------------------------------------


def test_none_slots_do_not_fall_back_to_mock() -> None:
    """`provider=cloud_ocr` 下 `text` / `vision` 必须是 `None`（**不回落到 mock**）。

    为什么这是硬要求而不是洁癖：在 `provider=cloud_ocr` 的部署里给 VISION 槽位塞一个 mock，
    等于让生产上视觉审核的结论来自模拟实现——`design.md:56` 逐字「生产环境自动降级 Mock
    会造成更严重的合规事故（等于用假数据伪造 AI 结论并进入人工复核）」。
    """
    providers = select_providers(_settings(provider="cloud_ocr"))

    assert providers.text is None and providers.vision is None, (
        "选不中的通道 MUST 返回 None：调用方据此转人工（4003），而不是拿到一个假通道"
    )
    assert providers.ocr is not None


def test_fallback_assertion_has_discriminating_power() -> None:
    """**判别力自证**：若实现改成「回落 mock」，上面那条断言会红。

    做法：在用例内构造一个「会回落」的假实现（与本文件被测的选择器无关），
    断言它给出非 `None` —— 从而证明「`is None`」这个方向确实能区分两种实现，
    而不是一条对任何实现都成立的恒真断言（例如把 `providers.text` 写成常量 `None` 时，
    上面那条会假通过吗？不会：`test_selection_matrix_matches_the_table_cell_by_cell`
    对 `mock` 行断言了 text 非 None，两侧合起来才封住）。
    """

    def _fallback(_config: Settings) -> Providers:
        """「回落版」实现：没配的通道一律拿 mock 顶上（本任务明令禁止的形态）。"""
        return Providers(
            text=selector_module.MockTextProvider(),
            vision=selector_module.MockVisionProvider(),
            ocr=selector_module.MockOcrProvider(),
        )

    fallback = _fallback(_settings(provider="cloud_ocr"))
    assert fallback.text is not None, (
        "回落版实现必须给出非 None 的 text —— 否则本自证无判别力（两种实现同态）"
    )
    # 两侧对照：真实现给 None、回落版给非 None，故 `is None` 这条断言是**有判别力的**。
    assert select_providers(_settings(provider="cloud_ocr")).text is None


# ---------------------------------------------------------------------------
# 10. `provider/__init__.py` 没有新增导出
# ---------------------------------------------------------------------------


def test_provider_facade_does_not_reexport_the_selector() -> None:
    """门面 MUST NOT 再导出 `select_providers`（`.importlinter` 契约 2 的分层边界）。

    `aicore.provider` 整包是 `service` 的 forbidden 模块，`service` 只允许依赖
    `aicore.provider.base`；门面一旦导出选择器，`service` 就能用
    `import aicore.provider` 绕过分层边界。组合根（`main.py`）直连
    `aicore.provider.selector`，不需要门面代劳。
    """
    import aicore.provider as facade

    assert not hasattr(facade, "select_providers"), (
        "provider/__init__.py 导出了 select_providers：service 层可经 `import aicore.provider` "
        "碰到具体通道实现，绕过分层边界（.importlinter 契约 2）"
    )
    source = (PROVIDER_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert imported == [], f"provider/__init__.py 出现导入语句：{[ast.dump(n) for n in imported]}"
