### Task 1.3: 分层依赖规则固化为检查

**Files:**
- Create: `services/aicore/.importlinter`（import-linter 分层契约，INI 形式，**必须 UTF-8 无 BOM**）
- Modify: `services/aicore/tests/structural/test_layering.py`
- Create: `services/aicore/tests/structural/test_source_guards.py`

**Interfaces:**
- Consumes: Task 1.2 的六层包结构；`aicore.service.desensitize`、`aicore.service.verdict`（规则 6 的受检文件）
- Produces: `pytest` 可执行的分层契约检查；`tests/structural/test_source_guards.py` 提供 `iter_python_files() -> list[Path]` 与 `find_swallowed_exceptions(source: str) -> list[int]>` 两个可复用函数

**已实测的关键写法（不要改动）**：
1. import-linter 2.15 的公开入口是 `importlinter.application.use_cases.lint_imports`，且**必须先 `import importlinter.api`** 触发 `configuration.configure()`，否则 `USER_OPTION_READERS` 未注册、配置读不出来。
2. `forbidden_modules` 写 `aicore.provider` 会**连带禁止** `aicore.provider.base`；必须**精确列出具体实现模块**，并用 `ignore_imports` 放行 Protocol。
3. 配置文件中的中文契约名需要文件本身是 UTF-8；用 Python 写文件可确保编码。

- [ ] **Step 1: 先写阴性用例（验证检查会响）**

`tests/structural/test_layering.py`：

> **以仓库实际文件为准**：下面是首版参考模板，权威定义是
> `services/aicore/tests/structural/test_layering.py`。已落地的版本与本片段有三处差异，
> 照抄会把旧写法写回去：
> 1. 四条契约**各自**一条参数化阴性用例（`PROBES`），不是一条笼统的"注入违规"用例；
> 2. 所有 lint 调用传 `cache_dir=None` 关缓存，**不再**用 `shutil.rmtree` 清
>    `.import_linter_cache/`；
> 3. 另有「放行正例」与「抽掉 ignore_imports 必变红」两条反证用例。

```python
"""分层依赖规则检查。

对应 design.md「依赖方向规则」的 6 条禁止项，其中规则 1~4 由 import-linter 契约承载，
规则 5、6 见 tests/structural/test_source_guards.py。

阳性/阴性双向验证：契约在干净代码上必须通过；故意注入违规导入后必须失败。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / ".importlinter"


@pytest.fixture(scope="module")
def lint() -> object:
    # 必须先 import importlinter.api：它调用 configuration.configure()，
    # 注册 USER_OPTION_READERS；只 import use_cases 会报 'USER_OPTION_READERS' KeyError。
    import importlinter.api  # noqa: F401
    from importlinter.application.use_cases import lint_imports

    return lint_imports


def test_layering_contracts_pass(lint: object) -> None:
    """干净代码上，全部分层契约必须通过。"""
    assert lint(config_filename=str(CONFIG), no_logo=True) is True


def test_violation_is_detected(lint: object) -> None:
    """阴性用例：往 api 层注入一处违规导入，契约必须变红。"""
    target = PROJECT_ROOT / "src" / "aicore" / "api" / "routes_probe.py"
    target.write_text(
        "from aicore.repository import task_repo  # 故意违规：api 不得直连 repository\n",
        encoding="utf-8",
    )
    try:
        importlib.invalidate_caches()
        assert lint(config_filename=str(CONFIG), no_logo=True) is False
    finally:
        target.unlink()
        importlib.invalidate_caches()
        # 缓存：shipped 版本所有 lint 调用都传 cache_dir=None，不再需要 rmtree 清理
        # （.import_linter_cache/ 根本不会生成）。

    assert lint(config_filename=str(CONFIG), no_logo=True) is True
```

