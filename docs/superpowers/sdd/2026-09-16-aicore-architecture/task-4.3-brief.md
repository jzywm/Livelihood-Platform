### Task 4.3: 真实 Provider 骨架与通道护栏（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；用 write/edit 工具，MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写中文。
**Shell**：`sh` 不可用（`E_ACCESS_DENIED`），命令一律 PowerShell。

**Files:**
- Create: `src/aicore/provider/guard.py`（超时 / 重试 / 熔断三件套，**全通道共用**）
- Create: `src/aicore/provider/cloud_vision.py`（当前 1 行空壳）
- Create: `src/aicore/provider/cloud_ocr.py`（当前 1 行空壳）
- Create: `src/aicore/provider/deepseek.py`（当前 1 行空壳）
- Create: `src/aicore/provider/_http.py`（三者共用的 httpx 客户端工厂 + 请求构造）
- Create: `tests/unit/test_provider_guard.py`、`tests/unit/test_provider_real.py`
- **MUST NOT 改**：`provider/base.py`、`provider/results.py`、`provider/errors.py`、
  `provider/mock.py`、`provider/selector.py`、`core/config.py`、`pyproject.toml`、`.importlinter`、
  `tests/` 下的既有文件、`main.py`。

---

## 0. 先读这些（**MUST 用 read 工具完整读，不是 grep**）

**契约（控制者已定稿，MUST NOT 改）**
1. `src/aicore/provider/base.py` —— 三个 Protocol 的逐字签名。
2. `src/aicore/provider/results.py` —— `ProviderResult` / `ProviderIdentity` / `OcrField` / `to_jsonable`。
3. `src/aicore/provider/errors.py` —— 三个异常类的**逐字语义**（尤其熔断归 `4003` 的理由）。

**权威设计依据**
4. tasks.md **4.3 L39** 逐字：「实现真实 Provider 骨架与通道护栏（DeepSeek 文本 / 云视觉 / 云 OCR 的
   客户端封装与超时、重试、熔断，密钥经 KMS 或环境变量；**外部模型 HTTP 调用只允许出现在 `provider/` 包内**）；
   验证：以假密钥走通「构造请求—超时—熔断—返回 4003」链路用例，不发出真实计费调用；
   结构性断言 `httpx` 模型调用仅在 provider 包内」
5. `docs/design/高并发架构演进设计.md` **L260、L294、L316、L317、L318、L423**（超时分级 / 重试 / 熔断阈值的**唯一数值来源**）
6. `services/_common/openapi.yaml` **L132-146**（`DependencyTimeout` 对「没等到响应」vs「等到了失败」的区分）
7. spec.md **L86、L90-96**（合规前置；未取得协议 MUST NOT 调用该通道）
8. `docs/design/产品设计文档.md` **L1088、L1108、L1832、L1623**（视觉云签约与脱敏前置）
9. `deploy/sql/ddl/10_ai_task.template.sql` 的 `model_meta` 列注释
10. `services/aicore/docs/er.md` **§6.1 L295**（`model_meta` = `{channel, provider, modelVersion, promptVersion, thresholds（high/medium）}`）

---

## 1. 数值口径（**已由用户定档，MUST 照此，MUST NOT 自己另选**）

四项护栏参数**已经**加进 `core/config.py`（控制者已完成，**MUST NOT 再改**）：

| 字段 | 默认 | 权威出处 |
|---|---|---|
| `ai_call_timeout_s` | `5.0` | 高并发 §4.4 L317 / §7.6 L423「AI 5s」 |
| `provider_max_retries` | `5` | 高并发 L260 / L318「幂等接口 ≤5 次指数退避」 |
| `circuit_error_ratio` | `0.5` | 高并发 L316「错误率 >50% … 熔断」 |
| `circuit_cooldown_s` | `10.0` | 高并发 L316「半开探测间隔 10s」 |

退避基数取 **1s**、公比 **2**（高并发 L260 逐字「指数退避（1s→2s→4s… 上限 5 次）」）。

---

## 2. `provider/guard.py` 交付接口（签名逐字）

```python
@dataclass(frozen=True, slots=True)
class GuardConfig:
    timeout_s: float
    max_retries: int          # 不含首次
    error_ratio: float        # 熔断阈值
    cooldown_s: float         # 半开探测间隔
    backoff_base_s: float = 1.0
    backoff_factor: float = 2.0

class StepClock(Protocol):
    """可注入时钟。**测试里 MUST NOT 真等**，故时钟与睡眠都必须可替换。"""
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...

def system_clock() -> StepClock: ...

class CircuitBreaker:
    """按 (provider, operation) 维度计的滑动窗口熔断器。"""
    def __init__(self, config: GuardConfig, *, clock: StepClock | None = None) -> None: ...
    def before_call(self, provider: str, operation: str) -> None:
        """打开态时抛 ProviderCircuitOpenError（**在发请求之前**）。"""
    def record_success(self, provider: str, operation: str) -> None: ...
    def record_failure(self, provider: str, operation: str) -> None: ...
    def state_of(self, provider: str, operation: str) -> Literal["CLOSED", "OPEN", "HALF_OPEN"]: ...

async def guarded_call(
    *,
    provider: str,
    operation: str,
    config: GuardConfig,
    breaker: CircuitBreaker,
    send: Callable[[], Awaitable[Any]],
    clock: StepClock | None = None,
) -> Any:
    """超时 + 指数退避重试 + 熔断；把底层异常归一为 provider/errors.py 的三类。"""
```

