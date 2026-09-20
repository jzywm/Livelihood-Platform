# Task 3.1 交付报告（DDL + 真实 MySQL 落地）

**日期**：2026-09-18 ｜ **worktree**：`.worktrees/aicore-architecture`（分支 `feature/aicore-architecture`）

## 0. 执行过程（如实登记，含两次实现者交接）

| 阶段 | 执行者 | 结果 |
|---|---|---|
| 第一轮 | subagent `b158a9e3`（被控制者中断） | 10 个 DDL + 用例 765 行。**列定义经控制者实测干净**；用例侧有 4 处解析器缺陷；**Step 2「真实 MySQL 执行」未执行**（两库表数均为 0） |
| 修正轮（FIX-1~5） | subagent `73c4c5e6`（被控制者中断） | 已修 FIX-4（约束名带月份）；FIX-1 的解耦思路正确；生产了自己也修不完的中间态（`tests/repository` 17 红） |
| 收尾与验证 | **控制者亲自执行** | 修完剩余缺陷 → 真实 MySQL 落地 → 全部门禁转绿 |

**为什么中断两次**：两个实现者都进入了"反复写探查脚本、不交付产物"的循环（分别产出 6 个 `_probe_recon*.py`）。
控制者接管比继续等更省。**这是流程教训**：探针数量应设上限（本任务后加：同一任务探针 >2 个即要求先写产物）。

## 1. 交付物

| 路径 | 说明 |
|---|---|
| `deploy/sql/ddl/00_create_database.sql` | 建库 `aicore` + `aicore_test` |
| `deploy/sql/ddl/10_ai_task.template.sql` | 分片表模板（`{table}` / `{month}`） |
| `deploy/sql/ddl/11_ocr_result.template.sql` | 同上 |
| `deploy/sql/ddl/12_ocr_correction.template.sql` | 同上 + **同月物理外键**，约束名带 `{month}` |
| `deploy/sql/ddl/20~25_*.sql` | 6 张非分片表 |
| `scripts/apply_ddl.py` | **固化建表路径**（渲染 + 顺序编排 + 真实执行） |
| `tests/repository/test_ddl_matches_er.py` | 离线三方比对（`er.md` / DDL / `openapi.yaml`） |
| `tests/repository/test_apply_ddl_mysql.py` | 真实 MySQL 集成用例（5 条，默认不跑） |
| `tests/repository/__init__.py` | 测试包 |

## 2. 修掉的缺陷（逐个附证据）

### FIX-1 `er.md` §6.10 解析（用例 bug，连带 6 条用例红）
`_iter_er_rows` 用标题文字圈章节，而 §6.10 标题以中文开头 → `current` 停在 `vision_qa_log` → 三列辅助结构表被当数据行。
**修法**：章节边界与表头判定解耦——**只认 6 列表头**决定"本节算不算数据字典"，不认标题文字。

### FIX-2 中文列注释断言（用例 bug）
`[^,\n]*` 被列定义里的逗号撞死（`enum('A','B')` / `decimal(3,2)`）。
**修法**：复用 `_split_top_level`（已正确处理括号与引号）切出列项后再在项内找 `COMMENT '...中文...'`。

### FIX-3 渲染残留断言（用例 bug）
残留的 `{...}` 全在**注释里的 JSON 示例**（`{channel, provider, ...}`、`{taskId}`）。
**修法**：先 `strip_sql_comments` 再 `strip_sql_string_literals` 掏空字面量，只对**可执行骨架**发问。

### FIX-4 外键约束名（**设计缺陷，控制者实证**）
```
ERROR 1826 (HY000): Duplicate foreign key constraint name 'fk_ocr_correction_task'
```
**MySQL 外键约束名在 schema 内唯一**，模板套到第二个月必撞名。
**修法**：约束名改为 `fk_ocr_correction_task_{month}`；并加防回归用例
（`test_ddl_constraint_names_all_carry_month`：三个模板里**所有** `CONSTRAINT` 名都必须含 `{month}`）。

### FIX-5 真实执行未固化（工单要求未完成）
新增 `scripts/apply_ddl.py` + 5 条集成用例。

### 控制者收尾时修的两处（**我自己的 bug，登记**）
1. **`_normalize_type` 把枚举也小写了**：`er.md` 的 `enum('VALID',...)` 被整体 `.lower()` → 期望值变 `('valid',...)`
   → 11 个枚举列全报不一致。**修法**：括号感知扫描，**只小写括号外的类型名**，括号内参数保原样
   （类型名大小写不敏感，而枚举值是字符串字面量、大小写敏感）。用显式扫描而非正则，因为枚举值里可能出现 `)`。
2. **渲染账算不平的反向自检写成了恒假断言**：`set(渲染后) == set(源)` 永远不成立（`{table}`/`{month}` 渲染后本就该消失）。
   **修法**：改成**精确核算**——源花括号 token 数减渲染后数，必须恰好等于 `count({table}) + count({month})`；
   并额外断言"源里除这两个占位符之外的示例花括号，渲染后逐个还在"。

### 集成用例里暴露的两处（真连库才看得见）
3. **清理顺序错**：按建表顺序 DROP，而 `ocr_correction` 有外键指向 `ocr_result` →
   `ERROR 3730 Cannot drop table ... referenced by a foreign key constraint`。**改为逆序**。
