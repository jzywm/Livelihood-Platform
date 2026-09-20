"""`repository/schema.py` 的用例：四源解析、归一化、差异清单。

**本文件覆盖的是"一致性检查工具自身"**——它的正确性直接决定三源比对能不能抓到真问题。
故用例分四组：

1. **归一化**：类型同义名与**枚举值大小写**（后者是本项目踩过两次的坑：
   Task 3.1 的 `er.md` 解析、Task 3.6 首版 `normalize_type` 都被整体 `.lower()` 害过）；
2. **表格解析**：DDL / `er.md` 的 9 张表都能解出，且**§6.10 辅助结构不被当成数据行**
   （它是 3 列表，靠标题文字区分章节会把它算成上一节的行——Task 3.1 首轮就是这么崩的）；
3. **元数据导出**：MUST 按 **MySQL 方言**编译类型，否则 `int unsigned` / `datetime(3)`
   会以 `INTEGER` / `DATETIME` 出现而与 DDL 假性不等；
4. **差异清单**：`diff` MUST 给出人可读、指出"哪张表哪个字段、期望 vs 实际"的清单，
   且**每一类差异都要有一条"会报警"的证据**（表集合 / 列集合 / 列顺序 / 类型 / 可空 / 枚举）。
"""

from __future__ import annotations

import pytest

from aicore.repository import schema
from aicore.repository.models import Base

# ---------------------------------------------------------------------------
# 第 1 组：归一化
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 类型名大小写不敏感
        ("int UNSIGNED", "int unsigned"),
        ("INTEGER UNSIGNED", "int unsigned"),
        ("VARCHAR(32)", "varchar(32)"),
        ("DATETIME(3)", "datetime(3)"),
        # 括号内逗号后的空格要压掉
        ("DECIMAL(5, 2)", "decimal(5,2)"),
        # 同义名归一（MySQL 里就是同一个类型）
        ("NUMERIC(3,2)", "decimal(3,2)"),
        ("BOOL", "tinyint(1)"),
        ("BOOLEAN", "tinyint(1)"),
        ("tinyint(1)", "tinyint(1)"),
        ("INTEGER", "int"),
        # 枚举：**类型名**小写，**枚举值**保原样
        ("enum('HIGH', 'MEDIUM', 'LOW')", "enum('HIGH','MEDIUM','LOW')"),
        ("ENUM('VALID','EXPIRING')", "enum('VALID','EXPIRING')"),
    ],
)
def test_normalize_type(raw: str, expected: str) -> None:
    assert schema.normalize_type(raw) == expected


def test_normalize_type_preserves_enum_value_case() -> None:
    """**本项目的重点**：枚举值是 SQL 字符串字面量，大小写敏感，MUST NOT 被小写。

    这条断言存在的理由：整体 `.lower()` 的写法在本项目**被写错过两次**
    （Task 3.1 的 `er.md` 解析器、Task 3.6 首版 `normalize_type`），
    每次的表现都是"枚举列全报不一致"这种看着像真缺陷的假红。
    """
    normalized = schema.normalize_type("enum('AI_PROCESSING','PENDING')")
    assert "AI_PROCESSING" in normalized
    assert "ai_processing" not in normalized


def test_normalize_type_handles_parenthesis_inside_enum_value() -> None:
    """枚举值里可能出现 `)`：故实现是引号感知 + 深度计数，不是正则断句。"""
    normalized = schema.normalize_type("enum('A)','B(')")
    assert normalized == "enum('A)','B(')"


@pytest.mark.parametrize(
    ("physical", "logical"),
    [
        ("ai_task_202601", "ai_task"),
        ("ocr_result_209912", "ocr_result"),
        ("vision_review", "vision_review"),
        ("risk_predict_result", "risk_predict_result"),
    ],
)
def test_normalize_table_name(physical: str, logical: str) -> None:
    assert schema.normalize_table_name(physical) == logical


# ---------------------------------------------------------------------------
# 第 2 组：表格解析
# ---------------------------------------------------------------------------


def test_parse_er_md_yields_exactly_nine_tables() -> None:
    """非空下限：解析塌了必须报警，而不是"9 张表都没解出来"却全绿。"""
    tables = schema.parse_er_md(schema.ER_MD.read_text(encoding="utf-8"))
    assert len(tables) == 9, f"er.md 应解出 9 张表，实际 {len(tables)}：{sorted(tables)}"


