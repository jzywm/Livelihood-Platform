"""配置模型（Pydantic Settings）与启动四条校验。

两条硬取向（`design.md` L250）：

1. **必填项一律不给默认值**——默认值会把配置错误隐藏到运行时；
2. **`extra="forbid"`**——写了不存在的配置项要报错，而非默默忽略（「以为配了其实没配」）。

字段级与跨字段的分工：字段级约束（必填 / 数值边界 / 枚举）是 `Field(...)` 的地盘，
跨字段规则在 `Settings._reject_invalid_startup_combination`（`model_validator(mode="after")`）——
两类错误的报告因此始终分得清（见下表）。

## 启动四条校验（`design.md` L245~250）

| 规则 | 判定 | 承担者 |
|---|---|---|
| 1. `env=prod` 且 `provider=mock` | 拒绝启动 | 跨字段（本模块） |
| 2. 真实通道被选中但密钥缺失 | 拒绝启动 | 跨字段（本模块） |
| 3. `dev` / `test` 降级 `mock` | 放行 + **告警**（不阻断） | 跨字段（本模块） |
| 4. 必填项缺失 | 拒绝启动、**不兜默认值** | 字段级（Task 2.1） |

规则 4 刻意不在这里重复实现：字段级失败时 pydantic **不会**进入 after 校验器，
两类错误天然分开；在此再写一遍边界判断只会造出第二套会漂移的口径。

**两类错误的判别方式**（运维排查最忌「到底哪错了」说不清）：

- **字段级**：`loc` 指向具体字段（如 `("mysql_user",)`），`type` 取 pydantic 内建值
  （`missing` / `literal_error` / `less_than_equal` / `extra_forbidden` …）；
- **跨字段**：`loc == ()`、`type == "value_error"`，且 `msg` 逐行以 `[跨字段：<代号>]` 开头
  （代号 `env-mock` / `provider-key` / `budget-order`）；告警以 `[告警：<代号>]` 开头。

**密钥安全（硬约束）**：`ValidationError.input` 与 `repr(Settings)` 都携带其它字段的原始值
（含 `mysql_password`）。故生成诊断信息时**只取 `loc` 与 `msg`**——见
`ConfigRejected.from_validation_error`；MUST NOT 拼接 `.input`、`str(exc)` 或 `repr(settings)`，
启动日志必须可以原样打印。

**告警机制（规则 3）**：用 `logging.getLogger(__name__).warning(...)`，不阻断、不 `print`。
选它而非 `warnings.warn` 的理由：① 这是面向运维的运行期事件，不是面向开发者的 API 弃用提示，
语义上属于日志；② Task 2.6 的 structlog JSON 配置建在 stdlib `logging` 之上，stdlib 记录会被
一并收编，换成 `warnings` 反而要另接一路；③ 测试侧可用 pytest `caplog` 直接断言，
且 pytest 自己会给根日志器挂处理器，`logging.lastResort` 不会触发，正常测试运行不往
stdout / stderr 打东西。

**谁来抛 `ConfigRejected`**：本模块的校验器只抛 pydantic 的 `ValidationError`（不与之对抗），
转换发生在**启动期**——组合根的 lifespan 钩子（Task 2.6）：

    try:
        settings = get_settings()
    except ValidationError as exc:
        raise ConfigRejected.from_validation_error(exc) from exc

`create_app()` MUST NOT 读配置（Task 1.4 的验收项：工厂是纯装配函数）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import Field, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# 运行环境：dev | test | prod。跨字段规则复用本别名。
type Env = Literal["dev", "test", "prod"]

_logger = logging.getLogger(__name__)

# 通道口径：mock 是唯一的「非真实」通道；真实通道的凭据必须可核验（见规则 2）。
_MOCK_PROVIDER = "mock"
_NON_PROD_ENVS: frozenset[str] = frozenset({"dev", "test"})

# 跨字段规则 / 告警的代号：出现在消息里，供运维与用例精确匹配。
_RULE_ENV_MOCK = "env-mock"
_RULE_PROVIDER_KEY = "provider-key"
_RULE_BUDGET_ORDER = "budget-order"
_WARNING_PROVIDER_KEY_UNCOVERED = "provider-key-uncovered"

# ---------------------------------------------------------------------------
# 规则 2 的可扩展结构：真实通道 → 其密钥字段名。
#
# 今天只有 deepseek 有密钥字段。**为某个通道加上密钥字段时，必须同时做三件事**：
#   ① `Settings` 增加该字段；② `.env.example` 增加 `AICORE_<字段名大写>`；
#   ③ 在本映射里登记一行——不登记，该通道的密钥缺失就不会被启动校验拦住。
# 字段名写进映射而不是写死判断，是为了让「密钥缺失」这条规则对通道保持中立：
# 新增通道只改数据，不改规则逻辑。
# ---------------------------------------------------------------------------
_REAL_PROVIDER_KEY_FIELDS: Mapping[str, str] = {"deepseek": "deepseek_api_key"}

# 已知**尚未声明**密钥字段的真实通道（`cloud_vision` / `cloud_ocr`）。
#
# 为什么不给它们凭空造一个密钥字段：本任务的范围是校验既有字段，新增字段等于假造接口契约
# （真实接入时字段名、是否必填、是否走另一套鉴权都还没定），且会让 `.env.example` 与
# 字段表用例一起改动。代价是规则 2 现在**无法核验**这两个通道的凭据——这个缺口不静默：
# 构造时会打告警（`[告警：provider-key-uncovered]`），运维看得到。
#
# 本集合与上面的映射必须**恰好**覆盖 `provider` 字面量里的全部真实通道（不含 mock）：
# tests/unit/test_config_startup.py 的结构用例强制这一点，新增通道必须择一登记，
# 不存在第三种「没人管」的类别。
_REAL_PROVIDERS_WITHOUT_KEY_FIELD: frozenset[str] = frozenset({"cloud_vision", "cloud_ocr"})

# pydantic 给 `ValueError` 系错误自动加的前缀，渲染诊断信息时去掉（只为可读，不改判定）。
_PYDANTIC_VALUE_ERROR_PREFIX = "Value error, "


def _is_blank(value: object) -> bool:
    """密钥是否等于「没配」：`None`、空串、纯空白都算没配。

    不给任何形式的空凭据放行（`AICORE_DEEPSEEK_API_KEY=` 这种「以为配了」最容易被漏掉）。
    只看「空不空」，MUST NOT 回显取值。
    """
    return not (isinstance(value, str) and value.strip())


def _env_var_name(field_name: str) -> str:
    """字段名 → 环境变量名（运维可直接照着改的环境变量，不含任何取值）。"""
    prefix = str(Settings.model_config.get("env_prefix", ""))
    return f"{prefix}{field_name.upper()}"


def _strip_value_error_prefix(message: str) -> str:
    """去掉 pydantic 的 `Value error, ` 前缀（跨字段消息自带 `[跨字段：...]` 标记）。"""
    return message.removeprefix(_PYDANTIC_VALUE_ERROR_PREFIX)


def _summarize_validation_error(exc: ValidationError) -> tuple[str, ...]:
    """从 `ValidationError` 提取**可安全打印**的逐条摘要。

    硬约束：只读 `loc` 与 `msg` 两个键。`errors()` 的元素还带 `input`——它携带**其它字段**
    的原始值（含 `mysql_password`），`str(exc)` 也会回显 `input_value`；两者一旦进入摘要，
    启动日志就等于把口令写进了日志文件。
    """
    items: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = _strip_value_error_prefix(str(error["msg"]))
        if location:
            # 字段级错误点名具体字段。
            items.append(f"[字段级] {location}：{message}")
        else:
            # 跨字段错误：`model_validator(mode="after")` 一次只能抛一个异常，故它的 msg 是
            # 一份**逐行的阻断项清单**，这里拆成独立的条目——否则「共 N 项」会把 3 条
            # 阻断项数成 1 条，与运维实际要修的数量对不上。
            items.extend(line for line in message.splitlines() if line.strip())
    return tuple(items)


class ConfigRejected(Exception):  # noqa: N818 —— 类名由任务简报 / 计划钉死为 ConfigRejected
    """启动期配置校验失败：**拒绝启动**，携带不含密钥的阻断项清单。

    与 pydantic 的分工：`Settings` 的校验器照 pydantic 的方式抛 `ValidationError`
    （不与之对抗），启动期由本类把它转成「可直接打印、不含密钥、且列全所有阻断项」的异常——
    运维不必改一条、重启一次、再看下一条。

    转换入口是 `ConfigRejected.from_validation_error`，Task 2.6 的 lifespan 启动钩子这样用它：

        try:
            settings = get_settings()
        except ValidationError as exc:
            raise ConfigRejected.from_validation_error(exc) from exc

    `items` 为逐条阻断项（字段级带字段名，跨字段带 `[跨字段：<代号>]`），`str(exc)` 为渲染后的
    多行摘要。本类 MUST NOT 携带原始配置值（构造它的唯一入口已经保证了这一点）。
    """

    def __init__(self, items: Sequence[str]) -> None:
        self.items: tuple[str, ...] = tuple(items)
        super().__init__(self._render(self.items))

    @staticmethod
    def _render(items: Sequence[str]) -> str:
        """把阻断项渲染成给运维看的多行摘要（一行一项，避免长句糊成一团）。"""
        lines = [f"AICORE 启动配置校验未通过，进程拒绝启动（共 {len(items)} 项阻断项）："]
        lines.extend(f"  - {item}" for item in items)
        lines.append("  同一环境的阻断项已一次性列全；按上述逐项修正后重启即可。")
        return "\n".join(lines)

    @classmethod
    def from_validation_error(cls, exc: ValidationError) -> ConfigRejected:
        """把 `ValidationError` 转成 `ConfigRejected`（**只取 `loc` / `msg`**）。

        返回异常对象而**不抛出**：调用方（lifespan）用 `raise ... from exc` 保留因果链，
        测试也能在不触发启动的前提下检查摘要内容。
        """
        return cls(_summarize_validation_error(exc))


class _UnknownEnvVarSource(PydanticBaseSettingsSource):
    """把**未被任何字段消费**的 `AICORE_*` 环境变量作为「多余项」交给 `extra="forbid"` 判定。

    为什么需要这个源（实测，非推断）：pydantic-settings 2.15 的 `EnvSettingsSource` 只遍历
    `model_fields`（`sources/providers/env.py` 无 extra 分支），故 `os.environ` 里的未识别变量
    **会被静默忽略**——恰是硬规则 2 要防的「以为配了其实没配」。对照之下 `.env` 文件一侧由
    `DotEnvSettingsSource.__call__` 把未识别键原样交给 pydantic，`extra="forbid"` 能判错；
    本类把环境变量一侧补齐，使两条路径行为一致（升级 pydantic-settings 后若上游自带该能力，
    本源最多重复产出同一批键，不会改变结论）。

    只产出「未识别的 `AICORE_*`」键（大小写不敏感比对，与 `case_sensitive=False` 同口径），
    不提供任何真实字段值，因此不参与取值优先级竞争。
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """本源不做逐字段取值，值的判定见 `__call__`。"""
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        prefix = str(self.settings_cls.model_config.get("env_prefix", "")).lower()
        if not prefix:
            # 无前缀时无法区分「本服务的变量」与「环境里的全部变量」，故一个键都不产出。
            return {}
        known = {f"{prefix}{name}".lower() for name in self.settings_cls.model_fields}
        return {
            name: value
            for name, value in os.environ.items()
            if name.lower().startswith(prefix) and name.lower() not in known
        }


