# 第 3 组独立评审（9a3f4be..d597768）

评审者：独立评审 subagent（**未修改任何被评审文件、未 `git commit`**）
worktree：`D:\progrom\.worktrees\aicore-architecture`（分支 `feature/aicore-architecture`）
范围：`9a3f4be`（第 2 组末）→ `d597768`，10 个提交 / 48 文件 / +11228 −13
方法：**先读全 spec §2.3·§5.1~§5.9·§6、plan 第 3 组（含 10 项验收）、`er.md` §5.2~§5.6·§6·§7、
9 份工单与 8 份交付报告、ledger 第 3 组（含 C1~C7）**，再独立复跑全部 9 条门禁，
另做 5 组变异测试、4 项数值抽查、3 个"检查器自身"的双向探针。

---

## 1. 结论

**有条件通过。**

理由一句话：10 项验收我逐条独立复跑**全部复现为绿**，9 条门禁零失败，交付物本身未发现错误；
但**验收项 7 的"总长恰为 32"这一维度在仓库内没有任何独立预言机**（断言与被测对象共用同一常量，
我已实证把常量改成自洽但错误的 35 时 `group3_acceptance.py` 仍报 **10/10 PASS**），
另有 5 处文档/可追溯性缺陷（含 ledger 引用了一个**不存在的提交**）。
这些不使交付物失效，但使"验收结论可复核"这一承诺打折，需按 §10 补齐后再宣布本组关闭。

**未发现阻塞级交付物缺陷**（无错误码错配、无结构漂移、无越界改动、无凭据入库、无越权建表）。

---

## 2. 10 项验收逐条判定（三态表）

| # | 验收项（plan §第 3 组验收原文） | 判定 | 证据（全部为**我自己**的复跑） |
|---|---|---|---|
| 1 | DDL 在真实 MySQL 8 执行成功 | **满足**（有保留，见 §9-1） | `group3_acceptance.py` → `[PASS] 1. 库 aicore 9 张表，与 deploy/sql/ddl 结构 0 差异`；我另行直连 `information_schema` 独立读到 `aicore` 9 张表，含 `ai_task_202609`/`ocr_result_202609`/`ocr_correction_202609`；integration **19 passed, 885 deselected**。保留：11 个 DDL 文件中 `00_create_database.sql` 从未在任何真实库执行 |
| 2 | 三源交叉比对正常态通过；三个方向单边改动各失败一次 | **满足** | `group3_acceptance.py` 项 2 `表数 (9,9,9)，三对组合差异 (0,0,0)`；项 3 `方向①1 处 / ②1 处 / ③1 处`；`compare_schema.py` 三源两两 `[ OK ]`；**我另用真实文件变异独立复现方向①③变红**（§5） |
| 3 | 跨月写入与边界查询用例通过（可控时钟，无 sleep） | **满足** | `test_sharding.py` 有毫秒边界 / UTC+8 跨年 / 闰日三类边界用例；项 4 无 sleep 检查 `PASS`；**我另喂 6 组正反样例复跑该检查器，6/6 符合预期**（§4-⑤） |
| 4 | 缺分片键抛错用例、跨分片操作被拒用例通过 | **满足** | 项 6 `缺键→1001 True；跨月→1003 True；同月去重→'202601' True`；`CrossShardOperationError.code == 1003` 与 plan Task 3.3 定档一致 |
| 5 | 只读会话分离用例通过；池大小随配置变化 | **满足**（限于"地址可配"，见 §9-2） | 项 7 `池取自配置 True；随配置变化 True；读写两引擎 True；无从库时回落主库 True`；集成用例真连库执行 `SELECT 1` 于两条独立连接池 |
| 6 | 空库零到目标结构可复现；重复执行幂等 | **未验证**（拆半：幂等✅ / 真·空库❌） | 项 8 只判"基线迁移就位"；幂等与两路一致由 `-m integration` 承载（已随 19 passed 跑过）。**"新建空库"路径无权限实测**：我独立执行 `CREATE DATABASE IF NOT EXISTS aicore_probe_review` → `OperationalError (1044, Access denied ...)`，`SHOW GRANTS` 证实 `GRANT USAGE ON *.*`。见 §9-1 |
| 7 | 1 万个 ID 全过正则且无重复 | **满足**（对交付物）/ **预言机不足**（见 §10-1） | 项 9 `唯一 True；最大长度 32 ≤ 32 True；全量校验 True`；**我另以字面量 `32`（不复用模块常量）独立复验**：六前缀逐一 `len==32` 且 hex 段合法、1 万并发唯一且 `len==32` 全量成立 |
| 8 | 全量 `pytest` 通过；`--cov src/aicore` ≥80% | **满足** | `877 passed, 8 skipped, 19 deselected in 11.34s`；覆盖率 `TOTAL 1314 36 97%` → `Required test coverage of 80.0% reached. Total coverage: 97.26%` |
| 9 | `commit-check` 门禁通过；提交信息不带 `[AI]` 前缀 | **未验证**（可自动化部分已全部复跑通过） | 项 10 `近 40 条：带 [AI] 前缀 0 条；格式不符 0 条`；我另行机械复跑：新增 11228 行中冲突标记 0、行尾空白 0、私钥头 0、真实 `.env` 赋值 0、`Co-Authored-By` 0、>1MB 文件 0、`.env` 未入库。**技能本体与物理 git hook 未复跑**（沙箱无 `sh`，第 1 组已登记的环境事实） |
| 10 | 向用户展示上述命令的原始输出并取得确认 | **未验证** | 前半（原始输出固化）已满足：ledger「第 3 组验收检查表」与 8 份报告均贴原始输出；后半（用户确认）属用户侧，仓库内无自证材料，评审者无法代证 |

