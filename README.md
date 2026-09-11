# 民生甄选 · Monorepo

> 民生综合服务平台(监督 + 透明交易 + 民生)的 monorepo 工程仓库。

## 项目简介

民生甄选是面向石家庄市(试点)的民生综合服务平台,围绕三条主线建设:

- **监督**:投诉 / 热线 / 申诉统一工单、监管看板、信用档案与红黑榜、全链路溯源;
- **透明交易**:担保交易、货款第三方托管、价格公示、商品透明详情;
- **民生**:实名账户、用工与劳务信用、工资代付、群众建议与民生项目公开。

## 技术栈与目录

| 目录 | 端 / 域 | 技术栈 | 当前状态 |
|---|---|---|---|
| [`apps/pc`](apps/pc) | PC 桌面端 | React 18 + Vite 5 + Electron 33 + TypeScript 5.6 | 脚手架 |
| [`apps/mobile`](apps/mobile) | 移动端 | uni-app(Vue 3),H5 + 微信小程序 | 脚手架 |
| [`apps/docs`](apps/docs) | 设计规范 | Markdown(设计原则 / 令牌 / 组件 / 响应式 / 工程 / 安全) | 文档 |
| [`services`](services) | 后端 | Java 17 + Spring Boot 3.5 模块化单体 + 网关微服务 GATEWAY(Spring Cloud Gateway);AI 侧 Python 3.12 + FastAPI | 文档基线(代码待开发) |
| [`docs`](docs) | 文档 | 需求调研 / 市场分析 / 设计 / SOP / 规范 | 文档 |

> 说明:后端采用「**模块化单体先聚合,按业务域预留拆分**」策略;AI 能力(`aicore` / `assist`)为独立 Python 服务,经统一鉴权内部接口取数、不直连主站数据库;**网关层为独立微服务 `gateway`(GATEWAY,M1 后期独立部署,平台唯一统一入口)**,前端不直连 Python 服务。

## 目录结构

```text
.
├── apps/                  # 前端应用(pnpm workspace)
│   ├── pc/                #   PC 桌面端(React + Electron)
│   ├── mobile/            #   移动端(uni-app,H5 / 微信小程序)
│   └── docs/              #   设计规范文档
├── services/              # 后端业务域服务(15 个,见下表)
├── docs/                  # 全部文档资产
│   ├── 需求调研/          #   需求调研与核心成果
│   ├── 市场分析/          #   市场分析 / 竞品调研
│   ├── design/            #   产品设计文档 / 架构演进 / 时序图 / 图表
│   ├── sop/               #   生命周期 SOP(阶段 0~4)
│   ├── agent-sdlc-standard/ # 五层门禁(G0~G4)规范 / 清单 / 模板
│   └── ai-presets/        #   AI 角色预设
├── AI_DEV_LOG/            # AI 开发过程日志(按天)
├── PROJECT_LOG/           # 项目生命周期日志(按天)
├── AGENT_MEMORY.md        # 行为规则(执行前先给方案等)
├── DEVELOPMENT_CONSTRAINTS.md # 全局开发约束(MUST / SHOULD)
└── package.json           # 根脚本(pnpm workspace)
```

## 业务域服务(15 个)

| 服务 | 中文名 | 定位 | 技术栈 |
|---|---|---|---|
| [`acc`](services/acc) | 账户服务 | 实名身份底座 + 纯记账簿 | Java |
| [`aicore`](services/aicore) | AI 能力中心服务 | AI 网关底座(模型路由)+ 视觉审核 + OCR + 图像问答 + 风险预测 | Python |
| [`assist`](services/assist) | 助手服务 | 三端复用智能助手侧边栏(脱敏 → 意图 → 动作) | Python |
| [`civic`](services/civic) | 民生互动服务 | 群众建议 / 民生项目公开 / 优质小店推广 / 论坛 | Java |
| [`cred`](services/cred) | 信用档案服务 | 商户 / 人员 / 供应商信用档案与信用分中枢 | Java |
| [`dash`](services/dash) | 监管看板服务 | 三端看板 / 预警双向推送 / 费率公示 | Java |
| [`delivery`](services/delivery) | 配送服务 | 本地配送下单 / 订单状态机 / 调度看板 / 运力管理与轨迹存证 | Java |
| [`emp`](services/emp) | 用工服务 | 用工关系 / 入职年龄核验 / 劳务信用互评 | Java |
| [`gateway`](services/gateway) | 网关服务 | 平台唯一统一入口:路由 / 鉴权 / 限流 / 灰度 / 超时熔断 / traceId / Envelope(M1 后期独立部署) | Java |
| [`prod`](services/prod) | 商品服务 | 商品上架审核 / 选品广场 / 透明详情 | Java |
| [`profile`](services/profile) | 画像服务 | 个人画像 / 画像四权 / 个性化推荐 | Java |
| [`settle`](services/settle) | 结算服务 | 资金结算唯一执行层(只走第三方持牌通道) | Java |
| [`ticket`](services/ticket) | 工单服务 | 投诉 / 热线 / 申诉统一工单内核 | Java |
| [`trace`](services/trace) | 溯源服务 | 供应商核验 / 溯源码 / 扫码验真 | Java |
| [`trade`](services/trade) | 交易服务 | 担保交易 / 货款托管 / 验收退款 / 争议仲裁 | Java |

