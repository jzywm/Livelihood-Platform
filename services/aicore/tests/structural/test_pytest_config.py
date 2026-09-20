"""机械判据：`pyproject.toml` 里 pytest 的**配置承诺必须真的成立**。

## 为什么需要这条判据（N5）

`pyproject.toml` 的 marker 描述逐字写着「需要真实 MySQL / Redis 的端到端用例，**默认不执行**」，
多份 docstring 与 `openspec` 的 `tasks.md` 也照抄了同一句承诺。而复核者（第 4 批）查清：
`addopts` 里**既没有 `-m` 也没有 collection hook** ⇒ **承诺是空的**，
裸 `pytest`（不带参数）会真的收集并执行集成用例。

这类"文档承诺、配置没兑现"的形态靠人读是看不出来的（两边都是"一句话"），
故用判据把它钉住：**删掉 `addopts` 里的 `-m "not integration"` 本文件即变红**。

## 判据必须**按 argparse 语义**解析，不能做子串包含（B3）

第一版是 `assert '-m "not integration"' in addopts` —— 复核者用一个坏配置证明它可被满足：

```
addopts = -q -m "not integration" -m integration     ← 子串在，判据绿
裸收集：50/1354 collected (50 deselected)            ← 承诺实际已经失效
```

根因：`-m` 是 argparse 的 `store` 动作，**后者覆盖前者**（`-m "not integration_typo"` 同理）。
故现在用 `shlex.split`（它才懂引号）分词后断言 **`-m` 恰好出现一次、且值恰为 `not integration`**。

## 判据为什么读 `pyproject.toml` 而不是跑一次 pytest

在用例里 `subprocess` 起一个 pytest 会引入一层新的失败形态（环境变量、工作目录、
递归收集），且拖慢默认段。配置是**声明**，判据就直接读那份声明——
"声明里有没有这条"与"pytest 会不会照做"是两件事，后者由 pytest 自己保证
（`-m` 是 pytest 的内建选项）。本文件的判据覆盖前者。

## ⚠ `-o addopts=""` 会**静默解除**这条承诺（B4，写在这里给人看见）

本任务的门禁命令用 `-o addopts=""` 是为了**看清汇总行**（ini 里的 `-q` 会被清掉），
但它**同时清掉了 `-m "not integration"`** —— 于是那一次运行会**恢复 50 条真连
Redis / MySQL 的集成用例**（实测：裸收集从 `1304 collected / 50 deselected`
变成 `1354 collected`）。

- 这条本身**不是缺陷**（`-o` 的语义就是"覆盖这一项 ini 设置"），但它**没有任何提示**；
- 故凡是要跑"默认段"的命令，`-m "not integration"` **必须由 CLI 显式给出**；
- 仓库内目前**没有任何命令/文档在用 `-o addopts=""`**（已确认），既有门禁不受影响——
  这句话是写给**将来的**命令作者看的。

## 为什么 MUST NOT 去掉 `integration` marker（同一处的边界）

`tests/integration/test_main_assembly.py` 确实会构造真实 `RedisLockStore`
（今天不连只是**惰性构造**的偶然）。摘掉 marker 等于把一个会碰 Redis 的用例
放进"默认段 MUST NOT 连 Redis"的段里——那是把承诺修反了方向。
"""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

#: 承诺的默认段过滤表达式：`-m` MUST **恰好一次**取这个值（不是"子串出现"，见 B3）。
DEFAULT_DESELECT = "not integration"

#: `-m` 这个短选项：分开写（`-m EXPR`）与贴着写（`-mEXPR`）都是同一个选项。
_M_FLAG = "-m"


def _pytest_ini() -> dict[str, object]:
    """现读 `pyproject.toml` 的 `[tool.pytest.ini_options]`（不抄成常量）。"""
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    ini = data.get("tool", {}).get("pytest", {}).get("ini_options")
    assert isinstance(ini, dict), f"{PYPROJECT.name} 里找不到 [tool.pytest.ini_options]"
    return ini


