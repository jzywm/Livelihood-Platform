"""Alembic 迁移的结构与落地口径（Task 3.5）。

## 这份用例守什么

三条幂等口径（工单原文），每条都有**正面证据**，不是"跑过就算"：

1. **重复 autogenerate 产生空迁移**——库与模型真正对齐时，第二次生成只有 `pass`。
   这条最值钱：它同时验了 Task 3.2 的 `server_default`、索引名、`with_variant` 类型
   （`int unsigned` / `datetime(3)`）是否与库一致；写入模型与库不一致时，
   autogenerate 每次都想改。
2. **空命名空间可重放**——先清空再 `upgrade head`，成功后**再跑一次是 no-op**。
3. **与 DDL 直建结果一致**——`alembic upgrade head` 建出的结构 与 `scripts/apply_ddl.py`
   建出的结构，用 **Task 3.6 的 `from_information_schema` + `diff`** 比对，差异为 0。
   MUST NOT 自己再写一套读 `information_schema` 的代码（本文件只调 Task 3.6 的实现）。

## 演练命名空间：**不是真·空库，是空命名空间**（如实登记）

`aicore_dev` 只有 `aicore` 与 `aicore_test` 的 ALL、**没有建库权限**（`SHOW GRANTS`
实测：`GRANT USAGE ON *.*` + 两个库的 ALL，故 `CREATE DATABASE` 必然 1044），
所以"新建空库 → `upgrade head`"这条路径**无法在本机验证**。等价做法是：
在 `aicore_test` 里把 6 张非分片表 + `alembic_version` 清掉，造出一个**空命名空间**，
跑完再把演练库**恢复进入时的形态**（进门前就有的表用权威 DDL 路径重建）。
本用例 MUST NOT `DROP DATABASE`、MUST NOT 碰 `aicore` 库里的任何东西。

并发注意（已知约束，不假装解决）：命名空间是 `aicore_test` 里的**共享表名**，
两个进程同时跑本文件的集成用例会互删表；演练月份按进程号取，避免与
`test_apply_ddl_mysql.py` 的分片表撞车。

## 破坏性 DDL 的判定为什么按"函数"分区

工单同时要求"基线里 MUST NOT 出现 `op.drop_table`"与"`downgrade()` MUST 只做基线撤销
（`drop_table` 本迁移创建的表）"。逐字扫全文会让两条自相矛盾，故按 AST 分区：

- `upgrade()` 里 MUST NOT 出现任何 `drop_*`（演进路径不许破坏性 DDL，spec §2.3）；
- `downgrade()` 必须**存在**（正向要求：只断言"不含 drop_table"的话，缺函数也能过），
  且它 drop 的表**恰好等于** `upgrade()` 建的表（撤得干净、且只撤自己建的）。
"""

from __future__ import annotations

import ast
import configparser
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL, Connection, Engine

from aicore.repository.schema import SERVICE_ROOT, diff, from_information_schema
from aicore.repository.sharding import FIXED_TABLES, SHARDED_TABLE_ORDER, SHARDED_TABLES

#: 迁移目录与配置文件（路径只有这两处定义，其余用例都从这里取）。
MIGRATION_DIR: Final[Path] = SERVICE_ROOT / "deploy" / "sql" / "migration"
VERSIONS_DIR: Final[Path] = MIGRATION_DIR / "versions"
ENV_PY: Final[Path] = MIGRATION_DIR / "env.py"
README: Final[Path] = MIGRATION_DIR / "README"
ALEMBIC_INI: Final[Path] = SERVICE_ROOT / "alembic.ini"

#: 基线迁移**逐字**必须建出的 6 张非分片表（工单要求逐字列出，不靠"看起来像"）。
EXPECTED_BASELINE_TABLES: Final[tuple[str, ...]] = (
    "vision_review",
    "vision_marker",
    "review_verdict",
    "kitchen_anomaly",
    "risk_predict_result",
    "vision_qa_log",
)

#: 本用例的演练库（MUST 是 `aicore_test`；产品库 `aicore` 全程不碰）。
DRILL_DATABASE: Final[str] = "aicore_test"

#: 分片演练月：**年份与 `test_apply_ddl_mysql.py` 的 2099 错开**，避免两个文件
#: 在同一进程里共用同一个月份、互相把对方的分片表删掉；月份按进程号取（1~12）。
DRILL_MONTH: Final[str] = f"2098{os.getpid() % 12 + 1:02d}"

