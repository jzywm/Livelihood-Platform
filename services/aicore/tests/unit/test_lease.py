"""`core/lease.py` 的 `InMemoryLockStore` 用例（工单 §3.1 的 8 条，零 IO、注入时钟）。

## 两条纪律

1. **零 IO、零真等**：`tests/conftest.py` 文件头逐字「测试内 MUST NOT 出现任意 sleep；
   等待一律走轮询断言或注入的时钟」。本文件所有的时间推进都走 `FakeClock.advance()`，
   **没有任何 `await asyncio.sleep(...)`**（Redis 的真等待在
   `tests/integration/test_lease_redis.py`，那里是集成段、允许真等且已注明）。
2. **每条断言都要有判别力**：例如「另一个 store 实例能领取」一条**显式共享
   `InMemoryState`**——若每个实例各持一份状态，这条会退化成「第二个实例第一次领取」，
   它证明不了租约回收，只证明了「两个互不相干的字典」（见 `InMemoryState` 的 docstring）。

## 为什么这些用例能用一份共享状态

工单 §3.1 第 3 条要求「**另一个 store 实例**能领取」、第 7 条要求「`attempt` 连续递增」。
两者都必须在**同一份键空间**上成立，故用例显式构造 `InMemoryState(clock)` 并把它交给
两个 `InMemoryLockStore`——这正是「同一台 Redis 上的两个执行器实例」的内存等价物。
"""

from __future__ import annotations

import pytest

from aicore.core.lease import (
    DEFAULT_ATTEMPT_COUNT_TTL_MS,
    InMemoryLockStore,
    InMemoryState,
    attempt_count_key,
    defer_key,
    lease_key,
)

TASK = "task_202609abc0000000000000000000ab"
#: 本文件统一用 1000ms 的租约：毫秒→秒的换算（1.0s）能被 `advance(1.5)` 这类整值推进干净地跨过，
#: 不依赖浮点边界。
LEASE_MS = 1000


