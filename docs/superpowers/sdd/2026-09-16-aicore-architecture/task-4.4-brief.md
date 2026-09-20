### Task 4.4: Provider 选择器（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM；用 write/edit 工具，MUST NOT 用 PowerShell `Set-Content`/`Out-File` 写中文。
**Shell**：`sh` 不可用，命令一律 PowerShell。

**Files:**
- Create: `src/aicore/provider/selector.py`（当前 1 行空壳）
- Create: `tests/unit/test_provider_selector.py`
- **MUST NOT 改**：`provider/base.py`、`provider/results.py`、`provider/errors.py`、
  `provider/guard.py`、`provider/_http.py`、三个真实通道文件、`core/config.py`、
  `pyproject.toml`、`.importlinter`、`tests/` 下的既有文件、`main.py`。

---

## 0. 先读这些（MUST 用 read 工具完整读）

**契约**
1. `src/aicore/provider/base.py` —— 三个 Protocol。
2. `src/aicore/provider/results.py` —— `Channel`（**只有 3 个成员：TEXT / VISION / OCR**）。
3. `src/aicore/core/config.py` 的 **`provider` 字段与 `_REAL_PROVIDER_KEY_FIELDS` /
   `_REAL_PROVIDERS_WITHOUT_KEY_FIELD`**，以及 `provider` / `deepseek_api_key` /
   `ai_call_timeout_s` / `provider_max_retries` / `circuit_error_ratio` / `circuit_cooldown_s` 六个字段。

**权威依据**
4. tasks.md **4.4 L40** 逐字：「实现 Provider 选择器（`provider/selector.py`，按配置选择通道，
   与 2.2 的启动校验衔接）；验证：**三种环境下的选择结果用例通过、选择逻辑不读取业务参数**」
5. design.md **L143**（`selector.py 按配置选择通道`）、**L54**（D3：三个 Protocol、`mock` 默认、
   `env=prod` + `mock` 拒绝启动）、**L247-249**（启动校验四条）
6. spec.md **L18-21**（通道可替换：换供应商时**调用方接口契约与业务逻辑无须改动**）
7. `tests/unit/test_config_startup.py` 的 `test_every_real_provider_is_registered_in_a_channel_table`
   （通道登记表的结构守卫）—— 你的实现 MUST NOT 破坏它

---

## 1. **先理解一个关键裁定，否则你会写错**

`Settings.provider` 是**单值** `Literal["mock","deepseek","cloud_vision","cloud_ocr"]`。
**这是对的，不是缺陷**：design.md L54 / L142 与 tasks.md L37 都只定义 **3 个** Protocol，
design.md L145 规划的真实通道文件只有 3 个；spec.md L11 说的「四类通道」里的
**「平台自建预测」在 M1 没有实现**，design.md L26 逐字「不实现 K-03/K-04/K-05/K-06 的业务逻辑
（只保留任务类型枚举与通道路由扩展位）」，L192 把它登记为 `RISK_PREDICT` 的**预留注册位**。

**因此**：`mock` 一个实现同时充当三个通道（Task 4.2 已交付 `MockTextProvider` /
`MockVisionProvider` / `MockOcrProvider`）；`deepseek` 提供 TEXT 通道；`cloud_vision` 提供
VISION 通道；`cloud_ocr` 提供 OCR 通道。

**MUST NOT 因为「一个 provider 要覆盖三个通道」就去改 `core/config.py` 加字段**
（那会撞 `test_env_example_matches_field_names_one_to_one` 与 `EXPECTED_FIELDS`）。
若你认为这个设计有问题，**在报告里写明并停手**，不要自行改配置。

---

## 2. 交付接口（签名逐字）

```python
@dataclass(frozen=True, slots=True)
class Providers:
    """一次选择的结果：三个通道的可调用对象（未选中的为 None）。"""
    text: TextProvider | None
    vision: VisionProvider | None
    ocr: OcrProvider | None

def select_providers(
    config: Settings,
    *,
    breaker: CircuitBreaker | None = None,
    clock: StepClock | None = None,
) -> Providers: ...
```

