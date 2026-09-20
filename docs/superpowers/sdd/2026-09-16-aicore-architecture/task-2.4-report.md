# Task 2.4 报告：统一响应信封

- **状态**：DONE
- **分支 / 提交**：`feature/aicore-architecture` @ `8bffbf7` `feat(aicore): 落地统一响应信封模型`
- **基线 HEAD**：`5f8d182`（任务书给出）
- **工作树**：`D:\progrom\.worktrees\aicore-architecture`

---

## 1. 交付物

| 文件 | 状态 | 一行职责 |
| --- | --- | --- |
| `services/aicore/src/aicore/core/envelope.py` | 修改（1 行 → 146 行） | **信封形状的唯一所有者**：`Envelope[T]` 泛型模型（四必填 + 可选 `data`）、`SUCCESS_CODE=0`、`utc_timestamp()`、唯一构造出口 `ok` / `fail` |
| `services/aicore/tests/unit/test_envelope.py` | 新建（686 行 / 44 条用例） | 平台契约对齐、成功码 0、`fail` 语义、`timestamp` 形状、traceId 与请求头同源、逐路由落地与 OpenAPI、反向对齐、`/health` 裸响应、两条结构红线（含阴性对照） |
| `services/aicore/src/aicore/core/errors.py` | 修改（+5 / −8 行） | 删掉本地的 `_utc_timestamp()`，改从 `core/envelope.py` 导入 `utc_timestamp()`（**唯一**行为变化是助手来源；输出逐字节不变） |

未改动：`api/health.py`、`main.py`、`.importlinter`、任何配置文件。没有引入中间件。

---

## 2. 关键决定

### (a) 时间戳助手：谁 import 谁 —— `errors.py → envelope.py`

**决定**：`utc_timestamp()` 定义在 `core/envelope.py`（公开名，去掉 `errors.py` 里原来的私有
`_utc_timestamp()`），`core/errors.py` 顶部 `from aicore.core.envelope import utc_timestamp`。

**理由**：

1. 任务书要求「`timestamp` 由信封模块自己生成」且「不得重复第二个时间戳助手」——两句话同时成立的
   唯一形态就是「信封定义、错误处理器复用」；
2. **依赖方向不能反过来**：信封模型是形状的所有者，`errors.py` 只是它的消费者（其 docstring 自己
   写着「`Envelope` 模型由 Task 2.4 拥有」）。若让 `envelope → errors` 导入，则模型依赖「异常 →
   业务码」映射层；更致命的是，`errors.py` 将来按设计改用 `Envelope.fail(...)` 时立刻构成循环导入；
3. **无环**：`trace ← envelope ← errors`（`errors.py` 本来就依赖 `core.trace`），import-linter
   `core 不得依赖任何业务层` 仍是 KEPT（实测见 §5）；
4. 行为等价：两处实现是同一个表达式 `datetime.now(UTC).isoformat().replace("+00:00", "Z")`，
   故 `errors.py` 的响应体逐字节不变（`test_errors.py` 的 72 条用例全绿佐证）。

**测试是否钉住**：`test_timestamp_helper_has_a_single_source` 断言
`errors_module.utc_timestamp is envelope_module.utc_timestamp`、`errors.py` 不再有
`_utc_timestamp` 属性、函数源码文件就是 `core/envelope.py`。

### (b) 结构扫描如何对待 `core/errors.py` —— 按文件的**窄豁免** + 承重自检

**决定**：扫描范围是 `src/aicore/**/*.py` **全量**（含 `core/`），排除 `core/envelope.py`（正本）
与 `HAND_ASSEMBLY_EXEMPT_FILES = {"core/errors.py"}`（唯一的窄豁免）。

**理由（为什么不用「只管 routes/services」的方案）**：

1. 「只管 routes/services」等于把 `core/` 整层划出红线——`core/` 里任何**新**模块都能悄悄手工
   拼装信封而扫描器一声不吭，红线被拆掉一半；按文件豁免则只放过**已经过评审的那一处**；
