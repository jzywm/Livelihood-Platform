### Task 4.7 + 4.8: 任务执行器内核与线程池边界（步骤级工单，T2）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**（`redis` 已在依赖里）。
**编码**：UTF-8 无 BOM / LF；用 write/edit 工具，**MUST NOT** 用 PowerShell `Set-Content`/`Out-File` 写中文。
**Shell**：`sh` 不可用（`E_ACCESS_DENIED`），命令一律 PowerShell；**每个 pwsh 调用前先 `$env:PYTHONUTF8='1'`**。
pytest 加 `-p no:cacheprovider`；**要看 `passed` 计数行必须写 `-o addopts=""`**。

**Files:**
- Create: `src/aicore/core/lease.py`（`LockStore` Protocol + 内存实现 + Redis 实现 + Lua 脚本）
- Create: `src/aicore/core/task_runner.py`（1 行空壳 → 执行器内核）
- Create: `src/aicore/repository/task_lease_store.py`（**新增**：把「扫可领取任务」的 SQL 隔离在此，见 §3）
- Create: `tests/unit/test_lease.py`、`tests/unit/test_task_runner.py`、`tests/unit/test_cpu_pool.py`
- Create: `tests/integration/test_lease_redis.py`、`tests/integration/test_runner_redis.py`（**真实 Redis**）
- Modify: `tests/conftest.py`（**只允许加** Redis 集成夹具与 `DSH_IT_REDIS_*` 默认值；其余一字不动）
- Modify: `src/aicore/main.py`（**只允许在 lifespan 里装配/启动/停止执行器**；其余一字不动）
- **MUST NOT 改**：`provider/**`、`repository/**` 的**既有文件**、`core/config.py`、`core/errors.py`、
  `core/envelope.py`、`api/**`、`service/**`、`pyproject.toml`、`.importlinter`、`tests/` 下的既有文件。

---

## 0. 先读这些（**MUST 用 read 工具完整读，不是 grep**）

1. `openspec/changes/implement-aicore-service/tasks.md` **L43-44**（4.7 / 4.8 的验收原文）
2. `design.md` **§异步并发与任务执行器内核 L196-212**（并发模型表、领取原子性、重试与退避、并发度与背压）
3. `design.md` **D2 L42-50**（`ai_task` 为唯一事实源、Redis 原子领取、M2 若切 MQ 只替换领取实现）
4. `services/aicore/docs/er.md` **§7.1 L425-435**（`ai_task` 索引与约束、状态机）、
   **§5.5 L252**（写后立即读走主库）、**§6.1 L284-298**（各列语义）
5. `docs/design/高并发架构演进设计.md` **L260 / L294 / L316 / L317 / L318 / L423**（超时、重试、熔断数值）
6. `src/aicore/core/lease.py` 不存在 → 先读 `src/aicore/provider/guard.py`
   （**现成的范式**：`StepClock` Protocol + `system_clock()` + 注入时钟，MUST 照它的风格写）
7. `src/aicore/repository/task_repo.py`（既有能力：`insert` / `get_by_id` / `update_status` / `find_by_idem_key`）
8. `src/aicore/repository/base.py` 的 `ShardKey` / `physical_table` / `BaseRepo`（**不要改它**）
9. `src/aicore/service/task/registry.py`（`get_policy` / `TaskPolicy.timeout_s` / `TaskPolicy.retryable`）
10. `tests/conftest.py`（`api_client` / `sandbox_engine` 夹具与**会话级 socket 守卫**）

---

## 1. 三个必须知道的**实测事实**（控制者已验，省你一轮）

### 1.1 `redis` 包版本是 **8.1.0**，且有两个 API 陷阱

```
redis.__version__ = 8.1.0
AsyncRedis.set 支持 nx / xx / px / ex / keepttl   ← 但组合有约束（见下）
AsyncRedis.renamenx 的签名里**没有** px 参数      ← 别想用它做"带过期时间的改名"
```

**陷阱 A（续期）**：`SET k v XX PX ms` 在 redis-py 里**不能**同时要 `keepttl`；而 `XX` 是"键存在才写"。
**续期必须保证「仍归我所有」**，故 MUST 用 Lua（见 §2.3），MUST NOT 用
`set(key, token, xx=True, px=lease_ms)`——它不校验 owner，**任何实例都能续期别人的租约**，
那正是 `design.md:208` 要防的「两个实例同时处理同一任务」。

**陷阱 B（领取）**：裸 `SET k v NX PX ms` 只能表达"键不存在则设置"，
**不能同时把尝试计数 +1**（而 `max_retries` 的判据是"领取次数"，见 §2.4）。故也用 Lua。

