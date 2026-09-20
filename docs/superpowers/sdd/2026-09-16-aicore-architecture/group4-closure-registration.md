# 第 4 组收口：四处「缓期」的仓库内登记（纯文档提交）

- 工作树：`D:\progrom\.worktrees\aicore-architecture`，基线 `f97849f`（R1/R2 两条已提交）
- **唯一改动文件**：`openspec/changes/implement-aicore-service/tasks.md`（+9 行，无删除）
- **未** `git add` / `git commit`
- 建议提交信息：`docs(aicore): 把第 4 组四处缓期登记进 tasks.md，并更正 4.3 的超时终码口径`

## 0. 一句话交付

四处缓期（4.8 耗时对照、4.8 附注 `run_cpu_bound` 未接、4.9 Provider 调用次数、4.10 分级端到端、
4.11 按码计数→指标）已作为**缩进登记行**写进 `tasks.md` 对应条目**下方**（原句一字未删），
并补了 4.3 的**口径更正**（超时/熔断终码 = `5002`，`4003` 只留给"等到了失败"）。
`openspec validate --all --strict`：**5 passed, 0 failed**；任务行数 **86 未变**。

登记位置的取舍说明：这四处都是"**M1 任务条款的阶段性缓期**"，指向的落点（`13.4`、`11.3`、第 5 组 §5）
也都在**同一个文件**里 ⇒ `tasks.md` 就是"跟着任务走的人一定会看到"的那个文件。
**没有**动 `services/aicore/docs/README`：README 是服务对外文档，同一件事写两处必然漂移
（本会话反复修的正是这种漂移）。若控制者更希望 README 也有一行指针，我可以补，但需要先说明再动。

---

## 1. ① 四处缓期登记（`tasks.md` 4.8 / 4.9 / 4.10 / 4.11）

### 1.1 `4.8`「并发提交时受理接口耗时不劣化（对照用例）」→ 归 `13.4`

登记要点（原句保留）：本阶段**未做**，归 `13.4`（压测 P95）。三条理由照裁定逐字写入：
① 它本质是**性能**条款，归宿就是压测；② M1 无 CPU 密集调用点，此时测"劣化"测不到东西；
③ 用例内自比时延正是本会话刚花整轮清掉的「时序余量判据」。

**依据核实（我在仓库里自己跑过一遍，不是照抄结论）**：

```
$ grep -rn "run_cpu_bound" services/aicore/src
src/aicore/core/task_runner.py:13     （docstring 说明）
src/aicore/core/task_runner.py:17     （docstring 说明）
src/aicore/core/task_runner.py:66     （docstring 表格）
src/aicore/core/task_runner.py:120    （docstring）
src/aicore/core/task_runner.py:198    （__all__）
src/aicore/core/task_runner.py:271    （注释）
src/aicore/core/task_runner.py:1008   （docstring）
src/aicore/core/task_runner.py:1304   （docstring）
src/aicore/core/task_runner.py:1360   def async def run_cpu_bound[U](...)   ← 定义
src/aicore/core/task_runner.py:1391   （docstring）
```

⇒ 全 `src/` 只在 `task_runner.py` 出现，且**没有任何调用点**（其余全是定义、`__all__` 与文档）
⇒ 附注「CPU 密集链路本阶段根本没接上」成立；同时我也记下了"这行 MUST NOT 读成 CPU 密集路径已被验证"。

### 1.2 `4.9`「断言 Provider 调用次数不增加」→ 字面判据缓期至第 5 组

登记要点：M1 受理路径**根本不调 Provider**（`main.py` 注入 `handlers={}`、`services/ocr_service.py` 空壳）
⇒ 字面判据**没有落点**；本阶段用**等价形态**（可领取行恰好一条 ⇒ 处理器只被调用一次，
用例 `tests/api/test_ocr_submit.py::test_duplicate_submit_yields_one_claimable_task_and_one_handler_call`）。
并**明确写出它弱一步**：不数真 Provider 调用，第 5 组 handler **内部重复调用/重试时本判据抓不到**，
届时 MUST 补真调用计数断言。

**依据核实**：该用例 docstring（`tests/api/test_ocr_submit.py:515-530`）已经有同口径说明
（「字面判据是"Provider 调用次数不增加"，但 M1 的受理路径根本不调 Provider」），
但它此前只存在于被 `.superpowers/sdd/.gitignore` 忽略的目录之外的**代码注释**里、
`tasks.md` 无标注 ⇒ 这次登记正是把它挂到任务条目上。

### 1.3 `4.10`「分级随 AI 输出返回」的端到端 → 缓期至第 5 组

登记要点：`spec.md:58` 要求「分级结果 MUST 随 AI 输出一并返回」，其**端到端**
（真通道 → 真落库 → 轮询返回分级）缓期至第 5 组（`5.6` 结果回执落地后）；
仓库内**已有会自己过期的 in-repo 判据**挂住它：
`tests/api/test_confidence_grading.py::test_m1_has_no_ocr_handler_so_grading_is_not_end_to_end_yet`
（今天断言 `main.py` 仍是 `handlers={}`，第 5 组注入真处理器后**自动变红**并提示补两条端到端断言）。

**依据核实**：`spec.md:58` 原文含「分级阈值 MUST 可按运营数据调整并留痕。分级结果 MUST 随 AI 输出
一并返回」✓；`test_confidence_grading.py:315-334` 断言 `"handlers={}" in main_source` ✓
（该用例是本轮登记的**最佳形态**：不需要任何人记得回来改，到点自己响）。

