# AICORE 架构部分 · 设计文档

> **变更**：`implement-aicore-service`（OpenSpec）· **范围**：`tasks.md` 第 1~3 组共 18 项（架构地基）
> **日期**：2026-09-16 · **状态**：待用户评审
> **流程**：superpowers `brainstorming`（architectural 路径）
> **本文档的定位**：只承载「**怎么做、按什么顺序、怎么算通过**」。决策与理由的**唯一事实源**仍是
> `openspec/changes/implement-aicore-service/design.md`（D1~D10 与七章架构），本文不复制、不另立第二口径。

---

## 1. 背景与范围

### 1.1 为什么先做架构部分

`design.md` Migration Plan 的落位注已定档：

> 以上第 1~3 步必须同时交付「工程结构与模块契约」的分层检查、「数据层落地」的分表路由与 `er.md` 一致性比对、
> 「异步并发与任务执行器内核」的线程池边界、「跨服务出向端口」的 Protocol + fake 实现、「横切关注点」的配置校验与
> 异常映射，以及「测试架构」的四层离线可跑。**这些不是收尾项**——它们在第 4 步之后才补，会付出返工代价
> （业务代码已按错误边界写死）。

本次交付第 1~3 组：**工程骨架与分层契约**（4 项）、**配置与横切关注点**（6 项）、**数据层与分表路由**（8 项）。
**不含**任何业务接口（OCR / 习惯计算 / 准确率闭环属第 4 组起）。

### 1.2 交付粒度（用户已确认：方案 A）

三组**分别交付、每组结束给出验证证据**，确认后进入下一组。理由：架构地基本身的价值在「边界正确」，
而边界是否正确只有跑起来才看得见。

### 1.3 事实源优先级（本设计遵守）

`PRD` > 非功能需求专项 > `PDD` > `SSOT`（微服务边界与职责基准）> 高并发架构演进设计 >
`services/aicore/docs/openapi.yaml`（接口**唯一可手改源**）与 `services/aicore/docs/er.md`（库表**唯一可手改源**）。

---

## 2. 已核实的权威口径

以下每一条都经**实读文件**核对（非记忆、非推断），是本设计的硬约束。

### 2.1 响应信封与错误码（源：`services/_common/openapi.yaml`）

| 事实 | 位置 | 值 |
|---|---|---|
| `Envelope` 必填字段 | L124–128 | `code` / `message` / `traceId` / `timestamp` |
| `data` 是否必填 | L136 | **否**（成功时有值，失败为 `null`） |
| 字段命名 | L138/L142 | **camelCase**：`traceId`（**不是** `trace_id`） |
| `timestamp` 格式 | L143–146 | `date-time`，**UTC** ISO 8601 |
| **成功码** | L122–123 | **`0`**；「前端可用 `code === 0` 判断成功」 |
| 错误码分段 | L122 | 0 成功 / 1xxx 参数 / 2xxx 鉴权权限 / 3xxx 业务规则 / 4xxx 第三方依赖 / 5xxx 系统 |
| `ErrorCode` 枚举 | L151–178 | 共 28 个取值（AICORE 只用到其中 8 个，见 §4.3） |
| 幂等键头名 | L46 | `Idempotency-Key`（`maxLength: 64`） |

### 2.2 traceId 与日志（源：`PDD` §8.5.1 L1747–1750、高并发 §7.6 L424）

| 事实 | 值 |
|---|---|
| traceId 请求头 | **`X-Request-Id`**（→ 映射为 `traceId`） |
| 生成责任 | 网关注入；**无请求 ID 时网关兜底生成**（PDD §5.16 L1372） |
| 日志必含字段（11 项） | `time` / `level` / `app` / `service` / `module` / **`traceId`** / **`spanId`** / `uid`（脱敏）/ `bizType` / `opCode` / `code` / `message` |
| Python 侧日志库 | `structlog` **或** `logging`（PDD 二者并列，本设计取 `structlog`） |
| 日志禁止内容 | 明文密钥、支付敏感信息（L1748）；脱敏规则与 J 助手共用（L1749） |
| AI 超时 | **5s**（高并发 L423「AI 5s」，与网关路由 `timeout: 5000` 一致） |

### 2.3 数据库约定（源：`services/aicore/docs/er.md` v1.2）