### 1.2 `ai_task.type` / `status` 是**原生 MySQL ENUM** + `validate_strings=True`

```
type   -> ENUM('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT')
status -> ENUM('PROCESSING','SUCCEEDED','FAILED','MANUAL_REVIEW')
```

**后果**：用非法值探测会抛 `Data truncated`，**写不进去**。故集成用例
**MUST NOT** 用"写一个非法枚举看它报错"来做探测——用 `VISION_REVIEW`（合法值）或直接改库。

### 1.3 Windows 上 `asyncio.new_event_loop()` 会真发起一次**回环** connect

（Proactor loop 的 self-pipe，控制者实测 1 次）。`tests/conftest.py` 已有**会话级 socket 守卫**
（判据：目标非环回 **且** 栈里有本项目帧）。故：**任何非环回的对外连接都会被守卫判红**，
而 Redis 在 `127.0.0.1` 属环回 → **集成用例连本机 Redis 不会被拦**，
但 **MUST NOT** 让默认段（离线）去连 Redis。

---

## 2. 交付接口

### 2.1 `core/lease.py` —— `LockStore` Protocol

```python
LeaseToken = str          # 每次领取生成的新 token（owner 身份 + 唯一性）

@dataclass(frozen=True, slots=True)
class TaskClaim:
    task_id: str
    token: LeaseToken
    attempt: int          # 第几次领取（从 1 起）；判据 = attempt > max_retries 即超限

class LockStore(Protocol):
    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        """原子领取：成功返回 TaskClaim，键已被占用则返回 None。MUST NOT 阻塞等待。"""
    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        """续期。**仅当键仍归本 token 所有**时成功；否则返回 False（调用方据此放弃任务）。"""
    async def release(self, claim: TaskClaim) -> bool:
        """主动释放（任务结束）。仅当仍归本 token 所有时删除。"""
    async def is_deferred(self, task_id: str) -> bool:
        """是否处于**退避等待期**（见 §2.4 的退避实现）。"""
    async def defer(self, task_id: str, *, delay_s: float) -> None:
        """把任务置入退避等待期：`delay_s` 秒内 `acquire` 必须失败。"""
    async def close(self) -> None: ...
```

**两个实现，MUST 都提供**：

```python
class InMemoryLockStore:   # 确定性、无 IO、供默认段用例；内部按"注入时钟"判过期
    def __init__(self, *, clock: StepClock | None = None) -> None: ...

class RedisLockStore:      # 真实实现，redis.asyncio
    def __init__(self, *, host: str, port: int, db: int, clock: StepClock | None = None) -> None: ...
```

`StepClock` / `system_clock()` **直接复用 `provider/guard.py` 的**（`core` 不得 import `provider`？
——**能 import**：契约 4 禁的是 `core → service/provider/repository/port` **整包**，
而 `provider/guard.py` 在禁止列表里（`aicore.provider` 是 forbidden）。
**故 MUST NOT 复用**：把 `StepClock` Protocol 在本文件里**重新声明一份**（两处 Protocol 各自独立，
在报告里登记这个重复及其原因）。`system_clock` 同此。

### 2.2 `core/lease.py` —— Lua 脚本（**MUST 用脚本，MUST NOT 用多条命令拼**）

```lua
-- acquire.lua
-- KEYS[1] = 租约键  KEYS[2] = 尝试计数键  KEYS[3] = 退避键
-- ARGV[1] = token   ARGV[2] = lease_ms    ARGV[3] = count_ttl_ms
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end          -- 退避中 → 不可领取
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) == false then return 0 end
local n = redis.call('INCR', KEYS[2])
if n == 1 then redis.call('PEXPIRE', KEYS[2], ARGV[3]) end
return n                                                          -- 返回尝试序号（≥1）

-- renew.lua
-- KEYS[1] = 租约键  ARGV[1] = token  ARGV[2] = lease_ms
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1

-- release.lua / defer.lua 同理（release 校验 token 后 DEL；defer 用 SET 带 PX 写退避键）
```

**控制者已在真实 Redis（8.0.5）上跑通上面两段脚本**，原始输出如下 —— 你可以照抄，
不必再从零推 Lua 语义（尤其 `SET ... NX` 在键已存在时返回 **`false`** 这一点）：

