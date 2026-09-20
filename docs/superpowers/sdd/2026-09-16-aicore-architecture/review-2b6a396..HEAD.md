# Review package 2b6a396..HEAD

## Commits

ad1c341 docs(aicore): 计划中豁免指令改为不带 noqa 前缀的正式写法
f4f77c7 fix(aicore): 分层契约间接导入语义与结构检查评审修复

## Stat

 .../plans/2026-09-16-aicore-architecture.md        |  19 ++-
 services/aicore/.importlinter                      |  40 +++++
 services/aicore/src/aicore/service/desensitize.py  |   3 +-
 services/aicore/src/aicore/service/verdict.py      |   3 +-
 services/aicore/tests/structural/test_layering.py  | 171 +++++++++++++++++---
 .../aicore/tests/structural/test_source_guards.py  | 179 ++++++++++++++++++++-
 6 files changed, 382 insertions(+), 33 deletions(-)

## Diff

```diff
diff --git a/docs/superpowers/plans/2026-09-16-aicore-architecture.md b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
index 1804d2e..6f9d6ec 100644
--- a/docs/superpowers/plans/2026-09-16-aicore-architecture.md
+++ b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
@@ -440,34 +440,34 @@ git commit -m "chore: 搭建 AICORE 工程骨架与工具链"

 ```python
 """纠错回流与固定评估集回归。第 5 组实现。"""
 ```

 ```python
 """C8 权威回写前置条件。

 【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过人工结论的
 回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
-确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填，见修复轮 1 更正）。

 第 8 组实现具体回写入口；本任务仅建文件以保证结构检查从第一天起生效。
 """
 ```

 - [ ] **Step 8: 写 `service/desensitize.py`（规则 6 的受检文件，本任务必须建）**

 ```python
 """图像脱敏前置阶段。

 【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
 的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
-确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填，见修复轮 1 更正）。

 第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
 """
 ```

 - [ ] **Step 9: 写 `service/habit/` 与 `service/task/` 子包空壳**

 - `service/habit/__init__.py`：`"""习惯计算纯函数包（无 IO、无写库路径）。第 10 组实现。"""`
 - `service/habit/engine.py` / `decay.py` / `evidence.py`：各一行文档串
 - `service/task/__init__.py`：`"""任务类型策略注册表。第 4 组实现。"""`
@@ -819,52 +819,61 @@ print('.importlinter 已写入（UTF-8）')
 $root = "D:\progrom\services\aicore"
 Push-Location $root
 & "$root\.venv\Scripts\python.exe" -m pytest tests/structural/test_layering.py -v
 Pop-Location
 ```

 Expected: `2 passed`

 - [ ] **Step 5: 写规则 5、6 的 AST 扫描用例**

+> **修复轮 1 提示**：下面这段代码块是首版写法，规则 6 的扫描函数已被修复轮改写
+> （不再下探嵌套 def/lambda/class/内层 except）。以
+> `services/aicore/tests/structural/test_source_guards.py` 的实际内容为准，勿照抄本片段。**
+
 `tests/structural/test_source_guards.py`：

 ```python
 """结构扫描专项：import-linter 表达不了的两条合规红线。

 规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
 规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
         的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

 规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
-确需吞异常时必须写 `# noqa: ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
+确需吞异常时必须写 `# ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
+
+> **修复轮 1 更正（评审 M9）**：豁免指令的正式写法是 `# ai-allow-swallow: <理由>`（不带 `noqa:` 前缀），
+> 本文档下列片段已同步更新。早期口径 `# noqa: ai-allow-swallow: <理由>` 语法上仍被扫描接受，
+> 但 ruff 会把 `ai-allow-swallow` 当成 noqa 规则码，每次使用都打印一条 `Invalid # noqa directive` 警告，
+> 故新代码一律用不带前缀的正式写法。理由必填不变（裸指令不算豁免）。
 """

 from __future__ import annotations

 import ast
 import re
 from pathlib import Path

 import pytest

 PROJECT_ROOT = Path(__file__).resolve().parents[2]
 SRC = PROJECT_ROOT / "src" / "aicore"

 # 只允许在 provider/ 包内出现的模型调用库
 MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
 HTTP_IMPORT_RE = re.compile(
     r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
 )

 GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")
-SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")
+SWALLOW_EXEMPT = re.compile(r"#\s*ai-allow-swallow:\s*\S+")


 def iter_python_files() -> list[Path]:
     return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


 def find_swallowed_exceptions(source: str) -> list[int]:
     """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
     hits: list[int] = []
     tree = ast.parse(source)