class Settings(BaseSettings):
    """AICORE 全部配置项；字段名对应 `AICORE_` 前缀的环境变量（大小写不敏感）。

    必填项（数据库、Redis、通道、内部凭据、配额与预算阈值）**刻意没有默认值**：
    缺失时必须当场报错，而不是拿占位值跑起来、把问题推迟到运行期。
    """

    model_config = SettingsConfigDict(
        env_prefix="AICORE_",
        case_sensitive=False,
        extra="forbid",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """在默认来源之后追加「未识别环境变量」检查源。

        顺序即优先级（靠前者优先）：本源排最后，且只产出未识别键，不会覆盖真实字段值。
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            _UnknownEnvVarSource(settings_cls),
        )

    # ---- 应用与环境 ----
    app_name: str = "aicore"
    env: Env = "dev"
    log_level: str = "INFO"

    # ---- MySQL（host / user / password / database 必填）----
    mysql_host: str
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_user: str
    mysql_password: str
    mysql_database: str

    # ---- Redis ----
    redis_host: str
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)

    # ---- 模型通道 ----
    provider: Literal["mock", "deepseek", "cloud_vision", "cloud_ocr"]
    deepseek_api_key: str | None = None

    # ---- 内部凭据与配额 / 预算护栏（阈值类必填）----
    internal_token: str = Field(min_length=1)
    daily_quota_per_account: int = Field(ge=1)
    daily_budget_total: int = Field(ge=1)
    budget_alert_ratio: float = Field(default=0.8, gt=0, lt=1)
    budget_degrade_ratio: float = Field(default=1.0, gt=0, le=1)
    concurrency_limit: int = Field(default=4, ge=1)
    lease_ms: int = Field(default=30000, ge=1)
    max_retries: int = Field(default=3, ge=0)

    @property
    def mysql_dsn(self) -> str:
        """可安全写日志的 MySQL 目标串（**不含口令**）。

        仅供日志与排障（例如启动时打印目标库）；真实连接由后续任务用
        `mysql_password` 单独拼接。MUST NOT 在本串里回填口令。
        """
        return (
            f"mysql+pymysql://{self.mysql_user}@{self.mysql_host}:{self.mysql_port}"
            f"/{self.mysql_database}?charset=utf8mb4"
        )

    # ---- 启动四条校验的跨字段部分（规则 1 / 2 / 3 + 预算阈值顺序）----
    @model_validator(mode="after")
    def _reject_invalid_startup_combination(self) -> Self:
        """跨字段规则：违规即抛 `ValidationError`（由启动期转成 `ConfigRejected`）。

        为什么是 `mode="after"`：它只在字段级校验全部通过后运行，于是「必填项缺失」
        （规则 4）永远走字段级报错、不会与本校验器的结论混在一起——两类错误的
        `loc` / `type` 因此始终不同（见模块 docstring 的判别方式）。

        多条阻断项**先收集、再一次性抛出**：`model_validator(mode="after")` 只能抛一个异常，
        故把全部阻断项拼进同一条消息，运维一轮就能看到全部问题，而不是逐条试错重启。

        告警只在**没有被阻断**时发出：一个已经被拒绝的配置不值得再对它的降级行为告警。
        """
        blockers: list[str] = []

        # 规则 1：生产环境不允许 mock 通道（D3）——否则生产会静默跑在模拟实现上。
        if self.env == "prod" and self.provider == _MOCK_PROVIDER:
            blockers.append(
                f"[跨字段：{_RULE_ENV_MOCK}] 生产环境不允许 mock 通道："
                f"env=prod 且 provider=mock；请把 AICORE_PROVIDER 指向真实通道并配置其密钥"
            )

        # 规则 2：真实通道被选中但其密钥没配——任何环境都拒绝（生产尤其不允许「无密钥」运行）。
        key_field = _REAL_PROVIDER_KEY_FIELDS.get(self.provider)
        if key_field is not None and _is_blank(getattr(self, key_field)):
            blockers.append(
                f"[跨字段：{_RULE_PROVIDER_KEY}] 真实通道缺少密钥："
                f"provider={self.provider} 要求 {_env_var_name(key_field)} 非空"
                f"（生产不允许以「无密钥」状态运行）"
            )

        # Task 2.1 遗留的跨字段边界：降级阈值低于告警阈值 = 先降级后告警，顺序颠倒。
        # （字段级只保证 0 < alert < 1、0 < degrade ≤ 1，管不到两者的相对关系。）
        if self.budget_degrade_ratio < self.budget_alert_ratio:
            blockers.append(
                f"[跨字段：{_RULE_BUDGET_ORDER}] 预算阈值顺序颠倒："
                f"budget_degrade_ratio={self.budget_degrade_ratio} 低于 "
                f"budget_alert_ratio={self.budget_alert_ratio}；"
                f"降级阈值必须不小于告警阈值，否则会先降级、后告警"
            )

        if blockers:
            # 纯文本、无原始取值：消息由字段名、枚举值与阈值数字（非密钥）拼成。
            raise ValueError("\n".join(blockers))

        self._warn_on_mock_fallback()
        self._warn_on_uncovered_channel_credentials()
        return self

    def _warn_on_mock_fallback(self) -> None:
        """规则 3：`dev` / `test` 允许降级 `mock`，但必须留痕（不阻断）。"""
        if self.env in _NON_PROD_ENVS and self.provider == _MOCK_PROVIDER:
            _logger.warning(
                "[告警：%s] env=%s 使用 mock 通道：模型能力为模拟实现，仅供开发与自测；"
                "生产（env=prod）会直接拒绝该组合",
                _RULE_ENV_MOCK,
                self.env,
            )

    def _warn_on_uncovered_channel_credentials(self) -> None:
        """规则 2 覆盖不到的真实通道**必须显式告警**，而不是静默放行。

        两条分支对应两种情形：已登记的「暂无密钥字段」通道（今天的 `cloud_vision` /
        `cloud_ocr`），以及新增后忘了登记到 `_REAL_PROVIDER_KEY_FIELDS` /
        `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 的通道。两种都不阻断，但都不静默。
        """
        if self.provider == _MOCK_PROVIDER or self.provider in _REAL_PROVIDER_KEY_FIELDS:
            return
        if self.provider in _REAL_PROVIDERS_WITHOUT_KEY_FIELD:
            _logger.warning(
                "[告警：%s] provider=%s 尚未声明密钥字段：启动校验无法核验其凭据，"
                "生产部署前请人工确认该通道凭据已就位",
                _WARNING_PROVIDER_KEY_UNCOVERED,
                self.provider,
            )
            return
        _logger.warning(
            "[告警：%s] provider=%s 未登记在任何一张通道表里：其密钥缺失不会被启动校验拦住，"
            "请为其登记密钥字段（_REAL_PROVIDER_KEY_FIELDS）或显式标注无密钥字段"
            "（_REAL_PROVIDERS_WITHOUT_KEY_FIELD）",
            _WARNING_PROVIDER_KEY_UNCOVERED,
            self.provider,
        )


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的 `Settings`（首次调用时构建）。

    构建失败即抛 `ValidationError`：缺必填项、写了不存在的 `AICORE_*`、或跨字段规则
    不通过都会在这里暴露。启动期由 Task 2.6 的 lifespan 钩子转成 `ConfigRejected`
    （`ConfigRejected.from_validation_error`）——本函数**刻意不自己包装**：
    pydantic 的校验就是抛 `ValidationError`，在此处再包一层会让「配置错误」与
    「校验器用法错误」两种异常在同一处混起来。缓存使「配置只解析一次」可断言。
    """
    # mypy 按 pydantic 合成的 `__init__` 签名要求显式传入全部必填项，但 BaseSettings 的值本就
    # 来自环境变量 / `.env`（这正是本模型存在的意义），故必须放宽这一条。ignore 是窄口径的
    # （只覆盖 call-arg），且 mypy strict 的 warn-unused-ignores 保证它一旦不再需要就会报错。
    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    """清空 `get_settings()` 的缓存（测试与配置重载路径用）。"""
    get_settings.cache_clear()