```
首次领取 attempt      = 1        （期望 1）
二次领取（未过期）    = 0        （期望 0）
PTTL                  = 4999     （期望 0 < ttl <= 5000）
错误 token 续期       = 0        （期望 0）
正确 token 续期       = 1，新 PTTL = 9000
退避中领取            = 0        （期望 0）
释放后再领取 attempt  = 2        （证明计数在累加，不因释放而清零）
清理后残留键          = []
```

- 注册用 `client.register_script(...)`（**实测可用**）；MUST NOT 用 `eval` 拼字符串。
- **`defer` 的键与租约键分离**：退避期间租约键应已过期（否则别人领不到），
  故「等待期」是**独立状态**，不靠"租约还没过期"来表达。
- **`is_deferred` 只读**，不得有副作用（用例会连调两次断言结果一致）。

### 2.3 `core/lease.py` —— 过期与回收的**唯一判据**

租约"过期"由 **Redis 的 `PX` 自动过期**承担（`InMemory` 用注入时钟模拟），
**MUST NOT** 在应用侧再维护一份"过期时间表"——两份时间源必然漂移，
而漂移的表现是「两个实例都认为自己是 owner」。

### 2.4 退避与超限（**本任务最容易写错的地方**）

`design.md:210` 逐字：「失败按指数退避重试，超过最大次数置 `FAILED` 并转人工复核队列
（对应用例：不静默丢单）」。**落到本栈的实现口径（控制者裁定，MUST 照此）**：

| 项 | 口径 | 依据 |
|---|---|---|
| 尝试次数 | **= 领取次数**，由 `acquire.lua` 的 `INCR` 计数 | `ai_task` **没有** attempts 列（`er.md` §6.1 L284-298 逐列可查），故计数只能落 Redis；用领取次数而非失败次数，因为"领取了但进程崩了"同样消耗一次尝试 |
| 超限判据 | `attempt > settings.max_retries` | `settings.max_retries` 默认 3（`core/config.py`，字段已存在） |
| 超限动作 | `status=FAILED`、`error_code=<最后一次的码>`、`finished_at=<now>`、`progress` 保持原值 | `er.md` §6.1 L294「FAILED 业务码」/ L298「完成时间（终态时）」 |
| 退避 | `delay_s = BACKOFF_BASE_S * 2 ** (attempt - 1)` | `高并发 L260`「指数退避（1s→2s→4s…）」 |
| 退避实现 | `defer(task_id, delay_s=...)` 写**退避键**（带 `PX`），到期自动消失 → 任务重新可见 | 不需要新列；`acquire.lua` 已检查该键 |
| **可重试性** | `policy.retryable` 为 `False` 的类型（`RISK_PREDICT`）**不进入退避**，直接按超限处理 | `design.md:185` 要求处理器"声明……是否可重试"——声明了就必须被用上，否则那个字段是装饰 |

`BACKOFF_BASE_S` 与轮询间隔 `POLL_INTERVAL_S`：**设计文档未给数值**，
故写成**本模块的 `Final` 常量**并注明出处与"未定档"（MUST NOT 凭空加 `Settings` 字段：
第 4 组 P 阶段加 4 个护栏字段是用户批准的，本任务没有这个授权）。

### 2.5 `core/task_runner.py` —— 执行器内核

