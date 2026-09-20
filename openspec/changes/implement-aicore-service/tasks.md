# Tasks: implement-aicore-service

> 实施顺序依据 design.md「Migration Plan」；每个任务的验收方式写在任务描述中。
> 规范依据：`specs/ai-core-service/spec.md`；接口唯一可手改源：`services/aicore/docs/openapi.yaml` v1.1.0；库表唯一可手改源：`services/aicore/docs/er.md` v1.2。
> 合规标记约定：涉及 R-05/C8（AI 只标记不决策）与 R-07（画像不杀熟）的任务，在描述中已显式标注，实现时须在代码注释中同步标注，不得默认略过（`openspec/config.yaml` operations.apply）。
> 架构依据：design.md「工程结构与模块契约」「接口分类与任务契约」「异步并发与任务执行器内核」「数据层落地」「跨服务出向端口与事件适配」「横切关注点」「测试架构与离线策略」七章；第 1~3 组为架构地基，先于业务组交付（design.md Migration Plan 注）。

## 1. 工程骨架与分层契约

- [ ] 1.1 建立 `services/aicore/` Python 工程（Python 3.12 + FastAPI + Pydantic v2 + pydantic-settings + SQLAlchemy 2.x + redis-py + httpx + pytest）：`pyproject.toml`（含 ruff / mypy / pytest / import-linter / coverage 配置）、`src/aicore/` 与 `tests/` 骨架；验证：`pip install -e .` 成功、`python -c "import aicore"` 无错、`pytest` 可收集到测试目录
- [ ] 1.2 按 design.md「目录与文件职责」建齐分层目录与占位模块（`core/` / `api/` / `service/` / `provider/` / `repository/` / `port/`，含 `main.py` 组合根）；验证：目录树与 design.md 清单逐项比对一致，各模块可被导入
- [ ] 1.3 落地分层依赖方向规则检查（design.md 6 条禁止项：`api` 不直连 `repository`/`provider`；`service` 只依赖 Provider Protocol 不依赖具体实现；`repository`/`provider` 不反向依赖 `service`；`core` 不依赖任何业务层；只有 `provider/` 可发起外部模型调用；`service/desensitize.py` 与 `service/verdict.py` 不得出现异常后继续执行的降级分支）；验证：故意引入一处违规导入，检查必须失败（阴性用例），移除后通过
- [ ] 1.4 建立 `main.py` 组合根与应用装配（生命周期钩子、路由挂载、依赖注入装配点——**唯一允许注入具体实现的位置**）；验证：应用可启动、`GET /health` 返回 200、重复装配不产生重复注册

## 2. 配置与横切关注点

- [ ] 2.1 实现 Pydantic Settings 配置模型（`core/config.py`，dev / test / prod 三套，含 MySQL / Redis / Provider 选择 / 内部 Token / 配额与预算阈值 / 并发度 / 租约与重试参数）；验证：配置加载用例通过、仓库内 `grep` 无任何硬编码密钥、`.env` 被 `.gitignore` 覆盖
- [ ] 2.2 实现启动即校验且拒绝启动的四条规则（design.md 横切关注点：`prod` + `mock` 拒绝启动；真实通道缺密钥拒绝启动；dev/test 允许降级 mock 并告警；必填项缺失拒绝启动且**不兜默认值**）；验证：四类组合（prod+mock、prod+缺密钥、dev+缺密钥、prod+缺必填项）各有用例断言启动行为，违规必须抛错退出
- [ ] 2.3 实现异常层次与错误码映射（`core/errors.py`：`AiCoreError` 基类 + 子类分别携带 `1001`/`1002`/`1003` 参数类、`2001` 未登录或 Token 失效、`2002` 越权、`2004` 请求过于频繁、`3006` 对象不存在、`4003` 通道失败、`5002` 依赖超时；全局异常处理器统一映射为信封；未预期异常归 `5000`，且 FastAPI 默认 `422` 必须收编为 `1001`/`1002`/`1003`；堆栈只进日志不进响应体且不泄露内部细节）；验证：每类异常到错误码的映射用例通过、未预期异常不泄露堆栈用例通过、错误码与 `services/_common/openapi.yaml` 的 `ErrorCode` 枚举逐项比对一致（**含阴性用例：出现枚举外的码即失败**）
- [ ] 2.4 实现统一 Envelope（`core/envelope.py`，对齐 `_common/openapi.yaml`：必填 `code` / `message` / `traceId` / `timestamp` 四字段，`data` 可选，**成功码为 `0`**，`traceId` 为 camelCase，`timestamp` 为 UTC ISO 8601）；验证：四必填字段序列化用例通过、成功响应 `code=0` 用例通过、`/health` 与 `/metrics` **不被信封包裹**的断言通过、业务代码无手工拼装信封的残留（结构性断言）
- [ ] 2.5 实现 traceId 上下文传播（`core/trace.py`：从网关注入请求头 **`X-Request-Id`** 接收 → 上下文变量 → 日志过滤器与出向 HTTP 客户端取用；**网关未注入时自行生成**且该行为在日志中可区分）；验证：注入 / 未注入两条路径用例通过，出向调用携带同一 traceId 的断言通过，**跨线程池（`run_in_executor`）传递 traceId** 用例通过
- [ ] 2.6 实现结构化 JSON 日志（`core/logging.py`，与主站同 schema；业务代码只传结构化字段不手工拼字符串）；验证：日志字段 schema 用例通过

