# Task 4.11 追加轮（第二次）报告：R1 硬断言 + R2 键异常出处

- 工作树：`D:\progrom\.worktrees\aicore-architecture`（AICORE 微服务）
- 基线：`96fb0f0`（控制者已提交上一轮；上一轮报告 `task-4.11-fix-report.md`）
- 本轮改动文件（2 个）：
  - `services/aicore/tests/unit/test_task_registry.py`（R1）
  - `services/aicore/tests/api/test_deps.py`（R2）
- 建议提交信息：`test(aicore): 把「本仓自己交付的东西」从跳过条件改成硬断言，并让依赖判据键异常出处`
  （两个文件可按此拆成两个提交，见 §5 的拆分建议）
- 本轮**未** `git add` / `git commit`

## 0. 一句话交付

R1：判据 2 的两个「对象不在就跳过」分支 → **硬断言**；
R2：依赖阴性对照的判据从「异常**类型**」收紧到「异常**出处** + 没有观察到值」。
两者都给了 **A/B 判别力自证**——同一变异喂下去：旧代码 SKIPPED／仍绿，新代码**判红**。
控制者复核后要求 R2 再去掉一处**排版耦合**（`match="'settings'"` → `match="settings"`）：
已改，并**重跑同一变异**确认判别力不变（§2.4）。
副作用：默认段 skip 数**不变**（13，全是边界族，环境族命中 0），集成段 3 连跑 **58 passed / 0 skipped**。

---

## 1. R1：把「本仓自己交付的东西」从跳过条件改成硬断言

文件：`services/aicore/tests/unit/test_task_registry.py`
用例：`test_adding_a_type_does_not_require_touching_the_runner`（判据 2：`core/task_runner.py` 里
MUST NOT 出现任务类型字面量）

### 1.1 改法

```python
    # ---- 判据 2：task_runner.py 里没有任务类型字面量 ----
    #
    # 这两个条件曾经是 `pytest.skip`（Task 4.6 时 `task_runner.py` 尚未创建；见模块 docstring）。
    # 本轮改成**硬断言**：扫描对象是**本仓自己交付**的东西，不是环境。
    # 「对象不在就跳过」的代价是：有人把执行器删空/清成空壳时，判据 2 会以 SKIPPED 的形态
    # **静默退出而不是判红**——与刚修掉的"随机值碰巧命中就跳过"同病，
    # 本仓已判过这种形态是**假 skip**（`tests/integration/test_main_assembly.py:216`：
    # 「判据必须与用例的**真实需求**对齐」）。
    assert RUNNER_PATH.is_file(), (
        f"{RUNNER_PATH.name} 不存在：判据 2 的扫描对象是**本仓交付物**，"
        f"缺失属于缺陷而不是环境，MUST NOT 用跳过把它藏起来"
    )
    runner_source = _read(RUNNER_PATH)
    assert _has_code_beyond_docstring(ast.parse(runner_source)), (
        f"{RUNNER_PATH.name} 仍是 docstring 空壳（AST 里除模块 docstring 外没有任何节点）："
        f"扫它等于扫一个空集 ⇒ 执行器被清空了，同样是缺陷，MUST NOT 静默跳过"
    )
    literals = find_task_type_literals(runner_source, registered_types())
    assert literals == [], (...)   # ← 原样保留（判据 2 本体）
```

同一文件的 **3 处历史陈述同步改掉**（否则文档会继续描述一个已不存在的行为）：

| 位置 | 原话 | 现在 |
|---|---|---|
| 模块 docstring「能力的边界」 | 「判据 B 此刻走 `pytest.skip`（不假装验过）……Task 4.7 一交付执行器，同一条用例自动变成真断言」 | 记"两个分支已在 4.11 追加轮改成硬断言"，并把**为什么当时允许、现在为什么过期**写清楚 |
| 用例 docstring 判据 2 一条 | 「本任务时它仍是 1 行 docstring 空壳 → 该条**显式跳过并说明**，MUST NOT 假装验过」 | 改为历史留档 + 指向硬断言；并保留「判据 1 的断言排在判据 2 之前」的顺序说明（原话是"判据 2 报 SKIPPED 时判据 1 仍是真验过的"） |
| `test_runner_literal_scan_is_discriminating` docstring | 「即便判据 2 此刻报 SKIPPED，它的判别力也已经被证明过」 | 改为"两者互补、都 MUST NOT 退化成跳过" |