```python
@dataclass(frozen=True, slots=True)
class RunnerConfig:
    lease_ms: int
    max_retries: int
    concurrency_limit: int
    poll_interval_s: float = POLL_INTERVAL_S

@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """可领取任务的**最小**信息（不含 handler，handler 由 TaskStore 之后按 policy 解析）。"""
    task_id: str
    task_type: str
    account_id: str
    created_at: datetime

class TaskPolicy(Protocol):
    """执行器**真正用到**的策略面：只有 `task_type` 与 `retryable`。

    ## ⚠️ 工单修正（2026-09-19，起因是本节初版与契约 4 自相矛盾）

    初版这里写的是 `from aicore.service.task.registry import TaskPolicy, get_policy`，
    而 §2.1 与 §4 又逐字要求 `core` 不得 import `aicore.service` —— **两句不能同时成立**。
    实测（`lint-imports --config .importlinter`）：

    ```
    core 不得依赖任何业务层                                  BROKEN
    -   aicore.core.task_runner -> aicore.service.task.registry (l.138)
    Contracts: 3 kept, 1 broken.
    ```

    契约 4 是**包级 forbidden**，不认「只取纯声明 dataclass」这种推断。故改为：

    - **`core` 侧就地声明本 Protocol**，只声明它真正用到的两个成员；
    - **策略由组合根注入**：`main.py` 传 `dict(REGISTRY)`；
    - 运行期由注册表的 `TaskPolicy` **结构化满足**（已实测：`TaskPolicy` 是
      `frozen=True, slots=True` 的 dataclass，6 个字段全是 `str`/`float`/`bool`，
      **没有任何 `service.*` 类型**，故同形 Protocol 成立）。

    **为什么只声明两个成员、MUST NOT 抄全 6 个字段**：抄全等于把 `service` 的结构
    复制进 `core`，正是契约 4 要防的耦合方向。
    """

    task_type: str
    retryable: bool

class TaskStore(Protocol):
    """`ai_task` 的**执行侧**抽象（由 `main.py` 注入 `repository/task_lease_store.py` 的实现）。

    **全部方法是同步的**（`def`，不是 `async def`）：本服务的数据库访问是同步 SQLAlchemy
    （`repository/session.py` 已定档，MUST NOT 引入 async driver），
    而 `TaskRunner` 是 async —— 故**边界在调用点**：
    `TaskRunner` MUST 用 `await run_in_threadpool(...)`（`starlette.concurrency`）
    调用这里的每个方法，MUST NOT 在事件循环里直接调它们。
    这与 `api/ocr.py::_submit_in_session` 的既有做法**完全同构**（那里也是整块同步工作交给线程池）。

    **每个写方法都收 `account_id` 与 `created_at`**：`ShardKey` 需要它们才能算出物理表名
    （`er.md` §5.2 的分片键是 `(account_id, created_at)`），
    而这两个值已经在 `ClaimedTask` 里了 —— 故 `TaskRunner` 直接把 `claimed` 拆开传进去，
    MUST NOT 让执行器自己去算表名（那会把分片知识复制到 `core`，而 `core` 不得依赖 `repository`）。
    """
    def list_claimable(self, *, limit: int, now: datetime) -> Sequence[ClaimedTask]: ...
    def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None: ...
    def mark_succeeded(
        self, task_id: str, *, account_id: str, created_at: datetime,
        progress: int, finished_at: datetime,
    ) -> None: ...
    def mark_failed(
        self, task_id: str, *, account_id: str, created_at: datetime,
        error_code: str, finished_at: datetime,
    ) -> None: ...
    def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None: ...

class TaskHandler(Protocol):
    """任务处理器（由 `service/task/registry.py` 的 `handler_ref` 解析后注入）。"""
    def timeout_s(self) -> float: ...
    async def handle(self, task: ClaimedTask) -> None:
        """成功即正常返回；失败 MUST 抛 `aicore.core.errors.AiCoreError`（带业务码）。"""

class TaskRunner:
    def __init__(
        self, *, store: TaskStore, locks: LockStore,
        handlers: Mapping[str, TaskHandler],
        policies: Mapping[str, TaskPolicy],           # 组合根注入（见上方 Protocol 的修正）
        config: RunnerConfig, clock: StepClock | None = None,
        executor: Executor | None = None,          # 4.8 的线程池注入点
    ) -> None: ...
    async def claim_once(self) -> ClaimedTask | None: ...
    async def execute(self, claimed: ClaimedTask) -> None: ...
    async def run_once(self) -> bool:
        """跑一轮：没有可领取任务返回 False。"""
    async def run_forever(self, *, stop: asyncio.Event) -> None:
        """按 `poll_interval_s` 轮询直到 `stop` 被 set；并发度由信号量封顶（背压）。"""
```

**Hard constraints（每条都要有用例）**：

1. **领取顺序**：`list_claimable`（MySQL）→ 逐个 `locks.acquire`（Redis）→ **第一个成功即返回**。
   `acquire` 返回 `None`（别人持有 / 退避中）就**试下一个**，MUST NOT 重试同一个。
2. **领取成功后 MUST 立刻 `store.begin_attempt(...)`**：这一笔写的是
   `status=PROCESSING` + `progress=1`（进度回写，`er.md` §6.1 L293），
   即"事实源里标记为在跑"。它 MUST 在**启动心跳之前**完成。
3. **心跳续期**：`execute` 内起一个**独立 task**，按 `lease_ms // 3` 间隔 `renew`。
   - **续期返回 `False` → MUST 主动放弃**：取消处理、**不写任何终态**、
     让租约自然过期由别人回收（`design.md:208`）。
     用例 MUST 断言：`mark_succeeded` **一次都没被调用**。
   - **`renew` 抛异常（Redis 抖动）→ 同样按放弃处理**，MUST NOT 静默继续。
     （这是 `tests/structural/test_source_guards.py` 规则 6 的同向取向：不许"异常后继续执行"。）
