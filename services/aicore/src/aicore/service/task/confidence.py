"""置信度分级：**高 ≥0.9 / 中 0.7~0.9 / 低 <0.7**（阈值可配并留痕）。Task 4.10。

**权威依据**：`tasks.md:46`（任务口径）、`spec.md:58`（阈值可调并留痕 + 分级随 AI 输出返回 +
**置信度 MUST NOT 被用作跳过人工确认的依据**）、`spec.md:63`（人工端据此**排序**复核）、
`spec.md:128`（**当次**置信度阈值快照）、`er.md:63`（`HIGH≥0.9` 是显式边界）、
`er.md:40`/`:345`/`:481`（置信度不足 → `needs_manual_review` → 转人工核验兜底）、
`provider/results.py` 的模块 docstring（`confidence: float | None` 是为了区分
**「没有置信度」与「置信度为 0」**）。

## 一、边界归属：`0.9` 与 `0.7` 曾被两档同时包含（控制者裁定）

`spec.md:58` / `er.md:63` / `er.md:301` 三处都写「高 ≥0.9、中 0.7~0.9、低 <0.7」，
于是 `0.9` 与 `0.7` **各被两档同时包含**。控制者裁定（**MUST 照此，不得另选**）：

| 输入 | 判级 | 归属规则 |
|---|---|---|
| `c >= 0.9` | `HIGH` | 显式边界（`er.md:63` 的 `HIGH≥0.9`）优先 |
| `0.7 <= c < 0.9` | `MEDIUM` | 余下区间自然取半开 |
| `c < 0.7` | `LOW` | `er.md:63` 的 `LOW<0.7` |

依据：`HIGH≥0.9` 是**显式边界**，而 `MEDIUM 0.7~0.9` 只是**区间描述**；反过来判
（`0.9 → MEDIUM`）必须改 `HIGH≥0.9` 才能自洽，那是"改文档迁就猜法"。

**边界规则只有一处**：`classify_confidence` 是**纯函数**，全仓三分只此一份
（散成多处 `if` 必然漂移）。"阈值可配"只影响两个阈值，**不影响**上面的归属规则。

## 二、`confidence is None`：**不判级** + `needs_manual_review = 1`（控制者裁定）

三处文档只写了"有置信度"的情形 ⇒ 这是典型的**文档少写**。裁定：

- **不判级**（`level is None`），**MUST NOT** 返回 `LOW`；
- 且 **`needs_manual_review = 1`**——依据 `er.md:40`「置信度**不足**转人工核验**兜底**」的目的：
  通道没给置信度 ⇒ AI 无法自证可靠 ⇒ 走兜底。

**这两件事的语义区别（MUST NOT 混同）**：

- ❌ **把 `None` 当 `0.0`** ⇒ 伪造出一个 `LOW`：那是**造假数据**——系统凭空宣称
  "这次判定置信度极低"，而真实情况是"通道没给这个数"。`provider/results.py` 的
  `OcrField.confidence` 逐字写着"**MUST NOT 补 0**"，理由就是这个。
- ✅ **`None` ⇒ 不判级 + 兜底**：**保守兜底**——系统如实说"这次没有可用的置信度"，
  同时按"无法自证可靠"处置（转人工）。两者对下游的差别是：
  前者给出一条**假的低置信度记录**（会污染按置信度排序与统计），后者给出一条
  **没有分级的记录 + 人工兜底**。

## 三、`MUST NOT` 被用作跳过人工确认的依据（`spec.md:58` 末句）

`spec.md:58`：「置信度 **MUST NOT** 被用作跳过人工确认的依据」；`:63`：分级是**排序**依据；
`:65-68`：**高置信度仍不自动执行任何执法/处罚/公示动作**。

故 `ConfidenceVerdict` **只有两个字段**（`level` / `needs_manual_review`），
**没有**任何能表达"免人工 / 跳过复核"的字段；`needs_manual_review` 的含义是
`er.md:481` 的「转人工核验**兜底**队列」，不是"是否需要人看"（所有输出都进人工端，
只是排序不同）。判据见 `tests/unit/test_confidence.py`：它断言**字段集合恰好是两个**，
于是"哪天有人加了个 `skip_review`"会当场变红。

## 四、契约 2：本模块**只吃 `float`，不碰 provider 类型**

`.importlinter` 契约 2 把 `aicore.service → aicore.provider` **整包**列为违规
（只放行 `provider.base`）。故本模块**不** import `provider/results.py` 的
`ProviderResult` / `OcrField`——调用方把 `result.confidence`（一个 `float | None`）取出来传进来。
这既满足契约，也让三分逻辑**与通道形态无关**（换供应商不影响它）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

__all__ = [
    "MODEL_META_THRESHOLDS_KEY",
    "THRESHOLD_HIGH_KEY",
    "THRESHOLD_MEDIUM_KEY",
    "ConfidenceLevel",
    "ConfidenceVerdict",
    "classify_confidence",
    "confidence_thresholds",
    "grade",
    "thresholds_snapshot_of",
]


class ConfidenceLevel(StrEnum):
    """分级取值（`spec.md:63` 的三个值）。

    用 `StrEnum` 而不是裸字符串：分级要**随 AI 输出一并返回**（`spec.md:58`），
    输出侧的取值域因此需要一个可枚举、可校验的类型；同时 `StrEnum` 的成员**就是 `str`**，
    渲染进 JSON / 落库时不需要额外转换。

    与 `er.md:63` 的 `confidence_level` 列（原生 enum）取值逐字一致——但**不要**据此以为
    M1 该加那一列：那个列在 `VISION_REVIEW` 表上，属 M2 的任务类型（`design.md:190`）。
    M1 的落库后果是 `ocr_result.needs_manual_review`（`er.md:40`）。
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


