# 第 4 组 P 阶段 · 独立评审结论（reviewer-authored，与实现者/控制者无关）

> 评审者：独立评审会话。工作树 `D:\progrom\.worktrees\aicore-architecture`，HEAD `204801fe26b49485d72b188acc254f724ba19c9a`。
> 所有数字均为**本评审自己复跑**所得，未引用控制者或实现者的任何数字。
> 评审结束状态：`git status --porcelain` 与评审开始时**逐字节一致**（9 个 M + 11 个 ??，见 §3.0 自证）。

---

## 1. 结论

### **有条件通过**

六条门禁全部真实复现通过（§2），假绿搜索**抓到 3 处真实假绿 + 2 处口径性假绿**（§3），
其中 1 处是可被 Mutation Testing 直接证伪的**判别力伪造**（§3.2）。
数值/口径抽查发现 **1 处与权威文档正面冲突的裁定**（§4.1）与 **2 处出处行号失实**（§4.2）。

### 必须在收尾前修的（3 条）

| # | 条目 | 位置 | 为什么必须修 |
|---|---|---|---|
| **B1** | 熔断归 `4003` 与权威文档**正面冲突** | `provider/errors.py:12,80-85`、`provider/guard.py:263`；测试把它**钉死**在 `test_provider_guard.py:185`、`test_provider_real.py:653` | 唯一权威码表 `services/_common/openapi.yaml:208` 逐字 `- 5002 # 依赖超时 / 熔断`；`:134` 逐字 `依赖超时 / 熔断（code=5002）`；**本仓自己的** `core/errors.py:33` / `:252` / `:395-398` 也把熔断归 5002「依赖超时或熔断」。评审包 §4 把 `_common/openapi.yaml:132-146` 列为该裁定的依据，但该依据**恰恰写着反面**。现在改口径只需改 2 个常量 + 3 条断言的期望值；等 4.9/4.11/5.7 落库与前端契约都按 4003 固化后再改，代价是一个数据迁移。 |
| **B2** | 签名相等断言的自证**对真实断言零判别力** | `tests/unit/test_provider_base_contract.py:183-229`（自证）、`:85`（真实断言） | 实测：把 `:85` 弱化成 `len(actual.parameters) == len(expected.parameters)`，同时在真实通道里制造**真签名漂移**（删掉 `DeepSeekTextProvider.complete` 的 `*`）→ **全量 1088 passed**，且那条自称"判别力自证"的用例**照样 passed**。自证只测了合成类上的 `!=`，从未让真实断言跑过。 |
| **B3** | Mock 的「零 socket 建连」取证面**不含它要保护的源码** | `tests/unit/test_provider_mock.py:111-187`（守卫）、`:174-187`（autouse） | 实测：往 `src/aicore/provider/mock.py` 里塞一个真实 `socket.connect(("192.0.2.1", 9))` 后，`test_provider_mock.py`(**48 passed**)、`test_provider_real.py`(**51 passed**)、`test_provider_selector.py`(**35 passed**) 全绿。守卫的 `_PROJECT_FRAME_TOKENS` 第一项是 `str(SRC_DIR)`，但判据取"栈里第一个命中者"，而测试文件自己的帧永远先命中 → **只要不是测试自己发起，一律放行**（见 §3.1 的实测栈）。 |

### 建议同批修（不阻塞，但收尾前顺手做掉最省事）

- **C1** 覆盖率口径：`98.60%` 是**排除掉本组三个真实通道文件**之后算出来的（`pyproject.toml:118` 的 `omit`），
  而这三个文件里有 17 行**可达未测**代码（含 `confidence=true` 这类"最容易被漏"的畸形响应分支）。不改 omit 的话，
  建议在交付说明里明确标注"98.60% 不含三个真实通道"。
- **C2** `test_none_slots_do_not_fall_back_to_mock` 的自证（`test_provider_selector.py:835-858`）**不经过被测选择器**，
  是"张冠李戴式自证"，判别力弱于它自称的程度。
- **C3** 出处行号失实 2 处（`deepseek.py:9` 与 `:11`），见 §4.2。

---

## 2. 门禁复跑原始输出（六条，全部本评审自己跑）

复跑口径：`$env:PYTHONUTF8='1'`，`workdir = services/aicore`，pytest 一律带 `-p no:cacheprovider -o addopts=""`。

### 2.1 `pytest -m "not integration"`

```
============== 1088 passed, 12 skipped, 19 deselected in 23.64s ===============
EXIT1=0
```

### 2.2 `pytest -m "integration"`

```
collected 1119 items / 1100 deselected / 19 selected
tests\repository\test_apply_ddl_mysql.py .....                           [ 26%]
tests\repository\test_migration.py .....                                 [ 52%]
tests\repository\test_repos.py .....                                     [ 73%]
tests\repository\test_session.py ..                                      [ 84%]
tests\repository\test_sharding.py ...                                    [100%]
==================== 19 passed, 1100 deselected in 20.09s =====================
EXIT2=0
```

### 2.3 `pytest -m "not integration" --cov --cov-report=term-missing`

```
Required test coverage of 80.0% reached. Total coverage: 98.60%
============== 1088 passed, 12 skipped, 19 deselected in 22.87s ===============
EXIT3=0
```

明细（本组相关行，逐字摘自输出；`deepseek.py` / `cloud_vision.py` / `cloud_ocr.py` **不在表内**，原因见 §3.4）：

```
src\aicore\provider\_http.py                  32      0   100%
src\aicore\provider\base.py                   26      0   100%
src\aicore\provider\errors.py                 21      0   100%
src\aicore\provider\guard.py                 129      1    99%   386
src\aicore\provider\mock.py                  154      4    97%   296-299, 556
src\aicore\provider\results.py                47      1    98%   187
src\aicore\provider\selector.py               68      0   100%
TOTAL                                       1783     25    99%
```

### 2.4 `ruff check --no-cache src tests`

```
All checks passed!
EXIT4=0
```

### 2.5 `mypy --strict src`

```
Success: no issues found in 56 source files
EXIT5=0
```

### 2.6 `lint-imports --config .importlinter`

```
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.

--------
Warnings
--------

service 层只可与 provider.base 交互，不得依赖具体通道实现
----------------------------------------

- No matches for ignored import aicore.service.** -> aicore.provider.base.
EXIT6=0
```

**与评审包 §6 的差异**：六项**逐项一致**（1088/12/19、19、98.60%、ruff 全绿、mypy 56 files、4 kept 0 broken）。
§6 的计数是用正确写法取到的（本评审不叠加 `-q`，汇总行正常打印）。

### 2.7 评审包 §3 的文件行数与实测不符（非功能性，但请更正包本身）

`Get-Content .Count` 与 Python `splitlines()` 两种口径**同值**，与包内声明值全部不符（包内值一律偏小 1.5~1.8 倍）：

| 文件 | 包内声明 | 实测行数 | 实测字节 |
|---|---|---|---|
| `provider/_http.py` | 97 | **166** | 8271 |
| `provider/errors.py` | 50 | **85** | 4135 |
| `provider/guard.py` | 248 | **386** | 19355 |
| `provider/results.py` | 119 | **205** | 10320 |
| `tests/.../test_provider_base_contract.py` | 139 | **229** | 11375 |
| `tests/.../test_provider_guard.py` | 464 | **649** | 26523 |
| `tests/.../test_provider_mock.py` | 726 | **1008** | 47209 |
| `tests/.../test_provider_real.py` | 762 | **1070** | 45620 |
| `tests/.../test_provider_results.py` | 176 | **282** | 13739 |
| `tests/.../test_provider_selector.py` | 562 | **883** | 42780 |

复算方式：
`.\.venv\Scripts\python.exe -c "from pathlib import Path; print(len(Path('...').read_bytes().splitlines()))"`。
另：`git status --porcelain` 多出一个包内未列的未跟踪文件 **`.sdd-tools.py`**（106 行，SDD 工具脚本），
不属于本组交付但会随工作区一起提交，请确认是否有意提交。

---

## 3. 假绿搜索

### 3.0 自证：评审未留下任何改动

用 SHA256 逐文件留证（变异前值 = 变异并还原后的值）：

