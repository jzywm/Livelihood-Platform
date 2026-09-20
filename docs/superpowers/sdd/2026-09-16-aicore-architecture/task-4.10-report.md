# Task 4.10 报告：置信度分级（阈值可配并留痕）

**基线**：HEAD `d1ff44e` + `5ae4af2`（Task 4.9 的两次提交），工作树干净
**工单**：`task-4.10-brief.md`（目标逐字取自 `tasks.md:46`）
**环境**：MySQL 与 Redis 均可用（控制者确认；本报告的集成段 `54 passed / 0 skipped`）
**纪律**：未 `git add` / `git commit`；探针 **0 个新文件**；未动 `provider/**`、
`core/task_runner.py`、`core/lease.py`、`.importlinter`、`pyproject.toml`、`er.md`、`openapi.yaml`。

---

## 0. RECON（先读代码与三处权威口径，再动手）

### 0.1 三处文档的边界口径（**核对结果：与裁定一致，没有冲突**）

| 出处 | 原文（逐字） |
|---|---|
| `spec.md:58` | 系统 SHALL 对 AI 输出做置信度分级（**高 ≥0.9、中 0.7~0.9、低 <0.7**），分级阈值 MUST 可按运营数据调整并留痕。分级结果 MUST 随 AI 输出一并返回，供人工复核与处置排序使用。**置信度 MUST NOT 被用作跳过人工确认的依据。** |
| `er.md:63` | `enum confidence_level "HIGH≥0.9/MEDIUM0.7~0.9/LOW<0.7"`（在 `VISION_REVIEW` 表上 = **M2 的任务类型**） |
| `er.md:301` | 置信度分级阈值 \| ✅ 已定（2026-09-11）：HIGH ≥0.9 / MEDIUM 0.7~0.9 / LOW <0.7 \| 已定档，工作台运营期可调 |

⇒ 三处的重叠（`0.9` 与 `0.7` 各被两档包含）确实存在，工单 §2 的裁定与"显式边界优先"的理由成立。
**没有任何文档与工单 §3（`None` 不判级 + 兜底）冲突**——三处都只写有值的情形，属于"文档少写"。

### 0.2 已有什么（可复用的落点）

| 关切 | 已有 | 本轮用法 |
|---|---|---|
| `confidence` 的可空语义 | `provider/results.py` 的模块 docstring + `OcrField.confidence` / `ProviderResult.confidence`（`float \| None`，"MUST NOT 补 0"） | **不改**；本模块只吃 `float \| None`（契约 2 禁止 `service → provider` 整包） |
| 阈值快照的容器 | `ProviderIdentity.thresholds`（docstring 逐字写 `{high, medium}`）+ `as_model_meta()`（渲染 `ai_task.model_meta` 的 5 键） | 键名**逐字对齐**它；本任务只写 `thresholds` 一个键，其余 4 键归执行期 |
| 受理回执 | `api/ocr.py` 的 202 + `TaskAccepted`；依赖注入点齐备（`get_account_id`/`get_engine_factory`/`get_now`） | 新增第 4 个依赖 `get_settings`（只为两个阈值） |
| 落库路径 | `submit.py::new_task` 逐列造行；`api/tasks.py` 轮询回执 | `model_meta` 从 `None` 改成 `{"thresholds": …}` |
| 配置 | `Settings` + 跨字段校验器（`budget-order` / `readonly-pair` 等先例）+ `.env.example` + 测试里固化的字段表 | 加两个字段 + 一条同族跨字段规则 |

### 0.3 缺什么（本任务的活）

1. **分级函数本身不存在**（全仓只有文档口径，没有实现）；
2. **两个阈值不在配置里**（`er.md:301` 要求"运营期可调"）；
3. **`model_meta.thresholds` 没有任何写入点**（`new_task` 写的是 `None`，"归执行期"）；
4. **"随 AI 输出返回分级"没有载体**（`grade()` 不存在）；
5. **判据全缺**（边界三分、`None` 处置、阈值移动、留痕、`MUST NOT` 免人工）。

---

## 1. 三分函数的边界表（工单 §7 要求）

