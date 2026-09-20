# Task 4.9 工单：任务提交幂等与跨账号越权拦截

**阶段**：第 4 组 G 段（G = 4.9 / 4.10 / 4.11）
**依据**：`openspec/changes/implement-aicore-service/tasks.md:45`（任务口径）· `spec.md:25`/`:35`（权威需求）·
`er.md:22`（`uk_idem` 唯一键）· `design.md`（幂等与越权相关段）
**前置**：T1（4.5/4.6）与 T2（4.7/4.8）已交付；HEAD 见开工时的 `git log`

---

## 0. 第一步是 **RECON，不是写代码**

T1 已经把幂等与越权的**大部分机制**铺好了，本任务很可能是"**补缺口 + 把它钉成判据**"，
**MUST NOT** 重新实现一遍。请先读并**在报告里逐项列出"已有什么 / 缺什么"**，再动手：

- `service/task/submit.py`：`compute_idem_key(explicit, image_key, doc_type)`、`submit_ocr_task`、`SubmitOutcome`
- `repository/task_repo.py::find_by_idem_key`（按 `uk_idem` 查同月表内原任务）
- `service/task/query.py::load_owned_task`（归属判定 → `2002`）
- `api/ocr.py`（`202` + `TaskAccepted`）、`api/tasks.py`（轮询）
- `docs/openapi.yaml` 的 `TaskAccepted` / 错误码声明

**已知缺口（T1 自己登记的，很可能就是本任务的活）**：
> 并发同幂等键提交有竞态：第二个 `insert` 撞 `uk_idem` → `5000`

`spec.md:25` 要求「重复提交 MUST 幂等，返回**原任务标识**而不重复产生任务与调用费用」——
**并发重复**是"重复提交"的一种，撞唯一键后应当**回读原任务并返回它**，而不是报 `5000`。

---

## 1. 目标（tasks.md:45 逐字）

> 实现任务提交幂等与跨账号越权拦截（相同幂等键返回原任务号不重复调用；非本人任务查询返回 `2002` 且不泄露任何结果内容）

## 2. 判据形态（**控制者已裁定，照此执行**）

### 2.1 幂等：「Provider 调用次数不增加」的字面判据在 M1 无处落点

**问题**：`main.py` 注的是 `handlers={}`、`service/ocr_service.py` 是空壳 ⇒ **提交路径根本不调 Provider**
（OCR 处理器属第 5 组 K-01）。字面判据没有落点。

**等价且可测的形态（MUST 照此）**：
1. 构造一个**计数 handler** 的 `TaskRunner`（替身即可，**MUST NOT** 依赖第 5 组）；
2. 同一 `(account_id, idem_key)` 提交**两次**；
3. 断言：`ai_task` **只多一行**、第二次返回**原 `taskId`**、**可领取任务只有一条**
   ⇒ 执行器把该任务交给处理器时，**处理器只被调用一次**。

**这就是 `spec.md:25`「不重复产生任务**与调用费用**」的可观测代理**（调用费用 = 每任务一次处理器调用）。
**并登记**：字面版（真 Provider 的调用次数）应在第 5 组注入真实 OCR 处理器后补一条端到端用例。

### 2.2 并发重复提交（上面那个已知缺口）

两个并发请求带同一 `(account_id, idem_key)`：**恰好一个创建、另一个返回同一个 `taskId`**，
**两个响应都必须成功**（`MUST NOT` 让其中一个报 `5000`）。
实现要点（由你定，但要在 docstring 写明依据）：撞 `uk_idem` 的 `IntegrityError` 要**回读**而不是上抛；
回读要**走主库**（`er.md:287`「关键『写后立即读』强制走主库，避免主从延迟读到旧状态」）。

### 2.3 越权：**MUST NOT 只断言状态码**

`spec.md:35` 要求「返回 `2002` 且**不泄露该任务的任何结果内容**」。
⇒ 判据要**同时**断言：① `code == 2002`；② 响应体**只含信封四字段**、`data` 为 `null`；
③ 响应里**不出现**该任务的任何业务内容（原图键、字段值、结论）。

**判别力自证（MUST）**：构造一个"码对但把结果塞进了 `data`"的实现（**内存变异或局部复制控制流**），
上述 ②/③ **必须变红**。只断言码的判据对它是绿的——**那正是要防的形态**。

### 2.4 幂等的**键来源**要各有一条判据

`compute_idem_key` 有两条路径：显式 `Idempotency-Key` 优先，否则 `sha256(imageKey NUL docType)` 派生
（`er.md:290`「同 imageKey+docType 返回原任务号」）。**两条都要有用例**，且要有一条
**"不同 docType 不互相幂等"** 的阴性用例——只测"相同键幂等"会让"把 key 写死"的实现照样绿。

---

## 3. 必须改 / 不许改

- **可改**：`service/task/submit.py`、`service/task/query.py`、`api/ocr.py`、`api/tasks.py`、
  `repository/task_repo.py`（**仅在你确实需要新查询时**，且必须在报告里单列理由）、
  以及 `tests/` 下与之相关的新增用例文件；
- **不许改**：`provider/**`、`core/lease.py`、`core/task_runner.py`、`core/errors.py`、`core/config.py`、
  `.importlinter`、`pyproject.toml`；**既有测试文件**除非本任务直接相关（改了要在报告里逐条说明改了什么、为什么）；
- **契约**：`api` 不得直接依赖 `repository`（契约 1）；`service` 只可与 `provider.base` 交互（契约 2）；
  `core` 不得依赖任何业务层（契约 4）。**新增 import 前先想清它属于哪一层**——
  本任务最容易踩的是"在 `api` 里直接查库"。

## 4. 交付与验收

- **先 RECON 再动手**：报告里先给"已有什么 / 缺什么"的清单；
- 交付形态：**1~2 个提交**（建议：① 并发重复提交的回读修复 + 判据；② 越权不泄露的判据补严）；
- **MUST NOT** 自己 `git add`/`git commit`；
- 验收命令（缺 MySQL 时会失败，如实报告而不是绕过）：
  ```
  pytest -p no:cacheprovider -o addopts="" -m "not integration" -q
  pytest -p no:cacheprovider -o addopts="" -m "integration" -q
  ruff check --no-cache src tests scripts
  mypy --strict src
  lint-imports --config .importlinter
  python scripts/group3_acceptance.py
  ```
- **判别力自证**：本工单点名的两处（2.3 的"码对但泄露"、2.4 的"key 写死"）**都要能判红**；
  做不出就停下写明是哪一条。
