# Task 2.6 报告：结构化 JSON 日志 + `main.py` lifespan 接线（收口第 2 组）

- **状态**：DONE_WITH_CONCERNS
- **提交**：`0ac7f5d feat(aicore): 实现结构化 JSON 日志并接线启动钩子`（3 files changed, 1296 insertions(+), 4 deletions(-)）
- **分支**：`feature/aicore-architecture`（worktree `D:\progrom\.worktrees\aicore-architecture`），父提交 `8bffbf7`
- **门禁**：pytest **378 passed / 8 skipped**（本任务新增 41 条）；ruff `All checks passed!`；mypy `Success: no issues found in 51 source files`；lint-imports `4 kept, 0 broken`；覆盖率 **96.49%**，`core/logging.py` **100%（112 语句）**
- **说明**：`.superpowers\sdd\2026-09-16-aicore-architecture\task-2.6-brief.md` **在 worktree 中不存在**（该目录只有 2.5 与 3.1 的 brief）。本报告以控制者在任务书中给出的**扩写简报**为权威口径执行。

---

## 1. 交付物（文件清单与职责）

| 文件 | 状态 | 职责 |
|---|---|---|
| `services/aicore/src/aicore/core/logging.py` | 修改（1 行 docstring 桩 → 438 行） | 结构化 JSON 日志的唯一产出点：schema 常量、事件处理器（traceId/spanId/uid/脱敏）、structlog 与 stdlib 的桥接、处理器装卸与刷盘 |
| `services/aicore/src/aicore/main.py` | 修改（+27/-4） | lifespan 启动钩子：读配置 → 失败转 `ConfigRejected`（`from None`）→ 装配日志 → 关闭刷盘 |
| `services/aicore/tests/unit/test_logging.py` | 新建（833 行 / 41 条用例） | schema、spanId 留空、逐行 JSON、traceId 来源标记、stdlib 收编、脱敏与打码、可重复配置、lifespan 接线 |

**产出的接口（后续任务按名导入）**：

```python
REQUIRED_LOG_FIELDS: frozenset[str]        # PDD §8.5.1 L1747 的 12 项必含字段（逐字）
configure_logging(settings: Settings) -> None
get_logger(module: str) -> structlog.stdlib.BoundLogger   # 惰性代理，首次调用时装配
flush_logging() -> None                    # 关闭钩子刷盘（新增，简报未列）
desensitize_uid(value: object) -> str      # uid 脱敏唯一实现（新增，简报未列）
SERVICE_NAME / DEFAULT_CODE / SPAN_ID_EMPTY / REDACTED     # schema 常量（新增）
```

**计划文本的「11 字段」是笔误**：计划与 spec 表都写「11 项」，但 PDD L1747 逐字列出的名字是 **12 个**。以 PDD 为准实现 12 项（模块 docstring 已登记该差异），用例同时与**字面量集合**比对，常量被改名/删项会立刻变红。

## 2. structlog 与 stdlib `logging` 的集成方式（规则 3 告警仍能浮出）

**不是二选一，而是让 structlog 当渲染层、stdlib 当地基**：

```
业务代码 get_logger(__name__)  ──► structlog.stdlib.LoggerFactory() ──► logging.getLogger(module)
                                        │（调用期跑 _shared_processors）
                                        └─ ProcessorFormatter.wrap_for_formatter ─┐
                                                                                 ▼
root 上的 _JsonStreamHandler ◄── ProcessorFormatter(foreign_pre_chain=_shared_processors)
   （stderr）                        processors=[remove_processors_meta, EventRenamer("message"),
                                                _order_fields, JSONRenderer]
```

关键点：**同一份 `_shared_processors` 列表同时挂在两处**——structlog 记录的调用链、stdlib 记录的 `foreign_pre_chain`。于是 `core/config.py` 里既有的 `logging.getLogger(__name__).warning(...)`（Task 2.2 规则 3）**一行不改**就获得同一 schema、同一脱敏、同一 traceId 注入。

**实测证据**（真实进程，非测试夹具；`anyio` 直接驱动 `app.router.lifespan_context`，与 uvicorn 走同一个钩子）：

```
$ .\.venv\Scripts\python.exe -   # 真实 lifespan 内：注入 traceId 后 info / error / stdlib warning 各一条
{"time": "2026-09-18T07:50:29.615444Z", "level": "INFO", "app": "aicore", "service": "aicore", "module": "aicore.service.ocr_service", "traceId": "3f2a1b9c8d7e6f50", "traceIdSource": "propagated", "spanId": "", "uid": "110***********0011", "bizType": "ocr", "opCode": "ocr.recognize", "code": 0, "message": "OCR \u8bc6\u522b\u5b8c\u6210", "confidence": 0.97, "token_count": 812}
{"time": "2026-09-18T07:50:29.615709Z", "level": "ERROR", "app": "aicore", "service": "aicore", "module": "aicore.service.ocr_service", "traceId": "3f2a1b9c8d7e6f50", "traceIdSource": "propagated", "spanId": "", "uid": "", "bizType": "ocr", "opCode": "ocr.recognize", "code": 4003, "message": "\u901a\u9053\u8c03\u7528\u5931\u8d25", "provider": "deepseek", "retry": 3, "mysql_password": "***"}
{"time": "2026-09-18T07:50:29.615888Z", "level": "WARNING", "app": "aicore", "service": "aicore", "module": "aicore.core.config", "traceId": "3f2a1b9c8d7e6f50", "traceIdSource": "propagated", "spanId": "", "uid": "", "bizType": "", "opCode": "", "code": 0, "message": "[\u544a\u8b66\uff1aenv-mock] \u6765\u81ea stdlib \u7684\u544a\u8b66\uff1amock \u901a\u9053"}
```

