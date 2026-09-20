### Task 4.5: 任务提交与状态机（步骤级工单）

**Worktree**：`D:\progrom\.worktrees\aicore-architecture`，服务根 `services/aicore/`。
**Python**：`.venv\Scripts\python.exe`（3.14.6）。**MUST NOT `pip install`**。
**编码**：UTF-8 无 BOM / LF；用 write/edit 工具，**MUST NOT** 用 PowerShell `Set-Content`/`Out-File` 写中文。
**Shell**：`sh` 不可用（`E_ACCESS_DENIED`），命令一律 PowerShell；**每个 pwsh 调用前先 `$env:PYTHONUTF8='1'`**。
pytest 加 `-p no:cacheprovider`；**要看 `passed` 计数行必须写 `-o addopts=""`**
（`addopts` 已含 `-q`，叠加成 `-qq` 会吞掉汇总行）。

**Files:**
- Modify: `src/aicore/api/ocr.py`、`src/aicore/api/tasks.py`、`src/aicore/api/deps.py`、`src/aicore/main.py`（挂路由）
- Create: `src/aicore/service/task/state.py`（状态机，纯函数）、`src/aicore/service/task/submit.py`（提交编排）
- Create: `tests/api/test_ocr_submit.py`、`tests/api/test_task_poll.py`、`tests/unit/test_task_state.py`
- **MUST NOT 改**：`provider/**`、`repository/**`、`core/config.py`、`core/errors.py`、`core/envelope.py`、
  `pyproject.toml`、`.importlinter`、`tests/` 下的既有文件、`tests/conftest.py`。

---

## 0. 先读这些（**MUST 用 read 工具完整读，不是 grep**）

**接口契约（唯一可手改源）**
1. `docs/openapi.yaml` 的 `/aicore/ocr`（L44-106）与 `/aicore/tasks/{taskId}`（L107-155）
2. `docs/openapi.yaml` 的 `OcrRequest`（L696-707）、`TaskAccepted`（L774-786）、
   `TaskResult`（L787-825）、`TaskType`（L764-768）、`TaskStatus`（L769-773）
3. `services/_common/openapi.yaml` 的 `Envelope`（L150-165）与 `ErrorCode`（L178-209）

**设计依据**
4. `openspec/changes/implement-aicore-service/design.md` **§接口分类与任务契约 L175-194**
   （`POST /aicore/ocr` 落 `ai_task`；轮询仅限本人；跨账号 `2002`）、
   **§数据层落地 L214-227**（写后立即读走主库）
5. `services/aicore/docs/er.md` **§6.1 L284-298**（`ai_task` 数据字典）、
   **§7.1 L425-435**（索引 / 约束 / 状态机）、**§5.2 L217**（按月分表）、
   **§5.5 L252**（「写后立即读」强制走主库）
6. `specs/ai-core-service/spec.md` **L23-40**（异步任务队列与结果回执三个 Scenario：
   受理即返回任务号、跨账号查询被拒 `2002`、重复提交幂等）

**既有实现（MUST 复用，不得重造）**
7. `src/aicore/core/idgen.py`（`new_id("task")`）、`src/aicore/repository/task_repo.py`
   （`insert` / `get_by_id` / `update_status` / `find_by_idem_key`）、
   `src/aicore/repository/session.py`（会话与引擎）、`src/aicore/repository/sharding.py`（分片键）
8. `src/aicore/api/deps.py`、`src/aicore/core/envelope.py`、`src/aicore/core/errors.py`（异常层次与信封）

---

## 1. 身份来源（**权威口径，MUST 照此，不得自创**）

网关是唯一鉴权点，验签后**先剥离客户端伪造头、再写入**四头身份：

