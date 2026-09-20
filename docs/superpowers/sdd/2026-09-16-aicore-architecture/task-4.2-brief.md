### Task 4.2: Mock Provider（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**（沙箱实测：pip 能下载但写 `.whl` 被拒，`PermissionError`）。
**编码**：UTF-8 无 BOM；MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写含中文的文件（用 write/edit 工具）。
**Shell**：`sh` 在本沙箱不可用，故本工单所有命令用 PowerShell 形式。

**Files:**
- Create: `src/aicore/provider/mock.py`（当前是 1 行 docstring 空壳，本任务写满）
- Create: `tests/unit/test_provider_mock.py`
- **MUST NOT 改**：`src/aicore/provider/base.py`、`src/aicore/provider/results.py`、`src/aicore/provider/errors.py`、
  `src/aicore/core/config.py`、`pyproject.toml`、`.importlinter`、任何 `tests/` 下的既有文件。

---

## 0. 先读这三份契约（**控制者已定稿，MUST NOT 改**）

1. `src/aicore/provider/base.py` —— `TextProvider` / `VisionProvider` / `OcrProvider` 三个 Protocol
   的**逐字签名**（方法名、关键字参数名、返回类型）。
2. `src/aicore/provider/results.py` —— `ProviderResult` / `ProviderIdentity` / `OcrField` /
   `CHANNELS` / `to_jsonable`。
3. `src/aicore/provider/errors.py` —— `ProviderChannelFailureError` / `ProviderTimeoutError` /
   `ProviderCircuitOpenError`。

**权威设计依据（MUST 先读，不要只 grep）**：
- spec **§AI 网关与模型路由 L11、L18-21**（通道可替换；调用方无须感知供应商）
- design.md **D3 L52-58**（`mock`「确定性、可离线」；dev/test 允许降级并告警；**prod 禁用**）
- tasks.md **4.2 L38**（「确定性输出、可注入延迟与故障」；验证：**全程无网络依赖（断网可跑）**）
- design.md **L280**（夹具）与 **L282**（离线保证：「纯函数、契约、接口、仓储四层在**零密钥、零外部中间件**下即可跑通」）
- 本工单 **§3 的零 socket 取证条款**（用户已选定的取证方式）

---

## 1. 交付接口（MUST 照此，签名逐字）

```python
MOCK_PROVIDER_NAME: str = "mock"

@dataclass(frozen=True, slots=True)
class MockFault:
    """注入的故障。三者互斥（同时为真时按 kind 优先级取第一个命中的，见 §2.4）。"""
    kind: Literal["timeout", "error", "empty"]
    #: 命中第几次调用时触发（从 1 开始）。默认 1 = 首次即触发。
    on_call: int = 1

@dataclass(frozen=True, slots=True)
class MockScript:
    """Mock 的行为脚本。**默认值 = 完全确定性、零延迟、零故障**。"""
    latency_s: float = 0.0
    fault: MockFault | None = None

class MockTextProvider:
    name: str = MOCK_PROVIDER_NAME
    model_version: str = "mock-text-v1"
    prompt_version: str = "mock-prompt-v1"
    def __init__(self, script: MockScript | None = None) -> None: ...
    async def complete(self, *, prompt: str, payload: Mapping[str, Any], timeout_s: float) -> ProviderResult: ...
    def model_meta(self) -> dict[str, Any]: ...
    @property
    def call_count(self) -> int: ...       # 供 Task 4.9 断言「Provider 调用次数不增加」

class MockVisionProvider:   # name="mock", model_version="mock-vision-v1", prompt_version="mock-prompt-v1"
    async def analyze(self, *, image_key: str, labels: list[str], timeout_s: float) -> ProviderResult: ...

class MockOcrProvider:      # name="mock", model_version="mock-ocr-v1", prompt_version="mock-prompt-v1"
    async def recognize(self, *, image_key: str, doc_type: str, timeout_s: float) -> ProviderResult: ...
```

三个类**都**要有 `call_count` 属性与 `model_meta()` 方法。

---

## 2. 硬约束（每条都有可核方式；偏离即返工）

### 2.1 确定性：同输入 MUST 同输出（**逐字节**）

`complete` / `analyze` / `recognize` 的返回值 MUST 由**入参的稳定哈希**派生，
MUST NOT 用 `random`、`uuid4`、`time.time()`、`os.urandom`、字典遍历顺序等不稳定来源。

- 派生方式：`hashlib.sha256` 对**规范化后的入参**（`repr` 或 JSON 排序键）取 hex，
  再按需切片构造文本/字段值。**`hashlib` 是 stdlib，允许**。
