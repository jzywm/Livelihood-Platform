# Task 1.3 报告：分层依赖规则固化为检查

**状态**：DONE_WITH_CONCERNS
**提交**：`73ea7d0`　`test: 固化 AICORE 分层依赖规则与合规红线结构检查`
**基线**：`b7dae75`（工作树 `D:\progrom\.worktrees\aicore-architecture`，分支 `feature/aicore-architecture`）

---

## 1. 产出物

| 文件 | 动作 | 说明 |
|---|---|---|
| `services/aicore/.importlinter` | 新增 | import-linter 分层契约（INI，UTF-8 无 BOM，61 行），承载规则 1~4 |
| `services/aicore/tests/structural/test_layering.py` | 改写（占位 → 52 行） | 契约正例 + 注入违规的阴性用例 |
| `services/aicore/tests/structural/test_source_guards.py` | 新增（85 行） | 规则 5、6 的 AST 扫描，导出可复用 `iter_python_files()` / `find_swallowed_exceptions()` |

提交统计：`3 files changed, 198 insertions(+), 1 deletion(-)`。

### 契约内容（4 条，对应 design.md 禁止项 1~4）

| 契约 | 规则 | 来源 |
|---|---|---|
| `api-no-repo-provider` | api 不得依赖 repository / provider | design.md 禁止项 1 |
| `service-provider-impl` | service 只可与 `provider.base` 交互，不得依赖 5 个具体实现 | 禁止项 2 |
| `no-reverse-dependency` | repository / provider / port 不得反向依赖 service | 禁止项 3 |
| `core-independent` | core 不得依赖 service / provider / repository / port | 禁止项 4 |

---

## 2. 逐步验证证据（真实输出）

### Step 2：先跑阴性用例 —— 预期失败（`.importlinter` 尚不存在）✅ 符合预期

```
tests\structural\test_layering.py FF                                     [100%]
E       AssertionError: assert False is True
tests\structural\test_layering.py:33: AssertionError
---------------------------- Captured stdout call -----------------------------
Could not find
D:\progrom\.worktrees\aicore-architecture\services\aicore\.importlinter.
=========================== short test summary info ===========================
FAILED tests/structural/test_layering.py::test_layering_contracts_pass
FAILED tests/structural/test_layering.py::test_violation_is_detected
============================== 2 failed in 0.52s ==============================
EXIT=1
```

### Step 4：`.importlinter` 就位后 —— 两个用例通过 ✅

```
tests\structural\test_layering.py ..                                     [100%]
============================== 2 passed in 0.29s ==============================
EXIT=0
```

底层 `lint_imports` 直跑结果：

```
Analyzed 50 files, 0 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
RESULT True
```

### Step 6：全部结构用例 ✅

```
collected 55 items
tests\structural\test_layering.py ..                                     [  3%]
tests\structural\test_source_guards.py ......................sssssss.... [ 63%]
....................                                                     [100%]
======================== 48 passed, 7 skipped in 0.21s ========================
EXIT=0
```

文件基数实测：`src/aicore` 下共 **50** 个 `.py`（含 `__init__.py`）→ provider 包 **7** 个被 skip，其余 **43** 个参与规则 5 断言。`48 passed + 7 skipped = 55` 与收集数一致。

### Step 7：规则 5 阴性验证 —— 注入 `import httpx` 后变红 ✅

注入：`src/aicore/service/ocr_match.py` 追加一行 `import httpx`。

```
collected 55 items / 54 deselected / 1 selected
tests\structural\test_source_guards.py F                                 [100%]
>       assert not found, f"{path.relative_to(PROJECT_ROOT)} 出现外部模型调用库 {found}，违反规则 5"
E       AssertionError: src\aicore\service\ocr_match.py 出现外部模型调用库 ['httpx']，违反规则 5
E       assert not ['httpx']
FAILED tests/structural/test_source_guards.py::test_model_http_calls_only_in_provider[service\\ocr_match.py]
====================== 1 failed, 54 deselected in 0.09s =======================
EXIT=1
```

**还原后复绿**（hash 回填一致 + 全量结构用例）：

```
=== RESTORED hash (must equal 418bfb21b7b96bc838b317d21a5014b70fbac98c) ===
418bfb21b7b96bc838b317d21a5014b70fbac98c
=== git diff for src/ (must be empty) ===
(end diff)
........................sssssss........................                  [100%]
48 passed, 7 skipped in 0.24s
EXIT=0
```

### Step 8：规则 6 阴性验证 —— 注入 `try/except: return None` 后变红 ✅

注入：`src/aicore/service/desensitize.py` 追加含静默降级分支的函数。

```
collected 55 items / 53 deselected / 2 selected
tests\structural\test_source_guards.py F.                                [100%]
E       AssertionError: service/desensitize.py 在第 [15] 行的 except 块中未重新抛出异常。脱敏失败必须拒绝外发、无人工结论不得回写；确需吞异常请加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
E       assert not [15]
FAILED tests/structural/test_source_guards.py::test_no_silent_degradation_in_guarded_files[service/desensitize.py]
================= 1 failed, 1 passed, 53 deselected in 0.07s ==================
EXIT=1
```

同一轮里 `[service/verdict.py]` **passed** —— 两个受检文件独立判定，未联动误伤。

**还原后复绿**：

```
=== RESTORED hash (must equal 504aafa2ab4d7d772f452bfdb8f7bd86dde5a3ee) ===
504aafa2ab4d7d772f452bfdb8f7bd86dde5a3ee
=== git diff src/ (must be empty) ===
(end diff)
........................sssssss........................                  [100%]
48 passed, 7 skipped in 0.28s
EXIT=0
```

### 追加验证（brief 未要求，但为覆盖我改动的两处配置）✅

| 场景 | 结果 |
|---|---|
| 临时探针含 `from aicore.provider import base` | `service 层…KEPT (1 ignored import)`，`RESULT True` → **Protocol 放行真的生效** |
| 临时探针含 `from aicore.provider import mock` | `aicore.service is not allowed to import aicore.provider.mock`，`RESULT False` → **规则 2 仍会变红，未被我的改动削弱** |
| 探针 + `# noqa: ai-allow-swallow: …` 豁免注释 | `2 passed`（`-k silent_degradation`）→ **规则 6 的豁免通道确实可用** |

---

## 3. 残留物清零证明

```
=== full worktree status ===
?? .sdd-il-probe.py
?? .sdd-scan.py
?? .sdd-setup-db.py
?? .sdd-tools.py
```

- 工作树**只剩 4 个 `.sdd-*.py`**，均为**本任务开始前就存在**的既有未跟踪文件（Task 1.1 遗留，位于工作树根目录），本任务未触碰、未提交。
- `routes_probe: False`（`test_layering.py` 的阴性探针已由 `finally` 删除）
- `_il_probe:    False`（我自建的临时探针已删除）
- 两处注入文件的 git blob hash **逐个与注入前完全一致**（见 Step 7 / 8），且 `git diff -- services/aicore/src` 为空 → 注入改动 **零残留**。
- `__pycache__` 目录（src、tests 下）创建时间为 `2026/9/17 16:54`，**早于本任务**，属 Task 1.2 产物，且已被 `.gitignore` 覆盖（`git check-ignore` 命中 `services/aicore/.gitignore:1`）。
- `.import_linter_cache/`：被 `services/aicore/.gitignore:9` 覆盖；`test_layering.py` 的 `finally` 亦会 `rmtree` 清理。

---

## 4. 变更文件与质量门禁