```
services/gateway/src/main/java/com/msz/gateway/filter/JwtAuthFilter.java
  :22    四头身份透传（X-User-Id / X-User-Role / X-User-Mfa / X-User-Jti）
  :90-93 headers.remove(USER_ID_HEADER) 等四行 —— 先剥离客户端伪造值
  :96    builder.header(USER_ID_HEADER, sub)   —— 只写验签后的 JWT sub
  :75-76 jti 撤销检查
services/acc/src/main/java/com/msz/acc/infrastructure/auth/TrustedHeaderAuthFilter.java
  :23    身份头（与网关 JwtAuthFilter 写入口径一致）：X-User-Id(JWT sub)
  :27    受保护路径缺少 X-User-Id → 401 + code 2001（fail-closed）
```

**故**：
- 本服务的 `account_id` **取请求头 `X-User-Id`**，它是验签 JWT 的 `sub`，客户端无法伪造；
- **缺失 / 空串 / 纯空白 → `UnauthorizedError`（`2001`，HTTP 401）**，fail-closed。
  MUST NOT 回落成「匿名账号」或默认账号——那会让每个未鉴权请求都写进某个真实账号的任务表；
- **MUST NOT 信任自造头**，本任务只用 `X-User-Id`。

**头名常量落点**：在 `api/deps.py` 定义 `ACCOUNT_ID_HEADER: Final = "X-User-Id"`，
MUST NOT 在各路由里散写字面量。空白判定复用 `core/config.py` 的**公开** `is_blank`
（Task 4.4 已把它公开；MUST NOT 复制第二份）。

---

## 1.5 会话来源（控制者补的装配点，与 L2 同批）

`api/deps.py` 目前只有 `get_settings`。本任务要在其中**再加一个提供者**：

```python
def get_engine_factory(request: Request) -> EngineFactory:
    """返回组合根装配到 `app.state.engine_factory` 的 EngineFactory 实例。"""
```

并在 `main.py` 的 lifespan 里，紧随 `app.state.settings = settings` 之后装配：

```python
    app.state.settings = settings
    app.state.engine_factory = EngineFactory(settings)   # 组合根是唯一装配点
    ...
    yield
    ...
    app.state.engine_factory.dispose()                   # 关闭时释放连接池
```

**为什么由控制者现在补这一处**：Task 4.5 是本服务**第一条需要数据库的真实路由**，
而 `main.py` 此前从未装配任何仓储层入口——与 L2（`app.state.settings` 未装配）
是同一类断链。不补，路由拿不到会话。

**会话选型（MUST 照此，两个接口用不同的会话）**：

| 接口 | 会话 | 依据 |
|---|---|---|
| `POST /aicore/ocr` | `factory.write_session()` | 写任务行 |
| `GET /aicore/tasks/{taskId}` | `factory.primary_read_session()` | `er.md:252` 逐字「关键**写后立即读**（任务提交后立即轮询、复核后立即查状态）**强制走主库**」 |

**MUST NOT 用 `read_session()` 跑轮询**：它会在「本会话被标记为写后立即读」时
抛 `ParamError(1002)`（`repository/session.py:243-249`）——那正是 `er.md` §5.5 要拦的形态。
**好处**：本任务因此**天然覆盖**了 `session_needs_primary` 这条守卫的真实用法。

**`EngineFactory` 的导入位置（`api/deps.py` 侧）**：`.importlinter` 契约 1 禁止
`api` **直接**依赖 `repository`，而返回类型注解会构成直接依赖。故正确做法是
**在 `api/deps.py` 里就地定义两个 `Protocol`**（只描述形状，不 import `repository`）：

```python
class SessionFactory(Protocol):          # 就地在 deps.py 定义，不 import repository
    def write_session(self) -> AbstractContextManager[Session]: ...
    def primary_read_session(self) -> AbstractContextManager[Session]: ...

class EngineFactoryLike(Protocol):
    @property
    def write_engine(self) -> Engine: ...
    ...
```

**为什么用 Protocol 而不是 import `repository.session.EngineFactory`**：
① 契约 1 禁止 `api → repository` 的直接依赖，注解也算依赖；
② 即便用 `TYPE_CHECKING`，mypy 的 `strict` 下仍会把该注解视为真实依赖，而契约检查用的
grimp 只看运行期 import —— 那会造出「mypy 看不见、契约也看不见」的假放行；
③ Protocol 的额外收益是**测试可以注入替身**（`conftest.py` 的沙盒引擎），
而 `EngineFactory` 的构造签名要求 `Settings`、内部 `build_engine` 会去连真实 MySQL
——**MUST NOT** 为测试给 `EngineFactory` 加"可替换引擎"的入口（那会把测试关切泄进生产类）。