### 2.1 `guarded_call` 的**精确**行为（每条都要有用例）

1. **熔断门在最前**：`breaker.before_call()` 在 `send` **之前**调用。
   因此熔断打开时 **`send` 一次都不会被调用** —— 这是可断言的（用例里 `send` 挂一个计数）。
2. **超时**：每次尝试用 `asyncio.wait_for(send(), timeout=config.timeout_s)`；
   超时 → 记失败 → 若还有重试次数则退避后重试，否则抛
   `ProviderTimeoutError(provider, operation, reason="timeout")`。
3. **可重试的失败**：底层抛 `httpx.TimeoutException` → 按超时处理；
   抛 `httpx.TransportError` / `httpx.HTTPStatusError`（5xx）/ **429** → 记失败 + 退避重试；
   抛 `httpx.HTTPStatusError`（**4xx 且非 429**）→ **MUST NOT 重试**（客户端错误重试无意义），
   立即抛 `ProviderChannelFailureError(reason=f"http-{status}")`。
   **`ValueError` / `TypeError` 之类编程错误 MUST NOT 被吞成通道失败** —— MUST 原样上抛
   （吞掉会让 bug 变成"通道故障"，运维白查一天）。用例 MUST 覆盖这一条。
4. **退避**：第 n 次失败后睡 `backoff_base_s * backoff_factor ** (n - 1)` 秒（n 从 1 起）。
   **通过注入的 `clock.sleep`**，MUST NOT 直接 `asyncio.sleep`。
   用例断言**睡眠序列**逐项相等（如 `[1.0, 2.0, 4.0, 8.0, 16.0]`），而不是断言"大概退避了"。
5. **重试耗尽**：抛最后一次的异常类型（超时 → `ProviderTimeoutError`；5xx → `ProviderChannelFailureError`）。
6. **熔断打开后**：`cooldown_s` 内所有调用直接抛 `ProviderCircuitOpenError`；
   超过 `cooldown_s`（用注入时钟推进）后进入 `HALF_OPEN`，**放行一次**探测：
   成功 → 回 `CLOSED` 并清窗口；失败 → 回 `OPEN` 并重置冷却计时。
7. **窗口口径**（MUST 写进 docstring 并有用例）：至少 `MIN_SAMPLES = 5` 次调用才判熔断，
   且错误率 `> config.error_ratio`（**严格大于**，不是 ≥，对齐 L316 的「>50%」）。
   **为什么要有最小样本数**：只有 1 次调用失败时错误率就是 100%，直接熔断等于
   「首次抖动即熔断」，把瞬时故障放大成可用性事故。

### 2.2 时钟与睡眠的注入纪律

`system_clock()` 用 `time.monotonic()` + `asyncio.sleep`。
**测试 MUST 用 `FakeClock`**（在用例文件里实现），`monotonic()` 返回可控值、`sleep()` 累加虚拟时间。
依据：`tests/conftest.py` 文件头逐字「测试内 MUST NOT 出现任意 sleep；等待一律走轮询断言或注入的时钟」。
用例 MUST 断言整条用例的**墙钟耗时 < 0.5s**（证明没有真睡）。

---

## 3. 三个真实通道（`deepseek.py` / `cloud_vision.py` / `cloud_ocr.py`）

### 3.1 共同要求

- 类名：`DeepSeekTextProvider` / `CloudVisionProvider` / `CloudOcrProvider`。
- `name` 分别为 `"deepseek"` / `"cloud_vision"` / `"cloud_ocr"`（**逐字对齐
  `config.py` 的 `provider` 字面量与 `.env.example` 注释**）。
- `model_version` / `prompt_version` 用模块级常量，取值须带通道前缀（如 `"deepseek-chat-v1"`）。
- 构造函数签名：`__init__(self, config: Settings, *, breaker: CircuitBreaker | None = None, clock: StepClock | None = None) -> None`
  —— `Settings` 从 `aicore.core.config` 导入（`provider → core` 合法；**反向不允许**）。
- 三个类**都**要实现 `model_meta()`，**委托 `ProviderIdentity.as_model_meta()`**，MUST NOT 手拼 dict。
- 三个类**都**要有 `call_count` 属性（供 Task 4.9 断言幂等不增加调用）。

