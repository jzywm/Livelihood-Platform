### Task 4.6: 任务类型策略注册表（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM / LF；用 write/edit 工具，**MUST NOT** 用 PowerShell `Set-Content`/`Out-File` 写中文。
**Shell**：`sh` 不可用（`E_ACCESS_DENIED`），命令一律 PowerShell；**每个 pwsh 调用前先 `$env:PYTHONUTF8='1'`**。
pytest 加 `-p no:cacheprovider`；**要看 `passed` 计数行必须写 `-o addopts=""`**。

**Files:**
- Modify: `src/aicore/service/task/registry.py`（当前是 1 行 docstring 空壳）
- Create: `tests/unit/test_task_registry.py`
- **MUST NOT 改**：`provider/**`、`repository/**`、`core/**`、`api/**`、
  `service/task/state.py`、`service/task/submit.py`（Task 4.5 的产物）、
  `pyproject.toml`、`.importlinter`、`tests/` 下的既有文件。

---

## 0. 先读这些（**MUST 用 read 工具完整读**）

1. `openspec/changes/implement-aicore-service/design.md` **§任务类型策略注册表 L185-194**
   —— **这是本任务的唯一权威依据**，逐字包含：
   - 「`ai_task.type` 的每个取值对应一个处理器，在 `service/task/registry.py` 注册，
     处理器需声明自身的结果结构、超时与是否可重试」；
   - 四行任务类型表（`OCR` → `service/ocr_service.py` → `OcrResult` → **M1 实现**；
     `VISION_REVIEW` / `KITCHEN_ANOMALY` / `RISK_PREDICT` → 预留注册位 → 否）；
   - 「**为什么用注册表**：M2 新增视觉审核时，期望的改动量是「新增一个处理器文件 + 一行注册」，
     而不是去改 `task_runner` 的分支逻辑。这也保证 `task_runner` 在 M1 之后保持稳定……
     **未注册的类型必须显式失败**（而非静默忽略），避免告警丢失。」
2. `services/aicore/docs/er.md` **§6.1 L291**（`type` 的 enum 四个取值，逐字）
3. `services/aicore/docs/openapi.yaml` **L764-768**（`TaskType` 枚举）、
   **L787-825**（`TaskResult` 的 `result` 是 `oneOf` 四个结果结构）、
   **L863-884**（`VisionReviewResult`）、**L1144-1165**（`KitchenAnomalyResult`）、
   **L1179-1208**（`RiskPredictResult`）
4. `src/aicore/service/ocr_service.py`（当前是 1 行空壳——**本任务不实现它**，
   只在注册表里登记它的**位置**与**声明**）
5. `src/aicore/core/config.py` 的 `ai_call_timeout_s`（L~331 起）——注册表的超时口径要与它对齐

---

## 1. 交付接口（签名逐字）

```python
@dataclass(frozen=True, slots=True)
class TaskPolicy:
    """一个任务类型的**声明**：结果结构、超时、是否可重试、处理器位置。"""

    task_type: str
    result_schema: str          # 结果结构名，逐字取自 openapi.yaml 的 components.schemas
    timeout_s: float
    retryable: bool
    handler_ref: str            # 处理器所在的模块与属性（本任务只登记"在哪"，不导入它）
    implemented: bool           # M1 是否已实现

REGISTRY: Final[Mapping[str, TaskPolicy]]
def get_policy(task_type: str) -> TaskPolicy: ...
def registered_types() -> frozenset[str]: ...
```

**四条登记（逐条对齐 design.md L189-192 的四行表，MUST NOT 增删）**：

| `task_type` | `result_schema` | `timeout_s` | `retryable` | `handler_ref` | `implemented` |
|---|---|---|---|---|---|
| `OCR` | `OcrResult` | 取 `Settings.ai_call_timeout_s` | `True` | `service.ocr_service` | `True` |
| `VISION_REVIEW` | `VisionReviewResult` | 同上 | `True` | 预留 | `False` |
| `KITCHEN_ANOMALY` | `KitchenAnomalyResult` | 同上 | `True` | 预留 | `False` |
| `RISK_PREDICT` | `RiskPredictResult` | 同上 | `False` | 预留 | `False` |

