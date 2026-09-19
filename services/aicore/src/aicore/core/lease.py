"""租约锁：`LockStore` Protocol + 内存实现 + Redis 实现（Task 4.7）。

**权威依据**：`design.md` L208（`SET key value NX PX <leaseMs>` 原子领取、续期由心跳完成、
**续期失败必须主动放弃任务**）、`design.md` L210（失败按指数退避重试）、
`design.md` L212（实例内并发度由信号量封顶）；`er.md` §6.1（`ai_task` 没有 attempts 列，
故尝试计数只能落 Redis）；`services/aicore/docs/er.md` §7.1（状态机）。

## 一、这份协议解决什么

执行器要在**多实例并行**下「同一个任务只被一个实例处理」。事实源是 MySQL 的 `ai_task`
（`design.md` D2），但 MySQL 行锁不适合做**长事务**租约——一次 OCR 要几秒到几十秒，
把行锁拿着跨整个处理过程会让并发退化成串行。故租约落在 Redis：
`SET key value NX PX <leaseMs>` 一条命令同时表达「键不存在才写」与「到期自动消失」，
到期未被续期即被其它实例回收（`design.md` L208）。

## 二、MUST 用 Lua，MUST NOT 用多条命令拼（实测理由）

控制者已在**真实 Redis 8.0.5** 上实测两条关键语义（原始输出见工单 §2.2）：

1. **裸 `SET k v NX PX ms` 只能表达「键不存在则设置」，不能同时把尝试计数 +1**。
   而超额判据是「领取次数 > `max_retries`」（`ai_task` 没有 attempts 列），
   故「领取」与「计数」必须是一次原子操作——否则两个实例会各自 SET 成功、各自读到同一个 `n`。
2. **`SET k v XX PX ms` 不校验 owner**（`redis-py` 的 `renamenx` 签名里**也没有** `px`），
   故**续期绝不能用它**：任何实例都能续期别人的租约，那正是 `design.md:208` 要防的
   「两个实例同时处理同一任务」（重复调用付费通道，产生真实费用）。

两条都只能由 Lua 承担。四段脚本见模块底部的 `_ACQUIRE_LUA` / `_RENEW_LUA` /
`_RELEASE_LUA` / `_DEFER_LUA`，注册一律走 `client.register_script(...)`
（MUST NOT 用 `eval` 拼字符串：拼串会让脚本内容与参数在日志/异常里混在一起）。

## 三、过期的**唯一判据**是 Redis 的 `PX`

`design.md` L208 的租约语义由 **Redis 的键过期**承担（`InMemoryLockStore` 用注入时钟模拟），
本模块 **MUST NOT** 在应用侧再维护一份「过期时间表」——两份时间源必然漂移，
而漂移的表现恰好是「两个实例都认为自己是 owner」，即本协议要防的那件事。
故 `is_deferred` / `acquire` / `renew` / `release` 的每一个判定都只读键的**当前存在性**。

## 四、退避是**独立状态**，不靠「租约还没过期」表达

`defer(task_id, delay_s=...)` 写的是**第三个键**（退避键，带 `PX`），与租约键分离。
理由：退避期间租约应当已经释放/过期（否则别人也领不到，退避就成了「占着茅坑」），
故「等待期」必须能独立于租约存在；到期后键自动消失，任务重新可见
（`acquire` 的第一行就是检查该键）。这样退避**不需要给 `ai_task` 加列**
（`er.md` §6.1 的列清单里没有它，也不该有：它是执行侧的瞬态，不是事实源的一部分）。

## 五、`StepClock` 是**刻意的重复声明**（MUST NOT 改成复用 `provider/guard.py`）

本文件的 `StepClock` / `system_clock()` 与 `provider/guard.py` 的同名物**逐字同形但彼此独立**。
这不是疏漏：`.importlinter` **契约 4**（`core 不得依赖任何业务层`）的 forbidden 列表
**含 `aicore.provider` 整包**，且该契约**未开 `allow_indirect_imports`**——
`core/lease.py` 一旦 `from aicore.provider.guard import StepClock`，契约当场 BROKEN。
两个 Protocol 各自独立是**结构子类型**（structural subtyping）的正常用法：
调用方传任何同时具备 `monotonic()` 与 `async sleep()` 的对象都能用，
故 `provider/guard.py` 的假时钟可以直接注入 `InMemoryLockStore`（用例里正是这么做的），
不需要继承、也不需要共享基类。**重复的代价（两份声明可能漂移）已经用「接口极小」压到最低**：
两个成员、共两行，且两边的语义逐字相同（单调读数 + 可注入睡眠）。

## 六、本模块的依赖面（契约 4）

只 import `aicore.core.*` 与 stdlib，外加三方包 `redis.asyncio`
（三方包不在分层契约的管辖范围内，工单 §4 明示允许）。
MUST NOT import `aicore.provider` / `aicore.service` / `aicore.repository` / `aicore.port`。

## 七、入参拒绝面：**两个实现同判**（F9）

`LockStore` 是交付契约，而"单测绿、生产抛"是这几轮反复出现的形态，故替身 MUST NOT
比真 Redis 宽松。真 Redis 实测会拒绝的值，两侧都用**同一个函数 + 同一个异常类型**拒绝：

| 输入 | 真 Redis | 本模块两侧的处置 |
|---|---|---|
| `acquire(lease_ms=0 / -5)` | `invalid expire time` | `InvalidLeaseArgumentError` |
| `acquire(lease_ms=1000.5)` | `value is not an integer` | 同上 |
| `renew(lease_ms<=0 / 小数)` | `PEXPIRE 0` **删键** / `-5` 报错 | 同上 |
| `defer`，`int(s*1000) == 0` | `PX 0` 报错 | 按"不退避"处置（不写键 + 清旧的） |
| `defer(delay_s=1.9999)` | 实际退避 **1998ms** | `_defer_delay_ms` 截断到整毫秒，两侧一致 |

生产调用点**今天都不可达**（`Settings.lease_ms ge=1`、执行器退避下界 1.0s）——
不构成不修的理由（见上）。跨实现一致性用例（`tests/integration/test_lease_redis.py`）
把**同一组输入**喂两侧并断言同判。

### 已接受差异：过期边界的比较符（F9(b)）

真 Redis 判"键过期"用的是 `now > when`，替身用 `now >= expires_at`（`live_lease` /
`purge_expired` / `live_attempt_counter` 三处都是 `>=`）。实测最大差 **1ms**。
**本模块选择 `>=` 并把它登记为已接受差异**，理由：替身的时间由注入时钟驱动，
用例要求「`advance(lease_ms/1000)` 恰好让租约过期」可判定；改成 `>` 会让"恰好推进一个租期"
落在边界之外，于是每个用例都得再加一点点余量——那正是本模块其它地方一直在消灭的东西。
"1ms 内谁先认为过期"不影响协议语义：两个实例之间的回收竞争本来就要靠 `SET NX` 决出胜负。
"""