2. 豁免不是空白话：`test_hand_assembly_scan_is_not_vacuous` 断言「把豁免关掉，`core/errors.py`
   今天就应当被判违规」（实测通过）——它同时证明扫描器在真实代码上有判别力、豁免清单没写歪，
   并且一旦 `errors.py` 改用 `Envelope`，用例变红提示删除失效豁免；
3. 判据是「映射字面量里**四个键全中**」而不是「含 `code`/`message`」：后者在本仓库遍地都是
   （业务 DTO、日志字段），放宽判据会让扫描器变成噪音源最终被关掉；
4. `dict(code=..., message=..., traceId=..., timestamp=...)` 这种等价拼装口同样覆盖（否则留了
   一条现成的绕过通道）；`{**other}`、变量键无法静态判定，已在 docstring 写明这是有意接受的边界。

**「扫描器永远绿」的防线**（三件套，都在同一文件里）：

- 非空下限：`iter_source_files()` 至少 20 个 .py（实际 51），否则判失败；
- 阴性对照：4 个违规样本（字面量 / 带 data / `dict(...)` / 嵌套）必须被报、3 个合法样本
  （少一个键、键名只出现在字符串里）必须不报；
- 第二条红线：`find_envelope_model_classes()` 扫「类体字段注解覆盖四键的类」，`core/envelope.py`
  之外一律判违规；正本自己必须被这个判据认出来（断言 `["Envelope"]`），另有第二个模型的阴性对照。

### (c) 其余决定（超出任务书，需控制者知情）

| 决定 | 取值 | 依据 / 说明 |
| --- | --- | --- |
| 成功文案 | `SUCCESS_MESSAGE = "成功"` | `_common` 只锁了错误文案表（`DEFAULT_MESSAGES`）与 `code===0`；`Envelope.message` 的 `example: ok` 是 schema 占位示例，不是锁定值。取中文与平台其余面向用户文案同口径。**若控制者要按 `_common` 示例取 `ok`，改一处常量即可** |
| `extra` | `extra="forbid"` | 多一个键就是形状被改过（拼装残留 / 字段名写错），当场炸而不是静默丢弃；顺带让反向对齐成为强断言（多键、少键都失败） |
| `data` 缺省语义 | 键**始终在**、值 `null` | 失败路径本来就在发 `"data": null`；省略键会让平台出现两种形状（`test_data_is_serialized_as_json_null_rather_than_omitted`） |
| 泛型写法 | PEP 695 `class Envelope[T](BaseModel)` | ruff `UP046` 要求；`Envelope[T]` 用法与任务书接口完全一致，mypy/OpenAPI/参数化校验全部实测通过 |
| `/metrics` | 存在才断言（当前 skip） | 端点属后续可观测性任务；写成「端点到岗自动生效」的守护，显式 skip 而不是静默通过 |
| 报告 | 不入库 | `.superpowers/` 在仓库中未被跟踪（`git ls-files .superpowers` = 0），与前序任务一致 |
| 提交 trailer | 不加 `Co-authored-by` | 任务书只要求 Conventional Commits + 无 `[AI]` 前缀；仓库近 6 次提交均无 trailer，从既有约定 |

---

## 3. 反向对齐结果（Task 2.3 的承诺是否兑现）

**结论：通过，且是双向钉住的。**

1. `test_error_body_builder_output_validates_against_the_envelope_model`（参数化覆盖
   `AICORE_ERROR_CODES` 全部 10 个码）：`_error_body(code, DEFAULT_MESSAGES[code])` 的键集合恰为
   五键、`Envelope.model_validate(...)` 通过，且 `code`/`message`/`data=None`/`traceId`(16 hex)/
   `timestamp`(UTC Z) 逐项复核；
2. `test_failing_http_responses_validate_against_the_envelope_model`：**真实请求**走完中间件 →
   异常处理器 → JSON 序列化后，业务 404 与框架 404 的响应体都通过 `Envelope.model_validate`；
   并复核「路由 404 与业务 `NotFoundError` 文案可区分」（Task 2.3 的口径未回归）；