第 3 行就是规则 3 的告警：`module=aicore.core.config`、`level=WARNING`、12 项必含字段齐全，且**与前两条同一 schema**。用例侧由 `test_stdlib_record_is_rendered_in_the_same_schema` 与 `test_rule_three_warning_still_surfaces_in_json` 端到端钉住（后者直接构造 `dev + mock` 的 `Settings`，断言告警以 JSON 行出现且字段齐全）。

**为什么写 stderr**：stdlib `StreamHandler` 的默认目标就是 stderr；stdout 留给程序自身输出，日志不与之混流。另有一条本仓库的硬约束：`test_config_startup.py::test_mock_fallback_warning_is_assertable_via_log_not_stdout` 固化了「告警不像 `print` 那样落 stdout」。若日志写 stdout，那条既有用例会因执行顺序（`tests/api` 先触发 lifespan 装上处理器）随机变红——写 stderr 让该契约继续成立（已在 §4.4 用变异实测确认过这条耦合）。

## 3. `traceIdSource` 已经到输出（Task 2.5 遗留项的验收证据）

`_add_trace_context` 从 `core/trace.py` 取 `get_trace_id()` **与** `get_trace_source()`（单一来源，无第二份实现），写 `traceId` 与 `TRACE_SOURCE_FIELD`（`"traceIdSource"`）。两条用例**走真实请求**（`TestClient` → lifespan 真配置 → 中间件绑 header → 路由内写日志）：

| 场景 | 断言 | 结果 |
|---|---|---|
| 带 `X-Request-Id: 3f2a1b9c8d7e6f50` | `traceId == 3f2a1b9c8d7e6f50` 且 `traceIdSource == propagated` | 通过 |
| 不带请求头 | `traceId` 匹配 `^[0-9a-f]{16}$` 且 `traceIdSource == generated` | 通过 |
| 请求内的 **stdlib** 记录 | 同一个 `traceId` + `propagated` | 通过 |

上表第 1 行即「生成行为在日志中可区分」的落点：`propagated`/`generated` 现在真的出现在每一行日志里（§2 的实测第 1、3 行可见 `"traceIdSource": "propagated"`）。变异验证见 §4.3：删掉这一行写入，3 条用例立刻变红。

## 4. 验证（真实输出）

### 4.1 用例与门禁

```
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
378 passed, 8 skipped in 3.95s

$ .\.venv\Scripts\python.exe -m pytest tests/unit/test_logging.py -p no:cacheprovider
41 passed in 0.30s

$ .\.venv\Scripts\ruff.exe check . --no-cache
All checks passed!

$ .\.venv\Scripts\mypy.exe src --cache-dir .venv\mypy_cache
Success: no issues found in 51 source files

$ .\.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.

$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --cov=src/aicore --cov-report=term-missing
src\aicore\core\logging.py                   112      0   100%
src\aicore\core\config.py                    119      0   100%
src\aicore\core\trace.py                      82      0   100%
TOTAL                                        485     17    96%
Required test coverage of 80.0% reached. Total coverage: 96.49%
```

`lint-imports` 的那 1 条 warning 是 Task 1.3 已知的 `unmatched_ignore_imports_alerting = warn`，与本次改动无关。

**测试输出洁净（本任务把日志配成全局状态，故专门核过）**：整轮输出的可疑模式扫描（`Logging error` / `Traceback` / `warnings summary` / `DeprecationWarning` / `N warning`）**命中 0 条**；连续多轮运行不累积处理器（用例级夹具摘除本用例新增的处理器并还原 root 与 `aicore` 命名空间的级别）。

### 4.2 真实进程（uvicorn）

配置非法（`env=prod + provider=mock + 口令哨兵`）时拒绝启动，且异常链里没有口令：

```
$ .\.venv\Scripts\python.exe -m uvicorn aicore.main:app --port 8099     # exit 3
INFO:     Waiting for application startup.
ERROR:    Traceback (most recent call last):
  ...
  File "...\src\aicore\main.py", line 49, in lifespan
    raise ConfigRejected.from_validation_error(exc) from None
aicore.core.config.ConfigRejected: AICORE 启动配置校验未通过，进程拒绝启动（共 1 项阻断项）：
  - [跨字段：env-mock] 生产环境不允许 mock 通道：env=prod 且 provider=mock；请把 AICORE_PROVIDER 指向真实通道并配置其密钥
ERROR:    Application startup failed. Exiting.
==== 哨兵出现次数: 0 ====
```

uvicorn 确实带 `exc_info` 打印了启动失败栈（这正是 `from None` 要防的通道），而哨兵出现 **0 次**——栈停在我们的 `raise` 处，没有把原始 `ValidationError` 带出来。

配置合法时进程正常起来（`test + mock`，顺便暴露了 §6.1 的告警顺序问题）：

```
INFO:     Started server process [32708]
INFO:     Waiting for application startup.
[告警：env-mock] env=test 使用 mock 通道：模型能力为模拟实现，仅供开发与自测；生产（env=prod）会直接拒绝该组合
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8099 (Press CTRL+C to quit)

$ curl.exe -s -i -H "X-Request-Id: 3f2a1b9c8d7e6f50" http://127.0.0.1:8099/health
HTTP/1.1 200 OK
content-length: 15
x-request-id: 3f2a1b9c8d7e6f50

{"status":"ok"}
```