**`Session` / `Engine` 的类型注解同样**：用 `TYPE_CHECKING` 下的
`from sqlalchemy.orm import Session`（sqlalchemy 是既有依赖，不违任何契约）。

**测试侧注入（`tests/conftest.py`，由控制者提供）**：一个 `api_client` 夹具
（经真组合根 + sqlite 沙盒），它用 `tests/support/db_sandbox.py` 的
`build_sqlite_engine()`、以 `app.state.engine_factory = <替身>` 注入。**MUST NOT 改**该夹具。

若实现时发现契约 1 仍然变红，**停下并在报告里写明**，
MUST NOT 通过放宽 `.importlinter` 或删掉契约来绕过。

---

## 2. 交付接口

### 2.1 `service/task/state.py`（**纯函数，无 IO**）

```python
PROCESSING: Final = "PROCESSING"
SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
MANUAL_REVIEW: Final = "MANUAL_REVIEW"

TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({SUCCEEDED, FAILED, MANUAL_REVIEW})
ALLOWED_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    PROCESSING: frozenset({SUCCEEDED, FAILED, MANUAL_REVIEW}),
}

class IllegalTransitionError(ConflictError):      # code = 3007
    """状态转移非法（`3007` 状态不允许该操作，HTTP 409）。"""

def assert_transition(current: str, target: str) -> None: ...
def is_terminal(status: str) -> bool: ...
```

**硬约束**：
- `ALLOWED_TRANSITIONS` 的**唯一依据**是 `er.md` §7.1 L430 逐字
  「状态机 PROCESSING→SUCCEEDED/FAILED/MANUAL_REVIEW」——
  即**只有 `PROCESSING` 是起点，三个终态各自只能从 `PROCESSING` 到达**。
- **MUST NOT 允许**：终态→终态、终态→`PROCESSING`（重开）、同状态自转移、任何未登记的取值。
- 未知状态值 → `ParamError(code=1003)`（枚举或范围非法），**MUST NOT** 静默放行。
- **非法转移用 `3007`（`ConflictError`）**，依据 `core/errors.py:370-384`：
  「冲突来自**服务端已有状态**」正是本场景；用 `1003` 会把「状态已终态」说成「你参数写错了」。
  **MUST NOT 用 `1001`/`1002`**。
- 本文件**只 import `aicore.core.errors` 与 stdlib**（`service` 层不得 import 具体 Provider；
  纯函数不得碰 repository）。

### 2.2 `service/task/submit.py`

```python
@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    task: AiTask
    created: bool          # True = 新建；False = 幂等命中，返回既有任务

def compute_idem_key(*, explicit: str | None, image_key: str, doc_type: str) -> str | None: ...
def new_task(*, account_id: str, task_type: str, idem_key: str | None, now: datetime) -> AiTask: ...
def submit_ocr_task(
    session: Session, *, account_id: str, image_key: str, doc_type: str,
    idem_key: str | None, now: datetime,
) -> SubmitOutcome: ...
```

**`compute_idem_key` 的口径（MUST 精确，这是「幂等」能不能站住的关键）**：
- 显式给了 `Idempotency-Key` 头 → 用它（`openapi.yaml:54` 逐字「支持 `Idempotency-Key` 头」）；
- 没给 → 由 `image_key` + `doc_type` **派生**：
  `sha256(f"{image_key}\x00{doc_type}")` 的 hex 前若干位。
  依据 `er.md:290` 逐字「同 imageKey+docType 返回原任务号」与 `openapi.yaml:54` 同一句。
- **长度 MUST ≤ 64**（`er.md:290` `idem_key varchar(64)`）；超长 → `ParamError(code=1003)`，
  MUST NOT 静默截断（截断会让不同键碰撞）。