| 事实 | 位置 | 值 |
|---|---|---|
| 库 | §5.1 | **独立库 `aicore`**（MySQL 8，与主站库物理/逻辑隔离） |
| **分片表只有 3 张** | §5.2 | `ai_task` / `ocr_result` / `ocr_correction`，均 `_YYYYMM` **按月** |
| 另 6 张**不分片** | §5.2 | `vision_review` / `vision_marker` / `review_verdict` / `kitchen_anomaly` / `risk_predict_result` / `vision_qa_log` |
| 分片键 | §5.3 | `ShardingKey(account_id, created_at)`；`ocr_result`/`ocr_correction` 随 `task_id` **同月同分片** |
| 路由禁令 | §5.3 | **禁止跨分片 JOIN / 聚合 / 事务**；查询**必须**携带分片键下推 |
| **AICORE 不用雪花 ID** | §5.4 L247 | 「雪花 ID 与时钟回拨三档预案**仅适用于写库 Java 域**」；AICORE 无 workerId、无回拨风险面 |
| ID 形态 | §5.4 | `前缀 + UUID`，**均为 `varchar(32)`** |
| ID 前缀 | §5.4 | `task_` / `cor_` / `rev_` / `marker_` / `kan_` / `qa_` |
| 读写分离 | §5.5 | 主库写、从库读；**写后立即读强制走主库** |
| 演进 | §5.6 | expand-migrate-contract 四步（双写 → 回灌 → 切读 → 收缩），**禁止破坏性 DDL 直上生产** |
| 通用约定 | §6 绪 | InnoDB、`utf8mb4`、`datetime(3)` 毫秒、**UTC 存储 / 输出 Asia/Shanghai**、置信度 `decimal(3,2)`、风险分 `decimal(5,2)`、数组用 JSON 列、**不存原始图像与证件明文**、枚举与 `openapi.yaml` `components.schemas` 一一对应 |

### 2.4 环境实测结论（本次探测所得，影响实施方式）

| 项 | 结论 |
|---|---|
| Python | 本机 **3.14.6**（`D:\soft\Miniconda`）；无 3.12 |
| 依赖栈 | 全部**预编译 wheel** 安装成功：fastapi 0.141.1 / pydantic 2.13.5 / pydantic-settings 2.15.0 / SQLAlchemy 2.0.54 / redis 8.1.0 / httpx 0.28.1 / alembic 1.20.0 / pytest 9.1.1 / import-linter 2.15 / ruff 0.16.7 / mypy 2.3.1 / cryptography 50.0.1 / pillow 12.3.0 / PyMySQL 1.2.0 |
| 可行性冒烟 | 启动四校验 4/4、`GET /health` 200、**分层契约「违规 → `False`、移除 → `True`」**、AST 扫描检出违规且不误报 —— **全部通过** |
| MySQL | **8.0.35** 可用（`D:\soft\mysql`）；服务壳打不开，以 `mysqld` 直启进程可用 |
| 测试库 | `aicore_test`，账号 `aicore_dev`（仅该库 ALL + 全局 USAGE），**建表权限与 `information_schema` 读取已实测** |
| Redis | **未安装**（影响见 §7 的 V4/V5） |
| Docker | **未安装** |

### 2.5 本次实读发现的三处文档缺陷（必须在实现期规避）

| # | 缺陷 | 处置 |
|---|---|---|
| **F1** | `design.md` L252 与 `tasks.md` 2.3 写「`429` 限流」，但 `_common/openapi.yaml` 的 `ErrorCode` 枚举**没有 429**（`429` 是 HTTP 状态码）。最接近的业务码是 `2004 # 请求过于频繁` | **按接口文档写**：业务码用 **`2004`**；HTTP 状态码另按语义给（限流场景 429） |
| **F2** | `design.md` 未写明**成功码**，实现时极易写成 `200`（非平台口径） | **成功码 = `0`**（`_common` L122 已写死，前端按 `code === 0` 判断） |
| **F3** | 内部 Token 的**请求头名全平台无定义**（PDD L1429 仅称「内部 Token」；`aicore/docs/openapi.yaml` L1097/L1173 描述里提及但未定义 securityScheme） | 定名 **`X-Internal-Token`** 并**补写进 `aicore/docs/openapi.yaml` 的 securityScheme**（理由：PROFILE 侧要按同一名字调用，不写进接口文档两服务必然对不上） |

> 另注：`er.md` §6.10 与 §5.7 提到「令牌桶（Redis）… 限流（429，成本护栏）」，同样属 F1 口径，一并按 `2004` 处理。

---

## 3. 第 1 组：工程骨架与分层契约（4 项）

