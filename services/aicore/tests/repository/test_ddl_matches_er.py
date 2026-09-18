"""逐列比对用例：`docs/er.md` §6 数据字典、`deploy/sql/ddl/*.sql`、`docs/openapi.yaml` 三方一致。

**为什么是纯文本用例**（无需数据库）：本用例要在**任何环境**（含无 MySQL 的 CI 与全新
checkout）拦住「文档改了表没跟上 / 表改了文档没跟上」这类静默漂移（design.md 风险项
「er.md 与 DDL 单边改动」）。真实 `information_schema` 侧的一致性由集成用例承担，
本用例只做离线文本层比对，故 MUST NOT 依赖数据库、网络或任何密钥。

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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

# 注意：`Mapping` / `Sequence` **MUST NOT** 只放在 `if TYPE_CHECKING:` 里。
# 它们在本文件里是**运行期**用到的（`isinstance(document, Mapping)` 与函数签名），
# 只在类型检查期导入会让 `load_openapi()` 抛 `NameError: name 'Mapping' is not defined`
# —— 本任务首轮就是这么挂掉 18 条用例的（报错点离真正原因很远，极难回推）。

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ER_MD = PROJECT_ROOT / "docs" / "er.md"
OPENAPI_YAML = PROJECT_ROOT / "docs" / "openapi.yaml"
DDL_DIR = PROJECT_ROOT / "deploy" / "sql" / "ddl"

# ---------------------------------------------------------------------------
# 逻辑表 -> DDL 文件（brief 的 Files 表逐行落位）
#
# 三张分片表用 `.template.sql`（含 {table} / {month} 占位符，不能直接执行）；
# 六张非分片表用 `.sql`。本任务的建表演练月固定为 202601。
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
RENDER_MONTH = "202601"
PHYSICAL_SUFFIX_RE = re.compile(r"_\d{6}$")
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
# 通用解析工具
# ---------------------------------------------------------------------------
# 类型 = 类型名 [+ 括号参数] [+ unsigned]，其后必须紧跟空白或行尾。
# 用 `(?=\s|$)` 而不是忽略尾部：否则 `varchar2(32)` 这类拼错的类型名会被前缀匹配
# 静默截成 `varchar`，与数据字典"相等"而本用例全绿——那是最危险的一类假绿。
DDL_TYPE_RE = re.compile(
    r"^(?P<type>[a-z]+(?:\s*\([^)]*\))?(?:\s+unsigned)?)(?=\s|$)", re.IGNORECASE
)
ENUM_TYPE_RE = re.compile(r"enum\((?P<values>.+)\)", re.IGNORECASE)
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`(?P<name>[^`]+)`\s*\((?P<body>.*?)\)\s*ENGINE\s*=",
    re.IGNORECASE | re.DOTALL,
)
ER_HEADING_RE = re.compile(r"^###\s+6\.\d+")
# 从标题里取**表名**：编号后紧跟的 ASCII 标识符（`6.1 ai_task（...）` -> `ai_task`）。
# 取不到（形如 `6.10 辅助结构（...）`）时回退成整行标题当键 —— 键只需**稳定且唯一**；
# 真正决定"这一节算不算数据字典"的是表头口径，不是这个键长什么样。
ER_TABLE_NAME_RE = re.compile(r"^###\s+6\.\d+\s+([A-Za-z_]\w*)?")
# 数据字典表格的表头（6 列口径）。「本节到底是不是数据字典」**只认这一行**，
# 不认标题文字 —— 标题里既有 `6.1 ai_task（...）` 也有 `6.10 辅助结构（Redis / MQ / OSS）`，
# 靠中文/ASCII 前缀区分迟早再漏一个（§6.10 就是这么把 9 张表一起带崩的）。
MD_HEADER_CELLS = ["字段", "类型", "空", "键", "默认", "说明"]
# 反引号列项（`` `col` 类型... ``）的开头：用来把「列」与「索引/约束项」分开。
# 判据与 parse_ddl_columns 同源：PRIMARY/UNIQUE/KEY/INDEX/CONSTRAINT/FOREIGN/CHECK
# 这些项**不是**反引号列名开头，故不会被误判成列。
DDL_COLUMN_ITEM_RE = re.compile(r"^`[^`]+`\s+\S")


@dataclass(frozen=True)
class Column:
    """一列的比对口径：DDL 与数据字典都表达得了的维度。"""

    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class DdlTable:
    """DDL 里的一张表：渲染后的表名 + 逐列定义 + 建表正文（列/索引/约束项）。"""

    name: str
    columns: list[Column]
    create_body: str


class ErFormatError(Exception):
    """er.md 的 markdown 表格结构与预期不符。"""


def _split_markdown_row(line: str) -> list[str]:
    """切分 markdown 表格行：先把转义竖线 `\\|` 换成占位符再切，最后还原。"""
    placeholder = "\x00PIPE\x00"
    cells = line.replace(r"\|", placeholder).split("|")
    return [cell.strip().replace(placeholder, "|") for cell in cells]


def _strip_outer_empty(cells: list[str]) -> list[str]:
    """去掉 markdown 行首/行尾竖线带来的空单元格。"""
    return [
        cell
        for index, cell in enumerate(cells)
        if not (index in (0, len(cells) - 1) and cell == "")
    ]


def _is_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(set(cell) <= set("-: ") and "-" in cell for cell in cells)


def _iter_er_rows(path: Path) -> Iterable[tuple[str, list[str]]]:
    """依次交出 `er.md` §6 每张表的每个数据行（表名 + 单元格）。

    **章节边界与表头判定必须解耦**（本任务首轮的血债）：`§6.10 辅助结构（Redis / MQ / OSS）`
    的表头是「结构 / 类型 / 说明」（3 列），按"标题后面是不是 ASCII 表名"来圈章节会漏掉它，
    于是它的三行被当成上一节 `vision_qa_log` 的数据行 → 列数不足 → 抛错 → 连带 8 条用例全红。

    故本函数改成：
      1. 逐行扫描；
      2. 遇到 `^###\\s+6\\.\\d+`（**只认编号前缀，不要求后面是 ASCII**）就看它后面的第一张表
         是不是 6 列数据字典口径：是 -> 进入数据字典状态；不是 -> `current = None`，
         整节直到下一个 `### 6.x` 之前都**不解析、也不抛错**；
      3. `current is None` 时任何 `|` 行都被忽略；
      4. 处于数据字典状态时，数据行列数不足 6 **照旧抛 `ErFormatError`**
         —— 这是"解析塌了要报警"的防线，**不为了让 §6.10 过而删掉**。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    index = 0
    while index < total:
        line = lines[index]
        index += 1
        if not ER_HEADING_RE.match(line):
            continue
        # 找到本节第一张表格的第一行
        while index < total and not lines[index].startswith("|"):
            index += 1
        rows: list[list[str]] = []
        while index < total and lines[index].startswith("|"):
            rows.append(_strip_outer_empty(_split_markdown_row(lines[index])))
            index += 1
        header = rows[0] if rows else []
        body = [cells for cells in rows[1:] if not _is_separator_row(cells)]
        if list(header) != MD_HEADER_CELLS:
            # 非数据字典口径（§6.10 辅助结构）-> 本节退出比对范围
            continue
        match = ER_TABLE_NAME_RE.match(line)
        table = (match.group(1) if match else None) or line
        for cells in body:
            if len(cells) < len(MD_HEADER_CELLS):
                raise ErFormatError(
                    f"{path.name} 表 {table} 行列数不足"
                    f" {len(MD_HEADER_CELLS)}：{' | '.join(cells)}"
                )
            yield table, cells