| 文件 | SHA256（评审前 = 评审后） |
|---|---|
| `src/aicore/provider/mock.py` | `D601ECFC4CFF5E84FA4811E4AFCD98D813C2B965C07B4005B206493B5E40E55D` |
| `src/aicore/provider/guard.py` | `CDC8E3F602E54410A311898633F77538D2BACE030F945109AEEBEB5CEC3830CB` |
| `src/aicore/provider/selector.py` | `1464CED5F69E4C808BE67885F91CD37E791BE352DA7CCC020C3284355A5624A8` |
| `src/aicore/provider/deepseek.py` | `914A05E70E5525C718A0E80872CD469A8F34A489ECB35126E44E12B0185D13DA` |
| `tests/unit/test_provider_mock.py` | `0910F6D6DCCFCF5E70D92D17B9B9B7F6D40C444D48C316B702433A66724B132F` |
| `tests/unit/test_provider_base_contract.py` | `562ECDF6B797AD588928B1CC85729BC2951E77792634FFBD16042567A7AB99C5` |

`git status --porcelain` 在评审前后逐项相同（9 个 ` M` + 11 个 `??`，无新增/无删除）。
所有临时脚本与变异备份均已删除，`Get-ChildItem -Recurse -Include '*.g4bak','test_zz_review_probe.py','g4review_cov.ini'` 返回空。

### 3.1 【假绿 · 确认】Mock「零 socket 建连」守卫的取证面不含源码

**变异方法**：在真实源码 `src/aicore/provider/mock.py` 顶部插入

```python
def _mutation_probe_connect() -> None:
    import socket as _socket
    _sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        _sock.connect(("192.0.2.1", 9))   # RFC 5737 文档专用网段
    finally:
        _sock.close()
```

并由**新增的**探针用例（`tests/unit/test_zz_review_probe.py`，评审后已删）调用它。

**变更后的真实输出**：

```
=== M1: NEW violation in real source code (mock.py) ===
tests\unit\test_zz_review_probe.py .                                     [100%]
============================= 1 passed in 21.07s ==============================
M1_EXIT=0
```

**关键对照**（同一次变异状态下）：

```
tests/unit/test_provider_real.py    ....................................... [ 76%]  → 51 passed in 0.82s
tests/unit/test_provider_selector.py ................................... [100%]     → 35 passed in 0.90s
```

**结论**：`test_provider_mock.py` 的守卫**只抓"测试代码自己发起的 connect"**，对 `src/aicore` 下任何模块发起的 connect 一律放行。

**根因（文件行号 + 实测栈）**：`_attribute_connect`（`test_provider_mock.py:134-142`）取「栈里第一个命中者」，而候选帧顺序是
`stack[2]` 起，`_PROJECT_FRAME_TOKENS = (str(SRC_DIR), str(Path(__file__).parent))`（`:76`）。
守卫自己实测到的两条栈（`:125-127`）也印证了这点：

```
直接调用：0:_attribute_connect | 1:_spy | 2:test_provider_mock.py:<用例> | 3:pytest…
self-pipe：0:_attribute_connect | 1:_spy | 2:socket.py:_fallback_socketpair | 3:proactor_events.py:_make_self_pipe
```

当**源码**发起 connect 时，栈是 `0:_attribute_connect | 1:_spy | 2:mock.py:_mutation_probe_connect | 3:…`——
`mock.py` 在第 2 帧就命中 `str(SRC_DIR)`，**理应判违规**。实测却未判违规，说明该帧未被 `inspect.stack()` 呈现（子进程/异步栈截断），
即"可归因"这一保证在真实源码路径上**不成立**。该用例 docstring 第 3-5 行与 `:25-26` 声称「本项目自己的代码全程零 socket 建连
（见 `_forbid_socket` 与它的判别力自证用例），故『断网可跑』这件事在 CI 里有可核证据」——**这句话的取证面被高估**。

**它自己会红吗？会，但只在一个方向上**（见 3.2 的 M2a/M2b），这也是为什么这条假绿能长期存活：
双向变异都只在"测试代码帧"这一侧被触发。

**是否还原**：已还原，`mock.py` SHA256 回到 `D601ECFC…E55D`（与变异前逐字节相同），探针文件已删。

**附带发现（低置信，未复现失败）**：`test_provider_real.py:237-254` 的 `_SocketGuard` **会真拦**对外建连
（`if _is_loopback(address): … return` / `raise _RealSocketBlockedError`），与它 `:11-12` 的 docstring
「把 `socket.socket.connect` 换成**会抛异常的桩**」相符；同名的 `test_provider_selector.py:_SocketGuard:125-131` 亦然。
而 `test_provider_mock.py` 的同名注释 `:178` 写「建连一律**透传给真实实现**」——**三处同名结构口径不同且都与注释相符**，
但"守卫"这个词在三个文件里指两种不同强度，建议改名消歧（`_SocketBlocker` vs `_SocketRecorder`）。

### 3.2 【假绿 · 确认，最严重】签名相等断言的自证对真实断言零判别力

交付物中的两处：

- 真实断言：`test_provider_base_contract.py:85` `assert actual == expected, (…)`
- 自称的"判别力自证"：同文件 `:183-229` `test_signature_equality_is_discriminating`

**变异 1（只弱化断言，不改被测代码）**：

```
m3_signature: pre  sha256=562ecdf6b797ad588928b1cc85729bc2951e77792634ffbd16042567a7ab99c5
m3_signature: post sha256=9f75fdb65062735239fd952e71d7ea44e68e83134f3d2a065989a4887f8b654d
============================= 26 passed in 0.11s ==============================
```

把 `assert actual == expected` 换成 `assert len(actual.parameters) == len(expected.parameters)`，
**26 条用例全绿**。这本身只是"没抓到"，还需要证明它**抓不到真问题**。

**变异 2（弱化断言 + 真实签名漂移，联合变异）**：

```
m3b_weakened_plus_kwonly_drop: pre  sha256=562ecdf6…  post sha256=9f75fdb6…
m3c_kwonly_drop:               pre  sha256=914a05e7…  post sha256=da9179a8…
---- FULL non-integration suite under (weakened assert + real drift) ----
============== 1088 passed, 12 skipped, 19 deselected in 20.17s ===============
---- and the discriminating-power self-proof test specifically ----
============================== 1 passed in 0.08s ==============================
```

漂移内容：把 `deepseek.py:134-140` 的 `async def complete(self, *, prompt, payload: Mapping[str, Any], timeout_s)`
改成 `async def complete(self, prompt, payload: Mapping[str, Any], timeout_s)`——**丢掉 `*`**，
即 `base.py` 文档里点名的那种"契约静默分叉"（调用方全用关键字实参，实现退化成位置可传）。

**结论**：`assert len(parameters) == len(parameters)`（参数个数相同、种类不同）**能过**，
而自称"证明判据真的会因不一致而变红"的那条自证用例**照样 passed**——它的对照组
（`:189-214` 的 `_DifferentName` / `_DifferentKind` / `_MissingParameter` / `_ExtraParameter`）只在**合成类**上测 `!=`，
**从未让 `:85` 那条真实断言参与**，因此它证明的是"`Signature.__eq__` 不是恒真函数"，不是"这条断言有判别力"。

**这不是必然假绿，而是"自证写错了对象"**：`test_signature_equality_is_discriminating` 与被保护的断言**没有任何数据流关系**，
删掉它、弱化它、或让它测别的东西，`:85` 的退化都不会被发现。

**附**：`:149-169` 的 `test_matrix_covers_every_channel_file` 是有效守卫（矩阵与显式集合双向比对），
它保护的是"矩阵完整"，**不保护"断言强度"**——两者缺一不可，现在缺的是后者。

**是否还原**：两个文件均按字节还原（`deepseek.py` → `914A05E7…`，`test_provider_base_contract.py` → `562ECDF6…`）。

**正面对照（同一手法证明哪些断言是真的有判别力）**：

```
###### M6a: drop keyword-only '*' from DeepSeekTextProvider.complete (REAL drift) ######
E       AssertionError: DeepSeekTextProvider.complete 与 TextProvider 的签名不一致。
FAILED tests/unit/test_provider_base_contract.py::test_implementation_signature_equals_protocol_signature[DeepSeekTextProvider.complete]
---- M6a on the FULL non-integration suite ----
========= 1 failed, 1087 passed, 12 skipped, 19 deselected in 20.29s ==========
```

