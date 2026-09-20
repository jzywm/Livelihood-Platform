# Task 4.2 报告：Mock Provider

**状态**：完成（5 条验收命令全绿）。
**工作树**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。未执行任何 `pip install`；未 `git add` / `git commit`。

## 1. 交付物

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/aicore/provider/mock.py` | 571 | 由 1 行 docstring 空壳写满（27998 字节，UTF-8 无 BOM） |
| `tests/unit/test_provider_mock.py` | 1008 | 新建，48 条用例（含参数化）（47209 字节，UTF-8 无 BOM） |

**未改动**工单 §Files 列出的任何「不可改」文件：`base.py` / `results.py` / `errors.py` /
`core/config.py` / `pyproject.toml` / `.importlinter` / `tests/` 下既有文件，逐字未动。
新建的临时探针脚本 **0 个**（`_probe*.py` 一个都没建）；排障一律用 `pwsh` 内联与既有测试用例
完成，未在仓库留下任何临时文件。

## 2. 逐项验收结论

| # | 硬约束 | 结论 | 取证 |
|---|---|---|---|
| §1 | 三通道类 + 常量 + 两个 dataclass，签名逐字 | ✅ | `MOCK_PROVIDER_NAME="mock"`；`MockFault(kind, on_call=1)`；`MockScript(latency_s=0.0, fault=None)`；三类的 `name`/`model_version`/`prompt_version`/`call_count`/`model_meta()` 齐备（`test_all_channels_expose_call_count_and_model_meta`） |
| §2.1 | 同输入同输出（逐字节），`hashlib` 而非 `hash()` | ✅ | 同进程 3 次相等 + **跨进程** 3 条（TEXT/VISION/OCR）+ 判别力自证（不同入参必须不同输出） |
| §2.2 | 延迟可注入、测试不 sleep、`latency_s > timeout_s` 抛超时 | ✅ | 注入假 sleep 断言 `requests == [0.25]` 且墙钟 `< 0.1s`；超时路径**不请求睡眠**且 `code==5002`（三通道参数化） |
| §2.3 | 三种故障各自的异常/返回 | ✅ | `timeout`→5002、`error`→4003、`empty`→正常返回且 `confidence is None`（并正面断言 `!= 0.0`） |
| §2.4 | `on_call` 语义（第 N 次触发，其余正常） | ✅ | `on_call=2` → 正常/抛/正常三步；另加「第 4 次仍正常」；`call_count` 含故障调用 |
| §2.5 | `confidence` ∈ [0,1] 或 None；OCR fields 契约域；载荷字段互斥 | ✅ | 11 个置信度候选逐一校验；三通道各自的载荷互斥断言；`OcrField` 三键非空 |
| §2.6 | 值已脱敏，无 15 位以上连续数字 | ✅ | 4 种 doc_type 参数化；编号类字段额外要求含 `***` 脱敏段 |
| §2.7 | `model_meta()` 委托 `ProviderIdentity.as_model_meta()` | ✅ | 三通道逐键相等，且键集恰为 5 个 camelCase 键、无 snake_case |
| §2.8 | 零网络依赖 | ✅ | 源码无 `httpx`/`requests`/`aiohttp`/`socket`/`urllib` import（源码扫描用例）；运行期零项目建连（见 §4 偏离 D1） |
| §3 | 零 socket 取证 + 判别力自证 | ✅ | autouse 守卫 + 两条自证用例（正例被记录 / 事件循环 self-pipe 不被误判） |
| §4.1-13 | 用例清单 13 项 | ✅ | 逐项落到命名用例，见下 |
| §6 | 探针纪律（> 2 个即停） | ✅ | 0 个 |

**§4 用例清单映射**（48 条 = 13 项 + 参数化展开 + 判别力补充）：

1. 三通道基本调用 → `test_text_provider_returns_text_only` / `..._vision_..._markers_only` / `..._ocr_..._fields_only` / `..._vision_without_labels...`
2. 确定性同进程 → `test_text_output_is_deterministic_within_process` / `..._vision_and_ocr_...`
3. 确定性跨进程 → `test_cross_process_determinism_{text,vision,ocr}`（**关键证据，3 条**）
4. 可注入延迟 → `test_latency_is_requested_through_injected_sleep` / `test_zero_latency_never_calls_sleep`
5. 延迟超时 → `test_latency_above_timeout_raises_without_sleeping[3 参数]`
6. 三种故障 → `test_fault_{timeout,error,empty}_...`
7. `on_call` → `test_fault_on_call_two_triggers_only_on_second_call` 等
8. `call_count` → `test_call_count_counts_faulty_calls_too` / `..._is_per_instance`
9. 脱敏 → `test_ocr_field_values_are_masked[4 参数]` / `test_all_channel_outputs_contain_no_long_digit_run`
10. 置信度域 → `test_all_confidences_are_within_contract_domain` / `test_marker_level_agrees_with_its_own_confidence`
11. `model_meta()` 键名 → `test_model_meta_matches_provider_identity[3 参数]`
12. 零 socket → `test_socket_guard_has_discriminating_power` / `test_socket_guard_does_not_flag_the_event_loop_self_pipe`
13. Protocol 结构子类型 → `test_provider_protocol_structural_subtyping`（docstring 已写明「`@runtime_checkable` 只查成员不查签名」的边界）+ 两条关键字调用签名断言

## 3. 五条验收命令的原始输出

```
### CMD1: .\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_mock.py -q -p no:cacheprovider
................................................                         [100%]
EXIT=0
（48 passed）

