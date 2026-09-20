# Task 1.4 报告：组合根与应用装配

- 工作区：`D:\progrom\.worktrees\aicore-architecture`（分支 `feature/aicore-architecture`）
- 起始 HEAD：`21cef10`　提交后 HEAD：`e4a801a`
- 解释器：`services\aicore\.venv\Scripts\python.exe`（Python 3.14.6 / fastapi 0.141.1 / starlette 1.6.0 / pytest 9.1.1）
- 环境变量：所有 Python 调用前均设 `PYTHONUTF8=1`；字节缓存一律落 `PYTHONPYCACHEPREFIX=services\aicore\.venv\pycache\progrom14`；pytest 一律 `-p no:cacheprovider`；ruff `--no-cache`；mypy `--cache-dir .venv\pycache\mypy14`。
- 所有文件写入均走文件工具（UTF-8、LF），未用 `Set-Content`/`Out-File`。

---

## 一、交付物（文件清单与职责）

| 文件 | 状态 | 职责（一句话） |
|---|---|---|
| `services/aicore/src/aicore/main.py` | 新建（44 行） | 组合根：`create_app()` 工厂 + 模块级 `app`，唯一允许注入具体实现的位置；本阶段只装 `/health` 路由 |
| `services/aicore/src/aicore/api/health.py` | 填充（原 1 行文档串） | `GET /health` 存活探针，返回**裸响应** `{"status":"ok"}`，不进信封 |
| `services/aicore/src/aicore/api/deps.py` | 填充（原 1 行文档串） | `get_settings` 依赖提供者，只从 `request.app.state` 取已装配对象，不构造任何具体实现 |
| `services/aicore/tests/conftest.py` | 扩展（13 → 32 行） | 全局夹具：新增 `app`（每次 `create_app()`）与 `client`（`with TestClient` 以触发 lifespan） |
| `services/aicore/tests/api/test_health.py` | 新建（37 行） | 首个接口用例：200 + 裸响应（无 `code`/`traceId`）+ 重复装配不产生路由差异 |
| `services/aicore/tests/api/__init__.py` | 新建（0 字节） | 使 `tests/api` 成为包，与既有 `tests/structural/__init__.py` 约定一致（**简报清单外，见 §二.3**） |

提交：`e4a801a feat: 实现 AICORE 组合根与存活检查`（6 files changed, 136 insertions(+), 2 deletions(-)）。未提交控制者的未跟踪文件 `.sdd-tools.py`。

---

## 二、与简报的差异（逐条给实测证据）

### 2.1【被迫适配】`main.py` 的 `AsyncIterator` 导入源

简报 Step 5 给的是 `from typing import AsyncIterator`。该项目 `pyproject.toml` 的 ruff `select` 含 `UP`，故实测直接报错：

```
$ .venv\Scripts\python.exe -m ruff check --no-cache .
UP035 [*] Import from `collections.abc` instead: `AsyncIterator`
  --> src\aicore\main.py:13:1
   |
12 | from contextlib import asynccontextmanager
13 | from typing import AsyncIterator
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
help: Import from `collections.abc`
Found 1 error.
[*] 1 fixable with the `--fix` option.
[ruff exit code: 1]
```

已改为 `from collections.abc import AsyncIterator`（与简报 Step 6 自己用的 `from collections.abc import Iterator` 同口径）。语义完全等价：`from __future__ import annotations` 下注解本就是惰性的。改后 `ruff check` 全绿。

### 2.2【被迫适配】`test_health.py` 的路由枚举方式

简报 Step 1 第三条用例写 `{r.path for r in first.routes}`。**在本环境不可能通过**——FastAPI 0.141 起 `include_router` 是惰性的，`app.routes` 里放的是 `_IncludedRouter` 包装对象，没有 `.path`：

```
tests\api\test_health.py ..F                                             [100%]
    def test_repeated_assembly_does_not_duplicate_routes() -> None:
        paths_first = sorted({r.path for r in first.routes})
E       AttributeError: '_IncludedRouter' object has no attribute 'path'
FAILED tests/api/test_health.py::test_repeated_assembly_does_not_duplicate_routes
=================== 1 failed, 2 passed, 2 warnings in 0.23s ====================
```

实测 introspection（临时探针，已删）：

```
fastapi 0.141.1 starlette 1.6.0
ROUTE starlette.routing.Route | path= /openapi.json
ROUTE starlette.routing.Route | path= /docs
ROUTE starlette.routing.Route | path= /docs/oauth2-redirect
ROUTE starlette.routing.Route | path= /redoc
ROUTE fastapi.routing._IncludedRouter | path= <none>
   dir: ['effective_candidates', 'effective_low_priority_routes', 'effective_route_contexts',
         'handle', 'include_context', 'matches', 'original_router', 'url_path_for']
```

改用 FastAPI 自己提供的公开展平 API `fastapi.routing.iter_route_contexts()`（该模块内非下划线名，`RouteContext.path` 为公开属性），断言逐字保留简报原文：

```
RouteContext count: 5
  path= /openapi.json | methods= {'HEAD', 'GET'}
  path= /docs | methods= {'HEAD', 'GET'}
  path= /docs/oauth2-redirect | methods= {'HEAD', 'GET'}
  path= /redoc | methods= {'HEAD', 'GET'}
  path= /health | methods= {'GET'}
paths_first  = ['/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc']
paths_second = ['/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc']
equal: True
```

**被否掉的替代方案**：在 `main.py` 里绕过 `include_router`（如 `app.routes.extend(health.router.routes)`）能让简报原文逐字通过，但那是为了让一条测试好写而扭曲生产代码（会丢掉 include 上下文/前缀/tags 机制），不予采用。

### 2.3【补充】`tests/api/__init__.py`

