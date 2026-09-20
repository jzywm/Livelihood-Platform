"""`ocr_correction`（人工核验纠错回流，**随任务同月分片**）的数据访问（Task 3.7）。

**权威依据**：`er.md` §7.3——用途是"AI 准确率提升闭环的语料层"（一行一字段留痕），
索引 `idx_task(task_id)` 与 `idx_field_corrected(field_name, corrected_at)`，
约束**只增不改**（纠错留痕不可篡改，保障评估集可信）；§5.2/§5.3 的分片口径同 `ocr_result`。

**R5 在本模块的落点**：本类**只有** `insert` + `list_by_task`，MUST NOT 出现任何
`update*` / `delete*` 方法。为什么这条要写死：纠错语料一旦可改，"字段级准确率"与
"固定评估集回归"的结论就失去了基准（改动历史可以让任何模型看起来都变好了）；
`tests/repository/test_repos.py` 用 `dir()` 正面断言"没有更新/删除入口"。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from aicore.repository.base import BaseRepo, ShardKey
from aicore.repository.models import OcrCorrection
from aicore.repository.sharding import require_shard_key

#: 本模块的逻辑表名（只此一处字面量）。
CORRECTION_LOGICAL_TABLE: Final[str] = "ocr_correction"


class CorrectionRepo(BaseRepo[OcrCorrection]):
    """`ocr_correction` 的**只增**仓储（分片表：物理名 `ocr_correction_YYYYMM`）。"""

    logical_table: ClassVar[str] = CORRECTION_LOGICAL_TABLE
    model = OcrCorrection

    def insert(self, session: Session, entity: OcrCorrection, *, shard: ShardKey) -> None:
        """写入一条纠错留痕；物理表 = `shard` 所在月（**该任务**的 `created_at` 所在月）。

        **偏离工单**：同 `OcrRepo.insert`——本表也没有业务时间列（只有 `corrected_at`，
        而按 S5 口径月份 MUST 取自**任务的** `created_at`，MUST NOT 用纠错动作的时间：
        纠错发生在几个月后，用 `corrected_at` 算月会把留痕写进另一张表，
        破坏"同一 `task_id` 落同分片、1:N 查询不跨分片"（er.md §7.3））。

        本表有一条**指向同月 `ocr_result_YYYYMM` 的物理外键**（约束名带月份后缀），
        故错片的写入会被 MySQL 直接拒绝（找不到被引用行）——这是设计里刻意留的物理兜底。
        """
        self._insert(session, shard, entity)

    def list_by_task(
        self,
        session: Session,
        task_id: str,
        *,
        shard: ShardKey,
        limit: int,
        offset: int,
    ) -> Sequence[OcrCorrection]:
        """按任务取纠错明细（R1：必须带分片键），走 `idx_task(task_id)`。

        排序 `corrected_at DESC, correction_id DESC`：纠错明细按"最近改的先看"排列，
        次排序键保证翻页稳定（同一毫秒的两条留痕不会因页边界漏行或重复）。
        `field_name` + `corrected_at` 的统计口径（`idx_field_corrected`）不在这里——
        那属于聚合查询，按 er.md §5.3 的口径走异步 / 从库，不在单任务读取路径上。
        """
        require_shard_key(task_id, field="task_id")
        table = self._table(shard)
        statement = (
            select(table)
            .where(table.c.task_id == task_id)
            .order_by(table.c.corrected_at.desc(), table.c.correction_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._select_many(session, statement)
