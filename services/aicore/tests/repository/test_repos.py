"""`repository/{base,task_repo,ocr_repo,correction_repo,verdict_repo}.py` 的用例（Task 3.7）。

**两段式**（与仓库既有口径一致）：

- **默认段：纯逻辑 + `sqlite` 内存沙盒**，不连真实数据库、不读系统时钟（时间一律显式构造），
  测试内 MUST NOT 出现 `sleep`（`tests/conftest.py` 的约定）；
- **`@pytest.mark.integration` 段：真实 MySQL（`aicore_test`）**，默认不跑；连不上时
  **显式 skip 并说明原因**——静默通过等于让这道门禁在 CI 里永远不生效。

**沙盒的三处"缩水"（MUST 知道，否则会把沙盒的绿灯当成生产保证）**：

1. `server_default='CURRENT_TIMESTAMP(3)'` 是 MySQL 语法（sqlite 报
   `near "(" syntax error`，实测），沙盒里**只抹掉时间类默认值**；`DEFAULT 0` /
   `DEFAULT 'PROCESSING'` 这类 sqlite 认得，一律保留。故"库默认值"的真实行为由集成用例覆盖，
   沙盒只覆盖**语句语义与对象映射**。
2. 物理表副本的外键在模型里指向**逻辑名**（`ocr_correction` → `ocr_result`），而生产上那个
   名字由 DDL 模板渲染成带月份的物理名；sqlite 里无法随物理名解析，故沙盒**不建分片表外键**
   （`include_foreign_key_constraints=[]`，实测可行）。外键的真实行为由集成用例（MySQL 上是
   真外键）与 `test_apply_ddl_mysql.py` 覆盖。
3. sqlite 默认**不校验外键**；只有"外键失败 MUST NOT 被误报成重复结论"那条用例显式
   `PRAGMA foreign_keys=ON` 并把固定表的外键建出来。

**期望值来源**：错误码（`1001` / `1002` / `1003`）与"分片表只有 3 张"取自 Task 3.3 与
`core/errors.py` 的定档值；演练月、演练库名是本用例自己的隔离参数，逐字钉死。
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import MetaData, Table, create_engine, event, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from aicore.core.errors import ParamError
from aicore.repository.base import (
    BaseRepo,
    ShardKey,
    cross_shard_transaction_guard,
    physical_table,
)
from aicore.repository.correction_repo import CorrectionRepo
from aicore.repository.models import (
    LOGICAL_TABLE_NAMES,
    AiTask,
    Base,
    OcrCorrection,
    OcrResult,
    ReviewVerdict,
    VisionReview,
)
from aicore.repository.ocr_repo import OcrRepo
from aicore.repository.sharding import (
    CrossShardOperationError,
    MissingShardKeyError,
    ensure_month_tables,
    shard_month_of,
)
from aicore.repository.task_repo import (
    TASK_LOGICAL_TABLE,
    TaskRepo,
    status_update_statement,
)
from aicore.repository.verdict_repo import DuplicateVerdictError, VerdictRepo

# ---------------------------------------------------------------------------
# 定档值（本用例自己的隔离参数，硬编码）
# ---------------------------------------------------------------------------
#: 沙盒的演练月（远未来年份，不与任何真实数据撞车）。
MONTH: Final[str] = "202607"
#: 邻近的另一个月：验证"同账号、不同月落在不同物理表"。
OTHER_MONTH: Final[str] = "202608"

#: 三张分片表的逻辑名（`models.py` 的 `LOGICAL_TABLE_NAMES` 才是唯一出处，此处只列名字，
#: 用于"物理名 MUST 由月份现算"的断言与集成用例的清理）。
SHARDED_LOGICAL_TABLES: Final[tuple[str, ...]] = ("ai_task", "ocr_result", "ocr_correction")

#: 本任务涉及的两张非分片表（`VerdictRepo`）。
FIXED_LOGICAL_TABLES: Final[tuple[str, ...]] = ("vision_review", "review_verdict")


def _at(hour: int = 8, *, month: str = MONTH, day: int = 15) -> datetime:
    """显式构造一个 **aware** 时刻（其分片月 = `month`）；用例不读系统时钟。"""
    return datetime(int(month[:4]), int(month[4:]), day, hour, 0, tzinfo=UTC)


def _shard(account_id: str = "acc_1", *, month: str = MONTH, day: int = 15) -> ShardKey:
    """构造分片键（账号 + 业务时间）。"""
    return ShardKey(account_id=account_id, created_at=_at(month=month, day=day))


def _as_utc(value: datetime | None) -> datetime | None:
    """把读回来的时间归一到 UTC 感知形态（库里的 `datetime(3)` 不存时区）。"""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ---------------------------------------------------------------------------
# 实体工厂（字段口径取自 er.md §6 数据字典）
# ---------------------------------------------------------------------------
def _task(
    task_id: str,
    *,
    account_id: str = "acc_1",
    at: datetime | None = None,
    idem_key: str | None = None,
    status: str = "PROCESSING",
    progress: int = 0,
    model_meta: dict[str, Any] | None = None,
    is_eval_sample: bool = False,
) -> AiTask:
    """`ai_task` 实体（字段按 DDL 的非空约束给全；`created_at` 必填，它是分片键）。"""
    return AiTask(
        task_id=task_id,
        account_id=account_id,
        idem_key=idem_key,
        type="OCR",
        status=status,
        progress=progress,
        model_meta=model_meta,
        is_eval_sample=is_eval_sample,
        created_at=at if at is not None else _at(),
    )


def _result(task_id: str, *, summary: str = "证照识别完成") -> OcrResult:
    """`ocr_result` 实体（注意：本表**没有**业务时间列，故分片月只能由调用方给）。"""
    return OcrResult(
        task_id=task_id,
        fields_json=[{"name": "营业执照", "value": "911301********1234"}],
        validity="VALID",
        category_match=True,
        summary=summary,
        suggestions_json=None,
        needs_manual_review=False,
    )


def _correction(
    correction_id: str,
    task_id: str,
    *,
    field_name: str = "legalPerson",
    corrected_at: datetime | None = None,
) -> OcrCorrection:
    """`ocr_correction` 实体（`corrected_at` 是**纠错时刻**，不是分片月来源）。"""
    return OcrCorrection(
        correction_id=correction_id,
        task_id=task_id,
        field_name=field_name,
        ai_value="王*员",
        human_value="王*民",
        confidence=Decimal("0.72"),
        corrected_by="审*员",
        corrected_at=corrected_at if corrected_at is not None else _at(hour=10),
    )


def _review(
    review_id: str,
    *,
    at: datetime | None = None,
    status: str | None = None,
    task_id: str | None = None,
) -> VisionReview:
    """`vision_review` 实体；`status=None` 时**不写该列**，用于验证库默认值生效。"""
    entity = VisionReview(
        review_id=review_id,
        task_id=task_id,
        biz_type="KITCHEN",
        merchant_id="mch_1",
        merchant_name="某*商户",
        batch_id=None,
        image_keys_json=["oss://bucket/a.jpg"],
        confidence_level="HIGH",
        confidence=Decimal("0.91"),
        created_at=at if at is not None else _at(),
    )
    if status is not None:
        entity.status = status
    return entity


def _verdict(
    review_id: str,
    *,
    action: str = "CONFIRM",
    reviewed_at: datetime | None = None,
) -> ReviewVerdict:
    """`review_verdict` 实体（`reviewed_at` 无库默认值，业务必须给）。"""
    return ReviewVerdict(
        review_id=review_id,
        action=action,
        comment=None,
        reviewed_by="审*员",
        reviewed_at=reviewed_at if reviewed_at is not None else _at(hour=11),
        authority_written=False,
    )


# ---------------------------------------------------------------------------
# sqlite 沙盒
# ---------------------------------------------------------------------------
#: 逻辑表 → 模型（`models.py` 是唯一出处，这里只做反查）。
_MODELS: Final[Mapping[str, type[Base]]] = {
    logical: model for model, logical in LOGICAL_TABLE_NAMES.items()
}

#: 沙盒要建的表：`(逻辑名, 物理名)`，**顺序即建表顺序**（固定名表里 `vision_review` 先于
#: `review_verdict`，因为后者带指向它的外键）。分片表建两个月的：既覆盖路由，也覆盖隔离。
_SANDBOX_TABLES: Final[tuple[tuple[str, str], ...]] = (
    ("ai_task", f"ai_task_{MONTH}"),
    ("ai_task", f"ai_task_{OTHER_MONTH}"),
    ("ocr_result", f"ocr_result_{MONTH}"),
    ("ocr_result", f"ocr_result_{OTHER_MONTH}"),
    ("ocr_correction", f"ocr_correction_{MONTH}"),
    ("ocr_correction", f"ocr_correction_{OTHER_MONTH}"),
    ("vision_review", "vision_review"),
    ("review_verdict", "review_verdict"),
)


def _sandbox_copy(logical: str, physical: str, meta: MetaData) -> Table:
    """把模型里的逻辑表复制成**物理表名**的副本（列定义全部来自 `models.py`）。"""
    copy = _MODELS[logical].__table__.to_metadata(meta, name=physical)
    for column in copy.columns:
        default = column.server_default
        # 只抹时间类默认值：`DEFAULT (CURRENT_TIMESTAMP(3))` 是 sqlite 的唯一硬伤。
        if default is not None and "CURRENT_TIMESTAMP" in str(default.arg).upper():
            column.server_default = None
    return copy


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    """sqlite 默认**不**校验外键；要验外键路径时必须显式打开。"""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def _sqlite_engine(*, enforce_fixed_foreign_key: bool = False) -> Engine:
    """建 sqlite 内存库并按**物理名**建表（分片表两个月 + 两张固定名表）。

    `enforce_fixed_foreign_key=True` 时给 `review_verdict` 建出指向 `vision_review` 的外键，
    并打开 `PRAGMA foreign_keys`（sqlite 默认不校验），用于验证"外键失败 MUST NOT 被误报成
    重复结论"。
    """
    engine = create_engine("sqlite://")
    if enforce_fixed_foreign_key:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    meta = MetaData()
    copies: list[tuple[str, Table]] = [
        (logical, _sandbox_copy(logical, physical, meta))
        for logical, physical in _SANDBOX_TABLES
    ]
    with engine.begin() as conn:
        for logical, table in copies:
            foreign_keys = (
                list(table.foreign_key_constraints)
                if enforce_fixed_foreign_key and logical == "review_verdict"
                else []
            )
            conn.exec_driver_sql(
                str(
                    CreateTable(table, include_foreign_key_constraints=foreign_keys).compile(
                        dialect=conn.dialect
                    )
                )
            )
    return engine


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """沙盒引擎（每个用例一个内存库，用例间零共享）。"""
    engine = _sqlite_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sqlite_session(sqlite_engine: Engine) -> Iterator[Session]:
    """沙盒会话：**由用例自己开**（仓储 MUST NOT 自开会话，与 Task 3.4 解耦）。"""
    with Session(sqlite_engine) as session:
        yield session


class _SqlCapture:
    """收集本连接上执行过的 SQL 原文（断言"打到物理表"用；只读、不改写语句）。"""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        self.statements.append(statement)


# ---------------------------------------------------------------------------
# 1. `ShardKey` 不变式（工单用例 1）
# ---------------------------------------------------------------------------
def test_shard_key_requires_aware_created_at() -> None:
    """naive `created_at` MUST 在**构造期**抛 `ParamError(1002)`。

    naive 值既可能是 UTC 也可能是本地时间，猜错就跨月错片，而错片的表现是
    "数据写到了另一个月的表里"——比抛错危险得多。校验收在构造期，比散在各调用点可靠。
    """
    with pytest.raises(ParamError) as excinfo:
        ShardKey(account_id="acc_1", created_at=datetime(2026, 7, 15, 8, 0))
    assert excinfo.value.code == 1002

    key = ShardKey(account_id="acc_1", created_at=_at())
    assert key.month == MONTH


def test_shard_key_requires_non_empty_account_id() -> None:
    """空白账号 MUST 抛 `MissingShardKeyError(1001)`：缺分片键不能退化成"查无数据"。"""
    for blank in ("", "   "):
        with pytest.raises(MissingShardKeyError) as excinfo:
            ShardKey(account_id=blank, created_at=_at())
        assert excinfo.value.code == 1001


def test_shard_key_month_is_derived_and_matches_task_3_3() -> None:
    """`month` 是**派生属性**、与 Task 3.3 的 `shard_month_of` 恒等，且不可能是字段。"""
    key = _shard()
    assert key.month == shard_month_of(key.created_at) == MONTH
    assert [field.name for field in fields(ShardKey)] == ["account_id", "created_at"]
    with pytest.raises(FrozenInstanceError):
        key.month = "202601"


def test_shard_key_month_is_utc_normalized() -> None:
    """分片月按 **UTC** 算：`+08:00` 的 1 月 1 日 0 点落在 UTC 的 12 月 31 日 → `202512`。

    这是"猜时区就会静默错片"的正面证据：本地时间看着是 1 月，UTC 归属却是 12 月。
    """
    local = datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert ShardKey(account_id="acc_1", created_at=local).month == "202512"


# ---------------------------------------------------------------------------
# 2. 单分片守卫与跨分片装饰器（工单用例 2 + "装饰器真的会拒"的正面证明）
# ---------------------------------------------------------------------------
def test_require_same_shard_returns_physical_name_for_one_month() -> None:
    """同月通过，返回**本表物理名**（调用方不必各算一份表名）。"""
    repo = TaskRepo()
    assert (
        repo.require_same_shard(_shard(), _shard(day=20), operation="同月读写")
        == f"{TASK_LOGICAL_TABLE}_{MONTH}"
    )


def test_require_same_shard_rejects_cross_month() -> None:
    """跨月 MUST 抛 `CrossShardOperationError(1003)`，消息点名 operation（便于运维定位）。"""
    with pytest.raises(CrossShardOperationError) as excinfo:
        TaskRepo().require_same_shard(_shard(), _shard(month=OTHER_MONTH), operation="双月写任务")
    assert excinfo.value.code == 1003
    assert "双月写任务" in str(excinfo.value)


def test_require_same_shard_rejects_empty_keys() -> None:
    """一个分片键都没带 MUST 抛 `MissingShardKeyError(1001)`（fail closed）。"""
    with pytest.raises(MissingShardKeyError) as excinfo:
        TaskRepo().require_same_shard(operation="无分片键写任务")
    assert excinfo.value.code == 1001


def test_physical_name_agrees_with_the_same_shard_guard() -> None:
    """`physical_name` 与 `require_same_shard` MUST 给出**同一个**表名（否则调用方会各算一份）。"""
    repo = TaskRepo()
    shard = _shard()
    assert repo.physical_name(shard) == f"{TASK_LOGICAL_TABLE}_{MONTH}"
    assert repo.physical_name(shard) == repo.require_same_shard(shard, operation="同月读写")
    assert OcrRepo().physical_name(shard) == f"ocr_result_{MONTH}"
    assert CorrectionRepo().physical_name(shard) == f"ocr_correction_{MONTH}"


def test_cross_shard_transaction_guard_really_rejects_two_months() -> None:
    """装饰器的**正面证明**：一次调用拿到两个月 → 抛错，且被装饰函数**一行都没执行**。

    "没执行"必须断言：只在装饰器里判断、却仍把函数跑一遍的写法，等于把跨分片操作开出来了
    再报错——那已经晚了（R2 要的是**不开**）。
    """
    executed: list[str] = []

    @cross_shard_transaction_guard("双月写任务")
    def write_two_months(first: ShardKey, second: ShardKey) -> None:
        executed.append(f"{first.month}->{second.month}")

    with pytest.raises(CrossShardOperationError) as excinfo:
        write_two_months(_shard(), _shard(month=OTHER_MONTH))
    assert excinfo.value.code == 1003
    assert executed == [], "守卫必须在被装饰函数执行**之前**拒绝"


def test_cross_shard_transaction_guard_allows_single_month_and_reads_containers() -> None:
    """同月放行；分片键放在容器里（批量写）同样被收集、同样能拒跨月。"""
    seen: list[str] = []

    @cross_shard_transaction_guard("批量写")
    def write_many(keys: Sequence[ShardKey], note: str = "") -> None:
        seen.append(f"{note}:{len(keys)}")

    write_many([_shard(), _shard(day=16)], note="同月")
    assert seen == ["同月:2"]

    with pytest.raises(CrossShardOperationError):
        write_many([_shard(), _shard(month=OTHER_MONTH)], note="跨月")
    assert seen == ["同月:2"], "跨月那次 MUST NOT 执行"


def test_cross_shard_transaction_guard_fails_closed_without_any_key() -> None:
    """没有任何 `ShardKey` 时抛 `MissingShardKeyError(1001)`：判断不了分片就不放行。"""

    @cross_shard_transaction_guard("无键写")
    def write_without_key(entity: str) -> None:  # pragma: no cover - 不该被执行
        raise AssertionError("守卫应在调用被装饰函数之前拒绝")

    with pytest.raises(MissingShardKeyError) as excinfo:
        write_without_key("task_1")
    assert excinfo.value.code == 1001


def test_cross_shard_transaction_guard_keeps_the_signature() -> None:
    """`functools.wraps` 让签名可读：R1 的签名断言不会被装饰器破坏。"""

    @cross_shard_transaction_guard("同分片写")
    def write_one(key: ShardKey, *, note: str) -> None:
        """占位函数：只验证签名。"""

    assert list(inspect.signature(write_one).parameters) == ["key", "note"]


# ---------------------------------------------------------------------------
# 3. R4 / R5 的结构断言（工单用例 3）
# ---------------------------------------------------------------------------
def test_correction_repo_has_no_update_or_delete_entry_point() -> None:
    """R5：`CorrectionRepo` **没有** `update*` / `delete*` 属性（纠错留痕只增不改）。

    **这是"防回归"的弱断言**（`dir()` 只能证明今天没有这个方法名），真正的保证在评审：
    语料一旦可改，"字段级准确率"与"固定评估集回归"就失去了基准。
    """
    forbidden = [
        name
        for name in dir(CorrectionRepo)
        if name.startswith(("update", "delete", "remove", "replace"))
    ]
    assert forbidden == [], f"纠错留痕只能新增，出现了可写入口：{forbidden}"
    assert {
        name
        for name, member in vars(CorrectionRepo).items()
        if not name.startswith("_") and inspect.isfunction(member)
    } == {"insert", "list_by_task"}


def test_verdict_repo_has_no_update_or_delete_for_verdict() -> None:
    """R4：`VerdictRepo` **没有** `update_verdict` / `delete_verdict`（结论只增不改）。

    同样是防回归的弱断言：真正的不变式由 `review_verdict` 的主键（每审核记录至多一条）
    与"不实现任何覆盖路径"共同保证。
    """
    assert not hasattr(VerdictRepo, "update_verdict")
    assert not hasattr(VerdictRepo, "delete_verdict")
    forbidden = [
        name
        for name in dir(VerdictRepo)
        if name.startswith(("update", "delete", "remove", "replace"))
    ]
    assert forbidden == [], f"复核结论只能新增，出现了可写入口：{forbidden}"


# ---------------------------------------------------------------------------
# 4. R1 的机械证据：读取方法签名（工单用例 4）
# ---------------------------------------------------------------------------
#: 四个仓储的**写**方法（R1 只管读取方法；写方法的入参理由写在各自 docstring）。
_WRITE_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("TaskRepo", "insert"),
        ("OcrRepo", "insert"),
        ("CorrectionRepo", "insert"),
        ("VerdictRepo", "insert_review"),
        ("VerdictRepo", "insert_verdict"),
    }
)

#: R1 的**显式豁免名单**：唯二不收分片键的读取方法，理由是那两张表**不分片**（er.md §5.2）。
#: MUST 逐条列出，MUST NOT 用"名字里含 review"这类模式匹配——白名单才看得出谁被豁免了。
_NON_SHARDED_READ_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("VerdictRepo", "get_review"),
        ("VerdictRepo", "get_verdict"),
    }
)

#: 四个仓储类（名字 → 类），供遍历用。
_REPO_CLASSES: Final[Mapping[str, type[BaseRepo[Any]]]] = {
    "TaskRepo": TaskRepo,
    "OcrRepo": OcrRepo,
    "CorrectionRepo": CorrectionRepo,
    "VerdictRepo": VerdictRepo,
}


def _declared_methods(class_name: str) -> frozenset[str]:
    """本类**自己声明**的公开方法名（不含基类继承来的，避免把基类方法算成仓储方法）。"""
    return frozenset(
        name
        for name, member in vars(_REPO_CLASSES[class_name]).items()
        if not name.startswith("_") and inspect.isfunction(member)
    )


def test_every_read_method_requires_the_shard_key() -> None:
    """R1 的机械证据：全部公开读取方法的签名里都有**关键字**参数 `shard`。

    分类是穷尽的——写方法在 `_WRITE_METHODS`、非分片读取在 `_NON_SHARDED_READ_METHODS`，
    剩下的一律按"分片表读取"要求 `shard`：将来有人加一个不带 `shard` 的读取入口，
    本用例立刻红（"新增读取入口必须显式面对 R1"）。

    要求 `KEYWORD_ONLY` 而不是"有这个名字就行"：调用点被迫写 `shard=`，
    少一个"位置参数写错、静默查了另一张月表"的机会。
    """
    for class_name in _REPO_CLASSES:
        for method_name in _declared_methods(class_name):
            if (class_name, method_name) in _WRITE_METHODS:
                continue
            if (class_name, method_name) in _NON_SHARDED_READ_METHODS:
                continue
            signature = inspect.signature(getattr(_REPO_CLASSES[class_name], method_name))
            assert "shard" in signature.parameters, (
                f"{class_name}.{method_name} 未在豁免名单里，就 MUST 收分片键（R1）"
            )
            assert signature.parameters["shard"].kind is inspect.Parameter.KEYWORD_ONLY, (
                f"{class_name}.{method_name} 的 shard MUST 是关键字参数（强制调用点写 shard=）"
            )


def test_r1_whitelists_have_no_stale_entries() -> None:
    """豁免 / 写名单 MUST NOT 有失效条目：名单里写了个不存在的方法 = 名单在骗人。"""
    for class_name, method_name in _WRITE_METHODS | _NON_SHARDED_READ_METHODS:
        assert method_name in _declared_methods(class_name), (
            f"名单里的 {class_name}.{method_name} 不存在（名单过期或拼错）"
        )


def test_task_derived_tables_require_shard_key_on_insert() -> None:
    """**偏离工单**的正面记录：`ocr_result` / `ocr_correction` 的 `insert` 必带 `shard`。

    这两张表没有自己的业务时间列，分片月只能来自"该任务的 `created_at`"（`sharding.py` 的
    S5）；工单给的 `insert(session, entity)` 没有月份来源，补分片键是本任务唯一可行的做法
    （否则只剩"猜当前时间"（静默错片）或"扫全部分片"（R1 明禁）两条路）。此处把它钉死：
    将来有人"顺手删掉"这个参数，本用例立刻红。

    反面对照一并断言：`ai_task` 自带 `created_at`、复核两表不分片，它们的写方法**不**收分片键。
    """
    for repo_class in (OcrRepo, CorrectionRepo):
        parameters = inspect.signature(repo_class.insert).parameters
        assert "shard" in parameters, f"{repo_class.__name__}.insert 必须收分片键"
        assert parameters["shard"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "shard" not in inspect.signature(TaskRepo.insert).parameters
    assert "shard" not in inspect.signature(VerdictRepo.insert_review).parameters
    assert "shard" not in inspect.signature(VerdictRepo.insert_verdict).parameters


def test_repo_logical_tables_match_the_model_metadata() -> None:
    """仓储声明的逻辑表名 MUST 等于模型元数据里的 `__tablename__`（两处字面量不得漂移）。"""
    assert TaskRepo.logical_table == AiTask.__tablename__ == "ai_task"
    assert OcrRepo.logical_table == OcrResult.__tablename__ == "ocr_result"
    assert CorrectionRepo.logical_table == OcrCorrection.__tablename__ == "ocr_correction"
    assert VerdictRepo.logical_table == VisionReview.__tablename__ == "vision_review"


def test_model_column_names_match_attribute_names() -> None:
    """`_to_entity` 的前提：每列的**列名 / 列键 / 映射属性名**三者一致。

    分片表的读路径用 `Model(**row)` 把 `RowMapping` 还原成实体，行里的键就是列名；三者一旦
    不一致，失败形态是运行期 `TypeError`（最难排查的那种）。本用例让它在测试期就炸。
    """
    for model in (AiTask, OcrResult, OcrCorrection, VisionReview, ReviewVerdict):
        mapper = sa_inspect(model)
        pairs = {
            column.name: mapper.get_property_by_column(column).key for column in mapper.columns
        }
        assert set(pairs) == {column.name for column in model.__table__.columns}, (
            f"{model.__name__} 的映射列与表列不一致"
        )
        for column in model.__table__.columns:
            assert column.key == column.name, f"{model.__name__}.{column.key} 的列键与列名不一致"
        assert all(name == key for name, key in pairs.items()), (
            f"{model.__name__} 的映射属性名与列名不一致：{pairs}"
        )


#: 本任务交付的五个仓储模块所在目录（`session.py` 是 Task 3.4 的装配模块，不在本任务范围）。
_REPOSITORY_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "aicore" / "repository"

#: 本任务交付的五个模块（显式列出：新增的仓储模块必须自己面对 R3 / R7 的扫描）。
_REPO_MODULES: Final[tuple[str, ...]] = (
    "base.py",
    "task_repo.py",
    "ocr_repo.py",
    "correction_repo.py",
    "verdict_repo.py",
)

#: 这五个模块允许出现的**顶层**依赖（R7：repository 只可依赖 core / 相邻 repository / 三方库）。
_ALLOWED_IMPORT_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "collections",
        "contextlib",
        "dataclasses",
        "datetime",
        "functools",
        "sqlalchemy",
        "typing",
        "aicore",
    }
)


def _identifiers(source: str) -> set[str]:
    """源码里出现过的**标识符**（变量名 / 属性名 / 导入名）——注释与字符串不计入。"""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name)
            if node.asname:
                found.add(node.asname)
    return found


# ---------------------------------------------------------------------------
# 5. `update_status` 只更新允许的列（工单用例 5）+ 物理表对象
# ---------------------------------------------------------------------------
def test_repository_modules_do_not_open_sessions_or_reach_upward() -> None:
    """R3 + R7 的结构证据（按**标识符**扫描，不受注释与 docstring 措辞影响）。

    - **R3**：仓储 MUST NOT 自己开引擎 / 会话，也 MUST NOT 挑主从库——写方法与读方法都只接受
      调用方传入的 `Session`，故"写完立刻读"必然落在同一个（主库）连接上。一旦有人在仓储里
      引入 `EngineFactory` / `create_engine` / `read_session` 这类符号，"读走从库"就变成可能，
      本用例立刻红；
    - **R7**：五个模块 MUST NOT 依赖 `aicore.service` / `aicore.provider`（`.importlinter`
      契约 3 / 4 是主证据，这里是零成本的补充）。

    扫描 `repository/session.py` 之外的本任务模块：`session.py` 是 Task 3.4 的**装配**模块，
    "开会话"正是它的职责，不在此列。
    """
    forbidden = frozenset(
        {
            # R3：不自己开引擎 / 会话、不挑主从库
            "EngineFactory",
            "create_engine",
            "sessionmaker",
            "read_session",
            "primary_read_session",
            "mark_write_then_read",
            "replica",
            # R7：不向上依赖
            "service",
            "provider",
            "api",
            "port",
        }
    )
    for module in _REPO_MODULES:
        source = (_REPOSITORY_DIR / module).read_text(encoding="utf-8")
        found = _identifiers(source) & forbidden
        assert not found, f"{module} 里出现了 {sorted(found)}：仓储 MUST NOT 自开会话或向上依赖"
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }
        for name in imports:
            assert name.split(".")[0] in _ALLOWED_IMPORT_ROOTS, (
                f"{module} 引入了预期之外的依赖 {name}"
            )
            assert not name.startswith(("aicore.service", "aicore.provider")), (
                f"{module} 引入了 {name}（R7：repository MUST NOT 依赖 service / provider）"
            )


def test_repository_layer_never_manages_the_transaction() -> None:
    """R2：仓储 MUST NOT 自己 `commit()` / `flush()` / 开两阶段提交——事务边界归调用方。

    机械证据（同样是标识符扫描，不受注释措辞影响）：五个模块里 MUST NOT 出现 `commit` /
    `flush` / `rollback` / `begin_twophase` / `two_phase` / `prepare`。`begin` 本身刻意不列：
    "由谁开事务"要靠人判断，而 `commit` / `flush` 一旦出现，越权就已经发生了。
    """
    forbidden = frozenset(
        {"commit", "flush", "rollback", "begin_twophase", "two_phase", "prepare", "begin_nested"}
    )
    for module in _REPO_MODULES:
        source = (_REPOSITORY_DIR / module).read_text(encoding="utf-8")
        found = _identifiers(source) & forbidden
        assert not found, f"{module} 里出现了 {sorted(found)}：仓储 MUST NOT 自己管事务（R2）"


def test_status_update_statement_only_sets_three_columns() -> None:
    """**不传 `error_code` 时** SET 列集合恰为 `{status, progress, finished_at}`，
    且 SQL 里没有整行覆盖列。

    这是"不用 `session.merge(entity)` 整行覆盖"的**机械证据**：语句对象在手，
    `_values` 的键就是 SET 列（`Update._values` 是 SQLAlchemy 的内部结构，
    这里刻意直接断言它——工单的用例 5 点名了这个判据）。

    **"不传时恰好三列"这半边 MUST NOT 被削弱**（Task 4.7 修复轮的授权范围逐字要求保留）：
    `begin_attempt` / `mark_succeeded` / `requeue` 三个调用方走的都是不传 `error_code`
    的路径，它们的 SQL 必须逐字保持不变。
    """
    statement = status_update_statement(
        MONTH,
        "task_1",
        status="SUCCEEDED",
        progress=100,
        finished_at=_at(hour=9),
    )
    assert {getattr(key, "key", key) for key in statement._values} == {
        "status",
        "progress",
        "finished_at",
    }
    compiled = str(statement.compile(dialect=mysql.dialect()))
    assert f"UPDATE {TASK_LOGICAL_TABLE}_{MONTH} SET" in compiled, (
        f"UPDATE MUST 打到物理表，实际：{compiled}"
    )
    for column in ("created_at", "model_meta", "is_eval_sample", "account_id", "idem_key"):
        assert column not in compiled, f"UPDATE 语句里出现了非目标列 {column}：{compiled}"


def test_status_update_statement_sets_error_code_when_given() -> None:
    """**传了 `error_code` 时** SET 列集合恰为四列，且该值真的进了语句。

    Task 4.7 修复轮（B3）新增：`mark_failed` 要把 `FAILED` 业务码落库，
    否则 Task 4.11 的「`4003` / `5002` 分别计数」没有依据（`er.md` §6.1 L294）。
    与上一条用例**成对**：一条钉"不传时恰好三列"（既有调用方不受影响），
    一条钉"传了时恰好四列"（新路径真的写进去了）。

    只断言"`error_code` 在 `_values` 里"不够：那漏掉「列进去了但值是 `None`」
    （例如实现里写成 `.values(error_code=...)` 却传了个空）这类形态——
    故同时断言**值**等于传进去的那个码。
    """
    statement = status_update_statement(
        MONTH,
        "task_1",
        status="FAILED",
        progress=10,
        finished_at=_at(hour=9),
        error_code="5002",
    )
    values = {getattr(key, "key", key): value for key, value in statement._values.items()}
    assert set(values) == {"status", "progress", "finished_at", "error_code"}
    # `_values` 里的东西是 `BindParameter`（SQLAlchemy 2.x 的绑定参数对象），
    # 故取值要经 `.value`；直接比它会拿到对象本身。
    # 断言**值**而不是"键在不在"：只断言键会漏掉「列进去了但值是 None」这类实现。
    assert getattr(values["error_code"], "value", values["error_code"]) == "5002", (
        f"error_code 的值没有进语句：{values!r}"
    )
    compiled = str(statement.compile(dialect=mysql.dialect()))
    assert f"UPDATE {TASK_LOGICAL_TABLE}_{MONTH} SET" in compiled, (
        f"UPDATE MUST 打到物理表，实际：{compiled}"
    )
    for column in ("created_at", "model_meta", "is_eval_sample", "account_id", "idem_key"):
        assert column not in compiled, f"UPDATE 语句里出现了非目标列 {column}：{compiled}"


def test_physical_table_names_are_computed_not_written_down() -> None:
    """物理表对象按 (逻辑表, 月份) 现算并缓存；副本的列与模型逐列一致（没有第二套模型）。"""
    july = physical_table(TASK_LOGICAL_TABLE, MONTH)
    assert july.name == f"{TASK_LOGICAL_TABLE}_{MONTH}"
    assert physical_table(TASK_LOGICAL_TABLE, MONTH) is july, (
        "同一 (逻辑表, 月份) MUST 复用同一对象"
    )
    august = physical_table(TASK_LOGICAL_TABLE, OTHER_MONTH)
    assert august.name == f"{TASK_LOGICAL_TABLE}_{OTHER_MONTH}"
    assert august is not july
    assert [column.name for column in july.columns] == [
        column.name for column in AiTask.__table__.columns
    ]


def test_physical_table_rejects_fixed_tables() -> None:
    """`physical_table` 只服务 3 张分片表：固定名表传进来一律 `ParamError(1002)`。

    放行会造出 `vision_review_202601` 这种**谁也查不到的孤儿表**（建表与写入都"成功"，
    查询永远落空）——判据复用 Task 3.3 的 `physical_table_name`。
    """
    for logical in (*FIXED_LOGICAL_TABLES, "vision_qa_log"):
        with pytest.raises(ParamError) as excinfo:
            physical_table(logical, MONTH)
        assert excinfo.value.code == 1002


def test_model_metadata_still_holds_only_logical_names() -> None:
    """`models.py` 的元数据里 MUST 只有逻辑名（没有 `_YYYYMM` 后缀）。

    Task 3.6 的三源比对依赖这一点；物理名由 `physical_table` 现算，MUST NOT 回写进元数据。
    """
    assert set(Base.metadata.tables) == set(LOGICAL_TABLE_NAMES.values())
    for model, logical in LOGICAL_TABLE_NAMES.items():
        assert model.__tablename__ == logical
        assert re.search(r"_\d{6}$", logical) is None, f"{logical} 看起来带了月份后缀"
    assert set(SHARDED_LOGICAL_TABLES) | set(FIXED_LOGICAL_TABLES) <= set(
        LOGICAL_TABLE_NAMES.values()
    )


# ---------------------------------------------------------------------------
# 6. sqlite 沙盒上的功能用例
# ---------------------------------------------------------------------------
def test_sharded_access_always_targets_the_physical_table(
    sqlite_engine: Engine, sqlite_session: Session
) -> None:
    """分片表的读 / 写 MUST 打到 `xxx_YYYYMM`，MUST NOT 出现逻辑名的裸查询。

    这条把探针实测到的坑固化成回归断言：`aliased(Model, name=物理名)` 编译出的是
    `FROM ai_task AS ai_task_202607`——表名被当**别名**用，底表仍是逻辑表 `ai_task`；
    生产库上它要么报"表不存在"，要么（若真有同名表）静默读写**另一张表**。

    沙盒本身也是证据：沙盒里**只有**物理名表，任何裸查逻辑表的语句都会直接报
    "no such table"，不可能悄悄通过。
    """
    captured = _SqlCapture()
    event.listen(sqlite_engine, "before_cursor_execute", captured)
    repo = TaskRepo()
    shard = _shard()
    repo.insert(sqlite_session, _task("task_sql", at=_at()))
    assert repo.get_by_id(sqlite_session, "task_sql", shard=shard) is not None
    repo.list_by_account(sqlite_session, shard=shard, limit=10, offset=0)
    repo.update_status(
        sqlite_session, "task_sql", shard=shard, status="SUCCEEDED", progress=100, finished_at=None
    )
    repo.find_by_idem_key(sqlite_session, shard=shard, account_id="acc_1", idem_key="idem_x")

    joined = "\n".join(captured.statements)
    assert f"ai_task_{MONTH}" in joined, f"没有打到物理分片表：{joined}"
    for logical in SHARDED_LOGICAL_TABLES:
        assert re.search(rf"\b{logical}\b", joined) is None, (
            f"出现了逻辑表 {logical} 的裸查询（分片表必须走物理名）：{joined}"
        )


def test_task_repo_round_trip_and_write_then_read(sqlite_session: Session) -> None:
    """任务四步：插入 → 按分片键读回 → 更新 → 再读；写后立即读用**同一个会话**（R3）。

    R3 的落点就在这里：仓储不自开引擎、也不给"只读会话"的旁路，调用方传入的写会话就是
    主库连接，故"写完立刻读"必然读到刚写的值，不会落到有主从延迟的从库上。
    """
    repo = TaskRepo()
    shard = _shard()
    created = _at()
    repo.insert(sqlite_session, _task("task_rw", at=created, idem_key="idem_rw"))

    read_back = repo.get_by_id(sqlite_session, "task_rw", shard=shard)
    assert read_back is not None, "写后立即读 MUST 看得到（同一个会话即主库连接）"
    assert read_back.account_id == "acc_1"
    assert _as_utc(read_back.created_at) == created

    changed = repo.update_status(
        sqlite_session,
        "task_rw",
        shard=shard,
        status="SUCCEEDED",
        progress=100,
        finished_at=_at(hour=9),
    )
    assert changed == 1
    again = repo.get_by_id(sqlite_session, "task_rw", shard=shard)
    assert again is not None
    assert (again.status, again.progress) == ("SUCCEEDED", 100)
    assert _as_utc(again.finished_at) == _at(hour=9)


def test_update_status_leaves_non_target_columns_untouched(sqlite_session: Session) -> None:
    """更新只动目标三列：`created_at` / `model_meta` / `idem_key` 一个都不许变。"""
    repo = TaskRepo()
    shard = _shard()
    created = _at()
    lineage = {"channel": "mock", "modelVersion": "v1", "threshold": 0.5}
    repo.insert(
        sqlite_session,
        _task(
            "task_keep",
            at=created,
            idem_key="idem_keep",
            model_meta=lineage,
            is_eval_sample=True,
        ),
    )

    assert (
        repo.update_status(
            sqlite_session,
            "task_keep",
            shard=shard,
            status="MANUAL_REVIEW",
            progress=50,
            finished_at=None,
        )
        == 1
    )
    kept = repo.get_by_id(sqlite_session, "task_keep", shard=shard)
    assert kept is not None
    assert _as_utc(kept.created_at) == created
    assert kept.model_meta == lineage, "血缘快照被整行覆盖写回了内存里的旧值"
    assert kept.idem_key == "idem_keep"
    assert kept.is_eval_sample is True
    assert (kept.status, kept.progress) == ("MANUAL_REVIEW", 50)


def test_update_status_on_missing_row_returns_zero(sqlite_session: Session) -> None:
    """不存在的行返回 0（不是异常）：调用方据此判断"是否存在"。"""
    changed = TaskRepo().update_status(
        sqlite_session,
        "task_missing",
        shard=_shard(),
        status="FAILED",
        progress=0,
        finished_at=None,
    )
    assert changed == 0


def test_list_by_account_filters_and_paginates(sqlite_session: Session) -> None:
    """本人任务列表：账号过滤取自分片键（R6），排序 `created_at DESC`，分页稳定。"""
    repo = TaskRepo()
    repo.insert(sqlite_session, _task("task_a1", at=_at(day=10)))
    repo.insert(sqlite_session, _task("task_a2", at=_at(day=12)))
    repo.insert(sqlite_session, _task("task_a3", at=_at(day=14)))
    repo.insert(sqlite_session, _task("task_b1", account_id="acc_2", at=_at(day=13)))

    first_page = repo.list_by_account(sqlite_session, shard=_shard(), limit=2, offset=0)
    assert [task.task_id for task in first_page] == ["task_a3", "task_a2"]
    second_page = repo.list_by_account(sqlite_session, shard=_shard(), limit=2, offset=2)
    assert [task.task_id for task in second_page] == ["task_a1"]
    assert all(task.account_id == "acc_1" for task in (*first_page, *second_page)), (
        "list_by_account MUST 按分片键里的 account_id 过滤（R6）"
    )


def test_find_by_idem_key_is_scoped_to_the_account(sqlite_session: Session) -> None:
    """`uk_idem(account_id, idem_key)`：同月表内两个账号可以有同一个幂等键，各查各的。"""
    repo = TaskRepo()
    shard = _shard()
    repo.insert(sqlite_session, _task("task_i1", account_id="acc_1", at=_at(), idem_key="same_key"))
    repo.insert(sqlite_session, _task("task_i2", account_id="acc_2", at=_at(), idem_key="same_key"))

    mine = repo.find_by_idem_key(
        sqlite_session, shard=shard, account_id="acc_1", idem_key="same_key"
    )
    other = repo.find_by_idem_key(
        sqlite_session, shard=shard, account_id="acc_2", idem_key="same_key"
    )
    assert mine is not None and mine.task_id == "task_i1"
    assert other is not None and other.task_id == "task_i2"
    assert (
        repo.find_by_idem_key(sqlite_session, shard=shard, account_id="acc_3", idem_key="same_key")
        is None
    )


def test_missing_in_table_routing_key_raises_1001(sqlite_session: Session) -> None:
    """`task_id` / `idem_key` 缺失 MUST 抛 `MissingShardKeyError(1001)`。

    空串直接去查会静默返回 `None`，让"参数没送到"看起来像"对象不存在"——两者处置完全不同
    （400 vs 404），故在入口炸掉。
    """
    repo = TaskRepo()
    with pytest.raises(MissingShardKeyError) as task_exc:
        repo.get_by_id(sqlite_session, "", shard=_shard())
    assert task_exc.value.code == 1001

    with pytest.raises(MissingShardKeyError) as idem_exc:
        repo.find_by_idem_key(sqlite_session, shard=_shard(), account_id="acc_1", idem_key="  ")
    assert idem_exc.value.code == 1001

    with pytest.raises(MissingShardKeyError) as account_exc:
        repo.find_by_idem_key(sqlite_session, shard=_shard(), account_id="", idem_key="k")
    assert account_exc.value.code == 1001


def test_result_and_correction_round_trip_on_the_same_shard(sqlite_session: Session) -> None:
    """结果表与纠错表都随任务同月：同月读得到，读另一张月表就是空（分片隔离）。"""
    shard = _shard()
    TaskRepo().insert(sqlite_session, _task("task_ocr", at=_at()))
    ocr_repo = OcrRepo()
    ocr_repo.insert(sqlite_session, _result("task_ocr"), shard=shard)

    got = ocr_repo.get_by_id(sqlite_session, "task_ocr", shard=shard)
    assert got is not None
    assert got.validity == "VALID" and got.category_match is True
    assert got.fields_json == [{"name": "营业执照", "value": "911301********1234"}]
    # 同一个 task_id 在**另一张月表**里不存在：分片路由按月份切，不是按账号切。
    assert ocr_repo.get_by_id(sqlite_session, "task_ocr", shard=_shard(month=OTHER_MONTH)) is None

    correction_repo = CorrectionRepo()
    correction_repo.insert(
        sqlite_session, _correction("cor_1", "task_ocr", corrected_at=_at(hour=10)), shard=shard
    )
    correction_repo.insert(
        sqlite_session, _correction("cor_2", "task_ocr", corrected_at=_at(hour=12)), shard=shard
    )
    rows = correction_repo.list_by_task(sqlite_session, "task_ocr", shard=shard, limit=10, offset=0)
    assert [row.correction_id for row in rows] == ["cor_2", "cor_1"], "最近改的先出"
    assert rows[0].confidence == Decimal("0.72")
    page = correction_repo.list_by_task(sqlite_session, "task_ocr", shard=shard, limit=1, offset=1)
    assert [row.correction_id for row in page] == ["cor_1"]


def test_verdict_repo_round_trip_and_at_most_one_verdict(sqlite_session: Session) -> None:
    """R4 实证（沙盒段）：同 `review_id` 第二次写结论 MUST 失败，且**原结论不被覆盖**。"""
    repo = VerdictRepo()
    repo.insert_review(sqlite_session, _review("rev_1"))
    review = repo.get_review(sqlite_session, "rev_1")
    assert review is not None
    assert review.status == "AI_PROCESSING", "未写 status 时应取库的 server_default"

    repo.insert_verdict(sqlite_session, _verdict("rev_1", action="CONFIRM"))
    first = repo.get_verdict(sqlite_session, "rev_1")
    assert first is not None and first.action == "CONFIRM"

    with pytest.raises(DuplicateVerdictError) as excinfo:
        repo.insert_verdict(sqlite_session, _verdict("rev_1", action="REJECT"))
    assert excinfo.value.code == 3007

    still = repo.get_verdict(sqlite_session, "rev_1")
    assert still is not None and still.action == "CONFIRM", "已有结论 MUST NOT 被覆盖（只增不改）"
    assert repo.get_verdict(sqlite_session, "rev_missing") is None


def test_verdict_concurrent_duplicate_is_converted_by_the_primary_key(
    sqlite_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发窗口（TOCTOU）的落地：前置检查没看到结论、但主键拒绝时，MUST 也转成业务异常。

    这条路径单线程进不去（前置检查会先发现重复），故用"**只让第一次前置检查**看不到"的方式
    复现真实的并发窗口：两个复核同时读到"还没有结论"，其中一个先写入，另一个撞主键。
    确定性复现比"起两个线程碰运气"可靠，且正好钉住"转换前 MUST 回查一次"这个区分动作。
    """
    repo = VerdictRepo()
    repo.insert_review(sqlite_session, _review("rev_race"))
    repo.insert_verdict(sqlite_session, _verdict("rev_race", action="CONFIRM"))

    original = VerdictRepo.get_verdict
    calls: list[str] = []

    def blind_on_the_first_check(
        self: VerdictRepo, session: Session, review_id: str
    ) -> ReviewVerdict | None:
        calls.append(review_id)
        if len(calls) == 1:
            return None  # 只让前置检查看不到：模拟"检查与写入之间被人抢先"的窗口
        return original(self, session, review_id)

    monkeypatch.setattr(VerdictRepo, "get_verdict", blind_on_the_first_check)
    with pytest.raises(DuplicateVerdictError) as excinfo:
        repo.insert_verdict(sqlite_session, _verdict("rev_race", action="REJECT"))
    assert excinfo.value.code == 3007
    assert len(calls) == 2, "捕获 IntegrityError 后 MUST 回查一次（用于区分主键冲突与外键失败）"


