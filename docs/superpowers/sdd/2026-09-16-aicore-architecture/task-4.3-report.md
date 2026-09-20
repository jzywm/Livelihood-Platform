# Task 4.3 实现报告：真实 Provider 骨架与通道护栏

- **Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`
- **Python**：`.venv\Scripts\python.exe`（3.14.6）；未执行任何 `pip install`
- **纪律**：未 `git add` / `git commit`；未改工单 §Files 的「不可改」清单（见 §5 的核对）
- **报告口径**：§2 贴六条验收命令的**原始输出**；§4 是「偏离项与没做到的事」——如实写，不含「应该没问题」

---

## 1. 改了 / 建了哪些文件

### 1.1 新建（7 个，全部是本工单 §Files 的 Create 项）

| 文件（相对 worktree 根） | 行数 | 说明 |
|---|---|---|
| `services/aicore/src/aicore/provider/guard.py` | 386 | 超时 / 重试 / 熔断三件套（全通道共用）+ `Settings → GuardConfig` 映射 |
| `services/aicore/src/aicore/provider/_http.py` | 166 | **唯一**的 httpx 客户端构造点 + 请求头 / 响应解码 / 入参校验零件 |
| `services/aicore/src/aicore/provider/deepseek.py` | 296 | `DeepSeekTextProvider`（合规门 `COMPLIANCE_READY = True`） |
| `services/aicore/src/aicore/provider/cloud_vision.py` | 291 | `CloudVisionProvider`（合规门 `False`，协议 M2 前签署） |
| `services/aicore/src/aicore/provider/cloud_ocr.py` | 335 | `CloudOcrProvider`（合规门 `False`）+ 字段值脱敏 |
| `services/aicore/tests/unit/test_provider_guard.py` | 649 | 护栏用例 **31** 条 |
| `services/aicore/tests/unit/test_provider_real.py` | 1070 | 三通道契约 / 护栏 / 合规门用例 **51** 条 |

> 行数为 Python 权威口径（`len(text.splitlines())`，LF 结尾、无 BOM、无异常行分隔符）。
> 三个通道文件原先各是 **1 行空壳**（`"""…骨架。第 4 组实现…"""`），本任务把它们填成实现；
> `deepseek.py` / `cloud_vision.py` / `cloud_ocr.py` 在 `git status` 里因此显示为 `M`（修改），
> 其余四个是新文件（`??`）。

### 1.2 交付接口与工单 §2 / §3 的逐条对位

| 工单要求 | 落点 |
|---|---|
| `GuardConfig`（frozen+slots，6 字段，后两项有默认值） | `guard.py` |
| `StepClock`（`monotonic` + `async sleep`）、`system_clock()` | `guard.py` |
| `CircuitBreaker.__init__(config, *, clock=None)` / `before_call` / `record_success` / `record_failure` / `state_of` | `guard.py` |
| `guarded_call(*, provider, operation, config, breaker, send, clock=None)` | `guard.py` |
| §2.1 的 7 条精确行为 | `guard.py` 模块 docstring 的分类表 + §3 的窗口口径；31 条用例逐条覆盖 |
| `_http.build_client(*, base_url, api_key, timeout_s)` | `_http.py`（签名逐字） |
| 三通道类名 / `name` / `model_version` / `prompt_version` / 构造函数签名 | 三个通道文件 |
| 三通道 `model_meta()` **委托** `ProviderIdentity.as_model_meta()` | 三个通道文件（用例逐键比对） |
| 三通道 `call_count` 属性 | 三个通道文件（口径写进 `deepseek.py` 的 docstring，并被熔断/合规用例正面钉住） |
| `COMPLIANCE_READY` + 构造请求**之前**的合规门 + WARNING + `compliance-missing` | 三个通道文件（云通道 `False`） |
| 响应畸形 → `malformed-response`；`value` ≥15 位连续数字脱敏 | 三通道解析函数 + `cloud_ocr.mask_long_digit_runs` |

---

## 2. 六条验收命令的原始输出

前置：每条命令前都设 `$env:PYTHONUTF8='1'`，`cd D:\progrom\.worktrees\aicore-architecture\services\aicore`。
本轮全部命令都在同一轮串行执行（`tests/structural/test_layering.py` 会往真实源码树写探针，并发不可信）。

### 2.1 新增的两个用例文件

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_guard.py tests/unit/test_provider_real.py -q -p no:cacheprovider
```