| 门禁 | 命令 | 结果 |
|---|---|---|
| pytest（结构） | `python -m pytest tests/structural -p no:cacheprovider` | `48 passed, 7 skipped`（exit 0） |
| pytest（全量） | `python -m pytest -p no:cacheprovider` | `48 passed, 7 skipped`（exit 0） |
| ruff lint | `python -m ruff check --no-cache tests src` | `All checks passed!`（exit 0，55 文件） |
| ruff format | `python -m ruff format --check --no-cache tests src` | `55 files already formatted` |
| mypy | `python -m mypy --cache-dir .venv\mypy_cache tests/structural` | `Success: no issues found in 3 source files` |
| 编码 | 三个文件 | `BOM=False utf8=True`，均以 LF 结尾 |

所有命令均设 `PYTHONUTF8=1`、`PYTHONPYCACHEPREFIX` 指向 `.venv\pycache`、pytest 加 `-p no:cacheprovider`、ruff 加 `--no-cache`、mypy 用 `.venv\mypy_cache`。未执行任何 `pip install`。

### commit-check（`.githooks` 无法执行，逐项手工复现）

`sh` 不在 PATH，`.githooks/*` 对本沙箱内任何人都无法执行，故以 `--no-verify` 提交，并手工复现其全部确定性检查：

| hook 检查项 | 手工复现结果 |
|---|---|
| 合并冲突标记 | `none` |
| 行尾空白 / 末尾多余空行（`git diff --cached --check`） | 退出码 0，`none` |
| 大文件 >1MB | 最大 3492 bytes |
| 私钥块 / 云密钥（`AKIA…`/`ASIA…`） | `none` |
| 疑似硬编码凭据正则 | `none` |
| 真实 `.env` 入库 | 本次无 `.env` |
| `commit-msg` Conventional Commits | `PASS: 'test: 固化 AICORE 分层依赖规则与合规红线结构检查'` |
| 不带 `[AI]` 前缀 | `PASS` |
| 提交粒度单一 | 3 文件全部围绕同一件事（分层/红线检查），无夹带 |

语义级检查：注释与文档全中文、标识符全英文（`DEVELOPMENT_CONSTRAINTS.md` §2）；无 SQL 拼接 / XSS / 敏感信息入日志；新增安全相关逻辑（规则 5、6 检查）均带测试。

---

## 5. 自查发现（自行审查 diff 后）

### 5.1 【必须报告】对 brief 原文的两处偏离

brief 的 `.importlinter` 原文**在干净代码上就是红的**（Step 4 无法达成"2 passed"）。根因经实测定位到两点，均已修复并在配置内写明理由：

**偏离 1 — `ignore_imports` 表达式恒不匹配（原文功能失效）**

brief 写 `aicore.service -> aicore.provider.base`。经 grimp 3.17 直接实测（探针含 `from aicore.provider import base`）：

```
edge exists: True
aicore.service     -> aicore.provider.base -> []          ← 不匹配
aicore.service.*   -> aicore.provider.base -> 命中
aicore.service.**  -> aicore.provider.base -> 命中
```

非通配模块名在**导入方**只精确匹配该模块自身，不覆盖子模块；而 service 的代码都在子模块（`service/desensitize.py` 等）。故原文是一条**永远不会生效的放行声明**。已改为 `aicore.service.** -> aicore.provider.base`，并实测放行生效（`KEPT (1 ignored import)`）。

**偏离 2 — `unmatched_ignore_imports_alerting` 采用默认值 `error`**

`ForbiddenContract.unmatched_ignore_imports_alerting` 默认 `AlertLevel.ERROR`（`importlinter/contracts/forbidden.py:76`），放行表达式匹配不到任何真实导入即抛 `MissingImport`、直接判契约失败。叠加偏离 1，干净代码必然变红。已显式设 `warn`：正例通过，Task 4 落地真实 Protocol 导入后警告自动消失。

> 我特意保留 `warn` 而非 `none`，并在配置里注释说明：这是一个静默失效点，放行表达式一旦写错不会有人发现，留 `warn` 才能在 Task 4 时给出"放行没生效"的信号。

**为什么必须偏离而不是照抄**：任务目标是"让规则会变红"。照抄原文的结果是 4 条契约**全部**在干净代码上变红 → 整层检查立即失效、后续任务会学会忽略它。两处修改均不放松任何禁止项：实测规则 2 注入 `provider.mock` 仍然 `RESULT False`。

已尝试按 brief 要求先向你提问，但 `ask_user_question` 返回：*"human interaction is unavailable while the calling agent is owned by another live agent"* —— 我是被委派的子代理，无法向你提问，故按上述判断落地并在本报告中显式上报，请复核裁定。

### 5.2 【已修】brief 的测试代码不符合本仓库 lint 门禁

本仓库 baseline 为 **ruff 0 错、55/55 文件格式合规**，而 brief 的 `test_source_guards.py` 有两处违规：

- `E501 Line too long (120 > 100)`：`good` 样例字符串（line-length = 100，`pyproject.toml` 配置）
- `ruff format` 要求列表推导换行

均已按 ruff 修好，**语义完全等价**（`find_swallowed_exceptions(good) == []` 仍成立）。

### 5.3 【已修】brief 里 `lint` 夹具标注 `-> object` 导致 mypy 报错

`"object" not callable [operator]`，3 处。已改为 `Callable[..., bool]`（夹具与两个用例签名同步），mypy 清零。行为零变化。

### 5.4 【已修】brief 的 `test_guard_detects_swallowing(tmp_path)` 在本沙箱报错

该用例**从不使用** `tmp_path`，但请求该夹具会尝试创建 `C:\Users\…\AppData\Local\Temp\dsh-…\pytest-of-…`，本会话沙箱拒绝写入：

```
E  PermissionError: [WinError 5] 拒绝访问。: 'C:\\Users\\贾锐航\\AppData\\Local\\Temp\\dsh-FcEk6l\\pytest-of-贾锐航'
=========================== 47 passed, 7 skipped, 1 error in 0.43s ===========================
```

已删除这个未使用的参数（无行为变化），之后 `48 passed, 7 skipped`。这是沙箱环境约束，不是代码缺陷；若在无沙箱限制的环境运行，原写法应也能通过。

### 5.5 【已修，我方失误】用 PowerShell 5.1 改文件引入了 UTF-8 BOM

我一度用 `Set-Content -Encoding utf8` 批量改 `test_layering.py` 的函数签名，该 shell 是 **PowerShell 5.1**，其 `utf8` 会写 BOM。检测到 `BOM=True` 后已用 write 工具重写该文件，复核为 `BOM=False utf8=True LF`。教训与任务提示一致：**此类编辑一律走 edit/write 工具**。已确认此失误**未进入提交**（提交后复核三个文件 `BOM=False`）。

### 5.6 设计上已确认的既有取舍（非缺陷，供知悉）

- **规则 5 是包级规则**：`provider/` 下 7 个文件被 skip（连空壳 `provider/__init__.py` 也 skip），意味着该包内任何模块都可发 HTTP。这是 brief 与 design.md 明示的取向，需靠评审约束。
- **`iter_python_files()` 在 import 时求值**：参数化列表在模块导入时固化，同一 pytest 会话中后创建的文件不会被扫到。对静态结构检查无实际影响。
- **规则 6 的 `raise` 检测用 `ast.walk` 全深度搜索**：`except` 块内若嵌套函数/内层 `try` 中另有 `raise`，外层吞异常可能被漏判。brief 明确的写法，属"偏严取向 + 显式豁免"的已知边界。

---

## 6. 遗留问题 / 关切（请裁定）

