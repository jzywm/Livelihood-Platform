"""三方向阴性用例：单边改「DDL / `er.md` / 模型」中的任一侧，一致性检查 MUST 变红。

## 为什么必须有这个文件（spec §5.9 第 2 条）

spec §5.9 的验收证据第 2 条是「三源交叉比对：正常态通过；**单边改任一侧 → 失败**
（三个方向各验一次）」。只证明"正常态是绿的"远远不够：一个**永远返回空差异**的检查器
也能让正常态全绿，而它拦不住任何漂移。故本文件为每一侧各造一次真实的单边改动，
并要求差异清单点名到"哪张表、哪个字段"。

## MUST NOT 改仓库里的真实源文件

三个方向一律**在内存里改文本或临时 `MetaData`**：

 ① 改 DDL：读 `.sql` 文本 -> 改某列类型 -> `schema.parse_ddl`；
 ② 改 `er.md`：读文本 -> 把某列的「空」由 `NO` 改成 `YES` -> `schema.parse_er_md`；
 ③ 改模型：`Base.metadata` 深拷贝进临时 `MetaData` -> 改某列 `nullable` -> `from_metadata`。

"改真实文件再还原"是危险做法（用例中途失败会留下脏文件、并发跑测试还会互扰），
本文件 MUST NOT 采用。

## 每个方向都配三件套（防"看着严、其实是空的"）

- **正常态对照**：未改动的版本 `diff == []`（证明上面的红是改动引起的，不是本来就红）；
- **非空下限**：三源各自解析出的表数 == 9（防解析塌了导致"两边都空、彼此一致"）；
- **命中面收窄**：差异清单**恰好 1 条**且点名表 + 字段（防"报了一堆别的差异"冒充命中）。

## 还验 `scripts/compare_schema.py` 的退出码

它是 CI 门禁（spec §5.6「任一条边不一致即失败」），判据就是**退出码**：
正常态 `0`；`--with-mysql` 缺口令 `2`；`--with-mysql` 连不上 `2`
（**MUST NOT 静默降级成"两源通过"**——静默降级会让人以为真库也验过了）。

## 与 `test_schema.py` 的分工

`test_schema.py` 覆盖的是共享层自身的函数行为（归一化 / 表格解析 / `diff` 的六类差异）。
本文件覆盖的是**端到端的三源一致性检查**：改动 -> 解析 -> 比对 -> 是否报警，
以及 CLI 门禁的退出码。两者不重复。
"""

from __future__ import annotations

import importlib.util
import os
import re
from types import ModuleType
from typing import TYPE_CHECKING

from sqlalchemy import MetaData

from aicore.repository import schema

if TYPE_CHECKING:
    import pytest

#: 渲染分片模板用的演练月。刻意是常量而非当前月：本比对与"今天是几月"无关。
RENDER_MONTH = "202601"

#: 非空下限：9 张逻辑表 = 3 张分片表 + 6 张非分片表。
TABLE_COUNT = 9


# ---------------------------------------------------------------------------
# 三源取值（一律调共享层，本文件 MUST NOT 另写解析）
# ---------------------------------------------------------------------------
def er_tables() -> dict[str, schema.TableSpec]:
    """`er.md` §6 数据字典。"""
    return schema.parse_er_md(schema.ER_MD.read_text(encoding="utf-8"))


def ddl_tables() -> dict[str, schema.TableSpec]:
    """`deploy/sql/ddl/**`（含三张分片模板的共享层渲染）。"""
    return schema.parse_ddl_directory(schema.DDL_DIR, month=RENDER_MONTH)


def metadata_tables() -> dict[str, schema.TableSpec]:
    """`repository/models.py` 的 `Base.metadata`。"""
    return schema.from_metadata(schema.load_metadata())


def test_three_sources_are_non_vacuous() -> None:
    """非空下限：三源各自都 MUST 解出 9 张表。

    没有这条，下面的"两边都空、彼此一致"会表现为全绿 —— 那是比红更坏的结果：
    检查器看起来在工作，实际上什么都没比。
    """
    for name, tables in (
        ("DDL", ddl_tables()),
        ("er.md", er_tables()),
        ("SQLAlchemy 元数据", metadata_tables()),
    ):
        assert len(tables) == TABLE_COUNT, (
            f"{name} 只解析到 {len(tables)} 张表（期望 {TABLE_COUNT}）：{sorted(tables)}"
        )


