# Task 4.11 追加轮报告：随机自跳过修复 + 同类跳过普查

- 工作树：`D:\progrom\.worktrees\aicore-architecture`（AICORE 微服务）
- 基线：`bb1a460`（Task 4.11 第二个提交），本轮**未** `git add` / `git commit`
- 本轮唯一改动的文件：`services/aicore/tests/repository/test_apply_ddl_mysql.py`
- 建议提交信息：`test(aicore): 用确定性非法月份替掉随机自跳过，并普查同类跳过`

## 0. 一句话交付

① 随机自跳过**已修**（写死 `"12345x"`，必然含字母 ⇒ 每次真跑），并给了 can-go-red 自证：
两个 SUT 变异分别被该用例自己的两条断言抓到、连跑 10 次 10/10 真跑且绿；
② 全仓普查：**`pytest.skip` 调用点 19 处 = 合法 17 / 可疑 2**，另 **缺陷 1 处（即 ①，已修）**，
装饰器形态（`mark.skip` / `skipif` / `importorskip` / `xfail`）**0 处**；
可疑 2 处**只报不改**，等指令。附带发现 1 处「裸 `return` 的原因盲区」（非 skip 形态）一并报上。

---

## 1. ① 随机自跳过：已修

### 1.1 现场（修前）

```python
@pytest.mark.integration
def test_apply_ddl_rejects_bad_month(drill_month: str) -> None:
    """参数自检：非法月份 MUST 以非 0 退出码拒绝，MUST NOT 静默建到错月份。"""
    bad = uuid.uuid4().hex[:6]  # 6 位但含字母与数字，可能碰巧全数字则跳过
    if bad.isdigit():
        pytest.skip("随机值碰巧是纯数字，本用例只验证非数字月份被拒")
    ...
```

`uuid4().hex[:6]` 是 6 位十六进制，**全为数字的概率 `(10/16)**6 = 0.0596…`，即 **5.96%**
（`1/0.0596 ≈ 16.8` ⇒ 平均每 **17** 次跑一次）。控制者本轮健康检查实测到 1 次：
`57 passed, 1 skipped`。

> 数值勘误：本轮的初稿 docstring 把概率写成 `≈ 4.7%`（"每 21 次一次"），
> 复算后是 `5.96%`（"每 17 次一次"）；交付文件里的数值已是复算值。

两层危害（写进了新 docstring）：

1. **一个自己决定不跑的用例，和一个不存在的用例没有区别**：平均每 17 次跑就有一次静默
   不跑，而报告里仍是绿的；
2. 门禁规则是「集成段 `skipped != 0` 即视为未通过」⇒ 这条**随机**跳过把那条规则变成
   **假警报源**：真出问题时，第一反应会是"大概是那条随机的又碰上了"。

### 1.2 修法

```python
    bad = "12345x"  # 6 位、含字母 ⇒ 必然落到「必须是 6 位数字 YYYYMM」那条拒绝
    assert len(bad) == 6 and not bad.isdigit(), (
        "取值前提变了：本用例验的是『长度对但不是 6 位纯数字』这一档"
    )
    result = _run_apply(bad)
    assert result.returncode != 0, "非法月份应被拒绝"
    assert "6 位数字" in result.stderr, f"拒绝原因应可读，实际 stderr：{result.stderr!r}"
```

- 取值本身**把前提写成断言**：取值前提若被人改坏（例如改成合法月份），用例立刻变红，
  而不是又一次"碰巧跳过去"。
- **MUST NOT** 用「重摇直到非全数字」的循环：那只是把不确定性藏进一个循环里，
  仍然存在"循环次数不可预测"和"这段代码没人验"两个问题；确定性取值没有这些问题。
- 被验对象没变：仍是「长度对但不是 6 位纯数字」这一档，仍走 `scripts/apply_ddl.py` 子进程
  （运维真正会敲的那条命令），仍断言**退出码非 0** + **原因可读**。
- `import uuid` 已删（否则 ruff F401）。

### 1.3 can-go-red 自证（探针，已删；输出原文见 §4.4）

