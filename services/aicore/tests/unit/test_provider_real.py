"""三个真实通道（`deepseek` / `cloud_vision` / `cloud_ocr`）的契约与护栏用例（Task 4.3）。

## 铁律：一条真实网络调用都不许发出（工单 §3.4 的验收硬项）

三层防护，缺一层都不算「不发出真实计费调用」：

1. **`httpx.MockTransport`**：本文件所有用例的客户端都由夹具 `harness` 提供的替身构造
   （`transport=httpx.MockTransport(handler)`），请求根本出不了进程；
2. **假地址**：autouse 夹具 `_fake_endpoints` 把三个通道的 `base_url` 常量指到 RFC 2606 的
   `.invalid` 保留域（**不可能解析**），云通道密钥指到假值——即使第 1 层失效也发不出去；
3. **socket 探针**：autouse 夹具 `socket_guard` 把 `socket.socket.connect` 换成会抛异常的桩，
   并断言整条用例里它一次都没被触发。

第 3 层还带**判别力自证**（`test_socket_guard_has_discriminating_power`）：桩必须真的能拦住
一次建连，否则「全绿」只说明没人建连，不说明探针有效。

## 替身与真实工厂的关系（本文件唯一的一处「测试替身」）

通道的 `build_client` 签名（工单 §3.2 逐字）不接受 `transport`，构造函数签名（§3.1 逐字）
也不接受。故夹具以 `monkeypatch.setattr(_http, "build_client", ...)` 注入一个
**只用 `_http.auth_headers()` 造头**的替身，从而：
- 三通道仍是「用真代码构造请求 → 真代码解析响应」，替身只换掉传输层；
- 头的口径仍来自被测模块（不是测试另写一份 `Bearer ...`）。

真实工厂本身另有直接断言（`test_real_factory_sets_timeout_and_auth_header` /
`test_api_key_never_appears_in_logs_messages_or_repr`），避免「替身好用、工厂坏了」的假绿。
"""

from __future__ import annotations

import ast
import json
import logging
import socket
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple, get_args

import httpx
import pytest

from aicore.core.config import Settings
from aicore.provider import _http, cloud_ocr, cloud_vision, deepseek
from aicore.provider.base import OcrProvider, TextProvider, VisionProvider
from aicore.provider.errors import (
    ProviderChannelFailureError,
    ProviderCircuitOpenError,
    ProviderTimeoutError,
)
from aicore.provider.guard import MIN_SAMPLES, CircuitBreaker, GuardConfig
from aicore.provider.results import ProviderIdentity, ProviderResult, to_jsonable

# ---------------------------------------------------------------------------
# 测试常量：一律假值（凭据扫描器与「不发出真实调用」两条红线都要求如此）
# ---------------------------------------------------------------------------

#: 假密钥。云通道用它覆盖 `API_KEY`，deepseek 用它构造 `Settings`。
FAKE_API_KEY = "sk-fake-0000-not-a-real-key"
#: 假对象键：`base.py` 要求通道收的是**对象存储键**而不是图像字节。
FAKE_IMAGE_KEY = "oss://aicore-test/desensitized/fake-image-0001.jpg"
#: 假地址（RFC 2606 保留域，DNS 永远解析不出结果）。
FAKE_BASE_URL = "https://fake.invalid"

TIMEOUT_S = 5.0
PROMPT_TEXT = "ocr-verify-v1"
TEXT_PAYLOAD: dict[str, Any] = {"taskId": "task_fake0001", "labels": ["ACID", "SALMONELLA"]}
VISION_LABELS = ["UNSANITARY", "MISLABEL"]
DOC_TYPE = "BUSINESS_LICENSE"

PROVIDER_DIR = Path(__file__).resolve().parents[2] / "src" / "aicore" / "provider"
CHANNEL_FILES = ("deepseek.py", "cloud_vision.py", "cloud_ocr.py")

#: 供应商 SDK（tasks.md 4.3 验收项：「不依赖任何具体供应商 SDK」）。
VENDOR_SDKS = (
    "openai",
    "anthropic",
    "dashscope",
    "volcengine",
    "zhipu",
    "baidu",
    "tencentcloud",
    "aliyun",
)

#: 通道文件允许依赖的第三方顶层模块（白名单比黑名单更能防「新引入一个没人想到的 SDK」）。
ALLOWED_THIRD_PARTY = {"httpx"}


# ---------------------------------------------------------------------------
# 假时钟（本文件自带的副本：两个测试文件各自独立，MUST NOT 互相 import 私有对象）
# ---------------------------------------------------------------------------


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
# 网络替身
# ---------------------------------------------------------------------------

Responder = Callable[[httpx.Request], httpx.Response]