# ---------------------------------------------------------------------------
# 方向 ①：改 DDL（文本层）
#
# 选非分片表的 `.sql`：它可直接 `schema.parse_ddl`，不必先渲染模板，改动到结论的
# 因果链最短（分片模板的渲染由共享层负责，不是本方向要验的东西）。
# ---------------------------------------------------------------------------
MUTATED_DDL_FILE = "25_vision_qa_log.sql"
MUTATED_DDL_TABLE = "vision_qa_log"
MUTATED_DDL_COLUMN = "qa_id"
MUTATED_DDL_FROM = "varchar(32)"
MUTATED_DDL_TO = "varchar(64)"


def _ddl_text_with_widened_column() -> str:
    """把 `qa_id` 的类型由 `varchar(32)` 改成 `varchar(64)`（只在内存里改文本）。"""
    text = (schema.DDL_DIR / MUTATED_DDL_FILE).read_text(encoding="utf-8")
    pattern = re.compile(r"(?m)^(\s*`" + re.escape(MUTATED_DDL_COLUMN) + r"`\s+)varchar\(32\)")
    mutated, replaced = pattern.subn(r"\1varchar(64)", text)
    # 自检：改不动就说明 DDL 已变、或正则锚错了列 —— 那时下面的"红"是假的（根本没改到东西），
    # 而假绿的检查比没有检查更危险。
    assert replaced == 1, (
        f"{MUTATED_DDL_FILE} 里形如 `` `{MUTATED_DDL_COLUMN}` varchar(32) `` 的列定义"
        f"应恰好 1 处，实际 {replaced} 处：改动没落到目标列上"
    )
    return mutated


def test_ddl_side_unmutated_is_green() -> None:
    """正常态对照（方向①）：未改动的 DDL 与 `er.md` 必须 `diff == []`。"""
    ddl = ddl_tables()
    assert len(ddl) == TABLE_COUNT, sorted(ddl)
    assert schema.diff(er_tables(), ddl) == []


def test_mutating_ddl_side_goes_red() -> None:
    """方向①：DDL 单边改一列类型 -> 清单点名该表该列，且给出**期望与实际**两个值。"""
    er = er_tables()
    ddl = ddl_tables()
    assert len(ddl) == TABLE_COUNT, sorted(ddl)

    mutated = schema.parse_ddl(_ddl_text_with_widened_column())
    assert len(mutated) == 1, sorted(mutated)
    original = ddl[MUTATED_DDL_TABLE]
    ddl[MUTATED_DDL_TABLE] = mutated[MUTATED_DDL_TABLE]
    # 反假绿：改动 MUST 反映到**解析结果**上（只改到文本、解析却没变，下面的"红"就是假的）。
    assert ddl[MUTATED_DDL_TABLE] != original, "改动没有反映到解析结果里（这条断言会变成假绿）"

    differences = schema.diff(er, ddl)
    assert len(differences) == 1, f"期望恰好 1 处差异，实际 {len(differences)}：{differences}"
    message = differences[0]
    assert MUTATED_DDL_TABLE in message and MUTATED_DDL_COLUMN in message, message
    assert MUTATED_DDL_FROM in message, f"清单缺少期望值 {MUTATED_DDL_FROM}：{message}"
    assert MUTATED_DDL_TO in message, f"清单缺少实际值 {MUTATED_DDL_TO}：{message}"


# ---------------------------------------------------------------------------
# 方向 ②：改 `er.md`（文本层）
#
# **刻意写全整行**而不是只写片段：`er.md` 里有三处 `reviewed_at`（另两处的「空」是 YES），
# 用片段替换可能命中别处；写全行 + `count == 1` 自检才能保证"改的正是这一处、且只改一处"。
# 行写死了也要留个响亮的失败：`er.md` 一改，`count == 1` 立刻报红并指出该更新这里。
# ---------------------------------------------------------------------------
MUTATED_ER_TABLE = "review_verdict"
MUTATED_ER_COLUMN = "reviewed_at"
MUTATED_ER_ROW = "| reviewed_at | datetime(3) | NO | — | — | 复核时间（全链路审计） |"