#: 降级守卫用例的目标库名：**故意用不存在的库**，这样即使守卫失效，
#: 最坏结果也只是"连不上库"而不是"把产品库的表删了"。
GUARD_PROBE_DATABASE: Final[str] = "aicore_t35_guard_probe"

#: 删表顺序：先删引用方（子表）再删被引用方，否则 MySQL 3730 拒绝。
#: 与 `test_apply_ddl_mysql.py` 的清理注释同源（那里是实测踩出来的）。
DROP_ORDER: Final[tuple[str, ...]] = (
    "vision_marker",
    "review_verdict",
    "kitchen_anomaly",
    "vision_review",
    "risk_predict_result",
    "vision_qa_log",
)


# ---------------------------------------------------------------------------
# 不连数据库的用例（默认跑）
# ---------------------------------------------------------------------------


def test_alembic_ini_points_to_migration_dir() -> None:
    """`script_location` / `version_locations` 必须指向 `deploy/sql/migration`。"""
    raw = configparser.RawConfigParser()
    raw.read(ALEMBIC_INI, encoding="utf-8")
    section = raw["alembic"]
    script_location = section["script_location"]
    version_locations = section["version_locations"]
    assert "deploy/sql/migration" in script_location, script_location
    assert script_location.replace("\\", "/").endswith("deploy/sql/migration"), script_location
    assert "deploy/sql/migration/versions" in version_locations.replace("\\", "/"), (
        version_locations
    )


def test_alembic_ini_has_no_credentials() -> None:
    """`alembic.ini` 会入库，故 MUST NOT 有口令（URL 留空、由 env.py 从环境变量组装）。

    口令用**环境里的真实值**反查，而不是写死字面量：写字面量本身就是"把凭据放进仓库"。
    """
    text = ALEMBIC_INI.read_text(encoding="utf-8")
    raw = configparser.RawConfigParser()
    raw.read(ALEMBIC_INI, encoding="utf-8")
    assert raw["alembic"]["sqlalchemy.url"].strip() == "", "sqlalchemy.url 必须留空"
    assert "mysql+pymysql" not in text, "alembic.ini 里 MUST NOT 出现连接串"
    secret = os.environ.get("DSH_IT_MYSQL_PASSWORD") or os.environ.get("AICORE_MYSQL_PASSWORD")
    if secret:
        assert secret not in text, "alembic.ini 里出现了真实口令"


def test_alembic_ini_is_ascii_only() -> None:
    """`alembic.ini` 必须**纯 ASCII**：Alembic 用它读不出 UTF-8 中文。

    实测（原始报错留在 Task 3.5 报告里）：alembic 1.20 走
    `alembic/util/compat.py: file_config.read(path, encoding="locale")`，
    本机 locale 是 cp936/GBK，于是带中文的 UTF-8 配置文件在 `configparser` 阶段就
    `UnicodeDecodeError`，**任何 alembic 命令都跑不起来**——`PYTHONUTF8=1` 也救不了，
    因为 `"locale"` 明确要的是 locale 编码。故这里把"纯 ASCII"钉成不变量：
    中文说明放在 `deploy/sql/migration/README` 与 `env.py`（它们由 Python/Mako 读，UTF-8）。
    """
    data = ALEMBIC_INI.read_bytes()
    bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    assert not bad, f"alembic.ini 含非 ASCII 字节（Alembic 会用 locale 编码读它）：{bad[:5]}"
    assert not data.startswith(b"\xef\xbb\xbf"), "alembic.ini MUST NOT 带 BOM"


def test_versions_dir_has_exactly_one_baseline_revision() -> None:
    """`versions/` 下**恰好 1 条**迁移，且它是根版本（`down_revision is None`）。"""
    files = sorted(VERSIONS_DIR.glob("*.py"))
    assert len(files) == 1, f"versions/ 下应恰好 1 条基线迁移，实际 {[f.name for f in files]}"
    baseline = files[0]
    assert "baseline" in baseline.name, baseline.name
    tree = ast.parse(baseline.read_text(encoding="utf-8"))
    revision = _module_constant(tree, "revision")
    down_revision = _module_constant(tree, "down_revision")
    assert isinstance(revision, str) and revision, f"revision 必须是非空字符串：{revision!r}"
    assert down_revision is None, f"基线必须是根版本（down_revision 为 None）：{down_revision!r}"