def test_verdict_foreign_key_failure_is_not_reported_as_duplicate() -> None:
    """外键失败 MUST NOT 被误报成"已有结论"：那是"引用了不存在的审核记录"。

    `IntegrityError` 同时覆盖主键冲突与外键失败，故 `insert_verdict` 的捕获分支用
    "回查是否已有结论"来区分（不解析方言相关的错误码）。本用例把 sqlite 的外键校验打开，
    正面验证这条区分：未知 `review_id` → 抛外键错误，**不是** `DuplicateVerdictError`。
    """
    engine = _sqlite_engine(enforce_fixed_foreign_key=True)
    try:
        with Session(engine) as session:
            with pytest.raises(IntegrityError) as excinfo:
                VerdictRepo().insert_verdict(session, _verdict("rev_unknown"))
            assert not isinstance(excinfo.value, DuplicateVerdictError)
            assert "FOREIGN KEY" in str(excinfo.value).upper(), (
                f"应当是外键失败，实际：{excinfo.value}"
            )
    finally:
        engine.dispose()


def test_repo_writes_open_no_two_phase_transaction(
    sqlite_engine: Engine, sqlite_session: Session
) -> None:
    """R2：仓储的写路径 MUST NOT 引入分布式事务（`begin_twophase` 零次触发）。

    sqlite 方言根本不支持两阶段提交，故这条在沙盒里也是真检查：一旦有人给仓储加上
    `begin_twophase`，本用例会以"方言不支持"暴露出来。
    """
    two_phase: list[Any] = []
    event.listen(sqlite_engine, "begin_twophase", lambda *args: two_phase.append(args))
    TaskRepo().insert(sqlite_session, _task("task_2pc", at=_at()))
    VerdictRepo().insert_review(sqlite_session, _review("rev_2pc"))
    VerdictRepo().insert_verdict(sqlite_session, _verdict("rev_2pc"))
    assert two_phase == []


