# Task 1.2 执行报告：分层目录与模块契约

工作区：`D:\progrom\.worktrees\aicore-architecture`（分支 `feature/aicore-architecture`，基线 `b98f251`）
解释器：`D:\progrom\.worktrees\aicore-architecture\services\aicore\.venv\Scripts\python.exe`（Python 3.14.6）
结论：**DONE_WITH_CONCERNS** —— brief 的 18 个 Step 全部执行完毕，50 个文件入库，全部验证通过；两项需计划裁定的偏差（模块数 49 与 brief 期望 30 不符、`main.py` 归属）已在 §9 逐条给出证据与建议。**未派发任何子代理。**

---

## 1. 交付物：50 个新文件（每行一句职责）

全部为**空壳**（仅模块文档串；`provider/base.py` 除外，含三个真实 `Protocol`）。职责列即入库 docstring 的原文。

### `core/`（11 个）— 横切关注点

| 文件 | 职责（docstring 原文） |
|---|---|
| `core/__init__.py` | 横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 setup.cfg 契约） |
| `core/config.py` | 配置模型。Task 2.1 实现 Pydantic Settings 与启动四条校验 |
| `core/errors.py` | 异常层次与错误码常量。Task 2.3 实现 |
| `core/envelope.py` | 统一响应信封（code/message/traceId/timestamp）。Task 2.4 实现 |
| `core/trace.py` | traceId 上下文变量与传播（请求头 X-Request-Id）。Task 2.5 实现 |
| `core/logging.py` | 结构化 JSON 日志（11 必含字段）。Task 2.6 实现 |
| `core/idgen.py` | 前缀化分布式 ID（前缀 + UUID，总长 ≤32）。Task 3.8 实现 |
| `core/security.py` | 内部 Token 校验（请求头 X-Internal-Token）。第 4 组实现 |
| `core/ratelimit.py` | Redis 令牌桶限流（业务码 2004）。第 4/9 组实现 |
| `core/budget.py` | 成本三层护栏（日配额 / 全局预算 / 调用方归因）。第 9 组实现 |
| `core/task_runner.py` | 任务执行器内核（领取 / 租约 / 重试 / 线程池边界）。第 4 组实现 |

### `api/`（6 个）— 协议适配层（MUST NOT 直接访问 repository / provider）

| 文件 | 职责 |
|---|---|
| `api/__init__.py` | 协议适配层。仅做入参校验与协议转换 |
| `api/deps.py` | 依赖注入提供者（FastAPI Depends 装配点）。Task 1.4 填实 |
| `api/health.py` | 存活与就绪检查。Task 1.4 实现 |
| `api/ocr.py` | 证照 OCR 提交与结果。第 4 组实现 |
| `api/tasks.py` | 任务查询回执。第 4 组实现 |
| `api/habit.py` | 习惯与购买影响因素无状态计算（服务端间）。第 10 组实现 |

### `service/`（12 个，含两个子包）— 业务编排层

| 文件 | 职责 |
|---|---|
| `service/__init__.py` | 业务编排层。只依赖 provider 的 Protocol、repository 与 port |
| `service/ocr_service.py` | OCR 任务编排。第 4 组实现 |
| `service/ocr_match.py` | 有效期与经营类目比对（纯函数）。第 4 组实现 |
| `service/accuracy.py` | 纠错回流与固定评估集回归。第 5 组实现 |
| **`service/desensitize.py`** | **合规红线 D4 / R-03 受检文件**（8 行 docstring，见 §2） |
| `service/verdict.py` | C8 权威回写前置条件：无人工复核结论则不存在回写入口。第 8 组实现 |
| `service/habit/__init__.py` | 习惯计算纯函数包（无 IO、无写库路径）。第 10 组实现 |
| `service/habit/engine.py` | 习惯计算引擎（纯函数，无 IO、无写库路径）。第 10 组实现 ★ |
| `service/habit/decay.py` | 证据时间衰减权重（纯函数，无 IO、无写库路径）。第 10 组实现 ★ |
| `service/habit/evidence.py` | 购买影响因素证据生成（纯函数，无 IO、无写库路径）。第 10 组实现 ★ |
| `service/task/__init__.py` | 任务类型策略注册表。第 4 组实现 |
| `service/task/registry.py` | 任务类型 → 处理器注册表（OCR 已实现，其余预留）。第 4 组实现 |

★ = brief 未给原文、由我撰写的三行（见 §9.3）。

### `provider/`（7 个）— 唯一允许发起外部模型 HTTP 调用的层

| 文件 | 职责 |
|---|---|
| `provider/__init__.py` | 外部模型通道边界 |
| **`provider/base.py`** | **本层唯一被 service 依赖的文件**：`TextProvider` / `VisionProvider` / `OcrProvider` 三个 `@runtime_checkable Protocol`（45 行，brief 逐字） |
| `provider/selector.py` | 按配置选择模型通道。第 4 组实现 |
| `provider/mock.py` | 确定性 Mock 通道（离线测试与降级演练）。第 4 组实现 |
| `provider/deepseek.py` | DeepSeek 文本通道骨架。Task 4.3 实现；覆盖率排除 |
| `provider/cloud_vision.py` | 云视觉通道骨架。第 4 组实现；覆盖率排除 |
| `provider/cloud_ocr.py` | 云 OCR 通道骨架。第 4 组实现；覆盖率排除 |

### `repository/`（9 个）— 自有库数据访问层（MUST NOT 依赖 service）

| 文件 | 职责 |
|---|---|
| `repository/__init__.py` | 自有库数据访问层。MUST NOT 依赖 service（避免边界倒置使合规检查点失效） |
| `repository/task_repo.py` | 任务表数据访问。Task 3.7 实现 |
| `repository/ocr_repo.py` | OCR 结果表数据访问。Task 3.7 实现 |
| `repository/correction_repo.py` | 纠错回流表数据访问。Task 3.7 实现 |
| `repository/verdict_repo.py` | 复核结论表数据访问。Task 3.7 实现 |
| `repository/sharding.py` | 按月分表路由（物理表名 xxx_YYYYMM）。Task 3.3 实现 |
| `repository/session.py` | 会话与连接池（同步会话 + 线程池；写会话 / 只读会话分离）。Task 3.4 实现 |
| `repository/models.py` | SQLAlchemy 2.x 声明式模型（字段对齐 er.md §6）。Task 3.2 实现 |
| `repository/base.py` | repository 基类与跨分片操作守卫。Task 3.7 实现 |

### `port/`（4 个）— 跨服务出向端口

| 文件 | 职责 |
|---|---|
| `port/__init__.py` | 跨服务出向端口。只在 service 中被依赖，实现由组合根注入 |
| `port/cred.py` | CRED 权威数据回写端口（A-02 档案 / 信用分）。第 7 组实现 |
| `port/dash.py` | DASH 预警上报端口（A-08）。第 7 组实现 |
| `port/events.py` | 事件幂等键（authority_event_id）与每日对账。第 7 组实现 |

### `tests/`（1 个）