- [ ] **Step 2: 运行，确认第一步失败（`.importlinter` 尚不存在）**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural/test_layering.py -v
Pop-Location
```

Expected: FAIL —— `FileNotFoundError` 或 `lint_imports` 读配置报错

- [ ] **Step 3: 写 `.importlinter`（用 Python 写以确保 UTF-8）**

```powershell
# 注意：以下为参考模板。**权威定义是仓库中的 services/aicore/.importlinter 本身**——
# 该文件含多处实测得出的关键设置（allow_indirect_imports、递归通配 ignore_imports、
# unmatched_ignore_imports_alerting、aicore.provider 整包禁止），每处都带注释说明依据。
# 若本模板与之不一致，以实际文件为准；不要照抄本模板覆盖它。
$root = "D:\progrom\services\aicore"
& "$root\.venv\Scripts\python.exe" -c @"
from pathlib import Path
cfg = '''[importlinter]
root_package = aicore

[importlinter:contract:api-no-repo-provider]
name = api 层不得直接依赖 repository / provider
type = forbidden
# 必须显式写 true：forbidden 默认 false 会沿调用链报**传递**依赖，
# 而 api -> service -> repository 正是本设计的分层路径，实测会被误判为违规。
allow_indirect_imports = true
source_modules =
    aicore.api
forbidden_modules =
    aicore.repository
    aicore.provider

[importlinter:contract:service-provider-impl]
name = service 层只可与 provider.base 交互，不得依赖具体通道实现
type = forbidden
source_modules =
    aicore.service
forbidden_modules =
    aicore.provider
    aicore.provider.mock
    aicore.provider.selector
    aicore.provider.deepseek
    aicore.provider.cloud_vision
    aicore.provider.cloud_ocr
ignore_imports =
    aicore.service.** -> aicore.provider.base
# 必须写递归通配 `aicore.service.**`，不能写 `aicore.service`：实测（grimp 3.17）
# 非通配的 importer 名只精确匹配该模块自身、不覆盖子模块，而 service 的代码都在子模块里，
# 故非通配写法恒匹配不到任何边，是一条永远失效的放行声明。三种写法的实测对照：
#   aicore.service     -> aicore.provider.base  => 0 命中
#   aicore.service.*   -> aicore.provider.base  => 命中
#   aicore.service.**  -> aicore.provider.base  => 命中
# 另：forbidden 契约默认 unmatched_ignore_imports_alerting=error，放行表达式匹配不到真实
# 导入即判契约失败；当前各模块仍是空壳（尚无 service -> provider.base 的实际导入），用默认值
# 会让干净代码的正例直接变红。故设为 warn：正例通过，且放行写错时仍会留下警告线索。
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

[importlinter:contract:core-independent]
name = core 不得依赖任何业务层
type = forbidden
source_modules =
    aicore.core
forbidden_modules =
    aicore.api
    aicore.service
    aicore.provider
    aicore.repository
    aicore.port
'''
Path(r'$root\.importlinter').write_text(cfg, encoding='utf-8')
print('.importlinter 已写入（UTF-8）')
"@
```

- [ ] **Step 4: 运行，确认全部用例通过（用例数以仓库实际文件为准，见 Step 1 提示）**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural/test_layering.py -v
Pop-Location
```

Expected: 全部 passed。用例数以仓库实际文件为准：shipped 版本是四条契约的参数化阴性用例
（每条注入一处违规，并逐条确认其余三条契约仍 KEPT）+ 两条放行反证，不再是首版的 2 个。

- [ ] **Step 5: 写规则 5、6 的 AST 扫描用例**

> **修复轮 1 提示**：下面这段代码块是首版写法，规则 6 的扫描函数已被修复轮改写
> （不再下探嵌套 def/lambda/class/内层 except）。以
> `services/aicore/tests/structural/test_source_guards.py` 的实际内容为准，勿照抄本片段。**
>
> 豁免指令也以实际文件为准：shipped 实现是 `SWALLOW_EXEMPT_PATTERNS`（正式写法
> `# ai-allow-swallow: <理由>` + 兼容写法 `# noqa: ai-allow-swallow: <理由>`，两条正则、理由必填）
> 与 `has_swallow_exemption()`，而本片段只有一条只认正式写法的 `SWALLOW_EXEMPT`。