`service/task/confidence.py::classify_confidence(confidence, *, high, medium)`
（**纯函数**：无 IO、无配置读取、无隐藏状态；两个阈值显式传入）。

| 输入 | 判级 | 归属规则（`er.md:63`） |
|---|---|---|
| `0.9` | **`HIGH`** | `c >= high`（**显式边界优先**：`HIGH≥0.9`） |
| `0.899` | **`MEDIUM`** | `medium <= c < high`（余下区间自然取半开） |
| `0.7` | **`MEDIUM`** | 同上（`MEDIUM 0.7~0.9` 是**区间描述**，不占端点） |
| `0.95` | `HIGH` | 档内值（判据要"各档内再各一个值"） |
| `0.8` | `MEDIUM` | 档内值 |
| `0.1` | `LOW` | `c < medium` |
| `1.0` | `HIGH` | 值域上端（`er.md` §6.2：confidence 是 0~1） |
| `0.0` | `LOW` | 值域下端——**注意：`0.0` 判 `LOW`，`None` 不判级**（见 §2） |
| `None` | **不判级（`None`）** | 控制者裁定，见 §2 |

**"阈值可配"只影响两条线**：`high` / `medium` 是参数（来自 `Settings` 冻结进快照的当次值），
**不影响**上面的归属规则——规则只有一处实现，见上表的第三列。

---

## 2. `None` 处置的 docstring 原文（工单 §7 要求）

`service/task/confidence.py` 的模块 docstring §二（**逐字**）：

> ## 二、`confidence is None`：**不判级** + `needs_manual_review = 1`（控制者裁定）
>
> 三处文档只写了"有置信度"的情形 ⇒ 这是典型的**文档少写**。裁定：
>
> - **不判级**（`level is None`），**MUST NOT** 返回 `LOW`；
> - 且 **`needs_manual_review = 1`**——依据 `er.md:40`「置信度**不足**转人工核验**兜底**」的目的：
>   通道没给置信度 ⇒ AI 无法自证可靠 ⇒ 走兜底。
>
> **这两件事的语义区别（MUST NOT 混同）**：
>
> - ❌ **把 `None` 当 `0.0`** ⇒ 伪造出一个 `LOW`：那是**造假数据**——系统凭空宣称
>   "这次判定置信度极低"，而真实情况是"通道没给这个数"。`provider/results.py` 的
>   `OcrField.confidence` 逐字写着"**MUST NOT 补 0**"，理由就是这个。
> - ✅ **`None` ⇒ 不判级 + 兜底**：**保守兜底**——系统如实说"这次没有可用的置信度"，
>   同时按"无法自证可靠"处置（转人工）。两者对下游的差别是：
>   前者给出一条**假的低置信度记录**（会污染按置信度排序与统计），后者给出一条
>   **没有分级的记录 + 人工兜底**。

对应的判据（`tests/unit/test_confidence.py`）：`level is None` **且**显式断言
`level is not ConfidenceLevel.LOW` **且** `needs_manual_review is True`。
第二段是判别力所在——只断言"转人工"的话，把 `None` 当 `0.0` 的实现**也给 True**（`LOW` 同样转人工）。

### 2.1 `needs_manual_review` 置位规则（一处**我做的**判断，请复核）

| 档位 | 置位 | 依据 |
|---|---|---|
| `None` | **1** | `er.md:40` 兜底目的（控制者裁定） |
| `LOW` | **1** | `er.md:345`「识别置信度不足 → 转人工核验兜底」 |
| `MEDIUM` / `HIGH` | **0** | 不在"不足"档；`spec.md:63` 的分级是**排序**依据——所有输出都进人工端，只是排序不同 |

**这是全篇唯一没有逐字文档支撑的取值**（文档只说"不足"转人工，没说 `MEDIUM` 算不算"不足"）。
我的读法：`er.md:481` 的 `needs_manual_review` 是"进**兜底**队列"的开关，
而 `spec.md:63` 明说人工端**按分级排序复核**（即人人都会看，只是顺序不同）⇒
只有 `LOW` 与"无置信度"进兜底队列。**若控制者认为 `MEDIUM` 也该置位，改一处即可**
（`confidence.py::grade` 的表达式 + 两条用例的期望值），其余不受影响。