1. **`core-independent` 未禁止 `core -> api`**（**建议补**）：design.md 禁止项 4 的原文是"`core/` MUST NOT 导入 `service/` / `provider/` / `repository/`"，标题为"core 不得依赖任何业务层"；brief 的契约列了 service / provider / repository / port 四项，**漏了 `api`**。即当前 `core` 依赖 `api` 不会被拦。我按"照 brief 逐字实现"处理，未擅自扩列 —— 但按标题语义（core 不依赖任何业务层）这是覆盖缺口。补一行 `aicore.api` 即可闭合，请裁定。
2. **偏离 5.1 需你确认**：`.importlinter` 有两处与 brief 原文不同（`aicore.service.**`、`unmatched_ignore_imports_alerting = warn`），理由已在配置文件内以中文注释固化，并在本文档给出实测对照。若你要求严格照抄 brief 原文，则该配置在 Task 4 落地真实 `provider.base` 导入前**始终是红的**，规则 1~4 在本任务内不可用。
3. **`.githooks` 在本沙箱无法执行**（`sh` 不在 PATH），按授权以 `--no-verify` 提交，已手工复现其 8 项确定性检查（见 §4）。CI G2 仍应能正常执行 hook。
4. **4 个 `.sdd-*.py` 未跟踪文件**留在工作树根目录（Task 1.1 遗留，非本任务产物），既未提交也未删除 —— 清理与否请一并裁定。

---

## 7. 结论

- 4 条分层契约全部落地并在干净代码上 `KEPT`（`Contracts: 4 kept, 0 broken.`）。
- 规则 5、6 的 AST 扫描落地，且**各自经一次"注入 → 变红 → 还原 → 复绿"闭环验证**，红线真的会响。
- 额外验证了 Protocol 放行生效、规则 2 未被削弱、规则 6 豁免通道可用。
- 注入改动零残留（hash 逐个一致），探针文件零残留。
- `73ea7d0` 已提交；pytest / ruff / ruff format / mypy 全绿。
- 待裁定事项共 4 项，见 §6。

---

## 修复轮 1（评审发现）

**状态**：DONE（自评；评审的 4 项 Important + 6 项 Minor 全部处理，无 Critical）
**提交**：
- `f4f77c7`　`fix(aicore): 分层契约间接导入语义与结构检查评审修复`（5 文件，+368/−28）
- `ad1c341`　`docs(aicore): 计划中豁免指令改为不带 noqa 前缀的正式写法`（1 文件，+14/−5）

拆两个提交是因为我在实现 M9 时改了 `docs/superpowers/plans/2026-09-16-aicore-architecture.md`（评审在 M9 里明确要求三处同步，「计划口径」占其一）。该文档变更与代码检查无关，混在一个提交里会让 `fix` 提交带进 6 万字节的文档 diff，故单独成 `docs` 提交。

**基线**：`2b6a396`（工作树 `D:\progrom\.worktrees\aicore-architecture`，分支 `feature/aicore-architecture`）

---

### 逐条处理

#### I1 — 契约 1 的间接导入语义（已修，并在配置内写清四条契约各自的取舍）

**依据直接来自设计原文**：`openspec/changes/implement-aicore-service/design.md` 禁止项 1 的措辞是
「`api/` MUST NOT **直接导入** `repository/` 或 `provider/`——路由只调 service」，而分层允许方向写的是
`api ──→ service ──→ {provider 抽象, repository, port}`。也就是说 `api → service → repository` 是**被设计明令允许**的路径，
默认 `allow_indirect_imports=false` 会把它判违规。已加 `allow_indirect_imports = true`。

**并逐条决定了另外三条契约的取向（全部取默认 `false`，并在配置内逐条注释理由）**：

| 契约 | 取值 | 理由（配置内已写） |
|---|---|---|
| `api-no-repo-provider` | `true` | 设计原文写的是「直接导入」；`api → service → repository` 是应放行的设计路径 |
| `service-provider-impl` | `false`（默认） | 「service 只可与 provider.base 交互」不因中间隔一层而成立；`service → repository → provider.mock` 照样把具体实现绑进 service |
| `no-reverse-dependency` | `false`（默认） | 禁止项 3 封的是「反向依赖」这件事本身，多跳链一旦成立事实已存在；放行间接会产出「KEPT 但已反向依赖」的假绿 |
| `core-independent` | `false`（默认） | core 是横切层，只要存在 `core → … → 业务层` 链路就会被拖进依赖环 |

**并把「代价」也实测了**（不是推断）：契约 1 放开间接路径后，我逐条构造真实链路验证兜底没有漏口——

| 构造的链路 | 实测结果 |
|---|---|
| `api → service → repository → provider.deepseek` | 契约 2 `BROKEN`（打印两跳链路） |
| `api → service → repository → provider.mock` | 契约 2 `BROKEN`（打印两跳链路） |
| `core → api → service` | 契约 4 `BROKEN`（既抓 core→api 也抓 core→…→service） |
| `repository → provider → service`（反向两跳） | 契约 3 `BROKEN`（repository→provider 与 provider→service 都报） |
| `api → service → port`（不触碰 provider/repository） | `4 kept`（正是设计要放行的路径） |

唯一被放开的形态是 `api → service → provider.base`——禁止项 2 明示合法（只依赖 Protocol）。

**对照实测（`allow_indirect_imports` 两档差异）**：构造 `api.chain_c → service.chain_b → repository.chain_a`
（三跳之间**没有**任何 `api → repository` 直接导入）：

```
direct api->repository exists: False
chains api -> repository: {('aicore.api.routes_probe', 'aicore.service.svc_probe', 'aicore.repository.residue_probe')}
--- 默认 false（未修复前）---
api 层不得直接依赖 repository / provider BROKEN
Broken contracts
aicore.api is not allowed to import aicore.repository:
-   aicore.api.routes_probe -> aicore.service.svc_probe (l.1)
    aicore.service.svc_probe -> aicore.repository.residue_probe (l.1)
RESULT False
--- true（已修复后）---
api 层不得直接依赖 repository / provider KEPT
Contracts: 4 kept, 0 broken.
RESULT True
```

#### I2 — 四条契约的阴性证据 + 两条改动的回归守护（已修）

`tests/structural/test_layering.py` 重写为 **8 个用例**：

| 用例 | 覆盖 |
|---|---|
| `test_layering_contracts_pass` | 干净代码 4 kept |
| `test_contract_goes_red_on_violation[api-no-repo-provider]` | 探针 `api/routes_probe.py`：`from aicore.repository import task_repo` |
| `test_contract_goes_red_on_violation[service-provider-impl]` | 探针 `service/svc_probe.py`：`from aicore.provider import mock` |
| `test_contract_goes_red_on_violation[no-reverse-dependency]` | 探针 `repository/repo_probe.py`：`from aicore.service import desensitize`（**契约 3 的首条红证据**） |
| `test_contract_goes_red_on_violation[core-independent]` | 探针 `core/core_probe.py`：`from aicore.api import health` |
| `test_allowed_provider_base_import_is_kept` | **正例**：`service → provider.base` 仍 KEPT（`.**` 放行的回归守 |
| `test_ignore_imports_still_needed_for_provider_base` | **反证**：把 `ignore_imports` 抽掉后同一条导入变红 → 证明那行放行真的在承载 |
| `test_provider_facade_reexport_is_forbidden` | M6 门面漏口的独立覆盖证据 |

每个阴性用例**先单判该契约**（`limit_to_contracts`）、**再全量判一次**，所以单跑一条也能知道是哪条契约没响（顺带解决 M8）。
探针写入/还原走 `probe_files()` 上下文管理器，还原在 `finally` 内，被覆盖的既有文件按内容回填。

**四条契约各自的真实红输出**（逐条注入，`--- 只判该契约 ---` 后为单判输出）：