### 3.2 `_http.py`：**唯一**构造 httpx 客户端的地方

```python
def build_client(*, base_url: str, api_key: str, timeout_s: float) -> httpx.AsyncClient: ...
```

- MUST 用 `httpx.AsyncClient`，MUST 设 `timeout=httpx.Timeout(timeout_s)`。
- 密钥**只经请求头传递**，MUST NOT 进 URL query、MUST NOT 进日志、MUST NOT 进异常消息。
  用例 MUST 断言「把假密钥传进去后，异常消息、日志与 `repr(client)` 里都不含该密钥」。
- **MUST NOT 用真实的计费地址做默认值**：`base_url` 必须由调用方给出，
  三个通道各自有一个**模块级默认常量**（如 `DEFAULT_DEEPSEEK_BASE_URL`），
  但**这些常量 MUST NOT 被用作构造客户端的唯一来源** —— 见 §3.4 的假地址要求。

### 3.3 请求/响应解析

- `DeepSeekTextProvider.complete`：POST `/chat/completions`，体含 `model`、`messages`；
  解析 `choices[0].message.content` → `ProviderResult.text`，`confidence` 取通道返回值，
  **缺失则为 `None`（MUST NOT 补 0）**。
- `CloudVisionProvider.analyze`：POST 一个视觉接口路径，体含 `image_key`、`labels`；
  解析出 `markers`（`tuple[Mapping[str, Any], ...]`，每项至少 `label` / `level` / `confidence`）。
- `CloudOcrProvider.recognize`：POST 一个 OCR 接口路径，体含 `image_key`、`doc_type`；
  解析出 `fields`（`tuple[OcrField, ...]`）。
- **响应解析 MUST 对畸形响应显式失败**（缺字段 / 类型不对 → `ProviderChannelFailureError(reason="malformed-response")`），
  MUST NOT 静默返回空结果。用例 MUST 覆盖「响应体缺字段」这一条。
- **解析出的 `value` MUST 做脱敏保护**：若通道返回的字段值是连续 15 位以上数字，
  MUST 就地脱敏（中间打星）后才放进 `OcrField.value`。依据：`er.md` §6.2 要求 `value` 是「脱敏输出」；
  spec.md:100「MUST NOT 以任何形式向外部模型供应商上传用户数据以改进其模型」与 :243-246
  「日志中不出现未脱敏的证件字段值」。用例 MUST 覆盖。

### 3.4 **不发出真实计费调用**（Task 4.3 的验收硬项）

用例 MUST 用 `httpx.MockTransport`（**httpx 自带，无需新依赖**）把请求拦截掉：

```python
transport = httpx.MockTransport(handler)
```

- **所有**用例都 MUST 经 `MockTransport`，**MUST NOT** 有任何一条用例走真实网络。
- 用例文件 MUST 有 autouse fixture：断言测试全程**未发生真实 socket 建连**
  （做法同 Task 4.2 工单 §3：`monkeypatch.setattr(socket.socket, "connect", _spy)`），
  并附一条「判别力自证」（证明这个桩真的会拦住东西）。
- 用例 MUST 断言：① 请求**确实被构造出来**（handler 收到了 `request.method` / `url` /
  `headers`）；② 请求头里**有**假密钥；③ 请求体里**有**假 image_key。

### 3.5 **合规门（用户已定档的加固项，MUST 实现）**

spec.md:86 逐字：「送往云视觉 API 的图像 MUST 处于已签署的数据合规协议之下…
合规协议状态 MUST 可被核对，**未取得协议时系统 MUST NOT 调用该通道**」；
spec.md:95-96 逐字：「某外部通道的数据合规协议未生效或已过期 → 系统**拒绝调用该通道并告警**，
不以外发图像的方式继续处理」。

当前配置里云通道**没有**合规字段（`core/config.py` 的
`_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 明确标注它们"暂无密钥字段"）。故实现为：

- 每个通道有一个模块级常量 `COMPLIANCE_READY: bool`，取值与依据写进 docstring：
  - `deepseek.py` → **`True`**（依据：`docs/design/产品设计文档.md:1623` 与需求 29 L43
    「与 DeepSeek 对话数据口径一致」已评审通过）
  - `cloud_vision.py` / `cloud_ocr.py` → **`False`**（依据：`产品设计文档.md:1832`
    逐字「协议:**M2 前签署**」——M1 尚未签署）
- 通道方法在**构造请求之前**检查：`if not COMPLIANCE_READY: 记 WARNING 日志 + 抛
  ProviderChannelFailureError(self.name, "<方法名>", reason="compliance-missing")`。
- **可核方式（本工单的核心负向证据，MUST 有）**：用例断言合规未就绪时
  **HTTP transport 的 handler 一次都没被调用**（用计数器，断言 `== 0`）。
- **MUST NOT 用一个「异常后继续执行」的分支来"兼容"合规未就绪** —— 那正是
  design.md:171 禁止项 6 的形态（虽然它只硬约束 `service/desensitize.py` 与
  `service/verdict.py` 两个文件，但本处的取向相同）。若确实需要吞异常，
  MUST 在该 `except` 行写 `# ai-allow-swallow: <理由>`。
