# Task 3.4 报告：会话与连接池

**执行者**：Task 3.4 实现者（subagent）· **日期**：2026-09-18
**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
**结论**：交付接口 100% 落地；8 条用例全绿（含 2 条真实 MySQL 集成）；
全量基线 `827 passed, 8 skipped`（基线 773/8，**未变红**）；`mypy` / `lint-imports` / 覆盖率均过；
`ruff check .` 整仓仍红，**15 条全部来自他人遗留的探针脚本**（本任务文件 0 条，我不删他人文件）。

---

## 1. 交付文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `src/aicore/core/config.py` | 改（432 → 521 行） | +4 字段（`mysql_pool_size` / `mysql_max_overflow` 必填、`mysql_readonly_host` / `mysql_readonly_port` 可空）；+1 字段校验器 `_reject_blank_readonly_host`；+4 派生属性 `mysql_read_host` / `mysql_read_port` / `read_target_is_primary` / `mysql_read_dsn`（与 `mysql_dsn` 成组）；模块 docstring 增一节说明两组字段为何分档 |
| `src/aicore/repository/session.py` | 改（1 行占位 → 276 行） | `build_engine(settings, *, read_only)`、`session_scope(engine)`、`dispose_engines(*engines)`、`mark_write_then_read(session)`、`session_needs_primary(session)`、`EngineFactory`（`write_engine` / `read_engine` / `primary_read_engine` / `read_target_is_primary` / `write_session` / `read_session` / `primary_read_session` / `dispose`） |
| `.env.example` | 改（37 → 51 行） | +4 行（`AICORE_MYSQL_POOL_SIZE` / `AICORE_MYSQL_MAX_OVERFLOW` / `AICORE_MYSQL_READONLY_HOST` / `AICORE_MYSQL_READONLY_PORT`），并写明"没有从库时整行删掉、不要写空值" |
| `tests/conftest.py` | 改 | `_TEST_ENV_DEFAULTS` +4（只读地址注入 `127.0.0.1`，覆盖"有独立从库地址"分支） |
| `tests/unit/test_config.py` | 改（467 → 620 行） | 三处耦合点同步（`EXPECTED_FIELDS` +4、`REQUIRED_FIELDS` **只加池参数 2 项**、`BASE_ENV` +2 必填项）；`INVALID_BOUNDS` / `VALID_BOUNDS` 各 +4；+9 条新用例（只读回落、端口独立回落、空串拒绝、绕过校验的属性兜底、只读 DSN 不泄口令、模板可用性） |
| `tests/unit/test_config_startup.py` | 改（**工单未列的耦合点**，见 D2） | `BASE_ENV` +2 必填项 |
| `tests/unit/test_logging.py` | 改（**工单未列的耦合点**，见 D2） | 启动环境变量清单 +2 必填项 |
| `tests/repository/test_session.py` | **新增**（639 行） | 25 条用例：23 条默认跑（含 3 条源码扫描 + 1 条配置 DSN + 会话生命周期 + 写后立即读守卫 + dispose 幂等）+ 2 条 `integration` |
| `src/aicore/main.py` | **未改** | 遵守工单硬约束 6「MUST NOT 本任务改接线」 |

> 本任务**没有创建任何探针脚本**（探针预算 2 个，实用 0 个；所有临时探查都用 `python -c` 内联完成，未落盘）。

---

## 2. 每条验证命令的原始输出

### 2.1 `.venv\Scripts\python.exe -m pytest tests/repository/test_session.py tests/unit/test_config.py -q`
（`pyproject` 的 `addopts = "-q"` 与命令行的 `-q` 叠加成 `-qq`，故只输出进度、无汇总行；退出码 0）

