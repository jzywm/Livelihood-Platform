"""任务读取与归属判定（K-02 轮询的 service 侧）。Task 4.5。

## 为什么这里必须存在一个 service 函数（而不是让路由直接查仓储）

`.importlinter` 契约 1 逐字：**「api 层不得直接依赖 repository / provider」**
（`design.md` 禁止项 1：「api/ MUST NOT **直接导入** repository/ 或 provider/
——路由只调 service」）。
轮询要按任务号取一行、再比账号，若这段逻辑写在 `api/tasks.py` 里，就必须 import
`repository.base` / `repository.models` / `repository.task_repo` —— 契约当场 BROKEN
（实测：`aicore.api.tasks -> aicore.repository.base / .models / .task_repo` 三条边）。

**「越权判定属 service 层」不是本模块的发明**：`repository/base.py` 的 R6 逐字写着
「跨账号越权（`2002`）的判定属 **service** 层，但本层**只提供带账号过滤的入口**」。
故本模块是这句话的落点，`api/tasks.py` 只做「取快照 → 拼回执」。

## 为什么返回快照（DTO）而不是 ORM 实体

`TaskSnapshot` 只装**回执需要的列**，不是 `AiTask` 的复本：

- **依赖面**：api 层拿到的类型来自 service，故 `api → repository` 这条边在结构上不存在
  （用实体就得在 api 侧 import `AiTask` 做类型注解，注解也算依赖）；
- **输出白名单**：`account_id`、`idem_key`、`model_meta`、`is_eval_sample` 这些内部列
  **根本不进快照**，于是「哪些列可能出现在响应里」是一份可审的清单，
  而不是「谁顺手加了个字段」（跨账号泄露的红线因此多一道结构性保险）。

## 分片月怎么来（`er.md` §5.4 v1.3，2026-09-19 定档）

`task_id` **自描述创建月**（`task_` + `YYYYMM` + UUID hex，总长恒 32），故本模块用
`idgen.task_month_of(task_id)` 定位物理表，**MUST NOT 用当前时刻现算分片月**。

改用月份自描述之前，查询窗口被钉在"本月"，后果是**上月 23:59:59 提交的任务，
次月 00:00:01 轮询即 404**——而逐月试探扫描被 `er.md` §5.3
「查询 MUST 携带分片键下推、禁止跨分片」直接禁止。
`YYYYMM` 是**创建时由 `created_at` 冻结进字符串的业务标签**，此后不再从时钟推导，
故不构成"依赖内嵌时间戳"（那条禁的是雪花式毫秒时间戳，见 `er.md` §5.4 的口径澄清）。

判定顺序：**先取行**（不存在 → `3006`），**再比账号**（不是本人 → `2002`）。
不能反过来「带本人账号查」：分片只按月份切，别人的任务与本人**在同一张月表**里，
带账号过滤会把「是别人的」与「不存在」压成同一个 `None`，于是越权只能报成 404，
调用方无法区分「任务号写错」与「任务不是你的」——`spec.md:32-35` 要的正是后者报 `2002`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from aicore.core.errors import (
    PARAM_VALUE_CODE,
    ForbiddenError,
    NotFoundError,
    ParamError,
)
from aicore.core.idgen import ID_PREFIX_LENGTHS, MAX_ID_LENGTH, task_month_of
from aicore.repository.base import ShardKey
from aicore.repository.models import AiTask
from aicore.repository.task_repo import TaskRepo


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """轮询回执所需的任务快照（service → api 的 DTO，见模块 docstring 的输出白名单）。

    字段名用 snake_case（Python 侧口径）；camelCase 是 **api 层**的契约形状，
    由 `api/tasks.py` 的 pydantic 模型负责，两层的命名约定不在中间层混淆。
    """

    task_id: str
    task_type: str
    status: str
    progress: int
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


def snapshot_of(task: AiTask) -> TaskSnapshot:
    """实体 → 快照（**输出白名单的唯一落点**：只有这里列出的列能流向响应）。

    单独成一个函数而不是写在 `load_owned_task` 里：它是「哪些列可以外发」这条规则的
    唯一实现处，测试可以直接对着一行实体断言快照的字段集合（加字段即失败）。
    """
    return TaskSnapshot(
        task_id=task.task_id,
        task_type=task.type,
        status=task.status,
        progress=task.progress,
        error_code=task.error_code,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )


def load_owned_task(
    session: Session,
    *,
    task_id: str,
    account_id: str,
    now: datetime,
) -> TaskSnapshot:
    """按任务号取行并判定归属，返回快照。

    - 行不存在 → `NotFoundError`（`3006`，HTTP 404）；
    - 行存在但不是本人提交 → `ForbiddenError`（`2002`，HTTP 403），且**不做任何别的动作**：
      MUST NOT 把行内容写进日志或异常文案（`spec.md:35`：不泄露该任务的任何结果内容）。

    ## 分片月从 `task_id` 解析（`er.md` §5.4 v1.3，2026-09-19）

    **`task_id` 自描述创建月**（`task_` + `YYYYMM` + UUID hex），故这里用
    `idgen.task_month_of(task_id)` 得出的月份去定位物理表，
    **MUST NOT 用 `now` 当分片键的 `created_at`**——那样查询窗口被钉在"本月"，
    表现为**上月 23:59:59 提交的任务，次月 00:00:01 轮询即 404**；
    而逐月试探扫描被 `er.md` §5.3「查询 MUST 携带分片键下推、禁止跨分片」直接禁止。

    `now` 参数因此**只作诊断/未来扩展用**（当前实现不依赖它定位分片）——
    保留形参是为了不动调用方签名；若你认为该删，MUST 在报告里说明。

    `task_id` 形态非法时抛 `ParamError(1003)`：它是**入参格式错误**，
    不是"任务不存在"（`3006`）——把它报成 404 会让调用方以为任务丢了。

    `session` 由调用方给出（路由传进来的是 `primary_read_session()`：**写后立即读走主库**，
    `er.md:252` 点名的「任务提交后立即轮询」正是这条路径）；本层 MUST NOT 自开引擎或会话
    （`repository/base.py` R3）。
    """
    try:
        month = task_month_of(task_id)
    except ValueError:
        raise ParamError(
            f"任务号形态非法：期望 `task_` + 6 位创建月（YYYYMM）+ "
            f"{ID_PREFIX_LENGTHS['task']} 位小写 hex，总长 {MAX_ID_LENGTH}"
            f"（er.md §5.4）",
            code=PARAM_VALUE_CODE,
        ) from None
    # 分片键的 `created_at` 只需**落在目标月内**即可定位到同一张物理表（`ShardKey` 只用它算月）。
    # 用该月 1 日 00:00 UTC 构造：月份来自 task_id，不是"当前时间"，故跨月轮询成立。
    at = datetime(int(month[:4]), int(month[4:]), 1, tzinfo=UTC)
    task = TaskRepo().get_by_id(
        session,
        task_id,
        shard=ShardKey(account_id=account_id, created_at=at),
    )
    if task is None:
        raise NotFoundError()
    if task.account_id != account_id:
        raise ForbiddenError()
    return snapshot_of(task)