### 1.4 `4.11`「分别计数」的指标侧 → 缓期至第 11 组

登记要点：本阶段只保证**事实源可分组**（`ai_task` 上
`WHERE status='FAILED' GROUP BY error_code`，用例 `tests/integration/test_failure_codes_mysql.py`）；
**明确写出仓库内确无判据**把"按码计数"挂到指标端点——`tests/unit/test_envelope.py:501`
只管 `/metrics` 的**端点存在性**（且会自过期），**不管**按码计数 ⇒ 第 11 组落地 `11.3` 时
MUST 补「两类码分别 +1」的断言。

**依据核实**：`test_failure_codes_mysql.py:169/216/227` 确实是 `GROUP BY error_code` 形态 ✓；
`tasks.md:110` 的 `11.3` 是 Prometheus 指标条目 ✓。

---

## 2. ② `4.3` 的文档自相矛盾：更正口径（原句保留）

`tasks.md:39`（4.3）写「以假密钥走通『构造请求—超时—熔断—**返回 4003**』链路」，
但同一文件 `4.11` 写「依赖超时 `5002`」，`spec.md:227` 写「依赖调用超时 → `5002`」。

**结论：代码正确、文档错**，已在 4.3 下方加**口径更正行**（不删原句）：

- **超时 / 熔断终码 = `5002`**；`4003` 只留给「等到了失败」（通道确实返回失败）；
- 权威链：`spec.md:227`（依赖调用超时 → `5002`）+ `tasks.md` 的 `4.11`（依赖超时 `5002`）；
- 实现依据：`services/_common/openapi.yaml:208`（`5002 # 依赖超时 / 熔断`）
  与 `services/aicore/docs/er.md:26`（`error_code`：`4003` 通道失败转人工 / `5002` 依赖超时）；
- **MUST NOT** 为此改 `spec.md`（权威源且本身写对）——这一句也写进了登记行。

---

## 3. ③ `4.10`「阈值变更记录可查」→ 按权威文档执行（只报不改代码）

`tasks.md:46` 的措辞「阈值变更记录可查」比权威文档更宽：

| 权威文档 | 原文 | 落地形态 |
|---|---|---|
| `spec.md:58` | 「分级阈值 MUST 可按运营数据调整并**留痕**」 | 每任务当次**阈值快照** |
| `er.md:27`（`model_meta`） | 「模型/Prompt 血缘：通道+供应商+modelVersion+promptVersion+**阈值快照**」 | 同上（`ai_task.model_meta.thresholds`） |

⇒ 条款措辞比权威文档更宽，**按权威文档执行**：快照**满足**「留痕」；
「配置变更日志」不是任何权威文档要求的交付物，**不必为此新增日志机制**。

我在报告之外，也把这一句作为**口径说明**写在了 `tasks.md` 4.10 下方（纯文档、一行）——
理由是：下一个读这条任务的人会问"变更记录在哪"，与其让他去翻报告，不如让答案跟着条款走。
**若控制者认为 ③ 应当只留在报告里，我可以撤掉这一行**（一行删除，不影响其它四处登记）。

---

## 4. 验收

### 4.1 `openspec validate --all --strict`（原始输出）

```
✓ change/add-m1-core-capabilities
✓ change/add-refresh-token-rotation
✓ change/fix-acc-transaction-boundary
✓ change/implement-aicore-service
✓ change/implement-gateway-service
Totals: 5 passed, 0 failed (5 items)
validate exit=0
```

> 原始输出说明：CLI 会把进度行 `- Validating...` 打到 **stderr**，PowerShell 因此把它渲染成
> `NativeCommandError` 记录（`openspec.ps1:16`）。这不是校验失败——**exit code 是 0**，
> 且 stdout 的 5 行 `✓` 与 `Totals: 5 passed, 0 failed` 是 CLI 自己的结论。
> （改动前后各跑一次，输出完全一致。）

### 4.2 任务结构未被改动

```
任务行数（^- [ ]）: 86           ← 改动前后相同
已发生缩进登记行（^  - ）: 9     ← 本轮新增（4.3:1 + 4.8:2 + 4.9:2 + 4.10:2 + 4.11:2）
总行数: 134 → 143
```

⇒ 登记行是**缩进子项**，不是新任务：OpenSpec 的任务计数仍为 86，`--strict` 通过。

### 4.3 工作树状态

```
$ git status --porcelain
 M openspec/changes/implement-aicore-service/tasks.md
?? .sdd-tools.py            ← 不是本轮产物
$ git diff --stat
 openspec/changes/implement-aicore-service/tasks.md | 9 +++++++++
 1 file changed, 9 insertions(+)
```

**纯文档**：`git diff` 里没有任何 `.py` / `yaml` / 代码文件；`spec.md` / `design.md` / `er.md` /
`openapi.yaml` **一字未动**（可用 `git status` 与 `git diff --stat` 直接核）。

---

## 5. 未做清单

1. **未** `git add` / `git commit` / `git stash`；
2. **未**改 `spec.md`（含 `specs/ai-core-service/spec.md`）/ `design.md` / `er.md` / 任何 `openapi.yaml`；
3. **未**改任何代码、测试、配置（本轮 `git diff` 只有一个 `.md`）；
4. **未**新增"配置变更日志"机制（③ 的裁定）；
5. **未**动 `services/aicore/docs/README`（理由见 §0；如需要我可以再补，动之前会先说明）；
6. **未**改 `.superpowers/sdd/` 下的历史报告结论（只在 `task-4.11-fix-report-2.md` 末尾加一节指向本文件）。
