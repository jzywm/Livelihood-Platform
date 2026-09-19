"""`RedisLockStore` 的真实 Redis 用例（工单 §3.4 的三条，`@pytest.mark.integration`）。

**默认不跑**（`-m integration` 才执行）；连不上 Redis 时夹具**显式 skip 并说明**
（`tests/conftest.py` 的 `redis_is_available()`），MUST NOT 静默通过。

## 与默认段的分工

| 关切 | 默认段 | 本文件 |
|---|---|---|
| 协议语义（谁持有、过期后能否回收、退避窗口） | `tests/unit/test_lease.py`（注入时钟，零 IO） | — |
| **真实 Redis 的原子性**（两条连接并发抢同一把锁） | **不可替代** | 第 27 条 |
| **真实 `PX` 语义**（`PTTL` 与到点回收） | 模拟（注入时钟） | 第 28 条 |

## 关于真等待（本文件两处，逐处写明）

工单 §3.4 第 28 条逐字允许「**这里允许真等**，因为它是集成段；但等待时间 MUST ≤ 2s」
——真实 `PX` 的到期只能靠真实时间证明（注入时钟改不了 Redis 服务端的过期计时）。
本文件有**两处** `await asyncio.sleep`，都带 `# ai-allow-sleep: <理由>` 行级豁免
（验收脚本第 4 项的判据支持该豁免，理由必填）：

| 位置 | 用途 | 等待 |
|---|---|---|
| `test_lease_expires_and_becomes_claimable_again` | 真实 `PX` 到点回收 | 1.1s |
| `test_attempt_counter_expires_after_its_own_ttl` | 计数键自己的 TTL 到点 | 0.7s |

> 更正（本轮）：此处此前写"本文件**只有一处** `await asyncio.sleep`"，而实际是两处
> ——A3/A4 补上"计数键自己的 TTL"那条用例时漏改了这句话。

睡眠豁免：2 处（机械判据逐文件比对，见 `tests/structural/test_sleep_exemption_counts.py`）。

## 键前缀

每个用例用 `redis_prefix` 夹具给的 `aicore:test:<uuid>:`，用例结束由 `redis_client`
夹具按前缀清理（**MUST NOT `FLUSHDB`**：那会清掉同机其它测试的状态）。
`RedisLockStore.prefix` 是公开属性，故用例可以直接按它现算键名去读 `PTTL`。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from aicore.core.lease import (
    RedisLockStore,
    attempt_count_key,
    defer_key,
    lease_key,
)
from tests.conftest import redis_integration_target

pytestmark = pytest.mark.integration

#: 用例要的短租约（`PTTL` 断言与真等待都用它）。
LEASE_MS = 1000
#: 真等待的时长：比租约多 0.1s（最坏 1.1s，工单上限 2s）。
EXPIRY_WAIT_S = 1.1


def _task_id() -> str:
    """一个本用例专属的 task_id（形态与 `er.md` §5.4 的生产 ID 同形，便于读日志）。"""
    return f"task_202609{uuid.uuid4().hex[:22]}"


def _sibling_store(store: RedisLockStore) -> RedisLockStore:
    """与 `store` **同前缀、独立连接**的第二个实例（模拟另一台执行器）。

    用同一个 client 的两个实例不算数：那两次 `acquire` 在同一个连接的
    wait-for-response 队列里**串行**执行，第二次必然看到第一次的结果，原子性无从谈起。
    独立的连接才可能让两段 Lua 真正交错——这才是「Redis 单线程执行脚本」要证明的东西。

    构造 `RedisLockStore` 会**另开一个客户端**（`redis.asyncio.Redis` 的分支）：
    它仍是惰性的，第一条命令才建连接。
    """
    host, port, db = redis_integration_target()
    return RedisLockStore(host=host, port=port, db=db, prefix=store.prefix)


async def test_acquire_renew_release_defer_round_trip(
    redis_store: RedisLockStore, redis_client: object
) -> None:
    """26. `acquire` / `renew` / `release` / `defer` / `is_deferred` 基本链路（真实 Redis）。"""
    task_id = _task_id()

    claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert claim is not None
    assert claim.attempt == 1, "首次领取的尝试序号必须是 1"

    assert await redis_store.acquire(task_id, lease_ms=LEASE_MS) is None, "键已被占用仍领到了"

    assert await redis_store.renew(claim, lease_ms=LEASE_MS) is True
    assert await redis_store.release(claim) is True

    again = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert again is not None
    assert again.attempt == 2, "释放后计数被清零了：超额判据会永远不成立"
    assert again.token != claim.token, "每次领取必须换 token（否则所有权校验形同虚设）"

    await redis_store.defer(task_id, delay_s=30.0)
    assert await redis_store.is_deferred(task_id) is True
    assert await redis_store.is_deferred(task_id) is True, "is_deferred 连读两次结果不一致"
    assert await redis_store.acquire(task_id, lease_ms=LEASE_MS) is None, "退避期内不该能领取"

    await redis_store.release(again)


async def test_two_connections_race_and_exactly_one_wins(redis_store: RedisLockStore) -> None:
    """27. **原子性真验**：两条独立连接并发 `acquire` 同一 task_id → **恰好一个**成功。

    「恰好一个」是两段断言的合取：成功数 `== 1`（不多）**且**另一个拿到 `None`（不少）。
    只断言前者会漏掉"两个都成功但计数只加了 1"这类实现。

    并发的真实性：`asyncio.gather` 把两个 `acquire` 同时挂起，两者的
    `EVALSHA` 分别走**各自的连接**；Redis 单线程串行执行脚本，故"谁先执行谁拿到"，
    而两个脚本都不会看到"对方还没写但自己已经判断完"的中间态——这正是要验的性质。
    """
    task_id = _task_id()
    other = _sibling_store(redis_store)
    try:
        results = await asyncio.gather(
            redis_store.acquire(task_id, lease_ms=LEASE_MS),
            other.acquire(task_id, lease_ms=LEASE_MS),
        )
    finally:
        await other.close()

    winners = [claim for claim in results if claim is not None]
    assert len(winners) == 1, (
        f"两条并发领取拿到了 {len(winners)} 个租约：同一任务会被两个实例同时处理"
    )
    assert results.count(None) == 1, "另一个必须拿到 None（键已被占用）"
    assert winners[0].attempt == 1, "只有一次成功的领取，尝试序号必须是 1"


async def test_pttl_is_within_the_lease_and_renew_extends_it(
    redis_store: RedisLockStore, redis_client: object
) -> None:
    """28（前半）. 真 `PX` 生效：`acquire` 后 `PTTL` ∈ `(0, lease_ms]`。

    用**原始客户端**读 `PTTL`：这是"Redis 真的设了过期时间"的直接证据。
    只断言"过一会儿能领取"证明不了 TTL 被设成了 lease_ms 量级（设成 1 小时也会过期，
    只是要等一小时）。
    """
    task_id = _task_id()
    key = lease_key(task_id, prefix=redis_store.prefix)

    claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert claim is not None

    ttl = await redis_client.pttl(key)  # type: ignore[attr-defined]
    assert 0 < ttl <= LEASE_MS, f"PTTL={ttl} 不在 (0, {LEASE_MS}] 内：租约的过期时间不对"

    assert await redis_store.renew(claim, lease_ms=LEASE_MS * 2) is True
    extended = await redis_client.pttl(key)  # type: ignore[attr-defined]
    assert LEASE_MS < extended <= LEASE_MS * 2, (
        f"续期后的 PTTL={extended} 没有延长到 (1000, 2000]：续期没写进去"
    )


async def test_lease_expires_and_becomes_claimable_again(redis_store: RedisLockStore) -> None:
    """28（后半）. 推进**真实时间**过 `lease_ms` 后，另一个连接能领取。

    **这里允许真等**（集成段）：真实 `PX` 的到期由 Redis 服务端的计时决定，
    注入的假时钟改不了它。等待 1.1s（租约 1000ms + 0.1s 余量），最坏 1.1s ≤ 工单上限 2s。
    """
    task_id = _task_id()
    other = _sibling_store(redis_store)
    try:
        claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
        assert claim is not None
        assert await other.acquire(task_id, lease_ms=LEASE_MS) is None, "未过期就被别人领走"

        # 真等：租约 1000ms + 0.1s 余量，最坏 1.1s ≤ 工单上限 2s（豁免指令必须与调用同一行）。
        await asyncio.sleep(EXPIRY_WAIT_S)  # ai-allow-sleep: 集成段验证真 PX 过期，等待 1.1s ≤2s

        reclaimed = await other.acquire(task_id, lease_ms=LEASE_MS)
        assert reclaimed is not None, "租约在真实 Redis 上没有按时过期：任务会被永久占住"
        assert reclaimed.attempt == 2, "回收必须消耗一次尝试（计数不因过期而清零）"
    finally:
        await other.close()


async def test_renew_and_release_reject_a_foreign_token(
    redis_store: RedisLockStore, redis_client: object
) -> None:
    """补充：**Lua 校验 owner** 的真实验证（这是 MUST 用 Lua 的唯一理由）。

    构造一个 token 不匹配的 claim：`renew` 与 `release` 都必须返回 `False`，
    且键**仍在**、键值仍是原 token。若实现用了裸 `SET k v XX PX ms`（不校验 owner），
    本用例的 `renew` 会返回 `True`——那正是 `design.md:208` 要防的
    「任何实例都能续期别人的租约 ⇒ 两个实例同时处理同一任务」。
    """
    task_id = _task_id()
    key = lease_key(task_id, prefix=redis_store.prefix)

    claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert claim is not None
    foreign = type(claim)(task_id=task_id, token="not-the-owner-token", attempt=claim.attempt)

    assert await redis_store.renew(foreign, lease_ms=LEASE_MS * 5) is False, (
        "别人的 token 续期成功了：任何实例都能续期别人的租约（design.md:208 要防的形态）"
    )
    assert await redis_store.release(foreign) is False, "别人的 token 释放成功了"

    assert await redis_client.get(key) == claim.token, "键值被改动了（续期必须只改 TTL）"  # type: ignore[attr-defined]
    ttl = await redis_client.pttl(key)  # type: ignore[attr-defined]
    assert 0 < ttl <= LEASE_MS, f"被拒的续期仍然改了 TTL：{ttl}（owner 校验没有生效）"


async def test_defer_key_is_separate_from_the_lease_key(
    redis_store: RedisLockStore, redis_client: object
) -> None:
    """补充：退避键与租约键**分离**（`defer` 不碰租约键）。

    工单 §2.2 逐字：「`defer` 的键与租约键分离：退避期间租约键应已过期（否则别人领不到），
    故『等待期』是**独立状态**，不靠『租约还没过期』来表达」。
    """
    task_id = _task_id()
    prefix = redis_store.prefix
    claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert claim is not None

    await redis_store.defer(task_id, delay_s=30.0)

    assert await redis_client.exists(defer_key(task_id, prefix=prefix)) == 1  # type: ignore[attr-defined]
    defer_ttl = await redis_client.pttl(defer_key(task_id, prefix=prefix))  # type: ignore[attr-defined]
    assert 0 < defer_ttl <= 30_000, f"退避键的 TTL={defer_ttl} 不是 30s 量级"
    lease_ttl = await redis_client.pttl(lease_key(task_id, prefix=prefix))  # type: ignore[attr-defined]
    assert 0 < lease_ttl <= LEASE_MS, "defer 改动了租约键：退避与租约没有分离"


async def test_three_keys_are_distinct_and_all_cleaned_by_the_fixture(
    redis_store: RedisLockStore, redis_client: object
) -> None:
    """补充：三类键都在同一个前缀下（**集成夹具按前缀清理的可靠性**依赖这一点）。

    若某类键用了别的前缀，`redis_client` 夹具的按前缀清理会**漏键**，
    残留会累积在共享 Redis 上（且对下一条用例不可见——因为它用的是新前缀）。
    """
    task_id = _task_id()
    prefix = redis_store.prefix
    keys = [
        lease_key(task_id, prefix=prefix),
        attempt_count_key(task_id, prefix=prefix),
        defer_key(task_id, prefix=prefix),
    ]

    assert len(set(keys)) == 3, f"三类键有重名：{keys}"

    claim = await redis_store.acquire(task_id, lease_ms=LEASE_MS)
    assert claim is not None
    await redis_store.defer(task_id, delay_s=30.0)

    existing = [key for key in keys if await redis_client.exists(key)]  # type: ignore[attr-defined]
    assert sorted(existing) == sorted(keys), (
        f"领取 + 退避之后应当三类键都在，实际只有 {existing}"
        f"（缺的那类说明它用了别的前缀，或者根本没写）"
    )
    assert all(key.startswith(prefix) for key in keys), "有键不在本用例前缀下：夹具清理会漏"


# ---------------------------------------------------------------------------
# A3：**两侧语义一致性**（内存替身 vs 真 Redis，同一 TTL 下必须给出同一序列）
# ---------------------------------------------------------------------------
async def test_attempt_counter_semantics_match_the_in_memory_store(
    redis_prefix: str,
) -> None:
    """**A3**：同一组 TTL 下，真 Redis 与内存替身给出**同一个** `attempt` 序列。

    这是 A3 的**跨实现判据**：单侧用例只能证明"某一侧按 TTL 过期"，
    而这条把两侧放在**同一组参数**下直接对比——评审实测的分歧
    （真 Redis `[1,1,1]` vs 替身 `[1,2,3]`）正是它能抓到的东西。

    ## 真等与虚拟时间的分工（本用例是唯一同时用两者的地方）

    - **真 Redis** 的 `PX` 由服务端计时，故必须有**真实时间**流过：每步真等 0.4s
      （3 步 ⇒ 约 0.8s，工单上限 2s 之内）；
    - **内存替身** 用注入时钟推进**相同**的秒数——于是两侧看到的"过了多久"一致，
      差别只剩"哪一侧实现了计数键的到期"。

    租约取 100ms（`PX` 到期远早于 0.4s 的推进，故每步都能重新领取），
    计数 TTL 取 250ms（< 0.4s，故每步都该过期 → 两侧都必须是 `[1, 1, 1]`）。
    """
    from aicore.core.lease import InMemoryLockStore as _InMemory

    lease_ms = 100
    count_ttl_ms = 250
    step_s = 0.4

    clock = _StepClock()
    memory = _InMemory(clock=clock, attempt_count_ttl_ms=count_ttl_ms)
    redis_store = _redis_store_with(redis_prefix, attempt_count_ttl_ms=count_ttl_ms)
    try:
        memory_sequence: list[int] = []
        redis_sequence: list[int] = []
        for index in range(3):
            memory_claim = await memory.acquire(f"task-mem-{index}", lease_ms=lease_ms)
            assert memory_claim is not None
            memory_sequence.append(memory_claim.attempt)
            clock.advance(step_s)

            redis_claim = await redis_store.acquire(f"task-redis-{index}", lease_ms=lease_ms)
            assert redis_claim is not None
            redis_sequence.append(redis_claim.attempt)
            # 豁免指令必须与调用**同一行**（判据取 `lines[node.lineno - 1]`）。
            await asyncio.sleep(step_s)  # ai-allow-sleep: 集成段验真 PX+计数 TTL，每步 0.4s
    finally:
        await redis_store.close()

    assert redis_sequence == [1, 1, 1], (
        f"真 Redis 的序列是 {redis_sequence}（期望 [1, 1, 1]：计数键 TTL 250ms < 每步 0.4s）"
    )
    assert memory_sequence == redis_sequence, (
        f"两侧语义不一致：内存替身 {memory_sequence} vs 真 Redis {redis_sequence}——"
        f"离线段会在这一点上给生产一个错误的绿灯"
    )


class _StepClock:
    """`StepClock` 的最小实现（内存替身用；只被本文件的一致性用例使用）。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _redis_store_with(prefix: str, *, attempt_count_ttl_ms: int) -> RedisLockStore:
    """按给定计数 TTL 建一个 `RedisLockStore`（一致性用例要显式控制它）。"""
    host, port, db = redis_integration_target()
    return RedisLockStore(
        host=host, port=port, db=db, prefix=prefix, attempt_count_ttl_ms=attempt_count_ttl_ms
    )