| 项目 | 做法 | 结果 |
|---|---|---|
| 结构自证 | AST 扫该用例体：`pytest.skip` 调用点 | `[]`（结构性不可能自跳过） |
| 结构自证 | 旧跳过的守卫 `("12345x").isdigit()` | `False` ⇒ 即便那段代码搬回来也**进不去** |
| 变异 A | CLI 原因文案不变、退出码 `SystemExit(2)`→`(0)` | 被断言①抓到：`AssertionError: 非法月份应被拒绝` / `assert 0 != 0` |
| 变异 B | CLI 仍非 0 退出，原因文案换成 `月份格式不对` | 被断言②抓到：`AssertionError: 拒绝原因应可读` |
| 基线 | 真实 CLI | `1 passed` |
| 确定性 | 同一条用例连跑 10 次 | `1 passed` ×10，`skipped` 出现 **0** 次 |

变异**只在内存里**做：读 `scripts/apply_ddl.py` → 字符串替换（断言锚点唯一，`count == 1`）
→ `compile` → 落成探针目录下的旁本文件；`src/` 与 `scripts/` 一个字节都没改。
两个变异都只翻**一个**可观测量，且都在校验处退出 ⇒ **不落任何 DDL、零副作用**。

---

## 2. ② 同类跳过普查

### 2.1 方法（机器扫描，不靠人眼记忆）

探针用 AST 全量遍历 `tests/**/*.py`（跳过 `__pycache__`），对每个 `pytest.skip(...)` 调用：

1. 打印 `文件:行`、所在函数名、**包裹它的 `if` 条件**（源码片段）、skip 消息；
2. 另扫装饰器形态 `pytest.mark.skip` / `skipif` / `xfail` / `pytest.importorskip`；
3. 附带扫另一种「自己决定不跑」的形态：**测试体里的裸 `return`**。

### 2.2 原始数据

```
TOTAL_SKIP_CALLS 19
TOTAL_EARLY_RETURNS 2
装饰器形态（mark.skip/skipif/xfail/importorskip）：0 处
```

- 19 处调用点与独立 `grep` 结果**逐行一致**（互相印证，不是同一份数据的两次引用）；
- 装饰器形态 **0 处** ⇒ 本仓不存在"挂在用例上的条件跳过"，全部跳过都是**测试体内/夹具内**的显式决定；
- 裸 `return` 2 处见 §3.2。

> **口径提醒（避免看 `-rs` 时误判本普查漏项）**：普查列的是**决策点**（`pytest.skip` 写在哪个函数里），
> 而 `-rs` 打印的是**命中面**（哪条用例被跳过）。夹具里的跳过会被 pytest 归因到**请求该夹具的用例**行号，
> 所以死库环境下会看到 `test_repos.py:1263/1353/1375/1396`、`test_submit_mysql.py:179/247/278`、
> `test_runner_redis.py:360/412/491` 等行号——它们的**决策点**都是本表里的 14 个环境探测（§2.4）。

### 2.3 分类总表：合法 17 / 可疑 2 / 缺陷 1（已修）

