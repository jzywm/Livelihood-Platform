"""core/config.py（Pydantic Settings 配置模型）的字段级契约用例。

覆盖范围（Task 2.1）：必填项不给默认值、数值边界、枚举、`extra="forbid"`、
`get_settings()` 缓存与重建、`mysql_dsn` 不含口令。

**刻意不覆盖**跨字段的「启动四条校验」（prod + mock、真实通道缺密钥等）：那是 Task 2.2。
本文件只断言字段级失败，使两类错误在测试层面也分得清——字段级失败的错误 loc 指向具体字段。

与开发者本地 `.env` 的隔离：两条路径都只让默认文件**失效**，不换成别的配置文件——
- 直接构造：显式传 `_env_file=None`；
- `get_settings()` 无构造参数：`monkeypatch.chdir(_NO_ENV_DIR)` 让相对路径 `.env` 落空。
这样「本地有 `.env`、CI 没有」两种环境下结论一致，配置来源始终是环境变量。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from aicore.core.config import Env, Settings, clear_settings_cache, get_settings

# `get_settings()` 不接受构造参数，无法像直接构造那样传 `_env_file=None`，故改为切换 CWD：
# 本文件所在目录没有 `.env`，相对路径 `.env` 自然落空。
# 为什么不用 pytest 的 `tmp_path`：本项目的沙箱环境禁止在系统临时目录下建目录
# （`PermissionError: [WinError 5]`），而「切到仓库内既有的无 `.env` 目录」既能隔离又不写任何文件。
_NO_ENV_DIR = Path(__file__).resolve().parent

# `.env.example` 与字段表的一致性检查用（见 test_env_example_matches_field_names_one_to_one）。
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
_ENV_VAR_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# 设计文档字段表逐项固化：字段被增删或改名时本用例显式失败，而不是悄悄放行。
EXPECTED_FIELDS = frozenset(
    {
        "app_name",
        "env",
        "log_level",
        "mysql_host",
        "mysql_port",
        "mysql_user",
        "mysql_password",
        "mysql_database",
        "redis_host",
        "redis_port",
        "redis_db",
        "provider",
        "deepseek_api_key",
        "internal_token",
        "daily_quota_per_account",
        "daily_budget_total",
        "budget_alert_ratio",
        "budget_degrade_ratio",
        "concurrency_limit",
        "lease_ms",
        "max_retries",
    }
)

# 必填字段：MUST NOT 给默认值（硬规则 1）。
REQUIRED_FIELDS = (
    "mysql_host",
    "mysql_user",
    "mysql_password",
    "mysql_database",
    "redis_host",
    "provider",
    "internal_token",
    "daily_quota_per_account",
    "daily_budget_total",
)

# 基线环境（与 conftest 注入同名同值，此处独立列出，使本文件不依赖 conftest 的内部实现）。
# 不含 AICORE_ENV：`env` 的默认值 dev 本身就是要断言的内容（Task 2.2 允许 dev/test 配 mock）。
# 值一律 test_* 占位符，MUST NOT 出现真实凭据。
BASE_ENV: dict[str, str] = {
    "AICORE_MYSQL_HOST": "127.0.0.1",
    "AICORE_MYSQL_USER": "test_user",
    "AICORE_MYSQL_PASSWORD": "test_password",
    "AICORE_MYSQL_DATABASE": "aicore_test",
    "AICORE_REDIS_HOST": "127.0.0.1",
    "AICORE_PROVIDER": "mock",
    "AICORE_INTERNAL_TOKEN": "test_internal_token",
    "AICORE_DAILY_QUOTA_PER_ACCOUNT": "1000",
    "AICORE_DAILY_BUDGET_TOTAL": "100000",
}


def _clear_aicore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉进程里已有的 `AICORE_*`（含开发者本机导出的），使用例只看到本文件铺设的值。

    `monkeypatch` 保证用例结束后还原，不会把改动留给其他用例。
    """
    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
        monkeypatch.delenv(name)


def _apply_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """铺一份干净的基线环境。"""
    _clear_aicore_env(monkeypatch)
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)


def build_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    """在干净的基线环境上构造 `Settings`，可用关键字参数覆盖任意字段。

    `_env_file=None` 是显式构造参数（控制器裁定允许）：只让 `.env` 失效，
    不指向别的配置文件——缺失项用例因此不会因本地 `.env` 恰好有值而变绿。
    """
    _apply_base_env(monkeypatch)
    return Settings(_env_file=None, **overrides)


