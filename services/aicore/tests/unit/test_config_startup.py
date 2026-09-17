"""启动四条校验（Task 2.2）的契约用例：跨字段规则、告警机制与诊断信息的安全性。

与 `test_config.py`（Task 2.1）的分工——两类错误在测试层面也必须分得清：

- 那里断言**字段级**失败：`loc` 指向具体字段、`type` 取 pydantic 内建值（`missing` 等）；
- 这里断言**跨字段**失败：`loc == ()`、`type == "value_error"`、消息逐行带 `[跨字段：<代号>]`，
  外加「两类错误分得清」本身，以及「诊断信息不含任何密钥」。

隔离与残留：所有用例都显式构造 `Settings(_env_file=None, ...)`（只让本地 `.env` 失效，
不换别的配置文件），并先清空进程里的 `AICORE_*`（`monkeypatch` 负责还原）；
不碰 `get_settings()` 的进程级缓存，故用例之间不通过进程状态互相影响。
取值一律 `test_*` / `SENTINEL_*` 占位符，MUST NOT 出现真实凭据。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Literal, get_args

import pytest
from pydantic import ValidationError

from aicore.core import config as config_module
from aicore.core.config import ConfigRejected, Settings
from aicore.main import create_app

# 规则 3 的告警走本模块的 stdlib 日志器；名字取自模块本身，避免与实现漂移。
CONFIG_LOGGER = config_module.__name__

# ---------------------------------------------------------------------------
# 秘密哨兵：只要出现在诊断信息里就说明用例失败。
# 值本身刻意「一眼假」，使断言不依赖任何真实凭据；同时用作**阴性对照**的探针
# （见 test_cross_field_diagnostics_never_leak_secret_values）。
# ---------------------------------------------------------------------------
PASSWORD_SENTINEL = "SENTINEL_PASSWORD_DO_NOT_LEAK"
TOKEN_SENTINEL = "SENTINEL_INTERNAL_TOKEN_DO_NOT_LEAK"
CHANNEL_KEY_SENTINEL = "SENTINEL_DEEPSEEK_KEY_DO_NOT_LEAK"
SECRET_SENTINELS = (PASSWORD_SENTINEL, TOKEN_SENTINEL, CHANNEL_KEY_SENTINEL)

# 真实通道的 `test_*` 占位密钥（MUST NOT 使用真实密钥）。
TEST_DEEPSEEK_KEY = "test_deepseek_placeholder"

# 基线环境（与 conftest 注入同名同值，此处独立列出，使本文件不依赖 conftest 的内部实现）。
# 不含 AICORE_ENV：`env` 默认 dev，正是规则 3 要覆盖的场景之一，用例按需显式覆盖。
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
    """清掉进程里已有的 `AICORE_*`（含开发者本机导出的、以及 conftest 注入的）。"""
    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
        monkeypatch.delenv(name)


def _apply_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """铺一份干净的基线环境。"""
    _clear_aicore_env(monkeypatch)
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)


def build_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    env_extra: Mapping[str, str] | None = None,
    **overrides: object,
) -> Settings:
    """在干净的基线环境上构造 `Settings`，可用关键字参数覆盖任意字段。

    `env_extra` 在铺完基线**之后**才写入——顺序很关键：`_apply_base_env` 会清掉进程里
    全部 `AICORE_*`，先设的密钥会被它抹掉（这正是本参数的由来）。
    构造参数 `overrides` 的优先级高于环境变量。
    """
    _apply_base_env(monkeypatch)
    for name, value in (env_extra or {}).items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None, **overrides)


def _skip_env_var(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """铺基线环境，但**不设**某个字段对应的环境变量（用于制造字段级缺失）。"""
    _clear_aicore_env(monkeypatch)
    for name, value in BASE_ENV.items():
        if name != f"AICORE_{field.upper()}":
            monkeypatch.setenv(name, value)


def _assert_no_secret(text: str, *, context: str) -> None:
    """断言 `text` 里不含任何秘密哨兵。"""
    leaked = [sentinel for sentinel in SECRET_SENTINELS if sentinel in text]
    assert not leaked, f"{context} 泄漏了凭据：{leaked}"


# ---------------------------------------------------------------------------
# 接口契约：ConfigRejected
# ---------------------------------------------------------------------------


def test_config_rejected_is_importable_and_separate_from_validation_error() -> None:
    """`ConfigRejected` 从 `aicore.core.config` 可取，且与 pydantic 的错误**不同类**。

    两者分工：`Settings` 的校验器抛 `ValidationError`（pydantic 的做法，不对抗），
    启动期由 `ConfigRejected.from_validation_error` 转成「可直接打印」的异常。
    """
    assert issubclass(ConfigRejected, Exception)
    assert not issubclass(ConfigRejected, ValidationError)
    assert callable(ConfigRejected.from_validation_error)


def test_config_rejected_lists_every_item() -> None:
    """摘要必须**逐条**列出全部阻断项，并给出准确条数。"""
    rejected = ConfigRejected(["甲项阻断", "乙项阻断"])

    assert rejected.items == ("甲项阻断", "乙项阻断")
    assert "甲项阻断" in str(rejected)
    assert "乙项阻断" in str(rejected)
    assert "共 2 项阻断项" in str(rejected)


# ---------------------------------------------------------------------------
# 规则 1：env=prod 且 provider=mock → 拒绝启动
# ---------------------------------------------------------------------------


def test_prod_with_mock_is_rejected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """生产配 mock 必须被拒绝，且错误可归因到跨字段规则（不是字段级）。"""
    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)

    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, env="prod", provider="mock")

    errors = excinfo.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
    assert "[跨字段：env-mock]" in errors[0]["msg"]
    assert "env=prod" in errors[0]["msg"] and "provider=mock" in errors[0]["msg"]

    rejected = ConfigRejected.from_validation_error(excinfo.value)
    assert "[跨字段：env-mock]" in str(rejected)
    # 已被拒绝的配置不再对「降级 mock」告警：告警只在放行的组合上出现。
    assert "[告警：env-mock]" not in caplog.text


@pytest.mark.parametrize("provider", ["cloud_vision", "cloud_ocr"])
def test_prod_with_keyless_real_channel_is_not_blocked_but_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
) -> None:
    """`cloud_*` 暂无密钥字段 → **不阻断**，但必须告警说明规则 2 覆盖不到它。

    这是本任务的显式取舍（不凭空给这两个通道造密钥字段）：缺口不静默，靠告警与
    结构性用例（见 test_every_real_provider_is_registered_in_a_channel_table）暴露。
    """
    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)

    settings = build_settings(monkeypatch, env="prod", provider=provider)

    assert settings.provider == provider
    assert "[告警：provider-key-uncovered]" in caplog.text
    assert provider in caplog.text


# ---------------------------------------------------------------------------
# 规则 2：真实通道被选中但密钥缺失 → 拒绝启动
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_real_channel_without_key_is_rejected_in_every_env(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """`deepseek` 没有密钥 → 任何环境都拒绝（生产尤其不允许「无密钥」运行）。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, env=env, provider="deepseek")

    errors = excinfo.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
    assert "[跨字段：provider-key]" in errors[0]["msg"]
    assert "provider=deepseek" in errors[0]["msg"]
    # 报错要给出可照做的环境变量名（而不是只报字段名）。
    assert "AICORE_DEEPSEEK_API_KEY" in errors[0]["msg"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    """空串 / 纯空白等于「没配」——`AICORE_DEEPSEEK_API_KEY=` 这种最容易被漏掉。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(
            monkeypatch,
            env_extra={"AICORE_DEEPSEEK_API_KEY": blank},
            provider="deepseek",
        )

    assert "[跨字段：provider-key]" in excinfo.value.errors()[0]["msg"]


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_real_channel_with_key_is_accepted(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    """真实通道 + 密钥 → 放行（含 prod，也是规则 1 的合法生产组合）。"""
    settings = build_settings(
        monkeypatch,
        env_extra={"AICORE_DEEPSEEK_API_KEY": TEST_DEEPSEEK_KEY},
        env=env,
        provider="deepseek",
    )

    assert settings.env == env
    assert settings.provider == "deepseek"


# ---------------------------------------------------------------------------
# 规则 3：dev / test 允许降级 mock，但必须告警（不阻断）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test"])
def test_mock_fallback_constructs_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, env: str
) -> None:
    """dev / test + mock：**构造成功**（不 raise），并通过日志留痕。"""
    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)

    settings = build_settings(monkeypatch, env=env, provider="mock")

    assert settings.env == env
    assert settings.provider == "mock"
    assert "[告警：env-mock]" in caplog.text
    assert f"env={env}" in caplog.text


def test_mock_fallback_warning_is_assertable_via_log_not_stdout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """告警机制选 stdlib `logging`：可被 `caplog` 断言，且**不往 stdout 打印**。

    选它而不是 `warnings.warn` 的理由见 `config.py` 模块 docstring：告警面向运维、
    属运行期事件，且 Task 2.6 的 structlog JSON 配置建在 stdlib logging 之上。
    """
    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)

    build_settings(monkeypatch, env="dev", provider="mock")

    assert "[告警：env-mock]" in caplog.text
    assert "[告警：env-mock]" not in capsys.readouterr().out


def test_real_channel_with_key_emits_no_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """阴性对照：dev + 真实通道 + 密钥不该产生任何本模块的告警。"""
    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)

    build_settings(
        monkeypatch,
        env_extra={"AICORE_DEEPSEEK_API_KEY": TEST_DEEPSEEK_KEY},
        env="dev",
        provider="deepseek",
    )

    assert [record for record in caplog.records if record.name == CONFIG_LOGGER] == []


# ---------------------------------------------------------------------------
# 预算阈值顺序（Task 2.1 遗留的跨字段边界）
# ---------------------------------------------------------------------------


def test_degrade_below_alert_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """降级阈值低于告警阈值 = 先降级后告警，顺序颠倒，必须拒绝。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, budget_alert_ratio=0.8, budget_degrade_ratio=0.5)

    errors = excinfo.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
    assert "[跨字段：budget-order]" in errors[0]["msg"]
    assert "budget_degrade_ratio=0.5" in errors[0]["msg"]
    assert "budget_alert_ratio=0.8" in errors[0]["msg"]