即：**原样交付的判据确实有判别力**（唯一失败点就是它），`test_signature_equality_is_discriminating` 属于"多余的装饰性自证"。
这条结论对交付物是**加分**（断言本身没问题），对评审包 §8 的第三项自述是**修正**（自证并未覆盖它声称的那条退化路径）。

### 3.3 【假绿 · 确认】`test_none_slots_do_not_fall_back_to_mock` 的自证不经过被测对象

`test_provider_selector.py:835-858`：

```python
    def _fallback(_config: Settings) -> Providers:      # 用例内自建函数，非被测选择器
        return Providers(text=MockTextProvider(), …)
    fallback = _fallback(_settings(provider="cloud_ocr"))
    assert fallback.text is not None, "回落版实现必须给出非 None 的 text …"
    assert select_providers(_settings(provider="cloud_ocr")).text is None
```

`:857` 的"两侧对照"是**自证的 `_fallback`** 与**真实 `select_providers`** 的对照，
而 `_fallback` 这个名字从未出现在 `selector.py` 的任何代码路径上——**把 `_fallback` 写成永远返回 3 个 mock，
或把它删掉，本用例的判别力一个字都不变**。它证明的是"存在一种会回落的实现"，不是"被测实现在回落时会红"。

**真正的判别力来自 `:290-300`**（用实现的 `_SELECTABLE_SLOTS` 表驱动）与 `:304-309`
（对选中槽位断言 `model_meta()["channel"]`）——这两条是真的有判别力，**但它们是"按实现自报的表"在断言**：
`:290` `expected_selected = set(selector_module._SELECTABLE_SLOTS[provider])` 与 `:389` 同形，
即"选中的槽位"这一侧**仍以实现自己的表为准**。`:335-341` 补了"表与 `Settings.provider` 字面量恰好互相覆盖"，
`:345` 补了单向包含，**这层防护是有效的**（见 3.5 的 M5 实证），故本条按"自证写法问题"而非"契约漏洞"登记。

### 3.4 【假绿 · 口径性，确认】98.60% 覆盖率**排除**了本组三个真实通道文件

`services/aicore/pyproject.toml:116-118`（`git blame` 指向 `37aa77b` 骨架提交，非本组引入）：

```toml
[tool.coverage.run]
source = ["src/aicore"]
omit = ["src/aicore/main.py", "src/aicore/provider/deepseek.py", "src/aicore/provider/cloud_vision.py", "src/aicore/provider/cloud_ocr.py"]
```

三个被 omit 的文件**恰好是 Task 4.3 的三项主交付物**。用同一套用例、去掉 omit 后实测（临时 rcfile，已删）：

```
src\aicore\provider\cloud_ocr.py             106      7    93%   265, 276, 279, 283, 289, 305-306
src\aicore\provider\cloud_vision.py           99      7    93%   225, 237, 240, 244, 249, 264-265
src\aicore\provider\deepseek.py               86      7    92%   245, 251, 254, 257, 268, 290-296
TOTAL                                       2109     46    98%      ← 含三通道
TOTAL                                       1783     25    99%      ← 交付口径（含 omit）
```

**这是真实的假绿形态吗？部分是为真、部分是口径问题，如实分开讲**：

1. **它们是被测到的**——93%/93%/92% 说明 `test_provider_real.py` 的 51 条用例确实覆盖了三个通道，
   不存在"没测却报 100%"。**这一半是好的**，评审包 §6 的 98.60% 本身没造假。
2. **但 98.60% 这个数字让读者以为"全仓 98.60%"**，而它实际是"排除 291 个语句（占 2109 的 13.8%）之后的数字"。
   更关键的是：`main.py`（未接线，§5-6）与三个通道一起被 omit，
   **本服务"HTTP 出入"的那一段正好整体落在覆盖率盲区里**。
3. **omit 掩盖了 17 行可达未测代码**，其中两类是有真实风险的：

   | 位置 | 内容 | 为什么值得测 |
   |---|---|---|
   | `cloud_ocr.py:275-276, 279, 283, 289` | `_parse_fields` 的 4 条畸形响应分支：`payload` 不是对象 / `fields` 缺失或不是数组 / 数组元素不是对象 / `value` 不是字符串 | 对端一个 HTML 错误页或 `{"fields": "x"}` 就会走到这里。`:714` 的 `deepseek` 畸形用例只覆盖了"缺 content"一种形态 |
   | `cloud_ocr.py:305-306` | `_optional_confidence` 的 **`bool` 显式排除**分支 | `json true` → Python `bool` → 不排除就被 `float()` 成 `1.0`，于是"通道给了非数值"被静默变成"置信度 100%"。**`deepseek` 有专门用例（`test_confidence_with_wrong_type_is_malformed:702-717`），云 OCR/云视觉没有**——同一个契约在两个通道上只有一半证据 |
   | `cloud_vision.py:264-265` | 同一处 `_optional_confidence` | 同上 |

   复现方式：`--cov-report=term-missing` 配合去掉 omit 的 rcfile，或直接读上述行号。

**建议**：把 `provider/*.py` 从 omit 里移除（当前 93%/93%/92% 远高于 80% 门禁，移除不会让门禁红），
或至少把 `main.py` 保留在 omit 的同时在交付说明中写明"覆盖率不含 provider 真实通道与 main.py"。

### 3.5 【正面结论 · 变异证明判据是真的】M4 / M5

**M4 — 熔断阈值严格大于（`guard.py:299`）**

变异：`if self._failure_ratio(window) > self._config.error_ratio:` → `>=`

```
E       AssertionError: 5/10 = 50% 恰好等于阈值，MUST NOT 熔断（判据是严格大于）
tests\unit\test_provider_guard.py:492: AssertionError
FAILED tests/unit/test_provider_guard.py::test_threshold_is_strictly_greater_than_the_error_ratio
======================== 1 failed, 30 passed in 0.32s =========================
```

**判定：退避序列断言与熔断窗口断言是真的在验它声称验的东西。**
`clock.sleeps == EXPECTED_BACKOFF`（`test_provider_guard.py:47,234`）的期望值是**写死的常量**（不是现算），
`_open_the_circuit` 用 `max_retries=0` 使"一次调用 = 一条样本"，算术可读；
`test_only_one_probe_is_let_through:556-569` 直接调 `before_call` 两次，抓的是"半开放行一次"这件事本身。

**M5 — selector 的 AST 业务标识符扫描（`test_provider_selector.py:436-467`）**

变异：在 `selector.py` 插入 `_BUSINESS_BYPASS = "account_id"`

```
E       AssertionError: selector.py 出现了业务参数标识符 ['account_id']：选择 MUST 只读 config
tests\unit\test_provider_selector.py:467: AssertionError
FAILED tests/unit/test_provider_selector.py::test_selector_source_has_no_business_identifiers
======================== 1 failed, 34 passed in 1.02s =========================
```

**判定：签名参数名集合断言（`:423-433`）与 AST 扫描都真有判别力**，且 `:439-447` 的 docstring
**主动声明了 AST 扫描是弱断言**（改名 `aid` 可绕过、动态取属性扫不到）并指出真正的保证是签名断言——这个自我限定的写法是本组文档质量最好的一处。

### 3.6 【假绿 · 判别力双向自证】M2a / M2b 对 `_attribute_connect`

| 变异 | 变更后真实输出 | 判定 |
|---|---|---|
| **M2a** `_attribute_connect` → `return True, ("mutation-frame",)` | `2 failed, 46 passed, 42 errors`（`test_socket_guard_has_discriminating_power` 与 `test_socket_guard_does_not_flag_the_event_loop_self_pipe` 均 ERROR） | 归因逻辑**真在跑**，async 用例确实依赖它 |
| **M2b** `_attribute_connect` → `return False, ()`（守卫退化成空操作） | `1 failed, 47 passed`，唯一失败者是 `test_socket_guard_has_discriminating_power` | 守卫被架空时**有且仅有自证用例会红** |

**这条要连着读**：M2b 说明"守卫被整体架空"能被抓到（好），
但 M1 说明"守卫只保护测试文件、不保护源码"这件事**没有任何用例能抓到**（坏）。
两者合起来的准确表述是：**这套守卫验证的是"测试自己没偷偷建连"，不是"项目代码没建连"**。