### 3.1 工程布局（任务 1.1）

采用 **`src/` 布局**（`design.md` L118 已定档 `src/aicore/`）：

```
services/aicore/
├── pyproject.toml          依赖 + ruff / mypy / pytest / import-linter / coverage 五套工具配置
├── .gitignore              __pycache__ / .venv / *.egg-info / .pytest_cache / .import_linter_cache / .coverage
├── .env.example            环境变量模板（不含真实密钥；.env 已被根 .gitignore 覆盖）
├── src/aicore/…            见 §3.2
├── tests/…                 见 §6
└── deploy/
    ├── Dockerfile
    └── sql/{ddl,migration}/
```

**为什么用 `src/` 布局**：测试跑的是**安装后的包**而非碰巧在 cwd 里的目录，能提前暴露「漏声明依赖」「包数据缺失」
这类只在部署时才炸的问题。仓库内其余服务均为 Java（`src/main/java`），Python 无先例可对齐，故以 `design.md` 为准。

**Python 版本口径（用户已确认，记为已声明偏差）**：`requires-python = ">=3.12"`，本机 3.14.6 上开发与验证。
偏差理由：本仓库当前无 Python CI，3.12/3.14 目前均只是注解；本机无 3.12。待部署环境定档后再收紧。

### 3.2 分层目录与模块契约（任务 1.2）

严格照 `design.md` L112–153 的清单建齐，**骨架阶段只建空壳与类型签名**，不写业务逻辑：

| 层 | 文件 | 职责（一句话） |
|---|---|---|
| 组合根 | `main.py` | 应用装配与生命周期；**唯一允许注入具体实现的位置** |
| `core/` | `config.py` | Pydantic Settings 配置模型（含 prod 禁 Mock 校验） |
| | `errors.py` | 异常层次 + 错误码常量（对齐 `_common/openapi.yaml`） |
| | `envelope.py` | 统一响应信封 |
| | `trace.py` | traceId 上下文变量与传播 |
| | `logging.py` | 结构化 JSON 日志 |
| | `security.py` | 内部 Token 校验 |
| | `ratelimit.py` | Redis 令牌桶 |
| | `budget.py` | 三层成本护栏 |
| | `idgen.py` | 前缀化分布式 ID |
| | `task_runner.py` | 任务执行器内核（领取/租约/重试/线程池边界） |
| `api/` | `ocr.py` `tasks.py` `habit.py` `health.py` `deps.py` | 仅协议适配与入参校验，**不含业务判断** |
| `service/` | `ocr_service.py` `ocr_match.py` `desensitize.py` `accuracy.py` `verdict.py` `habit/{engine,decay,evidence}.py` `task/registry.py` | 业务编排，可编排多 provider / 多 repository |
| `provider/` | `base.py` `selector.py` `mock.py` `{deepseek,cloud_vision,cloud_ocr}.py` | 外部模型通道边界，**唯一允许发起外部模型调用的层** |
| `repository/` | `models.py` `base.py` `sharding.py` `session.py` `task_repo.py` `ocr_repo.py` `correction_repo.py` `verdict_repo.py` | 自有库数据访问 |
| `port/` | `cred.py` `dash.py` `events.py` | 跨服务出向端口（回写外部权威数据） |

> `core/ratelimit.py` / `budget.py` / `security.py` / `task_runner.py` 与 `port/` 的**行为**在第 4 组起实现；
> 第 1 组**只建模块与签名**，保证分层规则从第一天起可检查。

### 3.3 分层依赖规则固化为检查（任务 1.3）

`design.md` L164–171 的 6 条禁止项，逐条对应一条自动化检查：

| # | 禁止项 | 固化手段 |
|---|---|---|
| 1 | `api/` MUST NOT 直接导入 `repository/` 或 `provider/` | import-linter `forbidden` 契约 |
| 2 | `service/` MUST NOT 导入任何具体 Provider 实现，只依赖 `provider/base.py` 的 Protocol | import-linter `forbidden` 契约（放行表达式**必须用递归通配**，见下） |
| 3 | `repository/` 与 `provider/` MUST NOT 导入 `service/` | import-linter `forbidden` 契约 |
| 4 | `core/` MUST NOT 导入任何业务层（`api/` / `service/` / `provider/` / `repository/` / `port/`） | import-linter `forbidden` 契约 |
| 5 | 只有 `provider/` 下的模块可发起外部模型 HTTP 调用 | AST 扫描断言（`httpx` 调用点） |
| 6 | `service/desensitize.py` 与 `service/verdict.py` MUST NOT 出现「异常后继续执行」的分支 | AST 扫描断言 |