@@ -893,21 +902,21 @@ def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
     path = SRC / relative
     source = path.read_text(encoding="utf-8")
     lines = source.splitlines()
     offenders = [
         lineno for lineno in find_swallowed_exceptions(source)
         if not SWALLOW_EXEMPT.search(lines[lineno - 1])
     ]
     assert not offenders, (
         f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
         f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
-        f"`# noqa: ai-allow-swallow: <理由>` 显式豁免。"
+        f"`# ai-allow-swallow: <理由>` 显式豁免。"
     )


 def test_guard_detects_swallowing(tmp_path: Path) -> None:
     """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
     bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
     good = "def f():\n    try:\n        return 1\n    except Exception as exc:\n        raise RuntimeError() from exc\n"
     assert find_swallowed_exceptions(bad) == [4]
     assert find_swallowed_exceptions(good) == []
 ```
diff --git a/services/aicore/.importlinter b/services/aicore/.importlinter
index d234012..8efb830 100644
--- a/services/aicore/.importlinter
+++ b/services/aicore/.importlinter
@@ -2,63 +2,103 @@
 root_package = aicore

 [importlinter:contract:api-no-repo-provider]
 name = api 层不得直接依赖 repository / provider
 type = forbidden
 source_modules =
     aicore.api
 forbidden_modules =
     aicore.repository
     aicore.provider
+# allow_indirect_imports = true：只禁止「直接依赖」，依据是设计原文本身。
+# design.md 禁止项 1 的措辞是「api/ MUST NOT **直接导入** repository/ 或 provider/——路由只调 service」，
+# 分层的允许方向是 api → service → {provider 抽象, repository, port}。
+# 而 forbidden 契约默认 false 会走 find_shortest_chains，把 api → service → repository
+# 这条**正是要放行的**路径判成违规。用默认值等于把架构本身钉成红灯。
+# 实测（api 只 import service、service 只 import repository，全树无 api → repository 直接导入）：
+#   默认 false => BROKEN，打印链路 pkg.api.routes -> pkg.service.svc / pkg.service.svc -> pkg.repository.repo
+#   true      => KEPT
+# 代价与兜底（已实测，非推断）：放开间接路径后，api 经由 service 间接触碰 repository / provider
+# 不再由本契约拦。逐条实测结论——不存在漏口：
+#   api → service → repository → provider.deepseek / provider.mock
+#        => 契约 2 BROKEN（service 间接导入 provider.* 仍违规，中间隔 repository 也拦得住）
+#   core → api → service
+#        => 契约 4 BROKEN（core 间接依赖业务层）
+#   repository → provider → service（反向两跳）
+#        => 契约 3 BROKEN（反向依赖 service，中间隔 provider 一样算）
+#   api → service → port（不触碰 provider/repository）
+#        => 4 kept，这正是设计要放行的路径（port 是 service 的合法出向边界）
+# 唯一被放开的形态是 api → service → provider.base：禁止项 2 明示合法（只依赖 Protocol），
+# 也正是 api 取模型的正常路径。
+allow_indirect_imports = true

 [importlinter:contract:service-provider-impl]
 name = service 层只可与 provider.base 交互，不得依赖具体通道实现
 type = forbidden
 source_modules =
     aicore.service
 forbidden_modules =
+    # 含 aicore.provider 整包：provider/__init__.py 若再导出「非 aicore.provider.*」的符号
+    # （例：from aicore.port.x import …），service `import aicore.provider` 就会拿到它，
+    # 而这条边（service -> aicore.provider）不等于任何具体实现的模块名，只列下面 5 个实现模块会漏掉。
+    # 实测对照（临时探针：门面再导出 aicore.port.facade_probe，service 写 `import aicore.provider`）：
+    #   未列 aicore.provider => 4 kept（漏判）；列了 => 契约 2 BROKEN。见 test_provider_facade_reexport_is_forbidden。
+    # 门面若只再导出 aicore.provider.mock 之类，间接链路本就能查到（会打印两跳链路），
+    # 但那依赖"实现模块被逐个列全"；列出整包让这条防线不依赖枚举的完备性。
+    aicore.provider
     aicore.provider.mock
     aicore.provider.selector
     aicore.provider.deepseek
     aicore.provider.cloud_vision
     aicore.provider.cloud_ocr
 # 放行 service 层的 Protocol 依赖：service 只可与 provider/base.py 交互。
 # 必须写 `aicore.service.**`（递归通配）而非 brief 原文的 `aicore.service`：
 # 经 grimp 3.17 实测，导入表达式的「非通配」模块名只精确匹配该模块自身，不覆盖其子模块——
 # 而 service 的代码都在子模块里（service/desensitize.py 等），
 # 故 `aicore.service -> aicore.provider.base` 恒匹配不到任何边，是一条永远失效的放行声明。
 # 实测对照（临时探针 src/aicore/service/_il_probe.py 内含 from aicore.provider import base）：
 #   aicore.service     -> aicore.provider.base  => []（不匹配）
 #   aicore.service.*   -> aicore.provider.base  => 命中
 #   aicore.service.**  -> aicore.provider.base  => 命中
 ignore_imports =
     aicore.service.** -> aicore.provider.base
+# 间接路径同样违规（未开 allow_indirect_imports，用默认 false）：
+# 「service 只可与 provider.base 交互」不因中间隔了一层就成立——service → repository → provider.mock
+# 照样把具体通道实现绑进了 service。默认 false 才是与规则 2 同向的取舍。
 # forbidden 契约默认 unmatched_ignore_imports_alerting=error：放行表达式匹配不到任何真实导入
 # 即判契约失败。当前 service 各模块仍是 docstring 空壳，尚未出现 service -> provider.base 的
 # 导入，用默认值会让「干净代码」正例直接变红，整套分层检查形同虚设。改为 warn 后：正例通过，
 # Task 4 落地真实 Protocol 导入时该警告自动消失；若那时仍未消失，说明放行写错了。
 # 注意这是一个静默失效点，放行表达式一旦写错不会有人发现，故此处保留 warn 而非 none。
 unmatched_ignore_imports_alerting = warn

 [importlinter:contract:no-reverse-dependency]
 name = repository / provider / port 不得反向依赖 service
 type = forbidden
 source_modules =
     aicore.repository
     aicore.provider
     aicore.port
 forbidden_modules =
     aicore.service
+# 间接路径同样违规（未开 allow_indirect_imports，用默认 false）：
+# 禁止项 3 要封的是「反向依赖 service」这件事本身，而不是某种写法。
+# 反向层 → service → provider.deepseek 之类多跳链路一旦成立，反向依赖就已实际存在，
+# 中间隔一跳不改变事实。放行间接路径才会出现「契约说 KEPT、实际已经反向依赖」的假绿。

 [importlinter:contract:core-independent]
 name = core 不得依赖任何业务层
 type = forbidden
 source_modules =
     aicore.core
 # 含 aicore.api：api 同属业务层，且分层图（api → service）意味着 core → api 会成环。
 # 补入后实测：干净代码仍 4 kept；注入 core → api 被抓；service → provider.mock 防线未削弱。
 forbidden_modules =
     aicore.api
     aicore.service
     aicore.provider
     aicore.repository
     aicore.port
+# 间接路径同样违规（未开 allow_indirect_imports，用默认 false）：
+# core 是横切层，须能被任何层安全 import；只要存在 core → … → 业务层 的链路，
+# core 就会随业务层一起被拖进依赖环，与「不依赖任何业务层」直接冲突。
+# 本契约三条不变量均取默认 false，与契约 1 的 true 形成对照：只有明确写「直接」的规则才放行间接。
diff --git a/services/aicore/src/aicore/service/desensitize.py b/services/aicore/src/aicore/service/desensitize.py
index 504aafa..021da44 100644
--- a/services/aicore/src/aicore/service/desensitize.py
+++ b/services/aicore/src/aicore/service/desensitize.py
@@ -1,8 +1,9 @@
 """图像脱敏前置阶段。

 【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
 的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