### 3.7 覆盖率数字里"被测到但断言为恒真"的代码

按评审包 §8 第二项的同类形态，逐条查了 `errors.py` / `base.py` / `_http.py`（三者均 100% 行覆盖）：

| 文件 | 行覆盖 | 断言证据 | 判定 |
|---|---|---|---|
| `provider/base.py` | 100%（26 语句） | 26 条 `inspect.signature` 相等 + 协程性 + 类属性类型 + matrix 完整性（§3.2 已证有判别力） | **不是假绿**，§8 自述属实 |
| `provider/errors.py` | 100%（21 语句） | `tests/unit/` 下**没有任何用例直接构造 `ProviderError`**；三个子类只被 `pytest.raises` 按类型捕获 | **部分假绿**：类体（`__init__` 三行 + MRO 调用）靠被抛出来"覆盖"，**没有任何断言检验它的对外契约**。本评审实探（§4.3）发现 `str(ProviderCircuitOpenError("p","op","circuit-open"))` == `'大模型或视觉 API 失败'`——`args` 里既无 provider 也无 operation，`reason` 完全不出现在 `str()` 里，与 `errors.py:23-25` 声称的"可观测、可断言的差异"不符 |
| `provider/_http.py` | 100%（32 语句） | `test_build_client_rejects_key_material_in_the_url:777-792` 三种 bad URL、`test_real_factory_sets_timeout_and_auth_header:725-737` 直测真实工厂 | **不是假绿**，包括"替身好用工厂坏了"这一层对照都做了 |

`guard.py:386`（`raise AssertionError("unreachable")`）未覆盖是**合法的**（结构不可达），不构成假绿。

### 3.8 我试过但**没有**找到假绿的方向（如实登记）

| 方向 | 手法 | 结果 |
|---|---|---|
| `guarded_call` 的编程错误分类是否只认 3 种异常 | 自写探针（`g4_guard_exc_probe.py`）注入 10 种异常：`ValueError` / `TypeError` / `KeyError` / `RuntimeError` / `AttributeError` / `IndexError` / `ZeroDivisionError` / `NotImplementedError` / `AssertionError` / `OSError` | **全部 send_calls=1、全部原样上抛、breaker 全部 CLOSED、backoff 全空**。原实现用"只列出 5 类可捕获异常、其余一律冒泡"的写法，**天然覆盖全部编程错误**——这是正确的写法，`test_provider_guard.py:400` 只参数化 3 种不是缺口 |
| selector 的 `_SLOT_NAMES` 是否"从 dataclass 取"导致循环论证 | 读 `selector.py:_SLOT_NAMES = tuple(field.name for field in fields(Providers))` | `dataclass.fields()` **不会**把字段名放进 `__init__` 的源码，注入 `account_id` 字段不会让 AST 扫描命中——但**签名断言 `set(parameters) == {"config","breaker","clock"}` 会立刻红**。两层任一生效即足够 |
| 熔断窗口断言是否只验了"窗口非空" | 读 `test_threshold_is_strictly_greater_than_the_error_ratio:470-498` 的样本序列 | 序列 `S,S,S,S,F,F,S,F,F,F` 的**每个前缀**都不超 50%（0/0/0/0/20%/33%/29%/38%/44%/50%），只有"恰好等于阈值"能测出 `>` 与 `>=` 的差别——M4 实测确实只有这一条红。**设计正确** |
| 合规门的 handler 计数 0 是否恒真 | 看 `harness()` 的 `_json_responder(case.ok_payload)` 与 `_handle` 的 `self.requests.append(request)` | `_Harness._handle` **确实**会把请求 append 进 `requests`（`test_provider_real.py:145-147`），`count` 非恒 0；且同一夹具在 `test_channel_issues_the_expected_request:536-552` 里被证明能记到 1（`assert box.build_calls == 1`）。**不是恒真** |
| `cloud_ocr.py:301-305` 的 bool 排除是否被测到 | 读 `_optional_confidence` 与全部调用点的期望值 | **未被测到**——已并入 §3.4 的 omit 掩盖项，此处不再重复计数 |

---

## 4. 数值 / 口径抽查（逐项：文档原文 vs 代码取值 + 出处行号）

### 4.1 熔断归 `4003` —— **与权威文档正面冲突**（本评审最重要的一条口径发现）

| 出处 | 原文（逐字） | 代码取值 | 一致？ |
|---|---|---|---|
| `services/_common/openapi.yaml:208`（`ErrorCode` 枚举） | `- 5002 # 依赖超时 / 熔断` | `ProviderCircuitOpenError` → `4003` | **否** |
| `services/_common/openapi.yaml:204`（同枚举） | `- 4003 # 大模型 / 视觉 API 失败` | 熔断用的就是这个 | **否**（语义不符） |
| `services/_common/openapi.yaml:132-136` | `DependencyTimeout:` / `description: \|` / `依赖超时 / 熔断（code=5002）。` / `与第三方业务失败（4001/4002/4003/4004）严格区分…` | 代码取 `:135` 的"没等到响应 vs 等到了失败"作为归 4003 的依据 | **否**——`:135` 区分的是 4001/2/3/4 与 5002 两**组**；`:134` 明写熔断属 5002 这一组 |
| `services/aicore/src/aicore/core/errors.py:33` | `` | `5002` | 504 | 依赖超时 / 熔断 | `DependencyTimeoutError` | | 熔断在 5002 | **否** |
| `services/aicore/src/aicore/core/errors.py:252` | `DEPENDENCY_TIMEOUT_CODE: "依赖超时或熔断",` | — | **否** |
| `services/aicore/src/aicore/core/errors.py:395-396` | `class DependencyTimeoutError(AiCoreError):` / `"""依赖超时 / 熔断（5002，HTTP 504）：**没等到响应**。"""` | — | **否** |
| `services/aicore/src/aicore/core/errors.py:386-387` | `class ChannelFailureError(AiCoreError):` / `"""大模型 / 视觉 API 失败（4003，HTTP 502）…"""` | — | **否** |

**代码侧落点**：`provider/errors.py:12`（表格 `ProviderCircuitOpenError | 4003 | 熔断打开，未发请求`）、
`:80-85`（`class ProviderCircuitOpenError(ProviderError, ChannelFailureError)`）、
`provider/guard.py:263`（`raise ProviderCircuitOpenError(provider, operation, reason="circuit-open")`）。

**代码给出的理由**（`provider/errors.py:16-21`）：
> 熔断的成因是短时间错误率超阈值……即「通道已经坏了」……与 `4003` 一致。而 `5002` 的语义是「依赖劣化」（等不到响应）……

这是一个**工程上可辩的论证**，但它与它自己引用的权威（`_common/openapi.yaml:132-146`）以及本仓 `core/errors.py` 的既有口径**相反**，
而评审的职责是核对"是否真的来自权威文档"，结论是**没有**。

**用户可见后果**（本评审实测，见 §4.3）：熔断打开时 `str(exc)` == `'大模型或视觉 API 失败'`，HTTP 502。
运维看到的是"大模型/视觉 API 失败"，而真实情况是"我方熔断器主动拒绝、根本没打对端"——
这正是 `errors.py:23-25` 自己警告的"让运维误判"。

**测试把错误口径钉死了**（这意味着不修就得带着）：`test_provider_guard.py:185`
`assert excinfo.value.code == 4003, "熔断归 4003（通道已坏），不是 5002（依赖劣化）"`；
`test_provider_real.py:653` 同形。

### 4.2 出处行号失实 —— 2 处（**同一段论证内自相矛盾**）

`provider/deepseek.py:9`：

> `` docs/design/产品设计文档.md:1623 `` 逐字「云视觉 API 签数据合规协议（不用于训练、图像数据合规口径**与对话一致**）」

- **`:1623` 的内容属实**（逐字核对 `产品设计文档.md:1623` = `| 7.9 | AI 辅助边界（K） | **AI 只标记不决策**…云视觉 API 签数据合规协议（不用于训练、图像数据合规口径与对话一致）…`）。
- **但"逐字"二字不成立**：该引用做了省略（真实文本在"（不用于训练"与"图像数据合规口径"之间还有"、图像数据合规口径"以外的内容），
  且被引的句子**主语是"云视觉 API"**，而结论却落在"对话侧的合规口径已评审通过"——**跨了通道**。