**规则 2 的放行表达式必须写递归通配 `aicore.service.**`（2026-09-17 实测修正）**：
`ignore_imports` 中的 importer 名若写成非通配的 `aicore.service`，**只精确匹配该模块自身、不覆盖子模块**
（grimp 3.17 实测：非通配 0 命中、`.*` 与 `.**` 命中）。而 service 的代码都在子模块里
（`service/desensitize.py` 等），故非通配写法是一条**永远失效的放行声明**，会让契约整体失败。
另须设 `unmatched_ignore_imports_alerting = warn` —— `forbidden` 契约默认 `error`，
放行表达式匹配不到真实导入即判失败，会使空壳阶段的干净代码正例直接变红；
设 `warn` 后正例通过，且放行写错时仍留警告线索，不至于静默失效。

**规则 4 补入 `api/`（2026-09-17）**：原文只列 `service` / `provider` / `repository`，
漏了 `api` —— `api` 同属业务层，且分层图（`api → service`）意味着 `core → api` 会成环。
实测补入 `aicore.api` 后干净代码仍 4 kept、注入 `core → api` 被抓、
且 `service → provider.mock` 的防线未被削弱。

**为什么规则 5、6 不用 import-linter**：它只能表达「模块 A 不导入模块 B」，表达不了「某个包内不得出现某类调用」
与「`except` 块不得静默放行」。后两者恰是**合规红线**（D4 脱敏失败即拒绝、D5 无人工结论不回写），
不能靠评审约定，必须可执行。

**规则 6 的取向：偏严 + 显式豁免**（用户已确认）。AST 扫描 `ExceptHandler` 中是否存在 `raise`；
不含 `raise` 即判违规。误报（如 `except: return default` 的合法场景）由**显式豁免注释**处理——
宁可让人解释一次，也不要它悄悄漏掉。

**豁免指令的正式写法：`# ai-allow-swallow: <理由>`（理由必填）**（2026-09-17 实测确定）。
早期的 `# noqa: ai-allow-swallow: <理由>` 写法**语法上仍被扫描接受**，但会让 ruff 把
`ai-allow-swallow` 当成一个 noqa 规则码，**每次使用都打印 `Invalid # noqa directive` 警告**
（实测 7 种变体，无一能既保留 `noqa:` 前缀又不告警），故正式口径改为不带前缀的写法，
旧写法保留兼容以免既有文档失效。

**规则 6 的已知边界（有意接受，非遗漏）**：
① **不下降进嵌套作用域** —— 处理器体内嵌 `def` / `lambda` / `class` 里的 `raise` **不**算该处理器抛异常，
因为那种 `raise` 在处理器自身的控制流中并不会终止它；这是"偏严"取向的必然结果。
② **条件重抛被接受** —— `if strict: raise` 后接 `return` 不判违规（代价：极少数真实漏判）。
③ 扫描以 `ExceptHandler` 为单位，多层 `try` 各自独立判定。

**契约的传递语义必须显式声明（2026-09-17 实测）**：`forbidden` 契约默认 `allow_indirect_imports = False`，
会沿调用链报出**传递**依赖——实测在「`api` 只导入 `service`、`service` 只导入 `repository`」
（无任何 `api → repository` 直接导入）的树上，默认配置判 **BROKEN** 并打印传递链；
加 `allow_indirect_imports = true` 后正确放行。故 `api-no-repo-provider` 必须显式声明
`allow_indirect_imports = true`：它的契约名写的就是「不得**直接**依赖」，而 `api → service → repository`
正是本设计要的分层路径。若不声明，待后续任务落地真实导入，检查会对**正确架构**误报。

**固化为检查的验收方式**：**阴性用例**。故意引入一处违规导入 → 检查必须失败；移除 → 必须通过。
只写「规则存在」不算数，须证明它会响。

### 3.4 `main.py` 组合根与应用装配（任务 1.4）

生命周期钩子、路由挂载、依赖注入装配点。第 1 组仅挂 `GET /health` 返回 200。
验收：应用可启动、`GET /health` = 200、**重复装配不产生重复注册**。

---

## 4. 第 2 组：配置与横切关注点（6 项）

### 4.1 配置模型（任务 2.1，`core/config.py`）

Pydantic Settings，`env: dev | test | prod` 三套。