### CMD2: .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"
（工单要求 880 passed, 8 skipped —— 见下方 §4 偏离 D3 的说明）
注意：pyproject 的 addopts="-q" 与命令行 -q 叠加会吞掉计数行，故计数用 -o addopts="" 取。
本次实测（排除另一个 agent 当时仍在写入的 tests/unit/test_provider_real.py）：
976 passed, 12 skipped, 19 deselected in 17.89s
EXIT=0
其中属于本任务的是 48 条；基线（本任务动手前实测）为 880 passed, 8 skipped。
另外实测：tests/structural 64 passed, 11 skipped（EXIT=0）。
若**不**排除该文件，同一时刻会看到 56 errors —— 全部落在 test_provider_real.py 内，
与 mock.py 无导入关系（详见 D3）。

### CMD3: .\.venv\Scripts\ruff.exe check --no-cache src/aicore/provider/mock.py tests/unit/test_provider_mock.py
All checks passed!
EXIT=0

### CMD4: .\.venv\Scripts\python.exe -m mypy --strict src
Success: no issues found in 56 source files
EXIT=0

### CMD5: .\.venv\Scripts\lint-imports.exe --config .importlinter
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.
Warnings: No matches for ignored import aicore.service.** -> aicore.provider.base.
EXIT=0
```

基线取证（本任务动手前，`git` 工作区尚未有我的文件时实测）：

```
### 基线: .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"
........................................................................ [  8%]
...（全绿）...
..........................                                               [100%]
[status: completed, exit code: 0]
```

## 4. 偏离项 + 理由

### D1（**必须看**）：零 socket 守卫从「一律禁 connect」改为「按调用栈归因」

工单 §3 给定的实现是「把 `socket.socket.connect` 换成一律抛错的桩」。**该形式在本机
（Windows + Python 3.14.6）不可用**，实测证据：

```
CONNECT ('127.0.0.1', 56708)
  asyncio/runners.py:147:_lazy_init → events.py:735:new_event_loop
  → windows_events.py:316:__init__ → proactor_events.py:639:__init__
  → proactor_events.py:785:_make_self_pipe
