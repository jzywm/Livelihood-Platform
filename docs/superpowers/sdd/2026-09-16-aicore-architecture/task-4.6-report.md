# Task 4.6 实现报告：任务类型策略注册表

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
**Python**：`.venv\Scripts\python.exe`（3.14.6）；**未执行任何 `pip install`**
**判据口径**：五条验收命令均判「**EXIT=0 且 failed == 0**」（不写固定计数）。
**纪律**：未 `git commit` / `git add`；未改工单 §Files 的「不可改」清单；未对 `src/` 做任何变异注入。

---

## 1. 交付物

| 文件 | 动作 | 行数 | 内容 |
|---|---|---|---|
| `services/aicore/src/aicore/service/task/registry.py` | 改（1 行 docstring 空壳 → 实现） | **245** | `TaskPolicy` / `REGISTRY` / `get_policy` / `registered_types` / `assert_submittable` |
| `services/aicore/tests/unit/test_task_registry.py` | 新建 | **775** | 29 个用例节点（28 passed + 1 skipped，见 §6） |

两个文件均为 **UTF-8 无 BOM / LF**（实测：`crlf=0`、`bom=False`），全部经 write/edit 工具写入，
**未用** `Set-Content` / `Out-File` / `>`。

**git 足迹**（只跑的只读命令 `git status --porcelain`，**未** add/commit）：

```
 M services/aicore/src/aicore/service/task/registry.py
?? services/aicore/tests/unit/test_task_registry.py
```

`services/aicore` 下其余 `M`/`??` 全部属 **Task 4.5**（`api/{deps,ocr,tasks}.py`、`main.py`、
`tests/conftest.py`、`tests/api/test_deps.py`、`service/task/{submit,state,query}.py`）或既有未跟踪目录
`tests/support/`。**我没有创建、修改或导入 `service/task/submit.py`、`state.py`、`query.py`**
（grep 证实：`submit.py` 里 `Task 4.7 的注册表` 只是注释，无任何 import 我的模块的行）。

---

## 2. 权威依据逐条核对（全部用 read 工具**完整读**，非 grep）

| 依据（工单 §0） | 读到的原文要点 | 落实位置 |
|---|---|---|
| `design.md` L185-194 | L185「…在 `service/task/registry.py` 注册，处理器需声明自身的结果结构、超时与是否可重试」；L189-192 四行表；L194「新增一个处理器文件 + 一行注册」/「`task_runner` 在 M1 之后保持稳定」/「未注册的类型必须显式失败（而非静默忽略），避免告警丢失」 | 模块 docstring 逐字引用；`REGISTRY` 四条登记；`get_policy` 抛 `1003` |
| `er.md` §6.1 L291 | `\| type \| enum('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT') \|` | `REGISTRY` 键集合；用例**现读**该行比对 |
| `openapi.yaml` L764-768 | `TaskType.enum: [OCR, VISION_REVIEW, KITCHEN_ANOMALY, RISK_PREDICT]` | 与 er.md 同集合 |
| `openapi.yaml` L787-825（`TaskResult.result` 的 `oneOf`） | `oneOf` 恰为四个结果结构 | 用例 `test_task_result_one_of_covers_declared_result_schemas` **双向互等**比对 |
| `openapi.yaml` L863-884 / L1144-1165 / L1179-1208 | `VisionReviewResult` / `KitchenAnomalyResult` / `RiskPredictResult` 真实存在 | `result_schema` 逐字取值；用例从 `components.schemas` 现读比对 |
| `openapi.yaml` L749 `OcrResult` | 同上 | 同上 |
| `service/ocr_service.py` | **1 行空壳**（`"""OCR 任务编排。第 4 组实现。"""`） | **未实现、未导入**；只登记 `handler_ref="service.ocr_service"` 并断言该文件**存在** |
| `core/config.py` L360-368 | `ai_call_timeout_s: float = Field(default=5.0, gt=0)`；L356-359 明说这几项「要从配置侧能调」 | 超时口径经 `get_policy` **现读**（不冻结） |

