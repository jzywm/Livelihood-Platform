"""Provider 选择器（Task 4.4）：按配置把三个通道槽位装配出来。

`main.py` 组合根的唯一入口是 `select_providers(config)`——它把 `Settings.provider`
这**一个**字面量翻译成 `Providers`（TEXT / VISION / OCR 三个槽位）。

## 选择矩阵（`None` 的格子是本任务的核心，MUST NOT 被"优化"掉）

| `config.provider` | TEXT | VISION | OCR |
|---|---|---|---|
| `mock` | `MockTextProvider` | `MockVisionProvider` | `MockOcrProvider` |
| `deepseek` | `DeepSeekTextProvider` | `None` | `None` |
| `cloud_vision` | `None` | `CloudVisionProvider` | `None` |
| `cloud_ocr` | `None` | `None` | `CloudOcrProvider` |

`mock` 是**唯一**覆盖三个槽位的 provider：`design.md:54/:142` 与 `tasks.md:37` 只定义
3 个 Protocol，spec.md:11 的「四类通道」里的「平台自建预测」在 M1 没有实现
（`design.md:26` 逐字「不实现 K-03/K-04/K-05/K-06 的业务逻辑（只保留任务类型枚举与
通道路由扩展位）」，`results.py` 的 `Channel` 因此只有 3 个成员）。

### 为什么选不中的通道返回 `None`，**MUST NOT 回落到 `mock`**

在 `provider=cloud_ocr` 的部署里悄悄给 VISION 槽位塞一个 mock，意味着**生产上视觉审核
的结论会来自模拟实现**——正是 `design.md:56` 说的「生产环境自动降级 Mock 会造成更严重的
合规事故（等于用假数据伪造 AI 结论并进入人工复核）」。故本模块**不回落**：调用方拿到
`None` 时必须自己决定（报 `4003` 转人工，或该任务类型根本不该在这个部署形态下跑）。
这条与本项目「宁可拒绝也不静默降级」的既有取向一致（同 `core/config.py` 的
`mysql_readonly_host` 只认 `None` 的做法）。

反过来，`None` 是**可断言的部署事实**：它让「这个部署里视觉链路不可用」在装配期就看得见，
而不是等到第一次视觉调用时临时编一个结论。

## 与启动校验（Task 2.2）的分工

`env=prod` + `provider=mock` 与「真实通道缺密钥」两类组合**已在 `Settings` 构造期被
`_reject_invalid_startup_combination` 拒绝**，故本模块 MUST NOT 重复实现这两条判断
（重复实现会造出第二套会漂移的口径）。

本模块只补一件 `Settings` 管不到的事：**被选中通道的凭据为空时 fail fast**——
`provider=deepseek` 且 `deepseek_api_key` 为 `None` / 空串 / 纯空白时抛 `ValueError`。
**刻意不是 `ProviderChannelFailureError`**：这属**装配期配置错误**，应当在启动 / 装配阶段
炸掉，而不是伪装成一次「通道调用失败」让任务转人工（那会把一个配置错误变成一条
无人复核的业务任务）。空白判定走 `core/config.py` 的**公开** `is_blank` 同一实现，口径只有一处。

> **控制者裁定（Task 4.4 收尾）**：本模块原先 `from aicore.core.config import _is_blank`，
> 即**跨模块 import 私有名**——mypy 不拦、ruff 不拦、用例也不拦，但它是「口径只有一处」
> 这句话的唯一支撑。已由控制者把 `core/config.py` 的该函数公开为 `is_blank`
> （保留 `_is_blank` 作别名，不产生第二份函数体），本模块改用公开名。

`cloud_vision` / `cloud_ocr` 的凭据字段**当前不存在**（`_REAL_PROVIDERS_WITHOUT_KEY_FIELD`
逐字标注），故本模块 MUST NOT 为它们凭空查一个不存在的字段——查了会 `AttributeError`。
它们的合规门由通道实现内部承担（`cloud_*.py` 的 `COMPLIANCE_READY = False`，Task 4.3 已交付），
选择器只负责把它们选出来。

## 不读任何业务参数

选择是**纯函数式**的：只读 `config`，签名里根本没有 `account_id` / `task_id` /
`merchant_id` / `doc_type` / `image_key` / `request` / `headers` / `trace_id` / `idem_key`
这些名字（任务级信息属 Task 4.6 的任务处理器，不属于装配）。
`tests/unit/test_provider_selector.py` 用「签名参数名集合」+ AST 标识符扫描两层把它钉住。

## 护栏参数的唯一来源

四项护栏参数经 `guard.guard_config_from(config)` 映射后传给真实通道。
**MUST NOT 在本文件写死任何护栏数值**：那样「超时可配」（Task 4.6 要求处理器声明自身超时、
Task 4.11 要求降级可观测）就只是一句话。

**本文件的证据边界（P 阶段独立评审 N6 的修正，如实登记）**：这句话原先接的是
「用例把 `httpx.MockTransport` 的 handler 计入请求数，用它反推『重试次数确实来自配置』」——
**而那条用例不存在**。`test_provider_selector.py` 对 `provider_max_retries` 只有
**等值断言**（读通道持有的 `GuardConfig` 比字段），没有行为断言。
文件名与真实覆盖范围的对照如下，MUST NOT 被读成「行为已验证」：

| 护栏参数 | 本文件的验证方式 |
|---|---|
| `ai_call_timeout_s` | 行为断言：handler 真挂 10s，断言 <1.0s 内以 `ProviderTimeoutError` 终结 |
| `provider_max_retries` | 仅等值断言：读 `_guard_config` 比对字段，**行为断言缺失** |
| `circuit_error_ratio` | 仅等值断言：无法从外部反推，窗口口径在 `guard.py` 内部 |
| `circuit_cooldown_s` | 仅等值断言：冷却计时同样在 `guard.py` 内部 |

上面第一行的「透传失效会走通道自带的 5s」是这句断言有判别力的原因：
两档超时相差 25 倍，透传一旦失效立刻变红。

**注意 ruff 的 E501 按显示宽度计**（CJK 字符算 2 格），故本文件里的表格行
MUST 按显示宽度而不是 `len()` 控制长度——实测踩过：某行 78 个字符却有 24 个宽字符，
显示宽度 102 > 100，`len()` 看不出来。

补齐 `provider_max_retries` 的行为断言归 T/G 阶段（Task 4.11 要「降级状态可观测」时会自然覆盖）。
**在那之前，MUST NOT 把本文件的「透传」叙述当作「重试次数确实随配置变化」的证据。**
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, fields

from aicore.core.config import Settings, is_blank
from aicore.provider import cloud_ocr, cloud_vision, deepseek
from aicore.provider.base import OcrProvider, TextProvider, VisionProvider
from aicore.provider.cloud_ocr import CloudOcrProvider
from aicore.provider.cloud_vision import CloudVisionProvider
from aicore.provider.deepseek import DeepSeekTextProvider
from aicore.provider.guard import CircuitBreaker, GuardConfig, StepClock, guard_config_from
from aicore.provider.mock import MockOcrProvider, MockTextProvider, MockVisionProvider

__all__ = ["Providers", "select_providers"]

_logger = logging.getLogger(__name__)

#: 通道实现名（落 `model_meta.provider`，`er.md` §6.1）。逐字对齐 `Settings.provider`
#: 的字面量与各通道模块内的 `NAME` 常量。
PROVIDER_MOCK = "mock"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_CLOUD_VISION = "cloud_vision"
PROVIDER_CLOUD_OCR = "cloud_ocr"


@dataclass(frozen=True, slots=True)
class Providers:
    """一次选择的结果：三个通道的可调用对象（**未选中的为 `None`**）。

    `None` 不是「忘了装配」而是「本部署不提供该通道」，语义见模块 docstring
    （MUST NOT 回落到 mock）。三个字段都是 Protocol 类型而非具体类：
    调用方（Task 4.6 的任务处理器）只依赖 `provider/base.py` 的抽象，
    spec.md:18-21 的「换供应商时调用方接口契约与业务逻辑无须改动」才成立。
    """

    text: TextProvider | None
    vision: VisionProvider | None
    ocr: OcrProvider | None


#: 三个槽位名（`Providers` 的字段名）。**顺序即装配顺序**，也是「每张通道表都把三个槽位
#: 写全（含 `None`）」这条纪律的判据（见 `_CHANNEL_TABLE` 与 `_SELECTABLE_SLOTS`）。
#:
#: 从 dataclass 自身取而不是另抄一份字面量：抄一份就多了一个会漂移的副本，
#: 而「槽位名与字段名不一致」的后果是 `providers.ocr is None` 这类断言静默失效。
_SLOT_NAMES: tuple[str, ...] = tuple(field.name for field in fields(Providers))


def select_providers(
    config: Settings,
    *,
    breaker: CircuitBreaker | None = None,
    clock: StepClock | None = None,
) -> Providers:
    """按 `config.provider` 装配三个通道槽位；未选中的槽位为 `None`。

    只读 `config`（见模块 docstring「不读任何业务参数」）。`breaker` / `clock` 缺省时：

    - `breaker=None` → **本次选择结果的三个通道共享一个新实例**。熔断状态是**进程级**的
      健康判断，每个通道各造一个会让「deepseek 挂了」这件事对其余通道不可见；共用是安全的，
      因为熔断按 `(provider, operation)` 维度隔离（`guard.CircuitBreaker`）。
      **MUST NOT 用模块级单例**：那会让用例之间互相污染（第 3 组吃过
      `fileConfig` 禁用全部日志器导致 17 条用例红的教训）。故每次调用各造一个。
    - `clock=None` → 真实时钟（`guard.system_clock()`，由通道实现内部兜底）；
      用例注入假时钟即可让退避与冷却零成本可测。

    `mock` 槽位**不接**护栏（不传 `breaker` / `config`）：Mock 是零网络、零故障的确定性
    实现，给它接熔断只会让「Mock 被熔断」这种不可能的状态进入可观测面；
    且 `MockTextProvider()` 保留自己的 `MockScript` 注入点供演练用。

    被选中通道的**凭据为空**时抛 `ValueError`（`cloud_*` 无凭据字段，不查）。
    """
    if config.provider == PROVIDER_MOCK:
        return _build_mock_providers()

    entry = _REAL_PROVIDER_TABLE.get(config.provider)
    if entry is None:
        # 结构上不可达：`Settings.provider` 是封闭的 `Literal`，表与它由
        # tests/unit/test_provider_selector.py 的两侧断言钉住。显式抛出只为满足
        # mypy strict 的「所有路径都有返回值」，并让「新增通道却忘了登记」变成一条
        # 带名字的错误，而不是静默返回一个三槽皆 None 的 Providers（那会让选择器
        # 在新增通道时安静地"成功"）。
        raise ValueError(
            f"未登记的通道 provider={config.provider!r}："
            f"selector 只认 {PROVIDER_MOCK!r} 与 {sorted(_REAL_PROVIDER_TABLE)}；"
            f"新增通道 MUST 同时登记 core/config.py 的密钥表与本文件的 _REAL_PROVIDER_TABLE"
        )

    _require_api_key(config, entry)
    guard_config: GuardConfig = guard_config_from(config)
    shared_breaker = breaker if breaker is not None else CircuitBreaker(guard_config, clock=clock)
    return entry.build(config, shared_breaker, clock)


def _build_mock_providers() -> Providers:
    """`provider=mock`：三个槽位**各一个实例**。

    不共用一个实例：三个 Mock 类各有自己的 `call_count` 与 `MockScript`
    （`provider/mock.py`），共用会让「TEXT 被调用了几次」与「OCR 被调用了几次」不可分。
    """
    return Providers(
        text=MockTextProvider(),
        vision=MockVisionProvider(),
        ocr=MockOcrProvider(),
    )


def _build_deepseek(
    config: Settings,
    breaker: CircuitBreaker,
    clock: StepClock | None,
) -> Providers:
    """`provider=deepseek`：只提供 TEXT（VISION / OCR 为 `None`）。

    通道自己会用同一个 `config` 经 `guard_config_from(config)` 再算一次护栏参数
    （`deepseek.py` 的 `__init__`），故两者必然同值。本层**不**再往里塞第二份护栏参数：
    通道构造函数是 Task 4.3 定稿的 `(config, *, breaker, clock)`，多传一份会让
    「护栏参数从哪来」变成两个来源。
    """
    return Providers(
        text=DeepSeekTextProvider(config, breaker=breaker, clock=clock),
        vision=None,
        ocr=None,
    )


def _build_cloud_vision(
    config: Settings,
    breaker: CircuitBreaker,
    clock: StepClock | None,
) -> Providers:
    """`provider=cloud_vision`：只提供 VISION（TEXT / OCR 为 `None`）。"""
    return Providers(
        text=None,
        vision=CloudVisionProvider(config, breaker=breaker, clock=clock),
        ocr=None,
    )


def _build_cloud_ocr(
    config: Settings,
    breaker: CircuitBreaker,
    clock: StepClock | None,
) -> Providers:
    """`provider=cloud_ocr`：只提供 OCR（TEXT / VISION 为 `None`）。"""
    return Providers(
        text=None,
        vision=None,
        ocr=CloudOcrProvider(config, breaker=breaker, clock=clock),
    )


def _require_api_key(config: Settings, entry: _ChannelEntry) -> None:
    """被选中通道的凭据为空时 fail fast（**装配期配置错误**，见模块 docstring）。

    只对**已声明密钥字段**的通道做这件事：`cloud_vision` / `cloud_ocr` 的
    `api_key_field` 为 `None`，本函数**直接返回、不查字段**——凭空查一个不存在的属性会
    `AttributeError`，那是把「暂无凭据字段」变成一条看不懂的崩溃。

    错误消息**点名环境变量**（`AICORE_DEEPSEEK_API_KEY`），且**只回显字段名与 provider**，
    MUST NOT 回显取值本身（凭据安全，同 `core/config.py` 的硬约束）。

    `Settings` 侧已有的「真实通道缺密钥」跨字段校验拦的是**同一件事**，故本函数在正常
    启动路径上不会触发；它存在是为了兜住绕过 `Settings` 校验的路径（`model_copy` 改字段、
    测试里直接构造带空密钥的实例），使「空密钥进到通道」只有一种失败方式，且是当场失败。
    """
    if entry.api_key_field is None:
        return
    if is_blank(getattr(config, entry.api_key_field)):
        raise ValueError(
            f"provider={config.provider!r} 的凭据未配置：{entry.api_key_field} 为空"
            f"（读作环境变量 AICORE_{entry.api_key_field.upper()}）。"
            f"这是装配期配置错误：本服务 MUST NOT 以「无凭据」状态构造真实通道——"
            f"否则每次调用都会以 4003 失败并让任务转人工，而根因只是一行漏配的环境变量"
        )


# ---------------------------------------------------------------------------
# 真实通道表（设计文档 L143 的措辞「按配置选择通道」的落点）
#
# 每张表把**一个** `provider` 取值映射到四件东西：
#   ① `build`：三槽位的构造函数，返回 `Providers`（未选中的槽位显式为 `None`）；
#   ② `slots`：本 provider **已选**的槽位（可遍历数据，供结构用例与文档引用）；
#   ③ `api_key_field`：该 provider 的密钥字段名；`None` = 尚无密钥字段（云通道）；
#   ④ `provider_name`：落 `model_meta.provider` 的通道实现名（与通道模块的 `NAME` 同值）。
#
# 为什么用「表」而不是一串 if/elif：`select_providers` 里写死的分支只能靠读代码核对
# 「四个 provider × 三个槽位」是否写全；表是可遍历的数据，
# tests/unit/test_provider_selector.py 因此能对**整张矩阵**做结构断言（含 `None` 的格子），
# 而不是只测「我已经想到的那几格」。新增通道时：`core/config.py` 的密钥表 + 本表
# 一起改，两侧用例各自会红一次。
#
# `slots` 与 `build` 的一致性**不是**约定而是可查的：用例逐 provider 断言
# 「`slots` 里列出的槽位构造出来非 None，其余恰好为 None」。
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ChannelEntry:
    """一个真实 provider 的通道表行（字段含义见上一段注释）。"""

    build: Callable[[Settings, CircuitBreaker, StepClock | None], Providers]
    slots: tuple[str, ...]
    api_key_field: str | None
    provider_name: str


_REAL_PROVIDER_TABLE: dict[str, _ChannelEntry] = {
    PROVIDER_DEEPSEEK: _ChannelEntry(
        build=_build_deepseek,
        slots=("text",),
        api_key_field="deepseek_api_key",
        provider_name=PROVIDER_DEEPSEEK,
    ),
    PROVIDER_CLOUD_VISION: _ChannelEntry(
        build=_build_cloud_vision,
        slots=("vision",),
        # 尚无密钥字段：`core/config.py` 的 `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 逐字标注，
        # 真实接入时该集合与本行要一起改（改完启动校验的规则 2 自动开始核验它）。
        api_key_field=None,
        provider_name=PROVIDER_CLOUD_VISION,
    ),
    PROVIDER_CLOUD_OCR: _ChannelEntry(
        build=_build_cloud_ocr,
        slots=("ocr",),
        api_key_field=None,
        provider_name=PROVIDER_CLOUD_OCR,
    ),
}

#: `mock` 的槽位元数据。它不走 `_REAL_PROVIDER_TABLE`（真表要 `CircuitBreaker`，
#: 而 Mock 明确不接护栏，见 `select_providers` 的 docstring），但槽位元数据仍要在同一处
#: 可查——否则「mock 覆盖三个槽位」这句话只活在文档里，而它正是本任务矩阵的第一行。
_MOCK_SLOTS: tuple[str, ...] = _SLOT_NAMES

#: provider → 已选槽位（**含 mock**，即设计文档 L143 的「三张通道表」的全集）。
#:
#: 用例用它遍历整张矩阵：对每个 provider 断言「`slots` 里列出的槽位非 None，
#: 其余**恰好**为 None」——这样 `slots` 与 `build` 的一致性是可查的，而不是靠约定。
_SELECTABLE_SLOTS: dict[str, tuple[str, ...]] = {
    PROVIDER_MOCK: _MOCK_SLOTS,
    **{name: entry.slots for name, entry in _REAL_PROVIDER_TABLE.items()},
}


def _validate_channel_table() -> None:
    """表自身的自检：**表里的元数据与代码事实对不上时，这里在 import 期就红**。

    每条各自对应一种已经踩过的形态：

    1. **槽位名拼错**（`"visions"`）：表里多一个永远为 `None` 的槽位、少一个真实的槽位，
       而在运行期只表现为「视觉通道不可用」——一个极难归因的静默失效；
    2. **`slots` 为空**：一个「一个通道都不提供」的真实通道没有意义，
       它多半是漏写而不是有意为之；
    3. **密钥字段名拼错**：凭空查一个不存在的 `Settings` 字段会在装配期
       `AttributeError`——那是把「配错」变成一条看不懂的崩溃；
    4. **`provider_name` 与通道模块的 `NAME` 不一致**：它落 `model_meta.provider`，
       是血缘的「哪个实现产出了这条结论」（`er.md` §6.1）。对不齐会让 4.10 的阈值留痕
       与按版本复盘（spec.md:128）指到另一个通道上。

    「表与 `Settings.provider` 字面量必须恰好互相覆盖」这条**不在这里**：它要读 pydantic 的
    注解，属结构性用例的地盘（`tests/unit/test_provider_selector.py`——与
    `test_config_startup.py::test_every_real_provider_is_registered_in_a_channel_table`
    同向）。放在模块里做会在 import 期把 `core.config` 的注解对象固化进本模块。
    """
    unknown = sorted(set(_SELECTABLE_SLOTS) - {PROVIDER_MOCK} - set(_REAL_PROVIDER_TABLE))
    assert not unknown, f"通道表与已选槽位表不一致：{unknown}"
    #: 各通道模块声明的实现名。与上面理由 4 同一件事，用模块常量读而不是再抄一遍字面量。
    declared_names = {
        PROVIDER_DEEPSEEK: deepseek.NAME,
        PROVIDER_CLOUD_VISION: cloud_vision.NAME,
        PROVIDER_CLOUD_OCR: cloud_ocr.NAME,
    }
    for provider, entry in _REAL_PROVIDER_TABLE.items():
        assert entry.slots, f"{provider} 的 slots 为空：一个通道都不提供的『真实通道』没有意义"
        bad_slots = [slot for slot in entry.slots if slot not in _SLOT_NAMES]
        assert not bad_slots, (
            f"{provider} 的 slots 含未知槽位 {bad_slots}："
            f"合法槽位只有 {list(_SLOT_NAMES)}（拼错的槽位会永远为 None，是静默失效）"
        )
        if entry.api_key_field is not None:
            assert entry.api_key_field in Settings.model_fields, (
                f"{provider} 登记的密钥字段 {entry.api_key_field} 不存在于 Settings："
                f"凭空查一个不存在的字段会在装配期 AttributeError"
            )
        assert entry.provider_name == declared_names[provider], (
            f"{provider} 的通道表写着 provider_name={entry.provider_name!r}，"
            f"而通道模块声明的 NAME={declared_names[provider]!r}："
            f"这个值会落 model_meta.provider（血缘），两处必须逐字一致"
        )


_validate_channel_table()