`provider/deepseek.py:11`：

> `` 产品设计文档.md:1618 ``（7.4 大模型对话合规）把「M0 确认数据合规条款（不用于训练 / 留存策略）、数据不出域」记为**已定档项**

- **`:1618` 属实**（逐字核对 = `| 7.4 | 大模型对话合规 | 服务商 = **DeepSeek 开放平台（国内服务）**;输入脱敏前置…M0 确认数据合规条款（不用于训练/留存策略）;**数据不出域**…`）。
- **但"已定档项"是对文档状态的误读**：`产品设计文档.md:1826`（同文档的【待评审】清单）逐字写
  `| DeepSeek 数据合规条款 | J 助手上线前提 | M0 与 DeepSeek 确认数据不用于训练/留存策略;保留双服务商备选;开源权重私有化作为 M2 后强选项 | 用户+运营 / M0 |`
  ——**状态栏是"用户+运营 / M0"（未完成），不是"已完成"**。文档里明写"已完成（协议:M2 前签署）"的只有 `:1832` 的**云视觉**那一条，
  而云通道正确地取了 `False`。

**这两处合起来构成一个自相矛盾的论证**：`deepseek.py` 一边说"云视觉协议 M2 前才签，故关"（`:13-14`，正确），
一边用"图像数据合规口径与对话一致"推出"对话侧协议已就绪"（`:9-10`），
而**对话侧的合规条款同样未确认**（`:1826` 状态栏"用户+运营 / M0"）。

**这不是行为缺陷（合规门的实现是对的：在构造请求之前查、拒绝时告警、无降级分支），是论证链的过度声称。**

`COMPLIANCE_READY = True`（`deepseek.py:75`）与 `= False`（`cloud_vision.py:83`、`cloud_ocr.py:92`）
**本身没有可引用的、明确写"已完成/已生效"的出处**——文档只给了"何时确认"（M0 / M2 前）与"未确认的后果"。
唯一形式上最强的依据是 `产品设计文档.md:1832` 对**云视觉**的"已完成（协议:M2 前签署）"，
而它与 `cloud_vision.COMPLIANCE_READY = False` 的方向相反（"已完成"竟对应 False、"未确认"竟对应 True）。

**测试侧**：`test_provider_real.py:898-902`
`test_three_channels_have_independent_compliance_flags` 只断言三个常量 `is True/is False`，
**没有任何用例核对"取值是否有出处"**——这正是 §3 那类"被测到但判据是常量"的形态。

### 4.3 熔断错误的对外观感（本评审实探原始输出）

探针：`$env:TEMP\g4_errors_probe.py`（已删）

```
class                            code  http  isinstance(Core)  message
ProviderChannelFailureError      4003   502              True  '大模型或视觉 API 失败'
ProviderCircuitOpenError         4003   502              True  '大模型或视觉 API 失败'
ProviderTimeoutError             5002   504              True  '依赖超时或熔断'
ProviderError                    None  None             False  None

--- attribute surface ---
  provider     = 'prov'
  operation    = 'op'
  reason       = 'circuit-open'
  code         = 4003
  message      = '大模型或视觉 API 失败'
  args         = ('大模型或视觉 API 失败',)
  str(e)       = '大模型或视觉 API 失败'
```

两点补充：

1. **端到端是通的**：`core/errors.py:428` 注册了 `app.add_exception_handler(AiCoreError, _handle_ai_core_error)`，
   `ProviderCircuitOpenError` 经 `ChannelFailureError` 是 `AiCoreError` 子类（上表 `isinstance(Core)=True`），
   MRO 与业务码映射正确，**不会落到 5000**——这一点做对了。
2. **但 `reason` 与 `operation` 进不了 `str()`**：`args` 只有平台文案。
   `errors.py:23-25` 声称"熔断要单独一个类……让『因熔断而没调用』与『调用了但失败』在日志与计数上不可分"，
   而实测两者的 `str()` **完全相同**（都是 `'大模型或视觉 API 失败'`），
   差异只在 `type(exc)` 与 `.reason` 上——**只有按类型/属性检查的代码能分辨，打日志的代码分辨不了**。

### 4.4 通道护栏四项：**全部逐字一致**（本评审自己读的文档行）

| 项 | 文档出处与原文 | 代码取值 | 一致？ |
|---|---|---|---|
| AI 超时 5s | `docs/design/高并发架构演进设计.md:317` = `` | 超时分级 | 第三方支付 3s / AI 5s / 短信 2s / 内部服务 1s ★ | 依赖 SLO | `` | `Settings.ai_call_timeout_s = 5.0`（`core/config.py`）+`.env.example` | **是** |
| 同项第二出处 | 同文档 `:423` = `- 统一超时分级：内部服务 1s / 第三方支付 3s / AI 5s（§4.4 初值）；网关聚合超时按路由配置。` | 同上 | **是** |
| 重试 ≤5 次 | 同文档 `:260` = `` | 重试 | 仅**幂等接口**可重试；指数退避（1s→2s→4s… 上限 5 次）；非幂等操作禁止自动重试，转人工/对账 | `` | `provider_max_retries = 5` | **是** |
| 同项第二出处 | 同文档 `:318` = `` | 重试 | 幂等接口 ≤5 次指数退避；非幂等 0 次 ★ | 评审 | `` | 同上 | **是** |
| 熔断阈值 50% | 同文档 `:316` = `` | 熔断阈值 | 错误率 >50% 或慢调用 >阈值 连续触发 → 熔断；半开探测间隔 10s ★ | 压测 | `` | `circuit_error_ratio = 0.5`，判据 `>`（`guard.py:299`） | **是** |
| 半开 10s | 同文档 `:316`（同上） | `circuit_cooldown_s = 10.0` | **是** |
| 退避基数 1s / 公比 2 | 同文档 `:260` 逐字「指数退避（1s→2s→4s… 上限 5 次）」 | `GuardConfig.backoff_base_s = 1.0` / `backoff_factor = 2.0`（`guard.py:137-138`） | **是** |
| 「慢调用 >阈值」未实现 | 同文档 `:316` 的「或慢调用 >阈值」 | 无对应 `Settings` 字段 | **确认未实现**（§5-5 属实） |

### 4.5 `model_meta` 五个键名 vs `er.md` §6.1 —— **逐字一致**

- 文档：`services/aicore/docs/er.md:295` = `` | model_meta | JSON | YES | — | NULL | **模型/Prompt 血缘（2026-09-16 增）**：`{channel, provider, modelVersion, promptVersion, thresholds（high/medium）}`；满足 PRD §4「依据什么模型」可追溯 | ``
- 代码：`provider/results.py:126-132` 的 `as_model_meta()` 返回 `{"channel", "provider", "modelVersion", "promptVersion", "thresholds"}`
- 判定：**一致**（5 个键名逐字相同；`thresholds（high/medium）` 的子键由 `test_provider_results.py:145-148` 单独钉）。
- 且测试**从文档现读**（`test_provider_results.py:114-128` 用正则从 `er.md` 抽键清单，
  并带 `assert match is not None` 的前置断言防止抽取退化成空比对）——**这是本组最好的取证写法之一**。

### 4.6 `OcrField` 三个键名 vs `services/aicore/docs/openapi.yaml:708-726` —— **逐字一致**

- 文档 `:710` `required: [fieldName, value, confidence]`；`:712` `fieldName:`；`:716` `value:`；`:720` `confidence:`；
  `:718` `description: 识别值（脱敏输出）`；`:723-724` `minimum: 0` / `maximum: 1`
- 代码 `provider/results.py:70-72`：
  `fieldName: FieldName` / `value: str` / `confidence: float | None = None`（带 `# noqa: N815` 并注明"逐字取自 openapi.yaml 的 OcrField"）
- 判定：**一致**。
- 测试 `test_provider_results.py:207-225` 从 yaml 现读并用 `re.search(r"\n    OcrField:\n(.*?)\n    \w", …, re.DOTALL)` 抽块，
  **但该抽取只做 `assert name in body`（子串包含）**，不校验 `required` 列表本身；
  `:210` 的注释声称"同时覆盖 `required: [fieldName, value, confidence]`"——**这一步没做**。
  这是一处**断言弱于注释**的小问题：把 `required` 改成 `[fieldName]` 后本用例仍绿。
  （不影响当前正确性：三个键名本身是真的逐字一致。）