def test_env_py_takes_target_metadata_from_base() -> None:
    """`env.py` 的 `target_metadata` 取自 `repository.models.Base`，并开了类型比对。"""
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    metadata_assign = _module_assign(tree, "target_metadata")
    assert isinstance(metadata_assign, ast.Attribute), "target_metadata 应直接取某个属性"
    assert metadata_assign.attr == "metadata", metadata_assign.attr
    assert isinstance(metadata_assign.value, ast.Name), "target_metadata 的宿主应是 Base"
    assert metadata_assign.value.id == "Base", metadata_assign.value.id
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "aicore.repository.models"
        for alias in node.names
    }
    assert "Base" in imported, f"env.py 应从 aicore.repository.models 导入 Base，实际 {imported}"

    compare_type_values = [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "configure"
        for keyword in node.keywords
        if keyword.arg == "compare_type"
        and isinstance(keyword.value, ast.Constant)
    ]
    assert compare_type_values, "env.py 的 context.configure 应显式传 compare_type"
    assert all(value is True for value in compare_type_values), compare_type_values


def test_env_py_excludes_shard_tables_and_exposes_shard_hook() -> None:
    """分片表两个方向都被 `include_object` 排除；`create_shard_tables_for` 委托 Task 3.3。

    断言用 AST 而不是子串：子串能靠注释骗过（"我们不建分片表"这句注释就能让弱断言变绿）。
    """
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    include_object = _function(tree, "include_object")
    referenced = {
        node.id for node in ast.walk(include_object) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(include_object) if isinstance(node, ast.Attribute)
    }
    assert "normalize_table_name" in referenced, "排除判据应走 Task 3.6 的逻辑名归一"
    assert "SHARDED_TABLES" in referenced, "排除判据应基于 sharding.SHARDED_TABLES"

    hook = _function(tree, "create_shard_tables_for")
    delegated = {
        node.func.attr
        for node in ast.walk(hook)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(hook)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "ensure_month_tables" in delegated, (
        "迁移钩子 MUST 委托 sharding.ensure_month_tables（唯一实现处），"
        f"实际调用 {sorted(delegated)}"
    )


def test_baseline_upgrade_is_non_destructive() -> None:
    """`upgrade()` 里 MUST NOT 有 `drop_table` / `drop_column`（spec §2.3）。"""
    upgrade = _baseline_function("upgrade")
    calls = _op_attributes(upgrade)
    destructive = sorted(name for name in calls if name.startswith("drop"))
    assert not destructive, f"基线 upgrade() 里出现了破坏性操作：{destructive}"


def test_baseline_downgrade_exists_and_reverts_only_itself() -> None:
    """`downgrade()` 必须**存在**，且它 drop 的表恰好等于 `upgrade()` 建的表。

    "含 `def downgrade`"是**正向**要求：只断言"不含 drop_table"的话，
    一个没有 `downgrade()`（或它是空函数）的迁移也能过。
    """
    upgrade = _baseline_function("upgrade")
    downgrade = _baseline_function("downgrade")
    created = _op_string_arguments(upgrade, "create_table")
    assert created == set(EXPECTED_BASELINE_TABLES), f"upgrade() 建表集合异常：{sorted(created)}"
    dropped = _op_string_arguments(downgrade, "drop_table")
    assert dropped == created, (
        f"downgrade() 只应撤销本迁移建的表：建 {sorted(created)}，撤 {sorted(dropped)}"
    )
    # 整个文件里 MUST NOT 有 drop_column：基线没有列级撤销这回事。
    whole_file = _op_attributes(_baseline_tree())
    assert "drop_column" not in whole_file, "基线迁移里 MUST NOT 出现 op.drop_column"


def test_baseline_creates_exactly_the_six_fixed_tables() -> None:
    """基线只含 6 张非分片表，且**不含**分片表（逐字比对 + 与 sharding 清单交叉验证）。"""
    created = _op_string_arguments(_baseline_function("upgrade"), "create_table")
    assert created == set(EXPECTED_BASELINE_TABLES), f"实际 {sorted(created)}"
    assert created == set(FIXED_TABLES), (
        f"基线表集合应与 sharding.FIXED_TABLES 一致：基线 {sorted(created)}，"
        f"清单 {sorted(FIXED_TABLES)}"
    )
    assert not created & set(SHARDED_TABLES), f"基线里 MUST NOT 有分片表：{sorted(created)}"
    assert all("_2" not in name for name in created), "基线里 MUST NOT 出现带月份的物理表名"


def test_migration_readme_documents_shard_and_new_migration() -> None:
    """README 必须讲清"分片表由运行时创建"与"新增迁移的正确姿势"。

    **这是弱断言**（子串匹配），只能证明"话写了"，证明不了"话对"；
    真正的强制在 `test_env_py_excludes_shard_tables_and_exposes_shard_hook` 与集成用例里。
    """
    assert README.is_file(), f"缺少 {README}"
    text = README.read_text(encoding="utf-8")
    assert "分片表由运行时创建" in text
    assert "新增迁移的正确姿势" in text
    assert "ensure_month_tables" in text, "README 应点明分片物理表由谁建"


def test_env_py_readme_and_mako_exist() -> None:
    """交付清单齐不齐：env.py / script.py.mako / README / versions 全在。"""
    for path in (ENV_PY, MIGRATION_DIR / "script.py.mako", README, VERSIONS_DIR):
        assert path.exists(), f"缺少交付物 {path}"


def test_downgrade_is_refused_without_explicit_flag() -> None:
    """`alembic downgrade` 默认被拒（生产禁用破坏性 DDL），且**不连库**。

    用不存在的库名 + 去掉演练凭据，使这条用例：① 不需要 MySQL；② 即使守卫失效，
    最坏结果也只是连不上库。断言点在"守卫先于连接"——若它先去连库，
    报的会是 1049/1045 而不是这条拒绝原因。
    """
    env = dict(os.environ)
    env.pop("DSH_IT_MYSQL_PASSWORD", None)
    env["AICORE_MYSQL_DATABASE"] = GUARD_PROBE_DATABASE
    result = _run_alembic("downgrade", "base", env=env)
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0, f"downgrade 应被拒绝，实际退出码 0：\n{output}"
    assert "downgrade 默认被拒绝" in output, f"拒绝原因应可读，实际：\n{output}"
    assert "allow_downgrade" in output, f"拒绝时应指出放行开关，实际：\n{output}"


# ---------------------------------------------------------------------------
# 连数据库的用例（-m integration）
# ---------------------------------------------------------------------------


@pytest.fixture
def probe_tmp() -> Iterator[Path]:
    """本用例的临时目录。

    **偏离工单（如实登记）**：工单要求用 pytest 的 `tmp_path`，本机两种做法都用不了：

    1. `tmp_path` 建在 `tempfile.gettempdir()`（`C:\\Users\\<用户>\\AppData\\Local\\Temp\\
       dsh-*`），那在工作区之外，**文件写入被沙箱拒绝**，夹具在 setup 阶段就抛
       `PermissionError: [WinError 5] ...\\pytest-of-<用户>`；
    2. 退一步改用 `tempfile.mkdtemp(dir=<工作区内>)` 也不行：`mkdtemp` 建的目录带
       0700 ACL，随后往里写文件同样 `WinError 5`（实测矩阵见 Task 3.5 报告）。

    故这里用 `Path.mkdir()` 自建临时目录（实测可写），性质与 `tmp_path` 相同：
    **进程唯一、随用例销毁、MUST NOT 落在 `versions/`**。名字带 `.` 前缀且带 uuid，
    即使用例被强杀、`finally` 没跑到，也一眼看出是临时产物。
    """
    path = SERVICE_ROOT / f".aicore-migration-probe-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.mark.integration
def test_upgrade_on_empty_namespace_then_second_upgrade_is_noop() -> None:
    """口径 2：空命名空间 `upgrade head` 成功；**再跑一次是 no-op**。

    no-op 的证据是 `diff(前后两次的结构快照) == []`，而不是"退出码 0"——
    退出码 0 对"什么都没干"和"重建了一遍"是一样的。
    """
    engine = _drill_engine()
    _empty_namespace(engine)
    first = _run_alembic("upgrade", "head")
    assert first.returncode == 0, _failure("首次 upgrade head 失败", first)
    assert "Running upgrade" in first.stderr, f"首次升级应真的执行了：\n{first.stderr}"

    names = set(inspect(engine).get_table_names())
    missing = sorted(set(EXPECTED_BASELINE_TABLES) - names)
    assert not missing, f"upgrade head 之后仍缺表：{missing}（实际 {sorted(names)}）"
    # 快照用**新连接**取：DDL 由子进程执行，复用旧连接可能读到旧快照（REPEATABLE READ）。
    with engine.connect() as conn:
        before = _snapshot(conn)

    second = _run_alembic("upgrade", "head")
    assert second.returncode == 0, _failure("二次 upgrade head 失败", second)
    assert "Running upgrade" not in second.stderr, (
        f"二次 upgrade head 应当是 no-op（不应再执行任何版本）：\n{second.stderr}"
    )
    with engine.connect() as conn:
        after = _snapshot(conn)

    assert len(before) == len(EXPECTED_BASELINE_TABLES), f"快照应含 6 张表：{sorted(before)}"
    assert diff(before, after) == [], f"二次 upgrade 改变了结构：{diff(before, after)}"
    engine.dispose()


@pytest.mark.integration
def test_alembic_result_matches_apply_ddl_result() -> None:
    """口径 3：`alembic upgrade head` 与 `apply_ddl.py` 建出的结构**差异为 0**。

    两条路径必须各自从**空命名空间**开始，否则 `CREATE TABLE IF NOT EXISTS` 会让
    第二条路径变成 no-op —— 那样比对的是"同一批表"，差异恒为 0，验了个寂寞。
    故顺序是：清空 → alembic 建 → 取快照 → 清空 → DDL 建 → 取快照 → 比对。
    """
    engine = _drill_engine()
    _empty_namespace(engine)
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, _failure("alembic upgrade head 失败", result)
    with engine.connect() as conn:
        from_alembic = _snapshot(conn)

    _empty_namespace(engine)
    ddl = _run_apply_ddl()
    assert ddl.returncode == 0, _failure("apply_ddl.py 失败", ddl)
    with engine.connect() as conn:
        from_ddl = _snapshot(conn)

    assert len(from_alembic) == len(EXPECTED_BASELINE_TABLES), (
        f"alembic 侧应恰好 6 张表：{sorted(from_alembic)}"
    )
    assert len(from_ddl) == len(EXPECTED_BASELINE_TABLES), (
        f"DDL 侧应恰好 6 张表：{sorted(from_ddl)}"
    )
    assert diff(from_alembic, from_ddl) == [], (
        "两条落地路径的结构 MUST 一致（用 Task 3.6 的 from_information_schema + diff 比对）：\n"
        + "\n".join(diff(from_alembic, from_ddl))
    )
    engine.dispose()


@pytest.mark.integration
def test_autogenerate_converges_on_upgraded_db(probe_tmp: Path) -> None:
    """口径 1：在已 upgrade 的库上再 autogenerate，生成的升级脚本**没有 `op.` 调用**。

    迁移目录**整份复制到临时目录**再生成：临时产物 MUST NOT 留在 `versions/`
    （交付时那里恰好 1 条基线迁移）。
    """
    from alembic import command
    from alembic.config import Config

    engine = _drill_engine()
    _empty_namespace(engine)
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, _failure("alembic upgrade head 失败", result)

    copied = probe_tmp / "migration"
    _copytree(MIGRATION_DIR, copied)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(copied))
    config.set_main_option("version_locations", str(copied / "versions"))
    command.revision(config, message="probe", autogenerate=True)

    generated = sorted((copied / "versions").glob("*_probe.py"))
    assert len(generated) == 1, f"探针迁移应恰好生成 1 个：{generated}"
    probe_tree = ast.parse(generated[0].read_text(encoding="utf-8"))
    probe_upgrade = _function(probe_tree, "upgrade")
    calls = _op_attributes(probe_upgrade)
    assert not calls, (
        "库与模型已经一致，探针迁移里 MUST NOT 有任何 op.* 调用，实际："
        f"{sorted(set(calls))}\n生成物：{generated[0]}"
    )
    # 真实交付目录不受影响：仍然恰好 1 条基线迁移。
    assert len(sorted(VERSIONS_DIR.glob("*.py"))) == 1, "临时产物泄漏进了 versions/"
    engine.dispose()


