"""Mock 通道契约用例（Task 4.2）。

本文件是 `provider/mock.py` 的**离线可跑证明**：本项目自己的代码全程零 socket 建连
（见 `tests/conftest.py` 的 `_session_socket_guard` 与它的判别力自证用例），
故「断网可跑」这件事在 CI 里有可核证据，而不是靠「我们没写过网络代码」这句自述。

## 零建连的取证口径：为什么不是「一刀切禁止所有 connect」

工单 §3 给的取证形式是「把 `socket.socket.connect` 换成一律抛错的桩」，并自证判别力。
**在本机实测该形式不可用**——不是因为它太严，而是因为它会先炸掉与本任务无关的东西：

    CONNECT ('127.0.0.1', 56708)
      asyncio/runners.py:147:_lazy_init → events.py:735:new_event_loop
      → windows_events.py:316:__init__ → proactor_events.py:639:__init__
      → proactor_events.py:785:_make_self_pipe

Windows 上 asyncio 的 Proactor 事件循环用**一对回环 socket** 当 self-pipe，
建循环即建连；而 pytest-asyncio 在**夹具阶段**就建好了本用例的循环——早于本文件任何
一行代码。于是一刀切会让每条 async 用例在 setup/teardown 阶段就失败（实测：本文件
51 条用例全 ERROR），而它们的失败与「有没有网络依赖」毫无关系。

故取证口径改为**可归因**：记录每一次 connect 及其调用栈，只有在栈里出现
**本项目自己的代码**（本测试文件 / `src/aicore` 下任何模块）时才算违规。威胁模型正是
「provider 或测试偷偷建连」，而 asyncio 的 self-pipe 栈里只有 stdlib 的 asyncio 帧
（上面那段栈逐行可复核），两者不会混淆。事件循环那条被单独记为
`allowed_self_pipe` 并在守卫消息里保留，使「允许了什么」永远可见而不是被静默放过。

## 确定性为什么要跨进程验一遍

同进程连调三次相等**不足以**证明确定性：Python 对 `str` 的 `hash()` 带
`PYTHONHASHSEED` 随机化，同进程内哈希种子固定，用它写出来的「确定性」在单进程里
永远看起来是对的，只有换一个解释器（或 pytest-xdist 分片、或 CI 上另一个 runner）
才会露馅。故 `test_cross_process_determinism_*` 起**真的新解释器**跑同一入参并比对
输出——那三条才是「跨进程确定」的证据。

## 本文件不做什么

- 不接真实模型、不读密钥、不发任何请求；
- 不 `sleep`（延迟经注入的假睡眠函数断言，见 `tests/conftest.py` 文件头）；
- 不把 `isinstance(obj, Protocol)` 当作「契约已验证」——见
  `test_provider_protocol_structural_subtyping` 的 docstring。
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aicore.provider import base
from aicore.provider.errors import ProviderChannelFailureError, ProviderTimeoutError
from aicore.provider.mock import (
    MOCK_PROVIDER_NAME,
    MockFault,
    MockOcrProvider,
    MockScript,
    MockTextProvider,
    MockVisionProvider,
)
from aicore.provider.results import OcrField, ProviderIdentity, ProviderResult, to_jsonable

#: 服务根的 `src/` 目录：跨进程用例要把它拼进子进程的 `sys.path`。
SRC_DIR = Path(__file__).resolve().parents[2] / "src"

#: 判定「看似真实证件号」的正则：连续 15 位以上数字（工单 §2.6 的可核方式）。
_LONG_DIGIT_RUN = re.compile(r"\d{15,}")

#: 「编号类字段」的判据：按**字段名**判定，而不是按值的形状。
#:
#: 为什么按名字而不是按值：值的形状会把脱敏本身变成判据的一部分（脱敏后的
#: `91330100********1234` 含星号、不再「纯 ASCII」），于是「没脱敏的值」反而被判成
#: 非编号字段，断言自我失效——实测踩到过。字段名与脱敏无关，是稳定判据。
#: 中文命名的非编号字段（名称 / 经营范围 / 检测结论 / 有效期至）不在其列：
#: 它们本就不是编号，对其要求星号是把工单没要求的形态强加给实现。
_IDENTIFIER_FIELD_NAME_TOKENS = ("编号", "信用代码")

#: 脱敏段：连续 3 个以上星号（中间打星号的形态，如 `911301********1234`）。
_MASK_RUN = re.compile(r"\*{3,}")

#: `model_meta` 的键集合（`er.md` §6.1 的 5 个键，camelCase）。
_EXPECTED_MODEL_META_KEYS = {"channel", "provider", "modelVersion", "promptVersion", "thresholds"}

#: 未知 doc_type 的通用字段名（与 `mock.py` 的 `_UNKNOWN_DOC_FIELD_NAMES` 同形）。
#: 这里显式写死一份而**不是** import 实现里的私有名：断言要与实现独立，
#: 否则实现把常量改空，用例会跟着一起"通过"。
_UNKNOWN_DOC_FIELD_NAMES = ("文档编号", "主体名称", "有效期至")


def _is_identifier_field(field_name: str) -> bool:
    """该字段是否「编号类」（判据见 `_IDENTIFIER_FIELD_NAME_TOKENS` 的注释）。"""
    return any(token in field_name for token in _IDENTIFIER_FIELD_NAME_TOKENS)


class _SleepRecorder:
    """记录睡眠请求的假睡眠函数：断言「收到了几秒的请求」而**不真的等**。"""

    def __init__(self) -> None:
        self.requests: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.requests.append(seconds)


async def _call_channel(
    provider: Any, operation: str, *, timeout_s: float, latency_s: float = 0.0
) -> ProviderResult:
    """按方法名调用某个通道。

    三个通道的入参各不相同（`prompt`+`payload` / `image_key`+`labels` /
    `image_key`+`doc_type`），故集中在这里收口，使「三通道同一条规则」的断言
    （超时护栏等）不必把同一个调用写三遍——写三遍就会出现「某个通道漏改」。
    """
    if operation == "complete":
        result = await provider.complete(prompt="p", payload={"a": 1}, timeout_s=timeout_s)
    elif operation == "analyze":
        result = await provider.analyze(image_key="k", labels=["疑似过期"], timeout_s=timeout_s)
    else:
        result = await provider.recognize(image_key="k", doc_type="LICENSE", timeout_s=timeout_s)
    assert isinstance(result, ProviderResult)
    return result


def _payload_field(result: ProviderResult) -> str:
    """返回该结果实际填写的载荷字段名；三个载荷字段都为空时失败。

    一个函数服务两类断言：`..._payload_fields_are_mutually_exclusive` 要它等于期望
    字段名，其余用例借它顺手确认「实现确实产出了载荷」（否则空实现能全绿）。
    """
    filled = [
        name
        for name, value in (
            ("text", result.text),
            ("markers", result.markers),
            ("fields", result.fields),
        )
        if value is not None
    ]
    assert filled, f"ProviderResult 三个载荷字段全为空，违反「载荷字段互斥」契约：{result!r}"
    assert len(filled) == 1, f"ProviderResult 同时填写了多个载荷字段 {filled}：{result!r}"
    return filled[0]


def _all_text_values(result: ProviderResult) -> list[str]:
    """把结果里的**所有文本值**摊平成字符串，供脱敏检查使用。

    摊平而不是只查 `fields[].value`：脱敏是「产出里不许出现明文」这件事的**整体**
    性质，只查一个字段会漏掉 marker 的 `label` 与 TEXT 的 `text`（同样是通道产出）。
    """
    values: list[str] = []
    if result.text is not None:
        values.append(result.text)
    for marker in result.markers or ():
        values.extend(str(value) for value in marker.values())
    for field in result.fields or ():
        values.append(field.fieldName)
        values.append(field.value)
    return values


def _assert_payload_fields_are_mutually_exclusive(result: ProviderResult, expected: str) -> None:
    """三个载荷字段三选一，其余 MUST 为 `None`（工单 §2.5）。"""
    assert _payload_field(result) == expected
    for name in ("text", "markers", "fields"):
        if name != expected:
            assert getattr(result, name) is None, (
                f"{expected} 通道的结果里 {name} 不为 None：{getattr(result, name)!r}"
            )


def _as_dict(value: Any) -> Any:
    """JSON 往返归一化：把父进程的结果压成与子进程 stdout 同形的结构。"""
    return json.loads(json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True))


def _subprocess_result(operation: str, **kwargs: str) -> Any:
    """在**新解释器**里跑一次同一入参，返回其 JSON 输出（经 stdout 传回）。

    子进程只 import `provider/*`（纯 stdlib 链路），不经过 `tests/conftest.py`，
    故它读不到任何配置、不依赖任何夹具——这正是「离线可跑」的形态。
    """
    script = (
        "import asyncio, json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from aicore.provider.mock import MockOcrProvider, MockTextProvider, MockVisionProvider\n"
        "from aicore.provider.results import to_jsonable\n"
        "op, a, b, t = sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])\n"
        "async def main():\n"
        "    if op == 'complete':\n"
        "        r = await MockTextProvider().complete(\n"
        "            prompt=a, payload=json.loads(b), timeout_s=t)\n"
        "    elif op == 'analyze':\n"
        "        r = await MockVisionProvider().analyze(\n"
        "            image_key=a, labels=json.loads(b), timeout_s=t)\n"
        "    else:\n"
        "        r = await MockOcrProvider().recognize(image_key=a, doc_type=b, timeout_s=t)\n"
        "    return to_jsonable(r)\n"
        "print(json.dumps(asyncio.run(main()), ensure_ascii=False, sort_keys=True))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(SRC_DIR), operation, *kwargs.values()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, (
        f"子进程复算失败（rc={completed.returncode}）：{completed.stderr}"
    )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# 1. 三通道基本调用
# ---------------------------------------------------------------------------


async def test_text_provider_returns_text_only() -> None:
    """TEXT 通道只填 `text`，`markers` / `fields` 恒为 `None`，`channel` 为 TEXT。"""
    result = await MockTextProvider().complete(
        prompt="ocr-verify", payload={"docType": "BUSINESS_LICENSE"}, timeout_s=1.0
    )
    assert isinstance(result, ProviderResult)
    assert result.identity.channel == "TEXT"
    assert result.identity.provider == MOCK_PROVIDER_NAME
    assert isinstance(result.text, str) and result.text
    _assert_payload_fields_are_mutually_exclusive(result, "text")


async def test_vision_provider_returns_markers_only() -> None:
    """VISION 通道只填 `markers`，且每个 label 产出一条 marker。"""
    labels = ["疑似过期", "卫生问题", "未穿工装"]
    result = await MockVisionProvider().analyze(
        image_key="cert/oss/2026/01/abc123.jpg", labels=labels, timeout_s=1.0
    )
    assert isinstance(result, ProviderResult)
    assert result.identity.channel == "VISION"
    _assert_payload_fields_are_mutually_exclusive(result, "markers")
    markers = result.markers
    assert markers is not None
    assert len(markers) == len(labels)
    assert [marker["label"] for marker in markers] == labels
    for marker in markers:
        # 键名对齐 openapi.yaml:945-992 的 VisionMarker；level 取自 ConfidenceLevel。
        assert set(marker) == {"label", "level", "confidence", "bbox"}
        assert marker["level"] in {"HIGH", "MEDIUM", "LOW"}


async def test_vision_without_labels_returns_empty_markers() -> None:
    """`labels` 为空 → `markers=()` + `confidence=None`（与 `empty` 故障同形态）。"""
    result = await MockVisionProvider().analyze(image_key="k", labels=[], timeout_s=1.0)
    _assert_payload_fields_are_mutually_exclusive(result, "markers")
    assert result.markers == ()
    assert result.confidence is None


async def test_ocr_provider_returns_fields_only() -> None:
    """OCR 通道只填 `fields`，键名与 `openapi.yaml:708-726` 的 `OcrField` 一致。"""
    result = await MockOcrProvider().recognize(
        image_key="cert/oss/2026/01/abc123.jpg", doc_type="BUSINESS_LICENSE", timeout_s=1.0
    )
    assert isinstance(result, ProviderResult)
    assert result.identity.channel == "OCR"
    _assert_payload_fields_are_mutually_exclusive(result, "fields")
    fields = result.fields
    assert fields is not None and fields
    for field in fields:
        assert isinstance(field, OcrField)
        assert field.fieldName
        assert field.value


@pytest.mark.parametrize(
    ("doc_type", "expected_names"),
    [
        (
            "BUSINESS_LICENSE",
            ("统一社会信用代码", "名称", "法定代表人", "有效期至", "经营范围"),
        ),
        ("LICENSE", ("许可证编号", "持证单位", "法定代表人", "有效期至", "许可范围", "发证机关")),
        (
            "INSPECTION_REPORT",
            ("报告编号", "受检单位", "样品名称", "检测项目", "检测结论", "报告日期"),
        ),
    ],
)
async def test_ocr_field_set_follows_doc_type(
    doc_type: str, expected_names: tuple[str, ...]
) -> None:
    """三类证照提取各自的字段集：Mock 必须看 `doc_type`，否则 Task 5.3 的用例没有判别力。"""
    result = await MockOcrProvider().recognize(
        image_key="cert/oss/2026/01/abc123.jpg", doc_type=doc_type, timeout_s=1.0
    )
    fields = result.fields
    assert fields is not None
    names = tuple(field.fieldName for field in fields)
    assert names == expected_names
    assert len(names) == len(set(names)), f"同一证照出现重复字段名：{names}"


async def test_unknown_doc_type_falls_back_to_generic_fields() -> None:
    """未在模板表里的 doc_type 返回通用字段集（而非空集，见 `mock.py` 的注释）。

    返回空集会让「Mock 不认识这个 doc_type」与「通道返回了空结果」两个成因
    在数据上不可分——而后者正是 `MockFault(kind="empty")` 要演练的形态。
    """
    result = await MockOcrProvider().recognize(
        image_key="cert/oss/2026/01/abc123.jpg", doc_type="UNRECOGNIZED_DOC", timeout_s=1.0
    )
    fields = result.fields
    assert fields is not None
    assert tuple(field.fieldName for field in fields) == _UNKNOWN_DOC_FIELD_NAMES


# ---------------------------------------------------------------------------
# 2. 确定性（同进程）
# ---------------------------------------------------------------------------


async def test_text_output_is_deterministic_within_process() -> None:
    """同入参连调 3 次，`to_jsonable` 完全相等（逐字节）。"""
    provider = MockTextProvider()
    outputs = [
        _as_dict(
            await provider.complete(prompt="ocr-verify", payload={"b": 2, "a": 1}, timeout_s=1.0)
        )
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]
    # 键序不同的同一份 Mapping 必须得到同一结果（sort_keys 规范化）。
    reordered = _as_dict(
        await provider.complete(prompt="ocr-verify", payload={"a": 1, "b": 2}, timeout_s=1.0)
    )
    assert reordered == outputs[0], "Mapping 的插入顺序影响了产出：入参规范化没有生效"


async def test_vision_and_ocr_outputs_are_deterministic_within_process() -> None:
    """视觉与 OCR 同样「同输入同输出」，且产出**与调用序号无关**。"""
    vision = MockVisionProvider()
    vision_first = _as_dict(
        await vision.analyze(image_key="k1", labels=["疑似过期"], timeout_s=1.0)
    )
    vision_second = _as_dict(
        await vision.analyze(image_key="k1", labels=["疑似过期"], timeout_s=1.0)
    )
    assert vision_first == vision_second, "VISION 的产出随调用序号漂移（call_count 不该参与派生）"

    ocr = MockOcrProvider()
    ocr_first = _as_dict(await ocr.recognize(image_key="k1", doc_type="LICENSE", timeout_s=1.0))
    ocr_second = _as_dict(await ocr.recognize(image_key="k1", doc_type="LICENSE", timeout_s=1.0))
    assert ocr_first == ocr_second, "OCR 的产出随调用序号漂移（call_count 不该参与派生）"


async def test_different_inputs_produce_different_outputs() -> None:
    """确定性的**判别力自证**：入参变一处，产出必须变。

    只断言「同输入同输出」时，一个返回常量的实现能全绿通过；加这一条才说明产出
    真的由入参派生（sha256）而不是被写死。
    """
    text = MockTextProvider()
    first = await text.complete(prompt="prompt-a", payload={"a": 1}, timeout_s=1.0)
    second = await text.complete(prompt="prompt-b", payload={"a": 1}, timeout_s=1.0)
    assert _as_dict(first) != _as_dict(second)

    ocr = MockOcrProvider()
    ocr_a = await ocr.recognize(image_key="key-a", doc_type="LICENSE", timeout_s=1.0)
    ocr_b = await ocr.recognize(image_key="key-b", doc_type="LICENSE", timeout_s=1.0)
    assert _as_dict(ocr_a) != _as_dict(ocr_b)

    vision = MockVisionProvider()
    vision_a = await vision.analyze(image_key="key-a", labels=["l"], timeout_s=1.0)
    vision_b = await vision.analyze(image_key="key-b", labels=["l"], timeout_s=1.0)
    assert _as_dict(vision_a) != _as_dict(vision_b)


# ---------------------------------------------------------------------------
# 3. 确定性（跨进程）—— 本任务的关键证据
# ---------------------------------------------------------------------------


async def test_cross_process_determinism_text() -> None:
    """**新解释器**跑同一入参，输出与父进程逐字节相等。

    这条才真正证明「跨进程确定」：同进程三次相等无法发现 `hash()` 的
    `PYTHONHASHSEED` 随机化（见模块 docstring）。
    """
    payload = {"docType": "BUSINESS_LICENSE", "scene": "MERCHANT_ONBOARDING"}
    local = _as_dict(
        await MockTextProvider().complete(prompt="ocr-verify", payload=payload, timeout_s=1.0)
    )
    remote = _subprocess_result(
        "complete",
        prompt="ocr-verify",
        payload=json.dumps(payload, ensure_ascii=False),
        timeout_s="1.0",
    )
    assert remote == local, f"子进程输出与父进程不一致：\n父={local}\n子={remote}"


async def test_cross_process_determinism_ocr() -> None:
    """OCR 通道的跨进程一致性（字段值含中文，故同时验证编码链路不漂移）。"""
    local = _as_dict(
        await MockOcrProvider().recognize(
            image_key="cert/oss/2026/01/abc123.jpg", doc_type="BUSINESS_LICENSE", timeout_s=1.0
        )
    )
    remote = _subprocess_result(
        "recognize",
        image_key="cert/oss/2026/01/abc123.jpg",
        doc_type="BUSINESS_LICENSE",
        timeout_s="1.0",
    )
    assert remote == local, f"子进程输出与父进程不一致：\n父={local}\n子={remote}"


async def test_cross_process_determinism_vision() -> None:
    """视觉通道的跨进程一致性。"""
    local = _as_dict(
        await MockVisionProvider().analyze(image_key="k-cross", labels=["疑似过期"], timeout_s=1.0)
    )
    remote = _subprocess_result(
        "analyze",
        image_key="k-cross",
        labels=json.dumps(["疑似过期"], ensure_ascii=False),
        timeout_s="1.0",
    )
    assert remote == local, f"子进程输出与父进程不一致：\n父={local}\n子={remote}"


# ---------------------------------------------------------------------------
# 4. 可注入延迟（不真的等）
# ---------------------------------------------------------------------------


async def test_latency_is_requested_through_injected_sleep() -> None:
    """注入假 sleep：断言「收到了 0.25 秒的睡眠请求」，且墙钟耗时 < 0.1s（没有真等）。"""
    recorder = _SleepRecorder()
    provider = MockTextProvider(script=MockScript(latency_s=0.25), sleep=recorder)

    started = time.monotonic()
    result = await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    elapsed = time.monotonic() - started

    assert recorder.requests == [0.25], f"睡眠请求与脚本不符：{recorder.requests}"
    assert elapsed < 0.1, f"用例真的等了 {elapsed:.3f}s：延迟没有走注入的睡眠函数"
    assert isinstance(result, ProviderResult)


async def test_zero_latency_never_calls_sleep() -> None:
    """默认脚本（`latency_s=0.0`）MUST NOT 调用睡眠函数——否则每个离线用例都白等一轮。"""
    recorder = _SleepRecorder()
    await MockTextProvider(sleep=recorder).complete(prompt="p", payload={}, timeout_s=1.0)
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("provider_factory", "operation"),
    [
        (MockTextProvider, "complete"),
        (MockVisionProvider, "analyze"),
        (MockOcrProvider, "recognize"),
    ],
)
async def test_latency_above_timeout_raises_without_sleeping(
    provider_factory: Callable[..., Any], operation: str
) -> None:
    """`latency_s=10 > timeout_s=0.5` → 抛 `ProviderTimeoutError`（`code=5002`）且**不睡**。

    三个通道都参数化：超时护栏只在 TEXT 上实现是很容易漏的形态。
    """
    recorder = _SleepRecorder()
    provider = provider_factory(MockScript(latency_s=10.0), recorder)

    started = time.monotonic()
    with pytest.raises(ProviderTimeoutError) as excinfo:
        await _call_channel(provider, operation, timeout_s=0.5)
    elapsed = time.monotonic() - started

    assert excinfo.value.code == 5002
    assert excinfo.value.provider == MOCK_PROVIDER_NAME
    assert excinfo.value.operation == operation
    assert recorder.requests == [], (
        "超时路径不该请求睡眠：先睡满再返回会把「依赖劣化」伪装成「慢但成功」"
    )
    assert elapsed < 0.1, f"超时判定前真的等了 {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# 5. 三种故障形态
# ---------------------------------------------------------------------------


async def test_fault_timeout_raises_provider_timeout_error() -> None:
    """`kind="timeout"` → `ProviderTimeoutError`，`code == 5002`。"""
    provider = MockTextProvider(script=MockScript(fault=MockFault(kind="timeout")))
    with pytest.raises(ProviderTimeoutError) as excinfo:
        await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert excinfo.value.code == 5002
    assert excinfo.value.reason == "mock-timeout"
    assert excinfo.value.provider == MOCK_PROVIDER_NAME
    assert excinfo.value.operation == "complete"


async def test_fault_error_raises_channel_failure_error() -> None:
    """`kind="error"` → `ProviderChannelFailureError`，`code == 4003`。"""
    provider = MockTextProvider(script=MockScript(fault=MockFault(kind="error")))
    with pytest.raises(ProviderChannelFailureError) as excinfo:
        await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert excinfo.value.code == 4003
    assert excinfo.value.reason == "mock-error"
    assert excinfo.value.operation == "complete"


async def test_fault_empty_returns_normally_with_none_confidence() -> None:
    """`kind="empty"` → **正常返回**、载荷为空、`confidence is None`（**MUST NOT 是 0.0**）。"""
    provider = MockOcrProvider(script=MockScript(fault=MockFault(kind="empty")))
    result = await provider.recognize(image_key="k", doc_type="LICENSE", timeout_s=5.0)

    assert isinstance(result, ProviderResult)
    assert result.fields == ()
    assert result.confidence is None
    # `None` 与 `0.0` 的区分是 4.10 分级的前提，故正面断言一次（不写 `is not 0.0`：
    # 那是语法警告）。
    assert result.confidence != 0.0
    assert result.text is None
    assert result.markers is None


async def test_fault_empty_on_text_and_vision() -> None:
    """`empty` 在 TEXT / VISION 两个通道上的形态（空载荷 + `confidence=None`）。"""
    text = await MockTextProvider(script=MockScript(fault=MockFault(kind="empty"))).complete(
        prompt="p", payload={}, timeout_s=5.0
    )
    assert text.text == ""
    assert text.confidence is None

    vision = await MockVisionProvider(script=MockScript(fault=MockFault(kind="empty"))).analyze(
        image_key="k", labels=["疑似过期"], timeout_s=5.0
    )
    assert vision.markers == ()
    assert vision.confidence is None


def test_fault_on_call_must_be_at_least_one() -> None:
    """`on_call` 从 1 开始：`0` 在构造期失败，而不是变成一个永不生效的故障脚本。"""
    with pytest.raises(ValueError, match="on_call"):
        MockFault(kind="timeout", on_call=0)


# ---------------------------------------------------------------------------
# 6. `on_call` 语义与 `call_count`
# ---------------------------------------------------------------------------


async def test_fault_on_call_two_triggers_only_on_second_call() -> None:
    """`on_call=2` → 第 1 次正常、第 2 次抛、第 3 次正常。"""
    provider = MockTextProvider(script=MockScript(fault=MockFault(kind="timeout", on_call=2)))

    first = await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert isinstance(first, ProviderResult)

    with pytest.raises(ProviderTimeoutError) as excinfo:
        await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert excinfo.value.code == 5002

    third = await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert _as_dict(third) == _as_dict(first), "故障恢复后的产出与首次不一致"


async def test_fault_on_call_two_does_not_affect_third_and_beyond() -> None:
    """`on_call` 命中一次即过：第 4 次仍正常（故障不是「从此每次都触发」）。"""
    provider = MockOcrProvider(script=MockScript(fault=MockFault(kind="error", on_call=2)))
    await provider.recognize(image_key="k", doc_type="LICENSE", timeout_s=5.0)
    with pytest.raises(ProviderChannelFailureError):
        await provider.recognize(image_key="k", doc_type="LICENSE", timeout_s=5.0)
    for _ in range(2):
        result = await provider.recognize(image_key="k", doc_type="LICENSE", timeout_s=5.0)
        assert result.fields
    assert provider.call_count == 4


async def test_call_count_counts_faulty_calls_too() -> None:
    """调用 3 次后 `call_count == 3`；其中一次抛异常**也要**计数（§2.4）。"""
    provider = MockTextProvider(script=MockScript(fault=MockFault(kind="error", on_call=2)))
    assert provider.call_count == 0

    await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert provider.call_count == 1

    with pytest.raises(ProviderChannelFailureError):
        await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert provider.call_count == 2, "故障调用没有被计数：那 call_count 就变成「成功次数」了"

    await provider.complete(prompt="p", payload={}, timeout_s=5.0)
    assert provider.call_count == 3


async def test_call_count_is_per_instance() -> None:
    """计数在**同一个实例内**累计：新实例从 0 起（Task 4.9 的断言依赖这条口径）。"""
    first = MockOcrProvider()
    second = MockOcrProvider()
    await first.recognize(image_key="k", doc_type="LICENSE", timeout_s=1.0)
    assert first.call_count == 1
    assert second.call_count == 0


@pytest.mark.parametrize(
    ("provider_factory", "operation"),
    [
        (MockTextProvider, "complete"),
        (MockVisionProvider, "analyze"),
        (MockOcrProvider, "recognize"),
    ],
)
async def test_all_channels_expose_call_count_and_model_meta(
    provider_factory: Callable[..., Any], operation: str
) -> None:
    """三个类**都**要有 `call_count` 与 `model_meta()`（工单 §1 的「三个类都要有」）。"""
    provider = provider_factory()
    assert provider.call_count == 0
    await _call_channel(provider, operation, timeout_s=1.0)
    assert provider.call_count == 1
    assert set(provider.model_meta()) == _EXPECTED_MODEL_META_KEYS


# ---------------------------------------------------------------------------
# 7. 脱敏与契约域
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc_type", "image_key"),
    [
        ("BUSINESS_LICENSE", "cert/oss/2026/01/abc123.jpg"),
        ("LICENSE", "cert/oss/2026/02/def456.jpg"),
        ("INSPECTION_REPORT", "cert/oss/2026/03/ghi789.jpg"),
        ("UNRECOGNIZED_DOC", "cert/oss/2026/04/jkl012.jpg"),
    ],
)
async def test_ocr_field_values_are_masked(doc_type: str, image_key: str) -> None:
    """`value` MUST NOT 含连续 15 位以上数字；**凡是编号类字段** MUST 带脱敏标记。

    判据分两档，理由是「哪些值算『看起来像真实证件号』」这个问题有边界：

    1. **全体字段**：MUST NOT 出现连续 15 位以上数字（工单 §2.6 的可核方式）。
       这是「任何字段都不许是明文证件号」这条红线的直接形式。
    2. **编号类字段**（字段名含「编号」/「信用代码」）：MUST 带 `******` 形态的脱敏段。
       中文命名的非编号字段（名称 / 经营范围 / 检测结论 / 有效期至）不在此列——
       它们本就不是编号，其占位样例也不含需要保护的号码段。

    第 2 档同时兜住「新增了编号字段、脱敏逻辑没跟上」：第 1 档（15 位数字）在编号
    只有 10 位时抓不住，而星号要求抓得住。
    """
    result = await MockOcrProvider().recognize(
        image_key=image_key, doc_type=doc_type, timeout_s=1.0
    )
    fields = result.fields
    assert fields is not None and fields
    identifier_fields = 0
    for field in fields:
        assert not _LONG_DIGIT_RUN.search(field.value), (
            f"字段 {field.fieldName} 的值疑似明文证件号：{field.value!r}"
        )
        if _is_identifier_field(field.fieldName):
            identifier_fields += 1
            assert _MASK_RUN.search(field.value), (
                f"编号类字段 {field.fieldName} 的值没有脱敏段"
                f"（er.md §6.2 要求中间打星号）：{field.value!r}"
            )
    assert identifier_fields >= 1, (
        f"doc_type={doc_type} 没有任何编号类字段：第 2 档断言退化成空集，"
        f"脱敏形态实际上没被验过（字段={[f.fieldName for f in fields]}）"
    )


async def test_all_channel_outputs_contain_no_long_digit_run() -> None:
    """三通道产出的**所有文本值**都不含连续 15 位以上数字（§2.6 的逐通道口径）。"""
    results = [
        await MockTextProvider().complete(prompt="p", payload={"a": 1}, timeout_s=1.0),
        await MockVisionProvider().analyze(image_key="k", labels=["疑似过期"], timeout_s=1.0),
        await MockOcrProvider().recognize(image_key="k", doc_type="LICENSE", timeout_s=1.0),
    ]
    values = [value for result in results for value in _all_text_values(result)]
    assert values, "摊平后没有任何文本值：断言会退化成空集全绿"
    for value in values:
        assert not _LONG_DIGIT_RUN.search(value), f"产出里出现疑似明文：{value!r}"


async def test_all_confidences_are_within_contract_domain() -> None:
    """所有 `confidence` ∈ [0, 1] 或 `None`（`openapi.yaml:723-724` 的 min/max）。"""
    text = await MockTextProvider().complete(prompt="p", payload={}, timeout_s=1.0)
    vision = await MockVisionProvider().analyze(
        image_key="k", labels=["疑似过期", "卫生问题"], timeout_s=1.0
    )
    ocr = await MockOcrProvider().recognize(image_key="k", doc_type="LICENSE", timeout_s=1.0)

    candidates: list[float | None] = [text.confidence, vision.confidence, ocr.confidence]
    for marker in vision.markers or ():
        candidates.append(marker["confidence"])
    for field in ocr.fields or ():
        candidates.append(field.confidence)

    assert len(candidates) >= 6, f"置信度候选集过小（{len(candidates)}）：夹具可能没产出内容"
    for value in candidates:
        assert value is None or 0.0 <= value <= 1.0, f"置信度越界：{value!r}"


async def test_marker_level_agrees_with_its_own_confidence() -> None:
    """marker 的 `level` 与其**自身** `confidence` 一致（不是通道级那一个）。

    这条能抓住「level 取错对象」这类实现错：通道级 `confidence` 与 marker 级
    常常不等，用错字段时分级会整体偏移。
    """
    result = await MockVisionProvider().analyze(
        image_key="k", labels=["疑似过期", "卫生问题", "未穿工装"], timeout_s=1.0
    )
    markers = result.markers or ()
    assert markers
    for marker in markers:
        score = marker["confidence"]
        expected = "HIGH" if score >= 0.9 else "MEDIUM" if score >= 0.7 else "LOW"
        assert marker["level"] == expected, f"分级标注与置信度不符：{marker}"


async def test_identity_carries_provider_and_prompt_version() -> None:
    """三个通道的身份字段：`provider="mock"`、`prompt_version` 显式有值（`base.py` 收紧 2）。"""
    cases = (
        (
            await MockTextProvider().complete(prompt="p", payload={}, timeout_s=1.0),
            "TEXT",
            "mock-text-v1",
        ),
        (
            await MockVisionProvider().analyze(image_key="k", labels=["l"], timeout_s=1.0),
            "VISION",
            "mock-vision-v1",
        ),
        (
            await MockOcrProvider().recognize(image_key="k", doc_type="LICENSE", timeout_s=1.0),
            "OCR",
            "mock-ocr-v1",
        ),
    )
    for result, channel, model_version in cases:
        assert result.identity.provider == MOCK_PROVIDER_NAME
        assert result.identity.model_version == model_version
        assert result.identity.prompt_version == "mock-prompt-v1"
        assert result.identity.channel == channel
        assert result.lineage == result.identity


# ---------------------------------------------------------------------------
# 8. `model_meta()`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider_factory", "channel", "model_version"),
    [
        (MockTextProvider, "TEXT", "mock-text-v1"),
        (MockVisionProvider, "VISION", "mock-vision-v1"),
        (MockOcrProvider, "OCR", "mock-ocr-v1"),
    ],
)
def test_model_meta_matches_provider_identity(
    provider_factory: Callable[[], Any], channel: str, model_version: str
) -> None:
    """`model_meta()` 与 `ProviderIdentity.as_model_meta()` **逐键相等**。

    键集 MUST 恰为 `er.md` §6.1 的 5 个 camelCase 键。
    """
    expected = ProviderIdentity(
        channel=channel,  # type: ignore[arg-type] —— 参数化表里是字面量，运行期已由 CHANNELS 校验
        provider=MOCK_PROVIDER_NAME,
        model_version=model_version,
        prompt_version="mock-prompt-v1",
    ).as_model_meta()

    meta = provider_factory().model_meta()

    assert set(meta) == _EXPECTED_MODEL_META_KEYS
    assert meta == expected
    # 逐键相等还不够：键名本身必须是 camelCase（若实现手拼了 snake_case，
    # 而 as_model_meta 也被改成 snake_case，逐键相等会一起绿——这里钉住字面形状）。
    assert meta == {
        "channel": channel,
        "provider": "mock",
        "modelVersion": model_version,
        "promptVersion": "mock-prompt-v1",
        "thresholds": {},
    }


# ---------------------------------------------------------------------------
# 9. 零 socket（含判别力自证）
# ---------------------------------------------------------------------------


def test_socket_violations_has_discriminating_power(
    socket_violations: list[tuple[str, tuple[str, ...]]],
) -> None:
    """**判别力自证**：会话级「零建连」断言不是假绿。

    `tests/conftest.py` 的 `_session_socket_guard` 判据是**合取**
    （目标非环回 **且** 栈里有本项目帧），故本用例用**三组对照**证明它真的有判别力：

    - **实验组**：本项目代码连一个**对外**地址（`192.0.2.1` 是 RFC 5737 保留的
      TEST-NET-1 文档地址，**保留给文档与测试用、不可路由**，故绝不会真的连上任何服务）
      → 守卫**必须**记录它。这条同时证明判据两个条件都在生效；
    - **对照一（环回）**：本项目代码连环回 → **不**记录。这条把「判据是合取而不是
      "见 connect 就记"」钉住；若哪天有人把环回放行删掉，**全部 async 用例**都会
      因 self-pipe 而 ERROR（实测过：32 次误报，栈全指向守卫自己的转发帧）；
    - **对照二（构造）**：`socket.socket()` 的构造不建连 → 不记录。
      它把「记录被填充」与「碰到 socket 就记一笔」区分开。

    **清账**：实验组故意制造的那一条属"预期中的违规"，断言完即清；否则会话结束时
    那条断言会报一条预期中的 ERROR——预期中的红灯与真故障混在一起时，没人会再看红灯。
    """
    assert socket_violations == [], "本用例开始时账本已有记录，说明它是空的或前序用例没清账"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
        pass
    assert socket_violations == [], "仅仅构造 socket 就被记成建连：判据过宽"

    # 对照一：环回 MUST 放行（self-pipe 走这里，拦掉它会让全部 async 用例建不起事件循环）
    loopback = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            loopback.connect(("127.0.0.1", 1))
    finally:
        loopback.close()
    assert socket_violations == [], (
        f"环回建连被误判成违规：{socket_violations}——"
        f"这会让事件循环的 self-pipe 把全部 async 用例打成 ERROR"
    )

    # 实验组：对外地址 + 本项目栈 → 必须记录
    external = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            # 192.0.2.0/24 是 RFC 5737 的 TEST-NET-1：保留给文档与测试，不可路由。
            external.connect(("192.0.2.1", 9))
    finally:
        external.close()

    assert len(socket_violations) == 1, (
        f"本项目代码向对外地址发起 connect 后守卫没有记录到违规：{socket_violations}——"
        f"说明合取判据失效（判定退化成永真空集）"
    )
    target, frames = socket_violations[0]
    assert target == "('192.0.2.1', 9)"
    assert any("test_socket_violations_has_discriminating_power" in frame for frame in frames), (
        f"栈归因没有指向发起连接的那条用例：{frames}"
    )
    socket_violations.clear()


def test_socket_violations_does_not_flag_the_event_loop_self_pipe(
    socket_violations: list[tuple[str, tuple[str, ...]]],
) -> None:
    """对照组：事件循环自建 self-pipe 的 connect **不**算违规。

    这是把「一刀切禁止」改成「可归因」的那条依据的可执行形式：
    Windows 上 `asyncio.Runner` 建循环时必然发生一次**回环** connect
    （`_make_self_pipe` → `_fallback_socketpair`，见 `conftest.py` 里守卫的注释），
    若它被判成违规，所有 async 用例都会因为**与业务无关**的原因变红。
    """
    with asyncio.Runner() as runner:
        # 只为**触发事件循环建 self-pipe**（0 秒、不等待）；本用例的断言对象是那次 connect。
        runner.run(asyncio.sleep(0))  # ai-allow-sleep: 0 秒，用于触发 Proactor self-pipe

    assert socket_violations == [], (
        f"事件循环自建 self-pipe 被误判成违规：{socket_violations}"
    )


def test_module_does_not_import_network_libraries() -> None:
    """零网络依赖的**结构性**旁证：`mock.py` 源码里没有网络库的 import。

    与 `tests/conftest.py` 的 `_session_socket_guard` 的分工：那条管「运行期没建连」，
    这条管「源码里没有网络库」。
    两者都不是「拔网线」本身，但合起来覆盖了「离线可跑」的两个失效形态
    （偷偷 import / 偷偷连）。真正的断网执行由验收环境承担。
    """
    source = (SRC_DIR / "aicore" / "provider" / "mock.py").read_text(encoding="utf-8")
    assert len(source) > 1000, "读到的源码过短：路径可能已失效（断言会退化成空扫描）"
    for module in ("httpx", "requests", "aiohttp", "socket", "urllib"):
        pattern = rf"^\s*(?:import|from)\s+{module}\b"
        assert not re.search(pattern, source, re.MULTILINE), (
            f"provider/mock.py 出现了 {module} 的 import：违反 §2.8 的零网络依赖"
        )


# ---------------------------------------------------------------------------
# 10. Protocol 结构子类型
# ---------------------------------------------------------------------------


def test_provider_protocol_structural_subtyping() -> None:
    """三个 Mock 都满足对应 Protocol 的**成员存在性**检查。

    **这条的边界（MUST NOT 被当作「契约已验证」的唯一证据）**：
    `@runtime_checkable` 的 `isinstance` **只检查成员是否存在，不检查签名**。
    一个把 `complete(self, prompt, payload, timeout_s)` 写成位置参数的实现照样通过
    ——而 `base.py` 的三处调用点全部是关键字实参（`*,` 关键字限定）。
    签名一致性由 `mypy --strict` 保证（本模块在 `mypy --strict src` 的检查范围内），
    本用例只覆盖「成员漏了 / 改名了」这一档。
    """
    assert isinstance(MockTextProvider(), base.TextProvider)
    assert isinstance(MockVisionProvider(), base.VisionProvider)
    assert isinstance(MockOcrProvider(), base.OcrProvider)
    # 反向判别力：成员缺失时必须判否，否则上面三条不构成检查。
    assert not isinstance(object(), base.TextProvider)


async def test_text_provider_requires_keyword_arguments() -> None:
    """`complete` 的关键字限定是可核的：位置实参会直接 `TypeError`。

    这条补上 `isinstance` 覆盖不到的那一档（签名）。`mypy` 在运行期不参与，
    故签名一致性的**运行期**证据只有这一类调用形状断言。
    """
    with pytest.raises(TypeError):
        await MockTextProvider().complete("p", {}, 1.0)  # type: ignore[misc]


async def test_vision_and_ocr_require_keyword_arguments() -> None:
    """`analyze` / `recognize` 同样关键字限定。"""
    with pytest.raises(TypeError):
        await MockVisionProvider().analyze("k", ["l"], 1.0)  # type: ignore[misc]
    with pytest.raises(TypeError):
        await MockOcrProvider().recognize("k", "LICENSE", 1.0)  # type: ignore[misc]