def _m_filter_values(addopts: str) -> list[str]:
    """`addopts` 里**每一个** `-m` 选项的取值（按 argparse 语义：可重复，后者覆盖前者）。

    用 `shlex.split` 而不是 `str.split`：只有前者懂引号，
    故 `-m "not integration"` 被切成 `['-m', 'not integration']` 两个 token
    （`str.split` 会给出 `['-m', '"not', 'integration"']`，于是判据要么写错、
    要么退化成子串匹配 —— 那正是 B3 要修掉的东西）。
    """
    tokens = shlex.split(addopts)
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == _M_FLAG:
            assert index + 1 < len(tokens), f"`-m` 后面没有取值：{addopts!r}"
            values.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith(_M_FLAG) and len(token) > len(_M_FLAG):
            # 贴着写：`shlex` 把 `-m"not integration"` 切成 `-mnot integration` 一个 token。
            values.append(token[len(_M_FLAG) :])
        index += 1
    return values


def _assert_default_deselects_integration(addopts: str) -> None:
    """**判据本体（B3）**：`-m` 恰好一次，且值恰为 `not integration`。

    抽成函数是为了让判别力自证把**合成的坏配置**喂给它（同一份判据），
    而不是让自证复制一份判据——复制出来的判据与真判据会各自漂移。
    """
    values = _m_filter_values(addopts)
    assert len(values) == 1, (
        f"addopts={addopts!r} 里 `-m` 出现了 {len(values)} 次（取值 {values}）："
        f"pytest 的 `-m` 是 argparse 的 store 动作，**后者覆盖前者** ——"
        f"多出来的那一次会让「默认不执行集成用例」这条承诺静默失效（B3）"
    )
    assert values[0] == DEFAULT_DESELECT, (
        f"addopts={addopts!r} 里 `-m` 的取值是 {values[0]!r}，不是 {DEFAULT_DESELECT!r}："
        f"marker 描述与多份文档承诺的「默认不执行」就是**空的**"
        f"（`not integration_typo` 这类拼写错同样会让筛选失效）"
    )


def test_default_addopts_really_deselects_integration_cases() -> None:
    """`addopts` MUST 让 `-m` **恰好一次**取 `not integration` —— 否则"默认不执行"是一句空话。"""
    addopts = _pytest_ini().get("addopts")
    assert isinstance(addopts, str), f"addopts 不是字符串：{addopts!r}"
    _assert_default_deselects_integration(addopts)


def test_default_deselect_criterion_discriminates() -> None:
    """**B3 的判别力自证**：三种坏配置都**必须**让判据变红（合成输入，不落盘）。

    | 坏配置 | 为什么**子串**判据会放行、而本判据拦得住 |
    |---|---|
    | `-q -m "not integration" -m integration` | 复核者实测的形态：子串在，但**后者覆盖前者** |
    | `-q -m "not integration_typo"` | `not integration` 是它的**子串** |
    | `-q -m integration` | 完全反了，但整段 `-m "not integration"` 的子串 `-m integration` 在 |

    后两条阳性对照（两种合法写法）保证判据**不是一律判红**——
    否则"能判红"可能只是"它总在抛错"，那同样是零判别力。
    """
    with pytest.raises(AssertionError, match="后者覆盖前者"):
        _assert_default_deselects_integration('-q -m "not integration" -m integration')
    with pytest.raises(AssertionError, match="不是"):
        _assert_default_deselects_integration('-q -m "not integration_typo"')
    with pytest.raises(AssertionError, match="不是"):
        _assert_default_deselects_integration("-q -m integration")

    # 阳性对照：分开写与贴着写都必须通过。
    _assert_default_deselects_integration('-q -m "not integration"')
    _assert_default_deselects_integration("-q -m'not integration'")


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
