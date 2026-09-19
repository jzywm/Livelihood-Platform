"""机械判据：`pyproject.toml` 里 pytest 的**配置承诺必须真的成立**。

## 为什么需要这条判据（N5）

`pyproject.toml` 的 marker 描述逐字写着「需要真实 MySQL / Redis 的端到端用例，**默认不执行**」，
多份 docstring 与 `openspec` 的 `tasks.md` 也照抄了同一句承诺。而复核者（第 4 批）查清：
`addopts` 里**既没有 `-m` 也没有 collection hook** ⇒ **承诺是空的**，
裸 `pytest`（不带参数）会真的收集并执行集成用例。

这类"文档承诺、配置没兑现"的形态靠人读是看不出来的（两边都是"一句话"），
故用判据把它钉住：**删掉 `addopts` 里的 `-m "not integration"` 本文件即变红**。

## 判据为什么读 `pyproject.toml` 而不是跑一次 pytest

在用例里 `subprocess` 起一个 pytest 会引入一层新的失败形态（环境变量、工作目录、
递归收集），且拖慢默认段。配置是**声明**，判据就直接读那份声明——
"声明里有没有这条"与"pytest 会不会照做"是两件事，后者由 pytest 自己保证
（`-m` 是 pytest 的内建选项）。本文件的判据覆盖前者。

## 为什么 MUST NOT 去掉 `integration` marker（同一处的边界）

`tests/integration/test_main_assembly.py` 确实会构造真实 `RedisLockStore`
（今天不连只是**惰性构造**的偶然）。摘掉 marker 等于把一个会碰 Redis 的用例
放进"默认段 MUST NOT 连 Redis"的段里——那是把承诺修反了方向。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

#: 承诺的默认段过滤表达式（`addopts` 里 MUST 含它）。
DEFAULT_DESELECT = 'not integration'


def _pytest_ini() -> dict[str, object]:
    """现读 `pyproject.toml` 的 `[tool.pytest.ini_options]`（不抄成常量）。"""
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    ini = data.get("tool", {}).get("pytest", {}).get("ini_options")
    assert isinstance(ini, dict), f"{PYPROJECT.name} 里找不到 [tool.pytest.ini_options]"
    return ini


def test_default_addopts_really_deselects_integration_cases() -> None:
    """`addopts` MUST 含 `-m "not integration"` —— 否则"默认不执行"是一句空话。"""
    addopts = _pytest_ini().get("addopts")
    assert isinstance(addopts, str), f"addopts 不是字符串：{addopts!r}"
    assert DEFAULT_DESELECT in addopts, (
        f"addopts={addopts!r} 里没有 `-m \"{DEFAULT_DESELECT}\"`："
        f"marker 描述与多份文档承诺的「默认不执行」就是**空的**，"
        f"裸 `pytest` 会真的去构造 `RedisLockStore`（N5）"
    )


def test_integration_marker_still_registered() -> None:
    """`integration` marker MUST 仍被注册（`--strict-markers` 之外的注册来源就是这里）。

    与上一条同处一地：去掉 marker 会让"默认段不跑集成"变成"集成用例混进默认段"
    ——修承诺不能靠摘掉承诺的对象。
    """
    markers = _pytest_ini().get("markers")
    assert isinstance(markers, list) and markers, f"markers 不是非空列表：{markers!r}"
    assert any(str(entry).startswith("integration:") for entry in markers), (
        f"`integration` marker 没有注册：{markers!r}——"
        f"集成用例会与默认段混在一起（它们会构造真 Redis 客户端）"
    )