-确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填）。
+兼容写法 `# noqa: ai-allow-swallow: <理由>` 同样被接受，但会让 ruff 报 noqa 指令告警，新代码用前者。

 第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
 """
diff --git a/services/aicore/src/aicore/service/verdict.py b/services/aicore/src/aicore/service/verdict.py
index c7b0199..d65ec8e 100644
--- a/services/aicore/src/aicore/service/verdict.py
+++ b/services/aicore/src/aicore/service/verdict.py
@@ -1,8 +1,9 @@
 """C8 权威回写前置条件。

 【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过
 人工结论的回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
-确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+确需吞掉异常时，必须在该 except 行加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填）。
+兼容写法 `# noqa: ai-allow-swallow: <理由>` 同样被接受，但会让 ruff 报 noqa 指令告警，新代码用前者。

 第 8 组实现具体校验；本任务仅建文件以保证结构检查从第一天起生效。
 """
diff --git a/services/aicore/tests/structural/test_layering.py b/services/aicore/tests/structural/test_layering.py
index 42b431a..51524c8 100644
--- a/services/aicore/tests/structural/test_layering.py
+++ b/services/aicore/tests/structural/test_layering.py
@@ -1,52 +1,187 @@
 """分层依赖规则检查。

 对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
 规则 5、6 见 tests/structural/test_source_guards.py。

