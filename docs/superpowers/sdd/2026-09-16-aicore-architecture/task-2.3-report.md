# Task 2.3 报告：异常层次与错误码映射

- 工作树：`D:\progrom\.worktrees\aicore-architecture`（分支 `feature/aicore-architecture`）
- 起点 HEAD：`5a5fd4e`
- 提交：`1e86f0e feat(aicore): 实现异常层次与错误码映射`（`--no-verify`，逐项等价复核见 §7）
- 状态：DONE_WITH_CONCERNS（顾虑见 §9；无阻塞项）

> **brief 文件缺失**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-2.3-brief.md` 在本工作树
> HEAD 上**不存在**（该目录下只有 1.1 / 1.2 / 1.3 / 1.4 / 2.1 / 2.5 / 3.1 的 brief）。本任务按
> ①控制者在下发文本中的「expanded」描述（与 brief 冲突时以它为准）、②计划文档
> `docs/superpowers/plans/2026-09-16-aicore-architecture.md` L1273–1297 的 Task 2.3、
> ③`openspec/changes/implement-aicore-service/tasks.md` 的 2.3 条目三者一致落地。
> 请控制者确认是否需要补一份 brief 归档。

## 1. 交付物

| 文件 | 状态 | 一行职责 |
| --- | --- | --- |
| `services/aicore/src/aicore/core/errors.py` | 修改（1 行文档串 → 394 行） | 业务异常层次 + 业务码常量 + 业务码↔HTTP 状态映射 + 三条错误路径的全局处理器注册；业务码 → 响应的**唯一**出口 |
| `services/aicore/src/aicore/main.py` | 修改（+4 行） | `create_app()` 调用 `register_exception_handlers(app)`（仍是纯装配、不读配置） |
| `services/aicore/tests/unit/test_errors.py` | 新建（587 行 / 72 条用例） | 上述全部行为的用例（含平台错误码表比对的正反两向、变异可判别的阴性样本） |
| `.superpowers/sdd/2026-09-16-aicore-architecture/task-2.3-report.md` | 新建 | 本报告 |

`core/envelope.py` **一行未动**（模型归 Task 2.4）；除上述文件外未改任何文件。

## 2. 接口（确切形状，后续任务可直接 import）

### 2.1 异常层次

```python
class AiCoreError(Exception):
    code: int = 5000                     # 业务码（类属性，缺省 5000）
    def __init__(self, message: str | None = None) -> None: ...
```

- `message` 是**实例**属性；缺省时取 `DEFAULT_MESSAGES[code]`（平台文案）。
- `str(exc) == exc.message`（`Exception.__init__(message)` 已调用）。
- 构造期强校验 `code in AICORE_ERROR_CODES`，否则 `raise ValueError`（fail fast）。
- 子类只声明 `code`，不再覆盖 `__init__`：

| 类 | `code` | HTTP | 触发语义 |
| --- | --- | --- | --- |
| `ParamError` | 缺省 `1002`，可传 `1001`/`1002`/`1003` | 400 | 参数类失败（见 §2.2） |
| `UnauthorizedError` | `2001` | 401 | 内部凭据无效（网关凭据 / 内部 Token） |
| `ForbiddenError` | `2002` | 403 | 无权限 / 越权 |
| `RateLimitedError` | `2004` | 429 | 网关级限流 + 服务域成本护栏共用 |
| `NotFoundError` | `3006` | 404 | 对象不存在 |
| `ChannelFailureError` | `4003` | 502 | 通道**等到响应但响应是失败** |
| `DependencyTimeoutError` | `5002` | 504 | 通道**没等到响应**（超时 / 熔断） |
| （未预期异常） | `5000` | 500 | 兜底处理器，不是异常类 |

### 2.2 `ParamError` 的形状（控制者要求「自选并写明」）

```python
class ParamError(AiCoreError):
    code = 1002                                      # 缺省档
    def __init__(self, message: str | None = None, *, code: int | None = None) -> None: ...
```

**三档共用一个类，档位由构造参数 `code` 指定；缺省 `1002`（参数格式错误）；`code` 只接受
`PARAM_ERROR_CODES = {1001, 1002, 1003}`，传 `0 / 2001 / 3006 / 429 / 9999` 一律构造期
`ValueError`。** 理由：

1. 平台把 1xxx 三档放在同一段，差别只有「缺失 / 格式 / 枚举或范围」这一维度，拆成三个类会让
   调用方在「这算格式还是算范围」上多做一次类选择；
2. 缺省 1002 与框架校验路径的兜底码一致（§3.2）：两条路径对「归不了类的参数错误」给同一个码，
   前端只需记一个兜底值；
3. 缺省文案随**最终码值**走：`ParamError(code=1001).message == "参数缺失"`（不是 1002 的文案）。

### 2.3 其余对外符号

```python
def register_exception_handlers(app: FastAPI) -> None: ...   # 幂等：重复调用只覆盖同名处理器
AICORE_ERROR_CODES: Final[frozenset[int]] = frozenset({1001, 1002, 1003, 2001, 2002, 2004,
                                                       3006, 4003, 5000, 5002})