def _er_text_with_nullable_flipped() -> str:
    """把 `review_verdict.reviewed_at` 那一行的「空」由 `NO` 改成 `YES`（只在内存里改）。"""
    text = schema.ER_MD.read_text(encoding="utf-8")
    assert text.count(MUTATED_ER_ROW) == 1, (
        f"{schema.ER_MD.name} 里目标行应恰好出现 1 次，实际 {text.count(MUTATED_ER_ROW)} 次："
        f"er.md 已改动，请同步更新本文件里的 MUTATED_ER_ROW"
    )
    return text.replace(MUTATED_ER_ROW, MUTATED_ER_ROW.replace("| NO |", "| YES |", 1))


def test_er_md_side_unmutated_is_green() -> None:
    """正常态对照（方向②）：未改动的 `er.md` 与 DDL 必须 `diff == []`。"""
    er = er_tables()
    assert len(er) == TABLE_COUNT, sorted(er)
    assert schema.diff(er, ddl_tables()) == []


def test_mutating_er_md_side_goes_red() -> None:
    """方向②：`er.md` 单边改一列可空性 -> 清单必须含「可空性」并点名表 + 字段。"""
    ddl = ddl_tables()
    assert len(ddl) == TABLE_COUNT, sorted(ddl)

    mutated = schema.parse_er_md(_er_text_with_nullable_flipped())
    assert len(mutated) == TABLE_COUNT, sorted(mutated)
    # 反假绿：改动 MUST 反映到**解析结果**上（只改到文本、解析却没变，下面的"红"就是假的）。
    assert mutated[MUTATED_ER_TABLE] != er_tables()[MUTATED_ER_TABLE], (
        "改动没有反映到解析结果里（这条断言会变成假绿）"
    )

    differences = schema.diff(mutated, ddl)
    assert len(differences) == 1, f"期望恰好 1 处差异，实际 {len(differences)}：{differences}"
    message = differences[0]
    assert "可空性不一致" in message, message
    assert MUTATED_ER_TABLE in message and MUTATED_ER_COLUMN in message, message


# ---------------------------------------------------------------------------
# 方向 ③：改模型（临时 MetaData）
#
# 只改 `nullable` 而**不**改类型，理由是对象共享：`to_metadata` 内部的 `Column._copy()`
# 对普通类型（VARCHAR / DECIMAL 这类）**共享同一个 TypeEngine 实例**（只有 `Enum` 这类
# SchemaEventTarget 才会 copy），于是 `column.type.length = 64` 会**连带改到
# `Base.metadata`** —— 污染全局元数据、连累同进程的其它用例。
# `nullable` 是 Column 自己的属性，改副本不会碰到原件（下面有断言钉住这一点）。
# ---------------------------------------------------------------------------
MUTATED_META_TABLE = "vision_review"
MUTATED_META_COLUMN = "confidence"


def _metadata_with_flipped_nullable() -> MetaData:
    """`Base.metadata` 的深拷贝 + 把某列 `nullable` 取反（**原件不受影响**）。"""
    original = schema.load_metadata()
    copied = MetaData()
    for table in original.tables.values():
        table.to_metadata(copied)
    column = copied.tables[MUTATED_META_TABLE].c[MUTATED_META_COLUMN]
    column.nullable = not column.nullable
    # 自检：改副本 MUST NOT 动到原件（否则"红"会污染同进程的其它用例，且失败点离原因很远）。
    assert original.tables[MUTATED_META_TABLE].c[MUTATED_META_COLUMN].nullable != column.nullable, (
        f"改临时 MetaData 时碰到了 Base.metadata.{MUTATED_META_TABLE}.{MUTATED_META_COLUMN}"
    )
    return copied


def test_metadata_side_unmutated_is_green() -> None:
    """正常态对照（方向③）：未改动的元数据与 DDL 必须 `diff == []`。"""
    meta = metadata_tables()
    assert len(meta) == TABLE_COUNT, sorted(meta)
    assert schema.diff(ddl_tables(), meta) == []