def _isolate_get_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """让无参数的 `get_settings()` 也脱离本地 `.env`：切到不含 `.env` 的目录。"""
    monkeypatch.chdir(_NO_ENV_DIR)
    # 隔离自检：该目录一旦出现 `.env`，隔离即失效——宁可显式失败，也不静默读本地配置。
    assert not Path(".env").exists(), f"隔离目录 {_NO_ENV_DIR} 出现 .env，缓存用例失去隔离"
    _apply_base_env(monkeypatch)


def test_is_base_settings_subclass() -> None:
    """接口契约：`Settings` 必须是 Pydantic `BaseSettings` 子类。"""
    assert issubclass(Settings, BaseSettings)


def test_field_set_matches_design_table() -> None:
    """字段集合与设计文档字段表一一对应。"""
    assert set(Settings.model_fields) == set(EXPECTED_FIELDS)


def test_env_example_matches_field_names_one_to_one() -> None:
    """`.env.example` 的 `AICORE_*` 变量与字段名一一对应（两个方向都会踩坑）。

    模板里多出未识别变量：复制成 `.env` 后直接被 `extra="forbid"` 拒绝，模板不可用；
    模板里缺少字段（尤其必填项）：复制后服务起不来。故用集合相等把两者钉在一起，
    新增字段时同步更新模板——这条用例的价值正在于此。
    """
    declared_all = set(_ENV_VAR_RE.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    declared = {name for name in declared_all if name.startswith("AICORE_")}
    expected = {f"AICORE_{name.upper()}" for name in Settings.model_fields}

    assert declared == expected, (
        f"模板多出：{sorted(declared - expected)}；模板缺少：{sorted(expected - declared)}"
    )
    # 非本服务前缀的键同样会被 `extra="forbid"` 拒绝：dotenv 源把未被任何字段消费的键
    # 原样交给 pydantic 判为多余项。故模板里不允许出现任何非 `AICORE_` 前缀的变量。
    assert declared_all == declared, f"模板含非本服务前缀变量：{sorted(declared_all - declared)}"


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_required_fields_have_no_default(field: str) -> None:
    """硬规则 1：必填项 MUST NOT 有默认值（默认值会把配置错误隐藏到运行时）。"""
    assert Settings.model_fields[field].is_required(), f"{field} 被给了默认值"


def test_model_config_pins_env_contract() -> None:
    """硬规则 2 的配置面：前缀、大小写不敏感、extra=forbid、本地 `.env` 读取。"""
    assert Settings.model_config["env_prefix"] == "AICORE_"
    assert Settings.model_config["case_sensitive"] is False
    assert Settings.model_config["extra"] == "forbid"
    assert Settings.model_config["env_file"] == ".env"
    assert Settings.model_config["env_file_encoding"] == "utf-8"


def test_defaults_are_applied_when_only_required_values_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只给必填项时，其余字段取文档默认值；`env` 默认 dev、`provider` 来自环境。"""
    settings = build_settings(monkeypatch)

    assert settings.env == "dev"
    assert settings.provider == "mock"
    assert settings.app_name == "aicore"
    assert settings.log_level == "INFO"
    assert settings.mysql_port == 3306
    assert settings.redis_port == 6379
    assert settings.redis_db == 0
    assert settings.deepseek_api_key is None
    assert settings.budget_alert_ratio == 0.8
    assert settings.budget_degrade_ratio == 1.0
    assert settings.concurrency_limit == 4
    assert settings.lease_ms == 30000
    assert settings.max_retries == 3


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_missing_required_field_is_rejected(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """必填项缺失 → `ValidationError`，且错误必须点名缺失的那一项。"""
    _clear_aicore_env(monkeypatch)
    for name, value in BASE_ENV.items():
        if name != f"AICORE_{missing.upper()}":
            monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    errors = excinfo.value.errors()
    assert (missing,) in [err["loc"] for err in errors], (
        f"{missing} 缺失必须被判为必填缺失，实际错误：{errors}"
    )
    assert missing in str(excinfo.value), "错误信息里必须看得到缺失的字段名（供运维排查）"


def _set_placeholder_deepseek_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """给真实通道塞一个 test_ 占位密钥（MUST NOT 使用真实密钥）。

    走环境变量而非构造参数：这样「真实通道 + 密钥」的组合同时覆盖了 env 取值路径。
    """
    monkeypatch.setenv("AICORE_DEEPSEEK_API_KEY", "test_deepseek_placeholder")


def test_guard_source_is_inert_without_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_UnknownEnvVarSource` 的两条自我保护：不提供字段值；无前缀时不产出任何键。

    两条分支在正常路径上不可达（前缀恒为 `AICORE_`），但不能删：前缀若被改空，
    环境里**所有**变量都会被判成多余项，服务将完全无法启动；而若本源开始提供字段值，
    取值优先级会被悄悄改变。故用直接调用把这两条边界钉住。
    """
    from aicore.core.config import _UnknownEnvVarSource

    class _NoPrefixSettings(Settings):
        model_config = SettingsConfigDict(env_prefix="")

    monkeypatch.setenv("UNRELATED_VARIABLE", "value")
    source = _UnknownEnvVarSource(_NoPrefixSettings)

    assert source() == {}
    assert source.get_field_value(Settings.model_fields["app_name"], "app_name") == (
        None,
        "app_name",
        False,
    )


def test_unknown_prefixed_env_var_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """硬规则 2：写了不存在的 `AICORE_*` 环境变量必须报错，而非默默忽略。

    实现说明（也是本用例的存在理由）：pydantic-settings 2.15 的 `EnvSettingsSource`
    只遍历已知字段，`os.environ` 中的未识别变量会被**静默忽略**；config.py 因此追加了一个
    只产出「未识别 `AICORE_*`」的 settings source，由 `extra="forbid"` 判定。本用例断言的
    正是这条链路，而不只是 `model_config["extra"]` 的取值。
    """
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("AICORE_NOT_A_REAL_SETTING", "typo")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    errors = excinfo.value.errors()
    extra_errors = [err for err in errors if err["type"] == "extra_forbidden"]
    assert extra_errors, f"未识别变量必须判为多余项，实际错误：{errors}"
    assert any("not_a_real_setting" in str(err["loc"][0]).lower() for err in extra_errors), (
        f"错误必须点名未识别的变量，实际：{extra_errors}"
    )


def test_unknown_unprefixed_env_var_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """边界：`extra="forbid"` 只管本服务的 `AICORE_` 前缀变量，不得误伤无关环境变量。"""
    expected = build_settings(monkeypatch)
    monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "value")

    assert Settings(_env_file=None).mysql_host == expected.mysql_host


