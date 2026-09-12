# add-m1-core-capabilities

## Why

「民生甄选」城市民生综合服务平台的 PRD v2.3（2026-09-11 评审定档）与 PDD v1.0（2026-09-11 定档）已完成，M1 MVP（试点 ≥200 商户、≥3 行业、PC Web 三端）即将进入开发；但 `openspec/specs/` 当前为空，实施缺少以「能力」为单位的权威行为规范。本变更将 PRD v2.3 §3.1 已冻结的 M1 范围固化为 9 个 OpenSpec 能力规范，作为 M1 开发、测试与验收的唯一规范来源。

## What Changes

- 新增 9 个 M1 能力规范（详见 Capabilities），覆盖 PRD §3.1 M1 范围全部功能点：平台级能力（P-01~P-06）、信用与监管（A-01~A-08 的 M1 基础口径）、用工保障（C-01 防童工、C-02 打卡记工时）、投诉直达（D-02）、政民互动（G-01 基础）、平台账户与资金（I-01/I-02/I-03）、智能助手与画像（J-01~J-06/J-12/J-13 + J-07~J-11 画像 M1 基础版）、AI 能力底座（K-01/K-02）、供应商与溯源底座（T-01/T-05 基础/T-08/T-09）。
- 全部规范以 PRD v2.3（`docs/需求调研/核心成果/产品需求文档.md`）、非功能专项 v1.0（`docs/需求调研/核心成果/非功能需求-信息安全与可靠性专项.md`）、PDD v1.0（`docs/design/产品设计文档.md`）、高并发架构演进设计 v1.0（`docs/design/高并发架构演进设计.md`）与用例图规约为事实来源；不臆造接口、模块、文件名或实现细节。
- 平台级红线 R-01~R-16 与合规验收 AC-C1~C8、非功能验收 AC-NFR-1~11 贯穿全部能力，写入对应能力的 Requirement 与场景。
- 非目标（Non-Goals）：M2/M3 功能域（B-02/B-03 完整版、D-03、E/F/H 组、G-02/G-03、L 配送交付、T-02~T-21、K-03~K-06、I-04/I-05、骑手端交付、EDU 专项）不在本变更内，后续里程碑另行提出 change；本变更只建规范、不改代码。

## Capabilities

### New Capabilities

- `platform-baseline`：平台级能力（P-01 费率/抽成公开公示、P-02 全平台证据存证与出证、P-03 试点范围与行业扩展机制、P-04 政务对接替代与双轨切换、P-05 平台定位与信任背书承诺、P-06 商户冷启动与存量导入）。
- `credibility-regulation`：信用与监管内核（A-01 商户入驻与证照核验建档、A-02 一店一档公开页、A-03 档案维护与异常标记、A-04 价格公示基础版、A-05 未成年人禁入承诺标注、A-06 一人一档与从业履历、A-07 信用分与红黑榜、A-08 监管预警 M1 基础）。
- `employment-protection`：用工与保障（C-01 防童工入职年龄核验、C-02 打卡记工时——工时自动累计，作为 I-03 工资代付考勤依据；C1 工资保障→I-03、C3 履历→A-06 按去重口径归位）。
- `complaint-redress`：交易与维权（D-02 投诉直达+进度可见+结果公示，含「未成年人违规进入」举报类别）。
- `civic-interaction`：政民互动（G-01 群众热线/诉求工单基础版，12345 不可接→自建工单+线下流转）。
- `account-funds`：平台账户系统（I-01 实名账户与钱包记账、I-02 劳务信用双向互评、I-03 工资保障代付，记账与支付分离、不沉淀资金）。
- `smart-assistant`：智能使用助手与个人画像（J-01~J-06 助手基础能力、J-12 服务治理、J-13 澄清式导购、J-07~J-11 个人画像 M1 基础版：数据源/标签/三用途/画像四权/合规 C7）。
- `ai-capability-center`：AI 能力中心（K-01 证照 OCR 自动核验、K-02 AI 网关与治理底座，AI 只标记不决策 C8）。
- `supplier-traceability`：全产业透明交易 M1 底座（T-01 供应商入驻与品类资质核验、T-05 供应商信用档案基础、T-08 溯源批次码生成与环节上报、T-09 扫码验真与全链透明展示）。

### Modified Capabilities

（无——`openspec/specs/` 当前为空，本变更为首个能力基线。）

## Impact

- **后端服务**（按 PDD §5 服务映射，均为绿场实现）：`services/acc`（I1）、`services/settle`（I3 代付）、`services/cred`（A1/A2/A3 + 价目表 + 禁入承诺）、`services/emp`（C-01/I2 互评）、`services/ticket`（D2/G1）、`services/trace`（T2/T3）、`services/assist`（J，Python）、`services/aicore`（K-01/K-02，Python）、`services/dash`（费率公示页 AC-M1.10）、`services/profile`（J7 画像，Java）、`services/gateway`（M1 后期独立部署，M1 初期内嵌 Filter+Nginx）、`services/_common`（公共组件/错误码/存证/幂等）。
- **前端**：`apps/pc`（消费端/经营端/监管端三端合一单 App）；`apps/mobile` 不在 M1 范围。
- **外部依赖**：微信/支付宝实名回传（唯一通道）、微信支付/支付宝代付、DeepSeek 开放平台 API、云视觉 API（OCR）、短信通道；均 M0 前置开通（AC-M0.1~M0.6）。
- **非功能与合规**：等保三级（定级备案 M0、测评 M1 上线前）、OWASP ASVS L2、L1 可用性 ≥99.95%、压测规划峰值 1.5~3x（AC-NFR 系列）；高并发地基（按月分表、infra-idgen 分布式 ID、幂等、接口级限流、可观测三件套）M1 启动即做。
- **文档**：本变更仅新增 `openspec/changes/add-m1-core-capabilities/` 下的规范文件，不改动任何现有 PRD/PDD/服务文档。
