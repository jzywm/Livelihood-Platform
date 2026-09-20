# Task 3.5 报告：Schema 迁移（Alembic）

**执行者**：Task 3.5 实现者（subagent）· **日期**：2026-09-18
**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
**结论**：交付 6 个文件全部落地；用例 **17 条全绿**（12 条默认 + 5 条真实 MySQL 集成）；
**三条幂等口径全部有正面证据**（口径 1 的探针迁移 `upgrade()`/`downgrade()` 体内只有 `pass`，
零 `op.*` 调用）；全量基线 **877 passed, 8 skipped, 19 deselected**（未变红）；
`mypy src` / `lint-imports` / 覆盖率 97.26% 全过；`ruff check .` 整仓绿。
**建库路径未验证**（无权限，见 §6 N1），**分片表名前缀隔离未实现**（见 §6 N2）——两条都如实登记。
**Task 3.2 的两处 `with_variant` 不需要任何模型侧改动**：autogenerate 一次收敛（见 §3 口径 1）。

---

## 1. 交付文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `alembic.ini` | **新增**（3905 B，纯 ASCII） | `script_location` / `version_locations` 指向 `deploy/sql/migration{,/versions}`（用 `%(here)s` 锚定，与 shell cwd 无关）；`sqlalchemy.url` **留空**；`prepend_sys_path`；`path_separator = os`；`[post_write_hooks]` = `ruff format` + `ruff check --fix`；`[loggers]` 一组（否则 `upgrade head` 一行输出都没有） |
| `deploy/sql/migration/env.py` | **新增**（254 行） | `target_metadata = Base.metadata`；`compare_type=True` + `compare_server_default=True`；`include_object`（分片表**两个方向**都不进迁移）；`create_shard_tables_for(conn, month)`（委托 `sharding.ensure_month_tables`）+ `-x shard_month=YYYYMM` 钩子；`database_url()`（演练库轨优先）；`reject_unflagged_downgrade()` + `_command_name()`；`strip_redundant_drop_index()`（生成期后处理，见 D4） |
| `deploy/sql/migration/script.py.mako` | **新增** | Alembic 官方模板的本仓适配：`from __future__` + `str \| None` 新式注解、import 顺序按 ruff isort、`Revises:` 用纯 Python 表达式（避免空值尾随空格，理由写在模板注释里） |
| `deploy/sql/migration/README` | **新增** | 「新增迁移的正确姿势」「分片表由运行时创建」「连哪个库（口令不入库）」「基线迁移的范围与降级纪律」 |
| `deploy/sql/migration/versions/2523574bd75d_baseline_schema.py` | **新增**（由 `alembic revision --autogenerate` 生成，235 行） | **唯一基线迁移**：`upgrade()` 建 **6 张非分片表** + 10 个索引；`downgrade()` **只** `drop_table` 这 6 张表 |
| `tests/repository/test_migration.py` | **新增**（17 条用例：12 默认 + 5 `integration`） | 结构断言 / 非破坏性（AST 分区）/ 分片表不在基线 / README 弱断言 / 降级守卫（无需 DB）；空命名空间重放、两条落地路径 `diff`、autogenerate 收敛（临时目录）、分片月钩子、显式放行降级 |

**没有创建任何一次性探针脚本**（探针预算 2 个，实用 **0** 个；全部临时探查用 `python - ` 内联 stdin 完成，未落盘）。
**没有 `git commit`。** **没有改** `src/aicore/repository/{base,task_repo,ocr_repo,correction_repo,verdict_repo}.py` 与 `tests/repository/test_repos.py`（并发 subagent 的文件），也**没有改** `models.py`（无必要，见 §3）。

`versions/` 交付态（`Get-ChildItem -Recurse`）：**恰好 1 个 `.py` 文件**，无 `__pycache__`、无探针残留。

---

## 2. 每条验证命令的原始输出