```
########## api-no-repo-provider <- api/routes_probe.py ##########
api 层不得直接依赖 repository / provider BROKEN
Contracts: 0 kept, 1 broken.
aicore.api is not allowed to import aicore.repository:
-   aicore.api.routes_probe -> aicore.repository.task_repo (l.1)
SINGLE RESULT: False        FULL RESULT: False（另 3 条 KEPT）

########## service-provider-impl <- service/svc_probe.py ##########
service 层只可与 provider.base 交互，不得依赖具体通道实现 BROKEN (1 warning)
Contracts: 0 kept, 1 broken.
aicore.service is not allowed to import aicore.provider:
-   aicore.service.svc_probe -> aicore.provider.mock (l.1)
aicore.service is not allowed to import aicore.provider.mock:
-   aicore.service.svc_probe -> aicore.provider.mock (l.1)
SINGLE RESULT: False        FULL RESULT: False

########## no-reverse-dependency <- repository/repo_probe.py ##########
repository / provider / port 不得反向依赖 service BROKEN
Contracts: 0 kept, 1 broken.
aicore.repository is not allowed to import aicore.service:
-   aicore.repository.repo_probe -> aicore.service.desensitize (l.1)
SINGLE RESULT: False        FULL RESULT: False

########## core-independent <- core/core_probe.py ##########
core 不得依赖任何业务层 BROKEN
Contracts: 0 kept, 1 broken.
aicore.core is not allowed to import aicore.api:
-   aicore.core.core_probe -> aicore.api.health (l.1)
SINGLE RESULT: False        FULL RESULT: False
```

正例与反证（`test_allowed_provider_base_import_is_kept` / `test_ignore_imports_still_needed_for_provider_base`）实测：

```
Probe C-direct-service-base :: service/svc_probe.py  （from aicore.provider import base）
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 ignored import)
Contracts: 4 kept, 0 broken.        RESULT True
```

#### I3 — `find_swallowed_exceptions` 的静默漏报（已修）

- 新增 `iter_handler_flow()`：只走处理块**自身**语句流，**不下探** `FunctionDef` / `AsyncFunctionDef` / `Lambda` / `ClassDef`。
- **额外发现（评审未点名，我实测后一并修）**：只挡嵌套作用域还不够——内层 `try/except` 里的 `raise` 也会被算进外层处理块。
  我最初只挡四个嵌套作用域节点，`test_guard_ignores_raise_inside_nested_scope` 立刻抓到：
  `except Exception:` 里套 `try/except ValueError: raise` 时外层被判为「已重新抛出」（`assert [] == [4]` 失败）。
  修法是把 `ast.ExceptHandler` 也列为边界——**每个处理块单独判定**，这才是「不含 raise 即违规」的正确读法。
- 条件式重新抛出按**有意接受的边界**处理（`if strict: raise` 判为已重新抛出），理由写进 `find_swallowed_exceptions` 的 docstring：
  AST 无法证明条件恒假，连它一起判违规会让「偏严」退化成「凡带判断都要写豁免」，反而促使作者删掉判断；
  代价是「写了 raise 但条件恒不成立」扫描不到，由人工评审兜住。

新增/强化的用例（全部通过）：`test_guard_ignores_raise_inside_nested_scope`（嵌套 def / lambda / class / 内层 except 四种）、
`test_guard_accepts_conditional_reraise`、`test_guard_detects_swallowing`（保留原样）。

真实输出（证据脚本，探针定义 import 自测试文件本身）：

```
嵌套 def 里的 raise + 外层吞异常: [4]        ← 修复前是 []（漏报）
条件式重新抛出: []                          ← 有意接受的边界
内层 except 的 raise（外层仍吞）: [4]        ← 本轮新发现并修掉
无 raise 的普通吞异常: [4]
```

#### I4 — 缓存残留（已修）

`lint_imports(..., cache_dir=None)` 关闭缓存（import-linter 2.15 的公开参数，`None` 即禁用），删掉 `rmtree` 与 `shutil` 依赖。
理由：本沙箱的 `tempfile.gettempdir()`（`C:\Users\…\AppData\Local\Temp\dsh-*`）**不可写**（`PermissionError [Errno 13]`），
故不能指向系统临时目录；`None` 是唯一既不落仓库也不依赖系统临时目录的选项。

**残留清零实测**（全量 pytest 之后）：

```
### residue: .import_linter_cache = False
=== probe files under services/aicore (excl .venv) === 0
=== git diff --stat（HEAD 与工作区）=> 空
```

#### M5 — 豁免正则收紧（已修）

`SWALLOW_EXEMPT` 单一正则改为 `SWALLOW_EXEMPT_PATTERNS` 元组 + `has_swallow_exemption(line)` 函数。
理由必填由 `\S+` 强制，实测：

```
 True  <- except Exception:  # ai-allow-swallow: 已上报并转默认值
False  <- except Exception:  # ai-allow-swallow:
False  <- except Exception:  # ai-allow-swallow
 True  <- except Exception:  # noqa: ai-allow-swallow: 兼容写法
False  <- except Exception:  # noqa: ai-allow-swallow
False  <- except Exception:
```

（对评审给的 `r"#\s*noqa:\s*ai-allow-swallow:\s*\S+"` 做了一处偏离：**必须**保留不要求 `noqa:` 前缀的形式，
否则 M9 选定新写法后全部豁免都会失效。两种写法都要求理由，未放松任何东西。见 M9。）

#### M6 — provider 门面（已修，但实测结论与评审描述有一处不同，如实记录）

已把 `aicore.provider` 加进契约 2 的 `forbidden_modules`，并补了一条**永久回归用例**守住它。
但实测显示：**门面再导出 `aicore.provider.*` 内部的模块时，未列整包的旧配置本来也能抓到**——
因为契约 2 默认走间接路径，会打印两跳链路：

```
旧配置（未列 aicore.provider）: aicore.service is not allowed to import aicore.provider.mock:
-   aicore.service.svc_probe -> aicore.provider (l.1)
    aicore.provider -> aicore.provider.mock (l.2)
```

**真正只能靠「列整包」补上的漏口**，是门面再导出**非 `aicore.provider.*`** 的符号。实测对照
（探针：`provider/__init__.py` 追加 `from aicore.port.facade_probe import *`，service 写 `import aicore.provider`）：

```
旧配置（未列 aicore.provider）      => Contracts: 4 kept, 0 broken.   ← 漏判
现行配置（列了 aicore.provider）    => service 层… BROKEN
                                      aicore.service is not allowed to import aicore.provider:
                                      -   aicore.service.svc_probe -> aicore.provider (l.1)
```

已把这个对照写进 `.importlinter` 的注释，并落成 `test_provider_facade_reexport_is_forbidden`——删掉那行 `aicore.provider` 该用例立刻变红。

**`warn` 的现状（按要求保留，未改成 `error`）**——干净代码实测输出：

```
Analyzed 50 files, 0 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
Warnings: service 层只可与 provider.base 交互，不得依赖具体通道实现
- No matches for ignored import aicore.service.** -> aicore.provider.base.
```

即：**警告仍在**。它现在**确实**对应一条真实缺口（service 尚无 `provider.base` 导入），不是配置写错；
Task 4 落地 Protocol 导入后应自动消失。注意「让 ignore 行变 load-bearing」的判定不是看有无警告，
而是看 `test_ignore_imports_still_needed_for_provider_base`：抽掉放行后 `service → provider.base` 会变红 → 该行确实是承重的。

#### M7 — 规则 5 的非空下限（已修；库清单按 brief 原样保留）

- 加 `MIN_SCANNED_FILES = 20` 与 `test_rule_5_scan_is_not_vacuous()`：同时断言「扫描文件数 ≥ 20」且「参与断言的模块非空」。
  实测基线 `iter_python_files() -> 50`，下限取 20 是防「扫描根失效 → 参数化静默收集 0 个用例 → 全绿」。
