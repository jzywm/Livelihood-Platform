### Task 3.8: 前缀化 ID（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件。

**Files:**
- Modify: `src/aicore/core/idgen.py`
- Create: `tests/unit/test_idgen.py`

**权威依据（MUST 先读）**：
- spec **§2.3**（ID 形态：`前缀 + UUID`，**均为 `varchar(32)`**；ID 前缀 6 种）、**§5.8**（格式 `前缀 + UUID 去连字符后的 hex`，**总长必须 ≤32**，裸 UUID 36 字符**超限 4 位**，生成时校验、超限抛错而非静默截断）
- `services/aicore/docs/er.md` **§5.4 L239–L248**（各表 ID 的生成方式与"**Python 侧不参与雪花域**、无 workerId、无时钟回拨风险面"）
- `deploy/sql/ddl/*.sql`（所有 ID 列均为 `varchar(32)`）

---

#### 交付接口

```python
ID_PREFIXES: dict[str, str]        # 6 种：task/cor/rev/marker/kan/qa
def new_id(kind: str) -> str
def validate_id(value: str, kind: str | None = None) -> bool
```

**6 个前缀 MUST 逐字来自 `er.md` §5.4，含下划线**：

| `kind` | 前缀 | 对应 ID 列 |
|---|---|---|
| `task` | `task_` | `ai_task.task_id` / `ocr_result.task_id` |
| `cor` | `cor_` | `ocr_correction.correction_id` |
| `rev` | `rev_` | `vision_review.review_id` / `review_verdict.review_id` |
| `marker` | `marker_` | `vision_marker.marker_id` |
| `kan` | `kan_` | `kitchen_anomaly.anomaly_id` |
| `qa` | `qa_` | `vision_qa_log.qa_id` |

**`risk_predict_result.merchant_id` 不在本表**：`er.md` §5.4 L244 明写"**源服务生成，只读引用，不重新发号**"。
故 `new_id("merchant")` MUST 抛错，**MUST NOT** 给它造一个前缀。

**ID 形态（MUST 照此，这是本项最容易写错的地方）**：
`前缀 + UUID4 的 hex（去连字符）` = `task_` (5) + 32 = **37 字符 —— 超限**。
所以**MUST 用 `uuid4().hex` 的截断或"%030x"式缩位**？**不** —— 见下：

**正确的缩位方式（MUST 照此实现，理由必须写进 docstring）**：
`prefix + uuid4().hex[: N ]`，其中 `N = MAX_ID_LENGTH - len(prefix)`（`MAX_ID_LENGTH = 32`）。
逐前缀的实际长度（MUST 在实现里由常量算出，**MUST NOT 把 32/27 之类字面量散落在函数体**）：

| 前缀 | 长度 | UUID hex 取多少位 | 总长 |
|---|---|---|---|
| `task_` | 5 | 27 | 32 |
| `cor_` | 4 | 28 | 32 |
| `rev_` | 4 | 28 | 32 |
| `qa_` | 3 | 29 | 32 |
| `kan_` | 4 | 28 | 32 |
| `marker_` | 7 | 25 | 32 |

**为什么截断 UUID 是安全的（必须写进 docstring，否则后人会以为这是权宜之计）**：
UUID4 有 122 位随机性；截到 25~29 个 hex 字符（100~116 位）后，
**生日界下碰撞概率仍远低于同月分片表的容量上限**（`er.md` §5.2：单表 >2000 万行触发再分），
且 ID 的**唯一性最终由数据库主键约束兜底**——截断带来的风险是"概率极低的主键冲突"，
而超长带来的风险是**每一行都写不进去**。两害相权，截断 + 数据库兜底是对的。
**但**：`new_id` MUST 在生成后**自校验 `len(id) <= 32` 且 `validate_id(id, kind)` 为真**，
不满足即抛 `ValueError`（**MUST NOT 静默返回超长串**）——这条自校验是"常量写错时立刻炸"的保险。