> 环境：MySQL 8.0.35 @127.0.0.1:3306，演练库 `aicore_test`，凭据只从环境变量取
> （`DSH_IT_MYSQL_PASSWORD`，由 `.env` 回填，**未硬编码、未写进 `alembic.ini`**）。
> PowerShell 把子进程 stderr 包成 `NativeCommandError` 是显示层的噪声，内容未改；下文的
> 「stderr」块就是 Alembic 自己的 INFO 日志（`[logger_alembic]` 打到 stderr）。

### 2.1 `.venv\Scripts\python.exe -m pytest tests/repository/test_migration.py -q`
```
.................                                                        [100%]
exit=0
```
（`pyproject` 的 `addopts = "-q"` 与命令行 `-q` 叠加成 `-qq`，故无汇总行；清空 `addopts` 重跑取到汇总：`17 passed in 12.48s`）

### 2.2 `.venv\Scripts\python.exe -m pytest tests/repository/test_migration.py -q -m integration`
```
.....                                                                    [100%]
exit=0
```
（汇总：`5 passed, 12 deselected in 11.41s`）

### 2.3 `.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head`（**空命名空间**，第 1 次）
```
[prep] aicore_test tables before upgrade: ['ai_task_202607', 'ocr_correction_202607', 'ocr_result_202607']
[alembic] 目标库 = mysql+pymysql://aicore_dev:***@127.0.0.1:3306/aicore_test?charset=utf8mb4 | 配置来源 = 演练库(DSH_IT_MYSQL_*)
### exit=0
```
stderr（Alembic 日志）：
```
INFO  [alembic.runtime.migration] Context impl MySQLImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 2523574bd75d, baseline schema
```

### 2.4 同一条命令**再跑一次**（口径 2 的 no-op 证据）
```
[alembic] 目标库 = mysql+pymysql://aicore_dev:***@127.0.0.1:3306/aicore_test?charset=utf8mb4 | 配置来源 = 演练库(DSH_IT_MYSQL_*)
### exit=0
```
stderr：
```
INFO  [alembic.runtime.migration] Context impl MySQLImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
```
**没有 `Running upgrade` 行** = 没有执行任何版本。`.venv\Scripts\python.exe -m alembic -c alembic.ini current`：
```
[alembic] 目标库 = mysql+pymysql://aicore_dev:***@127.0.0.1:3306/aicore_test?charset=utf8mb4 | 配置来源 = 演练库(DSH_IT_MYSQL_*)
2523574bd75d (head)
### exit=0
```

### 2.5 `.venv\Scripts\python.exe -m alembic -c alembic.ini revision --autogenerate -m "probe"`（口径 1）
```
[alembic] 目标库 = mysql+pymysql://aicore_dev:***@127.0.0.1:3306/aicore_test?charset=utf8mb4 | 配置来源 = 演练库(DSH_IT_MYSQL_*)
Generating D:\...\deploy\sql\migration\versions\2a7276cb9bf8_probe.py ...  done
Running post write hook 'ruff_format' ...
1 file reformatted
  done
Running post write hook 'ruff_lint' ...
Found 4 errors (4 fixed, 0 remaining).
  done
### exit=0
```
**关键：全程没有一行 `Detected added/removed ...`**（autogenerate 只在发现差异时打这类 INFO；这次一条都没有）。
生成物全文（Python 按 UTF-8 读出，避免 PowerShell 的 GBK 显示乱码）：
```python
"""probe

Revision ID: 2a7276cb9bf8
Revises: 2523574bd75d
Create Date: 2026-09-18 19:38:42.033110
（模板头部中文说明，略）

from __future__ import annotations

from collections.abc import Sequence

# Alembic 的版本标识（revision 之间靠它们串成链）。
revision: str = "2a7276cb9bf8"
down_revision: str | None = "2523574bd75d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """升级到本版本。"""
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###


def downgrade() -> None:
    """回退本版本。基线迁移只撤自己建的表；生产禁用降级。"""
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
```
同一次运行的 AST 复核（脚本内即时打印）：
```
[AST] upgrade() 里 op.* 调用 = []
[AST] downgrade() 里 op.* 调用 = []
[cleanup] deleted: 2a7276cb9bf8_probe.py | versions/*.py left = ['2523574bd75d_baseline_schema.py']
```
（`ruff_lint` 那 4 个 fix 是空迁移里的 `sa` / `op` / `Sequence` 未使用 + 尾随空格，正是 post-write hook 的作用。）