| # | 位置 | 用例 / 夹具 | 条件 | 判定 |
|---|---|---|---|---|
| 1 | `tests/conftest.py:492` | 夹具 `redis_client` | `redis_is_available() is not None` | 合法（外部依赖 Redis 未就绪） |
| 2 | `tests/conftest.py:525` | 夹具 `redis_store` | 同上 | 合法 |
| 3 | `tests/conftest.py:594` | 夹具 `integration_engine_factory` | 无 `DSH_IT_MYSQL_PASSWORD` | 合法 |
| 4 | `tests/conftest.py:605` | 夹具 `integration_engine_factory` | 连不上 MySQL | 合法 |
| 5 | `tests/repository/test_apply_ddl_mysql.py:91` | `_engine`（DDL 演练库） | 无口令 | 合法 |
| 6 | `tests/repository/test_apply_ddl_mysql.py:114` | `_require_mysql` | 连不上 | 合法 |
| 7 | `tests/repository/test_migration.py:491` | `_drill_engine` | 无口令 | 合法 |
| 8 | `tests/repository/test_migration.py:516` | `_drill_engine` | 连不上 | 合法 |
| 9 | `tests/repository/test_repos.py:1161` | `_mysql_engine` | 无口令 | 合法 |
| 10 | `tests/repository/test_repos.py:1184` | `_require_mysql` | 连不上 | 合法 |
| 11 | `tests/repository/test_session.py:542` | `_integration_settings` | 无口令 | 合法 |
| 12 | `tests/repository/test_session.py:565` | `_skip_unless_mysql_reachable` | 连不上 | 合法 |
| 13 | `tests/repository/test_sharding.py:518` | `_engine` | 无口令 | 合法 |
| 14 | `tests/repository/test_sharding.py:541` | `_require_mysql` | 连不上 | 合法 |
| 15 | `tests/structural/test_source_guards.py:102` | `test_model_http_calls_only_in_provider[provider/*]` | `path.parts[...] == "provider"` | 合法（规则**作用域**边界；实测贡献 11 条） |
| 16 | `tests/unit/test_envelope.py:501` | `test_metrics_is_bare_too_when_the_endpoint_lands` | `"/metrics" not in paths` | 合法（**能力**边界，自过期） |
| 17 | `tests/unit/test_provider_base_contract.py:148` | `test_implementation_method_is_async[_DriftedTextProvider]` | `impl is _DriftedTextProvider` | 合法（该单元格对本载体无判别意义） |
| 18 | `tests/unit/test_task_registry.py:704` | `test_adding_a_type_does_not_require_touching_the_runner` | `not RUNNER_PATH.is_file()` | **可疑（报请裁定）** |
| 19 | `tests/unit/test_task_registry.py:708` | 同上 | runner「仍是 docstring 空壳」 | **可疑（报请裁定）** |
| — | `tests/repository/test_apply_ddl_mysql.py:318`（**已修，不在现状里**） | `test_apply_ddl_rejects_bad_month` | `bad.isdigit()`（`uuid4().hex[:6]`） | **缺陷（已修）** |

**计数**：合法 **17** / 可疑 **2** / 缺陷 **1（已修）** ⇒ 现状 19 = 17 + 2。

### 2.4 逐条判定依据

**(a) 合法 14 处＝环境探测族**（表中 1–14）：条件全部读**外部依赖**，且 skip 消息
**点名缺什么**（`DSH_IT_MYSQL_PASSWORD` / `aicore_test@127.0.0.1:3306` / Redis 探测原因），
并给出"怎么补"。这一族**不含任何** 随机值、时间、行数、查询结果，
且本机环境齐备时**一条都不触发**（默认段 `-rs` 里它们的命中数为 0，见 §4.2）。

**(b) 合法但要点名的 3 处**：

- **#15 `test_source_guards.py:102`**：规则 5 是「外部模型 HTTP 调用只允许出现在 `provider/`」，
  对 `provider/` 自己的文件而言这条规则**不适用**（不是"没验到"，是"按设计排除"）。
  它是**确定性**的（只取决于文件路径），且**有配套的非空下限**：同文件
  `test_rule_5_scan_is_not_vacuous` 断言非 provider 文件非空、扫描文件数 ≥ 下限——
  即「扫描范围塌掉」时会有**红灯**而不是全 skip。
  **要点名**：它是默认段 13 条 skip 中的 **11 条**（参数化展开），
  所以「默认段 0 skipped」**在设计上不可能**成立；控制者的「0 skipped」门禁**只对集成段**有意义。
- **#16 `test_envelope.py:501`**：`/metrics` 由后续（可观测性）任务交付，此刻**没有可断言的对象**。
  它是**确定性**且**自过期**的：端点一到岗，同一条用例自动开始断言
  （不是"到岗后要记得回来改"）。与控制者此前肯定的"自过期判据"同源，只是方向相反（存在才断言）。
  **要点名**：它让默认段多 1 条 skip；若该任务被取消/长期不落地，这条 skip 会**永久**留着——
  这是**交付风险**，不是用例缺陷，请在验收该端点时一并把它划掉。