@pytest.mark.parametrize(
    ("alert", "degrade"),
    [
        (0.8, 0.8),  # 边界：相等允许（先告警、同时降级）
        (0.8, 1.0),  # 默认组合
        (0.0001, 0.9999),
    ],
)
def test_degrade_at_or_above_alert_is_accepted(
    monkeypatch: pytest.MonkeyPatch, alert: float, degrade: float
) -> None:
    """边界：`degrade >= alert` 一律放行——防止把 `>=` 写成 `>` 这类「偏严」错误。"""
    settings = build_settings(monkeypatch, budget_alert_ratio=alert, budget_degrade_ratio=degrade)

    assert settings.budget_alert_ratio == alert
    assert settings.budget_degrade_ratio == degrade


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("budget_degrade_ratio", 1.5, "less_than_equal"),
        ("budget_degrade_ratio", 0, "greater_than"),
        ("budget_alert_ratio", 0, "greater_than"),
        ("budget_alert_ratio", 1.5, "less_than"),
    ],
)
def test_single_field_bounds_are_still_field_level(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float, error_type: str
) -> None:
    """**不许把字段级边界搬进跨字段规则**：越界值仍须由字段级 `Field` 拒绝。

    Task 2.1 的边界若被本任务抄一遍，就会出现两套会各自漂移的口径；
    本用例盯住「loc 指向具体字段、type 是 pydantic 内建边界错」这两条特征。
    """
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, **{field: value})

    errors = excinfo.value.errors()
    assert [(error["type"], error["loc"]) for error in errors] == [(error_type, (field,))]