```
........................................................................ [ 62%]
............................................                             [100%]
=============================== warnings summary ===============================
.venv\Lib\site-packages\_pytest\cacheprovider.py:469
  ...\services\aicore\.venv\Lib\site-packages\_pytest\cacheprovider.py:469: PytestCacheWarning: could not create cache path ...\.pytest_cache\v\cache\nodeids: [WinError 5] 拒绝访问。: '...\pytest-cache-files-w0einzrk'
    config.cache.set("cache/nodeids", sorted(self.cached_nodeids))
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
exit=0
```
同一条命令加 `-o addopts=""` 取到汇总行（同一批用例）：

```
116 passed in 1.24s
```
（该数字随后因我在 `test_config.py` 追加 1 条模板可用性用例而变为 **117**；见 2.3 的最终全量数字。）

### 2.2 `.venv\Scripts\python.exe -m pytest tests/repository/test_session.py -q -m integration`（真实 MySQL）
```
..                                                                       [100%]
exit=0
```
加 `-o addopts=""` 取汇总行：
```
2 passed, 23 deselected in 0.93s
```

### 2.3 `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -m "not integration"`（全量基线）
最终一次：
```
827 passed, 8 skipped, 10 deselected in 17.61s
```
跳过项明细（`-rs`，与基线一致，非本次改动引入）：
```
SKIPPED [7] tests\structural\test_source_guards.py:102: provider 包是唯一允许发起外部模型调用的层
SKIPPED [1] tests\unit\test_envelope.py:501: /metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言
```
基线 773 passed / 8 skipped → 本次净增 54 条：其中 **46 条来自本任务**（test_session.py 23 条非集成 + test_config.py 21 条），
其余 8 条来自**控制者并发新增**的 `tests/repository/test_schema_consistency.py`（该文件共 10 条，含 2 条 integration），非本任务产物。

含 integration 的全量：
```
837 passed, 8 skipped in 27.95s
```

### 2.4 `.venv\Scripts\ruff.exe check . --no-cache`
```
_probe_repo_paths.py:45:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:55:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:68:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:80:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:91:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:104:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:118:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:133:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:149:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:157:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths.py:185:99: E501 Line too long (108 > 100)
_probe_repo_paths2.py:31:27: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
_probe_repo_paths2.py:75:101: E501 Line too long (105 > 100)
_probe_repo_paths2.py:78:74: E501 Line too long (104 > 100)
_probe_repo_paths2.py:154:31: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)
Found 15 errors.
[*] 12 fixable with the `--fix` option.
exit=1
```
**15 条全部落在 `services/aicore/_probe_repo_paths.py` / `_probe_repo_paths2.py`——他人（前序任务/并发任务）遗留的探针脚本，不是我建的，我按"不越权删他人文件"处理，未删除。**
本任务改动的 7 个文件单跑：
```
> .venv\Scripts\ruff.exe check src/aicore/core/config.py src/aicore/repository/session.py tests/repository/test_session.py tests/unit/test_config.py tests/unit/test_config_startup.py tests/unit/test_logging.py tests/conftest.py --no-cache
All checks passed!
```

### 2.5 `.venv\Scripts\mypy.exe src`（strict）
```
Success: no issues found in 52 source files
exit=0
```
stderr 有 22 条 `warning: Encountered error: 拒绝访问。 (os error 5)`——沙箱不允许 mypy 写缓存目录所致的噪声，检查本身成功（exit 0、无 error）。

### 2.6 `.venv\Scripts\lint-imports.exe --config .importlinter --no-cache`
```
Analyzed 52 files, 17 dependencies.
-----------------------------------

api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.

--------
Warnings
--------
service 层只可与 provider.base 交互，不得依赖具体通道实现
----------------------------------------
- No matches for ignored import aicore.service.** -> aicore.provider.base.
```
（该 warning 是 `.importlinter` 里已登记的已知状态：service 层尚无真实 Protocol 导入。）