def test_mutating_metadata_side_goes_red() -> None:
    """方向③：模型单边改一列可空性 -> 清单点名该列（模型与 DDL 走偏 MUST 被抓）。"""
    ddl = ddl_tables()
    assert len(ddl) == TABLE_COUNT, sorted(ddl)

    mutated = schema.from_metadata(_metadata_with_flipped_nullable())
    assert len(mutated) == TABLE_COUNT, sorted(mutated)
    # 反假绿：改动 MUST 反映到**导出结果**上（只改到 MetaData、导出却没变，下面的"红"就是假的）。
    assert mutated[MUTATED_META_TABLE] != metadata_tables()[MUTATED_META_TABLE], (
        "改动没有反映到 from_metadata 的结果里（这条断言会变成假绿）"
    )

    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1, f"期望恰好 1 处差异，实际 {len(differences)}：{differences}"
    message = differences[0]
    assert MUTATED_META_TABLE in message and MUTATED_META_COLUMN in message, message
    assert "可空性不一致" in message, message


# ---------------------------------------------------------------------------
# CLI 门禁 `scripts/compare_schema.py` 的退出码
#
# **按路径载入真脚本**而不是在测试里重写一份退出码逻辑：重写等于测"我抄的那份"，
# 真正的门禁仍然可以悄悄坏掉。脚本自身在导入时把 `src` 挂上 `sys.path`（见其文件头）。
# ---------------------------------------------------------------------------
_COMPARE_SCHEMA_PATH = schema.SERVICE_ROOT / "scripts" / "compare_schema.py"


def _load_compare_schema() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aicore_compare_schema", _COMPARE_SCHEMA_PATH)
    assert spec is not None and spec.loader is not None, f"无法载入 {_COMPARE_SCHEMA_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare_schema = _load_compare_schema()

#: 一定不存在的库名：用来验证"连不上 MUST 非 0"，而不是静默降级成"两源通过"。
_MISSING_DATABASE = "aicore_db_that_does_not_exist"

#: 口令环境变量（脚本按 `DSH_IT_MYSQL_` 与 `AICORE_MYSQL_` 两个前缀查 `PASSWORD`）。
_PASSWORD_ENV_VARS = ("DSH_IT_MYSQL_PASSWORD", "AICORE_MYSQL_PASSWORD")


def test_compare_schema_returns_zero_on_the_happy_path(capsys: pytest.CaptureFixture[str]) -> None:
    """正常态：三源两两一致 -> 退出码 `0`。

    顺带钉住"三个源都真解出了 9 张表"：只看退出码的话，三源**同时**解析塌成 0 张表
    也会报一致并通过 —— 那正是脚本里 `EXPECTED_TABLE_COUNT` 自检要拦的东西。
    """
    code = compare_schema.main([])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert printed.count(f"解析到 {TABLE_COUNT} 张表") == 3, printed
    assert "[FAIL]" not in printed, printed


def test_compare_schema_with_mysql_without_password_is_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺口令时 `--with-mysql` 返回 `2`：MUST NOT 静默降级成"两源通过"。"""
    for name in _PASSWORD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert compare_schema.main(["--with-mysql"]) == 2


def test_compare_schema_with_mysql_unreachable_database_is_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连不上库时 `--with-mysql` 返回 `2`（库不存在、MySQL 没起、口令不对都算连不上）。

    口令从环境取（`tests/conftest.py` 会用本机 `.env` 回填 `DSH_IT_MYSQL_PASSWORD`）；
    取不到时用**一眼看得出是占位符**的非空串顶上 —— 目的是让脚本**真的走到连接那一步**：
    留空会让它命中上一条用例的"缺口令"提前返回，这条断言就退化成重复的空断言。
    **MUST NOT 硬编码真实口令**（那是把凭据写进版本库）。
    """
    monkeypatch.setenv(
        "DSH_IT_MYSQL_PASSWORD",
        os.environ.get("DSH_IT_MYSQL_PASSWORD") or "not-a-real-password",
    )
    assert compare_schema.main(["--with-mysql", "--database", _MISSING_DATABASE]) == 2