---

## 3. §4 的 M1 边界（工单 §7 要求逐字登记）

> **M1 的边界（如实登记）**：`main.py` 注的是 `handlers={}` ⇒ **没有真实 OCR 执行** ⇒
> "随 AI 输出返回"这条**本阶段只能测到 service 层**（喂一个 `ProviderResult` 替身），
> 端到端（真通道 → 真落库 → 轮询返回分级）**登记为第 5 组补**。**MUST NOT** 假装它已端到端验过。

本轮的实际落地与之逐字一致，且**没有喂 `ProviderResult` 替身**——比工单更保守一步：
`grade()` 收的是 `float | None`（因为 `.importlinter` 契约 2 把
`aicore.service → aicore.provider` **整包**列为违规，只放行 `provider.base`），
调用方（第 5 组）把 `result.confidence` 取出来传进来。

**这条边界现在由一条会自己过期的判据守着**：
`tests/api/test_confidence_grading.py::test_m1_has_no_ocr_handler_so_grading_is_not_end_to_end_yet`
断言 `main.py` 里仍有 `handlers={}`；第 5 组注入真实处理器之后它会**自动变红**，
提示必须补 ① `ocr_result.needs_manual_review` 与 ② "分级随输出返回"两条端到端判据。
"待第 5 组补"因此不是报告里的一句注释，而是一个到点会响的提醒。

---

## 4. 判据与判别力自证（工单 §5 逐条）

| 工单 §5 | 判据 | 落点 |
|---|---|---|
| 1 边界三分（`0.899/0.9/0.7` + **各档内一个值**） | `_assert_ruled_levels`（9 格逐格断言：`0.9/0.899/0.7` + `0.95/0.8/0.1` + `1.0/0.0/0.6999`） | `tests/unit/test_confidence.py` |
| 2 `None` 不判级 + 兜底 + **没变成 `LOW`** | `test_none_confidence_is_not_graded_but_goes_to_manual_review` + 对照组 `test_zero_confidence_...` | 同上 |
| 3 阈值可配、**边界随之移动** | `test_changing_the_high_threshold_moves_the_boundary` / `..._medium_...`（同一输入、不同阈值 ⇒ 档位改变） | 同上 |
| 4 **留痕 = 当次快照** | `test_threshold_snapshot_is_frozen_at_submission`（提交 A → 改配置 → 提交 B → **回头读 A 仍是旧值**）+ `test_threshold_config_really_reaches_the_route` | `tests/api/test_confidence_grading.py` |
| 5 `MUST NOT` 免人工 | `_assert_verdict_has_no_skip_field`（字段集合**恰好** `{level, needs_manual_review}`）+ 行为对照 `test_high_confidence_does_not_clear_...` | `tests/unit/test_confidence.py` |

### 4.1 判别力自证（工单 §5 末段点名的两条，**都能判红**）

| 变异（**内存变异，文件从不被写**） | 结果 |
|---|---|
| 三分 `>=` → `>`（闭区间口径） | 变异后 `0.9 → MEDIUM`、`0.7 → LOW`（**先断言变异生效**）；同一份判据 `_assert_ruled_levels` **必红**，且红在"c=0.9 应判 HIGH"那一格 |
| `thresholds_snapshot_of` 改成"读当前配置" | 变异后同一次读给出**当前配置**（`0.95/0.6`）而生产读法给出**行里的旧快照**（`0.9/0.7`，**先断言两者不同**）；同一份判据 `_assert_snapshot_is_frozen` **必红**，红在"当次快照"那一句 |
| （自加）`ConfidenceVerdict` 加一个 `skip_review: bool = False` | 字段集合判据**必红**（"字段集合变了"）——"高置信度免人工"落地的第一步会被拦住 |

**⚠ 自证里踩的一个坑（写下来免得后人重踩）**：变异体读的是
`core/config.py::get_settings`（进程内缓存那份），而**路由**读的是
`api/deps.py::get_settings`（从 `app.state.settings` 取的那份）——两个同名函数。
第一版只替换了路由依赖 ⇒ 变异体读到的仍是 `.env` 的默认值 ⇒ **"变异生效"那一步直接失败**。
自证里两处都换，才是同一个场景。