```text
........................................................................ [ 87%]
..........                                                               [100%]
```

**注意**：`pyproject.toml` 的 `addopts` 已含 `-q`，再传一个 `-q` 等于 `-qq`，pytest 会**省略成功时的计数行**——
这是命令字面量的效果，不是失败。同一条命令去掉冗余的 `-q` 后：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_guard.py tests/unit/test_provider_real.py -p no:cacheprovider --no-header
```

```text
........................................................................ [ 87%]
..........                                                               [100%]
82 passed in 1.31s
```

（= `test_provider_guard.py` 31 条 + `test_provider_real.py` 51 条；退出码 0。整轮墙钟 1.31s，
其中包含 `test_wait_for_timeout_is_enforced_by_the_real_loop` 故意跑的 0.01s 真超时——
其余退避（1+2+4+8+16s）全部走注入的 `FakeClock`。）

### 2.2 全量套件

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"
```

```text
........................................................................ [  6%]
........................................................................ [ 13%]
........................................................................ [ 20%]
......................................................................ss [ 27%]
sssssssss............................................................... [ 34%]
........................................................................ [ 41%]
................................................................s....... [ 48%]
........................................................................ [ 55%]
........................................................................ [ 62%]
........................................................................ [ 69%]
........................................................................ [ 76%]
........................................................................ [ 83%]
........................................................................ [ 90%]
........................................................................ [ 97%]
...............................                                          [100%]
---- exit: 0 ----
```

同样受 `-qq` 影响没有计数行，故补一条计数可见的等价命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -m "not integration" --no-header -rs
```

```text
1027 passed, 12 skipped, 19 deselected in 23.93s
=========================== short test summary info ===========================
SKIPPED [11] tests\structural\test_source_guards.py:102: provider 包是唯一允许发起外部模型调用的层
SKIPPED [1] tests\unit\test_envelope.py:501: /metrics 尚未落地（后续任务）；端点到岗后本用例自动开始断言
---- exit: 0 ----
```

**与工单预期数字的差异（如实说明，不是失败）**：工单写「必须 880 passed, 8 skipped」，实测
**1027 passed / 12 skipped / 19 deselected，exit 0**。差异来源可逐个指认，且都不是本任务的失败：

1. 工单里的 880 是**写工单时的快照**。此后树里新增了别的任务的用例文件：
   `tests/unit/test_provider_results.py`（Task 4.1）、`tests/unit/test_provider_mock.py`（Task 4.2），
   加上本任务的 82 条 → 自然超过 880；
2. `skipped` 从 8 变 12：`tests/structural/test_source_guards.py` 的规则 5 对 **provider 包下每个 `.py`**
   各参数化一条并整条 `skip`，本任务在 provider 包内新增了 `guard.py` 与 `_http.py`（另三个文件原先是空壳、
   已计入）→ skip 数 +2；另一条新增 skip 来自 `test_envelope.py`（`/metrics` 未落地）。两条 skip 都在
   用例自身的 `skip reason` 里写明原因，不是静默跳过。

**另记一条现场（供控制者判断）**：本任务开工前的基线跑出过 2 个失败——
`tests/structural/test_layering.py::test_contract_goes_red_on_violation[core-independent]` 与
`tests/unit/test_provider_results.py::test_to_jsonable_is_json_serializable_end_to_end`。
本轮全量运行两条都已转绿，**不是本任务修的**（我未改这两个文件），只是同一工作树里其他实现者/控制者
在并行推进，故基线快照与终态不同。

### 2.3 结构性规则 5（`httpx` 模型调用仅在 provider 包内）

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/structural/test_source_guards.py
```