def test_unknown_constructor_kwarg_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造函数路径同样受 `extra="forbid"` 管辖（Pydantic 内建行为，一并钉住）。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, not_a_real_field="typo")

    assert ("not_a_real_field",) in [err["loc"] for err in excinfo.value.errors()]


def test_lowercase_env_var_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """`case_sensitive=False`：全小写的 `aicore_mysql_user` 同样生效。"""
    _clear_aicore_env(monkeypatch)
    for name, value in BASE_ENV.items():
        if name != "AICORE_MYSQL_USER":
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("aicore_mysql_user", "test_lower_user")

    assert Settings(_env_file=None).mysql_user == "test_lower_user"


INVALID_BOUNDS: tuple[tuple[str, object], ...] = (
    ("mysql_port", 0),
    ("mysql_port", 70000),
    ("redis_port", 0),
    ("redis_port", 70000),
    ("redis_db", -1),
    ("daily_quota_per_account", 0),
    ("daily_budget_total", 0),
    ("budget_alert_ratio", 0),
    ("budget_alert_ratio", 1.5),
    ("budget_degrade_ratio", 0),
    ("budget_degrade_ratio", 1.5),
    ("concurrency_limit", 0),
    ("lease_ms", 0),
    ("max_retries", -1),
    ("internal_token", ""),
)