### 1.2 判别力自证（探针 1，已删）

**（A）新代码：4 个变异必须判红且不是 skip**（变异只改探针目录里的临时副本，`src/` 未动）

| 变异（喂给 `RUNNER_PATH`） | 结果 | 抓它的断言 |
|---|---|---|
| 基线（真实 `task_runner.py`） | `1 passed`（exit 0） | — |
| M1 路径不存在 | `1 failed` | `runner_missing.py 不存在：判据 2 的扫描对象是**本仓交付物**，缺失属于缺陷而不是环境，MUST NOT 用跳过把它藏起来` |
| M2 空文件 | `1 failed` | `runner_empty.py 仍是 docstring 空壳（AST 里除模块 docstring 外没有任何节点）：扫它等于扫一个空集 ⇒ 执行器被清空了，同样是缺陷，MUST NOT 静默跳过` |
| M3 只有 docstring | `1 failed` | 同上 |
| M4 含任务类型字面量（`TYPE = "OCR"`） | `1 failed` | `runner_with_literal.py 出现任务类型字面量 [(3, 'OCR')]：执行器应按注册表表查找解析类型，MUST NOT 出现任何逐类型分支（design.md:194）` |

四个变异的 pytest 摘要都是 `1 failed`，**没有** `SKIPPED` 行、没有 `1 skipped` ⇒ 判红而不是 skip。
M4 的作用是证明**改写没有削弱判据本来那一条**（看到字面量照样红）。

**（B）旧代码（`git show HEAD:…` 取出的真本，内存 `exec`，非手抄）**

```
[OK ] B0旧本确实含那两个 skip 分支 :: HEAD 版本里两个分支都在
M1 路径不存在: 旧代码抛 Skipped :: skipped=True
M2 空文件: 旧代码抛 Skipped :: skipped=True
M3 只有 docstring: 旧代码抛 Skipped :: skipped=True
```

⇒ 同一组变异：**旧代码静默跳过、新代码判红**。这正是控制者要的「必须变红而不是 skip」，
也说明本轮改的是**形态**而不是"顺手把测试改松/改紧"。

> 自证过程中的一个自查：探针第一版的"不是 skip"判据误报（我扫的是 `"skipped" in stdout`，
> 而 pytest 回溯会打印我新写的源码注释，里面本来就有 `SKIPPED` 字样）。
> 已改成只认 pytest 自己的跳过报告（行首 `SKIPPED` 或摘要 `1 skipped`）后全绿——
> 记在这里是因为它与本轮主题同形：**判据要键出处，不能键子串**。

### 1.3 为什么这不属于"顺手全改"

上一轮我把这两处列为**可疑**并只报不改，等到了明确裁定；控制者采纳的理由与本仓既有判例一致，
改法也按裁定给的两种之一（硬断言）执行，且**保留了** `test_runner_literal_scan_is_discriminating`
（它刻意不跳过）——判别力与"真文件被验过"两件事分开守，没有互相顶替。

---

## 2. R2：依赖阴性对照的判据收紧到「异常出处」

文件：`services/aicore/tests/api/test_deps.py`
用例：`test_dependency_is_not_available_before_startup`（**阴性对照**）

### 2.1 改法

```python
    client = TestClient(app)  # 刻意不进 `with`：不触发 lifespan
    with pytest.raises(AttributeError, match="settings"):
        client.get("/__probe__/settings")

    assert observed == [], (
        "依赖竟然解析出值并交给了路由：说明有人加了兜底取值"
        "（`api/deps.py` 明令禁止，它会把误配置推迟到运行期）"
    )
```

两条**正面事实**取代了原来的「抛了 `AttributeError` 就算走对了路」：

1. **出处**：抛出的必须是 `State.__getattr__` 那一条（消息里点名缺失的属性 `settings`）；
2. **没有观察到值**：`observed == []`（路由一旦拿到 settings，第一件事就是 `observed.append`）。

同时补 `import pytest`（该文件此前没有用它）；用例 docstring 记下了旧判据的实测盲区
（`Settings()` 判红、`model_construct()` / `SimpleNamespace()` 仍绿）与机理
（`TestClient` 会把**处理函数内部**的 `AttributeError` 原样抛出）。

