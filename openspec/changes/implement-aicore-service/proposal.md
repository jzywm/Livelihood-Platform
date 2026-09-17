# implement-aicore-service

## Why

AICORE 是平台 AI 能力的唯一底座，但 `services/aicore/` 当前**仅有 4 份文档**（README / openapi.yaml / er.md / apifox 产物）、**零代码**：无 `pyproject.toml`、无 `Dockerfile`、无任何 Python 源文件。证照 OCR（K-01）是 M1 验收项 **AC-M1.11**（「OCR 结果可追溯」），AI 网关底座（K-02）是 K3~K6 全部能力的公共前置，且 PROFILE 的 M1 习惯计算链路（`add-m1-core-capabilities` 任务 6.9/6.10、7.7）**依赖 `POST /aicore/habit/summarize` 真实可用**。GATEWAY 侧已为 AICORE 预留路由与限流档位（`application.yml` 中 `id: aicore` → `http://localhost:8083`、`Tier.AI` 10 次/分/账号），但路由处于注释状态、后端无服务可转发。本变更把 AICORE 从「只有文档基线」落为**可运行的 M1 服务**：AI 网关底座 + 证照 OCR + 合规与成本护栏 + 习惯无状态计算。

## What Changes

- **新增 `services/aicore/` Python 工程**（Python 3.12 + FastAPI）：分层结构（api / service / provider / repository / core）、`pyproject.toml`、`deploy/Dockerfile`、配置多环境（dev/test/prod，密钥仅走环境变量或 KMS，禁写库）。
- **AI 网关与治理底座（K-02）**：统一模型路由（文本 / 视觉云 / OCR / 自建预测四通道）、服务端间内部 Token 鉴权 + 越权 2002、Redis 令牌桶限流、异步任务队列（受理即返回 `taskId` + 幂等 + 进度回执）、置信度分级（高 ≥0.9 / 中 0.7~0.9 / 低 <0.7，初值可调）、全链路审计（模型与 Prompt 血缘）、通道失败降级不阻塞核心业务。**服务端间的习惯计算不走异步任务队列**——按同步无副作用调用返回（不落 `ai_task`，理由见 `design.md` 接口分类）。
- **证照 OCR 自动核验（K-01）**：`POST /aicore/ocr` 提取字段并比对有效期与经营类目，`GET /aicore/tasks/{taskId}` 轮询结果；结果仅作预审、人工核验兜底；识别失败或图像模糊转人工、提示重传。
- **合规护栏（R-05 / R-03 / C8）**：图像脱敏前置（去人脸 / 车牌）后方可调用云视觉 API；云视觉处于数据合规协议之下（不用于训练、数据不出域）；**权威数据回写（CRED 档案 / 信用分、DASH 预警）以存在人工复核结论为前提，AI 输出不得直接触发**；回写带事件标识支持幂等与每日对账。
- **准确率提升闭环**【M1 起】：人工核验字段级纠错回流（`ocr_correction`，一行一字段：AI 原值 / 人工真值 / 当时置信度）、固定评估集（`ai_task.is_eval_sample`）改动前后回归、未标记样本 1%~5% 抽样复核以发现漏检（人工复核发现不了漏报）。
- **成本三层护栏**【M1 起】：单账号日配额（超限业务码 `2004`）→ 全局日预算（80% 告警 / 100% 降级人工复核）→ 按调用方成本归因。
- **习惯与购买影响因素无状态计算**：`POST /aicore/habit/summarize` 按滚动窗口 + 时序衰减，由行为日聚合输出六类习惯与十类购买影响因素权重；**只算不存、不建任何记忆表、不存画像与对话原文**，权威存储归 PROFILE（SSOT v2.0 §4.16-C16）；样本不足如实返回空结论，算法迭代不触发数据迁移。
- **独立库 `aicore`（MySQL 8，9 表）DDL 与迁移脚本**：对齐 `services/aicore/docs/er.md` v1.2——`ai_task` / `ocr_result` / `ocr_correction` / `vision_review` / `vision_marker` / `review_verdict` / `kitchen_anomaly` / `risk_predict_result` / `vision_qa_log`，任务与结果类按月分表；**不引入 PostgreSQL**。
- **GATEWAY 路由启用**：放开 `services/gateway/src/main/resources/application.yml` 中 `id: aicore` 路由（`/api/v1/aicore/**` → AICORE，`RewritePath` 去前缀，超时 5000ms）；**BREAKING（对内部调用方）**：习惯计算走服务端间内部 Token，不在账号级网关限流档位内，需在网关侧按内部身份单独计档。
- **工程化配套**：`GET /health` 健康检查、结构化 JSON 日志（与主站同 schema）、traceId 全链路透传、Prometheus 指标（OCR 通过率、任务成功率、AI 类 P95、人工复核量 / 总调用量）。
- **文档口径修正**：PDD §6.4.13 接口清单与 openapi.yaml 路径不一致（`/vision/review` vs `/vision/reviews`、`/kitchen/anomaly` vs `/kitchen/anomalies`），按「openapi.yaml 为接口唯一可手改源」修正 PDD。
- **非目标（Non-Goals）**：视觉合规审核工作台（K-03，M2）、图像问答（K-04，M2）、后厨直播异常识别（K-05，M2/M3）、风险预测预警（K-06，M3）——本变更只保留通道与任务类型的扩展位，不实现其业务逻辑；SkyWalking Python agent 接入、Grafana 看板、CI 流水线、第三方模型微调（R-05/C8 明令禁止）均不在范围内。