（该轮以 `job_kill` 强制结束，属**强杀**，故 uvicorn 的优雅关闭与 `flush_logging()` 未在该轮跑到；关闭刷盘由 `test_lifespan_flushes_logging_on_shutdown` 覆盖。端口 8099 已确认释放、无残留 python 进程、无残留文件。）

### 4.3 变异验证（证明用例有判别力，不是跟着实现一起绿）

对源码做 4 处临时变异（每次改完即跑、跑完按字节还原），结果：

| 变异 | 预期变红点 | 实测失败 |
|---|---|---|
| M1 去掉 `traceIdSource` 写入 | 3 条 traceId 来源用例 | **3 条**（propagated / generated / stdlib 各 1） |
| M2 `desensitize_uid` 退化为原样返回 | 证件号用例 + 脱敏参数化用例 | **4 条**（证件号 1 + 参数化 3） |
| M4 `from None` 改成 `from exc` | 启动拒绝用例的 `__cause__ is None` | **1 条** |
| M3 去掉「先摘旧处理器」 | 重复配置的 2 条用例 | **2 条**，并在整套运行时放大了 23 条（旧处理器与新处理器同时输出，所有「恰好一条记录」的断言全部变红） |

```
$ # M1+M2+M4 同时生效（M3 已还原）——失败集合恰好等于三者之和，无级联
8 failed, 366 passed, 8 skipped
```

变异还原后逐文件校验 sha256，与变异前**完全一致**（无残留）：

```
c96161bd5b79e35519ffb5363b056d2ac52b4e344e8744163677b425bcd91c1b  core/logging.py
c811a12369c4f549746d0b81a628892858824613155c10ddc3e5662c0dbd883f  main.py
968aad2c16ebbbf1262342ef37c9c65dbf2ff66af1fafd35ad2b94c7fb7f76b5  tests/unit/test_logging.py
```

### 4.4 自查发现的一个真实缺陷（由本任务用例抓出）

`test_error_record_with_traceback_stays_one_json_line` 第一次跑就变红：`logger.exception(...)` 产出的 `level` 是 **`EXCEPTION`**，而平台级别词表（SLF4J：TRACE/DEBUG/INFO/WARN/ERROR）里没有这个词——采集侧按级别过滤会把这类错误日志**整批漏掉**。根因是 `_add_log_level` 自己 uppercase 方法名，漏了 structlog 的别名归一。修法：改调 `structlog.stdlib.add_log_level`（structlog 自 24.1 起把 `exception`→`error`、`warn`→`warning`）后只做大写转换，不另写会漂移的别名表。现已由「带堆栈的记录」用例（断言 `level == "ERROR"`）与 `warn` 参数化用例双向钉住。

## 5. 提交门禁（`--no-verify` 已获授权：沙箱内无 `sh`）

逐条手工复刻 `.githooks/pre-commit`：

| hook 检查 | 结果 |
|---|---|
| 1) 新增行含合并冲突标记 | 命中 **0** |
| 2) `git diff --cached --check`（行尾空白 / 末尾多余空行） | 空（干净） |
| 3) 新增大文件 >1MB | 最大 36,011 字节（test_logging.py），ok |
| 4) 私钥块 / `AKIA` / `ASIA` | 命中 **0** |
| 5) 疑似硬编码凭据正则 | 命中 2 行，**确认为测试 fixture 误报**（见下） |
| 6) 提交真实 `.env*`（仅允许 `.env.example`） | 命中 **0** |

第 5 项的两行是 `mysql_password=PASSWORD_SENTINEL,` 与 `deepseek_api_key=CHANNEL_KEY_SENTINEL,`——它们是**脱敏用例的输入**，值本身在文件内声明为一眼假的哨兵（`SENTINEL_PASSWORD_DO_NOT_LEAK` 等），且同一字符串**已存在于 HEAD**（`tests/unit/test_config_startup.py:37`），用例断言的正是「这两个值绝不出现在日志输出里」。hook 提示允许对测试 fixture 误报确认后提交，此处据实确认并登记。

`.githooks/commit-msg`：`feat(aicore): 实现结构化 JSON 日志并接线启动钩子` 匹配 `^(feat|fix|…)(\([^)]*\))?: .+`；subject 中文、type 英文；无 `[AI]` 前缀，未加 trailer（与仓库既有 17 个提交及 Task 2.5 的先例一致）。

另核：三个文件的 `git hash-object --path=<f> <f>` 与 `git rev-parse :<f>` **逐一相等**，确认 `core.autocrlf=true` 下入库 blob 为 LF、未被改写成 CRLF。

`commit-check` 技能清单 A–F 逐项自查：A 格式合规、单一目的（仅本任务 3 文件）；B 无真实密钥/大文件/`.env`；C 行尾干净、标识符英文、注释中文；D 日志本身即本任务的防御对象（不打码即用例变红）；E 关键安全逻辑（不落敏感信息、异常链不泄漏）有 41 条用例、`core/logging.py` 100% 覆盖；F 无冲突标记。

## 6. 自查发现与关注点

### 6.1 启动首行告警仍是纯文本（顺序性缺口，需控制者裁定）