| 文件 | 职责 |
|---|---|
| `tests/structural/test_layering.py` | 分层依赖规则检查。Task 1.3 填实（占位，无用例） |

> `tests/structural/__init__.py` **未创建**：brief Step 15 只要求一个文件，Task 1.3 的 Files 清单（`Create: test_source_guards.py` / `Modify: test_layering.py`）同样未列它。已实测 pytest 能正常收集该目录（见 §5.3），无导入错误。

---

## 2. 逐字校验：入库 blob vs brief 上游文本

**方法**：从 `task-1.2-brief.md` 抽出全部 ` ```python ` 代码块（44 个）与全部行内 `"""…"""` 文档串（53 处，覆盖 Step 9 的行内写法），归一化为 LF + 单个结尾换行，然后**逐个读取 `HEAD` 的 blob**（`git cat-file -p HEAD:<path>`，不读工作区）做全等比较。

```
HEAD 树内目标路径 .py 文件数: 51
  VERBATIM-OK（与 brief 上游文本逐字一致）: 47
  本任务自行撰写文档串（brief 未给原文）  : 3 -> [habit/decay.py, habit/engine.py, habit/evidence.py]
  非本任务文件（Task 1.1 既有）          : 1 -> [src/aicore/__init__.py]
  既非逐字也非授权撰写（应为 0）          : 0
```

反向校验：brief 的 44 个代码块中**未被落盘使用的 = 0**，即没有遗漏任何一段给定文本。

`service/desensitize.py`（合规红线受检文件）入库全文，8 行逐字一致：

```python
"""图像脱敏前置阶段。

【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。

第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
"""
```

---

## 3. Step 16 验证：目录树与模块可导入

brief 原命令（`$root` 从 `D:\progrom\services\aicore` 适配到本 worktree），提交后复跑：

```powershell
$root = "D:\progrom\.worktrees\aicore-architecture\services\aicore"
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPYCACHEPREFIX = "$root\.venv\pycache\pyc"
Push-Location $root
& "$root\.venv\Scripts\python.exe" -c @"
import importlib, pkgutil, aicore
mods = [m.name for m in pkgutil.walk_packages(aicore.__path__, prefix='aicore.')]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        failed.append((m, repr(e)))
print(f'共 {len(mods)} 个模块')
for m, e in failed:
    print('导入失败:', m, e)
raise SystemExit(1 if failed else 0)
"@
Pop-Location
```

**真实输出（逐字复制的原始输出）：**

```
共 49 个模块
[Step16 exit code: 0]
```

- **模块数 = 49**，brief Step 16 期望 `共 30 个模块`（容差 ±2）→ **实测 +19，远超容差。**
- **导入失败 = 0 条**，退出码 **0**（`raise SystemExit(1 if failed else 0)` 走的是 0 分支），无任何 `导入失败:` 行。
- 中文输出**未出现乱码**（`PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` + `[Console]::OutputEncoding=UTF8` 三重设置生效），因此该计数是可信读数而非编码事故的产物。

**未做任何"凑数"调整**：文件集合完全由 brief 的 Step 1~15 逐条决定，我没有为了靠近 30 而删文件或合并模块。49 的来源见 §9.1。

<details>
<summary>49 个模块清单（原始输出）</summary>

```
aicore.api  aicore.api.deps  aicore.api.habit  aicore.api.health  aicore.api.ocr  aicore.api.tasks
aicore.core  aicore.core.budget  aicore.core.config  aicore.core.envelope  aicore.core.errors
aicore.core.idgen  aicore.core.logging  aicore.core.ratelimit  aicore.core.security
aicore.core.task_runner  aicore.core.trace
aicore.port  aicore.port.cred  aicore.port.dash  aicore.port.events
aicore.provider  aicore.provider.base  aicore.provider.cloud_ocr  aicore.provider.cloud_vision
aicore.provider.deepseek  aicore.provider.mock  aicore.provider.selector
aicore.repository  aicore.repository.base  aicore.repository.correction_repo
aicore.repository.models  aicore.repository.ocr_repo  aicore.repository.session
aicore.repository.sharding  aicore.repository.task_repo  aicore.repository.verdict_repo
aicore.service  aicore.service.accuracy  aicore.service.desensitize  aicore.service.habit
aicore.service.habit.decay  aicore.service.habit.engine  aicore.service.habit.evidence
aicore.service.ocr_match  aicore.service.ocr_service  aicore.service.task
aicore.service.task.registry  aicore.service.verdict
```
即 **8 个包 + 41 个模块 = 49**。
</details>

---

## 4. Step 17 验证：与设计文档 §3.2 表格逐行核对

**方法**：程序化解析 `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` 第 129–150 行的 §3.2 表格（从 `### 3.2 ` 到 `### 3.3 ` 之间），逐行取「层」与「文件」两列，展开 `{a,b,c}.py` 花括号写法（`habit/{engine,decay,evidence}.py`、`{deepseek,cloud_vision,cloud_ocr}.py`），再逐个 `Path.exists()`。

**原始输出：**

```
解析到 16 行表格
  [组合根      ] 应用装配与生命周期；唯一允许注入具体实现的位置   ✘ main.py
  [`core/`     ] Pydantic Settings 配置模型（含 prod 禁 Mock 校验） ✔ config.py
  [`core/`     ] 异常层次 + 错误码常量（对齐 _common/openapi.yaml） ✔ errors.py
  [`core/`     ] 统一响应信封                                   ✔ envelope.py
  [`core/`     ] traceId 上下文变量与传播                        ✔ trace.py
  [`core/`     ] 结构化 JSON 日志                               ✔ logging.py
  [`core/`     ] 内部 Token 校验                                ✔ security.py
  [`core/`     ] Redis 令牌桶                                   ✔ ratelimit.py
  [`core/`     ] 三层成本护栏                                    ✔ budget.py
  [`core/`     ] 前缀化分布式 ID                                 ✔ idgen.py
  [`core/`     ] 任务执行器内核（领取/租约/重试/线程池边界）          ✔ task_runner.py
  [`api/`      ] 仅协议适配与入参校验，不含业务判断                 ✔ ocr.py ✔ tasks.py ✔ habit.py ✔ health.py ✔ deps.py
  [`service/`  ] 业务编排，可编排多 provider / 多 repository        ✔ ocr_service.py ✔ ocr_match.py ✔ desensitize.py ✔ accuracy.py ✔ verdict.py ✔ habit/engine.py ✔ habit/decay.py ✔ habit/evidence.py ✔ task/registry.py
  [`provider/` ] 外部模型通道边界，唯一允许发起外部模型调用的层        ✔ base.py ✔ selector.py ✔ mock.py ✔ deepseek.py ✔ cloud_vision.py ✔ cloud_ocr.py
  [`repository/`] 自有库数据访问                                   ✔ models.py ✔ base.py ✔ sharding.py ✔ session.py ✔ task_repo.py ✔ ocr_repo.py ✔ correction_repo.py ✔ verdict_repo.py
  [`port/`     ] 跨服务出向端口（回写外部权威数据）                   ✔ cred.py ✔ dash.py ✔ events.py

§3.2 表格要求文件总数: 42
缺失: 1
    - 组合根 / main.py  ->  src/aicore/main.py
```