- `urllib.request` / `http.client`：**未加**。design.md 禁止项 5 的原文是
  「只有 `provider/` 下的模块可以发起外部模型 HTTP 调用（**`httpx` 的模型调用仅出现在该包内**）」，
  brief 也把库清单定为 `("httpx","requests","aiohttp")`；擅自扩列会与 brief 口径冲突，故按「不改 brief 清单」处理。
  另外实测确认规则 5 仍是**文本正则**，`import httpx` 出现在注释/文档串里会误报——两条一起列为后续建议（见文末）。

#### M8 — 契约 1 阴性用例的精确断言（已修）

不再只断言 `is False`：每条阴性用例先 `limit_to_contracts=(该契约 id,)` 单判（失败时 pytest 报错直接点名该契约），
再全量判一次确认「只有该契约红」。实测四条各自的 `SINGLE RESULT: False` / 全量 `3 kept, 1 broken` 见 I2 证据块。

#### M9 — `# noqa:` 前缀引发的 ruff 警告（已修：换掉 noqa 前缀，两种写法都接受）

**实测结论**：不存在「保留 `# noqa: ai-allow-swallow: <理由>` 又不让 ruff 警告」的干净写法。逐变体实测
（`ruff check --stdin-filename src/aicore/probe_variant.py -`）：

| 写法 | ruff 结果 |
|---|---|
| `# noqa: ai-allow-swallow: 理由` | `warning: Invalid # noqa directive … expected a comma-separated list of codes` |
| `# noqa: ai-allow-swallow`（裸） | 同上 |
| `# noqa: BLE001 ai-allow-swallow: 理由` | 同上 warning **+** `RUF100 Unused noqa directive` |
| `# noqa: SIM105 ai-allow-swallow: 理由` | `RUF100 Unused noqa directive` |
| `# noqa: SIM105, ai-allow-swallow: 理由` | `RUF100 Unused noqa directive` |
| `# noqa: SIM105  # ai-allow-swallow: 理由` | `RUF100 Unused noqa directive` |
| **`# ai-allow-swallow: 理由`（不带 noqa 前缀）** | **无警告、无报错** |

根因：ruff 把 `# noqa:` 后面的整串当**规则码列表**解析，任何非规则码 token 都会触发警告；把有效码放前面则由 RUF100 接手报未使用。

**选定方案**：正式写法改为不带前缀的 `# ai-allow-swallow: <理由>`（ruff 完全不介入），
**同时**让扫描继续接受 `# noqa: ai-allow-swallow: <理由>` 作为兼容写法（早期文档口径不失效）。
三处同步已做：① 扫描（`SWALLOW_EXEMPT_PATTERNS` + docstring 说明）；② 两个受检文件 `service/desensitize.py`、`service/verdict.py` 的 docstring；
③ 计划文档 `docs/superpowers/plans/2026-09-16-aicore-architecture.md`（4 处口径 + 1 处代码片段正则 + 1 处「以实际文件为准」提示）。

> **需你知悉的范围扩张**：计划文档不在本任务「Files」清单里，但 M9 明确要求「计划口径」同步，且该文档里嵌着
> 会被后续组照抄的代码片段（旧正则、旧扫描函数），不标注就会把已修的漏洞重新抄回来。我的改动是**有界的**：
> 只改豁免指令口径与那一条正则，并加了一条「本片段是首版、以实际文件为准」的提示；不改计划的任务结构或验收标准。
> 若你认为计划文档不该由我改，`ad1c341` 可以单独 revert（`f4f77c7` 不依赖它）。

#### M10 — 探针写入真实源码树（信息性，无改动）

已按要求只在报告中记录：阴性探针与门面用例都要写真实源码树（import-linter 只认磁盘包结构），
写入点全部在 `probe_files()` 的 `try` 内、还原在 `finally` 内；`provider/__init__.py` 这类既有文件按内容回填，
其余探针文件 `unlink(missing_ok=True)`。本轮所有运行后的 `git status` / `git diff HEAD` 均为空，实测见 I4 与文末。

---

### 门禁与验证（真实输出，全部在最终提交后的工作区上重跑）

```
### lint-imports --config .importlinter --no-cache
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
- No matches for ignored import aicore.service.** -> aicore.provider.base.
EXIT=0

### pytest tests/structural -p no:cacheprovider
60 passed, 7 skipped in 0.29s        EXIT=0

### pytest（全量）
60 passed, 7 skipped in 0.32s        EXIT=0

### ruff check --no-cache tests src
All checks passed!                    EXIT=0

### ruff format --check --no-cache tests src
55 files already formatted            EXIT=0

### mypy --cache-dir .venv\mypy_cache tests/structural
Success: no issues found in 3 source files     EXIT=0

### 残留
.import_linter_cache = False
probe 文件（仓库内，排除 .venv）= 0
git diff HEAD --stat = 空
```

规则 5、规则 6 的阴性注入**在本轮重新跑过**（不是引用上一轮结论）：

```
# 规则 5：src/aicore/service/ocr_match.py 追加一行 import httpx
collected 59 items / 9 deselected / 50 selected
E  AssertionError: src\aicore\service\ocr_match.py 出现外部模型调用库 ['httpx']，违反规则 5
FAILED tests/structural/test_source_guards.py::test_model_http_calls_only_in_provider[service\\ocr_match.py]
1 failed, 42 passed, 7 skipped, 9 deselected
→ 还原后 git diff 该文件为空

# 规则 6：src/aicore/service/desensitize.py 追加 try/except: return None
collected 59 items / 57 deselected / 2 selected
E  AssertionError: service/desensitize.py 在第 [15] 行的 except 块中未重新抛出异常。…确需吞异常请加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填）
FAILED tests/structural/test_source_guards.py::test_no_silent_degradation_in_guarded_files[service/desensitize.py]
1 failed, 1 passed, 57 deselected      ← verdict.py 同轮 passed，未联动误伤
→ 还原后 git diff 该文件仅剩本轮的 docstring 口径改动
```

**编码复核（提交后）**：`.importlinter`、两个测试文件、两个受检文件均 `BOM=False utf8=True` 纯 LF；
计划文档 `BOM=False utf8=True` 纯 CRLF（与仓库既有行尾一致，`core.autocrlf=true`，入库仍是 LF）。
提交对象内的 `.importlinter` 也复核过：`BOM False utf8 True bytes 5355 has_cn True`。

### 提交前 hook 检查的逐项手工复现（`--no-verify`，`sh` 不在 PATH）

`pre-commit`（`.githooks/pre-commit`）6 项 + `commit-msg` 1 项，逐项手工执行：

| hook 检查项 | 手工复现结果 |
|---|---|
| 1 合并冲突标记 | `none` |
| 2 行尾空白 / 末尾多余空行（`git diff --cached --check`） | `clean`（退出码 0） |
| 3 大文件 >1MB | 最大 62407 bytes（计划文档） |
| 4 私钥块 / 云密钥（`AKIA…`/`ASIA…`） | `none` |
| 5 疑似硬编码凭据正则 | `none` |
| 6 真实 `.env` 入库 | `none` |
| `commit-msg` Conventional Commits | `PASS: 'fix(aicore): 分层契约间接导入语义与结构检查评审修复'` |
| 不带 `[AI]` 前缀 | `PASS` |
| 提交粒度 | 拆两个单一目的提交（代码检查修复 / 文档口径同步），无夹带 |

语义级自查：注释与文档全中文、标识符全英文；无 SQL 拼接 / XSS / 敏感信息入日志；本轮新增的安全相关逻辑
（契约 4 条阴性证据、豁免理由必填、嵌套作用域边界、门面回归）**全部带测试**。

### 自查 diff 后追加的发现与修正（本轮内）

1. **内层 `except` 的 `raise` 会污染外层判定**（评审未点名）：新增用例当场抓到 `assert [] == [4]`，
   已把 `ast.ExceptHandler` 一并列为 `iter_handler_flow` 的边界。
