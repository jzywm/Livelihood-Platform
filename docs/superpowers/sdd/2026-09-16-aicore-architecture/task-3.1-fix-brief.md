### Task 3.1-修正：DDL 用例修复 + 真实 MySQL 固化执行（步骤级工单）

**背景**：Task 3.1 的第一轮交付（10 个 DDL + `tests/repository/test_ddl_matches_er.py` 765 行）**DDL 侧干净**，
但**用例侧的解析器有四处实质缺陷**，且工单要求的 Step 2「真实 MySQL 执行」**根本没有执行**
（控制者实测：`aicore` 与 `aicore_test` 两库表数均为 0）。本工单修复这两件事。

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`services/aicore/.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文或反斜杠路径的文件。
**MySQL**：`127.0.0.1:3306`，库 `aicore`（生产结构）/ `aicore_test`（演练）；账号 `aicore_dev` / `Aicore_Dev_2026`（两库均 ALL）。
客户端 `D:\soft\mysql\bin\mysql.exe`；**MUST NOT 手动 `mysqld.exe`**（Windows 服务已在跑，手动实例会抢数据目录）。

---

#### 缺陷 FIX-1：`_iter_er_rows` 未跳过 `er.md` §6.10 辅助结构

**现象**：`ErFormatError: er.md 表 vision_qa_log 的数据行列数不足 6：| 结构 | 类型 | 说明 |`
**根因**：`er.md` §6.10「辅助结构（Redis / MQ / OSS）」的表头是 `| 结构 | 类型 | 说明 |`（3 列），
而 `ER_HEADING_RE` 只匹配 `^###\s+6\.\d+\s+([A-Za-z_]...)` —— §6.10 的标题是
`### 6.10 辅助结构（Redis / MQ / OSS）`，**以中文开头**，故不匹配；于是 `current` 仍停留在 §6.9 的
`vision_qa_log`，§6.10 的三行被当成 §6.9 的数据行 → 列数不足 → 抛错。
**连锁后果**：`parse_er_tables` 抛错 ⇒ 8 个用例（逐列比对、枚举比对、默认值比对、覆盖反向检查…）全部 FAIL，
其中 6 条是**这个同一个根因**。这也解释了第一轮为何没跑通。

**修法（MUST 照此，不要用"再补一条标题正则"的窄修）**：把 §6 的**章节边界**判定与**表头**判定解耦：
在 `_iter_er_rows` 里，用**列标题行**（`字段 / 类型 / 空 / 键 / 默认 / 说明`）作为"本节是数据字典表格"的判据，
而不是用标题文字。具体：

1. 逐行扫描 `er.md`；
2. 遇到 `^###\s+6\.\d+` 形式的标题（**编号前缀即可，不要求后面是 ASCII**）时，
   若**下一批行里的表头**不是 6 列数据字典口径，则把 `current = None`（进入"非数据字典章节"状态），
   直到遇到下一个 `### 6.x` 标题；
3. 处于 `current is None` 状态时，**任何 `|` 行都不参与解析、也不抛错**；
4. 处于数据字典章节时，表头 MUST 恰为 6 列口径；数据行列数不足 6 MUST 抛 `ErFormatError`
   （这条**保留**——它是"解析塌了要报警"的防线，不要为了让 §6.10 过而删掉）。

**验收**：`parse_er_tables()` 返回**恰好 9 张表**且表名集合等于 `ALL_TABLES`；
且对 `er.md` 追加一行 `| 结构 | 类型 | 说明 |` 于 §6.9 之后仍然不炸（非空下限用例已覆盖）。

---

#### 缺陷 FIX-2：中文列注释断言的正则过窄（`[^,\n]*` 撞逗号）

**现象**：`vision_review` 的 `biz_type`（`enum('RAW_MATERIAL','CERTIFICATE',...)`）、
`status`（`enum('AI_PROCESSING',...)`）、`confidence_level`（`enum('HIGH','MEDIUM','LOW')`）、
`confidence`（`decimal(3,2)`）四条匹配失败——但**它们的 DDL 里确实有中文注释**。
**根因**：用例用 `[^,\n]*` 限定"列名到 COMMENT 之间不含逗号与换行"，而这几列的**类型本身含逗号**。
**修法**：取"该列定义片段"必须**跳过括号与引号内部**再找边界——复用文件里已有的
`_split_top_level(body)`（它已经正确处理了括号/引号），用它切出每个**列项**，
再在**列项内**判定 `COMMENT '...中文...'`。
**MUST NOT** 改成"只要有 `COMMENT` 就算过"（那会让"注释是英文"或"注释缺失"漏检）。
**验收**：`vision_review` 全部 13 列中文注释断言通过；且**反向验证**——临时把某列的
`COMMENT '任务状态机'` 改成 `COMMENT 'state machine'`（纯 ASCII），该断言 MUST 变红。反向验证做完把文件按字节还原。

