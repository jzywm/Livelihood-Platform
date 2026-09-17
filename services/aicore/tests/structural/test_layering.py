"""分层依赖规则检查。

对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
规则 5、6 见 tests/structural/test_source_guards.py。

阳性/阴性双向验证：契约在干净代码上必须通过；故意注入违规导入后必须失败。
"""

from __future__ import annotations

import importlib
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / ".importlinter"


@pytest.fixture(scope="module")
def lint() -> Callable[..., bool]:
    # 必须先 import importlinter.api：它调用 configuration.configure()，
    # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
    import importlinter.api  # noqa: F401
    from importlinter.application.use_cases import lint_imports

    return lint_imports


def test_layering_contracts_pass(lint: Callable[..., bool]) -> None:
    """干净代码上，全部分层契约必须通过。"""
    assert lint(config_filename=str(CONFIG), no_logo=True) is True


def test_violation_is_detected(lint: Callable[..., bool]) -> None:
    """阴性用例：往 api 层注入一处违规导入，契约必须变红。"""
    target = PROJECT_ROOT / "src" / "aicore" / "api" / "routes_probe.py"
    target.write_text(
        "from aicore.repository import task_repo  # 故意违规：api 不得直连 repository\n",
        encoding="utf-8",
    )
    try:
        importlib.invalidate_caches()
        assert lint(config_filename=str(CONFIG), no_logo=True) is False
    finally:
        target.unlink()
        importlib.invalidate_caches()
        shutil.rmtree(PROJECT_ROOT / ".import_linter_cache", ignore_errors=True)

    assert lint(config_filename=str(CONFIG), no_logo=True) is True