def _normalize_type(raw: str) -> str:
    """类型归一：**只小写类型名，括号内的参数保原样**。

    为什么不能整体 `.lower()`（首轮的真缺陷）：`er.md` 的类型列写的是
    `enum('VALID','EXPIRING','EXPIRED','UNKNOWN')` —— 括号里是**枚举值**，
    它们是 SQL 字符串字面量，**大小写敏感**。整体小写会把期望值变成
    `('valid','expiring',...)`，与 DDL 的 `('VALID',...)` 必然不等，
    于是 11 个枚举列全报"枚举值不一致"（实测就是这 11 条）。

    而括号**外**的部分（`VARCHAR` / `Int UNSIGNED` / `DATETIME`）大小写不敏感，
    必须归一，否则 `int UNSIGNED`（`er.md`）与 `int unsigned`（DDL）会被判成不同。

    实现方式：显式扫描而不是正则 `^([^(]*)[(](.*)[)]$` ——
    枚举值里可能出现 `)`（如 `enum('A)','B')`），正则会在错的括号处断句；
    扫描按"引号优先、深度计数"处理，天然免疫。
    """
    text = re.sub(r"\s+", " ", raw.strip())
    out: list[str] = []
    depth = 0
    quote: str | None = None
    for char in text:
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
        # 括号外（depth == 0）类型名部分才小写；括号内是参数，保原样
        out.append(char.lower() if depth == 0 else char)
    return "".join(out)