实测（§4.2 第二次 uvicorn 运行）：`[告警：env-mock] …` 以**纯文本**打在 stderr，且出现在 `Application startup complete` 之前。原因不是漏接线，而是**顺序本身就是简报钉死的**：`get_settings()` 在 `configure_logging()` 之前，而规则 3 的告警在 `Settings(...)` 构造瞬间发出，此时 JSON 处理器还没装（生产下 root 无处理器 → `logging.lastResort` 兜底成纯文本）。

- **影响**：dev/test 降级 mock 时，进程的**第一行日志不合 schema**（采集侧按 JSON 解析会丢掉这一行）。
- **建议修法（未实施，属超出简报给定顺序的改动）**：lifespan 里先装一个「引导配置」（默认 INFO + `app=aicore`）再读配置，读到后再 `configure_logging(settings)` 覆盖——`configure_logging` 本身可重复调用，代价只是启动期多一次装卸。
- **为什么不自行实施**：简报明确「On startup: 1. `get_settings()` 2. Then `configure_logging(settings)`」并要求「不要发明后续分组负责的生命周期工作」。此项属设计层取舍，请控制者裁定后由后续小任务落地（或改 `core/config.py` 把告警延后到首次取用时）。

### 6.2 `uid` 脱敏的边界（有意划定）

处理器只对 **schema 里的 `uid` 字段**做脱敏，并对**密钥类字段名**（精确名 + `*_password` / `*_token` / `*_secret` / `*_api_key` 后缀）打码。**不按取值内容扫描**（如「任意字段里的 18 位身份证号」）——那是 PDD L1749 所说的脱敏组件（正则 + 实体识别）的职责，在日志模块重复实现会造出第二套会漂移的口径。因此：**把证件号塞进 `message` 或自定义字段仍然会落盘**，防线是「业务代码只传结构化字段」这条规矩。建议 Task 4 的 `service/desensitize.py` 落地后，由组合根把它的正则/实体识别接成一个处理器（挂点已留好：`_shared_processors`）。

### 6.3 其他值得记录的决定

1. **中文以 `\uXXXX` 转义**（`JSONRenderer(ensure_ascii=True)`）：stderr 在非 UTF-8 代码页（本机 cp936）下会把裸中文按 GBK 编码，UTF-8 采集器拿到的是**非法字节序列**（整行丢失，而非只是乱码）。纯 ASCII 输出没有这个依赖，JSON 解析器会还原中文。代价：人眼看日志要过一层转义。
2. **级别设在 `aicore` 命名空间而非 root**：root 的级别会连带打开第三方库的 INFO——**实测** httpx 的 INFO 会把完整请求 URL（含 query 里的用户输入）写进日志，`test_errors.py::test_validation_log_keeps_types_but_not_user_input` 当场变红。处理器仍挂 root，故第三方库的 WARNING 及以上照样进同一 schema（`test_log_level_is_scoped_to_the_service_namespace` 双向钉住）。
3. **`WARNING` vs `WARN` 的双语言字面量**：PDD 只钉了字段名 `level`，没钉取值词表。本服务取 Python 口径（`WARNING`），并在两路径间保持一致；主站 Logback 的 `%level` 输出是 `WARN`。若平台要求两侧字面量对齐，属平台级裁定，届时应两侧同改（模块 docstring 已登记）。
4. **`_JsonStreamHandler` 惰性解析 `sys.stderr`**：pytest 的 capsys/capfd 会在用例结束**关闭**被替换的流；构造时抓引用会在后续写日志时抛 `ValueError` 并打印 `--- Logging error ---` 污染输出。实测多轮运行无此噪音。
5. **`cache_logger_on_first_use=False`**：本函数允许重复调用（测试隔离、配置重载），缓存会让已建日志器继续用旧配置。代价是每次调用多一次装配开销，换取可重配置性。
6. **`main.py` 在覆盖率 `omit` 名单里**：lifespan 的 4 行不计入覆盖率，但仍由 4 条用例（含真实 uvicorn 拒绝启动）行为覆盖；未因此调整 omit 配置。
7. **`level` 的 `code` 默认值取 0**（平台码表的成功码）：字段必须永不为空，而未传错误码的非错误路径用 0 最符合码表语义；任务 §6.2 的错误码由调用方显式传入（用例已覆盖 4003 透传）。

### 6.4 与既有测试的耦合（已实测，未削弱任何断言）

`configure_logging` 是全局状态，`client` 夹具进上下文即触发 lifespan 配置。实测整套 378 条用例全绿且输出洁净；其中 `test_config_startup.py` 那条「告警不落 stdout」的断言正是选择 stderr 的原因之一（§2）。本任务**没有修改任何既有测试**。

## 7. 交接与后续

1. **业务代码的入口**：`from aicore.core.logging import get_logger; _logger = get_logger(__name__)`；只传结构化字段（`bizType` / `opCode` / `code` / `uid` / 业务键），MUST NOT 拼字符串。
2. **Task 3.x 起的 ERROR 日志**已自动带 `exception` 字段（堆栈压在一行内，采集侧按行解析不受影响），无需额外处理。
3. **待接的处理器挂点**：`_shared_processors(app)` 一行即可挂入脱敏组件（§6.2）；`traceIdSource` 之外若再要 `spanId` 有值，需先落地 SkyWalking 接入（D9 变更）。
4. **待控制者裁定**：§6.1 的启动首行告警顺序缺口、§6.3.3 的 `WARNING`/`WARN` 双语言口径。

---

# 修复轮 1（启动首行非 JSON）

