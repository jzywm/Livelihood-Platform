"""仓储基类：分片表名的**唯一**解析处 + 跨分片拒绝（Task 3.7）。

## 一、权威依据

- spec **§2.3**：分片表只有 3 张（`ai_task` / `ocr_result` / `ocr_correction`），分片键是
  `ShardingKey(account_id, created_at)`，**禁止跨分片 JOIN / 聚合 / 事务**，
  查询 MUST 携带分片键下推；
- spec **§5.7**：repository 四类（任务 / 结果 / 纠错 / 复核结论）与事务边界——
  **单表一事务；同分片跨表可合并；跨分片拆为多次独立事务 + 幂等补偿，不引入分布式事务**；
- `services/aicore/docs/er.md` **§5.3**（同一组路由禁令）、**§5.5**（写后立即读强制走主库）、
  **§7.1~§7.9**（各表索引与约束，尤其 §7.3 只增不改、§7.6 每审核记录至多一条结论）。

## 二、七条硬约束 → 代码落点

- **R1（读取方法 MUST 收分片键；缺了直接抛错，MUST NOT 退化为全表扫描）**：
  `ShardKey` 在构造期校验"账号非空 + `created_at` 带时区"；表内路由键（`task_id` 这类）
  复用 Task 3.3 的 `require_shard_key`；四个仓储的读取方法签名都带 `shard`
  （`tests/repository/test_repos.py` 用 `inspect.signature` 逐方法断言）。
- **R2（单表一事务；同分片跨表可合并；跨分片拆多次独立事务；MUST NOT 分布式事务）**：
  `require_same_shard` 与 `cross_shard_transaction_guard`，判据**委托** Task 3.3 的
  `assert_single_shard`；本层 MUST NOT `commit()`、MUST NOT 触 `begin_twophase`。
- **R3（写后立即读强制走主库）**：本层**不自开引擎与会话**——写方法与读方法收的是**同一个**
  调用方 `Session`，写完立刻用同一会话读回，落的就是主库连接；本层 MUST NOT 提供
  "读不到就回落从库"这类回退（那正是 R3 要禁的形态）。
- **R4（`review_verdict` 每审核记录至多一条结论、只增不改）**：`VerdictRepo.insert_verdict`
  （前置检查 + 主键冲突转换），且该类**没有任何** verdict 更新路径。
- **R5（`ocr_correction` 只增不改）**：`CorrectionRepo` 只有 `insert` + 只读方法。
- **R6（任务仅本人可查；越权判定属 service，但 repository MUST 提供按 `account_id` 过滤）**：
  `TaskRepo.list_by_account` 的账号取自分片键、`find_by_idem_key` 的账号是必填参数；
  **不提供**"只按 `task_id` 查、不带账号"的便捷入口。
- **R7（repository MUST NOT import service / provider）**：本模块只 import `aicore.core.*`、
  `aicore.repository.*` 与 `sqlalchemy`（`.importlinter` 契约 3 / 4）。

## 三、物理表名怎么落到 SQL 上（**实测选型**，不是凭感觉挑的）

工单列了三条候选路径。两次一次性探针（跑完即删）的实测结论如下，
原始输出抄在 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.7-report.md`：

- **② `aliased(Model, name=物理名)`：读错表。** 实测编译出
  `SELECT ... FROM ai_task AS ai_task_202607` —— `name=` 的语义是 **SQL 别名**，
  底表仍是逻辑表 `ai_task`（生产上并不存在这样一张表）；写入路径另报
  `AttributeError: 'AnnotatedAlias' object has no attribute '_autoincrement_column'`；
  换成 `aliased(Model, <物理表副本>)` 则报
  `InvalidRequestError: Query contains no columns with which to SELECT from`。
- **① `table_prefix` + `before_cursor_execute` 语句改写：结构上不可行。**
  官方示例要在**引擎**上注册事件监听，而本层只收调用方传入的 `Session`
  （与 Task 3.4 解耦的硬要求：MUST NOT 自开引擎），注册全局监听既越权、又会影响进程内
  所有语句；且占位前缀要写进 `__tablename__`，而 Task 3.2 已定"元数据里只有逻辑名"、
  Task 3.6 的三源比对依赖这一点，MUST NOT 改。
- **③ `text()` 手写 SQL：未采用。** 会丢掉类型与参数绑定，且与"模型是唯一代码侧映射"相悖，
  故不适用工单要求的"选它须给参数绑定方案"。

**本层的落点**：用 `Table.to_metadata(MetaData(), name=物理名)` 复制出一张**物理表对象**，
读与写全部走它上面的 Core 语句。同一探针实测编译结果：

```
SELECT ai_task_202607.task_id, ... FROM ai_task_202607 WHERE ai_task_202607.task_id = %s
INSERT INTO ai_task_202607 (task_id, account_id, ...) VALUES (%s, %s, ...)
UPDATE ai_task_202607 SET status=%s, progress=%s, finished_at=%s WHERE ai_task_202607.task_id = %s
```

三点性质：**列定义全部来自 `models.py` 的元数据**（`to_metadata` 复制列、类型、可空性、
约束、索引；`__tablename__` 一个字符没改，故 Task 3.6 拿 `Base.metadata` 做的三源比对不受
影响，也**没有**第二套模型）；参数是真绑定参数（不是拼串）；副本按 `(逻辑表, 物理名)` 缓存，
一个月一张。

**读回来为什么是"实体构造"而不是 ORM 查询**：分片表的 SQL 打在物理表副本上，
`Session.execute()` 回的是 `RowMapping`，故 `_to_entity()` 用 Task 3.2 的声明式构造器把行
还原成实体（列名与映射属性名一致，用例有一条防漂移断言钉住这个前提）。固定名表
（`vision_review` / `review_verdict`）没有表名改写问题，`VerdictRepo` 直接用 ORM 实体查询。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, ClassVar, Final, Generic, TypeVar, cast

from sqlalchemy import MetaData, Select, Table, insert
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.orm import Mapper, Session

from aicore.repository.models import LOGICAL_TABLE_NAMES, Base
from aicore.repository.sharding import (
    assert_single_shard,
    physical_table_name,
    require_shard_key,
    shard_month_of,
)

#: 模型类型变量：四个仓储各自绑定一个模型（`TaskRepo(BaseRepo[AiTask])` 这样用）。
ModelT = TypeVar("ModelT", bound=Base)

#: 被装饰函数类型变量（`cross_shard_transaction_guard` 用）。
F = TypeVar("F", bound=Callable[..., Any])

#: 逻辑表名 → `models.py` 里的 Table 对象（`LOGICAL_TABLE_NAMES` 的反查，只建一次）。
#:
#: `DeclarativeBase.__table__` 在类型上是 `FromClause`（SQLAlchemy 的声明式基类不承诺它
#: 一定是 `Table`），但声明式映射的类在运行期必然是 `Table`，且下面 `to_metadata` 只对
#: `Table` 有效，故此处 cast 一次并在此说明来源，MUST NOT 在别处再 cast。
_LOGICAL_TABLES: Final[Mapping[str, Table]] = {
    logical: cast("Table", model.__table__) for model, logical in LOGICAL_TABLE_NAMES.items()
}

#: 物理表对象缓存：`(逻辑表, 物理名) -> Table`。
_PHYSICAL_TABLES: dict[tuple[str, str], Table] = {}


def physical_table(logical: str, month: str) -> Table:
    """逻辑表 + 分片月 → **物理表对象**（`logical_YYYYMM`），读 / 写都用它。

    选型理由与实测证据见模块 docstring 第三节。三条实现口径：

    - **表名由 Task 3.3 现算**（`physical_table_name`）：非分片表一律 `ParamError(1002)`，
      故本函数只服务 3 张分片表——放行会造出 `vision_review_202601` 这种谁也查不到的孤儿表；
    - **列定义 MUST 由 `models.py` 复制**（`to_metadata`），MUST NOT 在这里手写列清单：
      手写就是第二套模型，DDL 与代码两侧一旦漂移，Task 3.6 的三源比对也抓不到；
    - **每个副本自带一个 `MetaData`**：同一个 `MetaData` 里定义两张同名表会抛
      `InvalidRequestError: Table ... is already defined`，而本函数会被多线程并发调用
      （Task 3.4 的会话跑在线程池里）。用 `dict.setdefault` 做无锁去重：并发下最坏是
      多构造一份副本并被丢弃，既不会抛错，也不会让两个调用方拿到内容不一致的表。
    """
    name = physical_table_name(logical, month)
    key = (logical, name)
    cached = _PHYSICAL_TABLES.get(key)
    if cached is not None:
        return cached
    copy = _LOGICAL_TABLES[logical].to_metadata(MetaData(), name=name)
    return _PHYSICAL_TABLES.setdefault(key, copy)


def entity_values(entity: Base) -> dict[str, Any]:
    """ORM 实体 → Core `INSERT` 的参数字典（**值为 `None` 的列整个不进列清单**）。

    为什么 `None` 要省掉、而不是显式写 NULL：DDL 里 `status` / `progress` /
    `is_eval_sample` / `created_at` 这类列带 `server_default`（Task 3.2 逐列镜像过），
    显式写 NULL 会把"让库取默认值"变成"写一个 NULL"（NOT NULL 列直接失败）；而**可空列**
    省掉与写 NULL 在 MySQL 里等价（可空列的隐含默认就是 NULL）。取值时刻由业务决定，
    本函数只负责"内存里没赋值的列交给库"。

    列名取 `column.key`、属性名取 mapper 的映射键：两者在本项目的模型上恒等，
    但顺着两者各自的定义取，模型若将来给某列写了 `key=` 也不会静默写错列。
    """
    mapper: Mapper[Any] = cast("Mapper[Any]", sa_inspect(type(entity)))
    values: dict[str, Any] = {}
    for column in mapper.columns:
        value = getattr(entity, mapper.get_property_by_column(column).key)
        if value is not None:
            values[column.key] = value
    return values


@dataclass(frozen=True)
class ShardKey:
    """分片键：`account_id` + `created_at`（`er.md` §5.3 的 `ShardingKey` 约定）。

    **两个字段都由调用方给出**：`account_id` 是"谁的数据"，`created_at` 是"哪个月"。

    **不变式（构造期校验，比散在各调用点可靠）**：

    - `account_id` MUST 非空：空白账号查不出任何东西，却会让"缺分片键"以"查无数据"的
      形态静默出现；缺 → `MissingShardKeyError(1001)`；
    - `created_at` MUST 是 **aware** `datetime`：naive 值既可能是 UTC 也可能是本地时间，
      猜错就跨月错片，而错片的表现是"数据写到了另一个月的表里"，比抛错危险得多；
      naive → `ParamError(1002)`（判据直接借 Task 3.3 的 `shard_month_of`，MUST NOT 重写）。

    **时区口径**：`month` 先把 `created_at` 归一到 UTC 再取月，故
    `2026-01-01 00:00+08:00` 的分片月是 **`202512`**（它的 UTC 时刻在 2025-12-31）。
    """

    account_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_shard_key(self.account_id, field="account_id")
        # 借 Task 3.3 的 shard_month_of 做时区校验：naive、以及 tzinfo 非空但 utcoffset()
        # 为 None 的畸形时区，两种都拦。这里只要它的校验副作用，返回值由 month 现算。
        shard_month_of(self.created_at)

    @property
    def month(self) -> str:
        """分片月 `YYYYMM`（**派生属性**，由 `created_at` 现算，MUST NOT 缓存成字段）。

        **为什么不做成字段**：字段与 `created_at` 会变成两个能互相漂移的事实源——改了
        `created_at` 忘了改 `month`，SQL 就打到了另一个月的表上，而"表存在、写入成功、
        查询永远落空"是最难排查的一类故障。派生属性让这种漂移在结构上不可能发生。
        """
        return shard_month_of(self.created_at)


def _shard_keys_in(values: Iterable[Any]) -> list[ShardKey]:
    """从一次调用的实参里收集 `ShardKey`（含 `list` / `tuple` / `set` 里的元素）。

    批量写常常把分片键放在列表里传（`write_many(session, keys, rows)`），故顺带看一层容器；
    **不递归**嵌套结构：判据越简单，"它到底挡得住什么"越说得清。
    """
    found: list[ShardKey] = []
    for value in values:
        if isinstance(value, ShardKey):
            found.append(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            found.extend(item for item in value if isinstance(item, ShardKey))
    return found


def cross_shard_transaction_guard(operation: str) -> Callable[[F], F]:
    """装饰器：拒绝"在一次调用里对**多个分片**发起写"（R2，spec §5.7 / er.md §5.3）。

    判据**委托** Task 3.3 的 `assert_single_shard`（MUST NOT 各写一份）：本次调用收集到的
    分片键若跨了两个月 → `CrossShardOperationError(1003)`；**一个分片键都没收集到** →
    `MissingShardKeyError(1001)`，即 fail closed——守卫无法判断这次操作落在哪个分片时，
    放行等于让"忘了传分片键"静默通过。

    **它挡得住什么、挡不住什么（诚实标注，因为这决定评审该看哪里）**：

    - 挡得住：被装饰函数在同一次调用里同时拿到两个月（最容易被写成"一次分布式事务"的写法）；
    - **挡不住"跨事务的跨分片"**：先写 A 月、提交，再写 B 月，是两次独立事务，按 R2 本就
      允许（拆为多次独立事务 + 幂等补偿）。事务边界归调用方，装饰器不越权去数事务；
    - **挡不住"函数从别处取分片键"**：分片键只从入参收集；函数若自己从 session 或上下文里
      摸出第二个分片，本装饰器看不见。R2 的最终保证仍在评审与 service 层"按分片拆调用"。

    实现上用 `functools.wraps`：包装函数的签名经 `__wrapped__` 仍可被 `inspect.signature`
    读到（R1 的签名断言会遍历四个仓储的方法，装饰器不改变这一点）。
    """

    def decorate(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            keys = _shard_keys_in((*args, *kwargs.values()))
            assert_single_shard((key.month for key in keys), operation=operation)
            return func(*args, **kwargs)

        return cast("F", wrapper)

    return decorate


# 工单逐字要求 `class BaseRepo(Generic[ModelT])`（PEP 695 的 `class BaseRepo[ModelT]` 语义等价
# 但形状不同），且验收项点名"mypy strict 下 Generic[ModelT] 必须过"，故保留工单给定的写法，
# 对 UP046 显式豁免（不是漏改）。
class BaseRepo(Generic[ModelT]):  # noqa: UP046
    """仓储基类：把"分片表名解析 + 跨分片拒绝 + 分片表读写"收在一处。

    子类 MUST 声明两个类属性：`logical_table`（**逻辑**表名，即 `models.py` 的
    `__tablename__`，不含月份后缀）与 `model`（对应模型）。

    `model` 是本次在工单给定的两个成员之外补的一个类属性（偏离项已登记在报告）：
    四个仓储都要"逻辑名 → 物理表对象 / 行 → 实体"，放基类可避免四份重复。
    它声明成普通类属性、而不是 `ClassVar[type[ModelT]]`，是因为 **mypy 拒绝 ClassVar 里
    出现类型变量**（`ClassVar cannot contain type variables`）；普通类属性既受泛型参数约束，
    又能在子类里收窄成 `type[AiTask]`。
    """

    #: 逻辑表名（`models.py` 的 `__tablename__`，不含月份后缀）。
    logical_table: ClassVar[str]
    #: 逻辑表对应的 ORM 模型（子类在类体里赋具体类，见类 docstring）。
    model: type[ModelT]

    def physical_name(self, key: ShardKey) -> str:
        """分片键 → 本表物理名（如 `ai_task_202607`）；月份由 `key.month` 现算。"""
        return physical_table_name(self.logical_table, key.month)

    def require_same_shard(self, *keys: ShardKey, operation: str) -> str:
        """单分片守卫：本次操作涉及的月份去重后必须恰好 1 个，返回本表物理名。

        判据**委托** Task 3.3 的 `assert_single_shard`（MUST NOT 各写一份）：空集 →
        `MissingShardKeyError(1001)`、跨月 → `CrossShardOperationError(1003)`。
        两份判据必然漂移，而漂移的表现是"某条路径放行了跨分片"，故只允许有一处实现。

        `operation` 只进报错文案：跨分片的消息要点名是哪次操作跨了片，运维才能直接定位。
        """
        month = assert_single_shard((key.month for key in keys), operation=operation)
        return physical_table_name(self.logical_table, month)

    # ------------------------------------------------------------------
    # 分片表上的共用动作：表名一律由月份现算，MUST NOT 出现逻辑表名的裸查询
    # ------------------------------------------------------------------
    def _table(self, key: ShardKey) -> Table:
        """本表在 `key` 月份上的**物理表对象**（读 / 写都用它）。"""
        return physical_table(self.logical_table, key.month)

    def _insert(self, session: Session, key: ShardKey, entity: ModelT) -> None:
        """把实体写进 `key` 月份的物理分片表。

        **不 `commit()`、不 `flush()`**：事务边界归调用方（spec §5.7 的"单表一事务"是
        service 层决定的事）；本层只回答"在这个会话里怎么写这张分片表"。
        """
        session.execute(insert(self._table(key)).values(entity_values(entity)))

    def _select_one(self, session: Session, statement: Select[Any]) -> ModelT | None:
        """执行查询取第一行 → 实体；没有行时返回 `None`（不是抛异常）。

        "不存在"是正常结果（任务还没落库、幂等键首次出现），故返回 `None` 让调用方决定
        是 404 还是继续；`MUST NOT` 在仓储层抛 `NotFoundError`——那会把"查不到"与
        "不该查"混成一个码（越权与不存在必须能被 service 层区分处置）。
        """
        row = session.execute(statement).mappings().first()
        return None if row is None else self._to_entity(row)

    def _select_many(self, session: Session, statement: Select[Any]) -> list[ModelT]:
        """执行查询取全部行 → 实体列表（分页由调用方在语句上表达：`limit` / `offset`）。"""
        rows = session.execute(statement).mappings().all()
        return [self._to_entity(row) for row in rows]

    def _update(self, session: Session, statement: Any) -> int:
        """执行 UPDATE 并返回**受影响行数**。

        `cast` 的理由：`Session.execute()` 的静态返回类型是 `Result`，而实际执行 DML 时
        回的是 `CursorResult`（`rowcount` 只在后者上）。这里 cast 一次并说明来源，
        MUST NOT 在别处再 cast。
        """
        result = cast("CursorResult[Any]", session.execute(statement))
        return result.rowcount

    def _to_entity(self, row: RowMapping) -> ModelT:
        """一行（`RowMapping`）→ ORM 实体（Task 3.2 的声明式构造器）。

        返回的是**游离（transient）实体**：它不属于任何 session 的 identity map，故同一行
        读两次会得到两个对象。代价可接受——本项目模型没有任何 relationship，不存在懒加载
        语义；换来的是"分片表名现算"这件事不依赖改 `__tablename__` 或另建一套映射。

        前提是**每列的列名与映射属性名一致**（`Model(**row)` 要求如此）：
        `tests/repository/test_repos.py` 的 `test_model_column_names_match_attribute_names`
        正面钉住它，让"不一致"在测试期就炸，而不是等到运行期的 `TypeError`。
        """
        constructor = cast("Callable[..., ModelT]", self.model)
        return constructor(**dict(row))