### 2.6 `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -m "not integration"`（全量基线）
```
877 passed, 8 skipped, 19 deselected in 11.04s
exit=0
```
跳过项明细（`-rs`，与 Task 3.4 报告的基线**完全一致**，非本任务引入）：
```
SKIPPED [7] tests\structural\test_source_guards.py:102: provider 包是唯一允许发起外部模型调用的层
SKIPPED [1] tests\unit\test_envelope.py:501: /metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言
```
> 中途一次运行曾出现 `2 failed`（`tests/repository/test_repos.py::test_verdict_*`，断言 `code == 1003` 实得 `3007`）。
> **与本次改动无关**：那是并发 subagent 正在改 `core/errors.py` + `verdict_repo.py` 的中间态
> （`git status` 显示这 6 个文件 + `tests/unit/test_errors.py` 被它改着）。单跑该文件确认：
> `pytest tests/repository/test_repos.py -q -p no:cacheprovider -m "not integration"` → `.....................................  [100%]`，`exit=0`；
> 其作者改完后全量重跑即 **877 passed**（见上）。

### 2.7 `.venv\Scripts\ruff.exe check . --no-cache`
```
All checks passed!
exit=0
```
（中途一次运行曾报 6 条 `F841`，**全部在并发 subagent 的未跟踪文件 `scripts/group3_acceptance.py`** 里；
该文件随后被其作者改掉，重跑即 `All checks passed!`。本任务 5 个文件 0 条。）

### 2.8 `.venv\Scripts\mypy.exe src`
```
Success: no issues found in 52 source files
exit=0
```

### 2.9 `.venv\Scripts\lint-imports.exe --config .importlinter --no-cache`
```
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.
exit=0
```

### 2.10 追加验证（工单没列，但能证明"没踩别人"与门禁）

| 命令 | 输出 | 退出码 |
|---|---|---|
| `pytest -p no:cacheprovider -m integration -o addopts="" -q`（**全量集成套件**，含 Task 3.1 的 `test_apply_ddl_mysql.py`） | `...................  [100%]` / `19 passed, 885 deselected in 18.17s` | 0 |
| `pytest -p no:cacheprovider -q -m "not integration" --cov`（覆盖率门禁 `fail_under = 80`） | `Required test coverage of 80.0% reached. Total coverage: 97.26%`（TOTAL 1314 语句 / 36 未覆盖） | 0 |

演练库收尾态（我自己查的）：`aicore_test = ['ai_task_202607', 'alembic_version', 'kitchen_anomaly', 'ocr_correction_202607', 'ocr_result_202607', 'review_verdict', 'risk_predict_result', 'vision_marker', 'vision_qa_log', 'vision_review']`，
`aicore_test.alembic_version = ['2523574bd75d']`；
产品库 `aicore` 全程 **9 张表未变**（每一次 alembic 运行的第一行都打印 `.../aicore_test`，可逐条核对）。

---

## 3. 三条幂等口径各自的证据