from __future__ import annotations

import asyncio
import math
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final, Protocol

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

__all__ = [
    "LEASE_KEY_PREFIX",
    "AttemptCounter",
    "InMemoryLockStore",
    "InMemoryState",
    "InvalidLeaseArgumentError",
    "LeaseToken",
    "LockStore",
    "RedisLockStore",
    "StepClock",
    "TaskClaim",
    "attempt_count_key",
    "defer_key",
    "lease_key",
    "system_clock",
]

#: 租约键的默认前缀。三个键（租约 / 尝试计数 / 退避）共用它，
#: 「同一个 task_id 的三类键」因此可被一次 `SCAN <prefix>*` 找全
#: ——集成夹具的清理（MUST NOT `FLUSHDB`）正是靠这一点。
LEASE_KEY_PREFIX: Final = "aicore:lease:"

#: 每秒多少毫秒（`delay_s` 是秒、`PX` 收毫秒，换算只在这一处做）。
_MS_PER_SECOND: Final = 1000.0

#: 尝试计数键的默认存活时长：24 小时。
#:
#: **口径说明（本模块的 `Final` 常量，不是 `Settings` 字段）**：设计文档没有给数值，
#: 而「尝试计数保留多久」是**执行侧的瞬态策略**而不是部署护栏，故按工单 §2.4 的处置
#: 写成模块常量并在此注明「未定档」。取 24h 的理由：它必须**远大于**任一任务的
#: 最大处理时长（否则计数会在任务重试期间过期，超额判据退化成「永远第 1 次」、
#: 无限重试），同时又不是永久（否则 Redis 会为每个历史任务永久留一个键）。
#: 按退避序列 1s→2s→4s（`max_retries=3`）算，一个任务的全部尝试在 1 分钟内跑完，
#: 24h 是三个数量级以上的余量。
DEFAULT_ATTEMPT_COUNT_TTL_MS: Final = 24 * 60 * 60 * 1000

#: 每次领取生成的新 token（owner 身份 + 唯一性）。同一 task 的两次领取 token 必然不同。
LeaseToken = str


class StepClock(Protocol):
    """可注入时钟（**本文件独立声明**，理由见模块 docstring §5）。

    两个成员分工与 `provider/guard.py` 的同名 Protocol **逐字相同**：

    - `monotonic()`：单调读数（**MUST 单调**：墙钟会因 NTP 校时回拨，
      回拨会让「刚建立的租约」看起来已经过期，于是两个实例同时认为自己持有租约）；
    - `sleep()`：等待的**唯一**入口。执行器的轮询等待 MUST 走它，
      否则用例只能真等 `poll_interval_s`（`tests/conftest.py` 文件头逐字禁止）。
    """

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class _SystemClock:
    """`system_clock()` 的实现（生产用；测试 MUST 注入假时钟）。"""

    __slots__ = ()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def system_clock() -> StepClock:
    """生产时钟：`time.monotonic()` + `asyncio.sleep`。

    **本文件独立声明**（与 `provider/guard.py` 的同名物逐字同形但彼此独立，
    理由见模块 docstring §5：契约 4 禁止 `core` 依赖 `aicore.provider` 整包）。
    """
    return _SystemClock()


@dataclass(frozen=True, slots=True)
class TaskClaim:
    """一次成功的领取：谁（`token`）领到了哪个任务（`task_id`）、这是第几次（`attempt`）。

    `frozen=True` + `slots=True` 是硬要求（同 `service/task/registry.py` 的 `TaskPolicy`）：
    领取凭据是**共享事实**，就地改写会让「续期用哪个 token」与「释放用哪个 token」
    在不同调用点取到不同的值——而那正是「两个实例都认为自己是 owner」的另一种形态。
    """

    task_id: str
    token: LeaseToken
    #: 第几次领取（**从 1 起**）。判据：`attempt > max_retries` 即超限（工单 §2.4）。
    #: 语义是「**领取**次数」而不是「失败次数」：领了但进程崩了同样消耗一次尝试，
    #: 否则一个必然导致崩溃的任务会被无限重试（每次都在 `attempt=1` 上崩）。
    attempt: int