def test_parse_er_md_skips_the_auxiliary_section() -> None:
    """§6.10「辅助结构（Redis / MQ / OSS）」是 3 列表，MUST NOT 被当成某张表的数据行。

    靠标题文字（"后面是不是 ASCII 表名"）区分章节会漏掉它——它的中文标题让正则不匹配，
    于是它的行被算进上一节，报"列数不足"（Task 3.1 首轮实测：连带 8 条用例全红）。
    正确判据是**只认 6 列表头**。
    """
    text = schema.ER_MD.read_text(encoding="utf-8")
    tables = schema.parse_er_md(text)
    # 辅助结构里的条目不应出现在任何表里
    all_columns = {column.name for spec in tables.values() for column in spec.columns}
    assert "task:{task_id}" not in all_columns
    assert "aicore.conclusion" not in all_columns


def test_parse_er_md_rejects_a_row_with_too_few_cells() -> None:
    """数据字典章节里列数不足 MUST 抛错（"解析塌了要报警"的防线，不为了让某节过而删）。"""
    broken = (
        "### 6.1 ai_task（测试）\n"
        "\n"
        "| 字段 | 类型 | 空 | 键 | 默认 | 说明 |\n"
        "|---|---|---|---|---|---|\n"
        "| a | b |\n"
    )
    with pytest.raises(schema.SchemaParseError, match="列数不足"):
        schema.parse_er_md(broken)


def test_parse_ddl_reads_columns_and_enums() -> None:
    text = (schema.DDL_DIR / "20_vision_review.sql").read_text(encoding="utf-8")
    tables = schema.parse_ddl(text)
    assert set(tables) == {"vision_review"}
    spec = tables["vision_review"]
    names = list(spec.column_names())
    assert names[:3] == ["review_id", "task_id", "biz_type"]
    status = next(column for column in spec.columns if column.name == "status")
    assert status.enum_values == (
        "AI_PROCESSING",
        "PENDING",
        "CONFIRMED",
        "REFERRED",
        "REJECTED",
        "ARCHIVED",
    )
    # 索引/约束项 MUST NOT 被当成列
    assert "PRIMARY" not in names
    assert all(not name.startswith("idx") for name in names)


def test_parse_ddl_ignores_comments() -> None:
    """注释里的示例 SQL 不是结构：去掉 `--` 行后不应多出表。"""
    text = (
        "-- CREATE TABLE IF NOT EXISTS `fake` (`x` int) ENGINE=InnoDB;\n"
        + (schema.DDL_DIR / "25_vision_qa_log.sql").read_text(encoding="utf-8")
    )
    assert set(schema.parse_ddl(text)) == {"vision_qa_log"}


def test_parse_ddl_directory_covers_all_nine_tables() -> None:
    """整目录解析（含 3 张模板渲染）必须得到 9 张逻辑表。"""
    tables = schema.parse_ddl_directory(schema.DDL_DIR, month="202601")
    assert len(tables) == 9, sorted(tables)
    assert "ai_task" in tables and "ocr_correction" in tables


def test_parse_ddl_directory_refuses_a_template_outside_the_shard_manifest() -> None:
    """模板名不在分片清单里 MUST 抛错——否则新加一张模板会被静默当成固定表。"""
    fake = schema.DDL_DIR / "99_not_a_real_table.template.sql"
    assert not fake.exists()
    try:
        fake.write_text("CREATE TABLE IF NOT EXISTS `x` (`a` int) ENGINE=InnoDB;", encoding="utf-8")
        with pytest.raises(schema.SchemaParseError, match="不在分片表清单内"):
            schema.parse_ddl_directory(schema.DDL_DIR, month="202601")
    finally:
        fake.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 第 3 组：元数据导出
# ---------------------------------------------------------------------------


def test_from_metadata_compiles_types_with_mysql_dialect() -> None:
    """**必须按 MySQL 方言编译**：只读 `str(column.type)` 会丢掉 `unsigned` 与 `(3)`。

    实测对照（Task 3.2 的模型用了 `with_variant(..., "mysql")`）：
        progress    generic=INTEGER    mysql=INTEGER UNSIGNED
        created_at  generic=DATETIME   mysql=DATETIME(3)
    不按方言编译就会与 DDL 的 `int unsigned` / `datetime(3)` 假性不等——
    而假性不等的下一步往往是"有人把这条检查关掉"。
    """
    tables = schema.from_metadata(Base.metadata)
    ai_task = tables["ai_task"]
    progress = next(column for column in ai_task.columns if column.name == "progress")
    assert progress.type == "int unsigned", progress.type
    created_at = next(column for column in ai_task.columns if column.name == "created_at")
    assert created_at.type == "datetime(3)", created_at.type


def test_from_metadata_uses_logical_table_names_only() -> None:
    """元数据里只有逻辑表名（物理分片名由 sharding 现算）。"""
    tables = schema.from_metadata(Base.metadata)
    assert len(tables) == 9
    assert not any(name[-6:].isdigit() for name in tables)


