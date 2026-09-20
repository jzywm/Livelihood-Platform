# Task 2.5 报告：traceId 上下文传播

- **状态**：DONE
- **提交**：`83f3a66 feat(aicore): 实现 traceId 上下文传播与响应头回显`（4 files changed, 738 insertions(+), 3 deletions(-)）
- **分支**：`feature/aicore-architecture`（worktree `D:\progrom\.worktrees\aicore-architecture`），父提交 `7e67112`
- **门禁**：pytest 94 passed / 7 skipped；ruff 通过；mypy 通过（51 文件）；lint-imports `4 kept, 0 broken`；`core/trace.py` 覆盖率 100%

---

## 1. 交付物（文件清单与职责）

| 文件 | 状态 | 职责 |
|---|---|---|
| `services/aicore/src/aicore/core/trace.py` | 修改（1 行 docstring 桩 → 253 行） | traceId 的 ContextVar 绑定、请求头解析与校验、跨线程上下文复制、纯 ASGI 中间件 |
| `services/aicore/src/aicore/main.py` | 修改（+31/-3） | 组合根：`_TracedFastAPI` 把 traceId 中间件包在整条 ASGI 栈之外并装配到 `create_app()` |
| `services/aicore/tests/unit/test_trace.py` | 新建（456 行） | 27 条用例：注入 / 缺失 / 非法 / 跨线程池 / 防串号 / 异常兜底 / 契约字面量 |
| `services/aicore/tests/unit/__init__.py` | 新建（0 字节） | 测试包标记，与 `tests/`、`tests/api/`、`tests/structural/` 的既有约定一致 |

## 2. 产出的接口（后续任务按名导入）

```python
TRACE_ID_HEADER      = "X-Request-Id"        # 网关注入用的请求头（不是 X-Trace-Id）
TRACE_SOURCE_FIELD   = "traceIdSource"       # 日志字段名：propagated / generated
TRACE_SOURCE_PROPAGATED = "propagated"
TRACE_SOURCE_GENERATED  = "generated"
TRACE_ID_HEX_LENGTH  = 16
MAX_TRACE_ID_LENGTH  = 64
TraceContext(trace_id: str, source: str)     # 冻结 dataclass；ContextVar 里存的记录
new_trace_id() -> str                        # 16 位小写 hex（secrets.token_hex(8)）
get_trace_id() -> str                        # 未绑定时生成并写回当前上下文
get_trace_source() -> str                    # 与 get_trace_id() 同源，顺序无关
set_trace_id(value, *, source=PROPAGATED) -> Token[TraceContext | None]
reset_trace_id(token=None) -> None           # token 省略时清空当前上下文
copy_context_for_thread() -> Context
TraceIdMiddleware(app)                       # 纯 ASGI 中间件
```

## 3. 关键设计决定（含实测依据）

### 3.1 中间件放最外层，而不是 `app.add_middleware()`

Starlette 的 `build_middleware_stack()` 固定拼成
`[ServerErrorMiddleware] + user_middleware + [ExceptionMiddleware]`
（`starlette/applications.py` L74-83），所以 `add_middleware` 注册的中间件**永远在 ServerErrorMiddleware 之内**，
而未捕获异常由后者在最外层渲染 500。实测两条路径（同一探针：注入 `X-Request-Id: 3f2a1b9c8d7e6f50`，
路由抛 `RuntimeError`，并注册 `@app.exception_handler(Exception)` 读 `get_trace_id()`）：

| 放置方式 | 500 响应头 | 异常处理器读到的 traceId |
|---|---|---|
| `add_middleware`（内层） | `None`（缺 `X-Request-Id`） | `743a6eef26551a63`（**新生成**，与网关值不符） |
| 最外层（本次实现） | `3f2a1b9c8d7e6f50` | `3f2a1b9c8d7e6f50` |

失守的不只是响应头：注册在 `Exception` 上的处理器会被 Starlette 提升为 ServerErrorMiddleware 的
`handler`，内层方案下它执行时中间件的 `finally` 已按 token 回滚，Task 2.4 的 500 信封只能拿到一个
**新生成**的 traceId。故在组合根用 `_TracedFastAPI.build_middleware_stack()` 把中间件包在应用之外
（`build_middleware_stack` 是 Starlette 的公开方法；其余中间件照旧走 `add_middleware` 通道）。
`create_app()` 仍是纯装配函数，**不读配置**（必填项拒绝留在 lifespan，Task 2.2）。

### 3.2 单一 ContextVar 存 `{traceId, source}` 记录

两个独立 ContextVar 会产生两个 token，「回滚了值、标记留在原地」会出现半截状态（后续 `get_trace_id()`
自动生成时被旧标记误标成 `propagated`）。存一条冻结记录后，一次 `set` 一个 token，`reset` 原子恢复。

### 3.3 外来头校验（拒绝即按缺失处理）

