"""执行器内核的真实 Redis + 真实 MySQL 全链路用例（工单 §3.5 的三条）。

**默认不跑**（`-m integration`）；连不上 Redis 或 MySQL 时**显式 skip 并说明**
（`conftest` 的 `redis_is_available()` 与 `integration_engine_factory`），MUST NOT 静默通过。

## 本文件证明什么（默认段证明不了的部分）

- **SQL 真的落地**：`list_claimable` 确实扫到当月 `PROCESSING` 的行，
  `mark_succeeded` 确实把 `ai_task.status` / `progress` 写成 `SUCCEEDED` / `100`
  （默认段用替身 store，验的是**执行器的调用序列**，不是 SQL 的语义）；
- **真 store 与真锁店的契约成立**：同一个执行器驱动 `SqlTaskLeaseStore` + `RedisLockStore`
  能跑通全链路——这是「`TaskStore` / `LockStore` 是结构化 Protocol」的运行期证据。

## 分片表怎么来的（与既有集成用例同一口径）

用 `scripts/apply_ddl.py` 同一个渲染器（`repository/sharding.py` 的 `render_shard_template`）
现建本进程专属演练月的三张分片表，结束时**逆序** DROP（`ocr_correction` 有指向同月
`ocr_result` 的物理外键）。**MUST NOT `DROP DATABASE`、MUST NOT 碰 6 张固定名表。**

## ⚠ `error_code` 的落库（B3 已闭合，本文件的断言随之升级）

`SqlTaskLeaseStore.mark_failed` 现在**真的写** `ai_task.error_code`（Task 4.7 修复轮
获得授权，给 `TaskRepo.update_status` 加了一个**可选**的 `error_code` 形参；
不传时列集合仍是三列，既有调用方的 SQL 逐字不变）。
故 `test_failure_backs_off_then_exhausts_to_failed` 断言的是**真实码值**
（`5002` / `4003` 那一档），而不再是"该列为 NULL"——后者是缺口期的取证形态。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from aicore.core.errors import CHANNEL_FAILURE_CODE, ChannelFailureError
from aicore.core.lease import RedisLockStore, defer_key, lease_key
from aicore.core.task_runner import ClaimedTask, RunnerConfig, TaskRunner
from aicore.repository.base import physical_table
from aicore.repository.models import AiTask
from aicore.repository.session import EngineFactory
from aicore.repository.sharding import (
    ensure_month_tables,
    render_shard_template,
    sql_skeleton,
)
from aicore.repository.task_lease_store import SqlTaskLeaseStore, TaskRowMissingError
from aicore.repository.task_repo import TaskRepo
from aicore.service.task.registry import REGISTRY

pytestmark = pytest.mark.integration

ACCOUNT_ID = "acc_0000000000000000000000000001"
#: 用**合法枚举值**（`ai_task.type` 是原生 MySQL ENUM + `validate_strings=True`）：
#: 工单 §1.2 明示「非法值写不进去」，故集成用例 MUST NOT 用非法枚举做探测。
TASK_TYPE = "OCR"
LEASE_MS = 30_000
#: 逆建表顺序（`ocr_correction` 有指向同月 `ocr_result` 的物理外键）。
_SHARDED_ORDER = ("ai_task", "ocr_result", "ocr_correction")

#: 演练月 = **当前月**（`datetime.now(UTC)` 现算）。
#:
#: ## 为什么必须是当前月（实测踩过一次）
#:
#: `TaskRunner.now()` 用的是**墙钟**（`finished_at` 要写进库、要与人读的时间对齐，
#: 见它的 docstring），而 `SqlTaskLeaseStore.list_claimable` 按**传进去的 `now`** 现算月份。
#: 两者的 `now` 是**同一个时刻**（`runner.now()` → `claim_once(now=...)`）。
#: 第一版把演练月取成 `2099<pid%12+1>`（跟既有集成用例的风味），于是：
#:   - 表建在 `ai_task_209902`（夹具按演练月建）；
#:   - 扫描打的是 `ai_task_202609`（runner 的墙钟月）→ `Table doesn't exist`。
#: 既有集成用例能用"未来月"是因为它们**自己指定月份**（从不问"现在几月"）；
#: 本文件走的是**执行器的真实路径**，故月份必须由时钟决定，演练月只能是当前月。
#:
#: ### 并发冲突怎么处理（照既有集成用例的先例）
#: 多进程同时跑会互相 DROP 对方刚建的表。既有用例的处置是"按 pid 分桶取不同月份"
#: （`test_apply_ddl_mysql.py` 的实测记录），而本文件的分桶维度是**天**：
#: 同一天的所有进程共用同一个物理月表，DDL 是 `CREATE TABLE IF NOT EXISTS`（幂等），
#: 数据按 `task_id`（UUID 后缀）互不冲突。收尾**不 DROP**（DROP 会打掉同一天其它进程
#: 正在用的表）；代价是演练库里会留下本月的 `ai_task_YYYYMM` 与若干行测试数据
#: ——与"`train_` 前缀的演练表"同一档，且下月自然轮换。这个取舍已登记在报告里。
_RUN_NOW = datetime.now(UTC)
DRILL_MONTH = f"{_RUN_NOW:%Y%m}"
#: 写进 `created_at` 的时刻：**本月内**的固定时刻（避免月末跑测试时 `created_at`
#: 落到下个月、与扫描月不一致）。取当月 1 日 03:00 UTC，与 `_RUN_NOW` 同月。
DRILL_NOW = datetime(_RUN_NOW.year, _RUN_NOW.month, 1, 3, 0, tzinfo=UTC)


def _task_id() -> str:
    """`task_` + 创建月 + UUID hex（`er.md` §5.4 的形态，总长 32）。"""
    return f"task_{DRILL_MONTH}{uuid.uuid4().hex[:20]}"


def _drop_month_tables(factory: EngineFactory, month: str) -> None:
    """只 DROP 指定的分片表（逆序，避免外键 3730）。**只给"本文件独占的月份"用**。

    当前月的表**不清**（同一天可能有别的进程正在用，见 `DRILL_MONTH` 的注释）；
    这条助手只服务「跨月扫描」用例里那个**本文件自造的下个月**。
    """
    with factory.write_session() as session:
        for logical in reversed(_SHARDED_ORDER):
            session.execute(text(f"DROP TABLE IF EXISTS `{logical}_{month}`"))


@pytest.fixture
def drill_factory(integration_engine_factory: EngineFactory) -> Iterator[EngineFactory]:
    """真实 MySQL：确保**当前月**三张分片表存在；收尾**不 DROP**（理由见 `DRILL_MONTH`）。

    同时清掉**历史上**遗留的演练行（见 `_purge_stale_tasks`）——不清的话，
    `list_claimable` 会把上几次失败/中断的用例留下的 `PROCESSING` 行扫出来，
    `run_once` 于是领走**别人**的任务，本用例的断言全部指向错误的行
    （实测：`run_once` 返回 True 而"自己那行"仍是 `PROCESSING`）。
    """
    factory = integration_engine_factory
    with factory.write_session() as session:
        ensure_month_tables(session.connection(), DRILL_MONTH)
    _purge_stale_tasks(factory)
    yield factory
    _purge_stale_tasks(factory)


def _purge_stale_tasks(factory: EngineFactory) -> None:
    """删掉本月表里**本文件造的**演练行（判据：`account_id` 是 `ACCOUNT_ID`）。

    只删自己的账号：别的集成用例（如 Task 4.5 的提交链路）也用本月表，
    删它们的行会破坏它们的断言——「清理自己造的东西」是这条助手唯一的边界。
    前置与收尾各调一次：中断的用例（被 Ctrl-C / 超时杀掉）留下的行由**下一次**前置清掉。
    """
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.write_session() as session:
        session.execute(table.delete().where(table.c.account_id == ACCOUNT_ID))


class _Env:
    """一次用例的执行器环境：真 MySQL + 真 Redis + 读原始事实的入口。"""

    def __init__(self, factory: EngineFactory, locks: RedisLockStore, client: Any) -> None:
        self.factory = factory
        self.locks = locks
        self.client = client
        self.prefix = locks.prefix
        self._repo = TaskRepo()

    def insert_task(self, task_id: str) -> None:
        """按提交侧的口径落一行 `ai_task`（`status=PROCESSING`、`progress=0`）。

        **必须走 `TaskRepo.insert`**（而不是 `session.add(entity)`）：分片表的物理名
        由调用方按月现算，ORM 的 `Session.add` 只会把行打到**逻辑表** `ai_task`
        （生产上并不存在那张表）。这不是风格问题——实测报错就是
        `Table 'aicore_test.ai_task' doesn't exist`（本用例第一版踩过）。
        """
        with self.factory.write_session() as session:
            self._repo.insert(
                session,
                AiTask(
                    task_id=task_id,
                    account_id=ACCOUNT_ID,
                    type=TASK_TYPE,
                    status="PROCESSING",
                    progress=0,
                    created_at=DRILL_NOW,
                ),
            )

    def read_row(self, task_id: str) -> dict[str, Any] | None:
        """读回这一行（**新会话**：走连接池里的另一条连接，验的才是"库里真的变了"）。"""
        table = physical_table("ai_task", DRILL_MONTH)
        with self.factory.primary_read_session() as session:
            row = (
                session.execute(select(table).where(table.c.task_id == task_id))
                .mappings()
                .first()
            )
        return None if row is None else dict(row)

    def make_runner(self, handler: Any, *, max_retries: int = 3) -> TaskRunner:
        return TaskRunner(
            store=SqlTaskLeaseStore(self.factory),
            locks=self.locks,
            handlers={TASK_TYPE: handler},
            policies=REGISTRY,
            config=RunnerConfig(
                lease_ms=LEASE_MS, max_retries=max_retries, concurrency_limit=2
            ),
        )


@pytest.fixture
async def runner_env(
    drill_factory: EngineFactory, redis_client: Any, redis_store: RedisLockStore
) -> Any:
    """执行器环境：真 MySQL（`SqlTaskLeaseStore`）+ 真 Redis（`RedisLockStore`）。

    依赖 `redis_store` + `redis_client` **两个夹具**，各管一件事：

    - `redis_store` 给 `RedisLockStore`（本用例专属前缀）；
    - `redis_client` 给**原始客户端**（读 PTTL 用），并**负责按前缀清理本用例的键**。

    **为什么必须显式依赖 `redis_client`**（实测踩过一次）：清理逻辑写在
    `redis_client` 的终结器里，而它只在**被请求时**才会实例化。第一版本夹具自己
    新建客户端、不依赖 `redis_client`，于是只请求 `runner_env` 的用例跑完后
    **键全部留在 Redis 上**（实测 14 条集成用例跑完留下 7 个 `:attempts` / `:lease` 键）。
    靠"记得也要请求 redis_client"来保证清理，迟早会漏——故把依赖写进夹具本身。
    """
    locks = redis_store
    client = redis_client
    try:
        yield _Env(drill_factory, locks, client)
    finally:
        await locks.close()


class _SucceedingHandler:
    """「真处理器」的最小实现（工单 §2.8 第 4 条：集成段要真处理器就在测试里定义）。"""

    def timeout_s(self) -> float:
        return 10.0

    async def handle(self, task: ClaimedTask) -> None:
        return None


class _AlwaysFailingHandler:
    """立即失败的处理器（带业务码 `4003`：通道失败，可重试）。"""

    def timeout_s(self) -> float:
        return 10.0

    async def handle(self, task: ClaimedTask) -> None:
        raise ChannelFailureError("通道返回 503（集成用例的确定性失败）")


async def test_full_path_from_insert_to_succeeded(runner_env: _Env) -> None:
    """29. 「落库 → 领取 → 执行（假 handler）→ 成功」全链路：库里终态 `SUCCEEDED` / `progress=100`。

    断言的是**库里的行**（`read_row` 走新会话），而不是执行器记了什么——
    后者在默认段已经验过（替身 store 的调用序列）。
    """
    task_id = _task_id()
    runner_env.insert_task(task_id)
    before = runner_env.read_row(task_id)
    assert before is not None and before["status"] == "PROCESSING"

    runner = runner_env.make_runner(_SucceedingHandler())
    claimed = await runner.claim_once()
    assert claimed is not None, "真 MySQL 上没扫到刚插入的那一行"
    assert claimed.task_id == task_id, (
        f"领到的是别人的任务（{claimed.task_id}）：本月表里有遗留的 PROCESSING 行，"
        f"夹具的前置清理没有生效"
    )
    await runner.execute(claimed)

    row = runner_env.read_row(task_id)
    assert row is not None
    assert row["status"] == "SUCCEEDED", f"终态不是 SUCCEEDED：{row}"
    assert row["progress"] == 100, f"progress 不是 100：{row['progress']}"
    assert row["finished_at"] is not None, "终态必须写 finished_at（er.md §6.1 L298）"
    await runner.aclose()


async def test_lease_is_released_after_success(runner_env: _Env) -> None:
    """29（续）. 成功后租约**已释放**（真实的 Redis 键不在了）——否则任务一直占着锁。"""
    task_id = _task_id()
    runner_env.insert_task(task_id)
    runner = runner_env.make_runner(_SucceedingHandler())

    assert await runner.run_once() is True

    assert await runner_env.client.exists(lease_key(task_id, prefix=runner_env.prefix)) == 0, (
        "成功后租约键仍在：下一个实例会一直领不到这个任务（直到租约过期）"
    )
    await runner.aclose()


async def test_begin_attempt_progress_is_visible_in_the_row(runner_env: _Env) -> None:
    """29（续）. `begin_attempt` 真的把 `progress` 写成了 1（`er.md` §6.1 L293 的进度回写）。

    判据取自**处理器运行期间**的库状态：处理器读一次自己的行并把 `progress` 记下来
    （那是 `begin_attempt` 的产物，而不是终态的 100）。
    """
    task_id = _task_id()
    runner_env.insert_task(task_id)
    seen: list[int] = []
    env = runner_env

    class _ProgressReadingHandler:
        def timeout_s(self) -> float:
            return 10.0

        async def handle(self, task: ClaimedTask) -> None:
            row = env.read_row(task.task_id)
            assert row is not None
            seen.append(row["progress"])

    runner = env.make_runner(_ProgressReadingHandler())
    assert await runner.run_once() is True

    assert seen == [1], f"处理器运行期间库里的 progress 应为 1（begin_attempt 的产物），实际 {seen}"
    await runner.aclose()


async def test_failure_backs_off_then_exhausts_to_failed(runner_env: _Env) -> None:
    """30. 失败 + 退避 + 重试 + 超限转人工的全链路（`max_retries=1`）。

    链路（`max_retries=1`，即最多尝试 2 次）：

    1. 第 1 次失败 → `requeue`（`progress=0`）+ 退避 `BACKOFF_BASE_S * 2 ** 0 = 1.0s`；
    2. 退避期内 `claim_once` 领不到（真实的退避键在挡）；
    3. 清掉退避键（**模拟退避到期**：真等要 1s，而这一步的语义与时间无关）
       → 第 2 次失败，`attempt=2 > max_retries=1` → `mark_failed`；
    4. 库里终态 `FAILED`、`finished_at` 非空。

    ⚠ **`error_code` 此刻不会落库**：`SqlTaskLeaseStore.mark_failed` 写不了该列
    （`TaskRepo.update_status` 的列集合不含它）。故断言该列为 `None`——
    把缺口变成可复现的事实（见模块 docstring 的说明）。
    """
    task_id = _task_id()
    runner_env.insert_task(task_id)
    runner = runner_env.make_runner(_AlwaysFailingHandler(), max_retries=1)

    # ---- 第 1 次失败：重排队 + 退避 1.0s ----
    assert await runner.run_once() is True
    row = runner_env.read_row(task_id)
    assert row is not None
    assert row["status"] == "PROCESSING", f"第 1 次失败不该写终态：{row}"
    assert row["progress"] == 0, f"重排队应把 progress 写回 0：{row['progress']}"
    assert row["finished_at"] is None, "非终态不该有 finished_at"

    backoff_key = defer_key(task_id, prefix=runner_env.prefix)
    assert await runner_env.client.exists(backoff_key) == 1, "失败后没有写退避键"
    ttl = await runner_env.client.pttl(backoff_key)
    assert 0 < ttl <= 1000, f"第 1 次失败的退避应为 1.0s，实际 TTL={ttl}"

    # ---- 退避期内领不到（真实的退避键在挡） ----
    assert await runner.claim_once() is None, "退避期内仍然领到了任务：退避键没有生效"

    # ---- 清掉退避键（模拟退避到期），第 2 次失败即超限 ----
    await runner_env.client.delete(backoff_key)
    assert await runner.run_once() is True
    row = runner_env.read_row(task_id)
    assert row is not None
    assert row["status"] == "FAILED", f"超过 max_retries 之后必须置 FAILED：{row}"
    assert row["finished_at"] is not None, "终态必须写 finished_at"
    # **error_code 真的落库了**（B3 修复点）：Task 4.11 的「4003 / 5002 分别计数」靠这一列。
    # 修复前这里是 `assert row["error_code"] is None`——那是"正面记录缺口"的写法，
    # 缺口闭合后必须改成断言**真实码值**，否则它会把修复变成一条失败。
    assert row["error_code"] == str(CHANNEL_FAILURE_CODE), (
        f"FAILED 行的 error_code 应为 {CHANNEL_FAILURE_CODE}（处理器抛的是通道失败），"
        f"实际 {row['error_code']!r}：这一列是 4.11 分别计数的唯一依据"
    )
    await runner.aclose()


async def test_unreachable_redis_fails_fast_without_touching_the_row(runner_env: _Env) -> None:
    """31. Redis 不可达时（错误端口）**`claim_once` MUST 抛错而不是吞掉**，
    且**任务状态不被改动**（fail fast，不假装成功）。

    判据两段：

    1. `claim_once` 抛异常（**不是**返回 `None`）——返回 `None` 会让执行器以为
       「没有任务」，于是 Redis 挂了也照样安静地空转（运维看不到任何信号）；
    2. 库里的行**一个字节都没变**（status / progress / finished_at 都是原值）——
       fail fast 的语义是「什么都没做」，不是「做了一半」。
    """
    task_id = _task_id()
    runner_env.insert_task(task_id)
    before = runner_env.read_row(task_id)
    assert before is not None

    broken = RedisLockStore(host="127.0.0.1", port=1, db=0, prefix=runner_env.prefix)
    runner = TaskRunner(
        store=SqlTaskLeaseStore(runner_env.factory),
        locks=broken,
        handlers={TASK_TYPE: _SucceedingHandler()},
        policies=REGISTRY,
        config=RunnerConfig(lease_ms=LEASE_MS, max_retries=3, concurrency_limit=2),
    )

    with pytest.raises(Exception):  # noqa: B017 - 这里断言的是"必须抛"，类别由 redis-py 决定
        await runner.claim_once()

    after = runner_env.read_row(task_id)
    assert after == before, f"Redis 不可达时任务行被改动了：{before} -> {after}"
    await runner.aclose()
    await broken.close()


async def test_list_claimable_only_scans_the_current_month(runner_env: _Env) -> None:
    """补充：`list_claimable` **只扫当月**（分片键下推，`er.md` §5.3 禁跨分片）。

    ## R4 修复点：**阳性对照**与否定断言必须成对

    第一版只有否定断言（"下月的任务不在结果里"）——一个**恒返回 `[]`** 的实现照样绿，
    而那样的实现在生产上意味着"永远领不到任何任务"。故本用例在同一次调用里同时断言：

    - **本月**的任务**在**结果里（阳性对照）；
    - **下月**的任务**不在**结果里（判据本体）。

    两条合起来才说明"扫描按月份切分"，而不是"扫描什么都不返回"。

    ## 跨月扫描为什么必须禁止

    跨月扫描在语法上跑得通（MySQL 不拦 UNION 两个月分片表），但违反 `er.md` §5.3 的
    分片键下推，而且会让「上个月没跑完的任务」在本月被静默捡起来。
    """
    next_month_dt = DRILL_NOW + timedelta(days=40)
    next_month = next_month_dt.strftime("%Y%m")
    assert next_month != DRILL_MONTH, "演练月的选择有问题：下个月与本月相同"
    this_month_task = _task_id()
    other_task = f"task_{next_month}{uuid.uuid4().hex[:20]}"
    repo = TaskRepo()
    with runner_env.factory.write_session() as session:
        repo.insert(
            session,
            AiTask(
                task_id=this_month_task,
                account_id=ACCOUNT_ID,
                type=TASK_TYPE,
                status="PROCESSING",
                progress=0,
                created_at=DRILL_NOW,  # **本月**——阳性对照
            ),
        )
    with runner_env.factory.write_session() as session:
        ensure_month_tables(session.connection(), next_month)
        repo.insert(
            session,
            AiTask(
                task_id=other_task,
                account_id=ACCOUNT_ID,
                type=TASK_TYPE,
                status="PROCESSING",
                progress=0,
                created_at=next_month_dt,  # **下月**——不该被扫到
            ),
        )
    try:
        store = SqlTaskLeaseStore(runner_env.factory)
        seen = [task.task_id for task in store.list_claimable(limit=10, now=DRILL_NOW)]
        assert this_month_task in seen, (
            f"本月任务不在扫描结果里：{seen}（判据会退化成『恒返回空也绿』）"
        )
        assert other_task not in seen, (
            f"本月扫描扫到了 {next_month} 的任务：分片键没有下推（er.md §5.3 禁止跨分片）"
        )
    finally:
        _drop_month_tables(runner_env.factory, next_month)


def test_drill_tables_come_from_the_production_renderer() -> None:
    """补充：演练月的 `ai_task` 表是**用生产同一套模板**渲染出来的（本文件的夹具口径）。

    若夹具改用 `Base.metadata.create_all`（另一条建表路径），本文件验的就不再是
    生产结构——那正是「两份渲染实现必然漂移」要防的事。这条断言把口径写死。

    「渲染后没有占位符残留」的判据**复用生产自己的** `sql_skeleton`（剥注释 + 掏空
    字符串字面量）：第一版在这里手写了一个"逐行剔除以 `--` 开头的行"的判据，
    结果被 `COMMENT '... GET /aicore/tasks/{taskId}'` 里的花括号判红——
    那串在 MySQL 里是**数据**，不是占位符（`sharding.py` 的 `sql_skeleton` docstring
    正好记着这个坑）。教训：判据也要复用权威实现，别自己造一份。
    """
    ddl = render_shard_template("ai_task", DRILL_MONTH)
    assert f"ai_task_{DRILL_MONTH}" in ddl
    assert "{" not in sql_skeleton(ddl), "渲染后的 SQL 骨架里仍有占位符残留"


def test_write_back_to_a_missing_row_raises(drill_factory: EngineFactory) -> None:
    """**A5(c)**：写回一个**不存在**的行 → `rowcount == 0` → 抛 `TaskRowMissingError`。

    ## 这条用例为什么现在才有（我上轮的论证漏了一条路）

    我上轮把 A5(c) 登记成"没有测试覆盖"，理由是：伪造 `TaskRepo` 就测不到真 SQL；
    把分片键算错则**读也找不到**，用例会退化成"什么都查不到"的平凡真。
    **那条论证漏了集成段这条路**（控制者指出）：把当月表建好、**不插那一行**，
    直接对一个不存在的 `task_id` 调写回 —— 走的是**真 SQL、真库**，
    `UPDATE ... WHERE task_id = ...` 匹配 0 行，正是要判定的场景。

    ## 为什么这件事重要（不只是"抛个错更好看"）

    此前 `_write_back` / `mark_failed` 把 `update_status` 的返回值**丢掉**，
    于是 `rowcount == 0`（分片月算错 / 任务号不对 / 行被别处删了）时执行器**以为写成功了**
    并**释放租约**：行留在旧状态（例如 `PROCESSING`）等下一轮重放，
    而重放可能重复调用付费通道。抛错让失败**可见**，且不会误释放租约。

    四个写方法**逐个覆盖**：它们共用 `_write_back`（`mark_failed` 自己展开写），
    只测一个会漏掉"另一个忘了检查返回值"这类实现。
    """
    missing = _task_id()  # **从未插入**过这一行
    store = SqlTaskLeaseStore(drill_factory)
    finished_at = datetime.now(UTC)
    calls = {
        "begin_attempt": lambda: store.begin_attempt(
            missing, account_id=ACCOUNT_ID, created_at=DRILL_NOW
        ),
        "mark_succeeded": lambda: store.mark_succeeded(
            missing,
            account_id=ACCOUNT_ID,
            created_at=DRILL_NOW,
            progress=100,
            finished_at=finished_at,
        ),
        "mark_failed": lambda: store.mark_failed(
            missing,
            account_id=ACCOUNT_ID,
            created_at=DRILL_NOW,
            error_code="5002",
            finished_at=finished_at,
        ),
        "requeue": lambda: store.requeue(
            missing, account_id=ACCOUNT_ID, created_at=DRILL_NOW
        ),
    }
    for name, call in calls.items():
        with pytest.raises(TaskRowMissingError) as excinfo:
            call()
        assert missing in str(excinfo.value), (
            f"{name} 抛的错里没有任务号：{excinfo.value}（排障时要能定位是哪一行）"
        )

    # 反向对照：**行存在时不该抛**（否则上面四条可能只是"这个方法恒抛"的平凡真）。
    present = _task_id()
    _insert_task(drill_factory, present)
    store.begin_attempt(present, account_id=ACCOUNT_ID, created_at=DRILL_NOW)
    row = _read_row(drill_factory, present)
    assert row is not None and row["status"] == "PROCESSING", (
        f"行存在时 begin_attempt 应当正常写回，实际：{row}"
    )
    store.mark_failed(
        present,
        account_id=ACCOUNT_ID,
        created_at=DRILL_NOW,
        error_code="5002",
        finished_at=finished_at,
    )
    row = _read_row(drill_factory, present)
    assert row is not None and row["status"] == "FAILED"


def _insert_task(factory: EngineFactory, task_id: str) -> None:
    """插一行 `ai_task`（**必须走 `TaskRepo.insert`**：分片表物理名由它现算）。

    与 `_Env.insert_task` 同一口径；本文件的同步用例不经过 `runner_env`，故独立一份。
    （不共用 `_Env` 是因为那是 async 夹具的产物，而本用例**不需要** Redis。）
    """
    with factory.write_session() as session:
        TaskRepo().insert(
            session,
            AiTask(
                task_id=task_id,
                account_id=ACCOUNT_ID,
                type=TASK_TYPE,
                status="PROCESSING",
                progress=0,
                created_at=DRILL_NOW,
            ),
        )


def _read_row(factory: EngineFactory, task_id: str) -> dict[str, Any] | None:
    """读回一行（与 `_Env.read_row` 同一口径；本文件的同步用例独立用得到）。"""
    table = physical_table("ai_task", DRILL_MONTH)
    with factory.primary_read_session() as session:
        row = session.execute(select(table).where(table.c.task_id == task_id)).mappings().first()
    return None if row is None else dict(row)
