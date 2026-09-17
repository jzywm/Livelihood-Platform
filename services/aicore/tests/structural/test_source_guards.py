"""结构扫描专项：import-linter 表达不了的两条合规红线。

规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
        的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
确需吞异常时必须在该 except 行写 `# ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
理由必填：光有指令没有理由不算豁免（MUST NOT 用裸指令绕过检查）。
兼容写法：`# noqa: ai-allow-swallow: <理由>` 同样被接受，便于沿用早期文档口径；
但 `noqa:` 前缀会让 ruff 报 "Invalid `# noqa` directive" 警告（退出码仍为 0），
新代码请用不带 noqa 前缀的写法。

规则 6 已知边界（有意接受，见 find_swallowed_exceptions 的注释）：
条件式重新抛出（`if strict: raise`）按「已包含 raise」放行；
嵌套 def/lambda/class 内的 raise 不算数。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src" / "aicore"

# 只允许在 provider/ 包内出现的模型调用库
MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
HTTP_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
)

# 规则 5 的非空下限：低于此值说明扫描范围塌了（路径写错、包被搬走），
# 参数化用例会静默收集到 0 个用例而全绿——那种"绿"没有任何意义。
MIN_SCANNED_FILES = 20

GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")

# 豁免指令：`# ai-allow-swallow: <理由>`；理由必填（`\S+`），裸指令一律不豁免。
SWALLOW_EXEMPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*ai-allow-swallow:\s*\S+"),
    re.compile(r"#\s*noqa:\s*ai-allow-swallow:\s*\S+"),
)

# 不进入扫描的嵌套作用域：这些节点有自己的执行流，里面的 raise 不代表
# 外层 except 会重新抛出。
NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def iter_python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def iter_handler_flow(node: ast.AST) -> Iterator[ast.AST]:
    """遍历 except 处理块自身语句流中的节点，不进入任何嵌套作用域。

    - 嵌套 def / lambda / class 各有独立执行流：它们里面的 raise 与「本处理块是否
      重新抛出」无关，故到此为止不再下探；
    - 内层 `try/except` 的处理块同理：内层 except 自己的 raise 是内层重新抛出，
      不能算作外层重新抛出（每个处理块都单独判定，偏严）。
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*NESTED_SCOPE_NODES, ast.ExceptHandler)):
            continue
        yield child
        yield from iter_handler_flow(child)


def find_swallowed_exceptions(source: str) -> list[int]:
    """返回「except 块内不含 raise」的行号列表（即静默降级点）。

    只统计处理块自身的语句流（见 iter_handler_flow），因此：
    - 嵌套函数 / lambda / 类里的 raise **不算**本处理块重新抛出 → 仍判违规（偏严）；
    - 条件式重新抛出（`if strict: raise`）算已重新抛出 → 放行。
      这是**有意接受的边界**：AST 层面无法证明 `if` 条件恒假，若连它一起判违规，
      偏严就会变成"任何带条件的重新抛出都要写豁免"，反而促使作者删掉判断；
      代价是「写了 raise 但条件恒不成立」这类隐性吞异常扫描不到，由人工评审兜住。
    """
    hits: list[int] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not any(isinstance(inner, ast.Raise) for inner in iter_handler_flow(node)):
            hits.append(node.lineno)
    return sorted(hits)


def has_swallow_exemption(line: str) -> bool:
    """该行是否带规则 6 的显式豁免（理由必填）。"""
    return any(pattern.search(line) for pattern in SWALLOW_EXEMPT_PATTERNS)


@pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_model_http_calls_only_in_provider(path: Path) -> None:
    """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
    if path.parts[len(SRC.parts)] == "provider":
        pytest.skip("provider 包是唯一允许发起外部模型调用的层")
    text = path.read_text(encoding="utf-8")
    found = HTTP_IMPORT_RE.findall(text)
    assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"


def test_rule_5_scan_is_not_vacuous() -> None:
    """规则 5 的非空下限：扫描范围塌掉时必须报警，而不是静默全绿。"""
    files = iter_python_files()
    assert len(files) >= MIN_SCANNED_FILES, (
        f"规则 5 只扫到 {len(files)} 个 .py（下限 {MIN_SCANNED_FILES}）："
        f"扫描根 {SRC} 可能已失效，参数化用例会静默变成空集"
    )
    scanned = [p for p in files if p.parts[len(SRC.parts)] != "provider"]
    assert scanned, "规则 5 没有任何参与断言的模块（非 provider 文件为空）"


@pytest.mark.parametrize("relative", GUARDED_FILES)
def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
    """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
    path = SRC / relative
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    offenders = [
        lineno
        for lineno in find_swallowed_exceptions(source)
        if not has_swallow_exemption(lines[lineno - 1])
    ]
    assert not offenders, (
        f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
        f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
        f"`# ai-allow-swallow: <理由>` 显式豁免（理由必填）。"
    )


def test_guard_detects_swallowing() -> None:
    """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
    bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
    good = (
        "def f():\n    try:\n        return 1\n"
        "    except Exception as exc:\n        raise RuntimeError() from exc\n"
    )
    assert find_swallowed_exceptions(bad) == [4]
    assert find_swallowed_exceptions(good) == []


def test_guard_ignores_raise_inside_nested_scope() -> None:
    """嵌套作用域里的 raise 不算处理块重新抛出：外层吞异常仍须被检出。

    修复前的实现用 ast.walk 全深度下探，嵌套 def 里的 raise 会把外层处理块
    误判为"已重新抛出"——这是静默漏报，与「偏严」取向相反。
    """
    nested_def = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        def _swallow():\n"
        "            raise RuntimeError('与本次处理无关')\n"
        "        _swallow()\n"
        "        return None\n"
    )
    assert find_swallowed_exceptions(nested_def) == [4]

    nested_lambda = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        handler = lambda: exec('raise RuntimeError()')\n"
        "        handler()\n"
        "        return None\n"
    )
    assert find_swallowed_exceptions(nested_lambda) == [4]

    nested_class = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        class _Swallow:\n"
        "            raise RuntimeError('类体，与本次处理无关')\n"
        "        return None\n"
    )
    assert find_swallowed_exceptions(nested_class) == [4]

    nested_try = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        try:\n"
        "            pass\n"
        "        except ValueError:\n"
        "            raise\n"
        "        return None\n"
    )
    # 外层 except（第 4 行）吞异常 → 违规；内层 except（第 7 行）自己 raise → 不违规。
    assert find_swallowed_exceptions(nested_try) == [4]


def test_guard_accepts_conditional_reraise() -> None:
    """有意接受的边界：条件式重新抛出按「已重新抛出」放行（见函数 docstring）。"""
    conditional = (
        "def f(strict: bool):\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        if strict:\n"
        "            raise\n"
        "        return None\n"
    )
    assert find_swallowed_exceptions(conditional) == []


def test_exemption_requires_reason() -> None:
    """豁免指令必须带理由：裸指令不算豁免（守住 SWALLOW_EXEMPT 不放松）。"""
    assert has_swallow_exemption("except Exception:  # ai-allow-swallow: 脱敏失败已降级上报")
    assert has_swallow_exemption("except Exception:  # noqa: ai-allow-swallow: 兼容写法，理由必填")
    assert not has_swallow_exemption("except Exception:  # ai-allow-swallow:")
    assert not has_swallow_exemption("except Exception:  # ai-allow-swallow")
    assert not has_swallow_exemption("except Exception:  # noqa: ai-allow-swallow")
    assert not has_swallow_exemption("except Exception:")


def test_exempted_handler_is_not_reported() -> None:
    """规则 6 豁免通道的端到端小样：带理由的豁免真的能让扫描放行。"""
    source = (
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:  # ai-allow-swallow: 已上报并转为默认值\n"
        "        return 2\n"
    )
    lines = source.splitlines()
    offenders = [
        lineno
        for lineno in find_swallowed_exceptions(source)
        if not has_swallow_exemption(lines[lineno - 1])
    ]
    assert offenders == []


def test_guarded_files_exist_and_are_scanned() -> None:
    """非空下限：受检文件必须存在，否则规则 6 会静默变空。"""
    missing = [relative for relative in GUARDED_FILES if not (SRC / relative).is_file()]
    assert not missing, f"规则 6 的受检文件缺失：{missing}"
