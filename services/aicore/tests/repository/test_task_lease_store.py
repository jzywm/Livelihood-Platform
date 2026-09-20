"""`repository/task_lease_store.py` 就地声明的**状态字面量**与权威来源的一致性（Task 4.7）。

## 这个文件为什么必须存在（A7）

`repository/task_lease_store.py` **不导入** `service/task/state.py`——因为
`.importlinter` **契约 3**（`repository / provider / port 不得反向依赖 service`）把
`repository -> aicore.service` 判为违规。故它在文件顶部**就地声明**了三个状态字面量
（`PROCESSING_STATUS` / `SUCCEEDED_STATUS` / `FAILED_STATUS`），当时的 docstring 写着
「三处一致性由 `tests/repository/test_task_lease_store.py` 现读 `service/task/state.py`
与 `er.md` §6.1 逐字比对」——**而那个文件并不存在**（独立评审 A7：全仓只有那两处自我引用）。
即：就地声明状态字面量的**唯一防线没有实现**，那句话是一张空头支票。

本文件把那句话兑现：**不导入**不等于**不校验**。

## 三源是谁

| 源 | 位置 | 角色 |
|---|---|---|
| DDL / 库 | `deploy/sql/ddl/10_ai_task.template.sql` 的 `status` 原生 ENUM | 落库的**硬约束** |
| 文档 | `services/aicore/docs/er.md` §6.1 L292 的 `status` 行 | 口径来源 |
| 状态机 | `service/task/state.py` 的四个 `Final` 常量 | 「哪条转移合法」的**唯一**定义处 |
| 就地字面量 | `repository/task_lease_store.py` 的三个 `*_STATUS` | 本层写库时用的值 |

本文件把它们两两对上，且**现读**（不抄成常量——第 3 组有过「把权威表述抄进测试、
测试就只剩抄得对不对」的假绿教训）。

## 四条判据各自能红的形态（一处**已删的恒真判据**记在这里）

| 判据 | 现读的源 | 能红的形态 |
|---|---|---|
| `..._match_the_state_machine_constants` | `service/task/state.py` | 就地字面量与状态机漂移 |
| `..._match_the_ddl_enum` | `deploy/sql/ddl/10_ai_task.template.sql` | 写库会被 MySQL 拒绝的值 |
| `..._match_the_orm_enum` | `repository/models.py` 的 `AiTask` | 模型与 DDL 漂移 |
| `..._documents_all_three_statuses` | `docs/er.md` §6.1 | 文档口径改了而代码没跟 |

**已删**：`test_each_literal_is_a_non_empty_str`（参数化 3 条）——它断言
`isinstance(LOCAL_STATUS_LITERALS[name], str) and value.strip()`，
而被断言的值是**本文件刚从被测模块 import 进来的常量**：import 成功即说明值存在，
`Final` 声明缺值本来就是 `SyntaxError`。**它不可能红**（复核者记为 N4 的一处），
删掉不减少任何覆盖（上表四条才是真判据）。删除痕迹见文件末尾的 `_removed_..._note`。
"""

from __future__ import annotations

import re
from pathlib import Path

from aicore.repository.models import AiTask
from aicore.repository.task_lease_store import (
    FAILED_STATUS,
    PROCESSING_STATUS,
    SUCCEEDED_STATUS,
)
from aicore.service.task.state import ALL_STATUSES, FAILED, PROCESSING, SUCCEEDED

SERVICE_ROOT = Path(__file__).resolve().parents[2]
DDL_TEMPLATE = SERVICE_ROOT / "deploy" / "sql" / "ddl" / "10_ai_task.template.sql"
ER_DOC = SERVICE_ROOT / "docs" / "er.md"

#: 本模块就地声明的三个字面量（与常量名一起给出，便于报错时点名）。
LOCAL_STATUS_LITERALS: dict[str, str] = {
    "PROCESSING_STATUS": PROCESSING_STATUS,
    "SUCCEEDED_STATUS": SUCCEEDED_STATUS,
    "FAILED_STATUS": FAILED_STATUS,
}

#: `state.py` 里对应的权威常量（同名不同模块，逐个配对）。
AUTHORITATIVE_CONSTANTS: dict[str, str] = {
    "PROCESSING_STATUS": PROCESSING,
    "SUCCEEDED_STATUS": SUCCEEDED,
    "FAILED_STATUS": FAILED,
}


def _status_enum_from_ddl() -> list[str]:
    """现读 DDL 模板里 `status` 列的原生 ENUM 取值（**按声明顺序**）。"""
    text = DDL_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"`status`\s+enum\(([^)]*)\)", text)
    assert match is not None, (
        f"{DDL_TEMPLATE.name} 里找不到 `status` 的 enum 定义："
        f"判据的前提（DDL 是结构的唯一权威）失效"
    )
    return re.findall(r"'([^']*)'", match.group(1))


