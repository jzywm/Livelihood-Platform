"""结构比对的数据模型与**四源解析归一化层**（Task 3.6 的共享底座）。

## 为什么要有这一层（而不是各写各的解析器）

Task 3.1 已在 `tests/repository/test_ddl_matches_er.py` 里写过 DDL 与 `er.md` 的解析；
Task 3.6 若再写一份，同一件事就有两份实现，而它们的漂移表现是：
**`test_ddl_matches_er.py` 绿、`compare_schema.py` 红（或反之）**——
两个都叫"一致性检查"的工具互相矛盾，是最坏的一类故障（没人知道该信谁）。
故本模块是**解析与归一的唯一实现处**，测试与脚本都 import 它。

## 四个来源

| 源 | 入口 | 是否需要数据库 |
|---|---|---|
| `deploy/sql/ddl/**`（**权威定义**，spec §5.5） | `parse_ddl` / `parse_ddl_directory` | 否 |
| `docs/er.md` §6 数据字典 | `parse_er_md` | 否 |
| SQLAlchemy 元数据（`repository/models.py`） | `from_metadata` | 否 |
| `information_schema` | `from_information_schema` | 是 |

## 类型归一化（MUST 双向都做）

四个源的类型文本长得不一样，同一列可能写成 `varchar(32)` / `VARCHAR(32)` / `decimal(3, 2)` /
`int UNSIGNED`；`information_schema` 更碎（类型名与长度/精度/标度分列）。
故一律压到同一个规范形：**小写、去多余空白、括号内的逗号不留空格**
（`decimal(3, 2)` → `decimal(3,2)`）。

**`from_metadata` MUST 按 MySQL 方言编译类型，不能只读 `str(column.type)`**（Task 3.2 的实测结论）：
`int unsigned` 与 `datetime(3)` 在模型里是用 `with_variant(..., "mysql")` 表达的——
通用 `Integer` 在 SQLAlchemy 2.0.54 上不接收 `unsigned` 参数
（`TypeError: Integer() takes no arguments`），而通用 `DateTime()` 在 MySQL 上渲染成
`DATETIME`（**丢毫秒**）。
实测对照：
    progress    generic=INTEGER    mysql=INTEGER UNSIGNED
    created_at  generic=DATETIME   mysql=DATETIME(3)
只读 `str(column.type)` 会得到 `INTEGER` / `DATETIME`，与 DDL 的 `int unsigned` / `datetime(3)`
**假性不等**——而假性不等的下一步往往是"有人把这条检查关掉"。故此处走
`column.type.compile(dialect=mysql.dialect())`。

## 本模块 MUST NOT 依赖 `aicore.core.*` 与任何数据库连接

它是纯结构层：只 import stdlib + `sqlalchemy` + 相邻的 `repository.sharding`
（后者提供模板渲染，避免第二份渲染实现）。`core/` 的配置/日志不该绑进"读文本比结构"这件事。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import MetaData
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Connection
from sqlalchemy.sql import text as sql_text

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 服务根 = 本文件的上三级（src/aicore/repository/ -> services/aicore/）
SERVICE_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DDL_DIR: Final[Path] = SERVICE_ROOT / "deploy" / "sql" / "ddl"
ER_MD: Final[Path] = SERVICE_ROOT / "docs" / "er.md"

#: 分片表物理名后缀：`ai_task_202601` -> `ai_task`。
_SHARD_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(r"_\d{6}$")

#: 数据字典表格的表头（**只有这一行**能判定"本节是不是数据字典"）。
ER_HEADER_CELLS: Final[tuple[str, ...]] = ("字段", "类型", "空", "键", "默认", "说明")

#: `### 6.x` 形式的章节标题（**只认编号前缀**，不要求后面是 ASCII 表名——
#: §6.10「辅助结构（Redis / MQ / OSS）」以中文开头，靠 ASCII 前缀区分正是首轮踩过的坑）。
_ER_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^###\s+6\.\d+")
#: 从标题里取逻辑表名（`### 6.1 ai_task（…）` -> `ai_task`）。
_ER_TABLE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^###\s+6\.\d+\s+([A-Za-z_]\w*)")

#: `CREATE TABLE IF NOT EXISTS \`name\` ( ... ) ENGINE=`
_CREATE_TABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`(?P<name>[^`]+)`\s*\((?P<body>.*?)\)\s*ENGINE\s*=",
    re.IGNORECASE | re.DOTALL,
)
#: 列定义开头：`` `col` 类型... ``（索引/约束项不以反引号列名开头）。
_COLUMN_ITEM_RE: Final[re.Pattern[str]] = re.compile(
    r"^`(?P<name>[^`]+)`\s+(?P<rest>.+)$", re.DOTALL
)
#: 建表正文里的项分类前缀（这些不是列）。
_NON_COLUMN_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN|CHECK)\b", re.IGNORECASE
)
#: 类型名 [+ 括号参数] [+ unsigned]；用 `(?=\s|$)` 防止 `varchar2(32)` 被前缀匹配成 `varchar`。
_TYPE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<type>[a-z]+(?:\s*\([^)]*\))?(?:\s+unsigned)?)(?=\s|$)", re.IGNORECASE
)
_ENUM_RE: Final[re.Pattern[str]] = re.compile(
    r"^enum\((?P<values>.*)\)$", re.IGNORECASE | re.DOTALL
)


class SchemaParseError(Exception):
    """某个来源的结构文本与预期格式不符（**不静默跳过**：解析塌了必须报警）。"""


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """一列的可比对口径：四个来源都表达得了的维度。"""

    name: str
    type: str
    nullable: bool
    enum_values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class TableSpec:
    """一张表的可比对口径（表名一律是**逻辑名**，分片表的月份后缀已归一掉）。"""

    name: str
    columns: tuple[ColumnSpec, ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


def normalize_table_name(physical: str) -> str:
    """物理分片表名 -> 逻辑表名（`ai_task_202601` -> `ai_task`；非分片名原样返回）。"""
    return _SHARD_SUFFIX_RE.sub("", physical)


#: 同义类型归一：MySQL 里这些写法在 `information_schema` 里就是同一个东西。
#:
#: - `numeric` == `decimal`（MySQL 手册明示 NUMERIC 是 DECIMAL 的同义词）；
#: - `bool` / `boolean` == `tinyint(1)`（DDL 写 `tinyint(1)`，SQLAlchemy 编译成 `BOOL`）；
#: - `integer` == `int`（`markers_count` 实测：DDL 写 `int unsigned`，
#:   SQLAlchemy 编译成 `INTEGER UNSIGNED`；不归一就会白留一处差异）。
#: 不做这层归一的后果是**假性不等**（实测 15 处差异里 4 处 `decimal`/`numeric`、
#: 5 处 `integer`/`int`…），而假性不等的下一步往往是"有人把这条检查关掉"。
#:
#: 键是**基名**（不含参数）：`numeric(3,2)` 要归成 `decimal(3,2)`，
#: 故实现是"取基名查表、再把参数拼回去"，而不是对整串做精确匹配
#: （首版写成整串匹配，实测 `numeric(3,2)` 直接落空，白留 6 处差异）。
_TYPE_SYNONYMS: Final[dict[str, str]] = {
    "numeric": "decimal",
    "bool": "tinyint(1)",
    "boolean": "tinyint(1)",
    "integer": "int",
    "double precision": "double",
}

#: 基名 = 开头的连续字母；**其余部分（参数、unsigned 等后缀）一律原样拼回**。
#:
#: 首版写成 `[a-z]+(?:\s+[a-z]+)?`，它会把 `integer unsigned` 整体吃进基名，
#: 于是查表落空、`unsigned` 还被丢掉——实测就卡在这 1 处差异上（`integer unsigned`
#: 应归成 `int unsigned`，却输出 `int`）。
_TYPE_BASE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<base>[a-z]+)(?P<rest>[\s\S]*)$")


def normalize_type(raw: str) -> str:
    """类型文本归一：**只小写类型名，括号内的参数保原样**，并归一同义名。

    ## 为什么不能整体 `.lower()`（实测踩过，是 Task 3.1 同一个坑的复现）

    `er.md` 与 DDL 的类型列写的是 `enum('VALID','EXPIRING',...)` —— 括号里是**枚举值**，
    它们是 SQL 字符串字面量，**大小写敏感**。整体小写会得到
    `enum('valid','expiring',...)`，与模型侧（SQLAlchemy 的 `Enum` 保留原值）必然不等，
    实测表现为 6 张表 15 处差异里的一半。**故括号外小写、括号内原样。**

    ## 实现为什么是显式扫描而不是正则

    枚举值里可能出现 `)`（如 `enum('A)','B')`），正则 `^([^(]*)[(](.*)[)]$` 会在错的括号处断句。
    扫描按"引号优先、深度计数"处理，天然免疫。

    ## 同义名归一

    见 `_TYPE_SYNONYMS`：**先拆基名查表、再把剩余部分拼回**，
    这样 `numeric(3,2)` 与 `integer unsigned` 都能归到 `decimal(3,2)` 与 `int unsigned`。
    """
    collapsed = re.sub(r"\s+", " ", raw.strip())
    out: list[str] = []
    depth = 0
    quote: str | None = None
    for char in collapsed:
        if quote is not None:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            out.append(char)
            continue
        if char == "(":
            depth += 1
            out.append(char)
            continue
        if char == ")":
            depth = max(depth - 1, 0)
            out.append(char)
            continue
        out.append(char.lower() if depth == 0 else char)
    normalized = "".join(out)
    # 括号内逗号后的空格：`decimal(5, 2)` -> `decimal(5,2)`。
    normalized = re.sub(r",\s+", ",", normalized)
    # 同义名：拆基名 -> 查表 -> 拼回剩余部分（`numeric(3,2)`.rest = `(3,2)`）。
    match = _TYPE_BASE_RE.match(normalized)
    if match is not None:
        base = match.group("base")
        synonym = _TYPE_SYNONYMS.get(base)
        if synonym is not None:
            return synonym + match.group("rest")
    return _TYPE_SYNONYMS.get(normalized, normalized)


def _split_top_level(body: str) -> list[str]:
    """按顶层逗号切分（跳过括号与引号内部）——列定义里本来就有逗号（`enum('A','B')`）。"""
    items: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote: str | None = None
    for char in body:
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            buffer.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(char)
    tail = "".join(buffer).strip()
    if tail:
        items.append(tail)
    return items


def _parse_enum_values(raw: str) -> tuple[str, ...]:
    """`'A','B'` -> `("A", "B")`（去引号，**保持大小写与顺序**——枚举值是字符串字面量）。"""
    return tuple(
        value.strip().strip("'").strip('"') for value in raw.split(",") if value.strip()
    )


def _column_from_clause(clause: str) -> ColumnSpec:
    match = _COLUMN_ITEM_RE.match(clause)
    if match is None:
        raise SchemaParseError(f"无法解析的建表项（既非索引也非反引号列定义）：{clause!r}")
    rest = match.group("rest").strip()
    type_match = _TYPE_RE.match(rest)
    if type_match is None:
        raise SchemaParseError(f"列 {match.group('name')} 的类型无法解析：{rest!r}")
    normalized = normalize_type(type_match.group("type"))
    enum_match = _ENUM_RE.match(normalized)
    return ColumnSpec(
        name=match.group("name"),
        type=normalized,
        nullable=re.search(r"\bNOT\s+NULL\b", rest, re.IGNORECASE) is None,
        enum_values=_parse_enum_values(enum_match.group("values")) if enum_match else None,
    )


# ---------------------------------------------------------------------------
# 源 1：deploy/sql/ddl/**
# ---------------------------------------------------------------------------


def strip_sql_comments(source: str) -> str:
    """去掉 `--` 行注释（注释里的示例 SQL 不是真实结构）。"""
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("--"))


def parse_ddl(text: str) -> dict[str, TableSpec]:
    """解析 DDL 文本里的全部 `CREATE TABLE`（**已是可执行 SQL，无需渲染**）。

    返回的键是**逻辑表名**（分片表的 `_YYYYMM` 后缀已归一）。
    """
    cleaned = strip_sql_comments(text)
    tables: dict[str, TableSpec] = {}
    for match in _CREATE_TABLE_RE.finditer(cleaned):
        logical = normalize_table_name(match.group("name"))
        columns: list[ColumnSpec] = []
        for item in _split_top_level(match.group("body")):
            if not item.strip() or _NON_COLUMN_PREFIX_RE.match(item.strip()):
                continue
            columns.append(_column_from_clause(item))
        if logical in tables:
            raise SchemaParseError(
                f"同一个 DDL 文本里出现两次逻辑表 {logical!r}："
                f"分片表模板 MUST 只含本表的 CREATE TABLE"
            )
        tables[logical] = TableSpec(name=logical, columns=tuple(columns))
    return tables


def parse_ddl_directory(ddl_dir: Path = DDL_DIR, *, month: str) -> dict[str, TableSpec]:
    """解析整个 DDL 目录。

    `month` 用来渲染三个 `.template.sql` 的 `{table}` / `{month}` 占位符
    ——**由调用方给，MUST NOT 取当前时间**：这套比对与"今天是几月"无关，
    取当前月会让结果随运行日期漂移。

    渲染 MUST 复用 `repository.sharding` 的实现（**MUST NOT 在本模块再写一份**）：
    两份渲染实现会漂移，而漂移的表现是"脚本建的表与运行期建的表不是同一个结构"。
    """
    from aicore.repository.sharding import SHARDED_TABLES, render_shard_template

    tables: dict[str, TableSpec] = {}
    for path in sorted(ddl_dir.glob("*.sql")):
        if path.name == "00_create_database.sql":
            continue  # 建库脚本不含 CREATE TABLE
        if path.name.endswith(".template.sql"):
            logical = path.name.split("_", 1)[1].removesuffix(".template.sql")
            if logical not in SHARDED_TABLES:
                raise SchemaParseError(f"{path.name} 是模板但不在分片表清单内：{logical!r}")
            source = render_shard_template(logical, month)
        else:
            source = path.read_text(encoding="utf-8")
        for name, spec in parse_ddl(source).items():
            if name in tables:
                raise SchemaParseError(f"{path.name} 与先前文件都定义了逻辑表 {name!r}")
            tables[name] = spec
    return tables


# ---------------------------------------------------------------------------
# 源 2：docs/er.md §6 数据字典
# ---------------------------------------------------------------------------


def _split_markdown_row(line: str) -> list[str]:
    placeholder = "\x00PIPE\x00"
    cells = line.replace(r"\|", placeholder).split("|")
    return [cell.strip().replace(placeholder, "|") for cell in cells]


def _strip_outer_empty(cells: list[str]) -> list[str]:
    return [
        cell
        for index, cell in enumerate(cells)
        if not (index in (0, len(cells) - 1) and cell == "")
    ]


def _is_separator_row(cells: Iterable[str]) -> bool:
    items = list(cells)
    return bool(items) and all(set(cell) <= set("-: ") and "-" in cell for cell in items)


def parse_er_md(text: str) -> dict[str, TableSpec]:
    """解析 `er.md` §6 的数据字典表格。

    **章节边界与表头判定解耦**：只认 6 列表头（`字段/类型/空/键/默认/说明`）决定
    "本节算不算数据字典"，不认标题文字——§6.10「辅助结构（Redis / MQ / OSS）」是 3 列表，
    靠标题区分会把它当成上一节的数据行（Task 3.1 首轮正是这么把 9 张表一起带崩的）。
    """
    lines = text.splitlines()
    total = len(lines)
    index = 0
    tables: dict[str, TableSpec] = {}
    while index < total:
        line = lines[index]
        index += 1
        if not _ER_HEADING_RE.match(line):
            continue
        while index < total and not lines[index].startswith("|"):
            index += 1
        rows: list[list[str]] = []
        while index < total and lines[index].startswith("|"):
            rows.append(_strip_outer_empty(_split_markdown_row(lines[index])))
            index += 1
        header = rows[0] if rows else []
        if tuple(header) != ER_HEADER_CELLS:
            continue  # 非数据字典口径（如 §6.10 辅助结构）-> 本节退出比对范围
        name_match = _ER_TABLE_NAME_RE.match(line)
        if name_match is None:
            raise SchemaParseError(f"无法从数据字典标题取表名：{line!r}")
        logical = name_match.group(1)
        columns: list[ColumnSpec] = []
        for cells in rows[1:]:
            if _is_separator_row(cells):
                continue
            if len(cells) < len(ER_HEADER_CELLS):
                raise SchemaParseError(
                    f"表 {logical} 的数据行列数不足 {len(ER_HEADER_CELLS)}：{' | '.join(cells)}"
                )
            field, raw_type, nullable = cells[0], cells[1], cells[2]
            if nullable not in {"YES", "NO"}:
                raise SchemaParseError(f"表 {logical} 的「空」列既非 YES 也非 NO：{cells}")
            normalized = normalize_type(raw_type)
            enum_match = _ENUM_RE.match(normalized)
            columns.append(
                ColumnSpec(
                    name=field,
                    type=normalized,
                    nullable=nullable == "YES",
                    enum_values=(
                        _parse_enum_values(enum_match.group("values")) if enum_match else None
                    ),
                )
            )
        tables[logical] = TableSpec(name=logical, columns=tuple(columns))
    return tables


# ---------------------------------------------------------------------------
# 源 3：SQLAlchemy 元数据
# ---------------------------------------------------------------------------


def from_metadata(metadata: MetaData) -> dict[str, TableSpec]:
    """从 `Base.metadata` 导出结构。

    类型 MUST 按 **MySQL 方言**编译（见模块 docstring 的实测对照），
    否则 `int unsigned` / `datetime(3)` 会以 `INTEGER` / `DATETIME` 出现而与 DDL 假性不等。
    """
    dialect = mysql.dialect()
    tables: dict[str, TableSpec] = {}
    for physical, table in metadata.tables.items():
        logical = normalize_table_name(physical)
        columns: list[ColumnSpec] = []
        for column in table.columns:
            compiled = str(column.type.compile(dialect=dialect))
            normalized = normalize_type(compiled)
            enum_values = _collect_metadata_enum_values(column.type)
            columns.append(
                ColumnSpec(
                    name=column.name,
                    type=normalized,
                    nullable=bool(column.nullable),
                    enum_values=enum_values,
                )
            )
        tables[logical] = TableSpec(name=logical, columns=tuple(columns))
    return tables


def _collect_metadata_enum_values(column_type: Any) -> tuple[str, ...] | None:
    """取枚举值。

    `Enum` 可能被包在 `with_variant` 里，故沿 `_variant_mapping` 与 `.impl` 往下找；
    找不到就返回 `None`（该列不是枚举）。
    """
    seen: set[int] = set()
    current = column_type
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        enums = getattr(current, "enums", None)
        if enums:
            return tuple(str(value) for value in enums)
        variants = getattr(current, "_variant_mapping", None)
        if variants:
            variant = next(iter(variants.values()), None) if variants else None
            if variant is not None and getattr(variant, "enums", None):
                return tuple(str(value) for value in variant.enums)
        current = getattr(current, "impl", None)
    return None


# ---------------------------------------------------------------------------
# 源 4：information_schema（需要数据库）
# ---------------------------------------------------------------------------

_INFORMATION_SCHEMA_SQL: Final[str] = """
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = :database
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""


