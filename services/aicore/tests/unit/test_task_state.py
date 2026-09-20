"""任务状态机（纯函数）契约用例。Task 4.5 §3 的第 1~8 条。

## 本文件的取向：**期望值现读权威文档，不抄成常量**

第 3 组 `<= MAX_ID_LENGTH` 的假绿教训：把权威表述抄进用例后，用例就只剩「抄得对不对」，
文档改了、表改了，两边一起错也照样全绿。故 `er.md` §7.1 的状态机那一行是**现读**的：
`_er_state_machine()` 打开文件、切出 §7.1 一节、用正则解析出「起点」与「目标集合」，
再与 `state.py` 的表逐项比对（第 7 条）。合法转移那一条（第 1 条）也直接用解析结果参数化，
而不是用模块里的常量——否则它测的是「常量与它自己一致」。

## 码值为什么逐条钉死

非法转移 MUST 是 `3007`（状态不允许该操作）、未知取值 MUST 是 `1003`（枚举或范围非法），
两条都写死字面量：它们是**平台错误码表**里的定档值（`_common/openapi.yaml` 的 `ErrorCode`），
不是本模块可以自行发明的数字。`3007` 用 `1003` 会把「任务已终态」说成「你参数写错了」，
前端据此提示用户改参数，而真正的处置是「去看已有结论」。
"""

from __future__ import annotations

import ast
import re
from itertools import permutations
from pathlib import Path

import pytest