- **状态**：DONE
- **提交**：`fdd7ee3 fix(aicore): 启动首行日志改为引导配置下的 JSON`（3 files changed, 420 insertions(+), 43 deletions(-)）
- **分支 / worktree**：`feature/aicore-architecture`（`D:\progrom\.worktrees\aicore-architecture`），父提交 `0ac7f5d`
- **门禁**：pytest **387 passed / 8 skipped**（本轮 `test_logging.py` 41 → 50 条，新增 9 条）；ruff `All checks passed!`；mypy `Success: no issues found in 51 source files`；lint-imports **4 kept, 0 broken**；覆盖率 **96.56%**，`core/logging.py` **100%（121 语句）**

## 1. 问题（控制者裁定：修）

原顺序是「读配置 → 装配日志」，而 `core/config.py` 规则 3 的告警（dev/test + `provider=mock`）在 `Settings(...)` **构造瞬间**发出——那时 root 上还没有 JSON 处理器，这一行落到 `logging.lastResort` 上变成**纯文本**。真实进程实测——下面是**同一份 dev+mock 配置**下的对照，修复前（把 `bootstrap_logging()` 临时删掉的变异体，见 §4.1）首行是纯文本：

```
INFO:     Started server process [32212]
INFO:     Waiting for application startup.
[告警：env-mock] env=dev 使用 mock 通道：模型能力为模拟实现，仅供开发与自测；生产（env=prod）会直接拒绝该组合   ← 不是 JSON
INFO:     Application startup complete.
```

采集侧按 JSON 解析会把这一行整行丢掉——正是「统一结构化日志」要防的漏。

## 2. 改动（3 文件）

### 2.1 `core/logging.py`（+100/-31）

新增**引导配置**，与正式配置**共用同一套装配路径**（这是修复的实质：不是「另一种 JSON」，而是同一种 schema）。

| 新增符号 | 职责 |
|---|---|
| `bootstrap_logging() -> None` | 不依赖配置的引导装配：`BOOTSTRAP_LOG_LEVEL` + `DEFAULT_APP_NAME` |
| `BOOTSTRAP_LOG_LEVEL = "INFO"` | **引导默认级别**（正式级别在 `AICORE_LOG_LEVEL`，第二步生效）。取 `INFO` 而非 `DEBUG`：引导阶段只有启动校验的告警会说话，`INFO` 收得住又不会把正常启动刷成噪音 |
| `DEFAULT_APP_NAME = SERVICE_NAME`（即 `"aicore"`） | 引导写进 `app` 字段的部署名。引导**读不到配置**，只能取固定值；**代价已登记**：部署改 `AICORE_APP_NAME` 时，头几行仍写 `aicore`（有意取舍：宁可口径在头几行不同，也不让首行缺字段或非 JSON） |
| `_assemble_handler(shared, level)` | 正式/引导**唯一**的处理器装配点 |
| `_apply_json_logging(app, level)` | 两段配置**唯一**的落地动作（structlog 全局配置 + root 处理器 + 服务命名空间级别），全程不读配置 |

关键不变量逐条保住：① 「先摘旧的、再挂新的」在 `_apply_json_logging` 里，故「引导 + 正式」不会双份；② 级别仍只落在 `aicore` 命名空间（不动 root）；③ `_assemble_handler` 与 `_shared_processors` 共用，两段配置的**字段集合逐字相同**，只有 `app`/`level` 的**取值**可能不同。

（顺带把 `_iter_installed_handlers()` 的返回类型从 `logging.Handler` 收窄为 `_JsonStreamHandler`，让 `flush_logging` 的调用点在 mypy strict 下类型精确；无行为变化。）

### 2.2 `main.py`（+26/-7）：lifespan 改成三段顺序

```python
bootstrap_logging()                     # ① 不读配置，故能在读配置之前跑
try:
    settings = get_settings()           # ② 读配置（此刻告警已是 JSON）
except ValidationError as exc:
    rejected = ConfigRejected.from_validation_error(exc)
    _logger.error("%s", rejected)       # ③ 拒绝路径也留下结构化 ERROR 记录
    raise rejected from None            #    from None 保持不变（密钥安全）
configure_logging(settings)             # ④ 用配置覆盖引导默认值
yield
flush_logging()
```

**`create_app()` 仍是纯装配函数**：引导配置只在 lifespan 里，工厂既没读配置也没装日志（既有两条「清空 `AICORE_*` 仍可建实例」的用例继续守住）。

**为什么拒绝路径新增一条 ERROR 日志（本轮唯一的行为扩展，请控制者复核）**：验收要求「被拒绝的启动也必须输出 JSON」，而实测发现拒绝路径**一行我们自己的日志都没有**——`Settings` 的告警只在**放行**的组合上发（`core/config.py` 的取向：已拒绝的配置不值得再对降级行为告警），于是「拒绝启动」这件事只存在于 uvicorn 的**明文 stderr 栈**里，从不进平台的 JSON 管线。补一条 `_logger.error("%s", rejected)` 让采集器看得见启动拒绝；记录内容与异常消息**同源**（`str(ConfigRejected)`，只含字段名 / 环境变量名 / 阈值数字），故不含任何配置取值，`from None` 的密钥安全保证原样覆盖它。若控制者认为「拒绝路径不写日志」才是想要的语义，删掉那一行即可，其余部分不受影响（用例 `test_rejected_startup_still_logs_json` 需同步调整）。