- **#17 `test_provider_base_contract.py:148`**：`_DriftedTextProvider` 是**判别力载体**
  （用途是让签名判据失败），它的 `complete` 本来就是 `async def`，
  "是不是协程函数"这条对它**没有判别意义**；而同一载体在
  `test_implementation_signature_equals_protocol_signature` 里是**取反断言**
  （`pytest.raises(AssertionError, match="签名不一致")`）——它的判别力在别处已经兑现，
  这里跳过**不是**把检查躲掉。

### 2.5 「合法跳过」的代价：它们同样会让 `0 skipped` 不成立（实测）

把 MySQL 端口指向一个**没有监听**的端口（只改进程环境变量，不动任何文件）：

```
$env:DSH_IT_MYSQL_PORT = "3399"
pytest -p no:cacheprovider -o addopts="" -m "integration" -q -rs
→ 26 passed, 32 skipped, 1338 deselected in 74.09s
→ pytest exit=0          ← 注意：退出码仍是 0
```

两条结论：

1. **环境类 skip 的命中面是 32 条用例**（14 个决策点的爆炸半径），而不是 14；
2. **pytest 对 skip 仍返回 0** ⇒ 如果没有「集成段 0 skipped」这条门禁，
   一次**变量名拼错 / 端口写错 / 演练库被停**就会让整段覆盖静默消失而 CI 依然绿。
   这正是那条门禁的来由，也是本普查必须把这 14 处一条条点名的原因。

### 2.6 何时该 skip、何时不该（本轮给出的判据）

| 该 skip | 不该 skip |
|---|---|
| 依赖**本机不可能满足的外部条件**：无演练库凭据、端口无监听、无 Redis | 依赖**本仓库自己交付的东西**在不在（文件、端点、表、handler） |
| skip 理由**点名变量名 / 端点 / 库名**，并说明怎么补 | 理由是"这次没构造出条件"（随机值、时间、行数、查询结果） |
| 这条用例的**真实需求**确实需要那个外部依赖 | 用例其实**一条外部依赖都不需要**，只是顺手写了 skip |

后两条不是我发明的，是**本仓已有的判例**，本轮据此对齐：

- `tests/unit/test_provider_base_contract.py:188`
  「早期版本这里构造实例、对需要构造参数的真实通道 `pytest.skip`——那是**没有理由的跳过**：
  它会让真实通道恰好躲开这条检查，而真实通道才是最需要被检查的一侧。」
- `tests/integration/test_main_assembly.py:216`
  「N6 的修复：第一版在缺凭据时 `pytest.skip`，而这三条用例**一条外部依赖都不需要**
  （死端口下仍 4 passed 已证）⇒ 那是**假 skip**：凭据缺失时覆盖被静默砍掉……
  **判据必须与用例的真实需求对齐**。」

⇒ 规则 18/19（「对象不在就跳过」）之所以被列为**可疑**，正是因为它们把
**本仓自己交付的 `task_runner.py`** 是否就位当成了"环境"：那正是上表右列第二行。

---

## 3. 报请裁定（本轮**只报不改**，等控制者口头指令）

### 3.1 R1（可疑，2 处）：`tests/unit/test_task_registry.py:704 / :708`

```python
    if not RUNNER_PATH.is_file():
        pytest.skip(f"{RUNNER_PATH.name} 尚不存在：Task 4.7 才创建它，本任务没有可扫描的对象")
    runner_source = _read(RUNNER_PATH)
    if not _has_code_beyond_docstring(ast.parse(runner_source)):
        pytest.skip(f"{RUNNER_PATH.name} 仍是 docstring 空壳……Task 4.7 交付执行器后本断言自动生效")
```

- **现状**：`task_runner.py` 已存在且非空壳 ⇒ 两个分支**都已不可达**，本条现在**确实在跑**
  （所以它**不是**当下的缺陷）；