### 4.7 脱敏形态：与 `openapi.yaml` 一致，与 `er.md` §6.3 示例**不一致**（已登记为未做到项，此处补精确证据）

| 出处 | 原文/示例 | 位数 | 代码产出 | 一致？ |
|---|---|---|---|---|
| `services/aicore/docs/openapi.yaml:719` | `example: 911301********1234` | 18 位 → **8 个星** | `911301********1234` | **是** |
| `services/aicore/docs/er.md:319` | `AI 原值（**脱敏**，如 911301\*\*\*\*\*\*\*\*1234）` | 18 位 → **9 个星** | `911301********1234`（8 星） | **否** |
| `services/aicore/docs/er.md:305` §6.2 | `OcrField = {fieldName, value(脱敏), confidence(0~1)}` | 未给示例 | — | 不适用 |

代码规则（`cloud_ocr.py:246-252`）：首 6 + 等长星号 + 末 4，**长度不变**。
以 18 位身份证 `110101199003071234` 验算：6 + (18−6−4=8) + 4 → `110101********1234`，**8 个星**。
测试期望与代码一致（`test_provider_real.py:429-430` 明确写 `"110101********1234"` 并在注释里算了一遍 `18 - 6 - 4`）。

**结论**：`er.md` 自身的两处示例（§6.2 与 §6.3）星号数就不一致（`:319` 9 星），
OpenAPI 的例子（8 星）与代码一致。**代码选的是"长度不变"这条更强、可断言的规则，是正确的工程选择**，
但 `cloud_ocr.py:121` 的"（`er.md` §6.3 的示例同样是首 6 位）"与 `:124` 的"（见 `er.md` §6.3 的同形示例）"
把"首 6 位"这一点对齐了，**未说明星号数不同**——建议在这两处注释里显式标注"星号数与 `er.md:319` 的示例相差 1 位，本实现取长度不变口径"。

### 4.8 `ImageKey` 合规前置 vs `spec.md` —— 引用属实

- 文档 `openspec/changes/implement-aicore-service/specs/ai-core-service/spec.md:86` 逐字：
  「图像 MUST 在离开平台前完成脱敏……送往云视觉 API 的图像 MUST 处于已签署的数据合规协议之下（不用于训练、数据不出域或按协议留存）。合规协议状态 MUST 可被核对，未取得协议时系统 MUST NOT 调用该通道。」
- `:95-96` 逐字：「**WHEN** 某外部通道的数据合规协议未生效或已过期 / **THEN** 系统拒绝调用该通道并告警，不以外发图像的方式继续处理。」
- 代码 `cloud_ocr.py:320-335` / `cloud_vision.py:275-…` 的 `_require_compliance`：
  先 `_logger.warning(...)` 再 `raise ProviderChannelFailureError(..., reason="compliance-missing")`；
  调用点 `cloud_ocr.py:171-172` / `cloud_vision.py:150-151` 均为「`self._call_count += 1` → `_require_compliance(...)` → 入参校验 → 超时校验 → `guarded_call`」。
- 判定：**逐字一致，且"在构造请求之前"这一条经本评审独立实测为真**（§5 的 E2：`build_client_calls == 0` 且 `handler_calls == 0`）。

---

## 5. 未做到项核实（评审包 §7 十条，逐条）

| # | 声明 | 核实方法 | 判定 |
|---|---|---|---|
| 1 | 云通道 base_url/路径/请求体键名/鉴权头全是占位口径，未与真实厂商 API 校验；DeepSeek 未做真实调用 | 读 `cloud_ocr.py:95-98`（`https://cloud-ocr.vendor.invalid` + `/ocr/recognize`）、`cloud_vision.py:86-89`、`deepseek.py` 的 `DEFAULT_DEEPSEEK_BASE_URL`/`CHAT_COMPLETIONS_PATH` | **属实**。补精确化：`_http.AUTH_HEADER = "Authorization"` + `AUTH_SCHEME = "Bearer"`（`_http.py:59-62`）是**假设**，不是任一厂商的已核事实；DeepSeek 确实用 `Authorization: Bearer`，但云视觉/云 OCR 的厂商未定（`产品设计文档.md:1832` 只说"通义VL/GLM-4V 先小样测评"），故这个头对云通道**大概率要改** |
| 2 | `identity.thresholds` 三通道都是 `{}`，其所有者是 Task 4.10 | `grep thresholds src` → 只有 `results.py:102` 的默认空 dict 与 `mock.py:409` 的说明；**没有任何通道给 `thresholds` 赋值** | **属实**。补精确化：`产品设计文档.md:1623` 逐字给出了「置信度分级（高≥0.9/中 0.7~0.9/低<0.7,可调）」，即阈值**数值在文档里已经有**，只是"可调/留痕"的载体（Settings 字段 + 快照）归 4.10。故 `er.md` §6.1 的 `thresholds（high/medium）` 快照当前无值可记这件事，**不是"文档还没定"，是"配置面还没建"** |
| 3 | `ProviderResult.raw` 一律不填；本层未记 `requestId` | `grep 'raw=' src/aicore/provider/*.py` → **0 命中**；`grep 'requestId\|request_id'` → **0 命中** | **属实**（两条都属实，且比声明更彻底：连变量名都没出现） |
| 4 | 无连接复用（一次调用一客户端），性能代价未测 | `cloud_ocr.py:214-219` / `cloud_vision.py:191-…` / `deepseek.py` 的 `_exchange` 均为 `client = _http.build_client(...)` + `async with client:` | **属实**。补精确化：`_http.py:22-29` 给了取舍理由（超时逐次可传 → 客户端与超时一一对应），但"一次调用一个客户端"在**重试**时是**每个 attempt 一个新客户端**（`send` 闭包每次调用 `_exchange`），即 `max_retries=5` 时一次逻辑调用最多建 6 个客户端/6 次 TLS 握手——**这个放大量级比"无连接复用"本身更值得记** |
| 5 | 高并发 L316 的「慢调用 >阈值」未实现 | `grep` `Settings` 无对应字段；`guard.py:299` 只判 `_failure_ratio`（错误率） | **属实**。文档 `:316` 逐字同时给了两个触发条件（`错误率 >50% 或慢调用 >阈值`），当前只实现了前者；`GuardConfig` 里也没有耗时统计（`_Window.samples` 只存 `bool`，`guard.py:193-197` 明确说明"存耗时或异常对象会让窗口随时钟漂移"——这是有意的设计选择，但**后果是"慢调用"这一半在当前数据结构下无法补，需要改 `_Window`**） |
| 6 | `main.py` 未接线 | `Select-String -Path 'src\aicore\main.py' -Pattern 'select_providers\|provider'` → **0 命中** | **属实**。且 `main.py` 同时在覆盖率 omit 里，故"未接线"这件事在门禁上完全不可见 |
| 7 | `provider_max_retries` 只有等值断言，没有行为断言 | `test_provider_guard.py:617-636` `test_guard_config_maps_the_four_settings_fields` 断言 `config.max_retries == 7`（等值）；`test_provider_selector.py:483-515` 断言 `channel._guard_config == expected`（等值） | **属实**。**但需要更正一处**：`selector.py` 的模块 docstring 与 `test_provider_real.py` 的用例注释都声称"用例把 `httpx.MockTransport` 的 handler 计入请求数，用它反推『重试次数确实来自配置』"（`selector.py` docstring 末段逐字如此）。实测**不存在**这样的用例：`_transport` 在 selector 侧只用于 `test_timeout_from_config_cancels_the_call_at_the_new_deadline`（超时，`max_retries=0`）。即**注释声称了一个不存在的用例**，这比"只有等值断言"更值得登记 |
| 8 | `call_count` 语义 = 「方法被调用次数（含被合规门/熔断挡下的那次）」，需 4.9 复核 | `deepseek.py:124-132` docstring 逐字说明口径；实测 `channel_call_count == 1`（合规门挡下，§6 的 E2）与 `provider.call_count == MIN_SAMPLES + 1`（熔断挡下，`test_provider_real.py:656-658`） | **属实**，且实现与文档一致。补一条**潜在风险**：`call_count` 在**方法入口第一行**自增（`cloud_ocr.py:171`），若将来有人在 `_require_compliance` **之前**插入早退分支（例如限流），口径会变而文档不会跟着变——建议在 `:171` 加一行注释把"必须先于一切早退"钉住 |
| 9 | `test_provider_selector.py` 与 `test_provider_real.py` 存在有意代码重复（`_SocketGuard`/`_FakeClock`/`_is_loopback`） | 三者在两文件中各有一份：`test_provider_selector.py:92-131,255-270` 与 `test_provider_real.py:228-271,95-110` | **属实**。补一条**比"重复"更重要的事**：两条 `_SocketGuard` 的**行为强度不同**——`test_provider_real.py:266-271` 会 `raise _RealSocketBlockedError`（真拦），而 `test_provider_mock.py:160-168` 的 `_spy` 一律 `return real_connect(...)`（只记不拦，docstring `:178` 也这么说）。三处同名结构、两种语义，建议把 mock 那侧的类改名（如 `_ConnectRecorder`）以免后人误以为"被记下就等于被拦住" |
| 10 | Task 4.4 的实现者用了 3 个临时脚本（工单上限 2） | 过程事项，评审无法从工作区复核（探针已删） | **无法独立复核**。按纪律性质判断：3 个只读、`$env:TEMP` 下、用完即删的探针**未造成工作区污染**（本评审全程 `git status` 无第三方残留），**不建议为此返工**；建议按"下次限额提示写进工单"处理 |