**未验证项单列**：6（真·空库路径）、9（技能本体 / 物理 hook）、10（用户确认）；
另有 3 条**功能性未验证**：读写分离的主从延迟·从库一致性·只读权限·故障切换（§9-2）、
`scripts/*.py` 不在 mypy / import-linter 覆盖内（§9-3）、`pool_pre_ping` / `pool_recycle` 未做掐连接实测（§9-5）。

---

## 3. 独立复跑的原始输出

全部 9 条命令由我按序**串行**执行（避免 §7 的并发互扰），逐条原始输出如下（我自己跑的第一手输出）。

### 3.1 全量单元/仓储（`-m "not integration"`）

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -m "not integration"
...
877 passed, 8 skipped, 19 deselected in 11.34s        [exit code: 0]
```

### 3.2 集成（`-m integration`）

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -m integration
...................                                                      [100%]
19 passed, 885 deselected in 17.93s                   [exit code: 0]
```

（第一次捕获时 `2>&1 | Out-File` 吞掉了汇总行，故我重跑一次取汇总；两次均 19 通过。）

### 3.3 覆盖率门禁

```
$ .venv\Scripts\python.exe -m pytest --cov src/aicore --cov-report=term -m "not integration"
...
src\aicore\core\config.py                    149      0   100%
src\aicore\core\errors.py                    114      0   100%
src\aicore\core\idgen.py                      31      0   100%
src\aicore\repository\base.py                 83      0   100%
src\aicore\repository\models.py              121      0   100%
src\aicore\repository\schema.py              260     16    94%
src\aicore\repository\session.py              79      0   100%
src\aicore\repository\sharding.py            105      3    97%
src\aicore\repository\task_repo.py            37      0   100%
...
TOTAL                                       1314     36    97%
Required test coverage of 80.0% reached. Total coverage: 97.26%
877 passed, 8 skipped, 19 deselected in 13.01s         [exit code: 0]
```

### 3.4 验收检查表（10 项）

```
$ .venv\Scripts\python.exe scripts\group3_acceptance.py
[PASS] 1. DDL 在真实 MySQL 8 执行
        库 aicore 9 张表，与 deploy/sql/ddl 结构 0 差异
[PASS] 2. 三源交叉比对正常态
        表数 (9, 9, 9)，三对组合差异 (0, 0, 0)
[PASS] 3. 三源比对三方向阴性
        方向①1 处 / 方向②1 处 / 方向③1 处（各应恰好 1）
[PASS] 4. 测试内无 sleep
        AST 扫描全 tests/ 无 sleep 调用（注释里的说明不算）
[PASS] 5. 无跨分片 JOIN/聚合/两阶段提交
        全树无 select 上的 join、无两阶段提交
[PASS] 6. 缺分片键抛错 / 跨分片被拒
        缺键→1001 True；跨月→1003 True；同月去重→'202601' True
[PASS] 7. 只读会话分离 + 池随配置
        池取自配置 True；随配置变化 True；读写两引擎 True；无从库时回落主库 True
[PASS] 8. 迁移幂等（基线迁移就位）
        versions/ 下 1 条迁移 ['2523574bd75d_baseline_schema.py']；sqlalchemy.url 值 ''；无 password= 赋值 True
[PASS] 9. 一万个 ID 过正则且无重复
        唯一 True；最大长度 32 ≤ 32 True；全量校验 True
[PASS] 10. 提交不带 [AI] 前缀且符合 Conventional Commits
        近 40 条：带 [AI] 前缀 0 条；格式不符 0 条
结果：PASS 10 / FAIL 0 / INFO 0                    [exit code: 0]
```

### 3.5 `compare_schema.py`

```
[INFO] 模板渲染月 = 202601（缺省常量，刻意不取当前月）
[INFO] DDL(deploy/sql/ddl)      解析到 9 张表
[INFO] er.md §6 数据字典            解析到 9 张表
[INFO] SQLAlchemy 元数据           解析到 9 张表
[WARN] 未传 --with-mysql：**真实库结构未被校验**（只比了文本与元数据三源）
[ OK ] DDL(deploy/sql/ddl) vs er.md §6 数据字典：一致
[ OK ] DDL(deploy/sql/ddl) vs SQLAlchemy 元数据：一致
[ OK ] er.md §6 数据字典 vs SQLAlchemy 元数据：一致
[DONE] 3 个来源两两一致（9 张表）                    [exit code: 0]
```

### 3.6 ruff / mypy / import-linter

```
$ .venv\Scripts\ruff.exe check . --no-cache
warning: Encountered error: 拒绝访问。 (os error 5)      ← 重复 32 次，对应 32 个 ACL 残留目录
All checks passed!                                    [exit code: 0]

$ .venv\Scripts\mypy.exe src
Success: no issues found in 52 source files            [exit code: 0]

$ .venv\Scripts\lint-imports.exe --config .importlinter --no-cache
Analyzed 52 files, 32 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.                           [exit code: 0]
Warnings: No matches for ignored import aicore.service.** -> aicore.provider.base.
```

