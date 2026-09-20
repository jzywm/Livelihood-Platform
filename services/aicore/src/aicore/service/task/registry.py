"""任务类型策略注册表（design.md:185-194；er.md §6.1 L291；openapi.yaml 的四个结果结构）。

## 这张表是什么

`ai_task.type` 的每个取值对应一个处理器，处理器需声明自身的结果结构、超时与是否可重试
（design.md:185 逐字）。本模块是**唯一**的「任务类型 → 处理器」映射处。

## 为什么用注册表（design.md:194 逐字）

M2 新增视觉审核时，期望的改动量是「新增一个处理器文件 + 一行注册」，而不是去改
`task_runner` 的分支逻辑。这也保证 `task_runner` 在 M1 之后保持稳定——它是 D2「M2 可切
MQ」的替换点，越少人动越好。**未注册的类型必须显式失败**（而非静默忽略），避免告警丢失。

落地成两条可执行约束：

1. 类型 → 策略的解析在本模块是**表查找**（`REGISTRY[task_type]`），MUST NOT 出现
   `if task_type == …` / `match task_type` 这类逐类型分支——否则「新增类型」会从「加一行
   表项」退化成「加一个 elif」，`task_runner` 也就保不住稳定。该约束由
   `tests/unit/test_task_registry.py` 的 AST 断言把守（含判别力自证）。
2. 未注册类型抛 `ParamError(code=1003)`（枚举或范围非法），因此调用方拿不到任何返回值
   ——「不认识这个类型」不可能被当成「无事发生」静默跳过。

## 四条登记

| `task_type` | `result_schema` | `retryable` | `handler_ref` | `implemented` | 出处 |
|---|---|---|---|---|---|
| `OCR` | `OcrResult` | `True` | `service.ocr_service` | `True` | design.md:189 |
| `VISION_REVIEW` | `VisionReviewResult` | `True` | 预留 | `False`（M2） | design.md:190 |
| `KITCHEN_ANOMALY` | `KitchenAnomalyResult` | `True` | 预留 | `False`（M2/M3） | design.md:191 |
| `RISK_PREDICT` | `RiskPredictResult` | `False` | 预留 | `False`（M3） | design.md:192 |

- 键集合**恰好**是 `er.md` §6.1 L291 的 `type` enum 四个取值（MUST NOT 多、MUST NOT 少）；
- `result_schema` 逐字等于 `openapi.yaml` 的 `components.schemas` 键（`OcrResult:749`、
  `VisionReviewResult:863`、`KitchenAnomalyResult:1144`、`RiskPredictResult:1179`）；
- 这两组比对都在 `tests/unit/test_task_registry.py` 里**现读文档**完成，不在这里抄成常量
  —— 文档改了而本表没跟上时会立刻变红。

## 为什么预留位的 `handler_ref` 是 `<reserved>` 而不是某个模块路径

design.md:190-192 对三个未实现类型只写「**预留注册位**」，**没有给处理器文件**
（design.md:136-140 的目录树里也**没有** `vision_review.py` 之类）。凭空写一个
`service.vision_review` 会造出一个「看起来能 import、实际不存在」的位置：执行器若据此做
导入探测，M1 就会得到一个假的「注册表与实现不一致」。故预留位用**显式的非模块哨兵**
`<reserved>` 标出「此处尚无位置」，让「已登记但无处理器」一眼可辨。

## 超时口径：借来的值，如实标注

`timeout_s` 取 `Settings.ai_call_timeout_s`（Task 4.3；字段出处见 `core/config.py:360-368`，
默认 5.0s）。这是**从调用级超时借用**的值，不是独立定档的任务超时：`ai_call_timeout_s` 是
**单次模型调用**的超时，而任务级超时理论上应 ≥ 一次调用（含重试）—— 但 `design.md` 与
`er.md` 都**没有给任务级超时数值**。凭空造一个「任务级超时」数字等于自造第三口径
（违反自约束 C2/C7）；借用一个**有出处**的值并显式标注它是借用，比造一个没出处的值诚实。
**风险已登记**：Task 4.7 实现执行器时若发现借用值不合适，需要回来改这里。

由该口径派生出两条读法，两者都 MUST 遵守：

- `REGISTRY` 是**模块级常量声明表**（用例要对整张表断言，故 MUST NOT 在 `get_policy`
  里现算）；
- 超时**权威取值一律经 `get_policy` 现读 `Settings`**，MUST NOT 冻结成模块级常量——故
  `get_policy` 每次调用都用现读值覆盖行里的快照，`REGISTRY[…].timeout_s` 本身不是权威值
  （详见 `_BORROWED_TIMEOUT_S` 的注释）。

## 本模块 MUST NOT 导入处理器本体

`handler_ref` 只是字符串。导入处理器会让注册表与具体实现耦合，且 M1 的三个预留位
**没有实现可导**（`<reserved>` 更不可导）；design.md:194 要的改动量是「新增一个处理器
文件 + 一行注册」，若注册表 import 处理器，那一行注册就同时变成一次导入、失败面扩大。
`tests/unit/test_task_registry.py` 对该条有源码级断言（AST 扫 import）与运行期断言
（调用前后比对 `sys.modules` 增量）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

from aicore.core.config import Settings, get_settings
from aicore.core.errors import PARAM_VALUE_CODE, ParamError


@dataclass(frozen=True, slots=True)
class TaskPolicy:
    """一个任务类型的**声明**：结果结构、超时、是否可重试、处理器位置。

    frozen + slots 两条都是硬要求，不是风格偏好：

    - `frozen`：注册表是**共享常量**，任一调用方就地改写都会污染所有调用方（且改写点
      与受害点相隔很远，排障成本极高）。冻结后改写当场抛 `FrozenInstanceError`。
    - `slots`：防止顺手挂一个「本次专用的」属性上去——那等于用实例当缓存，
      共享常量的语义同样会被破坏。
    """

    task_type: str
    result_schema: str  # 结果结构名，逐字取自 openapi.yaml 的 components.schemas
    timeout_s: float
    retryable: bool
    handler_ref: str  # 处理器所在的模块与属性（本任务只登记「在哪」，不导入它）
    implemented: bool  # M1 是否已实现


#: 注册表**行内** `timeout_s` 的快照值：配置默认值（**不是**硬编码数字，也**不是**导入期读环境）。
#:
#: 为什么不是 `get_settings().ai_call_timeout_s`：那会让「import 本模块」变成一次配置解析，
#: 配置写错时将在 **import 期**抛 `ValidationError`，绕过 `core/config.py` 的启动期
#: `ConfigRejected` 路径（Task 2.6 的 lifespan 才有机会把它渲染成运维可读的阻断项清单）。
#: 注册表是纯声明，不该让任何 import 它的人被本机配置绑架。
#:
#: 为什么不是写 `5.0`：那会把同一个数字变成两处出处（`core/config.py:360` 与本文件），
#: 改了一处忘另一处时，「借来的值」会静默变成自造的值。故从模型字段元数据读默认。
#:
#: **代价（如实登记，MUST NOT 被当成"权威值"）**：环境变量覆盖了
#: `AICORE_AI_CALL_TIMEOUT_S` 时，`REGISTRY[…].timeout_s` 与**实际生效值不同**。
#: 故直接读表只应用于结构断言（键集合 / 结果结构 / 可否重试 / 是否已实现）；
#: **取超时一律走 `get_policy`**——它每次现读 `Settings`，见模块 docstring 的「超时口径」。
_BORROWED_TIMEOUT_S: Final[float] = float(Settings.model_fields["ai_call_timeout_s"].default)

#: 预留注册位的 `handler_ref` 哨兵：**显式表示「此处尚无处理器位置」**（见模块 docstring）。
#: 取值刻意不是合法模块名（含 `<` `>`），使「预留」与「已实现」在日志与断言输出里一眼可辨。
_RESERVED_HANDLER_REF: Final = "<reserved>"

#: 任务类型 → 策略。**模块级常量**（用例要对整张表断言，MUST NOT 在 `get_policy` 里现算）。
#:
#: 用 `MappingProxyType` 而不是裸 dict：`Final[Mapping[…]]` 只挡得住 mypy，运行期
#: `REGISTRY["X"] = …` 照样能改裸 dict。注册表是共享常量，就地改会污染所有调用方，
#: 故把它做成运行期也只读的视图（写入抛 `TypeError`）。
#:
#: 行内 `timeout_s` 是 `_BORROWED_TIMEOUT_S` 快照，**不是权威值**；权威超时经 `get_policy` 现读。
REGISTRY: Final[Mapping[str, TaskPolicy]] = MappingProxyType(
    {
        "OCR": TaskPolicy(
            task_type="OCR",
            result_schema="OcrResult",
            timeout_s=_BORROWED_TIMEOUT_S,
            retryable=True,
            handler_ref="service.ocr_service",
            implemented=True,
        ),
        "VISION_REVIEW": TaskPolicy(
            task_type="VISION_REVIEW",
            result_schema="VisionReviewResult",
            timeout_s=_BORROWED_TIMEOUT_S,
            retryable=True,
            handler_ref=_RESERVED_HANDLER_REF,
            implemented=False,
        ),
        "KITCHEN_ANOMALY": TaskPolicy(
            task_type="KITCHEN_ANOMALY",
            result_schema="KitchenAnomalyResult",
            timeout_s=_BORROWED_TIMEOUT_S,
            retryable=True,
            handler_ref=_RESERVED_HANDLER_REF,
            implemented=False,
        ),
        "RISK_PREDICT": TaskPolicy(
            task_type="RISK_PREDICT",
            result_schema="RiskPredictResult",
            timeout_s=_BORROWED_TIMEOUT_S,
            retryable=False,
            handler_ref=_RESERVED_HANDLER_REF,
            implemented=False,
        ),
    }
)


def _resolve_timeout_s(settings: Settings | None) -> float:
    """现读超时口径：显式注入的 `Settings` 优先，否则取进程内唯一配置。

    **每次调用都读**（`get_settings()` 本身有 `lru_cache`，故这是"读缓存"而非"每次重建"）：
    把结果缓到模块级常量里会让「改配置 → 重启」之外的任何标定手段失效，
    而 `core/config.py:356-359` 明确这几项护栏参数是"要从配置侧能调"的。
    """
    resolved = get_settings() if settings is None else settings
    return resolved.ai_call_timeout_s


def get_policy(task_type: str, *, settings: Settings | None = None) -> TaskPolicy:
    """取某任务类型的策略；**未注册类型显式失败**，不回落默认策略。

    `settings` 是**超时口径的注入点**（keyword-only，默认 `None` = 现读进程配置）：
    任务级超时是借来的值（见模块 docstring），Task 4.7 的执行器要按部署形态复核/标定它，
    测试要能证明"这个值确实随配置变、不是被冻结的常量"——两条都要求可注入。

    失败口径（`design.md:194`「未注册的类型必须显式失败（而非静默忽略），避免告警丢失」）：

    - 抛 `ParamError(code=1003)`（枚举或范围非法）—— 这是「请求里的枚举值不在合法范围内」，
      正是 `1003` 的定义；
    - **MUST NOT** 返回 `None`、**MUST NOT** 回落成某个默认策略：前者让调用方必须处理
      "没有策略"这一分支（迟早被 `or DEFAULT` 抹平），后者会把未知类型的任务按
      `OCR` 的处理器跑掉——两条都会让告警静默丢失；
    - 消息里**带上出错的那个类型**：告警要能定位，不能只说"类型非法"。

    `MUST NOT 用 3006/3007`：`3006` 是「对象不存在」（针对已存在的资源），`3007` 是
    「状态不允许该操作」（针对资源状态），两者都不是"参数取值越界"。
    """
    if task_type not in REGISTRY:
        raise ParamError(
            f"未注册的任务类型 {task_type!r}：合法取值为 {sorted(REGISTRY)}。"
            f"未注册类型必须显式失败而非静默忽略，否则告警会丢失（design.md:194）",
            code=PARAM_VALUE_CODE,
        )
    # 用行声明 + **现读**的超时：行里那份 timeout_s 只是配置默认值快照（见 _BORROWED_TIMEOUT_S）。
    return replace(REGISTRY[task_type], timeout_s=_resolve_timeout_s(settings))


def registered_types() -> frozenset[str]:
    """已注册的任务类型集合（恒等于 `REGISTRY` 的键集合）。"""
    return frozenset(REGISTRY)


def assert_submittable(task_type: str, *, settings: Settings | None = None) -> TaskPolicy:
    """提交前的准入判定：未注册 → `1003`；已注册但 M1 未实现 → `1003`（消息不同）。

    两种失败**共用 `1003` 但消息不同**，因为两者的性质是同一类：请求里的枚举值不在
    **当前可用**范围内。刻意不复用 `3006`（对象不存在）/`3007`（状态不允许该操作）——
    它们在 `core/errors.py` 里有明确定义的对象与状态语义，混用会把"你选了个还没上线的
    类型"说成"资源不存在"或"状态冲突"，前端据此会提示错误的处置动作。

    消息必须可分辨（`design.md:194` 的「避免告警丢失」）：预留位是**预期内**的拒绝
    （M2/M3 上线后自然放行），未注册是**预期外**的输入（可能是调用方拼错、也可能是新类型
    忘了注册）。运维看告警时要能一眼区分，故两条消息 MUST NOT 雷同。

    返回值与 `get_policy` 同形（`TaskPolicy`）：调用方拿到策略后即可用 `timeout_s` /
    `retryable` / `result_schema`，无需二次查表。
    """
    policy = get_policy(task_type, settings=settings)
    if not policy.implemented:
        available = sorted(name for name, item in REGISTRY.items() if item.implemented)
        raise ParamError(
            f"任务类型 {task_type!r} 已注册但 M1 未实现（预留注册位，design.md:190-192）："
            f"M1 可提交的类型为 {available}",
            code=PARAM_VALUE_CODE,
        )
    return policy


__all__ = [
    "REGISTRY",
    "TaskPolicy",
    "assert_submittable",
    "get_policy",
    "registered_types",
]
