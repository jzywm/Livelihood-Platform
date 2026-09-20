### Task 3.7: repository 层数据访问（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件。

**Files:**
- Modify: `src/aicore/repository/base.py`
- Modify: `src/aicore/repository/task_repo.py`
- Modify: `src/aicore/repository/ocr_repo.py`
- Modify: `src/aicore/repository/correction_repo.py`
- Modify: `src/aicore/repository/verdict_repo.py`
- Create: `tests/repository/test_repos.py`

**依赖的前序任务（MUST 已落地，MUST 先读它们的实现）**：
- Task 3.2 `repository/models.py`（9 个模型 + `Base` + `LOGICAL_TABLE_NAMES`）
- Task 3.3 `repository/sharding.py`（`physical_table_name` / `shard_month_of` / `assert_single_shard` /
  `MissingShardKeyError` / `CrossShardOperationError` / `ensure_month_tables`）
- Task 3.8 `core/idgen.py`（`new_id(kind)`）

**与 Task 3.4 的解耦（重要，决定你能不能独立开工）**：
Task 3.4 的 `repository/session.py` 提供 `EngineFactory` / `write_session` / `read_session` /
`primary_read_session`；但**本任务的仓储方法一律收调用方传进来的 `Session` 对象**，
**MUST NOT** import `EngineFactory`，也 MUST NOT 自己开引擎/会话、MUST NOT `commit()`。
理由：会话与事务边界归**调用方**（service 层），仓储只负责"在这个会话里怎么读写这张分片表"。
好处是本任务**不阻塞于 3.4**——本任务的用例用 `sqlite` 内存库或自建引擎即可跑通，
不必等 `session.py` 落地。若你确实需要 3.4 的产物（例如想验证只读会话），
**在报告里写明并跳过那一条**，不要为它停下整个任务。

**权威依据（MUST 先读）**：
- spec **§2.3**（分片键 / 路由禁令）、**§5.7**（repository 层四类与事务边界）
- `services/aicore/docs/er.md` **§5.3**（禁止跨分片 JOIN / 聚合 / 事务）、**§5.5**（写后立即读强制走主库）、
  **§7.1~§7.9**（每张表的索引与约束，尤其 §7.6 的"每审核记录至多一条结论"与"只增不改"）

---

#### 硬约束（逐条带出处）

| # | 约束 | 出处 |
|---|---|---|
| R1 | **所有读取方法的签名 MUST 收分片键**；缺分片键由 Task 3.3 的守卫抛错，**MUST NOT 退化为全表扫描** | spec §2.3、§5.3 |
| R2 | **单表一事务；同分片跨表可合并；跨分片拆为多次独立事务 + 幂等补偿**；**MUST NOT 引入分布式事务** | spec §5.7、er.md §5.3 |
| R3 | **写后立即读强制走主库** | er.md §5.5 |
| R4 | `review_verdict` **每审核记录至多一条结论**（1:1，主键即 `review_id`）；**只增不改** | er.md §7.6 |
| R5 | `ocr_correction` **只增不改**（纠错留痕不可篡改，保障评估集可信） | er.md §7.3 |
| R6 | 任务**仅本人可查**，跨账号报 `2002`（水平越权）——越权判定属 service 层，但 repository MUST **提供按 `account_id` 过滤的能力**，MUST NOT 提供"只按 task_id 查、不带账号"的便捷入口 | er.md §3（越权）、spec §4.3 |
| R7 | `repository` MUST NOT import `service`（契约 3）；MUST NOT import `provider` | `.importlinter` 契约 3、4 |

#### `repository/base.py` 交付内容

```python
@dataclass(frozen=True)
class ShardKey:
    """分片键：account_id + created_at（er.md §5.3 的 ShardingKey 约定）。"""
    account_id: str
    created_at: datetime
    @property
    def month(self) -> str            # 由 shard_month_of(created_at) 现算，MUST NOT 缓存成可写状态

class BaseRepo(Generic[ModelT]):
    """仓储基类：把"分片表名解析 + 跨分片拒绝"收在一处。"""
    logical_table: ClassVar[str]
    def physical_name(self, key: ShardKey) -> str
    def require_same_shard(self, *keys: ShardKey, operation: str) -> str

def cross_shard_transaction_guard(operation: str) -> Callable[[F], F]
    """装饰器：拒绝在**多个分片**上开事务（R2）。"""
```