class _Harness:
    """一次用例的网络替身：请求 spy + `build_client` 调用计数与超时记录。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, responder: Responder) -> None:
        self.requests: list[httpx.Request] = []
        self.build_calls = 0
        self.timeouts: list[float] = []
        self._responder = responder
        transport = httpx.MockTransport(self._handle)

        def _fake_build_client(
            *, base_url: str, api_key: str, timeout_s: float
        ) -> httpx.AsyncClient:
            self.build_calls += 1
            self.timeouts.append(timeout_s)
            # 头口径取被测模块的 `auth_headers`：替身只换传输层，不另写一套头。
            return httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(timeout_s),
                headers=_http.auth_headers(api_key),
                transport=transport,
            )

        monkeypatch.setattr(_http, "build_client", _fake_build_client)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    @property
    def count(self) -> int:
        """handler 被调用的次数 = 真实外发次数（「一次都没发出」的可断言之点）。"""
        return len(self.requests)

    @property
    def last(self) -> httpx.Request:
        """最近一次请求（handler 未被调用时显式失败，而不是抛 IndexError）。"""
        assert self.requests, "handler 一次都没被调用：请求根本没被构造出来"
        return self.requests[-1]

    def body_of(self, index: int = -1) -> dict[str, Any]:
        """请求体（JSON 解码后的对象）。"""
        return json.loads(self.requests[index].content)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Callable[[Responder], _Harness]:
    """安装 MockTransport 替身并返回 spy（每个用例一个新 spy）。"""

    def _install(responder: Responder) -> _Harness:
        return _Harness(monkeypatch, responder)

    return _install


def _json_responder(payload: Any, *, status: int = 200) -> Responder:
    """固定 JSON 响应。"""

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return _respond


def _raising_responder(error: Exception) -> Responder:
    """抛异常的 handler（模拟「等不到响应」的通道）。"""

    def _respond(request: httpx.Request) -> httpx.Response:
        raise error

    return _respond


@pytest.fixture(autouse=True)
def _fake_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """把三个通道的地址常量指到假地址、云通道密钥指到假密钥（见模块 docstring 的第 2 层）。

    改的是**模块级常量**（而不是给通道加一个只存在于测试里的构造参数）：
    通道在调用时才读这两个名字，故 `monkeypatch` 生效，且签名保持与工单 §3.1 逐字一致。
    """
    monkeypatch.setattr(deepseek, "DEFAULT_DEEPSEEK_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setattr(cloud_vision, "DEFAULT_CLOUD_VISION_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setattr(cloud_ocr, "DEFAULT_CLOUD_OCR_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setattr(cloud_vision, "API_KEY", FAKE_API_KEY)
    monkeypatch.setattr(cloud_ocr, "API_KEY", FAKE_API_KEY)


@pytest.fixture
def compliance_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """**临时**打开云通道的合规门，供「请求构造 / 响应解析」用例使用。

    合规门自身的负向证据在 `test_cloud_channel_compliance_gate_blocks_the_call`
    ——那里用**出厂值** `COMPLIANCE_READY=False` 断言 handler 计数为 0。
    """
    monkeypatch.setattr(cloud_vision, "COMPLIANCE_READY", True)
    monkeypatch.setattr(cloud_ocr, "COMPLIANCE_READY", True)


# ---------------------------------------------------------------------------
# socket 探针（第 3 层防护）
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

    ## 为什么环回必须放行（实测结论，不是推断）

    Windows 上 `asyncio.ProactorEventLoop` 构造时会 `_make_self_pipe()` →
    `socket.socketpair()`；Windows 没有原生 socketpair，走 `socket._fallback_socketpair`，
    它**真的 `connect((127.0.0.1, <临时端口>))`**。即：每条 async 用例在事件循环创建时
    都会产生一条环回建连。

    实测现场（临时探针打印调用栈，逐帧）：
    `asyncio/runners.py:60 → events.new_event_loop() → windows_events.py:316 →
    proactor_events.py:785 _make_self_pipe → socket.py:629 _fallback_socketpair
    → csock.connect((addr, port))`。

    拦住它等于让事件循环建不起来（async 用例直接 ERROR），而它**不产生任何外部流量**、
    更不可能产生计费调用，故显式放行——但依旧记录进 `attempts`：「放行」不等于「看不见」。
    对外目标（任何非环回地址）一律抛 `_RealSocketBlockedError`。
    """

    def __init__(self, real_connect: Any) -> None:
        self._real_connect = real_connect
        self.attempts: list[Any] = []

    @property
    def external(self) -> list[Any]:
        """本次用例里发生过的**对外**建连目标（teardown 断言它必须为空）。"""
        return [address for address in self.attempts if not _is_loopback(address)]

    def connect(self, sock: socket.socket, address: Any) -> None:
        self.attempts.append(address)
        if _is_loopback(address):
            self._real_connect(sock, address)
            return
        raise _RealSocketBlockedError(f"测试禁止对外建连：{address!r}")


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SocketGuard]:
    """全程禁止**对外** socket 建连，并在用例结束时断言「一次都没发生」。

    做法同 Task 4.2 工单 §3（`monkeypatch.setattr(socket.socket, "connect", _spy)`）：
    只拦 `connect` 而不拦 `socket()`——「建了套接字但没连」不产生流量。
    环回例外与理由见 `_SocketGuard` 的 docstring。
    """
    guard = _SocketGuard(socket.socket.connect)

    def _spy(self: socket.socket, address: Any) -> None:
        guard.connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _spy)
    yield guard
    assert guard.external == [], (
        f"用例期间发生了对外 socket 建连（目标 {guard.external!r}）：违反「不发真实调用」"
    )