## 3. 数据层与分表路由

- [ ] 3.1 编写库表 DDL（独立库 `aicore`，MySQL 8，9 表：`ai_task` / `ocr_result` / `ocr_correction` / `vision_review` / `vision_marker` / `review_verdict` / `kitchen_anomaly` / `risk_predict_result` / `vision_qa_log`，字段与类型严格对齐 `er.md` v1.2 §6 数据字典）；验证：DDL 在空库执行成功、与 `er.md` 字段清单逐列比对无缺项
- [ ] 3.2 实现 SQLAlchemy 2.x 声明式模型（`Mapped[]` 风格、mypy 友好，字段与类型对齐 `er.md` §6）；验证：模型元数据导出字段与 `er.md` 数据字典比对一致、mypy 检查通过
- [ ] 3.3 落地按月分表路由（`repository/sharding.py`：按 `(account_id, created_at)` 计算物理表名 `ai_task_YYYYMM` / `ocr_result_YYYYMM` / `ocr_correction_YYYYMM`；写入前幂等确保当月物理表存在；查询 MUST 携带分片键下推）；验证：跨月写入路由用例、跨月边界查询用例通过，且断言无跨分片 JOIN / 聚合 / 事务（`er.md` §5.3）
- [ ] 3.4 实现会话管理与连接池（同步会话 + 线程池；写会话与只读会话来分离；池大小从配置读取不写死）；验证：会话生命周期用例通过、只读查询走只读会话来例通过、池大小随配置变化
- [ ] 3.5 建立 Schema 迁移（Alembic 版本化迁移 + 幂等建表脚本 + 迁移钩子承接分表物理表创建，遵循 expand-migrate-contract）；验证：空库从零迁移到目标结构可复现、重复执行幂等、迁移脚本与 `deploy/sql/` 一致
- [ ] 3.6 实现「DDL 与 `er.md` 一致性」自动比对（导出 `information_schema` 实际结构与 `er.md` §6 数据字典比对）；验证：正常状态下比对通过；人为单边改表或改文档后比对失败（阴性用例）
- [ ] 3.7 实现 repository 层数据访问（任务 / 结果 / 纠错 / 复核结论四类；事务边界：单表一事务、同分片跨表可合并、**跨分片拆为独立事务 + 幂等补偿**）；验证：四类存取用例通过、跨分片操作断言不开启分布式事务
- [ ] 3.8 实现分布式 ID 与主键策略（`task_` / `cor_` / `rev_` / `hab_` / `fac_` 等前缀 + 唯一 ID，对齐 `er.md` §5.4）；验证：并发生成 1 万个 ID 无重复、前缀与 `er.md` 一致

## 4. AI 网关底座（K-02）