#: 阈值快照里的两个键名。**逐字对齐 `provider/results.py::ProviderIdentity.thresholds`
#: 的 `{high, medium}`**（它的 docstring 写着"判定阈值快照 `{high, medium}`"）——
#: 快照要经 `as_model_meta()` 落进 `ai_task.model_meta.thresholds`（`er.md:27`），
#: 两处键名不一致会让"留痕"与"读回"对不上。
THRESHOLD_HIGH_KEY: Final = "high"
THRESHOLD_MEDIUM_KEY: Final = "medium"

#: `ai_task.model_meta` 里承载阈值快照的那个键（`er.md:27`：`…+promptVersion+阈值快照`）。
MODEL_META_THRESHOLDS_KEY: Final = "thresholds"


@dataclass(frozen=True, slots=True)
class ConfidenceVerdict:
    """分级结果（`spec.md:58`「分级结果 MUST 随 AI 输出一并返回」）。

    **只有两个字段是刻意的**（见模块 docstring §三）：

    - `level`：`HIGH` / `MEDIUM` / `LOW`，或 `None`（**通道没给置信度 ⇒ 不判级**，
      不是 `LOW`——那是造假数据）；
    - `needs_manual_review`：是否进"人工核验**兜底**队列"（`er.md:481`）。

    `frozen` + `slots`：结果一旦产出就不可改（它是随输出外发的东西，
    下游顺手改一个字段会让"返回的分级"与"留痕/落库的分级"不再同源）。
    """

    level: ConfidenceLevel | None
    needs_manual_review: bool


def confidence_thresholds(*, high: float, medium: float) -> dict[str, float]:
    """把两个可配阈值渲染成**快照字典**（键名见 `THRESHOLD_HIGH_KEY` / `THRESHOLD_MEDIUM_KEY`）。

    这是快照键名的**唯一**产出点：`api/ocr.py` 用它把 `Settings` 的两个值冻进
    `ai_task.model_meta.thresholds`（`spec.md:128` 的"**当次**快照"），
    执行期（第 5 组）再用 `thresholds_snapshot_of` 读回来给 `grade`。
    两个方向共用一个键名定义，故"写得进、读得出"不靠人记。
    """
    return {THRESHOLD_HIGH_KEY: high, THRESHOLD_MEDIUM_KEY: medium}


def _threshold(thresholds: Mapping[str, float], key: str) -> float:
    """取一个阈值；缺失即**显式报错**（MUST NOT 回落到某个默认值）。

    `er.md:301` 把分级阈值标为「✅ 已定档，工作台运营期可调」——两个值**必须**来自配置，
    一个"缺失就当我 0.9"的兜底会让运营改了配置却不生效，而现场没有任何信号
    （正是本项目反复出现的"静默漂移"形态）。
    """
    try:
        return float(thresholds[key])
    except KeyError:
        raise ValueError(
            f"置信度阈值快照缺少 {key!r} 键（期望 {sorted(thresholds)} 含它）："
            f"分级阈值必须来自配置，MUST NOT 用内置默认值兜底"
        ) from None