@pytest.mark.integration
def test_shard_month_hook_creates_physical_tables() -> None:
    """迁移钩子：`-x shard_month=YYYYMM` 让 `upgrade head` 之后当月分片表也就绪。

    分片表**不在迁移里**（物理名依赖月份），但"升级完当月表就该在"这个能力由
    `env.py` 的 `create_shard_tables_for` 承接，本用例从 CLI 侧正面钉住它。
    """
    engine = _drill_engine()
    _empty_namespace(engine)
    result = _run_alembic("-x", f"shard_month={DRILL_MONTH}", "upgrade", "head")
    assert result.returncode == 0, _failure("带 -x shard_month 的 upgrade head 失败", result)
    assert DRILL_MONTH in result.stdout, f"钩子应回显已建分片表的月份：\n{result.stdout}"

    names = set(inspect(engine).get_table_names())
    expected = {f"{logical}_{DRILL_MONTH}" for logical in SHARDED_TABLE_ORDER}
    missing = sorted(expected - names)
    assert not missing, f"迁移钩子没把当月分片表建齐：缺 {missing}（实际 {sorted(names)}）"
    # 6 张非分片表同时也在（升级与钩子是同一次运行里的两步）。
    assert not set(EXPECTED_BASELINE_TABLES) - names
    _drop_shard_tables(engine, DRILL_MONTH)
    engine.dispose()