### 2.3 `tests/unit/test_logging.py`（+294/-5，41 → 50 条）

新增 9 条，全部先红后绿地钉住修复（见 §4.2 的变异实测）：

| 用例 | 钉住什么 |
|---|---|
| `test_bootstrap_emits_json_before_any_settings_are_read` | **不构造任何 `Settings`** 时输出已是 12 字段齐全的 JSON |
| `test_bootstrap_writes_to_the_same_schema_as_the_full_configuration` | 两段配置的**字段集合逐字相同**（只允许 `app` 取值不同） |
| `test_bootstrap_then_configure_does_not_double_emit` | 「引导 + 正式」每行只输出一份、root 只留一个处理器 |
| `test_repeated_bootstrap_installs_exactly_one_handler` | 「引导 + 引导」幂等 |
| `test_bootstrap_after_configure_is_idempotent_too` | 反序（正式 + 引导）也幂等，且「后配置者说了算」 |
| `test_bootstrap_default_level_does_not_silence_json_errors` | 引导级别 `INFO` 收得住告警；**不动 root 级别** |
| `test_startup_first_emitted_line_is_json_with_every_mandated_field` | 真实 lifespan + `dev + mock`：输出**每一行**都可 `json.loads`，且**首行**就是规则 3 告警、字段齐全 |
| `test_rejected_startup_still_logs_json` | 拒绝启动：异常仍是 `ConfigRejected`、`from None` 仍成立、输出逐行 JSON、ERROR 记录含阻断项且无口令哨兵 |
| `test_logging_survives_a_rejected_startup` | 拒绝之后日志管线没被拆坏：改成放行环境重启，首行仍是完整 schema 的 JSON |

**修改的既有用例（1 条，未削弱任何断言）**：`test_request_trace_id_is_carried_into_stdlib_records_too` 原先断言「`core/config.py` 日志器**整个模块**只有一条记录」。修复后规则 3 的告警真的进了 JSON，与它的探针记录同模块——该断言原本把「告警没进 JSON」当成了前提。现改为按消息来源收窄（只取 `[告警：探针]` 那条），三条断言的强度不变，且不再依赖那个缺陷。

## 3. 验收证据（真实 uvicorn 进程，端口 8083）

探针脚本一次性存在沙箱临时目录（`aicore_fix_round_probe.py`，仓库内无残留）：真实 `python -m uvicorn aicore.main:app`，cwd 指向一份临时 `.env`，`stderr`+`stdout` 合并落盘后**逐行**分类。

### 3.1 dev + `provider=mock`（触发规则 3 告警）

（`main.py` / `logging.py` 在本轮定稿后**未再改动**——后续编辑只落在用例文件，故此轮输出对提交内容 `fdd7ee3` 有效；§4.2 的变异跑在同一份文件上并已按 sha256 还原。）

```
$ python aicore_fix_round_probe.py <temp>\aicore_fix_round_dev <temp>\aicore_fix_round_dev.log
HTTP 200 X-Request-Id=3f2a1b9c8d7e6f50 body={"status":"ok"}
TOTAL_LINES=6 JSON_LINES=1 PLAIN_TEXT_LINES=5
--- 以 { 开头的行逐行解析 ---
[0] PARSED level=WARNING module=aicore.core.config app=aicore MISSING=NONE
--- 非 JSON 行（应只有框架自身的日志） ---
INFO:     Started server process [5928]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8083 (Press CTRL+C to quit)
INFO:     127.0.0.1:64412 - "GET /health HTTP/1.1" 200 OK
JSON_LINES_WITH_ALL_MANDATED_FIELDS=1/1
```

原文前 6 行（**保持原顺序**）：

```
INFO:     Started server process [5928]
INFO:     Waiting for application startup.
{"time": "2026-09-18T08:00:43.914399Z", "level": "WARNING", "app": "aicore", "service": "aicore", "module": "aicore.core.config", "traceId": "22a7e64934d79ed2", "traceIdSource": "generated", "spanId": "", "uid": "", "bizType": "", "opCode": "", "code": 0, "message": "[\u544a\u8b66\uff1aenv-mock] env=dev \u4f7f\u7528 mock \u901a\u9053\uff1a\u6a21\u578b\u80fd\u529b\u4e3a\u6a21\u62df\u5b9e\u73b0\uff0c\u4ec5\u4f9b\u5f00\u53d1\u4e0e\u81ea\u6d4b\uff1b\u751f\u4ea7\uff08env=prod\uff09\u4f1a\u76f4\u63a5\u62d2\u7edd\u8be5\u7ec4\u5408"}
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8083 (Press CTRL+C to quit)
INFO:     127.0.0.1:64412 - "GET /health HTTP/1.1" 200 OK
```

**判读**：应用在 lifespan 内写出的**唯一**一行日志就是规则 3 的告警，它出现在 `Application startup complete.` **之前**（即「启动首行」的位置），是 12 项必含字段齐全的 JSON（`message` 解转义后为 `[告警：env-mock] env=dev 使用 mock 通道：…`）。其余 5 行明文全部是 **uvicorn 框架自身**的日志（`INFO: Started server process` / `Waiting for application startup.` 等）——它们不经过本服务的 `logging` 配置，属框架输出，不在「平台结构化日志」范围内。

### 3.2 被拒绝的启动（dev + mock + 预算阈值颠倒）

（这一轮跑的是**加上拒绝路径 ERROR 记录之后**的最终代码；§5 的门禁也在同一份代码上复跑。）

