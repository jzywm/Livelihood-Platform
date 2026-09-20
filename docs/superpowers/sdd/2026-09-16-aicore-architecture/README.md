# AICORE「架构部分」SDD 台账（2026-09-16 起）

> 本目录是 **AICORE 微服务「架构部分」**（`tasks.md` 第 1~4 组）在 **subagent-driven-development**
> 方式下执行时的完整过程记录：**每一步的工单、实现报告、独立评审、以及控制者的逐条裁定与代价**。
>
> **它回答的是「当初为什么这么定、代价是什么、谁验的」** —— 这些问题的答案不在代码里，
> 也不在提交信息里（提交信息只记结论，这里记**过程与证据**）。

## 为什么它被移进受控目录（2026-09-20）

此前它放在 `.superpowers/sdd/`，而那个目录被 `.gitignore` 的 `*` 忽略。独立复核者实测：
**对目录 grep 返回 No matches** ⇒ **仓库内常规检索找不到**。

于是出现了这样一件事：`tasks.md` 的 4.9 与 4.11 把两条验收条款**缓期**到后续组，
登记却只写在这个被忽略的目录里 —— **一条别人找不到的登记，等于没登记。**

⇒ 缓期类登记现已改写进 `openspec/changes/implement-aicore-service/tasks.md` 本身
（跟着任务走的人一定会看到），本目录保留**完整过程**供追溯。

## 阅读顺序（想快速了解的人）

| 想知道什么 | 读什么 |
|---|---|
| **整体怎么走的、每一处裁定与代价** | `progress.md`（**最完整**，2700+ 行，按时间序，含所有 Ruling 与失败记录） |
| 某个任务要求做什么 | `task-<N>-brief.md`（含范围、判据形态、判别力自证要求、纪律） |
| 某个任务实际做成了什么 | `task-<N>-report.md`（含门禁原始输出与"没做到的事"） |
| 独立评审发现了什么 | `review-*.md`（评审者与实现者无共享上下文；`review-group4-closure-checklist.md` 是第 4 组收口的审计清单） |
| 修复轮的追加要求 | `task-<N>-fix-brief*.md` |

## 本套台账里最值得复用的几条（都已写进 `progress.md`）

1. **接受标准 = 一条今天就能红的用例** —— "请实现者给出自证"不作为验收依据：
   自证的成本由被评者自己定。本任务四轮里反复出现"用例在那儿但永远不会红"。
2. **内存变异**：`pytest -p <plugin>` 在**运行期替换模块属性** —— 不碰仓库文件，
   因而没有"改 src + finally 还原"留下的注入风险。用它复核判据的判别力。
3. **判据要键"出处"，不能键"看起来相关的表面特征"** —— 本任务该教训出现**五次**
   （栅栏位置、异常类型 vs 出处、`"skipped" in stdout`、pytest 打印正则的引号风格、
   验证脚本被 here-string 吃掉嵌套引号）。**探针本身也是判据。**
4. **MUST NOT 依赖被测对象自己的常量做期望值**（本仓判例：把常量改成自洽但错误的 35，验收脚本仍全绿）。
5. **假绿会训练人忽略红** —— 随机自跳过、依赖库标点导致的假红，都要消灭。
6. **一处约定若"将来才可能被违反"，就要有机械判据守着**（如"没有任何写回目标是 `MANUAL_REVIEW`"），
   但**判据的边界按语义划、不按字符串划** —— 宽判据会逼后来者加豁免注释，
   **而豁免注释正是约定悄悄失效的入口**。

## 与仓库其它文档的关系

- 计划与设计：`docs/superpowers/plans/2026-09-16-aicore-architecture.md`、
  `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md`
- 任务清单与验收条款：`openspec/changes/implement-aicore-service/tasks.md`（**权威**）
- 决策与理由的事实源：`openspec/changes/implement-aicore-service/design.md`
- 数据模型：`services/aicore/docs/er.md`；接口：`services/aicore/docs/openapi.yaml`
- 开发过程日志（面向"怎么用 AI 做出来"）：`AI_DEV_LOG/`