class LockStore(Protocol):
    """租约的原子领取 / 续期 / 释放 / 退避（结构子类型，两个实现见本模块）。

    **全部方法是 `async def`**：Redis 实现本来就是异步的；内存实现也写成 `async def`
    以便两者可互换（结构子类型要求形状一致，`async def` 与 `def` 返回协程的差别不能靠适配器抹平）。
    """

    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        """原子领取：成功返回 `TaskClaim`，键已被占用 / 处于退避期则返回 `None`。

        **MUST NOT 阻塞等待**：它是「试一次」，不是「排队等到拿住为止」。
        执行器对 `None` 的处置是**试下一个任务**（工单 §2.5 硬约束 1），
        而不是重试同一个——重试同一个会在别的实例正在处理时白烧一轮轮询。
        """
        ...

    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        """续期。**仅当键仍归本 token 所有**时成功；否则返回 `False`（调用方据此放弃任务）。

        返回 `False` 的两种情形都不区分：键已过期（被别人或自然回收），
        或键被**别人**持有（自己已失去所有权）。两者的处置相同——**主动放弃**
        （`design.md:208`），故不提供更细的返回类型：多一个分支就多一处可能被写错的地方。
        """
        ...

    async def release(self, claim: TaskClaim) -> bool:
        """主动释放（任务结束）。**仅当仍归本 token 所有**时删除；否则返回 `False` 且不动键。"""
        ...

    async def is_deferred(self, task_id: str) -> bool:
        """是否处于**退避等待期**（见模块 docstring §四）。

        **只读**：MUST NOT 有副作用（用例连调两次断言结果一致，且不改变可领取性）。
        """
        ...

    async def defer(self, task_id: str, *, delay_s: float) -> None:
        """把任务置入退避等待期：`delay_s` 秒内 `acquire` 必须失败。

        **非正 / 非有限的 `delay_s` = 不退避**（不写键、并清掉已有的退避键）：
        两个实现共用这一口径（理由见 `InMemoryLockStore.defer` 的 docstring）——
        真 Redis 无法表达"一个立即到期的键"（`PX 0` 是错误），
        「不写键」才是"不等待"的可实现形态。生产调用点只传
        `BACKOFF_BASE_S * 2 ** (attempt - 1) >= 1.0`，故这一档今天只服务契约的完备性。
        """
        ...

    async def close(self) -> None:
        """释放连接等资源（内存实现是空操作；Redis 实现关闭客户端）。"""
        ...


# ---------------------------------------------------------------------------
# 三类键的构造：**一份实现**，内存与 Redis 实现共用
#
# 共用不是为了省几行：两份键名一旦漂移，内存实现与 Redis 实现就不再是「同一个协议的两个
# 实现」，而用例会在内存实现上全绿、在真实 Redis 上打不到同一个键（假绿的一种）。
# ---------------------------------------------------------------------------
def lease_key(task_id: str, *, prefix: str = LEASE_KEY_PREFIX) -> str:
    """租约键：`<prefix><task_id>:lease`（`SET NX PX` 的目标）。"""
    return f"{prefix}{task_id}:lease"


def attempt_count_key(task_id: str, *, prefix: str = LEASE_KEY_PREFIX) -> str:
    """尝试计数键：`<prefix><task_id>:attempts`（`INCR` 的目标，见模块 docstring §二）。"""
    return f"{prefix}{task_id}:attempts"


def defer_key(task_id: str, *, prefix: str = LEASE_KEY_PREFIX) -> str:
    """退避键：`<prefix><task_id>:defer`（带 `PX` 写、到期自动消失，见模块 docstring §四）。"""
    return f"{prefix}{task_id}:defer"


def _require_positive_count_ttl(attempt_count_ttl_ms: int) -> int:
    """计数键存活时长的构造期校验：`<= 0` 一律**拒绝**（A3 的同族问题）。

    为什么必须拒绝而不是钳到一个值：真 Redis 的 `PEXPIRE key 0` 会**直接删键**
    （评审实测 `PEXPIRE 0 -> True | exists after = 0`），于是"计数只在首次 PEXPIRE"
    的口径下**每次领取都从 1 重来**——`attempt > max_retries` 这条超额判据被**静默关掉**，
    表现是「一个必然失败的任务被无限重试」（每次都可能在重放付费通道）。
    一个能静默关掉护栏的参数值不该被"温和地钳掉"：钳掉之后调用方以为自己配了什么、
    实际配的是另一个值，而这类漂移正是本模块通篇在防的东西。

    抛 `ValueError` 而不是 `ParamError`：这是**装配期**的参数错误（`RedisLockStore` 的
    构造参数，由组合根给），不是请求参数——`ParamError` 是 400 语义，用在这里会把
    "服务端配错了"报成"调用方传错了"。
    """
    if attempt_count_ttl_ms <= 0:
        raise ValueError(
            f"attempt_count_ttl_ms 必须为正，收到 {attempt_count_ttl_ms}（毫秒）："
            f"`PEXPIRE key 0` 在 Redis 上会**删除计数键**，每次领取都从 1 重来，"
            f"`attempt > max_retries` 的超额判据会被静默关掉 → 必然失败的任务被无限重试"
        )
    return attempt_count_ttl_ms


