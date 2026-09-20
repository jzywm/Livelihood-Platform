"""`ai_task`（统一异步 AI 任务，**按月分片**）的数据访问（Task 3.7）。

**权威依据**：`er.md` §7.1（索引 `idx_account_created` / `uk_idem` / `idx_status_created` /
`idx_eval`，约束"仅本人可查"）、§5.2（按月分表、分片键 `account_id` + `created_at`）、
§5.3（查询 MUST 携带分片键下推、禁止跨分片）；spec §2.3 / §5.7。

**两类硬约束在本模块的落点**：

- **R1**：所有读取方法都收 `shard: ShardKey`——分片键就是"哪个月的表"，缺了连表名都算不出来；
  表内的路由键（`task_id`）同样走 Task 3.3 的 `require_shard_key`，
  缺 → `MissingShardKeyError(1001)`。
- **R6**：跨账号越权（`2002`）的判定属 service 层，但本层**只提供带账号过滤的入口**：
  列表的账号取自分片键、幂等键查询的账号是必填参数；**MUST NOT** 提供"只按 `task_id` 查、
  不带账号"的便捷入口——那种入口一旦存在，越权判定就会在某个调用点被忘掉。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar, Final

from sqlalchemy import Update, select, update
from sqlalchemy.orm import Session

from aicore.repository.base import BaseRepo, ShardKey, physical_table
from aicore.repository.models import AiTask
from aicore.repository.sharding import require_shard_key

#: 本模块的逻辑表名：类属性与模块级的语句构造器**共用这一处字面量**，避免两处漂移。
TASK_LOGICAL_TABLE: Final[str] = "ai_task"


def status_update_statement(
    month: str,
    task_id: str,
    *,
    status: str,
    progress: int,
    finished_at: datetime | None,
    error_code: str | None = None,
) -> Update:
    """构造"只更新 status / progress / finished_at（+ 可选 error_code）"的语句
    （`ai_task_<month>`）。

    **为什么要单独有这个构造器**（而不是把语句写在 `update_status` 里）："只更新允许的列"
    是一条**可以被机械检查**的约束——语句一旦成对象，用例就能断言它的 SET 列集合恰好是那三列
    （或四列），而不是靠人去读方法体。故这里刻意留出一个纯函数接缝：输入是月份与目标值、
    输出是语句，没有会话、没有副作用。

    三个列名 MUST 逐个写出来，MUST NOT 用 `session.merge(entity)` 这类整行覆盖写法：
    `merge` 会把内存里那份实体的 `created_at` / `model_meta` / `is_eval_sample` 一起写回，
    等于拿调用方手里的旧快照覆盖库里的现状（`model_meta` 是血缘快照，覆盖掉再也回不来）。

    ## `error_code`：**仅当非 `None` 时才进列清单**（Task 4.7 修复轮授权的最小改动）

    `er.md` §6.1 L294 把该列定义为「FAILED 业务码」（`4003` 通道失败 / `5002` 依赖超时），
    而 Task 4.11 要求「`4003` 与 `5002` 分别计数」——那正是靠这一列。
    在此之前本构造器的列集合是**写死的三列**，于是 `FAILED` 行上的 `error_code` 永远是 NULL，
    4.11 拿不到计数依据。

    两条硬要求：

    - **不传时不出现该列**：既有的三个调用方（`begin_attempt` / `mark_succeeded` /
      `requeue`）的 SQL **逐字不变**（列集合仍是三列），故它们的既有用例与行为都不受影响；
    - **传了时恰好四列**：只有 `FAILED` 终态写回那一处带它。
    """
    table = physical_table(TASK_LOGICAL_TABLE, month)
    values: dict[str, object] = {
        "status": status,
        "progress": progress,
        "finished_at": finished_at,
    }
    if error_code is not None:
        values["error_code"] = error_code
    return update(table).where(table.c.task_id == task_id).values(**values)


class TaskRepo(BaseRepo[AiTask]):
    """`ai_task` 的读写仓储（分片表：物理名 `ai_task_YYYYMM`）。"""

    logical_table: ClassVar[str] = TASK_LOGICAL_TABLE
    model = AiTask

    def insert(self, session: Session, entity: AiTask) -> None:
        """写入任务；物理表 = `entity.created_at` 所在月。

        **分片月直接由 `entity.created_at` 现算**：被写入的 `created_at` 值与用来算月份的是
        **同一个字段**，故结构上不存在"写进 A 月、但值是 B 月"的漂移。代价是调用方 MUST 给
        非空且带时区的 `created_at`（naive / 缺省一律 `ParamError(1002)`）——这正是想要的
        fail fast：若指望库的 `DEFAULT CURRENT_TIMESTAMP(3)` 兜底，月份就无从算起了。
        """
        key = ShardKey(account_id=entity.account_id, created_at=entity.created_at)
        self._insert(session, key, entity)

    def get_by_id(self, session: Session, task_id: str, *, shard: ShardKey) -> AiTask | None:
        """按 `task_id` 取任务（R1：必须带分片键）。

        `task_id` 是主键，故语句带 `limit 1`；缺 `task_id` 抛 `MissingShardKeyError(1001)`，
        而不是把空串当成一个合法的任务号去查（那会静默返回 `None`，让"参数没送到"看起来
        像"任务不存在"）。
        """
        require_shard_key(task_id, field="task_id")
        table = self._table(shard)
        return self._select_one(session, select(table).where(table.c.task_id == task_id).limit(1))

    def list_by_account(
        self,
        session: Session,
        *,
        shard: ShardKey,
        limit: int,
        offset: int,
    ) -> Sequence[AiTask]:
        """本人任务列表（R6：账号过滤取自分片键，调用方**无法**"忘了带账号"）。

        排序 `created_at DESC, task_id DESC` 对齐 `idx_account_created(account_id, created_at)`
        （er.md §7.1 的"分片键剪枝 + 本人任务列表"）。第二个排序键是必要的：同一毫秒创建的两条
        任务若没有稳定的次排序键，翻页会出现漏行或重复行。
        """
        table = self._table(shard)
        statement = (
            select(table)
            .where(table.c.account_id == shard.account_id)
            .order_by(table.c.created_at.desc(), table.c.task_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._select_many(session, statement)

    def update_status(
        self,
        session: Session,
        task_id: str,
        *,
        shard: ShardKey,
        status: str,
        progress: int,
        finished_at: datetime | None,
        error_code: str | None = None,
    ) -> int:
        """只更新 `status` / `progress` / `finished_at`（+ 可选 `error_code`），
        返回**受影响行数**。

        语句由 `status_update_statement` 构造（"只更新允许的列"因此可被用例机械检查），
        见该函数的 docstring：MUST NOT 用 `merge` 整行覆盖。
        `error_code` **不传时列集合仍是三列**（既有调用方的 SQL 逐字不变），
        传了才是四列——用途与口径见 `status_update_statement` 的 docstring。

        **返回值的口径（本栈实测，与"裸 MySQL 默认"不同）**：`CursorResult.rowcount` 在
        SQLAlchemy 的 MySQL 方言下是**匹配行数**（不是变更行数）——方言在连接时硬编码加上了
        `CLIENT.FOUND_ROWS`（见 `sqlalchemy/dialects/mysql/base.py` 的 "rowcount Support"
        一节），这与 pymysql 自己的默认口径**相反**。实测（`aicore_test`，SQLAlchemy 2.0.54 +
        pymysql）：同值重复更新返回 **1**、不存在的行返回 **0**。

        故调用方拿它判断"是否存在"是可靠的（0 即没有这一行）；但**MUST NOT** 反过来把 1
        当成"值一定发生了改变"（同值重放也是 1）。这条口径差异值得写下来：按裸 MySQL 的
        默认语义写代码的人会以为同值更新返回 0。

        **调用方 MUST 检查这个返回值**（Task 4.7 修复轮 A5(c)）：`0` 意味着**那一行不存在**
        （分片打错月、任务号拼错），此时"写成功"的判断是错的——行会留在原状态等重放。
        """
        require_shard_key(task_id, field="task_id")
        statement = status_update_statement(
            shard.month,
            task_id,
            status=status,
            progress=progress,
            finished_at=finished_at,
            error_code=error_code,
        )
        return self._update(session, statement)

    def find_by_idem_key(
        self,
        session: Session,
        *,
        shard: ShardKey,
        account_id: str,
        idem_key: str,
    ) -> AiTask | None:
        """按 `uk_idem(account_id, idem_key)` 查同月表内的幂等键（er.md §7.1）。

        用途：同 `imageKey` + `docType` 重复提交 OCR 时返回**原任务号**。

        **账号是必填参数（R6）**：`uk_idem` 是两列唯一键，只按 `idem_key` 查会让 A 账号的
        幂等键命中 B 账号的任务，故本方法**没有**不带账号的重载。

        `shard` 与 `account_id` 是**两个独立事实源**（前者决定物理表、后者是行级过滤）：
        本层不强制二者一致——物理分片只按**月份**切，`account_id` 不参与分片，
        故"分片键里的账号 ≠ 过滤用的账号"在语义上并非错误（B 账号 7 月的任务同样落在
        `ai_task_202607`），是否一致由调用方（service 层）保证。
        """
        require_shard_key(account_id, field="account_id")
        require_shard_key(idem_key, field="idem_key")
        table = self._table(shard)
        statement = (
            select(table)
            .where(table.c.account_id == account_id, table.c.idem_key == idem_key)
            .limit(1)
        )
        return self._select_one(session, statement)