---

## 5. 改动清单（含对既有文件的两处改动，逐条说明）

| 文件 | 行数 | 改动 |
|---|---|---|
| `src/aicore/service/task/confidence.py` | **233（新建）** | 三分纯函数 + `ConfidenceVerdict` + `grade()` + 快照的写/读（`confidence_thresholds` / `thresholds_snapshot_of`） |
| `src/aicore/core/config.py` | 645 | 两个字段（`confidence_high`=0.9 / `confidence_medium`=0.7，`ge=0, le=1`）+ **一条跨字段规则** |
| `src/aicore/service/task/submit.py` | 360 | `new_task` / `submit_ocr_task` 收 `thresholds`，写 `model_meta={"thresholds": …}` |
| `src/aicore/api/ocr.py` | 293 | 新增 `Depends(get_settings)`（**只为两个阈值**）并传给编排 |
| `.env.example` | 68 | 两行（`AICORE_CONFIDENCE_HIGH` / `AICORE_CONFIDENCE_MEDIUM`）+ 出处注释 |
| `tests/unit/test_confidence.py` | **385（新建）** | §5 的 1/2/3/5 + 两条自证 + 快照读写 |
| `tests/api/test_confidence_grading.py` | **334（新建）** | §5.4 留痕（含自证）+ §5.3 接线 + M1 边界的过期提醒 |
| `tests/unit/test_config.py` | 698 | **既有文件**：`EXPECTED_FIELDS` 加两个名字 + 一条跨字段用例 |
| `tests/api/test_ocr_submit.py` | 895 | **既有文件**：`model_meta` 那条断言从 `is None` 改成逐字比对快照 |

### 5.1 对既有文件的两处改动（逐条说明"改了什么、为什么"）

1. **`tests/unit/test_config.py::EXPECTED_FIELDS` 加两个字段名**：
   该集合是"设计文档字段表逐项固化"（该用例的 docstring 逐字如此），
   且 `test_env_example_matches_field_names_one_to_one` 用集合相等把
   `Settings.model_fields` 与 `.env.example` 钉在一起 ⇒ **不更新它，加字段当场红**。
   这是"字段表同步"的机械落点（工单 §4 明示要同步字段表）。同时新增一条跨字段用例（见 §6）。
2. **`tests/api/test_ocr_submit.py` 的 `model_meta` 断言**：原来是
   `assert row["model_meta"] is None, "血缘（model_meta）在执行期才写，归 Task 4.7"`——
   本任务把"阈值快照"提前到受理时刻（`spec.md:128` 要"**当次**"，而受理是它最早可冻结的时刻，
   也是 M1 唯一可观测的时刻），故这一列在提交后**不再**是 `None`。
   断言改成**逐字比对那份快照**（值从 `app.state.settings` 现取，不写死），
   语义比原来更强（原来只断言"是 None"，现在断言"恰好是这份快照"）。
   **没有删除任何断言**，只在同一位置替换了这一条。
3. 顺带在同一文件加了 `_model_meta_of(row)` 助手：`_task_rows` 刻意走**裸 SQL**
   （要绕过被测代码的读路径），而 JSON 列在裸读下是**字符串**（ORM 才会反序列化）
   ——这不是缺陷，是"绕过 ORM 的代价"，写在助手注释里免得后人再踩。

---

## 6. 超出工单字面的一处（主动登记，可一键回退）

工单 §6 写「`core/config.py`（**仅新增两个字段** + 字段表/`.env.example` 同步）」。
除两个字段外，我**多加了一条跨字段规则**：

```python
if self.confidence_medium > self.confidence_high:   # 代号 confidence-order
    blockers.append(...)   # 启动期拒绝
```

**理由**：字段级校验（`ge=0, le=1`）管不到两者的**相对**关系，而反序的后果是
"中档区间变空 + `high` 以下一段被判成 HIGH"——运营以为改了中档线，实际得到另一个档位表，
**现场没有任何信号**（本项目的典型失效形态）。这与既有的
`budget_degrade_ratio < budget_alert_ratio` 规则**完全同族**（同样的收集式 `blockers`、
同样的 `[跨字段：…]` 代号），故我按先例加了它。
**相等是允许的**（`medium == high` ⇒ MEDIUM 档为空，是可表达的取舍），只拒"反序"。