def test_from_metadata_reads_enum_values() -> None:
    tables = schema.from_metadata(Base.metadata)
    status = next(
        column for column in tables["vision_review"].columns if column.name == "status"
    )
    assert status.enum_values == (
        "AI_PROCESSING",
        "PENDING",
        "CONFIRMED",
        "REFERRED",
        "REJECTED",
        "ARCHIVED",
    )


# ---------------------------------------------------------------------------
# 第 4 组：三源一致 + 差异清单的每一类都要有"会报警"的证据
# ---------------------------------------------------------------------------


def _three_sources() -> tuple[
    dict[str, schema.TableSpec], dict[str, schema.TableSpec], dict[str, schema.TableSpec]
]:
    ddl = schema.parse_ddl_directory(schema.DDL_DIR, month="202601")
    er = schema.parse_er_md(schema.ER_MD.read_text(encoding="utf-8"))
    meta = schema.from_metadata(Base.metadata)
    return ddl, er, meta


def test_three_sources_agree_on_the_happy_path() -> None:
    """正常态：三源两两一致（这是 Task 3.6 的核心断言）。"""
    ddl, er, meta = _three_sources()
    assert schema.diff(ddl, er) == []
    assert schema.diff(ddl, meta) == []
    assert schema.diff(er, meta) == []


def _copy(tables: dict[str, schema.TableSpec]) -> dict[str, schema.TableSpec]:
    return {
        name: schema.TableSpec(name=spec.name, columns=tuple(spec.columns))
        for name, spec in tables.items()
    }


def test_diff_detects_missing_table() -> None:
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    del mutated["vision_review"]
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1
    assert "vision_review" in differences[0]


def test_diff_detects_missing_column() -> None:
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    spec = mutated["vision_review"]
    mutated["vision_review"] = schema.TableSpec(
        name=spec.name,
        columns=tuple(column for column in spec.columns if column.name != "confidence"),
    )
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1
    assert "confidence" in differences[0]
    assert "列集合不一致" in differences[0]


def test_diff_detects_column_order_change() -> None:
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    spec = mutated["vision_review"]
    columns = list(spec.columns)
    columns[0], columns[1] = columns[1], columns[0]
    mutated["vision_review"] = schema.TableSpec(name=spec.name, columns=tuple(columns))
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1
    assert "列顺序不一致" in differences[0]


@pytest.mark.parametrize(
    ("field", "column_name", "expected_marker"),
    [
        ("类型", "confidence", "类型不一致"),
        ("可空性", "reviewed_at", "可空性不一致"),
    ],
)
def test_diff_detects_type_and_nullable_changes(
    field: str, column_name: str, expected_marker: str
) -> None:
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    spec = mutated["vision_review"]
    columns = []
    for column in spec.columns:
        if column.name != column_name:
            columns.append(column)
            continue
        if field == "类型":
            columns.append(
                schema.ColumnSpec(
                    name=column.name,
                    type="varchar(64)",
                    nullable=column.nullable,
                    enum_values=None,
                )
            )
        else:
            columns.append(
                schema.ColumnSpec(
                    name=column.name,
                    type=column.type,
                    nullable=not column.nullable,
                    enum_values=column.enum_values,
                )
            )
    mutated["vision_review"] = schema.TableSpec(name=spec.name, columns=tuple(columns))
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1, differences
    assert expected_marker in differences[0]
    assert column_name in differences[0]


def test_diff_detects_enum_value_change() -> None:
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    spec = mutated["review_verdict"]
    columns = []
    for column in spec.columns:
        if column.name != "action":
            columns.append(column)
            continue
        columns.append(
            schema.ColumnSpec(
                name="action",
                type=column.type,
                nullable=column.nullable,
                enum_values=("CONFIRM", "REFER", "REJECT"),
            )
        )
    mutated["review_verdict"] = schema.TableSpec(name=spec.name, columns=tuple(columns))
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1, differences
    assert "枚举值不一致" in differences[0]


def test_diff_lists_expected_and_actual_values() -> None:
    """差异清单 MUST 同时给出**期望与实际**（退化成一句 `a != b` 的检查最终会被绕过）。"""
    ddl, er, _ = _three_sources()
    mutated = _copy(er)
    spec = mutated["vision_qa_log"]
    columns = [
        schema.ColumnSpec(name="qa_id", type="varchar(64)", nullable=False, enum_values=None)
        if column.name == "qa_id"
        else column
        for column in spec.columns
    ]
    mutated["vision_qa_log"] = schema.TableSpec(name=spec.name, columns=tuple(columns))
    differences = schema.diff(ddl, mutated)
    assert len(differences) == 1
    message = differences[0]
    assert "varchar(32)" in message  # 期望值
    assert "varchar(64)" in message  # 实际值