4. **任务级超时**：`asyncio.wait_for(handler.handle(claimed), timeout=handler.timeout_s())`
   —— 用 **handler 自己声明的** `timeout_s`（`design.md:185`）。
   超时 → 按失败处理，业务码取 `5002`（`core/errors.py` 的 `DEPENDENCY_TIMEOUT_CODE`）。
5. **失败分流（两条，MUST 分开）**：
   - `policy.retryable is True` 且 `attempt <= max_retries` → `store.requeue(...)` +
     `locks.defer(task_id, delay_s=退避)`；
   - 否则 → `store.mark_failed(error_code=<异常的 code>, finished_at=now)`。
   `error_code` MUST 取**异常自带的 `code`**（`AiCoreError.code`），MUST NOT 由本层猜。
   - **`TaskRunner` MUST NOT 读 `policy.timeout_s`**（任务级超时取 `handler.timeout_s()`，
     见硬约束 4）。理由：注册表行内的 `timeout_s` 是**配置默认值快照、不是权威值**
     （4.6 的 docstring 有详述），读了它会静默拿到一个不随配置变的超时——
     「取了一个看起来对的错值」比报错更难查。**请加一条源码级断言钉住它**
     （AST 剥注释后扫 `timeout_s`）。
6. **成功后** `store.mark_succeeded(progress=100, finished_at=now)`，然后 `locks.release`。
   顺序 MUST 是**先写库后释放租约**：反过来的话，租约释放与终态落库之间有个窗口，
   别的实例可以领到同一个任务并**重复调用付费通道**（会产生真实费用，`design.md:208`）。
7. **并发度与背压**：`run_forever` 用 `asyncio.Semaphore(config.concurrency_limit)` 封顶；
   **信号量满时 MUST NOT 领取新任务**（先拿信号量再领取，而不是领了再排队）——
   否则租约在排队期间空转，表现为"领了但没跑"，最终被回收重做。
8. **`run_forever` MUST 可被 `stop` 事件立刻打断**，MUST NOT 用 `asyncio.sleep` 硬等：
   等待用 `asyncio.wait_for(stop.wait(), timeout=poll_interval_s)`。
   用例里 `clock`/`sleep` **可注入**（同 `provider/guard.py` 的取向），
   **MUST NOT 在用例里真等**。

### 2.5b Task 4.8 的交付接口（同在 `core/task_runner.py`）

```python
CPU_THREAD_PREFIX: Final = "aicore-cpu"

def cpu_pool(max_workers: int) -> ThreadPoolExecutor:
    """建**专用** CPU 池（线程名带 `CPU_THREAD_PREFIX`，便于用例与排障辨认）。"""

async def run_cpu_bound[T](
    fn: Callable[[], T],
    *,
    executor: Executor,
) -> T:
    """把 **CPU 密集** 的同步函数放到 `executor` 执行，返回其结果。

    **零参可调用**（`functools.partial` 由调用方负责）：这样签名只有一个类型参数 `T`，
    不必引入 `ParamSpec`；本服务的 CPU 密集点（图像解码、脱敏、哈希）本来就要先绑定参数。

    **`executor` 必须显式传入，MUST NOT 有默认值**：默认值会让"用了哪个池"变成隐式事实，
    而设计文档要求两类工作**分开**——
    「图像解码、脱敏处理、哈希与存证计算走 `run_in_executor`」（`design.md:200-206`）
    与「MySQL 访问走线程池」（同表 L203）是**CPU 密集 vs 阻塞 I/O** 两类，
    混在一个池里时一次图像解码会占住 MySQL 查询要用的线程。
    强制显式传入，使"谁在用哪个池"在每一处调用点都看得见。
    """
```

- `TaskRunner.__init__` 的 `executor` 形参：**默认 `None` 时 MUST 自建 `cpu_pool(...)`**
  （`max_workers` 取 `config.concurrency_limit`），MUST NOT 静默落到事件循环默认执行器。
  自建的池 MUST 在 `TaskRunner.stop()` / `aclose()` 里 `shutdown(wait=False)`，
  否则进程退出时线程泄漏（用例断言 `shutdown` 被调用）。
- `core/task_runner.py` 里 `import concurrent.futures` / `asyncio` 是 stdlib，**允许**。
- **重活的判定范围（MUST 写进 docstring）**：本层只提供**机制**（把函数放出去执行），
  不判定"什么算 CPU 密集"——那由调用方（未来的 `service/desensitize.py` 等）决定。
  单元用例里的"长耗时"用 `time.sleep` 模拟，**但 MUST NOT 出现在默认段的其他用例里**
  （`tests/conftest.py` 约定：测试内不得任意 sleep；sleep 只允许出现在**专门验证线程边界**的那条用例，
  且时长 ≤ 0.15s）。