---

## 3. 交付接口（签名逐字对齐工单 §1）

```python
@dataclass(frozen=True, slots=True)
class TaskPolicy:
    task_type: str
    result_schema: str   # 逐字取自 openapi.yaml 的 components.schemas
    timeout_s: float
    retryable: bool
    handler_ref: str     # 只登记「在哪」，不导入
    implemented: bool

REGISTRY: Final[Mapping[str, TaskPolicy]]      # 模块级常量（MappingProxyType）
def get_policy(task_type: str, *, settings: Settings | None = None) -> TaskPolicy
def registered_types() -> frozenset[str]
def assert_submittable(task_type: str, *, settings: Settings | None = None) -> TaskPolicy
```

四条登记（逐条对齐 design.md L189-192，MUST NOT 增删）：

| `task_type` | `result_schema` | `timeout_s` | `retryable` | `handler_ref` | `implemented` |
|---|---|---|---|---|---|
| `OCR` | `OcrResult` | `Settings.ai_call_timeout_s`（现读） | `True` | `service.ocr_service` | `True` |
| `VISION_REVIEW` | `VisionReviewResult` | 同上 | `True` | `<reserved>` | `False` |
| `KITCHEN_ANOMALY` | `KitchenAnomalyResult` | 同上 | `True` | `<reserved>` | `False` |
| `RISK_PREDICT` | `RiskPredictResult` | 同上 | `False` | `<reserved>` | `False` |

未注册类型 → `ParamError(code=1003)`，消息含出错类型；`implemented=False` 在提交准入 → 同为 `1003`
但**消息不同**（不含「未注册」字样，见 §4 第 8 条）。

---

## 4. 用例清单（工单 §4 的 13 条 → 落点）

| § | 要求 | 用例 | 状态 |
|---|---|---|---|
| 1 | 四条登记逐条断言 | `test_four_registrations_match_design_table` + `test_handler_ref_registers_a_location_without_fabricating_one` | PASSED |
| 2 | 键集合 vs `er.md` L291 enum **现读** | `test_registry_keys_equal_er_md_type_enum`（解析器自证：`test_er_md_enum_parser_is_discriminating`） | PASSED |
| 3 | `result_schema` 在 `components.schemas` 里存在（**现读**） | `test_result_schemas_exist_in_openapi_components`（自证：`test_openapi_schema_parser_is_discriminating`） | PASSED |
| 4 | 四个已注册类型各返回对应策略 | `test_get_policy_returns_the_registered_policy`（4 参数化） | PASSED |
| 5 | `get_policy("NOPE")` → `1003` 且消息含 `NOPE` | `test_get_policy_unknown_type_raises_1003_naming_the_type`（`NOPE` / `ocr` / `vision_review`） | PASSED |
| 6 | MUST NOT 返回 `None` / 回落默认策略 | `test_get_policy_fails_loudly_instead_of_returning_a_sentinel`（`pytest.raises` 内嵌 `pytest.fail`） | PASSED |
| 7 | `assert_submittable("OCR")` 通过 | `test_assert_submittable_accepts_ocr` | PASSED |
| 8 | 三个未实现类型各抛 `1003`，消息可分辨 | `test_assert_submittable_rejects_unimplemented_types_with_a_distinct_message` | PASSED |
| 9 | `assert_submittable("NOPE")` 抛 `1003` | `test_assert_submittable_unknown_type_raises_1003` | PASSED |
| 10 | `registered_types()` == `REGISTRY` 键集合 | `test_registered_types_equals_registry_keys` | PASSED |
| 11 | `timeout_s` 现读、非冻结常量 | `test_timeout_s_is_read_live_from_settings_not_a_frozen_constant` | PASSED |
| 12 | `TaskPolicy` frozen（`FrozenInstanceError`） | `test_task_policy_is_frozen_and_slotted` + `test_registry_is_a_read_only_mapping` | PASSED |
| 13 | §3 结构性断言 + 判别力自证 | `test_adding_a_type_does_not_require_touching_the_runner`（**判据 1 已执行；判据 2 SKIPPED**）+ `test_runner_literal_scan_is_discriminating` | 见 §5 |

