### Task 3.4: 会话与连接池（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文或反斜杠路径的文件。

**Files:**
- Modify: `src/aicore/core/config.py`（+4 字段与其派生属性）
- Modify: `src/aicore/repository/session.py`
- Modify: `.env.example`（+4 行）
- Modify: `tests/conftest.py`（注入 4 个新变量）
- Modify: `tests/unit/test_config.py`（同步 `EXPECTED_FIELDS` / `REQUIRED_FIELDS`）
- Create: `tests/repository/test_session.py`

**权威依据（MUST 先读，不许只 grep）**：
- spec **§2.3**（库 / 读写分离 / 通用约定）、**§5.4**（会话与连接池：同步会话 + 线程池、读写分离、池大小从配置读取）
- `services/aicore/docs/er.md` **§5.5**（读写分离与冷热归档：主库写、从库读、**写后立即读强制走主库**；池大小见 §5.2 的分片阈值旁注）
- `src/aicore/core/config.py` 模块 docstring（**必填项一律不给默认值** + `extra="forbid"` 两条强取向）
- `tests/unit/test_config.py`（**三处耦合点**，见下）

---

#### 背景：`Settings` 里此前**完全没有**池参数与只读库字段

spec §5.4 要求「池大小**从配置读取，不写死**」，`er.md` §5.5 要求「主库写、从库读」，
但 `Settings` 只有 `mysql_host/port/user/password/database` 五项，全设计文档亦无"只读"二字。
**用户已拍板（2026-09-18，方案 A）**：新增 4 个字段，并允许在关键点由控制者裁定。

#### 新增字段（MUST 照此，含"必填 vs 可选"的区分理由）

```python
# ---- MySQL 连接池（**必填**：容量是部署决策，给默认值等于替运维做决定）----
mysql_pool_size: int = Field(ge=1)
mysql_max_overflow: int = Field(ge=0)

# ---- 只读（从库）地址：留空则回落主库（见 mysql_read_* 属性的注释）----
mysql_readonly_host: str | None = None
mysql_readonly_port: int | None = Field(default=None, ge=1, le=65535)
```

**为什么池参数必填、只读地址可空**（这条区分 MUST 写进字段注释）：
- 池大小是**部署容量决策**，给默认值等于替运维做决定，且"以为配了其实没配"会表现为连接耗尽；
  两字段均 MUST `is_required()`（`test_required_fields_have_no_default` 会逐字段验）。
- `mysql_readonly_host` 是**可选能力**：本机没有从库（只有一个实例），
  若定为必填，任何单实例环境都必须把主库地址**再写一遍**——那是形式主义而非安全。
  故 `None` 明确表达"没有独立从库"，此时只读会话回落主库，**且 MUST 在日志/自检里可见**
  （见下 `read_target_is_primary` 属性），不许把"回落"伪装成"已分离"。

新增派生属性（MUST 有，且 MUST 在原 `mysql_dsn` 旁成组放置）：

```python
@property
def mysql_read_host(self) -> str:        # 只读实际连的 host
@property
def mysql_read_port(self) -> int:        # 只读实际连的 port
@property
def read_target_is_primary(self) -> bool # 只读是否回落到了主库（True 表示**没有**独立从库）
@property
def mysql_read_dsn(self) -> str          # 不含口令，形如 mysql_dsn
```

`mysql_read_host` 的回落**只认 `None`**，MUST NOT 把空串当 `None`：
空串是"配了但配错了"，应抛/报错而不是静默回落（回落会让"配错"变成"看起来正常"）。

#### 三处**必须同步**的耦合点（漏一处就有既有用例变红）

| 位置 | 内容 |
|---|---|
| `tests/unit/test_config.py` | `EXPECTED_FIELDS`（字段全集，`test_...model_fields == set(EXPECTED_FIELDS)`）、`REQUIRED_FIELDS`（必填子集） |
| `.env.example` | 必须加 `AICORE_MYSQL_POOL_SIZE` / `AICORE_MYSQL_MAX_OVERFLOW` / `AICORE_MYSQL_READONLY_HOST` / `AICORE_MYSQL_READONLY_PORT`——`test_env_example_matches_field_names_one_to_one` 强制 `model_fields` 与模板**一一对应** |
| `tests/conftest.py` | `_TEST_ENV_DEFAULTS` 注入 4 个值（只读地址注入 `127.0.0.1`，使测试覆盖"有独立从库地址"这条分支） |

**`REQUIRED_FIELDS` 只加前两个**（池参数），只读两字段 MUST NOT 进 `REQUIRED_FIELDS`（它们是可选的）。

---

#### `repository/session.py` 交付接口

```python
def build_engine(settings: Settings, *, read_only: bool) -> Engine
def session_scope(engine: Engine) -> Iterator[Session]        # contextmanager
def dispose_engines(*engines: Engine) -> None

class EngineFactory:
    def __init__(self, settings: Settings) -> None
    @property
    def write_engine(self) -> Engine
    @property
    def read_engine(self) -> Engine
    @property
    def primary_read_engine(self) -> Engine       # == write_engine（意图显式）
    @property
    def read_target_is_primary(self) -> bool
    @contextmanager
    def write_session(self) -> Iterator[Session]
    @contextmanager
    def read_session(self) -> Iterator[Session]
    @contextmanager
    def primary_read_session(self) -> Iterator[Session]   # 写后立即读
    def dispose(self) -> None

def mark_write_then_read(session: Session) -> None   # 在 session.info 上打标记
def session_needs_primary(session: Session) -> bool
```