**结论：§3.2 表格 16 行 42 个文件中，41 个已齐备；唯一未建的 `main.py` 属 Task 1.4，非本任务缺项。**

依据（不是我的推断，是 Task 1.4 brief 的原文）：

- `task-1.4-brief.md` 第 4 行：`- Modify: services/aicore/src/aicore/main.py（Task 1.2 未建，本任务创建）`
- `task-1.4-brief.md` 第 112 行 Step 5：`写 main.py`，Step 9 提交命令为 `git add services/aicore/src/aicore/main.py …`

因此 Step 17 的「缺项即补齐」对本任务是**空操作**：表格中属六层的行全部齐备，`main.py` 是 Task 1.4 明确接管的文件，我**没有**越界创建它（若建了，Task 1.4 的 Files 清单会从 `Modify` 语义变成重复创建）。

### 4.1 自审发现的验证脚本缺陷（已修）

第一版解析器把「层」列为空白的续行判成了分隔行（`set("") <= {"-"}` 恒为真），导致 `core/` 10 行里只核对了 1 行（`config.py`），却仍打印出看似完整的 33 项。**这是自审时读输出发现"core 只列了 1 行、但表格明明有 10 行"才暴露的。** 修正判据为「单元格非空且全为 `-`」后重跑，行数由 7 变为 16、应查文件数由 33 变为 42。上面 §4 的输出是修正后的版本。

---

## 5. 附加验证（brief 未要求，额外证据）

统一环境保护：每次 Python 调用前设 `PYTHONPYCACHEPREFIX=<root>\.venv\pycache\pyc`（仓库树外）、`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`；pytest 加 `-p no:cacheprovider`；ruff 加 `--no-cache`；mypy 用 `--cache-dir <venv>\pycache\mypy*`；`PYTHONPATH` 全程移除。

| # | 命令 | 真实输出 | 退出码 |
|---|---|---|---|
| 1 | `python -m mypy --cache-dir <venv>\pycache\mypy5`（cwd=`services\aicore`，strict） | `Success: no issues found in 50 source files` | **0** |
| 2 | `python -m ruff check services/aicore --no-cache`（cwd=worktree 根） | `All checks passed!` | **0** |
| 3 | `python -m pytest --collect-only -q -p no:cacheprovider` | （无输出） | **5** |
| 4 | `python -m pytest --collect-only -v tests/structural` | `collected 0 items` / `no tests collected in 0.02s`，**无 error** | **5** |

### 5.1 ruff 通过是本任务的一个有价值确认

brief 的原文里含有 `——`（U+2014 破折号）、`→`（U+2192）、`≤`（U+2264）、以及 `（）：；，` 全角标点。`pyproject.toml` 的 `allowed-confusables` 只放行了 7 个字符（`、。，（）：；`），**`——` / `→` / `≤` 都不在放行集合里**。实测 `ruff check` 全绿，说明这三者不触发 RUF001/RUF002/RUF003——即 Task 1.1 第三轮定的豁免集**足以覆盖 Task 1.2 的 brief 原文**，无需再加豁免（也就不必再动 `pyproject.toml`）。

### 5.2 分层纪律：全 `src` 树**零跨层导入**

对所有 50 个新文件做导入语句扫描：

```
--- 分层纪律：本任务新增文件不得有任何 import（provider/base.py 除外）---
违规: 无
provider/base.py 的 import 行: ['from __future__ import annotations', 'from typing import Any, Protocol, runtime_checkable']

--- 六层相互导入方向（本任务应完全无跨层导入）---
src 下所有 *.py 的 import 语句统计：
  src/aicore/provider/base.py: ['from __future__', 'from typing']
```

即：**除 `provider/base.py` 的两条标准库导入外，`src/aicore` 下没有任何一条 import 语句。** 这直接证明没有任何空壳提前引入会违反 Task 1.3 import-linter 契约的依赖（`api`→`repository/provider`、`service`→具体 Provider、`repository/provider`→`service`、`core`→业务层）。这是"分层规则从第一天起可检查"这一任务目的的直接证据。

### 5.3 `provider/base.py` 运行时结构（不是"读了一遍"，是导入后检查）

```
TextProvider : runtime_checkable=True 成员=['complete']
VisionProvider: runtime_checkable=True 成员=['analyze']
OcrProvider  : runtime_checkable=True 成员=['recognize']
三家 Protocol 的 name/model_version 注解: ['str', 'str']
```

### 5.4 覆盖率门禁现状（实测，非推测）

```
TOTAL                                         18     18     0%
FAIL Required test coverage of 80.0% not reached. Total coverage: 0.00%
no tests ran in 1.30s
[exit code: 1]
```

- 门禁**当前是红的**，原因唯一：本任务按 brief 不产用例，`tests/` 里没有任何用例（`no tests ran`）。Task 1.3 / 1.4 会补上第一批用例。
- **好消息（对本门禁有利的事实）**：49 个空壳模块在覆盖率统计里是 **0 statements**（逐个显示 `0 0 100%`），全部 18 条语句都来自 `provider/base.py`。也就是说**本任务的空壳不会抬高分母、不会让后续 ≥80% 更难达标**。
- 本次用 `COVERAGE_FILE=<venv>\pycache\.coverage` 把数据文件重定向出仓库树，实测 `Test-Path <root>\.coverage` → `False`，未在仓库内留痕。

---

## 6. 提交

| 项 | 值 |
|---|---|
| 完整 SHA | `305112d66147b2d349dd2461b1ab5efedecd4b28` |
| 短 SHA | `305112d` |
| Subject | `chore: 建立 AICORE 六层目录与模块契约空壳`（与 brief Step 18 第 322 行**逐字一致**） |
| 父提交 | `b98f2510970d47f53d7650bfcf515bdb645a26c8` |
| 规模 | `50 files changed, 101 insertions(+)`，无删除、无修改既有文件 |
| 命令 | `git commit --no-verify -m "chore: 建立 AICORE 六层目录与模块契约空壳"` → `[exit code: 0]` |
| 格式 | type 英文 `chore` + subject 中文；**无 `[AI]` 前缀**；无 `Co-authored-by`（仓库既有 3 个提交均未用，属可选） |

暂存范围：`git add services/aicore/src/aicore services/aicore/tests/structural`（brief Step 18 原命令）。
`git diff --cached --name-only` 恰为 50 个 `.py`，非 `.py` 项 = 0；`--diff-filter=ACMR` 计 50，**无任何既有文件被修改**（`src/aicore/__init__.py` 未变，故未进 diff）。

提交后：

```
$ git status --porcelain
?? .sdd-scan.py
?? .sdd-tools.py
$ git diff HEAD --stat
（空）
```

即**仅** Controller 的两个既有辅助脚本为未跟踪状态（按要求未触碰、未入库），无其它残留。

### 6.1 关于 `--no-verify`