@pytest.mark.integration
def test_downgrade_with_flag_reverts_baseline() -> None:
    """显式 `-x allow_downgrade=1` 时降级可用，且 `downgrade base` 撤掉 6 张表。

    这条证明基线迁移的 `downgrade()` 是**真能跑**的（不是只存在一个函数体）：
    演练库上的降级路径因此不是"纸面能力"。生产仍被默认守卫拦住。

    收尾再 `upgrade head` 一次：把演练库留在**稳态**（6 张表在、版本指向 head），
    而不是"跑完就没表了"——下一个用例/下一个人接手时不该先猜这里为什么是空的。
    """
    engine = _drill_engine()
    _empty_namespace(engine)
    upgraded = _run_alembic("upgrade", "head")
    assert upgraded.returncode == 0, _failure("upgrade head 失败", upgraded)
    result = _run_alembic("-x", "allow_downgrade=1", "downgrade", "base")
    assert result.returncode == 0, _failure("带放行开关的 downgrade base 失败", result)
    names = set(inspect(engine).get_table_names())
    leftover = sorted(set(EXPECTED_BASELINE_TABLES) & names)
    assert not leftover, f"downgrade base 之后仍有残留表：{leftover}"
    back = _run_alembic("upgrade", "head")
    assert back.returncode == 0, _failure("降级后重新 upgrade head 失败", back)
    assert not set(EXPECTED_BASELINE_TABLES) - set(inspect(engine).get_table_names())
    engine.dispose()