```

随带的公开常量（Task 2.4 与后续任务的比对输入，均以 `_CODE` 结尾以便与 HTTP 状态区分）：
`PARAM_MISSING_CODE`/`PARAM_FORMAT_CODE`/`PARAM_VALUE_CODE`/`UNAUTHORIZED_CODE`/`FORBIDDEN_CODE`/
`RATE_LIMITED_CODE`/`NOT_FOUND_CODE`/`CHANNEL_FAILURE_CODE`/`INTERNAL_ERROR_CODE`/
`DEPENDENCY_TIMEOUT_CODE`、`PARAM_ERROR_CODES`、`DEFAULT_MESSAGES`、`HTTP_STATUS_BY_ERROR_CODE`、
`VALIDATION_HTTP_STATUS = 422`。

`AICORE_ERROR_CODES` **不含** `0`（成功码不是错误码）与任何 HTTP 状态码（`400/401/403/404/422/429/500/502/504`）。

## 3. 映射口径

### 3.1 业务码 ↔ HTTP 状态（实现 = 控制者锁定表）

| 业务码 | HTTP | 响应体样例（实测，见 §5.5） |
| --- | --- | --- |
| `1001`/`1002`/`1003` | 400（业务侧异常）/ 422（框架校验） | `{"code":1001,"message":"参数缺失","data":null,"traceId":"…","timestamp":"…Z"}` |
| `2001` | 401 | `{"code":2001,…}` |
| `2002` | 403 | `{"code":2002,…}` |
| `2004` | 429 | `{"code":2004,…}`（**`429` 只出现在 HTTP 状态位**） |
| `3006` | 404 | `{"code":3006,…}` |
| `4003` | 502 | `{"code":4003,…}` |
| `5000` | 500 | `{"code":5000,…}` |
| `5002` | 504 | `{"code":5002,…}` |

代码里这条表就是 `HTTP_STATUS_BY_ERROR_CODE`（键=业务码、值=HTTP 状态，注释写明「只用于渲染
响应，业务码本身不含状态语义」）。测试用**字面量**钉住这张表（不与实现互相印证），并逐例断言
`body["code"] != response.status_code`。

### 3.2 参数校验 error `type` → `1xxx`（控制者要求「用判断力并写明」）

| 业务码 | 判定依据（pydantic v2 的 `type`） |
| --- | --- |
| `1001` | `missing` |
| `1003` | `enum`、`literal_error`；`greater_than`、`greater_than_equal`、`less_than`、`less_than_equal`、`multiple_of`、`finite_number`；`too_short`、`too_long`、`string_too_short`、`string_too_long`、`bytes_too_short`、`bytes_too_long` |
| `1002` | **其余全部** → 兜底（类型不符、解析失败、`string_pattern_mismatch`、`extra_forbidden`、`json_invalid` 等） |

选择理由：

- 长度约束（`*_too_short`/`*_too_long`）归**范围**（1003）而非格式：平台表对 1003 的定义就是
  「枚举/范围非法」，长度是数值区间约束；
- `extra_forbidden`（多余字段）归 1002：字段**送到了但不该送**，属参数结构/格式问题；
- 兜底放在 1002 而非 1001/1003：未识别的 type 说明「值到了但被拒」，不是「缺失」；归 1003 则等于
  凭空断定它是枚举/范围问题。pydantic 将来新增 type 时最坏落到 1002，**不会漏成 5000**；
- 多条错误同时命中时只回一个码，优先级 **1001 > 1003 > 1002**（缺参最该先补；枚举/范围比格式更具体）。

两条配套决定：

1. **`message` 不回显 pydantic 的 `msg`/`loc`**，只用平台固定文案（`DEFAULT_MESSAGES`）。
   理由：`msg` 是英文框架文案；更关键的是自定义校验器抛 `ValueError("…{}…")` 时 msg 会把**用户
   输入**带进响应体，而框架默认响应体里的 `input` 字段本身就回显原值（见 §5.6 对照组实测）。
2. **日志只记 `type` 与 `loc`**（`_loggable_errors`），不记 pydantic error dict 里的 `input`/`ctx`
   —— 那是 PII 泄漏通道；用例 `test_validation_log_keeps_types_but_not_user_input` 正面钉住。

### 3.3 三条路径的取向

- **业务异常**：`AiCoreError` → 对应状态 + 信封；`logger.info`（HTTP 4xx 是预期内的业务结果，不产生堆栈）。
- **框架 422**：保留 HTTP 422（框架原生语义，客户端/监控不需要改判），响应体换成信封；
  1xxx 业务码与业务侧 400 完全同码。
- **未预期异常**：`logger.error(..., exc_info=exc)` 记完整堆栈；响应体只有「服务内部错误」。
  显式传 `exc_info=exc` 而非 `logger.exception()`：处理器是 Starlette 在 `except` 块里 await 的，
  把异常对象本身交给日志才与「一定记下这条异常的堆栈」等价。

## 4. `_error_body()`：与 Task 2.4 的关系（刻意的同形）

失败体是**普通 dict**，键集合恒为 `{"code","message","data","traceId","timestamp"}`：

```json
{"code": 2004, "message": "请求过于频繁，请稍后重试", "data": null,
 "traceId": "3f2a1b9c8d7e6f50", "timestamp": "2026-09-18T06:59:46.270732Z"}
```

- 四必填字段 = `code`/`message`/`traceId`/`timestamp`；`data` 可选、失败时为 `null`；
- `timestamp` 为 UTC ISO 8601（`Z` 结尾，微秒精度，与 pydantic v2 的 UTC 序列化同形）；
- `traceId` 一律取自 `core/trace.py` 的 `get_trace_id()`（未另造来源）；
- `_error_body` 的 docstring 明写：**这里的形状就是 `Envelope` 形状，不是重复定义**——Task 2.3 先于
  Task 2.4 落地，异常处理器不能等模型就位；模型（及 `Envelope.ok/fail`）由 **Task 2.4 拥有**，
  届时以「本处理器输出能通过该模型校验」反向对齐，MUST NOT 在 `core/envelope.py` 之外再造模型类。

**给 Task 2.4 的交接**：校验时请注意两点——① 失败体的 `data` 键**存在且为 null**（`_common` 的
error 示例同样带 `data: null`），若模型的序列化默认 `exclude_none`，形状会与本处理器不一致；
② `timestamp` 带 `Z` 与微秒，请用能解析该格式的类型/校验器。

## 5. 验证证据（真实输出）

### 5.1 新用例

```
> .venv\Scripts\python.exe -m pytest tests/unit/test_errors.py -p no:cacheprovider
72 passed in 0.85s
```

### 5.2 全量用例（含既有 200 条）

```
> .venv\Scripts\python.exe -m pytest -p no:cacheprovider
272 passed, 7 skipped in 2.86s
```

### 5.3 覆盖率（`fail_under = 80`）

```
> $env:COVERAGE_FILE = .venv\.coverage23; pytest -p no:cacheprovider --cov --cov-report=term-missing
Name                                       Stmts   Miss  Cover   Missing
src\aicore\core\errors.py                     85      0   100%
TOTAL                                        317     17    95%
Required test coverage of 80.0% reached. Total coverage: 94.64%
```

### 5.4 ruff（`--no-cache`）/ mypy（strict）/ 分层契约

```
> ruff check . --no-cache
All checks passed!

> mypy src --cache-dir .venv\.mypy_cache
Success: no issues found in 51 source files

> lint-imports --config .importlinter --no-cache
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
```

（唯一 warning 是该契约既有的 `unmatched_ignore_imports`：`aicore.service.** -> aicore.provider.base`
尚无真实导入，Task 4 落地 Protocol 后自动消失。）

### 5.5 真实响应样例（探针路由，实测）

```
/__probe__/biz                -> 429 application/json {"code":2004,"message":"请求过于频繁，请稍后重试","data":null,"traceId":"3f2a1b9c8d7e6f50","timestamp":"2026-09-18T06:59:46.270732Z"}
/health                       -> 200 application/json {"status":"ok"}
/__probe__/validate?limit=abc -> 422 application/json {"code":1001,"message":"参数缺失","data":null,…}      # 同时缺 name → 缺失优先
/__probe__/validate?limit=99&name=x
                              -> 422 application/json {"code":1003,"message":"枚举或范围非法","data":null,…}
/__probe__/boom               -> 500 application/json {"code":5000,"message":"服务内部错误","data":null,"traceId":"3f2a1b9c8d7e6f50","timestamp":"…Z"}
/no-such-route                -> 404 application/json {"detail":"Not Found"}        # 见 §9 的边界说明
```

500 路径的日志（stderr，未配置 logging 时由 root lastResort 输出；Task 2.6 接管）：

```
未预期异常 code=5000 method=GET path=/__probe__/boom traceId=3f2a1b9c8d7e6f50
Traceback (most recent call last):
  …
  File "<stdin>", line 19, in boom