def _parse_enum_values(raw: str) -> tuple[str, ...]:
    """`'A','B'` -> `("A", "B")`（去引号与空白，保持文档里的顺序）。"""
    return tuple(value.strip().strip("'").strip('"') for value in raw.split(",") if value.strip())


def split_column_clauses(block: str) -> list[str]:
    """把建表正文按**列项**切开，每项含该列从列名到 COMMENT 的整段定义。

    **为什么不用 `[^,\\n]*` 这类行内正则**：列定义里本来就有逗号
    （`enum('RAW_MATERIAL','CERTIFICATE',...)`、`decimal(3,2)`），而 COMMENT 在逗号**之后**，
    截断必然把注释切掉 —— 结果是"DDL 里明明有中文注释却报缺失"的假红（本任务首轮的
    四处假红：`vision_review.biz_type` / `status` / `confidence_level` / `confidence`）。

    复用 `_split_top_level(body)`：它已经正确处理括号与引号，切出来的就是**顶层列项**
    （列 / 索引 / 约束各成一项）。每项再按"行首是不是新的反引号列名"细分成弱换行的同列续行，
    最后只保留**以反引号列名开头**的项 —— `CREATE TABLE ... (` 前缀、索引项、约束项、
    收尾的 `)` 全部落选（否则 `by_name` 与 `clauses` 的长度会对不上，那正是本函数的下限自检）。
    """
    clauses: list[str] = []
    buffer: list[str] = []
    for item in _split_top_level(block):
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


def strip_sql_comments(source: str) -> str:
    """去掉 `--` 行注释，避免注释里的示例 SQL 被当成真实 DDL 解析。"""
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("--"))


def strip_sql_string_literals(source: str) -> str:
    """把 `'...'` 字符串字面量的**内容**掏空，只留空引号。

    **为什么需要它**（FIX-3 的真正根因，工单里写的 `strip_sql_comments` 并不够）：
    模板里那些花括号示例不在 `--` 注释里，而在**列 COMMENT 的字符串字面量**里，例如
    ``COMMENT '...：{channel, provider, modelVersion, ...}'`` 与
    ``COMMENT '... GET /aicore/tasks/{taskId}'``。`strip_sql_comments` 只吃 `--` 行，
    所以剥完这些花括号**还在**（实测：剥注释后仍含花括号 = True）。

    结构性判据：字符串字面量在 MySQL 里是**数据**，永远不会被当 SQL 解析 —— 所以
    "这个模板渲染后还有没有残留占位符"只应对**代码骨架**发问，问法就是先把字面量掏空。
    **MUST NOT** 反过来把注释/示例里的花括号删掉：那是给人看的文档，
    为迁就一条断言而改文档是本末倒置。
    """
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", source)


def render_template(source: str, table: str, month: str) -> str:
    """按 brief 的占位符协议渲染模板（{table} 本表名、{month} 同月兄弟表月份）。"""
    return source.replace("{table}", table).replace("{month}", month)


def parse_er_tables(path: Path = ER_MD) -> dict[str, list[Column]]:
    """解析 `er.md` §6 的 9 张表（列：字段 / 类型 / 空 / 键 / 默认 / 说明）。"""
    tables: dict[str, list[Column]] = {}
    for table, cells in _iter_er_rows(path):
        field, raw_type, nullable = cells[0], cells[1], cells[2]
        if nullable not in {"YES", "NO"}:
            raise ErFormatError(f"{path.name} 表 {table} 的「空」列既非 YES 也非 NO：{cells}")
        tables.setdefault(table, []).append(
            Column(name=field, type=_normalize_type(raw_type), nullable=nullable == "YES")
        )
    return tables