- [ ] 4.1 实现 Provider Protocol 抽象（`provider/base.py`：TextProvider / VisionProvider / OcrProvider 三个结构子类型、统一入参与返回结构含置信度与血缘字段）；验证：Protocol 契约用例通过，且不依赖任何具体供应商 SDK
- [ ] 4.2 实现 Mock Provider（`provider/mock.py`：确定性输出、可注入延迟与故障，供离线测试与降级演练）；验证：Mock 下 OCR 与文本调用用例通过，全程无网络依赖（断网可跑）
- [ ] 4.3 实现真实 Provider 骨架与通道护栏（DeepSeek 文本 / 云视觉 / 云 OCR 的客户端封装与超时、重试、熔断，密钥经 KMS 或环境变量；**外部模型 HTTP 调用只允许出现在 `provider/` 包内**）；验证：以假密钥走通「构造请求—超时—熔断—返回 4003」链路用例，不发出真实计费调用；结构性断言 `httpx` 模型调用仅在 provider 包内
  - **口径更正（2026-09-20 复核；原句保留不删，便于追溯当时措辞）**：本行「超时—熔断—返回 `4003`」与 `4.11`「依赖超时 `5002`」及 `specs/ai-core-service/spec.md:227`（「依赖调用超时 → `5002`」）冲突。**权威口径以后两处为准，代码也是这么实现的**：**超时 / 熔断终码 = `5002`**；`4003` 只留给「等到了失败」（通道确实返回失败）。依据：`services/_common/openapi.yaml:208`（`5002 # 依赖超时 / 熔断`）、`services/aicore/docs/er.md:26`（`error_code`：`4003` 通道失败转人工 / `5002` 依赖超时）。`spec.md` 是权威源且本身写对，MUST NOT 为此改 `spec.md`。
- [ ] 4.4 实现 Provider 选择器（`provider/selector.py`，按配置选择通道，与 2.2 的启动校验衔接）；验证：三种环境下的选择结果用例通过、选择逻辑不读取业务参数
- [ ] 4.5 实现任务提交与状态机（提交即写 `ai_task` 返回 `taskId`；状态机 `PROCESSING → SUCCEEDED / FAILED / MANUAL_REVIEW`；进度回写）；验证：受理返回任务号、进度可查、状态转移非法路径被拒三类用例通过
- [ ] 4.6 实现任务类型策略注册表（`service/task/registry.py`：`OCR` 注册到 `ocr_service`，`VISION_REVIEW` / `KITCHEN_ANOMALY` / `RISK_PREDICT` 预留注册位并声明结果结构、超时、是否可重试；**未注册类型必须显式失败而非静默忽略**）；验证：注册与查询用例通过、未注册类型显式失败用例通过、新增类型不改 `task_runner`（结构性断言）
- [ ] 4.7 实现任务执行器内核（`core/task_runner.py`：Redis `SET NX PX` 原子领取 + 心跳续期 + 租约超时回收；**续期失败主动放弃任务**；指数退避重试、超限置 `FAILED` 转人工；实例内并发度信号量与背压）；验证：原子领取（并发领取不重复）、租约超时回收、续期失败放弃、退避重试、超限转人工五类用例通过
- [ ] 4.8 落实 CPU 密集任务下线程池（图像解码、脱敏处理、哈希存证计算走 `run_in_executor`，**不得在事件循环内执行**）；验证：断言重活不在事件循环执行的用例通过、并发提交时受理接口耗时不劣化（对照用例）
  - **缓期登记**：「并发提交时受理接口耗时不劣化（对照用例）」**本阶段未做**，归 **`13.4`**（本文件 `13.4` 压测 P95）。理由：① 它本质是**性能**条款，归宿就是压测；② M1 **无 CPU 密集调用点**（见下条附注），此时测「劣化」测不到东西；③ 用例内自比时延正是本会话刚花整轮清掉的「时序余量判据」。
  - **缓期登记（附注）**：`run_cpu_bound`（`src/aicore/core/task_runner.py`）在 `src/` 下**零调用点**（唯一出现处是它自己的定义与文档）⇒ CPU 密集链路（图像解码 / 脱敏 / 哈希存证）**本阶段根本没接上**：做这些的 OCR 处理器属**第 5 组 K-01**（本文件 §5）。故 4.8 的结论是「机制已就位、接入未发生」，MUST NOT 读成「CPU 密集路径已被验证」。