> `match` 的第一版带单引号（`match="'settings'"`），控制者复核后指出这是**排版耦合**：
> 上游把引号改成双引号、或写成 `State has no attribute settings`，判据就会因**纯排版**变红。
> 那种红换不来任何判别力，却会**训练人忽略红**——与刚花一轮消灭的随机假红是同一类成本。
> 已改为 `match="settings"`（§2.4 给了重跑证据与解耦证据）。

### 2.2 判别力自证（探针 2，已删）

变异方式：读 `src/aicore/api/deps.py` 源码 → 内存替换（锚点唯一）→ `compile` → `exec` 成新模块
对象并注册为 `aicore.api.deps`（在 `pytest_configure` 里，早于测试模块导入）⇒ **磁盘文件不动**。

| 兜底写法注入 `get_settings` | 结果 | 抓它的判据 |
|---|---|---|
| 基线（真实 `deps.py`） | `1 passed`（exit 0） | — |
| `Settings()`（请求变成 200） | `1 failed` | `Failed: DID NOT RAISE AttributeError` ⇒ 判据① |
| `SimpleNamespace()`（处理函数内炸） | `1 failed` | `AssertionError: Regex pattern did not match. Expected regex: "'settings'"; Actual message: "'types.SimpleNamespace' object has no attribute 'env'"` ⇒ 判据①（**出处**）〔这是**改前**带引号正则那一次；去引号后的重跑见 §2.4〕 |

两个变异都不是 skip。第二条尤其关键：它正是上一轮**旧判据下仍然全绿**的那一个形态，
现在被"出处"判据精确抓住——红了，而且**红的理由是对的**。
（`observed == []` 在第二个变异里轮不到执行：`pytest.raises` 先失败了。两条判据是"或"的关系，
任一条成立即判红；这一点在报告里说明，避免被读成"判据②没生效"。）

### 2.3 有意收紧的两点（口径变化）

1. **不再接受"框架把它转成 500"**（控制者已确认）：旧代码有 `assert response.status_code == 500`
   的兜底分支，新判据要求异常**传播到调用方**且点名 `settings`。若将来 FastAPI/Starlette 把它
   转成 500 响应，这条会红（fail-closed）——那正是一次"必须重新做决定"的红，而不是静默通过。
   当前实测行为就是"原样抛出"（基线绿 + `namespace` 变异实测）。
2. **判据仍然要求"消息点名缺的属性"，但已去掉标点耦合**（§2.4）：窄到"键的是哪个属性"，
   不再依赖上游用单引号还是双引号。这是本轮控制者复核后唯一的改动点。

### 2.4 复核改动：`match="'settings'"` → `match="settings"`（重跑自证）

改动理由（控制者）：`match` 是正则**搜索**，带引号就等于把判据绑定到 Starlette 今天的排版；
上游改成双引号或无引号会因**纯排版**变红，而那种红换不来判别力，却会**训练人忽略红**
——与本轮刚消灭的随机假红是同一类成本。

**重跑同一组变异（探针，已删）**：

```
--- (1) 基线：真实 deps.py（应绿）---            exit=0 :: 1 passed
--- (1) 变异 strict：兜底 Settings()（应红）---   exit=1 :: 1 failed
    E       Failed: DID NOT RAISE AttributeError
--- (1) 变异 namespace：兜底 SimpleNamespace()（本次改动的验收点）---  exit=1 :: 1 failed
    E       AssertionError: Regex pattern did not match.
    E         Expected regex: 'settings'
    E         Actual message: "'types.SimpleNamespace' object has no attribute 'env'"
[OK ] namespace 仍判红 :: 去掉引号后判别力未被去掉
[OK ] 红的理由仍是『出处』 :: regex 不匹配（非别的原因）
[OK ] 不是 skip :: 输出里没有 1 skipped
```

⇒ 控制者要的那一步验收（`SimpleNamespace` 变异**仍然红**）通过，且红的理由仍是**出处**。

**排版解耦的量化证据**（两种正则 × 四种上游文案，`re.search` 实测）：

| 上游文案 | 带引号 `'settings'` | 不带引号 `settings` |
|---|---|---|
| `'settings'`（今天的 Starlette 1.6.0） | 命中 | 命中 |
| `"settings"`（改成双引号） | **不命中** | 命中 |
| `State has no attribute settings`（无引号） | **不命中** | 命中 |
| `'types.SimpleNamespace' object has no attribute 'env'`（兜底爆炸，MUST NOT 命中） | 不命中 | 不命中 |

