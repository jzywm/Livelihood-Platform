# Review package — 第 4 组 P 阶段（未提交工作区，基于 `204801f`）

> 生成时间：2026-09-19。**本包描述的是未提交的工作区改动**，不是提交区间。
> 请用 `git diff HEAD` / `git status --porcelain` 自行复核，不要只信本包的清单。

## 1. 本包覆盖的任务

| 任务 | 交付物 | 用例数 |
|---|---|---|
| 4.1 Provider Protocol | `provider/results.py`、`provider/errors.py`、`provider/base.py` | 26（`test_provider_base_contract.py`）+ 17（`test_provider_results.py`） |
| 4.2 Mock Provider | `provider/mock.py` | 48（`test_provider_mock.py`） |
| 4.3 真实骨架与护栏 | `provider/guard.py`、`provider/_http.py`、`provider/{deepseek,cloud_vision,cloud_ocr}.py` | 31（`test_provider_guard.py`）+ 51（`test_provider_real.py`） |
| 4.4 Provider 选择器 | `provider/selector.py` | 35（`test_provider_selector.py`） |
| 配置（用户已批准） | `core/config.py` 4 个护栏字段 + `tests/unit/test_config.py` 的 `EXPECTED_FIELDS` + `.env.example` | 并入既有配置用例 |
| 控制者收尾修复 | `core/config.py` 的 `_is_blank` → 公开 `is_blank`（保留别名），`selector.py` 改用公开名 | 并入既有用例 |

## 2. 已跟踪文件的改动

```
 services/aicore/.env.example                       |   9 +
 services/aicore/src/aicore/core/config.py          |  65 ++-
 services/aicore/src/aicore/provider/base.py        | 108 +++-
 services/aicore/src/aicore/provider/cloud_ocr.py   | 336 +++++++++++-
 .../aicore/src/aicore/provider/cloud_vision.py     | 292 ++++++++++-
 .../aicore/src/aicore/provider/deepseek.py         | 297 ++++++++++-
 services/aicore/src/aicore/provider/mock.py        | 572 ++++++++++++++++++++-
 services/aicore/src/aicore/provider/selector.py    | 364 ++++++++++++-
 services/aicore/tests/unit/test_config.py          |   5 +
 9 files changed, 2030 insertions(+), 18 deletions(-)
```

## 3. 新增（未跟踪）文件清单

```
  97  services/aicore/src/aicore/provider/_http.py
  50  services/aicore/src/aicore/provider/errors.py
 248  services/aicore/src/aicore/provider/guard.py
 119  services/aicore/src/aicore/provider/results.py
 139  services/aicore/tests/unit/test_provider_base_contract.py
 464  services/aicore/tests/unit/test_provider_guard.py
 726  services/aicore/tests/unit/test_provider_mock.py
 762  services/aicore/tests/unit/test_provider_real.py
 176  services/aicore/tests/unit/test_provider_results.py
 562  services/aicore/tests/unit/test_provider_selector.py
```

**这些文件的正文不在本包内**（体积过大），请用 read 工具逐个读取。

## 4. 权威依据（评审时请对照，不要只看代码自洽）

| 内容 | 出处 |
|---|---|
| 三个 Protocol、Mock 默认、prod 禁用 Mock | `openspec/changes/implement-aicore-service/design.md` D3（L52-58） |
| 6 条分层禁止项 | 同上 L166-171 |
| 通道护栏四项数值（AI 5s / 重试 ≤5 / 熔断 50% / 半开 10s） | `docs/design/高并发架构演进设计.md` L260、L316、L317、L318、L423 |
| 「没等到响应」vs「等到了失败」 | `services/_common/openapi.yaml` L132-146 |
| 血缘键名 `{channel, provider, modelVersion, promptVersion, thresholds}` | `services/aicore/docs/er.md` §6.1 L295 |
| `OcrField` 键名 `fieldName`/`value`/`confidence` | `services/aicore/docs/openapi.yaml` L708-726 |
| 合规前置（未签协议 MUST NOT 调用该通道） | `specs/ai-core-service/spec.md` L86、L90-96 |
| 云视觉「协议:M2 前签署」 | `docs/design/产品设计文档.md` L1832 |
| 任务 4.1~4.4 的验收原文 | `openspec/changes/implement-aicore-service/tasks.md` L37-40 |

## 5. 控制者的独立验证记录（已做，供评审交叉核对，**不替代评审**）

控制者自建探针（用完即删）实测：