- [ ] 4.9 实现任务提交幂等与跨账号越权拦截（相同幂等键返回原任务号不重复调用；非本人任务查询返回 `2002` 且不泄露任何结果内容）；验证：幂等重提用例（断言 Provider 调用次数不增加）与越权查询 2002 用例通过
  - **缓期登记**：验证句里「断言 **Provider 调用次数**不增加」的**字面**判据缓期至**第 5 组 K-01**（本文件 §5）；M1 的受理路径**根本不调 Provider**（`main.py` 注入 `handlers={}`、`services/ocr_service.py` 仍是空壳）⇒ 字面判据**没有落点**。本阶段用**等价形态**：可领取行恰好一条 ⇒ 执行器只把任务交给处理器一次（`tests/api/test_ocr_submit.py::test_duplicate_submit_yields_one_claimable_task_and_one_handler_call`）。
  - **等价形态弱一步（如实登记，MUST NOT 读成已验）**：它**不数真 Provider 调用**——若第 5 组的 handler **内部重复调用或自身重试**，本判据**抓不到**。第 5 组处理器落地后 MUST 补「真 Provider 调用计数不增加」的断言。
- [ ] 4.10 实现置信度分级（高 ≥0.9 / 中 0.7~0.9 / 低 <0.7，阈值可配并留痕）；验证：三类边界值（0.899 / 0.9 / 0.7）分级用例通过，阈值变更记录可查
  - **缓期登记**：「分级结果 MUST 随 AI 输出一并返回」（`specs/ai-core-service/spec.md:58`）的**端到端**（真通道 → 真落库 → 轮询返回分级）缓期至**第 5 组 K-01**（`5.6` 结果回执落地后）。仓库内已有**会自己过期**的 in-repo 判据把它挂住：`tests/api/test_confidence_grading.py::test_m1_has_no_ocr_handler_so_grading_is_not_end_to_end_yet`——今天断言 `main.py` 仍是 `handlers={}`；第 5 组注入真处理器后该用例**自动变红**，提示补两条端到端断言（① `ocr_result.needs_manual_review`、② 分级随输出返回）。
  - **口径说明（本行措辞宽于权威文档，按权威文档执行）**：本行「阈值变更记录可查」按 `spec.md:58`（「阈值 MUST 可按运营数据调整并**留痕**」）与 `er.md:27`（`model_meta` 含**阈值快照**）执行 ⇒ 实现为**每任务当次阈值快照**（`ai_task.model_meta.thresholds`）；**MUST NOT** 为此新增「配置变更日志」机制——它不是任何权威文档要求的交付物。
- [ ] 4.11 实现通道失败降级与异常区分（通道失败 `4003` 转人工复核队列、依赖超时 `5002`，两者不混用且分别计数；降级状态可观测、不阻塞核心业务）；验证：`4003` 与 `5002` 分别断言用例通过，降级期间业务接口仍可正常受理新任务
  - **缓期登记**：「**分别计数**」的指标侧（→ Prometheus counter）缓期至**第 11 组**（本文件 `11.3` 暴露 Prometheus 指标）；本阶段只保证**事实源可分组**：`ai_task` 里 `WHERE status='FAILED' GROUP BY error_code` 能把 `4003` / `5002` 分开数（用例 `tests/integration/test_failure_codes_mysql.py`）。
  - **缓期理由（仓库内确无判据，如实登记）**：目前**没有**任何 in-repo 判据把「按码计数」挂到指标端点——`tests/unit/test_envelope.py:501` 只管 `/metrics` 的**端点存在性**（且会自过期），**不管**按码计数；故第 11 组落地 `11.3` 时 MUST 补「两类码分别 +1」的断言。

## 5. 证照 OCR 自动核验（K-01）

