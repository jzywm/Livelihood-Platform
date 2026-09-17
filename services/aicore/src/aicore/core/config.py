"""配置模型（Pydantic Settings）。

两条硬取向（`design.md` L250）：

1. **必填项一律不给默认值**——默认值会把配置错误隐藏到运行时；
2. **`extra="forbid"`**——写了不存在的配置项要报错，而非默默忽略（「以为配了其实没配」）。

字段级与跨字段的分工：本模块只放**字段级**约束（必填 / 数值边界 / 枚举），
跨字段的「启动四条校验」（prod 配 mock、真实通道缺密钥等）属 Task 2.2，
由它补 `model_validator(mode="after")`——两类错误的报告因此始终分得清。
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# 运行环境：dev | test | prod。Task 2.2 的跨字段规则复用本别名。
type Env = Literal["dev", "test", "prod"]


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


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的 `Settings`（首次调用时构建）。

    构建失败即抛 `ValidationError`：缺必填项或写了不存在的 `AICORE_*` 都会在这里暴露
    （是否包装成启动期异常由 Task 2.2 决定）。缓存使「配置只解析一次」可断言。
    """
    # mypy 按 pydantic 合成的 `__init__` 签名要求显式传入全部必填项，但 BaseSettings 的值本就
    # 来自环境变量 / `.env`（这正是本模型存在的意义），故必须放宽这一条。ignore 是窄口径的
    # （只覆盖 call-arg），且 mypy strict 的 warn-unused-ignores 保证它一旦不再需要就会报错。
    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    """清空 `get_settings()` 的缓存（测试与配置重载路径用）。"""
    get_settings.cache_clear()