### 2.7 覆盖率（`fail_under = 80`）
```
> .venv\Scripts\python.exe -m pytest tests/repository/test_session.py tests/unit/test_config.py tests/unit/test_config_startup.py -q --cov=aicore.repository.session --cov=aicore.core.config --cov-report=term-missing
Name                               Stmts   Miss  Cover   Missing
----------------------------------------------------------------
src\aicore\core\config.py            146      0   100%
src\aicore\repository\session.py      79      0   100%
----------------------------------------------------------------
TOTAL                                225      0   100%
Required test coverage of 80.0% reached. Total coverage: 100.00%
152 passed in 2.85s
```

### 2.8 一次**与本次改动无关**的全量失败（并发互扰，已单跑排除）
全量首次运行时出现：
```
FAILED tests/repository/test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[review_verdict.action]
E  aicore.repository.schema.SchemaParseError: 99_not_a_real_table.template.sql 是模板但不在分片表清单内：'not_a_real_table'
```
单跑该用例：
```
11 passed in 2.57s
```
复跑全量：`826 passed, 8 skipped`（当时）→ 与我的改动无关：控制者的 `tests/repository/test_schema_consistency.py`
会把探针 DDL 写进共享源码树，恰好与我的全量运行并发。属工单预告的已知约束。

---

## 3. 逐项验收结论

### 3.1 新增 4 字段（含"必填 vs 可空"的区分理由）
| 项 | 结论 |
|---|---|
| `mysql_pool_size: int = Field(ge=1)` / `mysql_max_overflow: int = Field(ge=0)`，**无默认值** | ✅ 注释写明"容量是部署决策，给默认值等于替运维做决定"；`test_required_fields_have_no_default` 逐字段验 `is_required()` |
| `mysql_readonly_host: str \| None = None` / `mysql_readonly_port: int \| None = Field(default=None, ge=1, le=65535)` | ✅ 注释写明"可选能力：本机没有从库，必填等于把主库地址再写一遍——形式主义而非安全；`None` 表示没有独立从库" |
| 4 个派生属性，成组放在 `mysql_dsn` 旁 | ✅ `mysql_read_host` / `mysql_read_port` / `read_target_is_primary` / `mysql_read_dsn` 与 `mysql_dsn` 同组 |
| 回落**只认 `None`**，空串抛错 | ✅ 双保险：字段校验器 `_reject_blank_readonly_host`（构造期、`loc` 指向字段）+ `mysql_read_host` 属性内再判（兜住 `model_copy` 等绕过路径）；两种情形各有用例 |
| 回落 MUST 在日志/自检里可见 | ✅ `read_target_is_primary` 属性 + `EngineFactory.__init__` 的 `[自检]` INFO 日志（写明"回落主库——未配置独立从库"），用例 `test_read_target_is_visible_in_the_assembly_log` 断言其可见且不含口令 |

### 3.2 三处耦合点
| 位置 | 结论 |
|---|---|
| `tests/unit/test_config.py` 的 `EXPECTED_FIELDS`（+4） | ✅ `test_field_set_matches_design_table` 绿 |
| 同文件的 `REQUIRED_FIELDS`（**只加池参数 2 项**） | ✅ 只读两项**未**进入；用例注释写明理由 |
| `.env.example` +4 行 | ✅ `test_env_example_matches_field_names_one_to_one` 绿（模板与字段一一对应；注释行不算声明，故 4 项都必须是真实行） |
| `tests/conftest.py` 注入 4 个值（只读地址注入 `127.0.0.1`） | ✅ 默认环境走"有独立从库"分支，`None` 回落分支由用例显式覆盖 |

### 3.3 `repository/session.py` 交付接口
`build_engine` / `session_scope` / `dispose_engines` / `EngineFactory`（`write_engine`、`read_engine`、
`primary_read_engine`、`read_target_is_primary`、`write_session`、`read_session`、`primary_read_session`、`dispose`）/
`mark_write_then_read` / `session_needs_primary` —— **全部按签名交付**（`mypy` strict 下返回类型全部标注）。

