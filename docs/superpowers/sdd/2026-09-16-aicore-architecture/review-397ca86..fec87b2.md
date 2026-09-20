# Review package 397ca86..fec87b2

## Commits

fec87b2 feat(aicore): 实现启动四条校验与配置拒绝异常

## Stat

 services/aicore/src/aicore/core/config.py         | 269 ++++++++++-
 services/aicore/tests/unit/test_config.py         |  34 +-
 services/aicore/tests/unit/test_config_startup.py | 518 ++++++++++++++++++++++
 3 files changed, 800 insertions(+), 21 deletions(-)

## Diff

```diff
diff --git a/services/aicore/src/aicore/core/config.py b/services/aicore/src/aicore/core/config.py
index f4ae347..de193fa 100644
--- a/services/aicore/src/aicore/core/config.py
+++ b/services/aicore/src/aicore/core/config.py
@@ -1,35 +1,198 @@
-"""配置模型（Pydantic Settings）。
+"""配置模型（Pydantic Settings）与启动四条校验。

 两条硬取向（`design.md` L250）：

 1. **必填项一律不给默认值**——默认值会把配置错误隐藏到运行时；
 2. **`extra="forbid"`**——写了不存在的配置项要报错，而非默默忽略（「以为配了其实没配」）。

-字段级与跨字段的分工：本模块只放**字段级**约束（必填 / 数值边界 / 枚举），
-跨字段的「启动四条校验」（prod 配 mock、真实通道缺密钥等）属 Task 2.2，
-由它补 `model_validator(mode="after")`——两类错误的报告因此始终分得清。
+字段级与跨字段的分工：字段级约束（必填 / 数值边界 / 枚举）是 `Field(...)` 的地盘，
+跨字段规则在 `Settings._reject_invalid_startup_combination`（`model_validator(mode="after")`）——
+两类错误的报告因此始终分得清（见下表）。
+
+## 启动四条校验（`design.md` L245~250）
+
+| 规则 | 判定 | 承担者 |
+|---|---|---|
+| 1. `env=prod` 且 `provider=mock` | 拒绝启动 | 跨字段（本模块） |
+| 2. 真实通道被选中但密钥缺失 | 拒绝启动 | 跨字段（本模块） |
+| 3. `dev` / `test` 降级 `mock` | 放行 + **告警**（不阻断） | 跨字段（本模块） |
+| 4. 必填项缺失 | 拒绝启动、**不兜默认值** | 字段级（Task 2.1） |
+
+规则 4 刻意不在这里重复实现：字段级失败时 pydantic **不会**进入 after 校验器，
+两类错误天然分开；在此再写一遍边界判断只会造出第二套会漂移的口径。
+
+**两类错误的判别方式**（运维排查最忌「到底哪错了」说不清）：
+
+- **字段级**：`loc` 指向具体字段（如 `("mysql_user",)`），`type` 取 pydantic 内建值
+  （`missing` / `literal_error` / `less_than_equal` / `extra_forbidden` …）；
+- **跨字段**：`loc == ()`、`type == "value_error"`，且 `msg` 逐行以 `[跨字段：<代号>]` 开头
+  （代号 `env-mock` / `provider-key` / `budget-order`）；告警以 `[告警：<代号>]` 开头。
+
+**密钥安全（硬约束）**：`ValidationError.input` 与 `repr(Settings)` 都携带其它字段的原始值
+（含 `mysql_password`）。故生成诊断信息时**只取 `loc` 与 `msg`**——见
+`ConfigRejected.from_validation_error`；MUST NOT 拼接 `.input`、`str(exc)` 或 `repr(settings)`，
+启动日志必须可以原样打印。
+
+**告警机制（规则 3）**：用 `logging.getLogger(__name__).warning(...)`，不阻断、不 `print`。
+选它而非 `warnings.warn` 的理由：① 这是面向运维的运行期事件，不是面向开发者的 API 弃用提示，
+语义上属于日志；② Task 2.6 的 structlog JSON 配置建在 stdlib `logging` 之上，stdlib 记录会被
+一并收编，换成 `warnings` 反而要另接一路；③ 测试侧可用 pytest `caplog` 直接断言，
+且 pytest 自己会给根日志器挂处理器，`logging.lastResort` 不会触发，正常测试运行不往
+stdout / stderr 打东西。
+
+**谁来抛 `ConfigRejected`**：本模块的校验器只抛 pydantic 的 `ValidationError`（不与之对抗），
+转换发生在**启动期**——组合根的 lifespan 钩子（Task 2.6）：
+
+    try:
+        settings = get_settings()
+    except ValidationError as exc:
+        raise ConfigRejected.from_validation_error(exc) from exc
+
+`create_app()` MUST NOT 读配置（Task 1.4 的验收项：工厂是纯装配函数）。
 """

 from __future__ import annotations

+import logging
 import os
+from collections.abc import Mapping, Sequence
 from functools import lru_cache
-from typing import Any, Literal
+from typing import Any, Literal, Self

-from pydantic import Field
+from pydantic import Field, ValidationError, model_validator
 from pydantic.fields import FieldInfo
 from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

-# 运行环境：dev | test | prod。Task 2.2 的跨字段规则复用本别名。
+# 运行环境：dev | test | prod。跨字段规则复用本别名。
 type Env = Literal["dev", "test", "prod"]

+_logger = logging.getLogger(__name__)
+
+# 通道口径：mock 是唯一的「非真实」通道；真实通道的凭据必须可核验（见规则 2）。
+_MOCK_PROVIDER = "mock"
+_NON_PROD_ENVS: frozenset[str] = frozenset({"dev", "test"})
+
+# 跨字段规则 / 告警的代号：出现在消息里，供运维与用例精确匹配。
+_RULE_ENV_MOCK = "env-mock"
+_RULE_PROVIDER_KEY = "provider-key"
+_RULE_BUDGET_ORDER = "budget-order"
+_WARNING_PROVIDER_KEY_UNCOVERED = "provider-key-uncovered"
+
+# ---------------------------------------------------------------------------
+# 规则 2 的可扩展结构：真实通道 → 其密钥字段名。
+#
+# 今天只有 deepseek 有密钥字段。**为某个通道加上密钥字段时，必须同时做三件事**：
+#   ① `Settings` 增加该字段；② `.env.example` 增加 `AICORE_<字段名大写>`；
+#   ③ 在本映射里登记一行——不登记，该通道的密钥缺失就不会被启动校验拦住。
+# 字段名写进映射而不是写死判断，是为了让「密钥缺失」这条规则对通道保持中立：
+# 新增通道只改数据，不改规则逻辑。
+# ---------------------------------------------------------------------------
+_REAL_PROVIDER_KEY_FIELDS: Mapping[str, str] = {"deepseek": "deepseek_api_key"}
+
+# 已知**尚未声明**密钥字段的真实通道（`cloud_vision` / `cloud_ocr`）。
+#
+# 为什么不给它们凭空造一个密钥字段：本任务的范围是校验既有字段，新增字段等于假造接口契约
+# （真实接入时字段名、是否必填、是否走另一套鉴权都还没定），且会让 `.env.example` 与
+# 字段表用例一起改动。代价是规则 2 现在**无法核验**这两个通道的凭据——这个缺口不静默：
+# 构造时会打告警（`[告警：provider-key-uncovered]`），运维看得到。
+#
+# 本集合与上面的映射必须**恰好**覆盖 `provider` 字面量里的全部真实通道（不含 mock）：
+# tests/unit/test_config_startup.py 的结构用例强制这一点，新增通道必须择一登记，
+# 不存在第三种「没人管」的类别。
+_REAL_PROVIDERS_WITHOUT_KEY_FIELD: frozenset[str] = frozenset({"cloud_vision", "cloud_ocr"})
+
+# pydantic 给 `ValueError` 系错误自动加的前缀，渲染诊断信息时去掉（只为可读，不改判定）。
+_PYDANTIC_VALUE_ERROR_PREFIX = "Value error, "
+
+
+def _is_blank(value: object) -> bool:
+    """密钥是否等于「没配」：`None`、空串、纯空白都算没配。
+
+    不给任何形式的空凭据放行（`AICORE_DEEPSEEK_API_KEY=` 这种「以为配了」最容易被漏掉）。
+    只看「空不空」，MUST NOT 回显取值。
+    """
+    return not (isinstance(value, str) and value.strip())
+
+
+def _env_var_name(field_name: str) -> str:
+    """字段名 → 环境变量名（运维可直接照着改的环境变量，不含任何取值）。"""
+    prefix = str(Settings.model_config.get("env_prefix", ""))
+    return f"{prefix}{field_name.upper()}"
+
+
+def _strip_value_error_prefix(message: str) -> str:
+    """去掉 pydantic 的 `Value error, ` 前缀（跨字段消息自带 `[跨字段：...]` 标记）。"""
+    return message.removeprefix(_PYDANTIC_VALUE_ERROR_PREFIX)
+
+
+def _summarize_validation_error(exc: ValidationError) -> tuple[str, ...]:
+    """从 `ValidationError` 提取**可安全打印**的逐条摘要。
+
+    硬约束：只读 `loc` 与 `msg` 两个键。`errors()` 的元素还带 `input`——它携带**其它字段**
+    的原始值（含 `mysql_password`），`str(exc)` 也会回显 `input_value`；两者一旦进入摘要，
+    启动日志就等于把口令写进了日志文件。
+    """
+    items: list[str] = []
+    for error in exc.errors():
+        location = ".".join(str(part) for part in error["loc"])
+        message = _strip_value_error_prefix(str(error["msg"]))
+        if location:
+            # 字段级错误点名具体字段。
+            items.append(f"[字段级] {location}：{message}")
+        else:
+            # 跨字段错误：`model_validator(mode="after")` 一次只能抛一个异常，故它的 msg 是
+            # 一份**逐行的阻断项清单**，这里拆成独立的条目——否则「共 N 项」会把 3 条
+            # 阻断项数成 1 条，与运维实际要修的数量对不上。
+            items.extend(line for line in message.splitlines() if line.strip())
+    return tuple(items)
+
+
+class ConfigRejected(Exception):  # noqa: N818 —— 类名由任务简报 / 计划钉死为 ConfigRejected
+    """启动期配置校验失败：**拒绝启动**，携带不含密钥的阻断项清单。
+
+    与 pydantic 的分工：`Settings` 的校验器照 pydantic 的方式抛 `ValidationError`
+    （不与之对抗），启动期由本类把它转成「可直接打印、不含密钥、且列全所有阻断项」的异常——
+    运维不必改一条、重启一次、再看下一条。
+
+    转换入口是 `ConfigRejected.from_validation_error`，Task 2.6 的 lifespan 启动钩子这样用它：
+
+        try:
+            settings = get_settings()
+        except ValidationError as exc:
+            raise ConfigRejected.from_validation_error(exc) from exc
+
+    `items` 为逐条阻断项（字段级带字段名，跨字段带 `[跨字段：<代号>]`），`str(exc)` 为渲染后的
+    多行摘要。本类 MUST NOT 携带原始配置值（构造它的唯一入口已经保证了这一点）。
+    """
+
+    def __init__(self, items: Sequence[str]) -> None:
+        self.items: tuple[str, ...] = tuple(items)
+        super().__init__(self._render(self.items))
+
+    @staticmethod
+    def _render(items: Sequence[str]) -> str:
+        """把阻断项渲染成给运维看的多行摘要（一行一项，避免长句糊成一团）。"""
+        lines = [f"AICORE 启动配置校验未通过，进程拒绝启动（共 {len(items)} 项阻断项）："]
+        lines.extend(f"  - {item}" for item in items)
+        lines.append("  同一环境的阻断项已一次性列全；按上述逐项修正后重启即可。")
+        return "\n".join(lines)
+
+    @classmethod
+    def from_validation_error(cls, exc: ValidationError) -> ConfigRejected:
+        """把 `ValidationError` 转成 `ConfigRejected`（**只取 `loc` / `msg`**）。
+
+        返回异常对象而**不抛出**：调用方（lifespan）用 `raise ... from exc` 保留因果链，
+        测试也能在不触发启动的前提下检查摘要内容。
+        """
+        return cls(_summarize_validation_error(exc))
+

 class _UnknownEnvVarSource(PydanticBaseSettingsSource):
     """把**未被任何字段消费**的 `AICORE_*` 环境变量作为「多余项」交给 `extra="forbid"` 判定。

     为什么需要这个源（实测，非推断）：pydantic-settings 2.15 的 `EnvSettingsSource` 只遍历
     `model_fields`（`sources/providers/env.py` 无 extra 分支），故 `os.environ` 里的未识别变量
     **会被静默忽略**——恰是硬规则 2 要防的「以为配了其实没配」。对照之下 `.env` 文件一侧由
     `DotEnvSettingsSource.__call__` 把未识别键原样交给 pydantic，`extra="forbid"` 能判错；
     本类把环境变量一侧补齐，使两条路径行为一致（升级 pydantic-settings 后若上游自带该能力，
     本源最多重复产出同一批键，不会改变结论）。
@@ -127,27 +290,115 @@ class Settings(BaseSettings):
         """可安全写日志的 MySQL 目标串（**不含口令**）。

         仅供日志与排障（例如启动时打印目标库）；真实连接由后续任务用
         `mysql_password` 单独拼接。MUST NOT 在本串里回填口令。
         """
         return (
             f"mysql+pymysql://{self.mysql_user}@{self.mysql_host}:{self.mysql_port}"
             f"/{self.mysql_database}?charset=utf8mb4"
         )

+    # ---- 启动四条校验的跨字段部分（规则 1 / 2 / 3 + 预算阈值顺序）----
+    @model_validator(mode="after")
+    def _reject_invalid_startup_combination(self) -> Self:
+        """跨字段规则：违规即抛 `ValidationError`（由启动期转成 `ConfigRejected`）。
+
+        为什么是 `mode="after"`：它只在字段级校验全部通过后运行，于是「必填项缺失」
+        （规则 4）永远走字段级报错、不会与本校验器的结论混在一起——两类错误的
+        `loc` / `type` 因此始终不同（见模块 docstring 的判别方式）。
+
+        多条阻断项**先收集、再一次性抛出**：`model_validator(mode="after")` 只能抛一个异常，
+        故把全部阻断项拼进同一条消息，运维一轮就能看到全部问题，而不是逐条试错重启。
+
+        告警只在**没有被阻断**时发出：一个已经被拒绝的配置不值得再对它的降级行为告警。
+        """
+        blockers: list[str] = []
+
+        # 规则 1：生产环境不允许 mock 通道（D3）——否则生产会静默跑在模拟实现上。
+        if self.env == "prod" and self.provider == _MOCK_PROVIDER:
+            blockers.append(
+                f"[跨字段：{_RULE_ENV_MOCK}] 生产环境不允许 mock 通道："
+                f"env=prod 且 provider=mock；请把 AICORE_PROVIDER 指向真实通道并配置其密钥"
+            )
+
+        # 规则 2：真实通道被选中但其密钥没配——任何环境都拒绝（生产尤其不允许「无密钥」运行）。
+        key_field = _REAL_PROVIDER_KEY_FIELDS.get(self.provider)
+        if key_field is not None and _is_blank(getattr(self, key_field)):
+            blockers.append(
+                f"[跨字段：{_RULE_PROVIDER_KEY}] 真实通道缺少密钥："
+                f"provider={self.provider} 要求 {_env_var_name(key_field)} 非空"
+                f"（生产不允许以「无密钥」状态运行）"
+            )
+
+        # Task 2.1 遗留的跨字段边界：降级阈值低于告警阈值 = 先降级后告警，顺序颠倒。
+        # （字段级只保证 0 < alert < 1、0 < degrade ≤ 1，管不到两者的相对关系。）
+        if self.budget_degrade_ratio < self.budget_alert_ratio:
+            blockers.append(
+                f"[跨字段：{_RULE_BUDGET_ORDER}] 预算阈值顺序颠倒："
+                f"budget_degrade_ratio={self.budget_degrade_ratio} 低于 "
+                f"budget_alert_ratio={self.budget_alert_ratio}；"
+                f"降级阈值必须不小于告警阈值，否则会先降级、后告警"
+            )
+
+        if blockers:
+            # 纯文本、无原始取值：消息由字段名、枚举值与阈值数字（非密钥）拼成。
+            raise ValueError("\n".join(blockers))
+
+        self._warn_on_mock_fallback()
+        self._warn_on_uncovered_channel_credentials()
+        return self
+
+    def _warn_on_mock_fallback(self) -> None:
+        """规则 3：`dev` / `test` 允许降级 `mock`，但必须留痕（不阻断）。"""
+        if self.env in _NON_PROD_ENVS and self.provider == _MOCK_PROVIDER:
+            _logger.warning(
+                "[告警：%s] env=%s 使用 mock 通道：模型能力为模拟实现，仅供开发与自测；"
+                "生产（env=prod）会直接拒绝该组合",
+                _RULE_ENV_MOCK,
+                self.env,
+            )
+
+    def _warn_on_uncovered_channel_credentials(self) -> None:
+        """规则 2 覆盖不到的真实通道**必须显式告警**，而不是静默放行。
+
+        两条分支对应两种情形：已登记的「暂无密钥字段」通道（今天的 `cloud_vision` /
+        `cloud_ocr`），以及新增后忘了登记到 `_REAL_PROVIDER_KEY_FIELDS` /
+        `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 的通道。两种都不阻断，但都不静默。
+        """
+        if self.provider == _MOCK_PROVIDER or self.provider in _REAL_PROVIDER_KEY_FIELDS:
+            return
+        if self.provider in _REAL_PROVIDERS_WITHOUT_KEY_FIELD:
+            _logger.warning(
+                "[告警：%s] provider=%s 尚未声明密钥字段：启动校验无法核验其凭据，"
+                "生产部署前请人工确认该通道凭据已就位",
+                _WARNING_PROVIDER_KEY_UNCOVERED,
+                self.provider,
+            )
+            return
+        _logger.warning(
+            "[告警：%s] provider=%s 未登记在任何一张通道表里：其密钥缺失不会被启动校验拦住，"
+            "请为其登记密钥字段（_REAL_PROVIDER_KEY_FIELDS）或显式标注无密钥字段"
+            "（_REAL_PROVIDERS_WITHOUT_KEY_FIELD）",
+            _WARNING_PROVIDER_KEY_UNCOVERED,
+            self.provider,
+        )
+

 @lru_cache
 def get_settings() -> Settings:
     """返回进程内唯一的 `Settings`（首次调用时构建）。