- **MUST NOT 让派生值为 `None`**：`uk_idem` 是 NULL 豁免唯一键，
  派生值为 `None` 时同一 imageKey 重复提交不会命中唯一键，幂等直接失效。
- **MUST NOT 把 `account_id` 拼进 `idem_key`**：`uk_idem` 已是 `(account_id, idem_key)` 两列，
  再拼一次是重复；「换账号同图 = 不同任务」靠两列唯一键实现，不是靠拼串。

**`new_task` 的字段口径（逐列对齐 `er.md` §6.1 L284-298）**：

| 列 | 取值 | 依据 |
|---|---|---|
| `task_id` | `new_id("task")`（**已有实现**） | `er.md` §5.4 L239 |
| `account_id` | 调用方传入（来自 `X-User-Id`） | L289：**分表键** |
| `idem_key` | 上面算出的值（可空） | L290 |
| `type` | `"OCR"`（本任务只提交 OCR） | L291 |
| `status` | `PROCESSING`（**不得由调用方指定**） | L292 默认 `PROCESSING` |
| `progress` | `0` | L293「0~100」 |
| `error_code` | `None` | L294「FAILED 业务码」 |
| `model_meta` | `None`（**执行期才写血缘**，归属 Task 4.7） | L295 |
| `is_eval_sample` | `False` | L296 |
| `created_at` | 调用方传入的 `now`（**带时区**） | L297：**分表键** |
| `finished_at` | `None` | L298 |

- `now` MUST 由**调用方**传入（可注入），MUST NOT 在编排里直接 `datetime.now()`
  —— 测试要能构造「跨月边界」与固定时间（`tests/conftest.py` 文件头：测试内不得任意 sleep）。
  **时区口径**：`er.md:282` 逐字「UTC 存储」→ 传 UTC 感知时间。
- `created_at` **MUST 带时区**：`TaskRepo.insert` 对 naive 值抛 `ParamError(1002)`（Task 3.7 已实现）。

**`submit_ocr_task` 的行为（顺序是硬要求）**：
1. 先按 `find_by_idem_key`（**带 account_id**）查同月表；
2. 命中 → **直接返回既有任务，MUST NOT 新建、MUST NOT 更新它的任何列**（`created=False`）；
3. 未命中 → `new_task` + `TaskRepo.insert`（`created=True`）；
4. **写后立即读** MUST 用**同一个** `Session`（`er.md:252`；`repository/base.py` 的 R3
   已保证同会话即主库连接）；
5. **月边界**：查幂等与插入 MUST 用**同一个月份**——由**同一个 `now`** 现算一次、两处共用。
   跨月瞬间（23:59:59.999 提交、查幂等用了上个月）会造出重复任务；本任务用「算一次共用」避免，
   并**有用例钉住**。

### 2.3 `api/ocr.py`

```python
router = APIRouter(prefix="/aicore", tags=["ocr"])

@router.post("/ocr", status_code=202)
async def submit_ocr(...) -> ...: ...
```

- 请求体按 `OcrRequest`：`imageKey`（必填）、`docType`（必填，枚举
  `BUSINESS_LICENSE` / `PERMIT` / `INSPECTION_REPORT`）、`scene`（可选）。
  **字段名 camelCase**；出参 `taskId`。
- **`scene` 本任务只做校验/透传，MUST NOT 落库**：`er.md` §6.1 的 `ai_task` **没有** `scene` 列。
  **MUST NOT** 为它新增列（会撞 Task 3.6 的三源比对）。
- 幂等头：`Idempotency-Key`（可选）。
- 出参：`{taskId, status: "PROCESSING"}`（`TaskAccepted`），**由信封包裹**（`code=0`）。
- 账号缺失 → `2001`（§1）。