### 口径 1：重复 autogenerate 产生**空**迁移（不是追加一条空壳）
- CLI 证据：§2.5 —— `revision --autogenerate -m "probe"` 全程无 `Detected ...`，生成物 `upgrade()` / `downgrade()` 体内只有 `pass`，AST 计得 **0 个 `op.*` 调用**；探针文件已删除，`versions/` 仍只剩基线。
- 用例证据：`test_autogenerate_converges_on_upgraded_db`（集成）把**整份迁移目录复制到临时目录**再生成，断言新生成脚本的 `upgrade()` 无 `op.*`，并断言真实 `versions/` 仍恰好 1 条迁移。
- **这条同时回答了控制者最关心的问题**：Task 3.2 的两处 `with_variant`
  （`Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")`、
  `DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")`）**没有造成任何反复改动**：
  基线生成时被如实渲染成 `.with_variant(...)`（差值 0），第二次生成的探针为空。
  这次 autogenerate 还额外开了 `compare_server_default=True`（工单只要求 `compare_type`），
  `DEFAULT 0` / `DEFAULT 'PROCESSING'` / `DEFAULT CURRENT_TIMESTAMP(3)` **也没有产生差异**
  ——即模型侧 `server_default=text(...)` 的写法与 MySQL 反射结果一致。**故我一个字都没改 `models.py`。**

### 口径 2：空命名空间重放可复现、二次 `upgrade head` 是 no-op
- CLI 证据：§2.3（首次：`Running upgrade  -> 2523574bd75d, baseline schema`）+ §2.4（二次：无 `Running upgrade` 行，退出码 0）+ `current` = `2523574bd75d (head)`。
- 用例证据：`test_upgrade_on_empty_namespace_then_second_upgrade_is_noop` —— 先 `_empty_namespace()`（并当场断言"真的空了"），
  首次 upgrade 后断言 6 张表齐全、**用新连接**取结构快照；二次 upgrade 后取第二份快照，
  断言 `diff(before, after) == []`（而不是只看退出码：退出码 0 对"什么都没干"和"重建了一遍"是一样的）。
- **口径的适用范围（如实说明）**：这是"**空命名空间**"，不是"真·空库"，理由与限制见 §6 N1。

### 口径 3：`alembic upgrade head` 与 `apply_ddl.py` 直建结果**差异为 0**
- 用例证据：`test_alembic_result_matches_apply_ddl_result` —— 顺序是
  `清空 → alembic 建（6 表）→ 快照 A → 清空 → apply_ddl 建（6 表）→ 快照 B → diff(A,B) == []`。
  两侧都断言 `len(snapshot) == 6`，**防止"两边都是空的、diff 也是空的"这种假通过**。
- **MUST 复用 Task 3.6 的读取器**：本用例只调 `from_information_schema(conn, "aicore_test")` + `diff(...)`
  （`tests/repository/test_migration.py` 里没有一行自己的 `information_schema` SQL）。
  结构快照只取 6 张非分片表（`FIXED_TABLES`），避免把演练月的分片表带进比对。
  表存在性检查用 SQLAlchemy 的 `inspect(engine).get_table_names()`（不是自己写查询）。

---

## 4. 逐项验收结论