```text
.......................sssssssssss.................................      [100%]
```

计数可见版（去掉冗余 `-q`）：`56 passed, 11 skipped in 0.28s`，退出码 0 —— **规则 5 仍绿**
（11 条 skip 即 provider 包下的 11 个 `.py`）。

### 2.4 ruff

```powershell
.\.venv\Scripts\ruff.exe check --no-cache src/aicore/provider/ tests/unit/test_provider_guard.py tests/unit/test_provider_real.py
```

```text
All checks passed!
```

### 2.5 mypy

```powershell
.\.venv\Scripts\python.exe -m mypy --strict src
```

```text
Success: no issues found in 56 source files
```

### 2.6 import-linter

```powershell
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

```text
---------
Contracts
---------

Analyzed 56 files, 54 dependencies.
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

**那条 warning 是 `.importlinter:72` 预先声明的状态**，不是本任务引入的问题：放行表达式
`aicore.service.** -> aicore.provider.base` 目前匹配不到任何导入（`service` 层尚未 import Protocol），
配置里写明「Task 4 落地真实 Protocol 导入时该警告自动消失」——那属于 4.5/4.6/4.7 的 service 侧接线。
本任务新增的 `provider → core.config`（`guard.py`）与 `provider → provider._http` 均未被判违规
（分层方向合法：`provider → core` 允许，反向才是禁止项 4）。