### 架构落地约束

上述能力不靠「写完再分层」，而是由一组可校验的架构约束承接（完整方案见 `design.md` 对应章节）：

- **分层依赖方向可校验**：`api → service → {provider 抽象, repository}`，`provider` 与 `repository` 互不依赖、且均不反向依赖 `service`；该规则由自动化检查固化（违反即用例变红），不靠评审自觉。
- **接口分类明确**：终端异步接口（落 `ai_task`）、结果轮询接口、服务端间同步接口（不落任务表）三类边界互不混用，M2 新增能力只新增处理器与注册项，不改动任务执行器内核。
- **数据层与文档同源**：ORM 模型与按月分表路由严格对齐 `er.md` v1.2，并有一条「DDL 与 `er.md` 一致性」的自动比对；Schema 变更走迁移脚本，禁止手改线上库。
- **出向调用走端口**：回写 CRED / DASH 经出向端口抽象，事件幂等与每日对账在该层收口；该层同时是 M2 若切换消息队列时的唯一替换点。
- **横切关注点集中**：配置模型启动即校验、统一异常到错误码的映射、traceId 上下文传播各自收敛在 `core/`，业务代码不重复实现。
- **测试可离线**：分层测试 + 依赖替身，无密钥、无外部中间件即可跑通全量单测，覆盖率门禁口径可复现。

## Capabilities

### New Capabilities

- `ai-core-service`: AI 能力中心 M1 服务能力——AI 网关与治理底座（多通道模型路由、内部鉴权与限流、异步任务队列与回执、置信度分级、全链路审计与血缘）、证照 OCR 自动核验、合规与成本护栏（图像脱敏前置、不回流第三方、成本三层护栏、C8 权威回写强制人工确认）、人工复核驱动的准确率闭环，以及习惯与购买影响因素的无状态计算。

### Modified Capabilities

（无——`openspec/specs/` 当前为空（仅 `.gitkeep`），无既有主能力规范需修改；`add-m1-core-capabilities` 的 `ai-capability-center` delta 描述 M1 的行为口径，本变更不改变该口径，而是把它落为可运行服务并补充工程化约束。）

## Impact

- **代码**：新增 `services/aicore/`（`pyproject.toml`、`src/aicore/**`、`tests/**`、`deploy/Dockerfile`、`deploy/sql/**`）；改动 `services/gateway/src/main/resources/application.yml`（放开 aicore 路由）与其路由/限流测试。
- **接口**：实现 `services/aicore/docs/openapi.yaml` v1.1.0 中 M1 的 2 个前端接口（`POST /aicore/ocr`、`GET /aicore/tasks/{taskId}`）与 1 个服务端间接口（`POST /aicore/habit/summarize`）；**该文件为接口唯一可手改源**，实现期如需调整先改它再改代码。
- **数据**：新增独立库 `aicore`（MySQL 8，9 表，任务/结果类按月分表），对齐 `services/aicore/docs/er.md` v1.2（**库表唯一可手改源**）；不复制 CRED（A-02 档案 / 信用分）与 DASH（A-08 预警）的权威数据，仅经事件回写。
- **文档**：修正 PDD §6.4.13 路径口径；AICORE README §3.2/§4.2 状态由「登记待落地」改为「已落地」；SSOT §2.12 与 `services/profile` 侧引用同步为「接口已可用」。
- **外部依赖**：DeepSeek 开放平台（文本通道）、云视觉 API（视觉通道，需签数据合规协议）、Redis 7（域内配额与预算计数、任务租约）、OSS/MinIO（图像对象键）、MySQL 8（独立库 `aicore`，**同时是异步任务的事实源与队列载体**——不引入 RabbitMQ，理由见 `design.md` D2）。
- **开发与测试可离线**：模型通道抽象为 Provider 接口，开发与测试环境**默认 Mock Provider**，CI 与本地测试不依赖真实密钥、不产生调用费用；生产环境 MUST 使用真实通道——若生产配置选中 Mock，进程**拒绝启动**（`design.md` D3）。测试以 fake provider + 依赖替身做到零密钥、零外部中间件可跑通全量单测（测试架构见 `design.md`）。
- **验证门禁**：单测覆盖率 ≥80%；分层依赖方向校验用例；DDL 与 `er.md` 一致性比对；OCR 正常 / 失败转人工 / 幂等重提 / 跨账号越权 2002 四类用例；习惯计算正常 / 样本不足 / 幂等重算 / 依赖超时 5002 四类用例；C8「无人工结论不得回写」用例；成本护栏配额与预算用例；提交前走 commit-check 门禁。