@pytest.mark.parametrize("bad", [0, -1])
async def test_redis_store_rejects_non_positive_count_ttl(bad: int) -> None:
    """**A3 同族**：真实现也在**构造期**拒绝 `attempt_count_ttl_ms <= 0`。

    这一条不需要连 Redis（构造不连接），故它在配置正确时也照样跑——
    而它的内容是"真 Redis 上 `PEXPIRE 0` 会删键、把超额判据静默关掉"，
    故必须与内存替身**同一口径**地拒绝。
    """
    host, port, db = redis_integration_target()
    with pytest.raises(ValueError, match="必须为正"):
        RedisLockStore(host=host, port=port, db=db, attempt_count_ttl_ms=bad)


# ---------------------------------------------------------------------------
# F9：**入参拒绝面**的跨实现一致性（同一组输入喂两侧，断言同判）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "lease_ms",
    [0, -5, 1000.5],
    ids=["0", "-5", "1000.5（小数）"],
)
async def test_both_implementations_reject_the_same_lease_ms(
    redis_prefix: str, lease_ms: object
) -> None:
    """**F9(a)**：真 Redis 会拒绝的 `lease_ms`，**两侧都拒绝**（同一个异常类型）。

    工单给出的真 Redis 实测：`PX 0` / `PX -5` → `invalid expire time in 'set' command`；
    `PX 1000.5` → `value is not an integer or out of range`。
    第一版的内存替身**照发租约并计数** ⇒ 离线段全绿、生产段一启动就抛。

    现在两侧都在发命令之前走同一个 `_require_lease_ms`，故判据是**同一个异常类型**
    （`ValueError` 的同一个子类）——这正是"同一组输入喂两侧、断言同判"的字面含义。
    **本用例不需要连 Redis**（校验在往返之前），但它被标 `integration` 是因为同族的
    真 Redis 行为只能在这里记录；判据本身是两侧对称的。
    """
    from aicore.core.lease import InMemoryLockStore as _InMemory

    clock = _StepClock()
    memory = _InMemory(clock=clock)
    redis_store = _redis_store_with(redis_prefix, attempt_count_ttl_ms=60_000)
    try:
        for name, store in (("内存替身", memory), ("真 Redis", redis_store)):
            try:
                await store.acquire(_task_id(), lease_ms=lease_ms)  # type: ignore[arg-type]
            except ValueError as exc:
                assert "lease_ms 必须是正整数毫秒" in str(exc), f"{name} 抛的是别的错：{exc}"
            else:
                pytest.fail(
                    f"{name} 没有拒绝 lease_ms={lease_ms!r}（真 Redis 会报 "
                    f"invalid expire time / value is not an integer）"
                )
    finally:
        await redis_store.close()


