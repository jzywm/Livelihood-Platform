"""`vision_review` / `review_verdict`（**均不分片**）的数据访问（Task 3.7）。

**权威依据**：`er.md` §5.2（`vision_review` 暂不分片，阈值触发再分；`review_verdict` 与
`vision_review` 同库物理外键）、§7.4（索引 `idx_merchant_created` / `idx_status_created` /
`idx_task`）、§7.6（**每审核记录至多一条结论**、复核留痕**只增不改**、
`authority_written` 只能由人工复核结论驱动置位）。

**R1 在本类的适用性（MUST 在此写明，否则下一个读者会以为漏了分片键）**：R1 要求"所有**读取**
方法收分片键"，而它的前提是**分片表**——本类操作的两张表都**不分片**（er.md §5.2），
物理名就是逻辑名、没有月份后缀可算，故本类方法**不收 `shard`**。
这不是漏项：`BaseRepo.physical_name` 对非分片表会直接抛 `ParamError(1002)`
（`sharding.py` 的口径），本类从不调用它。

**两张表的物理名相同，故不走 `physical_table()` 复制**：固定名表没有"表名要现算"的问题，
直接用模型元数据的表对象（写入）与 ORM 实体查询（读取，能进 identity map）。
分片表之所以要复制副本，只是因为物理名与 `__tablename__` 不同（见 `base.py` 第三节）。
"""

from __future__ import annotations

from typing import ClassVar, Final

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aicore.core.errors import CONFLICT_CODE, ConflictError
from aicore.repository.base import BaseRepo, entity_values
from aicore.repository.models import ReviewVerdict, VisionReview
from aicore.repository.sharding import require_shard_key

#: 本仓储的主逻辑表名（`BaseRepo` 要求声明；两张表都不分片，见模块 docstring）。
REVIEW_LOGICAL_TABLE: Final[str] = "vision_review"


class DuplicateVerdictError(ConflictError):
    """同一审核记录重复写入结论（R4，`er.md` §7.6「每审核记录至多一条结论」）。

    **码值已按 Task 3.7 报告的登记收紧为 `3007 # 状态不允许该操作`**（HTTP 409）：
    实现者当时借 `1003` 是**权宜之计**，理由是"新增一个码要按 `core/errors.py` 顶部的
    四处清单同步（含 `tests/unit/test_errors.py` 的两张字面量表），超出本任务文件边界"。
    **该理由成立，且它自己就把收紧方向写在了 docstring 里**——控制者据此把 3007 正式接入
    `errors.py`（四处清单 + 新增 `ConflictError`），本类随之改为继承 `ConflictError`，
    不再借码。

    **为什么 1003 是错的分类**：重复提交时请求参数完全合法，冲突来自**服务端已有状态**。
    用 1003（枚举或范围非法）会让前端提示用户"改参数"，而真正的处置是"去看已有结论"。
    语义错位会让调用方做错事。

    **为什么现在继承 `ConflictError` 而不是 `ParamError`**：`ParamError` 的价值是
    "码值必须落在 `PARAM_ERROR_CODES` 内"的构造期校验，而 3007 不在那个集合里；
    码值合法性由 `AiCoreError.__init__` 对 `AICORE_ERROR_CODES` 的校验继续保证。
    """

    #: 继承来的码值即 3007；显式写出让"不构造实例也能读到码"这一点在阅读时可见。
    code: int = CONFLICT_CODE