# ---------------------------------------------------------------------------
# 7. 真实 MySQL 集成段（默认不跑）
# ---------------------------------------------------------------------------
#: 演练库。
DRILL_DATABASE: Final[str] = "aicore_test"

#: 演练年：远未来（`2098`），不与真实数据、也不与另两个分片用例的 `2099` 撞车。
DRILL_YEAR: Final[str] = "2098"


def _drill_months() -> tuple[str, str]:
    """两个相邻的演练月，**按进程号取值**（并发跑测试的进程互不干扰）。

    为什么必须按进程隔离：本文件会被**并发执行**（多个 subagent 同时跑测试）。写死月份时
    两个进程会互相 `DROP` 对手刚建的表，失败现象与被测代码毫无关系——
    `tests/repository/test_apply_ddl_mysql.py` 的首轮实测记录就是这么写的。
    """
    first = (os.getpid() % 6) * 2 + 1
    return f"{DRILL_YEAR}{first:02d}", f"{DRILL_YEAR}{first + 1:02d}"


def _mysql_engine() -> Engine:
    """连**演练库**的引擎；凭据只从 `DSH_IT_MYSQL_*` 取（MUST NOT 硬编码）。

    环境变量口径与 `tests/conftest.py` 一致：`DSH_IT_MYSQL_PASSWORD` 由 conftest 从本机已被
    gitignore 的 `.env` 回填；取不到就显式 skip，而不是把凭据写进版本库换一次"绿灯"。
    """
    password = os.environ.get("DSH_IT_MYSQL_PASSWORD")
    if not password:
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "集成用例需要真实演练库凭据；凭据 MUST NOT 硬编码进仓库"
        )
    url = URL.create(
        drivername="mysql+pymysql",
        username=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        password=password,
        host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
        database=os.environ.get("DSH_IT_MYSQL_DATABASE", DRILL_DATABASE),
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True)