简报的 Files 段未列此文件。补建 0 字节 `__init__.py`，理由是仓库既有约定：`tests/__init__.py`（Task 1.1 建）与 `tests/structural/__init__.py`（Task 1.3 建）都存在；缺了它，pytest prepend 导入模式下 `tests/api/test_health.py` 会以裸模块名 `test_health` 进 `sys.modules`，与将来任何同名 `test_*.py` 冲突。若控制者要求严格逐字，删掉这一个空文件即可（不影响任何断言）。

### 2.4【未改动】简报其余内容逐字落地

`health.py`、`deps.py`、`main.py` 的文档串/函数体/参数、`conftest.py` 全篇、`test_health.py` 的用例名与全部断言语句，均与简报逐字一致。

---

## 三、验证证据（原始输出）

### 3.1 Step 2：先红（确认测试确实在测新东西）

```
$ pytest tests/api/test_health.py -v -p no:cacheprovider
collected 0 items / 1 error
tests\api\test_health.py:7: in <module>
    from aicore.main import create_app
E   ModuleNotFoundError: No module named 'aicore.main'
=========================== short test summary info ===========================
ERROR tests/api/test_health.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
======================== 2 warnings, 1 error in 3.60s =========================
[exit code: 2]
```

与简报预期一致（`ModuleNotFoundError: No module named 'aicore.main'`）。

### 3.2 Step 7：三接口用例全绿

```
$ pytest tests/api -v -p no:cacheprovider
collected 3 items

tests\api\test_health.py ...                                             [100%]
======================== 3 passed, 2 warnings in 0.06s ========================
[exit code: 0]
```

（2 条 warning 均为第三方库自身的 Deprecation：`starlette.testclient` 用 httpx、`anyio.abc.BlockingPortal` 别名。与本任务代码无关。）

### 3.3 Step 8：真实 uvicorn 进程 + 真实 HTTP 请求（强制证据）

命令（简报脚本，补 `-WorkingDirectory` 并在删除日志前打印日志内容；就绪用轮询替代盲目 6s 等待）：

```powershell
$proc = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","aicore.main:app","--port","8083","--host","127.0.0.1" `
  -WorkingDirectory $root -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput "$root\uvicorn.log" -RedirectStandardError "$root\uvicorn.err"
```

真实输出：

```
started PID=32076 at 18:25:53.194
RESULT: HTTP 200  body={"status":"ok"}
Content-Type: application/json
--- raw curl.exe -i ---
HTTP/1.1 200 OK
date: Thu, 17 Sep 2026 10:25:58 GMT
server: uvicorn
content-length: 15
content-type: application/json

{"status":"ok"}
process alive before stop: True
--- uvicorn stdout ---
INFO:     127.0.0.1:64927 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:64928 - "GET /health HTTP/1.1" 200 OK
--- uvicorn stderr ---
INFO:     Started server process [32480]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8083 (Press CTRL+C to quit)
process alive after stop: False
port 8083 listening after stop: False
log file remains: False / err file remains: False
```

与简报预期逐字一致：`HTTP 200  body={"status":"ok"}`；`content-length: 15` 也正面证明响应体就是裸 JSON，没有信封包裹（带信封的响应会多出 `code`/`message`/`traceId`/`timestamp` 四个字段，长度远大于 15）。

> 注：`Start-Process` 报出的 PID 32076 是 venv 的 `python.exe` 启动器，日志里的 `[32480]` 是它 exec 出来的真实解释器进程；停止时以端口与进程存活双重判定（见下），不依赖 PID 猜测。

**无环境变量启动**（本任务的硬约束）证据：

```
=== AICORE_* env vars in this session (expect none) ===
(none)
=== any .env / dotenv reference in src? ===
（grep 工具扫 src/：dotenv|\.env|os\.environ|getenv → No matches found）
```

即：进程环境里没有任何 `AICORE_*`；`src/` 全树不读 `.env`、不读环境变量，`services/aicore/.env` 虽存在但无任何代码路径会打开它。

### 3.4 Step 8 收尾：进程已停、无残留

```
=== python processes still alive ===
(no python process alive)
=== port 8083 listeners ===
(free)
uvicorn.log exists: False / uvicorn.err exists: False
=== probe-file residue from structural tests (expect none) ===
no *_probe.py
no .importlinter_* mutation config
=== git status (working tree) ===
?? .sdd-tools.py          ← 控制者的工具，未跟踪，未提交，非本次产物
```

（首次的 `Get-CimInstance Win32_Process` 被沙箱拒绝，故未采信；改用 `Get-Process` + `Get-NetTCPConnection` 重新取证，结果同上。）

### 3.5 ruff

```
$ .venv\Scripts\python.exe -m ruff check --no-cache .
All checks passed!
[ruff exit code: 0]

$ ruff format --check --no-cache src\aicore\main.py src\aicore\api\health.py src\aicore\api\deps.py tests\conftest.py tests\api
6 files already formatted
[exit code: 0]
```

（`ruff format --check` 全仓扫会报 `tools\patch_venv_utf8.py` —— Task 1.1 提交 `b98f251` 的既有文件，非本任务改动，且 `ruff format` 不在本项目既定门禁清单内，未处理。）

### 3.6 mypy（strict）

```
$ .venv\Scripts\python.exe -m mypy --cache-dir .venv\pycache\mypy14 src
Success: no issues found in 51 source files
[mypy exit code: 0]
```

（51 = 49 个既有模块 + 新建 `main.py` + …；`main.py` 已计入，未被排除。）

### 3.7 分层契约（**改动之后**跑，从 `services/aicore` 执行）

```
$ .venv\Scripts\lint-imports.exe --config .importlinter --no-cache

Analyzed 51 files, 2 dependencies.
----------------------------------

api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT

Contracts: 4 kept, 0 broken.