4. **集成测试变量名侵入应用配置命名空间**：初版用 `AICORE_TEST_MYSQL_*`，
   撞上 `core/config.py` 的 `_UnknownEnvVarSource`（**它拒绝任何未声明的 `AICORE_*` 变量，这是 Task 2.1 的正确防线**）
   → 全量套件 35 failed / 63 errors，阻断项正是这 5 个变量名。
   **修法**：改用独立前缀 `DSH_IT_MYSQL_*`。
   **这不是防线太严，是我的命名错了** —— 记录在此以免后人误判。

## 3. 真实 MySQL 落地证据（原始输出）

### 3.1 `apply_ddl.py --database aicore_test --month 202607`
```
[INFO] 目标库 = aicore_test ｜ 分片月 = 202607 ｜ 语句数 = 9
[INFO] 连接目标 = mysql+pymysql://aicore_dev:***@127.0.0.1:3306/aicore_test?charset=utf8mb4
  [OK] 10_ai_task.template.sql -> ai_task_202607
  [OK] 11_ocr_result.template.sql -> ocr_result_202607
  [OK] 12_ocr_correction.template.sql -> ocr_correction_202607
  [OK] 20_vision_review.sql
  [OK] 21_vision_marker.sql
  [OK] 22_review_verdict.sql
  [OK] 23_kitchen_anomaly.sql
  [OK] 24_risk_predict_result.sql
  [OK] 25_vision_qa_log.sql
[DONE] 9 条语句执行完毕（全部 CREATE TABLE IF NOT EXISTS，可安全复跑）
```
第二次执行同样 0 错误（**幂等**）。同理在 **`aicore`** 库以真实当前月 `202609` 执行成功。

### 3.2 `information_schema` 逐项核对（两库，总不符数 = 0）
```
--- aicore_test（月 202607）---
[1] 表清单（9 张）：ai_task_202607 / ocr_correction_202607 / ocr_result_202607
                   + kitchen_anomaly / review_verdict / risk_predict_result
                   / vision_marker / vision_qa_log / vision_review
    期望 9 张；缺失 无；多余 无
[2] 物理外键（4 条，全部 DELETE=RESTRICT UPDATE=RESTRICT）
    fk_kitchen_anomaly_review     kitchen_anomaly      -> vision_review
    fk_ocr_correction_task_202607 ocr_correction_202607 -> ocr_result_202607   <- 同月
    fk_review_verdict_review      review_verdict       -> vision_review
    fk_vision_marker_review       vision_marker        -> vision_review
[3] 索引逐个核对（er.md §7）：9 张表全部 [OK]（含 idx_eval / idx_field_corrected
    / idx_stream_detected / uk_idem 等）
--- aicore（月 202609）---  同上，全部通过
总不符数 = 0
```

## 4. 全部门禁（原始输出）

```
--- ruff ---          All checks passed!
--- mypy ---          Success: no issues found in 51 source files
--- lint-imports ---  Contracts: 4 kept, 0 broken.
--- full suite ---    453 passed, 8 skipped in 19.99s      （进入本任务前基线：387 passed / 8 skipped）
--- integration ---   5 passed（真连 MySQL）
--- coverage ---      TOTAL 494 17 97% ｜ Required 80.0% reached. Total 96.56%
--- 残留 ---          无 `_*` 临时文件
```

## 5. 顺手解决的两件事

1. **`ruff` 的 E501 按视觉宽度计**（东亚宽字符算 2 列），而 `ruff format` 按字符数折行 —— 两者对中文注释**天然打架**。
   实测：60 字符的行被报 "110 > 100"。本任务按"字符↔宽度差"逐个收窄了 6 行，并把 `？−×` 三个符号
   按仓库既定的**逐个放行**方式加进 `allowed-confusables`（不动规则本身）。
   **遗留**：这是仓库级缺口，后续任务写长中文断言消息会反复踩到；建议最终评审时决定是否引入宽度感知的格式化方案。
2. `pyproject.toml` 的 `allowed-confusables` 现为 10 项（原 7 项）。

## 6. 偏离与未验证项（诚实清单）

| 项 | 状态 |
|---|---|
| `er.md` §5.4 L240 说 `ocr_result.task_id` 未标 FK；spec §5.1 要求建物理外键 | **按 spec 执行**（建了）。冲突已登记在 ledger，`docs/er.md` 未改（它是"唯一可手改源"，改动需另走变更流程） |
| `scripts/apply_ddl.py` 是否被 mypy 覆盖 | **未覆盖**。`mypy` 的 `files = ["src"]`，脚本在 `scripts/` 下。已加完整类型标注，但**没有工具强制** |
| `apply_ddl.py` 是否被 import-linter 覆盖 | **未覆盖**（不在 `src/aicore` 包内）。已限制它只 import stdlib + `sqlalchemy` |
| 建库路径（`00_create_database.sql`） | **未在真实库上验证执行**：`aicore_dev` 无建库权限（实测 ERROR 1044）。两库由 root 预先建好；该文件只有离线文本断言（`CREATE DATABASE IF NOT EXISTS` × 2） |
| 定时/自动建下月表 | **未做**（Task 3.3 的 `ensure_month_tables` 承接） |
| 探针约束（新增流程约定） | 同一任务探针 >2 个即要求先交付产物 —— 本次两个实现者均违反，已登记为教训 |
