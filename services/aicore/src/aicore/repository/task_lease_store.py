"""`ai_task` 的**执行侧**数据访问：扫可领取任务 + 四个状态写回（Task 4.7）。

## 为什么新增一个文件，而不是改 `repository/task_repo.py`

`TaskRepo` 是 Task 3.7 已验收的产物，本任务不该动它；而「扫描可领取任务」这条 SQL 的
执行侧关切（终态过滤、`OrderBy`、`limit` 下推、只扫当月）与 3.7 的读写关切不同，
分开更清楚。四个写方法**复用** `TaskRepo.update_status`（既有能力，MUST NOT 重写一遍
UPDATE 语句——两处 UPDATE 的列集合一旦漂移，`TaskRepo` 那条「只更新允许的列」的用例
就守不住本模块写的那份）。

## 权威依据

- `er.md` §7.1 L425-435：索引 `idx_status_created(status, created_at)` 正是为「按状态扫待办、
  按创建时间排序」建的，故 `list_claimable` 的 `WHERE status = ? ORDER BY created_at`
  必须与它对齐（顺序反了就用不上索引，退化成全表扫描 + filesort）；
- `er.md` §5.3：查询 MUST 携带**分片键下推**，禁止跨分片扫描 → 本模块**只查当月**；
- `er.md` §5.5 L252：**写后立即读走主库** → 写方法用 `write_session()`、
  `list_claimable` 用 `primary_read_session()`（执行器扫完紧接着就要改这一行，
  从从库读到旧状态会让已终态的行被再次领走）；
- `er.md` §6.1 L284-298：各列语义（`progress` 是进度百分比；`error_code` 是 **FAILED 业务码**；
  `finished_at` 只在终态时才有值）。

## 状态字面量为什么在本文件里**就地声明**（不是从 `service/task/state.py` 导入）

`.importlinter` **契约 3**（`repository / provider / port 不得反向依赖 service`）把
`repository -> aicore.service` 判为违规，且**未开 `allow_indirect_imports`**——
`from aicore.service.task.state import PROCESSING` 会让契约当场 BROKEN
（实测报出 `aicore.repository.task_lease_store -> aicore.service.task.state`）。
而 `Status` 的**权威定义**确实是 `service/task/state.py`（Task 4.5 的产物，本任务不可改）。

故此处只声明**本模块写库时要用的三个字面量**，并在此点名权威出处：

- 它们**不是第二份状态机**：本模块没有任何转移规则、没有 `ALLOWED_TRANSITIONS`；
  「哪条转移合法」仍然只有 `service/task/state.py` 一处；
- 落库列的**权威约束在数据库侧**：`ai_task.status` 是原生 MySQL ENUM
  （`validate_strings=True`，见 `repository/models.py`），写错值会被库直接拒绝——
  这不是「靠约定对齐」，而是一条真实的、不可绕过的门禁；
- 三处一致性（本文件 / `state.py` / `er.md` / DDL / ORM 模型）由
  **`tests/repository/test_task_lease_store.py` 现读后逐字比对**——该文件由 Task 4.7
  修复轮补齐（A7：此前这句承诺指向一个**不存在**的文件，等于一条没有落点的防线）。
  **不导入**不等于**不校验**。

## `error_code` 已可落库（B3 闭合后更新）

`mark_failed` 现在**真的写** `ai_task.error_code`：Task 4.7 修复轮获得授权，
给 `TaskRepo.update_status` / `status_update_statement` 加了一个**可选**的
`error_code` 形参（不传时列集合仍是三列，既有三个调用方的 SQL 逐字不变）。
Task 4.11 的「`4003` / `5002` 分别计数」据此可用。
（此前那一段"缺口登记"与 WARNING 日志已随修复一起删除。）

## 写回时 `rowcount == 0` 会抛错（A5(c)）

`_write_back` 与 `mark_failed` 都检查 `TaskRepo.update_status` 的返回值：
`0` 意味着**那一行不存在**（分片月打错 / 任务号不对），此时"写成功"的判断是错的——
执行器会释放租约，而行仍留在旧状态等重放（可能重复调用付费通道）。
故抛 `TaskRowMissingError`，让失败**可见**。

## 一处结构性的口径，MUST 先看懂（否则会误以为这里写错了）

`TaskStore.list_claimable` 的签名只有 `limit` 与 `now`（工单 §2.5 逐字），**没有账号**。
但 `ShardKey` 需要 `(account_id, created_at)` 两个值。本模块的处置是把两个字段
**各取各的来源**：

| 字段 | 来源 | 作用 | 是否影响物理表名 |
|---|---|---|---|
| `account_id` | 哨兵 `SCAN_ACCOUNT_SENTINEL` | 仅作「本行过滤了哪个账号」的占位 | **否** |
| `created_at` | 调用方给的 `now` | 决定查哪个月的物理表 | **是** |

**这张表是本节的关键**：`ShardKey.month` 是 `shard_month_of(self.created_at)` 的派生属性
（`repository/base.py`），**`account_id` 完全不参与月份计算**——`physical_table_name` 的判据
只有 `created_at`（`er.md` §5.2：物理分片只按**月份**切，账号不参与分片）。
故哨兵不会把 SQL 打到别的表上；而 `TaskRepo.update_status` 的 `require_shard_key(task_id)`
与 `ShardKey` 的构造期校验（非空 + aware）都照常生效。

**为什么不允许「按账号扫」**：提交侧写入时 `created_at` 就是 `ai_task.created_at` 的取值，
执行侧扫描用的是**同一个字段**，故两边的月份必然一致（同一条行不会跨月）。若改成按账号扫，
就必须给 `list_claimable` 加一个账号参数——那会改工单给定的接口，而且执行器**不知道有哪些账号**。

## ★ 曾经的缺口：`mark_failed` 的 `error_code` **没有落库**（已闭合，本节保留成因）

> **本节此前逐字标题为「已知缺口：`mark_failed` 的 `error_code` **没有落库**（如实登记）」。**
> 那句话在本轮之前是对的，之后就不对了——但正文在 §43 更新时只改了一处，
> **旧的"缺口"章节被留了下来**，于是同一个文件里同时存在"落不了库"与"已可落库"两种说法
> （复核者把它记为"自相矛盾"）。现按实际状态改正，并把成因保留下来备查。

工单 §2.6 逐字要求「四个写方法用 `TaskRepo.update_status`（**既有能力，MUST 复用**）」，
而 `TaskRepo.update_status` 原本的列集合**只有 `status` / `progress` / `finished_at`**
（`task_repo.py` 的 `status_update_statement`；Task 3.7 有一条用例**逐列钉住**那三列），
签名里**没有** `error_code`。

三条要求同时成立时只剩一种可能：**不改 `task_repo.py` 就写不了 `error_code`**。
故当时的实现是"收下参数但落不了库"，并记一条 WARNING + 在报告里点名。

**本轮（Task 4.7 修复轮，B3）获得授权后按原计划补齐**：`status_update_statement` 的
`.values(...)` 增加一个**可选**列、`update_status` 增加 `error_code: str | None = None` 形参；
Task 3.7 的"恰好三列"用例**原样保留**，另加一条"传了就恰好四列且值正确"的用例。
WARNING 与"落不了库"的说明随修复一起删除。

## 依赖面（契约 3）

只 import `aicore.core.*` 与 `aicore.repository.*`。MUST NOT import `aicore.service` /
`aicore.provider` / `aicore.api`（契约 3 / 4）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from aicore.core.task_runner import ClaimedTask
from aicore.repository.base import ShardKey, physical_table
from aicore.repository.models import AiTask
from aicore.repository.session import EngineFactory
from aicore.repository.task_repo import TASK_LOGICAL_TABLE, TaskRepo

__all__ = [
    "BEGUN_PROGRESS",
    "FAILED_STATUS",
    "FINISHED_PROGRESS",
    "PROCESSING_STATUS",
    "REQUEUED_PROGRESS",
    "SCAN_ACCOUNT_SENTINEL",
    "SUCCEEDED_STATUS",
    "SqlTaskLeaseStore",
    "TaskRowMissingError",
    "current_month_of",
]

_logger = logging.getLogger(__name__)


class TaskRowMissingError(RuntimeError):
    """写回状态时**一行都没匹配到**（`rowcount == 0`）：那一行不存在（A5(c)）。

    抛 `RuntimeError` 而不是 `AiCoreError` 的某个业务码：这不是"调用方的请求有问题"，
    而是**服务端内部状态不一致**（分片月算错 / 任务号不对 / 行被别处删了）。
    按 `core/errors.py` 的口径，这类"内部缺陷"应当走 `5000` 那一档——
    而它由执行器上层的 `_track._settle` 记成 ERROR 并让任务留在原状态等租约回收；
    这里抛出的目的正是**不让执行器以为写成功了**（那会导致释放租约 + 行留在旧状态）。
    """

# ---------------------------------------------------------------------------
# 写库用的状态字面量（权威定义在 `service/task/state.py`，本模块**不导入**它——
# 理由见模块 docstring「状态字面量为什么在本文件里就地声明」一节）。
#
# 落地约束是数据库侧的原生 ENUM（`repository/models.py` 的 `ai_task.status`），
# 三处一致性（本文件 / state.py / er.md §6.1）由
# `tests/repository/test_task_lease_store.py` 现读后逐字比对。
# ---------------------------------------------------------------------------
#: 受理中 / 处理中（`er.md` §6.1 L292 的列默认值）。
PROCESSING_STATUS: Final = "PROCESSING"
#: 成功终态。
SUCCEEDED_STATUS: Final = "SUCCEEDED"
#: 失败终态（`error_code` 此时才有值，见 `er.md` §6.1 L294）。
FAILED_STATUS: Final = "FAILED"

#: 扫描用的账号哨兵。**它不是「某个账号」**：月度扫描本质上不带账号过滤
#: （见模块 docstring 的说明表），而 `ShardKey` 需要一个非空账号。
#: 取值形如 `<scan>`，与真实账号（`er.md` §5.4 的账号 ID 形态）不可能撞车，
#: 故它一旦出现在日志/报错里，一眼可辨「这是扫描路径，不是某个账号的行级过滤」。
SCAN_ACCOUNT_SENTINEL: Final = "<scan-all-accounts>"

#: 领取时写回的进度（`er.md` §6.1 L293：进度百分比，刚领到即已开始）。
BEGUN_PROGRESS: Final = 1

#: 成功终态的进度（工单 §2.5 硬约束 6 逐字 `progress=100`）。
FINISHED_PROGRESS: Final = 100

#: 重新排队时写回的进度（工单 §2.6 逐字 `progress=0`）。
REQUEUED_PROGRESS: Final = 0


def current_month_of(now: datetime) -> str:
    """`now` 所在的分片月 `YYYYMM`（**先归一到 UTC**，借 `repository` 侧的 `ShardKey`）。

    **为什么单独抽出来**：它是「扫描月」的**唯一**判据，而本模块的两条路径（未来若加
    「按账号扫」等入口）必须用同一个月份口径。实现上刻意走 `ShardKey` 的 `month` 派生属性
    而不是自己 `strftime("%Y%m")`：时区归一与 naive 拒绝的规则只允许有一处实现
    （`repository/sharding.py` 的 `shard_month_of`），自己写一份就会漂移，
    而漂移的表现是「扫描打到另一个月的表上」（表存在、查询永远落空）。

    `account_id` 传哨兵：它不参与月份计算（见模块 docstring 的说明表）。
    """
    return ShardKey(account_id=SCAN_ACCOUNT_SENTINEL, created_at=now).month


class SqlTaskLeaseStore:
    """`TaskStore` 的 SQL 实现（**每张月表一次查询**，分片键下推，禁跨分片）。

    四个写方法**全部经 `TaskRepo.update_status`**（既有能力，MUST NOT 另写 UPDATE）：
    本类只负责「写哪一列、写什么值、用哪个会话」，语句构造归 `TaskRepo`。
    """

    __slots__ = ("_factory", "_repo")

    def __init__(self, factory: EngineFactory) -> None:
        """收 `EngineFactory`（**MUST NOT 自开引擎**：池参数是部署决策，
        见 `repository/session.py` 的模块 docstring）。
        """
        self._factory = factory
        self._repo = TaskRepo()

    def list_claimable(self, *, limit: int, now: datetime) -> Sequence[ClaimedTask]:
        """扫出**当月**待处理任务：`WHERE status = 'PROCESSING' ORDER BY created_at ASC LIMIT n`。

        三点口径：

        - **只扫当月**（`now` 现算）：跨月扫描违反 `er.md` §5.3 的分片键下推要求。
          跨月的历史积压任务**不在本方法的职责内**（它们要么已被处理，要么由运维/对账介入）
          ——把「上个月没跑完的任务」在本月静默捡起来，会让「按月的处理窗口」这个语义消失；
        - **排序对齐 `idx_status_created(status, created_at)`**（`er.md` §7.1）：
          `WHERE status` + `ORDER BY created_at` 正好是那个复合索引的最左前缀，
          故这是**索引扫描**而不是全表扫描 + filesort；
        - **走主库只读会话**（`primary_read_session`）：执行器扫完立刻就要改这一行，
          从从库读到旧状态会让已终态的行再次被领走（`er.md` §5.5）。

        账号哨兵不参与表名计算（见模块 docstring 的说明表）：月份只由 `now` 决定。
        """
        month = current_month_of(now)
        table = physical_table(TASK_LOGICAL_TABLE, month)
        statement = (
            select(table)
            .where(table.c.status == PROCESSING_STATUS)
            .order_by(table.c.created_at.asc())
            .limit(limit)
        )
        with self._factory.primary_read_session() as session:
            # 物化在会话内完成（`all()`）：会话退出即归还连接，
            # MUST NOT 把 RowMapping 带出 `with` 之后再取列值。
            rows = session.execute(statement).mappings().all()
        return [self._to_claimable(row) for row in rows]

    def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        """标记「事实源里正在跑」：`status=PROCESSING` + `progress=1`。

        `status` 仍是 `PROCESSING`（**不是**新状态）：`er.md` §6.1 L292 的枚举只有四个取值，
        「正在跑」与「已受理待跑」在事实源里是同一个状态；区分它们的是**租约**
        （Redis）与 `progress`，MUST NOT 为它新增状态值（那会撞三源比对）。
        """
        self._write_back(
            task_id,
            account_id=account_id,
            created_at=created_at,
            status=PROCESSING_STATUS,
            progress=BEGUN_PROGRESS,
            finished_at=None,
        )

    def mark_succeeded(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        progress: int,
        finished_at: datetime,
    ) -> None:
        """写成功终态：`status=SUCCEEDED` + `progress=100` + `finished_at`。

        `progress` 由调用方给（执行器传 100），本方法不写死：将来若出现「部分成功」
        （例如多证照任务），那时改的是调用点的语义，而不是这里的一个字面量。
        """
        self._write_back(
            task_id,
            account_id=account_id,
            created_at=created_at,
            status=SUCCEEDED_STATUS,
            progress=progress,
            finished_at=finished_at,
        )

    def mark_failed(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        """写失败终态：`status=FAILED` + `error_code` + `finished_at`。

        `error_code` 落 `er.md` §6.1 L294 定义的那一列（**FAILED 业务码**，
        如 `'4003'` / `'5002'`），Task 4.11 的「`4003` 与 `5002` 分别计数」靠它。

        ## `progress` 的处置（**A5：这是"写回旧快照"，不是"原子地保持原值"**）

        `update_status` 的 `progress` 是必写列，故这里在**同一个写会话**里先读回现值再写回。
        **MUST NOT 读成"原子地保住了并发写入"**（评审用真 MySQL 实测过**丢失更新**：
        读到 `progress=10` → 另一个事务提交 `80` → 本方法把 `10` 写回去 → 最终 `10`）。
        它只是把**旧快照**写回去，读与写之间没有锁。

        真正的修复要给 `update_status` 一个"不动这一列"的表达（`progress` 不进展开列），
        那属于**共享列契约**的改动，应与 5.x「处理器开始回写进度」一起设计——
        本轮**不做**（控制者裁定），只把 docstring 里那句会让人误以为有原子性的措辞改准。

        `progress` 仍然**不能在失败时清零**：那会让调用方误以为任务刚提交。
        """
        shard = ShardKey(account_id=account_id, created_at=created_at)
        with self._factory.write_session() as session:
            kept_progress = self._current_progress(session, task_id, shard)
            affected = self._repo.update_status(
                session,
                task_id,
                shard=shard,
                status=FAILED_STATUS,
                progress=kept_progress,
                finished_at=finished_at,
                error_code=error_code,
            )
        if affected == 0:
            # 同 `_write_back`：0 行意味着那一行不存在，MUST NOT 当成写成功（A5(c)）。
            raise TaskRowMissingError(
                f"写回任务 {task_id} 的 FAILED 终态时匹配到 0 行（分片月 {shard.month}）："
                f"该行不存在——分片月算错或任务号不对"
            )

    def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        """重新排队：`status=PROCESSING` + `progress=0`。

        **不清 `error_code`**（工单 §2.6 的定档口径，本实现照此）：`er.md` §6.1 L294 的
        `error_code` 是「FAILED 业务码」，重排期间保留上一次的码有利于排障——
        运维看到「一行 PROCESSING 但 error_code=4003」就知道它已经失败过一次、
        正在重试，而不是「刚从队列里出来」。

        与 `mark_failed` 相反，这里**不需要写 `error_code`**（保留原值 = 不动那一列），
        故本方法没有上面那条缺口：`update_status` 的三个列正好够用。
        """
        self._write_back(
            task_id,
            account_id=account_id,
            created_at=created_at,
            status=PROCESSING_STATUS,
            progress=REQUEUED_PROGRESS,
            finished_at=None,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _write_back(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        status: str,
        progress: int,
        finished_at: datetime | None,
        error_code: str | None = None,
    ) -> None:
        """**单语句写回**的唯一出口：开写会话 → `TaskRepo.update_status`。

        三个「一条 UPDATE 就够」的写方法（`begin_attempt` / `mark_succeeded` / `requeue`）
        共用它：样板只写一遍，日后要一起改口径（例如统一加一列）时只有一个落点。

        `finished_at=None` 的语义是**写 NULL**：`requeue` / `begin_attempt` 都不是终态，
        `er.md` §6.1 L298 明确 `finished_at` 只在终态时才有值；重排队时把它清掉，
        是为了不让「上一轮的完成时间」留在一条正在跑的行上（那会让轮询方以为任务已结束）。

        **`rowcount == 0` 必须炸出来（A5(c)）**：`TaskRepo.update_status` 返回的是
        **匹配行数**（该仓储的 docstring 有实测记录），`0` 意味着**那一行不存在**——
        分片月打错、任务号拼错，或者行被别处删了。此前本类把返回值**丢掉**，
        于是执行器以为"写成功了"并**释放租约**：行留在原状态（例如 `PROCESSING`）
        等下一轮重放，而重放可能重复调用付费通道。
        故这里把 0 行当**异常**暴露出来：宁可让调用方看到一次失败，
        也不要让它以为写成功了。
        """
        shard = ShardKey(account_id=account_id, created_at=created_at)
        with self._factory.write_session() as session:
            affected = self._repo.update_status(
                session,
                task_id,
                shard=shard,
                status=status,
                progress=progress,
                finished_at=finished_at,
                error_code=error_code,
            )
        if affected == 0:
            raise TaskRowMissingError(
                f"写回任务 {task_id} 的状态时匹配到 0 行（分片月 {shard.month}）："
                f"该行不存在——分片月算错或任务号不对。"
                f"MUST NOT 当成写成功：否则执行器会释放租约，而事实源里那一行仍是旧状态"
            )

    def _current_progress(self, session: Session, task_id: str, shard: ShardKey) -> int:
        """读回该行当前的 `progress`（供 `mark_failed` 的写回用）。

        取不到行时返回 `0`（`er.md` §6.1 L293 的列默认值）。**这不是静默吞错**：
        行的存在性由紧接着那次 UPDATE 的 `rowcount` 决定，而 `_write_back` /
        `mark_failed` 现在都会在 `rowcount == 0` 时抛 `TaskRowMissingError`（A5(c)）。
        """
        task = self._repo.get_by_id(session, task_id, shard=shard)
        return 0 if task is None else task.progress

    @staticmethod
    def _to_claimable(row: RowMapping) -> ClaimedTask:
        """一行 → `ClaimedTask`。

        经 `AiTask(**row)`（列名与属性名一一对应）而不是手写字段映射：手写会在
        `models.py` 加列/改列名时静默取到别的字段，而 `AiTask(**row)` 会在列名不匹配时
        当场 `TypeError`（`repository/base.py` 的 `_to_entity` 同款取向；
        `tests/repository/test_repos.py` 的列名一致性用例正面钉住这个前提）。

        这里**不调 `TaskRepo._to_entity`**（下划线前缀的受保护成员）：本模块与 `TaskRepo`
        是同层邻居，但依赖一个受保护成员会让 3.7 调整它时静默影响本模块。

        ## `created_at` 为什么在出口处补上 UTC（**实测踩过一次**）

        MySQL 的 `DATETIME(3)` **不存时区**，故驱动回给 Python 的是 **naive** datetime
        （写入时明明是 aware 的）。而执行器要把这个值原样交给 `ShardKey`
        ——`ShardKey` 的构造期校验**拒绝 naive**（`repository/base.py`：「naive 值既可能是
        UTC 也可能是本地时间，猜错就跨月错片」）。故不补时区的话，第一条状态写回就会
        抛 `ParamError(1002)`（实测：`分片键 created_at 必须带时区`）。

        补 `UTC` 而不是 `astimezone()`（转换到本地时区）：`er.md` §6 绪定的是
        **UTC 存储**，故库里那个 naive 值的语义就是 UTC。这是「按已定档的口径解释」，
        不是「猜一个时区」——两者的区别是：前者有文档依据，后者没有。
        """
        entity = AiTask(**dict(row))
        created_at = entity.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return ClaimedTask(
            task_id=entity.task_id,
            task_type=entity.type,
            account_id=entity.account_id,
            created_at=created_at,
        )
