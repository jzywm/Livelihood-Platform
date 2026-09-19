"""任务执行器内核：领取 / 租约心跳 / 超时 / 失败分流 / 背压 + CPU 密集线程池边界。

**权威依据**：`design.md` L196-212（并发模型表、领取原子性、重试与退避、并发度与背压）、
`design.md` L185-194（任务类型策略注册表与「未注册类型必须显式失败」）、
`design.md` D2 L42-50（`ai_task` 是唯一事实源，领取实现可替换）、
`docs/design/高并发架构演进设计.md` L260（指数退避 1s→2s→4s…）；
`services/aicore/docs/er.md` §6.1 L284-298（各列语义：`progress` / `error_code` / `finished_at`）
与 §7.1 L425-435（状态机、索引）。验收原文：`openspec/changes/implement-aicore-service/tasks.md`
**L43-44**（4.7 内核 + 4.8 线程池）。

## 一、本模块是「机制」，不是「策略」——三条边界

1. **不判定「什么算 CPU 密集」**：`run_cpu_bound` 只提供**机制**（把一个零参可调用交给
   显式传入的 `executor`），不判定调用方交给它的是不是重活。判定权在调用方
   （未来的 `service/desensitize.py` 等）：图像解码 / 脱敏 / 哈希与存证计算是 CPU 密集，
   MySQL 访问是**阻塞 I/O**，两类在 `design.md:200-206` 的表里**分属两行**，故 MUST 分开两个池——
   混在一个池里时一次图像解码会占住 MySQL 查询要用的线程。`run_cpu_bound` 的 `executor`
   **必须显式传入、MUST NOT 有默认值**，正是为了让「谁在用哪个池」在每个调用点都看得见。
2. **不认识任何任务类型**：类型 → 处理器的解析在 `service/task/registry.py`（注册表是唯一来源），
   本模块只做 `handlers[task_type]` 这一下**表查找**，MUST NOT 出现逐类型分支、
   MUST NOT 出现任何任务类型字面量（`tests/unit/test_task_registry.py` 有 AST 判据钉住）。
3. **不碰具体处理器模块**：`handlers` 由组合根（`main.py`）注入，见下面 §三。

## 二、时序（`execute` 的步骤顺序本身就是契约）

1. `claim_once()`：`store.list_claimable`（MySQL）→ 逐个 `locks.acquire`（Redis）→
   **第一个成功即返回**；`acquire` 返回 `None`（别人持有 / 退避中）就**试下一个**，
   MUST NOT 重试同一个（重试同一个会在别人正在处理时白烧一轮）。
2. 领取成功后 **立刻** `store.begin_attempt(...)`（写 `status=PROCESSING` + `progress=1`，
   `er.md` §6.1 L293）：这是「事实源里标记为在跑」。它 MUST 在**启动心跳之前**完成——
   顺序反过来时，心跳先跑起来而事实源还显示旧状态，别人（或对账任务）会读到
   「有租约但没人处理」的假象。
3. 起**独立 task** 的处理器，同时起**独立 task** 的心跳（按 `lease_ms // 3` 间隔 `renew`，
   `design.md:208`「续期由心跳完成」）。间隔取 1/3 而不是 1/2：一次网络抖动加一次事件循环
   排队就足以吃掉半个租期，留两个完整窗口比留一个安全。
   处理器 MUST 是**可取消的 task**（不是就地 `await`）：租约丢失时要能把它**取消掉**
   （见下面的 §二之二）。
4. 用 `asyncio.wait({handler, heartbeat}, FIRST_COMPLETED)` 等**两者中先结束的那个**，
   由三条分支各自处置：处理器成功 / 处理器失败（含 `wait_for` 超时）/ **心跳先结束（租约丢失）**。
   第三条分支 MUST 取消处理器——这正是 B1 修复的落点。
5. 成功 → `store.mark_succeeded(progress=100, finished_at=now)`，**然后** `locks.release`。
   顺序 MUST 是「先写库后释放租约」：反过来的话，租约释放与终态落库之间有一个窗口，
   别的实例可以领到同一个任务并**重复调用付费通道**（`design.md:208`）。
6. 失败 → **两条分流**（`design.md:210`「失败按指数退避重试，超过最大次数置 `FAILED`
   并转人工复核队列（对应用例：不静默丢单）」）：
   - `policy.retryable` 为真 **且** `attempt <= max_retries` → `store.requeue(...)` +
     `locks.defer(delay_s = `BACKOFF_BASE_S` * 2 ** (attempt - 1))` + `locks.release(claim)`；
   - 否则 → `store.mark_failed(error_code=<异常自带的 code>, finished_at=now)`。
   `error_code` MUST 取异常自带的 `AiCoreError.code`，MUST NOT 由本层猜。

## 二之二、租约丢失时「放弃执行」的**准确含义**（MUST 照此理解，MUST NOT 夸大）

心跳续期失败（`renew` 返回 `False` 或抛异常）时，本层 **取消处理器的协程**，
并把该分支记成**放弃**：不再等它、不写任何终态、不再叠加后续工作。
这正是 `design.md:208` 逐字要求的那件事：

> 租约到期未被续期即可被其他实例回收……**续期失败必须主动放弃任务而非继续执行**，
> 避免出现「两个实例同时处理同一任务」的重复外部调用（会产生真实费用与重复标记）。

**能承诺什么、MUST NOT 承诺什么（诚实边界，MUST NOT 读成"已回滚副作用"）**：

| 事项 | 取消之后的状态 |
|---|---|
| 处理器协程 | **真的被取消**：`CancelledError` 在下一个 `await` 点抛出，协程不再往下走 |
| 协程里 `await` 出去的下游**异步**调用 | 随取消一起中断（如 `httpx` 出向请求会被取消） |
| **已交给线程的工作**（`run_cpu_bound`） | **收不回来**：线程不能被安全强杀，池里的任务会跑完 |
| 已经发出的**同步**调用 | **停不下来**：取消到达前已发出的请求照样到达对方、照样计费 |
| 终态写回 / 租约释放 | **不再做**（终态由回收后的新 owner 写；租约留待自然过期） |

故本层**只承诺**「不再等它、不再写终态、不再叠加后续工作」；
**MUST NOT** 在任何 docstring 或日志里写成「已回滚外部副作用」——那是做不到的，
而写出来只会让排障的人以为"取消过就一定没有重复调用"。


**「第几次尝试」从哪来**：`TaskClaim.attempt`（`core/lease.py` 的领取脚本用 `INCR` 计数得到）。
本类**必须**把 `claim_once` 拿到的那个 `TaskClaim` 带到 `execute` 里，MUST NOT 让 `execute`
自己再领一次（那会多一次 Redis 往返，而且拿到的是**新的** `attempt`，把「第 4 次该转人工」
错算成「第 1 次该退避」，表现为**无限重试**）。故 `claim_once` 把 claim 挂进 `self._claims`，
`execute` 按 `task_id` 取回；`execute` 也接受显式 `claim=` 形参（测试与将来的直调路径用），
两者都没有时才退化成 `attempt=1` 的合成 claim（**只可能出现在「没经过 `claim_once` 就执行」
这条路径上**）。

## 三、处理器的解析约定（本任务只写约定，不实现解析）

注册表（`service/task/registry.py`）给的是 `handler_ref` **字符串位置**，
**由组合根 `main.py` 解析**：`importlib.import_module(module)` + `getattr(module, attr)`
→ 构造实例 → 以 `Mapping[str, TaskHandler]` 注入本类。
本模块 MUST NOT import 或 `getattr` 任何具体处理器模块（契约 4：`core` 不得依赖业务层）；
Task 5.x 交付真实处理器后，组合根多解析一条即可，**本模块零改动**——
这正是 `design.md:194` 要的「新增一个处理器文件 + 一行注册」的可演进性。

### 处理器缺失不是「跳过」，是**装配缺失**（MUST 显式失败）

M1 的现实是 `handlers` 为空 mapping（`service/ocr_service.py` 仍是空壳，
见 `task-4.7-brief.md` §2.8）。执行器遇到「没有对应 handler」的任务时：

- 记 **ERROR** 日志（`design.md:194` 逐字「未注册的类型必须显式失败（而非静默忽略），
  避免告警丢失」的同向取向）；
- **按失败分流处理**，`error_code` 取 `5000`（`INTERNAL_ERROR_CODE`，内部错误）：
  这是**装配缺失**，既不是通道失败（`4003`）也不是依赖超时（`5002`），
  用那两码会把运维引向「去查通道」，而真正要修的是组合根没解析出处理器；
- **MUST NOT 静默跳过**（跳过会让任务永远停在 `PROCESSING`，且没有任何告警）；
- **MUST NOT 让它崩掉整个循环**（一个无法处理的任务不该中断本实例上的其它任务）。

## 四、`TaskStore` 是**同步**的，边界在调用点（`run_in_threadpool`）

本服务的数据库访问是**同步** SQLAlchemy（`repository/session.py` 已定档：
同步会话 + 线程池，MUST NOT 引入 async driver），而本类是 async。故：
**`TaskStore` 的每个方法都是 `def`，本类一律用 `await run_in_threadpool(...)` 调用它们**
（`starlette.concurrency`）。直接在事件循环里调同步 SQL 会把整个事件循环卡在一次
数据库往返上——「并发数不高但 P95 爆表」的典型成因（`design.md:206` 同款论证）。
形状与 `api/ocr.py::_submit_in_session` **完全同构**：整块同步工作交给线程池，
会话在哪个线程创建就在哪个线程用完。

`LockStore` 相反：它是 async 的（Redis 客户端本来就是），**MUST NOT** 再套线程池
（那会白占一个工作线程做纯等待）。

**本层用两个不同的池**：`run_in_threadpool` 走 anyio 的 worker 池（starlette 的既有设施），
`self._executor` 是 CPU 池——这正是 `design.md:200-206` 两行分工的落点；
CPU 池只服务 `run_cpu_bound`。
## 五、`run_forever` 的背压与退出

- **先拿信号量再领取**（不是领了再排队）：否则租约在排队期间空转，
  表现为「领了但没跑」，最终被回收重做——租约被浪费，而任务一次也没被执行。
- **等待用 `asyncio.wait_for(stop.wait(), timeout=poll_interval_s)`**，
  MUST NOT 用 `asyncio.sleep` 硬等：硬等时 `stop` 最多要等一个完整轮询间隔才生效，
  关停会变慢；`wait_for(stop.wait())` 在 `stop.set()` 的那一刻就返回。
- **`stop` 的语义（本实现的取舍，如实登记）**：`stop` 止住**新的领取**；
  `run_forever` 在本轮**在飞**的任务全部跑完（每个都被处理器声明的 `timeout_s` 界住）
  之后才返回。取舍理由：关停时把在飞任务直接取消，等于制造一批「有租约、不确定有没有
  写完外部副作用」的任务（它们会被回收并**重放**，而重放可能重复调用付费通道）；
  让它们跑完再退出，代价是关停最多等一个 `timeout_s`，换来的是「不静默丢单」。
  这与 `main.py` 的关停顺序（先 set stop、await 执行器退出、再关 Redis）配套。

## 六、依赖面（契约 4）与策略从哪来（**本实现的偏离项，见报告**）

只 import `aicore.core.*`、`starlette.concurrency` 与 stdlib。MUST NOT import
`aicore.service` / `aicore.repository` / `aicore.provider` / `aicore.api` / `aicore.port`
（`.importlinter` 契约 4 `core-independent` 把 `aicore.service` 整包列为 forbidden，
且**未**开 `allow_indirect_imports`）。

**故本层不含 `get_policy` 的调用，也不 import `service/task/registry.py`**：
策略映射由**组合根**（`main.py`，唯一允许跨层装配的位置）从注册表现读后
以 `policies: Mapping[str, TaskPolicy]` 注入——与 `handlers` 的注入方式完全同构。
`TaskPolicy` 在本模块是**结构化 Protocol**（只声明本层真正读的那一个字段 `retryable`），
故组合根传 `service.task.registry.TaskPolicy` 实例时**无需适配器、也无需 import**：
结构子类型让两边的类型互认。改动量是「组合根多传一个 mapping」，
与 `design.md:194` 要的「新增类型 = 加一行注册」不冲突。

> **为什么不做成 `Callable[[str], TaskPolicy | None]`**：那会让「有哪些策略」在运行期
> 才逐次问出来，而策略表是**启动期就确定的声明**。传一份 mapping 让
> 「执行器认识哪些策略」在装配那一刻就是确定的（也便于 `main.py` 打启动日志）。

分片知识（表名怎么算）同样不在本层：三个写方法收 `account_id` + `created_at`，
由 `repository` 侧用 `ShardKey` 现算物理表名。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Final, Protocol

from starlette.concurrency import run_in_threadpool

from aicore.core.errors import (
    INTERNAL_ERROR_CODE,
    AiCoreError,
    DependencyTimeoutError,
)
from aicore.core.lease import LockStore, TaskClaim

__all__ = [
    "BACKOFF_BASE_S",
    "BEGUN_PROGRESS",
    "CLAIM_FAILURE_BACKOFF_BASE_S",
    "CLAIM_FAILURE_BACKOFF_MAX_S",
    "CPU_THREAD_PREFIX",
    "FALLBACK_HANDLER_TIMEOUT_S",
    "HEARTBEAT_DIVISOR",
    "POLL_INTERVAL_S",
    "SUCCEEDED_PROGRESS",
    "ClaimedTask",
    "HandlerNotResolvedError",
    "RunnerConfig",
    "TaskHandler",
    "TaskRunner",
    "TaskStore",
    "cpu_pool",
    "run_cpu_bound",
]

_logger = logging.getLogger(__name__)

#: 专用 CPU 池的线程名前缀。带前缀的线程名让「重活到底在哪个池里跑」在排障时一眼可辨
#: （`threading.current_thread().name` 形如 `aicore-cpu_0`），也让用例能断言「属于注入的池」。
CPU_THREAD_PREFIX: Final = "aicore-cpu"

#: 心跳间隔 = `lease_ms / HEARTBEAT_DIVISOR`（`design.md:208`「续期由心跳完成」）。
#: 取 1/3 而不是 1/2：一次网络抖动加一次事件循环排队就足以吃掉半个租期，
#: 留两个完整窗口比留一个安全（多一次续期的往返成本可忽略）。
HEARTBEAT_DIVISOR: Final = 3

#: 处理器没声明 `timeout_s` 时的兜底超时（秒）。
#:
#: `execute` 走的是 `TaskHandler` Protocol（声明式），故这条兜底在**组合根装配正确时不可达**；
#: 它防的是「处理器对象缺该方法」这类装配错误。两条更坏的处置都被排除：
#: 用**无限**超时会让一个挂死的处理器永久占住并发额度（整个实例停止领新任务，
#: 而表面上没有任何错误）；当成 **0** 会把正常任务全部判超时。
#: 取一个保守小值（1s）：它的表现会立刻落在 `5002` 计数上，逼着把声明补上，
#: 而不是悄悄跑下去。
FALLBACK_HANDLER_TIMEOUT_S: Final = 1.0

#: 指数退避基数（秒）。**设计文档与 `er.md` 都没有给本模块的退避数值**，
#: 故按工单 §2.4 写成模块 `Final` 常量并注明「未定档」；MUST NOT 凭空加 `Settings` 字段
#: （第 4 组 P 阶段加 4 个护栏字段是用户批准的，本任务没有那个授权）。
#: 取 `1.0` 的依据是 `docs/design/高并发架构演进设计.md:260` 的通道级口径逐字
#: 「指数退避（1s→2s→4s…）」——**借用**同一基数，使任务级与通道级的退避序列一致，
#: 而不是各造一个数字。
BACKOFF_BASE_S: Final = 1.0

#: 执行器轮询间隔（秒）。同样**未定档**（设计文档只说「轮询」，未给间隔），故为模块常量。
#: 取 `1.0` 的理由：M1 的任务量约 1 万次/日（`design.md` D2），折算远低于 1 QPS，
#: 1 秒的空轮询成本可忽略；更短的间隔只会换来空查询（`idx_status_created` 上无命中），
#: 更长的间隔会把「提交 → 开始处理」的延迟直接加上去。
POLL_INTERVAL_S: Final = 1.0

#: 领取失败后的退避基数（秒）与**上限**（秒）——A2 修复引入的两个模块常量。
#:
#: 设计文档没有给数值（与 `BACKOFF_BASE_S` / `POLL_INTERVAL_S` 同档，故同样标"未定档"）。
#: 取 `0.5` 起步、`30` 封顶的理由：领取失败几乎都是**基础设施瞬时故障**
#: （月表还没建、Redis 抖动、连接池耗尽），它们通常在秒级恢复；而**上限必须有**——
#: 没有上限的指数退避会在几百次失败后变成"事实上停止工作"，
#: 没有上限的**不**退避则会变成"每轮狂打日志"（比死掉更难查，控制者原话）。
#: 上限 30s 让"持续失败"表现为一条每分钟两条的 ERROR 心跳日志，既不刷屏也不静默。
CLAIM_FAILURE_BACKOFF_BASE_S: Final = 0.5
CLAIM_FAILURE_BACKOFF_MAX_S: Final = 30.0

#: 领取时写回的进度值（`er.md` §6.1 L293：`progress` 是进度百分比，刚领到即已开始）。
BEGUN_PROGRESS: Final = 1

#: 成功终态的进度值（工单 §2.5 硬约束 6 逐字 `progress=100`）。
SUCCEEDED_PROGRESS: Final = 100

#: `run_cpu_bound` 返回类型与 `_invoke` 的共用类型变量说明：`_invoke` 用 PEP 695 的
#: 类型参数语法（`def _invoke[U](...)`，ruff UP047 要求），故这里不需要模块级 `TypeVar`。


class HandlerNotResolvedError(AiCoreError):
    """任务类型**没有可用处理器**（业务码 `5000`，内部错误）。

    两种成因共用本类（排障要看得出该修哪一处，故 `reason` 由调用方渲染）：

    - 类型在注册表里、但组合根没把它解析成实例（M1 的现状：`handlers={}`）
      → 修的是 `main.py` 的装配；
    - 类型**不在注册表**里（库里有一行执行器不认识的类型）
      → 修的是注册表或发布流程。

    ## 为什么是 `5000` 而不是 `1003` / `4003` / `5002`

    `get_policy` 对未注册类型抛 `ParamError(1003)`（枚举或范围非法）——那是**请求参数**语义，
    对的是「调用方提交了一个不存在的类型」。而执行器读到的 `task_type` 来自**库里已落行的
    数据**：此刻不认识它说明「注册表与库不一致」，是**服务端装配/发布问题**，
    不是某次请求的参数问题；把服务端缺陷报成 `1003` 会把排障方向指向调用方。
    同理不能用 `4003`（大模型/视觉 API 失败）——本层一次通道调用都没发出，
    用那个码会让 4.11 的「通道失败分别计数」把装配错误算进通道故障。
    故取 `5000`（内部错误）。本类继承 `AiCoreError` 而不是 `ParamError`：
    后者的构造期校验只接受 `1xxx` 三档。
    """

    code: int = INTERNAL_ERROR_CODE


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """执行器的四项参数（**前三项来自 `Settings`**，本类不产生数字）。

    四项参数的来源与出处（表格行宽会超限，故逐条列出，内容与表格等价）：

    - `lease_ms`：`Settings.lease_ms`（默认 30000），出处 `design.md:208` 的 `<leaseMs>`；
    - `max_retries`：`Settings.max_retries`（默认 3），出处 `design.md:210`「最大次数」；
    - `concurrency_limit`：`Settings.concurrency_limit`（默认 4），出处 `design.md:212`
      「实例内并发任务数由信号量封顶（可配）」；
    - `poll_interval_s`：本模块 `POLL_INTERVAL_S`，设计文档未给数值（见该常量的注释）。

    `frozen` + `slots` 同 `TaskPolicy`：配置是共享常量，就地改写会污染所有读取方
    （改写点与受害点相隔很远，排障成本极高）。
    """

    lease_ms: int
    max_retries: int
    concurrency_limit: int
    poll_interval_s: float = POLL_INTERVAL_S


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """可领取任务的**最小**信息（不含 handler——handler 由注册表按类型解析后注入）。

    `account_id` 与 `created_at` 是**分片键**（`er.md` §5.2），本层原样带走、原样交回
    `TaskStore` 的写方法：物理表名由 `repository` 侧现算，本层 MUST NOT 自己算表名
    （那会把分片知识复制进 `core`，而 `core` 不得依赖 `repository`）。
    """

    task_id: str
    task_type: str
    account_id: str
    created_at: datetime


class TaskStore(Protocol):
    """`ai_task` 的**执行侧**抽象（由 `main.py` 注入 `repository/task_lease_store.py` 的实现）。

    ## 全部方法是**同步**的（`def`，不是 `async def`）

    本服务的数据库访问是同步 SQLAlchemy（`repository/session.py` 已定档，MUST NOT 引入
    async driver），而 `TaskRunner` 是 async —— 故**边界在调用点**：
    `TaskRunner` MUST 用 `await run_in_threadpool(...)` 调用这里的每个方法，
    MUST NOT 在事件循环里直接调它们（理由见模块 docstring §四）。

    ## 每个写方法都收 `account_id` 与 `created_at`

    `ShardKey` 需要它们才能算出物理表名（`er.md` §5.2 的分片键是
    `(account_id, created_at)`），而这两个值已经在 `ClaimedTask` 里了 ——
    故 `TaskRunner` 直接把 `claimed` 拆开传进去。

    ## 为什么用 Protocol 而不是 ABC

    与 `provider/base.py` 同一取向（本服务只依赖 Protocol 的**形状**）：
    测试替身不必继承任何基类，且「少实现一个方法」在**注入点**就被 mypy 拦住
    （`TaskRunner.__init__` 的形参有类型），而不是等到运行期才炸。
    """

    def list_claimable(self, *, limit: int, now: datetime) -> Sequence[ClaimedTask]:
        """扫出可领取的任务（`status = PROCESSING`，按 `created_at` 升序，`limit` 下推）。

        **只扫当前月**：跨月扫描违反 `er.md` §5.3「查询 MUST 携带分片键下推」。
        """
        # 声明体用 `raise NotImplementedError` 而不是 `...`：mypy 2.x 的 strict 对
        # 「返回类型非 `None` 而函数体是 `...`」报 `empty-body`（`-> None` 才接受 `...`）。
        # 这一行同时是运行期护栏：本类只是**形状**声明，误当基类实例化后调用会当场炸，
        # 而不是安静地返回一个 `None` 让上层把「没实现」当成「没有可领取任务」。
        raise NotImplementedError

    def begin_attempt(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        """标记「事实源里正在跑」：`status=PROCESSING` + `progress=1`（`er.md` §6.1 L293）。"""
        ...

    def mark_succeeded(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        progress: int,
        finished_at: datetime,
    ) -> None:
        """写成功终态：`status=SUCCEEDED` + `progress=100` + `finished_at`。"""
        ...

    def mark_failed(
        self,
        task_id: str,
        *,
        account_id: str,
        created_at: datetime,
        error_code: str,
        finished_at: datetime,
    ) -> None:
        """写失败终态：`status=FAILED` + `error_code` + `finished_at`（`er.md` §6.1 L294/L298）。"""
        ...

    def requeue(self, task_id: str, *, account_id: str, created_at: datetime) -> None:
        """重新排队：`status=PROCESSING` + `progress=0`。

        **不清 `error_code`**（理由见 `repository/task_lease_store.py` 的同名方法）。
        """
        ...


class TaskPolicy(Protocol):
    """任务类型策略中**本层真正读到的成员**（`design.md:185` 的「是否可重试」+ 类型名）。

    ## 为什么是一个 Protocol，而不是 import 注册表的 dataclass

    `.importlinter` 契约 4 禁止 `core -> aicore.service` 的**任何**导入边
    （`aicore.service` 整包在 forbidden 列表里，且未开 `allow_indirect_imports`），
    而注册表的实现 `service/task/registry.py` 住在 service 层。故本层只能声明
    **自己需要的那部分形状**：结构子类型让 `service.task.registry.TaskPolicy`
    实例**直接**满足本 Protocol（它本来就有这两个成员），组合根无需适配器。

    ## 只声明两个成员（**MUST NOT 把六个字段全抄一遍**）

    把 `TaskPolicy` 的六个字段抄进 `core` 等于把 service 的结构复制过来——
    那正是契约 4 要防的耦合方向（下次注册表加字段，这里会跟着动）。
    本层真正读到的只有两个：

    - `retryable`：失败分流的判据（`False` → 不退避，直接转人工）；
    - `task_type`：日志与错误文案里点名是哪个类型（排障要能定位）。

    ## `timeout_s` **刻意不在本 Protocol 里**（这是一条被用例钉住的纪律）

    任务级超时按工单 §2.5 硬约束 4 取 **`handler.timeout_s()`**（处理器自己声明的那个）。
    注册表行内的 `timeout_s` 是**配置默认值快照、不是权威值**（见 4.6 的 `_BORROWED_TIMEOUT_S`
    注释）：权威值只在 `get_policy` 现读 `Settings` 时才产生。
    执行器若读策略里的 `timeout_s`，就会静默拿到一个**不随配置变**的超时——
    「取了一个看起来对的错值」比报错更难查，故本类不声明它，
    并由 `tests/unit/test_task_runner.py::test_runner_never_reads_policy_timeout`
    用源码级断言（AST 剥注释后扫 `timeout_s`）钉住。
    """

    @property
    def task_type(self) -> str:
        """本策略对应的任务类型（只进日志与错误文案，不参与任何分支）。"""
        raise NotImplementedError

    @property
    def retryable(self) -> bool:
        """该类型的任务失败后是否允许**重新排队重试**（`design.md:185`）。

        `False` 的类型**不进入退避**：首次失败即按超限处理（转人工复核队列）。
        声明了就必须被用上，否则那个字段只是装饰。
        """
        raise NotImplementedError


class TaskHandler(Protocol):
    """任务处理器（由注册表的 `handler_ref` 经组合根解析后注入，见模块 docstring §三）。"""

    def timeout_s(self) -> float:
        """本处理器声明的**任务级**超时（`design.md:185`：处理器需声明自身超时）。

        由**处理器自己**声明而不是执行器统一定：不同任务的合理时长不同
        （一次 OCR 与一次纯计算的风险面完全不同），执行器拿一个统一数字去卡，
        要么卡死正常的重活、要么放过跑飞的轻活。超时后执行器按失败分流，
        业务码取 `DEPENDENCY_TIMEOUT_CODE`（`5002`，`core/errors.py`）。
        """
        raise NotImplementedError

    async def handle(self, task: ClaimedTask) -> None:
        """执行任务。**成功即正常返回；失败 MUST 抛 `AiCoreError`（带业务码）**。

        抛出别的异常（`ValueError` 这类编程错误）执行器**不吞**也不改写：它会被记成
        ERROR 日志、该任务的终态**不写**（留待租约过期后由别的实例重做），
        因为「payload 拼错了」这种 bug 不该被伪装成一次业务失败
        （与 `provider/guard.py` 的「编程错误原样上抛、不计入熔断窗口」同向）。

        **边界（A1 修复后仍然成立，MUST NOT 读成"一定有人会重做"）**：上面那句
        「留待租约过期后重做」的**前提是心跳已经收掉**。若异常发生在心跳**起来之前**
        （处理器解析 / `begin_attempt` 写库），这一轮**根本没有租约心跳**，
        而 `__init__` 之前已经 `acquire` 成功——那份租约**只能等它自然过期**（`lease_ms`）。
        修复 A1 做的事是：把"可能抛异常的解析步骤"全部挪到心跳之前，
        让"起了心跳就必须收掉它"成为结构上成立的事（`finally` 覆盖范围之外不再有解析）。
        """
        ...


class TaskRunner:
    """执行器内核：领取 → 标记在跑 → 心跳续期 → 执行（带任务级超时）→ 终态 / 退避。

    各步骤的**顺序本身就是契约**，见模块 docstring §二；四条硬约束（续期失败即放弃、
    先写库后释放租约、超限转人工、可重试性）在 `execute` 的 docstring 里逐条标注。
    """

    def __init__(
        self,
        *,
        store: TaskStore,
        locks: LockStore,
        handlers: Mapping[str, TaskHandler],
        config: RunnerConfig,
        policies: Mapping[str, TaskPolicy] | None = None,
        executor: Executor | None = None,
    ) -> None:
        """`executor` 为 `None` 时**自建** `cpu_pool(config.concurrency_limit)`。

        MUST NOT 静默落到事件循环的默认执行器：默认池是**进程共享**的，
        把它当 CPU 池用会让「图像解码」占住其它库（例如 anyio 用于同步路由的线程）
        要用的线程——那正是 `design.md:200-206` 把两类工作分表的原因。
        自建的池在 `stop()` / `aclose()` 里 `shutdown(wait=False)`；
        **外部传入的池不在此关闭**（谁创建谁释放：那是调用方的资源）。

        `policies` 由**组合根**从注册表现读后注入（`dict(REGISTRY)`，见模块 docstring §六）。
        默认 `None` = **空映射**，语义是「本实例没有任何已知策略」→ 失败一律按
        「不可重试」分流（转人工，而不是无限重试）。这个默认值是**保守方向**：
        缺策略时宁可少重试几次、把任务交给人，也不要在一个本不该重试的类型上反复重试
        （那是**可观测的成本**：每次重试都可能重放一次付费通道）。

        ## 为什么**没有** `clock` 形参（曾有过，本轮删掉）

        第一版有过 `clock: StepClock | None = None`，理由是"同 `provider/guard.py` 的取向"。
        它是一个**会骗人的接缝**：注入了假时钟的调用方以为控制了时间，实际什么都没控制——
        本类的两处时间来源都**不可注入**，且各有硬理由：

        - `now()`（写进 `begin_attempt` / `mark_*` / `list_claimable` 的时间）**必须是墙钟**：
          它要与人读的时间对齐、要写进库、要算分片月；被假时钟改写成 1000 秒那一类值，
          库里的 `finished_at` 就成了假时间戳、分片月会算错；
        - 心跳的等待**必须是真的 `asyncio.sleep`**：它的作用是让出控制权并让真实时间流过
          （`lease_ms / 3` 是真实世界的节奏）。换成注入时钟的 `sleep` 后，一个
          "无让出点"的假时钟会把心跳变成**忙循环**（`await` 不挂起 → `while True` 空转，
          占满 CPU 且永远不续期）。

        故删掉这个形参，而不是把它改成"可用"。用例侧不再传 `clock=`。
        """
        self._store = store
        self._locks = locks
        self._handlers = dict(handlers)
        self._policies: dict[str, TaskPolicy] = (
            {} if policies is None else dict(policies)
        )
        self._config = config
        self._owned_executor = executor is None
        self._executor: Executor = (
            cpu_pool(config.concurrency_limit) if executor is None else executor
        )
        #: 已领取但还没执行完的 claim：`task_id -> TaskClaim`（见模块 docstring §二末）。
        self._claims: dict[str, TaskClaim] = {}
        #: 本轮在飞的任务（`run_forever` 退出前等它们收尾，见模块 docstring §五）。
        self._inflight: set[asyncio.Task[None]] = set()
        #: 「有任务在飞」的活动标记：只被 `run_forever` 的循环持有引用，
        #: 用于**不碰信号量内部队列**地等待空闲许可（理由见 `run_forever` 的 docstring）。
        self._any_task_active = asyncio.Event()
        self._closed = False

    @property
    def executor(self) -> Executor:
        """本实例使用的执行器（供用例与排障断言「用的是哪个池」）。"""
        return self._executor

    @property
    def config(self) -> RunnerConfig:
        """本实例的配置（只读；`RunnerConfig` 本身是 frozen 的）。"""
        return self._config

    @property
    def registered_handlers(self) -> tuple[str, ...]:
        """已注册处理器的类型名（**排序后的元组**，供组合根打启动日志与用例断言）。

        返回类型名而不是对象：启动日志里要的是「注册了几个、都是哪些」，
        把处理器对象交出去会给调用方一个"In 顺手调一下"的入口（那不是组合根该做的事）。
        元组而不是 `KeysView`：后者是**活视图**，日志输出后仍会随字典变化，
        排查时看到的与记录时的不一致。
        """
        return tuple(sorted(self._handlers))

    @property
    def registered_policy_types(self) -> tuple[str, ...]:
        """已注入策略的类型名（**排序后的元组**）。

        与 `registered_handlers` 对称：组合根注入 `policies=dict(REGISTRY)`，
        而「到底注入了哪些策略」是装配事实，需要可被**读**——
        否则只能从 `_policies` 这个私有字段里摸（测试与排障都不该那么做）。
        返回类型名而不是 `TaskPolicy` 对象，理由同 `registered_handlers`：
        启动日志与用例要的是"注册了哪些"，不是"给你一个可以顺手调用的对象"。
        """
        return tuple(sorted(self._policies))

    def now(self) -> datetime:
        """当前时刻（**墙钟**）：写进 `begin_attempt` / `mark_*` 的时间参数。

        与 `StepClock.monotonic()` 的**分工不是重复**：`monotonic` 是单调读数（只服务租约
        这类时长判断，墙钟回拨会把它算错），而写进库的时间要与人读的时间对齐，
        只能用墙钟。**故它不注入时钟**：`finished_at` 的值不该被测试的假时钟改写
        （否则库里会出现 1000 秒这类假时间戳）。
        """
        return datetime.now(UTC)

    async def claim_once(self) -> ClaimedTask | None:
        """领一个任务；一个都没领到返回 `None`。

        **顺序**（工单 §2.5 硬约束 1）：`list_claimable`（MySQL）→ 逐个 `locks.acquire`（Redis）
        → **第一个成功即返回**。`acquire` 返回 `None`（别人持有 / 退避中）就**试下一个**，
        MUST NOT 重试同一个。

        ## `limit` 为什么取 `concurrency_limit`（实测踩过一次，记在这里）

        第一版写的是 `limit=1`，理由是"本方法一次只交出一个任务，多查的行会作废"。
        **那个理由是错的**，而且错得隐蔽：`limit=1` 时 `list_claimable` 只回一行，
        于是「第一个抢不到就试下一个」这个循环**结构上永远进不了第二轮**——
        硬约束 1 的「试下一个」成了不可达代码，表现为「第一个候选被别人持有时，
        本轮一个任务都领不到」（容忍度退化成一个候选）。
        取 `concurrency_limit` 是因为它同时满足两头：

        - **够用**：一轮里确实可能连续遇到 `concurrency_limit` 个被占用的候选
          （本实例的并发上限就是这么多），取它让"试下一个"有实际余量；
        - **不浪费**：`run_forever` 每轮**先拿信号量再领取**，故本轮最多真正执行
          `剩余许可数 <= concurrency_limit` 个任务，多查的行不会白查到哪里去
          （抢不到的那几行本来也要被跳过）。

        代价（如实登记）：一轮里若候选全部被占，会多查几行"作废的行"。
        相对「硬约束 1 变成不可达代码」这个代价，几行索引扫描可以忽略。
        """
        candidates = await run_in_threadpool(
            self._store.list_claimable, limit=self._config.concurrency_limit, now=self.now()
        )
        for candidate in candidates:
            claim = await self._locks.acquire(candidate.task_id, lease_ms=self._config.lease_ms)
            if claim is None:
                # 别人持有 / 退避中：试下一个，**不重试同一个**。
                continue
            # 记下 claim：`execute` 要靠它拿 token 与 attempt（见模块 docstring §二末）。
            self._claims[candidate.task_id] = claim
            return candidate
        return None

    async def execute(self, claimed: ClaimedTask, *, claim: TaskClaim | None = None) -> None:
        """执行一个已领取的任务（步骤顺序见模块 docstring §二）。

        四条硬约束在代码里的落点：

        1. **`begin_attempt` 在心跳之前**（硬约束 2）：先让事实源显示「在跑」，再起续期。
        2. **续期失败 / 续期抛异常 → 主动放弃**（硬约束 3）：**取消处理器**、不写任何终态
           （`mark_succeeded` / `mark_failed` / `requeue` 一次都不调），
           让租约自然过期由别人回收（`design.md:208`）。
           「放弃」的准确含义与**不可承诺的部分**见模块 docstring §二之二——
           一句话：取消能停住协程，**收不回已经交给线程的工作、也收不回已经发出的同步调用**。
        3. **任务级超时用处理器声明的 `timeout_s`**（硬约束 4），超时按失败分流、
           业务码取 `DependencyTimeoutError` 自带的 `5002`。
        4. **成功后先 `mark_succeeded` 再 `release`**（硬约束 6）：反过来会在租约释放与
           终态落库之间留下一个窗口，别的实例可以领到同一个任务并**重复调用付费通道**。

        ## 为什么处理器是 `create_task` 而不是就地 `await`（B1 的修复要点）

        就地 `await handler.handle(...)` 时，心跳虽然能发现「租约没了」，
        但**没有任何办法把处理器停下来**——它只能等处理器自己返回（或等到 `timeout_s`）。
        实测（修复前）：`lease_ms=100`（心跳 0.033s）、`renew` 首次即 `False`、处理器耗 1.0s，
        结果是 0.033s 就打了「主动放弃执行」的日志，而 `execute` 到 **1.032s** 才返回、
        处理器**跑完了**、**付费调用发生了 1 次**。日志在说谎，设计禁令没落地。

        修法：处理器放进**独立 task**，用 `asyncio.wait({handler, heartbeat}, FIRST_COMPLETED)`
        等两者中先结束的那个；心跳先结束（= 租约丢失）时**取消处理器**。
        三条分支的处置：

        | 谁先结束 | 处置 |
        |---|---|
        | 心跳结束 | 租约丢失 → `handler_task.cancel()` + 等它真的结束 + **跳过全部写回** |
        | 处理器结束（心跳还在） | 正常路径：成功写终态并释放租约 / 失败走两条分流 |
        | 心跳**之前**就已结束 | 同「心跳结束」（`asyncio.wait` 把已完成的 task 放进 `done`） |
        | 外部取消（关停/调用方） | 原样上抛 `CancelledError`，**绝不吞掉**（与租约丢失严格区分） |

        `claim` 若不传，按 `task_id` 从 `claim_once` 记下的那份取；两者都没有时退化成
        `attempt=1` 的合成 claim（**只可能出现在「没经过 `claim_once` 就执行」的路径上**）。
        """
        resolved = self._claims.pop(claimed.task_id, None) if claim is None else claim
        if resolved is None:
            resolved = TaskClaim(task_id=claimed.task_id, token="", attempt=1)
        await run_in_threadpool(
            self._store.begin_attempt,
            claimed.task_id,
            account_id=claimed.account_id,
            created_at=claimed.created_at,
        )

        lease_lost = False

        async def _heartbeat() -> None:
            """独立 task 的续期心跳（间隔 `lease_ms / HEARTBEAT_DIVISOR`）。

            两种终止形态，处置相同（都是**放弃**，见模块 docstring §二之二）：

            - `renew` 返回 `False`（租约已过期或被别人持有）→ 置 `lease_lost` 并 return；
            - `renew` **抛异常**（Redis 抖动）→ 同样置 `lease_lost` 后 return。
              MUST NOT 静默继续：续不上租约还继续跑，就是「两个实例同时处理同一个任务」的
              入场券；而「异常后继续执行」正是 `tests/structural/test_source_guards.py`
              规则 6 要禁的形态（同向取向）。

            **本函数只负责"发现"**：它置位并返回，**取消处理器的是 `execute`**。
            取消逻辑放在 `execute` 而不是这里，是因为 `done` 集合里"心跳已结束"既可能来自
            自己 return、也可能来自它在 `wait` 之前就已结束——两条路都要走到同一处取消。
            """
            nonlocal lease_lost
            interval = self._config.lease_ms / 1000.0 / HEARTBEAT_DIVISOR
            while True:
                await asyncio.sleep(interval)
                try:
                    renewed = await self._locks.renew(resolved, lease_ms=self._config.lease_ms)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _logger.warning(
                        "任务 %s 的租约续期失败（Redis 异常）：停止等待处理器的结果，"
                        "不写终态，由租约过期后回收（design.md:208）",
                        claimed.task_id,
                        exc_info=True,
                    )
                    lease_lost = True
                    return
                if not renewed:
                    _logger.warning(
                        "任务 %s 的租约已不再归本实例所有（续期被拒）：停止等待处理器的结果，"
                        "不写终态，由租约过期后回收（design.md:208）",
                        claimed.task_id,
                    )
                    lease_lost = True
                    return

        # **解析顺序是硬要求（A1）**：处理器解析与超时声明都**在起心跳之前**完成。
        # 第一版把 `_declared_timeout_s(handler)` 放在 `create_task(_heartbeat())` 之后、
        # `try` 之前，于是处理器作者的一个 bug（`timeout_s` 抛异常 / 返回 None）就让心跳
        # **脱离所有回收路径**——它按 `lease_ms/3` 一直续期成功，**没有任何实例能再领到这个
        # 任务**（`SET NX` 永不成功），行永远停在 `PROCESSING`。
        # 实测（评审探针）：`execute` 抛 `KeyError` 后 0.25s 内心跳又跑了 8 次、`release` 0 次。
        handler = self._handlers.get(claimed.task_type)
        policy = self._policy_for(claimed.task_type)
        declared_timeout = self._declared_timeout_s(handler)

        heartbeat = asyncio.create_task(_heartbeat())
        succeeded = False
        error: AiCoreError | None = None
        timed_out = False
        if handler is None:
            # 装配缺失：显式失败（记 ERROR + 按失败分流），MUST NOT 静默跳过（§三）。
            error = self._unresolved_handler_error(claimed)
        else:
            # 处理器**先落成 task** 再等（`asyncio.wait` 只收 `Task`/`Future`，不收裸协程）。
            handler_task = asyncio.create_task(handler.handle(claimed))
            done, _pending = await asyncio.wait(
                {handler_task, heartbeat},
                timeout=declared_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                # `timeout` 到期而两者都还没结束 → **任务级超时**。
                #
                # 为什么不用 `asyncio.wait_for(handler_task, ...)`：`wait_for` **恰好超时**时
                # 取消的是被它包住的那个 task，而这个取消可能在处理器刚返回的同一瞬间到达——
                # 那时抛的是 `CancelledError` 而不是 `TimeoutError`，一条**正常完成**的任务
                # 会被判成超时（边界竞态）。这里自己判「谁都没结束」，语义不含糊。
                timed_out = True
                error = DependencyTimeoutError(
                    f"任务 {claimed.task_id} 超过处理器声明的超时 {declared_timeout}s"
                )
            elif heartbeat in done:
                # 租约丢失（或心跳在此之前就已结束）→ **取消处理**，见 §二之二。
                lease_lost = True
            else:
                try:
                    handler_task.result()  # 成功返回；失败按异常类型分流
                except AiCoreError as exc:
                    error = exc
                except asyncio.CancelledError:
                    # 外部取消（关停 / 调用方取消）→ 原样上抛，**绝不吞掉**。
                    # 租约丢失这一路不经过这里：那条路是 `heartbeat in done` 分支。
                    await _dissolve_task(handler_task)
                    raise
                else:
                    succeeded = True

        if lease_lost or timed_out:
            # 两种情况下处理器都还可能在跑，**必须**取消并等它真的结束：
            # - 租约丢失 → 放弃执行（§二之二）；
            # - 任务级超时 → 「不再等它」（超时的处置本来就是掐掉）。
            # `await` 是必须的：不 await 的话处理器可能在本协程返回后还在跑，
            # 而取消产生的 `CancelledError` 也无人接收（`_dissolve_task` 负责吞掉它）。
            await _dissolve_task(handler_task)
        try:
            if not lease_lost:
                if succeeded:
                    await self._mark_succeeded(claimed, resolved)
                else:
                    # 结构保证：`succeeded=False` 且未失去租约时必有 error。
                    assert error is not None
                    await self._handle_failure(claimed, policy, resolved, error)
        finally:
            await self._cancel_heartbeat(heartbeat)

    async def run_once(self) -> bool:
        """跑一轮：**没有可领取任务返回 `False`**，且此时**不调用 `acquire`**。

        「无任务时不碰 Redis」是一条性能要求而不是风格偏好：空轮询是执行器的常态
        （M1 的任务量远低于 1 QPS），每次空轮询多一跳 Redis 只会白占连接与带宽。
        `claim_once` 的结构天然满足它——`list_claimable` 返回空序列时循环体一次都不进。
        """
        claimed = await self.claim_once()
        if claimed is None:
            return False
        await self.execute(claimed)
        return True

    async def run_forever(self, *, stop: asyncio.Event) -> None:
        """按 `poll_interval_s` 轮询直到 `stop` 被 set（背压与退出语义见模块 docstring §五）。

        ## 为什么是「先拿许可、再领取」（B2 的修复要点）

        第一版是 `claim_once()` 之后把 `execute` 协程挂到信号量上排队 —— 也就是工单
        §2.5 硬约束 7 明令禁止的**领了再排队**。实测（控制者探针 B，`concurrency_limit=1`、
        8 个候选）：`max_in_flight=1` 但 **`max leases held at once = 2`** ——
        **第二个任务在第一个跑完前已经被领取了**，与验收第 18 条直接冲突。

        代价不是洁癖：被领取但还在排队的任务**持有租约却没有心跳**（心跳在 `execute` 里才起，
        而 `execute` 要等许可）。等待超过 `lease_ms` 时租约**静默过期** → 别的实例回收
        → 同一个任务被两个实例执行，正是 `design.md:208` 要防的重复付费调用。

        故顺序是：**拿许可 → 领任务 → 领到就派发、领不到就立刻还许可**。
        许可因此与「在飞任务数」一一对应，`run_forever` 不再持有任何"已领取但未开工"的租约。

        ## 这个契约**不依赖**存储层谓词的副作用（工单要求说明）

        `SqlTaskLeaseStore.list_claimable` 的谓词是 `WHERE status = 'PROCESSING'`，
        而 `begin_attempt` **不改 status** —— 于是**正在跑的行仍然出现在扫描窗口里**。
        在 `limit = concurrency_limit` 且窗口恰好被"自己在跑的行"占满时，`acquire` 会被自己
        挡住，**表面上看不出领了再排队**。那个掩盖是**偶然的、且依赖窗口大小**：
        窗口里一旦出现一个更早的、租约已过期可回收的行（崩溃回收路径），
        「领了再排队」就会真的发生。

        本实现在结构上排除了这种依赖：**许可在领取之前就已经拿到**，
        故「同时持有的租约数」在**任何**窗口内容下都 ≤ `concurrency_limit`——
        与 `list_claimable` 返回什么无关。

        > **一处曾经写错的地方（本轮更正，MUST NOT 再写成更强的断言）**：
        > 本段此前写着「窗口被许可数绑死，故"同时持有的租约数"对两种实现给同一个答案」。
        > **那是错的，而且已被控制者的探针否证**：`list_claimable` 的窗口语义**可以有另一种
        > 合法实现**——「排除**本轮已 `begin_attempt` 的行**」（理由：我自己正在处理的行，
        > 对我自己而言不是可领取的）。那种替身下，许可满时窗口里**仍有别的可领取任务**，
        > 于是"先领取再排队"的实现会**真的持有 2 个租约**（控制者探针实测：正确实现峰值 1、
        > 修复前形态峰值 2）。
        > 教训：**「不可能」是替身的性质，不是契约的性质**——不要把某个测试替身的行为
        > 写成对接口的断言（这正是本组反复在修的那类毛病）。

        ## `stop` 仍然能及时打断

        等许可时**不能**裸 `await semaphore.acquire()` 加超时包一层（`stop` 会在
        "许可被长任务占满"期间迟迟得不到响应），也**不能**用
        `wait_for(semaphore.acquire(), ...)`：实测那种组合会在超时时把
        `CancelledError` 泄漏出来——`asyncio.timeout` 只有在"取消计数是它自己那一次"时
        才把 `CancelledError` 转成 `TimeoutError`，而 `Semaphore.acquire` 在公平等待队列里的
        取消路径会让这个计数对不上，于是 `wait_for` 抛出的是 `CancelledError` 而不是
        `TimeoutError`（表现为 `run_forever` 整个被取消、`await run_forever(...)` 抛
        `asyncio.exceptions.CancelledError`）。

        改用**自己的活动标记**做等待条件：`any_task_active()` 是一个只被本循环持有引用的
        `asyncio.Event`，有任务在飞时被置位、`_drain_inflight` 收尾后清除。
        等它（`wait_for(..., timeout=poll_interval_s)`）就不会碰信号量的内部队列，
        超时干净地变成 `TimeoutError`，`stop` 也能在一个轮询间隔内被看到。

        ## 等许可的判据是「**在飞任务数 < 上限**」，不是「等到有人在飞」

        第一版写成「等标记置位」→ 在**空闲**的执行器上（没有任何在飞任务）标记**永远不置位**，
        于是 `run_forever` **一个任务都领不到**（实测：用例在外层 `wait_for(..., 5)` 上超时）。
        空闲时许可**本来就是空的**，正确判据是：

        - 在飞任务数 `<` 许可上限 → **不必等**，直接去 `acquire()`（它不会阻塞）；
        - 否则 → 等「有一个任务结束」（`_any_task_active.wait()` 被 `_settle` 置位——
          注意 `Event` 的 `set()` 会唤醒**全部**等待者，而 `_settle` 在每个任务结束时都会
          `set()`，故"至少一个许可空出来"必然唤醒它）。

        ## 为什么 `await semaphore.acquire()` 可以**不带超时**（不变式，MUST 守住）

        那一行没有超时、也不能被 `stop` 打断，故它**必须保证不会阻塞**。依据是本类的一条
        内部不变式：**在飞任务与许可一一对应**——

        - 许可**只在** `_execute_with_permit` 的 `finally` 里归还（`claimed is None` 那条
          路径当场归还），而该协程同时就是 `_inflight` 里的那个 task；
        - 于是「`len(self._inflight) < concurrency_limit`」⇒ 至少有一个许可空闲。

        反过来说：**任何让"门判据"与"许可容量"不一致的改动都会在这里造出一个永久卡死**
        （门说没满、许可却是 0 ⇒ 裸 `acquire()` 永远等下去，`stop` 也救不回来）。
        本轮就删掉了一个这样的暗扣（`RunnerConfig.extra_busy_permits` 曾把许可容量
        减成 `concurrency_limit - n`，而门仍按 `concurrency_limit` 判）。
        两处数字**必须恒等**，这正是不变式的全部内容。
        """
        semaphore = asyncio.Semaphore(self._config.concurrency_limit)
        consecutive_failures = 0
        while not stop.is_set():
            try:
                # 超时即「本轮没有可领的任务」：`stop.wait()` 被取消，不是错误。
                await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_s)
                break  # stop 被 set
            except TimeoutError:
                pass
            if stop.is_set():
                break
            if len(self._inflight) >= self._config.concurrency_limit:
                # 许可已满：等一个任务结束（不领取、不排队），或等一个轮询间隔后重查 `stop`。
                # 超时就是"这一个间隔内没有任务结束"，不是错误 → `suppress`。
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._any_task_active.wait(), timeout=self._config.poll_interval_s
                    )
                continue
            if stop.is_set():
                break
            # **先拿许可再领取**（背压）：此刻必然有空许可，`acquire()` 不会阻塞。
            await semaphore.acquire()
            try:
                claimed = await self.claim_once()
            except asyncio.CancelledError:
                semaphore.release()
                raise
            except Exception as exc:
                # **瞬时错误 MUST NOT 杀死轮询循环（A2）**。
                #
                # 为什么兜 `Exception` 而不是列几个具体类型：领取路径上会抛的瞬时错误形态很杂
                # ——`list_claimable` 打到还没建的月表（`1146`）、Redis 抖动、连接池借出失败……
                # 逐个列举必然漏。而两种错法的代价**不对称**：循环死掉 = 进程活着却永久不领任务、
                # 且此前一行日志都没有（`create_task` 的异常只在关停时才 retrieve）；
                # 多兜一层 = 一条有界退避 + 一条 ERROR。故取后者。
                # `consecutive_failures` 进日志：让"持续失败"在日志里一眼可见，
                # 而**有界**退避（上限 `CLAIM_FAILURE_BACKOFF_MAX_S`）保证它不会变成刷屏。
                semaphore.release()
                consecutive_failures += 1
                delay_s = min(
                    CLAIM_FAILURE_BACKOFF_BASE_S * 2 ** (consecutive_failures - 1),
                    CLAIM_FAILURE_BACKOFF_MAX_S,
                )
                _logger.error(
                    "领取任务失败（连续第 %d 次，退避 %.1fs 后重试）：%s: %s",
                    consecutive_failures,
                    delay_s,
                    type(exc).__name__,
                    exc,
                    exc_info=exc,
                )
                # 退避**可被 `stop` 打断**（验收第 19 条不得回退）：用 `stop.wait()` 当计时器，
                # 而不是 `asyncio.sleep`——`stop.set()` 的那一刻就返回，关停不必等完整个退避。
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay_s)
                continue
            consecutive_failures = 0
            if claimed is None:
                # 没有可领的任务：**立刻把许可还回去**，否则空轮询会把并发额度占死。
                semaphore.release()
                continue
            # 许可随任务一起交给这个协程持有：`execute` 结束（含被取消）时自动归还。
            self._track(asyncio.create_task(self._execute_with_permit(semaphore, claimed)))
        await self._drain_inflight()

    async def _execute_with_permit(
        self, semaphore: asyncio.Semaphore, claimed: ClaimedTask
    ) -> None:
        """占着一个许可执行任务：许可在 `execute` **整体**结束时才归还。

        许可的持有范围是并发封顶的关键（实测踩过一次）：若许可在"派发"之后就归还，
        并发度实际**没有任何封顶**（`concurrency_limit=1` 时观察到 2 个处理器同时在跑）。
        形态上的教训：**信号量保护的是「工作」，不是「派发工作的动作」**。
        """
        try:
            await self.execute(claimed)
        finally:
            semaphore.release()

    async def stop(self) -> None:
        """关停：释放自建的 CPU 池（`shutdown(wait=False)`）；**幂等**。

        只关闭**本实例自建**的池：外部注入的池归调用方所有（谁创建谁释放）。
        `wait=False` 的理由：等在飞任务收尾是 `run_forever` 的职责
        （它已经 `await _drain_inflight()`），这里若 `wait=True` 会把「关停」
        变成一次可能很久的阻塞。释放池**不影响**后台线程里正在跑的 `run_cpu_bound`：
        已提交的任务照常完成，只有新提交会被拒（`RuntimeError`）——
        而那时的正确处置就是「别再提交了」。
        """
        if self._closed:
            return
        self._closed = True
        if self._owned_executor:
            self._executor.shutdown(wait=False)

    async def aclose(self) -> None:
        """`stop()` 的别名（资源释放的统一入口，语义完全相同）。"""
        await self.stop()

    # ------------------------------------------------------------------
    # 内部：策略与处理器的解析 / 失败分流 / 终态写回 / 心跳收尾 / 在飞登记
    # ------------------------------------------------------------------
    def _policy_for(self, task_type: str) -> TaskPolicy | None:
        """取类型策略：**纯表查找**，取不到返回 `None`（由分流处切成 `5000`，见 §三）。

        MUST NOT 出现逐类型分支（`if task_type == ...` / `match task_type`）：
        那会让「新增类型」从「加一行注册」退化成「加一个 elif」
        （`design.md:194`；`tests/unit/test_task_registry.py` 有 AST 判据钉住）。

        取不到策略 = 执行器不认识这个类型 → 由调用方按**内部错误**（`5000`）分流，
        而不是抛出 `get_policy` 那种 `1003`（那是**请求参数**语义，对着的是
        「调用方提交了不存在的类型」；而执行器读到的是**库里已落行的数据**，
        此刻不认识它说明「注册表与库不一致」→ 服务端装配问题）。
        """
        return self._policies.get(task_type)

    def _unresolved_handler_error(self, claimed: ClaimedTask) -> AiCoreError:
        """构造「没有可用处理器」的错误（**先记一条 ERROR 日志**，绝不静默跳过）。

        消息里的成因提示是**条件式**的：只有确认过策略映射（`_policy_for` 取到了策略）
        才说「注册表里有、是组合根没解析出来」。M1 的 `handlers={}` 下取不到策略，
        故只能如实说「本实例没有为它解析出处理器」——MUST NOT 反过来断言
        「这个类型不在注册表里」，那是一句没有依据的话（会误导排障方向）。
        """
        known_in_registry = self._policy_for(claimed.task_type) is not None
        reason = (
            "该类型已有策略声明（任务类型策略注册表里有它），但本实例没有为它解析出处理器"
            "（见 core/task_runner.py 模块 docstring §三）"
            if known_in_registry
            else "本实例没有为它解析出处理器（组合根注入的 handlers 里没有这个类型；"
            "M1 的 handlers 为空，见 task-4.7-brief.md §2.8）"
        )
        _logger.error(
            "任务 %s 的类型 %r 没有可用处理器：%s。按失败分流处置，error_code=%s"
            "（MUST NOT 静默跳过：跳过会让任务永远停在 PROCESSING 且没有任何告警，"
            "design.md:194）",
            claimed.task_id,
            claimed.task_type,
            reason,
            INTERNAL_ERROR_CODE,
        )
        return HandlerNotResolvedError(
            f"任务 {claimed.task_id} 的类型 {claimed.task_type!r} 没有可用处理器：{reason}"
        )

    def _declared_timeout_s(self, handler: TaskHandler | None) -> float:
        """处理器声明的任务级超时；**缺声明时用保守兜底**（见 `FALLBACK_HANDLER_TIMEOUT_S`）。

        `handler is None` 时也走本方法（返回兜底值即可：那一路不会进 `wait_for`），
        故签名收 `None` 而不是让调用方分两处取。
        """
        if handler is None:
            return FALLBACK_HANDLER_TIMEOUT_S
        declared = getattr(handler, "timeout_s", None)
        if not callable(declared):
            _logger.error(
                "处理器缺少 timeout_s() 声明：按兜底 %.1fs 执行"
                "（本层 MUST NOT 用无限超时：一个挂死的处理器会把并发额度永久占满）",
                FALLBACK_HANDLER_TIMEOUT_S,
            )
            return FALLBACK_HANDLER_TIMEOUT_S
        value: float = float(declared())
        return value

    async def _handle_failure(
        self,
        claimed: ClaimedTask,
        policy: TaskPolicy | None,
        claim: TaskClaim,
        error: AiCoreError,
    ) -> None:
        """失败分流（**两条 MUST 分开**，工单 §2.5 硬约束 5）。

        `claim` 由调用方给（**不重领**）：`attempt` 取它、释放租约也用它——
        两处必须来自**同一个** claim，否则「第几次尝试」与「释放哪把锁」会错位。

        - 可重试 **且** 未超限 → `requeue` + `defer(退避)` + **`release`**；
        - 否则 → `mark_failed(error_code=<异常自带的 code>)`（终态，**不释放**租约）。

        `error_code` MUST 取异常自带的 `AiCoreError.code`，MUST NOT 由本层猜
        （本层不认识业务语义，猜出来的码会把运维引向错误的排查方向）。
        `attempt <= max_retries` **含等号**：`max_retries=3` 时第 3 次失败仍重试，
        第 4 次才转人工（工单 §3.2 第 15 条逐字）。

        **可重试性由策略声明**（`design.md:185` 要求处理器声明「是否可重试」）：
        `retryable=False` 的类型**不进入退避**，首次失败即按超限处理——
        声明了就必须被用上，否则那个字段只是装饰。

        ## 重排队分支为什么**必须**释放租约（实测踩过一次，记在这里）

        第一版只做了 `requeue` + `defer`，**没有** `release`，于是租约继续被本实例持有
        到 `lease_ms`（默认 30s）为止；而退避窗口只有 1s——**重试实质上被租约长度顶着**，
        不是被退避窗口顶着。实测表现：集成用例里"清掉退避键后立刻重领"返回 `None`
        （`acquire` 被自己还没过期的租约挡住），任务要等 30s 才可能被重试。
        对**别的实例**同样成立：它在退避窗口结束后仍然领不到（租约未过期）。

        顺序是**先写库、再写退避键、最后释放租约**：

        - `requeue` 把状态写回 `PROCESSING` 之后，本行就重新"可领取"了，故退避键必须
          **紧随其后**写好（否则这一瞬间任何实例都能领走它，退避形同虚设）；
        - 退避键替租约挡住了领取，故最后释放租约是安全的——释放到退避键生效之间
          不存在"谁都领得到"的窗口（退避键先写）。
        """
        retryable = policy is not None and policy.retryable
        attempt = claim.attempt
        # 策略里的 `task_type` 只进日志/文案（排障要能一眼定位是哪个类型，
        # 而不是回头去 hash 里找 key）：它不参与任何分支判定。
        policy_type = "未声明策略" if policy is None else policy.task_type
        if retryable and attempt <= self._config.max_retries:
            await run_in_threadpool(
                self._store.requeue,
                claimed.task_id,
                account_id=claimed.account_id,
                created_at=claimed.created_at,
            )
            # 退避 = BACKOFF_BASE_S * 2 ** (attempt - 1)：1s → 2s → 4s（《高并发》L260）。
            delay_s = BACKOFF_BASE_S * 2 ** (attempt - 1)
            await self._locks.defer(claimed.task_id, delay_s=delay_s)
            # 退避键已生效，此刻释放租约不再留窗口（理由见本方法的 docstring）。
            await self._locks.release(claim)
            _logger.warning(
                "任务 %s 第 %d 次尝试失败（code=%s，策略=%s）：已重新排队、退避 %.1fs 并释放租约"
                "（可重试=%s，上限=%d）",
                claimed.task_id,
                attempt,
                error.code,
                policy_type,
                delay_s,
                retryable,
                self._config.max_retries,
            )
            return
        await run_in_threadpool(
            self._store.mark_failed,
            claimed.task_id,
            account_id=claimed.account_id,
            created_at=claimed.created_at,
            error_code=str(error.code),
            finished_at=self.now(),
        )
        _logger.error(
            "任务 %s 第 %d 次尝试失败（code=%s，策略=%s）且不再重试（可重试=%s，上限=%d）："
            "置 FAILED 并转人工复核队列（design.md:210 不静默丢单）",
            claimed.task_id,
            attempt,
            error.code,
            policy_type,
            retryable,
            self._config.max_retries,
        )

    async def _mark_succeeded(self, claimed: ClaimedTask, claim: TaskClaim) -> None:
        """写成功终态，**然后**释放租约（顺序见 `execute` 的硬约束 4）。"""
        await run_in_threadpool(
            self._store.mark_succeeded,
            claimed.task_id,
            account_id=claimed.account_id,
            created_at=claimed.created_at,
            progress=SUCCEEDED_PROGRESS,
            finished_at=self.now(),
        )
        await self._locks.release(claim)

    async def _cancel_heartbeat(self, heartbeat: asyncio.Task[None]) -> None:
        """收掉心跳 task（**幂等**：已结束的 task `cancel()` 是空操作）。"""
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat

    def _track(self, task: asyncio.Task[None]) -> None:
        """登记在飞任务并挂**吞不掉异常**的收尾回调。

        `execute` 允许两类异常逃逸（处理器缺陷、终态写回失败），而逃逸到
        「无人 await 的 task」上时只会得到一条 "Task exception was never retrieved"
        警告——那正是「告警丢失」的形态（`design.md:194`）。这里把它收成
        **一条 ERROR 日志**，且**照旧让异常逃逸**（不假装成功）。故 `run_forever`
        不会因一个坏任务崩掉整轮循环，而失败痕迹一定留得下。
        """
        self._inflight.add(task)
        self._any_task_active.set()

        def _settle(done: asyncio.Task[None]) -> None:
            self._inflight.discard(done)
            if not self._inflight:
                # 最后一个在飞任务结束 → 清除活动标记（等待空闲许可的那个循环据此继续）。
                self._any_task_active.clear()
            if done.cancelled():
                return
            failure = done.exception()
            if failure is not None:
                _logger.error(
                    "执行器任务异常终止（未写终态；租约在心跳已收掉的前提下留待过期回收）：%s",
                    type(failure).__name__,
                    exc_info=failure,
                )

        task.add_done_callback(_settle)

    async def _drain_inflight(self) -> None:
        """等在飞任务收尾（`stop` 的语义见模块 docstring §五）。"""
        while self._inflight:
            await asyncio.gather(*tuple(self._inflight), return_exceptions=True)
        # 全部收尾后清掉活动标记：`run_forever` 退出前不留"永久置位"的标记
        # （否则下一次 `run_forever` 会以为一开始就有任务在飞）。
        self._any_task_active.clear()


async def _dissolve_task(task: asyncio.Task[None] | None) -> None:
    """取消一个 task 并**等它真的结束**（`None` 与已结束的 task 都是空操作）。

    两件事都必须做，缺一个都会留下问题：

    - **`cancel()` 之后 MUST `await`**：不 await 的话，本协程可能在处理器还没响应取消时
      就返回了（协程仍在事件循环上跑），而取消产生的 `CancelledError` 也没人接收；
    - **吞掉 `CancelledError`**：本函数是"清理"动作，不该把它传播给调用方
      （调用方若正处在"外部取消"路径上，会自己 `raise`）。

    **它取消不掉已经交给线程的工作**：处理器若把活放进了 `run_cpu_bound`，
    那个线程会继续跑到结束（Python 不能安全强杀线程）。这一点写在类 docstring 的
    §二之二 表格里，MUST NOT 在任何地方写成"副作用已回滚"。
    """
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def cpu_pool(max_workers: int) -> ThreadPoolExecutor:
    """建**专用** CPU 池（线程名带 `CPU_THREAD_PREFIX`，便于用例与排障辨认）。

    **为什么必须专用而不是用事件循环的默认执行器**：见模块 docstring §一。
    `thread_name_prefix` 让 `threading.current_thread().name` 形如 `aicore-cpu_0`，
    于是「这次图像解码跑在哪个池里」在日志与用例里都是**可判定的**，
    而不是靠「反正它不在主线程」这种弱断言。

    `max_workers` 由调用方给（`TaskRunner` 用 `config.concurrency_limit`）：
    池容量与并发额度一致，避免出现「信号量放行 4 个、池里只有 2 个线程」的排队。
    """
    return ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=CPU_THREAD_PREFIX,
    )


async def run_cpu_bound[U](fn: Callable[[], U], *, executor: Executor) -> U:
    """把 **CPU 密集** 的同步函数放到 `executor` 执行，返回其结果。

    **零参可调用**（`functools.partial` 由调用方负责）：这样签名只有一个类型参数，
    不必引入 `ParamSpec`；本服务的 CPU 密集点（图像解码、脱敏、哈希）本来就要先绑定参数。

    **`executor` 必须显式传入，MUST NOT 有默认值**：默认值会让「用了哪个池」变成隐式事实，
    而设计文档要求两类工作**分开**——
    「图像解码、脱敏处理、哈希与存证计算走 `run_in_executor`」（`design.md:200-206`）
    与「MySQL 访问走线程池」（同表 L203）是**CPU 密集 vs 阻塞 I/O** 两类，
    混在一个池里时一次图像解码会占住 MySQL 查询要用的线程。
    强制显式传入，使「谁在用哪个池」在每一处调用点都看得见。

    **重活的判定范围**（工单 §2.5b 逐字要求写进 docstring）：本函数只提供**机制**
    （把函数放出去执行），**不判定**「什么算 CPU 密集」——那由调用方决定。
    把判定写进本层会让「哪些工作该下池」散进 `core`，而调用方才是知道
    「这次解码多大、这次哈希多长」的那一层。

    **实现用 `loop.run_in_executor`**：它与 `design.md:204` 逐字要求的 `run_in_executor`
    是同一件设施，故「文档要求的东西在代码的哪里」不需要额外解释。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(_invoke, fn))


def _invoke[U](fn: Callable[[], U]) -> U:
    """把零参可调用**单独包一层**再交给执行器。

    `partial(_invoke, fn)` 与直接传 `fn` 行为等价，但这一层让「交给执行器的东西一定是
    零参可调用」在类型上成立：`run_in_executor` 的签名收 `Callable[..., _T]`，
    直接传 `fn` 时 mypy 会把返回类型推断落到 `object`；`partial` 包一层后
    `Callable[[], U]` 原样传递，`U` 在 `run_cpu_bound` 的调用点被绑定。

    用 PEP 695 的 `[U]` 而不是模块级 `TypeVar`（ruff UP047 的口径，本仓库
    `target-version = py312` 且运行在 3.14 上，语法可用）：
    私有工具函数各自绑定类型参数，不往模块命名空间里塞一个只为它存在的名字。
    """
    return fn()
