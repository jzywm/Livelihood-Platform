"""任务类型策略注册表用例（Task 4.6；工单 §4 的 13 条 + §3 的结构性断言）。

## 为什么权威值要「现读文档」而不是在用例里抄成常量

`er.md` §6.1 L291 的 enum 与 `openapi.yaml` 的 `components.schemas` 是**权威**，注册表是
**副本**。把四个名字抄进用例当常量，等于把「副本是否与权威一致」降级成「副本是否与我抄的
字符串一致」——那一层比对是空的（本组已出现三次同形态的假绿）。故两组比对都从文档**现读**，
并给解析函数各配一条**判别力自证**（喂合成文档，断言交出合成文档里的那组值；喂缺段文档，
断言报错而不是静默返回空集）。没有自证，「现读」也可能只是"读了个空集"。

## 本文件的两条**结构性判据**（源码级 AST，不是行为级）

判据 A（`find_per_type_branches`）：源码里 MUST NOT 出现「按 `task_type` 与字符串字面量
比较」的逐类型分支（`if` / `elif`）或 `match task_type`。
判据 B（`find_task_type_literals`）：`core/task_runner.py` 里 MUST NOT 出现任何任务类型字面量。

两条判据都配了**双向控制样本**：反面样本（elif 链 / 分支式 runner）必须判红，
正面样本（表查找）必须判绿。只验"反面判红"会漏掉"恒红判据"，只验"正面判绿"会漏掉
"恒绿判据"——两边都必须有，判据才算被证明过。

## 能力的边界（如实登记，MUST NOT 当成"已经验过"）

- 判据 A 是**源码级**的：它能证明"注册表不是靠分支解析类型"，不能证明"执行器会走表查找"
  ——后者要等 Task 4.7 的 `task_runner` 落地，本任务时该文件仍是 docstring 空壳，
  故判据 B 此刻走 `pytest.skip`（**不假装验过**），且跳过条件是「文件无代码」而非
  「本用例不想跑」：Task 4.7 一交付执行器，同一条用例自动变成真断言。
- 判据 B 取严口径：`docstring` 里出现类型名同样算命中（工单 §3 原文是「不出现任何任务类型
  字面量」）。放宽的那一档留给判据 A（它只判"逐类型分支"这一种行为）。
- 本文件不校验「执行器真的用上了注册表」，也不校验超时值是否符合真实任务耗时——两者的
  权威判断都在 Task 4.7。
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest
import yaml

from aicore.core.config import Settings, get_settings
from aicore.core.errors import PARAM_VALUE_CODE, ParamError
from aicore.service.task.registry import (
    REGISTRY,
    TaskPolicy,
    assert_submittable,
    get_policy,
    registered_types,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs"
SRC = PROJECT_ROOT / "src" / "aicore"
REGISTRY_PATH = SRC / "service" / "task" / "registry.py"
RUNNER_PATH = SRC / "core" / "task_runner.py"

#: design.md:189-192 的四行任务类型表
#: （`task_type` / `result_schema` / `retryable` / `implemented`）。
#: 这里可以逐条写死：它就是工单 §1「四条登记（MUST NOT 增删）」的**待验期望**。
#: 与之相对，`er.md` 的 enum 与 `openapi.yaml` 的结构名**一律现读**（见模块 docstring）。
_DESIGN_TABLE: tuple[tuple[str, str, bool, bool], ...] = (
    ("OCR", "OcrResult", True, True),
    ("VISION_REVIEW", "VisionReviewResult", True, False),
    ("KITCHEN_ANOMALY", "KitchenAnomalyResult", True, False),
    ("RISK_PREDICT", "RiskPredictResult", False, False),
)

#: 预留注册位的 `handler_ref` 哨兵（任务侧定义在 `registry.py`；这里独立写出，使断言不依赖私有名）。
_RESERVED_HANDLER_REF = "<reserved>"


# ---------------------------------------------------------------------------
# 文档解析器（现读权威，不抄常量）
# ---------------------------------------------------------------------------

_ENUM_CALL_RE = re.compile(r"enum\(([^)]*)\)")
_QUOTED_RE = re.compile(r"'([^']*)'")


def parse_ai_task_type_enum(er_md_text: str) -> frozenset[str]:
    """从 `er.md` 的 `ai_task` 字段表里现读 `type` 的 enum 取值集合。

    定位方式是**行首单元格** `| type |` 而不是行号：行号会随文档增删行漂移，而
    「`ai_task` 表里名为 `type` 的那一行」是文档结构本身（实测全文件只有 L291 一行匹配）。
    找不到即抛错——**MUST NOT 静默返回空集**：空集会让上层比对在"两边都空"时恒真。
    """
    for line in er_md_text.splitlines():
        if not line.startswith("| type |"):
            continue
        match = _ENUM_CALL_RE.search(line)
        if match is None:
            raise AssertionError(f"er.md 的 type 行里没有 enum(...) 形态：{line!r}")
        return frozenset(_QUOTED_RE.findall(match.group(1)))
    raise AssertionError("er.md 里找不到 `| type |` 行：ai_task 的 type 字段定义可能已改形态")


def parse_openapi_schema_names(openapi_text: str) -> frozenset[str]:
    """从 `openapi.yaml` 现读 `components.schemas` 的键集合（缺段即抛错，不返回空集）。"""
    document = yaml.safe_load(openapi_text)
    if not isinstance(document, dict):
        raise AssertionError("openapi.yaml 解析结果不是映射：文档形态可能已变")
    components = document.get("components")
    if not isinstance(components, dict):
        raise AssertionError("openapi.yaml 缺 components 段")
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        raise AssertionError("openapi.yaml 缺 components.schemas 段")
    return frozenset(schemas)


def parse_task_result_one_of(openapi_text: str) -> frozenset[str]:
    """现读 `TaskResult.result` 的 `oneOf` 里引用的结构名（openapi.yaml:805-811）。"""
    document = yaml.safe_load(openapi_text)
    task_result = document["components"]["schemas"]["TaskResult"]
    one_of = task_result["properties"]["result"]["oneOf"]
    return frozenset(str(entry["$ref"]).rsplit("/", 1)[-1] for entry in one_of)


# ---------------------------------------------------------------------------
# 结构判据（源码级 AST）
# ---------------------------------------------------------------------------

#: 只有这些比较运算才可能构成「与字面量逐类型分支」；`is` / `<` 之类不在此列。
_LITERAL_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)


def _mentions(node: ast.AST, subject: str) -> bool:
    """子树里是否出现过 `subject` 这个名字（含 `x.<subject>` 属性形态）。"""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == subject:
            return True
        if isinstance(inner, ast.Attribute) and inner.attr == subject:
            return True
    return False


def _holds_string_literal(node: ast.AST) -> bool:
    """子树里是否有字符串字面量（含常量元组 / 常量集合 / f-string 里的常量段）。"""
    return any(
        isinstance(inner, ast.Constant) and isinstance(inner.value, str) for inner in ast.walk(node)
    )


def _condition_branches_per_type(test: ast.expr, subject: str) -> bool:
    """条件里是否存在「`subject` 与字符串字面量比较」的成分（按 `and`/`or`/`not` 下探）。"""
    if isinstance(test, ast.BoolOp):
        return any(_condition_branches_per_type(value, subject) for value in test.values)
    if isinstance(test, ast.UnaryOp):
        return _condition_branches_per_type(test.operand, subject)
    if not isinstance(test, ast.Compare):
        return False
    if not any(isinstance(op, _LITERAL_COMPARE_OPS) for op in test.ops):
        return False
    operands = [test.left, *test.comparators]
    # 两个特征必须出现在**同一个比较**里：一边提到 subject、另一边有字符串字面量。
    # 只判「条件里出现过 subject」会把 `if task_type not in REGISTRY`（本任务要的正确写法）
    # 一起判红——那样的判据在正确实现上恒红，等于无效判据。
    return any(_mentions(operand, subject) for operand in operands) and any(
        _holds_string_literal(operand) for operand in operands
    )


def find_per_type_branches(source: str, *, subject: str) -> list[tuple[int, str]]:
    """判据 A：扫出「按 `subject` 逐类型分支」的位置（返回 `(行号, 形态)`，按行号排序）。

    命中的两类形态：

    1. `if` / `elif`（`ast.If`，`elif` 在 AST 里是嵌套的 `If`，会被一并走到）的条件里，
       `subject` 与**字符串字面量**做了 `==` / `!=` / `in` / `not in`；
    2. `match subject:`（`ast.Match`，任何 `case` 形态）。

    非空返回即判该实现「用分支而非表查找解析任务类型」。
    """
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Match) and _mentions(node.subject, subject):
            hits.append((node.lineno, "match"))
        elif isinstance(node, ast.If) and _condition_branches_per_type(node.test, subject):
            hits.append((node.lineno, "if/elif"))
    return sorted(hits)


def find_task_type_literals(source: str, task_types: frozenset[str]) -> list[tuple[int, str]]:
    """判据 B：扫出源码里**任何**等于某个任务类型的字符串常量（含 docstring，取严口径）。

    工单 §3 的措辞是「不出现任何任务类型字面量」，故不加「排除 docstring」之类的放宽：
    任务类型集合属于注册表，`task_runner` 连提都不需要提。
    """
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in task_types
        ):
            hits.append((node.lineno, node.value))
    return sorted(hits)


def _module_level_names(tree: ast.Module) -> set[str]:
    """模块顶层被赋值的名字（`x = …` / `x: T = …`）。"""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _registry_subscripts(node: ast.AST) -> list[int]:
    """`REGISTRY[...]` 形式下标访问所在行（表查找的证据）。"""
    return [
        inner.lineno
        for inner in ast.walk(node)
        if isinstance(inner, ast.Subscript)
        and isinstance(inner.value, ast.Name)
        and inner.value.id == "REGISTRY"
    ]


def _registry_subscripts_in_function(tree: ast.AST, name: str) -> list[int]:
    """某个函数体内 `REGISTRY[...]` 的行号（查无此函数即返回空）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return _registry_subscripts(node)
    return []