**两条强取向**：
1. **必填项一律不给默认值**（`design.md` L250）：默认值会把配置错误隐藏到运行时。
2. **未识别的配置项必须报错**，而非默默忽略——防止「以为配了其实没配」。

> **第 2 条不能只靠 `extra="forbid"` 实现（2026-09-17 实测）**：`pydantic-settings` 2.15 的
> `EnvSettingsSource` **没有 extra 分支**，未识别的 `AICORE_*` 环境变量会被**静默忽略**——
> 实测：裸 `BaseSettings` 加 `extra="forbid"` 后设置 `PROBE_UNKNOWN_VAR`，构造仍然成功、无任何告警。
> 也就是说照字面写 `extra="forbid"` 会让本条**看起来实现、实际落空**，且因静默而无迹可循。
> 实现须把未识别的环境变量**显式交给** `extra` 校验（本项目做法：自定义一个
> `PydanticBaseSettingsSource` 子类挂进 `settings_customise_sources`，见 `core/config.py`），
> 并用**阴性用例**守住（注入 `AICORE_TYPO_FIELD` → 必须抛 `ValidationError`）。
>
> 另注意 `ValidationError.input` 会**携带其它字段的原始值（含 `mysql_password`）**，
> 故生成启动拒绝信息时**只能取 `loc` / `msg`**；同理 `repr(Settings)` 含口令，
> 启动日志一律走不含口令的 `mysql_dsn`。

新增依赖：**`structlog`**（PDD L1747 指定的 Python 侧日志库，探测时未装）。

### 4.2 启动四条校验（任务 2.2）

分两层落，机制已实测可达：

| 规则 | 实现位置 | 实测 |
|---|---|---|
| `prod` + `mock` → 拒绝启动 | 跨字段校验 | 拒绝 ✓ |
| 真实通道被选中但密钥缺失 → 拒绝启动 | 跨字段校验 | 拒绝 ✓ |
| `dev` / `test` 允许降级 `mock` 并告警（不阻断） | 跨字段校验 | 放行 ✓ |
| 必填项缺失 → 拒绝启动且**不兜默认值** | 字段级校验 | 拒绝 ✓ |

**字段级错误与跨字段规则错误分开报告**——运维排查时最忌「配置到底哪错了」说不清。

### 4.3 异常层次与错误码映射（任务 2.3，`core/errors.py`）

| 异常类 | 业务码 | 语义 | 来源 |
|---|---|---|---|
| `ParamError` | `1001` / `1002` / `1003` | 参数缺失 / 格式错 / 枚举非法 | `_common` L153–155 |
| `UnauthorizedError` | `2001` | 未登录 / Token 失效 | L156 |
| `ForbiddenError` | `2002` | 越权（跨账号查任务，spec L25/L35） | L157 |
| `RateLimitedError` | **`2004`** | 请求过于频繁 | L159（**修正 F1**） |
| `NotFoundError` | `3006` | 对象不存在 | L165 |
| `ChannelFailureError` | `4003` | 大模型 / 视觉 API 失败 | L173 |
| `DependencyTimeoutError` | `5002` | 依赖超时 / 熔断 | L177 |
| 兜底 | `5000` | 内部错误（**堆栈只进日志**） | L175 |

**比 `design.md` 原文多两个码，理由**：
- `2001`：任务 10.3 要求「不接受终端 JWT」，拒绝时必须有个码——原设计未给，缺失会导致内部鉴权失败无法表达。
- `1001~1003`：FastAPI 请求校验失败默认返回 **422 + 框架自有格式**，必须收编为平台信封，否则前端拿到两套格式。

### 4.4 统一信封（任务 2.4，`core/envelope.py`）

严格按 §2.1 的四必填字段（`code` / `message` / `traceId` / `timestamp`），`data` 可选。

**落地方式：响应模型显式声明**（每个路由标注 `response_model=Envelope[XxxResult]`），
**不用全局中间件包响应**。理由：中间件会把 `/health`、`/metrics` 一并包住，
而这两个端点必须是裸的，否则存活探针与 Prometheus 抓取都会失效。

**成功码 = `0`**（F2 修正）。

### 4.5 traceId 传播（任务 2.5，`core/trace.py`）

- 从 **`X-Request-Id`** 读取（§2.2）；缺失时**自行生成 16 位 hex**
  （对齐 `_common` 示例 `3f2a1b9c8d7e6f50`），且**生成行为在日志中可区分**（加标记字段），
  以免掩盖网关故障——`design.md` L254 的明确要求。