- [ ] 5.1 实现图像脱敏前置阶段（人脸 / 车牌检测后不可逆处理，产出脱敏后对象；**脱敏失败或超时即拒绝外发**，任务转 `MANUAL_REVIEW` + `4003`，不得放行原图）【R-03/R-05】；验证：正常脱敏用例、脱敏超时拒绝用例、以及「脱敏失败时 Provider 未被调用」的断言用例全部通过
- [ ] 5.2 实现 `POST /aicore/ocr` 提交接口（按 `openapi.yaml` v1.1.0 契约：入参 `imageKey` / `docType` / `scene`，出参 `TaskAccepted`；支持 `Idempotency-Key` 头）；验证：契约字段与 `openapi.yaml` 逐项比对一致、OpenAPI 响应结构校验用例通过
- [ ] 5.3 实现 OCR 字段提取与结构化结果（`fields[]` 含 `fieldName` / `value`（脱敏输出）/ `confidence`）；验证：Mock 样本下三类证照（营业执照 / 许可证 / 检测报告）字段提取用例通过，且输出值已脱敏
- [ ] 5.4 实现有效期与经营类目比对（`validity` ∈ `VALID` / `EXPIRING` / `EXPIRED` / `UNKNOWN`，`categoryMatch`、一句话结论 `summary` 与人工核验提示 `suggestions`）；验证：有效期内 / 临期 / 已过期 / 无有效期字段 / 类目不符五类用例通过
- [ ] 5.5 实现识别失败与图像模糊的转人工路径（`needsManualReview=true` 或任务降级，提示重传，**预审流程不因 OCR 失败而阻塞**）；验证：通道失败、图像模糊两类用例通过，且入驻预审调用方收到明确的降级信号
- [ ] 5.6 实现 `GET /aicore/tasks/{taskId}` 结果回执（按 `type` 返回 `OcrResult`；`PROCESSING` 时 `result` 为空；`FAILED` 时返回 `errorCode`）；验证：三种状态各自的响应结构用例通过，字段与 `openapi.yaml` 的 `TaskResult` 一致
- [ ] 5.7 实现模型与 Prompt 血缘留痕（`ai_task.model_meta` 记录通道 / 供应商 / `modelVersion` / `promptVersion` / 阈值快照，并随任务查询返回；**与习惯计算的 `modelMeta` 区分**——后者记算法版本 / 窗口天数 / 最小样本量 / 阈值快照，不写 `ai_task`）；验证：任务血缘写入与查询用例通过、习惯计算血缘不写 `ai_task` 的断言通过、字段与 `er.md` §6.1 一致
- [ ] 5.8 验收 AC-M1.11「OCR 结果可追溯」：任务可追溯至所用通道 / 模型版本 / Prompt 版本 / 阈值快照，且能回溯到纠错留痕；验证：以一次完整 OCR 任务取证（任务 → 结果 → 血缘 → 纠错记录）四段可串联

## 6. 准确率闭环与合规护栏

- [ ] 6.1 实现纠错回流（人工核验纠正字段时写 `ocr_correction` **一行一字段**：AI 原值 / 人工真值（均脱敏）/ 当时置信度 / 核验人（脱敏）/ 时间）；验证：单次纠正多字段产生多行用例通过，断言语料中无原始证件图像与未脱敏值
- [ ] 6.2 实现按 label 与置信度分桶的准确率统计（字段级准确率、低置信误判分析；统计走只读会话/副本）；验证：分桶统计用例通过，桶边界与 `er.md` §7.11 口径一致
- [ ] 6.3 实现固定评估集与变更前回归（`ai_task.is_eval_sample` 标记评估集样本；模型 / Prompt / 阈值变更前后跑同一评估集输出对比，**无对照不得上线**）；验证：评估集回归脚本可运行并产出前后对比，缺对照时流程被判失败用例通过
- [ ] 6.4 实现未标记样本抽样复核（按 1%~5% 从**未被 AI 标记**的样本中随机抽样生成复核任务，用于发现漏检）；验证：抽样比例与来源用例通过（断言抽样样本均来自未标记集合），抽样任务可进入人工复核队列
- [ ] 6.5 实现「人工复核量 / 总调用量」主指标与准确率副指标的计算与暴露；验证：指标计算用例通过（给定固定输入得到确定值），指标可在 Prometheus 端点读到
- [ ] 6.6 验收 R-05「不回流第三方」：断言代码中不存在向外部模型供应商上传复核结论或纠错语料的调用路径，且真实 Provider 实现不接收该类语料作为训练输入；验证：结构性断言用例通过 + 人工核对 Provider 接口签名不接受纠错语料

## 7. 跨服务出向端口与事件适配