**关于 `timeout_s` 的来源（控制者裁定 + 一处必须你知悉的取舍）**：
- `ai_call_timeout_s` 是**单次模型调用**的超时（Task 4.3，默认 5.0s）；
- 任务级超时**理论上**应 ≥ 一次调用（含重试），但**设计文档未给任务级超时值**
  （`design.md` 无该数值，`er.md` 亦无）。
- **裁定：`TaskPolicy.timeout_s` 取 `Settings.ai_call_timeout_s`**，
  并在 docstring 逐字写明「这是**从调用级超时借用**的值，不是独立定档的任务超时」。
  **理由**：M1 只有 OCR 一个任务类型、且它当前只做提交（执行归 Task 4.7），
  凭空造一个"任务级超时"数字等于自造第三口径（违反自约束 C2/C7）；
  借用一个**有出处**的值并**显式标注它是借用**，比造一个没出处的值诚实。
  **风险已告知**：Task 4.7 实现执行器时若发现借用值不合适，需要回来改这里——
  故 `get_policy` MUST 从 `Settings` **现读**（可注入），MUST NOT 把它冻结成模块级常量。

**`REGISTRY` 的结构约束**：
- `REGISTRY` **MUST 是模块级常量**（不是 `get_policy` 内现算），使用例能对整张表断言；
- **键集合 MUST 恰好等于 `er.md` §6.1 L291 的 `type` enum 四个取值**，MUST NOT 多、MUST NOT 少；
- **`result_schema` MUST 逐字等于 `openapi.yaml` 的 `components.schemas` 里的名字**——
  四个名字都真实存在（`:749` `OcrResult`、`:863` `VisionReviewResult`、
  `:1144` `KitchenAnomalyResult`、`:1179` `RiskPredictResult`）。

---

## 2. `get_policy` 的硬约束

1. **未注册类型 MUST 显式失败**：抛 `ParamError(code=1003)`（枚举或范围非法），
   消息里**必须带上是哪个类型**，MUST NOT 静默返回 `None`、MUST NOT 回落成默认策略。
   依据 `design.md:194` 逐字「未注册的类型必须显式失败（而非静默忽略），**避免告警丢失**」。
2. **`implemented=False` 的类型（三个预留位）在 M1 提交时 MUST 被拒**：
   本任务提供一个单独的判据函数：

   ```python
   def assert_submittable(task_type: str) -> TaskPolicy:
       """提交前的准入判定：未注册 → 1003；已注册但 M1 未实现 → 1003（消息不同）。"""
   ```

   **为什么不是 `3006` 或 `3007`**：这是「请求里的枚举值不在**当前可用**范围内」，
   正是 `1003`（枚举或范围非法）的定义；`3006` 是「对象不存在」（针对已存在的资源）、
   `3007` 是「状态不允许该操作」（针对资源状态）。**MUST NOT 混用。**
3. **`get_policy` / `assert_submittable` 都 MUST NOT 导入处理器本体**（`handler_ref` 只是字符串）：
   导入处理器会让注册表与具体实现耦合，且 M1 的三个预留位**没有实现可导**——
   `design.md:194` 要求的改动量是「新增一个处理器文件 + 一行注册」，若注册表 import 处理器，
   那一行注册就同时变成一次导入、失败面扩大。

---

## 3. 本任务的**结构性断言**（design.md 明确要求的那一条）

`design.md:194` 逐字：「保证 `task_runner` 在 M1 之后保持稳定——它是 D2「M2 可切 MQ」的替换点，
越少人动越好」，`tasks.md` 4.6 的验收含「**新增类型不改 `task_runner`**（结构性断言）」。

**本任务交付该断言的用例**（Task 4.7 才写 `core/task_runner.py`，故本任务用 AST 做**源码级**断言）：

```python
def test_adding_a_type_does_not_require_touching_the_runner() -> None:
    """注册表是唯一的类型→处理器映射处；`task_runner` MUST NOT 含类型分支。"""
```