from aicore.core.errors import CONFLICT_CODE, PARAM_VALUE_CODE, ConflictError, ParamError
from aicore.service.task.state import (
    ALL_STATUSES,
    ALLOWED_TRANSITIONS,
    FAILED,
    MANUAL_REVIEW,
    PROCESSING,
    SUCCEEDED,
    TERMINAL_STATUSES,
    IllegalTransitionError,
    assert_transition,
    is_terminal,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ER_MD = PROJECT_ROOT / "docs" / "er.md"
STATE_PY = PROJECT_ROOT / "src" / "aicore" / "service" / "task" / "state.py"

#: `er.md` 的两节标题：用它切出 §7.1（`ai_task`）这一节。
#: **必须切节**：`er.md` 里共 3 处「状态机 X→Y/…」表述（§7.1 `ai_task`、§7.4 `vision_review`、
#: §7.6 `kitchen_anomaly`），全文正则会同时命中三条，于是「恰好一处」这条断言会假红。
ER_SECTION_7_1 = "### 7.1 ai_task"
ER_SECTION_7_2 = "### 7.2 ocr_result"

#: 状态机表述：`状态机 PROCESSING→SUCCEEDED/FAILED/MANUAL_REVIEW`。
STATE_MACHINE_PATTERN = re.compile(r"状态机\s*([A-Z_]+)\s*→\s*([A-Z_/]+)")

#: `state.py` 允许出现的第三方顶层包（一个都不许）。
FORBIDDEN_TOP_LEVEL = ("sqlalchemy",)
#: `state.py` 允许出现的 `aicore.*` 包（只有 `aicore.core.errors`）。
FORBIDDEN_AICORE_PREFIXES = ("aicore.repository", "aicore.provider")


def _er_state_machine() -> tuple[str, frozenset[str]]:
    """从 `er.md` §7.1 **现读**状态机表述 → `(起点, 目标集合)`。

    实现上先切节再匹配，并断言**恰好一处**：切节失败（标题被改名）会 `ValueError`，
    匹配数不为 1 会断言失败——两种都不会静默变成「空期望值」（那会让下面的比对恒真）。
    """
    text = ER_MD.read_text(encoding="utf-8")
    section = text[text.index(ER_SECTION_7_1) : text.index(ER_SECTION_7_2)]
    assert "uk_idem" in section, (
        f"切出的 §7.1 片段里没有 uk_idem，切片可能已失效（{ER_SECTION_7_1!r} 的边界变了）"
    )
    matches = STATE_MACHINE_PATTERN.findall(section)
    assert len(matches) == 1, f"§7.1 里的状态机表述应恰好一处，实际 {len(matches)} 处：{matches}"
    source, targets = matches[0]
    return source, frozenset(targets.split("/"))


def test_legal_transitions_from_processing_are_accepted() -> None:
    """第 1 条：`PROCESSING → SUCCEEDED / FAILED / MANUAL_REVIEW` 三条逐条通过。

    参数化用**现读**的目标集合，而不是模块常量：这样「表里少了某条合法边」会被抓到，
    而用常量参数化只能证明「表与它自己一致」。
    """
    source, targets = _er_state_machine()
    assert len(targets) == 3, f"er.md 的合法目标应恰好 3 个，实际 {sorted(targets)}"
    for target in sorted(targets):
        assert_transition(source, target)  # 不抛异常即合法


def test_all_six_terminal_to_terminal_transitions_are_rejected() -> None:
    """第 2 条：三个终态两两之间的**全部 6 条**转移被拒（`3007`）。

    先断言组合数是 6，再逐条断言——「6」这个数字写出来是为了防止终态集合被改小之后
    本用例悄悄少测几条（那时它仍会全绿）。
    """
    pairs = list(permutations(sorted(TERMINAL_STATUSES), 2))
    assert len(pairs) == 6, f"终态两两有序组合应恰好 6 条，实际 {len(pairs)}：{pairs}"
    for current, target in pairs:
        with pytest.raises(IllegalTransitionError) as excinfo:
            assert_transition(current, target)
        assert excinfo.value.code == CONFLICT_CODE == 3007, (
            f"{current}→{target} 的码值不是 3007（状态不允许该操作）：收到 {excinfo.value.code}"
        )
        assert isinstance(excinfo.value, ConflictError)


def test_terminal_states_cannot_reopen_to_processing() -> None:
    """第 3 条：三个终态各自 → `PROCESSING` 被拒（防「重开」）。"""
    for terminal in sorted(TERMINAL_STATUSES):
        with pytest.raises(IllegalTransitionError) as excinfo:
            assert_transition(terminal, PROCESSING)
        assert excinfo.value.code == CONFLICT_CODE


def test_self_transitions_are_rejected_including_processing() -> None:
    """第 4 条：同状态自转移被拒（含 `PROCESSING → PROCESSING`）。

    覆盖全部四个合法状态：自转移不改变任何事实，却会刷新 `progress` / `finished_at`
    这类副作用列，故必须与「终态→终态」同样被拒。
    """
    assert {PROCESSING, SUCCEEDED, FAILED, MANUAL_REVIEW} == ALL_STATUSES
    for status_value in sorted(ALL_STATUSES):
        with pytest.raises(IllegalTransitionError) as excinfo:
            assert_transition(status_value, status_value)
        assert excinfo.value.code == CONFLICT_CODE


def test_unknown_status_value_is_param_error_1003_not_conflict() -> None:
    """第 5 条：未知 `current` / 未知 `target` → `1003`（**不是** `3007`）。

    两档语义不同：`1003` 是「你给了一个不存在的状态」，`3007` 是「服务端已有状态不允许」。
    把未知取值判成 `3007` 会把调用方引向「去查已有结论」而不是「改你的取值」。
    """
    with pytest.raises(ParamError) as current_exc:
        assert_transition("RUNNING", PROCESSING)
    assert current_exc.value.code == PARAM_VALUE_CODE == 1003
    assert not isinstance(current_exc.value, ConflictError), (
        "未知 current 被判成了状态冲突（3007）：两档错误语义必须分开"
    )

    with pytest.raises(ParamError) as target_exc:
        assert_transition(PROCESSING, "RUNNING")
    assert target_exc.value.code == PARAM_VALUE_CODE
    assert not isinstance(target_exc.value, ConflictError)


def test_is_terminal_only_for_the_declared_terminal_statuses() -> None:
    """第 6 条：三个终态为真，`PROCESSING` 与未知值为假。

    未知值为假是刻意的（`is_terminal` 是**判定**不是**校验**）：
    调用方用它决定「要不要继续推进」，而「不认识」与「还能推进」都意味着别停。
    """
    for terminal in sorted(TERMINAL_STATUSES):
        assert is_terminal(terminal) is True
    assert is_terminal(PROCESSING) is False
    for unknown in ("", "RUNNING", "processing", "SUCCEEDED "):
        assert is_terminal(unknown) is False, f"未知取值 {unknown!r} 被判成了终态"


def test_transition_table_matches_er_md_verbatim() -> None:
    """第 7 条：`ALLOWED_TRANSITIONS` / `TERMINAL_STATUSES` 与 `er.md` §7.1 **现读**一致。

    双向都比：表里 MUST NOT 多出第二个起点、MUST NOT 多出目标、MUST NOT 少目标
    （单比一个方向会放过「多登记了一条边」）。
    """
    source, targets = _er_state_machine()
    assert set(ALLOWED_TRANSITIONS) == {source}, (
        f"状态机只允许 {source} 作为起点，表里的起点却是 {sorted(ALLOWED_TRANSITIONS)}"
    )
    assert ALLOWED_TRANSITIONS[source] == targets
    assert targets == TERMINAL_STATUSES
    assert targets | {source} == ALL_STATUSES


def _imported_modules(source: str) -> list[str]:
    """源码里出现的模块名（`import x` 与 `from x import y` 两种形态）。"""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def _offending_imports(source: str) -> list[str]:
    """越界导入：第三方包（`sqlalchemy`）与 `aicore.repository` / `aicore.provider`。"""
    return sorted(
        module
        for module in _imported_modules(source)
        if module.split(".")[0] in FORBIDDEN_TOP_LEVEL
        or module.startswith(FORBIDDEN_AICORE_PREFIXES)
    )


def test_state_module_is_pure_and_depends_only_on_core_errors() -> None:
    """第 8 条（AST 断言）：`state.py` 不 import `sqlalchemy` / repository / provider。

    为什么用 AST 而不是 grep：字符串里出现 `sqlalchemy`（注释、docstring）不算依赖，
    grep 会假红；而 AST 看的是真正的 import 语句。
    """
    source = STATE_PY.read_text(encoding="utf-8")
    assert source.strip(), "state.py 内容为空：下面的扫描会退化成空断言"

    offending = _offending_imports(source)
    assert offending == [], f"state.py 出现了越界导入 {offending}（纯函数层不得碰仓储与通道）"

    aicore_modules = {m for m in _imported_modules(source) if m.startswith("aicore")}
    assert aicore_modules == {"aicore.core.errors"}, (
        f"state.py 的 aicore 依赖应只有 aicore.core.errors，实际 {sorted(aicore_modules)}"
    )


def test_import_scanner_discriminates() -> None:
    """阴性对照：上面的扫描器必须能检出违规样本，否则第 8 条恒真。

    （本项目反复出现的形态：判据写错时用例仍全绿。这条把「判据有判别力」本身钉住。）
    """
    sample = (
        "import sqlalchemy\n"
        "from aicore.repository import task_repo\n"
        "from aicore.provider import mock\n"
        "from aicore.core.errors import ParamError\n"
    )
    # 结果是排序过的（判据按模块名字典序输出，便于失败信息稳定）。
    assert _offending_imports(sample) == [
        "aicore.provider",
        "aicore.repository",
        "sqlalchemy",
    ]