### 5.1 §7 未列、但控制者 §5 自述与实测不符的一处

评审包 §5 第 4 项逐字：

> **4.4**：12 格选择矩阵逐格正确；**选不中的槽位为 `None` 且不回落到 Mock**；四个护栏参数在不同取值下精确透传；空凭据三种形态 fail fast 且点名环境变量。

- "12 格逐格正确" / "槽位为 `None`" / "护栏参数精确透传" / "空凭据三种形态" → **本评审独立复现全部为真**（§6）。
- "**且不回落到 Mock**"这一句**没有独立的执行证据**：唯一声称验证它的用例 `test_none_slots_do_not_fall_back_to_mock`（`:820-832`）
  只断言 `providers.text is None and providers.vision is None`，**断的是"是 None"，不是"没有回落到 Mock"**；
  它的配套自证 `:835-858` 不经过被测选择器（§3.3）。
  这两者在当前实现下**等价**（回落到 Mock 就必然非 None），所以结论没错，
  但"不回落到 Mock"这条**语义**的取证是"由 `is None` 反推"，属于 §3 那类"断言比它声称的弱"。
  建议把 `:829` 的断言补成 `assert not isinstance(providers.text, MockTextProvider) and providers.text is None`，
  或直接断言 `type(...) is NoneType`，让"不回落"变成正面证据。

---

## 6. 复跑控制者的独立验证（评审包 §5）—— 至少 3 项，全部用**本评审自写的探针**

探针：`$env:TEMP\g4_e_probe.py`（评审自写，与实现者/控制者的探针无关，**用后已删**）。
运行：`cd services/aicore; .\.venv\Scripts\python.exe "$env:TEMP\g4_e_probe.py"`。

### E1 熔断门在 send 之前

```
E1 breaker-gate-before-send : {'state_after_open': 'OPEN', 'calls_to_open': 5, 'calls_after_gate': 5, 'gate_increment': 0, 'raised': 'ProviderCircuitOpenError', 'is_circuit_open_error': True}
```

**判定：控制者说法属实。** 熔断打开后 `send` 计数**增量 0**，抛 `ProviderCircuitOpenError`。
（该错误码为 `4003`，见 §4.1——门的位置对，归码错。）

### E2 合规门的 handler 计数为 0 + build_client 计数为 0

```
E2 compliance gate          :
       cloud_vision = {'compliance_ready': False, 'build_client_calls': 0, 'handler_calls': 0, 'reason': 'compliance-missing', 'code': 4003, 'channel_call_count': 1}
       cloud_ocr = {'compliance_ready': False, 'build_client_calls': 0, 'handler_calls': 0, 'reason': 'compliance-missing', 'code': 4003, 'channel_call_count': 1}
       deepseek = {'compliance_ready': True, 'build_client_calls': 1, 'handler_calls': 1}
```

**判定：控制者说法属实且比其声明更强**——不仅 `handler_calls == 0`，连 `build_client_calls == 0`，
即合规检查**确实在构造 HTTP 客户端之前**，与 `test_provider_real.py:872` 的注释一致。
`deepseek` 侧 `build_client_calls == 1` / `handler_calls == 1` 提供了正向对照（说明这一层替身真的能看到请求）。

### E3 selector 不回落 mock

```
E3 selector matrix          : {'mock': {'text': 'MockTextProvider', 'vision': 'MockVisionProvider', 'ocr': 'MockOcrProvider'}, 'deepseek': {'text': 'DeepSeekTextProvider', 'vision': None, 'ocr': None}, 'cloud_vision': {'text': None, 'vision': 'CloudVisionProvider', 'ocr': None}, 'cloud_ocr': {'text': None, 'vision': None, 'ocr': 'CloudOcrProvider'}, '_cloud_ocr_has_any_mock': False}
```

**判定：控制者说法属实**（12 格逐格正确；`cloud_ocr` 部署下三个槽位无一是 Mock）。
但见 §5.1：这条结论的**测试取证**弱于它的措辞。

### 额外第 4 项（评审包未列，本评审认为比上面三项更关键）

`test_provider_real.py:139` 的替身用 `headers=_http.auth_headers(api_key)`——**"密钥在头里"这条断言用的是被测模块自己的头构造器**。
这不构成假绿（因为 `test_real_factory_sets_timeout_and_auth_header:731-735` 用**真实** `build_client` 独立验了一次
`client.headers["Authorization"] == "Bearer sk-fake-…"`），属于"替身 + 工厂直测"两层取证，**写法正确**。

---

## 7. 我补登的遗漏项（控制者 §7 与实现者都没写的）

| # | 遗漏项 | 证据（可复核） | 严重度 |
|---|---|---|---|
| **N1** | `test_signature_equality_is_discriminating` 是**装饰性自证**：它证明的是 `Signature.__eq__` 不是恒真函数，与被保护的 `:85` 断言无数据流关系 | §3.2 的 M3/M3b+M3c 联合变异：弱化 `:85` + 真实 `*` 漂移 → **1088 passed**，自证用例自身也 passed | **高**（已并入 B2） |
| **N2** | Mock「零 socket」守卫**不覆盖 `src/aicore` 任何模块**，"断网可跑"的取证面被高估 | §3.1：往 `mock.py` 注入真实 connect → mock/real/selector 三套件全绿（48/51/35 passed） | **高**（已并入 B3） |
| **N3** | **熔断的用户可见文案是错的**：`str(ProviderCircuitOpenError(...))` == `'大模型或视觉 API 失败'`（HTTP 502），与 `ProviderChannelFailureError` **完全同串** | §4.3 探针原始输出；`errors.py:250`（`CHANNEL_FAILURE_CODE: "大模型或视觉 API 失败"`）。且 `reason`/`provider`/`operation` **不在 `args` 里**，打日志的代码分辨不出熔断与通道失败——与 `errors.py:23-25` 声称的意图相反 | **高**（与 B1 同源，独立列出因为它是"改码也改不掉"的那一半） |
| **N4** | `cloud_ocr` 的 **`confidence` bool 排除分支（`cloud_ocr.py:304-306`）零覆盖**，而同一契约在 `deepseek` 有专门用例 | 覆盖率实测（去掉 omit）：`cloud_ocr.py … 93% 265, 276, 279, 283, 289, 305-306`；`test_confidence_with_wrong_type_is_malformed:702-717` 只覆盖 deepseek | 中 |
| **N5** | `cloud_ocr._parse_fields` 的 4 条畸形响应分支（`:275-276, 279, 283, 289`）零覆盖 | 同上覆盖率输出 | 中 |
| **N6** | `selector.py` 模块 docstring **声称了一个不存在的用例**：「用例把 `httpx.MockTransport` 的 handler 计入请求数，用它反推『重试次数确实来自配置』」 | `grep _Transport test_provider_selector.py` → 只在 `test_timeout_from_config_cancels_the_call_at_the_new_deadline`（`max_retries=0`，验超时）里用；**没有任何用例用 handler 计数反推重试次数** | 中（文档失真，且正好覆盖了 §7-7 的真实缺口） |
| **N7** | `test_provider_results.py:210` 的注释声称"同时覆盖 `required: [fieldName, value, confidence]`"，实际只做 `assert name in body` 子串包含 | 该用例 `:218-219` 只遍历三个名字做包含判断；把 `required: [fieldName]` 改掉仍绿 | 低-中 |
| **N8** | `test_provider_real.py:898-902` 只断言三个 `COMPLIANCE_READY` 常量的**取值**，**不核对出处**；而其中 `deepseek=True` 的出处论证是错的（§4.2） | 该用例全文三行 `assert`；§4.2 的行号核对 | 中 |
| **N9** | `base.py:12-16` 的"收紧 2"自述与 `deepseek.py:14` 的遗留句**自相矛盾**：前者说"三个通道**都**声明 `prompt_version`"，后者仍写"VISION 没有 prompt 版本而血缘里留空" | `base.py:12` vs `deepseek.py:14`（两句都在最终工作区里）；实际 `cloud_vision.py:99` 有 `PROMPT_VERSION = "cloud_vision-not-applicable"` | 低（文档债，但"三通道都声明"正是 §7-2 之外另一处需要 4.10 补齐的地方） |
| **N10** | `ProviderResult.raw` 被 omit 掉的那三个通道**连"必须为 None"的断言都没有** | `grep 'raw=' src` → 0 命中，故 `raw` 恒为默认 `None`；但**没有任何用例断言它**。将来有人在 `cloud_ocr.py:226-230` 加一个 `raw=decoded` 就会把未脱敏证件值带进结果结构，而 51 条真实通道用例**全绿** | 中（`results.py:165-166` 明确写"`raw` MUST NOT 含未脱敏的证件值"，却没有对应的负向断言） |
| **N11** | 覆盖率 omit 掩盖了 291 个语句（13.8%），恰好是 `main.py` + 三个真实通道 | §3.4；`pyproject.toml:118` | 中（口径） |
| **N12** | 评审包 §3 的 10 个文件行数**全部失实**（偏小 1.5~1.8 倍），且漏列 `.sdd-tools.py` | §2.7 表格 + 复算命令 | 低（包本身的质量） |