-    构建失败即抛 `ValidationError`：缺必填项或写了不存在的 `AICORE_*` 都会在这里暴露
-    （是否包装成启动期异常由 Task 2.2 决定）。缓存使「配置只解析一次」可断言。
+    构建失败即抛 `ValidationError`：缺必填项、写了不存在的 `AICORE_*`、或跨字段规则
+    不通过都会在这里暴露。启动期由 Task 2.6 的 lifespan 钩子转成 `ConfigRejected`
+    （`ConfigRejected.from_validation_error`）——本函数**刻意不自己包装**：
+    pydantic 的校验就是抛 `ValidationError`，在此处再包一层会让「配置错误」与
+    「校验器用法错误」两种异常在同一处混起来。缓存使「配置只解析一次」可断言。
     """
     # mypy 按 pydantic 合成的 `__init__` 签名要求显式传入全部必填项，但 BaseSettings 的值本就
     # 来自环境变量 / `.env`（这正是本模型存在的意义），故必须放宽这一条。ignore 是窄口径的
     # （只覆盖 call-arg），且 mypy strict 的 warn-unused-ignores 保证它一旦不再需要就会报错。
     return Settings()  # type: ignore[call-arg]


 def clear_settings_cache() -> None:
     """清空 `get_settings()` 的缓存（测试与配置重载路径用）。"""
     get_settings.cache_clear()
diff --git a/services/aicore/tests/unit/test_config.py b/services/aicore/tests/unit/test_config.py
index cb73b11..944640e 100644
--- a/services/aicore/tests/unit/test_config.py
+++ b/services/aicore/tests/unit/test_config.py
@@ -9,20 +9,21 @@
 与开发者本地 `.env` 的隔离：两条路径都只让默认文件**失效**，不换成别的配置文件——
 - 直接构造：显式传 `_env_file=None`；
 - `get_settings()` 无构造参数：`monkeypatch.chdir(_NO_ENV_DIR)` 让相对路径 `.env` 落空。
 这样「本地有 `.env`、CI 没有」两种环境下结论一致，配置来源始终是环境变量。
 """

 from __future__ import annotations

 import os
 import re