-阳性/阴性双向验证：契约在干净代码上必须通过；故意注入违规导入后必须失败。
+阳性/阴性双向验证：契约在干净代码上必须通过；**四条契约各自**都要有「注入违规 → 变红」的
+阴性证据，外加一条「注入放行导入 → 仍然通过」的正例，守住 ignore_imports 写错即静默失效的风险。
+四条契约的间接导入取舍见 .importlinter 内逐条注释。
+
+缓存：所有 lint 调用都传 cache_dir=None（import-linter 2.15 支持，None 即关缓存），
+避免在仓库内留下 .import_linter_cache/ 残留。
 """

 from __future__ import annotations

 import importlib
-import shutil
-from collections.abc import Callable
+from collections.abc import Callable, Iterator
+from contextlib import contextmanager
 from pathlib import Path
+from typing import NamedTuple

 import pytest

 PROJECT_ROOT = Path(__file__).resolve().parents[2]
 CONFIG = PROJECT_ROOT / ".importlinter"
+SRC = PROJECT_ROOT / "src" / "aicore"
+PROVIDER_INIT = SRC / "provider" / "__init__.py"
+
+
+class Probe(NamedTuple):
+    """一条契约的阴性探针：把 forbidden 导入放进 source 包内，契约必须变红。"""
+
+    contract_id: str
+    rule: str
+    probe_relpath: str
+    probe_source: str
+
+
+# 四个探针各自只制造一处违规，其余三条契约必须仍为 KEPT（已逐条实测）。
+PROBES: tuple[Probe, ...] = (
+    Probe(
+        contract_id="api-no-repo-provider",
+        rule="禁止项 1：api 不得直接依赖 repository / provider",
+        probe_relpath="api/routes_probe.py",
+        probe_source="from aicore.repository import task_repo\n",
+    ),
+    Probe(
+        contract_id="service-provider-impl",
+        rule="禁止项 2：service 不得依赖具体通道实现",
+        probe_relpath="service/svc_probe.py",
+        probe_source="from aicore.provider import mock\n",
+    ),
+    Probe(
+        contract_id="no-reverse-dependency",
+        rule="禁止项 3：repository / provider / port 不得反向依赖 service",
+        probe_relpath="repository/repo_probe.py",
+        probe_source="from aicore.service import desensitize\n",
+    ),
+    Probe(
+        contract_id="core-independent",
+        rule="禁止项 4：core 不得依赖任何业务层",
+        probe_relpath="core/core_probe.py",
+        probe_source="from aicore.api import health\n",
+    ),
+)


 @pytest.fixture(scope="module")
 def lint() -> Callable[..., bool]:
     # 必须先 import importlinter.api：它调用 configuration.configure()，
     # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
     import importlinter.api  # noqa: F401
     from importlinter.application.use_cases import lint_imports

     return lint_imports


-def test_layering_contracts_pass(lint: Callable[..., bool]) -> None:
-    """干净代码上，全部分层契约必须通过。"""
-    assert lint(config_filename=str(CONFIG), no_logo=True) is True
+@contextmanager
+def probe_files(files: dict[Path, str]) -> Iterator[None]:
+    """临时写入探针文件，退出时无条件还原（含异常路径）。