### 2.6 `repository/task_lease_store.py`（**新增文件**，不是改既有仓储）

**为什么新增而不是改 `task_repo.py`**：`TaskRepo` 是 Task 3.7 已验收的产物，
本任务不该动它；而"扫描可领取任务"这条 SQL 的执行侧关切（终态过滤、OrderBy、
limit 下推）与 3.7 的读写关切不同，分开更清楚。

```python
class SqlTaskLeaseStore:
    """`TaskStore` 的 SQL 实现：**每张月表一次查询**（分片键下推，禁跨分片）。"""
    def __init__(self, factory: EngineFactory) -> None: ...
```

- `list_claimable(*, limit, now)`：按 `now` 现算**当月**物理表，
  `SELECT ... WHERE status = 'PROCESSING' ORDER BY created_at ASC LIMIT :limit`
  —— 排序用 `idx_status_created(status, created_at)`（`er.md` §7.1）。
  **MUST 只查当前月**：跨月扫描违反 `er.md` §5.3「查询 MUST 携带分片键下推」。
- 四个写方法用 `TaskRepo.update_status`（**既有能力，MUST 复用**），
  故 MUST 持有一个 `TaskRepo` 实例。
- **MUST NOT** 自开引擎：收 `EngineFactory` 并用 `primary_read_session()` 读、
  `write_session()` 写（`er.md:252` 写后立即读走主库）。
- `begin_attempt` 写 `progress=1`；`mark_succeeded` 写 `progress=100`。
  `requeue` 写回 `status=PROCESSING` + `progress=0`（**不清 `error_code`**：
  `er.md` §6.1 L294 的 `error_code` 是"FAILED 业务码"，重排期间保留上一次的码有利于排障；
  若你认为该清，MUST 在报告里说明并给依据）。

### 2.7 `main.py` 的装配（**只允许在 lifespan 内加**）

- 启动：按 `settings` 构造 `RedisLockStore` + `SqlTaskLeaseStore` + `TaskRunner`，
  挂到 `app.state.task_runner`；**启动执行器协程**并把 `asyncio.Event` 存起来。
- 关闭：**先 set stop、await 执行器退出**，再 `locks.close()`，最后 `engine_factory.dispose()`
  —— 顺序是硬要求：先关 Redis 会让在跑的任务续期失败（变成"无故放弃"）。
- **`env` 为 `test` 时 MUST NOT 启动执行器**（否则每个用 `TestClient` 的用例都会去连 Redis）。
  做法：`if settings.env != "test": ...`，并把该判据写进 docstring。

### 2.8 **处理器注册表此刻是空的**——这是事实，MUST NOT 用假实现填满它

控制者已核实：`src/aicore/service/ocr_service.py` **仍是 44 字节的空壳**
（只有一行 docstring）。而 `service/task/registry.py` 的 `OCR` 行 `handler_ref = "service.ocr_service"`
只是一个**字符串位置**——注册表**刻意不导入处理器**（`design.md:194` 要的改动量是
「新增一个处理器文件 + 一行注册」）。

**故本任务的口径（MUST 照此）**：

1. **`main.py` 装配时传空 mapping**：`handlers={}`，并在启动日志里记一条
   「执行器已启动，已注册处理器 0 个」——**如实反映 M1 现状**，
   MUST NOT 在 `main.py` 里 `import` 任何 `service.*` 或塞一个 `_FakeHandler` 进生产代码。
2. **执行器遇到"没有对应 handler"的任务 MUST NOT 静默跳过**：
   记 ERROR 日志 + 按失败分流处理（`error_code` 用 `5000`，因为这是**装配缺失**，
   不是通道失败也不是超时）。依据 `design.md:194`「未注册的类型必须显式失败（而非静默忽略），
   避免告警丢失」的同向取向。用例 MUST 覆盖这一条。
3. **handler 的解析约定写在 `task_runner.py` 的 docstring 里**（本任务只写约定、不实现解析）：
   注册表给 `handler_ref` 字符串 → 由 **`main.py`（组合根）** 用
   `importlib.import_module` + `getattr` 解析并构造 → 以 `Mapping[str, TaskHandler]` 注入。
   **MUST NOT 在 `core/task_runner.py` 里 import 或 `getattr` 任何 `service.*`**（契约 4）。
   Task 5.x 交付 `ocr_service.py` 后，只需在组合根把那一条 `handler_ref` 解析出来即可，
   **执行器本身零改动**——这正是 `design.md:194` 要的可演进性。