def parse_er_defaults(path: Path = ER_MD) -> dict[str, dict[str, str]]:
    """解析 `er.md` §6 的「默认」列：`表 -> {列: 默认值}`（`NULL` / `—` / `CURRENT_TIMESTAMP(3)`）。

    注：`er.md` 该列取值形如 `NULL` / `—`（破折号） / `CURRENT_TIMESTAMP(3)`。
    """
    defaults: dict[str, dict[str, str]] = {}
    for table, cells in _iter_er_rows(path):
        defaults.setdefault(table, {})[cells[0]] = cells[4]
    return defaults


def _split_top_level(body: str) -> list[str]:
    """按顶层逗号切分建表正文（跳过括号与引号内部），得到列/索引/约束项。"""
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    for char in body:
        if quote is not None:
            buf.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            buf.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def parse_ddl_columns(create_body: str) -> list[Column]:
    """从 `CREATE TABLE ... ( ... )` 的正文里抽列定义（跳过索引、外键约束等项）。"""
    columns: list[Column] = []
    for item in _split_top_level(create_body):
        stripped = item.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if re.match(
            r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN|CHECK)\b", stripped, re.IGNORECASE
        ):
            continue
        column = re.match(r"^`(?P<name>[^`]+)`\s+(?P<rest>.+)$", stripped, re.DOTALL)
        if not column:
            raise AssertionError(f"无法解析的建表项（既非索引也非反引号列定义）：{stripped!r}")
        rest = column.group("rest").strip()
        type_match = DDL_TYPE_RE.match(rest)
        if not type_match:
            raise AssertionError(f"列 {column.group('name')} 的类型无法解析：{rest!r}")
        columns.append(
            Column(
                name=column.group("name"),
                type=_normalize_type(type_match.group("type")),
                nullable=re.search(r"\bNOT\s+NULL\b", rest, re.IGNORECASE) is None,
            )
        )
    return columns


def parse_ddl_tables(source: str) -> list[DdlTable]:
    """解析一个 DDL 文件里的全部 `CREATE TABLE`（本任务每个文件恰好一张表）。"""
    text = strip_sql_comments(source)
    return [
        DdlTable(
            name=match.group("name"),
            columns=parse_ddl_columns(match.group("body")),
            create_body=match.group("body"),
        )
        for match in CREATE_TABLE_RE.finditer(text)
    ]


def collect_index_names(block: str) -> list[str]:
    """建表正文 -> 显式索引名序列（`idx_*` / `uk_*`；PRIMARY KEY 无名字，不计入）。

    给集成用例做**非空下限**用：只断言"information_schema 里有 4 条外键"而不看索引，
    等于让"索引整批漏建"静默通过；期望值现取自 DDL 自身，不另抄一份清单。
    """
    flat = re.sub(r"\s+", " ", strip_sql_comments(block))
    return re.findall(r"(?:UNIQUE\s+)?(?:KEY|INDEX)\s+`((?:idx|uk)_\w+)`", flat, re.IGNORECASE)


def normalize_logical_name(physical_name: str) -> str:
    """物理分片表名 -> 逻辑表名（`ai_task_202601` -> `ai_task`）。"""
    return PHYSICAL_SUFFIX_RE.sub("", physical_name)


def ddl_file(table: str) -> Path:
    return DDL_DIR / ALL_TABLES[table]


def read_ddl(table: str) -> str:
    return ddl_file(table).read_text(encoding="utf-8")


def parse_all_ddl_tables() -> dict[str, DdlTable]:
    """逻辑表名 -> DDL 解析结果（分片模板先按逻辑名渲染再解析，与非分片表同口径）。"""
    parsed: dict[str, DdlTable] = {}
    for table in ALL_TABLES:
        source = read_ddl(table)
        if table in SHARDED_TABLES:
            source = render_template(source, table, RENDER_MONTH)
        tables = parse_ddl_tables(source)
        assert len(tables) == 1, (
            f"{ALL_TABLES[table]} 期望恰好 1 张表，实际解析到 {[item.name for item in tables]}"
        )
        parsed[table] = tables[0]
    return parsed


def first_create_table_block(table: str) -> str:
    """取某个 DDL 文件里第一条 CREATE TABLE 语句（含 ENGINE / COMMENT 等后缀）。"""
    text = strip_sql_comments(read_ddl(table))
    match = re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b.*?;", text, re.IGNORECASE | re.DOTALL)
    assert match, f"{ALL_TABLES[table]} 中找不到 CREATE TABLE 语句"
    return match.group(0)