async def test_both_implementations_truncate_defer_to_whole_milliseconds(
    redis_prefix: str,
) -> None:
    """**F9(b)**：`defer(1.0009)` 在两侧都是**整毫秒**（真 Redis 的 `PTTL ≈ 1000ms`）。

    第一版替身存 `clock + 1.0009`，真 Redis 收 `PX 1000`。差不到 1ms，但口径必须一致——
    否则上面那条"两侧语义一致"的用例测的是替身自己的定义。
    这里直接读真 Redis 的 `PTTL`（原始事实），并断言它在 1000ms 附近而不是 1001ms。
    """
    from aicore.core.lease import InMemoryLockStore as _InMemory

    task_id = _task_id()
    clock = _StepClock()
    memory = _InMemory(clock=clock)
    redis_store = _redis_store_with(redis_prefix, attempt_count_ttl_ms=60_000)
    try:
        await memory.defer(task_id, delay_s=1.0009)
        await redis_store.defer(task_id, delay_s=1.0009)

        memory_remaining = memory.state.deferrals[task_id] - clock.monotonic()
        redis_pttl = await redis_store.client.pttl(defer_key(task_id, prefix=redis_prefix))
    finally:
        await redis_store.close()

    assert redis_pttl > 0, "真 Redis 上退避键不存在：defer 没有写键"
    assert abs(redis_pttl - 1000) <= 50, (
        f"真 Redis 的 PTTL 是 {redis_pttl}ms（期望 ≈1000ms，即 `int(1.0009*1000)`）"
    )
    assert abs(memory_remaining - 1.000) < 1e-9, (
        f"内存替身的退避时长是 {memory_remaining}s（期望 1.000s，即截断到整毫秒）——"
        f"两侧口径不一致"
    )


