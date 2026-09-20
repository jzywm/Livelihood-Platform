### Task 3.5: Schema 迁移（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**（`alembic 1.20.0` 已装）。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件。

**Files:**
- Create: `alembic.ini`
- Create: `deploy/sql/migration/env.py`
- Create: `deploy/sql/migration/script.py.mako`
- Create: `deploy/sql/migration/README`（Alembic 惯例的文件，写"如何再加一条迁移"）
- Create: `deploy/sql/migration/versions/<rev>_baseline_schema.py`
- Create: `tests/repository/test_migration.py`

**权威依据（MUST 先读）**：
- spec **§5.5**（DDL 与 Alembic 的分工：**纯 SQL DDL 是权威定义**；版本化迁移**从 SQLAlchemy 元数据生成**、不手写第二份 DDL；两条路径结果必须一致）、**§2.3**（演进：expand-migrate-contract 四步，**禁止破坏性 DDL**）
- `services/aicore/docs/er.md` **§5.6**（expand-migrate-contract：扩展 → 迁移 → 收缩）
- `deploy/sql/ddl/**`（Task 3.1 交付的权威 DDL）
- `src/aicore/repository/models.py`（Task 3.2 交付的元数据）

---

#### 交付内容

| 文件 | 内容 |
|---|---|
| `alembic.ini` | Alembic 配置；`script_location` 与 `version_locations` 指向 `deploy/sql/migration` 与 `deploy/sql/migration/versions`；`sqlalchemy.url` **留空并在 `env.py` 里从环境变量取**（见下） |
| `deploy/sql/migration/env.py` | `target_metadata = Base.metadata`；URL 从 `AICORE_MYSQL_*` 组装（复用 `core/config.py` 的 `Settings`，**MUST NOT 硬编码口令**）；开启 `compare_type=True`（类型变更也要被 autogenerate 发现） |
| `deploy/sql/migration/versions/<rev>_baseline_schema.py` | **单一基线迁移**：手写 `op.create_table` 的替代方案是**从 metadata 生成**——两条都行，但 MUST NOT 出现"第二份与 DDL 平行的列定义"（见下"分工纪律"） |
| `deploy/sql/migration/README` | 写清"新增迁移的正确姿势"与"分片表不在迁移里" |

#### 分工纪律（spec §5.5 的硬要求，MUST 照此）

- **纯 SQL DDL（`deploy/sql/ddl/**`）是权威定义**；迁移是"同一份结构的另一条落地路径"。
- **MUST NOT 手写第二份 DDL**：基线迁移 MUST 由 `alembic revision --autogenerate` 从
  `Base.metadata` 生成（生成命令与原始输出 MUST 贴进报告），或由脚本从 metadata 程序化产出。
- **分片表（`ai_task` / `ocr_result` / `ocr_correction`）不在基线迁移里**：
  它们的物理表由 Task 3.3 的 `ensure_month_tables()` **运行时按模板创建**。
  理由：物理表名依赖月份（`xxx_YYYYMM`），迁移是**时点结构**、月份是**运行期数据**——
  把某个月的物理表写死进迁移，等于让"新月份"必须等一次发版。
  **但本任务 MUST 交付"迁移钩子承接分片表创建"的能力**（见下 `versions/README` 之外的要求）：
  在 `env.py` 里提供 `create_shard_tables_for(month)` 之类的**可调用入口**，
  委托 Task 3.3 的 `ensure_month_tables`，使"`alembic upgrade head` 之后当月表也就绪"。
- **禁止破坏性 DDL**（spec §2.3 / er.md §5.6）：基线迁移里 MUST NOT 出现
  `op.drop_table` / `op.drop_column`；**`downgrade()` 必须存在**，但 MUST 只做"基线撤销"
  （即 `drop_table` 本迁移创建的表），并在 docstring 注明"生产禁用 downgrade，走 expand-migrate-contract"。

#### 幂等口径（三条，MUST 都可复核）

1. **重复 autogenerate 产生同一 revision，而非追加一条空迁移**：
   在已 `upgrade head` 的库上再跑 `alembic revision --autogenerate`，
   生成的迁移**内容必须为空**（`upgrade()` 体内无 `op.` 调用）。
   这条最值钱：它同时验证了 Task 3.2 的 `server_default` / 索引名 / 类型是否与 DDL 真正对齐——
   写入模型与库不一致时，autogenerate 每次都想改。
