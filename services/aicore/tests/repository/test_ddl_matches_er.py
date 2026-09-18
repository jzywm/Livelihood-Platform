"""逐列比对用例：`docs/er.md` §6 数据字典、`deploy/sql/ddl/*.sql`、`docs/openapi.yaml` 三方一致。

**为什么是纯文本用例**（无需数据库）：本用例要在**任何环境**（含无 MySQL 的 CI 与全新
checkout）拦住「文档改了表没跟上 / 表改了文档没跟上」这类静默漂移（design.md 风险项
「er.md 与 DDL 单边改动」）。真实 `information_schema` 侧的一致性由集成用例承担，
本用例只做离线文本层比对，故 MUST NOT 依赖数据库、网络或任何密钥。

**解析只剩一份**（Task 3.6b 重构）：DDL 与 `er.md` 的解析一律调共享层
`aicore.repository.schema`（`parse_ddl` / `parse_ddl_directory` / `parse_er_md` /
`normalize_type` / `strip_sql_comments` / `diff`），占位符渲染与 SQL 骨架一律调
`aicore.repository.sharding`（`render_shard_template` / `sql_skeleton`）。
本文件 **MUST NOT** 再出现第二份解析或渲染实现 —— Task 3.6 的价值全在「一致性检查本身
可信」，而两份实现的漂移表现是 `test_ddl_matches_er.py` 绿、`compare_schema.py` 红
（或反之）：两个都叫「一致性检查」的工具互相矛盾，没人知道该信谁。

**本文件唯一的局部解析是 `parse_er_defaults`**（`er.md` 的「默认」列）：共享层的
`ColumnSpec` 刻意只承载**四个来源都表达得了**的维度，而默认值只有 `er.md` 与 DDL
表达得了。详见该函数 docstring 里的完整理由。

**本文件独有的注释维度检查**：`COMMENT_*_RE` / `DDL_COLUMN_ITEM_RE` /
`split_column_clauses` / `collect_column_clauses` 与
`test_every_column_and_table_has_chinese_comment` —— 共享层只比结构
（表 / 列 / 类型 / 可空 / 枚举），**不比注释**，故这几件留在本地。

**期望值从哪来**（brief 硬性要求）：列名 / 类型 / 可空性 / 默认值 / 枚举值的期望值一律
**解析自 `docs/er.md` 与 `docs/openapi.yaml`**，MUST NOT 把数据字典的内容抄进本文件当期望值
—— 抄两遍等于把同一个笔误写两处，双双写错也发现不了。本文件里**唯一**硬编码的是
openapi 的枚举值集（`OPENAPI_ENUM_SPOT_CHECK`）与 DDL 列 -> openapi 路径的接线
（`DDL_ENUM_TO_OPENAPI`）：前者是"工单定档值"这一独立事实源，后者是两份源文件之间的
接线（无法从任一侧推导），两者都硬编码，才能让「openapi 被悄悄改值」也变红。

比对方向（四处都要成立，缺一即红）：
  1. er.md 枚举列  ==  DDL 枚举列          （test_ddl_enums_match_er_enums）
  2. DDL 枚举列    ==  openapi 枚举       （test_ddl_enum_matches_openapi_enum）
  3. openapi 枚举  ==  定档抽查值          （test_openapi_enum_values_match_spot_check）
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from aicore.repository import schema, sharding

# 注意：`Mapping` **MUST NOT** 只放在 `if TYPE_CHECKING:` 里。
# 它在本文件里是**运行期**用到的（`isinstance(document, Mapping)` 与函数签名），
# 只在类型检查期导入会让 `load_openapi()` 抛 `NameError: name 'Mapping' is not defined`
# —— 本任务首轮就是这么挂掉 18 条用例的（报错点离真正原因很远，极难回推）。

# ---------------------------------------------------------------------------
# 路径口径与共享层**同源**
#
# `DDL_DIR` / `ER_MD` 直接取共享层常量，本文件 MUST NOT 另算一份路径：
# 两份路径定义会在目录搬迁时漂移，而漂移的表现是"两个工具各比各的、结论互相矛盾"。
# `openapi.yaml` 只有本文件用（共享层不管它），故它的路径写在这里。
# ---------------------------------------------------------------------------
SERVICE_ROOT = schema.SERVICE_ROOT
DDL_DIR = schema.DDL_DIR
ER_MD = schema.ER_MD
OPENAPI_YAML = SERVICE_ROOT / "docs" / "openapi.yaml"

# ---------------------------------------------------------------------------
# 逻辑表 -> DDL 文件（brief 的 Files 表逐行落位）
#
# **刻意不从 `repository/sharding.py` 取这份清单**：它是本用例的**独立期望源**
# （`test_ddl_directory_matches_brief_manifest` 拿它去卡真实目录，见该用例 docstring），
# 从被测实现里取清单会让断言退化成"自己跟自己比"。
#
# 三张分片表用 `.template.sql`（含 {table} / {month} 占位符，不能直接执行）；
# 六张非分片表用 `.sql`。
# ---------------------------------------------------------------------------
SHARDED_TABLES: dict[str, str] = {
    "ai_task": "10_ai_task.template.sql",
    "ocr_result": "11_ocr_result.template.sql",
    "ocr_correction": "12_ocr_correction.template.sql",
}
FIXED_TABLES: dict[str, str] = {
    "vision_review": "20_vision_review.sql",
    "vision_marker": "21_vision_marker.sql",
    "review_verdict": "22_review_verdict.sql",
    "kitchen_anomaly": "23_kitchen_anomaly.sql",
    "risk_predict_result": "24_risk_predict_result.sql",
    "vision_qa_log": "25_vision_qa_log.sql",
}
ALL_TABLES: dict[str, str] = {**SHARDED_TABLES, **FIXED_TABLES}

# brief：物理表名形如 `ai_task_202601`；渲染/演练统一用这个月。
#
# **刻意是常量而非当前月**（共享层把 `month` 设计成必填的调用方参数正是为此）：
# 本比对与"今天是几月"无关，取当前月会让同一份代码在元旦、月末得出不同结论。
RENDER_MONTH = "202601"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# ---------------------------------------------------------------------------
# 枚举接线：DDL 列 -> openapi 中该枚举的取值位置
#
# 路径是 YAML 的 key 序列（不用行号：行号会随文档增删而漂移，key 路径不会）。
# 两种形态都覆盖：
#   - 具名 schema：components.schemas.<Name>.enum（TaskType / ConfidenceLevel ...）
#   - 属性内联 enum：components.schemas.<Parent>.properties.<prop>.enum
#     （`MatchResult.validity`）
# ---------------------------------------------------------------------------
_SCHEMAS = ("components", "schemas")
DDL_ENUM_TO_OPENAPI: dict[str, tuple[str, ...]] = {
    "ai_task.type": (*_SCHEMAS, "TaskType", "enum"),
    "ai_task.status": (*_SCHEMAS, "TaskStatus", "enum"),
    "ocr_result.validity": (*_SCHEMAS, "MatchResult", "properties", "validity", "enum"),
    "vision_review.biz_type": (*_SCHEMAS, "VisionBizType", "enum"),
    "vision_review.status": (*_SCHEMAS, "VisionReviewStatus", "enum"),
    "vision_review.confidence_level": (*_SCHEMAS, "ConfidenceLevel", "enum"),
    "vision_marker.level": (*_SCHEMAS, "ConfidenceLevel", "enum"),
    "review_verdict.action": (*_SCHEMAS, "VerdictAction", "enum"),
    "kitchen_anomaly.confidence_level": (*_SCHEMAS, "ConfidenceLevel", "enum"),
    "kitchen_anomaly.status": (*_SCHEMAS, "KitchenAnomalyStatus", "enum"),
    "risk_predict_result.risk_level": (*_SCHEMAS, "RiskLevel", "enum"),
}

# 抽查式硬编码：openapi 的枚举**值**必须与下表逐字一致。
# 这不是"抄一遍 er.md"——它抄的是 openapi 侧的定档值集，作用是把「DDL 与 openapi
# 一起被改错」也变成红灯（只做 DDL == openapi 的双向断言时，两边同时改就都绿了）。
# 键与 DDL_ENUM_TO_OPENAPI 的路径一一对应，故 openapi 侧一旦改名/挪位置，
# test_enum_wiring_is_self_consistent 与 test_openapi_spot_check_has_no_stale_path 会先报红。
OPENAPI_ENUM_SPOT_CHECK: dict[tuple[str, ...], set[str]] = {
    (*_SCHEMAS, "TaskType", "enum"): {"OCR", "VISION_REVIEW", "KITCHEN_ANOMALY", "RISK_PREDICT"},
    (*_SCHEMAS, "TaskStatus", "enum"): {"PROCESSING", "SUCCEEDED", "FAILED", "MANUAL_REVIEW"},
    (*_SCHEMAS, "MatchResult", "properties", "validity", "enum"): {
        "VALID",
        "EXPIRING",
        "EXPIRED",
        "UNKNOWN",
    },
    (*_SCHEMAS, "VisionBizType", "enum"): {
        "RAW_MATERIAL",
        "CERTIFICATE",
        "INSPECTION_SAMPLE",
        "KITCHEN",
    },
    (*_SCHEMAS, "VisionReviewStatus", "enum"): {
        "AI_PROCESSING",
        "PENDING",
        "CONFIRMED",
        "REFERRED",
        "REJECTED",
        "ARCHIVED",
    },
    (*_SCHEMAS, "ConfidenceLevel", "enum"): {"HIGH", "MEDIUM", "LOW"},
    (*_SCHEMAS, "VerdictAction", "enum"): {"CONFIRM", "REFER", "REJECT", "ARCHIVE"},
    (*_SCHEMAS, "KitchenAnomalyStatus", "enum"): {"PENDING", "CONFIRMED", "REJECTED", "ARCHIVED"},
    (*_SCHEMAS, "RiskLevel", "enum"): {"LOW", "MEDIUM", "HIGH", "CRITICAL"},
}

# 非空下限：解析塌了（路径写错、文件被换、正则失效）时必须报警而不是静默全绿。
MIN_ER_TABLES = 9
MIN_ENUM_COLUMNS = 11
MIN_OPENAPI_ENUM_LINES = 10
MIN_TIMESTAMP_DEFAULT_COLUMNS = 3


# ---------------------------------------------------------------------------
# 共享层调用点
#
# 下面两个函数**不含任何解析**，只是共享层的调用点：把"用哪个月渲染模板"这一个决策
# 收在一处。它们 MUST NOT 长出解析逻辑 —— 那正是本次重构删掉的第二份实现。
# ---------------------------------------------------------------------------
def load_er_tables() -> dict[str, schema.TableSpec]:
    """`er.md` §6 数据字典 -> `{逻辑表名: TableSpec}`（解析全部由共享层做）。"""
    return schema.parse_er_md(ER_MD.read_text(encoding="utf-8"))


def load_ddl_tables() -> dict[str, schema.TableSpec]:
    """`deploy/sql/ddl/**` -> `{逻辑表名: TableSpec}`（共享层解析 + 共享层渲染模板）。"""
    return schema.parse_ddl_directory(DDL_DIR, month=RENDER_MONTH)


# ---------------------------------------------------------------------------
# 文本级助手（共享层不做"读某个文件的第几条语句"这类事）
# ---------------------------------------------------------------------------
def ddl_file(table: str) -> Path:
    return DDL_DIR / ALL_TABLES[table]


def read_ddl(table: str) -> str:
    return ddl_file(table).read_text(encoding="utf-8")


def first_create_table_block(table: str) -> str:
    """取某个 DDL 文件里第一条 CREATE TABLE 语句（含 ENGINE / COMMENT 等后缀）。"""
    text = schema.strip_sql_comments(read_ddl(table))
    match = re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b.*?;", text, re.IGNORECASE | re.DOTALL)
    assert match, f"{ALL_TABLES[table]} 中找不到 CREATE TABLE 语句"
    return match.group(0)


def collect_index_names(block: str) -> list[str]:
    """建表正文 -> 显式索引名序列（`idx_*` / `uk_*`；PRIMARY KEY 无名字，不计入）。

    给集成用例做**非空下限**用：只断言"information_schema 里有 4 条外键"而不看索引，
    等于让"索引整批漏建"静默通过；期望值现取自 DDL 自身，不另抄一份清单。
    """
    flat = re.sub(r"\s+", " ", schema.strip_sql_comments(block))
    return re.findall(r"(?:UNIQUE\s+)?(?:KEY|INDEX)\s+`((?:idx|uk)_\w+)`", flat, re.IGNORECASE)


# ---------------------------------------------------------------------------
# 本文件独有的**注释维度**检查（共享层只比结构，不比注释）
# ---------------------------------------------------------------------------
COMMENT_COUNT_RE = re.compile(r"\bCOMMENT\b", re.IGNORECASE)
# 表注释：`COMMENT='...'`（table option 形态）。中文 MUST 落在**引号内**。
TABLE_CN_COMMENT_RE = re.compile(r"COMMENT\s*=\s*'[^']*" + CJK_RE.pattern + r"[^']*'")
# 列注释：`COMMENT '...'`（列属性形态），支持 `\'` 转义。中文同样 MUST 落在**引号内**。
COLUMN_COMMENT_RE = re.compile(r"COMMENT\s+'(?:[^'\\]|\\.)*'")
COLUMN_CN_COMMENT_RE = re.compile(
    r"COMMENT\s+'(?:[^'\\]|\\.)*" + CJK_RE.pattern + r"(?:[^'\\]|\\.)*'"
)
# 反引号列项（`` `col` 类型... ``）的开头：用来把「列」与「索引/约束项」分开。
# 判据与共享层的 `_NON_COLUMN_PREFIX_RE` 同源：PRIMARY/UNIQUE/KEY/INDEX/CONSTRAINT/
# FOREIGN/CHECK 这些项**不是**反引号列名开头，故不会被误判成列。
DDL_COLUMN_ITEM_RE = re.compile(r"^`[^`]+`\s+\S")


def split_column_clauses(block: str) -> list[str]:
    """把建表正文按**列项**切开，每项含该列从列名到 COMMENT 的整段定义。

    **为什么不用 `[^,\\n]*` 这类行内正则**：列定义里本来就有逗号
    （`enum('RAW_MATERIAL','CERTIFICATE',...)`、`decimal(3,2)`），而 COMMENT 在逗号**之后**，
    截断必然把注释切掉 —— 结果是"DDL 里明明有中文注释却报缺失"的假红（本任务首轮的
    四处假红：`vision_review.biz_type` / `status` / `confidence_level` / `confidence`）。

    顶层切分**复用共享层的 `schema._split_top_level`**（本文件 MUST NOT 再写一份）：
    它已正确处理括号与引号，切出来的就是**顶层列项**（列 / 索引 / 约束各成一项）。
    每项再按"行首是不是新的反引号列名"细分成弱换行的同列续行，最后只保留
    **以反引号列名开头**的项 —— `CREATE TABLE ... (` 前缀、索引项、约束项、
    收尾的 `)` 全部落选（否则 `by_name` 与 `clauses` 的长度会对不上，
    那正是 `test_every_column_and_table_has_chinese_comment` 的下限自检）。
    """
    clauses: list[str] = []
    buffer: list[str] = []
    for item in schema._split_top_level(block):
        for raw_line in item.splitlines():
            if raw_line.lstrip().startswith("`") and buffer:
                clauses.append("\n".join(buffer).strip())
                buffer = []
            buffer.append(raw_line)
    if buffer:
        clauses.append("\n".join(buffer).strip())
    return [clause for clause in clauses if DDL_COLUMN_ITEM_RE.match(clause)]


def collect_column_clauses(block: str) -> dict[str, str]:
    """建表正文 -> `{列名: 列定义整段}`（只收反引号开头的列项，索引/约束项跳过）。"""
    clauses: dict[str, str] = {}
    for clause in split_column_clauses(block):
        match = re.match(r"^`(?P<name>[^`]+)`\s", clause)
        if match:
            clauses[match.group("name")] = clause
    return clauses


# ---------------------------------------------------------------------------
# `er.md` 的「默认」列 —— **本文件唯一的局部解析**
# ---------------------------------------------------------------------------
def parse_er_defaults(path: Path = ER_MD) -> dict[str, dict[str, str]]:
    """解析 `er.md` §6 的「默认」列：`表 -> {列: 默认值}`（`NULL` / `—` / `CURRENT_TIMESTAMP(3)`）。

    ## 为什么共享层没有它（MUST 保留这段理由，防后来者"顺手统一掉"）

    共享层的 `ColumnSpec` 刻意只承载**四个来源都表达得了**的维度
    （名 / 类型 / 可空 / 枚举值）。「默认值」只有 `er.md` 与 DDL 表达得了 ——
    把它塞进 `ColumnSpec` 会让 `information_schema` 与模型侧**永远缺这一维**，
    于是四源比对的差异清单里会常年挂着"默认值不一致"的噪音（或更糟：有人为了消噪音
    把这条检查关掉）。故本函数留在本地，只读这一列。

    ## 章节与单元格判据仍然复用共享层

    `schema._ER_HEADING_RE` / `schema.ER_HEADER_CELLS` / `schema._split_markdown_row` /
    `schema._strip_outer_empty` / `schema._is_separator_row` 全部取自共享层，
    本函数**只多做一件事**：取第 5 个单元格。
    **MUST NOT** 在这里另写一套表头/章节判据 —— 那正是 Task 3.1 首轮把
    §6.10「辅助结构」（3 列表）当成 `vision_qa_log` 的数据行、连带 8 条用例全红的坑。

    ## 行数交叉自检（防"局部解析悄悄分叉"）

    每张表读到的数据行数 MUST 等于共享层解出的列数。不等即说明两个读者对
    "哪些行算数据行"的理解已经分叉 —— 那样本函数给出的默认值会张冠李戴，
    而 `test_timestamp_defaults_match_er_notes` 会**变成一条假断言**（对着错的行比）。
    """
    text = path.read_text(encoding="utf-8")
    # 先让共享层校验并解出结构："数据行列数不足""空列既非 YES 也非 NO"等一律由它报错，
    # 本函数不重复这些校验（也正因如此，下面的 cells[4] 不会被短行打穿）。
    structure = schema.parse_er_md(text)

    lines = text.splitlines()
    total = len(lines)
    index = 0
    defaults: dict[str, dict[str, str]] = {}
    while index < total:
        line = lines[index]
        index += 1
        if schema._ER_HEADING_RE.match(line) is None:
            continue
        # 本节第一张表格的第一行。
        while index < total and not lines[index].startswith("|"):
            index += 1
        rows: list[list[str]] = []
        while index < total and lines[index].startswith("|"):
            rows.append(schema._strip_outer_empty(schema._split_markdown_row(lines[index])))
            index += 1
        header = rows[0] if rows else []
        if tuple(header) != schema.ER_HEADER_CELLS:
            continue  # 非数据字典口径（如 §6.10 辅助结构）-> 本节退出比对范围
        name_match = schema._ER_TABLE_NAME_RE.match(line)
        if name_match is None:
            raise schema.SchemaParseError(f"无法从数据字典标题取表名：{line!r}")
        table = name_match.group(1)
        for cells in rows[1:]:
            if schema._is_separator_row(cells):
                continue
            defaults.setdefault(table, {})[cells[0]] = cells[4]

    if set(defaults) != set(structure):
        raise schema.SchemaParseError(
            f"「默认」列读到的表集合与共享层解出的不一致："
            f"仅默认列有 {sorted(set(defaults) - set(structure))}，"
            f"仅共享层有 {sorted(set(structure) - set(defaults))}"
        )
    for table, columns in defaults.items():
        expected = len(structure[table].columns)
        if len(columns) != expected:
            raise schema.SchemaParseError(
                f"表 {table} 的「默认」列读到 {len(columns)} 行，共享层解出 {expected} 列："
                f"两个读者对「哪些行算数据行」的理解已分叉，默认值会张冠李戴"
            )
    return defaults


# ---------------------------------------------------------------------------
# 枚举取值（一律现取共享层解好的 `enum_values`，不另写 `enum(...)` 正则）
# ---------------------------------------------------------------------------
def collect_enums(tables: Mapping[str, schema.TableSpec]) -> dict[str, tuple[str, ...]]:
    """`表.列 -> 枚举值序列`（从共享层解出的 `ColumnSpec.enum_values` 现取，不抄写）。

    **为什么不再扫 `enum(...)` 文本**：DDL 与 `er.md` 两侧的枚举解析已在共享层里，
    本文件再扫一遍就等于又开了一份实现 —— 两份实现漂移时，正是"两个一致性检查互相
    矛盾"的那类故障（Task 3.6b 的返工对象）。
    """
    collected: dict[str, tuple[str, ...]] = {}
    for table, spec in tables.items():
        for column in spec.columns:
            if column.enum_values is not None:
                collected[f"{table}.{column.name}"] = column.enum_values
    return collected


def resolve_yaml_path(document: Any, keys: tuple[str, ...]) -> Any:
    """按 key 路径取值；路径不存在时抛出带完整路径的可读错误。"""
    node = document
    walked: list[str] = []
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            raise AssertionError(
                f"openapi.yaml 中找不到路径 {'/'.join(keys)}"
                f"（在 {'/'.join(walked) or '<root>'} 处断掉）"
            )
        node = node[key]
        walked.append(key)
    return node


def load_openapi() -> Mapping[str, Any]:
    document = yaml.safe_load(OPENAPI_YAML.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise AssertionError(f"{OPENAPI_YAML.name} 顶层不是映射，实际为 {type(document).__name__}")
    return document


def format_differences(title: str, differences: Iterable[str]) -> str:
    """差异清单：MUST 逐项可读（哪张表 / 哪个字段 / 期望 vs 实际），不是一句 assert False。"""
    items = list(differences)
    listed = "\n".join(f"  - {item}" for item in items)
    return f"{title}（{len(items)} 处差异）：\n{listed}"


# ---------------------------------------------------------------------------
# 断言 1：逐列比对（表集合 / 列名序列 / 类型 / 可空性 / 默认值）
# ---------------------------------------------------------------------------
def test_er_md_parses_all_nine_tables() -> None:
    """非空下限 + 表集合：9 张表必须都解析出来，否则下面的比对会静默缩水。"""
    er_tables = load_er_tables()
    assert len(er_tables) >= MIN_ER_TABLES, (
        f"er.md 只解析到 {len(er_tables)} 张表（下限 {MIN_ER_TABLES}）：{'/'.join(er_tables)}"
    )
    er_only = sorted(set(er_tables) - set(ALL_TABLES))
    ddl_only = sorted(set(ALL_TABLES) - set(er_tables))
    assert set(er_tables) == set(ALL_TABLES), (
        f"er.md §6 的表集合与 DDL 逻辑表集合不一致：仅 er.md 有 {er_only}，仅 DDL 有 {ddl_only}"
    )


def test_ddl_directory_matches_brief_manifest() -> None:
    """DDL 目录的文件清单必须与 brief 的 Files 表一致（一个不多一个不少）。

    `ALL_TABLES` 是**本文件按 brief 手写的期望清单**，MUST NOT 改成从
    `repository/sharding.py` 取：那样断言会退化成"实现与自己比"，
    新建 DDL 文件却忘了登记这种事就再也抓不到了。
    """
    expected = sorted(["00_create_database.sql", *ALL_TABLES.values()])
    actual = sorted(path.name for path in DDL_DIR.glob("*.sql"))
    assert actual == expected, (
        f"deploy/sql/ddl 文件清单与工单不一致：期望 {expected}，实际 {actual}"
    )


def test_ddl_column_order_and_types_match_er() -> None:
    """逐列比对：每张表的列名序列、类型、可空性都必须与 er.md §6 完全相同。

    比对走共享层的 `schema.diff`（**MUST NOT** 在本文件再写一份逐列比对）：
    它同时覆盖表集合 / 列集合 / 列顺序 / 类型 / 可空性 / 枚举值六类差异，
    且给出"哪张表哪个字段、左 vs 右"的人可读清单。
    """
    er_tables = load_er_tables()
    ddl_tables = load_ddl_tables()
    assert set(ddl_tables) == set(er_tables), (
        f"表集合不一致：仅 DDL 有 {sorted(set(ddl_tables) - set(er_tables))}，"
        f"仅 er.md 有 {sorted(set(er_tables) - set(ddl_tables))}"
    )
    differences = schema.diff(er_tables, ddl_tables)
    assert not differences, format_differences(
        "DDL 与 er.md §6 数据字典逐列比对失败（左 er.md / 右 DDL）", differences
    )


def test_ddl_enums_match_er_enums() -> None:
    """枚举列的值集合与顺序也必须与 er.md 一致（顺序影响默认值语义与可读性）。"""
    er_enums = collect_enums(load_er_tables())
    ddl_enums = collect_enums(load_ddl_tables())
    differences: list[str] = []
    for key in sorted(set(er_enums) | set(ddl_enums)):
        if key not in ddl_enums:
            differences.append(f"{key} 在 er.md 中是枚举，DDL 中不是：期望 {er_enums[key]}")
        elif key not in er_enums:
            differences.append(f"{key} 在 DDL 中是枚举，er.md 中不是：实际 {ddl_enums[key]}")
        elif er_enums[key] != ddl_enums[key]:
            differences.append(f"{key} 枚举值不一致：期望 {er_enums[key]}，实际 {ddl_enums[key]}")
    assert not differences, format_differences("DDL 与 er.md 枚举值比对失败", differences)


def test_enum_column_count_is_not_vacuous() -> None:
    """非空下限：枚举列数量塌掉（正则失效）时必须报警，而不是静默全绿。"""
    ddl_enums = collect_enums(load_ddl_tables())
    er_enums = collect_enums(load_er_tables())
    assert len(ddl_enums) >= MIN_ENUM_COLUMNS, (
        f"只在 DDL 里解出 {len(ddl_enums)} 个枚举列（下限 {MIN_ENUM_COLUMNS}）：{sorted(ddl_enums)}"
    )
    assert set(ddl_enums) == set(er_enums), (
        f"er.md 与 DDL 的枚举列集合不一致：{sorted(set(ddl_enums) ^ set(er_enums))}"
    )


def test_timestamp_defaults_match_er_notes() -> None:
    """时间列默认值口径：`CURRENT_TIMESTAMP(3)` 只能出现在 er.md「默认」列写了它的列上。

    期望值现解自 er.md 的「默认」列（本文件唯一的局部解析，见 `parse_er_defaults`），
    故「顺手给 reviewed_at 加个默认值」这类偏离（会把"忘记写时间"变成静默假数据）
    会被本用例拦住。
    """
    er_tables = load_er_tables()
    er_defaults = parse_er_defaults()
    expected_with_ts = {
        f"{table}.{column}"
        for table, columns in er_defaults.items()
        for column, default in columns.items()
        if default.upper().startswith("CURRENT_TIMESTAMP")
    }
    assert len(expected_with_ts) >= MIN_TIMESTAMP_DEFAULT_COLUMNS, (
        f"er.md 只解析出 {len(expected_with_ts)} 个带 CURRENT_TIMESTAMP 默认值的列"
        f"（下限 {MIN_TIMESTAMP_DEFAULT_COLUMNS}）：{sorted(expected_with_ts)}"
    )
    mismatches: list[str] = []
    for table in sorted(ALL_TABLES):
        block = first_create_table_block(table)
        by_name = collect_column_clauses(block)
        for column in er_tables[table].columns:
            clause = by_name.get(column.name)
            if clause is None:
                mismatches.append(f"{table}.{column.name} 在 CREATE TABLE 中找不到")
                continue
            if column.type != "datetime(3)":
                continue
            has_ts_default = "DEFAULT CURRENT_TIMESTAMP(3)" in clause.upper()
            want_ts_default = f"{table}.{column.name}" in expected_with_ts
            if has_ts_default != want_ts_default:
                mismatches.append(
                    f"{table}.{column.name} 时间列默认值口径不一致：er.md 默认列为 "
                    f"{er_defaults[table][column.name]!r}，DDL"
                    f" {'有' if has_ts_default else '没有'} "
                    f"DEFAULT CURRENT_TIMESTAMP(3)"
                )
    assert not mismatches, format_differences("时间列默认值口径比对失败", mismatches)


# ---------------------------------------------------------------------------
# 断言 2：枚举 <-> openapi.yaml 一一对应
# ---------------------------------------------------------------------------
def test_openapi_has_enough_enum_lines() -> None:
    """非空下限：openapi 的内联 enum 行数塌掉时报警（防"解析成功但什么都没读到"）。"""
    count = len(
        re.findall(r"^\s*enum:\s*\[", OPENAPI_YAML.read_text(encoding="utf-8"), re.MULTILINE)
    )
    assert count >= MIN_OPENAPI_ENUM_LINES, (
        f"openapi.yaml 只找到 {count} 行内联 enum（下限 {MIN_OPENAPI_ENUM_LINES}）"
    )


def test_enum_wiring_is_self_consistent() -> None:
    """接线自检：DDL_ENUM_TO_OPENAPI 的每个路径都必须有定档抽查值，反之亦然。"""
    mapped = set(DDL_ENUM_TO_OPENAPI.values())
    spot_checked = set(OPENAPI_ENUM_SPOT_CHECK)
    assert mapped == spot_checked, (
        f"枚举接线不自洽：缺定档值的路径 {sorted(mapped - spot_checked)}，"
        f"多余的定档路径 {sorted(spot_checked - mapped)}"
    )


def test_every_er_enum_column_is_wired_to_openapi() -> None:
    """反向覆盖：er.md 里的每个枚举列都必须出现在接线表里，否则新枚举列会漏测 openapi。"""
    er_enums = set(collect_enums(load_er_tables()))
    wired = set(DDL_ENUM_TO_OPENAPI)
    assert er_enums == wired, (
        f"枚举接线表与 er.md 枚举列不一致：未接线的 {sorted(er_enums - wired)}，"
        f"已失效的 {sorted(wired - er_enums)}"
    )


@pytest.mark.parametrize("ddl_column", sorted(DDL_ENUM_TO_OPENAPI))
def test_ddl_enum_matches_openapi_enum(ddl_column: str) -> None:
    """每个 DDL 枚举列都必须与 openapi 对应 enum 双向（集合 + 顺序）相等。"""
    path = DDL_ENUM_TO_OPENAPI[ddl_column]
    raw = resolve_yaml_path(load_openapi(), path)
    assert isinstance(raw, list), (
        f"openapi 路径 {'/'.join(path)} 不是列表，实际 {type(raw).__name__}"
    )
    openapi_values = tuple(str(value) for value in raw)
    ddl_values = collect_enums(load_ddl_tables()).get(ddl_column)
    assert ddl_values is not None, (
        f"DDL 中找不到枚举列 {ddl_column}（接线表 DDL_ENUM_TO_OPENAPI 已过期？）"
    )
    assert set(ddl_values) == set(openapi_values), (
        f"{ddl_column} 与 openapi {'/'.join(path)} 枚举不一致：\n"
        f"      DDL      {list(ddl_values)}\n      openapi  {list(openapi_values)}"
    )
    assert ddl_values == openapi_values, (
        f"{ddl_column} 与 openapi {'/'.join(path)} 枚举顺序不一致：\n"
        f"      DDL      {list(ddl_values)}\n      openapi  {list(openapi_values)}"
    )


@pytest.mark.parametrize(
    "path", sorted(OPENAPI_ENUM_SPOT_CHECK), ids=lambda item: ".".join(item[-3:])
)
def test_openapi_enum_values_match_spot_check(path: tuple[str, ...]) -> None:
    """定档抽查：openapi 的枚举值必须与工单定档值逐字一致（抓"两侧一起改错"）。"""
    raw = resolve_yaml_path(load_openapi(), path)
    assert isinstance(raw, list), f"openapi 路径 {'/'.join(path)} 不是列表"
    assert set(raw) == OPENAPI_ENUM_SPOT_CHECK[path], (
        f"openapi {'/'.join(path)} 的值集合与定档值不一致：实际 {sorted(map(str, raw))}，"
        f"期望 {sorted(OPENAPI_ENUM_SPOT_CHECK[path])}"
    )


# ---------------------------------------------------------------------------
# 断言 3：占位符协议
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", sorted(SHARDED_TABLES))
def test_template_contains_both_placeholders(table: str) -> None:
    """三个模板都必须同时含 {table} 与 {month}：本表名 + 同月兄弟表名。"""
    source = read_ddl(table)
    assert "{table}" in source, f"{ALL_TABLES[table]} 缺少 {{table}} 占位符"
    assert "{month}" in source, f"{ALL_TABLES[table]} 缺少 {{month}} 占位符"


def test_correction_template_has_same_month_physical_foreign_key() -> None:
    """12_ocr_correction 必须含指向同月 `ocr_result_{month}` 的物理外键，且显式 RESTRICT。

    **约束名 MUST 带 `{month}`**（2026-09-16 修正）：MySQL 的外键约束名在 **schema 内唯一**，
    写死 `fk_ocr_correction_task` 会让模板套到第二个月时撞名报 1826。详见模板顶部注释。
    """
    source = read_ddl("ocr_correction")
    assert re.search(
        r"CONSTRAINT\s+`fk_ocr_correction_task_\{month\}`\s+FOREIGN\s+KEY", source, re.IGNORECASE
    ), (
        "ocr_correction 模板缺少 fk_ocr_correction_task_{month} 物理外键"
        "（约束名必须带月份，否则第二个月撞名）"
    )
    assert re.search(
        r"REFERENCES\s+`ocr_result_\{month\}`\s*\(`task_id`\)", source, re.IGNORECASE
    ), "ocr_correction 模板的外键必须 REFERENCES `ocr_result_{month}` (`task_id`)（同月同分片）"
    assert re.search(r"ON\s+DELETE\s+RESTRICT\s+ON\s+UPDATE\s+RESTRICT", source, re.IGNORECASE), (
        "外键必须显式写出 ON DELETE RESTRICT ON UPDATE RESTRICT"
    )


def test_ddl_constraint_names_all_carry_month() -> None:
    """防回归：**三个模板里所有 `CONSTRAINT` 名都 MUST 含 `{month}`**。

    这条是 FIX-4 的"守门人"——将来谁再往模板里写死一个约束名（无论是本模板还是新加的），
    套到第二个月就会在真实 MySQL 上炸 1826，而离线文本用例默认发现不了。故此处直接扫模板源文件。
    """
    offenders: list[str] = []
    for table in sorted(SHARDED_TABLES):
        source = schema.strip_sql_comments(read_ddl(table))
        for name in re.findall(r"CONSTRAINT\s+`([^`]+)`", source, re.IGNORECASE):
            if "{month}" not in name:
                offenders.append(f"{ALL_TABLES[table]} 的约束 {name!r}")
    assert not offenders, format_differences(
        "模板里的 CONSTRAINT 名必须带 {month}（MySQL 约束名 schema 内唯一，写死会跨月撞名）",
        offenders,
    )


@pytest.mark.parametrize("table", sorted(SHARDED_TABLES))
def test_rendered_template_has_no_placeholder_left(table: str) -> None:
    """渲染一次即成品：**代码骨架** MUST NOT 再含 `{`（残留占位符 = 不可执行 SQL）。

    **渲染与"骨架"口径一律走共享层**：`sharding.render_shard_template`（生产路径上
    `scripts/apply_ddl.py` 用的就是它）与 `sharding.sql_skeleton`（剥 `--` 行注释
    并把 `'...'` 字面量的内容掏空）。本文件 MUST NOT 再写一份渲染或骨架函数 ——
    那样测的就不是真正会被执行的渲染了。

    **为什么只看骨架**：模板里的花括号示例是**文档**，不是占位符 —— 例如 `model_meta`
    的 ``COMMENT '...：{channel, provider, modelVersion, ...}'``、`task_id` 的
    ``COMMENT '... GET /aicore/tasks/{taskId}'``，以及 `fields_json` 的
    ``COMMENT '... OcrField = {fieldName, value（脱敏）, confidence（0~1）}'``。
    这些串在 MySQL 里是**数据**，永远不会被当 SQL 解析，故对"可执行骨架"发问前先把它们掏空。
    **MUST NOT** 反过来把注释里的示例花括号删掉 —— 为了迁就一条断言而改文档是本末倒置。
    """
    source = read_ddl(table)
    rendered = sharding.render_shard_template(table, RENDER_MONTH)
    skeleton = sharding.sql_skeleton(rendered)
    leftovers = sorted(set(re.findall(r"\{[^}]*\}", skeleton)))
    assert not leftovers, f"{ALL_TABLES[table]} 渲染后代码骨架中仍残留占位符 {leftovers}"
    assert "{" not in skeleton, f"{ALL_TABLES[table]} 渲染后代码骨架中仍含 '{{' 字符，渲染不完整"
    # 反向自检：**占位符的账必须算平**。
    #
    # 首轮这里写的是一条恒假断言（`set(rendered_tokens) == set(source_tokens)`）：
    # `{table}` / `{month}` 渲染后本就该**消失**，源里有、渲染后没有 —— 相等永远不成立，
    # 三个模板必然全红。而正确的反向自检不是"集合相等"，是"**差额恰好等于被替换掉的占位符数**"：
    #   源里花括号 token 总数 − 渲染后骨架里花括号 token 总数
    #     == 源里 `{table}` 出现次数 + `{month}` 出现次数
    # 算不平就说明发生了别的事（渲染函数多替换/少替换、或注释被误删）——
    # 这正是"上面的断言看着严、其实是空的"的反面证据。
    source_tokens = re.findall(r"\{[^}]*\}", source)
    rendered_tokens = re.findall(r"\{[^}]*\}", rendered)
    table_hits = source.count("{table}")
    month_hits = source.count("{month}")
    substituted = table_hits + month_hits
    delta = len(source_tokens) - len(rendered_tokens)
    assert delta == substituted, (
        f"{ALL_TABLES[table]} 渲染的占位符账算不平：源 {len(source_tokens)} 个花括号 token 减 "
        f"渲染后 {len(rendered_tokens)} 个 = {delta}，"
        f"但 table 占位符 {table_hits} 次 + month 占位符 {month_hits} 次 = {substituted}"
        f"（差额不符说明渲染函数替换了不该替换的东西，或改动了注释）"
    )
    # 且渲染只允许动 `{table}` / `{month}`：源里除了这两个占位符之外的花括号示例，
    # 渲染后 MUST 逐个还在（注释是文档，MUST NOT 为迁就断言而改）。
    extra_examples = {token for token in source_tokens if token not in {"{table}", "{month}"}}
    still_there = set(rendered_tokens)
    missing_examples = sorted(extra_examples - still_there)
    assert not missing_examples, (
        f"{ALL_TABLES[table]} 渲染把注释里的示例花括号弄丢了 {missing_examples}："
        f"注释是文档，MUST NOT 为迁就断言而改"
    )


def test_sharded_templates_are_not_executable_verbatim() -> None:
    """反向保证：模板本身**不可执行**（含 `{`），故必须留在 .template.sql 命名下。"""
    for table in SHARDED_TABLES:
        assert "{" in read_ddl(table), f"{ALL_TABLES[table]} 不含占位符：分片表模板退化成了固定表名"
        assert ALL_TABLES[table].endswith(".template.sql"), (
            f"{ALL_TABLES[table]} 含占位符却不是 .template.sql 命名，可能被建表流程当普通 DDL 执行"
        )


def test_ddl_does_not_switch_database() -> None:
    """DDL 内 MUST NOT 写 USE：目标库由执行方以 `mysql -D <db>` 指定。"""
    for path in sorted(DDL_DIR.glob("*.sql")):
        text = schema.strip_sql_comments(path.read_text(encoding="utf-8"))
        assert not re.search(r"^\s*USE\s+", text, re.MULTILINE | re.IGNORECASE), (
            f"{path.name} 出现 USE 语句：库必须由执行方指定"
        )


# ---------------------------------------------------------------------------
# 断言 4：幂等性
# ---------------------------------------------------------------------------
def test_every_create_table_is_idempotent() -> None:
    """每个 DDL 文件的每张表都是 `CREATE TABLE IF NOT EXISTS`（复跑零错误的前提）。"""
    for path in sorted(DDL_DIR.glob("*.sql")):
        text = schema.strip_sql_comments(path.read_text(encoding="utf-8"))
        assert not re.findall(r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", text, re.IGNORECASE), (
            f"{path.name} 存在非幂等的 CREATE TABLE（缺 IF NOT EXISTS）"
        )
        guarded = len(re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", text, re.IGNORECASE))
        if path.name == "00_create_database.sql":
            assert guarded == 0, "建库脚本不应包含 CREATE TABLE"
        else:
            assert guarded == 1, f"{path.name} 期望恰好 1 张表，实际 {guarded}"


def test_create_database_is_idempotent() -> None:
    """建库脚本两个库都用 `CREATE DATABASE IF NOT EXISTS`。"""
    text = schema.strip_sql_comments(
        (DDL_DIR / "00_create_database.sql").read_text(encoding="utf-8")
    )
    assert not re.search(r"CREATE\s+DATABASE\s+(?!IF\s+NOT\s+EXISTS)", text, re.IGNORECASE), (
        "00_create_database.sql 存在非幂等的 CREATE DATABASE"
    )
    databases = re.findall(
        r"CREATE\s+DATABASE\s+IF\s+NOT\s+EXISTS\s+`([^`]+)`", text, re.IGNORECASE
    )
    assert databases == ["aicore", "aicore_test"], (
        f"建库清单应为 aicore + aicore_test，实际 {databases}"
    )


def test_ddl_declares_all_nine_tables() -> None:
    """9 张逻辑表一张不少：3 张分片表 + 6 张非分片表。"""
    ddl_tables = load_ddl_tables()
    assert len(ddl_tables) == 9, f"逻辑表应为 9 张，实际 {len(ddl_tables)}"
    assert set(ddl_tables) == set(ALL_TABLES), sorted(ddl_tables)


# ---------------------------------------------------------------------------
# 断言 5：通用 DDL 约定
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_common_ddl_conventions(table: str) -> None:
    """每张表都写全 ENGINE / 字符集 / 排序规则；不出现 ON UPDATE CURRENT_TIMESTAMP。"""
    flat = re.sub(r"\s+", " ", first_create_table_block(table))
    assert "ENGINE=InnoDB" in flat, f"{table} 的 CREATE TABLE 未写 ENGINE=InnoDB"
    assert "utf8mb4" in flat, f"{table} 的 CREATE TABLE 未写 utf8mb4 字符集"
    assert "COLLATE=utf8mb4_0900_ai_ci" in flat, f"{table} 未写 COLLATE=utf8mb4_0900_ai_ci"
    assert "ON UPDATE CURRENT_TIMESTAMP" not in flat.upper(), (
        f"{table} 出现 ON UPDATE CURRENT_TIMESTAMP：er.md 没有 updated_at 列，这是凭空多出的行为"
    )


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_every_column_and_table_has_chinese_comment(table: str) -> None:
    """中文注释强制：表有 COMMENT='...中文...'，且**每列**都有中文 COMMENT（漏注释即报红）。

    **本用例的正则口径（首轮写错过，特此登记）**：`COMMENT\\s+'[^']*'` + CJK 这类写法
    把中文字符类放在了**收尾引号之后** —— 那要求注释后面紧跟一个汉字，而注释后面是
    换行/逗号/行尾，于是**每一列都判成"缺少中文注释"**（9 张表全红）。
    正确口径是中文必须落在**引号内部**：`COMMENT\\s+'(?:[^'\\\\]|\\\\.)*'` 之后再要求
    引号内出现过 CJK。故此处统一用 `COLUMN_CN_COMMENT_RE` / `TABLE_CN_COMMENT_RE`
    （它们把 `[\\u4e00-\\u9fff]` 写在字符类里，而不是写在引号外）。
    """
    block = first_create_table_block(table)
    clauses = split_column_clauses(block)
    by_name = collect_column_clauses(block)
    assert len(by_name) == len(clauses), (
        f"{table} 的建表项切分自检失败：切出 {len(clauses)} 项但只认出 {len(by_name)} 个列名"
        f"（漏认的项会让列注释断言查错对象而静默变绿）"
    )
    ddl_table = load_ddl_tables()[table]
    comment_count = len(COMMENT_COUNT_RE.findall(block))
    assert comment_count >= len(ddl_table.columns) + 1, (
        f"{table} 有 {len(ddl_table.columns)} 列但只有 {comment_count} 处 COMMENT："
        f"每列一条 + 表一条，至少 {len(ddl_table.columns) + 1} 处"
    )
    assert TABLE_CN_COMMENT_RE.search(block), f"{table} 缺少中文表注释"
    for column in ddl_table.columns:
        clause = by_name.get(column.name)
        assert clause is not None, f"{table}.{column.name} 在 CREATE TABLE 中找不到"
        # 两步断言、分开报错：先证"有 COMMENT 子句"，再证"该子句的中文在引号内"。
        # 合成一条会让"注释是英文"与"根本没写注释"报同一个错，排查时看不出区别。
        assert COLUMN_COMMENT_RE.search(clause), f"{table}.{column.name} 没有 COMMENT 子句"
        assert COLUMN_CN_COMMENT_RE.search(clause), (
            f"{table}.{column.name} 缺少中文列注释：{clause!r}"
        )


def test_ddl_declares_physical_foreign_keys_with_restrict() -> None:
    """4 条物理外键逐条核对：名字、引用目标、显式 RESTRICT（工单要求显式写出）。

    期望值用**渲染后**的文本比对：`ocr_correction` 的约束名与引用目标都带 `{month}`，
    渲染成 `RENDER_MONTH` 后才是真实 MySQL 里看得到的名字（`fk_ocr_correction_task_202601`）。
    渲染一律调共享层（`sharding.render_shard_template`），本文件 MUST NOT 另写一份。
    """
    expected = {
        "ocr_correction": [
            (f"fk_ocr_correction_task_{RENDER_MONTH}", f"ocr_result_{RENDER_MONTH}", "task_id"),
        ],
        "vision_marker": [("fk_vision_marker_review", "vision_review", "review_id")],
        "review_verdict": [("fk_review_verdict_review", "vision_review", "review_id")],
        "kitchen_anomaly": [("fk_kitchen_anomaly_review", "vision_review", "review_id")],
    }
    differences: list[str] = []
    for table, keys in expected.items():
        if table in SHARDED_TABLES:
            raw = sharding.render_shard_template(table, RENDER_MONTH)
        else:
            raw = first_create_table_block(table)
        block = re.sub(r"\s+", " ", raw)
        for name, target, column in keys:
            pattern = (
                r"CONSTRAINT `"
                + re.escape(name)
                + r"` FOREIGN KEY \(`"
                + re.escape(column)
                + r"`\) REFERENCES `"
                + re.escape(target)
                + r"` \(`"
                + re.escape(column)
                + r"`\) ON DELETE RESTRICT ON UPDATE RESTRICT"
            )
            if not re.search(pattern, block, re.IGNORECASE):
                differences.append(
                    f"表 {table} 的外键 {name} 不符合期望：{target}({column}) + 显式 RESTRICT"
                )
    # 反向：未列出的表不得出现物理外键
    # （ai_task / ocr_result / vision_review / risk_predict / vision_qa_log）
    for table in sorted(set(ALL_TABLES) - set(expected)):
        block = re.sub(r"\s+", " ", first_create_table_block(table))
        if re.search(r"FOREIGN KEY", block, re.IGNORECASE):
            differences.append(f"表 {table} 不该有物理外键，却出现了 FOREIGN KEY")
    assert not differences, format_differences("物理外键比对失败", differences)