**13 条之外增补的 5 条**（均为补强，不替代任何一条）：`test_authoring_documents_exist`（权威文档存在性下限）、
`test_task_result_one_of_covers_declared_result_schemas`（与 `TaskResult.result.oneOf` 双向互等）、
`test_registry_does_not_import_handler_modules`（AST 扫 import）、
`test_calling_the_registry_does_not_import_handlers_at_runtime`（`sys.modules` 增量）、
`test_openapi_schema_parser_is_discriminating`（解析器自证）。

---

## 5. §3 结构性断言：判据、非空下限与**判别力自证**

### 判据 A —— `registry.py` 内 MUST NOT 有逐类型分支

`find_per_type_branches(source, subject="task_type")` 用 AST 命中两类形态：
`if`/`elif` 条件里 `task_type` 与**字符串字面量**比较（`==`/`!=`/`in`/`not in`）、`match task_type`。
**判据刻意要求"与字面量比较"**：`if task_type not in REGISTRY` 也提到 `task_type`，但它是表查找前的成员
检查（正是本任务要的写法）。若判据只看"条件里出现过 subject"，它会把正确实现判红——那种判据在正确代码上
恒不可满足，等价于没有判据。故同时用**正面样本**（表查找）反证"不误伤"。

**非空下限**（防"扫了个空文件"）：断言 `REGISTRY` 是 `registry.py` 的**模块级**赋值（AST 扫模块体），
且 `get_policy` 函数体内确实存在 `REGISTRY[...]` 下标访问。

### 判据 B —— `core/task_runner.py` 内 MUST NOT 出现任何任务类型字面量

`find_task_type_literals(source, registered_types())` 扫**全部**字符串常量（含 docstring，取严口径，
与工单 §3 原文一致）。**该文件此刻是 1 行 docstring 空壳**（AST 里除 docstring 外零节点）→
按工单 §3「MUST NOT 假装验过」**显式 `pytest.skip` 并说明**：

```
SKIPPED [1] tests\unit\test_task_registry.py:708: task_runner.py 仍是 docstring 空壳（AST 里除模块
docstring 外没有任何节点）：扫它等于扫一个空集，此刻下断言只是假绿；Task 4.7 交付执行器后本断言自动生效
```

跳过条件是「**文件无代码**」而不是「本用例不想跑」：Task 4.7 一交付 `task_runner`，同一条用例自动变成
真断言（判据 B 的取值集合来自 `registered_types()`，不是抄的常量）。判据 A 的断言**位于该 skip 之前**
且失败即红，故 skip 不掩盖判据 A 的结果。

### 判别力自证（**四层**，全部不落盘）

本组出现过三次「判据看着在验、实际验的是空集」的假绿，故这一条做了四层自证：

1. **合成 elif 链判红**：判据 A 精确报出 `[(3,'if/elif'), (5,…), (7,…), (9,…)]` —— 精确到行号，
   只断言"非空"会漏掉"只抓到第一个分支"的半失效判据；
2. **合成 `match` 判红**：`match task_type` 形态同样命中；
3. **正面样本不误伤**：表查找写法（成员检查 + 下标）判据返回 `[]` —— 否则判据在正确实现上恒红；
4. **对真实文件做内存变异判红（最强一档）**：取 `registry.py` 的**真实源码**，在内存里把
   `    if task_type not in REGISTRY:` 替换为「先插一个 `if task_type == "OCR": return REGISTRY["OCR"]`」，
   断言 (a) 替换**确实发生**（`mutated != source`，防锚点失配导致自证退化成空操作）、
   (b) 判据对变异后的源码**报红**。**变异只在内存里做字符串替换，完全不碰磁盘**——本组两次因
   「改 `src/` + finally 还原」被超时打断而把注入残留在交付文件里，故此处 MUST NOT 落盘。