-
-def test_violation_is_detected(lint: Callable[..., bool]) -> None:
-    """阴性用例：往 api 层注入一处违规导入，契约必须变红。"""
-    target = PROJECT_ROOT / "src" / "aicore" / "api" / "routes_probe.py"
-    target.write_text(
-        "from aicore.repository import task_repo  # 故意违规：api 不得直连 repository\n",
-        encoding="utf-8",
-    )
+    探针写在真实源码树里——import-linter 只认磁盘上的包结构，无法喂内存源码。
+    文件名为 *_probe.py，不会与真实模块重名；退出时逐个删除，
+    被覆盖的既有文件按内容还原，故注入不会留下改动（git diff 为空是关键证据）。
+    """
+    backup = {path: path.read_text(encoding="utf-8") for path in files if path.exists()}
     try:
+        for path, content in files.items():
+            path.write_text(content, encoding="utf-8")
         importlib.invalidate_caches()
-        assert lint(config_filename=str(CONFIG), no_logo=True) is False
+        yield
     finally:
-        target.unlink()
+        for path in files:
+            if path in backup:
+                path.write_text(backup[path], encoding="utf-8")
+            else:
+                path.unlink(missing_ok=True)
         importlib.invalidate_caches()
-        shutil.rmtree(PROJECT_ROOT / ".import_linter_cache", ignore_errors=True)

-    assert lint(config_filename=str(CONFIG), no_logo=True) is True
+
+def lint_once(
+    lint: Callable[..., bool],
+    contract_id: str | None = None,
+    config: Path | None = None,
+) -> bool:
+    """跑一次 lint；contract_id 非空时只判该契约，避免其余契约的噪声。
+
+    缓存一律关闭（cache_dir=None），故仓库内不会出现 .import_linter_cache/。
+    """
+    kwargs: dict[str, object] = {"no_logo": True, "cache_dir": None}
+    if contract_id is not None:
+        kwargs["limit_to_contracts"] = (contract_id,)
+    return lint(config_filename=str(config or CONFIG), **kwargs)
+
+
+def test_layering_contracts_pass(lint: Callable[..., bool]) -> None:
+    """干净代码上，全部分层契约必须通过，且不得有未匹配的放行表达式。"""
+    assert lint_once(lint) is True
+
+
+@pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.contract_id)
+def test_contract_goes_red_on_violation(lint: Callable[..., bool], probe: Probe) -> None:
+    """阴性用例：每条契约都要有一条「注入违规 → 变红」的证据。"""
+    target = SRC / probe.probe_relpath
+    with probe_files({target: probe.probe_source}):
+        # 先单判该契约：失败信息直接点名是哪条契约没响，不会与其它契约混淆。
+        assert lint_once(lint, probe.contract_id) is False, (
+            f"{probe.contract_id} 未响：{probe.rule} 的注入探针 {probe.probe_relpath} 没让契约变红"
+        )
+        # 再全量判一次：确认注入的违规没有顺带打翻其它契约（只由该契约负责）。
+        assert lint_once(lint) is False
+
+
+def test_allowed_provider_base_import_is_kept(lint: Callable[..., bool]) -> None:
+    """正例（放行回归）：service 导入 provider.base 合法，契约必须保持 KEPT。
+
+    守的是 ignore_imports 的 `aicore.service.** -> aicore.provider.base`：
+    它一旦写错（如退回成不匹配任何子模块的 `aicore.service`），本条会立刻变红。
+    """
+    target = SRC / "service" / "svc_probe.py"
+    with probe_files({target: "from aicore.provider import base\n"}):
+        assert lint_once(lint, "service-provider-impl") is True
+        assert lint_once(lint) is True
+
+
+def test_ignore_imports_still_needed_for_provider_base(lint: Callable[..., bool]) -> None:
+    """反证：把 ignore_imports 从配置里抽掉，同一条合法导入必须变红。
+
+    没有这一步，「正例通过」既可能是放行生效，也可能是契约根本没在看——
+    抽掉放行后变红，才证明那行 ignore_imports 真的在承载这条合法路径。
+    变异配置写到仓库内的临时文件名下，finally 无条件删除（沙箱内系统临时目录不可写）。
+    """
+    config_text = CONFIG.read_text(encoding="utf-8")
+    mutated = config_text.replace("    aicore.service.** -> aicore.provider.base\n", "", 1)
+    assert mutated != config_text, "变异失败：配置里找不到 service -> provider.base 的放行行"
+
+    target = SRC / "service" / "svc_probe.py"
+    with probe_files({target: "from aicore.provider import base\n"}):
+        mutated_config = PROJECT_ROOT / ".importlinter_nonexistent"
+        assert not mutated_config.exists(), "变异配置文件不该存在"
+        try:
+            mutated_config.write_text(mutated, encoding="utf-8")
+            importlib.invalidate_caches()
+            assert lint_once(lint, "service-provider-impl", config=mutated_config) is False
+        finally:
+            mutated_config.unlink(missing_ok=True)
+
+
+def test_provider_facade_reexport_is_forbidden(lint: Callable[..., bool]) -> None:
+    """阴性用例：provider 门面再导出相邻层模块时，`import aicore.provider` 必须被抓。
+
+    这是把 aicore.provider 整包写进 forbidden_modules 的独立理由：
+    若 provider/__init__.py 只再导出 aicore.provider.* 之外的符号（如 aicore.port.x），
+    只列 5 个具体实现模块的配置会漏掉 service -> aicore.provider -> aicore.port.x 这条链。
+    """
+    facade_export = SRC / "port" / "facade_probe.py"
+    with probe_files(
+        {
+            facade_export: '"""探针：被 provider 门面再导出的相邻层模块。"""\n',
+            PROVIDER_INIT: (
+                PROVIDER_INIT.read_text(encoding="utf-8")
+                + "from aicore.port.facade_probe import *  # noqa: F403\n"
+            ),
+            SRC / "service" / "svc_probe.py": "import aicore.provider\n",
+        }
+    ):
+        assert lint_once(lint, "service-provider-impl") is False
diff --git a/services/aicore/tests/structural/test_source_guards.py b/services/aicore/tests/structural/test_source_guards.py
index c5027b3..6df5f06 100644
--- a/services/aicore/tests/structural/test_source_guards.py
+++ b/services/aicore/tests/structural/test_source_guards.py
@@ -1,85 +1,248 @@
 """结构扫描专项：import-linter 表达不了的两条合规红线。

 规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
 规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
         的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

 规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