4. 用例里的 handler **只能出现在 `tests/` 下**（假 handler 是测试替身，不是生产代码）；
   集成段若要"真处理器"，就**在测试里定义**一个把 `ai_task` 置为 `SUCCEEDED` 的最小实现。

---

## 3. 用例清单

### 3.1 `tests/unit/test_lease.py`（`InMemoryLockStore`，注入时钟，零 IO）
1. `acquire` 首次成功、token 非空、`attempt == 1`；
2. **同 task 再 `acquire` → `None`**（未过期、非退避）；
3. 推进注入时钟过 `lease_ms` → **另一个 store 实例能领取**（租约超时回收）；
4. `renew` 用**旧 token** → `False`；用**当前 token** → `True` 且延长存活；
5. `release` 用**别人的 token** → `False` 且键仍在；用**自己的 token** → `True` 且键消失；
6. `defer` 后 `is_deferred` 为真、`acquire` 返回 `None`；推进时钟过 `delay_s` 后可领取；
7. **`attempt` 递增**：连续 expire→acquire 三次，`attempt` 依次 1/2/3；
8. `is_deferred` **无副作用**（连调两次结果一致、不改变可领取性）。

### 3.2 `tests/unit/test_task_runner.py`（假 store + 假 handler + 注入时钟）
9. **原子领取：并发领取不重复**——N 个协程同时 `claim_once()`，**恰好一个**拿到手，
   其余返回 `None`（用 `asyncio.gather`）；
10. 领取成功后**先** `begin_attempt` 再起心跳（用调用顺序记录断言）；
11. **续期失败 → 放弃**：把 lock store 换成"`renew` 恒 `False`"的替身 →
    `mark_succeeded` **零调用**、`mark_failed` **零调用**、`requeue` **零调用**；
12. **`renew` 抛异常 → 同样放弃**（同上三条零调用）；
13. **任务级超时**：handler 挂起超过 `timeout_s` → 走失败分流，业务码 `5002`；
14. **退避重试**：`attempt=1` 失败 → `requeue` 一次 + `defer` 的 `delay_s == 1.0`；
    第 2 次 → `2.0`；第 3 次 → `4.0`（**逐项断言，不是"大致递增"**）；
15. **超限转人工**：`max_retries=3`，第 4 次失败 → `mark_failed` 且
    `error_code` == 异常的 `code`、`finished_at` 非空、**`requeue` 零调用**；
16. **`retryable=False` 不进退避**：策略为 `retryable=False` 时首次失败即 `mark_failed`；
17. **成功路径**：`mark_succeeded(progress=100)` **先于** `locks.release`（顺序断言）；
18. **背压**：`concurrency_limit=1` 时，第二个任务在第一个跑完前**不被领取**
    （断言 `acquire` 的调用次数）；
19. **`stop` 可打断**：`run_forever` 在 `stop.set()` 后立即返回（注入的 sleep 记录等待时长）；
20. **`run_once` 无任务时返回 `False`**，且**不调用 `acquire`**（减少 Redis 往返）；
21. **没有对应 handler 的任务 MUST NOT 被静默跳过**（§2.8 第 2 条）：
    `handlers={}` 时领到任务 → 记 ERROR + 按失败分流，`error_code == 5000`；
    用例 MUST 同时断言**没有**抛异常逃逸（执行器不因一个无法处理的任务而崩掉整个循环）
    与**确实写了终态**（不是只打日志）。
22. **`TaskRunner` 不读 `policy.timeout_s`**（源码级：AST 剥注释/三引号后扫 `timeout_s`），
    并附**判别力自证**：在内存里给源码插入一次 `policy.timeout_s` 读取，断言该判据变红。
23. **契约 4 的本地回归**（与 Task 4.6 的判据 A 同构）：
    断言 `core/task_runner.py` 的可执行骨架里**不出现 `aicore.service`**，
    并附判别力自证——在内存里插一行 `from aicore.service.task.registry import TaskPolicy`，
    断言判据变红。**没有这条自证，就没人知道这条纪律还在不在。**
    （契约 4 本身由 `lint-imports` 守，但那是全仓门禁、不是本文件的本地判据；
    本地判据的价值是**改坏时立刻在最近的用例上红**，而不是等到跑门禁。）

### 3.3 `tests/unit/test_cpu_pool.py`（Task 4.8）
22. **重活不在事件循环执行**：`run_cpu_bound(fn)` 的返回体必须报告
    `threading.get_ident()` **≠** 事件循环线程的 ident，且该线程名属于注入的池；