判据（两条都要）：
1. **在 `registry.py` 的源码里**：MUST NOT 出现 `if task_type ==` / `match task_type` 这类
   **逐类型分支**；类型→策略的解析 MUST 是**表查找**（`REGISTRY[...]`）。
   —— 这条保证「新增类型 = 加一行表项」而不是「加一个 elif」。
2. **对 `core/task_runner.py`**：若文件已存在，AST 断言其中**不出现任何任务类型字面量**
   （`"OCR"` / `"VISION_REVIEW"` / `"KITCHEN_ANOMALY"` / `"RISK_PREDICT"`）。
   若文件尚不存在（本任务时它仍是空壳），**MUST 跳过并说明**，MUST NOT 假装验过。
   —— 跳过必须有明确理由，且 Task 4.7 的工单会接上这条断言。

**判别力自证**（必须）：用例内构造一个「用 elif 链」的合成实现，断言第 1 条的判据**会**把它判红
——否则判据可能只是「扫了个空文件」而已（本组已出现三次同形态假绿）。

---

## 4. 用例清单 `tests/unit/test_task_registry.py`

1. 四条登记逐条断言（`task_type` / `result_schema` / `retryable` / `implemented`）；
2. **`REGISTRY` 的键集合与 `er.md` §6.1 L291 的 enum 现读比对**
   —— 从 `er.md` 那一行解析 ``enum('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT')``，
   **MUST NOT 抄成常量**；
3. **`result_schema` 逐个在 `openapi.yaml` 的 `components.schemas` 里存在**
   —— 从 `openapi.yaml` 现读 `schemas` 段的键集合再比对，**MUST NOT 抄成常量**；
4. `get_policy` 对四个已注册类型各返回对应策略；
5. `get_policy("NOPE")` → `ParamError` 且 `code == 1003`，且消息里**含** `"NOPE"`；
6. **`get_policy` 对未注册类型 MUST NOT 返回 `None`、MUST NOT 回落默认策略**
   （用 `pytest.raises` 断言它抛错，而不是断言返回值——这条区分「显式失败」与「返回哨兵」）；
7. `assert_submittable("OCR")` 通过；
8. `assert_submittable` 对三个 `implemented=False` 类型各抛 `1003`，
   且消息与「未注册」那条**不同**（证明两种失败可分辨，对应 `design.md:194` 的「避免告警丢失」）；
9. `assert_submittable("NOPE")` 抛 `1003`；
10. `registered_types()` 恰好等于 `REGISTRY` 的键集合；
11. `timeout_s` **从 `Settings` 现读**：用两个不同的 `ai_call_timeout_s` 值各取一次策略，
    断言两次的 `timeout_s` 分别等于对应配置值 —— **证明它不是被冻结的模块常量**；
    并在 docstring 写明该值是**从调用级超时借用**（出处与取舍见 §1）。
12. **`TaskPolicy` 是 frozen dataclass**：断言改字段抛 `FrozenInstanceError`
    （防「策略被某处就地改写」——注册表是共享常量，就地改会污染所有调用方）；
13. 结构性断言 + 判别力自证（§3 两条）。

---

## 5. 验收（自证，**原始输出全部贴报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_task_registry.py -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
.\.venv\Scripts\ruff.exe check --no-cache src tests
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

- 全量判据 MUST 写「**EXIT=0 且 failed == 0**」，**MUST NOT 写固定计数**。
- `service/task/registry.py` 属 `service` 层：受 `.importlinter` 契约 2 约束
  （只可与 `provider/base.py` 交互）；本任务**不应** import provider 任何东西。
- **MUST NOT `git commit` / `git add`**。
- **MUST NOT 用「改 `src/` 文件 + finally 还原」做变异测试**（本组两次踩过，注入残留过）。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.6-report.md`。

## 6. 探针纪律

新建的临时脚本 > 2 个即停下报告。发现控制者给的接口有硬伤 → **停下并在报告里写明**。