按 Controller 授权使用。依据是**环境事实**：本沙箱内 MSYS `sh.exe` 无法创建信号管道（Task 1.1 第二轮已实测 `sh.exe: *** fatal error - couldn't create signal pipe, Win32 error 5`），且 `sh` 不在 PATH，故 `.githooks/pre-commit` 与 `.githooks/commit-msg` 对**任何**执行者都无法运行——不是检查失败。本次**未**改 `core.hooksPath`、**未**改门禁脚本。

### 6.2 门禁各项人工复现（作用对象：`git diff --cached`，新增 101 行）

复现方式与 hook 一致：`git diff --cached --unified=0 --no-color` 抽取 `^\+` 行（剔除 `^\+\+\+`），套用 hook 内**同一条正则**（POSIX 字符类按语义等价译为 .NET）。

| # | pre-commit 检查项 | hook 中的判据 | 结果 |
|---|---|---|---|
| 1 | 合并冲突标记 | `^\+<<<<<<<($| )\|^\+=======$\|^\+>>>>>>>($| )` | **clean**（0 命中） |
| 2 | 行尾空白 / 末尾多余空行 | `git diff --cached --check` | **clean**（无输出） |
| 2b | 缺文件末尾换行 | diff 中 `\ No newline at end of file` | **clean**（0 命中，对应 .editorconfig `insert_final_newline`） |
| 3 | 新增大文件 >1MB | `wc -c > 1048576` | **clean**（最大文件 **1179 B** = `provider/base.py`） |
| 4 | 私钥块 / AKIA·ASIA 云密钥 | `BEGIN (RSA \|EC \|OPENSSH \|DSA \|PGP )?PRIVATE KEY\|AKIA[0-9A-Z]{16}\|ASIA[0-9A-Z]{16}` | **clean**（0 命中） |
| 5 | 疑似硬编码凭据 | `(password\|passwd\|secret\|api[_-]?key\|access[_-]?token\|private[_-]?key\|client[_-]?secret)\s*[:=]\s*[^\s#]{8,}` − 豁免词表 | **clean**（原始正则命中 **0**，豁免后 0；本任务无任何配置/凭据内容） |
| 6 | 提交真实 `.env` 文件 | `--diff-filter=A \| grep -E '(^\|/)\.env(\..*)?$'` − `.env.example` | **clean**（0 命中，新增文件集里没有任何 `.env*`） |
| — | commit-msg：Conventional Commits | `^(feat\|fix\|perf\|refactor\|docs\|test\|chore\|ci\|build\|style)(\([^)]*\))?: .+` | **PASS** |
| — | commit-msg：`[AI]` 前缀 | 人工检查 | **无** |

### 6.3 编码 / 行尾（`.editorconfig`：utf-8 + lf + insert_final_newline + trim_trailing_whitespace）

```
staged 文件数: 50
BOM 存在: 无
CRLF 存在: 无
缺末尾换行: 无
行尾空白: 无
全部 50 个文件均可按 UTF-8 严格解码: True
$ git ls-files --eol …  →  i/lf -> 51 个文件
```

`git add` 时的 `LF will be replaced by CRLF the next time Git touches it` 提示是仓库既有 `core.autocrlf=true` 的行为，**索引侧确认 `i/lf`**，与仓库其他 tracked 文件一致。全程**未使用** PowerShell `Set-Content`/`Out-File` 触碰任何含中文的文件。

---

## 7. 自审（fresh eyes，基于 `git diff --cached` 全文与 HEAD blob 复核）

- **完整性**：brief 18 个 Step 全部落地。Step 1~15 → 50 个文件（core 11 + api 6 + service 12 + provider 7 + repository 9 + port 4 = **49 个包内模块**，另加 1 个占位用例）；Step 16 / 17 有真实输出；Step 18 已提交。反向校验：brief 的 44 个代码块**零遗漏**。
- **质量**：47/50 逐字一致；3 个为 brief 未给原文的撰写项（§9.3 逐条列明理由）；`provider/base.py` 三个 Protocol 经**运行时**验证（`runtime_checkable=True`、成员齐全、`str` 注解）。ruff / mypy strict 双绿。
- **纪律**：**全 `src` 树零跨层导入**（§5.2），未提前实现 Task 1.3/1.4 的任何内容；未创建 `main.py`（Task 1.4 的产物）；未新建 `tests/structural/__init__.py`（brief 未要求）；未动 `pyproject.toml` / `.gitignore` / `.env.example` / `tests/conftest.py` / `src/aicore/__init__.py`；未运行任何 `pip`；**未派发子代理、未自拉 reviewer**；未编辑任何 brief 或计划文档。
- **测试**：本任务按 brief 不产用例（`tests/structural/test_layering.py` 是 Task 1.3 的占位）。全仓库无 `sleep`：新增文件中唯一含 `sleep` 字样的是 `tests/conftest.py`（Task 1.1 既有）里的**约定文本**，非调用，且本任务未改该文件。
- **残留物**：本轮临时脚本（`verify.py` / `encode_check.py` / `post_commit_check.py`）置于 `services\aicore\.venv\pycache\sdd12\`（gitignore 覆盖），**已全部删除**（实测 `Test-Path` → `False`）。仓库树内（除 `.venv`）非 tracked 项**为空**。
- **提交粒度**：单一主题（建立六层空壳 + 占位用例），diff 未混入格式化、依赖升级或功能改动。

---

## 8. 复现命令清单

```powershell
$wt   = "D:\progrom\.worktrees\aicore-architecture"
$root = "$wt\services\aicore"
$py   = "$root\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPYCACHEPREFIX = "$root\.venv\pycache\pyc"
$env:COVERAGE_FILE = "$root\.venv\pycache\.coverage"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Step 16（模块计数 + 逐模块导入）
Push-Location $root
& $py -c @"
import importlib, pkgutil, aicore
mods = [m.name for m in pkgutil.walk_packages(aicore.__path__, prefix='aicore.')]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        failed.append((m, repr(e)))
print(f'共 {len(mods)} 个模块')
for m, e in failed:
    print('导入失败:', m, e)
raise SystemExit(1 if failed else 0)
"@
Pop-Location

# 工具链
Set-Location $root; & $py -m mypy --cache-dir "$root\.venv\pycache\mypy5"          # Success: 50 source files
& $py -m pytest --collect-only -q -p no:cacheprovider                              # 退出码 5，无导入错误
& $py -m pytest --cov --cov-report=term -p no:cacheprovider                        # 0.00%（暂无用例）
Set-Location $wt;  & $py -m ruff check services/aicore --no-cache                  # All checks passed!