+from collections.abc import Mapping
 from pathlib import Path
 from typing import get_args

 import pytest
 from pydantic import ValidationError
 from pydantic_settings import BaseSettings, SettingsConfigDict

 from aicore.core.config import Env, Settings, clear_settings_cache, get_settings

 # `get_settings()` 不接受构造参数，无法像直接构造那样传 `_env_file=None`，故改为切换 CWD：
@@ -100,27 +101,38 @@ def _clear_aicore_env(monkeypatch: pytest.MonkeyPatch) -> None:
         monkeypatch.delenv(name)


 def _apply_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
     """铺一份干净的基线环境。"""
     _clear_aicore_env(monkeypatch)
     for name, value in BASE_ENV.items():
         monkeypatch.setenv(name, value)


-def build_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
+def build_settings(
+    monkeypatch: pytest.MonkeyPatch,
+    *,
+    env_extra: Mapping[str, str] | None = None,
+    **overrides: object,
+) -> Settings:
     """在干净的基线环境上构造 `Settings`，可用关键字参数覆盖任意字段。

     `_env_file=None` 是显式构造参数（控制器裁定允许）：只让 `.env` 失效，
     不指向别的配置文件——缺失项用例因此不会因本地 `.env` 恰好有值而变绿。
+
+    `env_extra` 在铺完基线**之后**写入，顺序不能反：`_apply_base_env` 会清掉进程里
+    全部 `AICORE_*`，先设的值会被它抹掉（Task 2.2 起真实通道缺密钥即拒绝启动，
+    顺序错了「真实通道 + 密钥」的用例会以缺密钥的面目失败）。
     """
     _apply_base_env(monkeypatch)
