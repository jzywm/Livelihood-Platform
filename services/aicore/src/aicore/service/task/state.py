"""任务状态机（**纯函数、无 IO**）。Task 4.5。

## 权威依据（唯一一处，MUST NOT 自创）

`services/aicore/docs/er.md` §7.1 L430 逐字：

> - **约束**：状态机 PROCESSING→SUCCEEDED/FAILED/MANUAL_REVIEW；仅本人可查（2002 越权）；…

`ALLOWED_TRANSITIONS` 就是这句话的**唯一**机器可读形式：**只有 `PROCESSING` 是起点**，
三个终态各自只能从 `PROCESSING` 到达。`tests/unit/test_task_state.py` 有一条用例
**现读 `er.md` 那一行**、从中解析出三元组再与本模块逐项比对——期望值 MUST NOT 抄成常量
（第 3 组 `<= MAX_ID_LENGTH` 假绿的教训：把权威表述抄进测试，测试就只剩「抄得对不对」）。

状态取值与 `docs/openapi.yaml` 的 `TaskStatus` 枚举（L769-773）逐字一致；
落库列是 `ai_task.status`（`er.md` §6.1 L292，MySQL 原生 enum，库侧也会拒非法值）。

## 三条 MUST NOT（每条都对应一种真实事故）

1. **终态 → 终态**：终态意为「已出结论」，`finished_at` 已落。改写结论不是状态转移，
   是**篡改证据**（`er.md` §7.1 的 `model_meta` 血缘快照同此取向：历史结论要能复盘）。
2. **终态 → `PROCESSING`（重开）**：任务重开会让「同一个 taskId 先后有两个结论」，
   而调用方凭 taskId 轮询、凭结论处置——重开等于让已送达的处置依据失效。
3. **同状态自转移（含 `PROCESSING→PROCESSING`）**：它不改变任何事实，却会刷新
   `progress`/`finished_at` 这类副作用字段；把「原地踏步」判成非法，才能让
   `3007` 精确表达「这个动作现在不该发生」。

## 归属与依赖面

本模块只 import `aicore.core.errors` 与 stdlib：状态机是**领域规则**，不得碰仓储、
不得碰具体 Provider（`service` 层与 provider 具体实现的分层见 `.importlinter` 契约 2）。
用例有一条 AST 断言正面钉住这条依赖面。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from aicore.core.errors import PARAM_VALUE_CODE, ConflictError, ParamError

#: 受理中（`er.md` §6.1 L292 的列默认值，也是提交接口的受理状态）。
#:
#: **四个常量都显式标注 `Final[Literal[...]]` 而不是 `Final = "..."`**：默认推断只给到 `str`，
#: 而 `Literal[PROCESSING]`（回执模型的枚举约束）要求注解里的名字本身是字面量类型——
#: 否则 mypy 报 `Parameter 1 of Literal[...] is invalid`，于是「状态取值只有一处定义」
#: 这句话就会在 API 模型那一侧退化成再抄一遍字符串。
PROCESSING: Final[Literal["PROCESSING"]] = "PROCESSING"
#: 成功终态。
SUCCEEDED: Final[Literal["SUCCEEDED"]] = "SUCCEEDED"
#: 失败终态（`error_code` 此时才有值，见 `er.md` §6.1 L294）。
FAILED: Final[Literal["FAILED"]] = "FAILED"
#: 转人工核验终态（C8：AI 只标记、不决策；通道失败或置信度不足即转人工）。
MANUAL_REVIEW: Final[Literal["MANUAL_REVIEW"]] = "MANUAL_REVIEW"

#: 终态集合：到达即不可再转移。
#: 三个取值与 `ALLOWED_TRANSITIONS` 的值集**必然相等**（都由 `er.md` §7.1 那一行决定），
#: 但两者语义不同：前者答「停没停」，后者答「能去哪」，故各自独立成常量，
#: 由用例从权威表述现读后同时钉住。
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({SUCCEEDED, FAILED, MANUAL_REVIEW})

#: 全部合法状态（`openapi.yaml` 的 `TaskStatus` 枚举四个值）。
#: 用途：拒绝未登记取值——**静默放行**会让库里出现枚举以外的状态，
#: 而前端按枚举渲染时只能显示成空白。
ALL_STATUSES: Final[frozenset[str]] = frozenset({PROCESSING, *TERMINAL_STATUSES})

#: 允许的状态转移表（**唯一依据** `er.md` §7.1 L430）。
#: 只登记「起点」：不在表里的起点（即三个终态）一条边都没有，故终态→任何值都被拒。
ALLOWED_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    PROCESSING: frozenset({SUCCEEDED, FAILED, MANUAL_REVIEW}),
}


class IllegalTransitionError(ConflictError):
    """状态转移非法（业务码 **`3007`**，HTTP 409）。

    **为什么是 `3007` 而不是 `1003`**（`core/errors.py:370-384` 的定档理由）：
    走到这里时**请求参数完全合法**——冲突来自**服务端已有状态**（任务已终态）。
    用 `1003`（枚举或范围非法）等于对前端说「你参数写错了」，前端会提示用户改参数，
    而真正的处置是「去看已有结论」；语义错位会让调用方做错事。

    **MUST NOT 用 `1001`/`1002`**：那两个码说的是「没送到」与「格式不对」，
    与「状态不允许」是两件不同的事。`core/errors.py` 已把 `3007` 登记进
    `AICORE_ERROR_CODES`（Task 3.7 起），故本类不新增码值、不动平台的 `ErrorCode` 枚举。
    """


def _require_known(status: str, *, field: str) -> str:
    """校验状态取值已登记；未登记抛 `ParamError(1003)`（枚举或范围非法）。

    **MUST NOT 静默放行**：未知状态若是被当成「不在转移表里」而直接判 3007，
    就把「你给了一个不存在的状态」报成了「服务端状态冲突」，排障方向会被带偏。
    报错文案只点名**字段**与合法取值集合，不回显调用方传进来的原值
    （`core/errors.py` 的口径：响应 message 面向用户，不回显用户输入）。
    """
    if status not in ALL_STATUSES:
        raise ParamError(
            f"未知的任务状态 {field}：合法取值只有 {sorted(ALL_STATUSES)}",
            code=PARAM_VALUE_CODE,
        )
    return status


def assert_transition(current: str, target: str) -> None:
    """断言 `current → target` 合法，否则抛异常（**不返回布尔值**）。

    「合法性检查」做成断言式而不是返回 `bool`：调用方拿到 `False` 之后仍可能继续往下写库，
    而抛异常会把「非法转移」变成一条**不可绕过**的路径。两个入参各自先过取值校验
    （未知取值 → `1003`），再查转移表（非法转移 → `3007`），两档错误语义不混。
    """
    _require_known(current, field="current")
    _require_known(target, field="target")
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise IllegalTransitionError(
            f"任务状态不允许从 {current} 转移到 {target}"
            f"（er.md §7.1：状态机 {PROCESSING}→{SUCCEEDED}/{FAILED}/{MANUAL_REVIEW}）"
        )


def is_terminal(status: str) -> bool:
    """该状态是否终态（`SUCCEEDED` / `FAILED` / `MANUAL_REVIEW`）。

    未知取值返回 `False`（**不抛异常**）：本函数是**判定**而不是**校验**，
    调用方用它决定「要不要继续推进」，此时「不认识」与「还能推进」都意味着"别停"。
    取值合法性由 `assert_transition` 负责——两个函数吃不同的责任，故行为不同。
    """
    return status in TERMINAL_STATUSES