# 门禁人工复现
git diff --cached --check
git diff --cached --unified=0 --no-color | Select-String '^\+'
git grep --cached -I -n -i -E '(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|client[_-]?secret)[[:space:]]*[:=][[:space:]]*[^[:space:]#]{8,}'
```

（`verify.py`（逐字校验 + Step 16 + §3.2 逐行核对）、`encode_check.py`、`post_commit_check.py` 三个一次性脚本已删除；其完整输出已逐字抄录在本报告 §2/§4/§5/§6.3。）

---

## 9. 需计划裁定的偏差与关切

### 9.1 【最重要】模块数实测 49，brief Step 16 期望 30（容差 ±2）——差 +19

**这是 brief 的内部不一致，不是实现偏差。** 证据链：

| 口径 | 应得数量 | 与实测 49 的关系 |
|---|---|---|
| brief Step 1~15 逐条列出的文件（我照此落盘） | **49** | 完全一致 ✔ |
| 设计文档 §3.2 表格 42 项 − `main.py`（Task 1.4）= 41；+ 8 个未被表格列出的 `__init__.py`（core / api / service / service.habit / service.task / provider / repository / port） | **49** | 完全一致 ✔ |
| brief Step 16 的期望值 `共 30 个模块` | 30 | **对不上** ✘ |

即：**brief 的 Step 清单与设计文档 §3.2 表格互相印证为 49，唯独 Step 16 的期望数字 30 与两者都不符**（既不是 49、也不是 49−8 个包的 41）。我的判断是 Step 16 那句 `Expected: 共 30 个模块（数量允许 ±2）` 是早期草稿遗留的数字。

**我没有为靠近 30 做任何调整**（未删文件、未合并模块、未改 `walk_packages` 调用），因为计数是"brief 对不对"的证据，不是要凑的指标。建议 Controller 把 Step 16 的期望值更正为 49，或明确 30 的统计口径（若指"非 `__init__` 模块"应为 41，仍不是 30）。

### 9.2 `main.py`：§3.2 表格有、本任务未建（**有意为之**）

Step 17 说「缺项即补齐」，而 §3.2 表格含 `main.py`；但 Task 1.4 brief 第 4 行原文为 `Modify: services/aicore/src/aicore/main.py（Task 1.2 未建，本任务创建）`——**计划已明确规定由 Task 1.4 创建**。两条要求冲突时，我按更具体的分任务归属执行：**不建** `main.py`。若 Controller 认为 Step 17 的"补齐"应压过分工，请明确，我补一个空壳即可（一行改动）。

附带说明：`pyproject.toml` 的 `[tool.coverage.run] omit` 已含 `src/aicore/main.py`，本任务不建它不影响任何现有配置。

### 9.3 三个 docstring 由我撰写（brief 只写"各一行文档串"，未给原文）

Step 9 对 `service/habit/__init__.py`、`service/task/__init__.py`、`service/task/registry.py` 给了原文，但对 `engine.py` / `decay.py` / `evidence.py` **只写「各一行文档串」**，未给内容（计划文档第 465 行同样只有这句）。我据设计文档 §6 第 376 行的权威表述（"纯函数单测：**习惯计算引擎、衰减、证据生成**、置信度分级、类目比对"）派生，并沿用父包 `habit/__init__.py` 的"无 IO、无写库路径"约束：

| 文件 | 我写的 docstring | 派生依据 |
|---|---|---|
| `habit/engine.py` | `"""习惯计算引擎（纯函数，无 IO、无写库路径）。第 10 组实现。"""` | §6 L376「习惯计算引擎」 |
| `habit/decay.py` | `"""证据时间衰减权重（纯函数，无 IO、无写库路径）。第 10 组实现。"""` | §6 L376「衰减」 |
| `habit/evidence.py` | `"""购买影响因素证据生成（纯函数，无 IO、无写库路径）。第 10 组实现。"""` | §6 L376「证据生成」+ `api/habit.py` 的「购买影响因素」用词 |

**这是本任务唯一自行撰写的内容**，已在此显式登记而非默默发明。若计划另有规范措辞，第 10 组实现时改这三行即可（零风险）。

### 9.4 覆盖率门禁当前为红（0.00% < 80%）——属预期，非本任务缺陷

按 brief 本任务不产用例，故 `pytest --cov` 报 `no tests ran` / 0.00% / 退出码 1。**本任务的空壳对分母贡献为 0 statements**（18 条语句全部来自 `provider/base.py`），不会加重后续达标难度。第 1 组验收清单里也没有覆盖率项，故我未做任何"为过门禁而写无用测试"的动作。**提请知悉**：在第 1.3/1.4 补上用例之前，任何运行 `pytest --cov` 的会话都会看到这条红。

### 9.5 次要观察（不阻断，供 Task 1.3 参考）

1. **`tests/structural/` 无 `__init__.py`，而 `tests/` 有**。现状可用（实测 `pytest --collect-only -v tests/structural` → `collected 0 items`，无 error）。潜在风险：若将来在别处出现同名 `test_layering.py`，pytest 的 `prepend` 导入模式可能撞名。brief 与 Task 1.3 的 Files 清单都未列该文件，我按"不创建 brief 之外的文件"处理，留待 Task 1.3 决定。
2. **仓库树内已存在 `.mypy_cache`（mtime 2026-09-17 17:21:44），非本轮产物**：我本轮所有 mypy 调用均显式 `--cache-dir <venv>\pycache\mypy4|mypy5`（mtime 17:27:29 起），时间戳早于我的首次运行，应是 Task 1.1 与本任务之间由其它会话产生。它被 `services/aicore/.gitignore:7` 覆盖，不影响提交，我**未删除**（不处置非本任务产物）。
3. `services\aicore\src\aicore\__pycache__`（16:54:44）与 `tests\__pycache__`（16:55:11）时间戳**未变**，证明 `PYTHONPYCACHEPREFIX` 生效，本轮未在仓库树内新增任何字节码缓存。
4. `.sdd-scan.py` / `.sdd-tools.py` 未触碰、未入库（沿用 Task 1.1 的处置）。

---

## 10. 第 1 组验收清单中与本任务相关的项（自查）

| 验收项 | 本任务状态 |
|---|---|
| `import aicore` 无错 | ✔ 49 个模块全部导入成功（§3） |
| `pytest --collect-only` 可收集全部测试、无导入错误 | ✔ 退出码 5、无 error（§5.3；无用例符合本任务定位） |
| `lint-imports` 全绿 + 阴性用例 | ⏳ Task 1.3（本任务只保证包结构与零违规导入，§5.2） |
| 规则 5、6 AST 扫描阴性验证 | ⏳ Task 1.3（本任务已建 `desensitize.py` / `verdict.py` 两个受检文件） |
| `uvicorn aicore.main:app` 启动 + `/health` 200 | ⏳ Task 1.4（`main.py` / `api/health.py` 归其所有） |
| 全量 `pytest` 通过 | ⏳ 暂无用例 |

---

## 修复轮 1（评审发现）

**评审结论**：Approved —— 0 Critical / 2 Important；另加 1 项 Controller 指派的一致性修复（非评审发现）。
**基线**：`305112d` → **本修复提交**：`b5c5c7d`（父提交 `305112d66147b2d349dd2461b1ab5efedecd4b28`）
**改动规模**：5 个文件，`11 insertions(+), 4 deletions(-)`；1 新增（0 字节空文件）+ 4 修改。
**纪律**：**未新增任何代码**（只改模块文档串 + 建空 `__init__.py`）；未派发子代理；未自拉 reviewer；未触碰 brief / 计划文档 / `pyproject.toml` / 既有测试。

| # | 发现 | 严重度 | 处置 | 涉及文件 |
|---|---|---|---|---|
| 1 | `service/verdict.py` 缺红线豁免约定 | Important | 已修 | `src/aicore/service/verdict.py` |
| 2 | 三个文档串指向不存在的 `setup.cfg` | Important | 已修 | `src/aicore/__init__.py`、`src/aicore/core/__init__.py`、`src/aicore/provider/base.py` |
| 3 | `tests/structural/` 缺包标记 | Controller 指派 | 已修 | `tests/structural/__init__.py`（新增） |

**Parked 项（本轮按指令未动）**：`deps.py` / `__init__.py` 前向撞名风险、`Protocol` 数据成员 `issubclass` 局限、`task/registry.py` 的「（OCR 已实现，其余预留）」时态措辞——全部保留原样，留待整分支终审。brief Step 16 的「共 30 个模块」按裁定为陈旧值，未改 brief、未改代码。

---

### 修复 1（Important）：`service/verdict.py` 补齐红线豁免约定

**问题**：原文件仅 1 行，只陈述了 D5 的**实质**（无人工复核结论则不存在回写入口），**未陈述 `# noqa: ai-allow-swallow` 豁免约定**。绑定全局约束要求两个红线文件（`service/desensitize.py`、`service/verdict.py`）**同时**陈述「约束本身」与「豁免约定」；`desensitize.py:1-8` 已完整具备，`verdict.py` 缺失 → 以 `desensitize.py` 为模板扩写为两段式。