2. **提交卫生**：我第一次 `git commit --amend` 时把 `.importlinter` 误带进 `docs` 提交（变成「docs 提交改测试配置」）。
   该分支无上游（`git branch -a --contains` 只有本地 `feature/aicore-architecture`），已用 `reset --soft` + 重新分两次提交修正，
   最终 `f4f77c7`（5 文件，含 `.importlinter` 最终版）/ `ad1c341`（仅计划文档）。工作区与 HEAD 无差异。
3. **`.importlinter` 的多行值内注释安全性**：我在 `forbidden_modules` 列表中间插了整行注释，实测 `read_user_options()`
   解析结果干净（`forbidden_modules = ['aicore.provider', 'aicore.provider.mock', …]`，注释未被卷入），
   不会像 `unmatched_ignore_imports_alerting` 那样把后续行吞进多行值。
4. **对评审 M6 描述的一处不同意见**（已如实记录、未静默照办）：门面再导出 `aicore.provider.*` 时旧配置本就能抓到（走间接路径）；
   真正的独立覆盖是再导出**非 `aicore.provider.*`** 的符号。改动本身照做，但理由按实测重写了配置注释与用例。

### 遗留建议（不属本轮修复范围，供你裁定）

1. **规则 5 仍是文本正则**：`urllib.request` / `http.client` / 各厂商 SDK 扫不到；反向地，注释或 docstring 里出现
   `import httpx` 会误报。彻底解法是改成 AST 扫描（`ast.Import` / `ast.ImportFrom` 取顶层包名），
   但会改变 `HTTP_IMPORT_RE` 这个已导出的可复用符号与 brief 约定，需要你确认后另起一轮。
2. **计划文档内嵌的测试片段已过期**（`find_swallowed_exceptions` 旧实现等）：本轮只加了一句「以实际文件为准」的提示，
   没有重写整段片段——把长代码块同步进计划文档属于计划维护，建议由你在 Task 1.4 之前统一处理。
3. 上一轮遗留的 `.sdd-*.py`（现为 7 个）仍未跟踪、未删除，按授权「leave those alone」处理。

---

## 修复轮 2（复评 Minor）

复评结论为「All findings addressed，无新增 Critical/Important」，本轮消化剩余 Minor：F1~F4 已改，F5 按授权**只报告不改**（brief 由控制器重新生成）。

**提交**

| 提交 | 内容 |
|---|---|
| `bb7f8fc` | `fix(aicore): 结构检查复评 Minor 修复（探针字节还原与判别力）`——F1/F2/F3（3 文件：`.importlinter`、两个结构测试） |
| `21cef10` | `docs(aicore): Task 1.3 计划片段与落地文件对齐`——F4（计划文档；同时带入控制器本轮已改的 8 行模板内容） |

工作区提交后 `git diff HEAD` 为空；`git status --short` 只剩控制器的 7 个 `.sdd-*.py`（按授权不动）。

### F1 —— 探针按字节还原（真实缺陷，已修）

**问题**：`probe_files()` 用 `Path.read_text` / `write_text`（文本模式）备份还原。Windows 上 `write_text` 把 `\n` 写成 `\r\n`，于是「被覆盖文件在磁盘上是 LF」的检出里，还原会把文件改写成 CRLF——测试自己改了仓库，而 `core.autocrlf=true` 的检出里 `git status` 反而看不出来（本检出正是这种：门面在磁盘上是 CRLF，所以旧写法恰好往返无损）。

**改动**（`services/aicore/tests/structural/test_layering.py`）
- `probe_files()`：备份 `path.read_bytes()`、还原 `path.write_bytes(backup[path])`、写入 `path.write_bytes(content.encode("utf-8"))`——全程字节，对行尾中立。
- 新增 `read_source_exact()`：门面 `provider/__init__.py` 按原样读取（不做换行翻译），追加行沿用文件自身行尾（CRLF/LF），避免探针文件内混合行尾。
- 未动的文本写入只有一处：变异配置 `.importlinter_nonexistent` 是**新建后删除**的临时文件，不存在"还原既有文件"的路径，无同样缺陷。

**红：修复前，LF 检出会被改写成 CRLF**（把门面置为 LF 后跑会覆盖它的门面用例）

```
--- BEFORE (pre-fix code) ---
__init__.py: CRLF=1 LF=0 bytes=86 sha256=442e1c97f00e0299
已写入 LF 版本：
__init__.py: CRLF=0 LF=1 bytes=85 sha256=0feb139172d7a0e7
--- run facade probe test (pre-fix) ---
.                                                                        [100%]
EXIT=0
--- AFTER ---
__init__.py: CRLF=1 LF=0 bytes=86 sha256=442e1c97f00e0299      ← 85 字节的 LF 被写成 86 字节的 CRLF
--- git diff (normalized) ---
（空：core.autocrlf=true 把行尾归一化，git 看不出这次改写）
```

**绿：修复后，同一场景字节不变**（LF 门面 + 全量结构用例，含全部探针用例）

```
已写入 LF 版本：
__init__.py: CRLF=0 LF=1 bytes=85 sha256=0feb139172d7a0e7
src/aicore 文件数=50 全树指纹=d12e1f935c6e21a616d49d460eda007b
................................................................    [100%]
62 passed, 7 skipped in 0.54s
EXIT=0
--- AFTER ---
__init__.py: CRLF=0 LF=1 bytes=85 sha256=0feb139172d7a0e7      ← 行尾与字节完全不变
src/aicore 文件数=50 全树指纹=d12e1f935c6e21a616d49d460eda007b  ← 全树逐文件 sha256 汇总不变
```

（指纹是「路径 + 字节」的 sha256 汇总，`src/aicore` 下 50 个文件任何一个字节变化都会变。验证后门面用 `git checkout --` 还原为检出原始形态：CRLF=1、86 字节、sha256=442e1c97f00e0299。）

### F2 —— lambda 子例改为可判别（已修，并让判别力在用例内自证）

**问题**：原子例 `handler = lambda: exec('raise RuntimeError()')` 把 `raise` 写在**字符串**里，AST 里没有 `ast.Raise` 节点，因此修复前的 `ast.walk` 实现与修复后的实现都返回 `[4]`，断言对两侧同样成立——等于没测嵌套作用域边界。

**根因（实测的语法事实）**：`lambda` 体是 expression、`raise` 是语句，源码里根本构造不出「Lambda 子树内含 Raise」：

```
SyntaxError | lambda: (raise RuntimeError())                | invalid syntax
parsed      | lambda: exec('raise RuntimeError()')          | Raise nodes = 0
parsed      | lambda: (_ for _ in ()).throw(RuntimeError()) | Raise nodes = 0
parsed      | lambda: (yield 1)                             | Raise nodes = 0
```

所以评审批复里「lambda 体直接 raise / lambda 内嵌函数」两种写法都不可构造（后者同样非法）。**改法**：
1. `nested_lambda` 子例改为「lambda 调用处理块内的真实嵌套 `def`」——`raise` 语句真实存在于处理块内，修复前的 `ast.walk` 会把它当成"已重新抛出"而漏报；
2. 新增 `test_handler_flow_stops_at_lambda_boundary`：用普通表达式作标记（`lambda: _lambda_body_marker()`）直接验证遍历不下探 lambda 体——这是 lambda 这类"raise 进不去、但边界必须守着"的作用域唯一可判别的验证方式；
3. 新增 `test_lambda_body_cannot_hold_raise_statement`：把"lambda 里写不出 raise"固化为语法事实断言，并断言旧的字符串写法在两侧实现下结果相同（`_legacy_find_swallowed == find_swallowed_exceptions == [4]`），即**旧子例不判别**这条证据也固化在用例里；
4. 判别力不再靠人工复核：测试内保留修复前实现的复刻 `_legacy_find_swallowed()`（抄自计划文档首版片段），每个边界子例都过 `assert_boundary_is_discriminating()`——同时断言「旧实现漏报」+「新实现报违规」，任一不成立即红。顺带补了此前未覆盖的 `AsyncFunctionDef` 边界子例。