**关键设计（MUST 照此，理由写进 docstring）**：
- `ShardKey.month` 是**派生属性**而非字段：让它无法与 `created_at` 漂移（把月份缓存成字段，
  改了 `created_at` 忘了改 `month` 就会静默错片，而错片的表现是"数据写到了另一个月的表里"）。
- **不变式**：`ShardKey` 必须由 `account_id` + **aware** `created_at` 构造；
  `__post_init__` MUST 校验 `created_at.tzinfo is not None`（naive 时间跨月会错片，
  校验收在构造期比散在各调用点可靠）。naive 时抛 `ParamError(code=1002)`。
- `require_same_shard(*keys, operation=...)` MUST 委托 Task 3.3 的
  `assert_single_shard`（**MUST NOT 各写一份**），并把它收到的月份转成可读消息。
- `cross_shard_transaction_guard` 的语义：被装饰的函数若在一次事务里对**两个不同月份**发起写，
  MUST 抛 `CrossShardOperationError`。实现方式自选（建议：装饰器读取函数收到的全部 `ShardKey`，
  交给 `require_same_shard`），但 MUST 有一条用例正面证明它**真的会拒**。

#### 四个仓储（`TaskRepo` / `OcrRepo` / `CorrectionRepo` / `VerdictRepo`）

每个仓储 MUST 提供（签名照此，**所有读取方法都带分片键**）：

```python
class TaskRepo(BaseRepo[AiTask]):
    def insert(self, session: Session, entity: AiTask) -> None
    def get_by_id(self, session: Session, task_id: str, *, shard: ShardKey) -> AiTask | None
    def list_by_account(self, session: Session, *, shard: ShardKey, limit: int, offset: int) -> Sequence[AiTask]
    def update_status(self, session: Session, task_id: str, *, shard: ShardKey,
                      status: str, progress: int, finished_at: datetime | None) -> int   # 返回受影响行数
    def find_by_idem_key(self, session: Session, *, shard: ShardKey, account_id: str, idem_key: str) -> AiTask | None

class OcrRepo(BaseRepo[OcrResult]):
    def insert(self, session: Session, entity: OcrResult) -> None
    def get_by_id(self, session: Session, task_id: str, *, shard: ShardKey) -> OcrResult | None

class CorrectionRepo(BaseRepo[OcrCorrection]):
    def insert(self, session: Session, entity: OcrCorrection) -> None
    def list_by_task(self, session: Session, task_id: str, *, shard: ShardKey, limit: int, offset: int) -> Sequence[OcrCorrection]

class VerdictRepo(BaseRepo[VisionReview]):        # 非分片表
    def insert_review(self, session: Session, entity: VisionReview) -> None
    def get_review(self, session: Session, review_id: str) -> VisionReview | None
    def insert_verdict(self, session: Session, entity: ReviewVerdict) -> None
    def get_verdict(self, session: Session, review_id: str) -> ReviewVerdict | None
```

- **`VerdictRepo` 的两张表都不分片**（`er.md` §5.2），故其方法**不**收分片键——
  这不是违反 R1，而是 R1 的前提（"分片表"）不适用。**MUST 在其 docstring 里写明**这一点，
  否则下一个读者会以为漏了分片键。