+    for name, value in (env_extra or {}).items():
+        monkeypatch.setenv(name, value)
     return Settings(_env_file=None, **overrides)


 def _isolate_get_settings(monkeypatch: pytest.MonkeyPatch) -> None:
     """让无参数的 `get_settings()` 也脱离本地 `.env`：切到不含 `.env` 的目录。"""
     monkeypatch.chdir(_NO_ENV_DIR)
     # 隔离自检：该目录一旦出现 `.env`，隔离即失效——宁可显式失败，也不静默读本地配置。
     assert not Path(".env").exists(), f"隔离目录 {_NO_ENV_DIR} 出现 .env，缓存用例失去隔离"
     _apply_base_env(monkeypatch)

@@ -203,26 +215,25 @@ def test_missing_required_field_is_rejected(
     with pytest.raises(ValidationError) as excinfo:
         Settings(_env_file=None)

     errors = excinfo.value.errors()
     assert (missing,) in [err["loc"] for err in errors], (
         f"{missing} 缺失必须被判为必填缺失，实际错误：{errors}"
     )
     assert missing in str(excinfo.value), "错误信息里必须看得到缺失的字段名（供运维排查）"


-def _set_placeholder_deepseek_key(monkeypatch: pytest.MonkeyPatch) -> None:
-    """给真实通道塞一个 test_ 占位密钥（MUST NOT 使用真实密钥）。
-
-    走环境变量而非构造参数：这样「真实通道 + 密钥」的组合同时覆盖了 env 取值路径。
-    """
-    monkeypatch.setenv("AICORE_DEEPSEEK_API_KEY", "test_deepseek_placeholder")
+# 真实通道的占位密钥（MUST NOT 使用真实密钥）。注入方式只能是 `build_settings(env_extra=...)`：
+# 先 `monkeypatch.setenv` 再调 `build_settings` 等于没设——后者会先清空全部 `AICORE_*`
+# （原实现正是这样，于是「真实通道 + 密钥」的用例其实一个密钥都没给，直到 Task 2.2
+# 的规则 2「真实通道缺密钥即拒绝启动」落地才暴露出来）。
+DEEPSEEK_KEY_ENV: dict[str, str] = {"AICORE_DEEPSEEK_API_KEY": "test_deepseek_placeholder"}


 def test_guard_source_is_inert_without_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
     """`_UnknownEnvVarSource` 的两条自我保护：不提供字段值；无前缀时不产出任何键。

     两条分支在正常路径上不可达（前缀恒为 `AICORE_`），但不能删：前缀若被改空，
     环境里**所有**变量都会被判成多余项，服务将完全无法启动；而若本源开始提供字段值，
     取值优先级会被悄悄改变。故用直接调用把这两条边界钉住。
     """
     from aicore.core.config import _UnknownEnvVarSource
@@ -345,22 +356,21 @@ def test_boundary_values_are_accepted(
 ) -> None:
     """边界值必须被接受——防止把 `ge`/`le` 写成 `gt`/`lt` 这类「偏严」错误。"""
     settings = build_settings(monkeypatch, **{field: value})

     assert getattr(settings, field) == value


 @pytest.mark.parametrize("provider", ["mock", "deepseek", "cloud_vision", "cloud_ocr"])
 def test_provider_accepts_each_channel(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
     """四个通道枚举值都必须被接受（构造参数优先级高于注入的 `AICORE_PROVIDER`）。"""
-    _set_placeholder_deepseek_key(monkeypatch)
-    settings = build_settings(monkeypatch, provider=provider)
+    settings = build_settings(monkeypatch, env_extra=DEEPSEEK_KEY_ENV, provider=provider)

     assert settings.provider == provider


 def test_provider_rejects_unknown_channel(monkeypatch: pytest.MonkeyPatch) -> None:
     """未知通道必须被枚举拒绝，且错误指向 `provider`。"""
     with pytest.raises(ValidationError) as excinfo:
         build_settings(monkeypatch, provider="openai")

     assert ("provider",) in [err["loc"] for err in excinfo.value.errors()]
@@ -372,23 +382,23 @@ def test_provider_rejects_unknown_channel(monkeypatch: pytest.MonkeyPatch) -> No
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
-    if real_channel:
-        _set_placeholder_deepseek_key(monkeypatch)
-    settings = build_settings(monkeypatch, env=env, provider=provider)
+    # 走 `env_extra` 而不是先 `setenv`：`build_settings` 会先清空全部 `AICORE_*`。
+    extra = DEEPSEEK_KEY_ENV if real_channel else None
+    settings = build_settings(monkeypatch, env_extra=extra, env=env, provider=provider)

     assert settings.env == env


 def test_env_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
     """`env` 之外的取值必须被拒绝（如 staging）。"""
     with pytest.raises(ValidationError) as excinfo:
         build_settings(monkeypatch, env="staging")

     assert ("env",) in [err["loc"] for err in excinfo.value.errors()]
diff --git a/services/aicore/tests/unit/test_config_startup.py b/services/aicore/tests/unit/test_config_startup.py
new file mode 100644
index 0000000..8387db4
--- /dev/null
+++ b/services/aicore/tests/unit/test_config_startup.py
@@ -0,0 +1,518 @@
+"""启动四条校验（Task 2.2）的契约用例：跨字段规则、告警机制与诊断信息的安全性。
+
+与 `test_config.py`（Task 2.1）的分工——两类错误在测试层面也必须分得清：
+
+- 那里断言**字段级**失败：`loc` 指向具体字段、`type` 取 pydantic 内建值（`missing` 等）；
+- 这里断言**跨字段**失败：`loc == ()`、`type == "value_error"`、消息逐行带 `[跨字段：<代号>]`，
+  外加「两类错误分得清」本身，以及「诊断信息不含任何密钥」。
+
+隔离与残留：所有用例都显式构造 `Settings(_env_file=None, ...)`（只让本地 `.env` 失效，
+不换别的配置文件），并先清空进程里的 `AICORE_*`（`monkeypatch` 负责还原）；
+不碰 `get_settings()` 的进程级缓存，故用例之间不通过进程状态互相影响。
+取值一律 `test_*` / `SENTINEL_*` 占位符，MUST NOT 出现真实凭据。
+"""
+
+from __future__ import annotations
+
+import logging
+import os
+from collections.abc import Mapping
+from typing import Literal, get_args
+
+import pytest
+from pydantic import ValidationError
+
+from aicore.core import config as config_module
+from aicore.core.config import ConfigRejected, Settings
+from aicore.main import create_app
+
+# 规则 3 的告警走本模块的 stdlib 日志器；名字取自模块本身，避免与实现漂移。
+CONFIG_LOGGER = config_module.__name__
+
+# ---------------------------------------------------------------------------
+# 秘密哨兵：只要出现在诊断信息里就说明用例失败。
+# 值本身刻意「一眼假」，使断言不依赖任何真实凭据；同时用作**阴性对照**的探针
+# （见 test_cross_field_diagnostics_never_leak_secret_values）。
+# ---------------------------------------------------------------------------
+PASSWORD_SENTINEL = "SENTINEL_PASSWORD_DO_NOT_LEAK"
+TOKEN_SENTINEL = "SENTINEL_INTERNAL_TOKEN_DO_NOT_LEAK"
+CHANNEL_KEY_SENTINEL = "SENTINEL_DEEPSEEK_KEY_DO_NOT_LEAK"
+SECRET_SENTINELS = (PASSWORD_SENTINEL, TOKEN_SENTINEL, CHANNEL_KEY_SENTINEL)
+
+# 真实通道的 `test_*` 占位密钥（MUST NOT 使用真实密钥）。
+TEST_DEEPSEEK_KEY = "test_deepseek_placeholder"
+
+# 基线环境（与 conftest 注入同名同值，此处独立列出，使本文件不依赖 conftest 的内部实现）。
+# 不含 AICORE_ENV：`env` 默认 dev，正是规则 3 要覆盖的场景之一，用例按需显式覆盖。
+BASE_ENV: dict[str, str] = {
+    "AICORE_MYSQL_HOST": "127.0.0.1",
+    "AICORE_MYSQL_USER": "test_user",
+    "AICORE_MYSQL_PASSWORD": "test_password",
+    "AICORE_MYSQL_DATABASE": "aicore_test",
+    "AICORE_REDIS_HOST": "127.0.0.1",
+    "AICORE_PROVIDER": "mock",
+    "AICORE_INTERNAL_TOKEN": "test_internal_token",
+    "AICORE_DAILY_QUOTA_PER_ACCOUNT": "1000",
+    "AICORE_DAILY_BUDGET_TOTAL": "100000",
+}
+
+
+def _clear_aicore_env(monkeypatch: pytest.MonkeyPatch) -> None:
+    """清掉进程里已有的 `AICORE_*`（含开发者本机导出的、以及 conftest 注入的）。"""
+    for name in [name for name in os.environ if name.upper().startswith("AICORE_")]:
+        monkeypatch.delenv(name)
+
+
+def _apply_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
+    """铺一份干净的基线环境。"""
+    _clear_aicore_env(monkeypatch)
+    for name, value in BASE_ENV.items():
+        monkeypatch.setenv(name, value)
+
+
+def build_settings(
+    monkeypatch: pytest.MonkeyPatch,
+    *,
+    env_extra: Mapping[str, str] | None = None,
+    **overrides: object,
+) -> Settings:
+    """在干净的基线环境上构造 `Settings`，可用关键字参数覆盖任意字段。
+
+    `env_extra` 在铺完基线**之后**才写入——顺序很关键：`_apply_base_env` 会清掉进程里
+    全部 `AICORE_*`，先设的密钥会被它抹掉（这正是本参数的由来）。
+    构造参数 `overrides` 的优先级高于环境变量。
+    """
+    _apply_base_env(monkeypatch)
+    for name, value in (env_extra or {}).items():
+        monkeypatch.setenv(name, value)
+    return Settings(_env_file=None, **overrides)
+
+
+def _skip_env_var(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
+    """铺基线环境，但**不设**某个字段对应的环境变量（用于制造字段级缺失）。"""
+    _clear_aicore_env(monkeypatch)
+    for name, value in BASE_ENV.items():
+        if name != f"AICORE_{field.upper()}":
+            monkeypatch.setenv(name, value)
+
+
+def _assert_no_secret(text: str, *, context: str) -> None:
+    """断言 `text` 里不含任何秘密哨兵。"""
+    leaked = [sentinel for sentinel in SECRET_SENTINELS if sentinel in text]
+    assert not leaked, f"{context} 泄漏了凭据：{leaked}"
+
+
+# ---------------------------------------------------------------------------
+# 接口契约：ConfigRejected
+# ---------------------------------------------------------------------------
+
+
+def test_config_rejected_is_importable_and_separate_from_validation_error() -> None:
+    """`ConfigRejected` 从 `aicore.core.config` 可取，且与 pydantic 的错误**不同类**。
+
+    两者分工：`Settings` 的校验器抛 `ValidationError`（pydantic 的做法，不对抗），
+    启动期由 `ConfigRejected.from_validation_error` 转成「可直接打印」的异常。
+    """
+    assert issubclass(ConfigRejected, Exception)
+    assert not issubclass(ConfigRejected, ValidationError)
+    assert callable(ConfigRejected.from_validation_error)
+
+
+def test_config_rejected_lists_every_item() -> None:
+    """摘要必须**逐条**列出全部阻断项，并给出准确条数。"""
+    rejected = ConfigRejected(["甲项阻断", "乙项阻断"])
+
+    assert rejected.items == ("甲项阻断", "乙项阻断")
+    assert "甲项阻断" in str(rejected)
+    assert "乙项阻断" in str(rejected)
+    assert "共 2 项阻断项" in str(rejected)
+
+
+# ---------------------------------------------------------------------------
+# 规则 1：env=prod 且 provider=mock → 拒绝启动
+# ---------------------------------------------------------------------------
+
+
+def test_prod_with_mock_is_rejected(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
+) -> None:
+    """生产配 mock 必须被拒绝，且错误可归因到跨字段规则（不是字段级）。"""
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(monkeypatch, env="prod", provider="mock")
+
+    errors = excinfo.value.errors()
+    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
+    assert "[跨字段：env-mock]" in errors[0]["msg"]
+    assert "env=prod" in errors[0]["msg"] and "provider=mock" in errors[0]["msg"]
+
+    rejected = ConfigRejected.from_validation_error(excinfo.value)
+    assert "[跨字段：env-mock]" in str(rejected)
+    # 已被拒绝的配置不再对「降级 mock」告警：告警只在放行的组合上出现。
+    assert "[告警：env-mock]" not in caplog.text
+
+
+@pytest.mark.parametrize("provider", ["cloud_vision", "cloud_ocr"])
+def test_prod_with_keyless_real_channel_is_not_blocked_but_warns(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider: str
+) -> None:
+    """`cloud_*` 暂无密钥字段 → **不阻断**，但必须告警说明规则 2 覆盖不到它。
+
+    这是本任务的显式取舍（不凭空给这两个通道造密钥字段）：缺口不静默，靠告警与
+    结构性用例（见 test_every_real_provider_is_registered_in_a_channel_table）暴露。
+    """
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+
+    settings = build_settings(monkeypatch, env="prod", provider=provider)
+
+    assert settings.provider == provider
+    assert "[告警：provider-key-uncovered]" in caplog.text
+    assert provider in caplog.text
+
+
+# ---------------------------------------------------------------------------
+# 规则 2：真实通道被选中但密钥缺失 → 拒绝启动
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize("env", ["dev", "test", "prod"])
+def test_real_channel_without_key_is_rejected_in_every_env(
+    monkeypatch: pytest.MonkeyPatch, env: str
+) -> None:
+    """`deepseek` 没有密钥 → 任何环境都拒绝（生产尤其不允许「无密钥」运行）。"""
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(monkeypatch, env=env, provider="deepseek")
+
+    errors = excinfo.value.errors()
+    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
+    assert "[跨字段：provider-key]" in errors[0]["msg"]
+    assert "provider=deepseek" in errors[0]["msg"]
+    # 报错要给出可照做的环境变量名（而不是只报字段名）。
+    assert "AICORE_DEEPSEEK_API_KEY" in errors[0]["msg"]
+
+
+@pytest.mark.parametrize("blank", ["", "   "])
+def test_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
+    """空串 / 纯空白等于「没配」——`AICORE_DEEPSEEK_API_KEY=` 这种最容易被漏掉。"""
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(
+            monkeypatch,
+            env_extra={"AICORE_DEEPSEEK_API_KEY": blank},
+            provider="deepseek",
+        )
+
+    assert "[跨字段：provider-key]" in excinfo.value.errors()[0]["msg"]
+
+
+@pytest.mark.parametrize("env", ["dev", "test", "prod"])
+def test_real_channel_with_key_is_accepted(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
+    """真实通道 + 密钥 → 放行（含 prod，也是规则 1 的合法生产组合）。"""
+    settings = build_settings(
+        monkeypatch,
+        env_extra={"AICORE_DEEPSEEK_API_KEY": TEST_DEEPSEEK_KEY},
+        env=env,
+        provider="deepseek",
+    )
+
+    assert settings.env == env
+    assert settings.provider == "deepseek"
+
+
+# ---------------------------------------------------------------------------
+# 规则 3：dev / test 允许降级 mock，但必须告警（不阻断）
+# ---------------------------------------------------------------------------
+
+
+@pytest.mark.parametrize("env", ["dev", "test"])
+def test_mock_fallback_constructs_and_warns(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, env: str
+) -> None:
+    """dev / test + mock：**构造成功**（不 raise），并通过日志留痕。"""
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+
+    settings = build_settings(monkeypatch, env=env, provider="mock")
+
+    assert settings.env == env
+    assert settings.provider == "mock"
+    assert "[告警：env-mock]" in caplog.text
+    assert f"env={env}" in caplog.text
+
+
+def test_mock_fallback_warning_is_assertable_via_log_not_stdout(
+    monkeypatch: pytest.MonkeyPatch,
+    caplog: pytest.LogCaptureFixture,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """告警机制选 stdlib `logging`：可被 `caplog` 断言，且**不往 stdout 打印**。
+
+    选它而不是 `warnings.warn` 的理由见 `config.py` 模块 docstring：告警面向运维、
+    属运行期事件，且 Task 2.6 的 structlog JSON 配置建在 stdlib logging 之上。
+    """
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+
+    build_settings(monkeypatch, env="dev", provider="mock")
+
+    assert "[告警：env-mock]" in caplog.text
+    assert "[告警：env-mock]" not in capsys.readouterr().out
+
+
+def test_real_channel_with_key_emits_no_warning(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
+) -> None:
+    """阴性对照：dev + 真实通道 + 密钥不该产生任何本模块的告警。"""
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+
+    build_settings(
+        monkeypatch,
+        env_extra={"AICORE_DEEPSEEK_API_KEY": TEST_DEEPSEEK_KEY},
+        env="dev",
+        provider="deepseek",
+    )
+
+    assert [record for record in caplog.records if record.name == CONFIG_LOGGER] == []
+
+
+# ---------------------------------------------------------------------------
+# 预算阈值顺序（Task 2.1 遗留的跨字段边界）
+# ---------------------------------------------------------------------------
+
+
+def test_degrade_below_alert_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
+    """降级阈值低于告警阈值 = 先降级后告警，顺序颠倒，必须拒绝。"""
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(monkeypatch, budget_alert_ratio=0.8, budget_degrade_ratio=0.5)
+
+    errors = excinfo.value.errors()
+    assert [(error["type"], error["loc"]) for error in errors] == [("value_error", ())]
+    assert "[跨字段：budget-order]" in errors[0]["msg"]
+    assert "budget_degrade_ratio=0.5" in errors[0]["msg"]
+    assert "budget_alert_ratio=0.8" in errors[0]["msg"]
+
+
+@pytest.mark.parametrize(
+    ("alert", "degrade"),
+    [
+        (0.8, 0.8),  # 边界：相等允许（先告警、同时降级）
+        (0.8, 1.0),  # 默认组合
+        (0.0001, 0.9999),
+    ],
+)
+def test_degrade_at_or_above_alert_is_accepted(
+    monkeypatch: pytest.MonkeyPatch, alert: float, degrade: float
+) -> None:
+    """边界：`degrade >= alert` 一律放行——防止把 `>=` 写成 `>` 这类「偏严」错误。"""
+    settings = build_settings(monkeypatch, budget_alert_ratio=alert, budget_degrade_ratio=degrade)
+
+    assert settings.budget_alert_ratio == alert
+    assert settings.budget_degrade_ratio == degrade
+
+
+@pytest.mark.parametrize(
+    ("field", "value", "error_type"),
+    [
+        ("budget_degrade_ratio", 1.5, "less_than_equal"),
+        ("budget_degrade_ratio", 0, "greater_than"),
+        ("budget_alert_ratio", 0, "greater_than"),
+        ("budget_alert_ratio", 1.5, "less_than"),
+    ],
+)
+def test_single_field_bounds_are_still_field_level(
+    monkeypatch: pytest.MonkeyPatch, field: str, value: float, error_type: str
+) -> None:
+    """**不许把字段级边界搬进跨字段规则**：越界值仍须由字段级 `Field` 拒绝。
+
+    Task 2.1 的边界若被本任务抄一遍，就会出现两套会各自漂移的口径；
+    本用例盯住「loc 指向具体字段、type 是 pydantic 内建边界错」这两条特征。
+    """
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(monkeypatch, **{field: value})
+
+    errors = excinfo.value.errors()
+    assert [(error["type"], error["loc"]) for error in errors] == [(error_type, (field,))]
+
+
+# ---------------------------------------------------------------------------
+# 多条阻断项一次报全 / 两类错误可分辨
+# ---------------------------------------------------------------------------
+
+
+def test_all_cross_field_blockers_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
+    """prod + mock **且** 阈值颠倒：两条都要出现在同一条摘要里（不许改一条重启一次）。"""
+    with pytest.raises(ValidationError) as excinfo:
+        build_settings(monkeypatch, env="prod", provider="mock", budget_degrade_ratio=0.5)
+
+    rejected = ConfigRejected.from_validation_error(excinfo.value)
+
+    assert len(rejected.items) == 2
+    assert "共 2 项阻断项" in str(rejected)
+    assert "[跨字段：env-mock]" in str(rejected)
+    assert "[跨字段：budget-order]" in str(rejected)
+
+
+def test_all_field_level_blockers_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
+    """字段级缺失同样一次报全（pydantic 收集全部字段错误），且每条点名自己的字段。"""
+    _clear_aicore_env(monkeypatch)
+    missing = ("mysql_user", "internal_token", "daily_budget_total")
+    for name, value in BASE_ENV.items():
+        if name not in {f"AICORE_{field.upper()}" for field in missing}:
+            monkeypatch.setenv(name, value)
+
+    with pytest.raises(ValidationError) as excinfo:
+        Settings(_env_file=None)
+
+    rejected = ConfigRejected.from_validation_error(excinfo.value)
+
+    assert len(rejected.items) == len(missing)
+    assert "共 3 项阻断项" in str(rejected)
+    for field in missing:
+        assert f"[字段级] {field}：" in str(rejected)
+
+
+def test_field_level_and_cross_field_failures_are_distinguishable(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """两类错误必须能被程序分辨，而不只是「看起来不一样」。
+
+    字段级：`type` 为 pydantic 内建值、`loc` 指向具体字段；
+    跨字段：`type == "value_error"`、`loc == ()`、消息带 `[跨字段：<代号>]`、条数 = 阻断项条数。
+    """
+    _skip_env_var(monkeypatch, "mysql_user")
+    with pytest.raises(ValidationError) as field_excinfo:
+        Settings(_env_file=None)
+
+    field_errors = field_excinfo.value.errors()
+    assert [error["type"] for error in field_errors] == ["missing"]
+    assert [error["loc"] for error in field_errors] == [("mysql_user",)]
+    assert all(error["loc"] for error in field_errors), "字段级错误必须指向具体字段"
+
+    with pytest.raises(ValidationError) as cross_excinfo:
+        build_settings(monkeypatch, env="prod", provider="mock")
+
+    cross_errors = cross_excinfo.value.errors()
+    assert [(error["type"], error["loc"]) for error in cross_errors] == [("value_error", ())]
+    assert "[跨字段：" in cross_errors[0]["msg"]
+
+    # 两类错误在「渲染后的摘要」里也要分得开：字段级带 `[字段级] 字段名：`，跨字段带代号。
+    assert "[字段级] mysql_user：" in str(ConfigRejected.from_validation_error(field_excinfo.value))
+    assert "[字段级]" not in str(ConfigRejected.from_validation_error(cross_excinfo.value))
+
+
+# ---------------------------------------------------------------------------
+# 密钥安全：诊断信息可以直接打印
+# ---------------------------------------------------------------------------
+
+
+def test_cross_field_diagnostics_never_leak_secret_values(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """跨字段失败时，诊断信息 MUST NOT 带出任何凭据。
+
+    硬约束的来源：`ValidationError.errors()[i]["input"]` 携带**其它字段**的原始值
+    （含 `mysql_password`），`str(exc)` 也会回显 `input_value`。故摘要只允许取 `loc` / `msg`。
+    本用例先用哨兵证明「原始载荷确实带密钥」（否则断言就是空的），再断言我们的三条
+    对外路径都不含它。
+    """
+    _apply_base_env(monkeypatch)
+    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
+    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", TOKEN_SENTINEL)
+    monkeypatch.setenv("AICORE_DEEPSEEK_API_KEY", CHANNEL_KEY_SENTINEL)
+
+    with pytest.raises(ValidationError) as excinfo:
+        Settings(_env_file=None, env="prod", provider="mock", budget_degrade_ratio=0.5)
+    exc = excinfo.value
+
+    # 判别力对照：原始载荷里**确实**有哨兵，若这条不成立，下面的断言等于没测。
+    raw_payload = repr([error.get("input") for error in exc.errors()])
+    for sentinel in SECRET_SENTINELS:
+        assert sentinel in raw_payload, (
+            f"pydantic 的 errors()[i]['input'] 未携带 {sentinel}，本用例失去判别力"
+        )
+
+    rejected = ConfigRejected.from_validation_error(exc)
+    _assert_no_secret(str(rejected), context="ConfigRejected 摘要")
+    _assert_no_secret("\n".join(rejected.items), context="ConfigRejected 逐条阻断项")
+    _assert_no_secret(
+        "\n".join(f"{error['loc']}|{error['msg']}" for error in exc.errors()),
+        context="由 ValidationError 的 loc/msg 派生的摘要",
+    )
+    # 非空对照：摘要确实给出了可操作的结论（不是因为它什么都没说才「不泄漏」）。
+    assert "[跨字段：env-mock]" in str(rejected)
+    assert "[跨字段：budget-order]" in str(rejected)
+
+
+def test_field_level_diagnostics_never_leak_secret_values(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """字段级失败同理：缺 `mysql_user` 时，口令与内部令牌都不得出现在摘要里。"""
+    _skip_env_var(monkeypatch, "mysql_user")
+    monkeypatch.setenv("AICORE_MYSQL_PASSWORD", PASSWORD_SENTINEL)
+    monkeypatch.setenv("AICORE_INTERNAL_TOKEN", TOKEN_SENTINEL)
+
+    with pytest.raises(ValidationError) as excinfo:
+        Settings(_env_file=None)
+    exc = excinfo.value
+
+    raw_payload = repr([error.get("input") for error in exc.errors()])
+    assert PASSWORD_SENTINEL in raw_payload, "原始载荷应带口令哨兵，否则本用例失去判别力"
+
+    rejected = ConfigRejected.from_validation_error(exc)
+    _assert_no_secret(str(rejected), context="ConfigRejected 摘要")
+    _assert_no_secret("\n".join(rejected.items), context="ConfigRejected 逐条阻断项")
+    assert "[字段级] mysql_user：" in str(rejected)
+
+
+# ---------------------------------------------------------------------------
+# 规则 2 的覆盖面与组合根职责（结构性守卫）
+# ---------------------------------------------------------------------------
+
+
+def test_every_real_provider_is_registered_in_a_channel_table() -> None:
+    """每个真实通道都必须「登记密钥字段」或「显式标注暂无密钥字段」——不存在第三种。
+
+    这条用例是规则 2 的**决定性守卫**：日后给 `provider` 字面量加通道却忘了登记，
+    这里立刻变红，而不是让新通道悄悄绕过凭据校验。
+    """
+    real_providers = set(get_args(Settings.model_fields["provider"].annotation)) - {"mock"}
+    with_key_field = set(config_module._REAL_PROVIDER_KEY_FIELDS)
+    without_key_field = set(config_module._REAL_PROVIDERS_WITHOUT_KEY_FIELD)
+
+    assert with_key_field | without_key_field == real_providers, (
+        f"未登记的通道：{real_providers - (with_key_field | without_key_field)}"
+    )
+    assert not (with_key_field & without_key_field), "同一通道不能既登记密钥字段又标注无密钥字段"
+    for provider, field_name in config_module._REAL_PROVIDER_KEY_FIELDS.items():
+        assert field_name in Settings.model_fields, f"{provider} 登记的字段 {field_name} 不存在"
+
+
+def test_unregistered_real_channel_is_not_silently_accepted(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
+) -> None:
+    """未登记的真实通道走「显式告警」分支，而不是静默放行。
+
+    用一个把 `provider` 枚举加宽的 Settings 子类模拟「新增通道但忘了登记」：
+    该分支在正常路径上不可达，却正是最需要被看见的缺口，故用子类把它钉住。
+    """
+
+    class _FutureChannelSettings(Settings):
+        provider: Literal["mock", "deepseek", "cloud_vision", "cloud_ocr", "future_channel"]  # type: ignore[assignment]
+
+    caplog.set_level(logging.WARNING, logger=CONFIG_LOGGER)
+    _apply_base_env(monkeypatch)
+
+    settings = _FutureChannelSettings(_env_file=None, provider="future_channel")
+
+    assert settings.provider == "future_channel"
+    assert "[告警：provider-key-uncovered]" in caplog.text
+    assert "未登记在任何一张通道表里" in caplog.text
+
+
+def test_create_app_does_not_read_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
+    """组合根仍是**纯装配函数**：清空全部 `AICORE_*` 后 `create_app()` 依然可建实例。
+
+    这是控制器对 Task 2.2 的裁定（校验放启动期 lifespan，不放工厂），本用例把它钉成回归：
+    一旦有人在 `create_app()` 里读配置，缺配置时这里立刻变红。
+    """
+    _clear_aicore_env(monkeypatch)
+
+    assert create_app() is not None

```