RuntimeError: internal detail src/aicore/core/errors.py RuntimeError
```

响应体里没有出现上面任何一个片段（用例逐串断言：`Traceback`/`File `/`.py`/`RuntimeError`/`aicore`/
`services`/原始消息片段/内部路由路径）。

### 5.6 对照组：不注册处理器时框架返回什么（阴性对照，非推断）

```
no-handler 422 -> 422 {"detail":[{"type":"int_parsing","loc":["query","limit"],"msg":"Input should be a valid integer, unable to parse string as an integer","input":"abc"}]}
no-handler 500 -> 500 text/plain; charset=utf-8 'Internal Server Error'
```

即：不注册就是两种响应形状，且默认 422 体里的 `input` **回显了用户原值**；注册后两个路径都变成
§5.5 的信封。这条对照证明「信封是处理器造的」，不是别处恰好如此。

### 5.7 变异实跑（每一处都能变红，还原按字节 + sha256 校验）

| 变异 | 结果 |
| --- | --- |
| `main.py` 去掉 `register_exception_handlers(app)` 调用 | `25 failed, 47 passed`（信封/状态码/泄漏/日志/平台表比对全线变红） |
| `RATE_LIMITED_CODE := 429`（把 HTTP 状态当业务码） | `7 failed, 65 passed`：`test_exception_class_carries_expected_business_code[RateLimitedError]`、`test_business_exception_maps_to_envelope[rate-limited-2004]`、`test_rate_limited_is_business_code_2004_under_http_429`、**`test_aicore_error_codes_all_exist_in_the_platform_enum`**、`test_codes_outside_the_platform_table_are_detected`、`test_aicore_error_codes_is_exactly_the_emittable_set`、`test_http_status_table_matches_the_locked_platform_mapping` |

平台表比对（本任务的核心红线）在第二种变异下**确实变红**：`AICORE_ERROR_CODES` 由码值常量派生，
写错常量会连带污染集合，只有与 `_common/openapi.yaml` 的枚举比对能拦住——这正是控制者要求的
「阴性方向」。变异后按 sha256 校验还原（`9ea3113…` / `e6c767c…` 前后一致），`git status` 仅剩
任务开始前就存在的未跟踪文件 `.sdd-tools.py`，复跑全量 272 passed。

用例内还固化了判定器的判别力（不需要改文件即可证明）：`codes_outside_platform_table({*AICORE_ERROR_CODES, 9999}) == (9999,)`、
`…,429}) == (429,)`、`…,400}) == (400,)`；以及非空下限 `len(platform_codes) >= 25` 与
`{0,1001,1002,1003,2004,3007,5000,5002,5003} <= platform_codes`，防止解析塌成空集后「全绿」。

### 5.8 用例与验收项对照

| 控制者列的验收项 | 用例 |
| --- | --- |
| 每个异常类 → 业务码 + HTTP 状态（参数化，断言体 `code` 与 HTTP 状态） | `test_business_exception_maps_to_envelope`（10 例）+ `test_exception_class_carries_expected_business_code` |
| `ParamError` 可承载 `1001/1002/1003` | `test_param_error_carries_the_three_param_codes`、`test_param_error_rejects_codes_outside_the_param_family` |
| 框架 422 → 信封且含 `1xxx`、四键齐全、无 `detail` | `test_request_validation_error_is_absorbed_into_envelope`（7 例） |
| 未预期异常 → 500/`5000`、体无堆栈/路径/模块名、**堆栈确实进日志** | `test_unexpected_exception_maps_to_5000`、`…_body_leaks_no_internals`、`…_traceback_is_logged`（caplog 取到带 traceback 的 ERROR 记录，`traceback.format_exception` 里出现 `test_errors.py`：堆栈指向真实抛出点） |
| `AICORE_ERROR_CODES` 与平台枚举一致 + 阴性方向 | `test_aicore_error_codes_all_exist_in_the_platform_enum`、`test_codes_outside_the_platform_table_are_detected`、`test_platform_enum_is_readable_and_not_vacuous`、`test_aicore_error_codes_is_exactly_the_emittable_set` |
| 四键齐全、`timestamp` 可解析为 ISO 8601 UTC、`traceId` == 请求头 | `test_timestamp_is_iso8601_utc_within_the_request_window`、`test_trace_id_comes_from_request_header`、`test_trace_id_is_generated_when_header_is_absent` |
| `/health` 仍是裸响应（不得回归） | `test_health_stays_bare_after_handlers_are_registered` |
| （另加）`main.py` 真的接线 | `test_create_app_registers_the_three_handlers` |
| （另加）限流是 `(429, 2004)`、业务码与状态不混用 | `test_rate_limited_is_business_code_2004_under_http_429`、`test_http_status_table_matches_the_locked_platform_mapping` |
| （另加）校验日志不记用户输入 | `test_validation_log_keeps_types_but_not_user_input` |

探针路由（`/__test__/raise-*`、`/__test__/validate`）全部由夹具挂到用例自己的 `create_app()`
实例上，生产代码不含任何调试端点；用例内无 `sleep`、无网络、无数据库。

## 6. 改动文件

```
1e86f0e feat(aicore): 实现异常层次与错误码映射
 services/aicore/src/aicore/core/errors.py | 395 +++++++++++++++++++-
 services/aicore/src/aicore/main.py        |   4 +
 services/aicore/tests/unit/test_errors.py | 587 ++++++++++++++++++++++++++++++
 3 files changed, 985 insertions(+), 1 deletion(-)
```

`main.py` 的改动即：

```python
 from aicore.core.errors import register_exception_handlers
 ...
     app.include_router(health.router)
+    # 全局异常处理器（Task 2.3）：业务异常 / 框架 422 / 未预期异常统一映射为平台信封。
+    # 注册只改 app.exception_handlers，不读配置，create_app() 仍是纯装配函数。
+    register_exception_handlers(app)
     return app