2. **空库重放可复现**：在**新建的空库**上 `alembic upgrade head` 成功；
   再 `alembic upgrade head` 一次 MUST 是 no-op（Alembic 靠 `alembic_version` 表保证）。
3. **与直接执行 DDL 的结果一致**：`alembic upgrade head` 建出的结构 与
   `scripts/apply_ddl.py`（Task 3.1）建出的结构，用 Task 3.6 的
   `from_information_schema(...)` + `diff(...)` 比对，**差异为 0**。
   **MUST NOT** 自己再写一套"读 information_schema"的代码——复用 Task 3.6 的。

#### 库的使用（MUST）

- 演练一律在 **`aicore_test`**；**MUST NOT** 在 `aicore` 上跑 `downgrade` 或任何破坏性操作。
- 为"空库"用例，MUST 建一个**独立命名**的演练库或一套**独立前缀的库级隔离**；
  若 `aicore_dev` 无建库权限（实测：**确实没有**，只有 `aicore` 与 `aicore_test` 的 ALL），
  则 MUST 用 `aicore_test` 内的**独立表名前缀**做等价验证，并在报告里**如实说明**
  "不是真·空库，而是空命名空间"，**MUST NOT** 谎称验证了建库路径。

---

#### 用例 `tests/repository/test_migration.py`

**不连数据库的部分**（默认跑）：
1. **结构断言**：`alembic.ini` 的 `script_location` / `version_locations` 指向 `deploy/sql/migration`；
   `versions/` 下**恰好 1 条**基线迁移；`env.py` 里 `target_metadata` 取自 `repository.models.Base`。
2. **非破坏性**：读基线迁移源码，断言**不含** `op.drop_table` / `op.drop_column`；
   断言 `downgrade()` 存在。用 AST 或正则均可，但 MUST 断言"含 `def downgrade`"这条**正向**要求
   （只断言"不含 drop_table"是不够的——空函数也能过）。
3. **分片表不在基线里**：断言基线迁移的 `op.create_table(...)` 表名集合 == 6 张非分片表
   （**逐字**列出，不靠"看起来像"），且**不含** `ai_task` / `ocr_result` / `ocr_correction`。
4. **口诀文档**：断言 `deploy/sql/migration/README` 存在且提到"分片表由运行时创建"与
   "新增迁移的正确姿势"（用子串断言，MUST 说明这是弱断言）。

**连数据库的部分**（`@pytest.mark.integration`，默认不跑；连不上 MUST `pytest.skip` 并说明）：
5. `alembic upgrade head` 在 `aicore_test` 成功 → `information_schema` 断言 6 张表存在 →
   **再 `upgrade head` 一次**（no-op）→ 断言 0 差异。
6. **与 DDL 直建一致**：把 `alembic upgrade head` 的结果与 `apply_ddl.py` 的结果用 Task 3.6 的
   `diff` 比对，断言空清单。
7. **幂等（autogenerate 收敛）**：在已 upgrade 的库上跑一次 autogenerate 到**临时目录**，
   断言生成的升级脚本里**没有 `op.` 调用**（即"库与模型一致"）。
   临时目录用 `tmp_path`；**MUST NOT** 把生成物留在 `versions/`。
8. 清理：MUST 只 `DROP` 本任务建的表 + `alembic_version`，
   **MUST NOT `DROP DATABASE`**、MUST NOT 删 `aicore` 库里的任何东西。

**禁止**：`sleep`；把口令写进 `alembic.ini`（该文件会入库）。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_migration.py -q
.venv\Scripts\python.exe -m pytest tests/repository/test_migration.py -q -m integration
.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head        # 贴完整输出
.venv\Scripts\python.exe -m alembic -c alembic.ini revision --autogenerate -m "probe"  # 贴输出，证明为空
.venv\Scripts\python.exe -m pytest -q                                   # 全量基线不得变红
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.5-report.md`，
  含原始输出、三条幂等口径各自的证据、逐项验收结论、**偏离项 + 理由**、**没做到的事**
  （尤其：建库路径未能验证这一点 MUST 如实登记）。