def _require_mysql() -> Engine:
    """连不上就**显式跳过**（含原因），而不是让用例随机失败或静默通过。"""
    try:
        engine = _mysql_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"需要真实 MySQL（{DRILL_DATABASE}@127.0.0.1:3306）才能验证仓储落地："
            f"{type(exc).__name__}: {exc}"
        )
    return engine


def _drop_drill_shards(engine: Engine, months: Sequence[str]) -> None:
    """只 DROP 本用例自己建的分片表（MUST NOT `DROP DATABASE`、MUST NOT 碰固定名表）。

    **逆建表顺序删**：`ocr_correction` 有指向同月 `ocr_result` 的物理外键，先删被引用表会被
    MySQL 以 3730 拒绝（`test_apply_ddl_mysql.py` 已有同款实测记录）。
    """
    with engine.begin() as conn:
        for month in months:
            for logical in reversed(SHARDED_LOGICAL_TABLES):
                conn.execute(text(f"DROP TABLE IF EXISTS `{logical}_{month}`"))


def _mysql_temp_table_ddl(table: Table) -> str:
    """固定名表的**会话级临时表** DDL（MySQL）。

    为什么用临时表而不是真实表：6 张固定名表是共享对象（别的用例、同事的库都在用，
    `test_apply_ddl_mysql.py` 还会在结束时 DROP 它们），写真实表会互相打架；临时表只在
    **本连接**可见、连接归还即消失，既跑到了真实 MySQL 的 DDL 与约束语义，又不碰真实表。
    两处必须处理：MySQL 的临时表**不支持外键**（DDL 里 MUST NOT 带外键），
    以及把 `CREATE TABLE` 换成 `CREATE TEMPORARY TABLE`。
    """
    ddl = str(
        CreateTable(table, include_foreign_key_constraints=[]).compile(dialect=mysql.dialect())
    )
    return ddl.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1)