3. 未发现任何需要改 `errors.py` 形状才能对齐的问题——`errors.py` 的行为改动为零（只换了时间戳
   助手的来源），**没有出现「为了让校验通过而改被测代码」的情况**。

---

## 4. 验证命令与真实输出

工作目录 `services\aicore`；每次 Python 调用均设 `PYTHONUTF8=1` 与
`PYTHONPYCACHEPREFIX=<venv>\.pycache`（源树内无新增任何 `.pyc`，见 §7）。

```text
$ .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
337 passed, 8 skipped in 4.65s

$ .\.venv\Scripts\python.exe -m pytest tests/unit/test_envelope.py -p no:cacheprovider
43 passed, 1 skipped in 0.35s          # 新增 44 条（1 条是 /metrics 前置守护，显式 skip）

$ .\.venv\Scripts\ruff.exe check . --no-cache
All checks passed!

$ .\.venv\Scripts\mypy.exe src --cache-dir .venv\.mypy_cache
Success: no issues found in 51 source files

$ .\.venv\Scripts\lint-imports.exe --config .importlinter --no-cache
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.
- No matches for ignored import aicore.service.** -> aicore.provider.base.   （基线即存在的 warning，未变）
```

基线对照（同一命令，改动前）：`294 passed, 7 skipped` → 现在 `337 passed, 8 skipped`（+43 通过、
+1 skip，与新增用例数一致）；ruff / mypy / 契约在改动前后均干净。

**变异测试（自证用例有判别力，临时改动后按 sha256 逐字节还原）**：

| 变异 | 预期被谁抓 | 实测 |
| --- | --- | --- |
| `SUCCESS_CODE = 200` | 成功码用例 | FAILED `test_success_code_is_zero_and_must_never_become_http_200` + 路由用例 |
| `timestamp` 给上缺省值 | 必填集合用例 | FAILED `test_required_fields_match_the_platform_contract` + OpenAPI 用例 |
| 时间戳校验器失效 | 五种非法取值用例 | FAILED ×5（非 UTC 偏移 / 无时区 / 空格分隔 / `+00:00` / 非时间串） |
| `errors.py` 多发一个键 | 反向对齐用例 | FAILED 全部 10 个码 + 端到端反向对应用例 |
| 去掉 `extra="forbid"` | 额外键用例 | FAILED `test_unknown_keys_are_rejected` |
| `ok()` 不再取 `get_trace_id()` | traceId 用例 | FAILED ×10（含两条真实请求用例） |

还原校验：`restore envelope: True / errors: True`（sha256 与变异前一致）。

---

## 5. 变更文件

```text
$ git show --stat --oneline HEAD
8bffbf7 feat(aicore): 落地统一响应信封模型
 services/aicore/src/aicore/core/envelope.py | 147 +++++++++++++++++++++-
 services/aicore/src/aicore/core/errors.py   |  13 +--
 services/aicore/tests/unit/test_envelope.py | 686 ++++++++++++++++++++++++++++
 3 files changed, 837 insertions(+), 9 deletions(-)
```

`git status --porcelain` 只剩 `?? .sdd-tools.py`——该文件在我开始前就已存在（会话首次 `git status`
即有），不是本次产物，故未处理、未提交。

**提交前逐项复核的 hook 项**（`.githooks/pre-commit` + `commit-msg` 为 sh 脚本，本沙箱无 `sh`，
控制者已授权 `--no-verify`）：

| # | hook 检查 | 实测 |
| --- | --- | --- |
| ① | 暂存新增行含合并冲突标记 | 0 |
| ② | `git diff --cached --check`（行尾空白 / 文件末尾多余空行） | 0（exit 0） |
| ③ | 暂存文件 >1MB | 0（3 个文件：7,674 / 30,939 / 31,694 字节） |
| ④ | 私钥块 / 云密钥（`BEGIN … PRIVATE KEY`、`AKIA…`、`ASIA…`） | 0 |
| ⑤ | 疑似硬编码凭据正则（含 hook 的排除词） | 0 |
| ⑥ | 新增真实 `.env` | 0 |
| ⑦ | `commit-msg` 的 Conventional Commits 格式 | `feat(aicore): 落地统一响应信封模型` 匹配；无 `[AI]` 前缀，subject 中文 |

