# Review package b7dae75..HEAD

## Commits

2b6a396 test(aicore): 分层契约补入 api 层并说明放行写法的实测依据
269eebb docs(aicore): 计划中的分层契约改为实测正确的写法
73ea7d0 test: 固化 AICORE 分层依赖规则与合规红线结构检查

## Stat

 .../plans/2026-09-16-aicore-architecture.md        | 13 +++-
 services/aicore/.importlinter                      | 64 ++++++++++++++++
 services/aicore/tests/structural/test_layering.py  | 53 +++++++++++++-
 .../aicore/tests/structural/test_source_guards.py  | 85 ++++++++++++++++++++++
 4 files changed, 213 insertions(+), 2 deletions(-)

## Diff

```diff
diff --git a/docs/superpowers/plans/2026-09-16-aicore-architecture.md b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
index 028b48a..1804d2e 100644
--- a/docs/superpowers/plans/2026-09-16-aicore-architecture.md
+++ b/docs/superpowers/plans/2026-09-16-aicore-architecture.md
@@ -767,38 +767,49 @@ name = service 层只可与 provider.base 交互，不得依赖具体通道实
 type = forbidden
 source_modules =
     aicore.service
 forbidden_modules =
     aicore.provider.mock
     aicore.provider.selector
     aicore.provider.deepseek
     aicore.provider.cloud_vision
     aicore.provider.cloud_ocr
 ignore_imports =
-    aicore.service -> aicore.provider.base
+    aicore.service.** -> aicore.provider.base
+# 必须写递归通配 `aicore.service.**`，不能写 `aicore.service`：实测（grimp 3.17）
+# 非通配的 importer 名只精确匹配该模块自身、不覆盖子模块，而 service 的代码都在子模块里，
+# 故非通配写法恒匹配不到任何边，是一条永远失效的放行声明。三种写法的实测对照：
+#   aicore.service     -> aicore.provider.base  => 0 命中
+#   aicore.service.*   -> aicore.provider.base  => 命中
+#   aicore.service.**  -> aicore.provider.base  => 命中
+# 另：forbidden 契约默认 unmatched_ignore_imports_alerting=error，放行表达式匹配不到真实
+# 导入即判契约失败；当前各模块仍是空壳（尚无 service -> provider.base 的实际导入），用默认值
+# 会让干净代码的正例直接变红。故设为 warn：正例通过，且放行写错时仍会留下警告线索。
+unmatched_ignore_imports_alerting = warn

 [importlinter:contract:no-reverse-dependency]
 name = repository / provider / port 不得反向依赖 service
 type = forbidden
 source_modules =
     aicore.repository
     aicore.provider
     aicore.port
 forbidden_modules =
     aicore.service

 [importlinter:contract:core-independent]
 name = core 不得依赖任何业务层
 type = forbidden
 source_modules =
     aicore.core
 forbidden_modules =
+    aicore.api
     aicore.service
     aicore.provider
     aicore.repository
     aicore.port
 '''
 Path(r'$root\.importlinter').write_text(cfg, encoding='utf-8')
 print('.importlinter 已写入（UTF-8）')
 "@
 ```