### 3.4 七条硬约束
| # | 约束 | 结论 |
|---|---|---|
| 1 | 同步会话 + 线程池，MUST NOT async API | ✅ 无 `async_sessionmaker` / `AsyncEngine` / `create_async_engine` / `AsyncSession`；用例 `test_no_async_session_api_in_the_source`（AST 标识符扫描，4 参数） |
| 2 | 写会话 / 只读会话分离 | ✅ `write_session`→`write_engine`、`read_session`→`read_engine`；`test_read_and_write_sessions_use_distinct_engines_and_pools`（真实库） |
| 3 | 写后立即读强制走主库 | ✅ `primary_read_session()` + `mark_write_then_read` / `session_needs_primary`；`read_session()` 见标记即抛 `ParamError(code=1002)`（**码值选择与理由写在模块 docstring**：能落到这里的是"调用参数用错"，且新增内部码要先扩 `_common/openapi.yaml` 的 `ErrorCode` 枚举，代价与收益不成比例） |
| 4 | 池大小从配置读、不写死 | ✅ `pool_size=settings.mysql_pool_size` / `max_overflow=settings.mysql_max_overflow`；`test_pool_parameters_come_from_settings_not_literals`（两组配置 → 两组池参数）+ 源码扫描阴性/阳性对照各 1 条 |
| 5 | 口令不进 URL 字面量、不进日志 | ✅ 一律 `URL.create(password=...)`；`test_password_never_appears_in_printable_forms` 正面断言 `repr(engine)` / `str(url)` / 两个 DSN 均无哨兵口令，**并有阴性对照**（`hide_password=False` 里必须看得见口令，证明断言非空） |
| 6 | 引擎生命周期：构造不连接、`dispose()` 幂等、不改 `main.py` | ✅ `create_engine` 惰性（构造期无网络，断言见模块 docstring）；`test_dispose_is_idempotent` / `test_dispose_engines_accepts_the_same_engine_twice`；`main.py` 未改 |
| 7 | `repository` 不 import `service`，只允许 `aicore.core.*` 与 `sqlalchemy` | ✅ `test_repository_imports_stay_within_the_contract`（AST 导入白名单）+ `lint-imports` 4 kept / 0 broken |

`pool_pre_ping=True` 与 `pool_recycle=3600` **都开**，开与不开的取舍写在模块 docstring（僵尸连接 vs 每次借出一次
COM_PING；MySQL 8 默认 `wait_timeout=28800s`，取 1h 留余量，MUST NOT 用 `-1`）。

### 3.5 八条用例
| # | 用例 | 结论 |
|---|---|---|
| 1 | 池参数随配置变化 | ✅ 3/2 与 17/0 两组，`pool.size()` 与 `pool._max_overflow` 各自断言；只读池另验一次 |
| 2 | 读写引擎分离 / 回落 | ✅ 配从库：URL 不同 + `read_target_is_primary is False`；`None` 时：地址相同但**两个不同 Engine 对象、两个不同池**，且 `primary_read_engine is write_engine` |
| 3 | 口令不泄漏 | ✅ 哨兵 `SENTINEL_PW_9f3a`；含阴性对照（见 3.4-5） |
| 4 | `readonly_host=""` MUST NOT 静默回落 | ✅ 构造期 `ValidationError`（`loc == ("mysql_readonly_host",)`，参数化空串/纯空白）+ 绕过校验时属性抛 `ValueError` |
| 5 | 会话生命周期（内存 SQLite） | ✅ 正常退出：连接归还池（`pool.checkedout()` 1 → 0）、`in_transaction()` False；体内抛异常：新会话读不到那条 INSERT（回滚生效）；另加"正常退出即提交"一条 |
| 6 | 写后立即读标记 | ✅ `mark_write_then_read` → `session_needs_primary is True`；monkeypatch 会话工厂使 `read_session()` 拿到带标记的会话 → 抛 `ParamError`（`code == 1002`、消息指向 `primary_read_session()`、被拒的会话已关闭） |
| 7 | 真实库写后立即读（integration） | ✅ 临时表 `tmp_session_probe_<pid>`：写会话建表 + 插入 → `primary_read_session()` 立即读回；`finally` 里 DROP 自己的表（MUST NOT `DROP DATABASE`） |
| 8 | 只读 / 写会话对象与池不同（integration） | ✅ `get_bind()` 分别是 `read_engine` / `write_engine`，两个 `pool` 不是同一对象，且两侧都真跑通 `SELECT 1` |

