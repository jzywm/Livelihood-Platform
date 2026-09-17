"""结构扫描专项：import-linter 表达不了的两条合规红线。

规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
        的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
确需吞异常时必须写 `# noqa: ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src" / "aicore"

# 只允许在 provider/ 包内出现的模型调用库
MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
HTTP_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
)

GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")
SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")


def iter_python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def find_swallowed_exceptions(source: str) -> list[int]:
    """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
    hits: list[int] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        raises = any(isinstance(inner, ast.Raise) for stmt in node.body for inner in ast.walk(stmt))
        if not raises:
            hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_model_http_calls_only_in_provider(path: Path) -> None:
    """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
    if path.parts[len(SRC.parts)] == "provider":
        pytest.skip("provider 包是唯一允许发起外部模型调用的层")
    text = path.read_text(encoding="utf-8")
    found = HTTP_IMPORT_RE.findall(text)
    assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"


@pytest.mark.parametrize("relative", GUARDED_FILES)
def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
    """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
    path = SRC / relative
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    offenders = [
        lineno
        for lineno in find_swallowed_exceptions(source)
        if not SWALLOW_EXEMPT.search(lines[lineno - 1])
    ]
    assert not offenders, (
        f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
        f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
        f"`# noqa: ai-allow-swallow: <理由>` 显式豁免。"
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