**关于 HTTP 状态码 `202` vs `200`（控制者裁定，需你知悉）**：
`openapi.yaml:62` 写的是 `'200'`，但 `spec.md:30` 逐字「系统**立即返回**任务号与受理状态
（`PROCESSING`）」、`tasks.md` 4.5 逐字「**提交即写** `ai_task` 返回 `taskId`」——
语义是**受理（Accepted）**，`202` 是该语义的标准状态码；
`openapi.yaml:63` 自己就写着「受理成功，返回任务号（异步处理）」。
**裁定：用 `202`**，并在 ledger 登记该差异。
**理由**：RFC 9110 的 `202 Accepted` 定义即「请求已被接受处理，但处理尚未完成」，与本接口逐字一致；
`200` 会与「轮询已有结果」的语义混同。
**风险已告知**：若前端契约测试按 `200` 断言会红——故本工单要求用例**同时**断言
「状态码是 202」与「响应体是 `TaskAccepted` 契约」，让该差异显式可见而非隐藏。

### 2.4 `api/tasks.py`

```python
@router.get("/tasks/{taskId}")
async def get_task(...) -> ...: ...
```

- 出参按 `TaskResult`：必填 `[taskId, type, status, createdAt]`；`progress` 为 0~100；
  `result` 在 `PROCESSING` 与 `FAILED` 时为**空**（`openapi.yaml:806` 逐字）；
  `errorCode` 是 **string**（`openapi.yaml:813`），`FAILED` 时才有值；`finishedAt` 终态才有值。
- **`result` 本任务返回 `None`**：`OcrResult` 的装配属 Task 5.6（本任务只做提交与轮询回执骨架）。
  **MUST 在 docstring 写明**这是本任务边界，不得让读者以为「结果永远为空」。
- 时间用 **UTC ISO 8601**（`_common/openapi.yaml` 的 `timestamp` 口径）。
- **未找到 / 跨账号**（控制者裁定，**这是本任务最需你复核的一条**）：

  | 情形 | 返回 | 依据 |
  |---|---|---|
  | `task_id` 在本月表内不存在 | `3006`（HTTP 404） | `openapi.yaml:140-141` |
  | 存在但 `account_id` ≠ 调用者 | **`2002`（HTTP 403）** | `spec.md:32-35` 逐字「返回 `2002` **且不泄露该任务的任何结果内容**」 |

  **跨账号为什么必须先取行再比账号**：分片只按**月份**切，别人的任务**与本人在同一张月表**里，
  故「带本人账号查不到」无法区分「不存在」与「是别人的」。取行后比 `account_id` 是唯一可行路径；
  代价是**把别人的行读进了本进程**，故 MUST **立刻**判定、MUST NOT 写进日志或响应，
  且**返回体 MUST 只含 `code`/`message`/`traceId`/`timestamp`，`data` 为 `null`**
  （`spec.md:35` 按**最严**解读：连 `status` / `progress` 都不给）。
  用例 MUST 断言响应体里**不出现** `taskId` / `status` / `progress` / `result` 任何一个字段。

---

## 3. 用例清单

### `tests/unit/test_task_state.py`（纯函数，无 IO）
1. `PROCESSING → SUCCEEDED / FAILED / MANUAL_REVIEW` 三条合法转移逐条通过；
2. 三个终态两两之间的**全部 6 条**转移被拒（`3007`）；
3. 三个终态各自 → `PROCESSING` 被拒（防「重开」）；
4. 同状态自转移被拒（含 `PROCESSING → PROCESSING`）；
5. 未知 `current` / 未知 `target` → `1003`；
6. `is_terminal` 对三个终态为真、对 `PROCESSING` 与未知值为假；
7. **`ALLOWED_TRANSITIONS` 与 `er.md` §7.1 的逐字表述一致**：从 `er.md` **现读**那一行
   （`PROCESSING→SUCCEEDED/FAILED/MANUAL_REVIEW`）解析出三元组再比对
   —— **MUST NOT 把期望值抄成常量**（第 3 组 `<= MAX_ID_LENGTH` 的教训）；
8. 纯函数性：AST 断言 `state.py` 不 import `sqlalchemy` / `aicore.repository` / `aicore.provider`。

