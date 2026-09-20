## 本行是 Mako 注释，不进生成物。
##
## `Revises:` 用纯 Python 表达式而不是 Alembic 自带的 `| comma,n` 过滤器：
## 基线（down_revision 为 None）时那个过滤器渲染成空串，留下一行**尾随空格**
## （ruff W291）；而过滤器语法只能出现在 `${}` 表达式的最外层，
## 没法写成 `(x | comma,n) or "(root)"`——实测 Mako 会把它当 Python 的按位或，
## 渲染期直接 `TypeError: unsupported operand type(s) for |`。
## 本仓库是单头线性链，故直接给 `None` 一个可读的 `(root)`。
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision if down_revision else "(root)"}
Create Date: ${create_date}

**本文件由 `alembic revision [--autogenerate]` 从 `script.py.mako` 生成，
MUST NOT 手改生成的 `op.*` 调用**：结构定义以 `deploy/sql/ddl/**`（权威）与
`src/aicore/repository/models.py`（元数据）为准，改结构要先改那两处、再重新生成。
手改这里等于出现第三份结构定义，而它的漂移没有任何门禁能发现。

降级在生产被 `env.py` 默认拒绝（expand-migrate-contract，spec §2.3）。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
${imports if imports else ""}

# Alembic 的版本标识（revision 之间靠它们串成链）。
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """升级到本版本。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回退本版本。基线迁移只撤自己建的表；生产禁用降级。"""
    ${downgrades if downgrades else "pass"}