Warnings
service 层只可与 provider.base 交互，不得依赖具体通道实现
- No matches for ignored import aicore.service.** -> aicore.provider.base.
[exit code: 0]
```

`4 kept, 0 broken` ✓。那条 warning 是 `.importlinter` 内已记录的**已知状态**（service 层尚无真实 `provider.base` 导入，Task 4 落地后自动消失），非本次引入。

> 另注：`python -m importlinter.cli lint-imports ...` 返回 0 且**无任何输出**（不加载配置、静默空跑）。这条命令具有欺骗性，正确入口是 `.venv\Scripts\lint-imports.exe`。

### 3.8 全量与收集（第 1 组验收项）

```
$ pytest -p no:cacheprovider
66 passed, 7 skipped, 2 warnings in 0.54s          [exit code: 0]

$ pytest tests/structural -p no:cacheprovider
63 passed, 7 skipped, 2 warnings in 0.77s          [exit code: 0]
（含 Task 1.3 的四条契约阴性探针、规则 5/6 的 AST 扫描与判别力用例）

$ pytest --collect-only -p no:cacheprovider
73 tests collected in 0.05s                        [exit code: 0]
（66 passed + 7 skipped = 73，无导入错误）

$ python -c "import aicore; from aicore.main import app"
import OK from D:\progrom
version 0.1.0
```

`import aicore` 在**工作区外**的 cwd（`D:\progrom`）同样成功，证明 editable 安装指向本 worktree 的 `src`（`aicore.__file__` = `…\aicore-architecture\services\aicore\src\aicore\__init__.py`）。`pip install -e .` 本任务**未重跑**（沙箱内 pip 不可用，且属控制者此前已代为执行并记录在案的项目）。

### 3.9 覆盖率门禁（**未达标，见 §六 Concerns**）

```
$ pytest -p no:cacheprovider --cov --cov-report=term-missing
TOTAL                                         30     22    27%
FAIL Required test coverage of 80.0% not reached. Total coverage: 26.67%
[exit code: 1]
```

### 3.10 内容完整性（字节级）

```
=== byte-compare committed files: HEAD blob vs disk ===
src\aicore\main.py               blob=1232  disk=1232  identical=True
src\aicore\api\health.py         blob=618   disk=618   identical=True
src\aicore\api\deps.py           blob=605   disk=605   identical=True
tests\conftest.py                blob=701   disk=701   identical=True
tests\api\test_health.py         blob=1434  disk=1434  identical=True
tests\api\__init__.py            blob=0     disk=0     identical=True
```

六个文件均为 LF（CRLF 计数 0），UTF-8 均可解码（含中文文档串），提交后磁盘字节与 HEAD blob 完全一致。

---

## 四、提交

```
$ git commit --no-verify -m "feat: 实现 AICORE 组合根与存活检查"
[feature/aicore-architecture e4a801a] feat: 实现 AICORE 组合根与存活检查
 6 files changed, 136 insertions(+), 2 deletions(-)
 create mode 100644 services/aicore/src/aicore/main.py
 create mode 100644 services/aicore/tests/api/__init__.py
 create mode 100644 services/aicore/tests/api/test_health.py
[exit code: 0]
```

暂存范围严格等于简报 Step 9 的三条路径（`git add services/aicore/src/aicore/main.py services/aicore/src/aicore/api services/aicore/tests`），`git diff --cached --name-status` 确认只有 6 个文件；`--no-verify` 后复核提交内容：

```
$ git show --stat --oneline HEAD
e4a801a feat: 实现 AICORE 组合根与存活检查
 services/aicore/src/aicore/api/deps.py   | 18 +++++++++++++++-
 services/aicore/src/aicore/api/health.py | 21 ++++++++++++++++++++-
 services/aicore/src/aicore/main.py       | 44 +++++++++++++++++++++++++++++++++
 services/aicore/tests/api/__init__.py    |  0
 services/aicore/tests/api/test_health.py | 37 +++++++++++++++++++++++++++++++
 services/aicore/tests/conftest.py        | 18 +++++++++++++++++
 6 files changed, 136 insertions(+), 2 deletions(-)