class InvalidLeaseArgumentError(ValueError):
    """入参是**真 Redis 会拒绝的值**（F9）：两个实现用同一个异常、同一个判据。

    ## 为什么要有这个类型（而不是让 Redis 自己报 `ResponseError`）

    工单 §F9 的实测：内存替身比真 Redis **宽松 4 处**，其中

    - `acquire(lease_ms=0 / -5)` → 真 Redis `invalid expire time`，替身照发租约并计数；
    - `acquire(lease_ms=1000.5)` → 真 Redis `value is not an integer`，替身照发。

    若只在 Redis 侧重抛 `redis.exceptions.ResponseError`，两侧的**判据**就成了两个类型，
    而"同一组输入喂两侧、断言同判"这条一致性用例正是要钉住的东西。
    故两侧都在**发命令之前**用同一段校验（`_require_lease_ms`）拒绝**同一组**值，
    抛同一个异常类型。

    ## 为什么继承 `ValueError`

    这是**调用方把参数传错了**（不是服务端装配错误，也不是业务失败）：

    - 继承 `ValueError` 而不是 `AiCoreError`：`AiCoreError` 是被执行器按失败分流的业务错误，
      若让它落到那条路径上，一个编程错误会被写成"任务失败 + 重试/转人工"；
    - 不用 `ParamError`：那是 400 语义（HTTP 请求参数），会把"执行器内部传错"报成"调用方传错"。

    生产路径**今天不可达**（`Settings.lease_ms ge=1`、执行器的退避下界 1.0s），
    但 `LockStore` 是交付契约——"单测绿、生产抛"正是这几轮反复出现的形态，
    故按契约边界修，而不是按今天的可达性修。
    """


def _require_lease_ms(lease_ms: int) -> int:
    """`lease_ms` 必须是**正整数**（真 Redis 对 `PX` 的要求），否则抛 `InvalidLeaseArgumentError`。

    真 Redis 的实测口径（工单 §F9）：

    - `SET k v NX PX 0`（含负数）→ `invalid expire time in 'set' command`；
    - `PX 1000.5` → `value is not an integer or out of range`。

    第三类被拒的是 `bool`：`isinstance(True, int)` 为真，`lease_ms=True` 会被 `PX 1`
    悄悄接受成"1 毫秒的租约"——一个几乎立刻过期的租约看起来像"领取成功"，
    实际下一次 `renew` 就已经不是自己的了。这类"看起来成对的类型"必须显式挡掉。
    """
    if isinstance(lease_ms, bool) or not isinstance(lease_ms, int) or lease_ms <= 0:
        raise InvalidLeaseArgumentError(
            f"lease_ms 必须是正整数毫秒，收到 {lease_ms!r}"
            f"（{type(lease_ms).__name__}）：真 Redis 的 PX 会报 invalid expire time / "
            f"value is not an integer or out of range"
        )
    return lease_ms


def _defer_delay_ms(delay_s: float) -> int:
    """把 `delay_s` 折算成 `PX` 用的**整毫秒**（`<= 0` = 不该写这个键）。

    ## 截断口径必须两侧一致（F9 的第 4 处）

    真 Redis 收的是整数毫秒，故 `defer(delay_s=1.9999)` 实际退避 **1998ms 左右**；
    第一版的内存替身直接存 `clock + 1.9999` ⇒ 1999.9ms。差异只有 1~2ms，
    但"替身与真实现的口径不同"这件事本身必须消失——否则一致性用例测的是替身自己的定义。

    故本函数是**唯一**的折算处，两侧都调它，并把 `delay_ms / _MS_PER_SECOND` 作为内存侧的时长。

    ## 非正 / 非有限 → 返回 0（= "不写键"）

    - `int(delay_s * 1000) == 0`（即 `0 < delay_s < 0.001`）：真 Redis 的 `PX 0` 会**报错**，
      故两侧统一按"不退避"处置（调用方传这么小的值，意图就是"立刻可领"）；
    - `nan` / `inf`：真 Redis 会因为 `int(inf * 1000)` 抛 `OverflowError`；
      `nan` 更危险——旧实现里 `clock + nan` 的比较恒真，退避**永不结束**且没有任何报错。
      两者都归到"不写键"（最安全的解释是**别把任务锁死**）。
    """
    if not math.isfinite(delay_s):
        return 0
    return int(delay_s * _MS_PER_SECOND)


def _new_token() -> LeaseToken:
    """生成一次领取的 token。

    用 `secrets.token_hex(16)`（128 位随机）而不是「进程 id + 计数器」：
    多实例部署下两台机器的计数器会**同时从 1 开始**，于是「A 的第 3 次领取」与
    「B 的第 3 次领取」token 相同——`renew` 的所有权校验会把别人的租约当成自己的，
    正是本模块要防的重复处理。128 位随机让碰撞概率可忽略，且不引入新的依赖。
    """
    return secrets.token_hex(16)


@dataclass(slots=True)
class _Lease:
    """内存态的一条租约：owner token + 到期时刻（**注入时钟**的读数）。"""

    token: LeaseToken
    expires_at: float


@dataclass(slots=True)
class AttemptCounter:
    """尝试计数（内存态）：`n` = 领取次数，`expires_at` = 计数键的到期时刻。

    **它必须与租约分开存放**：租约过期/释放后计数仍在累加（否则超额判据永远不成立），
    见 `InMemoryState` 的 docstring。
    """

    n: int
    expires_at: float