### 2.7 覆盖率（门禁 ≥80%）

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration" --cov --cov-report=term-missing --no-header
```

提取与门禁相关的行：

```text
src\aicore\provider\_http.py                  32      0   100%
src\aicore\provider\guard.py                 129      1    99%   386
TOTAL                                       1714     25    99%
Required test coverage of 80.0% reached. Total coverage: 98.54%
```

- **总覆盖率 98.54%**（门禁 80% 已达成）；
- **`guard.py` 99%**（129 语句 / 1 未覆盖），
- **`_http.py` 100%**（32 语句 / 0 未覆盖）；
- `guard.py:386` 是 `guarded_call` 末尾那句结构性不可达的 `raise AssertionError("unreachable")`
  ——它存在的唯一目的是满足 mypy strict 的「所有路径都有返回」，**无法也不该**被用例覆盖（这是有意留的 1 行）；
- 三个通道文件照旧不在表内（`pyproject.toml` 的 `coverage.omit` 已含它们，依据 `design.md:284`
  「真实通道骨架允许排除」）——**未改该配置**。

---

## 3. 本任务的关键判据（控制者评审时可直接核这几条）

### 3.1 「熔断时一次请求都没发出」是可断言的

`guarded_call` 的第一行就是 `breaker.before_call(...)`，在 `send()` 之前；用例把 handler 计数挂在
`httpx.MockTransport` 上，正面断言：

- `test_breaker_gate_runs_before_send`：连续 5 次失败打开熔断 → 第 6 次 `send` 计数**不增加**；
- `test_channel_circuit_open_is_4003_and_stops_calling`（×3 通道）：打满失败后第 6 次 handler 计数**不变**。

### 3.2 「不发出真实计费调用」是三层证据，不是一个说法

1. `httpx.MockTransport` 拦下全部请求（每条用例都走它，无一条走真实网络）；
2. autouse 夹具 `_fake_endpoints` 把三个通道的 `base_url` 常量指到 RFC 2606 的 `.invalid` 保留域
   （DNS 永远解析不出来），云通道密钥指到假值；
3. autouse 夹具 `socket_guard` 把 `socket.socket.connect` 换成探针，**对外建连一律抛异常**，
   并在 teardown 断言「本次用例没有任何对外建连」。

### 3.3 socket 探针的环回例外（实测结论，附调用栈）

第一版探针把**所有** `connect` 都拦住，结果每条 async 用例都在**事件循环创建阶段**炸掉。实测打印调用栈后确认成因：

```text
asyncio/runners.py:60 __enter__ → events.new_event_loop() → windows_events.py:316 →
proactor_events.py:785 _make_self_pipe → socket.py:629 _fallback_socketpair
→ csock.connect((127.0.0.1, <临时端口>))
```

即 Windows 上 `asyncio.ProactorEventLoop` 用 `socket.socketpair()` 造自管道，而 Windows 没有原生
socketpair，走 fallback 实现**真的 connect 到环回地址**。故探针**只放行环回**（记录在案、不阻断），
**对外目标一律拦住**；判别力自证 `test_socket_guard_has_discriminating_power` 两向都测：
`192.0.2.1`（RFC 5737 文档网段，不可路由）必须被拦，环回必须被放行且被记录。
拦构造函数（`socket.socket`）而非 `connect` 的做法，无法区分这两种情况，故不采用。

### 3.4 合规门的负向证据

`test_cloud_channel_compliance_gate_blocks_the_call`（×`cloud_vision` / `cloud_ocr`）同时断言四件事：

- `box.count == 0`（handler **一次都没被调用**，请求根本没发出）；
- `box.build_calls == 0`（连 `_http.build_client` 都没进 → 名副其实的「在构造请求之前检查」）；
- `ProviderChannelFailureError.reason == "compliance-missing"` 且 `code == 4003`；
- WARNING 日志存在（`spec.md:95-96` 要求「拒绝调用**并告警**」，不是静默失败）。

`deepseek` 侧：`COMPLIANCE_READY is True` 且正常调用时 handler 计数 == 1（正例，避免「全拦住」也算绿）。
云通道的「请求构造 / 响应解析 / 脱敏」用例通过**临时** `monkeypatch` 打开 `COMPLIANCE_READY`
才跑到（那个开关就是本任务存在的意义：契约与护栏可测，而不是可用）。

### 3.5 失败分类与「不吞 bug」

`guard.py` 的分类表逐条有用例：超时（`5002`）、传输错误（`4003 transport-error`）、5xx（可重试）、
429（可重试）、4xx 非 429（**不重试**，`send` 只被调用 1 次，参数化 400/401/403/404/422）、
`send` 抛的 `ProviderError`（记失败、不重试）、`ValueError`/`TypeError`/`KeyError`（**原样上抛**、
不重试、且**不进熔断窗口**——bug 不是通道的表现）。

---

## 4. 偏离项与「没做到的事」

### 4.1 与工单字面的偏离（都是有意的，逐条给理由）

| # | 偏离 | 理由 |
|---|---|---|
| D1 | `guard.py` 增了一个未在 §2 列出的函数 `guard_config_from(settings)` | 四项护栏参数要从 `Settings` 映射到 `GuardConfig`；写在 guard 里只有一处口径，写三份会漂移。签名未改任何已列接口 |
| D2 | `_http.py` 除 `build_client` 外增了 `auth_headers` / `decode_json` / `malformed_response` / `require_positive_timeout`（`build_client` 签名**逐字未改**） | 工单把 `_http.py` 定义为「客户端工厂 + 请求构造」；这四个是请求头 / 响应解码 / 入参校验的共用零件，放通道里会三份重复 |
| D3 | 调用侧 `timeout_s` 与 `ai_call_timeout_s` 取 **min** 后作为每次尝试的预算 | 工单未规定二者关系。两者都是上限：任务级（Task 4.6「声明自身超时」）不该突破通道护栏，护栏也不该拉长任务声明的更短预算。已用 `test_effective_timeout_is_the_smaller_of_the_two` 正面钉住（观测点是传给客户端工厂的 `timeout_s`） |
| D4 | `send` 抛 `ProviderError` 时：**记失败但不重试** | 工单只写了 httpx 系的判据。畸形响应已属「等到了失败」，重发拿不回不同结果，却把一次计费放大成六次；同时它必须记进熔断窗口（连续 5 次畸形 = 通道契约坏了）。用例 `test_provider_error_from_send_is_recorded_but_not_retried` |
| D5 | 熔断**中途打开**不打断本次调用已在进行的重试 | 工单未规定。中途打断会让「重试耗尽抛最后一次的异常类型」变得不可预测；熔断效力体现在**后续调用**的 `before_call`（那才是可断言的部分）。已写进 `guarded_call` docstring |
| D6 | 重试耗尽时挂因果链（`raise ... from 最后一次的底层异常`） | 不挂的话调用点只看得到 `4003/5002` 与 `reason`，看不到「哪个 URL 的 503」。`reason` 仍是唯一判别依据；httpx 异常消息只含方法与 URL（密钥只进请求头），故因果链不引入泄漏（用例正面断言 `__cause__` 里也没有假密钥） |
| D7 | 三个通道各自新增了入参轻校验（`timeout_s <= 0`、空 `image_key`、空 `labels`、空 `doc_type` → `ValueError`） | 与 §2.1.3「编程错误 MUST NOT 被吞成通道失败」同向：放行会让「调用点算错超时」伪装成 `5002`、「拼错 image_key」伪装成一次无意义的计费调用 |
| D8 | `WINDOW_SIZE = 10`、`MIN_SAMPLES = 5` 的窗口长度由我定 | 权威文档只给了触发条件（L316「错误率 >50% 连续触发 → 熔断」）没给窗口大小。取 `MIN_SAMPLES` 的 2 倍并在 docstring 写明理由（下界够小：连续 5 次失败即 100% > 50%；上界够小：否则退化成「历史平均」，失去「连续触发」语义） |
| D9 | 用例侧用 `monkeypatch.setattr(_http, "build_client", ...)` 注入 `MockTransport` | 工单 §3.1/§3.2 把构造函数与 `build_client` 的签名钉死为**不接受 `transport`**，注入传输层只能替换工厂。为避免「替身好用、真工厂坏了」的假绿，另有用例直接断言**真实** `build_client` 的头与超时 |

### 4.2 没做到的事（如实列，评审请按此核查）

1. **`ProviderIdentity.thresholds` 三个通道都是空 dict**。`er.md` §6.1 的 `model_meta` 要求
   `thresholds（high/medium）`，但阈值的所有者是 Task 4.10（「阈值可配并留痕」），
   `Settings` 里**没有**对应字段；在 provider 里硬编码 0.9/0.7 会与 4.10 的可配阈值形成两份会漂移的口径
   （`results.py` 的 `ProviderIdentity` 注释已明确「默认空字典是合法的」）。→ **4.10 落地后需回填**。
2. **`ProviderResult.raw` 三个通道一律不填**。`results.py` 对该字段的硬约束是「MUST NOT 含未脱敏的证件值」，
   而 provider 是最靠近外部通道的一层、**没有能力判断**返回内容是否已脱敏；OCR 的原始响应里就是未脱敏的证件号，
   落库即违规。排障路径改为「按 taskId 对齐通道侧日志」——**本层没有记 requestId**，这条链路目前是空的。
3. **没有连接复用 / 连接池**。骨架阶段一次调用一个 `httpx.AsyncClient`（每次调用都要能带不同的
   `timeout_s`，而超时只能在构造客户端时绑定）。云通道在合规门打开前不可用，连接池要等真实接入与
   容量标定（《高并发》§4.4 的 ★ 项）才有基准可调。**未做压测**，故「每调用一客户端」的性能代价**未测**。
4. **L316 的另一半判据「慢调用 >阈值 → 熔断」未实现**。`Settings` 的四项护栏里没有慢调用阈值字段
   （控制者定档的就是错误率那一半），工单 §2.1.7 也只要求错误率口径。
5. **云通道的密钥没有出处**：`cloud_vision.API_KEY` / `cloud_ocr.API_KEY` 是模块级常量、默认空串。
   `core/config.py` 的 `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 明确标注云通道「尚未声明密钥字段」，
   新增字段属于假造接口契约（且要连带改 `.env.example` 与字段表用例），**超出本任务可改范围**——
   故**云通道即使打开合规门也拿不到真密钥**，真实接入时必须按 config.py 上方注释的三处同步登记。