- 存于 `ContextVar`。**跨线程池必须显式 `copy_context()`**：
  `run_in_executor` 会丢上下文，这是典型的静默故障（表现为「部分日志没有 traceId」），故必须有用例。

### 4.6 结构化日志（任务 2.6，`core/logging.py`）

`structlog` 输出 JSON，字段名与 PDD L1747 **逐字一致**。

**`spanId` 的处理**（用户已确认）：PDD 要求日志必含 `spanId`，但 `design.md` D9 明确**不接 SkyWalking agent**
（链路追踪后端留给平台级变更）。故**输出 `spanId` 字段但值为空**——schema 完整、不假装有埋点。
待平台接入 SkyWalking 时自然填充。

### 4.7 本组验收证据

1. 四类启动组合各有断言，违规**必须抛错退出**
2. 八类异常 → 码值映射用例；未预期异常**不泄露堆栈**
3. **码值全表与 `_common/openapi.yaml` 的 `ErrorCode` 枚举逐项比对用例**（越界即失败）
4. `Envelope` 四必填字段序列化用例；**`/health` 与 `/metrics` 不被包住**的断言
5. traceId 注入 / 未注入两条路径用例 + **跨线程池传递**用例
6. 日志 schema 用例（PDD L1747 列出的 **12 项逐字比对**）
7. 仓库内 `grep` 无硬编码密钥；`.env` 被 `.gitignore` 覆盖

---

## 5. 第 3 组：数据层与分表路由（8 项）

### 5.1 DDL（任务 3.1）

`deploy/sql/ddl/` 下 **11 个文件**：

| 文件 | 内容 |
|---|---|
| `00_create_database.sql` | 建库 `aicore`（`utf8mb4`，与 `aicore_test` 分离） |
| `10_ai_task.template.sql` | 分片表**模板**，表名占位（`ai_task_YYYYMM`） |
| `11_ocr_result.template.sql` | 同上 |
| `12_ocr_correction.template.sql` | 同上 |
| `20_vision_review.sql` ~ `25_vision_qa_log.sql` | 6 张**非分片**表 |

字段与类型**严格对齐 `er.md` §6 数据字典**（9 张表逐列）。

**物理外键的落位**（依 `er.md` L317 / L350 / L361 / L375 的 FK 标注）：

| 关联 | `er.md` 口径 | 落法 |
|---|---|---|
| `ocr_correction.task_id` → `ocr_result.task_id` | 物理外键，**同月同分片** | 在**同月模板内**声明物理外键（引用当月 `ocr_result_YYYYMM`） |
| `vision_marker.review_id` → `vision_review.review_id` | 物理外键，同库不分片 | 声明物理外键 |
| `review_verdict.review_id` → `vision_review.review_id` | 1:1 物理外键 | 声明物理外键 |
| `kitchen_anomaly.review_id` → `vision_review.review_id` | 物理外键 | 声明物理外键 |
| `ocr_result.task_id` → `ai_task.task_id` | **非外键**（`er.md` §1 L45 仅标 FK 作关联语义；跨月分片表间无法建） | 逻辑关联 + 幂等补偿 |
| `review_verdict` → CRED / DASH | **非外键**（L192–193 明示逻辑关联 + 事件） | 出向端口 + 事件（第 4 组起实现） |

**分片表物理外键的代价（必须知情）**：`ai_task` / `ocr_result` / `ocr_correction` 是**高频写入**表，
同月模板内声明物理外键会在每次写入时对被引用表加共享锁。本设计**遵循 `er.md` 口径建物理外键**，
并在**建表顺序**上保证被引用表先建（当月 `ai_task` → `ocr_result` → `ocr_correction`）。
若后续压测显示写入竞争明显，按 expand-migrate-contract 移除约束、改为应用层校验——
该决策点登记在此，不在实现期临时决定。

### 5.2 SQLAlchemy 模型（任务 3.2）

SQLAlchemy 2.x 声明式、`Mapped[]` 风格（mypy 友好），字段与类型对齐 `er.md` §6。
分片表用**同一套模型类**、按物理表名动态绑定（`__table_args__` 不写死表名）。

### 5.3 分表路由（任务 3.3，`repository/sharding.py`）

- 逻辑表 + `created_at`（或 `task_id` 所在月）→ 物理表名 `xxx_YYYYMM`。
- 写入前**幂等**确保当月物理表存在（`CREATE TABLE IF NOT EXISTS` + 模板套用）。
- **超出 tasks 原文但必要的加固**：查询**未携带分片键时直接抛错**，而非退化为全表扫描。
  `er.md` §5.3 写的是「必须携带分片键下推」——只写在文档里等于没写，必须可执行。