class InMemoryState:
    """`InMemoryLockStore` 的**可共享**状态（三个键的字典 + 一个注入时钟）。

    ## 为什么状态要能共享（而不是每个 store 自己一份）

    工单 §3.1 第 3 条与第 7 条要求「**另一个 store 实例**能领取」与「尝试计数连续递增」。
    若每个实例各持一份状态，第二条就退化成「第二个实例第一次领取」——
    它证明不了租约回收，只证明了「两个互不相干的字典」。
    故状态可显式共享：同进程内多个 `InMemoryLockStore` 共享同一份状态，
    正好模拟「同一台 Redis 上的两个执行器实例」；每个用例**默认新建**一份状态，
    故用例之间零共享（与 `sandbox_engine` 夹具同一取向）。

    ## 计数为什么独立于租约（与 Redis 实现的 `PX` 一一对应）

    Redis 里租约键与计数键是两个键、生命周期独立：租约过期 → 键消失 → 别人可领；
    计数键活得更久 → `INCR` 继续累加。内存态因此把 `attempts` 与 `leases` 分开存，
    并给计数一个自己的 `expires_at`（对应 `PEXPIRE <count_ttl_ms>`）。
    把计数挂在租约对象上（或释放时清零）会让「超额转人工」永远不可达——
    一个必然失败的任务会被无限重排。

    ## 「过期」的判据只有一处

    三个读方法都调 `_purge` / `_live_lease`，判据恒为 `clock.monotonic() >= expires_at`。
    MUST NOT 另设「惰性过期 + 定时清理」两条路径：两条路径的判据一旦有一处写成 `>`、
    另一处写成 `>=`，边界上就会出现「一个实例认为已过期、另一个认为未过期」。
    """

    __slots__ = ("attempts", "clock", "deferrals", "leases")

    def __init__(self, clock: StepClock) -> None:
        self.clock = clock
        self.leases: dict[str, _Lease] = {}
        self.deferrals: dict[str, float] = {}
        self.attempts: dict[str, AttemptCounter] = {}

    def purge_expired(self) -> None:
        """清掉已过期的租约与退避（**惰性**：只在读写时调用，不另起清理任务）。

        「惰性」不影响正确性：所有判定都先 `purge` 再读，故过期项在**任何一次读取**上
        都不会被当成有效；它只影响内存占用，而这个键集的规模由活跃任务数决定。
        """
        now = self.clock.monotonic()
        for task_id, lease in list(self.leases.items()):
            if now >= lease.expires_at:
                del self.leases[task_id]
        for task_id, until in list(self.deferrals.items()):
            if now >= until:
                del self.deferrals[task_id]

    def live_lease(self, task_id: str) -> _Lease | None:
        """该任务当前**有效**的租约（过期即视为不存在，并把过期项清掉）。"""
        lease = self.leases.get(task_id)
        if lease is None:
            return None
        if self.clock.monotonic() >= lease.expires_at:
            del self.leases[task_id]
            return None
        return lease

    def live_attempt_counter(self, task_id: str) -> AttemptCounter | None:
        """该任务当前的尝试计数（计数键到期即视为不存在，与 Redis 的 `PEXPIRE` 同义）。"""
        counter = self.attempts.get(task_id)
        if counter is None:
            return None
        if self.clock.monotonic() >= counter.expires_at:
            del self.attempts[task_id]
            return None
        return counter