# ---------------------------------------------------------------------------
# 多条阻断项一次报全 / 两类错误可分辨
# ---------------------------------------------------------------------------


def test_all_cross_field_blockers_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """prod + mock **且** 阈值颠倒：两条都要出现在同一条摘要里（不许改一条重启一次）。"""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(monkeypatch, env="prod", provider="mock", budget_degrade_ratio=0.5)

    rejected = ConfigRejected.from_validation_error(excinfo.value)

    assert len(rejected.items) == 2
    assert "共 2 项阻断项" in str(rejected)
    assert "[跨字段：env-mock]" in str(rejected)
    assert "[跨字段：budget-order]" in str(rejected)


def test_all_field_level_blockers_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """字段级缺失同样一次报全（pydantic 收集全部字段错误），且每条点名自己的字段。"""
    _clear_aicore_env(monkeypatch)
    missing = ("mysql_user", "internal_token", "daily_budget_total")
    for name, value in BASE_ENV.items():
        if name not in {f"AICORE_{field.upper()}" for field in missing}:
            monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    rejected = ConfigRejected.from_validation_error(excinfo.value)

    assert len(rejected.items) == len(missing)
    assert "共 3 项阻断项" in str(rejected)
    for field in missing:
        assert f"[字段级] {field}：" in str(rejected)