- 分片表的表名 MUST 由 `BaseRepo.physical_name(shard)` 现算。**三条候选路径**（按推荐度排列，
  **实现者 MUST 选一条并说明实测依据**，不要凭猜测选）：

  | 路径 | 做法 | 备注 |
  |---|---|---|
  | **① `table_prefix` + 语句改写**（SQLAlchemy 官方 sharding 示例的做法） | 建表时用占位前缀（如 `__prefix__ai_task`），在 `before_cursor_execute` 事件里按 `execution_options(table_prefix=...)` 把前缀替换成 `202607_` | 官方示例见 `examples.sharding.separate_tables`（[源码](https://docs.sqlalchemy.org/en/14/_modules/examples/sharding/separate_tables.html)）；**读/写都覆盖**，且不碰 `__tablename__` |
  | ② `aliased(Model, name=physical)` | 用 `aliased()` 造一个带物理表名的模块级别名，`select`/`insert`/`update` 都走它 | 更"ORM 原生"，但**写入路径是否完全可用需你自己实测**（`aliased()` 的传统用途是 SELECT） |
  | ③ `sqlalchemy.text()` 手写 SQL | 最直白 | **最后手段**：会丢掉类型/参数绑定安全，且与"模型是唯一代码侧映射"（Task 3.2）的取向相悖；选它 MUST 在报告里给出理由与参数绑定方案 |

  **MUST NOT** 在 `models.py` 上改 `__tablename__`（Task 3.2 已定：元数据里只有逻辑名，
  Task 3.6 的三源比对依赖这一点）。若三条路径都实测不可行，**停下报告**并附实测报错原文，
  **不要**自行改 `__tablename__` 或另建第二套模型。
- **`update_status` MUST 只更新允许的列**（status/progress/finished_at），
  **MUST NOT** 用 `session.merge(entity)` 这类"整行覆盖"写法（会顺手把 `created_at`、
  `model_meta` 等列覆盖成内存里的旧值）。返回受影响行数，供调用方判断"是否存在"。
- **R4 的落地**：`insert_verdict` MUST 在插入前检查该 `review_id` 是否已有结论
  （或在 `review_id` 主键冲突时把它转成明确的业务异常——**选哪个 MUST 说明理由**）；
  **MUST NOT** 实现"覆盖已有结论"的更新路径（`er.md` §7.6 只增不改）。
- **R5 的落地**：`CorrectionRepo` MUST 只有 `insert` + 只读方法，**MUST NOT** 有 `update` / `delete`。
- **`find_by_idem_key`** 对应 `uk_idem(account_id, idem_key)`（`er.md` §7.1）：同 `imageKey`+`docType`
  重复提交 OCR 返回原任务号。**MUST NOT** 让它在没有 `account_id` 的情况下被调用（分片键即账号）。

#### 用例 `tests/repository/test_repos.py`

**不连数据库的部分**（默认跑）：
1. `ShardKey` 不变式：naive `created_at` 抛 `ParamError`；aware 正常；`month` 与
   `shard_month_of(created_at)` 结果一致。
2. `require_same_shard` 同月通过、跨月抛 `CrossShardOperationError`（`code == 1003`）、空集抛
   `MissingShardKeyError`。
3. **R4/R5 的结构断言**：`CorrectionRepo` **没有** `update*`/`delete*` 属性；
   `VerdictRepo` **没有** `update_verdict`/`delete_verdict`。用 `dir()`/`getattr` 断言，
   并说明这是"防回归"的弱断言、真正的保证在评审。
4. **签名断言（R1 的机械证据）**：用 `inspect.signature` 遍历四个仓储的**全部公开读取方法**，
   断言其参数里有 `shard`（`VerdictRepo` 的非分片方法例外，MUST 用**显式白名单**列出例外，
   MUST NOT 用"名字里含 review"之类的模式匹配——白名单才看得出谁被豁免了）。
5. `update_status` **MUST NOT** 覆盖非目标列：用 `sqlite` 内存库或直接检查它构造的
   `update()` 语句的 `_values` keys 集合恰为 `{status, progress, finished_at}`。

**连数据库的部分**（`@pytest.mark.integration`，默认不跑；连不上 MUST `pytest.skip` 并说明）：
6. 在 `aicore_test` 上建演练月分片表 → 四类存取各一次（插入 → 按分片键读回 → 更新 → 再读）
   → 断言 `update_status` 返回 1、且只有目标列变化；
7. **跨分片被拒**：在一次 `cross_shard_transaction_guard` 内对两个月写入，MUST 抛
   `CrossShardOperationError`，且**断言没有分布式事务被开启**（即：没有 `two_phase` /
   `prepare` 调用；可用 `sqlalchemy.event` 监听 `begin_twophase` 断言**零次触发**）；
8. **R4 实证**：对同一 `review_id` 插两次结论，第二次 MUST 失败（且失败形态明确）；
9. 末尾清理自己建的分片表（**MUST NOT `DROP DATABASE`**、MUST NOT 碰固定名表——
   若测验需要 `review_verdict` 等固定表，MUST 用**独立前缀的临时表**而非真实表）。

**禁止**：`sleep`；在生产表（`aicore` 库）上跑写入用例。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_repos.py -q
.venv\Scripts\python.exe -m pytest tests/repository/test_repos.py -q -m integration
.venv\Scripts\python.exe -m pytest -q                       # 全量基线不得变红
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src                                  # strict，Generic[ModelT] 必须过
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- `mypy` strict 下 `Generic[ModelT]` + `Sequence[...]` 返回类型 MUST 干净标注。
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.7-report.md`，
  含原始输出、**R1~R7 逐条证据**、逐项验收结论、**偏离项 + 理由**、**没做到的事**。