---

## 6. 需求逐条对照

| 要求 | 落点 |
| --- | --- |
| 四必填 + `data` 可选缺省 `None` | `Envelope.code/message/traceId/timestamp` 无缺省；`data: T \| None = None`；用例双侧比对平台 `required`/`properties` |
| camelCase `traceId`（非 `trace_id`） | 字段名直写；`test_field_names_are_camel_case_trace_id_not_snake_case`；ruff `N815` 以带理由的 `# noqa` 豁免 |
| 成功码 `0`（不是 `200`） | `SUCCESS_CODE=0`；用例名与断言消息写明原因；另断言 `0 ∈ ErrorCode` 且 `200 ∉ ErrorCode` |
| `fail` → `data = None`，码/文案保留 | `Envelope[None](...)`；6 个码参数化用例 |
| `timestamp` 模块自生（UTC/`Z`，不接受调用方传入） | `utc_timestamp()` + 字段校验器；签名用例钉死 `ok(data)` / `fail(code, message)` 无时间戳参数 |
| `traceId` 只用 `core/trace.py` | `ok`/`fail` 内调 `get_trace_id()`；真实请求用例证明信封与错误路径取到同一个头值 |
| 泛型可用、`response_model` + OpenAPI 正常 | `Envelope[EchoResult]` 探针路由：序列化、反解、组件 `$ref` 与 `required` 断言；`create_app().openapi()` 亦断言 |
| 不用全局中间件、不动 `api/health.py` | 无中间件改动；`/health` 裸响应用例（被包住即变红）；`api/health.py` 零改动 |
| 唯一信封模型 | `find_envelope_model_classes` 扫全树 + 阴性对照 |
| 不手工拼装信封 | 四键映射字面量扫描 + 窄豁免 + 承重自检 + 阴性对照 |
| 中文注释、英文标识符 | 两个文件全中文 docstring/注释；标识符全英文 |
| 无 sleep / 无网络 / 无数据库 | 全用例纯进程内；全套 4.65s |
| 不留残留文件 | 变异测试的备份目录已删；源树无新增 `.pyc`；临时提交信息文件已删 |

**未做（刻意）**：`Envelope.fail` 不校验 `code != 0`（不替调用方发明码值策略）；`Envelope` 不加
`traceId` 非空/格式约束（网关注入值可长于 16 hex，加了会与 `_common` 的 `type: string` 分叉）。

---

## 7. 自审发现

1. **一次编辑事故，自查修复**：改 `test_envelope.py` 的 SIM300 时误删了
   `def scan_hand_assembled_envelopes(...)` 的函数头，留下一个「函数体只剩裸 docstring」的形态
   （语法合法、ruff 不报）。读回文件时发现并修复。若漏掉，扫描用例会以 `TypeError` 报错——
   测试能兜住，但这是靠回读而不是靠工具发现的。
2. ruff 首轮 7 处问题全部修净，而非 `noqa` 掩盖：`UP046`→PEP 695 泛型（mypy/OpenAPI/参数化校验
   重新实测）、`E501`×3、`SIM300`×4（改用 `set.issubset` / `sorted(...)` 比较）。仅 `traceId`
   字段保留 `# noqa: N815` 并写明理由（平台契约字段名就是驼峰）。
3. **接口可用性实测**（不是推断）：pydantic 2.13.5 下 `Envelope[Foo].model_validate(Envelope.ok(foo))`
   成立——未参数化实例能被 `response_model=Envelope[Foo]` 重新校验，已在 docstring 写明，并建议
   路由统一写 `Envelope[XxxResult].ok(...)`（静态类型即可对上）。