**硬约束**：

1. **同步会话 + 线程池**（非 async driver；spec §5.4 已定档，理由：分表动态 SQL 直观、规避"会话跨事件循环"陷阱）。
   MUST NOT 引入 `async_sessionmaker` / `AsyncEngine`。
2. **写会话与只读会话分离**：`write_session()` 用 `write_engine`，`read_session()` 用 `read_engine`。
3. **写后立即读强制走主库**（`er.md` §5.5）：提供 `primary_read_session()` 与 `mark_write_then_read()`，
   **MUST NOT 靠"调用方记得"**——`mark_write_then_read(session)` 在 `session.info` 上打标记，
   `session_needs_primary(session)` 读它；`read_session()` 内若发现会话带该标记，
   MUST 抛 `AiCoreError` 子类（用 `ParamError(code=1002)` 或新增明确的内部错误码均可，
   **但 MUST 在 docstring 里说明选了哪个与为什么**），避免"写完立刻读却从从库读到旧值"这种静默故障。
4. **池大小从配置读取，不写死**：`pool_size` / `max_overflow` 一律取 `settings`；
   MUST NOT 出现 `pool_size=5` 这类字面量。`pool_pre_ping=True` 与 `pool_recycle` 值得开
   （WSL/长连接下 MySQL 8 默认 `wait_timeout` 会掐空闲连接），开与不开 MUST 在 docstring 说明理由。
5. **口令不进 URL 字面量、不进日志**：用 `sqlalchemy.engine.URL.create(...)` 组装（`password=` 参数），
   MUST NOT 手工 f-string 拼 `mysql+pymysql://user:pass@...`。
   `repr(engine)` / `str(engine.url)` 会隐去口令——用例 MUST 正面断言"口令不出现在 dsn/url 的可打印形式里"。
6. **引擎生命周期**：`EngineFactory` 构造**不连接**数据库（SQLAlchemy 惰性连接）；
   `dispose()` MUST 幂等。**MUST NOT** 本任务改 `main.py` 接线（第 4 组接 lifespan；
   若你判断现在就必须接线，**停下来报告**而不是自行改组合根）。
7. `repository` 层 MUST NOT import `service`（契约 3）；只允许 import `aicore.core.*` 与 `sqlalchemy`。

---

#### 用例 `tests/repository/test_session.py`

**不连数据库的部分**（默认跑）：
1. **池参数随配置变化**：用两组不同 `Settings` 造两个 `EngineFactory`，
   断言 `write_engine.pool.size() == settings.mysql_pool_size`、
   `write_engine.pool._max_overflow == settings.mysql_max_overflow`（值**来自配置**，不是常量）。
2. **读写引擎分离**：`readonly_host` 配成与主库不同的地址时，
   `str(factory.read_engine.url)` 与 `str(factory.write_engine.url)` **不同**，且 `read_target_is_primary is False`；
   `readonly_host=None` 时 `read_target_is_primary is True`、两者 host 相同但**仍是两个不同 Engine 对象**。
3. **口令不泄漏**：`mysql_password` 用一个显眼哨兵（如 `SENTINEL_PW_9f3a`），
   断言它不出现在 `repr(engine)`、`str(engine.url)`、`factory.*_dsn` 的可打印形式中。
4. **`readonly_host=""`（空串）MUST NOT 静默回落**：断言抛错或用例可观察地区分"空串"与"None"。
5. **会话生命周期**：`session_scope` 正常退出后 `session.is_active is False`（已关闭）；
   体内抛异常时 MUST 回滚（可用一个**内存 SQLite** 引擎或 `create_engine("sqlite://")` 验证，
   **MUST NOT** 依赖真实 MySQL 做这条）。
6. **写后立即读标记**：`mark_write_then_read(s)` 后 `session_needs_primary(s) is True`；
   `read_session()` 拿到带标记的会话 MUST 抛错（用 `monkeypatch`/直接构造验证，不必真连库）。

**连数据库的部分**（`@pytest.mark.integration`，默认不跑；连不上 MUST `pytest.skip` 并说明）：
7. 用 `aicore_test` 建一个临时表 → `write_session()` 写入 → `primary_read_session()` 读回，
   断言数据在同一事务边界内可见；末尾 `DROP` 自己建的临时表（MUST NOT `DROP DATABASE`）。
8. 断言 `read_session()` 与 `write_session()` 连的是**不同 Engine 对象**且 `pool` 实例不同。

**禁止**：`sleep`；把口令硬编码进用例（用哨兵常量）。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/repository/test_session.py tests/unit/test_config.py -q
.venv\Scripts\python.exe -m pytest tests/repository/test_session.py -q -m integration
.venv\Scripts\python.exe -m pytest -q                       # 全量基线不得变红
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- 全量 `pytest` 基线：Task 3.3 结束时的数字，**不得变红**。
- `mypy` 是 **strict**：`EngineFactory` 的返回类型 MUST 标注（`Engine` / `Session` / `Iterator[Session]`）。
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.4-report.md`，
  含原始输出、逐项验收结论、**偏离项 + 理由**、**没做到的事**（尤其：若本机没有真实从库，
  MUST 如实说明"只读分离是**地址可配**，未验证主从延迟"）。