def collect_ddl_enums() -> dict[str, tuple[str, ...]]:
    """全部 DDL 枚举列：`表.列 -> 枚举值序列`（分片模板按逻辑表名渲染后解析）。"""
    collected: dict[str, tuple[str, ...]] = {}
    for table, ddl_table in parse_all_ddl_tables().items():
        for item in _split_top_level(ddl_table.create_body):
            column = re.match(
                r"^`(?P<name>[^`]+)`\s+enum\((?P<values>.*?)\)", item.strip(), re.DOTALL
            )
            if column:
                key = f"{table}.{column.group('name')}"
                collected[key] = _parse_enum_values(column.group("values"))
    return collected


def collect_er_enums(er_tables: Mapping[str, Sequence[Column]]) -> dict[str, tuple[str, ...]]:
    """数据字典里的枚举列：`表.列 -> 枚举值序列`（从「类型」列现解，不抄写）。"""
    collected: dict[str, tuple[str, ...]] = {}
    for table, columns in er_tables.items():
        for column in columns:
            match = ENUM_TYPE_RE.fullmatch(column.type)
            if match:
                collected[f"{table}.{column.name}"] = _parse_enum_values(match.group("values"))
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


def diff_columns(table: str, expected: Sequence[Column], actual: Sequence[Column]) -> list[str]:
    """逐列比对：列名序列、类型、可空性；差异按字段逐条给出期望与实际。"""
    expected_names = [column.name for column in expected]
    actual_names = [column.name for column in actual]
    if expected_names != actual_names:
        return [
            f"表 {table} 列名序列不一致（期望 er.md 的顺序）\n"
            f"      期望 {expected_names}\n      实际 {actual_names}"
        ]
    differences: list[str] = []
    for want, got in zip(expected, actual, strict=True):
        if want.type != got.type:
            differences.append(
                f"表 {table} 字段 {want.name} 类型不一致：期望 {want.type}，实际 {got.type}"
            )
        if want.nullable != got.nullable:
            differences.append(
                f"表 {table} 字段 {want.name} 可空性不一致："
                f"期望 {'YES' if want.nullable else 'NO'}，实际 {'YES' if got.nullable else 'NO'}"
            )
    return differences


# ---------------------------------------------------------------------------
# 断言 1：逐列比对（表集合 / 列名序列 / 类型 / 可空性 / 默认值）
# ---------------------------------------------------------------------------
def test_er_md_parses_all_nine_tables() -> None:
    """非空下限 + 表集合：9 张表必须都解析出来，否则下面的比对会静默缩水。"""
    er_tables = parse_er_tables()
    assert len(er_tables) >= MIN_ER_TABLES, (
        f"er.md 只解析到 {len(er_tables)} 张表（下限 {MIN_ER_TABLES}）：{'/'.join(er_tables)}"
    )
    er_only = sorted(set(er_tables) - set(ALL_TABLES))
    ddl_only = sorted(set(ALL_TABLES) - set(er_tables))
    assert set(er_tables) == set(ALL_TABLES), (
        f"er.md §6 的表集合与 DDL 逻辑表集合不一致：仅 er.md 有 {er_only}，仅 DDL 有 {ddl_only}"
    )


def test_ddl_directory_matches_brief_manifest() -> None:
    """DDL 目录的文件清单必须与 brief 的 Files 表一致（一个不多一个不少）。"""
    expected = sorted(["00_create_database.sql", *ALL_TABLES.values()])
    actual = sorted(path.name for path in DDL_DIR.glob("*.sql"))
    assert actual == expected, (
        f"deploy/sql/ddl 文件清单与工单不一致：期望 {expected}，实际 {actual}"
    )


def test_ddl_column_order_and_types_match_er() -> None:
    """逐列比对：每张表的列名序列、类型、可空性都必须与 er.md §6 完全相同。"""
    er_tables = parse_er_tables()
    ddl_tables = parse_all_ddl_tables()
    differences: list[str] = []
    assert set(ddl_tables) == set(er_tables), (
        f"表集合不一致：仅 DDL 有 {sorted(set(ddl_tables) - set(er_tables))}，"
        f"仅 er.md 有 {sorted(set(er_tables) - set(ddl_tables))}"
    )
    for table in sorted(er_tables):
        differences.extend(diff_columns(table, er_tables[table], ddl_tables[table].columns))
    assert not differences, format_differences("DDL 与 er.md §6 数据字典逐列比对失败", differences)