| 工单要求 | 落点 | 结论 |
|---|---|---|
| 交付 `alembic.ini` | §1 | ✅（含 D1 的纯 ASCII 偏离、D6/D7 的追加配置） |
| 交付 `deploy/sql/migration/env.py`（`target_metadata` 取自 `Base`、`compare_type=True`、URL 从环境取、不硬编码口令） | §1 / §2 | ✅ + 追加 `compare_server_default` / `include_object` / 降级守卫 / 分片钩子（D4/D5/D8） |
| 交付 `script.py.mako` | §1 | ✅ |
| 交付 `README`（"新增迁移的正确姿势" + "分片表不在迁移里"） | §1 | ✅（用例 4 用子串断言，**弱断言**已在用例 docstring 里注明） |
| **单一基线迁移**、由 autogenerate 从 `Base.metadata` 生成、**不手写第二份 DDL** | §2.5 / §1 | ✅ 生成命令与原始输出在 §2.5；`versions/` 恰好 1 条；基线是根版本（`down_revision is None`） |
| **分片表不进基线**，但要有"迁移钩子承接分片表创建"的能力 | `include_object` + `create_shard_tables_for` + `-x shard_month` | ✅ 基线只建 6 张非分片表；`test_shard_month_hook_creates_physical_tables` 从 CLI 侧证明 `upgrade head` 之后当月 3 张物理表就绪 |
| **禁止破坏性 DDL**：`upgrade()` 无 `drop_table` / `drop_column`；`downgrade()` 必须存在且只撤自己建的表 | 基线 + 用例 2 | ✅ AST 分区断言：`upgrade()` 里 0 个 `drop_*`；`downgrade()` 存在且 `drop_table` 集合 **==** `create_table` 集合（6 张）；全文件无 `drop_column`（分区理由见 D3） |
| 用例 1 结构断言（ini 指向、恰好 1 条、env.py 取 `Base`） | `test_alembic_ini_points_to_migration_dir` / `test_versions_dir_has_exactly_one_baseline_revision` / `test_env_py_takes_target_metadata_from_base` | ✅ |
| 用例 2 非破坏性 | `test_baseline_upgrade_is_non_destructive` / `test_baseline_downgrade_exists_and_reverts_only_itself` | ✅ |
| 用例 3 分片表不在基线（**逐字**列 6 张 + 不含 3 张分片表） | `test_baseline_creates_exactly_the_six_fixed_tables` | ✅ 逐字元组 + 与 `sharding.FIXED_TABLES` 交叉验证 + 断言无 `_2xxxxx` 物理名 |
| 用例 4 README 口径 | `test_migration_readme_documents_shard_and_new_migration` | ✅（弱断言，如实标注） |
| 用例 5 空库/空命名空间 `upgrade` + 二次 no-op + 0 差异 | `test_upgrade_on_empty_namespace_then_second_upgrade_is_noop` | ✅（"不是真·空库"见 N1） |
| 用例 6 与 DDL 直建一致（复用 Task 3.6 的 `diff`） | `test_alembic_result_matches_apply_ddl_result` | ✅ |
| 用例 7 幂等（autogenerate 到**临时目录**，断言无 `op.`） | `test_autogenerate_converges_on_upgraded_db` | ✅（临时目录实现见 D2） |
| 用例 8 清理只 DROP 本任务建的表 + `alembic_version`，不 `DROP DATABASE`、不碰 `aicore` | `_empty_namespace` / `_drop_shard_tables` | ✅ 只 DROP 6 个固定名 + `alembic_version` + 本用例演练月的 3 张分片表；全程无 `DROP DATABASE`；`aicore` 9 张表未变 |
| 集成用例连不上库时 `pytest.skip` 并说明 | `_drill_engine()` | ✅（缺 `DSH_IT_MYSQL_PASSWORD` 或连不上都 skip 并写明原因；目标库不是 `aicore_test` 则 **fail**） |
| `MUST NOT` `sleep` / 口令入 ini / 硬编码口令 / 探针残留 / `git commit` | 全仓库检查 | ✅ 无 `sleep`；`alembic.ini` 无连接串、无口令（用例反查真实口令未命中）；无 commit |

---

## 5. 偏离工单之处 + 理由（逐条）