**改动**：模块文档串由 1 行扩为 8 行，结构对齐 `desensitize.py`：`标题行` → `红线实质 + AST 扫描强制` → `豁免约定` → `收尾归属`。**仍为纯模块文档串，无任何代码行。**

修复后全文（`git show HEAD:services/aicore/src/aicore/service/verdict.py`）：

```python
"""C8 权威回写前置条件。

【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过
人工结论的回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。

第 8 组实现具体校验；本任务仅建文件以保证结构检查从第一天起生效。
"""
```

**措辞依据（非自行发挥）**：

| 新增文本要素 | 依据 |
|---|---|
| D5 编号 | `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md:169`「D5 无人工结论不回写」；计划文档 `:29`「无人工复核结论不得回写权威数据（D5）」 |
| C8 编号与首行「权威回写前置条件」 | brief Step 7 原文（`task-1.2-brief.md:118`）+ 设计文档 `:169`（D5 与 C8 同段并列） |
| `tests/structural/test_source_guards.py` 的 AST 扫描 | 计划文档 `:841` `GUARDED_FILES = ("service/desensitize.py", "service/verdict.py")` |
| 豁免注释写法 | 计划文档 `:821`/`:842`：`SWALLOW_EXEMPT = re.compile(r"#\s*noqa:\s*ai-allow-swallow")`，错误信息见 `:885` |
| 「MUST NOT 出现绕过人工结论的回写分支」 | Controller 修复指令原文 |
| 两段式版式 | `src/aicore/service/desensitize.py:1-8`（约束文件模板） |

> **口径变化登记**：本轮后 `verdict.py` **不再与 brief Step 7 原文逐字一致**，此即 Important 1 要求的改动。原报告 §2 的「47/50 逐字一致」应修正为：**46/50 逐字一致 + 1 个经评审授权的扩写（`verdict.py`）+ 3 个 §9.3 撰写项**。

---

### 修复 2（Important）：三个文档串的 `setup.cfg` → `.importlinter`

**问题**：`src/aicore/__init__.py:5`、`src/aicore/provider/base.py:4`、`src/aicore/core/__init__.py:1` 三处指向 `setup.cfg`，而仓库内**不存在** `setup.cfg`，且 `design.md` 载明工具链配置在 `pyproject.toml`。

**改动**（逐处，措辞按 Controller 指令逐字，并与计划文档 `:269` / `:483` / `:344` 已更新的文本核对一致——计划文档中的反引号为 Markdown 代码跨度格式，Python 文档串中不带反引号）：

| 文件:行 | 改前 | 改后 |
|---|---|---|
| `src/aicore/__init__.py:5` | `分层依赖规则见 setup.cfg 的 import-linter 契约与 tests/structural/。` | `分层依赖规则见 .importlinter 的 import-linter 契约与 tests/structural/。` |
| `src/aicore/provider/base.py:4` | `（mock / deepseek / cloud_vision / cloud_ocr）——由 setup.cfg 的 import-linter 契约强制。` | `（mock / deepseek / cloud_vision / cloud_ocr）——由 .importlinter 的 import-linter 契约强制。` |
| `src/aicore/core/__init__.py:1` | `"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 setup.cfg 契约）。"""` | `"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 .importlinter 契约）。"""` |

三处均为**文档串内单点替换**，各 `1 insertion(+), 1 deletion(-)`，无其它字符变动（见下方 diff 摘录与 §「自审」）。

---

### 修复 3（Controller 指派，非评审发现）：`tests/structural/__init__.py`

**问题**：`tests/` 有 `__init__.py`（0 字节包标记），`tests/structural/` 没有 → pytest 默认 `prepend` 导入模式下以**基名**为键，Task 1.4 加入 `tests/api/test_health.py` 等同类包后存在真实撞名风险。

**改动**：新建 `services/aicore/tests/structural/__init__.py`，**0 字节**。

**实证（不是"应该没问题"，是导入名变了）**：

```
tests                                      OK  file=tests/__init__.py
tests.structural                           OK  file=structural/__init__.py
tests.structural.test_layering             OK  file=structural/test_layering.py
[import-name exit code: 0]
```

即占位用例现在以**包限定名** `tests.structural.test_layering` 被导入（修复前该目录无 `__init__.py`，按 `prepend` 模式会以裸基名 `test_layering` 导入），撞名前提被消除。

**撞名风险的对照实验（不是断言，是实测；探针置于 `.venv\pycache\sdd12fix-probe\`——仓库树外，实验后已清理 `Test-Path → False`）**

用 pytest 编程式调用（`pytest.main(..., plugins=[…])`，`pytest_collection_finish` 中读取 `item.module.__name__`）对两种布局各跑一次，两种布局都放**两个同名 `test_x.py`**：

| 布局 | 包标记 | 实测导入名 | pytest 退出码 | 结果 |
|---|---|---|---|---|
| A（修复后形态） | 两目录均有 `__init__.py` | `['other.test_x', 'pkgid.test_x']` | **0** | 两个用例均正常收集 |
| B（修复前形态） | 两目录均无 `__init__.py` | `['test_x']` | **2** | `import file mismatch`，收集中断 |

布局 B 的原始报错（节选）：

```
_______ ERROR collecting .venv/pycache/sdd12fix-probe/B/sub2/test_x.py ________
import file mismatch:
imported module 'test_x' has this __file__ attribute:
  …\sdd12fix-probe\B\sub\test_x.py