- docstring MUST 写明：**M1 的云通道在合规门打开前不可用于真实调用**，
  它的存在意义是「契约与护栏可测」而不是「可用」。`pyproject.toml` 已把这三个文件
  列入 coverage omit（依据 design.md:284「真实通道骨架允许排除」），别去动那个配置。

---

## 4. 用例清单

### `tests/unit/test_provider_guard.py`
1. 熔断门在 `send` 之前：连续失败 5 次打开熔断后，第 6 次的 `send` 计数**不增加**。
2. 退避序列逐项相等（假时钟）：`[1.0, 2.0, 4.0, 8.0, 16.0]`。
3. 超时 → `ProviderTimeoutError` 且 `code == 5002`。
4. 5xx 重试耗尽 → `ProviderChannelFailureError` 且 `code == 4003`。
5. 4xx（非 429）**不重试**（`send` 只被调用 1 次）。
6. 429 → 会重试。
7. `ValueError` 从 `send` 抛出时**原样上抛**，不被转成通道失败。
8. 最小样本数：只有 1 次失败时 `state_of(...) == "CLOSED"`。
9. 半开：推进假时钟过 `cooldown_s` 后 `state_of(...) == "HALF_OPEN"`；探测成功后回 `CLOSED`。
10. 半开探测失败 → 回 `OPEN`，且冷却重新计时。
11. 整条用例墙钟耗时 < 0.5s（证明没真睡）。

### `tests/unit/test_provider_real.py`
1. 三通道各走一次 `MockTransport` 成功链路：断言请求方法/URL/头/体，断言解析结果正确。
2. 三通道各走「超时」链路（handler 里 `raise httpx.TimeoutException`）→ `5002`。
3. 三通道各走「熔断」链路（先打满失败打开熔断）→ `4003` 且 **handler 未被再次调用**。
4. 畸形响应（缺字段）→ `ProviderChannelFailureError(reason="malformed-response")`。
5. 密钥不泄漏（§3.2）。
6. 脱敏保护（§3.3）。
7. **合规门**：`cloud_vision` / `cloud_ocr` 的 handler 计数为 `0` + 抛 `4003` + 有 WARNING 日志；
   `deepseek` 的合规门为 `True`（正常发起请求）。
8. 零真实 socket（autouse fixture + 判别力自证）。
9. `model_meta()` 键名与 `ProviderIdentity.as_model_meta()` 逐键相等。
10. **Protocol 结构子类型**：`isinstance(obj, TextProvider/VisionProvider/OcrProvider)` 三条为真，
    并在 docstring 写明该断言**不检查签名**、签名一致性靠 `mypy --strict`。
11. **不依赖任何供应商 SDK**（tasks.md 4.3 的验收项）：断言三个通道文件的源码里
    **不含** `openai` / `anthropic` / `dashscope` / `volcengine` / `zhipu` / `baidu` /
    `tencentcloud` / `aliyun` 等厂商 SDK 的 import。

---

## 5. 验收（自证，**原始输出全部贴报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_guard.py tests/unit/test_provider_real.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"      # 必须 880 passed, 8 skipped
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/structural/test_source_guards.py   # 规则 5 必须仍绿
.\.venv\Scripts\ruff.exe check --no-cache src/aicore/provider/ tests/unit/test_provider_guard.py tests/unit/test_provider_real.py
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

- 覆盖率：这三个真实通道文件**已在 `pyproject.toml` 的 coverage omit 里**，
  但 `guard.py` 与 `_http.py` **不在** —— 故这两个文件的覆盖率由你的用例保证。
  跑一次 `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration" --cov --cov-report=term-missing`
  并把**总覆盖率**与 `guard.py` / `_http.py` 两行的数字贴进报告（门禁 ≥80%）。
- **MUST NOT `git commit` / `git add`**。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.3-report.md`。

---

## 6. 纪律

- 探针纪律：新建临时脚本 > 2 个即停下报告（第 3 组两次实现者交接都栽在这条）。
- 若发现控制者给的接口有硬伤（签名编译不过、与 `base.py` 冲突、`Settings` 里没有你需要的字段），
  **停下并在报告里写明**，MUST NOT 自行改契约文件或 `core/config.py`。
- 报告 MUST 有「**没做到的事**」一节，如实写。第 3 组的评审专门查这个：把未验证项写成"应该没问题"会被抓出来。