def test_socket_guard_has_discriminating_power(socket_guard: _SocketGuard) -> None:
    """判别力自证：桩真的会拦住东西，且例外**只**给环回（两向都测）。

    只测「拦住」不够：一个「什么都不拦」的桩也能让「对外建连为空」恒真。
    ① 对外目标必须被拦住（`192.0.2.1` 是 RFC 5737 的文档专用网段，不可路由）；
    ② 环回目标必须放行（事件循环的自管道要走它），但同样被记录在案。

    最后清空 `attempts` 是**自证所需**：本次建连是探针的受试对象，不是「用例偷偷发了
    真实请求」，故不该让 teardown 的断言炸掉。除此之外本文件 MUST NOT 出现清空动作。
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
# 三通道用例素材
# ---------------------------------------------------------------------------

DEEPSEEK_OK: dict[str, Any] = {
    "id": "chatcmpl-fake",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "识别结论：材料一致，建议通过"},
            "finish_reason": "stop",
        }
    ],
    "confidence": 0.93,
}

VISION_OK: dict[str, Any] = {
    "markers": [
        {"label": "UNSANITARY", "level": "HIGH", "confidence": 0.95},
        {"label": "MISLABEL", "level": "MEDIUM"},  # 缺 confidence → None（MUST NOT 补 0）
    ],
    "confidence": 0.9,
}

#: 含 18 位身份证号（会被脱敏）、带连字符的日期（不动）、以及缺 confidence 的字段。
OCR_OK: dict[str, Any] = {
    "fields": [
        {"fieldName": "idNo", "value": "110101199003071234", "confidence": 0.97},
        {"fieldName": "validUntil", "value": "2027-12-31", "confidence": 0.88},
        {"fieldName": "holderName", "value": "张三"},
    ],
    "confidence": 0.96,
}


def _settings(**overrides: Any) -> Settings:
    """测试配置：`_env_file=None` 隔离开发者本地 `.env`，其余取 conftest 注入的占位值。

    与 `tests/unit/test_config.py` 同口径（那里也显式传 `_env_file=None`）：
    不隔离的话「本机有 `.env`、CI 没有」会让结论随环境漂移。
    """
    base: dict[str, Any] = {"provider": "mock", "deepseek_api_key": FAKE_API_KEY}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _fast_settings(**overrides: Any) -> Settings:
    """`provider_max_retries=0` 的配置：一次调用 = 一次尝试。

    需要「数调用次数」或「只让通道失败一次」的用例必须用它——否则一个可重试的失败
    （5xx / 超时 / 传输错误）会真的走完 6 次尝试并**真睡** 1+2+4+8+16 秒
    （`conftest.py`：测试内 MUST NOT 出现任意 sleep）。
    """
    base: dict[str, Any] = {"provider_max_retries": 0}
    base.update(overrides)
    return _settings(**base)


def _guard_config(*, max_retries: int = 0) -> GuardConfig:
    """护栏参数：默认与 `Settings` 的定档初值一致，只把重试压成 0 以便数调用次数。"""
    return GuardConfig(
        timeout_s=TIMEOUT_S,
        max_retries=max_retries,
        error_ratio=0.5,
        cooldown_s=10.0,
    )


async def _invoke_text(provider: Any, timeout_s: float) -> ProviderResult:
    return await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=timeout_s)


async def _invoke_vision(provider: Any, timeout_s: float) -> ProviderResult:
    return await provider.analyze(
        image_key=FAKE_IMAGE_KEY, labels=VISION_LABELS, timeout_s=timeout_s
    )


async def _invoke_ocr(provider: Any, timeout_s: float) -> ProviderResult:
    return await provider.recognize(
        image_key=FAKE_IMAGE_KEY, doc_type=DOC_TYPE, timeout_s=timeout_s
    )


def _assert_text_ok(result: ProviderResult) -> None:
    """TEXT：`choices[0].message.content` → `text`；`confidence` 取通道返回值。"""
    assert result.text == "识别结论：材料一致，建议通过"
    assert result.confidence == 0.93
    assert result.markers is None and result.fields is None, "TEXT 结果的另两种载荷必须是 None"
    assert result.identity.channel == "TEXT"
    assert result.lineage.provider == "deepseek"


def _assert_vision_ok(result: ProviderResult) -> None:
    """VISION：`markers` 每项都有 `label` / `level` / `confidence` 三个键。"""
    assert result.markers is not None
    assert [marker["label"] for marker in result.markers] == ["UNSANITARY", "MISLABEL"]
    assert [marker["level"] for marker in result.markers] == ["HIGH", "MEDIUM"]
    assert result.markers[0]["confidence"] == 0.95
    assert result.markers[1]["confidence"] is None, "通道没给的置信度 MUST NOT 补 0"
    assert result.confidence == 0.9
    assert result.text is None and result.fields is None


def _assert_ocr_ok(result: ProviderResult) -> None:
    """OCR：`fields` 为 `tuple[OcrField, ...]`，`value` 已脱敏，缺 `confidence` 补 `None`。"""
    assert result.fields is not None
    assert [field.fieldName for field in result.fields] == ["idNo", "validUntil", "holderName"]
    # 18 位 → 首 6 + 中间 8 个星（18 - 6 - 4）+ 末 4，长度不变（er.md §6.3 的同形示例）。
    assert result.fields[0].value == "110101********1234", "18 位证件号 MUST 已脱敏"
    assert result.fields[1].value == "2027-12-31", "连字符日期里的数字串不足 15 位，MUST 保持原样"
    assert result.fields[2].confidence is None, "通道没给的置信度 MUST NOT 补 0"
    assert result.confidence == 0.96
    assert result.text is None and result.markers is None


def _assert_text_body(body: Mapping[str, Any]) -> None:
    """`model` + `messages`（system = 模板，user = payload 的确定性 JSON）。"""
    assert body["model"] == deepseek.MODEL_VERSION
    messages = body["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == PROMPT_TEXT
    assert json.loads(messages[1]["content"]) == TEXT_PAYLOAD


def _assert_vision_body(body: Mapping[str, Any]) -> None:
    assert body == {"image_key": FAKE_IMAGE_KEY, "labels": VISION_LABELS}


def _assert_ocr_body(body: Mapping[str, Any]) -> None:
    assert body == {"image_key": FAKE_IMAGE_KEY, "doc_type": DOC_TYPE}


class ChannelCase(NamedTuple):
    """一个通道的用例素材（避免三份几乎相同的用例各自漂移）。"""

    label: str
    module: Any
    channel: str
    operation: str
    protocol: type
    path: str
    build: Callable[..., Any]
    invoke: Callable[[Any, float], Awaitable[ProviderResult]]
    ok_payload: dict[str, Any]
    malformed_payload: Any
    assert_body: Callable[[Mapping[str, Any]], None]
    assert_ok: Callable[[ProviderResult], None]


CHANNEL_CASES: tuple[ChannelCase, ...] = (
    ChannelCase(
        label="deepseek",
        module=deepseek,
        channel="TEXT",
        operation="complete",
        protocol=TextProvider,
        path=deepseek.CHAT_COMPLETIONS_PATH,
        build=deepseek.DeepSeekTextProvider,
        invoke=_invoke_text,
        ok_payload=DEEPSEEK_OK,
        malformed_payload={"choices": []},
        assert_body=_assert_text_body,
        assert_ok=_assert_text_ok,
    ),
    ChannelCase(
        label="cloud_vision",
        module=cloud_vision,
        channel="VISION",
        operation="analyze",
        protocol=VisionProvider,
        path=cloud_vision.VISION_MARKERS_PATH,
        build=cloud_vision.CloudVisionProvider,
        invoke=_invoke_vision,
        ok_payload=VISION_OK,
        malformed_payload={"markers": [{"label": "UNSANITARY"}]},  # 缺 level
        assert_body=_assert_vision_body,
        assert_ok=_assert_vision_ok,
    ),
    ChannelCase(
        label="cloud_ocr",
        module=cloud_ocr,
        channel="OCR",
        operation="recognize",
        protocol=OcrProvider,
        path=cloud_ocr.OCR_RECOGNIZE_PATH,
        build=cloud_ocr.CloudOcrProvider,
        invoke=_invoke_ocr,
        ok_payload=OCR_OK,
        malformed_payload={"fields": [{"value": "110101199003071234"}]},  # 缺 fieldName
        assert_body=_assert_ocr_body,
        assert_ok=_assert_ocr_ok,
    ),
)

CASE_IDS = [case.label for case in CHANNEL_CASES]
CLOUD_CASES = [case for case in CHANNEL_CASES if case.label != "deepseek"]
CLOUD_IDS = [case.label for case in CLOUD_CASES]


# ===========================================================================
# 1. 成功链路：请求确实被构造出来了，且解析结果正确
# ===========================================================================


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
async def test_channel_issues_the_expected_request(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """三通道各走一次成功链路：断言方法 / URL / 头 / 体 + 解析结果。

    「请求确实被构造出来」由 handler 收到 `request` 正面证明（不是靠日志或桩内部状态）。
    """
    box = harness(_json_responder(case.ok_payload))
    provider = case.build(_settings())

    result = await case.invoke(provider, TIMEOUT_S)

    request = box.last
    assert request.method == "POST"
    assert str(request.url) == f"{FAKE_BASE_URL}{case.path}"
    assert request.headers[_http.AUTH_HEADER] == f"Bearer {FAKE_API_KEY}", (
        "密钥 MUST 只在请求头里"
    )
    assert request.headers["content-type"] == "application/json"
    assert "key" not in str(request.url).lower(), "密钥 MUST NOT 进 URL"
    case.assert_body(box.body_of())
    case.assert_ok(result)
    assert provider.call_count == 1
    assert box.build_calls == 1


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
def test_channel_names_versions_and_identity(
    case: ChannelCase,
) -> None:
    """`name` 逐字对齐 `config.py` 的 `provider` 字面量；版本常量带通道前缀（工单 §3.1）。

    `provider` 字面量从 `Settings` 的字段注解现读（不是抄一份常量）：新增/改名通道时
    本用例会立刻变红，而不是等「selector 选出了一个没人实现的通道」在运行期爆。
    """
    provider = case.build(_settings())
    literal_values = set(get_args(Settings.model_fields["provider"].annotation))

    assert provider.name == case.label
    assert provider.name in literal_values, f"name 必须在 {sorted(literal_values)} 内"
    assert provider.model_version == case.module.MODEL_VERSION
    assert provider.prompt_version == case.module.PROMPT_VERSION
    assert provider.model_version.startswith(case.label), "模型版本 MUST 带通道前缀"
    assert provider.prompt_version.startswith(case.label), "Prompt 版本 MUST 带通道前缀"


# ===========================================================================
# 2. 超时链路
# ===========================================================================


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
async def test_channel_timeout_is_5002(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """三通道各走一次「超时」链路（handler 抛 `httpx.TimeoutException`）→ `5002`。"""
    box = harness(_raising_responder(httpx.ReadTimeout("fake timeout")))
    clock = _FakeClock()
    provider = case.build(
        _fast_settings(), breaker=CircuitBreaker(_guard_config(), clock=clock), clock=clock
    )

    with pytest.raises(ProviderTimeoutError) as excinfo:
        await case.invoke(provider, TIMEOUT_S)

    assert excinfo.value.code == 5002, "「没等到响应」是 5002，不是 4003"
    assert excinfo.value.reason == "timeout"
    assert excinfo.value.provider == case.label
    assert excinfo.value.operation == case.operation
    assert box.count == 1


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
async def test_channel_4xx_fails_fast(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """4xx（非 429）不重试：handler 只被调用 1 次，异常是 `4003 http-401`。"""
    box = harness(_json_responder({"error": "unauthorized"}, status=401))
    provider = case.build(_settings())

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await case.invoke(provider, TIMEOUT_S)

    assert excinfo.value.reason == "http-401"
    assert excinfo.value.code == 4003
    assert box.count == 1, "4xx 重试会把一次计费调用放大成六次，MUST NOT 重试"


# ===========================================================================
# 3. 熔断链路
# ===========================================================================


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
async def test_channel_circuit_open_is_4003_and_stops_calling(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """三通道各打满失败打开熔断 → `5002`，且 **handler 未被再次调用**。

    熔断归 `5002` 的依据：`services/_common/openapi.yaml:208` 逐字
    `- 5002 # 依赖超时 / 熔断`；`:135` 把「没等到响应」（含熔断）与「等到了失败」
    （4001~4004）划成两档。控制者初版曾归 4003（自造口径），由 P 阶段独立评审
    用变异测试抓到并修正——详见 `provider/errors.py` 的模块 docstring。

    **与超时同码、不同类**：熔断时**请求压根没发出去**（`box.count` 不增），
    超时时请求已发出。两者的可分辨性由异常类型 + `reason` 承担，不靠码值。
    """
    box = harness(_json_responder({"error": "channel down"}, status=503))
    clock = _FakeClock()
    config = _guard_config()
    breaker = CircuitBreaker(config, clock=clock)
    provider = case.build(_fast_settings(), breaker=breaker, clock=clock)

    for _ in range(MIN_SAMPLES):
        with pytest.raises(ProviderChannelFailureError):
            await case.invoke(provider, TIMEOUT_S)
    assert breaker.state_of(case.label, case.operation) == "OPEN"
    calls_to_open = box.count
    assert calls_to_open == MIN_SAMPLES, "每次调用一次尝试（max_retries=0）"

    with pytest.raises(ProviderCircuitOpenError) as excinfo:
        await case.invoke(provider, TIMEOUT_S)

    assert excinfo.value.code == 5002
    assert excinfo.value.reason == "circuit-open"
    assert box.count == calls_to_open, "熔断打开后 MUST NOT 再发出请求（这是「不计费」的证据）"
    assert provider.call_count == MIN_SAMPLES + 1, (
        "call_count 数的是「通道方法被调用」，被熔断挡下的那次同样 +1"
    )


# ===========================================================================
# 4. 畸形响应
# ===========================================================================


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
async def test_channel_malformed_response_is_explicit_failure(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """响应体缺字段 → `ProviderChannelFailureError(reason="malformed-response")`。"""
    box = harness(_json_responder(case.malformed_payload))
    provider = case.build(_settings())

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await case.invoke(provider, TIMEOUT_S)

    assert excinfo.value.reason == "malformed-response"
    assert excinfo.value.code == 4003
    assert box.count == 1, "畸形响应不重试（重发拿不回不同的结果，只会放大计费）"


async def test_non_json_body_is_malformed_response(
    harness: Callable[[Responder], _Harness],
) -> None:
    """对端返回 HTML 错误页（不是 JSON）同样 MUST 显式失败，而不是变成「编程错误」。"""
    box = harness(
        lambda request: httpx.Response(
            200, text="<html>502 Bad Gateway</html>", headers={"content-type": "text/html"}
        )
    )
    provider = deepseek.DeepSeekTextProvider(_settings())

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=TIMEOUT_S)

    assert excinfo.value.reason == "malformed-response"
    assert box.count == 1


async def test_confidence_with_wrong_type_is_malformed(
    harness: Callable[[Responder], _Harness],
) -> None:
    """`confidence` 不是数值（JSON 的 `true` 在 Python 里是 int 的子类，故显式排除）→ 畸形。"""
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "confidence": True,
    }
    box = harness(_json_responder(payload))
    provider = deepseek.DeepSeekTextProvider(_settings())

    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=TIMEOUT_S)

    assert excinfo.value.reason == "malformed-response"
    assert box.count == 1


# ===========================================================================
# 5. 密钥不泄漏
# ===========================================================================


async def test_real_factory_sets_timeout_and_auth_header() -> None:
    """**真实** `build_client`（不是替身）：超时与请求头逐项可核。

    这条是「替身好用、工厂坏了」的对照：替身绕过了 `build_client`，故工厂本身
    必须被直接断言一次。
    """
    client = _http.build_client(base_url=FAKE_BASE_URL, api_key=FAKE_API_KEY, timeout_s=1.25)
    try:
        assert client.headers[_http.AUTH_HEADER] == f"Bearer {FAKE_API_KEY}"
        assert client.timeout == httpx.Timeout(1.25)
        assert str(client.base_url) == FAKE_BASE_URL
    finally:
        await client.aclose()


async def test_api_key_never_appears_in_logs_messages_or_repr(
    harness: Callable[[Responder], _Harness],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """假密钥不得出现在：异常消息、`repr()`、日志、URL 里（工单 §3.2 的硬约束）。

    同时断言「密钥确实在请求头里」——否则「不含密钥」可以靠「什么都不传」作弊。
    """
    caplog.set_level(logging.DEBUG)

    client = _http.build_client(base_url=FAKE_BASE_URL, api_key=FAKE_API_KEY, timeout_s=TIMEOUT_S)
    try:
        assert client.headers[_http.AUTH_HEADER] == f"Bearer {FAKE_API_KEY}"
        assert FAKE_API_KEY not in repr(client)
        assert FAKE_API_KEY not in str(client.base_url)
    finally:
        await client.aclose()

    box = harness(_json_responder({"error": "channel down"}, status=503))
    # `_fast_settings()`：503 是可重试失败，默认的 5 次重试会真睡 1+2+4+8+16 秒。
    provider = deepseek.DeepSeekTextProvider(_fast_settings())
    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=TIMEOUT_S)

    error = excinfo.value
    assert FAKE_API_KEY not in str(error)
    assert FAKE_API_KEY not in repr(error)
    assert error.__cause__ is not None and FAKE_API_KEY not in repr(error.__cause__)
    leaked = [
        record.getMessage()
        for record in caplog.records
        if FAKE_API_KEY in record.getMessage()
    ]
    assert leaked == [], f"日志里出现密钥：{leaked}"
    assert FAKE_API_KEY not in str(box.last.url)


def test_build_client_rejects_key_material_in_the_url() -> None:
    """`base_url` 带 query / userinfo / fragment 一律拒绝，且**异常消息不回显该 URL**。

    这是「密钥只经请求头」的可执行形态：密钥一旦进 URL，就会同时进 httpx 的异常消息、
    访问日志与中间代理日志。异常消息只描述规则、不回显输入（否则校验器自己是泄漏点）。
    """
    bad_urls = (
        "https://fake.invalid/api?key=sk-fake-0000-not-a-real-key",
        "https://user:sk-fake-0000-not-a-real-key@fake.invalid/api",
        "https://fake.invalid/api#sk-fake-0000-not-a-real-key",
    )
    for bad in bad_urls:
        with pytest.raises(ValueError) as excinfo:
            _http.build_client(base_url=bad, api_key=FAKE_API_KEY, timeout_s=TIMEOUT_S)
        assert FAKE_API_KEY not in str(excinfo.value)
        assert bad not in str(excinfo.value)


# ===========================================================================
# 6. 脱敏保护
# ===========================================================================


def test_mask_long_digit_runs_boundary() -> None:
    """15 位是脱敏下界：14 位不动、15 位开始中间打星（首 6 + 星 + 末 4）。"""
    assert cloud_ocr.mask_long_digit_runs("1" * 14) == "1" * 14
    assert cloud_ocr.mask_long_digit_runs("1" * 15) == "111111" + "*" * 5 + "1111"
    assert cloud_ocr.mask_long_digit_runs("") == ""


async def test_ocr_masks_digit_runs_embedded_in_text(
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """混在文本里的证件号也要脱敏，且**整个结果结构**里都不该再有原值。

    只判「整串是否都是数字」会漏掉最常见的一种形态：字段值带前后缀
    （「统一社会信用代码 9113… 备案号 110101199003071234」）。
    """
    original = "110101199003071234"
    payload = {
        "fields": [
            {
                "fieldName": "licenseNo",
                "value": f"统一社会信用代码 91130100MA0XXXXX12 备案号 {original}",
                "confidence": 0.9,
            }
        ]
    }
    box = harness(_json_responder(payload))
    provider = cloud_ocr.CloudOcrProvider(_settings())

    result = await provider.recognize(
        image_key=FAKE_IMAGE_KEY, doc_type=DOC_TYPE, timeout_s=TIMEOUT_S
    )

    assert result.fields is not None
    masked = result.fields[0].value
    assert original not in masked
    assert "110101********1234" in masked
    assert "91130100MA0XXXXX12" in masked, "非纯数字的统一社会信用代码不触发脱敏（下界 15 位数字）"
    dumped = json.dumps(to_jsonable(result), ensure_ascii=False)
    assert original not in dumped, "未脱敏的原值 MUST NOT 出现在结果结构里的任何位置"
    assert box.body_of()["image_key"] == FAKE_IMAGE_KEY


# ===========================================================================
# 7. 合规门
# ===========================================================================


@pytest.mark.parametrize("case", CLOUD_CASES, ids=CLOUD_IDS)
async def test_cloud_channel_compliance_gate_blocks_the_call(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """合规未就绪：**handler 一次都没被调用**（计数 == 0）+ `4003` + WARNING 日志。

    这是本工单的核心负向证据（`spec.md:86`「未取得协议时系统 MUST NOT 调用该通道」、
    `:95-96`「拒绝调用该通道并告警」）：
    - `box.count == 0` → 请求根本没发出；
    - `box.build_calls == 0` → 连客户端都没构造（「在构造请求之前检查」）；
    - WARNING 日志 → 不是静默失败。
    """
    box = harness(_json_responder(case.ok_payload))
    provider = case.build(_settings())

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderChannelFailureError) as excinfo:
        await case.invoke(provider, TIMEOUT_S)

    assert excinfo.value.reason == "compliance-missing"
    assert excinfo.value.code == 4003
    assert case.module.COMPLIANCE_READY is False, "云通道的出厂状态 MUST 是未就绪"
    assert box.count == 0, "合规未就绪时 MUST NOT 发出任何请求"
    assert box.build_calls == 0, "合规检查 MUST 在构造请求之前"
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and case.label in record.getMessage()
    ]
    assert warnings, "合规拒绝 MUST 告警（spec.md:95-96），而不是静默失败"
    assert provider.call_count == 1, (
        "call_count 数的是「通道方法被调用」：被合规门挡下的那次同样 +1（口径见 deepseek.py）"
    )


async def test_deepseek_compliance_is_ready_and_calls_through(
    harness: Callable[[Responder], _Harness],
) -> None:
    """`deepseek` 的合规门为 `True`（依据 `产品设计文档.md:1623`）→ 正常发起请求。"""
    box = harness(_json_responder(DEEPSEEK_OK))
    provider = deepseek.DeepSeekTextProvider(_settings())

    result = await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=TIMEOUT_S)

    assert deepseek.COMPLIANCE_READY is True
    assert result.text == "识别结论：材料一致，建议通过"
    assert box.count == 1, "合规门为开时必须真的发出请求（否则「绿」没有判别力）"


async def test_three_channels_have_independent_compliance_flags() -> None:
    """三个文件的合规常量各自独立、且取值与依据一致（不是「一处 True 处处 True」）。"""
    assert deepseek.COMPLIANCE_READY is True
    assert cloud_vision.COMPLIANCE_READY is False
    assert cloud_ocr.COMPLIANCE_READY is False


# ===========================================================================
# 8. 入参校验（编程错误 MUST NOT 变成通道失败）
# ===========================================================================


async def test_non_positive_timeout_is_a_programming_error(
    harness: Callable[[Responder], _Harness],
) -> None:
    """`timeout_s <= 0` 抛 `ValueError`（编程错误），且**不发请求、不构造客户端**。

    放行的话 `asyncio.wait_for` 会立刻超时，于是「调用方把超时算错了」会伪装成
    `5002 依赖超时`——运维照着通道方向排查，而真正的 bug 在调用点。
    """
    box = harness(_json_responder(DEEPSEEK_OK))
    provider = deepseek.DeepSeekTextProvider(_settings())

    with pytest.raises(ValueError) as excinfo:
        await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=0.0)

    assert "timeout_s" in str(excinfo.value)
    assert box.count == 0
    assert box.build_calls == 0


async def test_effective_timeout_is_the_smaller_of_the_two(
    harness: Callable[[Responder], _Harness],
) -> None:
    """调用侧声明的超时与 `ai_call_timeout_s` 取较小值 —— 两者都是上限，都要成立。

    可观测点：传给客户端工厂的 `timeout_s`（就是每次尝试的预算）。
    """
    box = harness(_json_responder(DEEPSEEK_OK))
    provider = deepseek.DeepSeekTextProvider(_settings(ai_call_timeout_s=2.0))

    await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=30.0)
    assert box.timeouts == [2.0], "护栏 2s 更小 → 用它"

    await provider.complete(prompt=PROMPT_TEXT, payload=TEXT_PAYLOAD, timeout_s=0.5)
    assert box.timeouts == [2.0, 0.5], "任务声明的 0.5s 更小 → 用它"


@pytest.mark.parametrize("case", CLOUD_CASES, ids=CLOUD_IDS)
async def test_blank_image_key_is_a_programming_error(
    case: ChannelCase,
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """空 `image_key` 抛 `ValueError`（调用点拼错了参数），MUST NOT 变成一次计费调用。"""
    box = harness(_json_responder(case.ok_payload))
    provider = case.build(_settings())

    with pytest.raises(ValueError):
        if case.label == "cloud_vision":
            await provider.analyze(image_key="  ", labels=VISION_LABELS, timeout_s=TIMEOUT_S)
        else:
            await provider.recognize(image_key="", doc_type=DOC_TYPE, timeout_s=TIMEOUT_S)

    assert box.count == 0


async def test_empty_labels_are_rejected(
    harness: Callable[[Responder], _Harness],
    compliance_open: None,
) -> None:
    """`labels` 为空时抛 `ValueError`（空 labels 的检测请求没有意义）。"""
    box = harness(_json_responder(VISION_OK))
    provider = cloud_vision.CloudVisionProvider(_settings())

    with pytest.raises(ValueError):
        await provider.analyze(image_key=FAKE_IMAGE_KEY, labels=[], timeout_s=TIMEOUT_S)

    assert box.count == 0


# ===========================================================================
# 9~11. 血缘、Protocol 结构子类型、不依赖供应商 SDK
# ===========================================================================


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
def test_model_meta_delegates_to_identity(case: ChannelCase) -> None:
    """`model_meta()` 与 `ProviderIdentity.as_model_meta()` **逐键相等**（`er.md` §6.1）。"""
    provider = case.build(_settings())
    expected = ProviderIdentity(
        channel=case.channel,
        provider=case.label,
        model_version=case.module.MODEL_VERSION,
        prompt_version=case.module.PROMPT_VERSION,
    ).as_model_meta()

    meta = provider.model_meta()
    assert meta == expected
    assert set(meta) == {"channel", "provider", "modelVersion", "promptVersion", "thresholds"}
    assert meta["channel"] == case.channel
    assert meta["provider"] == case.label


@pytest.mark.parametrize("case", CHANNEL_CASES, ids=CASE_IDS)
def test_channel_is_a_protocol_subtype(case: ChannelCase) -> None:
    """Protocol 结构子类型：`isinstance(obj, ...)` 三条为真。

    **该断言不检查签名**：`@runtime_checkable` 的 Protocol 在运行期只逐成员检查
    「属性 / 方法在不在」，参数名、参数类型、返回类型一概不看（`base.py` 的 docstring
    写明了这个能力边界）。签名一致性由 `mypy --strict src` 承担：三个实现都是
    `async def complete/analyze/recognize(*, ...) -> ProviderResult`，签名漂移会在
    mypy 阶段变红，而不是在这里。故本用例只能证明「成员都在」。
    """
    provider = case.build(_settings())
    assert isinstance(provider, case.protocol)


def _imported_top_level_modules(source: str) -> set[str]:
    """源码里 import 的顶层模块名（用 AST 而不是正则：字符串与注释里的 `import` 不算）。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_vendor_sdk_scanner_is_discriminating() -> None:
    """判别力自证：扫描器真的能抓到供应商 SDK 的 import（否则全绿说明不了任何事）。"""
    sample = "import openai\nfrom dashscope import MultiModalConversation\nimport httpx\n"
    assert _imported_top_level_modules(sample) == {"openai", "dashscope", "httpx"}