@pytest.fixture
def mysql_env() -> Iterator[tuple[Engine, str, str]]:
    """真实 MySQL：两个相邻演练月的分片表 + 引擎；结束时逆序 DROP 自己建的表。

    不建任何固定名表：`VerdictRepo` 的用例走**会话级临时表**（见 `_mysql_temp_table_ddl`）。
    """
    engine = _require_mysql()
    first, second = _drill_months()
    _drop_drill_shards(engine, (first, second))
    try:
        with engine.begin() as conn:
            for month in (first, second):
                ensure_month_tables(conn, month)
        yield engine, first, second
    finally:
        _drop_drill_shards(engine, (first, second))
        engine.dispose()


@pytest.fixture
def mysql_session(mysql_env: tuple[Engine, str, str]) -> Iterator[Session]:
    """真实 MySQL 会话 + 两张固定名表的**临时表**（建在会话自己的连接上）。

    临时表是连接级的：MUST 在**本会话的连接**上建，换一条连接就看不见了。
    teardown 先 DROP 临时表再关会话（顺带 `engine.dispose()`：临时表即使没删掉，
    也会随连接关闭消失，MUST NOT 留给同进程后续用例一条"带着脏临时表"的连接）。
    """
    engine, _first, _second = mysql_env
    session = Session(engine)
    connection = session.connection()
    for table in (VisionReview.__table__, ReviewVerdict.__table__):
        connection.exec_driver_sql(_mysql_temp_table_ddl(table))
    try:
        yield session
    finally:
        with contextlib.suppress(Exception):
            # 连接已失效时临时表随连接消失，DROP 失败无需额外处理。
            session.connection().exec_driver_sql(
                "DROP TEMPORARY TABLE IF EXISTS review_verdict, vision_review"
            )
        session.rollback()
        session.close()
        engine.dispose()