def from_information_schema(conn: Connection, database: str) -> dict[str, TableSpec]:
    """从真实库读取结构。

    用 `COLUMN_TYPE`（而非 `DATA_TYPE`）作为类型来源：它带长度/精度/枚举值
    （`varchar(32)` / `decimal(3,2)` / `enum('A','B')`），与 DDL 的写法同构，
    比 `DATA_TYPE` + 三个长度列拼装更少歧义。
    """
    rows = conn.execute(sql_text(_INFORMATION_SCHEMA_SQL), {"database": database}).all()
    grouped: dict[str, list[ColumnSpec]] = {}
    for table_name, column_name, column_type, is_nullable in rows:
        logical = normalize_table_name(str(table_name))
        normalized = normalize_type(str(column_type))
        enum_match = _ENUM_RE.match(normalized)
        grouped.setdefault(logical, []).append(
            ColumnSpec(
                name=str(column_name),
                type=normalized,
                nullable=str(is_nullable).upper() == "YES",
                enum_values=(
                    _parse_enum_values(enum_match.group("values")) if enum_match else None
                ),
            )
        )
    return {name: TableSpec(name=name, columns=tuple(columns)) for name, columns in grouped.items()}


# ---------------------------------------------------------------------------
# 比对
# ---------------------------------------------------------------------------