```
$ python aicore_fix_round_probe.py <temp>\aicore_fix_round_reject <temp>\aicore_fix_round_reject.log 15
HTTP: NO RESPONSE (服务未起来)
EXIT_CODE=3
TOTAL_LINES=23 JSON_LINES=1 PLAIN_TEXT_LINES=21
[0] PARSED level=ERROR module=aicore.main app=aicore MISSING=NONE
JSON_LINES_WITH_ALL_MANDATED_FIELDS=1/1
```

我们写出的那一行（原文顺序：紧随 `Waiting for application startup.`，在 uvicorn 的失败栈之前）：

```
{"time": "2026-09-18T08:01:51.305705Z", "level": "ERROR", "app": "aicore", "service": "aicore", "module": "aicore.main", "traceId": "8e05b72f5dd7969d", "traceIdSource": "generated", "spanId": "", "uid": "", "bizType": "", "opCode": "", "code": 0, "message": "AICORE \u542f\u52a8\u914d\u7f6e\u6821\u9a8c\u672a\u901a\u8fc7\uff0c\u8fdb\u7a0b\u62d2\u7edd\u542f\u52a8\uff08\u5171 1 \u9879\u963b\u65ad\u9879\uff09\uff1a\n  - [\u8de8\u5b57\u6bb5\uff1abudget-order] \u9884\u7b97\u9608\u503c\u987a\u5e8f\u98a0\u5012\uff1abudget_degrade_ratio=0.5 \u4f4e\u4e8e budget_alert_ratio=0.8\uff1b\u964d\u7ea7\u9608\u503c\u5fc5\u987b\u4e0d\u5c0f\u4e8e\u544a\u8b66\u9608\u503c\uff0c\u5426\u5219\u4f1a\u5148\u964d\u7ea7\u3001\u540e\u544a\u8b66\n  \u540c\u4e00\u73af\u5883\u7684\u963b\u65ad\u9879\u5df2\u4e00\u6b21\u6027\u5217\u5168\uff1b\u6309\u4e0a\u8ff0\u9010\u9879\u4fee\u6b63\u540e\u91cd\u542f\u5373\u53ef\u3002"}
```

**判读**：拒绝路径上我们自己的输出是**一行 JSON ERROR**（阻断项清单连同换行一起转义在一行内，`code=0`——平台码表里没有「启动配置拒绝」这一项，未凭空造码）。其余 21 行明文全部来自 uvicorn 渲染 `ConfigRejected` 的启动失败栈（框架的 stderr 明文输出，不进本服务的日志管线），栈里 `raise rejected from None` 可见、且**没有** `ValidationError` 的 `input_value`。

## 4. 证明修复真的生效

### 4.1 变异：把顺序改回修复前（真实进程）

临时删掉 lifespan 里的 `bootstrap_logging()`（其余不动），跑同一份 dev+mock 配置：

```
BASELINE_SHA256=494ee2512428169216b0c88908f9b00d8f49b986f3ec7f4ab3d839cff45823b2 LEN=6079
MUTATED_SHA256=b6a95119ed267fc8b869e3e10910cc9ebe3a9e3340802dad9d1252aac7729eec
TOTAL_LINES=6 JSON_LINES=0 PLAIN_TEXT_LINES=6
[告警：env-mock] env=dev 使用 mock 通道：模型能力为模拟实现，仅供开发与自测；生产（env=prod）会直接拒绝该组合   ← 首行不是 JSON
RESTORED_SHA256=494ee2512428169216b0c88908f9b00d8f49b986f3ec7f4ab3d839cff45823b2
RESTORE_OK：字节级一致
```

**同一份配置、同一个探针**：修复后 `JSON_LINES=1 / PLAIN=5`，变异体 `JSON_LINES=0 / PLAIN=6`——即修复前后的差别恰好是那一行。还原按字节写回，sha256 与基线逐位相同（`main.py` 入库 blob `25901b4`）。

### 4.2 变异：同一变异体下哪些用例变红

```
FAILED tests/unit/test_logging.py::test_startup_first_emitted_line_is_json_with_every_mandated_field
FAILED tests/unit/test_logging.py::test_rejected_startup_still_logs_json
FAILED tests/unit/test_logging.py::test_logging_survives_a_rejected_startup
RESTORED_SHA256=494ee2512428169216b0c88908f9b00d8f49b986f3ec7f4ab3d839cff45823b2 MATCH=True
```

三个**走 lifespan 的**用例立刻变红，其余引导用例按设计仍然绿（它们直接调 `bootstrap_logging()`，不经过 lifespan）——判别力落在正确的粒度上。

## 5. 门禁与真实输出（提交后复跑）

```
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
387 passed, 8 skipped in 4.86s

$ .\.venv\Scripts\python.exe -m pytest tests/unit/test_logging.py -p no:cacheprovider
50 passed in 0.70s

$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --cov=src/aicore --cov-report=term-missing -q
src\aicore\core\logging.py                   121      0   100%
TOTAL                                        494     17    97%
Required test coverage of 80.0% reached. Total coverage: 96.56%

$ .\.venv\Scripts\ruff.exe check . --no-cache
All checks passed!

$ .\.venv\Scripts\mypy.exe src --cache-dir .venv\mypy_cache
Success: no issues found in 51 source files

$ .\.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
Contracts: 4 kept, 0 broken.
```