def test_local_literals_match_the_state_machine_constants() -> None:
    """就地字面量逐字等于 `service/task/state.py` 的权威常量（A7 的核心判据）。

    这是「不导入也要校验」的落点：`task_lease_store.py` 出于分层约束不能 import
    `state.py`，但它写进库的值**必须**与状态机认可的值逐字一致——
    否则一次 `update_status` 会写进一个状态机不认的状态。
    """
    for local_name, authoritative in AUTHORITATIVE_CONSTANTS.items():
        local_value = LOCAL_STATUS_LITERALS[local_name]
        assert local_value == authoritative, (
            f"{local_name}={local_value!r} 与 service/task/state.py 的 "
            f"{authoritative!r} 不一致：就地字面量漂移了（写库的值会超出状态机的取值域）"
        )


def test_local_literals_are_within_the_known_status_set() -> None:
    """三个字面量都在 `state.py` 的 `ALL_STATUSES` 里（取值域校验）。"""
    unknown = sorted(set(LOCAL_STATUS_LITERALS.values()) - ALL_STATUSES)
    assert unknown == [], (
        f"task_lease_store.py 声明了状态机不认识的状态 {unknown}："
        f"合法取值只有 {sorted(ALL_STATUSES)}"
    )


def test_local_literals_match_the_ddl_enum() -> None:
    """就地字面量都在 DDL 的原生 ENUM 取值域内（**落库的硬约束**）。"""
    enum_values = _status_enum_from_ddl()
    assert enum_values, "DDL 的 status enum 解析为空：判据会退化成平凡真"
    for name, value in LOCAL_STATUS_LITERALS.items():
        assert value in enum_values, (
            f"{name}={value!r} 不在 DDL 的 status enum {enum_values} 里："
            f"写库会被 MySQL 拒绝（或静默截断）"
        )


def test_local_literals_match_the_orm_enum() -> None:
    """就地字面量都在 ORM 模型的 `Enum` 取值域内（三源比对里的模型那一源）。"""
    column = AiTask.__table__.c.status
    assert hasattr(column.type, "enums"), f"status 列不是 Enum 类型：{type(column.type)!r}"
    model_values = list(column.type.enums)
    assert model_values, "模型的 status enum 为空：判据会退化成平凡真"
    for name, value in LOCAL_STATUS_LITERALS.items():
        assert value in model_values, (
            f"{name}={value!r} 不在 ORM 模型的 status enum {model_values} 里："
            f"模型与 DDL 之间存在漂移"
        )


def test_er_doc_documents_all_three_statuses() -> None:
    """`er.md` §6.1 的 `status` 行逐字含全部四个状态（文档那一源）。

    现读文档而不是抄常量：`er.md` 改了而就地字面量没跟上时，本用例会给出
    「文档里有哪个值、代码里没有」的可核对输出。
    """
    text = ER_DOC.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if "status" in line and "enum" in line.lower()]
    assert lines, (
        f"{ER_DOC.name} 里找不到 `status` 的 enum 描述："
        f"文档口径可能改了写法，判据的锚点需要跟着更新"
    )
    documented = "\n".join(lines)
    missing = sorted(
        value for value in LOCAL_STATUS_LITERALS.values() if value not in documented
    )
    assert missing == [], (
        f"er.md §6.1 的 status 描述里没有 {missing}："
        f"就地字面量与文档的取值域不一致（文档行：{lines[0][:120]!r}）"
    )


def _removed_tautological_test_note() -> None:
    """**不是用例**（前缀 `_`，pytest 不收集）：记录这里删过一条**恒真判据**。

    删除的是 `test_each_literal_is_a_non_empty_str`（参数化 3 条）：它断言
    `isinstance(LOCAL_STATUS_LITERALS[name], str) and value.strip()`，
    而 `LOCAL_STATUS_LITERALS` 是**同一文件刚从被测模块 import 进来的常量**——
    import 成功即说明值存在，`Final` 声明缺值本来就是 `SyntaxError`。
    也就是说**它不可能红**，只在测试计数上多算三条（复核者把它记为 N4 的一处）。

    覆盖没有因此减少，`*_STATUS` 的三重一致性由本文件四条**现读**判据承担（见模块 docstring）。
    留一个**不叫 `test_` 的空函数**而不是整段删掉，是为了让"这里曾有一条恒真判据"在文件里
    留痕——复核者正是靠这种痕迹才没有把删除误读成"覆盖被砍"。**MUST NOT** 给它加上断言。
    """
