"""通道返回结构与血缘（Task 4.1）。

本模块只依赖 stdlib：**不受 `.importlinter` 契约 4（`core` 不得依赖业务层）约束**，
因为方向是 `provider → core` 合法而非反向；事实上本模块连 `core` 都不 import，
故它是全仓依赖最少的模块之一。

## 为什么是冻结 dataclass 而不是 Pydantic 模型

`core/envelope.py` 那类**跨进程契约**用 Pydantic（要序列化、要校验外部输入）；
本模块描述的是**进程内**跨层传递的结构：数据由我方通道实现产生，不来自用户输入，
不需要校验，需要的是「构造即不可变」与「字段名一眼可核」。frozen dataclass 同时满足
`mypy --strict` 与「结果不可被下游改写」（改写会静默污染审计血缘）。

## 为什么 dtype 全部显式写出

`float | None` 而不是 `float` + 省略：`Task 4.10`（置信度分级）与 `Task 4.11`
（通道失败/超时分别计数）都要**区分「没有置信度」与「置信度为 0」**。
用 `0.0` 兼任两者会让「通道没给置信度」被算成「极低置信度」，进而在 4.10 里
被判成 `LOW` 并转人工——那是造假数据，不是兜底。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Literal

#: 通道类别（3 个）。取值与 `er.md` §6.1 `model_meta` 的 `channel` 键一致。
#:
#: **为什么只有 3 个而不是 4 个**：spec.md:11 说「文本、视觉云、OCR 与平台自建预测
#: 四类通道」，但 design.md:54 / :142 与 tasks.md:37 都只定义 3 个 Protocol，
#: design.md:145 规划的真实通道文件只有 `{deepseek,cloud_vision,cloud_ocr}.py` 三个，
#: 且 design.md:26 明确「不实现 K-03/K-04/K-05/K-06 的业务逻辑（只保留任务类型枚举与
#: 通道路由扩展位）」。故「平台自建预测」在 M1 没有通道实现，它只以任务类型
#: `RISK_PREDICT` 的**预留注册位**存在（design.md:192）。
#: 给它造一个找不到实现的 `Channel` 成员会让「可替换通道」变成空话。
#:
#: **必须用 `Literal` 而不是 `str` 别名**：`Channel = str` 在静态与运行期都不构成
#: 任何约束（`channel="TEXTX"` 照样过 mypy），那样「通道类别是封闭集合」这句话就只剩注释。
#: 静态由 `Literal` 拦、运行期由 `ProviderIdentity.__post_init__` 拦，两层都要有——
#: 前者管手写字面量，后者管从配置/字典拼出来的值（配置写错的真实形态）。
type Channel = Literal["TEXT", "VISION", "OCR"]

#: 通道类别的封闭集合（运行期口径）。与上面的 `Literal` 必须同集合。
#:
#: **注意：比对 MUST NOT 走 `get_args(Channel)`**——实测（Python 3.14.6）
#: `get_args()` 对 `type X = Literal[...]` 形式返回**空元组**，不报错。
#: 于是「用 get_args 现算再比对」会退化成 `frozenset() == frozenset()` 或
#: `set() == CHANNELS` 的恒假/恒真断言，**看起来在防漂移，实际一行都没防**。
#: `Channel.__value__` 才是那份 `Literal`；同集合由
#: `tests/unit/test_provider_results.py::test_channel_literal_and_runtime_set_agree`
#: 经 `get_args(Channel.__value__)` 断言。
CHANNELS: frozenset[str] = frozenset({"TEXT", "VISION", "OCR"})

#: 结构化字段单条。键名与 `openapi.yaml:708-726` 的 `OcrField` 逐字一致
#: （`fieldName` / `value` / `confidence`），以便本结构**原样**落 `ocr_result.fields_json`
#: （`er.md` §6.2：「OcrField = {fieldName, value(脱敏), confidence(0~1)}」）。
type FieldName = str


@dataclass(frozen=True, slots=True)
class OcrField:
    """OCR 单字段。三个键名是**跨服务契约**（openapi.yaml 的 `OcrField`），不得改名。

    `confidence` 可空：通道未给出该字段置信度时保持 `None`，**MUST NOT 补 0**——
    补 0 会在 4.10 里被判成 `LOW` 并误触人工复核（见模块 docstring）。
    """

    fieldName: FieldName  # noqa: N815 —— 跨服务契约字段名，逐字取自 openapi.yaml 的 OcrField
    value: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """通道身份与血缘（`er.md` §6.1 `model_meta` 的 5 个键）。

    键名映射（**逐字对齐 `er.md` §6.1**，不是我的命名偏好）：

    | `model_meta` 键 | 本类字段 | 语义 |
    |---|---|---|
    | `channel` | `channel` | 通道**类别**（TEXT / VISION / OCR） |
    | `provider` | `provider` | 通道**实现**名（mock / deepseek / …） |
    | `modelVersion` | `model_version` | 模型版本 |
    | `promptVersion` | `prompt_version` | Prompt 版本 |
    | `thresholds` | `thresholds` | 判定阈值快照 `{high, medium}` |

    为什么把「类别」与「实现」分成两个字段：spec.md:20 的场景是「某类通道更换供应商
    → 调用方契约与业务逻辑无须改动，仅通道实现与配置发生变更」。只有一个字段时，
    换供应商会让历史血缘的**语义**发生变化（同一个值昨天指 A 模型、今天指 B 模型），
    按版本维度复盘准确率（spec.md:128「血缘记录 MUST 支持按版本维度统计结果质量」）
    就失去基准。
    """

    channel: Channel
    provider: str
    model_version: str
    prompt_version: str
    #: 阈值快照。默认空字典是**合法**的：TEXT 通道用不到置信度分级，
    #: 强行要求 `{high, medium}` 会逼调用方填假值。
    thresholds: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """通道类别必须在封闭集合内。

        为什么在 `__post_init__` 里查而不是靠 Literal：`Channel` 是 `str` 别名，
        类型检查器拦得住手写的 `ProviderIdentity(channel="TEXTX")`，拦不住从配置
        或字典拼出来的值——而那正是配置写错时的形态。这里把它变成构造期失败。
        """
        if self.channel not in CHANNELS:
            raise ValueError(
                f"未知通道类别 {self.channel!r}：合法取值为 {sorted(CHANNELS)}"
                f"（见 provider/results.py 的 CHANNELS；『平台自建预测』在 M1 无通道实现，"
                f"不以 Channel 形式存在——design.md:26 只保留其任务类型扩展位）"
            )

    def as_model_meta(self) -> dict[str, Any]:
        """渲染成 `er.md` §6.1 规定的 `ai_task.model_meta` JSON 结构。

        键名逐字用 camelCase（`modelVersion` / `promptVersion`）：`er.md` §6 的
        「枚举值与 openapi.yaml `components.schemas` 一一对应」与 openapi.yaml 全篇
        的 camelCase 风格在此一致。**MUST NOT 输出 snake_case**——那会让落库的 JSON
        与文档口径分叉，而 5.7 的验收正是「字段与 `er.md` §6.1 一致」。
        """
        return {
            "channel": self.channel,
            "provider": self.provider,
            "modelVersion": self.model_version,
            "promptVersion": self.prompt_version,
            "thresholds": dict(self.thresholds),
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """三通道**统一返回结构**（Task 4.1「统一入参与返回结构含置信度与血缘字段」）。

    各通道的载荷字段三选一，其余为 `None`：

    | 通道 | 载荷字段 | 形态 |
    |---|---|---|
    | TEXT | `text` | `str` |
    | VISION | `markers` | `tuple[Mapping[str, Any], ...]` |
    | OCR | `fields` | `tuple[OcrField, ...]` |

    VISION 的每个 marker 键名对齐 `openapi.yaml` 的 `VisionMarker`
    （`label` / `level` / `confidence`，见 openapi.yaml:945-992）。

    **为什么用一个类承载三种载荷而不是三个类**：Task 4.1 要的是「统一返回结构」；
    三个类会让 `service` 层为取得 `identity` 而写三份分支（`isinstance` 链），
    那样「统一」只体现在文档里。代价是类型上无法静态保证「TEXT 结果的 `markers` 必为
    `None`」——该保证由各实现自己的契约用例承担（不静默、可复核）。

    `confidence` 是**通道级**置信度：`None` 表示该通道/该次调用未给出，
    MUST NOT 被下游当成 `0.0`（见模块 docstring）。
    """

    identity: ProviderIdentity
    text: str | None = None
    markers: tuple[Mapping[str, Any], ...] | None = None
    fields: tuple[OcrField, ...] | None = None
    confidence: float | None = None
    #: 通道返回的原文/原始结构（排障与评估集用）。`None` = 通道未提供。
    #: **MUST NOT 含未脱敏的证件值**（spec.md:243-246：日志与审计不留未脱敏数据）——
    #: 本字段只随任务结果留痕，不进日志。
    raw: Mapping[str, Any] | None = None

    @property
    def lineage(self) -> ProviderIdentity:
        """血缘的别名。`er.md` §6.1 把它叫 `model_meta`，本类叫 `identity`——

        两个名字各有语境（库表字段 vs 进程内结构），故保留双入口而非二选一，
        避免调用方为了对齐文档再写一层 `result.identity.model_version` 的展开。
        """
        return self.identity


def to_jsonable(value: Any) -> Any:
    """把结果结构递归渲染成可 JSON 序列化的形态（枚举取 `value`，dataclass 取字段）。

    为什么手写而不用 `dataclasses.asdict` 一把梭：`asdict` 会**深拷贝** `Mapping`
    与 `tuple`，对 `raw`（可能很大）是纯浪费；且它不处理 `Enum`。
    本函数只做浅层转换，且把 `Mapping`/`tuple` 原样下探。
    """
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


__all__ = [
    "CHANNELS",
    "Channel",
    "FieldName",
    "OcrField",
    "ProviderIdentity",
    "ProviderResult",
    "to_jsonable",
]