@pytest.mark.integration
def test_sharded_repos_round_trip_on_real_mysql(
    mysql_session: Session, mysql_env: tuple[Engine, str, str]
) -> None:
    """用例 6：真实 MySQL 上四类存取各一次（插入 → 按分片键读回 → 更新 → 再读）。"""
    _engine, first, second = mysql_env
    repo = TaskRepo()
    shard = ShardKey(account_id="acc_it", created_at=_at(month=first))
    other_shard = ShardKey(account_id="acc_it", created_at=_at(month=second))
    repo.insert(mysql_session, _task("task_it_1", account_id="acc_it", at=_at(month=first)))

    read_back = repo.get_by_id(mysql_session, "task_it_1", shard=shard)
    assert read_back is not None and read_back.account_id == "acc_it"
    # 分片隔离的正面证据：另一个月的表里没有这一行。
    assert repo.get_by_id(mysql_session, "task_it_1", shard=other_shard) is None
    assert repo.find_by_idem_key(
        mysql_session, shard=shard, account_id="acc_it", idem_key="idem_it"
    ) is None, "本行没写幂等键，故按幂等键查不到（uk_idem 的 NULL 豁免）"
    assert [
        item.task_id
        for item in repo.list_by_account(mysql_session, shard=shard, limit=10, offset=0)
    ] == ["task_it_1"]

    # 只更新目标三列：更新后 `created_at` / `model_meta` / `idem_key` 必须原封不动。
    assert (
        repo.update_status(
            mysql_session,
            "task_it_1",
            shard=shard,
            status="SUCCEEDED",
            progress=100,
            finished_at=_at(hour=9, month=first),
        )
        == 1
    )
    again = repo.get_by_id(mysql_session, "task_it_1", shard=shard)
    assert again is not None
    assert (again.status, again.progress) == ("SUCCEEDED", 100)
    assert again.model_meta is None
    assert again.idem_key is None
    assert _as_utc(again.created_at) == _at(month=first)

    # 同值重复更新：**1**（本栈实测口径，与"裸 MySQL 默认"相反）。
    # SQLAlchemy 的 MySQL 方言在连接时硬编码加上 `CLIENT.FOUND_ROWS`，故 `rowcount` 是
    # **匹配行数**而不是变更行数（见 `mysql/base.py` 的 "rowcount Support" 一节）：
    # 同值重放返回 1、不存在的行返回 0。调用方据此判断"是否存在"是可靠的，
    # 但 MUST NOT 反过来把 1 当成"值一定变了"。
    assert (
        repo.update_status(
            mysql_session,
            "task_it_1",
            shard=shard,
            status="SUCCEEDED",
            progress=100,
            finished_at=_at(hour=9, month=first),
        )
        == 1
    )

    # 不存在的行：受影响行数 0。
    assert (
        repo.update_status(
            mysql_session,
            "task_it_missing",
            shard=shard,
            status="FAILED",
            progress=0,
            finished_at=None,
        )
        == 0
    )

    # 结果表 + 纠错表：同月可读，另一张月表读不到。
    ocr_repo = OcrRepo()
    ocr_repo.insert(mysql_session, _result("task_it_1"), shard=shard)
    assert ocr_repo.get_by_id(mysql_session, "task_it_1", shard=shard) is not None
    assert ocr_repo.get_by_id(mysql_session, "task_it_1", shard=other_shard) is None

    correction_repo = CorrectionRepo()
    correction_repo.insert(
        mysql_session,
        _correction("cor_it_1", "task_it_1", corrected_at=_at(hour=10, month=first)),
        shard=shard,
    )
    corrections = correction_repo.list_by_task(
        mysql_session, "task_it_1", shard=shard, limit=10, offset=0
    )
    assert [row.correction_id for row in corrections] == ["cor_it_1"]