which is not the same as the test file we want to collect:
  …\sdd12fix-probe\B\sub2\test_x.py
HINT: remove __pycache__ / .pyc files and/or use a unique basename for your test file modules
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

**结论**：Controller 指出的撞名风险**可复现**（布局 B → 退出码 2、收集中断），而包标记正是消除它的机制（布局 A → 退出码 0、导入名唯一化）。`tests/structural/__init__.py` 的加入使 `services/aicore/tests/` 下所有测试包标记一致。

**空文件身份校验**（与 `tests/__init__.py` 同一 blob）：

```
$ git rev-parse HEAD:services/aicore/tests/structural/__init__.py
e69de29bb2d1d6434b8b29ae775ad8c2e48c5391
$ git rev-parse HEAD:services/aicore/tests/__init__.py
e69de29bb2d1d6434b8b29ae775ad8c2e48c5391
```

`e69de29…` 即 Git 的空 blob，两个文件字节级等同。收集行为未受影响（见 V4）。

---

### 验证证据（全部在**提交后**、HEAD=`b5c5c7d`、工作区无 `services/aicore` 改动时复跑）

统一环境：`$env:PYTHONUTF8='1'`、`PYTHONIOENCODING=utf-8`、`PYTHONPYCACHEPREFIX=<root>\.venv\pycache\pyc`、移除 `PYTHONPATH`、`[Console]::OutputEncoding=UTF8`；ruff `--no-cache`；mypy `--cache-dir` 指向 venv；pytest `-p no:cacheprovider`。

**V1 模块导入遍历（brief Step 16 原命令）**

```
共 49 个模块
[exit code: 0]
```

49 与修复前一致（本轮未增删 `src` 下任何模块）；`导入失败:` 行 **0 条**，退出码 0。Controller 裁定 49 为正确值，本报告确认修复轮后仍是 49。

**V2 mypy（strict，cwd=`services\aicore`）**

```
Success: no issues found in 50 source files
[exit code: 0]
```

**V3 ruff**

```
$ python -m ruff check services/aicore --no-cache
All checks passed!
[exit code: 0]
```

补充：本轮新增字符含 `——`（U+2014）、`【】`（U+3010/3011）、全角 `，、：` 与 `<理由>`，`allowed-confusables` 未新增豁免即全绿 —— 与 §5.1 的结论一致。

**V4 pytest 收集（验证新包标记不破坏收集）**

```
$ python -m pytest --collect-only -q -p no:cacheprovider
（无输出）
[exit code: 5  （5 = 无用例收集，符合 Task 1.2 定位；无 error / 无 import mismatch）]
```

**V5 `setup.cfg` 引用 grep（必查项）**

| 范围 | 命中 | 说明 |
|---|---|---|
| `services\aicore\` 全树（含 `.venv`，**8616 个文件**） | **0** | ripgrep（`grep` 工具）与 PowerShell `Select-String` 双路复核均为 0 |
| `services\aicore\` 排除 `.venv` / `.mypy_cache`（121 个文件） | **0** | 同上 |
| **全 worktree tracked 文件** | **2**（均在 `AI_DEV_LOG/2026-09-16.md:242`、`:243`） | **不在 `services\aicore\` 内**，且属历史开发日志（记录 Task 1.1 当时对 `setup.cfg`／契约写法的实验过程），非生效契约陈述 |

命令与原始输出：

```powershell
$ hits = Get-ChildItem -Path $root -Recurse -File | Select-String -Pattern 'setup\.cfg' -SimpleMatch
命中: 0
扫描文件总数: 8616
```

```
$ git grep -n -I -e "setup\.cfg" -- .      # worktree 根，全部 tracked 文件
AI_DEV_LOG/2026-09-16.md  (行 242)
AI_DEV_LOG/2026-09-16.md  (行 243)
```

> **如实披露**：`AI_DEV_LOG/2026-09-16.md` 的两处提及**未删除**。理由：① Controller 的必查范围明确限定为 `services/aicore/`；② 该文件是开发日志（历史记录），记录的是 Task 1.1 当时的实验事实，事后改写历史日志不属本修复轮授权范围（本轮授权范围 = 评审 2 项 Important + 1 项 Controller 指派 + 本报告，且 `setup.cfg` 必查范围明确限定为 `services/aicore/`）。若 Controller 希望日志同步为 `.importlinter` 口径，请明示，我按日志 skill 的规范追加（而非回改）一段说明即可。

**V6 编码 / 行尾**（`.editorconfig`：utf-8 + lf + insert_final_newline + trim_trailing_whitespace）

```
src/aicore/__init__.py               bytes= 359 BOM=False CRLF=False 末尾换行=True 行尾空白行号=[] UTF8严格解码=True
src/aicore/core/__init__.py          bytes= 112 BOM=False CRLF=False 末尾换行=True 行尾空白行号=[] UTF8严格解码=True
src/aicore/provider/base.py          bytes=1183 BOM=False CRLF=False 末尾换行=True 行尾空白行号=[] UTF8严格解码=True
src/aicore/service/verdict.py        bytes= 453 BOM=False CRLF=False 末尾换行=True 行尾空白行号=[] UTF8严格解码=True
tests/structural/__init__.py         bytes=   0 BOM=False CRLF=False 末尾换行=True 行尾空白行号=[] UTF8严格解码=True
[encoding-check exit code: 0]
```

**V7 索引侧 EOL 与 blob**

```
$ git ls-files --eol <5 个文件>
i/lf    w/lf    attr/    services/aicore/src/aicore/__init__.py
i/lf    w/lf    attr/    services/aicore/src/aicore/core/__init__.py
i/lf    w/lf    attr/    services/aicore/src/aicore/provider/base.py
i/lf    w/lf    attr/    services/aicore/src/aicore/service/verdict.py
i/none  w/none  attr/    services/aicore/tests/structural/__init__.py
```

`git add` 时的 `LF will be replaced by CRLF…` 是仓库既有 `core.autocrlf=true` 的行为，**索引侧确认为 `i/lf`**（空文件为 `i/none`），与既有 tracked 文件一致。全程**未使用** `Set-Content` / `Out-File`，全部经 `edit` / `write` 工具写入。

---

### 提交

| 项 | 值 |
|---|---|
| 完整 SHA | `b5c5c7dcf6aa457126bdc320f565c43392f6098e` |
| 短 SHA | `b5c5c7d` |
| Subject | `fix(aicore): 补齐红线豁免约定并修正契约与测试包指向` |
| 父提交 | `305112d66147b2d349dd2461b1ab5efedecd4b28` |
| 规模 | `5 files changed, 11 insertions(+), 4 deletions(-)`；`create mode 100644 services/aicore/tests/structural/__init__.py` |
| 命令 | `git commit --no-verify -m "fix(aicore): 补齐红线豁免约定并修正契约与测试包指向"` → `[exit code: 0]` |
| 格式 | type 英文 `fix` + scope `(aicore)` + subject 中文；**无 `[AI]` 前缀** |
| 暂存范围 | 逐文件 `git add`（未用目录通配，避免误纳 Controller 的计划文档改动） |

`git diff --cached --name-only`（提交前）恰为 5 个路径；`--diff-filter` 统计 **A=1 / M=4**，无删除、无重命名。

**提交后仓库状态**：

```
$ git status --short
 M docs/superpowers/plans/2026-09-16-aicore-architecture.md