- [ ] 7.1 定义出向端口 Protocol（`port/cred.py` 的 `CredPort.write_authority` 回写 CRED A-02 档案与信用分、`port/dash.py` 的 `DashPort.report_alert` 上报 DASH A-08 预警；载荷与幂等键 `authority_event_id` 按 design.md 端口表）；验证：Protocol 契约用例通过，`service/` 仅依赖 Protocol 的断言通过
- [ ] 7.2 实现端口 fake 实现与组合根注入（测试用 fake，生产用 HTTP 实现；**M2 若切换消息队列只替换本层发送实现**）；验证：注入切换用例通过（同一 service 用例在 fake 与真实实现下跑同一套契约测试）、service 层不感知传输方式
- [ ] 7.3 实现发送可靠性（指数退避重试；重试耗尽写死信记录并告警，**不静默丢弃**）；验证：重试退避用例、重试耗尽产生死信与告警用例通过
- [ ] 7.4 实现每日对账（按 `authority_written=true` 与消费方回执比对，差异可发现、可补发、可告警）；验证：构造差异数据后对账任务能检出并告警的用例通过，补发路径幂等用例通过

## 8. C8 工程化强制（AI 只标记不决策）

- [ ] 8.1 实现权威回写前置条件（**无人工复核结论则不存在任何回写入口**：回写路径以 `review_verdict` 存在人工结论行为前提，`authority_written` 默认 `false`）；验证：无人工结论时回写被拒用例通过，且断言 AI 产出路径中无直接写权威数据的代码调用【C8】
- [ ] 8.2 实现回写事件与幂等（回写成功写 `authority_written=true` / `authority_event_id` / `authority_written_at`，事件标识供消费方幂等处理）；验证：重复消费同一事件不产生二次写入用例通过
- [ ] 8.3 断言回写只由「人工复核结论落地」触发（MUST NOT 由 AI 产出直接触发；`authority_written` 状态转移是唯一入口）；验证：结构性断言通过【C8】
- [ ] 8.4 断言系统不自动执行执法 / 处罚 / 公示动作（AI 输出仅产生标记与建议，无任何自动处置出口）；验证：结构性断言 + 接口清单核对（AICORE 无处置类写接口）通过【C8】

## 9. 成本三层护栏

- [ ] 9.1 实现单账号日配额（Redis 计数、超限返回业务码 `2004`（HTTP 状态码 429）、接近配额有可用量提示）；验证：配额边界用例通过（第 N 次通过、第 N+1 次 `2004`），跨日自动重置用例通过
- [ ] 9.2 实现全局日预算（80% 告警不降级、100% 降级为人工复核路径并告警）；验证：80% / 100% 两个阈值行为用例通过，降级后不继续调用外部模型
- [ ] 9.3 实现按调用方成本归因（记录调用方与用量，可按周期出账）；验证：多调用方混合流量下归因结果可核对用例通过
- [ ] 9.4 明确并实现「网关限流 vs 域内成本护栏」职责分离（GATEWAY 的 10 次/分/账号为速率限制；AICORE 日配额与预算为成本上限；习惯计算等**服务端间接口不计入账号级档位**，按调用方服务身份单独归因）；验证：终端账号请求与服务端间请求分别计档的用例通过

## 10. 习惯与购买影响因素无状态计算