def test_field_level_and_cross_field_failures_are_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两类错误必须能被程序分辨，而不只是「看起来不一样」。

    字段级：`type` 为 pydantic 内建值、`loc` 指向具体字段；
    跨字段：`type == "value_error"`、`loc == ()`、消息带 `[跨字段：<代号>]`、条数 = 阻断项条数。
    """
    _skip_env_var(monkeypatch, "mysql_user")
    with pytest.raises(ValidationError) as field_excinfo:
        Settings(_env_file=None)

    field_errors = field_excinfo.value.errors()
    assert [error["type"] for error in field_errors] == ["missing"]
    assert [error["loc"] for error in field_errors] == [("mysql_user",)]
    assert all(error["loc"] for error in field_errors), "字段级错误必须指向具体字段"

    with pytest.raises(ValidationError) as cross_excinfo:
        build_settings(monkeypatch, env="prod", provider="mock")

    cross_errors = cross_excinfo.value.errors()
    assert [(error["type"], error["loc"]) for error in cross_errors] == [("value_error", ())]
    assert "[跨字段：" in cross_errors[0]["msg"]

    # 两类错误在「渲染后的摘要」里也要分得开：字段级带 `[字段级] 字段名：`，跨字段带代号。
    assert "[字段级] mysql_user：" in str(ConfigRejected.from_validation_error(field_excinfo.value))
    assert "[字段级]" not in str(ConfigRejected.from_validation_error(cross_excinfo.value))


# ---------------------------------------------------------------------------
# 密钥安全：诊断信息可以直接打印
# ---------------------------------------------------------------------------


def test_cross_field_diagnostics_never_leak_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨字段失败时，诊断信息 MUST NOT 带出任何凭据。

    硬约束的来源：`ValidationError.errors()[i]["input"]` 携带**其它字段**的原始值
    （含 `mysql_password`），`str(exc)` 也会回显 `input_value`。故摘要只允许取 `loc` / `msg`。
    本用例先用哨兵证明「原始载荷确实带密钥」（否则断言就是空的），再断言我们的三条
    对外路径都不含它。
    """
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", TOKEN_SENTINEL)
    monkeypatch.setenv("AICORE_DEEPSEEK_API_KEY", CHANNEL_KEY_SENTINEL)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, env="prod", provider="mock", budget_degrade_ratio=0.5)
    exc = excinfo.value

    # 判别力对照：原始载荷里**确实**有哨兵，若这条不成立，下面的断言等于没测。
    raw_payload = repr([error.get("input") for error in exc.errors()])
    for sentinel in SECRET_SENTINELS:
        assert sentinel in raw_payload, (
            f"pydantic 的 errors()[i]['input'] 未携带 {sentinel}，本用例失去判别力"
        )

    rejected = ConfigRejected.from_validation_error(exc)
    _assert_no_secret(str(rejected), context="ConfigRejected 摘要")
    _assert_no_secret("\n".join(rejected.items), context="ConfigRejected 逐条阻断项")
    _assert_no_secret(
        "\n".join(f"{error['loc']}|{error['msg']}" for error in exc.errors()),
        context="由 ValidationError 的 loc/msg 派生的摘要",
    )
    # 非空对照：摘要确实给出了可操作的结论（不是因为它什么都没说才「不泄漏」）。
    assert "[跨字段：env-mock]" in str(rejected)
    assert "[跨字段：budget-order]" in str(rejected)


