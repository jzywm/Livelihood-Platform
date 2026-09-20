"""任务查询回执（K-02）。Task 4.5。

**契约来源**：`docs/openapi.yaml` 的 `/aicore/tasks/{taskId}`（L107-155）与 `TaskResult`
（L787-825）；归属口径来自 `spec.md:23-35`（仅本人可查、跨账号 `2002`）。

## 本模块只做三件事（取行与越权判定都不在这里）

1. 从请求头取身份（`api/deps.py::get_account_id`）；
2. 用**主库只读会话**（`primary_read_session()`）经 service 取任务快照；
3. 把快照拼成 `TaskResult` 并塞进平台信封。

「按任务号取行 + 比账号」属 **service**（`service/task/query.py`）：`.importlinter` 契约 1
禁止 `api` 直接依赖 `repository`（`design.md` 禁止项 1：「路由只调 service」），
而 `repository/base.py` 的 R6 也把越权判定定在 service 层。故这里
**MUST NOT** import 任何 `aicore.repository.*`。

## 三项硬口径

1. **会话用 `primary_read_session()`（写后立即读走主库）**：`er.md:252` 逐字
   「关键**写后立即读**（**任务提交后立即轮询**、复核后立即查状态）**强制走主库**，
   避免主从延迟读到旧状态」。轮询正是这句话点名的第一类路径——刚受理的任务若从从库读，
   表现为「受理成功但查询 404」。MUST NOT 用 `read_session()`：`repository/session.py:243-249`
   会在会话被标记为写后立即读时抛 `ParamError(1002)`，那正是本条要拦的形态。
2. **未找到 / 跨账号的区分**：`3006`（HTTP 404）与 `2002`（HTTP 403），判定在 service
   （见 `service/task/query.py` 的模块 docstring：必须先取行、再比账号）。本模块
   **不写任何把行内容带进日志或响应的语句**——跨账号时连 `status`/`progress` 都不给
   （`spec.md:35` 按最严解读）。
3. **`result` 恒为 `null`**：`OcrResult` 的装配属 Task 5.6（本任务只做提交与轮询回执骨架）。
   MUST NOT 把它读成「任务永远没有结果」——`result` 是**本任务边界内**为空，
   `SUCCEEDED` 时该字段由 Task 5.6 按 `ai_task.type` 取对应结果结构填充。

## 已知边界（如实登记，MUST NOT 当成已解决）

**查询窗口是「当前月」**：`ai_task` 按月分表，而 `taskId` 是「`task_` + UUID」、
**不含时间戳**（`er.md` §5.4 L248 定档），故单凭任务号推不出它在哪张月表。
本工单的口径是「本月表」（§2.4 的 3006 一行逐字「`task_id` 在**本月表**内不存在」），
即用**当前时刻**定位分片月。后果：**跨月轮询不成立**——上月提交、下月查询会得到 `404`
（任务其实还在上月表里）。要收口需要一个查询窗口（如「当月 + 上月」两次单分片点查，
或一张 `task_id → 月份` 的路由表），那不属本工单，故**没有**在这里自行扩大扫描范围
（跨月扫描会撞 `er.md` §5.3「跨月查询禁全表扫描 UNION」）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final, Literal, cast

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from aicore.api.deps import SessionFactory, get_account_id, get_engine_factory, get_now
from aicore.core.envelope import Envelope
from aicore.service.task.query import TaskSnapshot, load_owned_task
from aicore.service.task.state import (
    FAILED,
    MANUAL_REVIEW,
    PROCESSING,
    SUCCEEDED,
    is_terminal,
)

#: 任务类型取值域（`openapi.yaml` 的 `TaskType`，L764-768 逐字）。
#: 它是**响应模型**的枚举约束：`ai_task.type` 列在库里也是原生 enum，两层对得上，
#: 才不至于把「库里没有的值」原样发给前端。**任务类型注册表**（哪个类型对应哪个处理器、
#: 结果结构与超时）归 `service/task/registry.py`（Task 4.7），本类型别名只管 API 形状。
type TaskTypeValue = Literal["OCR", "VISION_REVIEW", "KITCHEN_ANOMALY", "RISK_PREDICT"]

#: 状态取值域：**被迫重抄的字符串** + 两道接线。
#:
#: mypy 不接受 `Literal[PROCESSING]`（`Final` 变量不能作 `Literal` 参数），
#: 故 `Literal[...]` 里只能写字面量，`service/task/state.py` 的四个常量因此在这里重抄一遍。
#: 两个方向都接住了，不会静默漂移：
#:
#: - **mypy**：下面的 `DECLARED_STATUSES` 把四个常量赋给 `TaskStatusValue`——
#:   谁改了常量的取值（如 `PROCESSING = "RUNNING"`），那一行立刻报类型错；
#: - **用例**：`tests/api/test_task_poll.py` 断言 `set(DECLARED_STATUSES) == ALL_STATUSES`
#:   —— 谁往 `state.py` 加了第五个状态，用例立刻红。
type TaskStatusValue = Literal["PROCESSING", "SUCCEEDED", "FAILED", "MANUAL_REVIEW"]

#: 本回执承认的全部状态（顺序即 `state.py` 的声明顺序）。
#: 运行期用途是上面那条用例的比对基准；类型上它同时是 mypy 的接线点。
DECLARED_STATUSES: Final[tuple[TaskStatusValue, ...]] = (
    PROCESSING,
    SUCCEEDED,
    FAILED,
    MANUAL_REVIEW,
)

#: UTC ISO 8601 的后缀替换对（与 `core/envelope.py::utc_timestamp` 同一口径）。
_ISO_SUFFIX: Final = "+00:00"
_ISO_ZULU: Final = "Z"


class TaskResult(BaseModel):
    """轮询回执（`openapi.yaml:787-825`）。字段名 MUST 保持 camelCase。

    三处逐字口径：

    - `progress` 是 `0~100` 的整数（L798-804）；
    - `errorCode` 是 **string**（L812-815）——不是数字。`er.md` §6.1 L294 的
      `error_code varchar(16)` 也是字符串列，两层一致才不会出现 `4003` / `"4003"` 两种形状；
    - `result` 在 `PROCESSING` 与 `FAILED` 时为空（L806 逐字），**本任务恒为 `None`**
      （见模块 docstring 的已知边界）。

    必填集合逐字对齐 L789 的 `required: [taskId, type, status, createdAt]`：
    其余四个字段在 schema 里是可选的，故在模型里给默认值——契约的可选性是形状的一部分，
    把它们写成必填会与 openapi 的 `required` 列表对不上。
    """

    taskId: str  # noqa: N815 —— 平台契约字段名就是 camelCase（同 core/envelope.py 的 traceId）
    type: TaskTypeValue
    status: TaskStatusValue
    progress: int | None = Field(default=None, ge=0, le=100)
    result: None = None
    errorCode: str | None = None  # noqa: N815
    createdAt: str  # noqa: N815
    finishedAt: str | None = None  # noqa: N815


router = APIRouter(prefix="/aicore", tags=["task"])


@router.get(
    "/tasks/{taskId}",
    response_model=Envelope[TaskResult],
    summary="查询异步 AI 任务进度与结果【M1 · K-02】",
)
async def get_task(
    task_id: Annotated[str, Path(alias="taskId")],
    account_id: Annotated[str, Depends(get_account_id)],
    factory: Annotated[SessionFactory, Depends(get_engine_factory)],
    now: Annotated[datetime, Depends(get_now)],
) -> Envelope[TaskResult]:
    """按任务号查进度与结果：**仅限本人**，跨账号 `2002`，不存在 `3006`。

    `task_id` 用 `Path(alias="taskId")` 接住 openapi 的 camelCase 路径参数名
    （Python 参数名保持 snake_case，故不需要 `# noqa: N803`）。

    `now` 用来定位分片月（见模块 docstring 的已知边界：查询窗口是当前月）。

    `factory` 只用到 `primary_read_session()` —— 本接口是**读**路径，
    但它是「写后立即读」形态（见模块 docstring 第 1 条），故 MUST NOT 用从库会话。
    """
    snapshot: TaskSnapshot = await run_in_threadpool(
        _load_in_session,
        factory,
        task_id=task_id,
        account_id=account_id,
        now=now,
    )
    return Envelope[TaskResult].ok(_to_result(snapshot))


def _load_in_session(
    factory: SessionFactory,
    *,
    task_id: str,
    account_id: str,
    now: datetime,
) -> TaskSnapshot:
    """在工作线程里开**主库只读会话**取快照（同步函数，故经 `run_in_threadpool` 调用）。

    - **主库只读会话**：`er.md:252` 的「任务提交后立即轮询」；
    - **在同一个线程内开与关**：连接有线程亲和性（`sqlite3` 的 `check_same_thread` 会直接拦），
      故 `with` 必须整体在工作线程里闭合；
    - **归属判定与取行都在 service**：本函数只负责「给会话、传参、交回快照」，
      不存在与不存在但非本人两种情况由 `load_owned_task` 抛
      `NotFoundError(3006)` / `ForbiddenError(2002)`，本模块不复制那份判定。
    """
    with factory.primary_read_session() as session:
        return load_owned_task(session, task_id=task_id, account_id=account_id, now=now)


def _to_result(snapshot: TaskSnapshot) -> TaskResult:
    """快照 → 回执模型（时间转 UTC ISO 8601）。

    `finishedAt` **只在终态有值**（`openapi.yaml:824` 逐字「完成时间
    （SUCCEEDED/FAILED/MANUAL_REVIEW 时）」）：库列在非终态就是 NULL，
    这里再按状态校一次是为了挡住「非终态却写了 `finished_at`」这种脏数据被原样透出——
    那会让前端把「还在跑」的任务渲染成「已完成」。
    终态判定转发 `service/task/state.py::is_terminal`（领域规则只有一处实现，
    MUST NOT 在这里重写一份 `status in {...}`）。
    """
    return TaskResult(
        taskId=snapshot.task_id,
        # cast 的理由：快照交回的是 `str`（列是 varchar / 原生 enum），而回执模型的字段是
        # 字面量类型。**这不是把校验绕过去**——pydantic 仍按字面量集合校验，
        # 库里的值若越出 `TaskType` / `TaskStatus` 枚举，本行会在运行期抛 ValidationError
        # （经兜底处理器成 5000），MUST NOT 换成「值不对就回个默认值」的兜底。
        type=cast("TaskTypeValue", snapshot.task_type),
        status=cast("TaskStatusValue", snapshot.status),
        progress=snapshot.progress,
        result=None,
        errorCode=snapshot.error_code,
        createdAt=_utc_iso(snapshot.created_at) or "",
        finishedAt=_utc_iso(snapshot.finished_at) if is_terminal(snapshot.status) else None,
    )


def _utc_iso(value: datetime | None) -> str | None:
    """时间 → **UTC ISO 8601**（`Z` 结尾），与 `_common/openapi.yaml` 的 `timestamp` 同形。

    库里的值可能是两种形态，都要收口到同一种输出：

    - **naive**：MySQL `DATETIME` 不存时区（`models.py` 偏差 2 明确不写 `timezone=True`），
      而 `er.md` §6 通用约定是「**UTC 存储**」——故 naive 值按 UTC 解释。
      这是**约定**而非猜测：库里存的就是 UTC，只是驱动不带时区信息；
    - **aware**：先 `astimezone(UTC)` 再渲染，避免输出成 `+08:00` 这种与契约不符的形状。

    渲染方式与 `core/envelope.py::utc_timestamp` 逐字一致（`isoformat()` 再把 `+00:00` 换成 `Z`）：
    全服务的时间戳形状只允许有一种，前端与日志解析才不必各写一套。
    """
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace(_ISO_SUFFIX, _ISO_ZULU)