- [ ] 10.1 实现 `POST /aicore/habit/summarize` 契约（按 `openapi.yaml` v1.1.0：入参 `accountId` / `periodStart` / `periodEnd` / `behaviorDailyAgg[]` 与可选 `sampleSource` / `windowDays` / `minSampleCount`；出参含 `habits[]` / `factors[]` / `isEmpty` / `sampleSource` / `windowDays` / `modelMeta` / `computedAt`）；验证：契约字段逐项比对用例与 OpenAPI 结构校验用例通过
- [ ] 10.2 实现该接口的同步语义（**不落 `ai_task`、无副作用、无进度语义**，与终端异步接口边界不混用，按 design.md「接口分类与任务契约」）；验证：调用后 `ai_task` 数据量不增长的断言用例通过、响应结构无任务字段用例通过
- [ ] 10.3 实现内部 Token 鉴权（服务端间独立凭据，请求头 **`X-Internal-Token`**，**不接受终端用户令牌**；头名须与 `openapi.yaml` 的 securityScheme 一致）；验证：内部凭据通过、终端 JWT 被拒（业务码 `2001`）两类用例通过；并断言该路径未出现在面向终端的接口清单中
- [ ] 10.4 实现计算纯函数（`service/habit/{engine,decay,evidence}.py`：滚动窗口 90 天可覆盖、时序衰减新证据权重高于旧证据；**无任何 IO 与写库路径**）；验证：纯函数用例通过（同输入同输出、无 IO），并对函数做「不调用 repository」的结构性断言
- [ ] 10.5 实现六类习惯与十类因素码的权重计算与可解释证据（`CATEGORY_PREF` / `PRICE_BAND` / `TIME_WINDOW` / `FREQUENCY` / `SUPPLIER_TRUST` / `CHANNEL`；`PRICE` / `CREDIT` / `TRACE` / `REVIEW` / `DELIVERY` / `BRAND` / `PROMO` / `SPEC` / `FRESHNESS` / `CERT`；证据为可读说明且不含对话原文）；验证：枚举与 `openapi.yaml` 一致比对通过、每类习惯与因素至少一条计算用例通过、证据文本不含对话原文
- [ ] 10.6 实现样本不足如实返回（低于 `minSampleCount`（默认 20）或入参为空 → `isEmpty=true` 与空数组，**不报错、不硬凑、不输出低置信度伪结论**）；验证：空数组、样本量 19、样本量 20 三类边界用例通过
- [ ] 10.7 实现幂等（同 `accountId` + `periodEnd` 幂等，重算覆盖）与服务端间限流；验证：重复请求返回一致结果用例通过（断言无副作用累积）、限流用例通过
- [ ] 10.8 实现异常区分（越权账号 `2002`、依赖超时 `5002`）与 `sampleSource` 如实回传（M1 无交易数据 → `BEHAVIOR`）；验证：`2002` / `5002` 分别断言用例与 `sampleSource` 回传用例通过
- [ ] 10.9 验收「只算不存」：断言本服务**未建立任何用户长期记忆表**、不持久化画像 / 行为聚合入参 / 对话原文，`aicore` 库表中无任何用户习惯类数据表；验证：库表清单核对用例通过（9 表中无习惯表）+ 全量调用后库内数据量断言不增长
- [ ] 10.10 验收「算法迭代不触发数据迁移」：将算法的 `modelVersion` 从统计版切换为新版本后，下游用户数据无需迁移、接口契约不变；验证：切换算法版本的回归用例通过（同一入参两版本各自可算、契约字段不变）【SSOT v2.0 §4.16-C16】
- [ ] 10.11 验收 R-07「权重不进定价」【R-07/C7】：断言同一商品在两个权重差异极大的画像下最终价格字段完全一致，且排序链路不引用价格字段；验证：同品同价用例通过 + 排序链路「不引用价格字段」结构性断言通过
- [ ] 10.12 断言输出不含人格推断标签（仅权重 / 样本量 / 可解释证据）；验证：输出结构断言用例通过（`habits[]` / `factors[]` 字段白名单校验，出现白名单外字段即失败）
- [ ] 10.13 与 PROFILE 侧联调习惯计算链路（PROFILE 以 `behavior_daily_agg` 日聚合调用 → 本服务返回结论 → PROFILE 落 `profile_habit` / `profile_habit_factor`；重算覆盖幂等；**计算失败 / 超时保留上一版结论、不阻塞画像读写**）；验证：端到端联调用例通过，含失败保留上一版的分支

## 11. 可观测性与健康检查

- [ ] 11.1 实现 `/health`（进程存活）与 `/health/ready`（依赖就绪：MySQL / Redis / Provider 可达性）分离；验证：依赖正常时就绪返回 200、断开依赖后就绪返回非 200 且存活仍为 200 的用例通过
- [ ] 11.2 实现日志脱敏保障（**确保日志不含原始图像与未脱敏证件字段**）；验证：敏感信息泄露扫描用例通过（构造含证件号的输入，断言日志中不出现明文）
- [ ] 11.3 暴露 Prometheus 指标（OCR 通过率、任务成功率、任务耗时分布、人工复核量 / 总调用量、配额与预算水位、**任务队列深度**）；验证：`/metrics` 端点可抓取、各指标在触发一次真实任务后数值按预期变化、队列深度指标随积压上升
- [ ] 11.4 实现 traceId 联调验证（从 GATEWAY 注入的请求头接收并透传至下游调用与全部日志）；验证：一次请求的网关日志与本服务日志可按同一 traceId 串联（联调用例）