- **禁止跨分片 JOIN / 聚合 / 事务**：由 `repository/base.py` 的守卫拒绝跨分片组合操作。

### 5.4 会话与连接池（任务 3.4，`repository/session.py`）

**同步会话 + 线程池**（`design.md` L216 已定档，理由：分表动态 SQL 直观、规避「会话跨事件循环」陷阱）。
写会话与只读会话来分离，落 `er.md` §5.5「写后立即读强制走主库」。池大小**从配置读取，不写死**。

### 5.5 Schema 迁移（任务 3.5）

Alembic 版本化迁移 + 幂等建表脚本 + 迁移钩子承接分表物理表创建，遵循 expand-migrate-contract（`er.md` §5.6）。

**DDL 与 Alembic 的分工（重要，避免结构定义写两遍）**：
- **纯 SQL DDL 是权威定义**。建新环境既可直接执行 `deploy/sql/ddl/**`，也可 `alembic upgrade head`，两条路径结果必须一致。
- **版本化迁移从 SQLAlchemy 元数据生成**，不手写第二份 DDL。
- 二者一致性由 §5.6 的三源交叉校验**强制**，而非靠人记得同步。

### 5.6 `er.md` 一致性自动比对（任务 3.6）—— 本组最值钱的一项

设计为**三源交叉校验**，而非两方比对：

```
DDL（权威）  ←→  ① SQLAlchemy 模型元数据
     ↕
er.md §6 数据字典
```

任一条边不一致即失败。**为什么加模型这一源**：tasks 原文只要求「DDL ↔ `er.md`」两方比对，
但那样**模型层写错了照样漏检**——而模型才是真正被业务代码使用的东西。
三源之后，「文档改了代码没改」「代码改了文档没改」「模型与 DDL 走偏」三类全部会被抓到。

- **无需数据库**即可跑通两源（DDL ↔ 文档、DDL ↔ 模型）——这是可离线校验的部分。
- 有 MySQL 时**叠加 `information_schema` 第三源**，验证真实库结构（本机已具备条件，见 §2.4）。

### 5.7 repository 层（任务 3.7）

四类：任务 / 结果 / 纠错 / 复核结论。事务边界依 `er.md` §5.3：
单表一事务；同分片跨表可合并；**跨分片拆为多次独立事务 + 幂等补偿**，不引入分布式事务。

### 5.8 前缀化 ID（任务 3.8，`core/idgen.py`）

**不用雪花**（`er.md` §5.4 L247 明确 AICORE 不参与雪花域）。

格式：`前缀 + UUID 去连字符后的 hex`，**总长必须 ≤32**（`er.md` 所有 ID 列均为 `varchar(32)`）。
裸 UUID 是 36 字符，超限 4 位——这是本项最容易写错的地方，故：

- 生成时**校验总长 ≤32**，超限即抛错（而非静默截断）。
- 用例：并发生成 1 万个 ID → **全量正则校验 + 去重**，并为每个前缀各验一次。

### 5.9 本组验收证据

1. DDL 在**真实 MySQL 8** 上执行成功（零错误）
2. 三源交叉比对：正常态通过；**单边改任一侧 → 失败**（三个方向各验一次）
3. 分表路由：跨月写入 / 跨月边界查询用例
4. **分片键缺失 → 抛错**用例；跨分片 JOIN / 事务 → 被拒用例
5. 会话：只读查询走只读会话；池大小随配置变化
6. 迁移：空库从零到目标结构可复现；重复执行幂等
7. ID：1 万个全过正则（总长 ≤32）且无重复

---

## 6. 测试架构（第 12 组的部分前置于第 1 组）

`design.md` L260–274 的五层测试与离线保证，**第 1 组即需具备骨架**（否则后续每项都要补测试基建）：

| 层 | 范围 | 依赖 |
|---|---|---|
| 纯函数单测 | 习惯计算引擎、衰减、证据生成、置信度分级、类目比对 | 零依赖 |
| 契约测试 | Provider Protocol、repository 接口、port 接口 | 依赖替身 |
| 仓储测试 | 分表路由、跨月边界、幂等写入 | 内存或轻量数据库 |
| 接口测试 | 路由契约、鉴权、错误码、信封 | `httpx` ASGI 传输 + 依赖替身 |
| 端到端 | 网关 → AICORE → Provider(Mock) → MySQL | `@pytest.mark.integration`，默认不执行 |