**`select_providers` 是纯函数式选择**：只读 `config`，**MUST NOT** 读任何业务参数
（account_id / task_id / merchant_id / doc_type / image_key / 请求头）。

### 2.1 选择矩阵（MUST 逐格实现，含 `None` 的格子）

| `config.provider` | TEXT | VISION | OCR |
|---|---|---|---|
| `mock` | `MockTextProvider` | `MockVisionProvider` | `MockOcrProvider` |
| `deepseek` | `DeepSeekTextProvider` | **`None`** | **`None`** |
| `cloud_vision` | **`None`** | `CloudVisionProvider` | **`None`** |
| `cloud_ocr` | **`None`** | **`None`** | `CloudOcrProvider` |

**为什么「选不中的通道返回 `None` 而不是回落到 mock」**（MUST 写进 docstring，这是本任务
最容易写错的地方）：在 `provider=cloud_ocr` 的部署里悄悄给 VISION 通道塞一个 mock，
意味着**生产上视觉审核的结论会来自模拟实现** —— 正是 design.md L56 说的
「生产环境自动降级 Mock 会造成更严重的合规事故（等于用假数据伪造 AI 结论并进入人工复核）」。
故**不回落**：调用方拿到 `None` 时必须自己决定（报 `4003` 转人工，或该任务类型根本不该跑）。
这条与本项目「宁可拒绝也不静默降级」的既有取向一致（同 `mysql_readonly_host` 只认 `None` 的做法）。

### 2.2 与启动校验（Task 2.2）的衔接

`env=prod` + `provider=mock` 与「真实通道缺密钥」两类组合**已在 `Settings` 构造期拒绝**
（`_reject_invalid_startup_combination`）。故选择器**MUST NOT 重复实现这两条**，
但 MUST 在**被选中通道的凭据为空**时 fail fast：

- `provider=deepseek` 且 `config.deepseek_api_key` 为 `None`/空串/纯空白 →
  抛 `ValueError`（**不是** `ProviderChannelFailureError`：这属**装配期配置错误**，
  应在启动/装配阶段炸，而不是伪装成一次"通道调用失败"让任务转人工）。
  `_is_blank` 的判定口径与 `core/config.py` 保持一致（None / 空串 / 纯空白都算没配）。
- `cloud_vision` / `cloud_ocr` 的凭据字段**当前不存在**（`_REAL_PROVIDERS_WITHOUT_KEY_FIELD`
  明确标注），故选择器**MUST NOT** 为它们凭空查一个不存在的字段 —— 查了会 `AttributeError`。
  它们的合规门由通道实现内部承担（Task 4.3 已交付），选择器只负责选出来。

### 2.3 护栏配置的传递（MUST）

`select_providers` MUST 把 `config` 的四个护栏字段组装成 `GuardConfig` 传给真实通道：

```python
GuardConfig(
    timeout_s=config.ai_call_timeout_s,
    max_retries=config.provider_max_retries,
    error_ratio=config.circuit_error_ratio,
    cooldown_s=config.circuit_cooldown_s,
)
```

**MUST NOT 把默认值写死在选择器里**：那样「超时可配」就只是一句话
（Task 4.6 要求处理器声明自身超时、Task 4.11 要求降级可观测，两者都依赖配置侧能调）。
用例 MUST 断言「改 `config.ai_call_timeout_s` 后，选出来的通道用的就是新值」
—— 通过把 `MockTransport` 或假时钟的行为与超时值关联起来断言，**不是**只断言对象存在。

### 2.4 熔断器共享（MUST）

`breaker` 参数默认为 `None`，此时为**整套选择结果共享一个** `CircuitBreaker` 实例
（三个通道共用；熔断按 `(provider, operation)` 维度隔离，故共用是安全的）。
调用方传入自己的 `breaker` 时 MUST 用它。