@pytest.mark.parametrize("delay_s", [0.0001, 0.0009], ids=["0.0001", "0.0009"])
async def test_both_implementations_do_not_defer_below_one_millisecond(
    redis_prefix: str, delay_s: float
) -> None:
    """**F9(c)**：`int(delay_s*1000) == 0` 时两侧都**不设退避**（真 Redis 的 `PX 0` 会报错）。

    真 Redis 那一侧如果照旧发 `PX 0`，脚本会抛 `invalid expire time`；
    故两侧都按"不退避"处置（不写键 + 清掉旧的）。本用例断言**两侧都没有退避键**。
    """
    from aicore.core.lease import InMemoryLockStore as _InMemory

    task_id = _task_id()
    clock = _StepClock()
    memory = _InMemory(clock=clock)
    redis_store = _redis_store_with(redis_prefix, attempt_count_ttl_ms=60_000)
    try:
        await memory.defer(task_id, delay_s=delay_s)
        await redis_store.defer(task_id, delay_s=delay_s)

        assert await memory.is_deferred(task_id) is False, "内存替身设了退避（真实现做不到）"
        assert await redis_store.is_deferred(task_id) is False, "真 Redis 上出现了退避键"
        redis_exists = await redis_store.client.exists(defer_key(task_id, prefix=redis_prefix))
    finally:
        await redis_store.close()

    assert redis_exists == 0, "真 Redis 上仍有退避键残留"
