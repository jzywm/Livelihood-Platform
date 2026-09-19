"""确定性 Mock 通道（离线测试与降级演练）。第 4 组实现（Task 4.2）。

本模块实现 `provider/base.py` 的三个 Protocol（`TextProvider` / `VisionProvider` /
`OcrProvider`），是 design.md D3 定档的**开发 / 测试默认通道**：

- **确定性、可离线**：产出只由入参派生，零延迟、零故障、零网络；
- **可注入延迟与故障**（tasks.md:38）：`MockScript` 描述延迟与故障脚本，供超时链路
  （Task 4.3）与降级链路（Task 4.11）在离线侧演练；
- **prod 禁用**：由 `core/config.py` 的启动校验拒绝（`env=prod` 且选中 `mock` 时
  进程拒绝启动），本模块自身**不做**环境判断——通道实现不该知道自己在哪个环境里跑，
  否则「谁在什么环境下允许降级」会散落到每个通道里。

## 确定性：为什么用 `hashlib` 而**不是** `hash()`

三个方法的返回值 MUST 由**入参的稳定哈希**派生。这里逐字记下那个最容易踩的坑：

**`hash()` 对 `str` / `bytes` 带 `PYTHONHASHSEED` 随机化，跨进程不稳定。**
用它写 Mock 会让「确定性」在**同一个 pytest 进程内看起来完全成立**（同进程内哈希种子
固定，连调三次必相等），而在**跨进程**时静默失效——pytest-xdist 分片、子进程复算、
CI 上两个不同的 runner 比对评估集产物，都会得到不同的「确定性」输出。
那种失败最难查：本地全绿，CI 上的对照断言红。

故本模块只用 `hashlib.sha256`（stdlib，无网络、无密钥、无随机源），对**规范化后的入参**
（`json.dumps(..., sort_keys=True, default=repr)`）取 hex，再按需切片构造文本 / 字段值。
`json.dumps` 的 `sort_keys=True` 顺带堵住另一个不稳定来源：`Mapping` 的遍历顺序。

`call_count` **刻意不参与派生**：否则「同输入同输出」会退化成「同输入 + 同调用序号同输出」，
重试、幂等复用（Task 4.9）这些真实场景下就再也拿不到同一份结果了。计数器只服务一件事——
判定第几次调用该触发故障。

## 契约域与脱敏（两条都是硬约束）

- `confidence` MUST 落在 `[0.0, 1.0]`（`openapi.yaml` 的 `minimum: 0` / `maximum: 1`），
  或为 `None`（`None` 与 `0.0` 语义不同，见 `results.py` 模块 docstring：后者会被
  Task 4.10 判成 `LOW` 并误触人工复核）。本模块产出的置信度统一收在 `[0.70, 0.99]`：
  既不越界，也不去踩分级边界，避免 Mock 的产物让 4.10 的边界用例假通过。
- 值 MUST **已脱敏**：`er.md` §6.2 逐字要求 `fields_json` 的 `value` 是「识别值（脱敏输出）」，
  `openapi.yaml:719` 的示例是 `911301********1234`。Mock 是 dev/test 的默认通道，
  它的输出会被写进 `ocr_result.fields_json`、进日志、进评估集——今天用假明文，
  明天就会有人把「反正只是 Mock」的样本导进评估集。故本模块的所有字段值都是
  **中间打星号**的形态，MUST NOT 出现 15 位以上连续数字。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from aicore.provider.errors import ProviderChannelFailureError, ProviderTimeoutError
from aicore.provider.results import OcrField, ProviderIdentity, ProviderResult

__all__ = [
    "MOCK_PROVIDER_NAME",
    "MockFault",
    "MockOcrProvider",
    "MockScript",
    "MockTextProvider",
    "MockVisionProvider",
]

#: 通道实现名。落 `model_meta.provider`（`er.md` §6.1）。
MOCK_PROVIDER_NAME: str = "mock"

#: 睡眠函数签名：`latency_s > 0` 时由实现调用。
#:
#: 注入点是**构造参数**而非类属性替换：测试用假 sleep（记录请求后立刻返回）断言
#: 「收到了 0.25 秒的睡眠请求」，而 `tests/conftest.py` 的约定是「测试内 MUST NOT
#: 出现任意 sleep；等待一律走轮询断言或注入的时钟」——替换全局的 `asyncio.sleep`
#: 会污染其他并行的 await 点，注入实例自己的函数则影响面只有本通道。
type SleepFn = Callable[[float], Awaitable[None]]

#: 三个通道的 Prompt 版本。三者共用一个版本号是刻意的：Mock 没有真实模板，
#: 但血缘字段 MUST 有值（`base.py` 的收紧 2），用同一个「不适用但显式」的字面量
#: 比留空串更能表达「这是 Mock，没有可迭代的 prompt」。
_MOCK_PROMPT_VERSION: str = "mock-prompt-v1"

#: 纯密码学哈希的十六进制长度（sha256 = 64 个 hex 字符）。所有切片都从它出发。
_DIGEST_HEX_LEN: int = 64

#: `OcrField.value` 的脱敏后缀长度与掩码字符：`中间打星号`（如 `91330100********1234`）。
_MASK_CHAR: str = "*"

#: 各通道产出置信度的取值区间 `[下界, 上界]`。
#: 上界 0.99 而不是 1.0：`1.0` 是「绝对确定」，Mock 不该伪造这种断言强度。
#: 下界 0.70 而不是 0.0：避开 Task 4.10 的 `LOW < 0.7` 边界，使 Mock 的产物
#: 不会让 4.10 的边界用例因为「样本本身就踩线」而真假不分。
_CONFIDENCE_SCALE: float = 0.29
_CONFIDENCE_FLOOR: float = 0.70


def _canonical_args(**kwargs: Any) -> str:
    """把入参规范化成**跨进程稳定**的字符串，作为哈希输入。

    `sort_keys=True` 堵 `Mapping` 顺序；`default=repr` 兜住不可 JSON 化的值
    （`repr` 对同一对象在同版本解释器内是稳定的，且比 `str()` 更少歧义）；
    `ensure_ascii=True`（默认）使中文入参归一为 `\\uXXXX` 转义——字节层面的稳定，
    不依赖终端编码或 `PYTHONUTF8`，于是「同输入」在 Windows 与 Linux 上同样成立。
    """
    return json.dumps(kwargs, sort_keys=True, default=repr, separators=(",", ":"))


def _digest(**kwargs: Any) -> str:
    """入参的 sha256 十六进制摘要（跨进程、跨平台、跨 `PYTHONHASHSEED` 稳定）。"""
    return hashlib.sha256(_canonical_args(**kwargs).encode("utf-8")).hexdigest()


def _chunk(digest: str, index: int) -> int:
    """从摘要里取第 `index` 个 16 位无符号分片（`0..65535`）。

    分片从摘要**尾部**往前取：前 52 个 hex 字符留给需要任意长度的载荷文本，
    尾部 12 个字符（3 个分片）留给数值参数，两块互不重叠——否则「文本长度一变，
    置信度跟着变」这类隐性耦合会让人误以为是随机。
    """
    start = _DIGEST_HEX_LEN - (index + 1) * 4
    return int(digest[start : start + 4], 16)


def _confidence(chunk: int) -> float:
    """把 16 位分片映射到 `[_CONFIDENCE_FLOOR, 1.0)` 内的置信度。

    用整数分片而不是 `random`：`random` 需要播种，而播种就要有种子来源
    （时间 / 熵池），那正是确定性要掐掉的东西。先 `round(…, 4)` 再截断到
    `[0.0, 1.0]`：浮点乘法在极端分片下仍可能溢出上界，截断是兜底而非修饰。
    """
    value = _CONFIDENCE_FLOOR + _CONFIDENCE_SCALE * (chunk / 0xFFFF)
    return min(1.0, max(0.0, round(value, 4)))


@dataclass(frozen=True, slots=True)
class MockFault:
    """注入的故障。三者互斥（同时为真时按 kind 优先级取第一个命中的，见 §2.4）。

    `kind` 的三种取值各自的**异常/返回**（逐字对应工单 §2.3 的表）：

    | `kind` | 行为 | 调用方可核点 |
    |---|---|---|
    | `timeout` | 抛 `ProviderTimeoutError`（`reason="mock-timeout"`） | `exc.code == 5002` |
    | `error` | 抛 `ProviderChannelFailureError`（`reason="mock-error"`） | `exc.code == 4003` |
    | `empty` | **正常返回**，载荷为空且 `confidence=None` | 不抛异常；`confidence is None` |

    「`empty` 的 `confidence` MUST 是 `None` 而不是 `0.0`」见 `results.py` 模块 docstring：
    `0.0` 会被 Task 4.10 判成 `LOW` 并误触人工复核，那是造假数据而不是兜底。

    「`empty` 不是异常」是刻意的：`base.py` 要求「失败 MUST 抛异常，MUST NOT 返回空结果」，
    而 `empty` 表达的是**通道成功返回但无可识别内容**（空图、白图、模板未命中）——
    这是 4.5/5.5「图像不可辨识 → 转人工」链路要演练的形态，不是通道故障。
    把它做成异常会让「转人工」的两条不同成因（通道坏了 / 图看不清）在代码里不可分。
    """

    kind: Literal["timeout", "error", "empty"]
    #: 命中第几次调用时触发（从 1 开始）。默认 1 = 首次即触发。
    on_call: int = 1

    def __post_init__(self) -> None:
        """`on_call` 必须 >= 1（从 1 开始计数，见 §2.4）。

        构造期失败而非运行期静默跳过：`on_call=0` 的直觉含义是「永不触发」，
        但那样写出的是一个**永远不生效的故障脚本**——演练会变成一场空跑，
        而调用方还以为降级链路被测过了。
        """
        if self.on_call < 1:
            raise ValueError(
                f"MockFault.on_call 从 1 开始计数，收到 {self.on_call}："
                f"要走『永不触发』请直接把 fault 留成 None，"
                f"否则会得到一个永远不生效的故障脚本（演练空跑）"
            )


@dataclass(frozen=True, slots=True)
class MockScript:
    """Mock 的行为脚本。**默认值 = 完全确定性、零延迟、零故障**。

    默认值即「离线契约测试」要的形态：不注入任何东西时，同输入必然同输出，
    且调用方不需要为「等多久」做任何假设。

    `latency_s > timeout_s` 时实现 MUST 抛 `ProviderTimeoutError`（**不是**睡完再返回）：
    这是 Task 4.3「超时」链路在离线侧的可测形态。先睡满再返回等于把「依赖劣化」
    伪装成「慢但成功」，运维看到的 P99 会好看，而真实链路早已熔断。
    """

    latency_s: float = 0.0
    fault: MockFault | None = None


# ---------------------------------------------------------------------------
# OCR 字段模板
#
# 字段名取自 `openapi.yaml:714` 的说明（「统一社会信用代码/名称/法定代表人/有效期至/
# 经营范围等」）与 `DocType` 枚举（`BUSINESS_LICENSE` / 许可证 / 检测报告）。
# 值一律是**脱敏形态**，见 `_masked_value`。
# ---------------------------------------------------------------------------

#: 文档类型 → 字段名模板。未列出的类型走 `_UNKNOWN_DOC_FIELD_NAMES`。
#:
#: 为什么按 `doc_type` 换一套字段而不是恒定返回同一组：Mock 是 Task 5.3「三类证照
#: 字段提取」在离线侧的替身，若它只看 `image_key` 而不看 `doc_type`，那条用例
#: 断言不了「不同证照提取不同字段」这件事，等于把被测行为偷偷替换成了常量。
_DOC_FIELD_NAMES: Mapping[str, tuple[str, ...]] = {
    "BUSINESS_LICENSE": (
        "统一社会信用代码",
        "名称",
        "法定代表人",
        "有效期至",
        "经营范围",
    ),
    "LICENSE": (
        "许可证编号",
        "持证单位",
        "法定代表人",
        "有效期至",
        "许可范围",
        "发证机关",
    ),
    "INSPECTION_REPORT": (
        "报告编号",
        "受检单位",
        "样品名称",
        "检测项目",
        "检测结论",
        "报告日期",
    ),
}

#: 未在模板表里的文档类型：返回**通用**字段集而不是空集。
#:
#: 返回空集看着更"严格"，但它会让调用方无法区分「Mock 不认识这个 doc_type」
#: 与「通道返回了空结果」——前者是 Mock 的能力边界（应显式可见），后者是
#: `MockFault(kind="empty")` 要演练的形态。两者混在一个形态里，演练就没有判据了。
_UNKNOWN_DOC_FIELD_NAMES: tuple[str, ...] = ("文档编号", "主体名称", "有效期至")

#: 脱敏字段值用的确定性素材池（按摘要分片取值，不用随机）。
#: 素材本身都是**编造**的占位内容，不含任何真实主体信息。
_NAME_SUFFIXES: tuple[str, ...] = ("示例商贸", "示例供应链", "示例食品", "示例检测")
_NAME_SUFFIX_TAIL: str = "有限公司"
_REGIONS: tuple[str, ...] = ("110108", "310115", "330106", "440305")
_LEGAL_REPRESENTATIVES: tuple[str, ...] = ("张", "李", "王", "赵")
_SCOPE_ITEMS: tuple[str, ...] = (
    "食品销售",
    "餐饮服务",
    "日用百货零售",
    "农副产品收购",
)
_ISSUERS: tuple[str, ...] = ("示例市市场监督管理局", "示例区市场监督管理局")

#: 文本通道产出的句式模板。
_TEXT_TEMPLATES: tuple[str, ...] = (
    "已按确定性规则处理该请求，结论见 payload 字段数 {n}。",
    "该请求已由离线通道确定性应答，入参字段数 {n}。",
)


def _masked_value(field_name: str, digest: str) -> str:
    """按字段名生成一个**已脱敏**的确定性值。

    形态对齐 `openapi.yaml:719` 的 `911301********1234`：**首尾可见、中间打星号**。
    星号段是刻意保留的——它是「这是脱敏输出」在数据里的可核标记；把整个值换成
    `***` 会让「脱敏了」与「识别失败」在库表里长得一样。

    `fieldName` 未命中任何已知字段时返回 `_UNKNOWN_DOC_FIELD_NAMES` 风格的通号值，
    **不返回空串**（`OcrField.value` 非空是契约域要求，见工单 §2.5）。
    """
    if "信用代码" in field_name or "编号" in field_name:
        # 统一社会信用代码的形态：4 位登记管理部门/机构类别码 + 6 位行政区划
        # + 9 位主体标识 + 1 位校验码，共 18 位。这里首 8 位可见、末 4 位可见、
        # 中间 6 位打星号 —— 与 openapi.yaml 的示例同构，且**任何连续数字段都不超过 10 位**。
        region = _REGIONS[_chunk(digest, 1) % len(_REGIONS)]
        head = f"{region}{_chunk(digest, 2) % 100:02d}"
        tail = f"{_chunk(digest, 3) % 10000:04d}"
        return f"{head}{_MASK_CHAR * 6}{tail}"
    if "法定代表人" in field_name:
        # 人名脱敏：只留姓氏，其余打星号（个保法口径下姓名属个人信息）。
        return f"{_LEGAL_REPRESENTATIVES[_chunk(digest, 1) % len(_LEGAL_REPRESENTATIVES)]}**"
    if "有效期至" in field_name or "报告日期" in field_name:
        # 固定未来区间内的日期，仅月日由摘要派生：不取 `date.today()`——那会让
        # 「同输入同输出」在跨天之后失效，是最隐蔽的一类不确定性。
        month = _chunk(digest, 2) % 12 + 1
        day = _chunk(digest, 3) % 28 + 1
        return f"20{_chunk(digest, 1) % 3 + 26:02d}-{month:02d}-{day:02d}"
    if "经营范围" in field_name or "许可范围" in field_name:
        first = _SCOPE_ITEMS[_chunk(digest, 2) % len(_SCOPE_ITEMS)]
        second = _SCOPE_ITEMS[(_chunk(digest, 3) + 1) % len(_SCOPE_ITEMS)]
        return f"{first}；{second}（依法须经批准的项目除外）"
    if "发证机关" in field_name:
        return _ISSUERS[_chunk(digest, 1) % len(_ISSUERS)]
    if "名称" in field_name or "单位" in field_name or "主体" in field_name:
        suffix = _NAME_SUFFIXES[_chunk(digest, 1) % len(_NAME_SUFFIXES)]
        return f"示例市{suffix}{_NAME_SUFFIX_TAIL}"
    if "检测项目" in field_name:
        return "微生物指标；理化指标"
    if "检测结论" in field_name:
        return "所检项目符合示例标准要求"
    if "样品名称" in field_name:
        return "示例样品（占位）"
    # 兜底：形态上仍是「中间打星号」的脱敏值，绝不回退成明文或空串。
    return f"占位{_MASK_CHAR * 4}{_chunk(digest, 3) % 100:02d}"


class _MockProviderBase:
    """三个 Mock 通道的公共部分：脚本、睡眠函数、调用计数。

    **为什么抽一个基类而不是各写一遍**：`call_count` / `latency_s` 超时判定 /
    `on_call` 判定是三处**同一份**逻辑（工单 §2.2 / §2.4），复制三遍迟早分叉——
    而这三个通道的契约用例是同一套，分叉会在「某个通道的计数语义与另两个不同」
    这种最难察觉的地方显形。

    但**它 MUST NOT 被当作实现基类对外暴露**：`base.py` 定的是结构子类型，
    `TextProvider` 等 Protocol **不继承**本类。保留三个类各自独立的 `name` /
    `model_version` / `prompt_version` 与 `model_meta()`，使
    `isinstance(obj, TextProvider)` 检查的仍是三个类自己的成员，而不是借来的。
    """

    #: 通道实现名（三通道共用 `mock`）；子类各自重声明，便于静态可读。
    name: str = MOCK_PROVIDER_NAME
    model_version: str = "mock-text-v1"
    prompt_version: str = _MOCK_PROMPT_VERSION
    #: 本通道的类别，供 `model_meta()` 委托 `ProviderIdentity.as_model_meta()` 时使用。
    channel: Literal["TEXT", "VISION", "OCR"] = "TEXT"

    def __init__(
        self,
        script: MockScript | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        """构造通道。

        `sleep` 是**可替换的睡眠函数**（默认 `asyncio.sleep`）：测试注入一个记录调用的
        假 sleep，就能断言「收到了 0.25 秒的睡眠请求」而**没有真的等**
        （`tests/conftest.py`：「测试内 MUST NOT 出现任意 sleep」）。
        """
        self._script: MockScript = script if script is not None else MockScript()
        self._sleep: SleepFn = sleep if sleep is not None else asyncio.sleep
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        """本实例已受理的调用次数（从 0 起，每次调用 +1，**故障调用也计数**）。

        供 Task 4.9 断言「幂等重提时 Provider 调用次数不增加」：
        计数必须是「通道被真正调用了几次」的事实，而不是「成功了几次」。
        """
        return self._call_count

    def model_meta(self) -> dict[str, Any]:
        """渲染 `er.md` §6.1 的 `ai_task.model_meta`。

        **直接委托 `ProviderIdentity.as_model_meta()`**，MUST NOT 在本文件里手拼 dict：
        键名是跨文档契约（`channel` / `provider` / `modelVersion` / `promptVersion` /
        `thresholds`），手拼一份就等于把这个契约复制出第二个副本，两份迟早分叉
        （`base.py` 的同名方法 docstring 逐字要求「实现应直接委托」）。
        """
        return ProviderIdentity(
            channel=self.channel,
            provider=self.name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        ).as_model_meta()

    async def _enter(self, operation: str, timeout_s: float) -> None:
        """每次调用进入时的统一前置：计数 → 超时判定 → 延迟 → 故障判定。

        四条次序是刻意的，交换任意两条都会改变可观测语义：

        1. **先计数**：故障调用也计数（工单 §2.4）。放到故障判定之后，第 2 次
           （触发故障那次）就不会被计入，`call_count` 会变成「成功次数」，
           而 4.9 的幂等断言恰恰要求它是「调用次数」。
        2. **再判超时**：`latency_s > timeout_s` 时抛 `ProviderTimeoutError`，
           **不睡**。先睡再抛会让离线演练白白耗掉真实秒数，且把「超时」的
           可观测点从「立刻报错」挪到「等满才报错」，与真实护栏的形态相反。
        3. **再睡**（此时已确定睡得完）：延迟经注入的睡眠函数，测试可零成本断言。
        4. **最后判故障**：`on_call` 命中才触发。`empty` 由调用方处理成
           「正常返回但载荷为空」，故这里只抛前两类。
        """
        self._call_count += 1
        if self._script.latency_s > timeout_s:
            raise ProviderTimeoutError(
                provider=self.name,
                operation=operation,
                reason="mock-timeout",
            )
        if self._script.latency_s > 0:
            await self._sleep(self._script.latency_s)
        fault = self._script.fault
        if fault is None or fault.on_call != self._call_count:
            return
        if fault.kind == "timeout":
            raise ProviderTimeoutError(
                provider=self.name,
                operation=operation,
                reason="mock-timeout",
            )
        if fault.kind == "error":
            raise ProviderChannelFailureError(
                provider=self.name,
                operation=operation,
                reason="mock-error",
            )
        # kind == "empty"：不是异常。载荷由调用方的 `_empty_*` 分支给出（见 MockFault docstring）。

    def _is_empty_call(self) -> bool:
        """本次调用是否命中 `empty` 故障（决定载荷取空还是取实）。"""
        fault = self._script.fault
        return fault is not None and fault.kind == "empty" and fault.on_call == self._call_count

    def _identity(self) -> ProviderIdentity:
        """本通道的血缘（`thresholds` 走默认空字典：Mock 不做置信度分级）。"""
        return ProviderIdentity(
            channel=self.channel,
            provider=self.name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )


class MockTextProvider(_MockProviderBase):
    """文本通道的确定性 Mock（`TextProvider` 结构子类型）。"""

    model_version: str = "mock-text-v1"
    channel: Literal["TEXT", "VISION", "OCR"] = "TEXT"

    async def complete(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> ProviderResult:
        """文本补全。载荷只填 `text`，`markers` / `fields` 恒为 `None`。

        `empty` 故障命中时 `text=""`（**空串而非 `None`**）：TEXT 通道没有「无载荷」
        的表达形式，空串是它的空值形态；`confidence` 则必须是 `None`（**MUST NOT 是 0.0**，
        见 `results.py` 模块 docstring）。
        """
        await self._enter("complete", timeout_s)
        if self._is_empty_call():
            return ProviderResult(identity=self._identity(), text="", confidence=None)
        digest = _digest(prompt=prompt, payload=dict(payload))
        template = _TEXT_TEMPLATES[_chunk(digest, 0) % len(_TEXT_TEMPLATES)]
        body = template.format(n=len(payload))
        return ProviderResult(
            identity=self._identity(),
            text=f"{body}[{digest[:12]}]",
            confidence=_confidence(_chunk(digest, 1)),
        )


class MockVisionProvider(_MockProviderBase):
    """视觉通道的确定性 Mock（`VisionProvider` 结构子类型）。"""

    model_version: str = "mock-vision-v1"
    channel: Literal["TEXT", "VISION", "OCR"] = "VISION"

    async def analyze(
        self,
        *,
        image_key: str,
        labels: list[str],
        timeout_s: float,
    ) -> ProviderResult:
        """按 `labels` 检测标记。载荷只填 `markers`，`text` / `fields` 恒为 `None`。

        **每个 `label` 产出一条 marker**（键名对齐 `openapi.yaml:945-992` 的
        `VisionMarker`：`label` / `level` / `confidence` / `bbox`）。条数由入参决定
        而不是常量：调用方断言「传 3 个标签拿到 3 条标记」才有意义。

        `labels` 为空时 `markers=()` 空元组 + `confidence=None`——与 `empty` 故障
        同一形态，因为两者对调用方的语义相同：**没有检出任何标记**。
        """
        await self._enter("analyze", timeout_s)
        if self._is_empty_call() or not labels:
            return ProviderResult(identity=self._identity(), markers=(), confidence=None)
        digest = _digest(image_key=image_key, labels=list(labels))
        markers: list[Mapping[str, Any]] = []
        for index, label in enumerate(labels):
            score = _confidence(_chunk(digest, index % 3))
            markers.append(
                {
                    "label": label,
                    "level": _level_for(score),
                    "confidence": score,
                    "bbox": _bbox(digest, index),
                }
            )
        return ProviderResult(
            identity=self._identity(),
            markers=tuple(markers),
            confidence=_confidence(_chunk(digest, 0)),
        )


class MockOcrProvider(_MockProviderBase):
    """OCR 通道的确定性 Mock（`OcrProvider` 结构子类型）。"""

    model_version: str = "mock-ocr-v1"
    channel: Literal["TEXT", "VISION", "OCR"] = "OCR"

    async def recognize(
        self,
        *,
        image_key: str,
        doc_type: str,
        timeout_s: float,
    ) -> ProviderResult:
        """识别证照，返回**已脱敏**的结构化字段。载荷只填 `fields`。

        `empty` 故障命中时返回**空元组**而不是 `None`：`fields` 是 OCR 结果的主要载荷，
        契约上它是 `tuple[OcrField, ...]`；用 `None` 表达「空」会让调用方为「无载荷」
        与「空结果」写两个分支，而两者对下游（转人工）是同一件事。
        """
        await self._enter("recognize", timeout_s)
        if self._is_empty_call():
            return ProviderResult(identity=self._identity(), fields=(), confidence=None)
        digest = _digest(image_key=image_key, doc_type=doc_type)
        names = _DOC_FIELD_NAMES.get(doc_type, _UNKNOWN_DOC_FIELD_NAMES)
        fields = tuple(
            OcrField(
                fieldName=name,
                value=_masked_value(name, digest),
                confidence=_confidence(_chunk(digest, index % 3)),
            )
            for index, name in enumerate(names)
        )
        return ProviderResult(
            identity=self._identity(),
            fields=fields,
            confidence=_confidence(_chunk(digest, 0)),
        )


#: 置信度分级名（`openapi.yaml:853-857` 的 `ConfidenceLevel`）。
#: 分级阈值（高 ≥0.9 / 中 0.7~0.9 / 低 <0.7）的**唯一权威**在 Task 4.10，
#: 本模块只按它把 marker 的 `level` 标注出来，MUST NOT 另立一套阈值表。
_CONFIDENCE_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")

#: 分级边界（含下界）：`HIGH` 的下界与 `MEDIUM` 的下界。
#: 与 `openapi.yaml:855` 的「高 ≥0.9 / 中 0.7~0.9 / 低 <0.7」逐字对应。
_HIGH_MIN: float = 0.9
_MEDIUM_MIN: float = 0.7


def _level_for(score: float) -> str:
    """按 Task 4.10 的阈值把置信度标成 `HIGH` / `MEDIUM` / `LOW`。

    **写成显式分支而不是索引算式**：`("LOW","MEDIUM","HIGH")[int(>=0.9) - int(<0.7)]`
    这类"聪明"写法在这里是错的——`0.84` 会算出 `0 - 0 = 0` 而落到 `LOW`，
    而它明明是 `MEDIUM`。分级错标的后果不是显示问题：4.10 用它决定是否转人工复核，
    把 `MEDIUM` 说成 `LOW` 会让复核队列被无关样本淹没。
    """
    if score >= _HIGH_MIN:
        return _CONFIDENCE_LEVELS[2]
    if score >= _MEDIUM_MIN:
        return _CONFIDENCE_LEVELS[1]
    return _CONFIDENCE_LEVELS[0]


def _bbox(digest: str, index: int) -> Mapping[str, float]:
    """归一化位置框（`openapi.yaml` 的 `VisionMarker.bbox`：4 个 0~1 的浮点数）。

    纯装饰性字段：Mock 没有图像可检测，但**漏掉它会让「marker 键名与文档一致」
    这条验收永久无法在离线侧取证**（4.x 的视觉链路消费 `bbox` 做前端框选）。
    """
    base = _chunk(digest, index % 3)
    return {
        "x": round((base % 50) / 100, 2),
        "y": round(((base // 50) % 50) / 100, 2),
        "width": round(((base % 30) + 10) / 100, 2),
        "height": round((((base // 30) % 30) + 10) / 100, 2),
    }