def _has_code_beyond_docstring(tree: ast.Module) -> bool:
    """模块是否有 docstring 之外的节点（纯 docstring 空壳返回 False）。"""
    return any(
        not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        for node in tree.body
    )


def _imported_module_names(source: str) -> set[str]:
    """源码里全部 `import` / `from … import` 的目标模块名（相对导入取已写部分）。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def _handler_module_path(handler_ref: str) -> Path:
    """`handler_ref`（`service.ocr_service` 形态）→ 源码路径。

    口径：design.md:189 写的是 `service/ocr_service.py`（相对 `src/aicore/`），
    `handler_ref` 沿用同一写法，故这里按点号拆成路径。只做**存在性**检查，**不导入**。
    """
    return SRC / Path(*handler_ref.split(".")).with_suffix(".py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 合成样本（判别力自证用；**不是**被测实现）
# ---------------------------------------------------------------------------

#: 反面样本：用 elif 链把任务类型映射到处理器（design.md:194 明确不要的写法）。
#: 四个分支刻意各带一次字面量比较（`else` 不带比较，故不写 `else`）：判据必须**逐处**命中。
_SYNTHETIC_ELIF_IMPL = (
    "def handler_for(task_type: str) -> str:\n"
    '    """反面样本：elif 链。"""\n'
    '    if task_type == "OCR":\n'
    '        return "service.ocr_service"\n'
    '    elif task_type == "VISION_REVIEW":\n'
    '        return "service.vision_review"\n'
    '    elif task_type == "KITCHEN_ANOMALY":\n'
    '        return "service.kitchen_anomaly"\n'
    '    elif task_type == "RISK_PREDICT":\n'
    '        return "service.risk_predict"\n'
    "    raise KeyError(task_type)\n"
)

#: 反面样本：`match` 形式（与 elif 链同类，只是换了语法）。
_SYNTHETIC_MATCH_IMPL = (
    "def handler_for(task_type: str) -> str:\n"
    "    match task_type:\n"
    '        case "OCR":\n'
    '            return "service.ocr_service"\n'
    "        case _:\n"
    '            return ""\n'
)

#: 正面样本：表查找（成员检查 + 下标）——判据 MUST NOT 误伤它。
_SYNTHETIC_TABLE_LOOKUP = (
    "def handler_for(task_type: str) -> str:\n"
    "    if task_type not in REGISTRY:\n"
    "        raise KeyError(task_type)\n"
    "    return REGISTRY[task_type].handler_ref\n"
)


# ---------------------------------------------------------------------------
# §4.1 四条登记
# ---------------------------------------------------------------------------


def test_authoring_documents_exist() -> None:
    """非空下限：被现读的权威文档必须存在，否则后面的比对会因读不到文件而失真。"""
    for path in (DOCS / "er.md", DOCS / "openapi.yaml", REGISTRY_PATH):
        assert path.is_file(), f"权威依据缺失：{path}"


def test_four_registrations_match_design_table() -> None:
    """§4.1 四条登记逐条对齐 design.md:189-192 的四行任务类型表。

    逐条断言：`task_type` / `result_schema` / `retryable` / `implemented`。
    """
    assert len(REGISTRY) == len(_DESIGN_TABLE), (
        f"登记条数 {len(REGISTRY)} != design.md 四行表的 {len(_DESIGN_TABLE)} 条（MUST NOT 增删）"
    )
    assert sorted(REGISTRY) == sorted(row[0] for row in _DESIGN_TABLE)
    for task_type, result_schema, retryable, implemented in _DESIGN_TABLE:
        policy = REGISTRY[task_type]
        assert policy.task_type == task_type
        assert policy.result_schema == result_schema
        assert policy.retryable is retryable
        assert policy.implemented is implemented


def test_handler_ref_registers_a_location_without_fabricating_one() -> None:
    """`handler_ref`：OCR 指向 design.md:189 的处理器文件；三个预留位是**显式哨兵**。

    预留位的 `handler_ref` MUST NOT 是一个"看起来能 import、实际不存在"的模块路径：
    那会让执行器的导入探测得到假的「注册表与实现不一致」。故断言哨兵不是合法模块名、
    且按它拼出的路径**不存在**（如实表达"此处尚无位置"）。
    """
    assert REGISTRY["OCR"].handler_ref == "service.ocr_service"
    assert _handler_module_path("service.ocr_service").is_file(), (
        "design.md:189 的处理器文件不存在：OCR 的 handler_ref 指向了错误的位置"
    )

    reserved = sorted(name for name, policy in REGISTRY.items() if not policy.implemented)
    assert reserved == ["KITCHEN_ANOMALY", "RISK_PREDICT", "VISION_REVIEW"], (
        f"预留注册位应恰好是 design.md:190-192 的三行，实际 {reserved}"
    )
    for task_type in reserved:
        handler_ref = REGISTRY[task_type].handler_ref
        assert handler_ref == _RESERVED_HANDLER_REF, (
            f"{task_type} 是预留位，handler_ref 应为哨兵 {_RESERVED_HANDLER_REF}，"
            f"实际 {handler_ref!r}"
        )
        assert not handler_ref.replace(".", "").isidentifier(), (
            f"{task_type} 的 handler_ref {handler_ref!r} 是合法模块名形态："
            f"预留位 MUST NOT 造一个不存在的模块路径"
        )
        assert not _handler_module_path(handler_ref).exists()


# ---------------------------------------------------------------------------
# §4.2 键集合 vs er.md 的 enum（现读）
# ---------------------------------------------------------------------------


def test_registry_keys_equal_er_md_type_enum() -> None:
    """§4.2 `REGISTRY` 的键集合恰好等于 `er.md` §6.1 L291 的 `type` enum（现读，不抄常量）。"""
    enum_values = parse_ai_task_type_enum(_read(DOCS / "er.md"))
    assert len(enum_values) >= 2, f"er.md 只解析出 {enum_values}：解析路径可能已失效"
    assert frozenset(REGISTRY) == enum_values, (
        f"注册表键集合与 er.md 的 type enum 不一致："
        f"多出 {sorted(frozenset(REGISTRY) - enum_values)}、"
        f"缺少 {sorted(enum_values - frozenset(REGISTRY))}"
    )


def test_er_md_enum_parser_is_discriminating() -> None:
    """判别力自证：解析函数在合成文档上必须交出该文档里的那组取值；缺行必须报错。

    没有这条，「现读 er.md」可能只是"读了个空集"——那时上面的集合比对在两边都空时恒真。
    """
    synthetic = "\n".join(
        [
            "| 字段 | 类型 | 空 |",
            "|---|---|---|",
            "| type | enum('ALPHA','BETA','GAMMA') | NO |",
            "| status | enum('X','Y') | NO |",
        ]
    )
    assert parse_ai_task_type_enum(synthetic) == frozenset({"ALPHA", "BETA", "GAMMA"})
    with pytest.raises(AssertionError):
        parse_ai_task_type_enum("| status | enum('X','Y') | NO |\n")


# ---------------------------------------------------------------------------
# §4.3 result_schema 在 openapi.yaml 里存在（现读）
# ---------------------------------------------------------------------------


def test_result_schemas_exist_in_openapi_components() -> None:
    """§4.3 每个 `result_schema` 都在 `openapi.yaml` 的 `components.schemas` 里（现读）。"""
    schema_names = parse_openapi_schema_names(_read(DOCS / "openapi.yaml"))
    declared = [policy.result_schema for policy in REGISTRY.values()]
    missing = sorted(name for name in declared if name not in schema_names)
    assert not missing, f"注册表声明的结果结构在 components.schemas 里不存在：{missing}"
    assert len(set(declared)) == len(REGISTRY), f"四条登记的结果结构有重复：{sorted(declared)}"


def test_task_result_one_of_covers_declared_result_schemas() -> None:
    """`TaskResult.result` 的 `oneOf`（openapi.yaml:805-811）与注册表声明的结果结构**互等**。

    两边都是现读（左：openapi.yaml；右：REGISTRY），故它同时能抓到两个方向的漂移：
    注册表声明了 openapi 里没有的结构，或 openapi 的 `result` 漏了某个已注册类型的结果结构。
    """
    one_of = parse_task_result_one_of(_read(DOCS / "openapi.yaml"))
    declared = frozenset(policy.result_schema for policy in REGISTRY.values())
    assert one_of == declared, (
        f"TaskResult.result 的 oneOf 与注册表不一致：多出 {sorted(one_of - declared)}、"
        f"缺少 {sorted(declared - one_of)}"
    )


def test_openapi_schema_parser_is_discriminating() -> None:
    """判别力自证：解析函数在合成文档上必须交出该文档的 schemas 键；缺段必须报错。"""
    synthetic = (
        "components:\n  schemas:\n"
        "    Alpha:\n      type: object\n"
        "    Beta:\n      type: string\n"
    )
    assert parse_openapi_schema_names(synthetic) == frozenset({"Alpha", "Beta"})
    with pytest.raises(AssertionError):
        parse_openapi_schema_names("openapi: 3.0.0\n")


# ---------------------------------------------------------------------------
# §4.4-4.6 get_policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_type", sorted(REGISTRY))
def test_get_policy_returns_the_registered_policy(task_type: str) -> None:
    """§4.4 `get_policy` 对四个已注册类型各返回对应策略（非超时字段逐条等于表项）。"""
    policy = get_policy(task_type)
    declared = REGISTRY[task_type]
    assert policy.task_type == task_type
    assert policy.result_schema == declared.result_schema
    assert policy.retryable is declared.retryable
    assert policy.implemented is declared.implemented
    assert policy.handler_ref == declared.handler_ref
    assert policy.timeout_s == get_settings().ai_call_timeout_s


@pytest.mark.parametrize("task_type", ["NOPE", "ocr", "vision_review"])
def test_get_policy_unknown_type_raises_1003_naming_the_type(task_type: str) -> None:
    """§4.5 未注册类型 → `ParamError`，`code == 1003`，且消息里**含**该类型。

    刻意带上大小写不同的 `ocr` / `vision_review`：enum 是大小写敏感的封闭集合，
    「顺手 lower() 一下再查表」那种归一化回落必须同样失败。
    """
    with pytest.raises(ParamError) as excinfo:
        get_policy(task_type)
    assert excinfo.value.code == PARAM_VALUE_CODE
    assert task_type in str(excinfo.value), f"消息里没带上是哪个类型：{str(excinfo.value)!r}"


@pytest.mark.parametrize("task_type", ["NOPE", "", "ocr"])
def test_get_policy_fails_loudly_instead_of_returning_a_sentinel(task_type: str) -> None:
    """§4.6 未注册类型 MUST NOT 返回 `None`、MUST NOT 回落默认策略。

    **为什么用 `pytest.raises` 而不是断言返回值**：断言 `get_policy(x) is None` 只能证明
    "这一版返回了 None"，而设计要的是**根本没有返回值**。函数体里那句 `pytest.fail`
    才是判据本体——它只在"居然正常返回了"时执行，于是"返回哨兵"与"回落默认策略"
    两种实现都会当场红（`Failed` 不是 `ParamError`，不会被 `pytest.raises` 吞掉）。
    """
    with pytest.raises(ParamError) as excinfo:
        result = get_policy(task_type)
        pytest.fail(f"未注册类型 {task_type!r} 没有显式失败，而是返回了 {result!r}")
    assert excinfo.value.code == PARAM_VALUE_CODE


# ---------------------------------------------------------------------------
# §4.7-4.9 assert_submittable
# ---------------------------------------------------------------------------


def test_assert_submittable_accepts_ocr() -> None:
    """§4.7 `assert_submittable("OCR")` 通过，且交出的策略与 `get_policy` 同形。"""
    policy = assert_submittable("OCR")
    assert policy == get_policy("OCR")
    assert policy.implemented is True


def test_assert_submittable_rejects_unimplemented_types_with_a_distinct_message() -> None:
    """§4.8 三个 `implemented=False` 类型各抛 `1003`，且消息与「未注册」那条**可分辨**。

    非空下限：先断言预留位恰好 3 个，否则下面的循环可能一个都不跑而"全绿"。
    """
    unimplemented = sorted(name for name, policy in REGISTRY.items() if not policy.implemented)
    assert len(unimplemented) == 3, f"预留注册位应有 3 个，实际 {unimplemented}"

    with pytest.raises(ParamError) as unregistered:
        assert_submittable("NOPE")
    unregistered_message = str(unregistered.value)
    assert unregistered.value.code == PARAM_VALUE_CODE

    for task_type in unimplemented:
        with pytest.raises(ParamError) as excinfo:
            assert_submittable(task_type)
        message = str(excinfo.value)
        assert excinfo.value.code == PARAM_VALUE_CODE
        assert task_type in message
        assert message != unregistered_message, (
            f"{task_type} 与未注册类型给出了同一条消息：两种失败无法分辨，"
            f"运维看不出是「还没上线」还是「类型写错了」（design.md:194）"
        )
        assert "未注册" not in message, (
            f"{task_type} 是**已注册但未实现**，消息却自称未注册：{message!r}"
        )


def test_assert_submittable_unknown_type_raises_1003() -> None:
    """§4.9 `assert_submittable("NOPE")` 抛 `1003`（与 `get_policy` 同码同源）。"""
    with pytest.raises(ParamError) as excinfo:
        assert_submittable("NOPE")
    assert excinfo.value.code == PARAM_VALUE_CODE
    assert "NOPE" in str(excinfo.value)


# ---------------------------------------------------------------------------
# §4.10 registered_types
# ---------------------------------------------------------------------------


def test_registered_types_equals_registry_keys() -> None:
    """§4.10 `registered_types()` 恰好等于 `REGISTRY` 的键集合，且是 `frozenset`。"""
    result = registered_types()
    assert isinstance(result, frozenset)
    assert result == frozenset(REGISTRY)


# ---------------------------------------------------------------------------
# §4.11 超时现读
# ---------------------------------------------------------------------------


def test_timeout_s_is_read_live_from_settings_not_a_frozen_constant() -> None:
    """§4.11 `timeout_s` 从 `Settings` **现读**，不是被冻结的模块常量。

    `timeout_s` 是**从调用级超时借用**的值，不是独立定档的任务超时（出处与取舍见
    `registry.py` 模块 docstring：任务级超时理论上应 ≥ 一次调用（含重试），但 design.md
    与 er.md 都没给该数值，故借用一个有出处的值并显式标注它是借用）。

    判别力：两个注入值刻意不同（`X1 != X2`）。若 `timeout_s` 是冻结常量，两次取值必然相同，
    而同一个值不可能同时等于 `X1` 与 `X2`——故这组断言不可能恒真。
    """
    default = float(Settings.model_fields["ai_call_timeout_s"].default)
    first_value = default + 1.5
    second_value = default + 3.75
    assert first_value != second_value

    first = get_policy("OCR", settings=Settings(ai_call_timeout_s=first_value))
    second = get_policy("OCR", settings=Settings(ai_call_timeout_s=second_value))
    assert first.timeout_s == first_value
    assert second.timeout_s == second_value
    assert first.timeout_s != second.timeout_s

    # 默认路径（不注入）同样现读进程配置，而不是回落到行内快照
    assert get_policy("OCR").timeout_s == get_settings().ai_call_timeout_s
    for task_type in sorted(REGISTRY):
        injected = Settings(ai_call_timeout_s=first_value)
        assert get_policy(task_type, settings=injected).timeout_s == first_value


# ---------------------------------------------------------------------------
# §4.12 frozen dataclass / 注册表只读
# ---------------------------------------------------------------------------


def test_task_policy_is_frozen_and_slotted() -> None:
    """§4.12 `TaskPolicy` 是 frozen dataclass：就地改写抛 `FrozenInstanceError`。

    为什么这条重要：注册表是**共享常量**，任一调用方就地改策略会污染所有调用方，
    而改写点与受害点相隔很远、排障成本极高。frozen 让它当场失败而不是静默生效。
    """
    assert is_dataclass(TaskPolicy)
    assert TaskPolicy.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    assert TaskPolicy.__slots__ == (
        "task_type",
        "result_schema",
        "timeout_s",
        "retryable",
        "handler_ref",
        "implemented",
    )

    policy = REGISTRY["OCR"]
    with pytest.raises(FrozenInstanceError):
        policy.timeout_s = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy.retryable = False  # type: ignore[misc]
    assert not hasattr(policy, "__dict__"), "slots 失效：实例能挂上「本次专用」的属性"


def test_registry_is_a_read_only_mapping() -> None:
    """`REGISTRY` 是模块级**只读**常量：就地写入 MUST 失败，否则会污染所有调用方。

    `Final[Mapping[…]]` 只挡得住 mypy；运行期能不能改取决于底层容器，故这里实测。
    """
    assert isinstance(REGISTRY, Mapping)
    with pytest.raises(TypeError):
        REGISTRY["OCR"] = REGISTRY["OCR"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# §4.13 / §3 结构性断言（含判别力自证）
# ---------------------------------------------------------------------------


def test_adding_a_type_does_not_require_touching_the_runner() -> None:
    """§3 注册表是唯一的类型→处理器映射处；`task_runner` MUST NOT 含类型分支。

    判据两条：

    1. `registry.py` 源码里 MUST NOT 出现逐类型分支（`if task_type == …` / `match task_type`），
       类型 → 策略的解析 MUST 是表查找（`REGISTRY[…]`）——保证「新增类型 = 加一行表项」
       而不是「加一个 elif」（design.md:194）；
    2. `core/task_runner.py` 里 MUST NOT 出现任何任务类型字面量。Task 4.7 才实现它，
       本任务时它仍是 1 行 docstring 空壳 → 该条**显式跳过并说明**，MUST NOT 假装验过。

    判据 1 自带判别力自证：本用例内构造「用 elif 链」的合成实现，断言判据**会**把它判红；
    再断言它**不**误伤表查找写法。没有这一步，判据可能只是"扫了个空文件"而已
    —— 若 `find_per_type_branches` 恒返回空，判据 1 在任何代码上都恒绿。

    **跳过与判据 1 的关系**：判据 1 的断言在跳过点**之前**全部执行完毕（断言失败会直接红），
    故判据 2 报 SKIPPED 时判据 1 仍是真验过的。判据 2 的判据本体另有
    `test_runner_literal_scan_is_discriminating` 用合成样本证明其判别力，与空壳与否无关。
    """
    source = _read(REGISTRY_PATH)

    # ---- 判据 1：registry.py 内部无逐类型分支 ----
    branches = find_per_type_branches(source, subject="task_type")
    assert branches == [], (
        f"registry.py 出现逐类型分支 {branches}：类型→策略必须是表查找（REGISTRY[…]），"
        f"否则 M2 新增类型要改的是分支逻辑而不是加一行注册（design.md:194）"
    )

    # 非空下限：判据面对的是有内容的源码，且表查找真的存在（不是"扫了个空文件"）
    tree = ast.parse(source)
    assert "REGISTRY" in _module_level_names(tree), (
        "REGISTRY 不是模块级常量：用例无法对整张表断言（工单 §1 的结构约束）"
    )
    assert _registry_subscripts_in_function(tree, "get_policy"), (
        "get_policy 里找不到 REGISTRY[…] 表查找：类型→策略可能退化成分支或常量展开"
    )

    # ---- 判别力自证：反面样本必须判红 ----
    elif_hits = find_per_type_branches(_SYNTHETIC_ELIF_IMPL, subject="task_type")
    # 精确到行号：四个分支（`if` + 3 个 `elif`，见 _SYNTHETIC_ELIF_IMPL）各命中一处。
    # 只断言"非空"会漏掉"只抓到第一个分支"这种半失效的判据。
    assert [lineno for lineno, _ in elif_hits] == [3, 5, 7, 9], (
        f"判据对 elif 链合成实现失去判别力：报出 {elif_hits}（应逐处命中 3/5/7/9 行）"
    )
    assert {form for _, form in elif_hits} == {"if/elif"}, f"形态标注错：{elif_hits}"
    assert find_per_type_branches(_SYNTHETIC_MATCH_IMPL, subject="task_type"), (
        "判据对 match 形式合成实现失去判别力：`match task_type` 必须判红"
    )

    # ---- 判别力自证：正面样本 MUST NOT 误伤（否则判据在正确实现上恒红，同样无效） ----
    assert find_per_type_branches(_SYNTHETIC_TABLE_LOOKUP, subject="task_type") == [], (
        "判据误伤了表查找写法（成员检查 + 下标）：那样的判据在正确实现上恒红，等于无效判据"
    )

    # ---- 判别力自证（最强一档）：在 registry.py 的**真实源码**上做内存变异，判据必须判红 ----
    #
    # 合成样本证明的是"判据函数能识别 elif 链"；这一段证明的是"把 elif 链放进**这个文件**
    # 也会被判据抓到"——两者的差别正是本组三次假绿的形态（判据看着在验 registry，
    # 实际验的是别的东西/空集）。变异**只在内存里做字符串替换，不落盘**：
    # 本组有过"改 src 文件 + finally 还原"被超时打断、把注入残留在交付文件里的现场，
    # 故此处 MUST NOT 碰磁盘。
    mutation_anchor = "    if task_type not in REGISTRY:"
    injected = (
        '    if task_type == "OCR":\n'
        '        return REGISTRY["OCR"]\n'
        + mutation_anchor
    )
    mutated = source.replace(mutation_anchor, injected, 1)
    assert mutated != source, (
        "内存变异的锚点没匹配上（registry.py 里已无该写法）："
        "自证会退化成空操作，等于没验——这正是要防的假绿形态"
    )
    mutated_hits = find_per_type_branches(mutated, subject="task_type")
    assert mutated_hits, (
        "在 registry.py 真实源码上注入 elif 分支后判据仍报空：判据对该文件失去判别力"
    )

    # ---- 判据 2：task_runner.py 里没有任务类型字面量 ----
    if not RUNNER_PATH.is_file():
        pytest.skip(f"{RUNNER_PATH.name} 尚不存在：Task 4.7 才创建它，本任务没有可扫描的对象")
    runner_source = _read(RUNNER_PATH)
    if not _has_code_beyond_docstring(ast.parse(runner_source)):
        pytest.skip(
            f"{RUNNER_PATH.name} 仍是 docstring 空壳（AST 里除模块 docstring 外没有任何节点）："
            f"扫它等于扫一个空集，此刻下断言只是假绿；Task 4.7 交付执行器后本断言自动生效"
        )
    literals = find_task_type_literals(runner_source, registered_types())
    assert literals == [], (
        f"{RUNNER_PATH.name} 出现任务类型字面量 {literals}：执行器应按注册表表查找解析类型，"
        f"MUST NOT 出现任何逐类型分支（design.md:194）"
    )


def test_runner_literal_scan_is_discriminating() -> None:
    """判据 2 的判据本体：分支式 runner 必须判红，表查找式 runner 必须判绿。

    这条**不跳过**（它扫的是合成样本，与 `task_runner.py` 是否空壳无关）：
    于是即便判据 2 此刻报 SKIPPED，它的判别力也已经被证明过，而不是"因为没对象所以没验"。
    """
    task_types = registered_types()
    branching_runner = (
        "def handle(task):\n"
        '    if task.type == "OCR":\n'
        "        return run_ocr(task)\n"
        '    if task.type == "VISION_REVIEW":\n'
        "        return run_vision(task)\n"
        "    return None\n"
    )
    hits = find_task_type_literals(branching_runner, task_types)
    assert [value for _, value in hits] == ["OCR", "VISION_REVIEW"], (
        f"判据 2 对分支式 runner 失去判别力：报出 {hits}"
    )

    table_runner = "def handle(task):\n    return REGISTRY[task.type].handler_ref\n"
    assert find_task_type_literals(table_runner, task_types) == [], (
        "判据 2 误伤了表查找式 runner：那样的判据在正确实现上恒红"
    )


def test_registry_does_not_import_handler_modules() -> None:
    """§2.3 注册表 MUST NOT 导入处理器本体（`handler_ref` 只是字符串）。

    源码级断言：import 目标里不得出现任何 `handler_ref`；顺带确认没有 provider 依赖
    （`.importlinter` 契约 2：service 层只可与 `provider/base.py` 交互，本任务不应 import
    provider 任何东西）。
    """
    imported = _imported_module_names(_read(REGISTRY_PATH))
    assert imported, "registry.py 一个 import 都没有：解析路径可能已失效"
    for policy in REGISTRY.values():
        offender = sorted(name for name in imported if policy.handler_ref in name)
        assert not offender, (
            f"注册表导入了处理器本体 {offender}（handler_ref={policy.handler_ref!r}）"
        )
    provider_imports = sorted(name for name in imported if name.startswith("aicore.provider"))
    assert not provider_imports, f"registry.py 不应依赖 provider（契约 2）：{provider_imports}"


def test_calling_the_registry_does_not_import_handlers_at_runtime() -> None:
    """§2.3 运行期断言：取策略不会顺带把处理器模块拉进 `sys.modules`。

    只看**增量**（调用前后差集）：处理器若已被别处导入过，那是别处的事，不算在本模块账上。
    """
    before = set(sys.modules)
    for task_type in sorted(REGISTRY):
        get_policy(task_type)
    assert_submittable("OCR")
    imported_now = sorted(set(sys.modules) - before)
    assert not any("ocr_service" in name for name in imported_now), (
        f"取策略时顺带导入了处理器本体：{imported_now}"
    )