-确需吞异常时必须写 `# noqa: ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
+确需吞异常时必须在该 except 行写 `# ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
+理由必填：光有指令没有理由不算豁免（MUST NOT 用裸指令绕过检查）。
+兼容写法：`# noqa: ai-allow-swallow: <理由>` 同样被接受，便于沿用早期文档口径；
+但 `noqa:` 前缀会让 ruff 报 "Invalid `# noqa` directive" 警告（退出码仍为 0），
+新代码请用不带 noqa 前缀的写法。
+
+规则 6 已知边界（有意接受，见 find_swallowed_exceptions 的注释）：
+条件式重新抛出（`if strict: raise`）按「已包含 raise」放行；
+嵌套 def/lambda/class 内的 raise 不算数。
 """

 from __future__ import annotations

 import ast
 import re
+from collections.abc import Iterator
 from pathlib import Path

 import pytest

 PROJECT_ROOT = Path(__file__).resolve().parents[2]
 SRC = PROJECT_ROOT / "src" / "aicore"

 # 只允许在 provider/ 包内出现的模型调用库
 MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
 HTTP_IMPORT_RE = re.compile(
     r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
 )

+# 规则 5 的非空下限：低于此值说明扫描范围塌了（路径写错、包被搬走），
+# 参数化用例会静默收集到 0 个用例而全绿——那种"绿"没有任何意义。
+MIN_SCANNED_FILES = 20
+
 GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")
-SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")
+
+# 豁免指令：`# ai-allow-swallow: <理由>`；理由必填（`\S+`），裸指令一律不豁免。
+SWALLOW_EXEMPT_PATTERNS: tuple[re.Pattern[str], ...] = (
+    re.compile(r"#\s*ai-allow-swallow:\s*\S+"),
+    re.compile(r"#\s*noqa:\s*ai-allow-swallow:\s*\S+"),
+)
+
+# 不进入扫描的嵌套作用域：这些节点有自己的执行流，里面的 raise 不代表
+# 外层 except 会重新抛出。
+NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


 def iter_python_files() -> list[Path]:
     return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


+def iter_handler_flow(node: ast.AST) -> Iterator[ast.AST]:
+    """遍历 except 处理块自身语句流中的节点，不进入任何嵌套作用域。
+
+    - 嵌套 def / lambda / class 各有独立执行流：它们里面的 raise 与「本处理块是否
+      重新抛出」无关，故到此为止不再下探；
+    - 内层 `try/except` 的处理块同理：内层 except 自己的 raise 是内层重新抛出，
+      不能算作外层重新抛出（每个处理块都单独判定，偏严）。
+    """
+    for child in ast.iter_child_nodes(node):
+        if isinstance(child, (*NESTED_SCOPE_NODES, ast.ExceptHandler)):
+            continue
+        yield child
+        yield from iter_handler_flow(child)
+
+
 def find_swallowed_exceptions(source: str) -> list[int]:
-    """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
+    """返回「except 块内不含 raise」的行号列表（即静默降级点）。
+
+    只统计处理块自身的语句流（见 iter_handler_flow），因此：
+    - 嵌套函数 / lambda / 类里的 raise **不算**本处理块重新抛出 → 仍判违规（偏严）；
+    - 条件式重新抛出（`if strict: raise`）算已重新抛出 → 放行。
+      这是**有意接受的边界**：AST 层面无法证明 `if` 条件恒假，若连它一起判违规，
+      偏严就会变成"任何带条件的重新抛出都要写豁免"，反而促使作者删掉判断；
+      代价是「写了 raise 但条件恒不成立」这类隐性吞异常扫描不到，由人工评审兜住。
+    """
     hits: list[int] = []
     tree = ast.parse(source)
     for node in ast.walk(tree):
         if not isinstance(node, ast.ExceptHandler):
             continue
