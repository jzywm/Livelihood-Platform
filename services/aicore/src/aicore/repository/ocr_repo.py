"""`ocr_result`（证照 OCR 结果，**随任务同月分片**）的数据访问（Task 3.7）。

**权威依据**：`er.md` §7.2（主键 `task_id`、无需附加索引、与 `ai_task` 同月同分片、1:1 查询
不跨分片）、§5.2/§5.3；`sharding.py` 的 S2/S5/S6（结果表随 `task_id` 同月、月份只从业务字段算）。

**分片月从哪来（本模块的关键约束）**：`ocr_result` 的 DDL 里**没有自己的业务时间列**，
而 `task_id` 是 `task_` + UUID、**不含任何内嵌时间戳**（er.md §5.4），故月份只能来自
**该任务的 `created_at`**——`sharding.py` 的模块 docstring 明写「调用方 MUST 传入该任务的
`created_at`」，且 MUST NOT 从 `task_id` 里解析月份。这就是 `insert` 多一个必填关键字
`shard` 的原因（偏离项已登记在报告）。
"""

from __future__ import annotations

from typing import ClassVar, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicore.repository.base import BaseRepo, ShardKey
from aicore.repository.models import OcrResult
from aicore.repository.sharding import require_shard_key

#: 本模块的逻辑表名（只此一处字面量）。
OCR_RESULT_LOGICAL_TABLE: Final[str] = "ocr_result"


class OcrRepo(BaseRepo[OcrResult]):
    """`ocr_result` 的读写仓储（分片表：物理名 `ocr_result_YYYYMM`）。"""

    logical_table: ClassVar[str] = OCR_RESULT_LOGICAL_TABLE
    model = OcrResult

    def insert(self, session: Session, entity: OcrResult, *, shard: ShardKey) -> None:
        """写入 OCR 结果；物理表 = `shard` 所在月（**该任务**的 `created_at` 所在月）。

        **偏离工单**：工单给的签名是 `insert(self, session, entity)`，但本表没有业务时间列，
        没有 `shard` 参数就只剩两条路——(a) 用当前时间猜月份（静默错片：任务创建于 1 月、
        结果写进 2 月表，两张表都"写成功"，1:1 查询永远落空）、(b) 回查所有分片找这个任务
        （R1 明禁的全表扫描）。故补一个**必填关键字** `shard`：它是本表唯一的月份来源。

        同月这一点由调用方保证（service 层手里正拿着该任务）；物理上的兜底只有一层——
        `ocr_correction` 有指向同月 `ocr_result_YYYYMM` 的物理外键，而**本表没有指向
        `ai_task` 的外键**（er.md §7.2 只有主键），故错片在本表不会立刻炸，这正是
        "月份 MUST 从任务来"必须写在签名上的原因。
        """
        self._insert(session, shard, entity)

    def get_by_id(self, session: Session, task_id: str, *, shard: ShardKey) -> OcrResult | None:
        """按 `task_id`（= 主键 = 任务号）取结果（R1：必须带分片键）。

        与 `ai_task` 同月同分片，故 1:1 查询不跨分片（er.md §5.2/§5.3）；`shard` MUST 是
        **该任务**所在月，否则查的是另一张月表（查不到不会报错，只会静默返回 `None`）。
        """
        require_shard_key(task_id, field="task_id")
        table = self._table(shard)
        return self._select_one(session, select(table).where(table.c.task_id == task_id).limit(1))