判据 B 的判据本体另有 `test_runner_literal_scan_is_discriminating`（**不跳过**，扫合成样本）：
分支式 runner（`task.type == "OCR"`）判红且精确报出 `["OCR","VISION_REVIEW"]`，表查找式 runner 判绿。
于是即便判据 B 报 SKIPPED，它的判别力也已被证明过，而不是"因为没对象所以没验"。

---

## 6. 五条验收命令的**原始输出**

命令前缀（每条都先执行）：`cd D:\progrom\.worktrees\aicore-architecture\services\aicore`；`$env:PYTHONUTF8='1'`

### ① 定向用例

```
PS> .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_task_registry.py -q
.........................s...                                            [100%]
28 passed, 1 skipped in 0.31s
EXIT=0
```

同一条命令加 `-rs`（仅为了打印 skip 原因）：

```
.........................s...                                            [100%]
=========================== short test summary info ===========================
SKIPPED [1] tests\unit\test_task_registry.py:708: task_runner.py 仍是 docstring 空壳（AST 里除模块 docstring 外没有任何节点）：扫它等于扫一个空集，此刻下断言只是假绿；Task 4.7 交付执行器后本断言自动生效
28 passed, 1 skipped in 0.32s
EXIT=0
```

**判据：EXIT=0 且 failed == 0 ✓**（1 skipped = 工单 §3 明确要求的"空壳即跳过并说明"）

### ② 全量（默认段）

```
PS> .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
tests\unit\test_task_registry.py .........................s...           [ 97%]
tests\unit\test_trace.py ...........................                     [100%]

============== 1142 passed, 14 skipped, 19 deselected in 43.73s ===============
EXIT=0
```

**判据：EXIT=0 且 failed == 0 ✓**（计数只作附注：`failed` 为 0；14 skipped 全属既有文件的既有跳过）

### ③ ruff

```
PS> .\.venv\Scripts\ruff.exe check --no-cache src tests
All checks passed!
EXIT_RUFF=0
```

**判据：EXIT=0 ✓**。补充取证（控制者提示后加固）：`E501` 按**显示宽度**计（CJK 算 2 格），
我用下式逐行自测，折行后**已无超宽行**（输出为空）：

```
PS> .\.venv\Scripts\python.exe -c "import pathlib; [print(p, (i, len(l), sum(1 for c in l if ord(c) > 0x2E80))) for p in ('tests/unit/test_task_registry.py','src/aicore/service/task/registry.py') for i, l in enumerate(pathlib.Path(p).read_text(encoding='utf-8').splitlines(), 1) if len(l) + sum(1 for c in l if ord(c) > 0x2E80) > 100]"
(无输出)
```

`pyproject.toml` 的 `line-length` 与 E501 **未改动**（未为了让检查变绿而放宽任何规则）。

### ④ mypy --strict

```
PS> .\.venv\Scripts\python.exe -m mypy --strict src
Success: no issues found in 59 source files
EXIT_MYPY=0
```

**判据：EXIT=0 ✓**

### ⑤ import-linter

```
PS> .\.venv\Scripts\lint-imports.exe --config .importlinter

Analyzed 59 files, 87 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
EXIT_IL=0
```

**判据：EXIT=0（4 kept / 0 broken）✓**。那条 warning 是**既有**状态（`.importlinter` 里
`unmatched_ignore_imports_alerting = warn`：`aicore.service.** -> aicore.provider.base` 尚无真实导入）。
**本任务未 import provider 任何东西**（源码 AST 断言 + 上面的 KEPT 共同证明）；为此**未改** `.importlinter`。

---

## 7. 偏离项与理由