**判别力实测（三次变异，每次都把文件按字节还原，sha256 一致）**

```
### mutation pre-fix-walk：把 find_swallowed_exceptions 换回 ast.walk 全深度下探
E   AssertionError: nested_def 子例未被检出：嵌套作用域边界失守（嵌套作用域里的 raise 被当成重新抛出）
FAILED tests/structural/test_source_guards.py::test_guard_ignores_raise_inside_nested_scope
[pre-fix-walk] pytest 退出码 = 1（期望非 0 = 用例变红）

### mutation no-lambda-boundary：NESTED_SCOPE_NODES 去掉 ast.Lambda
E   AssertionError: 遍历越过 lambda 边界，下探到 lambda 体内：交出的名字有 ['Exception', '_lambda_body_marker', 'handler']
FAILED tests/structural/test_source_guards.py::test_handler_flow_stops_at_lambda_boundary
[no-lambda-boundary] pytest 退出码 = 1

### mutation restore-old-lambda-sample：把 nested_lambda 样本换回旧的字符串写法
E   AssertionError: nested_lambda 子例失去判别力：修复前的 ast.walk 实现也报了违规，说明该样本没把 raise 藏进嵌套作用域
FAILED tests/structural/test_source_guards.py::test_guard_ignores_raise_inside_nested_scope
[restore-old-lambda-sample] pytest 退出码 = 1

[pre-fix-walk]            已还原，sha256 一致 = True (163194bec11b7ef6)
[no-lambda-boundary]      已还原，sha256 一致 = True (163194bec11b7ef6)
[restore-old-lambda-sample] 已还原，sha256 一致 = True (163194bec11b7ef6)
=== 变异测试结束：异常项 0 ===
```

第三条变异正是"新子例可判别"的直接证据：若沿用旧样本，用例当场变红（失去判别力）；换成新样本后绿。第一条证明"新实现报违规"确由嵌套作用域边界带来；第二条证明 lambda 边界本身被守住。

### F3 —— 三处夸大说明（已修，全部按"改注释 / 补断言"处理，未放松任何检查）

| 位置 | 原话 | 结论 | 改法 |
|---|---|---|---|
| `test_layering.py` 阴性用例 | "再全量判一次：确认注入的违规没有顺带打翻其它契约" | 一个布尔值看不出是谁红的，断言支撑不了这句 | **补断言**：整体必须变红之后，逐条 `limit_to_contracts` 断言其余三条契约仍为 `True`（红在哪条会直接点名） |
| `test_layering.py::test_layering_contracts_pass` | "全部分层契约必须通过，**且不得有未匹配的放行表达式**" | `.importlinter` 里 `unmatched_ignore_imports_alerting = warn`，未匹配只出 warning，永远不会让该断言失败 | **改注释**：说明该断言只证明四条契约整体 KEPT；未匹配警告当前确实存在（`aicore.service.** -> aicore.provider.base`），并由另外两条放行用例正面守住 |
| `.importlinter` 契约 4 末行 | "**本契约**三条不变量均取默认 false" | 三处 `allow_indirect_imports` 默认值分属契约 2、3、4 | **改注释**："契约 2、3、4 均未写 `allow_indirect_imports`（三次都取默认 false），与契约 1 的 true 形成对照" |

`.importlinter` 只改注释，未动任何配置项：四契约、`allow_indirect_imports`、`ignore_imports`、`unmatched_ignore_imports_alerting` 与上一轮完全一致（提交后 lint-imports 实测仍 `4 kept, 0 broken`）。

### F4 —— 计划文档一致性（已修，采用"权威指针 + 改过期表述"）

`docs/superpowers/plans/2026-09-16-aicore-architecture.md`（控制器已改的 `.importlinter` 模板 8 行**原样保留、未重做**）：

1. **Step 1 前加权威指针**（与控制器给 `.importlinter` 模板的写法一致）：以 `services/aicore/tests/structural/test_layering.py` 实际文件为准，并点名三处差异——四条契约各自一条参数化阴性用例、所有 lint 调用传 `cache_dir=None` 关缓存（不再 rmtree）、另有放行正例与"抽掉 ignore_imports 必变红"反证。
2. **Step 4 标题与 `Expected: 2 passed`** 改为以实际用例数为准（不再是"两个用例"/2 passed）。
3. **Step 1 片段里的 `shutil.rmtree(...)` 缓存清理**删除，连同随之无用的 `import shutil`；原位留一行注释说明 shipped 版本统一传 `cache_dir=None`。
4. **Step 5 的"修复轮 1 提示"补一句**：豁免指令同样以实际文件为准——shipped 是 `SWALLOW_EXEMPT_PATTERNS`（正式写法 + 兼容 `noqa:` 写法，理由必填）加 `has_swallow_exemption()`，片段里那条旧正则不再代表实现。

行尾复核：计划文档仍为纯 CRLF（CRLF=1560、裸 LF=0）、UTF-8 无 BOM；`git diff` 为逐行改动（25 增 4 删），无整文件重写。

### F5 —— 控制器 brief 的过期行清单（只报告，未改）

按授权未改 brief。以下行仍是修复轮 1 之前的形态，需你重新生成：

**`.superpowers/sdd/2026-09-16-aicore-architecture/task-1.3-brief.md`**

| 行号 | 过期内容 | 落地形态 |
|---|---|---|
| L70 | `shutil.rmtree(PROJECT_ROOT / ".import_linter_cache", ignore_errors=True)` | 所有 lint 调用传 `cache_dir=None`，不产生缓存目录 |
| L153 | `Expected: \`2 passed\`` | 四契约参数化阴性 + 放行正例 + 反证（本轮后结构用例 62 passed / 7 skipped） |
| L167 | 要求写 `# noqa: ai-allow-swallow: <理由>` | 正式写法不带 `noqa:` 前缀；`noqa` 形式仅作兼容 |
| L188 | `SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")`（理由可选、单条正则） | `SWALLOW_EXEMPT_PATTERNS` 两条正则（理由必填 `\S+`）+ `has_swallow_exemption()` |
| L226 | `if not SWALLOW_EXEMPT.search(lines[lineno - 1])` | `if not has_swallow_exemption(lines[lineno - 1])` |
| L231 | 报错信息里的 `# noqa: ai-allow-swallow: <理由>` | 同上，改为不带前缀的正式写法 |

同属首版片段、一并过期的次要行（同一批重生成时一并处理即可）：`L13-15`「已实测的关键写法」第 2 条（断言 `forbidden_modules` 写 `aicore.provider` 会连带禁止 `aicore.provider.base`、必须精确枚举——shipped 是整包禁止 + 递归通配 `ignore_imports` 放行）、`L43`（`def lint() -> object`，实际是 `Callable[..., bool]`）、`L144`（"运行，确认**两个**用例都通过"）。

**`.superpowers/sdd/2026-09-16-aicore-architecture/task-1.2-brief.md`**

| 行号 | 过期内容 | 落地形态 |
|---|---|---|
| L128 | `service/desensitize.py` docstring 要求写 `# noqa: ai-allow-swallow: <理由>` | 同上：正式写法不带 `noqa:` 前缀 |

### 门禁与验证（真实输出，全部在提交后的工作区重跑）

