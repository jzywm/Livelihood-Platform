# 民生甄选 · Monorepo

民生综合服务平台(监督 + 透明交易 + 民生)的 monorepo 工程仓库。

## 技术栈与目录

| 目录 | 端 | 技术栈 |
|---|---|---|
| [`apps/pc`](apps/pc) | PC 桌面端 | React 18 + Vite + Electron |
| [`apps/mobile`](apps/mobile) | 移动端 | uni-app(Vue 3 + Vite) |
| [`services`](services) | 后端 | Java 17 + Spring Boot 3.5 微服务(先单聚合) |
| [`docs`](docs) | 文档 | 需求调研 / 市场分析 / 设计 / SOP / 规范 |

## 快速开始

### 前端(需 pnpm)

```bash
pnpm install
pnpm dev:pc              # PC Web 开发
pnpm dev:pc:electron     # PC Electron 套壳
pnpm dev:mobile          # 移动端 H5
```

### 后端(需 JDK 17 + Maven)

```bash
cd services
mvn -pl server spring-boot:run    # http://localhost:8080
```

## 目录约定

- `apps/*` —— 前端应用(pnpm workspace)
- `services/*` —— 后端微服务(Maven 多模块;先单聚合服务 `server`,按业务域预留拆分)
- `docs/*` —— 全部文档资产(需求调研 / 市场分析 / 设计 / SOP / 规范)
- 根目录 `AI_DEV_LOG/`、`PROJECT_LOG/`、`AGENT_MEMORY.md` —— 过程日志与行为规则(技能硬读根路径,固定保留)
- `.downloads/`、`.dsh/`、`.npm-cache*/` —— 工具 / 环境目录,不纳入业务工程