**D1（接口扩展，工单 §1 明文授权）**：`get_policy` / `assert_submittable` 在工单给定签名之上各加一个
**keyword-only** 参数 `settings: Settings | None = None`。位置参数契约与工单逐字一致
（`get_policy("OCR")` 照旧可用）。依据：§1「`get_policy` MUST 从 `Settings` **现读（可注入）**」+
§4.11「用两个不同的 `ai_call_timeout_s` 值各取一次策略」。不注入就只能靠改环境变量 + 清
`get_settings` 缓存，那会污染同进程其它用例；注入让"现读"可被直接证明。

**D2（控制者给定的接口有内部冲突，我做了取舍，请复核）**：§1 同时要求
(a)「`REGISTRY` MUST 是**模块级常量**」与 (b)「`timeout_s` MUST NOT 被**冻结**成模块级常量」。
一个模块级常量表的字段**不可能**同时是"导入期定值"和"每次调用现读"——除非改类型（`float | None`）
或让 `REGISTRY` 变成惰性 Mapping（都是接口变更，超出我的授权）。我的取舍：

- `REGISTRY` 是**声明表**，行内 `timeout_s` = `_BORROWED_TIMEOUT_S`
  ＝ `float(Settings.model_fields["ai_call_timeout_s"].default)`（**不是硬编码 5.0**，避免同一数字两处出处；
  **也不是**导入期 `get_settings()`——那会让"import 本模块"变成一次配置解析，配置写错时在 import 期抛
  `ValidationError`，绕过 `core/config.py` 的启动期 `ConfigRejected` 路径）；
- `get_policy` 每次用 `dataclasses.replace(行, timeout_s=现读值)` 覆盖，**权威取值一律经 `get_policy`**。

**代价（如实登记，已写进 `registry.py` docstring 与 `_BORROWED_TIMEOUT_S` 注释，并有用例钉住）**：
环境变量覆盖了 `AICORE_AI_CALL_TIMEOUT_S` 时，直接读 `REGISTRY[…].timeout_s` 会拿到**配置默认值**而不是
生效值。故直接读表只用于结构断言。若控制者认为"读表即权威"是硬要求，请裁定改成
`timeout_s: float | None`（`None`=取现读）或惰性 Mapping——我按裁定改。

**D3（歧义消解）**：§1 表里三个预留位的 `handler_ref` 只写「预留」，未给字面量。我用**显式哨兵
`"<reserved>"`**，而不是编一个 `service.vision_review` 之类的模块路径——design.md L190-192 只写「预留
注册位」，L136-140 的目录树里也确实**没有** `vision_review.py`。编一个不存在的模块路径会让 Task 4.7 的
导入探测得到假的「注册表与实现不一致」。用例断言该哨兵**不是合法模块名形态**且按它拼出的路径不存在。

**D4（强化，非偏离）**：`REGISTRY` 用 `MappingProxyType` 包装。§1 只要求"模块级常量"，而
`Final[Mapping[…]]` 只挡 mypy、运行期 `REGISTRY["X"] = …` 照样能改裸 dict；注册表是共享常量，
就地改会污染所有调用方，故做成运行期只读（写入抛 `TypeError`，有用例）。

**D5（用例多于 13 条）**：见 §4 末尾的 5 条增补，均为补强（互等比对 / import 扫描 / 运行期增量 / 存在性下限 / 解析器自证），
不替代工单要求的任何一条。

**未偏离项**：`3006`/`3007` 未被使用（两条失败都用 `1003`，与 §2.2 一致）；`REGISTRY` 未增删类型
（4 条、键集合与 er.md enum 互等）；`handler_ref` 未导入（AST + 运行期双重断言）；未改
`provider/**`、`repository/**`、`core/**`、`api/**`、`submit.py`、`state.py`、`pyproject.toml`、
`.importlinter`、`tests/` 下既有文件。

---

## 8. 「没做到的事」清单（明确登记）