- **形态**：它们是"对象没就位就跳过"的**历史遗留**。今天若有人把 `task_runner.py`
  **删掉或清空**，这条用例会**静默 skip 而不是判红**——"判据 2：runner 里没有任务类型字面量"
  会以"绿"的形态消失。这与上一节右列第二行完全同形。
- **建议**（若控制者要收）：
  1. 把两处换成硬断言：`assert RUNNER_PATH.is_file()` / `assert _has_code_beyond_docstring(...)`，
     理由串直接写"没有可扫描的对象 = 执行器缺失，属于缺陷不是环境"；或
  2. 删掉两个分支（`_read` 让文件缺失自己抛 `FileNotFoundError`，同样是红灯）；
  3. 保留 `test_runner_literal_scan_is_discriminating`（它扫合成样本、**刻意不跳过**，
     已保证"判据本身有判别力"，与本条互不替代）。
- **未做**：按工作纪律「MUST NOT 顺手全改」，本轮一个字节都没动它们。

### 3.2 R2（附带发现，非 skip 形态）：`tests/api/test_deps.py:107` 的裸 `return` 有**原因盲区**

该用例是一条**阴性对照**（未进 lifespan 时取依赖必须失败）。它的通过分支是：

```python
    try:
        response = client.get("/__probe__/settings")
    except AttributeError:
        # 期望路径：Starlette 的 State.__getattr__ 在属性缺失时即抛。
        return
    assert response.status_code == 500, "未启动时依赖竟然可用……"
```

本轮把**该用例文档逐字点名的失败形态**注入进去做变异（内存变异，`src/` 不动）：

| 变异（`get_settings` 兜底） | 结果 | 说明 |
|---|---|---|
| `Settings()`（文档点名的形态） | **判红** ✓ | `未启动时依赖竟然可用（HTTP 200）` ⇒ 判据对这一形态有效 |
| `Settings.model_construct()` | **仍绿**（`1 passed`） | 兜底对象被访问属性时抛 `AttributeError` |
| `SimpleNamespace()` | **仍绿**（`1 passed`） | 同上 |

**机理已实测**：`TestClient` 会把**处理函数内部**的 `AttributeError` 原样抛出
（实测：`'types.SimpleNamespace' object has no attribute 'env'`），
而用例的 `except AttributeError: return` 把它当成"期望路径"吞掉 ⇒
`returncode == 0, 1 passed`。即：**判据键的是"异常类型"，不是"异常出处"**。

- **现状影响**：`src/aicore/api/deps.py` 里**没有**任何兜底 ⇒ 没有活体假绿；
  这是"若哪天有人加了兜底（而它恰好会炸）就看不见"的**潜在**弱化。
- **建议**（若控制者要收，任选其一）：
  - `with pytest.raises(AttributeError, match="settings"): client.get(...)`（把出处写进判据）；
  - 或补一句 `assert observed == []`（兜底对象一旦被注入，处理函数已经把 settings 记进 `observed` 了）；
  - 或同时断言 `response.status_code == 500 and observed == []`。
- **未做**：同上，本轮只报不改。这 2 处是"裸 `return`"扫描（共 2 处）里的 1 处；
  另一处 `tests/unit/test_provider_base_contract.py:133` **不是**盲区——
  它的 `return` 紧跟在同一分支的 `pytest.raises(AssertionError, match="签名不一致")` 之后，
  分支自带断言。

### 3.3 R3（判定为合法，但请一并确认口径）

`test_source_guards.py:102`（11 条）与 `test_envelope.py:501`（1 条）是**默认段 13 条 skip 的
全部来源**，两者都是**确定性 + 有兜底/自过期**的作用域或能力边界。若控制者认为
「规则 5 的 provider 文件不该进参数化」（用 `iter_python_files()` 过滤掉，而不是逐条 skip），
那是一次**表述方式**的调整（skip 数 11→0），判据强度不变；请指示是否要收。

---

## 4. 验收证据

### 4.1 集成段连跑 3 次（本轮验收核心）