```

## 7. pre-commit / commit-msg 的等价复核（`sh` 缺失，`--no-verify` 已授权）

沙箱无 `sh`，`.githooks/*` 无法执行，故逐项手工等价复核：

| hook 检查 | 复核命令 | 结果 |
| --- | --- | --- |
| ① 合并冲突标记 | `git diff --cached -U0 \| Select-String '^\+<<<<<<<\|^\+=======$\|^\+>>>>>>>'` | 0 命中 |
| ② 行尾空白 / 文件末尾多余空行 | `git diff --cached --check` | 退出码 0、无输出 |
| ③ 大文件 >1MB | `Get-Item` 三个文件 | 17.5KB / 3.0KB / 25.7KB |
| ④ 私钥块 / 云密钥 | `git diff --cached -U0 \| Select-String 'BEGIN …PRIVATE KEY\|AKIA[0-9A-Z]{16}\|ASIA…'` | 0 命中 |
| ⑤ 疑似硬编码凭据正则 | 同 hook 的 `P`/`EX` 正则重放 | 0 命中（测试值均为 `test_secret_value` 一类占位符，且不构成 `关键字[:=]值` 形状） |
| ⑥ 新增真实 `.env` | `git diff --cached --name-only --diff-filter=A` | 仅新增 `test_errors.py` |
| commit-msg（Conventional Commits） | 人工核对 | `feat(aicore): 实现异常层次与错误码映射`，type 英文 + subject 中文，**无 `[AI]` 前缀** |

另按 `commit-check` 技能的语义清单自查：标识符英文 / 注释文档中文（`DEVELOPMENT_CONSTRAINTS.md` §2）、
无真实密钥、单一逻辑变更（异常与错误码映射，测试随实现同批）、未放宽任何已有检查。

## 8. 自审发现

1. **`ruff format --check` 的一次未加 `--no-cache` 调用**在 `services/aicore/` 下生成了 `.ruff_cache/`
   （gitignored，任务开始前的目录清单里没有），已删除；此后所有 ruff 调用一律 `--no-cache`，
   pytest 一律 `-p no:cacheprovider`，mypy 缓存落在 `.venv\.mypy_cache`。
2. **`AiCoreError.__init__` 的 `ValueError` 是开发期守卫**：若将来有人给派生类写一个表外码值，
   异常会在**构造处**炸成 5000，而不是把错码送给前端。取向是「宁可 5000，也不发明码值」。
3. **500 路径会被记录两次**：Starlette 的 `ServerErrorMiddleware` 在调用处理器后**必然重新抛出**
   （设计如此），uvicorn 会再记一次；本服务的记录带 traceId 与 `code=5000`，是排障主入口。
   这是 Starlette 的既有行为，不是本实现的冗余。
4. **`DEFAULT_MESSAGES` 的键集被用例钉死为 `AICORE_ERROR_CODES`**：新增码值必须同时补文案，
   否则渲染信封时会 `KeyError`（该分支已被 100% 行覆盖之外的设计规避：键集相等即不可能触发）。
5. **`ParamError` 的 `message` 由调用方提供**（面向用户的提示文案）。默认文案取自平台表、不含内部
   细节；但调用方仍可能把内部信息塞进 message——目前没有结构性强约束，留给评审决定是否要加。
6. **平台表读取依赖 `yaml`**：`pyyaml 6.0.3` 在 venv 中存在，来源是 `uvicorn[standard]`
   （已核实 `Requires-Dist: pyyaml>=5.1; extra == 'standard'`）。它未在 `dev` extras 里显式声明，
   本次**未改 `pyproject.toml`**（遵守任务的文件清单）；建议某个后续任务把 `pyyaml` 补进 dev 依赖。
   若它缺失，用例会在导入期直接报错（不会静默跳过）。
7. **平台表路径**用 `Path(__file__).resolve().parents[2].parent / "_common" / "openapi.yaml"` +
   `is_file()` 断言；服务目录将来若挪位，用例立刻变红而不是静默通过。
8. 用例把「`429`/`400`/`0` 不得进业务码集合」写成了正面断言（`isdisjoint`、`0 not in`、
   `codes_outside_platform_table({429, 400}) == (400, 429)`），不只是靠代码审查。

## 9. 顾虑与交接

1. **`3007`（状态不允许该操作）——决定：现在不引入。** 依据：`AICORE_ERROR_CODES` 的语义是
   「本服务**今天**确实会发出的码」，状态机属后续组（任务 3.x/4.x 的任务表与状态流转）；
   现在加进集合会立刻让 `test_aicore_error_codes_is_exactly_the_emittable_set` 之类断言失去意义
   （集合里出现无人发出的死码）。`3007` 仍留在 `test_platform_enum_is_readable_and_not_vacuous`
   的解析下限集合里（它是平台表确实存在的码，也是「解析没在 2xxx 段截断」的证据）。
   请控制者确认此决定。
2. **未匹配路由 404 / 方法不允许 405 仍是框架默认 `{"detail": "Not Found"}`（形状与信封不同）。**
   决定不在此收编：平台表里 `3006` 的语义是「**对象**不存在」，而这里不存在的是**路由**，强行映射
   等于发明口径（控制者明令「不要发明其它映射」）。影响面：网关只把 `/api/v1/aicore/**` 转到本服务，
   该形状只会出现在路径写错/方法写错这类集成错误上，业务接口不经过它。**建议**由后续任务决定：
   要么给「接口不存在」定一个新码（需平台表先有该码），要么明确接受框架默认形状并补文档。
3. **框架 422 保留 HTTP 422（不回落到 400）**：控制者的映射表括注「400（and 422 where it is a
   FastAPI validation error）」，故 1xxx 的送达状态是 400（业务侧）/ 422（框架侧）两种，业务码同为
   1xxx。若控制者更希望统一成 400，改动是 `errors.py` 里的 `VALIDATION_HTTP_STATUS` 一行 + 两条
   用例的期望值（请指示，我按新口径改）。
4. **给 Task 2.4**：见 §4 的交接（`data: null` 键必须存在、`timestamp` 带 `Z` 与微秒、
   `traceId` 取值来自 `core/trace.py`、不要在 `core/envelope.py` 之外再造模型）。
5. **给后续业务任务**：只 `raise` 本模块的异常（鉴权路径用 `UnauthorizedError`/`ForbiddenError`），
   **不要**自己拼信封、**不要** `raise HTTPException`（那会绕开信封，回到 §5.6 的框架默认形状）。
6. **brief 文件缺失**（见文首）：请确认是否需要补 `task-2.3-brief.md` 归档。

---

## 修复轮 1（评审发现）

- 起点 HEAD：`5d861b2` → 提交：`805db9c fix(aicore): 收编框架 HTTPException 为统一信封`（`--no-verify`，逐项等价复核见 §R7）
- 评审结论：Needs fixes（0 Critical / 1 Important / 5 Minor）；本轮修 Important + M1 + M3 + M4，**M2 / M5 按评审指示不动**
- 状态：DONE（顾虑见 §R9）

### R1 重要项：框架 `HTTPException` 路径从未被信封化

**问题**：`register_exception_handlers()` 只注册了 `AiCoreError` / `RequestValidationError` / `Exception`。
Starlette 路由层在「路径未匹配」（404）与「方法不允许」（405）时抛的是 `StarletteHTTPException`，
它落到 FastAPI 预注册的 `http_exception_handler` 上，响应体是 `{"detail": "Not Found"}` —— 没有
`code` 字段，即前端必须特判的**第三种形状**。可达性不止拼错路径：`docs/openapi.yaml:40-41` 用全局
`security: bearerAuth` 覆盖全部操作，且各操作逐条声明 `'401'`/`'403'` → `_common` 的
`Unauthorized`/`Forbidden`（实测 13 处 401、12 处 403 / 10 个操作）；`HTTPBearer` 依赖内部抛
`HTTPException(401/403)`，调用点拦不住。
原报告 §9.2 以「3006 语义是对象不是路由」为由决定不收编——该理由只对 **message** 成立，不构成
放过**形状**的依据。评审的判断正确。

**改动**（`errors.py`，全部按控制者锁定口径，未发明任何映射）：

```python
HTTP_STATUS_BY_HTTP_EXCEPTION_STATUS = {401: 2001, 403: 2002, 404: 3006,
                                        429: 2004, 500: 5000, 502: 4003, 504: 5002}
HTTP_EXCEPTION_4XX_FALLBACK_CODE = 1001   # 未列入锁定对的 4xx
HTTP_EXCEPTION_5XX_FALLBACK_CODE = 5000   # 未列入锁定对的 5xx
ROUTE_NOT_FOUND_MESSAGE = "接口不存在"     # 404 专用文案，与业务 DEFAULT_MESSAGES[3006]="对象不存在" 区分
HTTP_ERROR_MESSAGES = {404: ROUTE_NOT_FOUND_MESSAGE}
```

- 注册点：`app.add_exception_handler(StarletteHTTPException, _handle_http_exception)`
  （`from starlette.exceptions import HTTPException as StarletteHTTPException`）；
- `exc.status_code` 原样作为响应 HTTP 状态；业务码走 `_http_exception_info()`：锁定对优先 →
  其余 4xx 落 `1001` → 其余 5xx 落 `5000`；
- **`1001` 兜底的理由已写进代码注释**（评审要求记录）：平台表 `1xxx` 段是参数校验，未匹配路由 /
  不被允许的方法**就是**「请求打错了地方」；普通业务 400 走 `AiCoreError` / `ParamError`，不经过
  本兜底，故不会遮住业务规则；`1001` 是平台表里真实存在的码，**没有为 405 发明新码**；
- **文案策略 = 平台文案，不是 `detail`**（见 §R2）；`detail` 也**不进日志**（它可能带上游内容）；
- 信封保证与其余三条路径**完全一致**：`code`/`message`/`data: null`/`traceId`/`timestamp`，
  traceId 取自 `core/trace.py`，timestamp 为 UTC ISO 8601。

**顺带发现并修掉的一个真实回归风险（评审未提，我主动收进本轮）**：FastAPI 的默认
`http_exception_handler` 会把 `exc.headers` 透传给响应。注册即**覆盖**它，若不显式透传，
`HTTPBearer` 的 401 会丢掉 `WWW-Authenticate: Bearer`——客户端就不知道该怎么补凭据。
故 `_handle_http_exception` 原样带上 `headers=http_exc.headers`，并有用例
`test_framework_http_exception_keeps_its_headers` 正面钉住。这是**保留框架既有行为**，不是新增口径。

**同时修正原报告一处事实偏差**（实测，非推断）：原报告 §9.2 说 404 是 `{"detail": "Not Found"}`，
方向对但机制说法不准。实测（FastAPI 0.141.1 / Starlette 1.6.0）：

```
FastAPI 默认        -> 404 application/json {"detail":"Not Found"}
预注册键: [<class 'starlette.exceptions.HTTPException'>, RequestValidationError, WebSocketRequestValidationError]
无该键(Starlette)   -> 404 text/plain Not Found
```

即：FastAPI 预注册的键**就是 Starlette 基类**（`fastapi.HTTPException is starlette.exceptions.HTTPException`
实测为 **False**，但键用的是基类），而 Starlette 自己的 `ExceptionMiddleware` 还内建一个
`http_exception` 回退（**text/plain**）。故不注册时的真实形状是 FastAPI 那个 JSON 处理器给的
`{"detail": "Not Found"}`（= 评审描述），本模块的注册是**覆盖**而非并存。三处 docstring 已按实测改写。

### R2 文案：没有对任何状态surfacing `detail`

**没有任何状态回显 `exc.detail`**，包括 404 —— 404 用的是平台风格新文案「接口不存在」（评审允许并
要求的「distinct message」），其余状态一律 `DEFAULT_MESSAGES[业务码]`。理由：`detail` 是框架给开发者
看的（`HTTPBearer` 抛的是 `"Not authenticated"` / `"Not enough permissions"`），而平台文案表是按
「面向用户、可直接展示」评审过的，`_common` 的 response example 就是它的权威。故本报告**无需**为
任何状态做「surfacing detail」的例外说明。

### R3 Minor M1：接线断言不可判别 → 改为断言处理器**身份**

原 `test_create_app_registers_the_three_handlers` 只断言键存在，而 FastAPI 构造时已预注册
`RequestValidationError`（与 `StarletteHTTPException`）两个键，故这两条路径「恒真」。改为
`handlers[K] is _handle_*`，并更名 `test_create_app_registers_the_four_handlers`。判别力由 §R5
的阴性实跑证明（删掉注册行该用例变红）。

### R4 Minor M3 与 M4

- **M3**：`decimal_max_digits` / `decimal_max_places` / `decimal_whole_digits` 三个 type 收进
  `_RANGE_ERROR_TYPES`（归 `1003`），不再落 `1002` 兜底；模块 docstring 的 1003 行同步。
  另补 `test_decimal_digit_constraints_are_real_pydantic_types` 做**行为证据**（真造 pydantic 错误、
  取实际 `type` 再喂分类器），并顺带实测到一个值得记录的事实：`Field(max_digits=…, decimal_places=…)`
  只会发 `decimal_max_digits` / `decimal_max_places`，**`decimal_whole_digits` 用常规 Field 约束触发不到**
  （pydantic-core 报的是 max_digits）——它仍按范围类收列，以免一旦出现就落兜底，这一点已写进代码注释。
- **M4**：**不重设计**，把「新增一个业务码的四处」集中成常量区顶部的一个清单注释
  （`AICORE_ERROR_CODES` / `DEFAULT_MESSAGES` / `HTTP_STATUS_BY_ERROR_CODE` /
  `test_errors.py` 里两张字面量表），并点名「漏掉第一处会让 raise 侧构造期 `ValueError` → 前端拿到
  5000」这一最危险的失效模式，以及「该码必须先在 `_common/openapi.yaml` 存在」的前提。

M2（文案与 doc 示例的措辞漂移）、M5（用例 import 私有 helper）按评审指示**未改动**。

### R5 验证证据（真实输出）

```
# 新增/改动用例
> pytest tests/unit/test_errors.py -p no:cacheprovider
84 passed in 0.84s                      # 原 72 条 → 84 条（+12）

# 全量
> pytest -p no:cacheprovider
284 passed, 7 skipped in 5.89s          # 原 272 → 284

# 覆盖率（fail_under = 80）
> $env:COVERAGE_FILE = .venv\.coverage23fix; pytest -p no:cacheprovider --cov --cov-report=term-missing
src\aicore\core\errors.py                    110      0   100%
TOTAL                                        342     17    95%
Required test coverage of 80.0% reached. Total coverage: 95.03%

> ruff check . --no-cache
All checks passed!

> mypy src --cache-dir .venv\.mypy_cache
Success: no issues found in 51 source files

> lint-imports --config .importlinter --no-cache
Contracts: 4 kept, 0 broken.            # core 不得依赖任何业务层 KEPT
```

新增用例 12 条：`test_unmatched_route_is_enveloped_as_route_not_found`、
`test_disallowed_method_is_enveloped`（405 → 1001）、
`test_framework_http_exception_is_enveloped_with_platform_message`（401→2001 / 403→2002 / 503→5000，3 例）、
`test_framework_http_exception_keeps_trace_id_from_request_header`、
`test_framework_http_exception_keeps_its_headers`、
`test_http_exception_status_mapping_is_exactly_the_locked_pairs`、
`test_decimal_digit_constraints_are_real_pydantic_types`、
`test_create_app_registers_the_four_handlers`（改造）、
`test_validation_error_type_mapping` 新增 3 例（decimal）+ 重命名 1 条。

新增用例全部满足评审的取证清单：**HTTP 状态正确**、`code == 3006` / `1001` / `2001` / `2002` / `5000`、
**四键齐全且 `detail` 缺席**（`assert set(body) == ENVELOPE_KEYS` + `"detail" not in body`）、
**文案与框架 `detail` 不同**（哨兵值 `FRAMEWORK_DETAIL_MUST_NOT_LEAK` + 框架固定片段
`Not Found` / `Method Not Allowed` / `Not authenticated` / `Not enough permissions` 逐串断言不出现）。
`/health` 仍裸响应、500 泄漏保证不变（既有用例全绿）。

**真实响应样例**（探针路由，实测）：

```
GET  /no-such-route      -> 404 application/json {"code":3006,"message":"接口不存在","data":null,"traceId":"26fe4a5f677a05d1","timestamp":"2026-09-18T07:13:45.016632Z"}
POST /__probe__/ok       -> 405 application/json {"code":1001,"message":"参数缺失","data":null,"traceId":"b7ac743a5f10c445",…}
GET  /__probe__/secured  -> 401 application/json {"code":2001,"message":"未登录或 Token 已失效","data":null,…}
     WWW-Authenticate: Bearer                      # 框架头已透传
GET  /__probe__/denied   -> 403 application/json {"code":2002,"message":"无权限访问该资源","data":null,…}
GET  /__probe__/boom     -> 503 application/json {"code":5000,"message":"服务内部错误","data":null,…}
GET  /health             -> 200 application/json {"status":"ok"}     # 仍裸
```

探针脚本写在 `.venv\` 下（自身 gitignored），**已删除**，仓库内无残留。

### R6 阴性实跑（本轮必交的负证据）

对**最终版本**（sha256 `687043F1918820597D0B3043E718D8141FB4D4CCFAB2EE5E11D98B2FD6962C96`）
临时删掉 `app.add_exception_handler(StarletteHTTPException, _handle_http_exception)` 这一行：

| 变异 | 结果 |
| --- | --- |
| 去掉 `StarletteHTTPException` 注册 | `7 failed, 277 passed, 7 skipped`，变红的**恰好是**本轮新增/改动的 7 个用例：`test_create_app_registers_the_four_handlers`、`test_unmatched_route_is_enveloped_as_route_not_found`、`test_disallowed_method_is_enveloped`、`…is_enveloped_with_platform_message[401/403/503]`、`…keeps_trace_id_from_request_header` |

失败形态即评审描述的缺陷本身（`response.json()["traceId"] → KeyError: 'traceId'`，
即响应体只有 `{"detail": …}`）。还原按**字节复制**回写，sha256 与改动前**逐字符一致**
（`687043F1…` 前后相同），复跑 `284 passed, 7 skipped`。**注意**：本节阴性实跑与 §R5 的
`test_framework_http_exception_keeps_its_headers` 无关——该用例在本变异下仍绿（FastAPI 默认处理器
也透传 headers），它守的是另一条口径。

### R7 pre-commit / commit-msg 的等价复核（`sh` 缺失，`--no-verify` 已授权）

`.githooks/pre-commit` 六项逐条重放（命令与 hook 内一致）：

| hook 检查 | 复核命令 | 结果 |
| --- | --- | --- |
| ① 合并冲突标记 | `git diff --cached -U0 \| Select-String '^\+<<<<<<<($\| )\|^\+=======$\|^\+>>>>>>>($\| )'` | 0 命中 |
| ② 行尾空白 / 文件末尾多余空行 | `git diff --cached --check` | 退出码 0、无输出 |
| ③ 大文件 >1MB | `Get-Item` 两个文件 | 28.0KB / 38.0KB |
| ④ 私钥块 / 云密钥 | 同 hook 的 `BEGIN …PRIVATE KEY\|AKIA…\|ASIA…` 正则重放 | 0 命中 |
| ⑤ 疑似硬编码凭据 | 同 hook 的 `P` 排除 `EX` 后重放 | 0 命中 |
| ⑥ 新增真实 `.env` | `git diff --cached --name-only --diff-filter=A` | 本次无新增文件 |
| commit-msg | `^(feat\|fix\|…)(\([^)]*\))?: .+` 正则匹配 | `fix(aicore): 收编框架 HTTPException 为统一信封` 通过；**无 `[AI]` 前缀** |

另按 `commit-check` 技能语义清单自查：注释文档中文 / 标识符英文、无真实密钥、单一逻辑变更
（框架 HTTPException 收编 + 两条 Minor，测试随实现同批）、**未放宽任何已有检查**（既无 `# type: ignore`
新增，也无 `noqa` 放宽；`test_errors.py` 的私有 helper import 属评审已接受的 M5）。

### R8 自审发现

1. **`_handle_http_exception` 的 `exc` 注解只能是 `Exception`**：与既有两个处理器同理，
   Starlette 的 `ExceptionHandler` 协议把第二参数声明为基类，写窄类型过不了 mypy strict；
   内部 `cast(StarletteHTTPException, exc)`，与既有写法保持一致。
2. **`_http_exception_info()` 用 `NamedTuple` 返回三件套**，而不是让处理器各自 `dict.get()`：
   映射逻辑只在一处，且 100% 行覆盖（覆盖率报告 `errors.py 110 stmts / 0 miss`）。
3. **段边界 400/500 用具名常量 `_CLIENT_ERROR_MIN` / `_SERVER_ERROR_MIN`**，不用裸字面量，
   并在注释里点名「它们是 HTTP 状态、不是业务码」——避免与业务码常量混读。
4. **退出码 1 的一次 `ruff format --check src tests`** 报出 `tests/unit/test_config.py:206` 未格式化。
   该文件**不是本任务改动的文件**（`git status` 可证），是既有状态；本任务只对自己改动的两个文件
   跑 format check（`2 files already formatted`）。**未顺手格式化它**：那会把无关文件的改动混进本次提交。
5. **`.venv\probe_fix1.py` / `probe_fix1_control.py` 两个临时探针已删除**，`git status --short`
   仅剩两个改动文件 + 控制者原有的未跟踪 `.sdd-tools.py`。
6. 全程遵守沙箱约束：`PYTHONUTF8=1`、`PYTHONPYCACHEPREFIX` 在 venv 下、`pytest -p no:cacheprovider`、
   `ruff --no-cache`、mypy 缓存在 `.venv\.mypy_cache`、未跑 `pip install`、未用
   `Set-Content`/`Out-File` 写文件。

### R9 顾虑与交接（本轮）

1. **原报告 §9.2 的顾虑已由本轮关闭**，但其口径需控制者确认一句话：路由 404 与业务 404 现在
   **同码 `3006`、不同文案**（「接口不存在」 vs「对象不存在」）。前端若按 `code` 分支，两者仍不可区分
   ——这是锁定对的必然结果（一个码只能有一个语义位）。若前端需要区分「路径错」与「对象无」，
   那需要平台表新增一个码（本轮**未**发明），请控制者裁定是否登记该需求。
2. **框架 5xx 兜底到 `5000` 会掩盖「上游依赖的 5xx 被当成内部错误」**：例如路由层抛
   `HTTPException(503)` 时，监控无法从 `code` 区分「本服务内部错误」与「框架/上游不可用」。
   本轮按控制者锁定口径（未列入的 5xx → 5000）执行；若将来需要区分，`5003`
   （网关暂不可用）已在平台表内，可作为候选——**但现在不引入**（属后续任务口径）。
3. **`/openapi.json` 与 `/docs` 的 404/405 也走本处理器**：它们的 JSON 响应体变成信封。
   这符合「所有错误响应同一形状」，但对自动化工具（依赖 `{"detail": …}` 的 OpenAPI 客户端生成器）
   是一个行为变更，请控制者知悉。
4. **`fastapi.HTTPException` 子类的行为未被单独测试**：本模块注册的是基类（即 FastAPI 预注册的那个键），
   子类实例按 MRO 也命中它，故 `raise fastapi.HTTPException(...)` 同样被信封化——但既有用例的探针
   一律抛基类。若认为需要，可后续补一条子类用例（本轮判定为低价值，未加）。
5. **给后续业务任务（同上文 §9.5，措辞更新）**：只 `raise` 本模块的异常；**不要** `raise HTTPException`
   ——现在它虽然也会被信封化，但会走「HTTP 状态 → 业务码」的兜底映射（多数状态落到 `1001`/`5000`），
   送出**错误语义**的业务码，比形状错误更难发现。

---

## 修复轮 2（复评 Minor）

- 起点 HEAD：`805db9c` → 提交：`5f8d182 fix(aicore): 无体状态不再套信封并修正 sub-400 业务码`
  （`--no-verify`，逐项等价复核见 §F6）
- 复评结论：**All findings addressed, no new Critical/Important breakage**；本轮修完剩余两条 Minor
- 状态：DONE（无顾虑阻塞项；遗留观察见 §F7.5）

### F1 Minor（真实 parity 缺口）：无体状态被套上 JSON 信封 + sub-400 落 `5000`

**问题**：`_handle_http_exception` 一律回 `JSONResponse`，而它覆盖的 FastAPI 默认处理器对
`1xx` / `204` / `205` / `304` 回的是**无体** `Response`（`fastapi/exception_handlers.py` 用
`is_body_allowed_for_status_code` 判定）。两者叠加出两个缺陷：① 无体状态带上
`application/json` 与一个信封体，违反 HTTP 契约；② `_http_exception_info` 的兜底判据是
「是否落在 4xx 段」，sub-400 落进 5xx 分支，得出 `code=5000` 这个「内部错误」假信号。

**修复前实测**（探针路由 `raise HTTPException(204/205/304, headers=…)`，`805db9c`）：

```
HTTPException(204) -> 204 content-type='application/json' headers={'etag':'"v1"'} body=b'{"code":5000,…}'
HTTPException(205) -> 205 content-type='application/json' + content-length: 127  body=b'{"code":5000,…}'
HTTPException(304) -> 304 content-type='application/json' headers={'etag':'"v2"'} body=b'{"code":5000,…}'
```

**改动**（`errors.py`，`main.py` 仅注释）：

1. 复用框架自己的判定：`from fastapi.utils import is_body_allowed_for_status_code`
   （选型理由见下）；
2. `_handle_http_exception` 返回类型 `JSONResponse` → `Response`（`fastapi.responses.Response`，
   即 Starlette 的 `Response`）。命中无体判据即
   `return Response(status_code=info.status_code, headers=http_exc.headers)`，返回前记一条带 traceId 的
   `logger.info`（这条路径没有信封可取 traceId，故直接取 `get_trace_id()`，与 500 处理器同一做法）；
3. 兜底判据由「`_CLIENT_ERROR_MIN <= status < _SERVER_ERROR_MIN`」改为「`status >= _SERVER_ERROR_MIN`」：
   常量更名 `HTTP_EXCEPTION_4XX_FALLBACK_CODE` → **`HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE`**
   （值仍是平台表内的 `1001`）。**为何更名**：判据不再等于「4xx」，留着 4xx 的名字会让名字与行为
   对不上（sub-400 也走它）；段边界常量删掉随之成为死代码的 `_CLIENT_ERROR_MIN`，只留下界 `500`；
4. 四处 docstring/注释同步（模块 docstring 的映射表 + 新增「无体状态」段、
   `register_exception_handlers`、`_handle_http_exception`、`_http_exception_info`），并按控制者要求
   **写明该分支当前不可达**（路由层只抛 404/405，业务代码抛 `AiCoreError`），是刻意镜像框架契约。

**为什么 sub-400 落 `1001` 而不是 `5000`**：`1xx`/`2xx`/`3xx` 不是服务端故障，落 `5000` 等于向监控
发「内部错误」假信号（会惊动 on-call）；它们与 4xx 同属「请求这一路不对」，故共用平台表内**既有**的
客户端侧兜底 `1001`——**没有发明新码**（平台表里本来就没有 sub-400 语义的码，控制者口径是
「不为未列出的状态发明映射」）。

**为什么选 `fastapi.utils.is_body_allowed_for_status_code`（控制者要求说明选型）**：

- 它就是 FastAPI 默认 `http_exception_handler` 用的**同一个函数**（实测其 import 行即
  `from fastapi.utils import is_body_allowed_for_status_code`），复用即「与框架契约逐字一致」，
  未来框架调整 1xx/204/205/304 规则时本服务自动跟随；
- **Starlette 侧取不到**：Starlette 1.6.0 的 `starlette._utils` 已无该名字，实测
  `ImportError: cannot import name 'is_body_allowed_for_status_code' from 'starlette._utils'`；
  `fastapi.utils` 属本服务**显式声明**的直接依赖（`pyproject.toml` 的 `fastapi>=0.141`），
  且 `core/errors.py` 的依赖白名单（`fastapi` / `starlette` / `aicore.core.trace`）未被突破。

**修复后实测**（同一探针，`5f8d182`）：

```
HTTPException(204) -> 204 content-type=None headers={'etag':'"v1"','x-request-id':'…'} body=b''
HTTPException(304) -> 304 content-type=None headers={'etag':'"v2"','x-request-id':'…'} body=b''
HTTPException(302) -> 302 application/json {"code":1001,"message":"参数缺失",…}    # sub-400 不再是 5000；Location 保留
route-404          -> 404 application/json {"code":3006,"message":"接口不存在",…}   # 既有行为未变
method-405         -> 405 application/json {"code":1001,"message":"参数缺失",…}     # 既有行为未变
/health            -> 200 application/json {"status":"ok"}                          # 仍是裸响应
```

**新增用例 10 条**（`tests/unit/test_errors.py`，把控制者的三件取证项全部正面钉住）：

| 用例 | 钉住什么 |
| --- | --- |
| `test_bodiless_status_is_returned_without_a_body[204/205/304]`（3 条） | 状态原样、`response.content == b""`、**无 `content-type`**（因此更不可能是 `application/json`）、框架 `detail` 不回显、`ETag` / `Cache-Control` 仍在 |
| `test_sub_400_status_is_enveloped_without_the_internal_error_code`（1 条） | `302` 走**真实链路**：完整信封 + `code != 5000`（另断言 `Location` 透传）。用 `302` 而不是 `204`/`304`：只有它允许响应体，`code` 才真的断言得到（无体状态的码只进日志） |
| `test_sub_400_status_never_maps_to_the_internal_error_code[100/200/204/205/304/302]`（6 条） | `_http_exception_info` 对 sub-400 一律 `!= INTERNAL_ERROR_CODE`、`== 1001`、仍落在 `AICORE_ERROR_CODES` 内、文案取 `DEFAULT_MESSAGES[码]` |

夹具 `http_exception_route` 新增**可选** `headers` 参数（401 的 `WWW-Authenticate: Bearer` 行为逐字保留）；
`test_http_exception_status_mapping_is_exactly_the_locked_pairs` 里 `1001` / `5000` 的**字面量钉住未放宽**，
仅跟随常量更名。**未删改任何既有断言**（全量 284 → 294，既有用例全绿）。

### F2 Minor（注释与实际不符）：`main.py` 仍写「三条路径」

`register_exception_handlers()` 自 `805db9c` 起注册**四条**（业务异常 / 框架 `HTTPException` /
框架 422 / 未预期异常），注释同步（保持中文、简短）：

```diff
-    # 全局异常处理器（Task 2.3）：业务异常 / 框架 422 / 未预期异常统一映射为平台信封。
+    # 全局异常处理器（Task 2.3）：业务异常 / 框架 HTTPException（路由 404、405 等）/
+    # 框架 422 / 未预期异常，四条路径统一映射为平台信封（无体状态按框架契约回无体响应）。
     # 注册只改 app.exception_handlers，不读配置，create_app() 仍是纯装配函数。
```

### F3 验证证据（真实输出，均在提交 `5f8d182` 的工作区上复跑）

```
> pytest tests/unit/test_errors.py -p no:cacheprovider
94 passed in 1.04s                      # 原 84 → 94（+10）

> pytest -p no:cacheprovider
294 passed, 7 skipped in 2.91s          # 原 284 → 294；7 skipped 是既有的 integration 标记

> $env:COVERAGE_FILE = .venv\.coverage23fix2final; pytest -p no:cacheprovider --cov --cov-report=term-missing
src\aicore\core\errors.py                    113      0   100%
TOTAL                                        345     17    95%
Required test coverage of 80.0% reached. Total coverage: 95.07%

> ruff check . --no-cache
All checks passed!

> ruff format --check src\aicore\core\errors.py src\aicore\main.py tests\unit\test_errors.py --no-cache
3 files already formatted

> mypy src --cache-dir .venv\.mypy_cache
Success: no issues found in 51 source files

> lint-imports --config .importlinter --no-cache
Contracts: 4 kept, 0 broken.            # 「core 不得依赖任何业务层」KEPT；新 import 只有 fastapi.utils
```

`errors.py` 100% 行覆盖保持：新增的无体分支由 3 条 204/205/304 用例覆盖，重写后的两档兜底分别由
405（`< 500`）与 503（`>= 500`）覆盖。

### F4 阴性实跑（两处变异都变红，还原按字节 + sha256 校验）

受验版本 sha256（`services/aicore/src/aicore/core/errors.py`，LF 行尾 / 596 行）：
**`C67B45169D22688FBBA71401D65CD4779D7AF0EC690E6CAA1EC367E98A0CA05D`**

| 变异 | 命令 | 结果 |
| --- | --- | --- |
| **A**：把 `if not is_body_allowed_for_status_code(info.status_code):` 改成 `if False:`（即处理器**永远发有体响应**，正是复评描述的错误实现） | `pytest tests/unit/test_errors.py -k bodiless` | **`3 failed, 91 deselected`**，红的**恰好**是三条新用例 `test_bodiless_status_is_returned_without_a_body[204/205/304]`；失败形态就是缺陷本身：`assert b'{"code":1001,…}' == b''` |
| **B**：把判据改回修复前的 `400 <= status_code < _SERVER_ERROR_MIN`（4xx→1001、**sub-400→5000**） | `pytest tests/unit/test_errors.py -k "sub_400 or disallowed_method or unmatched_route"` | **`7 failed, 2 passed`**，红的**恰好**是本轮新增的 7 条 sub-400 用例（`assert 5000 == 1001`）；404/405 两条既有用例仍绿 —— 证明该变异只动了 sub-400 这一档，没有误伤既有口径 |

两处变异都按**字节复制**还原，还原后 sha256 与变异前**逐字符一致**（`C67B4516…` 前后相同），
复跑 `94 passed`（模块）/ `294 passed, 7 skipped`（全量）。

（附记一次**无效变异**：我先把 B 写成 `400 <= status < 500 ? 5000 : 1001`（两个常量写反），得到
`1 failed, 8 passed` —— 405 变红而 sub-400 全绿。正因为它**不是**修复前的口径，我重做了忠实复现的
B，只采信后者。）

### F5 改动文件

```
5f8d182 fix(aicore): 无体状态不再套信封并修正 sub-400 业务码
 services/aicore/src/aicore/core/errors.py | 54 ++++++++++----  (54+/17-)
 services/aicore/src/aicore/main.py        |  3 +-            ( 2+/ 1-)
 services/aicore/tests/unit/test_errors.py | 95 ++++++++++++--- (87+/ 8-)
 3 files changed, 143 insertions(+), 26 deletions(-)
```

`git status --short` 仅剩控制者原有的未跟踪 `.sdd-tools.py`；本轮探针与临时件（含 venv 下的
`.coverage23fix2*`、`errors.py.fix2base` / `errors.py.fix2final` / `commitmsg.txt`）**已全部删除**，
`git diff HEAD --stat` 为空。

### F6 pre-commit / commit-msg 的等价复核（`sh` 缺失，`--no-verify` 已授权）

`.githooks/pre-commit` 六项逐条重放（命令与 hook 内一致，全部在 `git add` 之后、`commit` 之前执行）：

| hook 检查 | 复核命令 | 结果 |
| --- | --- | --- |
| ① 合并冲突标记 | `git diff --cached -U0 \| Select-String '^\+<<<<<<<($\| )\|^\+=======$\|^\+>>>>>>>($\| )'` | **0 命中** |
| ② 行尾空白 / 文件末尾多余空行 | `git diff --cached --check` | 退出码 **0**、无输出 |
| ③ 大文件 >1MB | `Get-Item` 三个暂存文件 | 30887 / 3128 / 42166 bytes |
| ④ 私钥块 / 云密钥 | 同 hook 的 `BEGIN …PRIVATE KEY\|AKIA…\|ASIA…` 正则重放 | **0 命中** |
| ⑤ 疑似硬编码凭据 | 同 hook 的 `P` 排除 `EX` 后重放 | **0 命中** |
| ⑥ 新增真实 `.env` | `git diff --cached --name-only --diff-filter=A` | 本次**无新增文件**（0 命中） |
| commit-msg | `^(feat\|fix\|…)(\([^)]*\))?: .+` 正则匹配 | `fix(aicore): 无体状态不再套信封并修正 sub-400 业务码` 通过；**无 `[AI]` 前缀**；与 805db9c 一致**未加** `Co-authored-by` trailer |

另按 `commit-check` 技能语义清单自查：注释文档中文 / 标识符英文（`DEVELOPMENT_CONSTRAINTS.md` §2）、
无真实密钥、单一逻辑变更（一条 parity 修复 + 一条注释订正，测试随实现同批）、
**未放宽任何已有检查**（无新增 `# type: ignore` / `noqa`；`ruff` 选择集与 `strict` 均未动）。

### F7 自审发现

1. **常量更名是**本轮唯一的对外符号变化：`HTTP_EXCEPTION_4XX_FALLBACK_CODE` →
   `HTTP_EXCEPTION_SUB_5XX_FALLBACK_CODE`（值仍 `1001`）。全仓 grep 确认引用点只有本模块与
   `test_errors.py`（两处），更名后无残留；值本身的字面量钉住**未放宽**。
2. **无体分支的日志**用 `get_trace_id()` 而不是信封里的 traceId：该分支不构造信封，
   若强行构造再丢弃等于白造一个 dict（也会让「无体」这条路径多一次无谓分配）；
   日志仍带 method / path / `code` / traceId 四个排障字段，与其余三条路径同形。
3. **`Response` 的类型注解**：`fastapi.responses.Response is starlette.responses.Response` 实测为
   `True`，故注解换成它不引入新依赖；`app.add_exception_handler` 的 `ExceptionHandler` 契约
   接受 `Response`（mypy strict 通过，51 文件 0 问题）。
4. **测试不能只测 `_http_exception_info`**：204/304 的 `code` 进不了响应体，只在函数层钉住会漏掉
   「处理器是否真的用了映射结果」这一环，故额外用 `302` 走真实 HTTP 链路（§F1 表格第 2 条用例）。
5. **遗留观察（不阻塞，供控制者判断是否需要后续任务）**：`205 Reset Content` 与 `304` 同属无体档，
   但平台表里没有任何「无体状态」语义的码——本轮的处置是**不发明码**（落 `1001`，且这些状态的
   `code` 通常不出现在响应体里）。若将来有人真的 `raise HTTPException(302)`，客户端会拿到一个带
   信封体的 3xx，`Location` 仍在；这属于「历史代码误用框架异常」的场景，§9.5 已写明新代码 MUST NOT
   这样写。