> 每个业务域当前为**文档基线**(`services/<域>/docs/README.md` 明确功能与质量基线),代码与 `pom.xml` 待 M1 开发落库;网关服务 `gateway` 为接入层基础设施微服务(无业务数据库,职责见其 README)。

## 快速开始

### 前置要求

- Node.js 18+ 与 **pnpm 9.14**(包管理器已通过 `packageManager` 锁定,禁止混用 npm / yarn)
- 后端:**JDK 17 + Maven**(`aicore` / `assist` 需 Python 3.12)

### 前端

```bash
pnpm install

pnpm dev:pc                    # PC Web 开发
pnpm dev:pc:electron           # PC Electron 套壳
pnpm build:pc                  # PC 构建

pnpm dev:mobile                # 移动端 H5
pnpm dev:mobile:mp-weixin      # 移动端微信小程序
pnpm build:mobile              # 移动端 H5 构建
pnpm build:mobile:mp-weixin    # 移动端微信小程序构建
```

### 后端

后端业务域服务当前处于**设计基线 / 文档脚手架**阶段(尚无 `pom.xml` 与 Java 源码),待 M1 起以「模块化单体」落地;网关层为独立微服务 [`gateway`](services/gateway)(Spring Cloud Gateway,M1 后期独立部署)。开发规范与拆分策略见 [`DEVELOPMENT_CONSTRAINTS.md`](DEVELOPMENT_CONSTRAINTS.md) 与 [`docs/design/高并发架构演进设计.md`](docs/design/高并发架构演进设计.md)。

## 开发规范与门禁

- **全局约束**:[`DEVELOPMENT_CONSTRAINTS.md`](DEVELOPMENT_CONSTRAINTS.md)(技术栈版本 / 代码风格 / 测试覆盖率 ≥80% / 提交规范 / 安全红线)。
- **流程门禁**:[`docs/agent-sdlc-standard/`](docs/agent-sdlc-standard)(五层门禁 G0~G4,含 PR 评审、安全评审清单与模板)。
- **提交门禁**:本地 hook(`.githooks/pre-commit`、`.githooks/commit-msg`)+ `commit-check` 技能,任一不过不得提交;提交信息遵循 Conventional Commits(`feat/fix/docs/...`),AI 提交须带 `[AI]` 标记。
- **行为规则**:[`AGENT_MEMORY.md`](AGENT_MEMORY.md)(执行前先给方案、收工总结等)。

## 文档导航

| 文档 | 说明 |
|---|---|
| [`docs/需求调研/`](docs/需求调研) | 需求调研素材与核心成果 |
| [`docs/市场分析/`](docs/市场分析) | 市场分析报告、竞品功能与核验调研 |
| [`docs/design/产品设计文档.md`](docs/design/产品设计文档.md) | 产品设计文档(PDD) |
| [`docs/design/高并发架构演进设计.md`](docs/design/高并发架构演进设计.md) | 架构演进设计 |
| [`docs/design/时序图.md`](docs/design/时序图.md) | 关键流程时序图 |
| [`docs/sop/`](docs/sop) | 生命周期 SOP(阶段 0~4) |
| [`docs/agent-sdlc-standard/`](docs/agent-sdlc-standard) | AI SDLC 规范、清单与模板 |
| [`apps/docs/`](apps/docs) | 前端设计规范(设计原则 / 令牌 / 组件等) |

## 过程日志与记忆

- [`AI_DEV_LOG/`](AI_DEV_LOG):AI 开发全过程日志(按天,含会话索引)。
- [`PROJECT_LOG/`](PROJECT_LOG):项目生命周期日志(按天,七阶段看板)。
- [`AGENT_MEMORY.md`](AGENT_MEMORY.md):长期行为规则,直接编辑即可改行为。

## 目录约定

- `apps/*` —— 前端应用(pnpm workspace);`.npm-cache*/`、`.downloads/`、`.dsh/` 为工具 / 环境目录,不纳入业务工程。
- `services/*` —— 后端业务域服务(模块化单体按域拆分)。
- `docs/*` —— 全部文档资产(需求 / 市场 / 设计 / SOP / 规范)。
- 根目录 `AI_DEV_LOG/`、`PROJECT_LOG/`、`AGENT_MEMORY.md`、`DEVELOPMENT_CONSTRAINTS.md` —— 过程日志与规则(技能硬读根路径,固定保留)。
