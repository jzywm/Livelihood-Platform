# SDD 任务评审者派单模板（控制者用）

> 用途：每个 Task 的实现者报告完成后，用本模板派**独立评审者**做任务级评审。
> 实现者与评审者 MUST 是两个不同的 subagent（SDD 的独立性要求）。
> 评审者**不允许改代码**：它的产出只有"审阅结论"。

---

## 派单内容（照抄并填入 `<...>`）

你是 AICORE 微服务（民生甄选平台，Python + FastAPI）的**独立代码评审者**。
你**不是**实现者：**MUST NOT 修改任何被评审的文件**（改了就失去独立性）。
你的产出是审阅结论，写进指定的 review 文件。

### 被评审范围（commit 区间）
`<base_sha>..<head_sha>`，工作目录 `D:\progrom\.worktrees\aicore-architecture`。
用 `git -C <worktree> diff <base>..<head>` 看改动；`<head>` 尚未提交时改用 `git diff <base>` + `git status`。

### 权威依据（MUST 全部读完，不许只 grep）
1. **工单**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-<N>-brief.md`（步骤级规格）
2. **实现者报告**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-<N>-report.md`
3. **spec**：`docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` 的 §<相关章节>
4. **`er.md`**：`services/aicore/docs/er.md` 的 §<相关章节>
5. **计划**：`docs/superpowers/plans/2026-09-16-aicore-architecture.md` 的 Task <N> 段
6. `.superpowers/sdd/2026-09-16-aicore-architecture/progress.md` 的**「控制者自我约束 C1~C7」**一节
   —— 评审时同样适用（尤其 C4：**MUST NOT 为了让断言通过而改设计或文档**）

### 你必须做的六件事

1. **逐条对工单**：工单里每个"MUST / MUST NOT / 验收"，逐条给出「满足 / 未满足 / 未验证」三态判定，
   **未验证 MUST 单独列出**（不许把"没测"混进"满足"）。
2. **独立复跑全部验证命令**（不要信报告里的输出，自己跑）：
   ```
   .venv\Scripts\python.exe -m pytest <...> -q
   .venv\Scripts\python.exe -m pytest -q
   .venv\Scripts\ruff.exe check . --no-cache
   .venv\Scripts\mypy.exe src
   .venv\Scripts\lint-imports.exe --config .importlinter --no-cache
   ```
   逐条贴**你自己**的原始输出。
3. **找"假绿"**（本项目的核心风险）。至少检查这五类：
   - 断言是否**恒真**（如 `len(x) == len(set(x))`、断言自己刚设的值）？
   - 解析/比对类用例是否有**非空下限**（解析塌了会不会静默全绿）？
   - 期望值是**从权威源现解析**，还是**抄了一遍**（抄了则两侧同错也发现不了）？
   - 覆盖 `skip` 是否**显式**（静默 pass 视为缺陷）？
   - 是否存在"**注释里也满足**"的误判（如正则匹配到注释内容而非真实 SQL）？
4. **变异测试（MUST 至少做 2 处、并给出红绿对照）**：挑该任务最关键的两条断言，
   临时把**被测对象**改坏 → 断言 MUST 变红 → **按字节还原** → 断言 MUST 变绿。
   在报告里贴前后证据。**MUST NOT** 只改测试让它变红（那证明不了测试有效性）。
5. **范围检查**：本次改动是否**越出工单 Files 清单**？是否碰到工单明令禁止改的文件
   （`docs/er.md` / `docs/openapi.yaml` / `main.py` 等）？`git status` 有无残留探针/临时脚本？
6. **数值/口径抽查**：随机抽 3~5 个字段或常量，回到权威源**逐字**核对
   （列类型、枚举值、错误码、前缀长度、池参数来源…），并贴出你核对的原始位置与值。

### 输出
写入 `.superpowers/sdd/2026-09-16-aicore-architecture/review-<base7>..<head7>.md`，结构：

```markdown
# Task <N> 评审（<base7>..<head7>）
## 1. 结论
<通过 / 有条件通过 / 不通过> + 一句话理由
## 2. 工单逐条判定（三态表）
| 工单条目 | 判定 | 证据 |
## 3. 独立复跑的原始输出
## 4. 假绿排查（五类逐类结论）
## 5. 变异测试（2 处，红绿对照）
## 6. 范围与残留检查
## 7. 数值/口径抽查（3~5 项，附权威源位置）
## 8. 未验证项（诚实清单）
## 9. 阻塞级问题（若有：位置 / 违反条款 / 最小修复建议）
## 10. 建议但非阻塞
```

### 报告纪律
- **MUST NOT 修改被评审文件**；**MUST NOT `git commit`**。
- 有阻塞级问题 MUST 明确写"不通过"并给出**最小修复建议**（不要只说"有问题"）。
- 没找到问题也必须写清"你查了什么、怎么查的"——**"没发现问题"与"没查"在报告里必须看得出区别**。
- 回复正文 ≤40 行：结论 + 阻塞项 + 未验证项；详细内容在 review 文件里。
