"""会话与连接池（同步会话 + 线程池；写会话 / 只读会话分离）。Task 3.4 实现。

## 为什么是同步会话（硬约束，`design.md` L216 / spec §5.4 已定档）

同步会话 + 线程池，**MUST NOT** 引入 `async_sessionmaker` / `AsyncEngine`：

1. 分表是运行期动态 SQL（`repository/sharding.py` 按月切物理表名），同步会话下「拼一条
   SQL 再执行」是直线代码；换成异步会话要把同样的逻辑拆进 `await` 链，可读性白白变差；
2. 规避「会话跨事件循环」陷阱：一个会话绑定一个连接，而连接池跨事件循环复用会引出
   `Future attached to a different loop` 这类运行期偶发故障。

## 池参数从配置读取（硬约束）

`pool_size` / `max_overflow` 一律取 `Settings.mysql_pool_size` / `mysql_max_overflow`，
本模块**不出现** `pool_size=5` 这类字面量（`tests/repository/test_session.py` 用源码扫描
正面钉住这条）。容量是部署决策，写死等于替运维做决定。

`pool_pre_ping=True` 与 `pool_recycle=3600` **都开**，取舍如下：

- `pool_pre_ping`：连接被池借出前先探活，把「被网络设备或服务端悄悄掐断的僵尸连接」
  换成一次重连，而不是把一个 `MySQL server has gone away` 抛给业务。代价是每次借出多
  一次极轻的往返（MySQL 8 上是 COM_PING，亚毫秒级）——相对「偶发失败」这个代价可接受；
- `pool_recycle=3600`：MySQL 8 服务端 `wait_timeout` 默认 28800 秒（8 小时），空闲连接
  到点会被**服务端单方面关闭**；取 1 小时留足余量，让连接在被掐断之前由池自己换掉。
  MUST NOT 设成 `-1`（永不过期）——那等于把这个僵尸连接问题放大到必然出现。

## 写后立即读（`er.md` §5.5）

主库写、从库读；「任务提交后立即轮询」「复核后立即查状态」这类**写后立即读**必须走主库，
否则会从从库读到旧状态。本模块给的不是「调用方记得用对方法」，而是两条可执行机制：

1. `primary_read_session()`：写后立即读的推荐入口（`primary_read_engine` 就是
   `write_engine`，共用同一条连接池）；
2. `mark_write_then_read(session)` / `session_needs_primary(session)`：在 `session.info`
   上打标记 / 读标记；`read_session()` 若拿到带标记的会话即**抛错**，把「写完立刻读却从
   从库读到旧值」这种静默故障变成一次明确的失败。

**抛的是 `ParamError(code=1002)`，理由**：能落到这里的是「调用方把一个写着『写后立即读』的
会话交给了只读路径」，属**调用参数用错**这一档，1002 正是平台错误码表里现成的「参数格式
错误」。为什么不新增一个内部错误码：`core/errors.py` 的新增清单要求码值先存在于
`services/_common/openapi.yaml` 的 `ErrorCode` 枚举（`tests/unit/test_errors.py` 正面强制
比对），为一条本服务内部的用法错误去扩平台公共枚举，代价与收益不成比例。

## 口令不进 URL 字面量、不进日志（硬约束）

连接串一律用 `sqlalchemy.engine.URL.create(...)` 组装（`password=` 是独立参数），
**MUST NOT** 手工 f-string 拼 `mysql+pymysql://user:pass@host`：手工拼串时口令就是 URL
字面量的一部分，`repr(engine)` / `str(engine.url)` / 异常栈都可能把它带出去。
SQLAlchemy 的 `URL.__repr__` 与 `str(url)` 默认按 `hide_password=True` 渲染，
本模块打日志只用 `Settings.mysql_dsn` / `mysql_read_dsn`（**本来就不含口令**）。

## 引擎生命周期

`EngineFactory.__init__` **不连接**数据库：`create_engine` 是惰性的，第一条语句才建连接，
故「配置错」不会在构造期变成一次网络等待（那会让配置错误看起来像网络慢）；`dispose()`
幂等。组合根的接线（lifespan）由第 4 组负责，**本模块刻意不提供全局单例**：由谁持有
`EngineFactory` 是组合根的决定，在这里造单例会与「工厂是纯装配函数」（Task 1.4）冲突。

## 已知边界（如实登记）

本机只有一个 MySQL 实例（没有真实从库），故读写分离在本任务里是**地址可配**：
只读引擎连的是「可配置的地址」，主从延迟与从库一致性**未验证**。
`read_target_is_primary` 与装配日志会把「只读其实落在主库上」显式暴露，不伪装成已分离。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from aicore.core.config import Settings
from aicore.core.errors import PARAM_FORMAT_CODE, ParamError

_logger = logging.getLogger(__name__)

#: 驱动名与字符集：与 `Settings.mysql_dsn` 同一口径（那里是给人看的串，这里是给引擎的 URL）。
_DRIVER_NAME: Final = "mysql+pymysql"
_CHARSET: Final = "utf8mb4"

#: 连接回收秒数：见模块 docstring（MySQL 8 默认 `wait_timeout` 28800 秒，取 1 小时留足余量）。
_POOL_RECYCLE_SECONDS: Final = 3600

#: `session.info` 上的「写后立即读」标记键。
_WRITE_THEN_READ_KEY: Final = "aicore.write_then_read"


def build_engine(settings: Settings, *, read_only: bool) -> Engine:
    """按配置造一个**同步**引擎；`read_only=True` 时指向只读目标（含回落主库）。

    「只读」指**用途**（这个引擎只服务只读会话），不是数据库层的权限强制：
    真正的只读写保护由从库自身的 `read_only` 与账号权限保证。

    池参数取自 `settings`（见模块 docstring）：容量是部署决策，MUST NOT 写死。
    """
    url = URL.create(
        drivername=_DRIVER_NAME,
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_read_host if read_only else settings.mysql_host,
        port=settings.mysql_read_port if read_only else settings.mysql_port,
        database=settings.mysql_database,
        query={"charset": _CHARSET},
    )
    return create_engine(
        url,
        pool_size=settings.mysql_pool_size,
        max_overflow=settings.mysql_max_overflow,
        pool_pre_ping=True,
        pool_recycle=_POOL_RECYCLE_SECONDS,
    )


def _open_session(engine: Engine) -> Session:
    """造会话的**唯一**入口（用例替换本函数即可验证 `read_session` 的守卫）。

    **不用 `scoped_session`**：线程本地会话在线程池下会被下一个请求复用，
    「上一次请求的事务 / 身份映射」因此可能悄悄带进下一次请求——那正是「会话跨执行单元」
    这一类故障；每次显式造一个会话，生命周期由 `_session_lifecycle` 收口。
    """
    return Session(bind=engine)


@contextmanager
def _session_lifecycle(session: Session) -> Iterator[Session]:
    """会话生命周期（**唯一实现**）：正常退出提交、异常回滚、退出即关闭。

    三条都由本函数承担，三个公开入口（`session_scope` / `write_session` /
    `read_session`）不再各写一遍——事务口径只允许有一处。
    """
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # 关会话必须无条件执行：它把连接还给池，漏掉一次就是一次连接泄漏。
        session.close()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """通用会话作用域：`with session_scope(engine) as session:`。

    读写不分家（引擎由调用方给）。业务代码应优先用 `EngineFactory` 的三个会话入口，
    它们把「这个会话该连哪个库」收进了工厂，而不是散在每个调用点。
    """
    with _session_lifecycle(_open_session(engine)) as session:
        yield session


def dispose_engines(*engines: Engine) -> None:
    """释放给定的全部引擎（**幂等**：重复传入同一引擎安全，`Engine.dispose()` 自身幂等）。"""
    for engine in engines:
        engine.dispose()


def mark_write_then_read(session: Session) -> None:
    """把会话标记为「刚写过，之后的读必须走主库」（`er.md` §5.5）。

    标记落在 `session.info`（SQLAlchemy 留给应用的字典，随会话生命周期存在），
    而不是模块级 / 线程级变量：会话结束标记即消失，不会把「某一次写」的状态带到下个请求。
    """
    session.info[_WRITE_THEN_READ_KEY] = True


def session_needs_primary(session: Session) -> bool:
    """该会话是否处于「写后立即读」状态（供只读路径与仓储层路由判断）。"""
    return bool(session.info.get(_WRITE_THEN_READ_KEY, False))


class EngineFactory:
    """引擎与会话的唯一出口：写会话 / 只读会话 / 主库只读会话。

    构造**不连接**数据库（`create_engine` 是惰性的，第一条语句才建连接），
    故「配置错」不会在构造期变成一次网络等待；`dispose()` 幂等。

    装配时会打一条 `[自检]` 日志，把「只读到底连哪里」写清楚——尤其是**回落主库**：
    本机只有一个实例，回落是常态，MUST NOT 让它在日志里看不出来。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._write_engine = build_engine(settings, read_only=False)
        self._read_engine = build_engine(settings, read_only=True)
        # 主库只读引擎**就是**写引擎（同一对象、同一条连接池）：写后立即读要读到自己刚写的
        # 数据，就必须与写共用同一条连接池与同一份会话视图；另造一个「主库只读」引擎会给
        # 同一份数据开出第二个池，既浪费连接，又让「读到自己写的」变成依赖两条连接的事。
        self._primary_read_engine = self._write_engine
        self._disposed = False
        _logger.info(
            "[自检] 会话引擎已装配：write=%s read=%s（只读地址：%s）",
            settings.mysql_dsn,
            settings.mysql_read_dsn,
            "回落主库——未配置独立从库"
            if settings.read_target_is_primary
            else "已配置独立从库地址",
        )

    @property
    def write_engine(self) -> Engine:
        """写引擎（主库）：`write_session()` 与 `primary_read_session()` 都用它。"""
        return self._write_engine

    @property
    def read_engine(self) -> Engine:
        """只读引擎：指向配置的只读地址；未配置时指向主库（见 `read_target_is_primary`）。"""
        return self._read_engine

    @property
    def primary_read_engine(self) -> Engine:
        """主库只读引擎（写后立即读用）：**等于** `write_engine`，名字把意图写显式。"""
        return self._primary_read_engine

    @property
    def read_target_is_primary(self) -> bool:
        """只读目标是否落在主库上（`True` = 没有独立从库，只读是回落的）。

        它把「回落」变成程序可断言、日志可核对的事实，MUST NOT 被读成「已经分离」。
        """
        return self._settings.read_target_is_primary

    @contextmanager
    def write_session(self) -> Iterator[Session]:
        """写会话（主库）：正常退出提交、异常回滚、退出即关闭。"""
        with session_scope(self.write_engine) as session:
            yield session

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        """只读会话（从库）：**不得**承担写后立即读，带标记的会话当场被拒。

        守卫放在这里而不是靠调用方记得，理由见模块 docstring。拒绝时抛
        `ParamError(code=1002)`；抛之前会话已被关掉（`_session_lifecycle` 的
        finally 负责归还连接），异常路径同样不漏连接。
        """
        with _session_lifecycle(_open_session(self.read_engine)) as session:
            if session_needs_primary(session):
                raise ParamError(
                    "只读会话不能承担「写后立即读」：请改用 primary_read_session()"
                    "（er.md §5.5：写后立即读强制走主库，避免从从库读到旧状态）",
                    code=PARAM_FORMAT_CODE,
                )
            yield session

    @contextmanager
    def primary_read_session(self) -> Iterator[Session]:
        """写后立即读专用会话（主库）：与 `write_session()` 共用同一条连接池。

        典型用法（`er.md` §5.5 的两条路径：任务提交后立即轮询、复核后立即查状态）：

            with factory.write_session() as session:
                ...写入...
            with factory.primary_read_session() as session:
                ...读回刚写的数据...
        """
        with session_scope(self.primary_read_engine) as session:
            yield session

    def dispose(self) -> None:
        """释放两个引擎的连接池；**幂等**（重复调用不重复释放、不报错）。

        用显式标志而不是「反正 `Engine.dispose()` 自己幂等」：本方法还要保证
        `primary_read_engine`（与写引擎同一对象）不被重复释放，
        标志让「每个池只释放一次」这件事在代码里看得见。
        """
        if self._disposed:
            return
        self._disposed = True
        dispose_engines(self._write_engine, self._read_engine)