def diff(a: Mapping[str, TableSpec], b: Mapping[str, TableSpec]) -> list[str]:
    """给出人可读差异清单（哪张表 / 哪个字段 / 期望 vs 实际）。

    **MUST NOT 退化成 `a != b` 一句话**：差异清单是这套检查唯一的产出，
    看不清"哪里不一样"的检查最终会被绕过。
    分类：① 表集合 ② 列集合 ③ 列顺序 ④ 类型 ⑤ 可空性 ⑥ 枚举值。
    """
    differences: list[str] = []
    for name in sorted(set(a) - set(b)):
        differences.append(f"表 {name} 只在一侧存在（另一侧缺失）")
    for name in sorted(set(b) - set(a)):
        differences.append(f"表 {name} 只在一侧存在（另一侧缺失）")
    for name in sorted(set(a) & set(b)):
        left, right = a[name], b[name]
        left_names = list(left.column_names())
        right_names = list(right.column_names())
        if set(left_names) != set(right_names):
            missing = sorted(set(left_names) - set(right_names))
            extra = sorted(set(right_names) - set(left_names))
            differences.append(
                f"表 {name} 列集合不一致：仅左侧有 {missing}，仅右侧有 {extra}"
            )
            continue
        if left_names != right_names:
            differences.append(
                f"表 {name} 列顺序不一致：\n      左 {left_names}\n      右 {right_names}"
            )
        right_by_name = {column.name: column for column in right.columns}
        for column in left.columns:
            other = right_by_name[column.name]
            if column.type != other.type:
                differences.append(
                    f"表 {name} 字段 {column.name} 类型不一致：左 {column.type}，右 {other.type}"
                )
            if column.nullable != other.nullable:
                differences.append(
                    f"表 {name} 字段 {column.name} 可空性不一致："
                    f"左 {'YES' if column.nullable else 'NO'}，"
                    f"右 {'YES' if other.nullable else 'NO'}"
                )
            if column.enum_values != other.enum_values:
                differences.append(
                    f"表 {name} 字段 {column.name} 枚举值不一致："
                    f"左 {column.enum_values}，右 {other.enum_values}"
                )
    return differences


def load_metadata() -> MetaData:
    """取 `repository.models.Base.metadata`（唯一入口，避免各处直接 import Base）。"""
    from aicore.repository.models import Base

    return Base.metadata
