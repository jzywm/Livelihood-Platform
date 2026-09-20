# Task 4.5 报告：任务提交与状态机（第 4 组 T1）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
**交付时间**：2026-09-19
**结论**：五条验收命令全部 **EXIT=0**；工单 §3 的 24 条用例全部落地并逐条对照；
偏离项 11 条、没做到的事 12 条，逐条在 §5/§6 写明（**没有任何一条被美化**）。

---

## 0. 一句话结论

`POST /aicore/ocr`（受理即返回任务号，落 `ai_task`，幂等）与 `GET /aicore/tasks/{taskId}`
（仅本人可查，跨账号 `2002` 且不泄露任何内容）已按工单实现并自证；
状态机是纯函数（`er.md` §7.1 现读比对）；组合根补齐了 `app.state.engine_factory` 装配；
契约 1 曾真的变红，**没有放宽契约**，而是把「取行 + 归属判定」下沉到 service 层解决。

---

## 1. 交付物清单

### 1.1 新建（源码）

| 文件（相对 `services/aicore/`） | 行数 | 角色 |
|---|---|---|
| `src/aicore/service/task/state.py` | 126 | 状态机（纯函数、无 IO）：四个状态常量、`TERMINAL_STATUSES`、`ALLOWED_TRANSITIONS`、`IllegalTransitionError(3007)`、`assert_transition`、`is_terminal` |
| `src/aicore/service/task/submit.py` | 251 | 提交编排：`compute_idem_key`（显式优先 / sha256 派生）、`new_task`（逐列对齐 `er.md` §6.1）、`submit_ocr_task`（查幂等 → 落库 → 写后立即读）、`SubmitOutcome` |
| `src/aicore/service/task/query.py` | 111 | **工单未列**（见偏离 D2）：取行 + 归属判定（`load_owned_task`）+ 输出白名单快照（`TaskSnapshot` / `snapshot_of`） |

### 1.2 修改（源码）

| 文件 | 行数（前 → 后） | 改动 |
|---|---|---|
| `src/aicore/api/deps.py` | 26 → 159 | 加 `ACCOUNT_ID_HEADER`、`SessionFactory` / `EngineFactoryLike` 两个就地 `Protocol`、`get_engine_factory`、`get_account_id`、`get_now` |
| `src/aicore/api/ocr.py` | 1（docstring 空壳）→ 279 | 请求体/回执模型、`require_image_key` / `require_doc_type` / `validate_scene`、`POST /aicore/ocr`（202）、注册表准入 `assert_submittable` |
| `src/aicore/api/tasks.py` | 1（docstring 空壳）→ 217 | `TaskResult`、`GET /aicore/tasks/{taskId}`（主库只读会话）、`_to_result` / `_utc_iso` |
| `src/aicore/main.py` | 128 → 151 | lifespan 装配 `app.state.engine_factory = EngineFactory(settings)` + 关闭期 `dispose()`；`create_app()` 挂 `ocr.router` / `tasks.router` |

### 1.3 新建（测试）

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `tests/unit/test_task_state.py` | 230 | 工单 §3 第 1~8 条（9 个用例） |
| `tests/api/test_ocr_submit.py` | 380 | 第 9~17 条 + 注册表准入接线（14 个用例） |
| `tests/api/test_task_poll.py` | 362 | 第 18~24 条 + 3 条守卫（10 个用例） |

**未改动**（工单「不可改」清单）：`provider/**`、`repository/**`、`core/config.py`、`core/errors.py`、
`core/envelope.py`、`pyproject.toml`、`.importlinter`、`tests/` 下既有文件、`tests/conftest.py`。
`git add` / `git commit` 全程未执行。

---

## 2. 五条验收命令的原始输出

### 2.1 定向用例

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_task_state.py tests/api/ -q
```

```
.........................................                                [100%]
41 passed in 1.63s
--- EXIT=0 ---
```

### 2.2 全量（非集成）

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
```