def classify_confidence(
    confidence: float | None, *, high: float, medium: float
) -> ConfidenceLevel | None:
    """**三分纯函数**（边界规则的唯一实现处，见模块 docstring §一）。

    | 输入 | 返回 |
    |---|---|
    | `None` | `None`（**不判级**；MUST NOT 返回 `LOW`，理由见模块 docstring §二） |
    | `>= high` | `HIGH` |
    | `>= medium` | `MEDIUM` |
    | 其余（含负数与 0） | `LOW` |

    纯函数的三条含义（都用例钉住）：无 IO、无配置读取（两个阈值**显式传入**）、
    无隐藏状态。参数名取 `high` / `medium` 而不是 `confidence_high` / `confidence_medium`：
    本函数只关心"两条线在哪"，字段名那层语义留给 `Settings`（调用方做一次映射）。

    `high` / `medium` 的**相对关系**（`medium <= high`）由配置层保证
    （`core/config.py` 的跨字段校验）；本函数对 `medium > high` 的行为是"`MEDIUM` 档为空、
    `HIGH` 从 `high` 起"——它仍然是一个良定义的函数，不需要在这里再报一次错。
    """
    if confidence is None:
        return None
    if confidence >= high:
        return ConfidenceLevel.HIGH
    if confidence >= medium:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def grade(confidence: float | None, *, thresholds: Mapping[str, float]) -> ConfidenceVerdict:
    """把一次 AI 输出的置信度判成 `ConfidenceVerdict`（**分级 + 是否需要人工兜底**）。

    `thresholds` 是**当次任务的阈值快照**（`confidence_thresholds` 产出的那个字典，
    从 `ai_task.model_meta.thresholds` 读回），**不是**"当前全局配置"：
    `spec.md:128` 要的是"当次快照"，用当前配置会让历史任务的分级随运营改配置而漂移。

    `needs_manual_review` 的判据（两处依据都在 `er.md`）：

    - `level is None`（通道没给置信度）⇒ **True**（`er.md:40` 的兜底目的，见模块 docstring §二）；
    - `level is LOW` ⇒ **True**（`er.md:345`「识别置信度不足 → 转人工核验兜底」）；
    - `HIGH` / `MEDIUM` ⇒ **False**——注意这**不是**"不用人看"：所有输出都进人工端
      （`spec.md:63`），`MEDIUM` 只是排序靠后。这一点写在字段名与 docstring 里，
      免得下游把本字段读成"免人工"。`spec.md:58` 末句禁的正是那种读法。
    """
    level = classify_confidence(
        confidence,
        high=_threshold(thresholds, THRESHOLD_HIGH_KEY),
        medium=_threshold(thresholds, THRESHOLD_MEDIUM_KEY),
    )
    return ConfidenceVerdict(
        level=level,
        needs_manual_review=level is None or level is ConfidenceLevel.LOW,
    )


def thresholds_snapshot_of(model_meta: Mapping[str, Any] | None) -> dict[str, float] | None:
    """从 `ai_task.model_meta` 里取**当次阈值快照**；取不到返回 `None`。

    ## 为什么取不到时**不**回落"当前配置"（这是本函数存在的全部理由）

    `spec.md:128` 要的是"**当次**置信度阈值快照"——留痕的意义就在于
    「**根据什么阈值作出的判定**」可追溯。若这里在快照缺失时悄悄读当前配置，
    留痕就变成**不可证伪**的：一个没有快照的历史任务会用今天的阈值被解释，
    而现场看不出任何异常（本项目反复出现的"静默漂移"）。

    故取不到就返回 `None`，把"没有当次快照"这件事**如实交给调用方**：
    执行侧要么按 `er.md:40` 的兜底转人工，要么补一次显式的补录——都是**可见**的决定。

    这与 `provider/results.py` 对 `confidence=None` 的口径同构：
    **"没有这个值"与"这个值是某个默认值"是两件事**，不许互相顶替。
    """
    if model_meta is None:
        return None
    raw = model_meta.get(MODEL_META_THRESHOLDS_KEY)
    if not isinstance(raw, Mapping):
        return None
    return {str(key): float(value) for key, value in raw.items()}
