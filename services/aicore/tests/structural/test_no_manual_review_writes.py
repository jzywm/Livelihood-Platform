"""机械判据：**没有任何代码路径会把任务置成 `MANUAL_REVIEW`**（Task 4.11 §3.5）。

## 为什么需要这条判据（控制者裁定 (a) 的守备）

用户 2026-09-20 裁定 **(a)：M1 不使用 `MANUAL_REVIEW`**——

- `4003` 与 `5002` **都是** `status = FAILED` + `error_code = 对应码`；
- "**已转人工**"是 `4003` 这个码**自带的语义**（`er.md:329` 逐字），**不是**状态迁移；
- "人工复核队列" = 运维按 `error_code` 的查询视图（`WHERE status='FAILED' AND error_code='4003'`），
  M1 不新建队列表、不新增状态；
- `MANUAL_REVIEW` 作为第四态保留在枚举与状态机里，**M1 无触发者**，留给 M2。

依据：`error_code` 在 `er.md:26`/`:329` **两处**都被定义为「**FAILED** 业务码」，
`design.md:210` 亦写「置 `FAILED` 并转人工复核队列」；选 (b)/(c) 都要反过来改这三处口径。

**为什么要机械化**：这是一条"**将来才可能被违反**"的约定——M2 接视觉审核时，
最自然的动作就是顺手把 `4003` 接到 `MANUAL_REVIEW` 上，而那会推翻本裁定且没人会注意到。
判据必须能判红（见 `test_manual_review_write_guard_discriminates`）。

## 判据的边界（**刻意取窄**，与裁定逐字一致）

- `state.py` **定义**该常量、`ALLOWED_TRANSITIONS` **包含**它 ⇒ **合法**（M2 的预留态）；
- `api/tasks.py` 的 `TaskStatusValue` / `DECLARED_STATUSES` 是**读侧**声明 ⇒ **合法**；
- `repository/models.py` 的 `Enum(..., "MANUAL_REVIEW", ...)` 是**列定义** ⇒ **合法**；
- 被拦的是**把它当成写回目标**：`MANUAL_REVIEW` 出现在
  `update_status` / `status_update_statement` / `mark_failed` / `mark_succeeded` /
  `requeue` / `begin_attempt` / `_write_back` 这些**写回调用**的实参里
  （**标识符**与**字符串字面量**两种形态都拦——`status="MANUAL_REVIEW"` 与
  `status=MANUAL_REVIEW` 是同一件事的两种写法）。
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src" / "aicore"

#: **写回调用**的方法名白名单：这些调用的实参里一旦出现 `MANUAL_REVIEW` 就是违规。
#:
#: 覆盖全仓的四条写回链路：
#: - 执行器经 `TaskStore` 协议 → `SqlTaskLeaseStore`（`mark_failed` / `mark_succeeded` /
#:   `requeue` / `begin_attempt`，内部都走 `_write_back`）；
#: - 仓储的通用写回（`TaskRepo.update_status` 与它唯一的语句构造器 `status_update_statement`）。
WRITE_BACK_CALLS: frozenset[str] = frozenset(
    {
        "update_status",
        "status_update_statement",
        "mark_failed",
        "mark_succeeded",
        "requeue",
        "begin_attempt",
        "_write_back",
    }
)

#: 被禁的取值（标识符名与字符串字面量都要拦）。
FORBIDDEN_STATUS: str = "MANUAL_REVIEW"


def iter_source_files() -> list[Path]:
    """`src/aicore` 下的全部 Python 文件（跳过缓存目录）。"""
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _called_name(node: ast.Call) -> str | None:
    """被调用者的名字：`obj.method(...)` 取 `method`，`func(...)` 取 `func`。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def manual_review_write_targets(tree: ast.Module) -> list[tuple[int, str]]:
    """扫出「把 `MANUAL_REVIEW` 当写回实参」的位置（`(行号, 形态说明)`）。

    **取窄**：只看白名单里的写回调用；`Enum(...)`、`Literal[...]`、`frozenset({...})`
    这些**定义/读侧**用法一律不拦（裁定逐字允许它们存在）。
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name not in WRITE_BACK_CALLS:
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        for argument in arguments:
            for inner in ast.walk(argument):
                if isinstance(inner, ast.Name) and inner.id == FORBIDDEN_STATUS:
                    hits.append((inner.lineno, f"{name}(...) 的实参里出现该值的标识符"))
                elif isinstance(inner, ast.Constant) and inner.value == FORBIDDEN_STATUS:
                    hits.append((inner.lineno, f"{name}(...) 的实参里出现该值的字符串字面量"))
    return hits


def test_no_code_path_writes_the_manual_review_status() -> None:
    """全 `src/` 扫描：`MANUAL_REVIEW` MUST NOT 出现在任何写回调用的实参里。

    M1 的失败终态只有 `FAILED`（`4003` / `5002` 都是它的 `error_code`）；
    第四态留给 M2，**没有触发者**。
    """
    scanned = 0
    offenders: list[str] = []
    for path in iter_source_files():
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, shape in manual_review_write_targets(tree):
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno} {shape}")

    assert offenders == [], (
        "有代码路径把任务写回成 MANUAL_REVIEW（Task 4.11 §2 的裁定 (a)：M1 不使用该状态；"
        "`4003`/`5002` 都是 `FAILED` + `error_code`）：\n  " + "\n  ".join(offenders)
    )
    # 空扫描自证：路径写错时本判据会"全绿"，故要求扫到的文件数不为零。
    assert scanned >= 20, f"只扫到 {scanned} 个源文件：SRC 的路径或 glob 坏了"


def test_manual_review_write_guard_discriminates() -> None:
    """**判别力自证**：给某个写回调用塞一个 `MANUAL_REVIEW` 实参 ⇒ 判据**必须红**。

    内存变异（**文件从不被写**）：拿 `repository/task_lease_store.py` 的源码，
    把 `mark_failed` 里那行 `status=FAILED_STATUS` 改成 `status=MANUAL_REVIEW`
    —— 这正是"M2 顺手把 4003 接到 MANUAL_REVIEW 上"的形态。
    同一份扫描函数喂给变异后的 AST ⇒ **必须报出命中**。

    两种写法各测一次（标识符与字符串字面量）：`status="MANUAL_REVIEW"` 与
    `status=MANUAL_REVIEW` 是同一件事的两种写法，只拦一种等于留了个后门。
    """
    source = (SRC / "repository" / "task_lease_store.py").read_text(encoding="utf-8")
    anchor = "status=FAILED_STATUS,"
    assert source.count(anchor) == 1, (
        f"变异锚点在 task_lease_store.py 里出现 {source.count(anchor)} 次（要求恰好 1 次）："
        f"{anchor!r}——锚点漂了就必须先修锚点"
    )

    for replacement, label in (
        ("status=MANUAL_REVIEW,", "标识符写法"),
        ('status="MANUAL_REVIEW",', "字符串写法"),
    ):
        mutated = source.replace(anchor, replacement)
        hits = manual_review_write_targets(ast.parse(mutated))
        assert hits, f"判据对{label}的 MANUAL_REVIEW 写回失去判别力：没有报出任何命中"

    # 阳性对照：未变异的源码 MUST NOT 报命中（否则本判据是"一律判红"）。
    assert manual_review_write_targets(ast.parse(source)) == []