测试输出洁净度：整轮输出扫描 `Logging error` / `Traceback` / `warnings summary` / `DeprecationWarning` / `failed` / `error` 各 **0** 次（连续多轮运行不累积处理器——引导配置与正式配置共用「先摘旧再挂新」）。

## 6. 提交门禁（`--no-verify`，沙箱内无 `sh`）

逐条手工复刻 `.githooks/pre-commit`（`sh` 不存在，故用等价命令核）：

| hook 检查 | 手工复刻命令 | 结果 |
|---|---|---|
| 1) 新增行含合并冲突标记 | 取 `git diff --cached -U0` 的新增行后匹配 `^\+<<<<<<<` / `^\+=======$` / `^\+>>>>>>>` | 命中 **0** |
| 2) 行尾空白 / 末尾多余空行 | `git diff --cached --check` | 空（exit 0） |
| 3) 新增大文件 >1MB | 逐文件 `Get-Item ... .Length` | 最大 50,429 字节（`test_logging.py`），ok |
| 4) 私钥块 / `AKIA` / `ASIA` | 新增行匹配 `BEGIN ... PRIVATE KEY\|AKIA[0-9A-Z]{16}\|ASIA[0-9A-Z]{16}` | 命中 **0** |
| 5) 疑似硬编码凭据（粗筛 + 排除词） | 新增行匹配凭据正则后剔除 `placeholder\|mock\|fixture\|…` | 剔除后 **0 行**（本轮 diff 里没有凭据形态的字面量） |
| 6) 提交真实 `.env*`（仅允许 `.env.example`） | `git diff --cached --name-only --diff-filter=A` 匹配 `(^\|/)\.env(\..*)?$` | 命中 **0** |

`.githooks/commit-msg`：`fix(aicore): 启动首行日志改为引导配置下的 JSON` 匹配 `^(feat|fix|…)(\([^)]*\))?: .+`；type 英文、subject 中文、无 `[AI]` 前缀、未加 trailer（与仓库既有提交及 Task 2.5/2.6 的先例一致）。

另核：三个文件的 `git hash-object --path=<f> <f>` 与 `git rev-parse :<f>` **逐一相等**（`958a78c` / `25901b4` / `9e44afe`），确认 `core.autocrlf=true` 下入库 blob 为 LF。

`commit-check` 技能清单 A–F 自查：A 格式合规、单一目的（仅本轮 3 文件，无格式化/依赖混入）；B 无真实密钥 / 大文件 / `.env`；C 行尾干净、标识符英文、注释中文；D 日志本身即本轮的防御对象（新增记录与异常消息同源、无取值），脱敏与打码未被削弱；E 9 条新用例覆盖引导配置、幂等与拒绝路径，`core/logging.py` 保持 100%；F 无冲突标记。

## 7. 残留与工作区

```
$ git status --short
?? .sdd-tools.py        # 控制者的未跟踪文件，本轮未触碰
```

端口 8083 无监听（仅两条 `TIME_WAIT` socket，无 python 进程）；仓库内无 `*.log` / `uvicorn*` / 探针脚本残留（探针、临时配置、日志全部落在沙箱临时目录，且本轮结束时已删除）；`PYTHONPYCACHEPREFIX` 与 mypy/ruff 缓存均在 `.venv` 下。

本轮涉及文件的 sha256（提交内容）：

```
420ddeaf4c67b2f1c4a815023a71d7463e33afdc34052e8b6b436247df9f52dd  25014  core/logging.py
494ee2512428169216b0c88908f9b00d8f49b986f3ec7f4ab3d839cff45823b2   6079  main.py
de46b9d30e1517088505bb2f5b4f70ef7c2ef5b9fbafea281ebb13f2b20176fd  50429  tests/unit/test_logging.py
```

## 8. 自查与关注点

1. **引导阶段的字段取值**（有意取舍，已登记在常量 docstring）：首行的 `app` 是引导默认值 `aicore`，不是 `settings.app_name`（读不到）；`traceId`/`traceIdSource` 是启动期生成的一个 `generated` 值（无请求上下文）。**schema 完整，取值口径在正式配置生效后一致**。若要把 `app` 也做成「配置值」，只能把 `get_settings()` 提前——那正是本轮要修的顺序问题，故不做。
2. **引导级别固定 `INFO`**：若部署把 `AICORE_LOG_LEVEL=ERROR`（想让日志安静），读配置阶段的告警仍会以 `WARNING` 输出一行——即「引导期间可能比配置的阈值更啰嗦一行」。这是引导配置读不到配置的必然代价；反过来（引导取 `WARNING`）会漏掉潜在的 INFO 级启动信息，且与「首行必须可见」的初衷相悖。请控制者知悉。
3. **拒绝路径新增的 ERROR 记录**见 §2.2：唯一的行为扩展，若不需要可一行删除。
4. 控制者的三条既有裁定**未触碰**：`level` 仍取 Python 口径 `WARNING`（本轮证据未改变该判断：引导与正式两段配置都输出 `WARNING`，与 Java 侧 `WARN` 的字面量对齐仍属平台级裁定）；`uid` 脱敏仍只覆盖 schema 字段 + 密钥类字段名（挂点未变）；`spanId` 仍为存在且为空。
5. `_assemble_handler(shared, level)` 在 `foreign_pre_chain` 上用 `list(shared)` 做了一份浅拷贝：处理器对象本身是有状态的（`TimeStamper` 等），**共享同一批对象是刻意的**——两段配置不存在并发使用，且共用同一批处理器正是「口径不会漂移」的保证。