1. **判据 B（`task_runner` 无类型字面量）本任务未真正执行**：`core/task_runner.py` 仍是 1 行空壳，
   用例显式 SKIPPED。我**没有**用任何方式假装验过；Task 4.7 交付执行器后该断言自动生效
   （跳过条件是"文件无代码"，不是"不想跑"）。同理，**"新增类型不改 task_runner"这个结构性性质，
   本任务只证明了"注册表侧是表查找而非分支"**，执行器侧的稳定性要等 Task 4.7 才可证。
2. **"未注册/未实现类型被拒"目前是函数级保证，HTTP 提交路径尚未接线**（**重要接缝，需控制者分派**）：
   Task 4.5 的 `service/task/submit.py:72-73` 自带 `OCR_TASK_TYPE: Final = "OCR"` 常量，
   **未 import 注册表**。即：M1 提交路径现在有**第二个任务类型来源**；`assert_submittable` 已交付但还没有
   调用方。按工单我 MUST NOT 碰 4.5 的文件，故我**没有**接线，只在此登记。建议由 4.5 或 4.7 任一方收口
   （例如 `api/ocr.py` 受理处调用 `assert_submittable`）。
3. **未验证超时值的业务正确性**：`timeout_s` 是**从调用级超时借用**的值，不是独立定档的任务超时
   （design.md / er.md 均无任务级超时数值）。我只证明了"它随 `Settings` 现读、不是冻结常量"，
   没有、也无法证明"5.0s 适合一次完整 OCR 任务"。风险已写入 `registry.py` docstring 并注明
   Task 4.7 可能需要回来改这里。
4. **未做真实 MySQL / Redis 集成验证**：本任务纯声明 + 纯函数，无 IO；未跑 `-m integration` 段
   （工单未要求，我的用例也不属 integration 标记）。
5. **未验证"执行器真的会走注册表"**：那是 Task 4.7 的契约（见第 1 条）。
6. **未覆盖的边界（有意接受）**：判据 A 只认"与字符串字面量比较"的形态；若有人用
   `if task_type in {"OCR"}` 之外的等价写法（如查一个 `_BRANCH = {"OCR": …}` 的**模块级私有 dict**），
   判据 A 不会报红——那种写法其实仍是"表查找"（符合 design.md:194 的意图），故不算漏判；
   但若有人把逐类型分支藏进**另一个模块**（如 `task_runner` 里写分支），判据 A 管不到，
   由判据 B（`task_runner` 字面量扫描）与 Task 4.7 的工单覆盖。
7. **探针纪律**：本轮**新建临时脚本 0 个**（上限 2 个），没有留下任何探针文件；
   所有变异自证都在内存里完成。

---

## 9. 并发干扰记录（Task 4.5）与最终归属

| 时点 | 全量/命令结果 | 归属 |
|---|---|---|
| 我第一次全量 | `1140 passed, 14 skipped, 19 deselected`，EXIT=0 | 当时 4.5 的产物尚未接线，全绿 |
| 第二次 | `ImportError while loading conftest`：`main.py:143 app.include_router(tasks.router)` → `aicore.api.tasks` 无 `router` | **4.5**（其 `api/tasks.py` 当时仍是 46 字节空壳）。我用 `--noconftest` + 注入 conftest 同款环境变量隔离自证我的文件（28 passed, 1 skipped） |
| 第三次 | `5 failed` 全在 `tests/structural/test_layering.py`；根因 `aicore.api.tasks -> aicore.repository.{base,models,task_repo}`（契约 1 BROKEN，`api/ocr.py:100` 的 mypy 错同时存在） | **4.5**。另 4 条失败是它们自己的"其余三条契约仍须 KEPT"连带断言 |
| 最终（4.5 修复后） | 五条命令全绿（§6） | 无我方失败项 |

**结论：本轮五条验收命令全绿，没有任何失败项可归因于 Task 4.6。**

---

## 10. 复现命令（逐条照抄即得 §6 输出）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_task_registry.py -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
.\.venv\Scripts\ruff.exe check --no-cache src tests
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```