- **为什么不能用 `hash()`**：Python 的 `hash()` 对 `str` 有 **PYTHONHASHSEED 随机化**，
  跨进程不稳定——用它会让「确定性」在同一个 pytest 进程里看起来成立、在 CI 分片跑时失败。
  这是本任务最容易踩的坑，docstring 里 MUST 写明。
- 可核方式：用例里对同一入参连续调 3 次，断言三次结果**完全相等**；
  再在**子进程**里跑一次同输入（`subprocess` 调 `.venv\Scripts\python.exe -c ...`），
  断言与父进程结果一致——这一条才真正证明「跨进程确定」。

### 2.2 延迟与故障可注入，且**测试里 MUST NOT 出现任意 sleep**

- `latency_s > 0` 时，`await asyncio.sleep(latency_s)`。
- **但**：用例 MUST NOT 真的等。做法是在 `MockScript` 之外给每个类一个
  **可替换的睡眠函数**（构造函数可选参数 `sleep: Callable[[float], Awaitable[None]] | None = None`，
  默认 `asyncio.sleep`）。用例注入一个**记录调用**的假 sleep（返回即刻完成的协程），
  断言「收到了 0.25 秒的睡眠请求」而不是真的睡 0.25 秒。
  依据：`tests/conftest.py` 文件头逐字「测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟」。
- `latency_s` 大于 `timeout_s` 时 MUST 抛 `ProviderTimeoutError`（不是让它睡完再返回）。
  **这一条是 Task 4.3「超时」链路在离线侧的可测形态**，必须有。

### 2.3 故障注入的三种形态与**各自的异常/返回**

| `kind` | 行为 | 断言点 |
|---|---|---|
| `"timeout"` | 抛 `ProviderTimeoutError(provider="mock", operation="<方法名>", reason="mock-timeout")` | `exc.code == 5002` |
| `"error"` | 抛 `ProviderChannelFailureError(..., reason="mock-error")` | `exc.code == 4003` |
| `"empty"` | **正常返回**，但载荷为空、`confidence=None` | 结果非异常；`confidence is None`（**MUST NOT 是 0.0**） |

### 2.4 `on_call` 语义

第 `on_call` 次调用触发故障，其余次正常。**同一个实例内计数**（`call_count` 从 1 开始）。
- `on_call=2` → 第 1 次正常、第 2 次抛、第 3 次正常。用例 MUST 覆盖这三步。

### 2.5 `confidence` 与字段值 MUST 落在契约域内

- `ProviderResult.confidence` ∈ `[0.0, 1.0]`，或 `None`。**MUST NOT 越界**（openapi.yaml
  的 `confidence` 是 `minimum: 0, maximum: 1`）。
- OCR 的 `fields` MUST 是 `tuple[OcrField, ...]`，每个 `OcrField.fieldName` 非空、
  `value` 非空、`confidence` ∈ [0,1] 或 `None`。
- 三个通道的 `ProviderResult` **载荷字段互斥**：TEXT 只填 `text`、VISION 只填 `markers`、
  OCR 只填 `fields`，其余两个字段 MUST 为 `None`。用例 MUST 逐通道断言这一点。

### 2.6 值 MUST 已脱敏（**合规红线**）

Mock 产出的 `value` MUST NOT 是"看起来像真实证件号"的明文。
`er.md` §6.2 逐字要求 `fields_json` 的 `value` 是「识别值（**脱敏输出**）」；
openapi.yaml:715 的示例是 `911301********1234`。故 Mock 的产出 MUST 采用
**中间打星号**的形态（如 `91330100********1234`），**MUST NOT** 输出 18 位纯数字。

- 可核方式：用例对产出的每个 `value` 断言「不含连续 15 位以上数字」。
- **为什么这条对 Mock 也较真**：Mock 是 dev/test 默认通道，它的输出会被写进
  `ocr_result.fields_json`、进日志、进评估集。今天用假明文，明天就会有人把
  "反正只是 Mock" 的样本导进评估集。

### 2.7 `model_meta()` MUST 委托 `ProviderIdentity.as_model_meta()`

MUST NOT 在本文件里手拼 dict（键名会与 `er.md` §6.1 分叉）。
`channel` 分别取 `"TEXT"` / `"VISION"` / `"OCR"`。

### 2.8 零网络依赖（**这是本任务的验收硬项**）

`mock.py` MUST NOT `import httpx` / `requests` / `aiohttp` / `socket` / `urllib*`。
`tests/unit/test_provider_mock.py` MUST NOT 发起任何真实网络请求。

---

## 3. 「断网可跑」的取证方式（**用户已选定，MUST 照此实现**）

无法真的拔网线，故用**可复核、可变异**的工程等价物：**断言测试全程零 socket 建连**。