接受条件全部满足才透传：非空、`len ≤ 64`、每个字符在 `0x20~0x7E`（可打印 ASCII）、至少一个非空格字符。
拒绝控制字符（含 CR/LF）/ DEL / 非 ASCII（含中文、emoji）既防日志伪造（换行注假日志行）也防响应头注入
（CRLF 拆头）；长度上限保证攻击者可控串不会撑爆日志与响应头。拒绝时**丢弃原值**、重新生成并标
`traceIdSource=generated`，使「网关没注入 / 注入非法」在日志里可见。十六进制解码用 `latin-1`（头是任意
字节，不会抛 `UnicodeDecodeError`），非 ASCII 字节自然落到 >0x7E 被判非法。

### 3.4 纯 ASGI + 同任务

`TraceIdMiddleware` 直接实现 ASGI 协议，不使用 `BaseHTTPMiddleware`。实测判别：
处理器内 `asyncio.current_task()` —— `BaseHTTPMiddleware` 为 `False`（下游被丢进新的 anyio 任务），
本实现为 `True`。用例 `test_request_runs_in_callers_task` 正面守住这一点。

## 4. 验证（真实输出）

### 4.1 用例（全部 27 条）

```
$ .\.venv\Scripts\python.exe -m pytest tests/unit/test_trace.py -p no:cacheprovider
tests\unit\test_trace.py ...........................                     [100%]
27 passed in 0.77s

$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider          # 全量
94 passed, 7 skipped in 1.98s

$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --ignore=tests/unit   # 改动前的既有用例
67 passed, 7 skipped in 1.60s                                        # 67 + 27 = 94
```

用例清单（`--collect-only`）：

```
test_exposed_contract_names_match_the_platform          test_request_runs_in_callers_task
test_new_trace_id_is_16_lowercase_hex                   test_thread_pool_keeps_trace_id_only_when_context_is_passed
test_get_trace_id_is_stable_within_one_context          test_sequential_requests_do_not_share_trace_id
test_explicit_set_and_token_reset                       test_token_reset_clears_context_after_request
test_copy_context_for_thread_carries_one_id_...         test_escaping_error_still_echoes_injected_trace_id
test_injected_header_is_used_and_echoed                 test_escaping_error_without_header_still_echoes_generated_trace_id
test_gateway_uuid_value_is_propagated_verbatim          test_unhandled_error_handler_reads_the_same_trace_id
test_absent_header_generates_and_marks_generated        test_not_found_response_also_echoes_trace_id
test_header_at_length_limit_is_still_accepted           test_health_stays_bare_and_still_echoes_trace_id
test_overlong_header_is_treated_as_absent[65|200]
test_hostile_header_bytes_are_treated_as_absent[含换行|CRLF-拆头|含制表符|含-NUL|含-DEL|非-ASCII|全空格]
```

非法头用例经 **ASGI 直调**注入：httpx 会拒收含 CR/LF 的请求头，TestClient 根本送不进去；
直调同时让「请求处理」与「用例」落在同一个 asyncio 任务里（正是 3.4 的判别式）。
跨线程池用例断言 `traced.thread_ident != snapshot.thread_ident`（真的换了线程），并保留阴性对照。

### 4.2 覆盖率

```
$ .\.venv\Scripts\python.exe -m pytest tests/unit/test_trace.py --cov=aicore.core.trace --cov-report=term-missing
Name                       Stmts   Miss  Cover
src\aicore\core\trace.py      82      0   100%
```

### 4.3 其余门禁

```
$ .\.venv\Scripts\ruff.exe check . --no-cache
All checks passed!

$ .\.venv\Scripts\mypy.exe src --cache-dir .venv\mypy_cache
Success: no issues found in 51 source files

$ .\.venv\Scripts\lint-imports.exe --config .importlinter --no-cache     # exit code: 0
Analyzed 51 files, 3 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
```

那条 warning 是 Task 1.3 已知的 `unmatched_ignore_imports_alerting = warn`（`aicore.service.** -> aicore.provider.base`
尚无真实导入），与本次改动无关，契约仍为 4 kept。

### 4.4 阴性/变异验证（证明用例有判别力，不是跟着实现一起绿）

| 变异 | 预期变红点 | 实测 |
|---|---|---|
| 改用 `add_middleware`（内层放置） | 500 回显头 + 信封 traceId 用例 | 头 `None`；信封 traceId `743a6eef26551a63`（新生成） |
| 改用 `BaseHTTPMiddleware` | `test_request_runs_in_callers_task` | 处理器与调用方同一任务 = `False` |
| `copy_context_for_thread()` 返回空 `Context()` | 线程池正例 `traced == 注入值` | 线程内读到 `ce6694b94f980615`（另一个 id） |
| 关掉 `_sanitize_trace_id`（恒等返回） | 非法头用例 | 响应头被原样写入 `b'trace\nid'`（校验开启时为 `b'37513d930a419411'`） |

变异均在内存中经 monkeypatch / 临时子类完成，**未改动任何被跟踪文件**（`git status` 仅本次 4 个文件）。