4. 平台 schema 与本模型并非逐字节相同：本模型多出 `additionalProperties: false`（`extra="forbid"`
   的产物），这是**更严**的一侧，且 `_common` 未禁止；用例只比对 `required` 与 `properties`，不比对
   该键，避免把「更严」误判成「分叉」。
5. 行尾与编码：三个文件的字节检查为 `CRLF=0`、`LF-only`、无 BOM、文件末尾有换行——与仓库其余
   文件一致（`core.autocrlf=true` 只影响 checkout，未污染本次改动）；`git diff` 无整文件重写噪音。
6. 残留物检查：`src/`、`tests/` 下无本次会话新增的 `.pyc`（全部 `__pycache__` 内容时间戳早于会话，
   我的 Python 调用全部走 `PYTHONPYCACHEPREFIX`）；变异测试的备份目录 `.venv\.mutation-backup`
   已删除；`git status` 只剩会话前就存在的 `?? .sdd-tools.py`。

---

## 8. 关注点（供控制者裁量）

1. **成功文案 `"成功"` 是我定的**：平台没有锁定成功文案（`_common` 只有 `message: ok` 这个 schema
   示例）。若前端/产品口径要 `ok`，改 `SUCCESS_MESSAGE` 一处即可，用例不需要动。
2. **`extra="forbid"` 会让「路由返回超集 dict」变成 500**（FastAPI 的 ResponseValidationError）。
   这是刻意的 fail-fast，但后续任务写路由时要返回**模型实例或恰好五键的 dict**，不能顺手多塞字段。
   这是本任务对后续任务唯一的硬性使用约束，已在模块 docstring 写明。
3. **`/metrics` 的前置守护当前是 skip**：全量输出因此多一条 skip（8 vs 基线 7）。端点到岗后自动
   开始断言；若控制者不接受 skip 形态，可改为「断言 app 上没有全局响应包装中间件」的等价写法
   （但那会误伤将来合法的全局中间件如 CORS）。
4. **结构扫描住在 `tests/unit/test_envelope.py`**：任务书的文件清单只允许新建这一个测试文件，
   故未放进仓库既有的 `tests/structural/`。后续若做结构检查归口，建议整段迁到
   `tests/structural/test_source_guards.py` 同侧。
5. **`task-2.4-brief.md` 在 SDD 目录中不存在**（该目录有 1.1–1.4、2.1、2.3、2.5、3.1 的 brief，
   唯独缺 2.4）。本次实现以控制者给出的扩充任务书 + `docs/superpowers/plans` Task 2.4 与
   `docs/superpowers/specs` §4.4 为准；若那份 brief 另有验收细节，需要控制者比对补差。
6. `errors.py` 与 `envelope.py` 之间新增了一条 `core` 内部依赖（errors → envelope）。它对
   import-linter 的四条契约无影响（实测 4 kept），但如果将来有「`core` 内模块必须互不依赖」的
   新契约，这条边需要显式放行——按本任务书的要求，它是**刻意**的单一来源设计。

---

## 9. 交付摘要

- 唯一信封模型 `Envelope[T]`（四必填 + `data` 可选），成功码 `0`，`timestamp` 自生（UTC/`Z`），
  `traceId` 只用 `core/trace.py`；逐路由 `response_model` 落地，零中间件，`/health` 仍裸。
- 时间戳助手单一来源：**`errors.py` 导入 `envelope.py`**（方向理由见 §2a），`errors.py` 输出不变。
- 结构红线两条 + 各自阴性对照 + 非空下限 + 豁免承重自检；`core/errors.py` 以**按文件的窄豁免**
  登记（理由与替代方案取舍见 §2b）。
- 反向对齐：**通过**（逐码 + 真实失败请求双路径），未改动 `errors.py` 的形状。
- 门禁：`pytest 337 passed / 8 skipped`、`ruff All checks passed`、`mypy Success (51 files)`、
  `lint-imports 4 kept / 0 broken`；提交 `8bffbf7`。
