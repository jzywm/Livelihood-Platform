### Task 3.3: 按月分表路由（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文或反斜杠路径的文件。

**Files:**
- Modify: `src/aicore/repository/sharding.py`
- Create: `tests/repository/test_sharding.py`

**权威依据（MUST 先读，不许只 grep）**：
- `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` **§2.3**（分片表只有 3 张 / 分片键 / 路由禁令 / ID 形态）、**§5.3**（分表路由三条加固）
- `services/aicore/docs/er.md` **§5.2**（分片矩阵）、**§5.3**（路由规则与事件回写）、**§5.4**（分布式 ID 与主键策略）、**§5.5**（读写分离）
- `src/aicore/core/errors.py`（`ParamError` / `AICORE_ERROR_CODES` 的构造期校验）
- `deploy/sql/ddl/*.template.sql`（模板与 `{table}` / `{month}` 占位符协议）

---

#### 硬约束（逐条来自 spec / er.md，不是我的偏好）

| # | 约束 | 出处 |
|---|---|---|
| S1 | 分片表**只有 3 张**：`ai_task` / `ocr_result` / `ocr_correction`，物理名 `xxx_YYYYMM` | spec §2.3、er.md §5.2 |
| S2 | 分片键 `ShardingKey(account_id, created_at)`；`ocr_result` / `ocr_correction` 随 `task_id` **同月同分片** | spec §2.3、er.md §5.3 |
| S3 | 查询**必须**携带分片键下推；缺失时**直接抛错**，MUST NOT 退化为全表扫描 | spec §2.3（er.md §5.3 原文）+ spec §5.3 的加固 |
| S4 | **禁止跨分片 JOIN / 聚合 / 事务** | spec §2.3、er.md §5.3 |
| S5 | 分表路由一律以业务字段 `created_at` / `task_id` 所在月为准，**不依赖任何内嵌时间戳** | er.md §5.4 L248 |
| S6 | 异步任务结果表同分片：1:1 查询不跨分片 | er.md §5.3 |

---

#### 交付接口（签名 MUST 一致）

```python
SHARDED_TABLES: frozenset[str]          # {"ai_task", "ocr_result", "ocr_correction"}
FIXED_TABLES: frozenset[str]            # 6 张非分片表
ALL_TABLES: frozenset[str]              # 9 张

def shard_month_of(created_at: datetime, *, field: str = "created_at") -> str
def physical_table_name(logical: str, at: datetime | str) -> str
def template_for(logical: str) -> Path                  # 分片表模板路径
def render_shard_template(logical: str, month: str) -> str
def ensure_month_tables(conn: Connection, month: str) -> None
def render_fixed_table_ddl(logical: str) -> str

class MissingShardKeyError(ParamError)      # code = 1001
class CrossShardOperationError(ParamError)  # code = 1003
def require_shard_key(value: object, *, field: str) -> None
def assert_single_shard(months: Iterable[str], *, operation: str) -> str
```

**`MissingShardKeyError` / `CrossShardOperationError` 的码值（MUST 照此，理由写进 docstring）**：
- `MissingShardKeyError` → **`1001`**（`errors.py` L47：「`missing` —— 必填项没送到」；spec §5.3 的加固正是"缺分片键"）
- `CrossShardOperationError` → **`1003`**（`errors.py` L48：「**枚举或范围非法**」）。
  依据：跨分片是"两个月的分片键被组合进同一次操作"，属**取值组合越界**，落在 `1003` 的"范围非法"语义内。
  **不要**用 `1002`：L52 明写 `1002` 是「其余全部 …… **兜底档**」，
  即"三桶都归不进去"的兜底；跨分片能明确归类，用兜底档会让码值语义漂移
  （plan §Task 3.3 亦定 1003）。
  **也不要**用 `3007` 之类"业务规则"段的码：`3007` 已锁 `409 资源冲突`（见 `errors.py` 的 HTTP 映射表），
  与"请求参数组合非法"不是一回事。

两者都 MUST 继承 `ParamError`（而非直接 `AiCoreError`）并传 `code=`，理由：
`ParamError` 是**唯一**做了"码值必须落在 `PARAM_ERROR_CODES` 内"构造期校验的类，
直接继承 `AiCoreError` 就绕过了这道校验。**保留 `ParamError` 的校验、改类名表达语义** —— 两者都要。

`shard_month_of` 只收 `datetime`（**不收 `str`**）：物理月必须由业务时间字段算，不收字符串可避免
"随手传个 `2026-01-15` 也能过"的模糊入口。**`ocr_result` / `ocr_correction` 的月份由 `task_id` 对应任务的
`created_at` 决定**——`task_id` 本身**不含时间戳**（er.md §5.4 L248 明确"不依赖任何内嵌时间戳"），
故调用方 MUST 传入该任务的 `created_at`；本模块**MUST NOT** 尝试从 `task_id` 解析月份。
`physical_table_name(logical, at)` 的 `at` 允许 `str`（已是 `YYYYMM` 的分片月，供"已知月份"的调用方复用），
`str` 入参 MUST 校验为 6 位数字且**月份在 01~12**，否则抛 `ParamError(code=1002)`。

`render_shard_template` **MUST** 在渲染后自检"无 `{` 残留"（模板写错时立刻炸，而不是把不可执行 SQL 送去数据库）。
渲染实现 MUST 与 Task 3.1 的 `scripts/apply_ddl.py` **共用同一份逻辑**：
本模块是唯一实现处，`apply_ddl.py` MUST 改为 import 本模块的函数（**MUST NOT 各写一份**——
两份渲染实现会漂移，而漂移的表现是"脚本建的表与运行期建的表不是同一个结构"）。