class FakeClock:
    """可注入的假时钟：`monotonic()` 返回可控值，`sleep()` 只推进虚拟时间。

    与 `tests/unit/test_provider_guard.py::FakeClock` **逐字同形但彼此独立**：
    两个被测模块（`provider/guard.py` 与 `core/lease.py`）各自声明了自己的 `StepClock`
    Protocol（契约 4 禁止 `core` 依赖 `aicore.provider`），故两个测试文件也各自持一份假时钟。
    结构子类型让同一个形状对两边都成立——这正是「Protocol 独立声明」的代价被压到最低的证据。
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock: FakeClock, state: InMemoryState | None = None) -> InMemoryLockStore:
    """建一个共享指定状态的 store（`state=None` 即新建一份）。"""
    if state is None:
        return InMemoryLockStore(clock=clock)
    return InMemoryLockStore(clock=clock, state=state)


async def test_first_acquire_succeeds_with_token_and_attempt_one() -> None:
    """1. `acquire` 首次成功、token 非空、`attempt == 1`。

    token 断言「非空」**并且**断言两次领取的 token 不同（第 7 条会再拿到第二个 token）：
    只断言非空的话，一个恒返回 `"x"` 的实现也能过——而那种实现会让**所有实例**都以为
    自己持有别人的租约（`renew` 只比较相等）。
    """
    clock = FakeClock()
    store = _store(clock)

    claim = await store.acquire(TASK, lease_ms=LEASE_MS)

    assert claim is not None
    assert claim.task_id == TASK
    assert claim.token != ""
    assert claim.attempt == 1


async def test_second_acquire_of_the_same_task_returns_none() -> None:
    """2. 同 task 再 `acquire` → `None`（未过期、非退避）。"""
    clock = FakeClock()
    store = _store(clock)
    first = await store.acquire(TASK, lease_ms=LEASE_MS)
    assert first is not None

    second = await store.acquire(TASK, lease_ms=LEASE_MS)

    assert second is None, "同一个未过期的租约被领取了两次：两个实例会同时处理同一个任务"


async def test_another_store_instance_can_reclaim_after_expiry() -> None:
    """3. 推进注入时钟过 `lease_ms` → **另一个 store 实例**能领取（租约超时回收）。

    两个实例**共享同一份 `InMemoryState`**：这才是「同一台 Redis 上的两个执行器实例」。
    若不共享，`second.acquire` 必然成功（它面对的是一个空字典），
    这条用例就退化成「空字典里能领取」——一句没有信息量的断言。
    """
    clock = FakeClock()
    state = InMemoryState(clock)
    first_store = _store(clock, state)
    second_store = _store(clock, state)

    assert await first_store.acquire(TASK, lease_ms=LEASE_MS) is not None
    assert await second_store.acquire(TASK, lease_ms=LEASE_MS) is None, "未过期就被别人领走"

    clock.advance(LEASE_MS / 1000 + 0.5)  # 1.5s > 1.0s 租约

    reclaimed = await second_store.acquire(TASK, lease_ms=LEASE_MS)

    assert reclaimed is not None, "租约过期后另一个实例仍领不到：任务会被永久占住"
    assert reclaimed.attempt == 2, "回收应当消耗一次尝试（attempt 必须累加）"


async def test_renew_requires_the_current_token() -> None:
    """4. `renew` 用**旧 token** → `False`；用**当前 token** → `True` 且延长存活。"""
    clock = FakeClock()
    state = InMemoryState(clock)
    first = _store(clock, state).acquire(TASK, lease_ms=LEASE_MS)
    stale = await first
    assert stale is not None

    # 让租约过期，再由另一个实例接管：此刻 `stale.token` 已是**旧** token。
    clock.advance(LEASE_MS / 1000 + 0.5)
    second_store = _store(clock, state)
    current = await second_store.acquire(TASK, lease_ms=LEASE_MS)
    assert current is not None
    assert current.token != stale.token, "第二次领取必须换 token，否则所有权校验形同虚设"

    assert await second_store.renew(stale, lease_ms=LEASE_MS) is False, "旧 token 续期不该成功"

    clock.advance(LEASE_MS / 1000 * 0.75)  # 再走 0.75s（原租约只剩 0.5s）
    assert await second_store.renew(current, lease_ms=LEASE_MS) is True

    # 续期确实延长了存活：从续期时刻起再过 0.75s 仍在租约内（合计 1.5s > 原始 1.0s）。
    clock.advance(LEASE_MS / 1000 * 0.75)
    third_store = _store(clock, state)
    assert await third_store.acquire(TASK, lease_ms=LEASE_MS) is None, (
        "续期没有真正延长租约：租约按原始到期时间失效了"
    )


async def test_release_requires_the_current_token() -> None:
    """5. `release` 用**别人的 token** → `False` 且键仍在；用**自己的 token** → `True` 且键消失。"""
    clock = FakeClock()
    state = InMemoryState(clock)
    owner = _store(clock, state)
    other = _store(clock, state)
    claim = await owner.acquire(TASK, lease_ms=LEASE_MS)
    assert claim is not None
    foreign = claim.__class__(task_id=claim.task_id, token="not-the-owner", attempt=claim.attempt)

    assert await other.release(foreign) is False, "别人的 token 不该能释放本租约"
    assert TASK in state.leases, "释放被拒之后键必须仍在"

    assert await other.release(claim) is True, "持有者用自己的 token 释放应当成功"
    assert TASK not in state.leases, "释放成功后键必须消失"


async def test_defer_blocks_until_the_delay_elapses() -> None:
    """6. `defer` 后 `is_deferred` 为真、`acquire` 返回 `None`；推进时钟过 `delay_s` 后可领取。"""
    clock = FakeClock()
    store = _store(clock)

    await store.defer(TASK, delay_s=1.0)

    assert await store.is_deferred(TASK) is True
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is None, "退避期内不该能领取"

    clock.advance(1.5)

    assert await store.is_deferred(TASK) is False
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is not None, "退避到期后必须重新可见"


async def test_attempt_increments_across_expire_and_reacquire() -> None:
    """7. **`attempt` 递增**：连续 expire→acquire 三次，`attempt` 依次 1/2/3。

    计数键的存活时长（`DEFAULT_ATTEMPT_COUNT_TTL_MS`）远大于本用例推进的 1.5s×2，
    故计数不会被自己的 TTL 清掉——这一条同时是「计数独立于租约」的证明：
    租约每次都被过期回收，计数却一直在累加。
    """
    assert DEFAULT_ATTEMPT_COUNT_TTL_MS > 3000, "计数存活时长必须远大于本用例推进的虚拟时间"

    clock = FakeClock()
    state = InMemoryState(clock)
    store = _store(clock, state)

    attempts: list[int] = []
    for _ in range(3):
        claim = await store.acquire(TASK, lease_ms=LEASE_MS)
        assert claim is not None
        attempts.append(claim.attempt)
        clock.advance(LEASE_MS / 1000 + 0.5)  # 让租约过期，下一次领取是新的一次尝试

    assert attempts == [1, 2, 3], f"尝试计数没有连续累加：{attempts}（超额判据会永远不成立）"


async def test_is_deferred_has_no_side_effects() -> None:
    """8. `is_deferred` **无副作用**（连调两次结果一致、不改变可领取性）。

    连读两次 + 读后再领取，三段都断言：只断言"两次结果一致"会漏掉
    「读操作顺手把键删了」这类副作用——那时两次都是 `False`，结果同样"一致"。
    """
    clock = FakeClock()
    store = _store(clock)
    await store.defer(TASK, delay_s=1.0)

    first = await store.is_deferred(TASK)
    second = await store.is_deferred(TASK)

    assert first is True
    assert second is True, "连读两次结果不一致：is_deferred 有副作用"
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is None, (
        "读过 is_deferred 之后退避就失效了：它在读的时候改动了状态"
    )


async def test_shared_state_makes_the_two_instances_see_the_same_keys() -> None:
    """补充（判别力自证）：**不共享**状态时第 3 条会退化成空断言。

    本用例正面演示两者差别：两个各自持有状态的实例**互相看不见**对方的键
    （未过期也能重复领取）。这正是第 3 条必须共享 `InMemoryState` 的理由——
    没有这一步，「另一个实例能领取」只是「另一个空字典能领取」。
    """
    clock = FakeClock()
    first = InMemoryLockStore(clock=clock)
    second = InMemoryLockStore(clock=clock)

    assert await first.acquire(TASK, lease_ms=LEASE_MS) is not None
    assert await second.acquire(TASK, lease_ms=LEASE_MS) is not None, (
        "各自持状态的实例本就应该互相看不见——这条断言证明第 3 条的共享是必要的"
    )


def test_key_names_are_three_distinct_keys() -> None:
    """补充：三类键必须**互不相同**且都带 task_id（三份键名漂移会让 Redis 实现打错键）。

    这一条钉住 `lease_key` / `attempt_count_key` / `defer_key` 的形状：
    它们一旦有两个相同，`SET NX` 的租约键就会与计数键互相覆盖，
    表现为「领取成功但计数被清零」或「退避键把租约键顶掉」。
    """
    keys = {
        lease_key(TASK),
        attempt_count_key(TASK),
        defer_key(TASK),
    }
    assert len(keys) == 3, f"三类键有重名：{sorted(keys)}"
    assert all(TASK in key for key in keys), f"键名里必须含 task_id：{sorted(keys)}"
    assert all(key.startswith("aicore:lease:") for key in keys), (
        f"键名前缀必须统一，否则按前缀清理（集成夹具）会漏键：{sorted(keys)}"
    )


# ---------------------------------------------------------------------------
# A3：计数键的**到期**语义必须与真 Redis 一致（离线段过去在这一点上与生产不一致）
# ---------------------------------------------------------------------------
async def test_attempt_counter_expires_after_its_own_ttl() -> None:
    """**A3**：计数键到期后，下一次领取的 `attempt` **从 1 重来**（与真 Redis `PEXPIRE` 一致）。

    ## 这条用例为什么必须有

    `InMemoryLockStore._increment_attempts` 曾经直接读 `self._state.attempts`，
    **绕过**了按 `expires_at` 判过期的 `live_attempt_counter`——于是内存侧"计数永不到期"。
    独立评审实测同一 TTL 下两侧给出**不同的序列**：

    ```
    Redis   acquire 序列（每步等 0.4s）: [1, 1, 1]   ← 计数键到期，INCR 从 1 重来
    InMem   acquire 序列（同一 TTL，注入时钟推进）: [1, 2, 3]   ← 计数永不到期
    ```

    含义：**离线段在这一点上与生产不一致**，而"计数丢失 → 超额判据归零 → 无限重试"
    正是 `DEFAULT_ATTEMPT_COUNT_TTL_MS` 那段 docstring 在论证的风险。修好后两侧同序。

    ## 参数怎么选（两条成对用例共用同一组，只差推进多少）

    租约 `lease_ms=200`、计数 TTL 500ms：

    - 本用例每步推进 0.7s：**租约过期**（能重新领取）且**计数也过期**（TTL 500ms）→ `[1, 1, 1]`；
    - 对照组每步推进 0.3s：租约过期但计数没过期 → `[1, 2, 3]`。

    两条只差一个数字，故"计数键有没有按 TTL 过期"是**唯一**的自变量。
    """
    short_lease_ms = 200
    count_ttl_ms = 500
    clock = FakeClock()
    state = InMemoryState(clock)
    store = InMemoryLockStore(clock=clock, state=state, attempt_count_ttl_ms=count_ttl_ms)

    attempts: list[int] = []
    for _ in range(3):
        claim = await store.acquire(TASK, lease_ms=short_lease_ms)
        assert claim is not None, "租约没在推进的时间里过期：本用例的前提不成立"
        attempts.append(claim.attempt)
        clock.advance(0.7)  # 0.7s > 计数 TTL 0.5s，也 > 租约 0.2s

    assert attempts == [1, 1, 1], (
        f"计数键没有按自己的 TTL 过期：{attempts}（期望 [1, 1, 1]，"
        f"与真 Redis 的 `PEXPIRE` 行为一致）"
    )


async def test_attempt_counter_does_not_expire_before_its_ttl() -> None:
    """**A3 的对照面**：TTL 之内计数**必须**继续累加。

    两条成对：一条钉"到期就重来"，一条钉"没到期就累加"。
    只留上面那条的话，一个**每次领取都清零计数**的实现也能过——
    而那正是"超额判据永远不成立 → 无限重试"的形态。
    """
    short_lease_ms = 200
    count_ttl_ms = 500
    clock = FakeClock()
    state = InMemoryState(clock)
    store = InMemoryLockStore(clock=clock, state=state, attempt_count_ttl_ms=count_ttl_ms)

    attempts: list[int] = []
    for _ in range(3):
        claim = await store.acquire(TASK, lease_ms=short_lease_ms)
        assert claim is not None, "租约没在推进的时间里过期：本用例的前提不成立"
        attempts.append(claim.attempt)
        clock.advance(0.3)  # 0.3s > 租约 0.2s，但 < 计数 TTL 0.5s

    assert attempts == [1, 2, 3], f"计数 TTL 之内没有累加：{attempts}（期望 [1, 2, 3]）"


@pytest.mark.parametrize("bad", [0, -1, -1000], ids=["0", "-1", "-1000"])
def test_attempt_count_ttl_must_be_positive(bad: int) -> None:
    """**A3 同族**：`attempt_count_ttl_ms <= 0` 必须在**构造期**被拒。

    为什么必须拒绝而不是"温和地钳一下"：真 Redis 的 `PEXPIRE key 0` 会**直接删键**
    （评审实测 `PEXPIRE 0 -> True | exists after = 0`），于是每次领取的计数都从 1 重来
    ⇒ `attempt > max_retries` 这条超额判据被**静默关掉** ⇒ 必然失败的任务被无限重试。
    钳掉之后调用方以为自己配了什么、实际配的是另一个值——那正是本模块通篇在防的漂移。
    """
    with pytest.raises(ValueError, match="必须为正"):
        InMemoryLockStore(attempt_count_ttl_ms=bad)


# ---------------------------------------------------------------------------
# A4：`defer` 的边界——替身与真 Redis 必须**同一口径**
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "delay_s",
    [0.0, -3.0, float("nan"), float("inf")],
    ids=["0.0", "-3.0", "nan", "inf"],
)
async def test_defer_with_non_positive_delay_does_not_defer(delay_s: float) -> None:
    """**A4**：非正 / 非有限的 `delay_s` **不设退避**——替身这一侧。

    三种口径原先互相打架（`LockStore.defer` 的 docstring、`RedisLockStore.defer` 的
    docstring、真 Redis 的行为）：docstring 说"写一个立即到期的键"，
    而真 Redis 的 `SET ... PX 0` **直接报错** `invalid expire time`。
    现在三处统一到**一个可实现的行为**：不写键 = 不等待 = 任务立刻可领。

    `nan` 尤其重要：旧实现里 `clock + nan` 的比较**恒真**，于是 `is_deferred` 永远为真
    ——**永久退避**（任务被永久挡住且没有任何报错），比"不等待"危险得多。
    """
    clock = FakeClock()
    store = _store(clock)

    await store.defer(TASK, delay_s=delay_s)

    assert await store.is_deferred(TASK) is False, (
        f"delay_s={delay_s!r} 之后仍处于退避期：口径没有对齐"
        f"（nan 会变成永久退避，那是最坏的形态）"
    )
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is not None, (
        f"delay_s={delay_s!r} 之后领不到任务：非正/非有限时长不该挡住任务"
    )


async def test_defer_with_non_positive_delay_clears_a_previous_window() -> None:
    """**A4 补充**：`defer(0)` **清掉**已有的退避窗口（而不是"什么都不做"）。

    调用方传 0 的意图是"现在就能领"；若残留着更早设下的退避窗口，那个意图就没被实现
    ——这类"看起来生效、实际被旧状态盖住"的形态正是本模块通篇在防的。
    """
    clock = FakeClock()
    store = _store(clock)
    await store.defer(TASK, delay_s=100.0)
    assert await store.is_deferred(TASK) is True

    await store.defer(TASK, delay_s=0.0)

    assert await store.is_deferred(TASK) is False, "传 0 没有清掉旧的退避窗口"
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is not None


async def test_defer_with_positive_delay_still_blocks() -> None:
    """**A4 的阳性对照**：正的 `delay_s` 仍然真的挡住任务（判据不是"永不退避"）。"""
    clock = FakeClock()
    store = _store(clock)

    await store.defer(TASK, delay_s=5.0)

    assert await store.is_deferred(TASK) is True
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is None
    clock.advance(5.5)
    assert await store.acquire(TASK, lease_ms=LEASE_MS) is not None


# ---------------------------------------------------------------------------
# F9：入参拒绝面——替身 MUST NOT 比真 Redis 宽松
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_lease_ms",
    [0, -5, 1000.5, True],
    ids=["0", "-5", "1000.5（小数）", "True（bool）"],
)
async def test_acquire_rejects_lease_ms_redis_would_reject(bad_lease_ms: object) -> None:
    """**F9**：真 Redis 会拒绝的 `lease_ms`，替身 MUST 也拒绝（且**同一个异常类型**）。

    真 Redis 实测口径：`SET k v NX PX 0` / `PX -5` → `invalid expire time in 'set' command`；
    `PX 1000.5` → `value is not an integer or out of range`。
    替身此前**照发租约并计数**——即"替身比真实现宽松"，它让离线段全绿、生产段一启动就抛。

    `True` 单列一条：`isinstance(True, int)` 为真，若不显式挡掉，`PX 1` 会被悄悄接受成
    "1 毫秒的租约"——它看起来像"领取成功"，而下一次 `renew` 时已经不是自己的了。

    断言的是**两件事**：抛出的类型（`ValueError` 子类，好让跨实现一致性用例能断言"同判"）
    与**没有留下任何键**（"抛之前先写了一半"是更隐蔽的形态）。
    """
    clock = FakeClock()
    store = _store(clock)

    with pytest.raises(ValueError, match="lease_ms 必须是正整数毫秒"):
        await store.acquire(TASK, lease_ms=bad_lease_ms)  # type: ignore[arg-type]

    assert store.state.leases == {}, f"拒绝 {bad_lease_ms!r} 时仍写下了租约键"
    assert store.state.attempts == {}, f"拒绝 {bad_lease_ms!r} 时仍累加了尝试计数"


async def test_renew_rejects_lease_ms_redis_would_reject() -> None:
    """**F9 的同族**：`renew` 的 `lease_ms` 同样被拒。

    真 Redis 上这两个值是两种不同的坏：`PEXPIRE key 0` 会**删除**键
    （于是"续期"变成"释放"，而调用方以为续上了），`PEXPIRE key -5` 报
    `invalid expire time`。替身若照收，就会把"续期失败"表现成"续期成功"。
    """
    clock = FakeClock()
    store = _store(clock)
    claim = await store.acquire(TASK, lease_ms=LEASE_MS)
    assert claim is not None

    for bad in (0, -5, 1000.5):
        with pytest.raises(ValueError, match="lease_ms 必须是正整数毫秒"):
            await store.renew(claim, lease_ms=bad)  # type: ignore[arg-type]

    # 阳性对照：合法值照常续期成功（判据不是"renew 一律抛"）。
    assert await store.renew(claim, lease_ms=LEASE_MS) is True


@pytest.mark.parametrize(
    "delay_s",
    [0.0001, 0.0005, 0.0009],
    ids=["0.0001", "0.0005", "0.0009"],
)
async def test_defer_shorter_than_one_millisecond_does_not_defer(delay_s: float) -> None:
    """**F9 第 3 处**：`int(delay_s * 1000) == 0` 的退避 MUST NOT 生效。

    真 Redis 收整数毫秒，`PX 0` **直接报错**（`invalid expire time`）；
    替身此前会真的设一个 0.0001s 的退避窗口——"替身做得到、真实现做不到"。
    两侧现在都走 `_defer_delay_ms`，折算后为 0 ⇒ 按"不退避"处置（不写键 + 清旧的）。

    与 `nan`/`inf` 归到同一档的理由也一致：调用方传这么小的值时，
    意图就是"立刻可领"；把它变成一个"几乎立刻过期但确实存在"的键只会制造竞态。
    """
    clock = FakeClock()
    store = _store(clock)

    await store.defer(TASK, delay_s=delay_s)

    assert await store.is_deferred(TASK) is False, (
        f"delay_s={delay_s!r} 折算后不足 1ms（真 Redis 的 PX 0 会报错），替身却真的退避了"
    )


async def test_defer_truncates_to_whole_milliseconds_like_redis() -> None:
    """**F9 第 4 处**：`defer(1.0009)` 的退避时长按**整毫秒截断**（真 Redis 收 `PX 1000`）。

    第一版替身直接存 `clock + 1.0009`（1000.9ms），真 Redis 只退避 1000ms。
    差不到 1ms 不影响协议，但"两侧的口径不同"会让跨实现一致性用例变成
    "在测替身自己的定义"，故由 `_defer_delay_ms` 统一。

    ## 取值是**故意挑的**（判据要能判红）

    截断后 `1000ms`、不截断 `1000.9ms`，故**在 `t = 1.0005s` 处两种实现给出相反答案**：
    截断 ⇒ 已过期（可领取）；不截断 ⇒ 仍在退避。本用例在该时刻断言"可领取"，
    于是它**能分辨**这两种实现（真 Redis 那一侧由集成用例比对 `PTTL`）。
    """
    clock = FakeClock()
    store = _store(clock)

    await store.defer(TASK, delay_s=1.0009)

    clock.advance(0.999)
    assert await store.is_deferred(TASK) is True, "0.999s 时不该已经可以领取"
    clock.advance(0.0015)  # 累计 1.0005s：截断后（1.000s）已过期，未截断（1.0009s）仍退避
    assert await store.is_deferred(TASK) is False, (
        "累计 1.0005s 时仍在退避：替身存的是 1.0009s 而不是截断后的 1.000s"
        "（与真 Redis 的 `PX <int ms>` 不同口径）"
    )