**`validate_id(value, kind=None)` 语义（MUST 精确）**：
- `kind` 给出时：必须匹配该 kind 的前缀，且**总长恰好等于该前缀下的最大长度**？→ **不**：
  用"长度在 `len(prefix)+1 .. 32` 之间"**过宽**（会把截断错误的串放过）。
  正确口径：**长度恰好 = `MAX_ID_LENGTH`**（因为 `new_id` 恒生成满 32 位），
  且前缀匹配、余下部分为**小写 hex**、非空。
- `kind=None` 时：只需匹配**任一**已知前缀且满足上面的长度/字符规则。
- 未知 `kind` 传入 `new_id` / `validate_id` MUST 抛 `ValueError`（fail fast，与 `AiCoreError` 的构造期校验同取向）。

**MUST NOT**：引入雪花 ID、workerId、时间戳内嵌、或任何"看起来像分布式 ID"的方案
（`er.md` §5.4 L247 + spec §2.3 双重明示 AICORE 不参与雪花域）。
MUST NOT 依赖 `uuid1`（含 MAC/时间，PII 与可预测性风险）。

---

#### 用例 `tests/unit/test_idgen.py`

1. **6 种前缀各生成一次**：断言前缀正确、`len(id) == 32`、`validate_id(id, kind) is True`；
   并断言 `ID_PREFIXES` 恰好 6 项、键集合为 6 个 kind。
2. **1 万个 ID 全过正则且无重复**（spec §5.8 明确要求）：
   用 `concurrent.futures.ThreadPoolExecutor`（**多线程**，"并发生成"不能是串行循环）
   生成 `10_000` 个 ID → 断言 `len(set(ids)) == len(ids)`（无重复）、
   **每一个**都通过 `validate_id(id, kind)`、且**每一个** `len(id) <= 32`。
   正则 MUST 从 `ID_PREFIXES` 现算，MUST NOT 把 `task_[0-9a-f]{27}` 这类写完的常数抄进用例
   （抄了就等于把"长度算对"这件事验两遍，还验不出两边一起错）。
3. **`merchant` 不在前缀表**：`new_id("merchant")` 抛 `ValueError`；`ID_PREFIXES` 不含 `merchant`。
4. **反例**：`validate_id("task_" + "0"*27, "cor")` 为 `False`（前缀不符）；
   `validate_id("task_" + "0"*26)` 为 `False`（长度不足）；
   `validate_id("task_" + "Z"*27)` 为 `False`（非 hex）；
   `validate_id("")` 为 `False`；`validate_id("task_" + "0"*27, "nope")` 抛 `ValueError`。
5. **自校验保险真的在**：`monkeypatch` 把 `MAX_ID_LENGTH` 改小（如 10），
   断言 `new_id("marker")` **抛 `ValueError`**（证明"超限即抛"不是空话）。
   **这条是本工单的核心负向证据**，MUST 有。
6. **不引入雪花/时间戳**：断言生成的 ID 里**不含**任何十进制时间戳样式子串？
   → 这条不可靠，**改成源码级断言**：断言 `idgen.py` 源码不含 `worker`, `snowflake`,
   `time.time`, `uuid1` 等标识（用 AST 或子串检查），并说明这是"防回归"的弱断言、真正的保证在评审。

---

#### 验收（自证，全部贴原始输出）

```
.venv\Scripts\python.exe -m pytest tests/unit/test_idgen.py -q
.venv\Scripts\python.exe -m pytest -q                       # 全量基线不得变红
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src                                  # strict
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
- `core` 层 MUST NOT import 任何业务层（契约 4）——`idgen.py` 只允许 stdlib。
- **MUST NOT `git commit`**；报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.8-report.md`，
  含原始输出（1 万 ID 用例要贴真实计数与耗时）、逐项验收结论、**偏离项 + 理由**、**没做到的事**。