@pytest.mark.parametrize("filename", CHANNEL_FILES)
def test_channel_imports_no_vendor_sdk(filename: str) -> None:
    """tasks.md 4.3 验收项：三个通道**不依赖任何具体供应商 SDK**。"""
    source = (PROVIDER_DIR / filename).read_text(encoding="utf-8")
    found = _imported_top_level_modules(source) & set(VENDOR_SDKS)
    assert found == set(), f"{filename} 引入了供应商 SDK {sorted(found)}：四类通道必须可替换"


@pytest.mark.parametrize("filename", CHANNEL_FILES)
def test_channel_dependencies_are_stdlib_aicore_or_httpx(filename: str) -> None:
    """通道依赖白名单：stdlib + `aicore` + `httpx`。

    白名单比黑名单更耐用：新增一个「没人想到要拉黑」的 SDK 时，黑名单放行、白名单报警。
    真实接入若要引入新依赖（例：厂商官方 SDK），必须显式改本用例——那就是一次评审。
    """
    source = (PROVIDER_DIR / filename).read_text(encoding="utf-8")
    foreign = {
        name
        for name in _imported_top_level_modules(source)
        if name not in sys.stdlib_module_names
        and name != "aicore"
        and name not in ALLOWED_THIRD_PARTY
    }
    assert foreign == set(), f"{filename} 引入了白名单外的依赖 {sorted(foreign)}"


@pytest.mark.parametrize("filename", CHANNEL_FILES)
def test_channels_use_the_shared_client_factory_only(filename: str) -> None:
    """通道 MUST NOT 自己 `httpx.AsyncClient(...)`：唯一构造点是 `_http.build_client`。

    规则 5（`tests/structural/test_source_guards.py`）只保证「HTTP 调用不越出 provider 包」，
    管不到包内是否各写一套客户端构造——那正是「超时 / 头 / base_url 口径三分」的来源。
    正向对照（`build_client` 必须在文件里出现）与反向断言成对：否则「没有 AsyncClient」
    可以靠「这段代码根本不存在」作弊。
    """
    source = (PROVIDER_DIR / filename).read_text(encoding="utf-8")
    assert "httpx.AsyncClient" not in source, f"{filename} 自己构造了 httpx 客户端"
    assert "_http.build_client(" in source, f"{filename} 没有走 `_http.build_client`"