`tests/structural/test_source_guards.py`：

```python
"""结构扫描专项：import-linter 表达不了的两条合规红线。

规则 5：只有 provider/ 下的模块可以发起外部模型 HTTP 调用。
规则 6：service/desensitize.py 与 service/verdict.py MUST NOT 出现「异常后继续执行」
        的降级分支（D4 脱敏失败即拒绝、D5 无人工结论不回写）。

规则 6 取向为「偏严 + 显式豁免」：不含 raise 的 except 即判违规，
确需吞异常时必须写 `# ai-allow-swallow: <理由>` —— 宁可让人解释一次，也不漏掉。

> **修复轮 1 更正（评审 M9）**：豁免指令的正式写法是 `# ai-allow-swallow: <理由>`（不带 `noqa:` 前缀），
> 本文档下列片段已同步更新。早期口径 `# noqa: ai-allow-swallow: <理由>` 语法上仍被扫描接受，
> 但 ruff 会把 `ai-allow-swallow` 当成 noqa 规则码，每次使用都打印一条 `Invalid # noqa directive` 警告，
> 故新代码一律用不带前缀的正式写法。理由必填不变（裸指令不算豁免）。
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
SWALLOW_EXEMPT = re.compile(r"#\s*ai-allow-swallow:\s*\S+")


def iter_python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def find_swallowed_exceptions(source: str) -> list[int]:
    """返回「except 块内不含 raise」的行号列表（即静默降级点）。"""
    hits: list[int] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        raises = any(isinstance(inner, ast.Raise) for stmt in node.body for inner in ast.walk(stmt))
        if not raises:
            hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("path", iter_python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_model_http_calls_only_in_provider(path: Path) -> None:
    """规则 5：外部模型 HTTP 调用只允许出现在 provider/ 包内。"""
    if path.parts[len(SRC.parts)] == "provider":
        pytest.skip("provider 包是唯一允许发起外部模型调用的层")
    text = path.read_text(encoding="utf-8")
    found = HTTP_IMPORT_RE.findall(text)
    assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"


@pytest.mark.parametrize("relative", GUARDED_FILES)
def test_no_silent_degradation_in_guarded_files(relative: str) -> None:
    """规则 6：合规红线文件不得有「异常后继续执行」的分支。"""
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
        f"`# ai-allow-swallow: <理由>` 显式豁免。"
    )


def test_guard_detects_swallowing(tmp_path: Path) -> None:
    """阴性用例：扫描函数必须能检出违规样本，且不误报合法样本。"""
    bad = "def f():\n    try:\n        return 1\n    except Exception:\n        return 2\n"
    good = "def f():\n    try:\n        return 1\n    except Exception as exc:\n        raise RuntimeError() from exc\n"
    assert find_swallowed_exceptions(bad) == [4]
    assert find_swallowed_exceptions(good) == []
```

- [ ] **Step 6: 运行全部结构用例**

```powershell
$root = "D:\progrom\services\aicore"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -m pytest tests/structural -v
Pop-Location
```

Expected: 全部 passed（规则 5 的 provider 用例被 skip 属正常）

- [ ] **Step 7: 阴性验证——故意让规则 5 变红，确认检查会响**

临时在 `src/aicore/service/ocr_match.py` 追加一行 `import httpx`，重跑 Step 6。

Expected: `test_model_http_calls_only_in_provider[service/ocr_match.py]` FAIL。**验证后必须删除该行**并重跑确认恢复绿。

- [ ] **Step 8: 阴性验证——故意让规则 6 变红，确认检查会响**

临时把 `src/aicore/service/desensitize.py` 改为含 `try/except: return None` 的函数，重跑 Step 6。

Expected: `test_no_silent_degradation_in_guarded_files[service/desensitize.py]` FAIL。**验证后必须还原**并重跑确认恢复绿。

- [ ] **Step 9: 提交**

```bash
git add services/aicore/.importlinter services/aicore/tests/structural
git commit -m "test: 固化 AICORE 分层依赖规则与合规红线结构检查"
```

---