```
### lint-imports --config .importlinter --no-cache（干净树，无探针）
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
- No matches for ignored import aicore.service.** -> aicore.provider.base.
EXIT=0

### pytest tests/structural -p no:cacheprovider
62 passed, 7 skipped in 0.45s        EXIT=0        （本轮 +2：lambda 边界用例、lambda 语法事实用例）

### pytest（全量）-p no:cacheprovider
62 passed, 7 skipped in 0.57s        EXIT=0

### ruff check --no-cache tests src
All checks passed!                    EXIT=0
### ruff format --check --no-cache tests src
55 files already formatted            EXIT=0
### mypy --cache-dir .venv\mypy_cache tests/structural
Success: no issues found in 3 source files     EXIT=0
### mypy --cache-dir .venv\mypy_cache（src，pyproject files=src）
Success: no issues found in 50 source files    EXIT=0
```

规则 5、规则 6 的阴性注入**本轮重新跑过**（不引用上一轮结论）；注入文件用 `git checkout --` 还原后 `git diff HEAD` 为空（该还原方式本身引入的 CRLF 问题与修法见文末自查第 3 条）：

```
# 规则 5：src/aicore/service/ocr_match.py 追加一行 import httpx
E   AssertionError: src\aicore\service\ocr_match.py 出现外部模型调用库 ['httpx']，违反规则 5
FAILED tests/structural/test_source_guards.py::test_model_http_calls_only_in_provider[service\\ocr_match.py]
1 failed, 42 passed, 7 skipped, 11 deselected in 0.06s        EXIT=1
→ 还原后 git diff HEAD = EMPTY

# 规则 6：src/aicore/service/desensitize.py 追加 try/except: return None
E   AssertionError: service/desensitize.py 在第 [16] 行的 except 块中未重新抛出异常。…确需吞异常请加 `# ai-allow-swallow: <理由>` 显式豁免（理由必填）。
FAILED tests/structural/test_source_guards.py::test_no_silent_degradation_in_guarded_files[service/desensitize.py]
1 failed, 1 passed, 59 deselected in 0.03s                    EXIT=1
→ verdict.py 同轮 passed（未联动误伤）；还原后 git diff HEAD = EMPTY
```

### 残留物清零

```
probe 文件数（services/aicore，排除 .venv）= 0
.import_linter_cache 目录数 = 0
.importlinter_nonexistent 存在 = False
仓库内 __pycache__ 目录数 = 0
pytest/ruff 缓存目录数 = 0
src/aicore 文件数=50 全树指纹=8d56782a2d5f53d720af8df7ecf22c65
    ← 与"提交后第一次门禁跑完"时的指纹逐字节一致，也覆盖了规则 5/6 注入 + 还原之后的复核
```

最终状态复核（规则 5/6 注入并还原之后重跑）：

```
### git status --short
?? .sdd-core-api-probe.py   ?? .sdd-il-indirect-probe.py   ?? .sdd-il-probe.py
?? .sdd-il-submodule-probe.py   ?? .sdd-scan.py   ?? .sdd-setup-db.py   ?? .sdd-tools.py
（只有控制器的 7 个助手；本轮临时脚本与消息文件已全部删除）
### git diff HEAD --stat
EMPTY
### 被注入又还原的两个源文件（工作区 vs 入库 blob 逐字节比较）
services/aicore/src/aicore/service/ocr_match.py    | 工作区 == 入库 blob: True | CRLF: 0
services/aicore/src/aicore/service/desensitize.py  | 工作区 == 入库 blob: True | CRLF: 0
```

**编码复核（提交后）**：`.importlinter` / `test_layering.py` / `test_source_guards.py` 均 `BOM=False utf8=True` 纯 LF；计划文档 `BOM=False utf8=True` 纯 CRLF（CRLF=1560、裸 LF=0，`core.autocrlf=true`，入库仍是 LF）。

### 提交前 hook 检查的逐项手工复现（`--no-verify`，`sh` 不在 PATH）

`.githooks/pre-commit` 6 项 + `.githooks/commit-msg` 1 项，**两次提交各自跑一遍**：

| hook 检查项 | 手工复现结果 |
|---|---|
| 1 合并冲突标记 | `none` |
| 2 行尾空白 / 末尾多余空行（`git diff --cached --check`） | `clean`（退出码 0） |
| 3 大文件 >1MB | 最大 64297 bytes（计划文档）；代码文件最大 15299 bytes |
| 4 私钥块 / 云密钥（`AKIA…`/`ASIA…`） | `none` |
| 5 疑似硬编码凭据正则 | `none` |
| 6 真实 `.env` 入库 | `none` |
| `commit-msg` Conventional Commits | `PASS` ×2（`fix(aicore): …` / `docs(aicore): …`） |
| 不带 `[AI]` 前缀 | `PASS` ×2 |
| 提交粒度 | 拆两个单一目的提交：代码/配置修复（F1~F3）与计划文档对齐（F4），无夹带 |

语义级自查：注释与文档全中文、标识符全英文；无 SQL 拼接 / XSS / 敏感信息入日志；本轮新增的检查逻辑（判别力自证、lambda 边界、语法事实）**全部带测试**。

### 自查 diff 后追加的发现与修正（本轮内）

1. **仓库内既有缓存残留（先于本会话，已清理）**：`services/aicore` 下有 11 个 `__pycache__` 与一个 `.mypy_cache`，mtime 为 16:54~17:52，本会话首个文件创建于 18:13，故非本轮产物；其中还留着一个孤儿 `tests/__pycache__/test_tmp_pythonpath_probe.cpython-314-pytest-9.1.1.pyc`（源文件早已不存在）。二者均被 `services/aicore/.gitignore` 忽略，已删除并在清理后的树上重跑全部门禁：不再出现（`PYTHONPYCACHEPREFIX` 与 `--cache-dir` 把字节码与 mypy 缓存都导向 `.venv/` 下）。
2. **F1 的同类风险已复查完**：测试目录内所有 `write_text` 只出现在 `test_layering.py:187`（新建后删除的变异配置），不存在"还原既有文件"的文本模式路径；`read_text`（扫描用）只读不写，无风险。
3. **本轮我自己踩到一次同类问题（已修，属 F1 的同一类）**：规则 5/6 的注入源文件我用 `git checkout --` 还原，而本检出 `core.autocrlf=true`——checkout 会把入库为 LF 的文件在工作区落成 **CRLF**。于是 `git ls-files --eol` 从 `w/lf` 变成 `w/crlf`（同目录另外 10 个文件仍是 `w/lf`，且修复轮 1 报告已记录这两个受检文件为纯 LF），而 `git diff HEAD` 依旧是空的——正是 F1 描述的"git 看不出来的工作区改写"。处理：按字节把两个文件归一化回 LF（CRLF→LF，无孤立 CR，机械可逆），再用 `git update-index --refresh` 刷新索引 stat 缓存（此前 `git status` 会因 autocrlf 的 stat/size 失配把这两个文件报成 ` M`，即使 `git diff HEAD` 为空）。复核：12 个 service 文件全为 `w/lf`、两文件与入库 blob 逐字节相等、`git status --short` 不再列出它们、src 全树指纹回到 `8d56782a…`。
4. **计划文档一处遗留排版问题（未改，仅报告）**：修复轮 1 提示块结尾多一个孤立 `**`（`> …勿照抄本片段。**`），markdown 会原样显示。它不在 F4 点名的三处之内，故未动，留给你在下次重生成计划时顺手修掉。
5. **对 F2 评审建议的一处不同意见（已如实记录）**：批复建议"lambda 体内放真实 `raise`（或 lambda 内嵌函数）"，但两者都是语法错误（lambda 体是 expression），源码层不可构造。故按"可判别的等价写法"落地（lambda 调用处理块内的嵌套 def + 直接验证 lambda 边界的标记用例 + 语法事实用例），**没有**因写不出来就删掉 `ast.Lambda` 这条边界——边界仍在 `NESTED_SCOPE_NODES` 里，且有专门的用例守着它。