`render_fixed_table_ddl(logical)` 只对**非分片表**有效；传分片表 MUST 抛 `ParamError(code=1002)`
（反向同理：`render_shard_template` 传非分片表也抛）。

---

#### 时区口径（MUST）

`er.md` §6 绪：**UTC 存储**。故：
- `shard_month_of` 对 **aware** datetime MUST 先 `astimezone(timezone.utc)` 再取 `%Y%m`
  —— 否则"本地 2026-01-01 00:00"会被算成 `202601`，而它 UTC 是 `202512`，**跨月错片**；
- 对 **naive** datetime MUST 抛 `ParamError(code=1002)` 并说明"时间必须带时区"，
  **MUST NOT** 猜它是 UTC 还是本地时间（猜错就是静默错片）。

**跨月边界用例 MUST 用可控时钟/显式构造的 datetime，测试内 MUST NOT 出现 `sleep`**
（spec §6 约定）。必须覆盖：
- `2026-01-31T23:59:59.999Z` → `202601`；`2026-02-01T00:00:00.000Z` → `202602`（相邻毫秒跨月）
- 带 `+08:00` 的 `2026-01-01T00:00:00+08:00` → **`202512`**（UTC 归属上一年 12 月）
- 闰年 `2028-02-29T12:00:00Z` → `202802`
- naive datetime → 抛 `ParamError`

#### `ensure_month_tables(conn, month)`

- 建表顺序 **MUST** 为 `ai_task` → `ocr_result` → `ocr_correction`（被引用表先建；er.md §5.2、§7.3、
  spec §5.1 的"建表顺序"硬要求）；
- 幂等（模板已是 `CREATE TABLE IF NOT EXISTS`；复跑 MUST 零错误）；
- 用 `conn.exec_driver_sql(sql)` 执行（`Connection` 类型取 `sqlalchemy.engine.Connection`）；
- 分片表物理名与**外键约束名**都由 `render_shard_template` 渲染，故 `{month}` MUST 同时替换到约束名里
  （Task 3.1 的 FIX-4 已定：约束名形如 `fk_ocr_correction_task_{month}`）；
- **MUST NOT** 在函数内 `DROP` 任何东西、**MUST NOT** 提交事务（事务边界归 Task 3.4/3.7）。

#### 跨分片守卫

`assert_single_shard(months, operation=...) -> str`：传入本次操作涉及的**全部**月份；
长度 0 → `MissingShardKeyError`；去重后 >1 → `CrossShardOperationError`
（消息 MUST 点名 `operation` 与涉及月份，便于运维定位）；恰好 1 → 返回它。
`require_shard_key(value, field=...)`：`None` / 空串 / 仅空白 → `MissingShardKeyError`。
两个函数的 docstring MUST 引用 S3/S4 的出处。

---

#### 用例 `tests/repository/test_sharding.py`（**纯逻辑，不连数据库**）

MUST 包含（缺一即返工）：
1. **S1 表清单**：`SHARDED_TABLES` / `FIXED_TABLES` / `ALL_TABLES` 逐项断言（3 / 6 / 9）。
2. **物理名**：3 张分片表 × 跨 2026-01/02 → `xxx_202601` / `xxx_202602`；非分片表传入 → 抛错。
3. **`shard_month_of` 边界四条**（见上），含 `+08:00` 跨年那条与 naive 抛错。
4. **模板渲染**：三张分片表渲染后**剥注释**无 `{` 残留；`render_fixed_table_ddl` 对分片表抛错。
5. **缺分片键**：`require_shard_key(None)` / `("")` / `("   ")` 各抛 `MissingShardKeyError`；
   且断言 `MissingShardKeyError.code == 1001`（**逐字**，不靠继承推断）。
6. **跨分片**：`assert_single_shard(["202601", "202602"])` 抛 `CrossShardOperationError`
   且 `code == 1003`（**逐字**）；`["202601", "202601"]` 通过并返回 `"202601"`；`[]` 抛 `MissingShardKeyError`。
7. **错误类语义**：两个异常都 MUST 是 `ParamError` 的子类（`issubclass` 断言），
   且 `AiCoreError` 的码值校验仍然生效（用一个假码构造 MUST 抛 `ValueError` 的反证）。
8. **`ensure_month_tables` 的真实 MySQL 用例**：放在本文件内并标 `@pytest.mark.integration`
   （默认不跑）。连不上 MySQL → **显式 `pytest.skip`**（不是静默通过）。跑通则断言：
   9 张表在 `aicore_test` 存在（3 张 `_<演练月>`）、外键约束名带月份、**第二次调用零错误**（幂等）、
   建表顺序通过**顺序探测**验证（可先只建 `ai_task`+`ocr_result` 再单独建 `ocr_correction` 成功；
   反序 MUST 失败——用 `pytest.raises` 断言 MySQL 报外键找不到被引用表）。
   用例末尾 MUST 清理自己建的 3 张 `_<演练月>` 表（**只 DROP 自己建的分片表**，
   MUST NOT `DROP DATABASE`、MUST NOT 碰固定名表）。

**禁止**：用 `time.sleep` / 用真实当前时间做跨月断言的唯一依据（跨月必须显式构造 datetime）。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -q
.venv\Scripts\python.exe -m pytest tests/repository/test_sharding.py -q -m integration
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- 全量 `pytest` 基线：Task 3.1 修正轮结束时的数字（**不得变红**）。
- `repository` 层 MUST NOT import `service`（契约 3）——`sharding.py` 只允许 import `aicore.core.*` 与 `sqlalchemy`。
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.3-report.md`，
  含原始输出、逐项验收结论、**偏离项 + 理由**、**没做到的事**。