6. **云通道的 base_url 与接口路径是占位值**：`https://cloud-vision.vendor.invalid` /
   `https://cloud-ocr.vendor.invalid`（RFC 2606，不可能解析）与 `/vision/markers`、`/ocr/recognize`。
   候选厂商未定（`产品设计文档.md:1832`「通义VL/GLM-4V 先小样测评；备选 DeepSeek-VL 私有化」），
   故**请求体键名（`image_key`/`labels`/`doc_type`）与鉴权头形式（`Authorization: Bearer`）都是自定口径**，
   **未与任何真实厂商 API 校验过**——这是「不发出真实计费调用」的必然代价，也是本任务最大的未验证面。
   DeepSeek 的 `https://api.deepseek.com` + `/chat/completions` + `model`/`messages` 形态按公开 API 口径写，
   但同样**未做真实调用验证**。
7. **三通道的真实端到端行为未验证**（无真实密钥、无真实通道、M2 前协议未签）；所有验证都在
   `MockTransport` 上完成。云通道在合规门关闭时**不可用**——这是设计要的结果，不是缺陷。
8. **熔断状态是每进程内存态**，多实例各自计数；跨实例全局熔断归网关侧 Resilience4j（config.py 的字段注释
   已写明这层分工）。**未做多进程一致性验证**（也不需要，口径如此）。