23. **事件循环不被阻塞**：注入一个"睡 0.1s（用注入时钟模拟为长耗时）"的 CPU 函数，
    同时用 `asyncio` 起一个定时协程，断言**定时协程先完成**——
    这是「并发提交时受理接口耗时不劣化」在离线段的**可判定替身**（真压测归 13.4）；
24. **`executor=None` 时用事件循环默认执行器**，且仍是**别的线程**；
25. **判别力自证**：若把 `run_cpu_bound` 改成直接 `fn()`（不经过执行器），
    第 22/23 条**必须变红**（用合成实现证明判据有判别力，写入用例内、不落盘）。

### 3.4 `tests/integration/test_lease_redis.py`（**真实 Redis**，`@pytest.mark.integration`）
26. `RedisLockStore.acquire` / `renew` / `release` / `defer` / `is_deferred` 基本链路；
27. **原子性真验**：用 **两个不同的 `Redis` 连接**（各自的 client）并发 `acquire`
    同一 task_id → **恰好一个成功**；
28. 真 `PX` 生效：`acquire` 后 `PTTL` ∈ `(0, lease_ms]`；推进真实时间过 `lease_ms`
    后另一个 client 能领取（**这里允许真等**，因为它是集成段；但等待时间 MUST ≤ 2s，
    用 `lease_ms=1000` 一类的短租约，并在用例里注明"集成段允许真等，默认段不允许"）。

    > **⚠️ 这一点会撞上第 3 组验收脚本的第 4 项「测试内无 sleep」**（它 AST 扫全 `tests/`）。
    > 该判据现在支持**行级豁免**：在 `sleep` 调用那一行写
    > `# ai-allow-sleep: <理由>`（**理由必填**）即可，与 `test_source_guards.py` 规则 6 的
    > `# ai-allow-swallow: <理由>` 同构。**MUST NOT** 因为这条就去改判据或删掉用例。
    > 报告里请列出你加了几处豁免、各是什么理由。

### 3.5 `tests/integration/test_runner_redis.py`（**真实 Redis + 真实 MySQL**）
29. 「提交 → 领取 → 执行（假 handler）→ 成功」全链路，断言库里终态为 `SUCCEEDED`/`progress=100`；
30. 失败 + 退避 + 重试 + 超限转人工的全链路（用**立即失败**的假 handler 与 `max_retries=1`）；
31. Redis 不可达时（用错误的端口）**`claim_once` MUST 抛错而不是吞掉**，
    且**任务状态不被改动**（fail fast，不假装成功）。

### 3.6 夹具（`tests/conftest.py`，**只允许加**）
- `DSH_IT_REDIS_HOST/PORT/DB` 默认值（与既有 `DSH_IT_MYSQL_*` 同形，`setdefault` 注入）；
- `redis_store` 夹具：连真实 Redis，**每个用例换一个 key 前缀**（`aicore:test:<uuid>:`），
  用例结束清理自己的键（**MUST NOT `FLUSHDB`**——那会清掉同机其它测试的状态）；
- 连不上时**显式 skip 并说明**（同既有 MySQL 集成夹具的口径，**MUST NOT 静默通过**）。

---

## 4. 验收（自证，**原始输出全部贴报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_lease.py tests/unit/test_task_runner.py tests/unit/test_cpu_pool.py -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "integration"      # 含真实 Redis
.\.venv\Scripts\ruff.exe check --no-cache src tests
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

- 全量判据 MUST 写「**EXIT=0 且 failed == 0**」，**MUST NOT 写固定计数**。
- **`core/lease.py` MUST NOT import `aicore.provider` / `aicore.service` / `aicore.repository` /
  `aicore.port`**（契约 4）。`import redis.asyncio` 是三方包，**允许**。
- **MUST NOT `git commit` / `git add`**。
- **MUST NOT 用「改 `src/` 文件 + finally 还原」做变异测试**（本组两次踩过，注入残留过交付文件）。
  要变异就在 `tests/` 下建临时用例文件或**在内存里**变异（Task 4.6 的判据 A 有现成范式）。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.7-report.md`，
  含逐项验收结论、原始输出、**偏离项 + 理由**、**没做到的事**。
- 若发现控制者给的接口有硬伤 → **停下并在报告里写明**，MUST NOT 自行改契约或既有文件。

## 5. 探针纪律

新建的临时脚本 > 2 个即停下报告。**临时的 Redis 键 MUST 用完即删**，并在报告里列出你用过的前缀。