```

无 `[AI]` 前缀，type 英文 + subject 中文，`--no-verify` 已获授权（沙箱内 `sh` 不在 PATH，`.githooks/*` 对任何人都不可能执行）。

---

## 五、hook 等价复核（7 项，逐条在暂存区上复跑）

`sh` 不可用 → `.githooks/pre-commit`、`.githooks/commit-msg` 物理未执行，改以等价脚本在 `git diff --cached` 上逐条复跑：

| # | 原 hook 检查 | 复跑结果 |
|---|---|---|
| 1 | 合并冲突标记（`<<<<<<<` / `=======` / `>>>>>>>`） | PASS (none) |
| 2 | 行尾空白 / 文件末尾多余空行（`git diff --cached --check`） | PASS (clean) |
| 3 | 大文件 >1MB | PASS (none) |
| 4 | 私钥块 / 云平台密钥（`BEGIN … PRIVATE KEY` / `AKIA…` / `ASIA…`） | PASS (none) |
| 5 | 疑似硬编码凭据（`password|secret|api_key|token…`，排除 `os.environ`/`your_`/`mock` 等） | PASS (none) |
| 6 | 真实 `.env` 入库（仅允许 `.env.example`） | PASS (none) |
| 7 | commit-msg 格式 `^(feat|fix|…)(\(…\))?: .+` | PASS: `feat: 实现 AICORE 组合根与存活检查` |

---

## 六、自审发现（读自己的 diff）

### F1【简报自带缺陷，未擅自改】重复装配用例的两条断言都不可能发现"重复注册"

```python
paths_first = sorted({c.path for c in iter_route_contexts(first.routes)})   # 集合 → 已去重
assert paths_first == paths_second                       # 比较的是去重后的集合
assert len(paths_first) == len(set(paths_first))          # 对集合派生的 list 恒真
```

- 第 3 条断言是**恒真式**：`paths_first` 由 `{…}` 集合派生，`len(list) == len(set(list))` 永远成立。
- 第 2 条断言比较的是两侧的**路径集合**：即便 `create_app()` 真的把同一 router 注册两遍，两侧集合仍然相等，用例照样绿。

也就是说，该用例的 docstring（"重复装配 MUST NOT 产生重复注册"）承诺的能力，其断言并不具备。**我没有擅自改写**（简报要求逐字，且简报 Step 7 预期 `3 passed`），建议的等价替换（留待控制者裁定）：

```python
from collections import Counter
...
paths_first = [c.path for c in iter_route_contexts(first.routes)]
paths_second = [c.path for c in iter_route_contexts(second.routes)]
assert sorted(paths_first) == sorted(paths_second)
assert Counter(paths_first).most_common(1)[0][1] == 1   # 真正卡住重复注册
assert "/health" in paths_first                          # 非空下限：守住 §二.2 的枚举适配不塌成空集
```

### F2【我的适配引入的风险，已用实测消解】

`iter_route_contexts()` 若因版本变化返回空迭代器，上面两条断言会同时退化为 `[] == []` 而**静默通过**。当前实测该迭代器交出 5 条路由且含 `/health`（见 §二.2），风险已被实测覆盖；若采纳 F1 的替换，第 3 行 `assert "/health" in paths_first` 即为其永久哨兵。

### F3【已消解】`deps.py` 是否会被误当成"具体实现注入点"

复查：`deps.py` 只 import 了 `fastapi.Request` 与 `typing.Any`，函数体只有一行 `request.app.state.settings`；全文件不出现任何 repository/provider 符号。分层契约（api 层不得依赖 repository/provider）在改动后仍 `4 kept, 0 broken`，构成独立佐证。

### F4【已消解】`main.py` 是否踩到分层契约

`main.py` 位于包根（非 `api`/`service`/`core`… 任一层），只 import `aicore`（取 `__version__`）与 `aicore.api.health`。契约 1/2/3/4 的 `source_modules` 都不覆盖包根，故合规；`lint-imports` 的 "Analyzed 51 files, 2 dependencies" 与 `4 kept, 0 broken` 是实测背书。

### F5【环境事实，非我引入】两个文件的工作区形态与 blob 不同（CRLF）

字节级对照（`git cat-file blob` 原始字节 vs 磁盘）：

| 文件 | blob | 磁盘 | 判定 |
|---|---|---|---|
| `src/aicore/provider/__init__.py` | 85 B（LF） | 86 B（CRLF） | 仅行尾差异 |
| `pyproject.toml` | 3018 B（LF） | 3104 B（CRLF） | 仅行尾差异（86 行全 CRLF，正常检出形态） |
| `src/aicore/service/desensitize.py` | 589 B | 589 B | **identical=True** |
| `tests/structural/test_layering.py` | 9984 B | 9984 B | **identical=True** |
| `.importlinter` | 6570 B | 6570 B | **identical=True** |

这是本仓库 `core.autocrlf=true` 下 `git status` 看不见的经典形态（Task 1.3 已记录的坑）。**与本任务无关**：我从未编辑这两个文件；唯一会重写 `provider/__init__.py` 的机制是 Task 1.3 的结构测试探针，而它的还原是**逐字节**的（`read_bytes` → `write_bytes`），故当前磁盘形态 == 探针首次运行前的形态（早于本任务）。未做任何"修复"——按字节回写才是唯一安全手段，`git checkout --` 会再次把它改写。

### F6【已消解】测试是否留下了残留

结构测试的探针文件（`*_probe.py`、`.importlinter_nonexistent`）在跑完后均不存在；`git status` 仅剩控制者的 `.sdd-tools.py`；`uvicorn.log`/`uvicorn.err` 已删；全仓无 `.pytest_cache`（`-p no:cacheprovider`）、无新增 `.ruff_cache`、无 `.coverage`（`COVERAGE_FILE` 指向 venv 内）；字节缓存全部落在 `.venv\pycache\` 下。

---

## 七、Concerns

### C1（必须知晓）今天调用 `get_settings` 会发生什么

`api/deps.py` 的 `get_settings` 返回 `request.app.state.settings`，而 `settings` 要到 **Task 2.1** 才存在。实测（临时探针，已删）：

```
app.state has 'settings' today: False
raise_server_exceptions=False -> HTTP 500 body= Internal Server Error
default TestClient raised: builtins.AttributeError -> 'State' object has no attribute 'settings'
```

即：**若今天有路由 `Depends(get_settings)`，该路由会 500**（Starlette `State.__getattr__` 抛 `AttributeError`，冒泡出依赖解析）。

**当前无影响**：全仓没有任何调用点（`/health` 不用它，`create_app()` 不碰它，`main.py` 也不设 `app.state`）。这正是简报 Step 4/5 的既定阶段划分——本任务不引入配置依赖。Task 2.1 装配 `app.state.settings` 后该依赖自然可用；在那之前它是一段"存在但不可调用"的代码。

### C2（需控制者裁定）覆盖率门禁当前为 27%，未达 80%

`pyproject.toml` 配了 `fail_under = 80`，实测 `Total coverage: 26.67%`（30 语句 / 22 未覆盖）。原因是结构性的，不是漏测：

- 六层 49 个模块目前**全是 docstring 空壳**（0 语句），不抬分母；
- 真正有语句的只有三处：`api/health.py` **100%**（本任务覆盖）、`api/deps.py` **0%**（5 语句，今天不可调用，见 C1）、`provider/base.py` **0%**（17 语句，纯 Protocol 声明，无实现可测）；
- `main.py` 已按全局约束排除。

也就是说：在"只有存活探针有实现"的阶段，80% 无论怎么写用例都到不了；它要等第 3~4 组业务实现落地才可能达标。第 1 组验收清单里也**没有**覆盖率条目。我不建议为凑数把 `deps.py`/`provider/base.py` 加进 `omit`（那是把门禁改瞎），故原样保留红灯并如实上报。

### C3（提示）`test_health.py` 依赖 FastAPI 的展平 API

`fastapi.routing.iter_route_contexts` 是非下划线公开名，但毕竟不是 `from fastapi import …` 顶层导出（实测顶层导入会 `ImportError`）。若未来 FastAPI 调整它，该用例会**红得很响**（导入失败），不会静默——可接受。更稳的替代是断言 `create_app().openapi()["paths"]`，但它丢掉了非 API 路由，且会把 OpenAPI 生成拉进用例。

### C4（提示）`python -m importlinter.cli lint-imports` 是静默空跑

见 §3.7 注。若后续任务/CI 照着这个写法调用分层检查，会得到"永远绿、其实没跑"的假绿。建议后续把 `lint-imports.exe`（或 `python -m importlinter`）写进文档/CI。

---

## 八、结论

- 简报 Step 1~9 全部执行，`3 passed`、`HTTP 200 body={"status":"ok"}`、`4 kept, 0 broken`、ruff/mypy 全绿、全量 `66 passed, 7 skipped` 均取得原始输出。
- 与简报的偏离共 4 处，全部在 §二 给出实测证据与替代方案取舍：2 处是环境（ruff UP035、FastAPI 0.141 惰性 include_router）逼出来的**不可能逐字**，2 处是补充（`tests/api/__init__.py`、`iter_route_contexts` 的文档串说明）。
- 无残留、无孤儿进程、无环境变量依赖、工作区字节与 HEAD 一致。
- 遗留待裁定：F1（简报自带断言恒真）+ C2（覆盖率 27%）。
  → **两者均已在本轮修复/裁定**，见下节。

---

## 修复轮 1（评审发现）

- 修复提交：`30ad766 fix: 修复重复注册守卫的恒真断言并补依赖契约用例`（3 files changed, 48 insertions(+), 7 deletions(-)）
- 起始 HEAD：`e4a801a`　修复后 HEAD：`30ad766`
- 评审结论：Needs fixes（0 Critical / 1 Important / 6 Minor）
- 工作区、解释器、环境变量纪律同 §开头（`PYTHONUTF8=1` + `PYTHONPYCACHEPREFIX` 落 venv + `-p no:cacheprovider` + ruff `--no-cache` + mypy `--cache-dir .venv\pycache\mypy14` + `COVERAGE_FILE` 落 venv）。

### 一、逐条处置对照

| 编号 | 评审发现 | 处置 | 落点 |
|---|---|---|---|
| **Important** | 重复注册守卫恒真：`len(paths_first) == len(set(paths_first))` 恒真，集合比较看不见双重注册 | **已修**——逐字采纳评审细化形式（`Counter` 相等 + 定向 `count("/health") == 1`） | `tests/api/test_health.py:49-52` |
| **M1** | `get_settings` 调用即 `AttributeError` 的事实只写在报告，未写进代码 | **已修**——函数 docstring 增 3 行；**未**加 `getattr(..., None)` 兜底 | `src/aicore/api/deps.py:16-21` |
| **M2(a)** | 覆盖率门禁红（27%） | **已修**——新增 deps 契约用例；覆盖率 **26.67% → 43.33%**（门禁仍红，裁定见 §三） | `tests/api/test_deps.py`（新增，§四） |
| **M2(b)** | `provider/base.py` 的 17 条未覆盖语句如何处置 | **裁定：不排除，保留计入分母**；`pyproject.toml` **零改动** | §三 |
| **M3** | 信封守卫只查 4 个信封字段中的 2 个 | **已修**——`assert body == {"status": "ok"}`（与 Important 同一提交落地） | `tests/api/test_health.py:24` |
| **M4** | `python -m importlinter.cli lint-imports` 静默假绿 | **已记录**（§五），并给出落地位置建议；未擅自改文档 | §五 |
| M5 | `iter_route_contexts` 非顶层导出 | 无动作（评审已确认：ImportError 会响，可接受） | — |
| M6 | 简报片段的适配 | 无动作（评审已确认：断言逐字保留） | — |

### 二、改动最终形态

**Important —— 断言取「去重前」的路径列表**（`tests/api/test_health.py:47-52`）：

```python
    first = create_app()
    second = create_app()
    paths_first = [c.path for c in iter_route_contexts(first.routes)]
    paths_second = [c.path for c in iter_route_contexts(second.routes)]
    assert Counter(paths_first) == Counter(paths_second)  # 两次装配互不累积
    assert paths_first.count("/health") == 1  # 单次装配不重复注册，兼作非空哨兵
```

（`from collections import Counter` 已加；`sorted({...})` 两行删除。）

docstring 同步补了「**为什么不写成** `Counter(...).most_common(1)[0][1] == 1`」的依据——同一路径合法地可以承载多个方法/路由上下文，那种写法会在后续组制造假失败。写进 docstring 是为了防止后人把它"改回去"：

```
39:     - Counter 相等：两次装配互不累积（first 上多出来的注册不会出现在 second 上）；
40:     - `/health` 恰好一次：单次装配自身不重复注册，兼作**非空哨兵**——若上面的展平 API
41:       失效导致枚举为空，本行立刻变红，不会退化成 [] == [] 静默通过。
43:     不写成「任何路径都至多一次」（如 Counter(...).most_common(1)[0][1] == 1）：同一路径
44:     合法地可以承载多个方法/路由上下文（后续组的 GET+POST 同路径），那种写法会制造假失败；
45:     这里只对确定的单方法路径 /health 收紧。
```

**M3 —— 信封守卫改全等**（`tests/api/test_health.py:19-24`）：

```python
def test_health_is_not_wrapped_in_envelope(client: TestClient) -> None:
    """存活探针必须是裸响应：被信封包住会让探针判定失效。"""
    body = client.get("/health").json()
    # 全等比较严格强于逐字段排查（原写法只看 code/traceId 两个字段）：
    # 信封的 code / message / traceId / timestamp / data 任一混入都会让本行变红。
    assert body == {"status": "ok"}
```

**M1 —— docstring 记录失败模式**（`src/aicore/api/deps.py:15-22`）：

```python
def get_settings(request: Request) -> Any:
    """返回组合根装配的 Settings 实例。Task 2.1 定类型。

    注意：`app.state.settings` 由 Task 2.1 装配，在那之前调用本函数会抛 AttributeError
    （Starlette `State.__getattr__` 在属性缺失时即抛）。此处刻意不做兜底取值：
    配置缺失必须在启动/装配期暴露，用 getattr 默认值掩盖只会把误配置推迟到运行期。
    """
    return request.app.state.settings
```

函数体一字未改（仍是裸 `request.app.state.settings`，无 `getattr` 兜底）；**模块级 docstring 按评审要求原样未动**。

**M2(a) —— `tests/api/test_deps.py`（新增，22 行）**：

```python
def test_get_settings_returns_assembled_instance() -> None:
    """装配什么就返回什么：以 sentinel 断言**同一性**（is），而不是相等性。"""
    sentinel = object()
    # 桩请求：get_settings 只要求 request.app.state.settings 这一条取值路径。
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=sentinel)))

    assert get_settings(request) is sentinel  # type: ignore[arg-type]
```

用 `SimpleNamespace` 组桩请求（不引入 `unittest.mock`）；**只断言同一性**，不测「未装配时抛 AttributeError」——那是 Task 2.1 之前的临时状态，写成用例会在 2.1 装配 `app.state.settings` 后变成假约束。

### 三、M2(b) 裁定：`provider/base.py` **不排除**（保留计入分母，门禁仍红）

**裁定：保留计入，`pyproject.toml` 不做任何改动。**（即评审给的第一个选项。）

理由（与既有 3 条 `omit` 的**授予口径**对比后得出，不是"少改一处配置"的偷懒）：

1. **既有的 3 条 `omit` 是"环境性豁免"，本文件不具备该性质。** `provider/deepseek.py` / `cloud_vision.py` / `cloud_ocr.py` 实测均为 docstring 空壳（97 / 67 / 66 字节，0 语句），`omit` 是为它们**将来装有网络调用与凭据**的实现在先豁免——与本任务"测试 MUST NOT 依赖网络"的硬约束同源。`provider/base.py` 恰恰相反：零依赖、可导入，其 17 条语句（3 个 `@runtime_checkable` 装饰器 + 3 个 class 语句）在 **import 时就会执行**，任何一条真实用例导入它就自然覆盖。
2. **排除会开一个会蔓延的先例。** 一旦"纯声明模块不进分母"成立，后续每个 `Protocol`/抽象基类文件都可以援引本条被排除，而这正是覆盖率门禁最容易被悄悄改瞎的路径。今天的 `base.py` 是纯声明，但同一路径明天可能长出默认实现或 mixin——`omit` 会连那些真实语句一起豁免。
3. **红灯不会因此长期停留，且无需改配置自愈。** 第 2/3 组落地后，任何 provider / service 用例导入 `provider.base` 即覆盖它，分母与分子同步增长，门禁在**不改配置**的前提下自然转绿。

**反事实（供控制者复核该裁定）**：若排除该文件，`Stmts` 由 30 降至 13、覆盖率变为 **13/13 = 100%**，门禁会**立刻转绿**——但那是由 `omit` 造出来的绿，且（依据第 3 点）它并不会让门禁更早反映真实实现进度。**我不建议这样做，也未这样做。**

**本轮的覆盖率数字（实测）**：`TOTAL 30 17 43%`，`Total coverage: 43.33%`（起点 26.67%）。分母 30 = `api/health.py` 7 + `api/deps.py` 5 + `provider/base.py` 17 + `__init__.py` 1（`__version__` 常量，已覆盖）；缺口 17 = `provider/base.py` 全部 17 条（`7-43` 行）。`api/deps.py` 由 0% → **100%**。

### 四、范围外新增（提请控制者复核）

| 文件 | 说明 | 理由 |
|---|---|---|
| `services/aicore/tests/api/test_deps.py` | **新增**（简报 Files 段未列） | M2(a) 是评审明确要求的交付项；该用例测的是 `deps.py`，放进 `test_health.py` 会让文件名与内容不符。与 §二.3 的 `tests/api/__init__.py` 同性质，均为可独立回退的补充。 |

`pyproject.toml` **未改动**（M2(b) 裁定不排除）；`main.py`、`health.py`、`conftest.py` 本轮**未改动**；未新增任何 `omit`。

### 五、M4 记录 + 建议落地位置（未擅自改文档）

事实复述（§3.7 注 / C4）：`python -m importlinter.cli lint-imports --config .importlinter` **退出码 0 且无任何输出**——它不加载配置、不分析依赖，是"永远绿、其实没跑"的假绿。正确入口是本轮实际使用的 `.venv\Scripts\lint-imports.exe`（本轮 4 条契约全绿即由它产出）。

**建议落地位置（请控制者定夺，本轮未改）**：`services/aicore/VENV.md` §三「已知环境约束」。理由：(1) 该文件已是"在本服务目录里跑命令前必须先读"的版本控制文档，且已收录同类坑（pip 沙箱失败、`Scripts\*.exe` 内嵌绝对路径不可改名、缓存落盘要求）；(2) 这条坑的受害者正是"照着文档敲命令的人 / 写 CI 脚本的人"，与 §三 的既有条目同类；(3) 若后续有 CI 脚本规范文档（`docs/agent-sdlc-standard/` 一类），则宜同时落到那里——但**那是 CI 门禁口径，属控制者/架构决策，不由本任务单方面写入**。

### 六、阴性验证（本轮的核心证据）

评审指出的要害是"**旧断言不可能失败**"，故本轮必须交出"新守卫**确实会红**"的阴性证据。两次注入都在 `create_app()` 上、都按字节还原、都用 `git hash-object` 对齐 HEAD blob。

**基线对齐（注入前）**：

```
=== HEAD blob ===
e0e6b23e7e74caf443d3255f72e44d8ea00dbaca
=== disk blob (before) ===
e0e6b23e7e74caf443d3255f72e44d8ea00dbaca
```

**阴性 ①：让 `create_app()` 把同一 router 注册两遍**（把 `    app.include_router(health.router)` 复制一行，注入靠 `bytes.replace`，备份走 `Path.write_bytes`）：

```
=== mutate ===
orig    len=1232 sha256=b011fff4804bcfaf5e158188f8c37752e2e94bcf0b6773f956293eca6f2d775b crlf=0
mutated len=1270 sha256=06fdcb311bcb808106d353113277623a0b5fdc9b78fafefa9f7716bdb156b24a
=== disk blob (mutated) ===
7f8fa02af0b25158a871d917ccc38b6cab7c5241
```

```
$ pytest tests/api/test_health.py -p no:cacheprovider
>       assert paths_first.count("/health") == 1  # 单次装配不重复注册，兼作非空哨兵
E       AssertionError: assert 2 == 1
E        +  where 2 = <built-in method count of list object at 0x0000027A10888440>('/health')
E        +    where <built-in method count of list object at 0x0000027A10888440> = ['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/health', '/health'].count
FAILED tests/api/test_health.py::test_repeated_assembly_does_not_duplicate_routes
1 failed, 2 passed, 2 warnings in 0.19s
```

→ **变红**（且证据链完整：`/health` 在展平结果里出现了两次）。**旧断言在此注入下必然全绿**（集合已把它去重），这正是评审给出的要害，现已被正面推翻。

**阴性 ②：非对称累积**（只让**偶数次** `create_app()` 多挂一条 `/probe-extra`；两次装配的 `/health` 计数都仍是 1）——用来证明 **Counter 那一行不是摆设**，旧写法的集合比较对它同样完全免疫：

```
$ pytest tests/api/test_health.py -v -p no:cacheprovider
>       assert Counter(paths_first) == Counter(paths_second)  # 两次装配互不累积
E       AssertionError: assert Counter({'/op...be-extra': 1}) == Counter({'/op...'/health': 1})
E         Omitting 5 identical items, use -vv to show
E         Left contains 1 more item:
E         {'/probe-extra': 1}
tests\api\test_health.py:51: AssertionError
1 failed, 2 passed, 2 warnings in 0.14s
```

**还原（两次注入各一次，逐字节）**：

```
=== restore ===
restored len=1232 sha256=b011fff4804bcfaf5e158188f8c37752e2e94bcf0b6773f956293eca6f2d775b crlf=0
backup_bytes == disk_bytes: True
backup removed: True
=== disk blob vs HEAD blob ===
e0e6b23e7e74caf443d3255f72e44d8ea00dbaca     ← disk
e0e6b23e7e74caf443d3255f72e44d8ea00dbaca     ← HEAD:services/aicore/src/aicore/main.py
=== re-observe GREEN ===
4 passed, 2 warnings in 0.07s
```

还原手段说明：注入与还原**都走 `read_bytes`/`write_bytes`**，还原后以 sha256 + `git hash-object` 双证（`e0e6b23e…` 与 HEAD blob 相同）；探针脚本与备份文件落在 `.venv\pycache\`（gitignore 内），用后即删，`Get-ChildItem .venv\pycache -Filter '*probe*'` 与 `-Filter 'main.py.*'` 均为空。

### 七、验证证据（修复后复跑，原始输出）

**测试**（提交后复跑）：

```
$ pytest tests/api -v -p no:cacheprovider -o addopts=''
collecting ... collected 4 items
tests/api/test_deps.py::test_get_settings_returns_assembled_instance PASSED [ 25%]
tests/api/test_health.py::test_health_returns_200 PASSED                 [ 50%]
tests/api/test_health.py::test_health_is_not_wrapped_in_envelope PASSED  [ 75%]
tests/api/test_health.py::test_repeated_assembly_does_not_duplicate_routes PASSED [100%]
======================== 4 passed, 2 warnings in 0.09s ========================

$ pytest -p no:cacheprovider
67 passed, 7 skipped, 2 warnings in 0.42s          [exit code: 0]
（修复前 66 passed / 7 skipped；+1 = 新增的 deps 契约用例）

$ pytest --collect-only -p no:cacheprovider
74 tests collected in 0.02s                        [exit code: 0]
（67 + 7 = 74，无导入错误）
```

**覆盖率（本轮数字，含逐文件明细）**：

```
$ pytest -p no:cacheprovider --cov --cov-report=term-missing
Name                                       Stmts   Miss  Cover   Missing
------------------------------------------------------------------------
src\aicore\api\__init__.py                     0      0   100%
src\aicore\api\deps.py                         5      0   100%      ← 0% → 100%（本轮的 M2(a)）
src\aicore\api\habit.py                        0      0   100%
src\aicore\api\health.py                       7      0   100%
src\aicore\api\ocr.py                          0      0   100%
src\aicore\api\tasks.py                        0      0   100%
src\aicore\provider\base.py                   17     17     0%   7-43 ← 裁定保留计入，见 §三
------------------------------------------------------------------------
TOTAL                                         30     17    43%
FAIL Required test coverage of 80.0% not reached. Total coverage: 43.33%
[exit code: 1]
```

**静态检查与分层契约**：

```
$ ruff check --no-cache .
All checks passed!                                              [exit code: 0]

$ ruff format --check --no-cache src\aicore\main.py src\aicore\api\health.py src\aicore\api\deps.py tests\conftest.py tests\api
7 files already formatted                                       [exit code: 0]

$ mypy --cache-dir .venv\pycache\mypy14 src
Success: no issues found in 51 source files                     [exit code: 0]

$ .venv\Scripts\lint-imports.exe --config .importlinter --no-cache
Analyzed 51 files, 2 dependencies.
api 层不得直接依赖 repository / provider KEPT
service 层只可与 provider.base 交互，不得依赖具体通道实现 KEPT (1 warning)
repository / provider / port 不得反向依赖 service KEPT
core 不得依赖任何业务层 KEPT
Contracts: 4 kept, 0 broken.                                    [exit code: 0]
（那条 warning 仍是 §3.7 记录的已知状态：service 层尚无真实 provider.base 导入。）
```

**内容完整性（提交后逐字节，HEAD blob vs 磁盘）**：

```
services/aicore/src/aicore/api/deps.py           blob=  934 disk=  934 identical=True crlf=0 bom=False
services/aicore/tests/api/test_health.py         blob= 2631 disk= 2631 identical=True crlf=0 bom=False
services/aicore/tests/api/test_deps.py           blob=  925 disk=  925 identical=True crlf=0 bom=False
services/aicore/src/aicore/main.py               blob= 1232 disk= 1232 identical=True crlf=0 bom=False
```
四个文件均 LF、无 BOM、UTF-8 可解码（含中文 docstring）；`main.py` 与注入前基线 blob 相同。

**残留**：无 `.pytest_cache`、无仓库内 `.coverage`、无 `*probe*` / `main.py.orig*`、无 uvicorn 日志。

### 八、提交与 hook 等价复核

```
$ git add services/aicore/src/aicore/api/deps.py services/aicore/tests/api/test_health.py services/aicore/tests/api/test_deps.py
$ git diff --cached --name-status
M	services/aicore/src/aicore/api/deps.py
A	services/aicore/tests/api/test_deps.py
M	services/aicore/tests/api/test_health.py

$ git commit --no-verify -F <msg>
[feature/aicore-architecture 30ad766] fix: 修复重复注册守卫的恒真断言并补依赖契约用例
 3 files changed, 48 insertions(+), 7 deletions(-)
 create mode 100644 services/aicore/tests/api/test_deps.py         [exit code: 0]
```

`--no-verify` 授权同 §四（沙箱内 `sh` 不在 PATH，`.githooks/*` 对任何人都不可能执行）。提交信息经 `-F <UTF-8 文件>` 传入（不经 PowerShell 引号/编码层），type 英文 + subject 中文，**无 `[AI]` 前缀**；`git log -1 --pretty=%s` 回读无乱码。

**hook 等价复核（7 项，改在 `HEAD~1..HEAD` 的 diff 上复跑；hook 原文用 `--cached`，故用同一脚本对已提交 diff 复跑）**：

| # | 原 hook 检查 | 复跑结果 |
|---|---|---|
| 1 | 合并冲突标记（`<<<<<<<` / `=======` / `>>>>>>>`） | PASS (none)，扫描 48 条新增行 |
| 2 | 行尾空白 / 文件末尾多余空行（`git diff --check`） | PASS (clean, exit 0) |
| 3 | 大文件 >1MB | PASS (none) |
| 4 | 私钥块 / 云平台密钥（`BEGIN … PRIVATE KEY` / `AKIA…` / `ASIA…`） | PASS (none) |
| 5 | 疑似硬编码凭据（`password\|secret\|api_key\|token…`，排除 `os.environ`/`your_`/`mock` 等） | PASS (none) |
| 6 | 真实 `.env` 入库（仅允许 `.env.example`） | PASS (none) |
| 7 | commit-msg 格式 `^(feat\|fix\|…)(\(…\))?: .+` | PASS: `fix: 修复重复注册守卫的恒真断言并补依赖契约用例` |
| + | `[AI]` 前缀（hook 不查，由 AI Skill 负责） | PASS (none) |

### 九、自审本轮 diff

- **没有削弱任何断言**：M3 由"挑两个字段"改成**全等**（严格更强）；Important 由两条恒真/近似恒真改成两条真判据；既有的 `test_health_returns_200`、路由枚举方式、`conftest.py` 夹具一律未动。
- **没有为了方便而改生产代码**：`health.py`、`main.py`、`conftest.py` 零改动；`deps.py` 只动 docstring（±1 行注释），函数体与模块 docstring 未动。
- **没有为绿灯改配置**：`pyproject.toml` 零改动，未新增 `omit`，未动 `fail_under`。
- **没有引入新依赖**：`SimpleNamespace`（stdlib）与 `collections.Counter`（stdlib）。
- **新守卫不是恒真式**：两条断言各有独立阴性证据（§六 ①/②）；`Counter` 那一行不是摆设，`/health` 计数那一行同时兜住"枚举塌成空列表"的退化（F2 的永久哨兵）。
- **命名/注释**：中文注释与 docstring、英文标识符；`test_deps.py` 无 `sleep`、无网络、无数据库、无残留文件。

### 十、本轮遗留（提请控制者）

1. **覆盖率门禁仍为红（43.33% < 80）**：本轮的裁定（§三）是保留 `provider/base.py` 计入分母、不改配置。若控制者希望门禁在本组就转绿，唯一不动分母的正当做法是**为 `provider/base.py` 写真实用例**（如 `isinstance` 结构化匹配的正/反例），而不是 `omit`——那需要控制者明确授权扩大本任务范围，本轮未做。
2. **M4 的落地位置**（§五）待控制者决定是否写入 `services/aicore/VENV.md` §三。
3. **`tests/api/test_deps.py` 属简报 Files 段外新增**（§四），保留或回退均可，回退不影响其余任何断言。