---

#### 缺陷 FIX-3：渲染残留断言把**注释里的 `{}`** 当成占位符

**现象**：`10_ai_task.template.sql` 渲染后残留 `['{channel, provider, modelVersion, promptVersion, thresholds（high/medium）}', '{taskId}']`，
`11_ocr_result.template.sql` 残留 `['{fieldName, value（脱敏）, confidence（0~1）}']`。
**根因**：这两处 `{...}` 是**注释里的 JSON 示例 / 接口路径**，不是占位符；断言在**未剥注释**的文本上找 `{`。
**修法**：断言前先 `strip_sql_comments(...)`（文件里已有该函数），只在**可执行 SQL 部分**找残留占位符。
**MUST NOT** 反过来把注释里的示例花括号改掉——注释是给人看的，为了迁就一条断言而改文档是本末倒置。
**验收**：三个模板渲染后、剥注释后 `{` 计数为 0；且**反向验证**——把 `{month}` 从
`12_ocr_correction.template.sql` 的 `REFERENCES` 行里删掉，该断言 MUST 变红（证明它真的在看 SQL 部分）。还原。

---

#### 缺陷 FIX-4（**设计层，控制者已实证**）：物理外键约束名 MUST 带月份

**已实证的事实**（控制者用 MySQL 8.0.35 实测，证据原文）：
```
ERROR 1826 (HY000) at line 37: Duplicate foreign key constraint name 'fk_ocr_correction_task'
```
**MySQL 的外键约束名在 schema 内唯一**，不是表内唯一。而 `12_ocr_correction.template.sql` 当前把约束名
硬编码为 `fk_ocr_correction_task` → 模板套用到**第二个月**（`ocr_correction_202602`）时必然撞名失败。

**修法**：约束名改为 `` `fk_ocr_correction_task_{month}` ``。
控制者已用修正后的命名在真实 MySQL 上验证通过（两个月的表都建成、各自带自己的 RESTRICT 约束、
非法父行被 1452 拒绝）。**照此改**。

**连带改动**：
- `tests/repository/test_ddl_matches_er.py` 的 `test_correction_template_has_same_month_physical_foreign_key`
  与 `test_ddl_declares_physical_foreign_keys_with_restrict` 里对 `fk_ocr_correction_task` 的期望，
  MUST 同步改为带 `{month}` 的形式；并且 MUST 新增一条断言：
  **三个模板里所有 `CONSTRAINT` 名都必须含 `{month}`**（防止将来又有人在模板里写死约束名）。
- 模板顶部注释里"约束名"的说明同步更新（现在它写的是不带月份的名字）。

**同时登记一处文档冲突（写入报告，不改 `er.md`）**：`er.md` §5.4 L240 说 `ocr_result.task_id` 是
"同月分片路由凭据"、**未标 FK**；而 spec §5.1 明确要求"在模板内声明物理外键"。两份权威文档不一致时，
本任务按 **spec §5.1** 执行（spec 是本次交付的设计权威），并把差异写进报告与 ledger。
**MUST NOT 自行修改 `docs/er.md`**（它是"唯一可手改源"之一，改动属另一条变更流程）。

---

#### 缺陷 FIX-5：Step 2「真实 MySQL 执行」MUST 固化为可复现脚本

第一轮只做了"当时手敲一遍"，仓库里**没有任何可复核的产物**，故无法证明执行过（控制者实测两库皆空）。
**MUST 新增** `scripts/apply_ddl.py`（**入仓库的固化脚本**，不是临时脚本）：

- 输入：`--database`（默认 `aicore`）、`--month`（6 位 YYYYMM）、`--dry-run`（只打印不执行）；
- 行为：读 `deploy/sql/ddl/*.sql`；三个 `.template.sql` 按 `{table}` / `{month}` 渲染；
  **严格按 `ai_task → ocr_result → ocr_correction` 顺序**建分片表（被引用表先建），再建 6 张非分片表；