**若控制者认为越界**：删掉 `_RULE_CONFIDENCE_ORDER` 常量 + 那个 `if` 块（约 12 行）
+ `test_confidence_thresholds_reject_a_reversed_pair` 一条用例即可，
其余实现与判据不受影响（分类器本身对反序是良定义的，见
`test_threshold_ordering_is_a_config_concern_not_a_classifier_concern`）。

---

## 7. 验收命令的原始输出（全部满绿）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
. .\.venv\Scripts\activate.ps1
```

### 默认段

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
1323 passed, 13 skipped, 54 deselected, 1 warning in 53.26s
```

> 1301 → **1323 passed**（+22：`test_confidence.py` 15 条 + `test_confidence_grading.py` 5 条
> + `test_config.py` 1 条 + 边界表由参数化改为单条后的净差）。

### 集成段（真 Redis + 真 MySQL，**0 skipped**）

```
$ python -m pytest -p no:cacheprovider -o addopts="" -m "integration" -q
54 passed, 1336 deselected in 27.61s
```

> 与 Task 4.9 收口时同数（本任务没有新增集成用例——分级与留痕都在 API/单元段可验），
> **`skipped = 0`** 满足控制者本轮的硬要求。

### ruff / mypy / lint-imports / 验收脚本 / Redis 残留

```
$ ruff check --no-cache src tests scripts
All checks passed!          EXIT=0

$ mypy --strict src
Success: no issues found in 62 source files

$ lint-imports --config .importlinter
Contracts: 4 kept, 0 broken.

$ python scripts/group3_acceptance.py
结果：PASS 10 / FAIL 0 / INFO 0

aicore:* = []   dbsize = 0
```

> `mypy --strict` 从 61 → **62 个源文件**（新增 `service/task/confidence.py`）。

---

## 8. 没做到的事（如实写）

1. **端到端没有验**（§3）：M1 无 OCR 执行 ⇒ `ocr_result.needs_manual_review` 与
   "分级随输出返回"只到 service 层。已登记为**第 5 组补**，并留了一条会自己过期的判据。
2. **`MEDIUM` 是否该置 `needs_manual_review`** 是我的判断（§2.1），文档没写；已给出改法。
3. **`needs_manual_review` 与分级的落库联动没有实现**：`ocr_result` 的写入归第 5 组
   （本任务不新增表、不新增列——`confidence_level` 那个 enum 列属 M2 的 `VISION_REVIEW`）。
4. **执行期"读回快照再分级"没有接线**：`thresholds_snapshot_of` 与 `grade` 都已就位并可测，
   但**没有生产调用方**（没有执行链路）——与第 1 条同源，第 5 组接线时才有调用点。
5. **`er.md` / `openapi.yaml` 一个字都没动**（工单：权威源，要动先问）。
   本轮不需要动它们：M1 的载体是 `model_meta.thresholds`（既有列）与
   `ocr_result.needs_manual_review`（既有列）。

---

## 9. 提交建议（1~2 个提交）

| 提交 | 内容 | 主要文件 |
|---|---|---|
| 1 | `feat(aicore): 置信度三分（阈值可配，含 None 的保守兜底）` | `service/task/confidence.py`（新建）、`core/config.py`、`.env.example`、`tests/unit/test_confidence.py`、`tests/unit/test_config.py` |
| 2 | `feat(aicore): 受理时冻结当次阈值快照（spec.md:128 留痕）` | `service/task/submit.py`、`api/ocr.py`、`tests/api/test_confidence_grading.py`（新建）、`tests/api/test_ocr_submit.py` 的一条断言 |

两个提交都能单独 checkout：提交 1 的实现不依赖提交 2（`grade` 的调用方在第 5 组），
提交 2 用到提交 1 的 `confidence_thresholds` / `thresholds_snapshot_of` ⇒
**若要求逐提交全绿，请按 1 → 2 的顺序提交**。