⇒ 去掉引号只去掉了**排版耦合**，信息量（"缺的是 `settings`"）一字不少，
且"兜底爆炸"那条仍然不被误放行。

---

## 3. 跳过普查现状（本轮之后）

| 口径 | 上一轮 | 本轮之后 |
|---|---|---|
| `pytest.skip` 调用点 | 19 | **17** |
| 合法（环境族 14 + 边界族 3） | 17 | **17** |
| 可疑 | 2（`test_task_registry.py:704/708`） | **0**（已改成硬断言） |
| 缺陷 | 1（随机自跳过，已修） | **0** |
| 装饰器形态（`mark.skip`/`skipif`/`xfail`/`importorskip`） | 0 | **0** |
| 裸 `return` 早退 | 2 | 2（`test_deps.py` 那处已收紧成"出处 + 无值"；`test_provider_base_contract.py:133` 本身紧跟取反断言，无需改） |

**默认段 skip 数不变**（13 = 11 + 1 + 1）：R1 那两个分支本来就是死分支，所以数量没动——
变的是**形态**：现在谁把执行器删空，默认段会**红**而不是多两条 SKIPPED。

---

## 4. 验收证据（全部在最终字节上跑）

### 4.1 默认段（`-m "not integration"`，带 `-rs`）

```
SKIPPED [11] tests\structural\test_source_guards.py:102: provider 包是唯一允许发起外部模型调用的层
SKIPPED [1] tests\unit\test_envelope.py:501: /metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言
SKIPPED [1] tests\unit\test_provider_base_contract.py:148: 判别力载体：它的用途是签名漂移，不是协程性
1325 passed, 13 skipped, 58 deselected, 1 warning in 39.57s
pytest exit=0
```

（`match` 去掉引号后重跑一次：`1325 passed, 13 skipped, 58 deselected, 1 warning in 39.90s`，
归因三行同上、exit 0——数值与上一段一致。）

- 13 条**全部**是边界族，**环境族命中 0** ⇒ 符合控制者本轮收窄后的规则
  （默认段允许这 13 条但必须逐条归因）；
- 1 个 warning 是既有的 sqlite `DeprecationWarning`（`test_task_poll.py`），与本轮无关；
- `58 deselected` 与集成段条数一致。

### 4.2 集成段连跑 3 次（`-m "integration"`，带 `-rs`）

```
===== INTEGRATION RUN 1 =====
58 passed, 1338 deselected in 26.02s
run 1 exit=0
===== INTEGRATION RUN 2 =====
58 passed, 1338 deselected in 26.14s
run 2 exit=0
===== INTEGRATION RUN 3 =====
58 passed, 1338 deselected in 25.93s
run 3 exit=0
```

三次都是 **58 passed / 0 skipped / exit 0**，`-rs` 无 `SKIPPED` 段。

`match` 改动后重跑三次（同一命令）：`58 passed, 1338 deselected` —— `26.16s` / `26.47s` / `25.86s`，
三次 exit 0、同样无 `SKIPPED` 段。

### 4.3 其它门禁

| 门禁 | 命令 | 结果 |
|---|---|---|
| ruff | `ruff check --no-cache src tests scripts` | `All checks passed!`（exit 0） |
| mypy | `mypy --strict src` | `Success: no issues found in 62 source files` |
| 分层契约 | `lint-imports --config .importlinter` | `Contracts: 4 kept, 0 broken.`（1 条既有 warning：`No matches for ignored import aicore.service.** -> aicore.provider.base`） |
| 第 3 组验收 | `python scripts/group3_acceptance.py` | `PASS 10 / FAIL 0 / INFO 0` |
| Redis 残留 | 只读扫 `aicore:*` + `dbsize` | `dbsize = 0`；`aicore:* = []` |

### 4.4 工作树状态（提交前核对）

```
$ git status --porcelain
 M services/aicore/tests/api/test_deps.py
 M services/aicore/tests/unit/test_task_registry.py
?? .sdd-tools.py            ← 不是本轮产物
$ git diff --stat
 services/aicore/tests/api/test_deps.py           | 39 +++++++++++++++-----
 services/aicore/tests/unit/test_task_registry.py | 46 +++++++++++++++---------
 2 files changed, 61 insertions(+), 24 deletions(-)
$ git log --oneline -2
96fb0f0 test(aicore): 用确定性非法月份替掉随机自跳过，并普查同类跳过
bb1a460 test(aicore): 机械守住「没有任何写回目标是 MANUAL_REVIEW」
```