命令（每次都是同一条）：
`pytest -p no:cacheprovider -o addopts="" -m "integration" -q -rs`

**最终字节上的三次（权威证据，docstring 勘误之后重跑）**：

```
===== INTEGRATION RUN 1 =====
..........................................................               [100%]
58 passed, 1338 deselected in 31.15s
run 1 exit=0
===== INTEGRATION RUN 2 =====
..........................................................               [100%]
58 passed, 1338 deselected in 31.05s
run 2 exit=0
===== INTEGRATION RUN 3 =====
..........................................................               [100%]
58 passed, 1338 deselected in 30.14s
run 3 exit=0
```

勘误前的同一命令三次（同样 58 passed / 0 skipped，仅耗时不同）：
`32.95s` / `32.89s` / `31.99s`，exit 全 0。

- 六次都是 **58 passed / 0 skipped / exit 0**；
- `-rs` **没有**输出 `short test summary info` 段（无 SKIPPED 行）⇒ 0 skip 不是被 `-q` 藏起来的；
- 58 条里包含被修的那条（修前它在该环境命中过 `1 skipped`）。

### 4.2 默认段（含 `-rs` 跳过归因）

命令：`pytest -p no:cacheprovider -o addopts="" -m "not integration" -q -rs`

```
SKIPPED [11] tests\structural\test_source_guards.py:102: provider 包是唯一允许发起外部模型调用的层
SKIPPED [1] tests\unit\test_envelope.py:501: /metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言
SKIPPED [1] tests\unit\test_provider_base_contract.py:148: 判别力载体：它的用途是签名漂移，不是协程性
1325 passed, 13 skipped, 58 deselected, 1 warning in 54.46s
pytest exit=0
```

- 13 = 11 + 1 + 1，与 §2.3 的 #15/#16/#17 一一对应；
- **环境族（#1–#14）命中 0 条**（本机 MySQL/Redis 齐备）⇒ 合法环境 skip 与合法边界 skip 在报告里可区分；
- 1 个 warning 是既有的 sqlite `DeprecationWarning`（`test_task_poll.py`），与本轮无关。

### 4.3 其它门禁

| 门禁 | 命令 | 结果 |
|---|---|---|
| ruff | `ruff check --no-cache src tests scripts` | `All checks passed!`（exit 0） |
| mypy | `mypy --strict src` | `Success: no issues found in 62 source files` |
| 分层契约 | `lint-imports --config .importlinter` | `Contracts: 4 kept, 0 broken.`（1 条既有 warning：`No matches for ignored import aicore.service.** -> aicore.provider.base`） |
| 第 3 组验收 | `python scripts/group3_acceptance.py` | `PASS 10 / FAIL 0 / INFO 0`（含真实 MySQL 8 上 9 张表 0 差异、AST 扫 sleep 21 处豁免） |
| Redis 残留 | 只读扫 `aicore:*` + `dbsize` | `dbsize = 0`；`aicore:* 残留键 = []`；`lease/attempts 类残留 = []` |

> 注：本轮第一次跑门禁时用的是系统 `python`（Miniconda），出现
> `ModuleNotFoundError: No module named 'sqlalchemy'` 与 `pytest/ruff/mypy/lint-imports 不是命令`。
> 这是**环境调用错误**（未用工作树 venv），不是被测代码问题；
> 上表结果全部由 `services/aicore/.venv/Scripts/python.exe` 重跑得到。

### 4.4 探针输出原文（① 与 R2 的自证）