diff --git a/services/aicore/.importlinter b/services/aicore/.importlinter
new file mode 100644
index 0000000..d234012
--- /dev/null
+++ b/services/aicore/.importlinter
@@ -0,0 +1,64 @@
+[importlinter]
+root_package = aicore
+
+[importlinter:contract:api-no-repo-provider]
+name = api 层不得直接依赖 repository / provider
+type = forbidden
+source_modules =
+    aicore.api
+forbidden_modules =
+    aicore.repository
+    aicore.provider
+
+[importlinter:contract:service-provider-impl]
+name = service 层只可与 provider.base 交互，不得依赖具体通道实现
+type = forbidden
+source_modules =
+    aicore.service
+forbidden_modules =
+    aicore.provider.mock
+    aicore.provider.selector
+    aicore.provider.deepseek
+    aicore.provider.cloud_vision
+    aicore.provider.cloud_ocr
+# 放行 service 层的 Protocol 依赖：service 只可与 provider/base.py 交互。
+# 必须写 `aicore.service.**`（递归通配）而非 brief 原文的 `aicore.service`：
+# 经 grimp 3.17 实测，导入表达式的「非通配」模块名只精确匹配该模块自身，不覆盖其子模块——
+# 而 service 的代码都在子模块里（service/desensitize.py 等），
+# 故 `aicore.service -> aicore.provider.base` 恒匹配不到任何边，是一条永远失效的放行声明。
+# 实测对照（临时探针 src/aicore/service/_il_probe.py 内含 from aicore.provider import base）：
+#   aicore.service     -> aicore.provider.base  => []（不匹配）
+#   aicore.service.*   -> aicore.provider.base  => 命中
+#   aicore.service.**  -> aicore.provider.base  => 命中
+ignore_imports =
+    aicore.service.** -> aicore.provider.base
+# forbidden 契约默认 unmatched_ignore_imports_alerting=error：放行表达式匹配不到任何真实导入
+# 即判契约失败。当前 service 各模块仍是 docstring 空壳，尚未出现 service -> provider.base 的
+# 导入，用默认值会让「干净代码」正例直接变红，整套分层检查形同虚设。改为 warn 后：正例通过，
+# Task 4 落地真实 Protocol 导入时该警告自动消失；若那时仍未消失，说明放行写错了。
+# 注意这是一个静默失效点，放行表达式一旦写错不会有人发现，故此处保留 warn 而非 none。
+unmatched_ignore_imports_alerting = warn
+
+[importlinter:contract:no-reverse-dependency]
+name = repository / provider / port 不得反向依赖 service
+type = forbidden
+source_modules =
+    aicore.repository
+    aicore.provider
+    aicore.port
+forbidden_modules =
+    aicore.service
+
+[importlinter:contract:core-independent]
+name = core 不得依赖任何业务层
+type = forbidden
+source_modules =
+    aicore.core
+# 含 aicore.api：api 同属业务层，且分层图（api → service）意味着 core → api 会成环。
+# 补入后实测：干净代码仍 4 kept；注入 core → api 被抓；service → provider.mock 防线未削弱。
+forbidden_modules =
+    aicore.api
+    aicore.service
+    aicore.provider
+    aicore.repository
+    aicore.port
diff --git a/services/aicore/tests/structural/test_layering.py b/services/aicore/tests/structural/test_layering.py
index 6f0fa8e..42b431a 100644
--- a/services/aicore/tests/structural/test_layering.py
+++ b/services/aicore/tests/structural/test_layering.py
@@ -1 +1,52 @@
-"""分层依赖规则检查。Task 1.3 填实。"""
+"""分层依赖规则检查。
+
+对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
+规则 5、6 见 tests/structural/test_source_guards.py。
+
+阳性/阴性双向验证：契约在干净代码上必须通过；故意注入违规导入后必须失败。
+"""
+
+from __future__ import annotations
+
+import importlib
+import shutil
+from collections.abc import Callable
+from pathlib import Path
+
+import pytest
+
+PROJECT_ROOT = Path(__file__).resolve().parents[2]
+CONFIG = PROJECT_ROOT / ".importlinter"
+
+
+@pytest.fixture(scope="module")
+def lint() -> Callable[..., bool]:
+    # 必须先 import importlinter.api：它调用 configuration.configure()，
+    # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
+    import importlinter.api  # noqa: F401
+    from importlinter.application.use_cases import lint_imports
+
+    return lint_imports
+
+
+def test_layering_contracts_pass(lint: Callable[..., bool]) -> None:
+    """干净代码上，全部分层契约必须通过。"""
+    assert lint(config_filename=str(CONFIG), no_logo=True) is True
+
+
+def test_violation_is_detected(lint: Callable[..., bool]) -> None:
+    """阴性用例：往 api 层注入一处违规导入，契约必须变红。"""
+    target = PROJECT_ROOT / "src" / "aicore" / "api" / "routes_probe.py"
+    target.write_text(
+        "from aicore.repository import task_repo  # 故意违规：api 不得直连 repository\n",
+        encoding="utf-8",
+    )
+    try:
+        importlib.invalidate_caches()
+        assert lint(config_filename=str(CONFIG), no_logo=True) is False
+    finally:
+        target.unlink()
+        importlib.invalidate_caches()
+        shutil.rmtree(PROJECT_ROOT / ".import_linter_cache", ignore_errors=True)
+
+    assert lint(config_filename=str(CONFIG), no_logo=True) is True
diff --git a/services/aicore/tests/structural/test_source_guards.py b/services/aicore/tests/structural/test_source_guards.py
new file mode 100644
index 0000000..c5027b3
--- /dev/null
+++ b/services/aicore/tests/structural/test_source_guards.py
@@ -0,0 +1,85 @@
+"""结构扫描专项：import-linter 表达不了的两条合规红线。
+
+规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
+规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
+        的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。
+
+规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
+确需吞异常时必须写 `# noqa: ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。
+"""
+
+from __future__ import annotations
+
+import ast
+import re
+from pathlib import Path
+
+import pytest
+
+PROJECT_ROOT = Path(__file__).resolve().parents[2]
+SRC = PROJECT_ROOT / "src" / "aicore"
+
+# 只允许在 provider/ 包内出现的模型调用库
+MODEL_CALL_LIBS = ("httpx", "requests", "aiohttp")
+HTTP_IMPORT_RE = re.compile(
+    r"^\s*(?:import|from)\s+(" + "|".join(MODEL_CALL_LIBS) + r")\b", re.MULTILINE
+)
+
+GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")
+SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")
+
+
+def iter_python_files() -> list[Path]:
+    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
+
+
+def find_swallowed_exceptions(source: str) -> list[int]:
+    """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
+    hits: list[int] = []
+    tree = ast.parse(source)
+    for node in ast.walk(tree):
+        if not isinstance(node, ast.ExceptHandler):
+            continue
+        raises = any(isinstance(inner, ast.Raise) for stmt in node.body for inner in ast.walk(stmt))
+        if not raises:
+            hits.append(node.lineno)
+    return hits
+
+
+@pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
+def test_model_http_calls_only_in_provider(path: Path) -> None:
+    """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
+    if path.parts[len(SRC.parts)] == "provider":
+        pytest.skip("provider 包是唯一允许发起外部模型调用的层")
+    text = path.read_text(encoding="utf-8")
+    found = HTTP_IMPORT_RE.findall(text)
+    assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"
+
+
+@pytest.mark.parametrize("relative", GUARDED_FILES)
+def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
+    """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
+    path = SRC / relative
+    source = path.read_text(encoding="utf-8")
+    lines = source.splitlines()
+    offenders = [
+        lineno
+        for lineno in find_swallowed_exceptions(source)
+        if not SWALLOW_EXEMPT.search(lines[lineno - 1])
+    ]
+    assert not offenders, (
+        f"{relative} 在第 {offenders} 行的 except 块中未重新抛出异常。"
+        f"脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 "
+        f"`# noqa: ai-allow-swallow: <理由>` 显式豁免。"
+    )
+
+
+def test_guard_detects_swallowing() -> None:
+    """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
+    bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
+    good = (
+        "def f():\n    try:\n        return 1\n"
+        "    except Exception as exc:\n        raise RuntimeError() from exc\n"
+    )
+    assert find_swallowed_exceptions(bad) == [4]
+    assert find_swallowed_exceptions(good) == []

```