> ruff 的 32 条 `os error 5` 说明：`ruff check .` **跳过了那 32 个读不到的残留目录**
> ——"All checks passed" 是对它**读得到的**树成立。这些目录未被 git 跟踪（§8），不影响交付物。

### 3.7 并发敏感用例单跑（§7 要求）

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -q tests/structural/test_layering.py
........                                                                 [100%]
8 passed                                               [exit code: 0]
```

---

## 4. 假绿排查（六类逐类结论）

### ① 断言是否恒真 / 断言自己刚设的值

- 我按 `len(x)==len(set(x))`、`== len(set(`、`assert x == x` 三类模式全量扫描 `services/aicore/tests/**`：
  **0 命中**。第 1 组已修的恒真断言（`len(paths_first)==len(set(paths_first))`）未复发。
- **发现 1 处"自证"型（非恒真，但等价效果）**：`group3_acceptance.py:311`
  `within = max(len(value) for value in ids) <= MAX_ID_LENGTH` —— 期望值取自**被测模块自己的常量**。
  变异实证见 §5-③/§5-④。**这是本次唯一实质性假绿。**
- 反例组充分：`test_idgen.py::TestValidateRejects` 7 条、`test_sharding.py` 的 `require_shard_key`
  与 `assert_single_shard` 拒绝分支、`schema.diff` 六类差异用例，均为真反例而非恒真。

### ② 解析/比对类用例是否有非空下限

**有，且是显式常量**：`test_ddl_matches_er.py:157-161` 定义
`MIN_ER_TABLES=9 / MIN_ENUM_COLUMNS=11 / MIN_OPENAPI_ENUM_LINES=10 / MIN_TIMESTAMP_DEFAULT_COLUMNS=3`
并在 `test_er_md_parses_all_nine_tables` / `test_enum_column_count_is_not_vacuous` /
`test_openapi_has_enough_enum_lines` / `test_timestamp_defaults_match_er_notes` 中先断下限再比对；
`test_schema_consistency.py:80` 的 `test_three_sources_are_non_vacuous` 对三源各断 `len==9`。
解析塌了会报红而不是静默全绿。**这一类合格。**

### ③ 期望值是现解析还是抄了一遍

**主体是现解析**：列名/类型/可空/默认/枚举一律来自 `schema.parse_er_md` /
`schema.parse_ddl_directory` / `schema.from_metadata`，DDL 目录清单与 `sharding.SHARDED_TABLES`
**刻意各写一份**（`test_ddl_matches_er.py:70-72` 写明理由）以免"自己比自己"。
**硬编码只有两处且都合理**：`OPENAPI_ENUM_SPOT_CHECK`（抄 openapi 侧的定档值集，
作用是让"DDL 与 openapi 一起改错"也变红）与 `DDL_ENUM_TO_OPENAPI`（跨文件接线，无法从任一侧推导）。
**反例**：`group3_acceptance.py` 项 1/2/3 的期望值全部来自实现侧 —— 但项 3 的变异锚点自带
`needle not in raw → FAIL` 自检，改不动即报红，故不构成静默假绿。

### ④ `skip` 是否显式

**全部显式**。全仓 `tests/**` 的 skip 命中 12 处，**无一处静默 pass**：均形如
`pytest.skip("<原因>")`，且原因文本点名缺哪个变量（`DSH_IT_MYSQL_PASSWORD`）。
`tests/unit/test_envelope.py:501` 的 `/metrics` 未落地 skip 也带说明。
**唯一可议**：`test_apply_ddl_mysql.py:317` 因"随机值碰巧是纯数字"而 skip —— 有个随机分支，
但它是**已通过随机性很难命中**的辅助用例，且 skip 有原因，不算静默。

### ⑤ "注释/docstring 里提到"导致的误判（**正反两向都查了**）

我把两个检查器**摘出来喂合成样例**（探针在 `D:\progrom\.review-group3\probe_guards.py`，
只把模块级 `SERVICE_ROOT`/`TESTS` 指到临时树，**未改被测文件**），结果 15/15 符合预期：

```
检查器 A：check_guard_existence
  [OK ] FAIL | 真 SQL JOIN：      x = select(A).join(B)
  [OK ] FAIL | outerjoin：        x = select(A).outerjoin(B)
  [OK ] FAIL | 两阶段提交：        conn.begin_twophase()
  [OK ] PASS | 字符串拼接：        x = "".join(parts)
  [OK ] PASS | docstring 提到 JOIN："""禁止跨分片 JOIN / 聚合 / 事务。"""
  [OK ] PASS | 行注释提到 JOIN：   # 禁止跨分片 JOIN / 聚合 / 事务
  [OK ] PASS | 字符串字面量提到：   msg = "禁止跨分片 JOIN"
  [OK ] PASS | 字符串 .prepare(：  x = "conn.prepare()"
  [OK ] PASS | docstring 提到 two_phase
检查器 B：check_no_sleep_in_tests
  [OK ] FAIL | time.sleep(1) / from time import sleep / fake.sleep()
  [OK ] PASS | 注释 / docstring / 字符串里提到 sleep
检查器 C：idgen 防回归断言的反向自检
  uuid4 in skeleton = True   ← 剥离失效时会变 False 从而报红，自检真的承重
  snowflake in skeleton = False / workerId in skeleton = False
```

**反向（②"断言只匹配到注释而没匹配到真实结构"）也查了**：`test_no_snowflake_or_timestamp_or_uuid1`
用 `tokenize` 剥注释与字符串后只对骨架发问，并带"剥离后仍须看到 `uuid4`"的反向自检（实测 True）；
`test_every_column_and_table_has_chinese_comment` 用"中文必须落在引号内"的
`COLUMN_CN_COMMENT_RE`/`TABLE_CN_COMMENT_RE`，不会把注释文字当成结构。
**我自己也踩了一次这个坑**（凭据扫描把 `sharding.py` docstring 里
`` mysql+pymysql://user:pass@host `` 这句**反面示例**判成"硬编码凭据"），已人工排除 —— 说明该判据方向确实是本项目的高频坑，实现方的处理是对的。

### ⑥ 阴性用例是否真的会响

**做了 5 组真实变异（§5），全部按预期变红并可按字节还原转绿**；
`test_schema_consistency.py` 三方向阴性每向都配"未改动对照 `diff == []`"+
"改动必须反映到解析结果"的反假绿断言；`group3_acceptance.py` 项 3 的
`needle/anchor not in text → FAIL` 自检让"改不动"变成显式红。
**唯一不足（实现者已在 3.6b 报告 §7-4 自认）**：阴性用例自身的"阴性"未做；
我用**真实文件变异**补上了方向①（DDL）与方向③（模型），方向②（`er.md`）仍只有内存变异 + 我的检查器探针间接佐证。

---

## 5. 变异测试（5 处，红绿对照）

方法：备份原文件字节 → **二进制替换**（不经文本模式，避免 `core.autocrlf` 换行翻译）
→ 跑门禁 → **按备份字节还原** → 校验 SHA256 相等 → 再跑一次确认转绿。
驱动脚本 `D:\progrom\.review-group3\mutate.py`；**未改任何测试文件**。

| # | 被测对象（改坏什么） | 变异 | 红（原始结论） | 还原 | 绿 |
|---|---|---|---|---|---|
| ① | `deploy/sql/ddl/20_vision_review.sql` `review_id varchar(32)→varchar(64)` | `before=3fd615d4fe41e374 after=7458f16e1f3792d6`（字节数不变） | `test_ddl_matches_er.py` **1 failed**：`表 vision_review 字段 review_id 类型不一致：左 varchar(32)，右 varchar(64)`；`group3_acceptance.py` **exit 1，PASS 7 / FAIL 3**（项 1、2、3 全红） | `byte_identical=True sha=3fd615d4fe41e374` | `test_ddl_matches_er.py` **61 passed**（exit 0） |
| ② | `repository/models.py` `ocr_result.summary` `nullable=False→True` | `before=92785ced55686e5c after=48682427479cc3f6` | `test_schema_consistency.py` **3 failed**（`表 ocr_result 字段 summary 可空性不一致：左 NO，右 YES`）；`test_models.py` **1 failed**；`group3_acceptance.py` **FAIL 2**（项 2、3） | `byte_identical=True sha=92785ced55686e5c` | 两文件 **exit 0**，全绿 |
| ③ | `core/idgen.py` `MAX_ID_LENGTH 32→36` | `before=54bc28e88915d958 after=e098f9ba3585b76e` | `test_idgen.py` **4 failed**；`group3_acceptance.py` **exit 1**（`ValueError: 生成的 ID 长度 35 不等于 36（前缀 'qa_'）`） | `byte_identical=True` | `test_idgen.py` **20 passed** |
| ④ | `core/idgen.py` `MAX_ID_LENGTH 32→35`（**自洽但错误**） | `after=e4a4e2577d2cc0c1` | `test_idgen.py` **仅 1 failed**，且失败者是 `TestValidateRejects::test_unknown_kind_raises` —— 它的 fixture 串长由 `MAX_ID_LENGTH` 现算，长度先不匹配就返回 `False`，**根本没走到它想测的"未知 kind"分支**；这是**附带红，不是对 32 的正面断言**。`group3_acceptance.py` **exit 0，10/10 PASS**（项 9 打印 `最大长度 35 ≤ 35 True`） | `byte_identical=True sha=54bc28e88915d958` | `test_idgen.py` **20 passed** |
| ⑤ | `core/idgen.py` `MAX_ID_LENGTH 32→10` | `after=1d6ee4756a76fa3e` | `test_idgen.py` **3 failed**（含 `test_over_length_guard_actually_fires` —— 因猴补丁值恰等于变异值而"碰巧"变红） | `byte_identical=True` | 转绿 |

**结论**：①②证明"DDL / 模型单边改坏真的会红"，阴性用例**会响**；
③④⑤精确定位了唯一的假绿面（§10-1）。

**还原校验（最终快照）**：

```
ddl_review_id_type       live=3fd615d4fe41e374 backup=3fd615d4fe41e374 identical=True
models_summary_nullable  live=92785ced55686e5c backup=92785ced55686e5c identical=True
idgen_max_len_36         live=54bc28e88915d958 backup=54bc28e88915d958 identical=True
idgen_max_len_35         live=54bc28e88915d958 backup=54bc28e88915d958 identical=True
idgen_max_len_10         live=54bc28e88915d958 backup=54bc28e88915d958 identical=True

$ git -C <worktree> status --porcelain
?? .sdd-tools.py          ← 评审开始前即存在的未跟踪文件，非我产生
```

---

## 6. 数值/口径抽查（4 项，附权威源位置与值）

### 抽查① 平台错误码 `3007`

| 权威源 | 位置 | 值 | 核对 |
|---|---|---|---|
| `services/_common/openapi.yaml` | L197 `ErrorCode` 枚举 | `- 3007 # 状态不允许该操作` | ✅ 在枚举内（我解析出全部 26 个码值逐一列出确认） |
| `core/errors.py` 第 1 处 | L148 `CONFLICT_CODE` + L170 `AICORE_ERROR_CODES` | `3007` | ✅ |
| `core/errors.py` 第 2 处 | L249 `DEFAULT_MESSAGES` | `"当前状态不允许该操作"` | ✅ |
| `core/errors.py` 第 3 处 | L187 `HTTP_STATUS_BY_ERROR_CODE` | `409` | ✅ 与第 2 组锁定映射一致 |
| `core/errors.py` 第 4 处 | `tests/unit/test_errors.py` 两张字面量表 | `3007` / `3007: 409` | ✅ 均在 |
| 死码检查 | `AICORE_ERROR_CODES ⊆ ErrorCode 枚举` | 差集为空 | ✅ 无死码（`3008` 按 ledger 理由未接，正确） |

### 抽查② ID 长度算术（用**字面量 32**，不复用模块常量）

| kind | 前缀 | 前缀长 | 实际 hex 位 | 总长 |
|---|---|---|---|---|
| `task` | `task_` | 5 | 27 | **32** |
| `cor` | `cor_` | 4 | 28 | **32** |
| `rev` | `rev_` | 4 | 28 | **32** |
| `marker` | `marker_` | 7 | 25 | **32** |
| `kan` | `kan_` | 4 | 28 | **32** |
| `qa` | `qa_` | 3 | 29 | **32** |

六前缀逐一如上；1 万并发：唯一 `True`、全量 `len==32`（字面量）`True`、全量 `validate_id` `True`、最大长度 `32`。
权威源：`er.md` §5.4「均为 `varchar(32)`」+ spec §5.8「总长必须 ≤32」。

### 抽查③ 分片表清单四处一致

| 源 | 值 |
|---|---|
| `sharding.SHARDED_TABLES` | `{ai_task, ocr_correction, ocr_result}` |
| `sharding.FIXED_TABLES` | `{kitchen_anomaly, review_verdict, risk_predict_result, vision_marker, vision_qa_log, vision_review}` |
| `models` 元数据 | 9 个**逻辑名**，无 `_YYYYMM` 后缀 ✅ |
| DDL 模板文件 | `10_ai_task/11_ocr_result/12_ocr_correction.template.sql` 三个 ✅ |
| `er.md` §5.2 | 解析出的 9 张表与上述**集合完全相等** ✅ |

四处 `set` 相等 = `True`。另：`sharding.py` 导入期自检 `_check_table_manifests()` 强制
"顺序表键集 == 模板表键集"∧"分片/非分片无交集"∧"总数 == 9"。

### 抽查④ 外键约束名与 `er.md` / spec §5.1 标注

| DDL 中的 CONSTRAINT | 指向 | 动作 | 权威源 |
|---|---|---|---|
| `fk_ocr_correction_task_{month}` | `ocr_result_{month}(task_id)` | `ON DELETE RESTRICT ON UPDATE RESTRICT` | spec §5.1 L286「在同月模板内声明物理外键」✅ |
| `fk_vision_marker_review` | `vision_review(review_id)` | RESTRICT / RESTRICT | spec §5.1 L287 ✅ |
| `fk_review_verdict_review` | `vision_review(review_id)` | RESTRICT / RESTRICT | spec §5.1 L288（1:1） ✅ |
| `fk_kitchen_anomaly_review` | `vision_review(review_id)` | RESTRICT / RESTRICT | spec §5.1 L289 ✅ |
| `11_ocr_result.template.sql` | — | **无物理外键** | spec §5.1 L290「**非外键**」✅ |
| `10_ai_task.template.sql` | — | 无（被引用表） | ✅ |

`ocr_correction` 的冲突已按 **spec §5.1 优先** 处理（`er.md` §5.4 L240 那行讲的是
**ID 生成策略**、未标 FK；我核对了原文 `| \`ocr_result.task_id\` | varchar(32)（= 任务号） | 由 \`ai_task\` 带入 | 同月分片路由凭据 |`
—— 它确实不含 FK 语义），与 ledger 的 C2/DP3 处置一致；`docs/er.md` 未被本组改动（§8）。

---

## 7. 并发约束复核（structural 单跑结果）

**我确认该约束属实且比 ledger 登记的更宽**：`tests/structural/test_layering.py`
不只写探针 —— `probe_files()` 把 `*_probe.py` 写进共享源码树
（`src/aicore/{api,service,repository,core,port}/`），`test_provider_facade_reexport_is_forbidden`
还**直接往真实被跟踪文件 `src/aicore/provider/__init__.py` 追加导入行**
（`L208-210`，靠 `finally` 还原），`test_ignore_imports_still_needed_for_provider_base`
还在**仓库根**写临时 `.importlinter_nonexistent`（`L184-191`）。

**单跑结果（我在 9 条门禁末尾单独执行）**：

```
$ .venv\Scripts\python.exe -m pytest -p no:cacheprovider --no-header -q tests/structural/test_layering.py
........                                                                 [100%]
8 passed                                               [exit code: 0]
```

**结论**：单跑**绿**，且我在**串行**执行的 3.1 全量套件里它同样绿。
**"全量并发跑时该用例结果不可采信"这一条我照单确认**：两个进程同时跑时，
一方可能读到对方注入的 `provider/__init__.py` 追加行或对方留下的 `svc_probe.py`，
且进程被杀会在**真实源码文件**上留下未还原的修改（`git status` 会变脏而原因难查）。
建议（非阻塞）改为"探针写进仓库内独立的临时包目录 + `finally` 备份还原"，
并把 `.importlinter_nonexistent` 也移出仓库根；本组不动它（属第 1 组已验收文件的语义变更）。

---

## 8. 范围与残留

**越界检查：无越界。** `git diff 9a3f4be..HEAD --stat -- . ':(exclude)services/aicore'` **输出为空**
—— 48 个改动文件全部落在 `services/aicore/` 内，没有一行碰 `docs/er.md`、`docs/openapi.yaml`、
`services/_common/`。这与 C5/DP3"`er.md` 属唯一可手改源、本组不碰"的处置一致（我逐文件核对 `git diff --name-only | Select-String docs/` → 空）。

**跨任务改动（已在 ledger 登记，非越界）**：`tests/unit/test_config.py` / `test_config_startup.py` /
`test_logging.py` / `tests/conftest.py` / `.env.example` —— 因 Task 3.4 新增两个**必填**池字段，
5 处耦合点必须同步（实现者报出"工单只列 3 处、实际 5 处"并对，已复验）。
`pyproject.toml` 的 `allowed-confusables` 由 7 项扩到 **11 项**（Task 3.1 +3、Task 3.8 +1）——
我逐字符核对了这 4 个字符的实际落点：`？`/`−` 各只在 `test_ddl_matches_er.py`
（一条断言消息 + 一条注释）、`×` 只在 `test_sharding.py` 的一句 docstring、`–` 只在
`core/idgen.py` 的一句 docstring —— **"只出现在注释与断言消息里"这一理由属实**，
且规则本身未关（未使用 ignore）。属可接受的收缩，但**门禁确实被放宽了 4 个字符**，见 §11-3。

`git status`：**干净**（唯一未跟踪项 `.sdd-tools.py` 在我评审开始**之前**就存在，
是 ledger 明示的"控制者哨兵工具，勿提交"）。

**残留核实**：
- `pytest-cache-files-*` / `probe-*` 目录数 **= 32**（我 `Get-ChildItem` 实数与 ledger 一致）；
  `git status` 只对它们输出 `warning: could not open directory ... Permission denied`，
  不列为未跟踪 —— 因为 git **读不进去**（`os.listdir` 同样 `PermissionError [WinError 5]`），
  不是因为被忽略。**`git check-ignore` 对这 32 个目录返回 exit 1（无任何忽略规则命中）**。
  → "未被 git 跟踪"**属实**；"不影响交付"**今天属实**；但**一旦 ACL 被放开，它们会立刻变成
  未跟踪项污染 `git status`**。建议补 `.gitignore` 规则（§11-2）。
- 我自己的评审脚手架全部落在 **`D:\progrom\.review-group3\`**（工作区根，不在 worktree 内），
  内含 `mutate.py` / `backup/` / `probe_guards.py` / `guardprobe/` 等；
  **worktree 内零新增文件**（`git status` 已证）。

---

## 9. "未验证清单"核实（逐条：属实 / 不属实 / 有遗漏）

| # | 声明 | 判定 | 我的独立核实方式与现场 |
|---|---|---|---|
| 1 | **建库路径（`00_create_database.sql`）未在真实库执行**：`aicore_dev` 在 `*.*` 上只有 USAGE | **属实** | 我用 `.env` 里的口令直连做**实测**（不是读报告）：`SHOW GRANTS` → `GRANT USAGE ON *.* TO 'aicore_dev'@'localhost'`（仅 `aicore.*` 与 `aicore_test.*` 是 ALL）；`CREATE DATABASE IF NOT EXISTS aicore_probe_review` → `OperationalError (1044, "Access denied ...")`；`SHOW DATABASES` → 只有 `aicore`/`aicore_test` 两库。**建库确实无法验证** |
| 2 | **读写分离只验到"地址可配 + 两个引擎/两个池"**；主从延迟 / 从库一致性 / 只读权限 / 故障切换完全未验证 | **属实** | `session.py` 模块 docstring「已知边界」明写；集成用例 `_integration_settings()` 把只读地址配成**同一个实例**（`L552-556` 注释直说"这验证的是地址可配"）；运行期 `read_target_is_primary=True`。本机 `SHOW DATABASES` 只有 `aicore`/`aicore_test`，**无第二个实例**，主从延迟在该环境**不可验证**（非"未做"，是"做不到"） |
| 3 | `scripts/apply_ddl.py` 与 `compare_schema.py` **不在** `mypy`（`files=["src"]`）与 import-linter 覆盖内 | **属实** | `mypy.exe src` → `Success: no issues found in 52 source files`（52 = `src/aicore` 全部模块）；`lint-imports` → `Analyzed 52 files` 同数；`scripts/` 下 3 个脚本（含 `group3_acceptance.py`）**一个都不在**覆盖内 |
| 4 | 分片表读回是**游离实体**（无 identity map） | **属实** | 读回一律经 Core 行 → `Model(**row)`（`base.py:326` 与各 repo 的 `get_by_id`），`base.py` docstring 明写"游离实体/detached"；我扫描 `session.get(`/`identity_map`/`populate_existing` 在 5 个 repo 模块中 **0 命中**（`task_repo.py` 里那一处 `session.merge(` 只出现在 docstring 的**禁用说明**里，不是调用） |
| 5 | `pool_pre_ping` / `pool_recycle` 只写了理由，未做掐连接实测 | **属实** | 全仓扫描无 `KILL`/`wait_timeout`/掐连接类用例；`session.py:18-25` 只有取舍理由，`pool_pre_ping=True`/`pool_recycle=3600` 仅被"参数来自配置"类断言覆盖 |

**有遗漏（我补登 6 条）**：

| # | 遗漏项 | 说明 |
|---|---|---|
| 6 | **验收项 7 的"恰为 32"无独立预言机** | `MAX_ID_LENGTH` 在 `tests/` 里**只出现在 `test_idgen.py` 且全部自引用**（21 处命中全是现算）；变异到自洽的 35 时 10/10 验收仍 PASS。见 §10-1 |
| 7 | **真·空库路径**（不是"空命名空间"） | 与 #1 同源：`alembic` 的"零到目标结构"是在 `aicore_test` 内**清空同名表**后验证的（3.5 报告 N1 自认），`CREATE DATABASE` 的字符集/排序/库级权限、"库不存在时 alembic 的报错形态"**均未验证** |
| 8 | **`test_layering.py` 的并发风险面比登记的更大** | 除探针文件外，它还会**改真实被跟踪的 `provider/__init__.py`** 与**在仓库根写临时配置**（§7） |
| 9 | **32 个残留目录没有 gitignore 规则兜底** | `git check-ignore` exit 1；今天是 ACL 挡住了 `git status`，不是规则挡住（§8） |
| 10 | **`task-3.6-report.md` 缺档**；ledger 引用**不存在的提交** `ffb0bd0` | 我逐项列出 SDD 目录：有 `task-3.6-brief.md`、`task-3.6b-brief/report.md`，**无 `task-3.6-report.md`**；ledger L743 写"提交：`45fb9b8`、`ffb0bd0`"，`git cat-file -t ffb0bd0` → `fatal: Not a valid object name`，`git log --all` 也无此哈希；实际对应提交是 `c604dfa`。ledger 的"10 个提交"清单同时**漏了 `2008cf7`** |
| 11 | `sharding.py` 关于 `3007` 的 docstring 已过期 | `CrossShardOperationError` docstring 写「`AICORE_ERROR_CODES` 里**根本没有** `3007`」—— Task 3.7 接入 3007 后这句话已为**假**（现为 3007 ∈ AICORE_ERROR_CODES）。它不影响任何断言（无测试引用该句），但会误导后来者 |

---

## 10. 阻塞级问题（位置 / 违反条款 / 最小修复建议）

**未发现阻塞级交付物缺陷**：无错误码错配、无 DDL/模型/文档结构漂移、无越界文件、
无凭据入库、无越权建表、无恒真断言、无静默 skip、9 条门禁零失败。

以下 1 项判定为**重要（收尾前必修）**——它不使交付物失效，但使"验收结论可复核"不成立：

### 10-1（重要）验收项 7 的判据与被测对象共用常量，"总长恰为 32"无独立预言机

- **位置**：`services/aicore/scripts/group3_acceptance.py:311`
  `within = max(len(value) for value in ids) <= MAX_ID_LENGTH`；
  `tests/unit/test_idgen.py:36/42/69/103-104/125-141`（期望值全部由 `MAX_ID_LENGTH` 现算）；
  `src/aicore/core/idgen.py:59-61`（`_UUID_HEX_LENGTHS` 也由同一常量现算）。
- **违反条款**：plan 第 3 组验收第 7 条原文「1 万个 ID 全过正则（**总长 ≤32**）且无重复」；
  spec §5.8「**总长必须 ≤32**」+ `er.md` §5.4「均为 `varchar(32)`」。
  现判据是"≤ 模块自己的常量"，**不是 ≤32**。
- **实证（§5-④）**：把 `MAX_ID_LENGTH` 改成**自洽但错误**的 `35`（`task_`→30 hex、`qa_`→32 hex 都在
  `uuid4().hex` 的 32 位以内，故内部自校验不响），
  **`group3_acceptance.py` 仍然输出 `结果：PASS 10 / FAIL 0 / INFO 0`**，
  项 9 打印 `最大长度 35 ≤ 35 True`；全量套件只红 **1** 条，且那一条
  （`TestValidateRejects::test_unknown_kind_raises`）是**附带红**：它的 fixture 长度由同一常量现算，
  长度先不匹配就提前返回 `False`，**根本没走到它想测的"未知 kind"分支**。
  即：项目声称的"挡住 32 被改错"的那道保险（`test_over_length_guard_actually_fires`）
  只覆盖 `MAX_ID_LENGTH > 35`（会让 `new_id` 长度自校验响）与"猴补丁值恰等于变异值"这一巧合，
  **不覆盖 33/34/35 这三个自洽的错值**。
- **影响面**：假绿条件下生成的 ID 会是 33~35 字符，`varchar(32)` 上**每一行都插不进去**
  （或 MySQL 严格模式报 1406）—— 正是 spec §5.8 点名"最容易写错"的那个后果。
- **最小修复建议**（3 行，属**测试侧**改动，不改设计、不改文档，符合 C4）：
  在 `tests/unit/test_idgen.py` 增加一条**字面量**断言，把"32"钉在**权威源**上而非模块常量上：
  ```python
  def test_id_width_is_the_literal_32_from_er_md_and_ddl() -> None:
      """er.md §5.4「均为 varchar(32)」/ DDL 的 ID 列宽是权威；32 必须写死在此，不得由模块常量代证。"""
      assert MAX_ID_LENGTH == 32                    # 字面量，故意与常量自证解耦
      assert all(len(new_id(k)) == 32 for k in ID_PREFIXES)
      # 反向：权威源那一侧也要真的写着 varchar(32)
      ddl = (schema.DDL_DIR / "20_vision_review.sql").read_text(encoding="utf-8")
      assert "`review_id`        varchar(32)" in ddl
  ```
  并把 `group3_acceptance.py:311` 的 `MAX_ID_LENGTH` 换成字面量 `32`（或直接 import 该断言）。
  我在**未变异**的 HEAD 上已用字面量 32 独立复验通过（§6-抽查②），故该修复不会引入新红。

---

## 11. 建议但非阻塞

1. **补 `task-3.6-report.md`，并修正 ledger 的提交清单**：`ffb0bd0` 不存在（`git cat-file` 实测），
   实际是 `c604dfa`；"10 个提交"清单漏了 `2008cf7`。交付报告的**可追溯性**是本项目明确追求的
   价值（"全部证据可由任何人复跑复现"），引用一个不存在的哈希会让这句话失效。
2. **给 32 个残留目录补 `.gitignore` 规则**（如 `services/aicore/pytest-cache-files-*/`、
   `services/aicore/probe-*/`）：`git check-ignore` 实测**无任何规则命中**，
   今天的"干净"完全依赖沙箱 ACL —— 换一台机器/一次 `icacls` 就会污染 `git status`。
3. **`allowed-confusables` 已 4→11 项**：理由是**属实**的（我逐字符核对了落点：`？`/`−`/`×` 在测试的
   注释与断言消息里、`–` 在 `idgen.py` 的 docstring 里），且规则仍开启。
   但 4 个新增字符里有 3 个只服务**一句**文案，建议改为在那一行加 `# noqa: RUF001` 之类的**行级**豁免，
   而不是继续扩大全局白名单 —— 全局白名单会让日后**字符串字面量**里的同形字符同样免检。
4. **`sharding.py` 的 `3007` docstring 已过期**：改为「`3007` 已由 Task 3.7 接入为
   `ConflictError`（资源状态冲突）；跨分片仍是**参数组合**问题，故取 `1003` 而非 `3007`」——
   顺手把"为什么不取 3007"的理由从"它不存在"升级成"语义不对"，后者才是长期成立的论据。
5. **`test_apply_ddl_mysql.py:317` 的随机 skip** 建议改为**固定种子或固定输入**
   （如 `monkeypatch` 掉随机源），消除"随机值碰巧是纯数字"这条与环境无关的抖动。
6. **`test_layering.py` 的探针隔离**（§7）：把探针写进仓库内独立临时包、
   把 `.importlinter_nonexistent` 移出仓库根，可让全量并发跑也敢采信该用例；
   本组不动它（属第 1 组已验收文件），建议单开一个小任务。
7. **迁移侧同样无工具覆盖**：`deploy/sql/migration/env.py`、`versions/*.py`、
   `alembic.ini` 都在 `mypy files=["src"]` 与 import-linter 范围外（与 `scripts/` 同因）。
   若要长期维护，建议把 `files` 扩成 `["src", "scripts", "deploy/sql/migration"]` 并复跑一次。
8. **`session.py` 的装配日志取 INFO**（3.4 报告自认）："只读回落主库"这件事值得一条 WARNING，
   否则生产上"以为在读从库、其实在读主库"会淹没在 INFO 里。

---

### 附：本次评审的产物清单（全部在 `D:\progrom\.review-group3\`，worktree 内零新增）

`gates.ps1`（9 条门禁串行驱动）、`g1..g9*.txt`（原始输出）、`mutate.py` + `backup/`（变异与字节还原）、
`m2.ps1` / `m3.ps1` / `m3c.ps1`、`spotcheck.py`（§6 抽查）、`probe_guards.py`（§4-⑤ 双向探针）、
`confusable_scan.py`、`commit_check_scan.py`、`verify_claims.py`（§9 逐条核实）。