@pytest.mark.parametrize(("field", "value"), INVALID_BOUNDS)
def test_invalid_bound_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """越界值必须在字段级被拒绝，且错误 loc 指向该字段。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, **{field: value})

    locs = [err["loc"] for err in excinfo.value.errors()]
    assert (field,) in locs, f"{field}={value!r} 必须被字段级边界拒绝，实际错误：{locs}"


VALID_BOUNDS: tuple[tuple[str, object], ...] = (
    ("mysql_port", 1),
    ("mysql_port", 65535),
    ("redis_port", 1),
    ("redis_port", 65535),
    ("redis_db", 0),
    ("daily_quota_per_account", 1),
    ("daily_budget_total", 1),
    ("budget_alert_ratio", 0.0001),
    ("budget_alert_ratio", 0.9999),
    ("budget_degrade_ratio", 1.0),
    ("concurrency_limit", 1),
    ("lease_ms", 1),
    ("max_retries", 0),
    ("internal_token", "x"),
)


@pytest.mark.parametrize(("field", "value"), VALID_BOUNDS)
def test_boundary_values_are_accepted(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """边界值必须被接受——防止把 `ge`/`le` 写成 `gt`/`lt` 这类「偏严」错误。"""
    settings = build_settings(monkeypatch, **{field: value})

    assert getattr(settings, field) == value


@pytest.mark.parametrize("provider", ["mock", "deepseek", "cloud_vision", "cloud_ocr"])
def test_provider_accepts_each_channel(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    """四个通道枚举值都必须被接受（构造参数优先级高于注入的 `AICORE_PROVIDER`）。"""
    _set_placeholder_deepseek_key(monkeypatch)
    settings = build_settings(monkeypatch, provider=provider)

    assert settings.provider == provider


def test_provider_rejects_unknown_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知通道必须被枚举拒绝，且错误指向 `provider`。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, provider="openai")

    assert ("provider",) in [err["loc"] for err in excinfo.value.errors()]


@pytest.mark.parametrize(
    ("env", "provider", "real_channel"),
    [
        ("dev", "mock", False),
        ("test", "mock", False),
        # prod 用「真实通道 + 密钥」这一合法生产组合，避免与 Task 2.2 的生产规则相互干扰。
        ("prod", "deepseek", True),
    ],
)
def test_env_accepts_dev_test_prod(
    monkeypatch: pytest.MonkeyPatch, env: str, provider: str, real_channel: bool
) -> None:
    """`env` 接受 dev / test / prod 三值。"""
    if real_channel:
        _set_placeholder_deepseek_key(monkeypatch)
    settings = build_settings(monkeypatch, env=env, provider=provider)

    assert settings.env == env


def test_env_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """`env` 之外的取值必须被拒绝（如 staging）。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, env="staging")

    assert ("env",) in [err["loc"] for err in excinfo.value.errors()]


def test_env_alias_is_dev_test_prod() -> None:
    """`Env` 类型别名恰为三值字面量（Task 2.2 的跨字段规则复用该别名）。

    `type Env = ...`（PEP 695）的值需经 `__value__` 取回：Python 3.14 实测
    `get_args(Env)` 返回空元组，直接对别名取 args 会得到一条恒真的空断言。
    """
    assert set(get_args(Env.__value__)) == {"dev", "test", "prod"}


def test_get_settings_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_settings()` 带缓存：重复调用返回**同一实例**。"""
    _isolate_get_settings(monkeypatch)
    clear_settings_cache()
    try:
        first = get_settings()

        assert get_settings() is first
    finally:
        # 缓存是进程级状态，用例结束必须清掉，避免影响其他用例。
        clear_settings_cache()


def test_clear_settings_cache_rebuilds_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`clear_settings_cache()` 后必须真的重建：只有「对象不是同一个」不足以证明重读了环境。"""
    _isolate_get_settings(monkeypatch)
    clear_settings_cache()
    try:
        first = get_settings()
        assert first.mysql_user == "test_user"

        monkeypatch.setenv("AICORE_MYSQL_USER", "test_user_after_clear")
        assert get_settings() is first, "缓存期内必须复用旧实例"
        assert get_settings().mysql_user == "test_user", "缓存期内不应重读环境"

        clear_settings_cache()
        second = get_settings()
        assert second is not first
        assert second.mysql_user == "test_user_after_clear", "重建后必须读到新的环境值"
    finally:
        clear_settings_cache()


def test_mysql_dsn_names_target_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """`mysql_dsn` 可安全写日志：含 host / user / database，MUST NOT 含口令。"""
    dsn = build_settings(monkeypatch).mysql_dsn

    assert "127.0.0.1" in dsn
    assert "test_user" in dsn
    assert "aicore_test" in dsn
    assert "3306" in dsn
    assert "test_password" not in dsn, f"DSN 泄漏了口令：{dsn}"


def test_mysql_dsn_does_not_change_with_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """阴性对照：只改口令，DSN 必须逐字不变——证明口令没有以任何形式进入该串。"""
    first = build_settings(monkeypatch)
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", "test_password_rotated")
    second = Settings(_env_file=None)

    assert second.mysql_password == "test_password_rotated"
    assert second.mysql_dsn == first.mysql_dsn