**为什么默认共享**：熔断状态是**进程级**的健康判断，每个通道各造一个会让
「deepseek 挂了」这件事对已存在的实例不可见。但 MUST NOT 用模块级全局单例 ——
那会让测试之间互相污染（第 3 组刚吃过 `fileConfig` 禁用全部日志器导致 17 条用例红的教训）。

### 2.5 `provider/__init__.py`（MUST 保持原样）

**MUST NOT** 在 `provider/__init__.py` 里再导出任何东西（包括 `select_providers`）。
理由：`.importlinter` 契约 2 把 `aicore.provider` **整包**列为 `service` 的 forbidden，
`service` 只允许依赖 `aicore.provider.base`。往门面里加导出会让
`service` 通过 `import aicore.provider` 拿到选择器，绕过分层边界
—— `.importlinter` 的注释里对此有实测记录（`test_provider_facade_reexport_is_forbidden`）。
`main.py` 组合根直接 `from aicore.provider.selector import select_providers`。

---

## 3. 用例清单 `tests/unit/test_provider_selector.py`

1. **四行选择矩阵逐格**：`mock` / `deepseek` / `cloud_vision` / `cloud_ocr` 各构造一次
   `Settings`，断言三个槽位的类型与 `None` 情况**逐格**与 §2.1 的表一致。
   `None` 的格子 MUST 显式断言 `is None`（**不是**只断言非 None 的那些）。
2. **三环境**（tasks.md 4.4 的验收项）：`env` 取 `dev` / `test` / `prod` × `provider` 取
   `mock` / `deepseek` 的组合，断言：
   - `dev`/`test` + `mock` → 选择成功；
   - `prod` + `mock` → `Settings` 构造期就抛 `ValidationError`（**这条断言的是启动校验，
     不是选择器**，docstring 里 MUST 写明分工，避免后人以为选择器也该拦）；
   - `prod` + `deepseek`（带密钥）→ 选择成功。
3. **不读业务参数**（tasks.md 4.4 的验收项，**这是本任务的核心结构断言**）：
   用 AST 解析 `selector.py` 源码，断言其中**不出现**以下任一标识符：
   `account_id`、`task_id`、`merchant_id`、`doc_type`、`image_key`、`request`、`headers`、
   `trace_id`、`idem_key`。
   **同时在 docstring 里写明这条断言的边界**：AST 扫标识符是**弱断言**（改名就绕过），
   真正的保证是「签名里根本没有这些参数」—— 故 MUST 额外断言
   `inspect.signature(select_providers)` 的参数名集合恰为 `{"config", "breaker", "clock"}`。
4. **护栏配置真的透传**（§2.3）：改 `config.ai_call_timeout_s` / `provider_max_retries` /
   `circuit_error_ratio` / `circuit_cooldown_s` 四个值，断言选出的真实通道实例内部
   持有的 `GuardConfig` 四个字段**逐项等于**新值。
   （若真实通道没暴露 `_guard` 之类的读取入口，**不要为了测试去加公开属性** ——
   改用 `MockTransport` 让请求超时，按假时钟推进的耗时反推 `timeout_s`。
   哪种做法你自己定，但 MUST 在报告里写明选了哪种以及为什么。）
5. **`mock` 不构造任何 HTTP 客户端**：断言 `provider=mock` 时选出的三个实例
   **不含** `httpx` 客户端属性（用 `httpx` 的类做 `isinstance` 扫描实例的 `__dict__` 值）。
6. **真实通道缺密钥 fail fast**（§2.2）：`provider=deepseek` 且 `deepseek_api_key=None`
   / `""` / `"   "` 三种 → 各抛 `ValueError`，且消息里点名 `AICORE_DEEPSEEK_API_KEY`。