### `tests/api/test_ocr_submit.py`
9. 受理返回 `202` + `TaskAccepted` 形状（`taskId` 前缀 `task_`、`status == "PROCESSING"`）
   + 信封 `code == 0`；
10. **库内确实多了一行**，且 `status=PROCESSING` / `progress=0` / `finished_at IS NULL` /
    `error_code IS NULL` / `model_meta IS NULL` / `is_eval_sample=0`（逐列断言，对照 §2.2 表）；
11. 幂等：同 `Idempotency-Key` 重提 → **同一 `taskId`**、库行数**不增**；
12. 幂等：无 `Idempotency-Key` 但同 `imageKey` + `docType` → 同一 `taskId`（`er.md:290`）；
13. 幂等：**不同** `docType` → 不同 `taskId`；
14. 幂等：**不同账号**同 `imageKey` + `docType` → **不同 `taskId`**（`uk_idem` 是两列）；
15. `X-User-Id` 缺失 / 空串 / 纯空白 → `401` + `2001`（三个参数化）；
16. `docType` 非枚举值 → `400` + `1003`；`imageKey` 缺失 → `400` + `1001`；
    **MUST NOT 出现框架原生 `422`**（第 2 组已把它收编为 `1001`/`1002`/`1003`）；
17. 月边界：注入 `now` 为 `2027-03-31T23:59:59.999Z` 提交、再用
    `2027-04-01T00:00:00.001Z` 重提同一幂等键 → **不同 `taskId`**
    （跨月不幂等是**已知且正确**的行为：`uk_idem` 是「同月表内唯一」）
    —— 用例 MUST 在 docstring 写明这是设计而非缺陷。

### `tests/api/test_task_poll.py`
18. `PROCESSING` 任务轮询 → `200` + `result is None` + `errorCode is None` + `finishedAt is None`；
19. 对手工置为 `SUCCEEDED` 的任务（用仓储直接改库，不经接口）→ `progress=100`、`finishedAt` 非空；
20. 对手工置为 `FAILED` 且 `error_code='4003'` 的任务 → `errorCode == "4003"`（**字符串**不是数字）；
21. 不存在的 `taskId` → `404` + `3006`；
22. 跨账号 → `403` + `2002`，且响应体**不含** `taskId`/`status`/`progress`/`result`（§2.4）；
23. **`account_id` 必须真的参与过滤**：把行直接改成别人的 `account_id` 后，本人再用原 `taskId`
    轮询 → `2002`（证明过滤生效，而不是「能查到就给」）；
24. 出参字段集合**从 `openapi.yaml` 现读**比对（`TaskResult` 的 `required` 列表），
    **MUST NOT** 抄成常量。

---

## 4. 验收（自证，**原始输出全部贴报告**）

```powershell
cd D:\progrom\.worktrees\aicore-architecture\services\aicore
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" tests/unit/test_task_state.py tests/api/ -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -m "not integration"
.\.venv\Scripts\ruff.exe check --no-cache src tests
.\.venv\Scripts\python.exe -m mypy --strict src
.\.venv\Scripts\lint-imports.exe --config .importlinter
```

- 全量判据 MUST 写「**EXIT=0 且 failed == 0**」，**MUST NOT 写固定计数**
  （`skipped` 会随 `provider/` 下文件数变化）。
- **MUST NOT `git commit` / `git add`**。
- **MUST NOT 用「改 `src/` 文件 + finally 还原」的方式做变异测试**：本组两次踩过——
  超时被杀后 `finally` 没跑完，注入**残留在交付文件里**。
  要变异就在 `tests/` 下建临时用例文件（用完删除）。
- 报告写入 `.superpowers/sdd/2026-09-16-aicore-architecture/task-4.5-report.md`，
  含逐项验收结论、原始输出、**偏离项 + 理由**、**没做到的事**。
- 若发现控制者给的接口有硬伤 → **停下并在报告里写明**，MUST NOT 自行改契约或 `repository/`。

## 5. 探针纪律

新建的临时脚本 > 2 个即停下报告（第 3 组两次实现者交接的教训）。
