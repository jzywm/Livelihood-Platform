"""机械判据：**每个测试文件"声称的睡眠豁免数"必须等于它的实际豁免数**。

## 为什么需要这条判据（N2 的修法）

工单 §2.5 硬约束 3 禁止测试内 `asyncio.sleep`，`scripts/group3_acceptance.py` 第 4 项
以"AST 扫描 + 行级豁免 `# ai-allow-sleep: <理由>`"承载它。豁免数因此成了一个**会被引用的数字**：
多份 docstring 用"共 N 处豁免""只有一处 sleep"来交代本文件的等待策略。

复核者的普查结论：**这些数字全部漂了**（`test_cpu_pool.py` 声称 2、实际 3；
`test_lease_redis.py` 声称 1、实际 2；`test_task_runner.py` 声称"没有 sleep"、实际 12）。
人写的数字一定会再漂——所以**数字必须由判据自己核对**，而不是靠下次评审再普查一遍。

## 判据（逐文件，两种取数方式）

1. **本任务可写的文件**：docstring 里 MUST 有一行
   `睡眠豁免：<N> 处（机械判据逐文件比对）`，且 `N` == AST 数出来的实际豁免数。
   把数字放在**被测文件自己的 docstring** 里，是为了让"改代码的人"和"看到数字的人"
   处在同一屏——改了一处豁免却忘了改数字，本判据立刻红。
2. **`READ_ONLY_TEST_FILES` 里的文件**：它们属于别的任务的既有实现，
   本任务的写权限被工单 §1 明确排除（"`tests/` 下除指名的那一条用例之外的既有文件"不可改），
   故**只读核对**：实际豁免数 MUST 等于本表里的数字。表变了/代码变了都会红，
   只是修法不同（前者是"另一个任务的改动被看见了"，后者是"本判据的表过期了"）。

实际豁免数的取法与 `scripts/group3_acceptance.py` 第 4 项**同构**：
AST 里凡是 `sleep` 调用（`Attribute.attr == "sleep"` 或 `Name.id == "sleep"`），
其所在行若匹配豁免正则即计入（每个调用一行，故"一处豁免"= 一个被豁免的 sleep 调用）。
两套实现**故意不共享代码**：判据脚本要能在测试套件之外单独运行（验收场景），
共享一个模块反而会让两者一起失效而无人察觉。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS = PROJECT_ROOT / "tests"

#: 豁免正则：与 `scripts/group3_acceptance.py` 第 4 项逐字同构（理由必填：`\S+`）。
EXEMPTION = re.compile(r"#\s*(?:noqa:\s*)?ai-allow-sleep:\s*\S+")

#: 各文件 docstring 里 MUST 出现的声明行（`<N>` 与实际豁免数比对）。
CLAIM = re.compile(r"睡眠豁免：(\d+) 处")

#: 本任务**无写权限**的既有测试文件 → 其实际豁免数（只读核对，见模块 docstring）。
#:
#: 依据：工单 `task-4.7-fix-brief.md` §1 末尾"仍然不可改……以及 `tests/` 下
#: **除第 3 条指名的那一条用例之外**的既有文件"。
READ_ONLY_TEST_FILES: dict[str, int] = {
    "test_provider_guard.py": 2,
    "test_provider_mock.py": 1,
    "test_provider_selector.py": 1,
}


def iter_test_files() -> list[Path]:
    """全部测试文件（跳过缓存目录）。"""
    return sorted(p for p in TESTS.rglob("*.py") if "__pycache__" not in p.parts)


def exempted_sleep_lines(path: Path) -> list[int]:
    """该文件里**被豁免的 `sleep` 调用**所在行号（1 起）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    hits: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        is_sleep_call = (isinstance(node, ast.Attribute) and node.attr == "sleep") or (
            isinstance(node, ast.Name) and node.id == "sleep"
        )
        if is_sleep_call and EXEMPTION.search(lines[node.lineno - 1]):
            hits.append(node.lineno)
    return hits


def test_every_test_file_agrees_with_its_own_sleep_exemption_count() -> None:
    """逐文件核对"声称的豁免数"与实际豁免数（见模块 docstring 的两种取数方式）。"""
    scanned = 0
    with_exemptions = 0
    for path in iter_test_files():
        scanned += 1
        actual = len(exempted_sleep_lines(path))
        expected_in_table = READ_ONLY_TEST_FILES.get(path.name)
        if expected_in_table is not None:
            assert actual == expected_in_table, (
                f"{path.name} 的实际睡眠豁免数为 {actual}，"
                f"与只读核对的期望 {expected_in_table} 不符——"
                f"该文件属别的任务的既有实现（本任务无写权限），"
                f"它变了就必须由**改动它的人**更新这张表，MUST NOT 悄悄放过"
            )
            with_exemptions += 1
            continue

        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        claim = CLAIM.search(docstring)
        if actual == 0:
            assert claim is None, (
                f"{path.name} 的 docstring 声明了 {claim.group(1)} 处睡眠豁免，"
                f"但实际一处都没有——这是**过期的声明**，删掉它（或补上豁免）"
            )
            continue
        with_exemptions += 1
        assert claim is not None, (
            f"{path.name} 有 {actual} 处睡眠豁免（`# ai-allow-sleep:`），"
            f"但 docstring 里没有 `睡眠豁免：{actual} 处` 这一行——"
            f"豁免数是会被引用的数字，MUST 由被测文件自己声明，"
            f"否则它一定会漂（N2 的普查结论）"
        )
        assert int(claim.group(1)) == actual, (
            f"{path.name} 的 docstring 声称 {claim.group(1)} 处睡眠豁免，实际 {actual} 处——"
            f"改豁免时请同步改这一行（本判据就是为了拦住这种漂移）"
        )

    # 空扫描自证：路径写错/目录被搬走时本判据会"全绿"，故要求扫到的文件数不为零。
    assert scanned > 0, f"没有扫到任何测试文件：{TESTS} 的路径不对"
    # 下界同时是"豁免确实存在于本仓库"的证据：若豁免全被删掉，上面 actual>0 的分支就不执行了，
    # 本判据会变成永远为真的空判据。
    assert with_exemptions >= 5, (
        f"只核对了 {with_exemptions} 个含豁免的文件（期望 ≥5）："
        f"豁免可能被大批删除，或本判据的扫描范围坏了"
    )