class InMemoryLockStore:
    """确定性、无 IO 的 `LockStore`（供默认段用例；内部按**注入时钟**判过期）。

    ## 它与 Redis 实现的语义对应表（逐条，便于评审核对）

    | 语义 | Redis | 本类 |
    |---|---|---|
    | 租约键占用 | `SET NX PX` 失败 | `leases` 里有未过期项 |
    | 租约到期 | `PX` 自动删除 | `expires_at <= clock.monotonic()`（见 §七） |
    | 尝试计数 | `INCR` + 首次 `PEXPIRE` | `AttemptCounter.n += 1`（到期同上） |
    | 退避期 | 退避键存在 | `deferrals` 里有未到期项（按整毫秒截断） |
    | token 校验 | Lua 里 `GET == ARGV[1]` | `_Lease.token == claim.token` |
    | **非法入参** | `PX <= 0` / 小数毫秒报错 | `InvalidLeaseArgumentError`（同一个校验函数） |

    ## 边界（如实登记）：本类**不**校验 `token` 的唯一性

    token 由 `_new_token()` 生成，本类只做**相等比较**。故「两个实例拿到同一个 token」
    这种故障在内存实现里**不会被发现**（真实 Redis 上同样不会被发现——它也只比较相等）。
    这是刻意的：本类的职责是复现**协议语义**，不是替随机数发生器做质量检测。
    """

    __slots__ = ("_count_ttl_ms", "_prefix", "_state")

    def __init__(
        self,
        *,
        clock: StepClock | None = None,
        state: InMemoryState | None = None,
        prefix: str = LEASE_KEY_PREFIX,
        attempt_count_ttl_ms: int = DEFAULT_ATTEMPT_COUNT_TTL_MS,
    ) -> None:
        """`state` 显式传入即与别的实例共享同一份键空间（见 `InMemoryState` 的 docstring）。"""
        active_clock: StepClock = system_clock() if clock is None else clock
        self._state = InMemoryState(active_clock) if state is None else state
        self._prefix = prefix
        self._count_ttl_ms = _require_positive_count_ttl(attempt_count_ttl_ms)

    @property
    def state(self) -> InMemoryState:
        """本实例的键空间（共享时即传入的那一份）。供用例检查键名与残留。"""
        return self._state

    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        """原子领取。检查与写入之间**没有 `await`**，故在 asyncio 单线程下天然原子
        （这正是 Redis 那段 Lua 脚本的等价物）。

        `lease_ms` 先过 `_require_lease_ms`（F9）：真 Redis 会拒绝 `PX <= 0` 与小数，
        替身 MUST NOT 反而照发一个立刻过期的租约——"替身比真实现宽松"是最坏的一类替身，
        它让离线段全绿而生产段一启动就抛。
        """
        lease_ms = _require_lease_ms(lease_ms)
        self._state.purge_expired()
        if task_id in self._state.deferrals:
            return None
        if task_id in self._state.leases:
            return None
        token = _new_token()
        now = self._state.clock.monotonic()
        self._state.leases[task_id] = _Lease(
            token=token, expires_at=now + lease_ms / _MS_PER_SECOND
        )
        n = self._increment_attempts(task_id, now)
        return TaskClaim(task_id=task_id, token=token, attempt=n)

    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        """续期（**仅当仍归本 token 所有**）。

        `lease_ms` 同样过 `_require_lease_ms`：真 Redis 的 `PEXPIRE key 0` 会**删除**键
        （即"续期"变成"释放"），而 `PEXPIRE key -5` 报 `invalid expire time`。
        替身若不校验，就会把"续期失败"表现成"续期成功"（F9 的同族形态）。
        """
        lease_ms = _require_lease_ms(lease_ms)
        lease = self._state.live_lease(claim.task_id)
        if lease is None or lease.token != claim.token:
            return False
        lease.expires_at = self._state.clock.monotonic() + lease_ms / _MS_PER_SECOND
        return True

    async def release(self, claim: TaskClaim) -> bool:
        """释放（**仅当仍归本 token 所有**）。"""
        lease = self._state.live_lease(claim.task_id)
        if lease is None or lease.token != claim.token:
            return False
        del self._state.leases[claim.task_id]
        return True

    async def is_deferred(self, task_id: str) -> bool:
        """是否处于退避等待期（**只读**：只调 `purge_expired`，不写任何键）。"""
        self._state.purge_expired()
        return task_id in self._state.deferrals

    async def defer(self, task_id: str, *, delay_s: float) -> None:
        """置入退避等待期；`delay_s` 非正（或非有限）时**不写退避键**（见下）。

        ## 口径：非正的 `delay_s` = **不退避**，而不是"写一个立即到期的键"（A4）

        工单原先在这里写「`delay_s <= 0` 按『不等待』处理（写一个立即到期的键）」，
        **真 Redis 做不到那件事**：`SET k v PX 0` 直接报
        `ResponseError: invalid expire time in 'set' command`（评审实测）。
        故三处口径统一到**一个可实现的行为**：`delay_s` 非正 → **直接不写键**
        （`acquire` 立刻可领，语义上就是"不等待"），与真实现的"跳过一次 `SET`"逐字一致。

        `nan` / `inf` 也归到同一档：`nan` 在旧实现里会被算成"永不结束的退避"
        （`clock + nan` 的比较恒真），那是**比不等待危险得多**的行为
        （任务被永久挡住且没有任何报错）。`inf` 同理——真 Redis 会因为
        `int(inf * 1000)` 抛 `OverflowError`。两者都按"不退避"处理，
        因为"调用方传了非法时长"最安全的解释是**别把任务锁死**。

        ## 折算成整毫秒（F9 的第 3、4 处）

        `0 < delay_s < 0.001` 时 `int(delay_s * 1000) == 0`，真 Redis 的 `PX 0` **报错**
        ——归到"不写键"那一档；`delay_s = 1.9999` 时真 Redis 退避 **1998ms**，
        替身此前退避 1999.9ms。两处都由 `_defer_delay_ms` 统一（两侧同一个折算函数）。
        """
        self._state.purge_expired()
        delay_ms = _defer_delay_ms(delay_s)
        if delay_ms <= 0:
            # 非正/过短/非有限：**清除**已有的退避（若上一步设过），并返回。
            # 「清除」而不是"什么都不做"：调用方传 0 的意图是"现在就能领"，
            # 若残留着更早设的退避窗口，那个意图就没被实现。
            self._state.deferrals.pop(task_id, None)
            return
        # **按毫秒截断后再折算回秒**：与真 Redis 的 `PX <int ms>` 逐字同口径。
        self._state.deferrals[task_id] = (
            self._state.clock.monotonic() + delay_ms / _MS_PER_SECOND
        )

    async def close(self) -> None:
        """内存实现没有连接可关（**幂等**，MUST NOT 清键：清键不等于关连接）。"""

    def _increment_attempts(self, task_id: str, now: float) -> int:
        """尝试计数 +1；计数键不存在则从 1 起并设置自己的存活时长。

        **每次都刷新 TTL**（与工单 §2.2 的参考脚本「仅首次 `PEXPIRE`」有意不同）：
        刷新让计数键的存活期从**最后一次领取**起算，语义是「这个任务最近还在被尝试」；
        仅首次设置时，存活期从**第一次领取**起算，一个被反复重排的长任务可能在
        自己的重试途中把计数丢掉（表现：超额判据突然归零 → 无限重试）。
        两种口径在正常量级下都会先于任务生命周期到期，故差别只在长任务上，
        而长任务正是最需要计数不丢的那一类。集成用例对计数**连续累加**有直接断言。

        ## 读计数走 `live_attempt_counter`（A3 的修复点）

        第一版直接 `self._state.attempts.get(...)`，**绕过了**按 `expires_at` 判过期的方法，
        于是内存侧"计数永不到期"（实测：同一 TTL 下真 Redis 给 `[1,1,1]`、替身给 `[1,2,3]`）
        ——离线段 10 条单测在这一点上与生产不一致，而那正是最需要一致的地方
        （计数丢失 → 超额判据归零 → 无限重试）。`live_attempt_counter` 是唯一按
        `expires_at` 判过期的方法，现在它是**唯一**的读取入口。
        """
        counter = self._state.live_attempt_counter(task_id)
        n = 1 if counter is None else counter.n + 1
        self._state.attempts[task_id] = AttemptCounter(
            n=n, expires_at=now + self._count_ttl_ms / _MS_PER_SECOND
        )
        return n