# ---------------------------------------------------------------------------
# 连库工具的公共部分
# ---------------------------------------------------------------------------


def _drill_engine() -> Engine:
    """连**演练库**的引擎；连不上显式 `pytest.skip` 并说明缺什么。

    只认 `DSH_IT_MYSQL_*`（演练库专用前缀，理由写在 `tests/conftest.py`）。
    目标库 MUST 是 `aicore_test`：**不是就红**，绝不把演练打到产品库上。
    """
    password = os.environ.get("DSH_IT_MYSQL_PASSWORD")
    if not password:
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "集成用例需要真实演练库凭据；凭据 MUST NOT 硬编码进仓库"
        )
    database = os.environ.get("DSH_IT_MYSQL_DATABASE", DRILL_DATABASE)
    if database != DRILL_DATABASE:
        pytest.fail(
            f"演练库 MUST 是 {DRILL_DATABASE}，实际 DSH_IT_MYSQL_DATABASE={database}："
            f"本文件的清理会 DROP 表，打错库的代价不可逆"
        )
    url = URL.create(
        drivername="mysql+pymysql",
        username=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        password=password,
        host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
        database=database,
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:
        engine.dispose()
        pytest.skip(
            f"需要真实 MySQL（{database}@127.0.0.1:3306）才能验证迁移落地："
            f"{type(exc).__name__}: {exc}"
        )
    return engine


def _drill_env() -> dict[str, str]:
    """子进程环境：继承当前环境，并强制子进程以 UTF-8 写输出（本用例按 UTF-8 解码）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_alembic(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """跑一次 alembic CLI（**运维真正会敲的那条命令**：参数解析、退出码、输出全覆盖）。"""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(SERVICE_ROOT),
        check=False,
        env=_drill_env() if env is None else env,
    )


def _run_apply_ddl() -> subprocess.CompletedProcess[str]:
    """跑一次 `scripts/apply_ddl.py`（Task 3.1 的权威落地路径）。"""
    return subprocess.run(
        [
            sys.executable,
            str(SERVICE_ROOT / "scripts" / "apply_ddl.py"),
            "--database",
            DRILL_DATABASE,
            "--month",
            DRILL_MONTH,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(SERVICE_ROOT),
        check=False,
        env=_drill_env(),
    )


def _empty_namespace(engine: Engine) -> None:
    """清空**演练命名空间**：6 张非分片表 + `alembic_version`，并当场断言真的空了。

    - 只 DROP 这 7 个名字，MUST NOT `DROP DATABASE`、MUST NOT 动
      `ai_task_YYYYMM` 这类分片表（它们属于别的用例的演练月份）；
    - 清完立刻用 `inspect()` 复验：不清不楚的"空"会让"空命名空间可重放"这条口径
      变成一句无法证伪的话。
    """
    with engine.begin() as conn:
        for name in DROP_ORDER:
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS `{name}`")
        conn.exec_driver_sql("DROP TABLE IF EXISTS `alembic_version`")
    leftovers = sorted((set(EXPECTED_BASELINE_TABLES) | {"alembic_version"})
                       & set(inspect(engine).get_table_names()))
    assert not leftovers, f"演练命名空间没清干净，残留：{leftovers}"


def _snapshot(conn: Connection) -> dict[str, object]:
    """取 6 张非分片表的结构快照（**复用 Task 3.6 的读取器**，不另写 information_schema）。"""
    everything = from_information_schema(conn, DRILL_DATABASE)
    return {name: spec for name, spec in everything.items() if name in FIXED_TABLES}


def _drop_shard_tables(engine: Engine, month: str) -> None:
    """只删本用例按月份建出来的分片物理表，**按建表顺序的逆序**。

    必须逆序：`ocr_correction_YYYYMM` 有指向同月 `ocr_result_YYYYMM` 的物理外键，
    先删 `ocr_result` 会被 MySQL 3730 拒绝（Task 3.1 已实测过同一件事）。
    顺序取自 `sharding.SHARDED_TABLE_ORDER`，MUST NOT 在这里再排一次序。
    """
    with engine.begin() as conn:
        for logical in reversed(SHARDED_TABLE_ORDER):
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS `{logical}_{month}`")


def _failure(title: str, result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"{title}（退出码 {result.returncode}）\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def _copytree(src: Path, dest: Path) -> None:
    """复制迁移目录（跳过 `__pycache__`：编译缓存不是迁移脚本）。"""
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))


# ---------------------------------------------------------------------------
# AST 工具
# ---------------------------------------------------------------------------


def _baseline_tree() -> ast.Module:
    files = sorted(VERSIONS_DIR.glob("*.py"))
    assert len(files) == 1, f"versions/ 下应恰好 1 条基线迁移，实际 {[f.name for f in files]}"
    return ast.parse(files[0].read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"没找到函数 {name}()：正向要求（缺函数 MUST 失败）")


def _baseline_function(name: str) -> ast.FunctionDef:
    return _function(_baseline_tree(), name)


def _module_constant(tree: ast.Module, name: str) -> object:
    return _literal(_module_assign(tree, name))


def _module_assign(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            assert node.value is not None, f"{name} 应带赋值"
            return node.value
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
    raise AssertionError(f"没找到模块级变量 {name}")


def _literal(node: ast.expr) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_literal(element) for element in node.elts]
    return None


def _op_attributes(node: ast.AST) -> list[str]:
    """收集子树里全部 `op.<name>(...)` 调用的 `<name>`。"""
    return [
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "op"
    ]


def _op_string_arguments(node: ast.AST, op_name: str) -> set[str]:
    """收集 `op.<op_name>('表名', ...)` 的第一个字符串字面量参数。"""
    names: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == op_name
            and child.args
            and isinstance(child.args[0], ast.Constant)
            and isinstance(child.args[0].value, str)
        ):
            names.add(child.args[0].value)
    return names