两个文件仍是 LF（与同目录其它文件一致；`core.autocrlf=true` 的 LF→CRLF 提示对所有文件都会出现）。

---

## 5. 未做清单

1. **未** `git add` / `git commit` / `git stash`；推荐按文件拆两个提交（R1 一条、R2 一条），
   顺序无所谓（两者无耦合）；若只提一条，用 §0 给的整句。
2. **未**改 `er.md` / `openapi.yaml` / `provider/**` / `core/errors.py` 语义 / `core/task_runner.py` /
   `core/lease.py` / `.importlinter` / `pyproject.toml`；`src/**` 一个字节未动（所有变异都在内存里）。
3. 本轮探针**只用 2 个**：`D:\progrom\.dsh-probe\prove_r1.py`、`prove_r2.py`
   （连同它们生成的 2 个插件与 3 个变异样本副本）；控制者复核后的 `match` 改动另用 **1 个**
   （`prove_r2_requote.py` + 它生成的 1 个插件）。**已全部删除**，目录现为空。
4. **未** `FLUSHDB`；Redis 清理只按前缀，实测残留 0。
5. 除 R1/R2（含 `match` 去引号）外**未**动任何其它跳过；普查现已无"可疑/缺陷"项（§3）。

---

## 6. 附：一条被记进项目级的教训（同一主题今天出现四次）

控制者把今天的三处并成一条通用纪律：**判据要键"这件事真正的出处"，不能键"看起来相关的表面特征"**。

| # | 场景 | 键错了什么 | 正确键法 |
|---|---|---|---|
| 1 | Task 4.9 真并发自证 | 栅栏位置（键"两个请求都进来了"，没键"查询已发生且为空"）⇒ 冲突根本没发生而三条结果断言全绿 | 键**因果链**那一环 |
| 2 | R2 依赖判据（本轮） | `except AttributeError`（键**异常类型**）⇒ 造个假兜底也能过 | 键**异常出处** |
| 3 | 我的探针"不是 skip"检查 | `"skipped" in stdout`（键**子串**）⇒ 回溯里我自己注释的 `SKIPPED` 字样也命中 | 键**产出方自己的报告** |
| 4 | 我的探针在 `match` 改动后的检查 | `Expected regex: "settings"`（键 **pytest 打印正则时的引号风格**）⇒ 误报一次 | 键**判据的内容**（`Expected regex: 'settings'` 的实际形态） |

第 4 条是**本轮新踩的**（控制者只看到前三条）：我把探针的检查写成了 pytest 消息的字面排版，
于是"改动是对的"这件事实被探针误判成失败——与 R2 要修的问题**同形**，只是这次坏在探针里。
已改为按内容判、重跑全绿。**记在这里是因为它证明这条纪律对我同样适用**：探针也是判据，
也得键出处。

---

## 7. 后续（第 4 组收口：缓期登记已进仓库内文件）

R1/R2 经控制者复核后提交为 `d6d20e7` + `f97849f`。随后按第 4 组收口复核的意见，
把四处「缓期」从**被 `.superpowers/sdd/.gitignore` 忽略的报告**里搬进**仓库内跟着任务走的文件**：
`openspec/changes/implement-aicore-service/tasks.md`（纯文档，+9 行，未提交）。

- ① 缓期登记：`4.8`（耗时对照 → `13.4`；附注 `run_cpu_bound` 在 `src/` 零调用点）、
  `4.9`（Provider 调用次数字面判据 → 第 5 组，并写明等价形态**弱一步**）、
  `4.10`（分级端到端 → 第 5 组，指向会自过期的 `test_confidence_grading.py` 判据）、
  `4.11`（按码计数 → 第 11 组；并记下仓库内确实没有判据把它挂上）；
- ② `4.3` 口径更正（超时/熔断终码 = `5002`，原句保留）；
- ③ `4.10`「阈值变更记录可查」按权威文档（`spec.md:58` + `er.md:27`）执行为**当次阈值快照**。

详见 `group4-closure-registration.md`（含 `openspec validate --all --strict` 的原始输出：
`Totals: 5 passed, 0 failed`；任务行数 86 未变）。