@pytest.mark.integration
def test_task_idem_key_round_trip_on_real_mysql(
    mysql_session: Session, mysql_env: tuple[Engine, str, str]
) -> None:
    """`uk_idem(account_id, idem_key)` 的正面路径：同 `imageKey`+`docType` 重复提交返回原任务号。"""
    _engine, first, _second = mysql_env
    repo = TaskRepo()
    shard = ShardKey(account_id="acc_it", created_at=_at(month=first))
    repo.insert(
        mysql_session,
        _task("task_it_idem", account_id="acc_it", at=_at(month=first), idem_key="k1"),
    )
    found = repo.find_by_idem_key(
        mysql_session, shard=shard, account_id="acc_it", idem_key="k1"
    )
    assert found is not None and found.task_id == "task_it_idem"
    assert (
        repo.find_by_idem_key(mysql_session, shard=shard, account_id="acc_other", idem_key="k1")
        is None
    ), "幂等键 MUST 按账号隔离（uk_idem 是两列唯一键，R6）"


@pytest.mark.integration
def test_verdict_repo_at_most_one_verdict_on_real_mysql(
    mysql_session: Session, mysql_env: tuple[Engine, str, str]
) -> None:
    """用例 8（R4 实证）：同一 `review_id` 插两次结论，第二次 MUST 失败且形态明确。"""
    _ = mysql_env
    repo = VerdictRepo()
    repo.insert_review(mysql_session, _review("rev_it_1"))
    assert repo.get_review(mysql_session, "rev_it_1") is not None

    repo.insert_verdict(mysql_session, _verdict("rev_it_1", action="CONFIRM"))
    first = repo.get_verdict(mysql_session, "rev_it_1")
    assert first is not None and first.action == "CONFIRM"

    with pytest.raises(DuplicateVerdictError) as excinfo:
        repo.insert_verdict(mysql_session, _verdict("rev_it_1", action="REJECT"))
    assert excinfo.value.code == 3007
    still = repo.get_verdict(mysql_session, "rev_it_1")
    assert still is not None and still.action == "CONFIRM", "已有结论 MUST NOT 被覆盖"