9. **`call_count` 的语义需要 4.9 复核**：我实现为「通道方法被调用次数（含被合规门 / 熔断挡下的那次）」，
   并在用例里正面断言（`test_channel_circuit_open_...` 与合规门用例）。Task 4.9 若要求「真实外发次数」，
   需要改口径——那会与 mock 通道的口径对齐问题一并出现（`mock.py` 由 4.2 拥有，我未碰、也未读其 `call_count` 语义）。
10. **未跑集成用例**（`-m "not integration"`，需真实 MySQL/Redis）；**未跑压测**；**未验证覆盖率的并发场景**。
11. `_http.build_client` 的 100% 覆盖率来自「构造 + 断言头/超时/repr」，**没有**经过真实 TLS 握手与
    真实代理环境（如企业代理、证书链）——按裁定不发真实调用，这块无法在本任务覆盖。
12. 沙箱事实（非本任务问题，仅记录）：`services/aicore/` 下有 32 个 ACL 锁死的 `pytest-cache-files-*` /
    `probe-*` 残留目录，按指示**未清理**。

### 4.3 交接提醒（给 Task 4.4 / 4.6 / 4.9 / 4.10 / 4.11）

- `provider/selector.py`（4.4）：三个通道的构造函数都是 `(config: Settings, *, breaker=None, clock=None)`，
  selector 只需按 `settings.provider` 的值构造；`deepseek` 的密钥来自 `settings.deepseek_api_key`，
  云通道的密钥注入点在各文件的 `API_KEY` 常量（见 §4.2 第 5 条）。
- `service/task/registry.py`（4.6）与处理器：每次调用都要传 `timeout_s`（任务级超时），最终生效值是
  `min(任务声明, settings.ai_call_timeout_s)`。
- 4.10 阈值分级：`ProviderResult.confidence` 与 `markers[i]["confidence"]` 在通道未给时是 `None`
  （**MUST NOT** 当 0 处理）；`identity.thresholds` 目前是空 dict（见 §4.2 第 1 条）。
- 4.11 降级可观测：`CircuitBreaker.state_of(provider, operation)` 是「开 / 半开 / 闭」的现成查询口，
  维度是 `(provider, operation)`；`4003` 与 `5002` 由 `guarded_call` 严格分流（4xx/5xx/传输 → `4003`；
  超时 → `5002`）。
- 全量套件的期望数字需要控制者更新（880 → 1027），并注意 `provider/` 下每新增一个 `.py` 会让
  规则 5 的 skip 数 +1（那是用例设计，不是缺陷）。