class VerdictRepo(BaseRepo[VisionReview]):
    """`vision_review`（审核记录）与 `review_verdict`（复核结论）的仓储；两张表都不分片。"""

    logical_table: ClassVar[str] = REVIEW_LOGICAL_TABLE
    model = VisionReview

    # ------------------------------------------------------------------
    # vision_review
    # ------------------------------------------------------------------
    def insert_review(self, session: Session, entity: VisionReview) -> None:
        """写入一条视觉合规审核记录（固定名表 `vision_review`）。

        与分片表的写入用同一条路径（`entity_values` → Core `INSERT`）：显式执行、不依赖
        `session.add()` 的延迟 flush，故"写完这一行"在语句返回时就已发生——R3 要求的
        "写后立即读"因此不取决于 autoflush 是否打开。`None` 值的列不进列清单（让
        `status` / `markers_count` / `created_at` 的 `server_default` 生效），见 `entity_values`。
        """
        session.execute(insert(VisionReview).values(entity_values(entity)))

    def get_review(self, session: Session, review_id: str) -> VisionReview | None:
        """按 `review_id` 取审核记录；不存在返回 `None`（不是抛异常，见 `_select_one`）。

        **不收分片键**：`vision_review` 不分片（见模块 docstring 的 R1 适用性一节）。
        """
        require_shard_key(review_id, field="review_id")
        statement = select(VisionReview).where(VisionReview.review_id == review_id).limit(1)
        return session.execute(statement).scalars().first()

    # ------------------------------------------------------------------
    # review_verdict（R4：每审核记录至多一条结论，只增不改）
    # ------------------------------------------------------------------
    def insert_verdict(self, session: Session, entity: ReviewVerdict) -> None:
        """写入人工复核结论；同一 `review_id` 已有结论时抛 `DuplicateVerdictError`。

        **两道防线同时上（工单允许二选一，这里说明为什么两道都要）**：

        1. **前置 SELECT**（`get_verdict`）：让"已知重复"这一常见情形拿到干净的业务异常与
           可读消息，而不必先制造一次数据库错误；
        2. **主键冲突转换**：前置检查存在 TOCTOU 窗口（两个并发复核都读到"还没有结论"），
           而唯一的**无竞态**保证是数据库主键——`review_verdict.review_id` 既是主键也是指向
           `vision_review` 的外键（1:1）。故 `IntegrityError` 一律**回查一次**再判定：
           回查到结论 → 转成 `DuplicateVerdictError`；回查不到 → **原样抛出**（那是外键失败，
           即"引用了不存在的审核记录"，不能报成"已有结论"而掩盖真正的问题）。
           用"回查"而不是解析驱动的错误码，是因为错误码是方言相关的（MySQL 1062 vs 1452）。

        **不自行 `rollback()`**：事务边界归调用方（spec §5.7）；调用方拿到本异常后 MUST
        自行回滚或重开事务（MySQL 下失败的 INSERT 只回滚该语句，事务本身仍可继续使用，
        但语义上这次写入已经失败）。

        **MUST NOT 实现"覆盖已有结论"的更新路径**（er.md §7.6 只增不改）：本类没有任何
        verdict 的 update / delete 方法，用例用 `dir()` 正面断言。
        """
        require_shard_key(entity.review_id, field="review_id")
        if self.get_verdict(session, entity.review_id) is not None:
            raise DuplicateVerdictError(
                f"审核记录 {entity.review_id} 已有复核结论："
                f"er.md §7.6 规定每审核记录至多一条结论、只增不改，MUST NOT 覆盖"
            )
        try:
            session.execute(insert(ReviewVerdict).values(entity_values(entity)))
        except IntegrityError as exc:
            if self.get_verdict(session, entity.review_id) is not None:
                raise DuplicateVerdictError(
                    f"审核记录 {entity.review_id} 的结论写入被数据库唯一约束拒绝"
                    f"（并发重复写入，非覆盖）"
                ) from exc
            raise

    def get_verdict(self, session: Session, review_id: str) -> ReviewVerdict | None:
        """按 `review_id`（= 主键 = 1:1 外键）取复核结论；不存在返回 `None`。

        **不收分片键**：`review_verdict` 不分片（见模块 docstring 的 R1 适用性一节）。
        """
        require_shard_key(review_id, field="review_id")
        statement = select(ReviewVerdict).where(ReviewVerdict.review_id == review_id).limit(1)
        return session.execute(statement).scalars().first()