## 5. 提交门禁（`--no-verify` 已获授权：沙箱内无 `sh`）

逐条手工复刻 `.githooks/pre-commit`：

| hook 检查 | 结果 |
|---|---|
| 1) 新增行含合并冲突标记 | none |
| 2) `git diff --cached --check`（行尾空白 / 文件末尾多余空行） | clean |
| 3) 新增大文件 >1MB | 最大 18,940 字节（test_trace.py），ok |
| 4) 私钥块 / `AKIA` / `ASIA` | none |
| 5) 疑似硬编码凭据正则（含排除词） | none |
| 6) 提交真实 `.env*`（仅允许 `.env.example`） | none |

`.githooks/commit-msg`：`feat(aicore): 实现 traceId 上下文传播与响应头回显` 匹配
`^(feat|fix|...)(\([^)]*\))?: .+`；subject 为中文；无 `[AI]` 前缀（与仓库既有提交一致，未加 trailer）。

另：`git hash-object --path=<f> <f>` 与 `git rev-parse :<f>` 三个文件逐一相等，确认 `core.autocrlf=true`
下入库 blob 未被改写成 CRLF；工作区所有文件为 LF、无 BOM。

`commit-check` 技能清单 A–F 逐项自查：A 提交信息合规、单一目的（仅本任务 4 文件）；B 无密钥 / 大文件 / `.env`；
C 行尾与末尾换行干净、命名英文、注释中文；D 无 SQL 拼接 / XSS，日志不落敏感信息；E 关键安全逻辑（外部输入校验 +
上下文隔离）有 27 条用例、`core/trace.py` 100% 覆盖；F 无冲突标记。

## 6. 自查发现（含与简报不一致之处，均已在此说明）

1. **`set_trace_id` 返回 token（简报写 `-> None`）**。简报同时要求 `reset_trace_id(token)`，而 token 只能由
   `ContextVar.set()` 产生；若 `set_trace_id` 返回 `None`，「绑定 → 回滚」这一对无法成对使用，回滚是防串号的
   唯一手段。返回 token 是 `-> None` 的严格超集（忽略返回值即等同旧用法），函数 docstring 已写明该偏差。
2. **`reset_trace_id(token=None)` 允许省略 token 直接清空**。为后台任务收尾与用例隔离提供一条公开的清空路径，
   避免测试去 import 私有 ContextVar。必填参数的调用形态不受影响。
3. **`TraceContext` 是新增公开名**。它出现在 `set_trace_id` 的返回类型里，若保持私有则公开签名引用私有名。
4. **中间件注册方式**：`create_app()` 返回 `_TracedFastAPI`（`FastAPI` 子类）而非直接 `app.add_middleware`，
   原因与实测见 §3.1。若评审要求 `app.user_middleware` 里能看到它，需改为 `add_middleware` —— 代价是 500 路径
   回显头缺失 + 信封 traceId 变成新生成值（两个用例会红）。
5. **空白字符口径**：简报写「可打印 ASCII」，实现取 `0x20~0x7E` 并额外拒绝**全空格**值（无意义）。比要求更严，
   且与网关 `[A-Za-z0-9._-]{1,64}` 同向；不存在「该放行却被拒」的生产路径（网关已先兜底重生成）。
6. **`starlette.types` 是直接导入但未在 `pyproject.toml` 直接声明**（starlette 由 fastapi 传递依赖，包已在 venv 内）。
   若要显式声明，加一行 `"starlette>=1.6"` 即可；本次未改 `pyproject.toml`，以免越出任务文件清单。
7. `_sanitize_trace_id` 的校验放在中间件解析路径上（`set_trace_id` 仍是原样 setter）：显式 set 的调用方是
   可信代码，攻击者可控串只可能从请求头进来。

## 7. 关注点与交接（供 Task 2.3 / 2.4 / 2.6 及评审）

1. **Task 2.6（结构化日志）必须把 `TRACE_SOURCE_FIELD`（`traceIdSource`）与 `get_trace_id()` / `get_trace_source()`
   接进 JSON 处理器**——「生成行为在日志中可区分」的落点在这里；本任务只提供字段名与来源标记（`core/logging.py`
   仍是桩，未在此处引入 stdlib logger，以免绕开 2.6 的 JSON 格式化）。
2. **Task 2.3 / 2.4 可直接受益**：注册在 `Exception` 上的 500 信封处理器现在能读到与响应头一致的 traceId
   （用例 `test_unhandled_error_handler_reads_the_same_trace_id` 已固化该契约）。
3. 未覆盖（按任务范围有意留空）：WebSocket / MQ header 透传、出向 HTTP 客户端注入 `X-Request-Id`、SSE 长连接
   （中间件的 `finally` 在响应结束后才回滚，SSE 期间上下文保持，符合预期）。
4. `/health` 仍为裸响应（用例断言全等 `{"status": "ok"}`），中间件只加响应头，不触碰 body。
5. 每个请求会调用一次 `secrets.token_hex`（仅在头缺失/非法时）；正常路径零生成开销。