?? .sdd-il-probe.py
?? .sdd-scan.py
?? .sdd-tools.py
```

`services/aicore` 下**无任何**未提交改动（`git diff HEAD --stat` 仅剩上表第一行的计划文档）。三项说明：

1. `docs/superpowers/plans/…md` 的 `M` 是 **Controller 本人的计划文档更新**（实测 `1 file changed, 12 insertions(+), 12 deletions(-)`；对 diff 逐行统计：新增行含 `.importlinter` 者 12 条、删除行含 `setup.cfg` 者 12 条，即这 12 对增删**全部**落在 `setup.cfg` → `.importlinter` 这一处替换上），**在我开始工作前就已存在**（开工首条 `git status` 即已确认），我**未触碰、未提交**——它是 Controller 的改动，不应混入本修复提交的粒度。
2. `?? .sdd-il-probe.py` / `?? .sdd-scan.py` / `?? .sdd-tools.py` 三个 Controller 辅助脚本**未触碰、未入库**（按指令保留）。
3. 无本轮临时脚本残留：本轮未创建任何临时脚本文件（校验均以 `python -c` 内联执行），`__pycache__` 全部由 `PYTHONPYCACHEPREFIX` 重定向至 `.venv` 内。

---

### 门禁人工复现（作用对象：本提交的 `git diff --cached`，新增 11 行）

`sh` 不在 PATH 且 MSYS 管道在本沙箱不可用，故 `.githooks/*` 对任何执行者都无法运行；按 Controller 授权使用 `--no-verify`，并**逐条复现** hook 判据（复现方式与 hook 一致：`git diff --cached --unified=0 --no-color` 抽 `^\+` 行并剔除 `^\+\+\+`，POSIX 字符类按语义等价译为 .NET；`.githooks/pre-commit` 与 `.githooks/commit-msg` 本次已逐行读取核对）。

| # | 检查项 | hook 判据 | 结果 |
|---|---|---|---|
| 1 | 合并冲突标记 | `^\+<<<<<<<($\| )\|^\+=======$\|^\+>>>>>>>($\| )` | **clean**（0 命中） |
| 2 | 行尾空白 / 末尾多余空行 | `git diff --cached --check` | **clean**（无输出） |
| 2b | 缺文件末尾换行 | diff 中 `\ No newline at end of file` | **clean**（0 命中；空文件不产生该标记） |
| 3 | 变更文件 >1MB | `wc -c > 1048576` | **clean**（最大文件 **1183 B** = `provider/base.py`） |
| 4 | 私钥块 / AKIA·ASIA 云密钥 | `BEGIN (RSA \|EC \|OPENSSH \|DSA \|PGP )?PRIVATE KEY\|AKIA[0-9A-Z]{16}\|ASIA[0-9A-Z]{16}` | **clean**（0 命中） |
| 5 | 疑似硬编码凭据 | `(password\|passwd\|secret\|api[_-]?key\|access[_-]?token\|private[_-]?key\|client[_-]?secret)\s*[:=]\s*[^\s#]{8,}` − 豁免词表 | **clean**（原始正则命中 **0**，豁免后 0） |
| 6 | 提交真实 `.env` | `--diff-filter=A \| (^\|/)\.env(\..*)?$` − `.env.example` | **clean**（0 命中；唯一新增文件为 `tests/structural/__init__.py`） |
| — | commit-msg：Conventional Commits | `^(feat\|fix\|perf\|refactor\|docs\|test\|chore\|ci\|build\|style)(\([^)]*\))?: .+` | **PASS**（实测 `True`） |
| — | commit-msg：`[AI]` 前缀 | 人工检查 | **无**（实测 `False`） |

---

### 自审（fresh eyes，基于 `git show HEAD` 全文复核）

- **完整性**：3 项（2 Important + 1 指派）**全部落地**，无一遗漏；未越界处理任何 Parked 项。
- **无代码新增**：4 个修改文件中，3 个是文档串内单点替换，1 个（`verdict.py`）是文档串扩写；新增文件为空。实测复核 `src/aicore` 下**全部** import 语句：

  ```
  src\aicore\provider\base.py: from __future__ import annotations
  src\aicore\provider\base.py: from typing import Any, Protocol, runtime_checkable
  ```

  即 import 语句仍只有 `provider/base.py` 的 2 条标准库导入（未被本轮改动），§5.2 的「零跨层导入」结论在修复后依然成立。
- **措辞准确性**：三处 `.importlinter` 文本与 Controller 指令及计划文档 `:269`/`:483`/`:344` 的已更新文本逐字一致；`verdict.py` 的每个新增要素都有上表所列的上游依据，无自行发明。
- **红线约定自洽**：`verdict.py` 现在描述的两条规则（受 `test_source_guards.py` AST 扫描、`# noqa: ai-allow-swallow: <理由>` 豁免）与计划文档 `:841`~`:842` 将要落地的实现**完全对应**，不会出现"文档承诺 / 检查不实现"的错位；两个红线文件的表述现在同构（`D4 / R-03` ↔ `D5 / C8`）。
- **测试纪律**：本仓库测试内 MUST NOT 出现任意 `sleep`——本轮**未新增任何测试**。实测 `src` + `tests` 全树扫描 `sleep` 仅 1 条命中，且是 `tests/conftest.py:3` 的**约定文本**（`约定：测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟。`），非调用。
- **失败面**：新包标记是本轮唯一可能影响运行时的改动（pytest 导入语义）。已用 V4（收集无 error）+ 包限定导入名实证双向确认，无回归。
- **残留物**：仓库树内（除 `.venv` 等 gitignore 项）非 tracked 项仅剩三个 Controller 辅助脚本；无临时脚本、无新字节码目录。

### 修复轮遗留 / 提请 Controller 知悉

1. **`AI_DEV_LOG/2026-09-16.md:242-243` 仍提 `setup.cfg`**（历史日志，见 V5 披露）——不在必查范围，未改，待指示。
2. **`tests/structural/__init__.py` 属 brief 与 Task 1.3 Files 清单之外的文件**（原报告 §9.5-1 登记过该缺口）。本轮按 Controller 指派创建，Task 1.3 的 Files 清单（`Create: test_source_guards.py` / `Modify: test_layering.py`）**无需**再列它，但若计划文档要精确反映产物，可在 Task 1.3 的 Files 中补一行 `Create: tests/structural/__init__.py（修复轮 1 已建）`——是否更新由 Controller 决定。
3. **覆盖率门禁仍为红**（0.00% < 80%，`no tests ran`）：与本轮修复无关，原因与 §9.4 相同，Task 1.3/1.4 补用例后转绿。
