# 全局开发约束规范

> 本文件约束本仓库(民生甄选 monorepo)的**全部开发工作**。
> 分级:**MUST** = 强制红线,违反即返工 / 阻断;**SHOULD** = 默认遵循,可说明理由偏离。
> 详细流程、门禁与清单见 `docs/agent-sdlc-standard/`(五层门禁 G0–G4)与 `docs/sop/`,本文档不重复,只保留"每次开发都需遵守"的核心约束。

## 0. 总则

- MUST:开发工作同时受本文件与根目录 `AGENT_MEMORY.md` 约束;两者冲突时,以 `AGENT_MEMORY.md` 的行为规则为准。
- 每条约束用 MUST / SHOULD 标注;偏离 SHOULD 时,需在 PR 描述或相关文档中说明理由。

## 1. 技术栈与版本

- MUST:PC 端 React 18 + Vite 5 + Electron 33 + TypeScript 5.6;移动端 uni-app(Vue 3,`@dcloudio/*` 锁定 `package.json` 内版本);后端 Java 17 + Spring Boot 3.5 + Maven(先单聚合 `server`,按业务域预留拆分)。
- MUST:包管理器统一 pnpm 9.14(`packageManager` 字段已锁定),禁止混用 npm / yarn;`pnpm-lock.yaml` 必须入库。
- MUST:依赖版本锁定入库,不随意升级大版本;大版本 / 破坏性升级须走评审(对齐 G2 / G3 门禁)。

## 2. 代码风格 / Lint

- MUST:遵循根目录 `.editorconfig`(UTF-8、LF、末尾换行、去行尾空格、2 空格缩进;Java / XML / YAML 4 空格)。
- MUST:TypeScript 保持 `strict` 及 `noUnusedLocals` / `noUnusedParameters` / `noFallthroughCasesInSwitch`,禁止降级关闭。
- 命名(标识符一律英文):
  - TS / JS:变量与函数 camelCase,组件与类 PascalCase,常量 UPPER_SNAKE_CASE。
  - Java:遵循《阿里巴巴 Java 开发手册》。
- 注释与文档使用中文,代码标识符使用英文。
- SHOULD:逐步引入 ESLint + Prettier 统一风格(当前缺失,列为技术债,随开发补齐)。

## 3. 测试要求

- MUST:新代码单元测试覆盖率 ≥80%(行 / 函数 / 分支,对齐 `agent-sdlc-standard` SLO)。
- MUST:关键业务逻辑、安全相关逻辑必须有测试,不得以"赶进度"为由省略。
- SHOULD:PC 端用 Vitest、移动端用 uni-automator、后端用 JUnit 5;测试框架当前前端缺失,随开发逐步引入。

## 4. Git 提交 / 分支

- MUST:遵循 `docs/agent-sdlc-standard/docs/01-开发与Git规范.md`;`main` 分支受保护,提交前过 G0(格式 / 密钥扫描)。
- 提交信息:Conventional Commits,type 英文 + 描述中文。type 集合:feat / fix / docs / style / refactor / perf / test / chore。示例:`feat: 新增商品比价`、`fix: 修复登录超时`。Agent / AI 提交须在 subject 前打 `[AI]` 标记(标准 01 §2)。
- 分支命名(带工单号,以标准 01 为准):`feature/<ticket>-<slug>`、`fix/<ticket>-<slug>`、`release/<version>`。
- MUST:提交前必须通过本地门禁(`.githooks/pre-commit`、`.githooks/commit-msg`)与 AI 提交检查技能 `commit-check`,任一不过不得提交;`--no-verify` 不得作为绕过手段(真正兜底由 CI G2 复验)。

## 5. 代码评审

- MUST:PR 至少 1 人评审 + 门禁全绿方可合并(对齐 G2 / G3);安全负责人经 CODEOWNERS 指定。
- SHOULD:评审响应 ≤24h(工作日);评审时按 `checklists/PR评审Checklist.md`、`checklists/安全评审Checklist.md` 逐项勾选。

## 6. 安全(MUST 红线)

- 密钥 / 凭据绝不入库:G0(Gitleaks)拦截 + G2 复验,泄露事件目标为 0。
- 不硬编码密钥 / 密码,用环境变量(根 `.gitignore` 已忽略 `.env*`),并提交 `.env.example` 模板。
- 输入校验、防注入(SQL / XSS)、防越权,对齐 OWASP;依赖高危漏洞立即升级(CRITICAL ≤24h,HIGH ≤7d)。

## 7. 性能

- SHOULD:前端按需懒加载、控制打包体积、避免无谓 re-render。
- SHOULD:后端避免 N+1 查询、合理使用缓存与连接池、接口做分页 / 限流。

## 8. 文档 / 日志

- MUST:需求 / 设计变更同步更新 `docs/`(产品设计文档、时序图等)。
- MUST:开发过程按 `ai-dev-log`、`project-log` 技能记录,收工时完成当天总结。
- SHOULD:README / 接口文档保持最新。
- SHOULD:后端结构化日志分级(ERROR / WARN / INFO / DEBUG),不记录密码、令牌、身份证号等敏感信息。

---

*创建:2026-09-06 · 落地方式:独立文件 + 记忆指针(`AGENT_MEMORY.md` 规则四)*