| # | 偏离 | 理由（都是实测，不是偏好） |
|---|---|---|
| **D1** | **`alembic.ini` 内**容**全 ASCII、没有中文注释** | alembic 1.20 用 `encoding="locale"` 读 ini（`alembic/util/compat.py: read_config_parser → file_config.read(path, encoding="locale")`）。本机 locale 是 cp936，含中文的 UTF-8 ini 在 `configparser` 阶段直接炸、**任何 alembic 命令都跑不起来**，`PYTHONUTF8=1` 也救不了（`"locale"` 明确要 locale 编码）。原始报错：`UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 38: illegal multibyte sequence`（栈顶 `alembic/config.py:250 in file_config`）。中文说明改放 `deploy/sql/migration/README` 与 `env.py`（由 Python/Mako 读，UTF-8 正常），并在 ini 头部用英文写明"为什么这里不能有中文"，另加用例 `test_alembic_ini_is_ascii_only` 把它钉成不变量（防后人"顺手补中文"再把 CI 打红） |
| **D2** | 集成用例的临时目录**不用 `tmp_path`**，改用自建夹具 `probe_tmp`（`Path.mkdir()`，名字带 `.` 前缀 + uuid，测完 `rmtree`） | 两种官方路径在本机都不可用：① `tmp_path` 建在 `tempfile.gettempdir()`=`C:\Users\<用户>\AppData\Local\Temp\dsh-*`，**在工作区之外、被沙箱拒写**，夹具 setup 直接 `PermissionError: [WinError 5] ...\pytest-of-<用户>`；② 退一步 `tempfile.mkdtemp(dir=<工作区内>)` 也不行——`mkdtemp` 建的目录带 0700 ACL，随后往里写文件同样 `WinError 5`（实测矩阵：`.mypy_cache` / `.ruff_cache` / `.pytest_cache` / 服务根 + mkdtemp 全 FAIL；`Path.mkdir()` + 写文件 4 处全 OK）。替代物性质相同：进程唯一、随用例销毁、**MUST NOT 落在 `versions/`**（用例另有断言守住这一点） |
| **D3** | "破坏性 DDL"的断言**按 `upgrade()` / `downgrade()` 分区**，而不是逐字扫全文 | 工单同时要求"基线里 MUST NOT 出现 `op.drop_table`"与"`downgrade()` MUST 只做基线撤销（`drop_table` 本迁移创建的表）"，逐字扫全文会让两条自相矛盾。落点：`upgrade()` 内 0 个 `drop_*`；`downgrade()` 必须存在（正向要求）且其 `drop_table` 集合 **等于** `upgrade()` 的 `create_table` 集合；全文件无 `drop_column` |
| **D4** | `env.py` 增加**生成期后处理** `strip_redundant_drop_index`（删掉"反正要删的表"自己的 `drop_index`） | autogenerate 的 `downgrade()` 是"先 `drop_index` 再 `drop_table`"，在 MySQL 上**跑不通**：`vision_marker.idx_review` 正是外键 `fk_vision_marker_review` 的支撑索引，实测 `(1553, "Cannot drop index 'idx_review': needed in a foreign key constraint")`。`DROP TABLE` 本就会带走表上的索引与外键，故这些 `drop_index` 多余且有害。**没有手改迁移文件**：这是 Alembic 官方的 `process_revision_directives` 扩展点，重跑 autogenerate 结果一致、可复现（生成物仍是机器产物）。修好后 `downgrade()` = 6 条 `drop_table`，正合工单"只做基线撤销"的原话。**实现踩坑也记一笔**：这些 `drop_index` 藏在 `ModifyTableOps` 里（不是顶层 list），首版只扫顶层 → 过滤静默失效（生成物 10 个 `drop_index` 一个没少），靠临时打印结构才定位 |
| **D5** | `env.py` 增加**降级守卫**：`alembic downgrade` 默认被拒，演练需 `-x allow_downgrade=1` | 把 spec §2.3 / `er.md` §5.6 的"生产禁用破坏性 DDL"从文档变成机制：误敲一次 `downgrade` 的代价是生产少 6 张表。守卫在**连库之前**生效，故默认用例 `test_downgrade_is_refused_without_explicit_flag` 不需要数据库、且把目标库指向一个不存在的库名（即使守卫失效也只会"连不上"，不会伤到任何真库）。**注意一个空洞（已写进模块 docstring）**：`config.cmd_opts` 只在 CLI 路径被赋值，程序化 `command.downgrade(cfg, ...)` 不带它 → 守卫对它不生效；演练一律走 CLI。**同样记一笔实现踩坑**：`cmd_opts.cmd` 不是命令名而是 `(函数, 位置参数名, 关键字参数名)` 三元组，首版拿它跟 `"downgrade"` 比 → 恒不等 → 守卫静默失效（用例里那次 downgrade 真去连了库、报 1045） |
| **D6** | `alembic.ini` 增加 `[post_write_hooks]`（`ruff format` + `ruff check --fix`，`type = module` 走 `python -m ruff`） | 不这么做，**每一个**生成的迁移都会踩本仓的 ruff 门禁：实测基线初版 **23 条 E501**（`sa.Column(...)` 单行长 129~198 列）+ W291 + I001，`ruff check .` 必红。`type = module` 用运行 alembic 的那个解释器执行 ruff，**不把 `ruff.exe` 绝对路径写进入库文件**。修好后 migrations 目录 `All checks passed!` |
| **D7** | `alembic.ini` 增加 `path_separator = os` | alembic 1.20 在没有该项时会发 `DeprecationWarning: No path_separator found in configuration; falling back to legacy splitting on spaces, commas, and colons`，而 legacy 的"冒号切分"在 Windows 上会把 `D:\progrom\...` 从盘符处切断。加上它既消警告，又让多路径选项按 `os.pathsep` 正确切分 |
| **D8** | `compare_server_default=True`（工单只要求 `compare_type=True`） | 不开这一项，DDL 的 `DEFAULT` 与模型 `server_default` 的漂移会被 autogenerate **安静放过**。开了之后实测仍然**收敛为空**（§3 口径 1），说明模型侧 `server_default=text(...)` 的写法与 MySQL 反射结果一致——这条顺带把 Task 3.2 docstring 里"必须显式写 server_default"的说法**验证**了，而不只是声称 |
| **D9** | 连接串两条轨：`DSH_IT_MYSQL_*`（演练库）**优先**，回落 `AICORE_MYSQL_*`（`Settings`） | 工单说"从 `AICORE_MYSQL_*` 组装（复用 `Settings`）"，但只走 `Settings` 会踩两个已知坑：① `tests/conftest.py` 注入的 `AICORE_MYSQL_PASSWORD=test_password` 是占位值 → 假凭据 → 连库被拒 → 用例 skip → **门禁静默失效**；② 本机 `.env` 的 `AICORE_MYSQL_DATABASE=aicore`（**产品库**）→ 演练会落到产品库上。两组变量的分工与两次实测现场写在 `tests/conftest.py` 那一节，`scripts/apply_ddl.py` 早已采用同一约定，这里只是沿用。每次运行第一行都打印遮蔽后的目标库与配置来源（`演练库(DSH_IT_MYSQL_*)` / `应用配置(AICORE_MYSQL_*)`），打错库看得见 |
| **D10** | 用例**多出 2 条**（超出工单 8 条清单）：`test_downgrade_is_refused_without_explicit_flag`（默认跑，无需 DB）、`test_downgrade_with_flag_reverts_baseline`（集成） | 前者是 D5 的正面证据；后者证明基线的 `downgrade()` **真能跑**（不是"只存在一个函数体"——D4 修之前它确实是坏的）。该用例结尾再 `upgrade head` 一次，把演练库留在稳态（6 张表在、版本指向 head） |