def test_field_level_diagnostics_never_leak_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """字段级失败同理：缺 `mysql_user` 时，口令与内部令牌都不得出现在摘要里。"""
    _skip_env_var(monkeypatch, "mysql_user")
    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", TOKEN_SENTINEL)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    exc = excinfo.value

    raw_payload = repr([error.get("input") for error in exc.errors()])
    assert PASSWORD_SENTINEL in raw_payload, "原始载荷应带口令哨兵，否则本用例失去判别力"

    rejected = ConfigRejected.from_validation_error(exc)
    _assert_no_secret(str(rejected), context="ConfigRejected 摘要")
    _assert_no_secret("\n".join(rejected.items), context="ConfigRejected 逐条阻断项")
    assert "[字段级] mysql_user：" in str(rejected)


# ---------------------------------------------------------------------------
# 规则 2 的覆盖面与组合根职责（结构性守卫）
# ---------------------------------------------------------------------------


def test_every_real_provider_is_registered_in_a_channel_table() -> None:
    """每个真实通道都必须「登记密钥字段」或「显式标注暂无密钥字段」——不存在第三种。

    这条用例是规则 2 的**决定性守卫**：日后给 `provider` 字面量加通道却忘了登记，
    这里立刻变红，而不是让新通道悄悄绕过凭据校验。
    """
    real_providers = set(get_args(Settings.model_fields["provider"].annotation)) - {"mock"}
    with_key_field = set(config_module._REAL_PROVIDER_KEY_FIELDS)
    without_key_field = set(config_module._REAL_PROVIDERS_WITHOUT_KEY_FIELD)

    assert with_key_field | without_key_field == real_providers, (
        f"未登记的通道：{real_providers - (with_key_field | without_key_field)}"
    )
    assert not (with_key_field & without_key_field), "同一通道不能既登记密钥字段又标注无密钥字段"
    for provider, field_name in config_module._REAL_PROVIDER_KEY_FIELDS.items():
        assert field_name in Settings.model_fields, f"{provider} 登记的字段 {field_name} 不存在"


def test_unregistered_real_channel_is_not_silently_accepted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """未登记的真实通道走「显式告警」分支，而不是静默放行。

    用一个把 `provider` 枚举加宽的 Settings 子类模拟「新增通道但忘了登记」：
    该分支在正常路径上不可达，却正是最需要被看见的缺口，故用子类把它钉住。
    """

    class _FutureChannelSettings(Settings):
        provider: Literal["mock", "deepseek", "cloud_vision", "cloud_ocr", "future_channel"]  # type: ignore[assignment]

    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
    _apply_base_env(monkeypatch)

    settings = _FutureChannelSettings(_env_file=None, provider="future_channel")

    assert settings.provider == "future_channel"
    assert "[告警：provider-key-uncovered]" in caplog.text
    assert "未登记在任何一张通道表里" in caplog.text


def test_create_app_does_not_read_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """组合根仍是**纯装配函数**：清空全部 `AICORE_*` 后 `create_app()` 依然可建实例。

    这是控制器对 Task 2.2 的裁定（校验放启动期 lifespan，不放工厂），本用例把它钉成回归：
    一旦有人在 `create_app()` 里读配置，缺配置时这里立刻变红。
    """
    _clear_aicore_env(monkeypatch)

    assert create_app() is not None