# ---------------------------------------------------------------------------
# Lua 脚本（四段）。控制者已在真实 Redis 8.0.5 上跑通 acquire / renew 两段，
# 关键语义：`SET ... NX` 在键已存在时返回 **false**（Lua 的 false，不是 nil）。
# ---------------------------------------------------------------------------

#: 领取：退避中不可领；`SET NX PX` 抢租约；抢到后 `INCR` 计数。
#: KEYS[1] 租约键 / KEYS[2] 尝试计数键 / KEYS[3] 退避键
#: ARGV[1] token / ARGV[2] lease_ms / ARGV[3] count_ttl_ms
#: 返回：0 = 没抢到（退避中或已被占）；>= 1 = 抢到了，值是**尝试序号**。
_ACQUIRE_LUA: Final = """
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) == false then return 0 end
local n = redis.call('INCR', KEYS[2])
redis.call('PEXPIRE', KEYS[2], ARGV[3])
return n
"""

#: 续期：**先校验 owner**（这是 MUST 用 Lua 的唯一理由，见模块 docstring §二）。
#: KEYS[1] 租约键 / ARGV[1] token / ARGV[2] lease_ms
#: 返回：1 = 续期成功；0 = 键已不在（过期或已释放）或 token 不匹配。
_RENEW_LUA: Final = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
"""

#: 释放：**先校验 owner 再 DEL**（同样不能用裸 `DEL`：那会删掉别人的租约）。
#: KEYS[1] 租约键 / ARGV[1] token
#: 返回：1 = 已释放；0 = 键已不在或 token 不匹配（两种情况处置相同，故不区分）。
_RELEASE_LUA: Final = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""

#: 退避：写退避键（带 `PX`，到期自动消失 → 任务重新可见）。
#: KEYS[1] 退避键 / ARGV[1] delay_ms
#: 返回：1（恒成功；`delay_ms` 已被 Python 侧钳到 >= 0）。
_DEFER_LUA: Final = """
redis.call('SET', KEYS[1], '1', 'PX', ARGV[1])
return 1
"""


class RedisLockStore:
    """真实实现（`redis.asyncio`）：四段 Lua 脚本 + 三个键（见模块 docstring §二/§四）。

    ## 构造**不连接**（与 `EngineFactory` 同一取向）

    `redis.asyncio.Redis` 是惰性的：第一条命令才建连接。故「Redis 地址配错」不会在
    构造期变成一次网络等待（那会让配置错误看起来像启动慢）；连不上时，
    **第一条命令**抛错——而执行器对 `claim_once` 的抛错口径是 **fail fast**
    （工单 §3.5 第 31 条：MUST NOT 吞掉，MUST NOT 假装成功）。

    ## 本类**没有** `clock` 形参（A9：与 `TaskRunner(clock=)` 同族，一起清掉）

    工单 §2.1 曾要求两个实现同形（含 `clock`），但那个形参在本类里**从未被读**：
    它只喂给 `monotonic_now()` 这个诊断入口，而**全仓没有任何调用者**。
    而 Redis 实现的**过期判据唯一**是服务端的 `PX`（见模块 docstring §三）——
    本类 MUST NOT 用本地时钟去判"租约到期没到期"，那正是两份时间源漂移的入口。
    一个"注入了却没被读"的时钟是**会骗人的接缝**（调用方以为控制了时间），故删掉它。
    `InMemoryLockStore` 保留 `clock`：那里它是**真的**判据（模拟 `PX`）。

    ## 客户端参数里刻意不设 `decode_responses=True`

    Lua 的返回值是整数（`redis.call` 的整数回复），`decode_responses` 只影响字符串回复；
    两处取返回值都用 `int(...)` 归一（`int(b"3")` 与 `int(3)` 都成立），
    故不依赖那个全局开关——它与「脚本返回值到底是 bytes 还是 int」无关，
    设上只会让将来读别的键时多一层隐式解码。

    ## 为什么 Redis 客户端**显式不自动重试**（N1，产品行为决定）

    redis-py 8.1.0 的默认值是 `Retry(ExponentialWithJitterBackoff(base=1, cap=10), retries=10)`
    ——**一次调用内部最多重试 10 次**。实测（复核者）：裸 `Redis(port=1).ping()` 要 **26.0s**
    才把连接错误抛出来，而 `test_unreachable_redis_fails_fast_without_touching_the_row`
    一条用例就占了集成段的 **25.18s / 50.10s**。

    这不只是慢：它把 **26 秒的长尾藏进一次"看起来很快"的调用**里——
    而那正是 **A2 刚消灭掉的形态**（A2 就是"一次瞬时错误不该杀死轮询循环"，
    改法是给 `run_forever` 加**有界退避**）。上游已经有分层处置：

    | 路径 | 上游处置 |
    |---|---|
    | `claim_once` 抛错 | `run_forever` 记 ERROR + **有界**退避（0.5s → 上限 30s） |
    | `renew` 抛错 | 心跳记 WARNING + **放弃执行**（`design.md:208`） |

    两处都**已经**在没有重试的前提下正确工作，故客户端再叠 10 次重试只是把
    同一个抖动放大成 26 秒的不可观测等待。

    **代价（如实登记）**：Redis 的一次瞬时抖动现在会立刻冒到执行器，表现为
    一条 ERROR/WARNING 日志 + 一次有界退避（原先它可能被客户端内部悄悄重试掉）。
    即"更早、更响、但更快恢复"，而不是"少一次错误日志"。
    这也是**产品行为**的改动，已单列在修复报告里。
    """

    __slots__ = ("_client", "_count_ttl_ms", "_prefix", "_scripts")

    def __init__(
        self,
        *,
        host: str,
        port: int,
        db: int,
        prefix: str = LEASE_KEY_PREFIX,
        attempt_count_ttl_ms: int = DEFAULT_ATTEMPT_COUNT_TTL_MS,
    ) -> None:
        self._client: Redis = Redis(
            host=host,
            port=port,
            db=db,
            # 显式不重试（`NoBackoff` + 0 次）：理由见类 docstring 的 N1 一节。
            retry=Retry(NoBackoff(), 0),
        )
        self._prefix = prefix
        self._count_ttl_ms = _require_positive_count_ttl(attempt_count_ttl_ms)
        self._scripts: dict[str, Any] = {}

    @property
    def client(self) -> Redis:
        """底层客户端（供排障与集成用例读 `PTTL` 这类原始事实）。"""
        return self._client

    @property
    def prefix(self) -> str:
        """本实例使用的键前缀（集成用例要按它现算键名读 `PTTL`；生产装配用默认值）。"""
        return self._prefix

    # ---- `LockStore` 协议 ----
    async def acquire(self, task_id: str, *, lease_ms: int) -> TaskClaim | None:
        """原子领取：退避中或已被占 → `None`；否则返回带**尝试序号**的 `TaskClaim`。

        `lease_ms` 先过 `_require_lease_ms`（F9）：真 Redis 本来就会因 `PX <= 0` /
        小数毫秒报错，提前在 Python 侧拒绝让**两侧的判据是同一个异常类型**
        （一致性用例要断言"同判"），也省掉一次注定失败的往返。
        """
        lease_ms = _require_lease_ms(lease_ms)
        script = self._script("acquire", _ACQUIRE_LUA)
        token = _new_token()
        raw = await script(
            keys=[
                lease_key(task_id, prefix=self._prefix),
                attempt_count_key(task_id, prefix=self._prefix),
                defer_key(task_id, prefix=self._prefix),
            ],
            args=[token, lease_ms, self._count_ttl_ms],
        )
        attempt = int(raw)
        if attempt == 0:
            return None
        return TaskClaim(task_id=task_id, token=token, attempt=attempt)

    async def renew(self, claim: TaskClaim, *, lease_ms: int) -> bool:
        """续期：键仍归本 token 所有才成功（Lua 里 `GET == token` 的判据）。

        `lease_ms` 先过 `_require_lease_ms`（F9 的同族）：`PEXPIRE key 0` 在真 Redis 上
        会**删除**键（"续期"变成"释放"），`PEXPIRE key -5` 报 `invalid expire time`。
        """
        lease_ms = _require_lease_ms(lease_ms)
        script = self._script("renew", _RENEW_LUA)
        raw = await script(
            keys=[lease_key(claim.task_id, prefix=self._prefix)],
            args=[claim.token, lease_ms],
        )
        return int(raw) == 1

    async def release(self, claim: TaskClaim) -> bool:
        """释放：键仍归本 token 所有才删除。"""
        script = self._script("release", _RELEASE_LUA)
        raw = await script(
            keys=[lease_key(claim.task_id, prefix=self._prefix)],
            args=[claim.token],
        )
        return int(raw) == 1

    async def is_deferred(self, task_id: str) -> bool:
        """是否处于退避等待期（**只读**：`EXISTS`，无副作用）。"""
        return bool(await self._client.exists(defer_key(task_id, prefix=self._prefix)))

    async def defer(self, task_id: str, *, delay_s: float) -> None:
        """写退避键（带 `PX`）。

        **非正 / 非有限 / 折算后不足 1ms 的 `delay_s` → 不写键，并清掉已有的退避键**（A4 + F9）：
        与 `InMemoryLockStore.defer` 同一口径（那边有完整的理由说明）。
        真 Redis 的 `SET k v PX 0` 会报 `invalid expire time`，
        故"写一个立即到期的键"这条路**走不通**；改为"不写 + 清掉旧的"，
        语义等价（任务立刻可领），且与替身逐字一致。
        折算走 `_defer_delay_ms`（**同一个**函数），故 `defer(1.9999)` 在两侧都是 1998ms。
        """
        key = defer_key(task_id, prefix=self._prefix)
        delay_ms = _defer_delay_ms(delay_s)
        if delay_ms <= 0:
            await self._client.delete(key)
            return
        script = self._script("defer", _DEFER_LUA)
        await script(keys=[key], args=[delay_ms])

    async def close(self) -> None:
        """关闭客户端（`aclose()`；**幂等**：重复调用安全）。"""
        await self._client.aclose()

    def _script(self, name: str, source: str) -> Any:
        """取（必要时注册）一段脚本。

        `register_script` 返回可调用对象，首次调用时自动 `EVALSHA`、必要时回落 `EVAL`
        （`NoScriptError` 时 redis-py 自己重发脚本）。故进程重启后无需预热。
        """
        script = self._scripts.get(name)
        if script is None:
            script = self._client.register_script(source)
            self._scripts[name] = script
        return script