```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\progrom\.worktrees\aicore-architecture\services\aicore
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0, cov-7.1.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 1208 items / 19 deselected / 1189 selected

tests\api\test_deps.py .....                                             [  0%]
tests\api\test_health.py ...                                             [  0%]
tests\api\test_ocr_submit.py ..............                              [  1%]
tests\api\test_task_poll.py ..........                                   [  2%]
tests\repository\test_ddl_matches_er.py ................................ [  5%]
.............................                                            [  7%]
tests\repository\test_migration.py ............                          [  8%]
tests\repository\test_repos.py .....................................     [ 11%]
tests\repository\test_schema.py ....................................     [ 14%]
tests\repository\test_schema_consistency.py ..........                   [ 15%]
tests\repository\test_session.py .......................                 [ 17%]
tests\repository\test_sharding.py ...................................... [ 20%]
..................................                                       [ 23%]
tests\structural\test_layering.py ........                               [ 24%]
tests\structural\test_source_guards.py .......................ssssssssss [ 27%]
s....................................                                    [ 30%]
tests\unit\test_config.py .............................................. [ 34%]
..............................................                           [ 38%]
tests\unit\test_config_startup.py ...................................    [ 41%]
tests\unit\test_envelope.py .......................................s.... [ 44%]
.                                                                        [ 44%]
tests\unit\test_errors.py .............................................. [ 48%]
................................................                         [ 52%]
tests\unit\test_idgen.py .......................                         [ 54%]
tests\unit\test_logging.py ............................................. [ 58%]
.....                                                                    [ 58%]
tests\unit\test_models.py .............................................. [ 62%]
........................................................................ [ 68%]
........................................................................ [ 74%]
......                                                                   [ 75%]
tests\unit\test_provider_base_contract.py .............s................ [ 77%]
.                                                                        [ 77%]
tests\unit\test_provider_errors.py ...........                           [ 78%]
tests\unit\test_provider_guard.py ...............................        [ 81%]
tests\unit\test_provider_mock.py ....................................... [ 84%]
.........                                                                [ 85%]
tests\unit\test_provider_real.py ....................................... [ 88%]
............                                                             [ 89%]
tests\unit\test_provider_results.py .....................                [ 91%]
tests\unit\test_provider_selector.py ................................... [ 94%]
                                                                         [ 94%]
tests\unit\test_task_registry.py .........................s...           [ 96%]
tests\unit\test_task_state.py .........                                  [ 97%]
tests\unit\test_trace.py ...........................                     [100%]

============== 1175 passed, 14 skipped, 19 deselected in 48.91s ===============
--- EXIT=0 ---
```

**全量判据：EXIT=0 且 failed == 0**（按工单要求，MUST NOT 写固定计数；`skipped` 会随
`provider/` 下文件数变化）。

### 2.3 ruff（范围含 `tests`）

```powershell
.\.venv\Scripts\ruff.exe check --no-cache src tests
```

```
All checks passed!
--- ruff EXIT=0 ---
```

### 2.4 mypy

```powershell
.\.venv\Scripts\python.exe -m mypy --strict src
```

```
Success: no issues found in 59 source files
--- mypy EXIT=0 ---
```

### 2.5 import-linter（契约）

```powershell
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

```
--------- Contracts ---------

Analyzed 59 files, 88 dependencies.
-----------------------------------

api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.