---

## 4. 偏离工单之处 + 理由

**D1｜用例 5 的 `session.is_active is False` 在本机 SQLAlchemy 2.0.54 上不成立（实测），改用等价的可观察事实。**
实测：`Session(bind=e); s.close(); s.is_active` → `True`（`is_active` 的语义是"会话不处于部分回滚态"，
`close()` 之后没有事务，故仍为 `True`）。工单要求的断言若照写会**恒红**。改用两条更强的事实：
`QueuePool.checkedout()`（会话没关就会一直占着连接 → 借出计数不归零）与 `session.in_transaction() is False`；
用例 docstring 与本报告都留了实测证据。集成用例里对**生产池（MySQL 的 QueuePool）**再断言一次 `checkedout() == 0`。

**D2｜工单只列了 3 处耦合点，实际还有 2 处，必须同改（否则这两个文件大面积变红）。**
`mysql_pool_size` / `mysql_max_overflow` 变必填后：
- `tests/unit/test_config_startup.py` 的 `BASE_ENV`（它自己 `_clear_aicore_env` + 重铺环境）→ 该文件所有用例都变成"缺必填项"；
- `tests/unit/test_logging.py::test_startup_first_emitted_line_is_json_with_every_mandated_field`（清空全部 `AICORE_*` 后自铺一套启动环境）→ 启动直接以"缺必填项"被 `ConfigRejected`，验不到"首行 JSON"这个目标。
两处各只加 2 行环境变量（+ 注释说明为什么要加），**没有**改动这两个文件里的任何断言口径。

**D3｜`read_session()` 守卫的语义边界：守卫的检查点在 `read_session()` 内，但该函数自己造会话，"带标记的会话"在生产路径上只在会话来源被替换/子类化时可达。**
按工单字面实现（`session.info` 打标记 + `read_session()` 内检查 + 抛错），并按要求用 monkeypatch 造出
"带标记的会话"验证（工单用例 6 明确允许）。如实登记：`mark_write_then_read` 的**真实用法**是调用方声明
"接下来要写后立即读"，随后由 `primary_read_session()` 承接；`read_session()` 的守卫是这条约定的 fail-fast 落点，
不是一个能自动触发的全局拦截（要做到后者需要跨会话/线程的待办状态，线程池下会把"某次写"的状态带给下一个请求，
风险大于收益）。选择写在模块 docstring 与用例 docstring 里。

**D4｜新增了 6 条工单未要求的用例（全部是加固，未改交付接口）**：
① 池参数源码扫描的**阳性对照**（`test_pool_parameters_are_passed_from_settings`，防止"参数压根没传"被当成通过）；
② 三条源码扫描用例本身（异步 API、导入边界、池字面量）；
③ `.env.example` 的**可用性**用例（清空进程环境后按模板构造 `Settings` 必须成功——比"名字一一对应"更强）；
④ 装配日志可见性用例（含"口令不进日志"）。理由：这四条硬约束/要求原本只写在 docstring 里，
"只写在文档里等于没写"（spec §5.2 的原话），落成可执行断言才防得住回归。

**D5｜只读端口单独配置时的语义（工单未规定），我按"不静默丢弃"裁定并写用例固定。**
`mysql_readonly_host=None` 而 `mysql_readonly_port=3307` 时：host 回落主库、port 取 3307（**不忽略端口**）。
理由：忽略等于"以为配了其实没配"（模块 docstring 硬取向 2）；另加拦截规则则会越出工单范围（要么改跨字段校验器
+ 其代号清单 + `test_config_startup.py` 的断言口径，工单未授权）。当前行为显式写进 `mysql_read_port` 的 docstring
并用例固定 `test_readonly_port_falls_back_independently_of_host`。**这条留给控制者裁定是否要改成启动期拒绝。**