```
[OK ] (1)用例体内无 pytest.skip :: skip 调用点 = []
[OK ] (1)取值必然非法 :: bad='12345x' len=6 isdigit=False
[OK ] (1)旧跳过的守卫求值为假（搬回来也进不去） :: 旧代码 if bad.isdigit(): skip -- 对该取值恒为 False

--- (2)A 变异=SUT 非 0 退出改成 0（断言①应红）---
>       assert result.returncode != 0, "非法月份应被拒绝"
E       AssertionError: 非法月份应被拒绝
E       assert 0 != 0
1 failed in 0.82s
[OK ] (2)A断言①变红 :: 变异被用例的『非 0 退出』断言抓到

--- (2)B 变异=SUT 原因文案改掉（断言②应红）---
>       assert "6 位数字" in result.stderr, f"拒绝原因应可读，实际 stderr：{result.stderr!r}"
E       AssertionError: 拒绝原因应可读，实际 stderr："[FAIL] --month 不合法（月份格式不对），收到 '12345x'\n"
1 failed in 1.02s
[OK ] (2)B断言②变红 :: 变异被用例的『原因可读』断言抓到

--- (2)C 基线（真实 CLI，应绿）--- exit=0 :: 1 passed in 0.67s
--- (3)同一条用例连跑 10 次 ---  run 01..10: 1 passed（skipped 出现 0 次）
===== 结论 ===== 全部自证通过
```

R2 的变异证据：

```
[OK ] 基线绿 :: 1 passed
[OK ] 机理已查明 :: TestClient 把处理函数里的 AttributeError 原样抛出：'types.SimpleNamespace' object has no attribute 'env'
[OK ] 变异 strict 被抓到 :: AssertionError: 未启动时依赖竟然可用（HTTP 200）／assert 200 == 500
[BAD] 变异 construct 被抓到 :: 1 passed（漏判）
[BAD] 变异 namespace 被抓到 :: 1 passed（漏判）
```

### 4.5 工作树状态（控制者提交前核对）

```
$ git status --porcelain
 M services/aicore/tests/repository/test_apply_ddl_mysql.py
?? .sdd-tools.py            ← 不是本轮产物（历史遗留未跟踪文件）
$ git log --oneline -3
bb1a460 test(aicore): 机械守住「没有任何写回目标是 MANUAL_REVIEW」
ba55f7d test(aicore): 真库上验 4003/5002 分别落库与分别计数
c924c6d feat(aicore): 受理时冻结当次阈值快照（spec.md:128 留痕）
```

`git diff` 只有两处：删 `import uuid`；`test_apply_ddl_rejects_bad_month` 的取直与两处断言
（外加解释性 docstring）。文件仍是 LF（与同目录其它文件一致；`core.autocrlf=true` 的
LF→CRLF 警告对所有文件都出现，不是本轮引入）。

---

## 5. 未做清单（逐条确认，均为工作纪律要求）

1. **未** `git add` / `git commit` / `git stash`；
2. **未**修改其它任何可疑跳过（R1/R2/R3 全部只报不改）；
3. **未**改 `er.md` / `openapi.yaml`（权威文件）、`provider/**`、`core/errors.py` 语义、
   `core/task_runner.py`、`core/lease.py`、`.importlinter`、`pyproject.toml`；
4. **未**改 `src/**` 任何文件（所有变异都在内存里：读源码 → 替换 → `compile` → `exec` 进临时模块）；
5. **未**产生"改 `src/` + finally 还原"式操作，**未**在仓库内留任何临时/探针文件；
6. 探针文件全部在 `D:\progrom\.dsh-probe\`，**用完已删**（`census_skips.py`、`prove_bad_month*.py`、
   `prove_deps_return.py`、`mutant_plugin.py`、`deps_mutant_plugin.py`、`redis_residue.py`、
   `apply_ddl_exit0.py`、`apply_ddl_msg.py`）；
7. **未** `FLUSHDB`；Redis 清理只按前缀，且本轮结束实测残留 0。

---

## 6. 后续（控制者裁定已落地，2026-09-20）

控制者独立复核后裁定：**R1、R2 都按本报告的建议做**。两者已落地，并各附
**A/B 判别力自证**（同一变异：旧代码 SKIPPED／仍绿 → 新代码判红）：
见 `task-4.11-fix-report-2.md`。

本报告 §2.3 的分类现状随之更新为：**合法 17 / 可疑 0 / 缺陷 0**
（`pytest.skip` 调用点 **19 → 17**；两处「把本仓自己交付的东西当成环境」的分支已改成硬断言）。
本报告保留当时的口径与判定，不改历史结论。