在 `tests/unit/test_provider_mock.py` 里实现一个 **autouse fixture**：

```python
@pytest.fixture(autouse=True)
def _forbid_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, int]]]:
    """本文件内禁止任何 socket 建连；记下尝试过的目标以便诊断。"""
    attempts: list[tuple[str, int]] = []
    real_connect = socket.socket.connect

    def _spy(self: socket.socket, address: Any) -> Any:
        attempts.append(address if isinstance(address, tuple) else (str(address), 0))
        raise AssertionError(f"测试尝试建立网络连接：{address}（Task 4.2 要求全程无网络依赖）")

    monkeypatch.setattr(socket.socket, "connect", _spy)
    yield attempts
    assert attempts == [], f"本文件出现了 {len(attempts)} 次 socket 建连尝试：{attempts}"
```

**MUST 附带一条「这条断言真有判别力」的自证用例**：在测试内部临时把
`socket.socket.connect` 还原成真实实现（或直接调用未打桩的原始引用去连一个
**不可达地址** `127.0.0.1:1`），断言它确实引发了建连尝试并被记录。
——没有这条自证，「零建连」可能只是因为这段代码根本没被执行（假绿）。

---

## 4. 用例清单 `tests/unit/test_provider_mock.py`

1. **三通道基本调用**：TEXT `complete` / VISION `analyze` / OCR `recognize` 各跑一次，
   断言返回类型是 `ProviderResult`、`identity.channel` 正确、载荷字段互斥（§2.5）。
2. **确定性（同进程）**：同入参调 3 次 → 三次 `to_jsonable(result)` 完全相等。
3. **确定性（跨进程）**：用 `subprocess` 起一个新解释器跑同一入参（把输入与输出都
   经 argv/stdout 传递），断言与父进程结果一致。**这条是本任务的关键证据，MUST 有。**
4. **可注入延迟**：注入假 sleep，断言收到了预期秒数、且**没有真等**（用 `time.monotonic` 包住调用，
   断言墙钟耗时 < 0.1s）。
5. **延迟超时**：`latency_s=10, timeout_s=0.5` → 抛 `ProviderTimeoutError` 且 `exc.code == 5002`。
6. **三种故障**：`timeout` / `error` / `empty` 各一条，按 §2.3 的表断言。
7. **`on_call`**：`on_call=2` → 第 1 次正常、第 2 次抛、第 3 次正常。
8. **`call_count`**：调用 3 次后 `== 3`；故障调用也计数。
9. **脱敏**：所有产出 `value` 不含连续 15 位以上数字（§2.6）。
10. **置信度域**：所有 `confidence` ∈ [0,1] 或 `None`（§2.5）。
11. **`model_meta()` 键名**：与 `ProviderIdentity.as_model_meta()` 的输出**逐键相等**，
    且键集合恰为 `{channel, provider, modelVersion, promptVersion, thresholds}`（camelCase）。
12. **零 socket**：autouse fixture 的断言（§3）+ 判别力自证。
13. **Protocol 结构子类型**：断言 `isinstance(MockTextProvider(), TextProvider)` 等三条为真。
    **同时在用例 docstring 里写明这条的边界**：`@runtime_checkable` 只检查**成员是否存在**，
    **不检查签名**——签名一致性由 `mypy --strict` 保证，故本用例 MUST NOT 被当作
    「契约已验证」的唯一证据。

---

## 5. 验收（自证，**全部贴原始输出到报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_mock.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"    # 必须 880 passed, 8 skipped
.\.venv\Scripts\ruff.exe check --no-cache src/aicore/provider/mock.py tests/unit/test_provider_mock.py
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

- **MUST NOT `git commit`**、MUST NOT `git add`。
- `provider/` 包**允许**`import httpx`（`tests/structural/test_source_guards.py` 规则 5 对
  `provider/` 整包 skip），但本文件**不允许**（§2.8）。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.2-report.md`，含：
  逐项验收结论、**原始命令输出**、**偏离项 + 理由**、**没做到的事**（如实写，不美化）。
- 若发现**控制者给的接口有硬伤**（例如某签名在 3.14 上根本编译不过、或与 `base.py` 冲突），
  **MUST 停下来在报告里写明并停手**，MUST NOT 自行改 `base.py` / `results.py` / `errors.py`。

---

## 6. 探针纪律（第 3 组两次教训，写进流程）

**同一任务内新建的 `_probe*.py` / 临时脚本 > 2 个即视为失控**：
一旦第 3 个探针还没换来一份可交付产物，MUST 停下、先在报告里写明当前卡点。
第 3 组的两次实现者交接（`b158a9e3`、`73c4c5e6`）都栽在这条上（各写了 6 个 `_probe_recon*.py`）。
