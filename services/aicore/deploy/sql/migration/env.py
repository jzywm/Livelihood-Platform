"""Alembic 运行环境（Task 3.5）：结构从元数据来、连接串从环境来、分片表不进基线。

## 三条分工（spec §5.5）

1. **纯 SQL DDL（`deploy/sql/ddl/**`）是权威定义**；本目录的迁移是**同一份结构的
   另一条落地路径**，由 `target_metadata = Base.metadata` 生成，MUST NOT 手写第二份
   列定义。两条路径的一致性由 Task 3.6 的三源比对强制，不靠人记得同步。
2. **连接串只从环境变量组装**：口令 MUST NOT 写进 `alembic.ini`（该文件入库）。
3. **分片表不进基线**：三张分片表的物理名带月份（`ai_task_202607`），月份是
   **运行期数据**；把某个月的物理表写死进迁移，等于让"新月份"必须等一次发版。
   物理表由 `create_shard_tables_for()` 在 upgrade 之后现建（委托 Task 3.3 的
   `ensure_month_tables`），入口是 `-x shard_month=YYYYMM`。

## `include_object` 为什么要同时排除"逻辑名"和"物理名"

反向的一个坑（实测推演，非臆测）：演练库里已经有 `ai_task_202607` 这类物理表，
而元数据里只有逻辑名 `ai_task`。autogenerate 见到"库里有、模型里没有"的表会生成
`op.drop_table('ai_task_202607')` —— 那既是破坏性 DDL，也让"重复 autogenerate
产生空迁移"这条幂等口径永远不成立。故过滤按**逻辑名**判：`normalize_table_name()`
（Task 3.6 的实现，MUST NOT 在本文件再写一份后缀剥离）。

## downgrade 默认被拒（spec §2.3 / er.md §5.6）

演进走 expand-migrate-contract（双写 → 回灌 → 切读 → 收缩），**禁止破坏性 DDL 直上
生产**。基线迁移的 `downgrade()` 只服务演练，故本环境默认拒绝 `alembic downgrade`；
演练要显式给 `-x allow_downgrade=1`。误敲一次 downgrade 的代价是生产少 6 张表。

## 两处已知边界（如实登记，不假装覆盖）

- 守卫看的是 `config.cmd_opts.cmd`，而 `cmd_opts` 只在 **CLI** 路径上被赋值
  （`alembic.config.CommandLine.main`）；`alembic.command.downgrade(cfg, ...)`
  这类程序化调用不带它，守卫对它**不生效**。演练因此一律走 CLI。
- 离线模式（`upgrade head --sql`）只渲染 SQL、不连库，故**不建分片表**
  （`-x shard_month=` 在离线模式被忽略），这是"没有连接就没有 DDL"的直接推论。
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Final

from alembic import context, util
from alembic.operations import ops as alembic_ops
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL, Connection

from aicore.core.config import get_settings
from aicore.repository.models import Base
from aicore.repository.schema import normalize_table_name
from aicore.repository.sharding import SHARDED_TABLES, ensure_month_tables

# Alembic 注入的运行时上下文：`from alembic import context` 拿到的是**活代理**，
# 下面的 `context.is_offline_mode()` / `context.configure()` 都由它转发。
config = context.config

if config.config_file_name is not None:
    # 读 alembic.ini 里的 `[loggers]`：不配置日志时 `upgrade head` 一行都不打，
    # 运维无法从输出判断"跑没跑、跑到哪个版本"。
    fileConfig(config.config_file_name)

#: 迁移的**唯一结构来源**（spec §5.5：从元数据生成，不手写第二份 DDL）。
#: 注意它含 9 张表（模型侧是逻辑名），三张分片表由下面的 `include_object` 排除。
target_metadata = Base.metadata

#: `-x shard_month=YYYYMM`：upgrade 跑完后顺带建出该月的 3 张分片物理表。
X_SHARD_MONTH: Final[str] = "shard_month"
#: `-x allow_downgrade=1`：显式放行降级（默认拒绝，见模块 docstring）。
X_ALLOW_DOWNGRADE: Final[str] = "allow_downgrade"

#: 演练库轨（DSH integration-test）：与 `tests/conftest.py` / `scripts/apply_ddl.py`
#: 同一组约定。触发条件是**口令存在**，与 `apply_ddl.build_engine` 完全一致。
_DRILL_PREFIX: Final[str] = "DSH_IT_MYSQL_"
_DRILL_DEFAULTS: Final[dict[str, str]] = {
    "HOST": "127.0.0.1",
    "PORT": "3306",
    "USER": "aicore_dev",
    "DATABASE": "aicore_test",
}


def x_arguments() -> dict[str, str]:
    """`-x key=value` 参数（Alembic 的扩展参数通道，比环境变量更适合一次性开关）。"""
    raw = context.get_x_argument(as_dictionary=True)
    return {str(key): str(value) for key, value in raw.items()}


def _drill_url() -> URL | None:
    """演练库轨的 URL；未配置演练口令时返回 `None`（回落应用配置轨）。"""
    password = os.environ.get(f"{_DRILL_PREFIX}PASSWORD")
    if not password:
        return None

    def _part(name: str) -> str:
        return os.environ.get(f"{_DRILL_PREFIX}{name}") or _DRILL_DEFAULTS[name]

    return URL.create(
        drivername="mysql+pymysql",
        username=_part("USER"),
        password=password,
        host=_part("HOST"),
        port=int(_part("PORT")),
        database=_part("DATABASE"),
        query={"charset": "utf8mb4"},
    )


def database_url() -> URL:
    """目标库连接串。两条轨，优先级固定：

    1. **演练库轨** `DSH_IT_MYSQL_*`（`DSH_IT_MYSQL_PASSWORD` 非空即生效）；
    2. **应用配置轨** `AICORE_MYSQL_*`（复用 `core.config.Settings`）。

    为什么演练轨必须优先（这是实测过的坑，不是洁癖）：`tests/conftest.py` 会往进程
    环境注入 `AICORE_MYSQL_PASSWORD=test_password` 这类占位值，应用轨读到的必然是
    **假凭据** —— 于是连库被拒 → 用例走 `pytest.skip` → 整条门禁静默失效；
    而本机 `.env` 的应用库名是**产品库 `aicore`**，演练更不能落到那里。
    两组变量的分工写在 `tests/conftest.py` 的那一节里（含两次实测现场）。
    """
    drill = _drill_url()
    if drill is not None:
        return drill

    settings = get_settings()
    return URL.create(
        drivername="mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        query={"charset": "utf8mb4"},
    )


def reject_unflagged_downgrade() -> None:
    """降级守卫：`alembic downgrade` 默认被拒，演练需 `-x allow_downgrade=1`。

    抛 `util.CommandError` 而不是 `RuntimeError`：CLI 会把它渲染成一行
    `FAILED: <原因>` 并以非 0 退出（`alembic.config.CommandLine.run_cmd` 的既有分支），
    而不是甩一段与使用者无关的栈。程序化调用方则照常收到异常。
    """
    if _command_name() != "downgrade":
        return
    if x_arguments().get(X_ALLOW_DOWNGRADE) == "1":
        return
    raise util.CommandError(
        "downgrade 默认被拒绝：spec §2.3 / er.md §5.6 要求演进走 "
        "expand-migrate-contract（双写→回灌→切读→收缩），禁止破坏性 DDL 直上生产。"
        "演练确需降级时显式加 -x allow_downgrade=1"
    )


def _command_name() -> str | None:
    """CLI 子命令名（`upgrade` / `downgrade` / `revision` …），取不到就是 `None`。

    **为什么不能直接比字符串**（首版就是这么写错的，实测证据在 Task 3.5 报告里）：
    `config.cmd_opts.cmd` 不是命令名，而是 argparse 存进去的
    **`(函数, 位置参数名, 关键字参数名)` 三元组**（`alembic/config.py` 的
    `subparser.set_defaults(cmd=(fn, positional, kwarg))`）。
    首版拿它跟 `"downgrade"` 比，恒不相等 → 守卫静默失效 → 用例里那次
    `alembic downgrade base` 真的去连了库（1045），而不是被拦下。
    程序化调用（`alembic.command.downgrade(cfg, ...)`）不带 `cmd_opts`，
    此处返回 `None`，守卫不生效——该空洞写在模块 docstring 里。
    """
    cmd = getattr(config.cmd_opts, "cmd", None)
    if isinstance(cmd, tuple) and cmd:
        return getattr(cmd[0], "__name__", None)
    return None


def strip_redundant_drop_index(
    migration_context: object, revision: object, directives: list[object]
) -> None:
    """生成期后处理：删掉"反正要删的表"自己的 `drop_index`（MySQL 上跑不通）。

    autogenerate 渲染出的 `downgrade()` 是"先 `drop_index`、再 `drop_table`"。
    在 MySQL 上这**跑不动**（实测 1553，原始报错见 Task 3.5 报告）：

        DROP INDEX idx_review ON vision_marker
        -> (1553, "Cannot drop index 'idx_review': needed in a foreign key constraint")

    `vision_marker.idx_review` 正是外键 `fk_vision_marker_review` 的支撑索引：
    MySQL 不允许在约束还在时删掉它背后的索引。而 `DROP TABLE` 会把表上的索引与
    外键一并带走，所以这些 `drop_index` 既多余又有害。

    **为什么在 env.py 里做、而不是手改迁移文件**：工单禁止"手改生成的 `op.*`"；
    这里是 Alembic 官方的**生成期扩展点**（`process_revision_directives`），
    重跑 `revision --autogenerate` 结果完全一致、可复现，生成物仍是机器产物。
    只动 `downgrade_ops` —— 演进路径（`upgrade()`）一个字节都不碰。
    只删"表也在同一批 drop 里"的索引：单独删索引的迁移（表还在）照旧保留。

    **`drop_index` 藏在 `ModifyTableOps` 里**（实测把结构打印出来才看见，见报告）：

        container=DowngradeOps ops=list len=12
          op=ModifyTableOps table=vision_marker    <- 里面才是 DropIndexOp
          op=DropTableOp   table=vision_marker
          op=ModifyTableOps table=review_verdict
          op=DropTableOp   table=review_verdict
          ...

    首版只扫了顶层 list，`isinstance(op, DropIndexOp)` 恒为假、过滤**静默失效**
    （生成物里 10 个 `drop_index` 一个没少）——故这里必须往下钻一层。
    """
    del migration_context, revision  # 扩展点签名要求，本处理不需要它们
    for script in directives:
        container = getattr(script, "downgrade_ops", None)
        operations = getattr(container, "ops", None)
        if not isinstance(operations, list):
            continue
        dropped_tables = {
            op.table_name for op in operations if isinstance(op, alembic_ops.DropTableOp)
        }
        kept: list[object] = []
        for operation in operations:
            if isinstance(operation, alembic_ops.ModifyTableOps):
                inner = [
                    child
                    for child in operation.ops
                    if not (
                        isinstance(child, alembic_ops.DropIndexOp)
                        and operation.table_name in dropped_tables
                    )
                ]
                if not inner:
                    continue  # 整组都被删掉：连空容器一起去掉
                operation.ops = inner
            kept.append(operation)
        container.ops = kept


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """autogenerate 的对象过滤器：**分片表两个方向都不进迁移**。

    三张分片表在模型里是逻辑名（`ai_task`），在库里是带月份的物理名
    （`ai_task_202607`），两边名字永远不会相等，故必须按**逻辑名**统一判：

    - `reflected=False`（模型侧对象）：`ai_task` 在 `SHARDED_TABLES` 里 → 排除，
      否则基线会多出 3 张永远不该由迁移负责的表；
    - `reflected=True`（库侧对象）：`ai_task_202607` 归一成 `ai_task` 后同样排除，
      否则 autogenerate 会生成 `op.drop_table('ai_task_202607')` —— 既破坏性，
      又让"重复 autogenerate 产生空迁移"这条口径永不成立。
    """
    if type_ != "table" or name is None:
        return True
    return normalize_table_name(name) not in SHARDED_TABLES


def create_shard_tables_for(connection: Connection, month: str) -> None:
    """迁移钩子：把 `month` 的三张分片物理表建出来。

    **委托 `sharding.ensure_month_tables`**（Task 3.3），MUST NOT 在本文件另写一份
    建表逻辑：分片物理表的结构、建表顺序、外键约束名的月份后缀，全部由那一个实现
    现算；两份实现漂移的表现是"迁移建的表与运行期建的表不是同一个结构"。

    它是**可调用入口**（不是只能通过 Alembic 触发）：运维脚本/部署钩子可以
    `create_shard_tables_for(conn, "202607")` 直接用；CLI 侧由 `-x shard_month=`
    在 `upgrade` 之后自动调用，使"`alembic upgrade head` 之后当月表也就绪"。
    """
    ensure_month_tables(connection, month)


def _announce(url: URL) -> None:
    """打印目标库（**口令遮蔽**）与运行模式，让 CLI 输出自带"打到哪个库"的证据。"""
    track = "演练库(DSH_IT_MYSQL_*)" if _drill_url() is not None else "应用配置(AICORE_MYSQL_*)"
    print(f"[alembic] 目标库 = {url.render_as_string(hide_password=True)} | 配置来源 = {track}")


def run_migrations_offline() -> None:
    """离线模式：只渲染 SQL 到 stdout，不连数据库（故不建分片表）。"""
    reject_unflagged_downgrade()
    url = database_url()
    _announce(url)
    context.configure(
        url=url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 类型变更也要被 autogenerate 发现（工单硬要求）。
        compare_type=True,
        # 服务端默认值同样要比：DDL 的 DEFAULT 与模型侧 `server_default` 不一致时，
        # 若不开这一项，autogenerate 会**安静地放过**那处漂移。
        compare_server_default=True,
        include_object=include_object,
        process_revision_directives=strip_redundant_drop_index,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移，随后按 `-x shard_month=` 建当月分片物理表。"""
    reject_unflagged_downgrade()
    url = database_url()
    _announce(url)
    # NullPool：迁移是一次性、串行的运维动作，池化只会把连接留到进程结束。
    connectable = create_engine(url, poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                include_object=include_object,
                process_revision_directives=strip_redundant_drop_index,
            )
            with context.begin_transaction():
                context.run_migrations()
            month = x_arguments().get(X_SHARD_MONTH)
            if month:
                create_shard_tables_for(connection, month)
                connection.commit()
                print(f"[alembic] 分片物理表已就绪（委托 ensure_month_tables）：{month}")
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