def test_ddl_enums_match_er_enums() -> None:
    """枚举列的值集合与顺序也必须与 er.md 一致（顺序影响默认值语义与可读性）。"""
    er_enums = collect_er_enums(parse_er_tables())
    ddl_enums = collect_ddl_enums()
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
    ddl_enums = collect_ddl_enums()
    er_enums = collect_er_enums(parse_er_tables())
    assert len(ddl_enums) >= MIN_ENUM_COLUMNS, (
        f"只在 DDL 里解出 {len(ddl_enums)} 个枚举列（下限 {MIN_ENUM_COLUMNS}）：{sorted(ddl_enums)}"
    )
    assert set(ddl_enums) == set(er_enums), (
        f"er.md 与 DDL 的枚举列集合不一致：{sorted(set(ddl_enums) ^ set(er_enums))}"
    )


def test_timestamp_defaults_match_er_notes() -> None:
    """时间列默认值口径：`CURRENT_TIMESTAMP(3)` 只能出现在 er.md「默认」列写了它的列上。

    期望值现解自 er.md 的「默认」列，故「顺手给 reviewed_at 加个默认值」这类偏离
    （会把"忘记写时间"变成静默假数据）会被本用例拦住。
    """
    er_tables = parse_er_tables()
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
        for column in er_tables[table]:
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
    er_enums = set(collect_er_enums(parse_er_tables()))
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
    ddl_values = collect_ddl_enums().get(ddl_column)
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
        source = strip_sql_comments(read_ddl(table))
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

    **为什么先剥注释再掏空字符串字面量**：模板里的花括号示例是**文档**，不是占位符 ——
    例如 `model_meta` 的 ``COMMENT '...：{channel, provider, modelVersion, ...}'``、
    `task_id` 的 ``COMMENT '... GET /aicore/tasks/{taskId}'``，以及 `fields_json` 的
    ``COMMENT '... OcrField = {fieldName, value（脱敏）, confidence（0~1）}'``。
    这些串在 MySQL 里是**数据**，永远不会被当 SQL 解析，故对"可执行骨架"发问前先把它们掏空。
    **MUST NOT** 反过来把注释里的示例花括号删掉 —— 为了迁就一条断言而改文档是本末倒置。
    """
    source = read_ddl(table)
    rendered = render_template(source, table, RENDER_MONTH)
    skeleton = strip_sql_string_literals(strip_sql_comments(rendered))
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
        text = strip_sql_comments(path.read_text(encoding="utf-8"))
        assert not re.search(r"^\s*USE\s+", text, re.MULTILINE | re.IGNORECASE), (
            f"{path.name} 出现 USE 语句：库必须由执行方指定"
        )


# ---------------------------------------------------------------------------
# 断言 4：幂等性
# ---------------------------------------------------------------------------
def test_every_create_table_is_idempotent() -> None:
    """每个 DDL 文件的每张表都是 `CREATE TABLE IF NOT EXISTS`（复跑零错误的前提）。"""
    for path in sorted(DDL_DIR.glob("*.sql")):
        text = strip_sql_comments(path.read_text(encoding="utf-8"))
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
    text = strip_sql_comments((DDL_DIR / "00_create_database.sql").read_text(encoding="utf-8"))
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
    ddl_tables = parse_all_ddl_tables()
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


COMMENT_COUNT_RE = re.compile(r"\bCOMMENT\b", re.IGNORECASE)
# 表注释：`COMMENT='...'`（table option 形态）。中文 MUST 落在**引号内**。
TABLE_CN_COMMENT_RE = re.compile(r"COMMENT\s*=\s*'[^']*" + CJK_RE.pattern + r"[^']*'")
# 列注释：`COMMENT '...'`（列属性形态），支持 `\'` 转义。中文同样 MUST 落在**引号内**。
COLUMN_COMMENT_RE = re.compile(r"COMMENT\s+'(?:[^'\\]|\\.)*'")
COLUMN_CN_COMMENT_RE = re.compile(
    r"COMMENT\s+'(?:[^'\\]|\\.)*" + CJK_RE.pattern + r"(?:[^'\\]|\\.)*'"
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
    ddl_table = parse_all_ddl_tables()[table]
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
        raw = first_create_table_block(table)
        if table in SHARDED_TABLES:
            raw = render_template(raw, table, RENDER_MONTH)
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