- **4.2**：同进程确定性、跨进程逐字节一致（真子进程对账）、载荷互斥、脱敏、置信度域 — 全 True。
- **4.3**：退避序列 `[1.0,2.0,4.0,8.0,16.0]`；4xx 不重试（send=1）；超时 5002 / 5xx 4003；
  熔断门在 send 之前（增量 0）；最小样本数；半开 `OPEN→HALF_OPEN`；`ValueError` 原样上抛。
- **4.3 合规门**：`cloud_vision`/`cloud_ocr` 返回 4003 `compliance-missing`，
  **`build_client` 与 HTTP 请求增量均为 0**；`deepseek` 放行（请求增量 1）。
- **4.4**：12 格选择矩阵逐格正确；**选不中的槽位为 `None` 且不回落到 Mock**；
  四个护栏参数在不同取值下精确透传；空凭据三种形态 fail fast 且点名环境变量。

## 6. 门禁现值（控制者复跑，请独立复跑核对）

```
pytest -m "not integration"   1088 passed, 12 skipped, 19 deselected
pytest -m "integration"       19 passed
覆盖率                         98.60%（门禁 80%）
ruff                           All checks passed!
mypy --strict                  Success: no issues found in 56 source files
lint-imports                   Contracts: 4 kept, 0 broken.
```

## 7. 已知未做到项（实现者主动登记，控制者确认属实，**请重点复核这些是否是"过得去的缺口"**）

1. **云通道的 `base_url` / 路径 / 请求体键名 / 鉴权头全是占位口径，未与任何真实厂商 API 校验过**；
   DeepSeek 同样未做真实调用验证。这是「不发出真实计费调用」的必然代价，**本阶段最大的未验证面**。
2. `identity.thresholds` 三通道都是 `{}` —— 置信度阈值字段尚不存在于 `Settings`，
   其所有者是 Task 4.10（G 阶段）。**后果**：`er.md` §6.1 要求的 `thresholds（high/medium）`
   快照目前无值可记。
3. `ProviderResult.raw` 一律不填（避免未脱敏证件值出域）；本层未记 `requestId`。
4. 无连接复用（一次调用一客户端），**性能代价未测**。
5. 高并发 L316 的「**慢调用** >阈值」未实现（`Settings` 无该字段）。
6. `main.py` **未接线** —— 「选择器已被进程真正使用」目前无证据。
7. `provider_max_retries` 只有等值断言，**没有行为断言**（重试次数真的变了的用例没写）。
8. `call_count` 语义 = 「方法被调用次数（**含被合规门/熔断挡下的那次**）」，需 Task 4.9 复核口径。
9. `tests/unit/test_provider_selector.py` 与 `test_provider_real.py` 存在**有意的代码重复**
   （`_SocketGuard`/`_FakeClock`/`_is_loopback`），因不许改既有测试文件而无法抽公共夹具。
10. **Task 4.4 的实现者自报探针纪律越界**：用了 3 个临时脚本（工单上限 2 个），
    均为只读探针、`$env:TEMP` 下用完即删。**请评审判断这是否需要返工。**

## 8. 本轮控制者自己犯的错（如实登记，供评审判断是否留下隐患）

**`pytest` 计数口径**：控制者曾在 4.4 工单里断言「`-o addopts=""` 不是必需的，两种写法都打印汇总行」，
并据此"证伪"了 Task 4.2 实现者的说法。**这个证伪是错的**：控制者当时比的是
「`-o addopts=""`」与「默认含 `-q`」，**没测双重 `-q` 这个真实形态**，而工单里写的正是双重 `-q`。
Task 4.4 的实现者提出更正，控制者复测确认：

| 写法 | 是否打印 `passed` 汇总行 |
|---|---|
| `-q`（`addopts` 已含 `-q`，叠加成 `-qq`） | 不打印 |
| `-o addopts="" -q` | 打印 |
| 完全不带 `-q` | 打印 |

**请评审复核本包 §6 的计数是不是用正确写法取到的。**

**另两处同类错误（同一天）**，请评审一并判断影响面：
- `type Channel = Literal[...]` 形式下 `get_args()` 返回**空元组**，故「用 `get_args` 现算比对」
  会退化成恒真/恒假断言（已改为 `Channel.__value__`，并加了前置断言把行为变化炸出来）。
- `provider/base.py` 的**行覆盖率 100% 是假的安全感**：三个 Protocol 方法体全是 `...`，
  跑一遍就 100%，签名一致性一个字都没验（已补 26 条 `inspect.signature` 相等用例 + 判别力自证）。