-------- Warnings --------
service 层只可与 provider.base 交互，不得依赖具体通道实现
- No matches for ignored import aicore.service.** -> aicore.provider.base.
--- lint-imports EXIT=0 ---
```

> 那条 warning 是**既有的**（`.importlinter` 里 `unmatched_ignore_imports_alerting = warn`）：
> 本任务的 service 代码不依赖 `provider.base`（OCR 提交不调模型，通道调用归 Task 4.7/5.x），
> 故放行表达式暂时匹配不到真实导入。契约本身 **4 kept**。

---

## 3. 逐条用例对照（工单 §3 的 24 条）

| # | 要求 | 落点（用例） | 备注 |
|---|---|---|---|
| 1 | 三条合法转移 | `test_legal_transitions_from_processing_are_accepted` | 参数化用**现读 er.md** 的结果 |
| 2 | 终态两两 6 条被拒（3007） | `test_all_six_terminal_to_terminal_transitions_are_rejected` | 先断言组合数 == 6 |
| 3 | 终态 → PROCESSING 被拒 | `test_terminal_states_cannot_reopen_to_processing` | |
| 4 | 自转移被拒 | `test_self_transitions_are_rejected_including_processing` | 覆盖四个状态 |
| 5 | 未知取值 → 1003 | `test_unknown_status_value_is_param_error_1003_not_conflict` | 并断言**不是** ConflictError |
| 6 | `is_terminal` | `test_is_terminal_only_for_the_declared_terminal_statuses` | 含 `"processing"` / 带空格 |
| 7 | 表 == er.md 逐字 | `test_transition_table_matches_er_md_verbatim` | 现读 §7.1，双向比对 |
| 8 | 纯函数性（AST） | `test_state_module_is_pure_and_depends_only_on_core_errors` + `test_import_scanner_discriminates` | 附阴性对照 |
| 9 | 202 + TaskAccepted + code 0 | `test_accepted_returns_202_with_the_task_accepted_contract` | 状态码与形状同时断言 |
| 10 | 库内多一行、逐列对齐 | `test_submission_writes_exactly_one_row_with_the_declared_columns` | 10 列逐列 |
| 11 | 显式键幂等 | `test_same_explicit_idempotency_key_returns_the_same_task` | 行数不增 |
| 12 | 同图同类幂等 | `test_same_image_key_and_doc_type_without_header_is_idempotent` | 并钉派生口径 |
| 13 | 不同 docType | `test_different_doc_type_makes_a_different_task` | |
| 14 | 不同账号 | `test_different_account_with_same_image_key_makes_a_different_task` | 并钉「账号不进 idem_key」 |
| 15 | 缺/空/空白身份 → 401+2001 | `test_missing_or_blank_account_header_is_401_and_writes_nothing` | 3 参数化 + 断言零落库 |
| 16 | 非枚举 400+1003 / 缺参 400+1001 / 无 422 | `test_invalid_doc_type_and_missing_image_key_are_400_not_422` + `test_scene_is_validated_but_never_persisted` | 见偏离 D5 |
| 17 | 月边界 | `test_month_boundary_resubmit_creates_a_second_task_by_design` | docstring 写明「设计而非缺陷」；月份见偏离 D6 |
| 18 | PROCESSING 轮询 | `test_processing_task_polls_with_empty_result` | |
| 19 | SUCCEEDED | `test_succeeded_task_reports_progress_and_finished_at` | 直改库 |
| 20 | FAILED + 4003 字符串 | `test_failed_task_reports_error_code_as_a_string` | `isinstance(str)` |
| 21 | 不存在 → 404+3006 | `test_unknown_task_id_is_404_with_code_3006` | 用 `new_id("task")` 现造 |
| 22 | 跨账号 → 403+2002 且不泄露 | `test_cross_account_poll_is_403_and_leaks_nothing` | 逐字段断言不出现 |
| 23 | 账号过滤真的生效 | `test_account_id_really_participates_in_the_filter` | 双向对照（本人 403 / 对方 200） |
| 24 | 出参字段**现读** openapi | `test_response_fields_match_openapi_required_list` + `test_response_enums_track_openapi_and_the_state_machine` | required ↔ 响应体 ↔ 模型必填三向 |
| — | §1.5 会话选型 | `test_session_entries_match_the_declared_split` + 判别力对照 | AST 断言：提交 `write_session` / 轮询 `primary_read_session` |
| — | 注册表准入接线（控制者裁定） | `test_acceptance_path_really_gates_on_the_registry`（2 参数化） | 行为断言，见 §4.3 |

---

## 4. 判别力自证（临时探针，**均已删除**）

探针纪律：新建 2 个临时文件（`tests/api/_probe_sandbox_route.py`、`tests/api/_probe_discriminating.py`），
用完即删；第三次判别力验证改用**内联脚本**（不落文件），未超「> 2 个即停下报告」的红线。
**MUST NOT** 用「改 `src/` 文件 + finally 还原」做变异测试——本次**一次都没有**这么做。

### 4.1 夹具硬伤（D1）的取证探针 —— 5 条原始证据

`tests/api/_probe_sandbox_route.py`（已删）实测输出：

```
A MAIN-THREAD MainThread ['ai_task_202607', 'ai_task_202608', 'ocr_correction_202607', 'ocr_result_202607']
A RESPONSE 200 {"thread":"AnyIO worker thread","tables":[]}
{"level": "ERROR", "module": "sqlalchemy.pool.impl.SingletonThreadPool",
 "message": "Exception closing connection <sqlite3.Connection object at 0x...>",
 "exception": "...sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in
  that same thread. The object was created in thread id 26612 and this is thread id 2732."}
.B RESPONSE 200 {"thread":"AnyIO worker thread","tables":["ai_task_202607","ai_task_202608","ocr_correction_202607","ocr_result_202607"]}
2 passed in 0.13s
```

另有两条环境事实（探针内实测 + 源码核对）：

- `type(engine.pool).__name__ == 'SingletonThreadPool'`，同一引擎主线程看得到 4 张表、
  工作线程看到 `[]`（**每线程一条连接 = 每线程一个空的内存库**）；
- starlette 1.6.0 的 `TestClientTransport.handle_request` 用
  `portal.call(self.app, scope, receive, send)` 把应用跑在 portal 线程；FastAPI 的同步路由
  再落到 `AnyIO worker thread`——两者都不是 pytest 主线程，故 `sandbox_engine` 夹具在主线程
  建的表，路由侧一条也看不到。

### 4.2 关键判据的变异自证（`_probe_discriminating.py`，已删）

| 变异 | 期望 | 实测输出 |
|---|---|---|
| A：`submit_ocr_task` 改成**不落库** | 202 照旧通过、但「库内多一行」判据变红 | `A status = 202` / `A rows = []` |
| B：`load_owned_task` 改成**不比较 account_id** | 越权查询从 403 变 200（证明 403 由账号比较支撑） | `B status = 200` / `B body = {"code":0,...,"data":{"taskId":"task_ce0a...","type":"OCR","status":"PROCESSING",...}}` |

### 4.3 注册表准入的判别力（内联探针，不落文件）

把 `api/ocr.py` 的 `assert_submittable` 换成不做 `implemented` 判定的 `get_policy`，
同时把端点类型改成 `VISION_REVIEW`（M1 预留位）：

```
BYPASS status: 202
BYPASS rows: [{'task_id': 'task_c3e64bf39fac453085ac657966a', 'type': 'VISION_REVIEW'}]
```

对照真实现（用例 `test_acceptance_path_really_gates_on_the_registry`）：**400 + 1003 + 零落行**。
→ 该用例确实由「准入调用在链上」支撑，不是结构断言。

---

## 5. 偏离项（逐条 + 理由）

### D1【夹具硬伤｜实现者发现，控制者已修，无遗留 workaround】

**现象**：`tests/support/db_sandbox.py::build_sqlite_engine()` 原用 `create_engine("sqlite://")`，
内存库的默认池是 `SingletonThreadPool`（每线程一条连接 = 每线程一个空库），而路由跑在
AnyIO 工作线程 → **路由侧看不到任何表**。夹具自证用例 `test_api_client_fixture_reaches_a_writable_sandbox`
之所以绿，是因为它在**主线程直接读写引擎**，把「经真应用发请求」这一环整个绕过去了
（与本项目反复出现的「用例把关键环节替成了桩」同型）。

**该缺陷由实现者（本任务 T1）在实现前发现并上报**，证据见 §4.1 的 5 条原始输出。
**处置：控制者已自行修复**（`db_sandbox.build_sqlite_engine` 改为
`poolclass=StaticPool` + `connect_args={"check_same_thread": False}`，并在 docstring 补了
「内存库必须 StaticPool」一节；另新增 route 级自证用例
`tests/api/test_deps.py::test_sandbox_tables_are_visible_from_a_route`，含去掉 StaticPool 的变异验证）。

**本任务的 workaround：从未落地。** 当时的备选方案是新建 `tests/api/conftest.py`
在包内覆盖 `sandbox_engine`（只覆盖引擎构造、不动 `api_client`、不动 `conftest.py`、不动 `db_sandbox.py`）；
控制者的修复先于该文件创建到达，故 `tests/api/conftest.py` **至今不存在**（无需删除）。
`tests/conftest.py` 与 `tests/support/db_sandbox.py` 本任务**一字未改**。

### D2【新增 `service/task/query.py`（工单 §Files 未列）】

**起因**：契约 1 在实现中真的变红（实测三条边：
`aicore.api.tasks -> aicore.repository.base / .models / .task_repo`）。
轮询要「按任务号取行 + 比账号」，写在路由里就必然 import repository。

**处置**：没有放宽 `.importlinter`、没有删契约。把「取行 + 归属判定」下沉到 service
——`repository/base.py` 的 R6 逐字写着「跨账号越权（`2002`）的判定属 **service** 层」，
`design.md` 禁止项 1 也写着「路由只调 service」。api 侧改吃 `TaskSnapshot`
（service 交出的快照），顺带成为**输出白名单**：`account_id` / `idem_key` / `model_meta`
等内部列根本不进快照，跨账号时天然带不出任何任务内容。

**代价**：多一个文件（工单 §Files 未列）。**控制者已确认这是正确处置**，不是需要批准的偏离。

### D3【`api/deps.py` 新增 `get_now` 时依赖（工单 §1.5 只写了 `get_engine_factory`）】

工单 §2.2 要求 `now` 必须**可注入**（月边界、固定时钟），而路由必须有个地方取「现在」。
补一个 `get_now()` 依赖是唯一不把时间源散进各路由的做法；测试用
`app.dependency_overrides[get_now]` 注入固定时钟。若不补，工单 §3 第 17 条（月边界）与
所有走库用例都无法写（沙盒只建了 `ai_task_202607/202608` 两张月表）。

### D4【关闭期 `dispose()` 释放的是**局部引用**，不是 `app.state.engine_factory`】

工单 §1.5 给的字面写法是 `app.state.engine_factory.dispose()`。**实测该写法会炸**：

- 沙盒替身 `_SandboxSessionFactory`（`tests/conftest.py`）**没有 `dispose()`**，而它在
  `with TestClient(app)` 期间被注入到同一装配点；
- starlette 1.6.0 的 `TestClient.__exit__` → `exit_stack.close()` → `portal.call(self.wait_shutdown)`
  → 关闭期异常被 `self.task.result()` **原样抛回 `with` 块之外**（源码见 §4.1 的机制说明），
  即每个用到 `api_client` 的用例都会在 teardown 变成 ERROR。

故 lifespan 里改为：装配时持有局部变量 `engine_factory`，关闭时 `engine_factory.dispose()`
——「释放自己创建的资源」是组合根唯一能保证的事；替身自己的引擎由它自己的夹具释放。
生产语义不变（生产上无人替换该装配点）。

### D5【本接口的必填 / 枚举走**业务路径**（400 + 1001/1003），不用 pydantic 枚举】

工单第 16 条要求 `docType` 非枚举 → **400** + `1003`、`imageKey` 缺失 → **400** + `1001`，
且「MUST NOT 出现框架原生 422」。而 FastAPI 的 pydantic 校验路径把这两类失败渲染成
**HTTP 422**（`core/errors.py` 的 `VALIDATION_HTTP_STATUS`，第 2 组定档、既有 `test_errors.py` 钉住，
本任务 MUST NOT 改），且 `docs/openapi.yaml` 对本接口只声明 `'400'`、**没有** 422。

两条口径不能同时成立，故：`OcrRequest` 的字段声明为 `str | None`，
由 `require_image_key` / `require_doc_type` / `validate_scene` 显式判定后抛 `ParamError`
（→ 400 + 平台信封）。**代价（如实登记）**：FastAPI 自动生成的 `/openapi.json` 对这三个字段
只显示 `string`（没有枚举与必填约束）；契约权威仍是 `docs/openapi.yaml`
（本项目口径：它是「唯一可手改源」），运行期取值域由 `DocType` / `OcrScene` 两个 `StrEnum` 单点判定。

**边界**：请求体不是 JSON 对象、字段类型不是字符串这类**解析/类型层**失败仍由框架渲染
（422 + `1002`/`1001`）——那是平台全局行为，不属本接口能改的范围；本任务只保证
**本接口声明的必填与枚举**不出现 422（用例正面钉住）。若控制者更希望走框架路径（422），
改动量是 3 行（恢复 `DocType` 注解 + 删三个 `require_*`），但会与第 16 条冲突。

### D6【月边界用例用 202607/202608，工单举例是 2027-03/04】

沙盒只建 `ai_task_202607` 与 `ai_task_202608`（`db_sandbox.py` 注释说明这两个月正是为
「跨月边界」准备的）；工单举例的 2027-03/04 在沙盒里没有物理表。语义逐字一致：
月末最后一毫秒（`2026-07-31T23:59:59.999Z`）提交 → 次月第一毫秒（`2026-08-01T00:00:00.001Z`）
用**同一个显式幂等键**重提 → 不同 `taskId`、两张月表各一行。

### D7【`submit_ocr_task` 增加 `policy` 参数（偏离工单 §2.2 的原签名）】

控制者裁定（2026-09-19）：注册表是任务类型的唯一来源，受理处 MUST 调 `assert_submittable`
并把交出的策略传给 `submit_ocr_task`。故：`submit.py` **删掉**本地 `OCR_TASK_TYPE` 常量，
`submit_ocr_task(..., policy: TaskPolicy)`，`new_task(task_type=policy.task_type, ...)`。
`new_task` 仍**不自己校验**类型（准入判定属注册表职责，重复实现会漂移）。
新增用例 `test_acceptance_path_really_gates_on_the_registry` 做行为断言（见 §4.3）。

### D8【幂等键派生放在 `submit_ocr_task` 内部，路由只传显式头值】

工单 §2.2 的函数签名同时给了 `image_key` / `doc_type` / `idem_key` 三个参数，但没说生效键在哪算。
若在路由算好再传入，`image_key` / `doc_type` 在编排里就**完全用不上**（`ai_task` 没有这两列）；
故生效键由 `compute_idem_key(explicit=idem_key, image_key=…, doc_type=…)` 在 service 内部派生，
两个参数因而都有用途，派生规则也只有一处（属 service 关切，api 只负责读头）。

### D9【回执枚举的字面量重抄 + 两道接线】

mypy **不接受** `Literal[PROCESSING]`（`Final` 变量不能作 `Literal` 参数，实测报
`Parameter 1 of Literal[...] is invalid`），故 `TaskStatusValue` 里只能写字面量。
两个方向都接住：`api/tasks.py` 的 `DECLARED_STATUSES` 把四个常量赋给该字面量类型
（改常量取值即 mypy 报错）；用例断言 `set(DECLARED_STATUSES) == ALL_STATUSES`
且 `defs["TaskStatusValue"]["enum"] == ALL_STATUSES`（加第五个状态即红）。
`ocr.py` 的 `_ACCEPTED_STATUS: Final[Literal["PROCESSING"]] = PROCESSING` 同理。

### D10【`202` 而非 openapi 的 `200`】

控制者裁定（工单 §2.3）：受理语义用 `202 Accepted`，差异在 ledger 登记。
用例**同时**断言「202」与「`TaskAccepted` 契约」，让差异显式可见。

### D11【`TaskResult` 的可选字段给默认值】

`openapi.yaml:789` 的 `required` 只有 `[taskId, type, status, createdAt]`；
故 `progress` / `result` / `errorCode` / `finishedAt` 在模型里带默认值，
用例把「模型必填集合 == openapi required」正面钉住（只比响应体抓不到这件事）。

---

## 6. 没做到的事（如实，不美化）

1. **跨月轮询不成立**：查询窗口是「当前月」（工单 §2.4 的口径），而 `taskId` 是
   `task_` + UUID、**不含时间戳**（`er.md` §5.4 L248），故上月提交、下月查询会 `404`
   （任务其实还在上月表）。要收口需定义查询窗口或建 `task_id → 月份` 路由表，
   **不属本工单**，我没有自行扩大扫描范围（会撞 `er.md` §5.3「跨月查询禁全表扫描 UNION」）。
2. **并发同幂等键提交的竞态未收口**：查幂等与插入是两条独立语句，同一
   `(account_id, idem_key)` 并发提交时第二个 `insert` 会撞 `uk_idem`，
   表现为 **5000（500）**而不是返回原任务号。工单 §2.2 的行为只列了 4 步，我没有自行加分支。
3. **空串 `imageKey` 未被拒**：`openapi.yaml` 对该字段只声明 `type: string`、无 `minLength`，
   本任务不擅自收紧契约（空串会照常派生幂等键并落库）。
4. **跨账号的「尝试访问」会留日志**：响应体已按最严解读最小化（只有
   `code`/`message`/`data:null`/`traceId`/`timestamp`），行内容不进日志；
   但 `core/errors.py` 的统一日志会记录 **method + path**，而 path 里含 `taskId`
   ——即"某人尝试查询过这个任务号"这一事实会留痕（不泄露对方的任何内容，
   但"该号存在"这一点在运维可见范围内）。这是既有错误处理器的行为，我没有改它。
5. **`result` 恒为 `null`**：`OcrResult` 装配归 Task 5.6，故 **SUCCEEDED 的任务现在也没有结果**。
   这是本任务的边界，不是「任务永远没结果」。
6. **没有真实 MySQL 集成用例**：本任务全部走 sqlite 沙盒。故「轮询走主库（读写分离）」
   只有**源码级 AST 断言**（§3 末行），没有真库证据；`ai_task.status/type` 的**原生 enum**
   与 `datetime(3)` 的真实行为也未在本任务验证（沙盒是 VARCHAR+CHECK 与无 fsp）。
7. **`scene` 收下即丢弃**：契约允许、`ai_task` 无该列，但"丢弃"这件事除了源码与用例断言外
   **没有任何运行期可见性**（比如不做日志）；调用方无从知道自己传的 scene 被忽略了。
8. **非终态带 `finished_at` 的脏数据被静默丢弃**：`_to_result` 在非终态一律回 `None`，
   不报警（本任务没有告警通道）。也就是说这种脏数据**不会**被暴露出来。
9. **`compute_idem_key` 的 `None` 分支当前不可达**：签名保留了「调用方选择不去重」的形态
   （列可空、`find_by_idem_key` 分支也写了），但现有实现两条分支都返回字符串
   ——即该分支**没有测试覆盖**（也无法覆盖）。
10. **`type` / `status` 的字面量接线是单向的**：mypy 只能保证「常量 ⊆ 字面量集合」，
    反向（字面量里没有多余成员）靠用例断言，不靠类型系统。
11. **`202` 与前端契约的兼容性未验证**：若前端契约测试按 `200` 断言会红（工单已告知风险），
    我没有前端契约测试可跑，只做了显式断言与登记。
12. **取证探针不在交付物里**：D1 的 5 条证据来自临时探针文件，按纪律已删除；
    复现需按 §4.1 的命令重写（输出已逐字留档）。

---

## 7. 交接事项

1. **Task 5.6**（`OcrResult` 装配）：`api/tasks.py::_to_result` 的 `result=None` 是留给你的接口位；
   `service/task/query.py::snapshot_of` 的字段集是**输出白名单**，新增结果字段时请连它一起改
   （别把 `AiTask` 实体直接塞进 api，会破契约 1）。
2. **Task 4.6/4.7**（执行器）：`submit_ocr_task` 的签名现为
   `(session, *, account_id, image_key, doc_type, idem_key, now, policy)`；
   `policy` 来自 `assert_submittable`，执行器可直接用 `policy.timeout_s` / `retryable` /
   `result_schema`。写终态时请用 `service/task/state.py::assert_transition`
   （本任务已把状态机做成唯一的合法性判定处，`TaskRepo.update_status` 不校验转移）。
3. **`app.state.engine_factory` 的装配点**已按约定就位（`main.py` lifespan）；测试注入替身
   只需满足 `api/deps.py::SessionFactory` 的两个方法（`write_session` / `primary_read_session`）。
   关闭期**不会**对 `app.state` 上的对象调 `dispose()`（理由见 D4）。
4. **工具观察（一条环境坑，供后续任务避坑）**：本机 pwsh 的
   `(Get-Content -LiteralPath <文件>).Count` 给出的行数与实际不符
   （实测 `state.py` 得 76，实际 126；`main.py` 得 102，实际 151），
   而 `.venv` 的 Python 按 `\n` 计数与 read 工具一致。**行长/行数统计请用 Python**，
   别用 `Get-Content.Count`（本项目已两次踩过「Windows 侧工具静默给出错值」）。