---

## 6. 我没做到的事（诚实登记）

| # | 没做到 | 现场与替代 |
|---|---|---|
| **N1** | **"新建空库 → `upgrade head`"这条路径没有验证** | `aicore_dev` 只有两个库的 ALL、**没有建库权限**。本任务实测的判据（**我没有重跑 `CREATE DATABASE`**，不想在共享实例上留下新库）：<br>`GRANT USAGE ON *.* TO 'aicore_dev'@'localhost'`<br>`GRANT ALL PRIVILEGES ON 'aicore'.* TO 'aicore_dev'@'localhost'`<br>`GRANT ALL PRIVILEGES ON 'aicore_test'.* TO 'aicore_dev'@'localhost'`<br>`SHOW DATABASES` → `['aicore', 'aicore_test', 'information_schema', 'performance_schema']`<br>→ `*.*` 上只有 USAGE，建库必然 1044（与工单里实测一致）。**替代物是"空命名空间"**：在 `aicore_test` 里把 6 张固定名表 + `alembic_version` 清掉、当场断言真的空了，再 `upgrade head`。**它验不到的是**：`CREATE DATABASE` 的字符集/排序规则、库级权限、以及"库不存在时 Alembic 的报错形态"。**MUST NOT 谎称验证了建库路径。** |
| **N2** | 工单建议的"**独立表名前缀**"隔离**没有实现** | 基线迁移的表名来自 `Base.metadata`（`op.create_table("vision_review", ...)`），要让它们带上前缀只有两条路：① 手写第二份带前缀的 DDL/迁移——**工单明令禁止**；② 让迁移在运行期从元数据现算表名——那基线就不再是"冻结的时点结构"，模型一改历史迁移跟着变（比前缀问题严重得多）。故退到**同名前缀命名空间的等价验证**：清空 6 个固定名 + `alembic_version`（清完断言），演练月按进程号取（`2098MM`，与 `test_apply_ddl_mysql.py` 的 `2099MM` 错开），分片表用完即删，收尾把 6 张表重建回稳态。**残留风险（如实说）**：6 个固定名是 `aicore_test` 里的**共享名字**，两个进程同时跑本文件的集成用例会互删表；集成用例默认不跑（`-m integration` 才跑），但这条约束是真的 |
| **N3** | 沙箱残留：`services/aicore/probe-7bz35wir/`（**空目录**）删不掉 | 那是我做 D2 可行性矩阵时 `tempfile.mkdtemp` 建出来的目录，带 0700 ACL；`Remove-Item` / `os.rmdir` / `shutil.rmtree` 全部 `WinError 5 拒绝访问`（连 `scandir` 都不行）。影响：**git 不跟踪空目录**，`git status` 只多一行 warning，不影响交付物（`versions/` 干净、无 `__pycache__`）。同目录下另有大量 `pytest-cache-files-*`（pytest 在 `.pytest_cache` 不可写时的回落产物）与 `.sdd-tools.py` / `scripts/group3_acceptance.py`，都是**别人/工具留下的**，我没有动 |
| **N4** | 覆盖率是我**额外**跑的，不是工单要求的门禁命令 | 工单的验收清单里没有 `--cov`；我跑它是为了确认 `fail_under = 80` 没被破坏（结果 97.26%）。`env.py` 与 `versions/*.py` 在 `src/` 之外，不参与覆盖率统计 |
| **N5** | `downgrade()` 的**生产可用性**没有、也不可能在这里验证 | 只有基线一条迁移，`upgrade → downgrade base → upgrade` 的往返在演练库上验过了（集成用例）；但"演进中的多版本降级链"要等第二条迁移出现才有意义。另外工单本身要求 `downgrade()` 只做基线撤销、生产禁用降级（spec §2.3），所以这不是缺口，是**口径**——写在这里免得被误读成"降级已充分验证" |

---

## 7. 给控制者的三句话

1. **`with_variant` 的裁定是对的、并且已被验证**：两处 `with_variant` 让 autogenerate 一次收敛
   （探针迁移空），不需要给迁移打任何补丁，也不需要动 `models.py`。
2. **两条落地路径现在真的等价**：`alembic upgrade head` 与 `apply_ddl.py` 在各自的空命名空间里直建，
   用 Task 3.6 的 `from_information_schema + diff` 比对**差异 0**（两侧各 6 张表，防空比对的假通过）。
3. **本次最大的两个坑与"生产禁用降级"都变成了机制**：
   `alembic.ini` 不能有中文（locale 编码）、MySQL 上 autogenerate 的 `drop_index` 不可执行（1553）、
   以及 `alembic downgrade` 默认被拒（要 `-x allow_downgrade=1`）。