**D6｜`.env.example` 里的可空项也必须写成真实行。**
`test_env_example_matches_field_names_one_to_one` 的正则是 `^([A-Z][A-Z0-9_]*)=`，注释掉的行不算声明，
故只读两项不能靠注释表达"可空"；模板里给出 `your_readonly_host` 占位，并在注释里写明"单实例环境请把这两行**整行删掉**，
不要写空值（空串会被拒绝）"。

**D7｜新增一条跨文件可执行断言的位置选择。**`mysql_readonly_host` 的"空串拒绝"落在 `config.py` 的字段校验器
（而非 `_reject_invalid_startup_combination`）：模块 docstring 明确"字段级约束是 `Field(...)` 的地盘，跨字段规则才进 after 校验器"，
空串是**单字段**判定（`loc` 应指向该字段），进跨字段会造出与文档口径不符的第二套分类。

**D8｜未改 `main.py`。**（工单硬约束 6；`EngineFactory` 的持有与 lifespan 接线属第 4 组。）

---

## 5. 我没做到的事（如实登记，不美化）

1. **读写分离的实效未验证——只验证了"地址可配"。** 本机只有一个 MySQL 实例，没有真实从库：
   只读引擎连的是**同一个实例**（集成用例把只读地址配成 `127.0.0.1`）。因此
   **主从延迟、从库一致性、`read_only` 只读权限、故障切换全都没有验证**；
   "写后立即读走主库"验证的是"两条连接池与主库会话路径正确"，不是"从库延迟下也不会读到旧值"。
2. **`pool_pre_ping` / `pool_recycle` 只写了理由，没有做掐连接的实测**（未制造服务端 `wait_timeout` 超时、
   未做网络中断演练），MySQL 服务是既有 Windows 服务，我没有重启它。
3. **`ruff check .` 整仓仍是红的**：15 条全部来自他人遗留的 `services/aicore/_probe_repo_paths.py` 与
   `_probe_repo_paths2.py`（我未创建、也未删除他人文件）。本任务 7 个文件 0 条。**需要控制者处置这两个脚本。**
4. **一次全量运行出现过与本次改动无关的失败**（`test_ddl_matches_er.py::test_ddl_enum_matches_openapi_enum[review_verdict.action]`，
   由并发写入共享 DDL 树的探针文件 `99_not_a_real_table.template.sql` 引起）；单跑该用例 11 passed，复跑全量恢复全绿（见 2.8）。
   我不能保证控制者在本报告之后继续并发写入时，全量不会再次出现同类瞬时失败。
5. **未跑全量覆盖率门禁**：只对两个改动模块做了 100% 覆盖验证（`config.py` 146 stmts、`session.py` 79 stmts，均 0 miss）；
   全量 `--cov` 未跑，故"整仓覆盖率 ≥ 80"只能由控制者最终确认。
6. **装配日志级别取 INFO 而非 WARNING**：单实例环境"回落主库"是常态，用 WARNING 会制造噪声告警；
   若控制者要求"回落必须告警"，需要上调为 `warning`（一行改动）。
7. **`session.py` 没有提供"只读会话的数据库层强制只读"**（例如给只读引擎设 `isolation_level` 或拦截写语句）：
   工单未要求，当前的"只读"仅指用途与地址；真正的只读保护依赖从库/账号权限（已在 docstring 里写明边界）。
8. **`EngineFactory` 没有提供线程安全的单例或请求级复用**：每次 `*_session()` 造一个新会话（不用 `scoped_session`），
   与 spec §5.4 一致，但**没有**验证"高并发下池耗尽"这类运行时行为（无压测）。
