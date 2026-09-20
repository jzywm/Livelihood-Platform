"""依赖注入提供者（FastAPI Depends 装配点）。

设计要点：本模块只暴露**抽象依赖**（从 app.state 取已装配好的对象），
MUST NOT 在此构造具体 Provider / repository —— 具体实现只在 main.py 组合根注入，
否则 service 层会通过依赖注入间接依赖具体实现，分层契约形同虚设。

## 身份来源（权威口径，MUST 照此）

网关是**唯一**鉴权点：验签后先剥离客户端伪造头、再写入四头身份
（`services/gateway/.../JwtAuthFilter.java:22/:90-93/:96`），ACC 侧的
`TrustedHeaderAuthFilter.java:23/:27` 与之一致，并对缺失该头的受保护路径回 `2001`（fail-closed）。
故本服务的 `account_id` **取请求头 `X-User-Id`**（它是验签 JWT 的 `sub`，客户端无法伪造）：

- 缺失 / 空串 / 纯空白 → `UnauthorizedError`（`2001`，HTTP 401），**fail-closed**；
- **MUST NOT 回落成「匿名账号」或默认账号** —— 那会让每个未鉴权请求都写进某个真实账号的
  任务表（等于替别人造任务，且越权查询会因此看起来"合法"）；
- **MUST NOT 信任自造头**：本任务只用 `X-User-Id`。
  头名常量落在这里（`ACCOUNT_ID_HEADER`），MUST NOT 在各路由里散写字面量。

## 会话来源：为什么用 `Protocol` 而不是 import `repository.session.EngineFactory`

`.importlinter` 契约 1 禁止 `api` **直接**依赖 `repository`（`allow_indirect_imports = true`
只放行 api → service → repository 这条设计路径），而**返回类型注解也算依赖**。故：

1. 本模块**就地定义** `SessionFactory` / `EngineFactoryLike` 两个 `Protocol`，只描述形状；
2. 即便改用 `TYPE_CHECKING` 下的 import，mypy strict 仍会把它当真实依赖，
   而契约检查用的 grimp 只看运行期 import —— 那会造出「mypy 看不见、契约也看不见」的假放行；
3. Protocol 的额外收益是**测试可注入替身**（`tests/conftest.py` 的沙盒引擎）——
   而 `EngineFactory` 的构造签名要求 `Settings`、其 `build_engine` 会去连真实 MySQL；
   **MUST NOT** 为测试给 `EngineFactory` 加「可替换引擎」的入口（那会把测试关切泄进生产类）。

`Session` / `Engine` 本身用 `TYPE_CHECKING` 下的 `sqlalchemy` 导入（sqlalchemy 是既有依赖，
不违任何契约）。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Final, Protocol

from fastapi import Header, Request

from aicore.core.config import Settings, is_blank
from aicore.core.errors import UnauthorizedError

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session


#: 网关注入的账号标识头（`JwtAuthFilter.java:22/:96`：只写验签后的 JWT `sub`）。
#: **唯一出处**：路由与提供者都从本常量取，MUST NOT 散写 `"X-User-Id"` 字面量。
ACCOUNT_ID_HEADER: Final = "X-User-Id"


class SessionFactory(Protocol):
    """路由需要的**最小**会话形状：写会话 + 「写后立即读」会话。

    刻意只声明两个方法：路由**不需要**知道引擎、池与 dispose（那是组合根的事），
    故测试替身只需实现这两个入口即可被注入——形状越窄，替身与真实实现之间
    「测试没覆盖到的差异」就越少。

    两个入口的分工是硬要求（`er.md` §5.5）：

    - `write_session()`：写路径（`POST /aicore/ocr` 落 `ai_task`）；
    - `primary_read_session()`：**写后立即读**路径（`GET /aicore/tasks/{taskId}` 轮询）——
      `er.md:252` 逐字「关键**写后立即读**（任务提交后立即轮询、复核后立即查状态）**强制走主库**」。
      **MUST NOT 用 `read_session()` 跑轮询**：从库延迟会让刚受理的任务查不到（表现为假 404），
      而 `repository/session.py:243-249` 的 `session_needs_primary` 守卫正是为拦这种形态而存在。
    """

    def write_session(self) -> AbstractContextManager[Session]: ...

    def primary_read_session(self) -> AbstractContextManager[Session]: ...


class EngineFactoryLike(SessionFactory, Protocol):
    """组合根装配到 `app.state.engine_factory` 的工厂形状（= `EngineFactory` 的公开面）。

    它比 `SessionFactory` 宽：额外声明三个引擎属性与 `dispose()`，
    因为**组合根**要持有并释放连接池，而**路由**只用会话入口。
    两个 Protocol 的关系是「装配点契约」与「使用点契约」，不是一个东西的两种写法。
    """

    @property
    def write_engine(self) -> Engine: ...

    @property
    def read_engine(self) -> Engine: ...

    @property
    def primary_read_engine(self) -> Engine: ...

    def dispose(self) -> None: ...


def get_settings(request: Request) -> Settings:
    """返回组合根装配到 `app.state.settings` 的 Settings 实例。

    注意：`app.state.settings` 由组合根在启动期装配，在那之前调用本函数会抛 AttributeError
    （Starlette `State.__getattr__` 在属性缺失时即抛）。此处刻意不做兜底取值：
    配置缺失必须在启动/装配期暴露，用 getattr 默认值掩盖只会把误配置推迟到运行期。
    """
    # 显式落一个具名变量：`request.app.state` 是 Any，直接 return 会被 mypy 记为
    # 「returning Any from function declared to return Settings」；改回 `-> Any` 又会让
    # 类型注解失去意义。
    settings: Settings = request.app.state.settings
    return settings


def get_engine_factory(request: Request) -> EngineFactoryLike:
    """返回组合根装配到 `app.state.engine_factory` 的 EngineFactory 实例。

    与 `get_settings` 同一形态：**只从 `app.state` 取已装配好的对象**，不在此构造。
    组合根未装配时（未经 lifespan 启动）同样抛 `AttributeError` —— 这是刻意的：
    本服务第一批需要数据库的路由若拿不到工厂，唯一正确的结局是**启动期就暴露**，
    而不是在请求里回落到某个默认引擎（那会把「装配漏了」变成「连到了别的库」）。
    """
    factory: EngineFactoryLike = request.app.state.engine_factory
    return factory


def get_account_id(
    x_user_id: Annotated[str | None, Header(alias=ACCOUNT_ID_HEADER)] = None,
) -> str:
    """取网关注入的账号标识（`X-User-Id`），缺失即 `2001`（fail-closed）。

    **为什么用 `Annotated[...]` 而不是默认值位置调 `Header(...)`**：后者会触发 ruff 的
    B008（在参数默认值里调用函数），而 B008 防的是「可变默认值 / 每次调用都求值的默认值」
    这类真实陷阱——FastAPI 的依赖注入只是恰好长成那样。用 `Annotated` 表达同一件事，
    既不必写行级豁免，也把「这段注解是元数据、不是默认值」表达得更准确。

    空白判定复用 `core/config.py` 的**公开** `is_blank`（Task 4.4 公开）：
    `None`、空串、纯空白三种都算「没带身份」，MUST NOT 复制第二份判定
    （两份必然会漂移，而漂移的表现是某一种空值被放行成真实账号）。

    **文案取平台默认**（`UnauthorizedError()` 不带参数 → `DEFAULT_MESSAGES[2001]`
    「未登录或 Token 已失效」）：头名与「是网关没注入还是客户端伪造」这类细节一律不进响应体
    （`core/errors.py` 的口径：message 面向用户，MUST NOT 拼内部细节）。
    """
    if x_user_id is None or is_blank(x_user_id):
        raise UnauthorizedError()
    return x_user_id


def get_now() -> datetime:
    """当前时刻（**UTC 感知**，`er.md` §6 绪「UTC 存储」）。

    **为什么时间也要走依赖注入**：`service/task/submit.py` 的 `now` 是**必传参数**
    （分片月与 `created_at` 都由它现算），而路由必须有个地方取「现在」。把取时刻做成依赖，
    测试就能用 `app.dependency_overrides[get_now]` 注入固定时钟——跨月边界、固定月份
    （沙盒只有 `ai_task_202607/202608`）这两类用例才写得出，且测试内 MUST NOT 出现任意 sleep。

    MUST NOT 让调用方自己 `datetime.now()`：那样时间源会散落在各路由里，
    注入点消失，「同一 `now` 现算一次、查幂等与插入共用」（见 submit.py 的月边界一节）
    也无从保证。
    """
    return datetime.now(UTC)