7. **`cloud_*` 不查不存在的字段**（§2.2）：`provider=cloud_vision` / `cloud_ocr` 时
   `select_providers` MUST NOT 抛 `AttributeError`（断言能正常返回）。
8. **熔断器共享**（§2.4）：断言两次调用 `select_providers(config)` 得到的
   `CircuitBreaker` 是**不同实例**（无模块级单例），而**同一次**返回的三个通道共享同一实例。
9. **`None` 召回不回落**（§2.1 的核心负向证据）：
   在 `provider=cloud_ocr` 下断言 `providers.text is None and providers.vision is None`
   —— 并附一条「判别力自证」：证明如果实现改成回落 mock，这条断言会红
   （做法：在用例内构造一个"会回落"的假实现并断言它给出非 None，从而证明断言方向正确）。
10. **`provider/__init__.py` 没有新增导出**（§2.5）：
    断言 `import aicore.provider` 后**不**存在 `aicore.provider.select_providers` 属性。

---

## 4. 验收（自证，**原始输出全部贴报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_selector.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not integration"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/structural/          # 含分层与源码守卫
.\.venv\Scripts\ruff.exe check --no-cache src/aicore/provider/selector.py tests/unit/test_provider_selector.py
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter                                # 必须 4 kept, 0 broken
```

### 关于「全量计数」的两个**已实测**口径（控制者第二次更正，MUST 照此读结果）

1. **全量数字会变，不要拿固定值当验收判据**。控制者实测：`-m "not integration"` 的 passed
   数随各任务落地而增长，其中 `skipped` 也会涨——因为
   `tests/structural/test_source_guards.py` 的规则 5 对 `provider/` 下**每个 `.py` 各 skip 一条**。
   故你只需断言 **EXIT=0 且 failed == 0**，MUST NOT 断言某个固定计数。
2. **要看到最终汇总计数行，MUST 写 `-o addopts=""`（或**不要**再加命令行 `-q`）**。
   控制者实测三种写法（同一条命令）：

   | 写法 | 是否打印 `passed` 汇总行 |
   |---|---|
   | `-q`（pyproject `addopts` 已含 `-q`，叠加成 `-qq`） | **不打印**（只有 `[100%]`） |
   | `-o addopts="" -q` | 打印 |
   | 完全不带 `-q` | 打印 |

   **控制者此前在本工单里断言过「`-o addopts=""` 不是必需的，两种写法都打印汇总行」，
   那是错的**：我当时比的是「`-o addopts=""`」与「默认含 `-q`」，**没测双重 `-q` 这个真实形态**——
   而工单 CMD 里写的正是双重 `-q`。Task 4.4 的实现者据此提出更正，控制者复测后确认他对、我错。
   故：**先按工单 CMD 原样跑（拿 EXIT 码），再补 `-o addopts=""` 取计数**，两种原始输出都贴报告。



- **MUST NOT `git commit` / `git add`**。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.4-report.md`，
  含逐项验收结论、原始输出、**偏离项 + 理由**、**没做到的事**。

---

## 5. 依赖与顺序

`selector.py` 要 import 三个真实通道与 mock，故 **Task 4.2 / 4.3 的产物必须先存在**。
若你开工时发现 `provider/mock.py` 或 `provider/cloud_*.py` 仍是 1 行空壳，
**MUST 停下来在报告里写明并停手**（不要自己造它们的实现——那会与并行的实现者冲突）。
可以先写完 `selector.py` 的框架与用例，再回来补验证？→ **不行**：MUST 等依赖到位，
一次性交付并跑通全部验收。等不到就在报告里写「阻塞于 Task 4.2/4.3」。

## 6. 纪律

- 探针纪律：新建临时脚本 > 2 个即停下报告。
- 若发现控制者给的接口有硬伤，**停下并在报告里写明**，MUST NOT 自行改契约或配置。
- 报告 MUST 有「**没做到的事**」一节，如实写。