## 12. 测试架构与离线策略

- [ ] 12.1 建立测试夹具（`tests/conftest.py`：配置夹具按环境覆盖、fake provider、内存或轻量库会话、ASGI `httpx` 客户端、应用装配夹具；**测试内不出现任意 sleep，等待走可控时钟或轮询断言**）；验证：夹具可被各层测试复用、时间相关用例（跨月 / 租约 / 对账）稳定通过
- [ ] 12.2 落地分层测试结构（纯函数单测 / 契约测试 / 仓储测试 / 接口测试四层与目录组织，对齐 design.md 测试分层表）；验证：四层各有实际用例且可分别执行
- [ ] 12.3 标记并区分集成测试（端到端层以 `@pytest.mark.integration` 标记、默认不执行）；验证：`pytest`（默认）不跑集成用例、`pytest -m integration` 可单独执行
- [ ] 12.4 证明离线可跑（无密钥、无外部中间件环境下执行前四层测试必须全绿）；验证：断网或屏蔽出口流量下执行前四层测试全绿的取证记录
- [ ] 12.5 建立结构性断言专项用例集（分层依赖规则、Provider 不接收纠错语料、AI 产出路径无权威回写调用、习惯计算不调用 repository、输出字段白名单）；验证：五项断言用例齐备且均可独立执行，故意破坏任一项即失败

## 13. 网关接入与端到端

- [ ] 13.1 放开 GATEWAY `id: aicore` 路由（`/api/v1/aicore/**` → AICORE，`RewritePath` 去前缀，超时 5000ms）并补充路由用例；验证：`services/gateway` 路由测试通过、经网关访问 `POST /api/v1/aicore/ocr` 可正确去前缀落到 `/aicore/ocr`
- [ ] 13.2 核对 AI 限流档位与内部调用计档（终端 `Tier.AI` 10 次/分/账号；习惯计算等内部调用不计入该档位，按调用方身份单独归因）；验证：终端调用触发业务码 `2004`（网关档位）的用例与内部调用不受该档位限制的用例同时通过
- [ ] 13.3 端到端联调（网关 → AICORE → Provider(Mock) → MySQL，覆盖 OCR 提交与轮询、习惯计算、越权 2002、通道失败 4003 四条链路）；验证：四链路端到端用例通过并留存 traceId 串链证据
- [ ] 13.4 实测 AI 类响应耗时（NFR：AI 类同步 P95 ≤3s，按异步任务设计）；验证：压测或批量调用记录 P95 数据，异步受理接口 P95 ≤3s，超标则记录瓶颈与整改项

## 14. 工程门禁与验收

- [ ] 14.1 单测覆盖率达标（`DEVELOPMENT_CONSTRAINTS.md` MUST：≥80%，按 design.md 覆盖率口径排除组合根与真实通道骨架）；验证：`pytest --cov` 报告覆盖率 ≥80%，排除项与 design.md 口径一致，报告归档
- [ ] 14.2 红线合规自检清单逐项取证（R-03 图像脱敏前置、R-05 不回流第三方 + AI 只标记不决策、R-07 权重不进定价、C8 无人工结论不回写）；验证：四项各附用例名与执行输出，形成自检记录
- [ ] 14.3 提交前走 commit-check 门禁（本次改动含代码与配置，须完整过 D 组安全与 E 组测试检查）；验证：commit-check 各清单项全部通过，无阻断项
- [ ] 14.4 文档口径同步：修正 PDD §6.4.13 与 `openapi.yaml` 不一致的路径（`/vision/review` → `/vision/reviews`、`/kitchen/anomaly` → `/kitchen/anomalies`）；AICORE README §3.2/§4.2 成本护栏状态由「登记待落地」改为「已落地」；SSOT §2.12 与 `services/profile` 侧引用同步为「接口已可用」；验证：三处文档改后全文检索无残留旧口径，`openspec validate --all --strict` 全绿
- [ ] 14.5 记录 `AI_DEV_LOG/` 当日文件（按「需求/问题 → 方案/动作 → 产出物 → 验证」四要素，附复刻要点）；验证：日志文件含本次产出物清单与验证证据（覆盖率报告、端到端用例输出、红线自检记录、离线可跑取证）