---

## 8. 次要问题与建议（不阻塞交付）

1. **`guard.py:193-197` 的 `samples` 只存 `bool`** → 「慢调用」那一半护栏（§5-5）在当前数据结构下无法补，
   需要改 `_Window`。建议在 4.10/4.11 的工单里显式登记这次结构变更，避免届时时序仓促。
2. **`provider/errors.py` 缺一个直接测试**（§3.7）：建议补一条最便宜的用例——
   `assert isinstance(ProviderCircuitOpenError("p","op","r"), ChannelFailureError)` 且
   `str(...)`/`code`/`http` 三件套与 `core/errors.py` 的注册表对齐。这条同时会把 §4.1 的分歧暴露成红灯，是**最低成本的收口点**。
3. **`_attribute_connect`（`test_provider_mock.py:111-142`）建议改为"栈里出现过 `src/aicore` 帧即违规"**，
   并把"测试自己的帧要跳过"改成显式白名单（当前用 `stack[2:]` 跳过两帧，是靠层数假设的脆弱写法）。
   改完后 §3.1 的 M1 应当变红——**这可以作为修复的验收判据**。
4. **三处同名 `_SocketGuard` 语义不同**（§5-9）：建议 mock 侧改名 `_ConnectRecorder`。
5. **`test_provider_selector.py:835-858` 的自证**（§3.3）建议删除或改为"把 `_SELECTABLE_SLOTS` 表故意改成含未选中槽位，
   断言用例矩阵会红"——后者才真的证明判据有判别力。
6. **`test_provider_real.py` 的 `compliance_open` 夹具是"临时打开合规门"**（`:207-215`）：
   它 `monkeypatch.setattr(cloud_vision, "COMPLIANCE_READY", True)`，
   而 `:870` 的负向用例又断言"出厂状态 MUST 是未就绪"。两者由 fixture 隔离，写法正确；
   建议加一条"`compliance_open` 未使用时 `COMPLIANCE_READY` 仍为 False"的断言，把"没被测试意外改坏"也钉住。
7. **`deepseek.py:75` 的 `COMPLIANCE_READY = True` 建议改成由 `Settings` 承载的开关**（与四项护栏同档），
   理由：它是**外部合规状态**，不是代码常量；落在常量里意味着"协议生效/失效"要靠改代码（一次发版）。
   当前用注释引用文档行号是次优做法，而这两条引用恰好有一条是错的（§4.2）。

---

## 9. 我自己的不确定项（如实列出）

1. **§3.1 的根因表述**：我确认了"注入到 `mock.py` 的 connect 不被记录"这一**事实**（三次运行、三个套件），
   但"为什么"我给的推断是"`inspect.stack()` 未呈现该帧"——**我没有直接打印那次 connect 的栈来证实**。
   可以直接证伪/证实的方法：把 `_attribute_connect` 临时改成 `print(inspect.stack())` 并在源码里触发一次 connect。
   我未做这一步，故把根因标注为**推断**；事实层面（不被记录）是**已证实的**。
2. **§4.1 的裁定是否应当改**：我能证明"与权威文档冲突"，但**不能**证明"改成 5002 一定更好"。
   代码给出的理由（熔断 = 通道已坏 → 4003）在工程上可辩。若控制者/用户认为应当保留 4003，
   那么**必须同步改 `_common/openapi.yaml:208` 与 `core/errors.py:33/252/395-398`**，
   否则仓库里会长期存在两套码表——分歧本身比取哪个值更危险。
3. **§5-10（探针数量越界）**：我无法从工作区复核（临时脚本已删），故只做了纪律性判断，未做事实认定。
4. **`test_provider_real.py` 的 `_SocketGuard` 是否真的会拦到东西**：我推断"会"（基于 `:266-271` 的代码与
   `test_socket_guard_has_discriminating_power:304-305` 的 `pytest.raises(_RealSocketBlockedError)` 通过），
   **没有做独立变异**（例如把 `raise` 改成 `return` 看是否有用例变红）。建议补做。
5. **`selector.py:_validate_channel_table()` 在 import 期用 `assert`**（`:310-…`）：
   它对外部条件不成立时是 `AssertionError`（`python -O` 下会被整段剥掉）。
   当前它是"表自检"，表是模块内常量、不依赖环境，故我不认为这是实际风险；
   但若将来表里加入读环境的判断，就需要换成显式 `raise`。**这一条我没有构造 `python -O` 的对照实验**。

---

## 10. 临时文件清单（评审自建，全部已删）

| 路径 | 用途 | 状态 |
|---|---|---|
| `$env:TEMP\g4_e_probe.py` | §6 的 E1/E2/E3 独立复跑探针 | **已删** |
| `$env:TEMP\g4_mutate.py` | §3 的变异应用/还原工具（含 SHA256 自证、`apply` 前校验锚点唯一、`restore` 后校验哈希） | **已删** |
| `$env:TEMP\g4_guard_exc_probe.py` | §3.8 的 `guarded_call` 异常分类探针（10 种异常） | **已删** |
| `$env:TEMP\g4_errors_probe.py` | §4.3 的错误类对外契约探针 | **已删** |
| `$env:TEMP\g4_cov_setup.py` | §3.4 覆盖率测量的早期尝试（未使用，改用 rcfile） | **已删** |
| `services/aicore\tests\unit\test_zz_review_probe.py` | §3.1 的 M1 探针用例（在工作树内，运行后立即删除） | **已删** |
| `services/aicore\g4review_cov.ini` | §3.4 覆盖率 rcfile（临时绕过 omit） | **已删** |
| `services/aicore\.coverage` | 覆盖率数据文件（由我运行的 pytest 产生，原本不存在） | **已删** |
| `*.g4bak`（若干） | 变异备份（每次 `restore` 校验哈希后自动删除） | **全部已删**，`Get-ChildItem -Recurse` 复查为空 |

**工作树终态自证**：`git status --porcelain` = 9 个 ` M` + 11 个 `??`，与评审开始时逐项相同；
6 个被我变异过的文件的 SHA256 与变异前**逐字节相同**（§3.0 表）。

---