@pytest.mark.integration
def test_cross_shard_write_is_rejected_and_no_two_phase_on_real_mysql(
    mysql_session: Session, mysql_env: tuple[Engine, str, str]
) -> None:
    """用例 7：一次调用里对两个月写入 → `CrossShardOperationError`，且**没有**两阶段提交。"""
    engine, first, second = mysql_env
    two_phase: list[Any] = []
    event.listen(engine, "begin_twophase", lambda *args: two_phase.append(args))
    repo = TaskRepo()
    first_shard = ShardKey(account_id="acc_it", created_at=_at(month=first))
    second_shard = ShardKey(account_id="acc_it", created_at=_at(month=second))

    @cross_shard_transaction_guard("双月写任务")
    def write_two_months(session: Session, left: ShardKey, right: ShardKey) -> None:
        repo.insert(session, _task("task_it_left", at=left.created_at))
        repo.insert(session, _task("task_it_right", at=right.created_at))

    with pytest.raises(CrossShardOperationError) as excinfo:
        write_two_months(mysql_session, first_shard, second_shard)
    assert excinfo.value.code == 1003

    # 守卫在写之前就拒了：两个月里都没有落库。
    assert repo.get_by_id(mysql_session, "task_it_left", shard=first_shard) is None
    assert repo.get_by_id(mysql_session, "task_it_right", shard=second_shard) is None
    assert two_phase == [], "MUST NOT 开启两阶段提交（禁止分布式事务）"