- **MUST NOT** 自己拼 SQL 语句（只做渲染与顺序编排），SQL 的唯一来源是 `deploy/sql/ddl/**`；
- **MUST** 用 `sqlalchemy` + `pymysql`（已在 `.venv`）执行，**MUST NOT** 在脚本里硬编码口令
  （从环境变量或 `--dsn` 取；默认读 `AICORE_MYSQL_*`），**MUST NOT** 打印口令；
- **MUST** 幂等：`IF NOT EXISTS` 保证复跑零错误，脚本自身不 `DROP` 任何东西；
- 退出码：成功 0、有 SQL 报错非 0。

**MUST 新增用例** `tests/repository/test_apply_ddl_mysql.py`（标记 `@pytest.mark.integration`，默认不跑）：
- 若连不上 MySQL → `pytest.skip("需要真实 MySQL：..."）`（**显式跳过，不是静默通过**）；
- 否则：在 `aicore_test` 上以 `--month` 用**一个专门的演练月**（如 `202607`）执行 → 用
  `information_schema` 断言 9 张表（3 张 `_202607` + 6 张固定名）、4 条外键约束名（含月份后缀）、
  以及 `idx_*` 索引名逐项存在；
- **再执行一次**断言零错误（幂等）；
- 用例末尾 MUST 清理它自己建的 3 张分片演练表（**只 DROP 自己建的 `_202607` 三张**，
  MUST NOT `DROP DATABASE`、MUST NOT 碰固定名表——那可能与别的用例/同事的库冲突）。

**Step 2 的执行记录（MUST 贴原始输出）**：用上面两个产物在 `aicore_test` 上跑一遍，把
`python scripts/apply_ddl.py --database aicore_test --month 202607` 的完整输出、
`information_schema` 核对结果、第二次执行的幂等输出，**原样粘进报告**。
另外**必须在 `aicore` 库也建一次**（`--month` 用当前真实月份，如 `202609`）——`aicore` 是交付环境的真实结构库，
只建在 `aicore_test` 等于没交付。

---

#### 交付物清单

| 文件 | 动作 |
|---|---|
| `tests/repository/test_ddl_matches_er.py` | 修 FIX-1/2/3/4 |
| `deploy/sql/ddl/12_ocr_correction.template.sql` | 修 FIX-4（约束名 + 顶部注释） |
| `scripts/apply_ddl.py` | 新增（FIX-5） |
| `tests/repository/test_apply_ddl_mysql.py` | 新增（FIX-5） |
| `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.1-report.md` | 新增：含全部原始输出 |

**MUST NOT**：改动 9 张表的列定义（DDL 列/类型/可空/默认/索引已实测干净，不要碰）；
改动 `docs/er.md` 或 `docs/openapi.yaml`；`git commit`。

---

**验收（自证，全部贴原始输出）**：
```
.venv\Scripts\python.exe -m pytest tests/repository -q                     # 全部通过（integration 默认 skip）
.venv\Scripts\python.exe -m pytest tests/repository -q -m integration      # 真实 MySQL 用例通过
.venv\Scripts\python.exe scripts\apply_ddl.py --database aicore_test --month 202607   # 贴输出
.venv\Scripts\python.exe scripts\apply_ddl.py --database aicore --month <当前月>       # 贴输出
.venv\Scripts\python.exe -m pytest -q                                      # 全量（原 387 passed / 8 skipped 不得变红）
.venv\Scripts\ruff.exe check . --no-cache
.venv\Scripts\mypy.exe src
.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
```
另 MUST 说明：`ruff` 对 `scripts/` 是否覆盖（pyproject 的 ruff 无 `include` 限制，应覆盖到）；
若 `scripts/apply_ddl.py` 因不在 `src/` 而被 mypy 漏检，**如实说明**，不要假称已检查。

**清理**：删掉 `services/aicore/_tmp_probe.py`、`services/aicore/_diag_ddl.py`（控制者留的诊断脚本）、
`services/aicore/pytest-cache-files-*` 遗留目录；交付时 `git status --short` 只应有本工单的文件。

**报告写入**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-3.1-report.md`