-        raises = any(isinstance(inner, ast.Raise) for stmt in node.body for inner in ast.walk(stmt))
-        if not raises:
+        if not any(isinstance(inner, ast.Raise) for inner in iter_handler_flow(node)):
             hits.append(node.lineno)
-    return hits
+    return sorted(hits)
+
+
+def has_swallow_exemption(line: str) -> bool:
+    """该行是否带规则 6 的显式豁免（理由必填）。"""
+    return any(pattern.search(line) for pattern in SWALLOW_EXEMPT_PATTERNS)


 @pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
 def test_model_http_calls_only_in_provider(path: Path) -> None:
     """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
     if path.parts[len(SRC.parts)] == "provider":
         pytest.skip("provider 包是唯一允许发起外部模型调用的层")
     text = path.read_text(encoding="utf-8")
     found = HTTP_IMPORT_RE.findall(text)
     assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"


+def test_rule_5_scan_is_not_vacuous() -> None:
+    """规则 5 的非空下限：扫描范围塌掉时必须报警，而不是静默全绿。"""
+    files = iter_python_files()
+    assert len(files) >= MIN_SCANNED_FILES, (
+        f"规则 5 只扫到 {len(files)} 个 .py（下限 {MIN_SCANNED_FILES}）："
+        f"扫描根 {SRC} 可能已失效，参数化用例会静默变成空集"
+    )
+    scanned = [p for p in files if p.parts[len(SRC.parts)] != "provider"]
+    assert scanned, "规则 5 没有任何参与断言的模块（非 provider 文件为空）"
+
+
 @pytest.mark.parametrize("relative", GUARDED_FILES)
 def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
     """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
     path = SRC / relative
     source = path.read_text(encoding="utf-8")
     lines = source.splitlines()
     offenders = [
         lineno
         for lineno in find_swallowed_exceptions(source)
-        if not SWALLOW_EXEMPT.search(lines[lineno - 1])
+        if not has_swallow_exemption(lines[lineno - 1])
     ]
     assert not offenders, (
         f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
         f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
-        f"`# noqa: ai-allow-swallow: <理由>` 显式豁免。"
+        f"`# ai-allow-swallow: <理由>` 显式豁免（理由必填）。"
     )


 def test_guard_detects_swallowing() -> None:
     """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
     bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
     good = (
         "def f():\n    try:\n        return 1\n"
         "    except Exception as exc:\n        raise RuntimeError() from exc\n"
     )
     assert find_swallowed_exceptions(bad) == [4]
     assert find_swallowed_exceptions(good) == []
+
+
+def test_guard_ignores_raise_inside_nested_scope() -> None:
+    """嵌套作用域里的 raise 不算处理块重新抛出：外层吞异常仍须被检出。
+
+    修复前的实现用 ast.walk 全深度下探，嵌套 def 里的 raise 会把外层处理块
+    误判为"已重新抛出"——这是静默漏报，与「偏严」取向相反。
+    """
+    nested_def = (
+        "def f():\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:\n"
+        "        def _swallow():\n"
+        "            raise RuntimeError('与本次处理无关')\n"
+        "        _swallow()\n"
+        "        return None\n"
+    )
+    assert find_swallowed_exceptions(nested_def) == [4]
+
+    nested_lambda = (
+        "def f():\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:\n"
+        "        handler = lambda: exec('raise RuntimeError()')\n"
+        "        handler()\n"
+        "        return None\n"
+    )
+    assert find_swallowed_exceptions(nested_lambda) == [4]
+
+    nested_class = (
+        "def f():\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:\n"
+        "        class _Swallow:\n"
+        "            raise RuntimeError('类体，与本次处理无关')\n"
+        "        return None\n"
+    )
+    assert find_swallowed_exceptions(nested_class) == [4]
+
+    nested_try = (
+        "def f():\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:\n"
+        "        try:\n"
+        "            pass\n"
+        "        except ValueError:\n"
+        "            raise\n"
+        "        return None\n"
+    )
+    # 外层 except（第 4 行）吞异常 → 违规；内层 except（第 7 行）自己 raise → 不违规。
+    assert find_swallowed_exceptions(nested_try) == [4]
+
+
+def test_guard_accepts_conditional_reraise() -> None:
+    """有意接受的边界：条件式重新抛出按「已重新抛出」放行（见函数 docstring）。"""
+    conditional = (
+        "def f(strict: bool):\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:\n"
+        "        if strict:\n"
+        "            raise\n"
+        "        return None\n"
+    )
+    assert find_swallowed_exceptions(conditional) == []
+
+
+def test_exemption_requires_reason() -> None:
+    """豁免指令必须带理由：裸指令不算豁免（守住 SWALLOW_EXEMPT 不放松）。"""
+    assert has_swallow_exemption("except Exception:  # ai-allow-swallow: 脱敏失败已降级上报")
+    assert has_swallow_exemption("except Exception:  # noqa: ai-allow-swallow: 兼容写法，理由必填")
+    assert not has_swallow_exemption("except Exception:  # ai-allow-swallow:")
+    assert not has_swallow_exemption("except Exception:  # ai-allow-swallow")
+    assert not has_swallow_exemption("except Exception:  # noqa: ai-allow-swallow")
+    assert not has_swallow_exemption("except Exception:")
+
+
+def test_exempted_handler_is_not_reported() -> None:
+    """规则 6 豁免通道的端到端小样：带理由的豁免真的能让扫描放行。"""
+    source = (
+        "def f():\n"
+        "    try:\n"
+        "        return 1\n"
+        "    except Exception:  # ai-allow-swallow: 已上报并转为默认值\n"
+        "        return 2\n"
+    )
+    lines = source.splitlines()
+    offenders = [
+        lineno
+        for lineno in find_swallowed_exceptions(source)
+        if not has_swallow_exemption(lines[lineno - 1])
+    ]
+    assert offenders == []
+
+
+def test_guarded_files_exist_and_are_scanned() -> None:
+    """非空下限：受检文件必须存在，否则规则 6 会静默变空。"""
+    missing = [relative for relative in GUARDED_FILES if not (SRC / relative).is_file()]
+    assert not missing, f"规则 6 的受检文件缺失：{missing}"

```