```

Windows 上 asyncio 的 Proactor 事件循环用**一对回环 socket** 当 self-pipe，建循环即建连；
而 `pytest-asyncio`（`asyncio_mode="auto"`）在**夹具阶段**就把本用例的循环建好了——
早于本文件任何一行代码。一刀切会让 48 条里所有 async 用例在 setup/teardown 阶段失败
（实测首次运行：51 条全 ERROR），而这些失败与「有没有网络依赖」毫无关系。

**改用的口径**（仍是「可复核、可变异」的工程等价物）：记录每次 connect 及其调用栈，
**只有栈中直接发起 connect 的那一帧属于本项目代码**（本测试文件或 `src/aicore/**`）
才算违规；stdlib 的 `socket`/`asyncio` 帧（即 self-pipe）放行并单独计数。守卫消息里
保留放行条数，使「允许了什么」可见而不是被静默放过。

配套两条自证用例：
- `test_socket_guard_has_discriminating_power`：在测试代码里真的 connect 一次不可达地址
  `127.0.0.1:1`，断言记录被填充、目标与栈都对得上；同时断言「仅构造 socket 不记一笔」
  以证明判据不过宽。用例末尾清空自己那条记录，不给套件留预期中的红灯。
- `test_socket_guard_does_not_flag_the_event_loop_self_pipe`：对照组，证明 self-pipe 不被误判。

**诚实标注的能力边界**：本守卫能抓「本项目代码建连」，**抓不到**「连接由非我们代码的
线程/框架发起」这一形态；`asyncio` 帧无条件放行也是刻意的取舍。上一版本我还试过
「栈里出现过本项目代码就算违规」，实测把 `asyncio.Runner()` 的正常 self-pipe 判成违规
（测试帧确实在栈上），故改为「最内层帧」判据——两种失败形态都写进了代码注释。

### D2：`empty` 故障在 VISION/OCR 上返回空元组而非 `None`，TEXT 返回空串

工单 §2.3 只规定 `empty` 的 `confidence` 为 `None`，未规定各通道载荷的「空」形态。
本实现取：TEXT `text=""`、VISION `markers=()`、OCR `fields=()`。理由：`ProviderResult`
的载荷字段在 `results.py` 里是 `tuple[...] | None`，用 `None` 表达「空」会与「该通道不是
这个载荷」撞在一起（§2.5 要求其余载荷字段为 `None`），调用方就分不清「视觉通道没检出」
与「这不是视觉结果」。已在代码注释与用例 docstring 写明。

### D3：全量套件计数与工单预期的 `880 passed, 8 skipped` 不一致 —— **不是我的改动导致的**

- 本任务动手**前**实测基线：880 passed / 8 skipped（工单预期值即此）。
- 本任务新增：48 条（CMD1 实测 `48 passed`）。
- 同时**另一个 agent（Task 4.3）正在同一工作树并发写入**：我工作期间出现了
  `src/aicore/provider/{_http,guard,deepseek,cloud_vision,cloud_ocr}.py` 与
  `tests/unit/test_provider_{guard,real}.py`（时间戳 10:15–10:20，与本任务同一时段），
  它们也带来了自己的用例。
- 中途两次运行出现过他人文件的失败/报错：
  ① `test_provider_guard.py::test_threshold_is_strictly_greater_than_the_error_ratio` 失败
  → 单独重跑该文件即 **passed**；
  ② 收尾时 `test_provider_real.py` 出现 **56 errors / 58 ERROR 行**（该文件当时仍在被写入）。
  两者都出现在**他人的文件**里，与 `mock.py` 无导入关系。

故本次交付的权威计数分两条，都实测过：

```
# 排除他人正在写入的文件，全量套件（证明我的改动没有破坏任何既有用例）
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -m "not integration" -o addopts="" -q \
    --tb=line --ignore=tests/unit/test_provider_real.py
976 passed, 12 skipped, 19 deselected in 17.89s      EXIT=0

# 结构性专项（含会写源码树探针的 test_layering.py，我串行跑）
.\.venv\Scripts\python.exe -m pytest tests/structural -q -p no:cacheprovider -o addopts=""
64 passed, 11 skipped in 0.48s                       EXIT=0
```

`976 = 880（基线）+ 48（本任务）+ 48（Task 4.3 增量）`，数字可对账。
**本任务的交付计数是 CMD1 的 `48 passed`，不是 976。**

### D4：脱敏断言的范围收窄（第二档只对「编号类字段」生效）

首次实现里我对**所有** `OcrField.value` 都断言必须含 `*`。实测 4 条失败——失败的是
`名称='示例市示例供应链有限公司'`、`有效期至='2028-11-25'` 这类字段。复核 `er.md` §6.2
原文是「value（**脱敏输出**）」，`openapi.yaml:714` 的字段清单是「统一社会信用代码/名称/
法定代表人/有效期至/经营范围等」：**「中间打星号」这个形态在文档里只由编号类字段
（`911301********1234`）示例承载**，对「名称」「有效期至」要求星号是把工单没要求的形态
强加给实现。故改为两档：

1. **全体字段**：MUST NOT 含连续 15 位以上数字（工单 §2.6 原文的可核方式）——红线不变；
2. **编号类字段**（字段名含「编号」/「信用代码」）：MUST 含 `***{3,}` 脱敏段。

判据按**字段名**而不是按值的形状：值的形状会把脱敏本身变成判据的一部分（脱敏后的值含
星号、不再「纯 ASCII」），于是「没脱敏的值」反而被判成非编号字段，断言自我失效——
这一点我在中途实测踩到过（`_is_identifier_shaped` 版本判定为 0 个编号字段），
两版差异与理由都写进了代码注释。

### D5：`MockFault.on_call < 1` 抛 `ValueError`

工单未要求这条校验。理由：`on_call=0` 的直觉含义是「永不触发」，但那样得到的是一个
**永远不生效的故障脚本**，演练会空跑而调用方以为降级链路已验过。构造期失败比运行期
静默更安全。有一条用例覆盖。

### D6：额外新增（工单未要求，但为满足 §1「三个类都要有」的可核性）

- `MockVisionProvider` 每个 label 产出一条 marker（含 `bbox`，键名对齐 `openapi.yaml`
  `VisionMarker`）——工单未规定条数。取「按入参条数」而不是常量，使「传 3 个标签拿到
  3 条标记」可断言；`bbox` 是文档要求的键，漏掉会让「marker 键名与文档一致」永久无法
  在离线侧取证。
- 未登记的 `doc_type` 返回通用字段集（而非空集）：空集会让「Mock 不认识这个 doc_type」
  与「通道返回了空结果」两个成因在数据上不可分，而后者正是 `empty` 故障要演练的形态。
- `test_module_does_not_import_network_libraries`：源码级扫描，与运行期守卫分工互补。

## 5. 没做到的事（如实列，不美化）

1. **「拔网线」本身没做**。工单 §3 也承认无法真拔网线，故我用的是「零建连」工程等价物。
   我没有、也无法证明「在真实断网环境下跑通」——那需要一台断网机器或出口屏蔽。
   本报告能证明的只有：源码无网络库 import、运行期无本项目代码发起的 connect。
2. **D1 的能力边界**：见上。守卫抓不到「非本项目代码发起的连接」，且对 stdlib
   `asyncio`/`socket` 帧无条件放行。若将来 provider 改用某个第三方 SDK 建连，栈里会出现
   该 SDK 的帧（非本项目路径）——那种情况本守卫会漏判，需要靠源码扫描用例兜住。
3. **全量套件的 976/12 含他人未完成的改动**，我无法为 Task 4.3 那部分负责；工单预期的
   `880 passed, 8 skipped` 在本任务叠加后必然变化。若控制者要一个只含本任务的干净计数，
   需要等 Task 4.3 收尾后重跑。
4. **未跑覆盖率门禁**（`pytest --cov`，pyproject 里 `fail_under=80`）。工单 §5 的 5 条
   验收命令里没有它，且它会受并发写入影响，故未执行。
5. **未验证 `mock.py` 在三通道之外的用法**（如 `provider/selector.py` 选通道、
   `provider/guard.py` 熔断）——那是 Task 4.3/4.4 的范围，本任务只保证 `mock.py` 自身
   与三份契约一致。`selector.py` 在我工作期间仍是 55 字节空壳。
6. **并发环境下的全量运行结果不可完全复现**：Task 4.3 的 agent 与我同一工作树同时写
   源码。我的 48 条用例与 `mock.py` 已单独验证全绿，且 `test_layering.py`（会写源码树
   探针）我只串行跑、未并行。
7. **`mock.py` 的置信度只落在 [0.70, 0.99]**（刻意避开 Task 4.10 的分级边界），
   故 marker 的 `level` 在实际产出里拿不到 `HIGH`（要 ≥0.9 需摘要分片恰好落在那一段）。
   分级函数本身是显式分支且有「level 与自身 confidence 一致」的用例，但
   「`HIGH` 分支在 Mock 的真实产出上出现过」这件事我没有取证。