**夹具（`tests/conftest.py`）**：配置夹具（按环境覆盖）、fake provider（确定性、可注入延迟与故障）、
内存/轻量库会话、ASGI 客户端、应用装配夹具。
**测试内不出现任意 `sleep`**——等待统一走可控时钟或轮询断言，否则跨月 / 租约 / 对账类用例会变成不稳定测试。

**覆盖率口径**：`pytest --cov` 统计 `src/aicore`，门禁 **≥80%**（`DEVELOPMENT_CONSTRAINTS.md` §3 MUST）。
`main.py`（组合根）与 `provider/` 中的**真实通道骨架允许排除**——其正确性依赖真实外部服务，
用真调用刷覆盖率既花钱又不反映质量；真实通道以契约测试 + 小样测评验收。

---

## 7. 已知偏差与未验证项（诚实登记）

| # | 项 | 状态 | 处置 |
|---|---|---|---|
| **V1** | Python 3.12 字面口径 | 偏差（用户已确认） | `requires-python = ">=3.12"`，本机 3.14.6 开发；待部署环境定档后收紧 |
| **V2** | `httpx2` 未引入 | 偏差 | FastAPI 0.141 / starlette 1.6 的 `TestClient` 打弃用警告（**非致命，实测可用**）；不引入 `httpx2`，改为压制该警告并锁 `httpx` 版本——不为他人的迁移买单 |
| **V3** | `spanId` 值为空 | 有意为之 | 见 §4.6；`design.md` D9 明确不接 SkyWalking agent |
| **V4** | **Redis 依赖项未验证** | 未验证 | 本机无 Redis。第 3 组**不依赖 Redis**，故不影响本组交付；第 4 组（任务领取、限流）起需要，届时以 fake/`fakeredis` 覆盖，**真机验证待环境补齐** |
| **V5** | `httpx2`/`redis` 之外的中间件 | 未验证 | 端到端层需真实 MySQL + Redis；MySQL 已具备，Redis 缺 |
| **V6** | `PDD` §6.4.13 与 `openapi.yaml` 路径不一致 | 既有缺陷 | `/vision/review` → `/vision/reviews`、`/kitchen/anomaly` → `/kitchen/anomalies`；属任务 14.4，**本次不改**（`openapi.yaml` 是唯一可手改源） |

---

## 8. 实施顺序与交付方式

```
第 1 组（4 项）─→ 验收证据 ─→ 用户确认 ─→ 第 2 组（6 项）─→ 验收 ─→ 用户确认 ─→ 第 3 组（8 项）─→ 验收
```

- 每组结束给出**原始命令输出**（不转述），用户确认后进入下一组。
- **不动** `openspec/` 下任何工件（`design.md` / `tasks.md` / `spec.md`）：本次是**实现**，不是改计划。
  F1/F2/F3 三处文档缺陷**登记在本文件**，OpenSpec 工件留待后续轮次统一修订。
- 每组交付后按 `commit-check` 门禁检查，提交信息不带 `[AI]` 前缀。

### 8.1 环境前置（已完成）

- MySQL 以 `mysqld` **直启进程**方式运行（服务壳不可用）；测试库 `aicore_test`、账号 `aicore_dev` 已建，
  权限与建表能力实测通过。
- **凭据不入库**：`.env.example` 只放占位符；真实口令仅存于本地 `.env`（已被根 `.gitignore` 覆盖）。

### 8.2 风险

| 风险 | 缓解 |
|---|---|
| 三源交叉校验器本身写错，误报/漏报 | 每个方向各做一次**阴性用例**（单边改动必须失败） |
| ID 长度超限（裸 UUID 36 > 32） | 生成即校验 + 1 万条全量正则用例 |
| 分层规则误报导致开发绕道 | 规则 6 提供显式豁免注释；其余 5 条为结构性导入规则，无误报空间 |
| MySQL 以裸进程运行，重启后消失 | 第 3 组交付前完成验证并留取证；不依赖其长期存活 |

---

## 9. 下一步

本文档经用户评审通过后，进入 **`writing-plans`**：产出
`docs/superpowers/plans/2026-09-16-aicore-architecture.md`（逐任务实现计划：步骤、验证命令、完成判据），
再按该计划执行第 1 组。

**本文档不含任何实现代码，也不启动实现**——实现须待计划产出并被批准。
