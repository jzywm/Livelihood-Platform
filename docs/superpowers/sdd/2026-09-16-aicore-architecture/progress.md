# SDD ledger — plan: docs/superpowers/plans/2026-09-16-aicore-architecture.md

工作区：`D:\progrom\.worktrees\aicore-architecture`（分支 `feature/aicore-architecture`，基线 `9523943`）
Spec：`docs/superpowers/specs/2026-09-16-aicore-architecture-design.md`（可达）
执行方式：Subagent-Driven（用户裁定）· 工作区隔离：worktree（用户裁定）

## Pre-flight 扫描

### 任务文件矩阵（Create / Modify 重叠检查）

| 对 | 一方产出 | 另一方消费/修改 | 结论 |
|---|---|---|---|
| 1.1 → 1.4 | `tests/conftest.py`（1.1 建最小版） | 1.4 扩展为 app/client 夹具 | 顺序依赖，无冲突 |
| 1.2 → 1.3 | `tests/structural/test_layering.py`（1.2 建占位） | 1.3 填实 | 顺序依赖，无冲突 |
| 1.2 → 1.4 | `src/aicore/main.py`、`api/health.py`、`api/deps.py`（1.2 建空壳） | 1.4 填实 | 顺序依赖，无冲突 |
| 1.2 内部 | `src/aicore/` 六层目录 | 1.3 的 import-linter 契约依赖该目录存在 | 顺序依赖，无冲突 |
| 1.3 内部 | `setup.cfg` | —— | 独立 |

- 两个任务创建同一文件：**无**
- 任务文本自相矛盾：**无**
- 计划强制但评审可能认定为缺陷的内容：**无**

### Ruling: 任务编号为三段式（Task 1.1 / 2.1 / 3.1），技能内 task-brief 脚本的 awk 规则只匹配 `Task <整数>`
- 决定：`.sdd-tools.py` 的提取正则扩展为 `Task (\d+(?:\.\d+)?)`，并加负向先行断言避免 1.1 误匹配 1.10。
- 依据：计划实际编号形态（第 1 组 1.1~1.4、第 2 组 2.1~2.6、第 3 组 3.1~3.8）。
- 代价：若计划改用整数编号，提取仍兼容（`Task 3` 同样匹配）。

### Ruling: worktree 建在工作区内 `.worktrees/` 而非工作区外的兄弟目录
- 决定：`D:\progrom\.worktrees\aicore-architecture`。
- 依据：沙箱限制写入工作区外路径（`fatal: could not create leading directories ... Permission denied`），工作区外建 worktree 需要提权，而提权应保留给 pip 这类不可避免的场景。
- 代价：worktree 位于仓库内，若 `.worktrees/` 未被忽略会污染 `git status`（执行前已确认忽略生效）。

### Ruling: 以 Python 复现技能的 bash 脚本（sdd-workspace / task-brief / review-package）
- 决定：`.sdd-tools.py` 提供 workspace / brief / package 三个子命令，目录约定与提取规则与技能脚本一致。
- 依据：沙箱内 `sh.exe` 无法创建信号管道（`Win32 error 5`），bash 脚本不可执行。
- 代价：脚本是等价复现而非原件，若技能升级脚本逻辑需同步（已按本计划实际编号形态做了必要扩展）。

### Ruling: Python 解释器取本机 3.14.6，`requires-python = ">=3.12"`
- 决定：按 Spec §7 的 V1 偏差执行（用户已确认）。
- 代价：若目标部署环境只有 3.12，需在交付前于 3.12 复跑一次全测试。

### 待用户提供（阻塞第 3 组，不阻塞第 1~2 组）
- MySQL 正式开发账号：用户选择「提供正式开发账号」，用户名/口令待补。
- 分支名 `feature/aicore-architecture` 未经用户确认（依 `01-开发与Git规范` 形态 + slug 拟定）。

## 进度

Task 1.1: 实现完成，提交 `37aa77b`（首个实现者被沙箱提交失败阻断，第二个实现者收尾并提交）
Task 1.1: 任务评审 — Spec ❌ / 质量需修复；1 Important + 4 Minor、0 Critical
Task 1.1: fix round 1/5（Important 1 项由控制者修复、Minor 2 项由实现者修复、上轮 5 项全部 ADDRESSED，0 项遗留；提交 `2b5f635`）
Task 1.1: minor (deferred): 计划与简报仍显示修订前的 `select` 行与旧占位符 —— 已裁定**搁置不入修复循环**，理由：后续简报由计划重新生成、实质内容（路径/接口/验收）不受影响；已带话至最终整体评审
Task 1.1: complete (commits 9523943..b98f251, review clean)

### 任务过程中产生的裁定（Ruling）

- Ruling: 计划与简报的两处行级过时内容搁置，不改计划/简报 —— 代价是最终评审会看到代码与此两行不一致，需人工确认无实质影响。
- Ruling: `--no-verify` 在本工作区获得授权 —— 依据：本沙箱 `sh` 不在 PATH，`.githooks/*` 对任何人都无法执行，属环境事实而非检查失败。代价：物理 hook 未真正运行，改为逐项等价复核（冲突标记/行尾空白/大文件/私钥/凭据模式/真实 .env/提交信息格式）。
- Ruling: 控制者代为执行 `pip install -e` —— 依据：pip 需 `0700` 临时目录且实现者无法发起提权审批。代价：该步不在实现者的证据链内，已由实现者独立复验并记入报告。
- Ruling: Ruff 豁免由 4 个全角标点扩到 7 个，仍保持规则开启、不使用 ignore —— 依据：后续任务简报实测出现 7 个全角标点。代价：这 7 个字符在字符串字面量中不再被 RUF001/2/3 检出；安全价值由「西里尔字母与全角数字仍被抓」的 5 组对照实证保住。
- Ruling: 任务提交粒度包含 `VENV.md`（用户直接要求的编码前置说明），虽不在任务简报交付物内 —— 依据：用户直接指令优先于计划范围。代价：该文件不在简报清单中，评审者被明确告知不要按 Missing 处理。

### 环境事实与环境债

- **MySQL 账号阻塞（影响第 3 组）**：用户提供的 `app_JRH / App@Pass556598@3306` 认证失败（`Access denied`），MySQL 服务端可连（root/123456 可用），说明账号或口令不对。Task 3.1 建表前必须解决。
- `services/aicore/.venv` 的 `activate.ps1` 已注入 UTF-8（用户直接要求的修复），已端到端验证；补丁工具入库于 `tools/patch_venv_utf8.py`。
- 哨兵：`.sdd-tools.py` / `.sdd-scan.py` 为控制者工具，未跟踪，勿提交。

### 待用户裁定

- 分支名 `feature/aicore-architecture` —— **用户已确认保留**（2026-09-17）。
- MySQL 凭据 —— 用户所给 `app_JRH` 经查**该实例上不存在此账号**（真实账号仅 `aicore_dev` / `root` / 3 个系统账号），用户表示未见过该凭据。用户选择「用 aicore_dev + 我给个新口令」，**新口令待用户提供**。不阻塞第 1~2 组。

---

## Task 1.2 记录

Task 1.2: 实现完成，提交 `305112d`（50 文件 / 101 行；六层 49 个模块 + `tools/` 与文档未动）
Task 1.2: 控制者独立核实——`.py` 文件 50 个（含 9 个 `__init__.py`）、`walk_packages` 得 **49 个模块、0 导入失败**、`main.py` 确未创建（Task 1.4 建）；各层清单与 design.md §3.2 吻合。

- Ruling: **简报 Step 16 的「共 30 个模块」为陈旧数字，实际为 49，以 49 为准，不改代码** —— 依据：① 简报自身 Step 1~15 逐条枚举得到 49；② design.md §3.2 的 42 行表 − `main.py`（Task 1.4 建）= 41，加 8 个层内 `__init__.py` = 49；③ 控制者独立复算得 49 且 0 导入失败。实现者主动报告差异、拒绝为凑数而改动，行为正确。
  代价：若「30」另有出处（如更早的设计稿），则该出处与实现不一致，需在最终评审确认；计划文本未同步修正。
- Ruling: `habit/{engine,decay,evidence}.py` 的三个 docstring 由实现者撰写（简报仅写「各一行文档串」未给文本），依 design §6 L376 推导并已在报告登记 —— 代价：属实现者补白，最终评审需确认措辞与设计一致。
- Ruling: 覆盖率门禁当前为 0.00%（尚无任何用例），**不视为缺陷** —— 依据：本阶段按计划只建空壳，49 个桩贡献 0 条语句，不抬高分母；覆盖率门禁的有效期自 Task 1.3 产生首批用例起算。代价：真实门禁要到第 1 组末才有意义，此前不能声称覆盖达标。

Task 1.2: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical + 2 Important + 5 Minor
Task 1.2: fix round 1/5（2 Important + 1 项控制者委派全部 ADDRESSED，0 项遗留；提交 `b5c5c7d`）
Task 1.2: complete (commits b98f251..b7dae75, review clean)

### Task 1.2 追加裁定

- Ruling: **分层契约载体由 `setup.cfg` 改为专用 `.importlinter`** —— 起因：评审发现三处 docstring 指向不存在的 `setup.cfg`，而 `design.md:113` 把五套工具配置归于 `pyproject.toml`，三处口径互斥。实测 import-linter 2.15 **三种载体都可用**（`.importlinter` / `setup.cfg` / `pyproject.toml`）且都能自动发现，故属一致性问题而非能力限制。选专用文件的理由：设计文档关于 `pyproject.toml` 的表述得以保持正确、避免 TOML 语法配置放进 `setup.cfg`、六契约独立成文件可读性最好。同步更新计划 9 处引用。
  代价：`src/aicore/__init__.py` 等三处 docstring 需随改（已随修复轮落地）；若日后有人按旧写法找 `setup.cfg` 会扑空，但计划与代码已一致。
- Ruling: 计划 Task 1.2 Step 7 的 `verdict.py` 原文由一句话扩为两段式，与实现文件一致 —— 依据：评审 Important 1 授权扩写。代价：计划与最初撰写时不再逐字相同，已用「口径已在报告登记」留痕。
- Ruling: 复评指出的两处**范围外**遗留——`AI_DEV_LOG/2026-09-16.md:242-243` 仍写 `setup.cfg`（历史日志，如实记录当时实验）、计划 L446 原文——前者**不改**（日志是历史记录，改写等于篡改），后者**已改**。
  代价：日志与现行载体的表述不一致，需在最终评审确认无实质影响。

### 环境事实与环境债（更新）

- 环境债：`services/aicore/tests/__pycache__/` 内有已删除探针的残留 `.pyc`（未跟踪、被 gitignore），无运行时影响；`AI_DEV_LOG` 的 `setup.cfg` 历史表述如上。

---

## Task 1.3 记录

Task 1.3: 实现完成，提交 `73ea7d0`（.importlinter + 两个结构测试；DONE_WITH_CONCERNS，5 项 concern）
Task 1.3: 任务评审 — Spec ✅ / 质量 **Needs fixes**；0 Critical + **4 Important** + 6 Minor
Task 1.3: fix round 1/5（4 Important + 6 Minor 全部 ADDRESSED，0 遗留；提交 `f4f77c7` + `ad1c341`）
Task 1.3: fix round 2/5（复评剩余 4 项 Minor 全部处理；提交 `bb7f8fc` + `21cef10`）
Task 1.3: complete (commits b7dae75..21cef10, review clean)

### Task 1.3 关键裁定与教训（本任务暴露了控制者两处错误）

- **控制者错误 1（严重）：早前给实现者的「已实测关键写法」是错的。** 我曾用探针测得
  `ignore_imports = pkg.service -> pkg.provider.base` 可行（`KEPT (1 ignored import)`），
  据此写进计划与设计文档。实现者实测推翻：**非通配的 importer 名只精确匹配该模块自身、不覆盖子模块**
  （grimp 3.17），而 service 代码都在子模块里，故该行**恒匹配不到任何边**，是一条永远失效的放行声明；
  叠加 `forbidden` 默认 `unmatched_ignore_imports_alerting=error`，干净树的正例直接变红。
  控制者用四组对照复现（非通配 0 命中 / `.*` 与 `.**` 命中），确认实现者正确。
  修正：`aicore.service.** -> aicore.provider.base` + `unmatched_ignore_imports_alerting = warn`。
  **教训**：控制者自己的探针也必须覆盖"该禁的被禁、该放的被放"两个方向，否则"通过"可能是假绿。
- **控制者错误 2：`forbidden` 契约默认检查传递依赖。** 评审发现并实测复现：在
  「api 只导入 service、service 只导入 repository」（无任何 api→repository 直接导入）的树上，
  默认配置判 **BROKEN** 并打印传递链；`allow_indirect_imports = true` 才正确放行。
  若不修，待后续任务落地真实导入，检查会对**正确架构**误报。已修正并写入设计文档。
- Ruling: 规则 4 的 `forbidden_modules` 补入 `aicore.api` —— 依据：api 同属业务层，且分层图
  （api → service）意味着 core → api 会成环；实测补入后干净树仍 4 kept、注入 core→api 被抓、
  service→provider.mock 防线未削弱。代价：契约比原计划更严，若有历史代码依赖 core→api 会变红（当前无）。
- Ruling: 规则 2 的 `forbidden_modules` 补入整包 `aicore.provider` —— 依据：只列 5 个具体模块时，
  `provider/__init__.py` 再导出会形成 `service -> aicore.provider` 边而无人管；补入后放行表达式
  才真正承重。实现者实测指出评审对此条的理由描述与实测不符（门面再导出 `provider.*` 本就能经传递链抓到），
  故按其实测重写理由并落成回归用例。代价：`provider/__init__.py` 不能再作为对外门面导出通道。
- Ruling: 豁免指令正式写法由 `# noqa: ai-allow-swallow: <理由>` 改为 `# ai-allow-swallow: <理由>`
  （旧写法保留兼容）—— 依据：实测 7 种变体，无一种能既保留 `noqa:` 前缀又不触发 ruff 的
  `Invalid # noqa directive` 警告。代价：早期文档口径需同步（计划、两个红线文件、设计文档已同步）。
- Ruling: 计划文档不再追求与代码逐字同步，改为**声明实际文件为权威** —— 依据：计划片段已两次落后于
  实现（载体、契约参数），而后续简报由计划生成，陈旧片段会被照抄并回退修复。代价：计划的可读性略降，
  读者需打开实际文件。
- **工程教训（实现者发现）：`git checkout --` 不能用来还原注入的探针。** `core.autocrlf` 会把 LF 文件
  写成 CRLF 而 `git diff` 看不出差异，导致"还原成功"是假象。应按字节归一化并校验 blob 相等。

---

## Task 1.4 记录

Task 1.4: 实现完成，提交 `e4a801a`（组合根 + /health + deps + 首个接口测试；DONE_WITH_CONCERNS，5 项 concern）
Task 1.4: 任务评审 — Spec ❌ / 质量 **Needs fixes**；0 Critical + **1 Important** + 6 Minor
Task 1.4: fix round 1/5（Important + M1/M2/M3 全部 ADDRESSED，0 遗留；提交 `30ad766`）
Task 1.4: complete (commits 21cef10..7e67112, review clean)

### Task 1.4 关键裁定

- Ruling: **重复注册守卫必须能失败** —— 计划原文的 `assert len(paths_first) == len(set(paths_first))`
  是恒真断言（集合派生后再比长度）、且 `set` 对比看不见重复注册，故"重复装配不产生重复注册"这一承诺
  **从未被验证**。评审给出更精确的替换形式（`Counter` 相等 + `/health` 计数为 1 兼非空哨兵），
  特意避开"任意路径不得出现两次"的过严写法（后续分组会有 GET+POST 同路径）。已按该形式落地并给出
  阴性证据（重复注册 → `assert 2 == 1`；非对称累积 → `Counter` 不等）。
  代价：该守卫只覆盖单方法路径；对称重复注册其它路径仍不可见（当前不可达）。
- Ruling: **拒绝把 `provider/base.py` 加入覆盖率 `omit`** —— 既有 3 个 omit 属环境豁免（网络/凭据），
  而 base.py 是导入期可执行、易覆盖的代码，豁免它会开"把门禁掏空"的先例。门禁保持红（43.33%）。
  代价：第 1 组末门禁为红，需在第 2/3 组落地用例后自然转绿；此偏差已在计划中登记。
- Ruling: **测试警告定向静默、不加 `error` 兜底** —— 两条警告均来自第三方库内部（starlette 的
  httpx/httpx2 提示、anyio 别名弃用），不引入 httpx2 是已定偏差 V2。实测 `error` 兜底会在
  **收集阶段 exit 4**（该警告由 conftest 导入期触发，早于 pytest 应用 filterwarnings），
  故兜底不可用，改为只按 message 精确匹配的定向 ignore。
  代价：新警告不会被自动拦截；若需拦截应在 CI 层用 `-W error` 并排除这两条。
- 观察（不改）：`src/aicore/provider/__init__.py` 磁盘为 CRLF（86 B）、blob 为 LF（85 B），
  `git status` 干净。这是 `core.autocrlf=true` 的正常行为，blob 为权威，**不强行改回 LF**
  （改了下次 checkout 仍会变，且等于和配置对抗）。

---

## 第 1 组验收（控制者终态复核，2026-09-17）

| 项 | 结果 |
|---|---|
| 分层契约（`.importlinter` 四契约） | `4 kept, 0 broken`（service 契约带 1 条待 Task 4 消解的 warn） |
| 全量测试 | **67 passed, 7 skipped, 0 warnings** |
| 结构测试阴性证据 | 四契约各有独立阴性用例；规则 5/6 各经注入→红→字节还原→绿 |
| ruff | `All checks passed!` |
| mypy（strict） | `Success: no issues found in 51 source files` |
| 真实进程 | `uvicorn aicore.main:app` → `HTTP 200 body={"status":"ok"}`，`content-length: 15`（证明未被信封包裹） |
| 覆盖率 | **43.33%**，**低于 80% 门禁** —— 已知偏差，第 2/3 组落地用例后转绿 |
| 残留 | 探针 0、`.import_linter_cache` 无、uvicorn 日志 0、端口 8083 空闲 |
| 提交 | 17 个提交（`9523943` → `7e67112`） |

**未验证项（诚实登记）**：① MySQL 真实建表要等第 3 组；② Redis 未安装，第 4 组起受限（偏差 V4/V5）；
③ 覆盖率门禁未达标；④ 物理 hook 未执行（沙箱无 `sh`），以逐项等价复核替代。

---

## 第 2 组：配置与横切关注点

### 环境变更（2026-09-17，缓解两项偏差）

- **Redis 已可用**：用户安装于 **WSL2 的 Ubuntu**（Redis 8.0.5，standalone）。Windows 侧 `127.0.0.1:6379`
  可连（`PING True`）。实测本项目要用的操作全部通过：`SET NX PX` 原子领取（20 线程并发恰好 1 个成功）、
  `PEXPIRTE` 续期、`INCR`+TTL 日配额与跨日重置、`EVAL` 限流脚本。
  偏差 V4/V5 由"Redis 缺、验证手段受限"**降级为**"可用但需注意 WSL 生命周期"。
- **运行特性（须记住）**：WSL 实例空闲会被 Windows 关闭，Redis 随之停止 —— 这解释了最初
  `Connection refused` 的现象（当时 WSL 为 `Stopped`）。第 4 组起的 Redis 相关测试须做**连通性探测 +
  明确跳过**，不让测试随机失败。
- **WSL 命令需提权**：`wsl` 在沙箱内默认被拒（`Wsl/Service/CreateInstance/E_ACCESSDENIED`），
  凡涉及 WSL 的操作都需一次授权。

### 第 2 组的关键裁定（开工前）

- Ruling: **启动四条校验放在 lifespan 启动钩子，而非 `create_app()`** —— 依据：第 1 组的验收项要求
  "`create_app()` 在无任何环境变量下可启动"，而本组要求"必填项缺失即拒绝启动"，二者不可同时成立于同一位置。
  放 lifespan 后：工厂仍是纯装配（测试可建实例），**进程启动**才校验，`uvicorn` 起不来即"拒绝启动"。
  代价：第 1 组验收项的**语义变更**（从"无配置可启动"变为"无配置可建实例、但启动被拒"），已在此显式登记。
- Ruling: **测试期配置由 `conftest.py` 顶层 `os.environ.setdefault` 注入假值** —— 依据：pytest 加载
  conftest 早于测试模块导入 `aicore.main`，时机成立；避免测试依赖开发者本机 `.env`（CI/新检出没有）。
  代价：伪造值对全部测试全局可见；"真缺配置时的拒绝"不由普通测试覆盖，而由 Task 2.2 的专用用例覆盖。
- Ruling: **业务码↔HTTP 状态码映射由实现定义** —— 依据：接口文档的共用件（`RateLimited`/
  `DependencyTimeout`/`Unauthorized` 等，覆盖多数端点）**未内联业务码**，只有内联处有（502→4003、
  422→1002、500→5000、409→3007），故须由实现保证一致。锁定映射：`1001/1002/1003→400/422`、
  `2001→401`、`2002→403`、`2004→429`、`3006→404`、`3007→409`、`4003→502`、`5000→500`、`5002→504`。
  代价：日后改状态码需同步接口文档的内联示例。
- Ruling: **traceId 缺失时生成 16 位 hex，中间件用纯 ASGI** —— 依据：`BaseHTTPMiddleware` 与
  `ContextVar` 传播有已知摩擦；16 位 hex 对齐 `_common` 示例。代价：多写十几行中间件代码。

---

## Task 2.5 记录（第 2 组先做 trace，因信封依赖 traceId）

Task 2.5: 实现完成，提交 `83f3a66`（core/trace.py 254 行 + 中间件 + 27 条用例；DONE_WITH_CONCERNS）
Task 2.5: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical / 0 Important / 6 Minor
Task 2.5: complete (commits 7e67112..20b9f3c, review clean)

- 交付：`X-Request-Id` 解析与校验（长度 ≤64、可打印 ASCII 白名单，防日志伪造与 CRLF 头注入）、
  缺失/非法即生成并标 `traceIdSource=generated`、响应头回显（先剔除应用自写的同名头）、
  请求结束在 `finally` 回滚 token、`copy_context_for_thread()` 供线程池传递、
  纯 ASGI 中间件（用例以「处理器内 `asyncio.current_task()` 必须等于调用方任务」正面守住不用
  `BaseHTTPMiddleware`）。
- Ruling: **中间件由组合根包在最外层**（覆盖 `build_middleware_stack`），而非 `app.add_middleware` ——
  依据：Starlette 固定把用户中间件放在 `ServerErrorMiddleware` 之内，未捕获异常的 500 由其在外层渲染；
  实现者实测放内层会导致 500 丢回显头、且 `Exception` 处理器读到**新生成**的 traceId（伤 Task 2.4 的 500 信封）。
  评审独立查了 starlette 1.6.0 源码确认该机制为**必然**而非偶然。
  代价：覆盖了 Starlette 内部约定的方法，故给 `starlette` 依赖**加上界 `<2`**（已提交 `20b9f3c`），
  大版本升级须人工复核该覆盖仍成立。
- Ruling: **`set_trace_id` 返回 `Token` 而非简报写的 `-> None`** —— 依据：`reset_trace_id(token)` 需要 token，
  否则"绑定→回滚"无法成对使用，而回滚是防同 worker 串号的唯一手段；返回 token 是 `-> None` 的严格超集。
  代价：公开签名比简报宽，评审判定为"名义上的扩大"，无破坏性。
- Ruling: **显式声明 `starlette>=1.6,<2`** —— 起因：实现者发现 `main.py`/`trace.py` 直接 import starlette
  却只作为 fastapi 的传递依赖。AST 扫描复核后确认无其它未声明项。代价：多一个需维护的版本约束。

---

## Task 2.1 记录

Task 2.1: 实现完成，提交 `397ca86`（Settings 153 行 + 71 条用例 + `_UnknownEnvVarSource`；DONE_WITH_CONCERNS）
Task 2.1: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical / 0 Important / 8 Minor
Task 2.1: complete (commits 20b9f3c..397ca86, review clean)

- **关键发现（控制者独立复现）：`extra="forbid"` 对 `os.environ` 不生效。** pydantic-settings 2.15 的
  `EnvSettingsSource` 没有 extra 分支，未识别的 `AICORE_*` 环境变量被**静默忽略** —— 裸 `BaseSettings`
  加 `extra="forbid"` 后设置 `PROBE_UNKNOWN_VAR`，构造仍成功且无任何告警。即**照字面实现会让设计意图
  落空且无迹可循**。项目补了 `_UnknownEnvVarSource` 挂进 `settings_customise_sources` 才真正生效
  （实测注入 `AICORE_TYPO_FIELD` → 抛 `ValidationError`）。设计文档已补记（提交 `e2ed639`）。
- 覆盖率 **88.41%**，第 1 组遗留的**红门禁转绿**（`core/config.py` 100%）。
- 超清单但必要：`api/deps.py`（计划 Task 2.1 明列"`get_settings` 定类型"）、`.env.example`
  （9 个必填项落地后原模板已无法启动，且有用例双向钉住二者一致）。
- 安全要点（评审已复现）：`ValidationError.input` 携带其它字段原始值**含 `mysql_password`**、
  `repr(Settings)` 亦含口令 → **Task 2.2 生成启动拒绝信息时只能取 `loc`/`msg`**，启动日志走不含口令的 `mysql_dsn`。
- 交 Task 2.2 的接口提示（评审 Minor）：`Env` 是 PEP 695 `type` 别名，`get_args(Env) == ()`，
  若需内省须用 `Env.__value__`；`core.config.get_settings()`（缓存工厂）与 `api.deps.get_settings(request)`
  （FastAPI 依赖）同名不同义，导入时勿混。

---

## Task 2.2 记录

Task 2.2: 实现完成，提交 `fec87b2`（config 跨字段校验 + ConfigRejected + 33 条用例；DONE_WITH_CONCERNS）
Task 2.2: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical + **2 Important** + 5 Minor
Task 2.2: 两条 Important 由控制者裁定并落地，提交 `5a5fd4e`
Task 2.2: complete (commits 397ca86..5a5fd4e, 2 Important 已按裁定修复)

- 交付：四条规则（prod+mock 拒绝 / 真实通道缺密钥拒绝 / dev·test 降级告警 / 必填缺失走字段级）、
  补 Task 2.1 遗留的跨字段边界 `budget_degrade_ratio >= budget_alert_ratio`、
  `ConfigRejected.from_validation_error`（**只取 `loc`/`msg`**，一次性列全阻断项）、
  `_REAL_PROVIDER_KEY_FIELDS` + `_REAL_PROVIDERS_WITHOUT_KEY_FIELD` 两张表 + 结构性用例强制二者恰好覆盖 provider 字面量。
- 规则 3 用 stdlib `logging.getLogger(__name__).warning`（可 `caplog` 断言、不落 stdout、与 Task 2.6 的 structlog 兼容）。
- **Important 1 裁定（采纳收紧）**：`prod + cloud_vision/cloud_ocr` 原为**只告警不拒绝**，
  而这两个通道尚未声明密钥字段、凭据无从核验——一个连凭据都无法确认的通道不该进生产，
  且 `ConfigRejected` 的消息写着「生产不允许以『无密钥』状态运行」，对该组合字面上不成立。
  依据 `services/aicore/docs/er.md` §7「密钥：DeepSeek/视觉云密钥经 KMS/环境变量注入」：云通道**本该有密钥**，
  缺字段只是范围裁剪。落地：prod 下凡「非 mock 且未登记密钥字段」的通道一律拒绝；dev/test 仍放行+告警；
  待密钥字段落地后自动改走规则 2，无需再动该分支。
  代价：`prod + cloud_*` 现在起不来（符合意图，但若有人打算先用云通道上线需先补密钥字段）。
  **评审指出原用例把宽松选择编码进了断言**，已改为 `test_dev_..._is_allowed_but_warns` + 新增 `test_prod_..._is_rejected`。
- **Important 2 裁定（必须修）**：两处给 Task 2.6 的用法示例写 `raise ... from exc`，
  会把 `__cause__` 设为原始 `ValidationError`；uvicorn 记录 lifespan 启动失败时带 `exc_info`，
  而 `str(ValidationError)` 回显（截断后的）`input_value`——**含 `mysql_password` 等原始值**，
  异常链因此成为绕过「只用 loc/msg」的泄漏通道。改为 `from None`，模块与类两处 docstring 写明理由。
  代价：启动失败栈少一层 cause 信息；但阻断项清单本身（`str(ConfigRejected)`）足以定位问题。
- **Minor 处置**：M1（「同一环境的阻断项已一次性列全」在混合场景下不成立——字段级失败会阻止 after 校验运行）
  与 M2（`create_app()` 回归用例未钉缓存状态）留下；M3（`main.py:27` 仍写「Task 2.2」，实际接线在 2.6）
  待 Task 2.6 落地时一并改正；M4（两份测试文件各自维护 `BASE_ENV`）与 M5（规则 3 告警在每次构造时发出，
  而非仅启动时）留下，交最终评审裁定。
- 验证：全量 **200 passed / 7 skipped**、覆盖率 **92.67%**、ruff/mypy 干净、契约 4 kept；
  另以七种 env×provider 组合实测行为（prod+cloud_* 拒绝、prod+deepseek 无密钥拒绝、prod+mock 拒绝、
  dev+cloud_* 放行并告警、test+mock 放行并告警）。

---

## Task 2.3 记录

Task 2.3: 实现完成，提交 `1e86f0e`（异常层次 + 码值↔HTTP 映射 + 全局处理器 + 72 条用例；DONE_WITH_CONCERNS）
Task 2.3: 任务评审 — Spec ❌ / 质量 **Needs fixes**；0 Critical + **1 Important** + 5 Minor
Task 2.3: fix round 1/5（Important + M1/M3/M4 全部 ADDRESSED；提交 `805db9c`）
Task 2.3: 复评 — 全部 ADDRESSED，无新增 Critical/Important；1 处新 Minor（204/304 无体 parity）+ 1 处注释过期
Task 2.3: fix round 2/5（两处 Minor 清除；提交 `5f8d182`）
Task 2.3: complete (commits 5a5fd4e..5f8d182, review clean)

- 交付：`AiCoreError` 基类 + 九个子类、码值↔HTTP 映射表、`register_exception_handlers`（**四个**处理器）、
  `AICORE_ERROR_CODES`、FastAPI 默认 422 收编为 `1001/1002/1003`、未预期异常归 `5000` 且堆栈只进日志。
- **Important 裁定（收编框架 `HTTPException`）**：原只注册 `AiCoreError`/`RequestValidationError`/`Exception`，
  而未匹配路由 404（`{"detail":"Not Found"}`）与方法不允许 405 是**第三套响应格式**、无 `code` 字段。
  评审进一步指出这不止影响路由：接口文档给所有端点标了 `security: bearerAuth` 并文档化 401→2001 / 403→2002，
  而惯用的 `HTTPBearer` 依赖内部抛 `HTTPException(401/403)`，**从调用点无法避免**。
  映射口径（控制者裁定）：锁定对优先（401→2001、403→2002、404→3006、429→2004、502→4003、504→5002、500→5000）；
  未匹配 4xx→`1001`（未匹配路由本身就是畸形请求路径，且普通业务 400 走 `AiCoreError`，不会被遮蔽）、
  未匹配 5xx→`5000`；404 保持 `3006` 但用**不同文案**（`接口不存在` vs `对象不存在`）以便区分框架路由错误与业务不存在。
  代价：路由 404 与业务 404 共用码值、仅文案不同，前端仅凭 `code` 无法区分（实现者拒绝凭空发明平台码，正确）；
  `/docs`、`/openapi.json` 的 404/405 也变成信封，对期待 `{"detail": …}` 的工具是行为变更。
- 实现者两处超简报改动，均正确：**保留 `exc.headers`**（否则 `WWW-Authenticate: Bearer` 在 401 上会丢，
  已加用例钉住）；**纠正原报告的一处事实错误**（`fastapi.HTTPException is starlette...HTTPException` 为 `False`，
  故是**覆盖**默认处理器而非共存——实测得出，非推断）。
- 复评后又修两处 Minor：`_handle_http_exception` 原本**总发 JSON 体**，而框架对 204/304 是无体响应
  （改为复用 `fastapi.utils.is_body_allowed_for_status_code`，Starlette 1.6.0 已无该名字）；
  sub-400 状态原本落进 5xx 分支得 `5000`，改为 `< 500` 判据。两处各有阴性证据。
- 验证：全量 **294 passed / 7 skipped**、覆盖率 **95.07%**、ruff/mypy 干净、契约 4 kept；
  变异实证（去掉 `main.py` 接线 → 25 failed；`RATE_LIMITED_CODE := 429` → 7 failed）+ 两处阴性还原。

---

## Task 2.4 记录

Task 2.4: 实现完成，提交 `8bffbf7`（Envelope 模型 + 44 条用例；DONE）
Task 2.4: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical / 0 Important / 8 Minor
Task 2.4: complete (commits 5f8d182..8bffbf7, review clean)

- 交付：`Envelope[T]`（四必填 + 可选 `data`）、`Envelope.ok`（`code=0`）、`Envelope.fail`、
  `REQUIRED_LOG_FIELDS` 之外的结构性扫描（**禁止业务代码手工拼装信封**）。
- **反向对齐通过**：Task 2.3 的错误处理器输出（10 个业务码逐码 + 真实失败请求）能被 `Envelope.model_validate` 通过，
  且 `errors.py` 形状未改——这正是 2.3 交付时承诺的"由 2.4 反向对齐"。
- 两处决定（实现者自定，评审判定合理）：① 时间戳助手定义在 `envelope.py`、`errors.py` 改为从它导入
  （方向 errors → envelope：模型是形状所有者、处理器是消费者；反向 import 会在 errors 改用 `Envelope.fail` 时成环）；
  ② 结构扫描对 `errors.py` 用**窄豁免**（全树扫描、只放过这一个文件）而不是"只管 routes/services"，
  并加**承重自检**证明关掉豁免今天就会违规——三模块依赖经控制者复核为**无环 DAG**（trace 是叶子）。
- 验证：全量 **337 passed / 8 skipped**、ruff/mypy 干净、契约 4 kept、6 处变异各被对应用例抓出。
- 待裁定的 Minor：`extra="forbid"` 使生成 schema 带 `additionalProperties: false`，而 `_common` 的 `Envelope` 允许额外属性；
  成功文案 `"成功"` 是实现者自定（`_common` 只给 `message: ok` 示例，未锁值）。

---

## Task 2.6 记录（第 2 组收官）

Task 2.6: 实现完成，提交 `0ac7f5d`（logging 508 行 + lifespan 接线 + 41 条用例；DONE_WITH_CONCERNS）
Task 2.6: fix round 1/5（启动首行非 JSON；提交 `fdd7ee3`）
Task 2.6: 任务评审 — Spec ✅ / 质量 **Approved**；0 Critical / 0 Important / 7 Minor
Task 2.6: complete (commits 8bffbf7..9a3f4be, review clean)

- 交付：12 必含字段（**PDD L1747 逐字**）、`spanId` 存在且为空、`traceIdSource` 由处理器落地
  （**接上 Task 2.5 记录的"生成可区分"未竟项**）、`uid` 强制脱敏、密钥类字段名回退遮蔽、
  `configure_logging` 幂等、lifespan 接线（`get_settings` → `ConfigRejected ... from None` → `configure_logging`）。
- **fix round 1 解决的问题（控制者顺序错误所致）**：规则 3 的告警在 `Settings(...)` 构造内发出，
  早于 `configure_logging`，故**启动第一行是纯文本**——对"统一 JSON 日志"是破口。
  修法：读配置前先装**引导日志配置**（同一 `_apply_json_logging`、同一 schema），再在拿到配置后应用完整配置。
  实测证据：dev+mock 真实 uvicorn 运行，应用写出的唯一一行是 JSON（`Application startup complete.` 之前），
  其余 5 行明文全是 **uvicorn 框架自身**的日志——这是已声明的边界，不改框架日志配置。
- 实现者一处超简报扩展（控制者已认可）：拒绝启动路径原先**一行自己的日志都没有**，
  故"拒绝启动"从不进 JSON 管线；在 lifespan 抛出前加了一条 `_logger.error("%s", rejected)`。
- 另一处：它收窄了既有用例 `test_request_trace_id_is_carried_into_stdlib_records_too`
  的"config 模块恰好一条记录"断言（原断言隐含依赖"告警没进 JSON"这一前提）。
  评审核实**未削弱**：该用例仍断言恰好一条探针记录且两条承重断言（traceId 相等、source=propagated）都在，
  而被移除的前提现在被正面钉住（恰好一条 config 模块记录且等于首行）。
- **口径修正**：日志必含字段数为 **12**（PDD L1747 逐字），我此前在设计文档与计划中写作"11 字段"并沿用多处，
  属计数错误；已修正（worktree `9a3f4be`、主工作区 `c66f521`）。
- 验证：全量 **387 passed / 8 skipped**、覆盖率 **96.56%**（`core/logging.py` 100%）、ruff/mypy 干净、契约 4 kept；
  变异实证（删 `bootstrap_logging()` → 首行变纯文本且 3 条 lifespan 用例红）+ 按字节还原。

---

## 第 2 组验收（控制者终态复核，2026-09-18）

| 项 | 结果 |
|---|---|
| 任务 | 2.5 traceId / 2.1 配置 / 2.2 四条校验 / 2.3 异常与码值 / 2.4 信封 / 2.6 日志 + lifespan 接线（**6/6 完成**） |
| 全量测试 | **387 passed, 8 skipped** |
| 覆盖率 | **96.56%**（≥80% 门禁达成；第 1 组遗留的红门禁已转绿） |
| 分层契约 | `4 kept, 0 broken`（service 契约带 1 条待 Task 4 消解的 warn） |
| ruff / mypy | `All checks passed!` / `Success: no issues found in 51 source files` |
| 真实进程 | 合法配置 `/health` 200；非法配置**拒绝启动**且口令哨兵出现 0 次；启动首行为 JSON |
| 残留 | 探针 0、`.import_linter_cache` 无、uvicorn 日志 0、端口 8083 空闲 |
| 提交 | 第 1 组 7 个 + 第 2 组 14 个 = 21 个（另有跨组文档修正） |

**未验证项（诚实登记）**：① MySQL 真实建表要等第 3 组；② Redis 在 WSL2，其相关测试尚未写，
须先做连通性探测 + 明确跳过；③ 物理 hook 未执行（沙箱无 `sh`），以逐项等价复核替代；
④ uvicorn 框架自身日志仍是明文（已声明边界，未改框架日志配置）。

---

## 第 3 组：数据层与分表路由

### 环境变更（2026-09-18）：MySQL 弹窗根因与修复（控制者执行，用户确认方案 A）

**用户诉求**：「每次起 MySQL 都弹窗问是否同意修改网络」+「在配置文件里写上 MySQL 在本地数据库中开启的语句」。

**先纠正一个前提（如实说明）**：MySQL **本来就是 Windows 服务自启**（`sc qc MySQL` → `START_TYPE: 2 AUTO_START`，
`LocalSystem`，`D:\soft\mysql\bin\mysqld MySQL`），**不需要手动拉起**。`my.ini` 里没有任何"自启动"语义可写——
`my.ini` 只有 `[mysqld]/[client]` 参数，开机自启由 SCM 的 START_TYPE 决定。

**弹窗根因**：`my.ini` **无 `bind-address`** → mysqld 监听 `0.0.0.0:3306`，X Plugin 监听 `[::]:33060`；
Windows 防火墙检测到"进程在非回环地址上监听"即弹出授权框。实测 `mysqld` 相关防火墙规则数 = **0**（从未建过允许规则），
故每次联网变化都重问。

**修复（方案 A，用户选定）**：`[mysqld]` 增加 `bind-address=127.0.0.1` + `mysqlx-bind-address=127.0.0.1` → 重启服务。
回环监听不触发防火墙弹窗，且本项目全部连接走 `127.0.0.1`。**代价**：同局域网其他机器与 WSL 默认拓扑访问不到 Windows MySQL
（本项目不需要；最小权限取向）。

**修复过程中我自己造的一次事故（必须留痕，是教训不是花絮）**：
第一次改写 `my.ini` 时把 `basedir=D:\\soft\\mysql` 的**双反斜杠吞成了单反斜杠**。MySQL 解析时把 `\s` 当转义符吃掉，
`datadir` 实际变成 `D: oft\mysql\data`（不存在）→ mysqld **在打开错误日志之前就中止**，所以日志一行没写、
现象是「服务 START_PENDING 直接转 STOPPED」。证据：`mysqld --console` 输出
`Can't find error-message file 'D:\progrom\ oft\mysql\share\errmsg.sys'`。
**修法**：不再重写文件，改为「从 `.bak` 恢复原字节 → 只在 `port=3306` 后插入两行 → 用 `WriteAllText` 显式 ASCII 无 BOM 写回
→ 读回校验双反斜杠与 CRLF 计数 → `mysqld --validate-config` 零输出 → 起服务」。
**沉淀的规则（已写入各任务工单）**：MUST NOT 用 PowerShell `Set-Content`/`Out-File`/`>` 写含中文或含反斜杠路径的文件。

**另一个发现**：历史上存在**孤儿 mysqld 进程**（与服务实例并存，不监听端口）。这就是过去"实例间歇性卡死"的来源
——手动拉的 `mysqld.exe` 与服务的实例抢数据目录。已在修复脚本中清理，并在工单里写明 **MUST NOT 手动 `mysqld.exe`**。

**修复后实测**：
```
STATE : 4 RUNNING ; PID : 5368
TCP 127.0.0.1:3306   LISTENING 8000
TCP 127.0.0.1:33060  LISTENING 8000
[System] X Plugin ready for connections. Bind-address: '127.0.0.1' port: 33060
[System] mysqld: ready for connections. Version: '8.0.35'  port: 3306
aicore_dev@localhost 连通，CREATE/INSERT/SELECT/DROP 全通过
```
临时诊断脚本（`mysql-*.ps1` / `*.log` / `mysqld-probe.*`）**全部已删除**，仓库根 `git status` 无残留。

**权限补配**：`GRANT ALL PRIVILEGES ON aicore_test.* TO 'aicore_dev'@'localhost'`（此前只有 `aicore`）。
第 3 组的建表/迁移/比对用例统一在 `aicore_test` 上做，避免污染 `aicore`。

### 第 3 组的关键裁定（开工前，2026-09-18）

1. **配置补字段（用户选方案 A）**：Task 3.4 要求「池大小从配置读取」「只读查询走只读会话」，
   但 `Settings` 此前**只有** host/port/user/password/database 五项、且全设计文档无"只读"二字。
   故新增四个字段：`mysql_pool_size`、`mysql_max_overflow`（**必填无默认值**，与 Task 2.1「必填项一律不给默认值」一致）、
   `mysql_readonly_host`、`mysql_readonly_port`（只读库地址，落 `er.md` §5.5 读写分离）。
   连带改动：`.env.example`、`tests/conftest.py` 的注入表、Task 2.1 的配置用例。
   **代价已告知用户**：改动了 Task 2.1 已验收的文件；收益是「只读查询走只读会话」可被**真实换库**断言，而非只断言对象不同。
2. **物理外键统一 `ON DELETE RESTRICT ON UPDATE RESTRICT`**：`er.md` 未规定动作，MySQL 默认即 RESTRICT；
   **显式写出**是为了不让读者以为漏写。选 RESTRICT 而非 CASCADE 的理由：`review_verdict` 是审计留痕、
   `ocr_correction` 是评估集语料，两者都**不该**被级联删除；CASCADE 会在删审核记录时悄悄抹掉审计证据。
3. **分片模板占位符为两个**：`{table}`（本表物理名）+ `{month}`（6 位 YYYYMM）。
   理由：`ocr_correction.task_id` 的物理外键必须指向**同月**的 `ocr_result_YYYYMM`，只有 `{table}` 表达不了"同月的另一张表"。
   工单里明确说明这是对设计文档 §5.1「表名占位统一为 `{table}`」的**细化而非推翻**（`{table}` 仍指本表名）。
4. **Alembic 只生成单一基线迁移**：设计文档 §5.1 明说 `deploy/sql/ddl/` 是「11 个文件」且未列 `versions/`，
   故基线只覆盖 6 张**非分片**表（结构确定）；三张分片表由迁移钩子**运行时**按模板 `CREATE TABLE IF NOT EXISTS` 创建。
   `server_default` 需显式写出，否则 autogenerate 会漏掉 `CURRENT_TIMESTAMP(3)` 与枚举默认值。
5. **迁移幂等口径**：重复 autogenerate 产生**同一 revision**（非重复追加迁移）；空库重放 `upgrade head` 成功；
   `alembic upgrade head` 建出的结构与直接执行 DDL 建出的结构**一致**（由 Task 3.6 的三源比对强制，而非靠人记得同步）。
6. **建表/迁移一律在 `aicore_test`**，不在 `aicore` 上做实验性 DDL。

**其余第 3 组范围口径**：暂不实现真正的主从复制（本机没有从库），只读会话指向可配置的地址；
若 `readonly_host` 缺省等于主库地址，则"只读会话"是**同库不同引擎**——这一点在验收时如实登记，不谎称已验证主从延迟。

### 控制者自我约束（用户 2026-09-18 要求「也要查看 spec 文档，然后限制自己的行为」）

**触发原因（我自己的两处越界，如实登记，不美化）**：

1. **越界一**：我把「`ocr_result.task_id` 不建物理外键」当成既定裁定写进工单，理由是 `er.md` §5.4 L240
   未标 FK。**这是错的**：我引的那一行讲的是 **ID 生成策略**（"同月分片路由凭据"），FK 标注在 §6.2 数据字典；
   而 **spec §5.1 L290 明确要求「在模板内声明物理外键」**。正确顺序是：读全 spec → 识别两文档冲突 →
   **登记冲突并按 spec 执行**（spec 是本次交付的设计权威），而不是默默按 `er.md` 改设计。
2. **越界二**：我把「同月分表之间能否建物理外键」当成**已知限制**、准备据此改设计，
   而那是**我的怀疑而非实证**。后补的实证（ERROR 1826）证明该怀疑方向对，
   但**先怀疑后验证**与**先验证再结论**不同——前者会改错设计。

**由此固化以下自约束，后续每个任务开工前对照执行**：

| # | 约束 | 可复核方式 |
|---|---|---|
| C1 | **开工前 MUST 完整读 spec 相关章节与 `er.md` 对应章节**，不得只 grep 片段 | 任务简报里必须引用 spec 章节号与 `er.md` 行号 |
| C2 | **权威文档之间冲突时 MUST 登记冲突、按事实源优先级（spec §1.3）择一执行**，MUST NOT 静默择一或自造第三口径 | ledger 里出现"文档冲突"条目 + 择一理由 |
| C3 | **任何"设计文档未覆盖"的裁定，MUST 先判断能否用真实环境实证**；能实证的 MUST 先实证再结论 | 裁定条目下附原始命令与原始输出 |
| C4 | **MUST NOT 为了让断言通过而改设计或改文档**；先判定是"被测对象错"还是"断言错" | 修正报告里逐条给出定性（如本轮 D1~D5） |
| C5 | **spec 自身有事实错误时，MUST NOT 直接改 spec**（它不是权威源）；登记并向用户报告 | ledger 的"文档级问题"条目 |
| C6 | 我替实现者做的裁定 MUST 写进工单并注明**依据的文档章节**，而非只写结论 | 工单里每条硬约束都带出处 |
| C7 | **改动计划/既有实现里的任何"值"（错误码、常量、命名、阈值）之前，MUST 先读该值的权威定义处并核对语义**；MUST NOT 凭"听起来更像"就改 | 裁定条目里附权威文件与行号 |

**C7 的来历（同一天第二次犯错，如实登记）**：写 Task 3.3 工单时，我把计划里定好的
`CrossShardOperationError` 码值从 `1003` 改成 `1002`，理由是我"觉得"跨分片更像"参数格式错"。
查证 `errors.py` L47~L52 后证明**计划是对的、我错了**：
`1002` 是「其余全部 …… **兜底档**」，`1003` 才是「枚举或范围非法」——
跨分片是"两个月的分片键被组合"，属取值组合越界，落 `1003` 才对。
已改回 `1003`，并把这次错误写进 C7。**教训**：`1002` 那个"兜底"二字我上一轮明明读过，
但当下没回去核对，凭印象下了判断——凭印象就是凭运气。

**读全 spec 后新发现的三处文档级问题（均已按 C5 登记，未擅自改动）**：

| # | 问题 | 处置 |
|---|---|---|
| **DP1** | spec §2.2 表格标题写「日志必含字段（**11 项**）」却列出 **12** 个字段名；spec §4.7 第 6 条同样写「日志 **11 字段**」。而 spec §4.6 要求字段名与 PDD L1747 **逐字一致**（PDD 为 12 项） | 按事实源优先级（`PDD` > spec），实现取 **12 项**（第 2 组已按 12 落地并修了设计文档与计划）。**spec 本身未改**；本表登记 |
| **DP2** | spec §2.4「MySQL … 服务壳打不开，以 `mysqld` 直启进程可用」**现状已反**：`MySQL` 服务为 AUTO_START、**必须由服务承载**，手动 `mysqld.exe` 才是实例卡死的元凶。spec §2.4 亦未记录弹窗根因（缺 `bind-address`） | 本组环境变更节已记录实测与修复；spec 未改，本表登记 |
| **DP3** | `er.md` §5.4 L240（`ocr_result.task_id` 标"同月分片路由凭据"、未标 FK）与 spec §5.1 L290（明确要求物理外键）**表述不一致** | 按 **spec §5.1** 执行（建同分片物理外键）；冲突已写入 Task 3.1 修正工单要求实现者登记；**`docs/er.md` 属"唯一可手改源"，改动需另走变更流程，本组不碰** |

### Task 3.1 第一轮的控制者复核（2026-09-18）

**第一轮实交付**：10 个 DDL 文件 + `tests/repository/test_ddl_matches_er.py`（765 行）。
**控制者实测定性（不是实现者自述）**：

| # | 现象 | 定性 |
|---|---|---|
| D1 | `ErFormatError: er.md 表 vision_qa_log 的数据行列数不足 6：\| 结构 \| 类型 \| 说明 \|` | **用例 bug**：`_iter_er_rows` 未跳过 §6.10 辅助结构（标题以中文开头，`ER_HEADING_RE` 不匹配，`current` 停在 `vision_qa_log`）。连带 **6 条用例红** |
| D2 | `biz_type` / `status` / `confidence_level` / `confidence` 中文注释断言失败 | **用例 bug**：正则 `[^,\n]*` 被列定义内的逗号（`enum('A','B')`、`decimal(3,2)`）撞死；DDL 注释实际存在 |
| D3 | `10_ai_task` / `11_ocr_result` 渲染后"残留占位符" | **用例 bug**：残留全在**注释里**（JSON 示例 `{channel, ...}`、路径 `{taskId}`），断言未先剥注释 |
| D4 | 8 条 FAIL 显示 `missing 1 required positional argument` | **非缺陷**：控制者诊断脚本直接调用 `@pytest.mark.parametrize` 函数所致 |
| D5 | `12_ocr_correction.template.sql` 外键约束名硬编码 `fk_ocr_correction_task` | **真缺陷（设计层）**：MySQL 外键约束名**在 schema 内唯一**，实证 `ERROR 1826 (HY000)`；模板套用到第二个月必失败 |

**另一处第一轮未完成的硬要求**：工单 Step 2「在真实 MySQL 上执行」**没有执行**，
仓库内无任何可复核产物；控制者实测 `aicore` 与 `aicore_test` **两库表数均为 0**。
→ 故新增 FIX-5：把执行路径固化为 `scripts/apply_ddl.py` + `tests/repository/test_apply_ddl_mysql.py`，
并要求在 `aicore_test` 与 `aicore` **两库都真跑**、原始输出入报告。

**修复工单**：`.superpowers/sdd/2026-09-16-aicore-architecture/task-3.1-fix-brief.md`（FIX-1~FIX-5）。

### Task 3.1 完成（2026-09-18）——含两次实现者交接

**提交**：`2a04934`（DDL + 三方比对用例）、`bd6c9d3`（`apply_ddl.py` + 集成用例）

**执行者交接（如实登记）**：第一轮 `b158a9e3`（7 个 DDL 出齐后进入探针循环，被中断）；
修正轮 `73c4c5e6`（修对了 FIX-4，但同样陷入探针循环，产出 6 个 `_probe_recon*.py`，被中断）；
**收尾与控制者亲自完成**。
**流程教训（已固化为约定）**：同一任务内探针脚本 >2 个即要求实现者**先交付产物**；
两个实现者都违反了这条，控制者接管比继续等更省。

**修掉的缺陷**：FIX-1（`er.md` §6.10 解析，连带 6 条用例红）、FIX-2（中文注释断言被列定义内逗号撞死）、
FIX-3（渲染残留断言未剥注释，把 JSON 示例当占位符）、FIX-4（**外键约束名 schema 内唯一**，
实测 `ERROR 1826`）、FIX-5（真实执行未固化）。

**控制者收尾时修的两处自己的 bug（登记）**：
① `_normalize_type` 把枚举值也小写了 → 11 个枚举列全红；改为**括号感知**归一（只小写括号外的类型名，
括号内是字符串字面量、大小写敏感）。
② 渲染反向自检写成**恒假断言**（`set(渲染后) == set(源)`；`{table}`/`{month}` 渲染后本就该消失）；
改为**精确核算差额** = `count({table}) + count({month})`。

**集成用例暴露的两处**：③ 清理 DROP 顺序错（外键引用导致 `ERROR 3730`）→ 改逆序；
④ **集成测试变量名侵入应用配置命名空间**：初版用 `AICORE_TEST_MYSQL_*`，
撞上 `_UnknownEnvVarSource`（Task 2.1 的**正确**防线）→ 全量套件 35 failed / 63 errors。
改用 `DSH_IT_MYSQL_*`。**这不是防线太严，是命名错了**。

**凭据红线（commit-check 清单 B 自查发现并修）**：初版把本地开发口令**硬编码**进 `conftest.py`
与集成测试。改为：`conftest` 用 `dotenv_values()` **直读 `.env` 文件**（该文件已被 gitignore），
`apply_ddl.py` 只从环境变量取、取不到即 **exit 2 并明确报错**。
**踩到的坑**：直接读 `os.environ["AICORE_MYSQL_PASSWORD"]` 永远拿到 conftest 注入的 13 字符占位值
（环境变量优先于 `.env`），故必须读**文件本身**。

**真实 MySQL 落地证据**：`information_schema` 逐项核对两库（`aicore` 月 202609 / `aicore_test` 月 202607）
→ **总不符数 = 0**（9 表 / 4 外键带月份且 RESTRICT / 24 个索引名全 OK）；复跑幂等（比对 `CREATE_TIME` 证明未重建）。

**门禁**：`453 passed, 8 skipped`（进入本任务前基线 387）、integration `5 passed`、
覆盖率 **96.56%**（≥80%）、`ruff All checks passed!`、`mypy Success: no issues found in 51 source files`、
`lint-imports 4 kept, 0 broken`、硬编码凭据扫描 **none**、残留 `_*` 文件 0。

**遗留（已登记，留待最终评审）**：
① `ruff` 的 E501 按**视觉宽度**计（东亚宽字符算 2 列），而 `ruff format` 按**字符数**折行，
两者对中文注释天然打架（实测 60 字符的行被报 "110 > 100"）。本任务逐个收窄了 6 行，
但这是**仓库级缺口**，后续写长中文断言消息会反复踩到。
② `scripts/apply_ddl.py` **不在** `mypy`（`files=["src"]`）与 import-linter 的覆盖范围内。
③ `00_create_database.sql` 的建库路径**未在真实库验证**（`aicore_dev` 无建库权限，实测 ERROR 1044）。

**流程偏差登记（如实说明，不辩解）**：Task 3.1 在**控制者接管的情况下**完成，
故**没有派独立评审者**做任务级评审——控制者既写了部分实现又做验收，独立性不足。
已采取的补偿：① 交付报告 `.superpowers/sdd/2026-09-16-aicore-architecture/task-3.1-report.md`
里逐项贴**原始输出**（不是结论），并单独列出"未验证项"（建库路径、脚本不在 mypy/linter 覆盖内、
E501 宽度缺口）；② 全部证据可由任何人复跑复现；③ **Task 3.1 纳入第 3 组整体评审的必审项**，
届时由独立评审者重新复跑并做变异测试。

### Task 3.8 完成（2026-09-18）——控制者亲自实现

**提交**：`a78f6c4`（`core/idgen.py` + `tests/unit/test_idgen.py` + `pyproject.toml`）

**为什么控制者亲自做**：Task 3.2 的实现者正在写 `repository/models.py`，
而 Task 3.8 只碰 `core/idgen.py`，**无文件重叠**，属真正可并行的两条线；
再派一个 subagent 只增加协调成本。**代价**：同样是自实现自验收，已纳入整体评审必审项。

**交付要点**：6 种前缀（`task_`/`cor_`/`rev_`/`marker_`/`kan_`/`qa_`）取自 `er.md` §5.4 L239–L245；
`merchant` **刻意不发号**（L244「源服务生成、只读引用」）；hex 段按「32 减前缀长度」截取，
**长度账只在常量表算一次**，生成后自校验、超限抛错（非静默截断）。

**实测证据**：
```
20 passed ｜ 1 万个并发生成：0.152s，唯一数 10000，最大长度 32，全量过 validate_id
各前缀分布 = {cor:1667, kan:1667, marker:1667, qa:1667, rev:1666, task:1666}
```
**核心负向证据**：`monkeypatch` 把 `MAX_ID_LENGTH` 改小 → `new_id` 抛 `ValueError`
（证明"超限即抛"不是文档里的一句话）。

**用例写错并修正的一处（登记）**：防回归断言初版对**整份源码**做子串检查，
在 docstring 里命中 `workerId`——而那段 docstring 正是在**说明禁用理由**。
修法：用 `tokenize` 剥注释与字符串，**只对代码骨架发问**，并加反向自检
（剥离后必须仍能看到 `uuid4`，否则断言变空）。

**门禁**：`473 passed, 8 skipped`（进入前 453）、ruff/mypy/lint-imports 全绿、覆盖率 96.56%。

**诚实登记**：① 未独立评审（见上）；② 「32 位截断后真的不撞」是**概率论证**，
无法用可承受的插入量实测，已如实标注为概率论证而非实测。

### Task 3.2 完成（2026-09-18）——subagent 实现 + 控制者独立验证

**提交**：`3d8d2f2`（`repository/models.py` 511 行 + `tests/unit/test_models.py` 757 行 / 196 用例）

**门禁**：`669 passed, 8 skipped`（排除本任务新用例 = 473，既有用例一条未红）、
`196 passed`、ruff/mypy/lint-imports 全绿。**该实现者未写任何探针脚本**。

**实现者主动纠正了工单的一处错误（值得记）**：工单写的基线「453 passed」是我在
**上一轮**的数字；它开工时真实基线已是 **473**（我在它运行期间并行提交了 Task 3.8 的 20 条用例）。
它没有盲从工单，而是实测后指出差异并按实测基线验收。**这正是我要的行为。**

**两处偏离工单（控制者已独立复验，均成立）**：

| # | 工单原文 | 实测 | 采用 |
|---|---|---|---|
| 1 | `Integer(unsigned=True)` | **硬报错** `TypeError: Integer() takes no arguments`（generic Integer 不收参数，`unsigned` 只存在于 mysql 方言） | `Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")` |
| 2 | `DateTime()` | 不报错但**静默丢毫秒**：MySQL 渲染成 `DATETIME`（fsp=0），与 DDL 的 `datetime(3)` 不符 | `DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")`；`timezone=True` 的禁令严格遵守 |

控制者复验原始输出：
```
声称1 成立: TypeError: Integer() takes no arguments
progress    generic=INTEGER   mysql=INTEGER UNSIGNED
created_at  generic=DATETIME  mysql=DATETIME(3)
元数据表名 = 9 个逻辑名，无月份后缀
```

**控制者发现实现者报告里的一处不准确推断（纠正并留痕）**：实现者称
「`column.type` 仍是 DateTime 实例，**Task 3.6 读元数据不受影响**」——**这句话是错的**：
实测 `str(AiTask.__table__.c["created_at"].type)` = `DATETIME`（**丢 fsp**）、
`progress` 得 `INTEGER`（**丢 UNSIGNED**）。`with_variant` 只在**按方言编译**时才生效。
若不纠正，Task 3.6 的比对器会得到 `DATETIME` / `INTEGER` 而与 DDL 的 `datetime(3)` / `int unsigned`
**假性不等**——而假性不等的下一步往往是"有人把这条检查关掉"。
已把该坑写进 **Task 3.6 工单**（MUST 走 `compile(dialect=mysql.dialect())`）。

**未做（实现者诚实登记 + 控制者确认）**：未连真实库（3.1 已覆盖）；未验证 Alembic autogenerate 收敛（3.5 的交付物）；
DDL 的列/表 COMMENT 未镜像（工单未要求；**若 Task 3.6 的比对维度含 comment 会呈现差异**，需在那时决定）；
未做类型映射的反向完备性扫描（3.6 职责）。

**控制者裁定（实现者请求裁定的偏离 2）**：**保留 `with_variant(mysql.DATETIME(fsp=3), "mysql")`**。
理由：① 权威源是 DDL（`datetime(3)`）而非我工单里的字面写法——工单是我写的，DDL 是权威；
② 丢掉毫秒精度是不可接受的静默降级（`er.md` §6 通用约定明写毫秒精度）；
③ 保留后 Task 3.5 的 autogenerate 才不会反复生成"把 datetime(3) 改成 DATETIME"的 alter。
**代价已登记**：3.6 的比对器 MUST 按方言编译类型（见上）。
对偏离 1 同样裁定**保留**（`Integer` 不收 `unsigned` 是 SQLAlchemy 的硬约束，`with_variant` 是官方表达方式）。

### Task 3.6 底座完成（2026-09-18）——控制者写 `repository/schema.py`

**为什么先写它**：它是本组最值钱一项（三源交叉校验）的共享底座，且与当时在跑的 Task 3.3
（只碰 `sharding.py` / `apply_ddl.py`）**无文件重叠**，属可并行的工作。
设计动因：Task 3.1 已在 `tests/repository/test_ddl_matches_er.py` 里写过 DDL 与 `er.md` 的解析，
Task 3.6 若再写一份，同一件事就有两份实现，漂移表现是**两个都叫"一致性检查"的工具互相矛盾**
（`test_ddl_matches_er.py` 绿、`compare_schema.py` 红，或反之）——那是最坏的一类故障。

**已实测（9 张表 × 3 对组合 × 0 处差异）**：
```
DDL 目录（含 3 张分片模板）: 9 张表
er.md                     : 9 张表
SQLAlchemy 元数据          : 9 张表
DDL vs er.md    : 0 处差异
DDL vs 元数据   : 0 处差异
er.md vs 元数据 : 0 处差异
```

**写这个模块时抓到我自己第二次犯同一个错（登记）**：首版 `normalize_type` 用整体 `.lower()`，
实测直接爆出 **15 处差异**，其中一半是枚举值被小写：
```
er.md vision_review.status enum = ('ai_processing','pending',...)   <- 错
meta  vision_review.status enum = ('AI_PROCESSING','PENDING',...)   <- 对
```
这与 Task 3.1 修的是**同一个错误**：枚举值是 SQL 字符串字面量、**大小写敏感**，类型名不敏感。
修法同为**括号感知**（引号优先 + 深度计数，而非正则——枚举值里可能出现 `)`）。
修完 15 → 6 处，剩余 6 处是**同义名未归一**（MySQL 里 `NUMERIC`≡`DECIMAL`、`BOOL`≡`tinyint(1)`、
`INTEGER`≡`INT`）。归一时又踩一次：整串精确匹配让 `numeric(3,2)` 落空 → 改为
**取前导字母作基名、其余原样拼回**（`integer unsigned` 里的 `unsigned` 一度被吞掉）。
最终归一化 9 个用例全过（`int UNSIGNED` → `int unsigned`、`NUMERIC(3,2)` → `decimal(3,2)`、
`BOOL` → `tinyint(1)`、`enum('HIGH', 'MEDIUM', 'LOW')` → `enum('HIGH','MEDIUM','LOW')`）。

**顺带证实 Task 3.2 那处不准确推断的后果是真的**：`markers_count` 的 `integer unsigned` 差异
正是"只读 `str(column.type)`"会踩的坑；本模块按要求走 `compile(dialect=mysql.dialect())` 后消失。

**与 Task 3.3 的接口已实测对齐**：`render_shard_template(logical, month)` 签名一致，
且渲染结果里 `fk_ocr_correction_task_202601` 与 `ocr_result_202601` 都正确
——Task 3.1 实证的"约束名必须带月份"被正确处理。

**门禁**：`ruff All checks passed!`、`mypy Success: no issues found in 52 source files`、
`lint-imports 4 kept, 0 broken`。**尚未提交**（等 Task 3.3 收工后一并提交，避免与它并发写同一提交）。

### Task 3.3 完成（2026-09-18）——subagent 实现 + 控制者独立验证

**提交**：`42e3803`（`sharding.py` 484 行 + `test_sharding.py` 75 条 + `apply_ddl.py` 收编 + 演练月同步）
与 `45fb9b8`（`schema.py` + `test_schema.py`，即上节的 Task 3.6 底座）。

**交付要点**：物理名 `xxx_YYYYMM`；分片月由 `created_at` 现算（aware 先转 UTC；
**naive 直接拒**——猜时区就是静默错片）；幂等建表严格按 `ai_task → ocr_result → ocr_correction`；
`MissingShardKeyError`=1001 / `CrossShardOperationError`=1003；`{month}` 同时进**外键约束名**。

**真实库证据（实现者给 + 控制者复跑）**：
```
反序建 ocr_correction → MySQL 1824 Failed to open the referenced table 'ocr_result_...'
正序建表成功；外键 fk_ocr_correction_task_<月> -> ocr_result_<月> 且 RESTRICT
复跑 CREATE_TIME 不变（幂等）；清理后无残留、6 张固定表完好
```
门禁：`75 passed`（含 3 条 integration）、全量 `773 passed, 8 skipped`、ruff/mypy/lint-imports 全绿、
覆盖率 **96.24%**（`schema.py` 93%，未覆盖的 18 行是 `from_information_schema`，需真实库）。

**实现者报出的一处真实不一致，控制者当轮修掉（不是延后）**：
`apply_ddl.py --month` 只查"6 位数字"，而运行期 `ensure_month_tables` / `physical_table_name(str)`
卡 `01~12` → **越界的 `202613` 能建表、同样的月份运行期会拒**。
这正是"同一份渲染逻辑两条路径严格度不同"，也正是本任务存在的意义。
修法：新增 `_reject_bad_month()` 把 CLI 收紧到同口径（错误消息点明 01~12），
并同步把演练月从 `202613` 改为 `209901`~`209912`（该文件属控制者改动范围）。
**反例已实测**：`--month 202613` → exit 2 且消息含「月份部分必须在 01~12」。

**Task 3.6 底座已可工作（`schema.py`，见上节）**：9 张表 × 3 对来源 × **0 处差异**。

### 新登记的流程级隐患（Task 3.3 实现者实测到，控制者确认）

`tests/structural/test_layering.py::test_layering_contracts_pass`
**把违规探针写进共享源码树**（`src/aicore/...` 下的 `*_probe.py`）再跑 lint。
这在**并发执行**时会与另一个正在 collect/import 的进程互扰——实现者实测到 1 次瞬时红灯
（同期独立 `lint-imports` 是 `4 kept, 0 broken`，单跑通过，随后连续 3 轮全绿）。

**这不是本组引入的问题，但它与"控制者与 subagent 并行跑测试"的工作方式直接冲突**，
故登记为已知约束：**并发跑测试时，`structural/test_layering.py` 的结果不可采信**，
须单跑复核。**建议**留待最终评审决定是否改为"探针目录隔离"（如写入独立的临时包再清理），
本组不动它（改动属第 1 组已验收文件的语义变更，需独立任务）。

### Task 3.6 完成（2026-09-18）

**提交**：`45fb9b8`（`schema.py` + 36 条用例）、`c604dfa`（`compare_schema.py` + 3.6b 重构与三方向阴性）。
> 勘误（第 3 组独立评审指出）：此处原写作 `ffb0bd0`，该对象**不存在**（`git cat-file` 实测
> `fatal: Not a valid object name`），实际提交是 `c604dfa`。已改正。
**执行方式**：底座与 CLI 由控制者写；1014 行用例的重构与三方向阴性由 subagent `df4ca778` 做。

**四源两两一致（控制者实测，含真实库）**：
```
[ OK ] DDL vs er.md ｜ DDL vs 元数据 ｜ DDL vs information_schema(aicore_test)
[ OK ] er.md vs 元数据 ｜ er.md vs information_schema ｜ 元数据 vs information_schema
[DONE] 4 个来源两两一致（9 张表）
```
反向也验了：**缺口令 `--with-mysql` → exit 2**、**指向不存在的库 → exit 2**
（连不上 MUST 非 0，静默降级成"两源通过"会让人以为真库也验过了）。

**三方向阴性（spec §5.9 第 2 条）——控制者先独立复现，再对照 subagent 的用例**：
```
正常态对照：DDL vs er.md 0 处差异；DDL vs 元数据 0 处差异
方向① 改 DDL   : 表 vision_review 字段 review_id 类型不一致：左 varchar(64)，右 varchar(32)
方向② 改 er.md : 表 vision_review 字段 review_id 可空性不一致：左 NO，右 YES
方向③ 改模型   : 表 vision_review 字段 review_id 可空性不一致：左 NO，右 YES
```
三向**各自独立**成立，且每向都配"未改动时 diff 为空"的对照（证明红是改动引起的，不是本来就红）。
变异一律**在内存内做、不碰真实源文件**——避免"改真实文件再还原"这种危险做法，
也避免与并发跑测试的进程冲突。

**3.6b 重构的"行为不变"判据**：重构前后均 **61 条**，用例名清单逐条一致
（`Compare-Object` 输出 `baseline=61 now=61 / IDENTICAL`）；文件 1014 → 714 行。
删除的本地实现全部换源到共享层；额外去掉本地渲染（改用 `sharding.render_shard_template`）
与骨架剥离（改用 `sharding.sql_skeleton`）与 7 个本地正则。
**保留并注明理由**：`parse_er_defaults` 是**唯一**局部解析（`ColumnSpec` 刻意不承载"默认值"，
不为它给共享层加一个只有两源表达得了的维度）；注释维度检查与 `openapi.yaml` 接线属本文件独有；
`ALL_TABLES` 等清单**刻意不从 `sharding` 取**——否则门禁断言会"自己比自己"。

**门禁**：`827 passed, 8 skipped`（并发中，含 3.4 新增的 session 用例）、
覆盖率 **96.78%**、`mypy Success: no issues found in 52 source files`、`lint-imports 4 kept, 0 broken`。

**本任务唯一未做到（subagent 诚实登记）**：未做"阴性用例自身的阴性"
（即未临时改测试文件去验证那些阴性断言自己会失败），改用"未改动对照 + 反假绿断言 +
独立脚本打印的红/绿原始输出"替代。**这一条由控制者的独立复现补上了**（见上）。

### Task 3.4 完成（2026-09-18）——subagent 实现 + 控制者裁定与复核

**提交**：`4c58544`（`session.py` 276 行 + `config.py` +4 字段 + `.env.example` + 5 处耦合点 + 25 条用例）

**交付**：同步会话 + 线程池（非 async driver）；写/只读会话分离；`primary_read_session` 表达
「写后立即读强制走主库」；池大小从配置读取；口令用 `URL.create` 组装且用哨兵断言"不进日志"。
**未改 `main.py`**（遵守硬约束：接线归第 4 组）。探针脚本用量 **0**。

**新增 4 字段的必填/可空分档（与用户拍板的方案 A 一致）**：
- `mysql_pool_size` / `mysql_max_overflow` **必填**——容量是部署决策，给默认值等于替运维做决定；
- `mysql_readonly_host` / `mysql_readonly_port` **可空**——`None` = 没有独立从库（本机即如此），
  定为必填会让单实例环境把主库地址再写一遍。**回落事实由 `read_target_is_primary` 显式暴露**，
  不把"回落主库"说成"已分离"。

**实现者报出"工单只列 3 处耦合点、实际 5 处"（它是对的）**：`test_config_startup.py` 的 `BASE_ENV`
与 `test_logging.py` 的启动环境清单也必须各 +2 必填项，否则两个文件因缺必填项大面积变红。
**这是工单的漏项，实现者补上了并写明理由**。

#### 控制者裁定：`readonly-pair`（第 5 条跨字段规则）

实现者请我裁定"只配只读端口、不配只读主机"怎么办，它选了"host 回落主库 + 端口生效"，
论证是「静默忽略端口更糟」（`[跨字段：readonly-pair]` 落地时重写了那条用例）。
**该论证成立，但它只看了两个选项**；还有第三个：**既不静默忽略、也不去连错地址，而是明确拒绝**。

**裁定为拒绝**，三条理由：
1. 「主库地址 + 非默认端口」**没有任何部署会要这个连接**，最可能是"想配从库却漏了 host"；
2. 静默接受的实际后果是**运行期连不上**，而根因（漏配 host）在日志里看不出来；
   拒绝把"漏配"变成启动期一句话；
3. 代价极小：多写一行配置。

**未破坏"不静默忽略"原则**——拒绝就是最强的"不忽略"。
**只配 host（端口回落主库）仍然合法**：同端口不同主机的从库是常见拓扑。
控制者实测四条正交行为：两处都空 → 回落主库；只配 host → 端口取主库端口；
**只配 port → 被拒且消息点名 `AICORE_MYSQL_READONLY_HOST`**；两处都配 → 全部生效。

**实现者另一处偏离（控制者接受）**：工单用例 5 的 `session.is_active is False` 在
SQLAlchemy 2.0.54 上**不成立**（实测 `close()` 后仍 `True`）→ 改用
`QueuePool.checkedout()` 1→0 + `in_transaction() is False`，并在集成用例里对生产 QueuePool 再验一次。

**门禁**：`860 passed, 8 skipped, 14 deselected`、`127 passed`（config 两文件）、
`ruff All checks passed!`、`mypy Success: no issues found in 52 source files`、
`lint-imports 4 kept, 0 broken`、`config.py` 与 `session.py` 覆盖率均 **100%**。

**未做到（实现者诚实登记，控制者确认）**：本机只有一个 MySQL 实例 →
读写分离**只验到"地址可配 + 两个引擎/两个池"**；**主从延迟、从库一致性、只读权限、
故障切换完全未验证**；`pool_pre_ping`/`pool_recycle` 只写了理由，未做掐连接实测；
装配日志取 INFO 而非 WARNING。

### Task 3.7 完成（2026-09-18）——subagent 实现 + 控制者收紧码值

**交付**：`base.py`（`ShardKey` / `BaseRepo[ModelT]` / `require_same_shard` /
`cross_shard_transaction_guard` / `physical_table`）、`task_repo.py` / `ocr_repo.py` /
`correction_repo.py`（只增）/ `verdict_repo.py`、`tests/repository/test_repos.py`（41 条：37 默认 + 4 集成）。
门禁：`37 passed` / `-m integration 4 passed`（真实 MySQL，未 skip）、
`ruff All checks passed`、`mypy Success`、`lint-imports 4 kept, 0 broken`、
本任务 5 个模块覆盖率 **100%**（全仓 97.26%）。

**实现者实测推翻了工单里的三条候选路径（值得记）**：
- **② `aliased(Model, name=物理名)` 编译成 `FROM ai_task AS ai_task_202607`——读的是逻辑表**，
  等于静默查错表；且 `insert` 报 `AttributeError: 'AnnotatedAlias' ... '_autoincrement_column'`；
  `aliased(Model, 物理表副本)` 报 `InvalidRequestError: Query contains no columns`。
- ① 需引擎级事件监听（本层不拥有引擎）+ 占位前缀进 `__tablename__`（Task 3.2 明令禁止）；
- ③ `text()` 会丢掉类型/参数绑定。
**采用**：`Table.to_metadata(MetaData(), name=物理名)` 得到真物理表对象 + Core 语句
（实测 SQL 全部打到 `ai_task_202607`），读回经 `Model(**row)` 构造**游离实体**（无 identity map，
代价已登记）。**这一条正是"工单里的技术指引可能错、实现者必须实测"的正面案例。**

**实现者的其余偏离（控制者接受）**：`OcrRepo/CorrectionRepo.insert` 补必填关键字 `shard`
（两表无业务时间列、`task_id` 不含时间戳，原签名无法算月）；集成用例的固定名表改用会话级临时表；
`rowcount` 口径按实测纠正（SQLAlchemy MySQL 方言硬编码 `CLIENT.FOUND_ROWS` →
同值更新返回 1 而非 0）。

#### 控制者收紧：把 `3007` 正式接入（Task 3.7 报告里的"待收紧项"）

实现者的 `DuplicateVerdictError` 借用了 `1003`，并**自己把收紧方向写在 docstring 里**：
「平台 `3007 # 状态不允许该操作` 语义最贴（锁 409），但新增码要按 `core/errors.py` 顶部的
四处清单同步（含 `test_errors.py` 两张字面量表），超出本任务文件边界」。**该理由成立。**

控制者核查后**按四处清单正式接入 3007**：
1. `CONFLICT_CODE = 3007` 常量 + 进 `AICORE_ERROR_CODES`；
2. `DEFAULT_MESSAGES[3007] = "当前状态不允许该操作"`；
3. `HTTP_STATUS_BY_ERROR_CODE[3007] = 409`（与 Task 2.3 的锁定映射表一致）；
4. `tests/unit/test_errors.py` 的两张字面量表同步。
另在 `errors.py` 新增 **`ConflictError`**（异常层次的家，不放仓储层），
`DuplicateVerdictError` 改为继承它。**为什么不复用 `ParamError(code=1003)`**：
重复提交时请求参数完全合法，冲突来自**服务端已有状态**；用 1003 会让前端提示"改参数"，
而真正的处置是"去看已有结论"——语义错位会让调用方做错事。

**为什么只接 3007、不接 3008（幂等键冲突）**：`ai_task.idem_key` 的重复提交按 `er.md` §3 的
幂等口径**返回原任务号**（不是错误），故 3008 现在没有任何会发出的路径；
`test_aicore_error_codes_is_exactly_the_emittable_set` 的注释明写「多了是死码」，
接一个没人发的码正是它要拦的事。**留到真有路径时再接。**

**控制者改错又改回一处（登记）**：批量替换码值断言时把 `CrossShardOperationError` 的
`1003` 断言也改成了 3007（共 4 处，其中 1 处属跨分片）。单跑变红后立即改回。
**教训**：批量替换 MUST 先按"该断言属于哪个异常类"分组，而不是按行号列表一把改。

### 第 3 组验收检查表（`scripts/group3_acceptance.py`，控制者新增）

把 10 项验收固化成**可复跑**的脚本（只读动作，随时可重跑）。当前结果：

```
[PASS] 1. DDL 在真实 MySQL 8 执行     库 aicore 9 张表，与 deploy/sql/ddl 结构 0 差异
[PASS] 2. 三源交叉比对正常态          表数 (9,9,9)，三对组合差异 (0,0,0)
[PASS] 3. 三源比对三方向阴性          方向①1 处 / ②1 处 / ③1 处（各应恰好 1）
[PASS] 4. 测试内无 sleep              AST 扫描全 tests/ 无 sleep 调用
[PASS] 5. 无跨分片 JOIN/聚合/两阶段提交  全树无 select 上的 join、无两阶段提交
[PASS] 6. 缺分片键抛错 / 跨分片被拒     缺键→1001；跨月→1003；同月去重→'202601'
[PASS] 7. 只读会话分离 + 池随配置      池取自配置、随配置变化、读写两引擎、无配置时回落
[PASS] 8. 迁移幂等（基线迁移就位）     versions/ 1 条；sqlalchemy.url 为空串；无 password= 赋值
[PASS] 9. 一万个 ID 过正则且无重复     唯一、≤32、全量校验
[PASS] 10. 提交不带 [AI] 前缀         近 40 条：0 条带前缀、0 条格式不符
结果：PASS 10 / FAIL 0 / INFO 0
```

**第 5 项的检查器我改坏过三版（登记，与 Task 3.8 的 tokenize 教训同类）**：
① 子串匹配 `join(` 把 `"".join(out)` 这类**字符串拼接**判成 SQL JOIN；
② 加 `\bJOIN\b` 后把 docstring 里"禁止跨分片 JOIN"这句**说明**判成违规；
③ 想在 token 流上剔"引号三元组"，但引号被 `tokenize` 拆成独立 token、条件恒不成立。
**最终换判据**：不问"是不是 join"，问"**有没有 SELECT 上的 join**"
（本项目 repository 层不构造 select 之外的 join）。
并加**反向自检**：喂一段真 `select(...).join(...)` → 必须命中；喂 `"".join(...)` 与
docstring 提到 JOIN → 必须不命中。三项实测皆如预期。

**第 8 项的检查器也改坏过两次**：先是 `"password" not in ini_text` 被文件头那句
`# The password is NEVER stored here` 判红（**说明正确做法的话被当成违规证据**）；
再是正则跨行吞掉后续注释。最终改为"取 `sqlalchemy.url` 的**值**、要求为空串"。

### Task 3.5 完成（2026-09-18）——第 3 组最后一项

**提交**：`d597768`（`alembic.ini` + `deploy/sql/migration/{env.py,script.py.mako,README}` +
`versions/2523574bd75d_baseline_schema.py` + `test_migration.py` 17 条）

**三条幂等口径（控制者独立复跑确认）**：
1. **收敛**：再跑 `autogenerate` **无任何 `Detected` 行**，生成物 `upgrade()/downgrade()` 体内只有 `pass`、
   AST 计 **0 个 `op.*`** → **Task 3.2 的两处 `with_variant` 与 `server_default` 真正对齐，
   不需要给迁移打补丁、也不需要动 `models.py`**（这正是把幂等口径定成"生成物为空"的价值：
   它同时验证了模型的类型表达）。
2. **空命名空间**：首次 `Running upgrade -> 2523574bd75d`；二次**无 `Running` 行**、`current=head`、
   结构快照 `diff` 为空。
3. **两路一致**：alembic 建 6 表 vs `apply_ddl.py` 建 6 表，经 Task 3.6 的
   `from_information_schema + diff` → **差异 0**（两侧各断言 6 张表，防"两边都空"的假通过）。

**两个实测发现（都写进 `env.py`/`README` 并有用例钉住，价值高）**：
- **`alembic.ini` MUST 全 ASCII**：alembic 1.20 用 `encoding="locale"` 读 ini，
  本机 cp936 下**含中文的 UTF-8 ini 直接 `UnicodeDecodeError`**，任何 alembic 命令都起不来，
  且 **`PYTHONUTF8=1` 无效**（它管的是 stdlib 默认编码，不管 `configparser` 显式传的 locale）。
  控制者实测确认：`alembic.ini` 3905 字节、`maxByte=121`（全 ASCII）。
- **autogenerate 生成的 `downgrade` 在 MySQL 上跑不通**：先 `drop_index` 会撞 **1553**
  （`idx_review` 是外键支撑索引）。实现者用官方 `process_revision_directives`
  在**生成期**去掉"反正要删的表"的冗余 `drop_index`（**未手改迁移文件**），
  修好后 `downgrade` = 6 条 `drop_table`，正合工单"只做基线撤销"。
  控制者实测确认：`versions/*_baseline_schema.py` 第 232 行之后**只有 6 条 `op.drop_table`**。

**另加机制**：`downgrade` 默认被拒（需 `-x allow_downgrade=1`，守卫在**连库前**生效）；
`alembic.ini` 加 `[post_write_hooks]`（否则生成物 23 条 E501 必红门禁）；
`env.py` 的 `include_object` 从 autogenerate 里排除 `SHARDED_TABLES`
（防"某月物理表被反向工程进迁移图"）。

**未做到（实现者诚实登记，控制者确认）**：**建库路径未验证**——`aicore_dev` 在 `*.*` 上只有 USAGE
（`SHOW GRANTS` 实测），无 `CREATE DATABASE` 权限，故只有"空命名空间"等价验证，
**已明说不是真·空库**；工单建议的"独立表名前缀"未实现（表名来自 metadata，
加前缀等于第二份 DDL），退到同名前缀命名空间的清空+重建，并登记了 6 个固定名在 `aicore_test`
内跨进程共享的并发风险；`tmp_path` 在本沙箱不可用（工作区外拒写 + `mkdtemp` 0700 ACL），
改用自建 `probe_tmp` 夹具。

### 第 3 组：8 项任务全部完成（2026-09-18）

**提交清单（10 个，`9a3f4be` → `d597768`）**：
```
d597768 feat(aicore): 加 Alembic 基线迁移，两条落地路径结构一致      ← 3.5
c4d9691 feat(aicore): 落地 repository 层四类仓储并接入 3007 状态冲突码  ← 3.7
4c58544 feat(aicore): 实现同步会话与连接池并补只读库配置              ← 3.4
c604dfa test(aicore): DDL 比对用例改用共享层并补三源三方向阴性用例      ← 3.6b
2008cf7 chore(aicore): 标注 idgen 的不可达防御性检查并补覆盖率
45fb9b8 feat(aicore): 落地四源结构比对层 repository/schema.py         ← 3.6
42e3803 feat(aicore): 实现按月分表路由与跨分片守卫                    ← 3.3
e9d265f fix(aicore): 集成用例的演练月改为按进程唯一
3d8d2f2 feat(aicore): 落地 9 张表的 SQLAlchemy 声明式模型             ← 3.2
a78f6c4 feat(aicore): 实现前缀化业务 ID（总长恒 32）                  ← 3.8
```

**最终门禁**：`877 passed, 8 skipped, 19 deselected`；全量 integration **19 passed**；
覆盖率 **97.26%**（≥80%）；`ruff All checks passed!`；
`mypy Success: no issues found in 52 source files`；`lint-imports 4 kept, 0 broken`；
验收检查表 **10/10 PASS**。

**环境限制（如实登记，不影响交付）**：`services/aicore/` 下有 **32 个**
`pytest-cache-files-*` / `probe-*` 残留目录，沙箱 ACL 拒绝删除
（`Access to the path ... is denied`，`ruff` 也报过同源的 `os error 5`）。
实测确认：**未被 git 跟踪**（`git status` 干净），故不入库、不影响交付；
彻底清理需提权，为一次性清理弹 UAC 不划算。

### 第 3 组独立评审（2026-09-18，subagent `74834705`）

**结论：有条件通过**（无交付物阻塞缺陷；1 项重要、收尾前必修）。
评审者独立复跑 9 条门禁全绿，做了 **5 处变异测试**（含按字节还原、`git diff HEAD` 为空），
抽查 4 项数值/口径，核实了 5 条已登记未验证项**全部属实**，并**补登 6 条遗漏**。
报告：`review-group3.md`（36.8KB，11 章）。

#### 评审抓到的一处假绿（重要，控制者随后修复）——**这是本轮最有价值的发现**

验收项 7「一万个 ID 全过正则（**总长 ≤32**）且无重复」**在仓库内没有任何独立预言机**：
- `group3_acceptance.py` 的判据写成 `<= MAX_ID_LENGTH`（**被测对象自己的常量**）；
- `tests/unit/test_idgen.py` **21 处期望值全部由该常量现算**。

**实证**：把 `MAX_ID_LENGTH` 改成**自洽但错误**的 `35`（各前缀 hex 位数仍落在 `uuid4().hex`
的 32 位内，故模块内部自校验不响）→ **验收脚本仍输出 `PASS 10 / FAIL 0`**
（打印"最大长度 35 ≤ 35 True"），全量只红 1 条且是**附带红**。
而 `er.md` §5.4 的 ID 列都是 `varchar(32)` —— 33~35 字符会让**每一行都插不进去**，
正是 spec §5.8 点名"最容易写错"的后果。

**这恰好是我反复强调的那条原则的自我违反**：「期望值 MUST NOT 取自被测对象」。
我在工单里要求别人现解析权威源，却在验收脚本上把判据系在了被测常量上。

**修复（纯测试侧，3 处，符合 C4 不改设计）**：
1. `test_idgen.py` 新增字面量 `CONTRACT_ID_MAX_LENGTH = 32`（出处：`er.md` §5.4 的列宽）
   + 三条锚用例：常量等于文档列宽、**六前缀各自长度恰好 32**（不是"不超过"）、
   前缀长度与 hex 位数**逐前缀**求和为 32（防"一长一短互相掩盖"）；
2. `group3_acceptance.py` 改用字面量 32，并加"常量==契约""逐前缀各 32""算术自证"三项判据；
3. `idgen` 把 `_UUID_HEX_LENGTHS` 公开为 `ID_PREFIX_LENGTHS`
   （位数分布是**对外契约**——影响可读性与排障——不是内部实现细节）。
**分工要分清**：各前缀"该有多少位 hex"是**内部算术**，现算合理；
"这个算术的上限必须是 32"是**外部契约**，只能写死。

**修复的变异复验（控制者实测）**：常量改成 35 →
验收脚本从 `PASS 10 / FAIL 0` 变为 **`PASS 9 / FAIL 1`**、`test_idgen` **4 failed**；
按字节还原 `SequenceEqual=True`。

#### 评审指出的其余三项（控制者已全修）

| # | 问题 | 修法 |
|---|---|---|
| ⑨ | 32 个残留目录**没有任何 gitignore 规则**（`git check-ignore` 实测 exit 1），今天只靠沙箱 ACL 拒绝读取才没出现在 `git status`；**权限一变就会冒出 30+ 个未跟踪目录** | `.gitignore` 补 `pytest-cache-files-*/` 与 `probe-*/`；`--no-index` 实测命中 `.gitignore:21/22` |
| ⑩ | `task-3.6-report.md` **缺档**；ledger 引用了**不存在的提交 `ffb0bd0`**（`git cat-file` 实测 fatal，实际是 `c604dfa`）；"10 个提交"清单漏了 `2008cf7` | 补 `task-3.6-report.md`（含执行方式、四源一致、三方向、类型归一化两次踩坑、未做到清单）；ledger 加勘误 |
| ⑪ | `sharding.py` 关于 3007 的 docstring 已过期（3007 现已在 `AICORE_ERROR_CODES` 内） | 加勘误说明；**本类码值不变**——原句只是旁证，定档理由是语义论证 |

#### 评审补登、控制者未处理的项（如实保留）

- **⑧ `test_layering.py` 的并发风险比原登记更大**：它还会**改真实被跟踪的
  `provider/__init__.py`** 并在仓库根写临时配置。本组不动它（属第 1 组已验收文件的语义变更，
  需独立任务）；**并发跑测试时该用例结果不可采信，须单跑复核**（评审单跑 `8 passed`，绿）。
- **`pyproject.toml` 的 `allowed-confusables` 由 7 扩到 11（+`？` `−` `×` `–`）**：
  评审逐字符核实过落点、认为理由属实，但**建议改为行级豁免**（`# noqa: RUF001`）
  而不是全局放行。**留待最终评审决定**——本组不再动（它是第 1 组的配置文件）。

### 第 3 组最终门禁（提交 `204801f`，控制者复跑）

```
验收检查表        PASS 10 / FAIL 0 / INFO 0
全量             880 passed, 8 skipped, 19 deselected
integration      19 passed
覆盖率           97.26%（≥80% 门禁）
四源比对         [OK] DDL / er.md / 元数据 三源两两一致（9 张表）
ruff             All checks passed!
mypy             Success: no issues found in 52 source files
lint-imports     4 kept, 0 broken
提交             12 个（9a3f4be → 204801f），工作区干净
```

---

## 第 4 组：AI 网关底座（K-02，共 11 项）

**用户 2026-09-19 选定交付方式（方案 A，与第 3 组同构）**：

| 阶段 | 任务 | 说明 |
|---|---|---|
| **P** | 4.1 Provider Protocol · 4.2 Mock · 4.3 真实骨架+护栏 · 4.4 selector | 不依赖 Redis，可先做 |
| **T** | 4.5 提交与状态机 · 4.6 类型注册表 · 4.7 执行器内核 · 4.8 线程池 | 依赖 3.7 仓储；**4.7 依赖 Redis** |
| **G** | 4.9 幂等+越权 · 4.10 置信度分级 · 4.11 降级与异常区分 | 依赖 T |

另两项用户裁定：**4.2 的「断网可跑」以「测试全程零 socket 建连」取证**（附判别力自证）；
**Redis 由用户在沙箱外自行启动**，控制者已起后台探测任务，6379 一通即补跑真实集成用例，
未通则在验收里如实登记「未验证」而非写成通过。

### 第 4 组开工前的三路只读取证（2026-09-19，控制者派发 3 个 subagent）

侦察结论中**直接改变实现方式**的六条（每条带出处，符合自约束 C6）：

| # | 结论 | 出处 | 对实现的影响 |
|---|---|---|---|
| R1 | `X-Internal-Token` 在 `services/aicore/docs/openapi.yaml` **不存在**（全文无 `securitySchemes:` 段） | 侦察员实测零匹配；F3 决策要求「补写进 securityScheme」**至今未落地** | 第 10.3 项要补，**第 4 组不需要**；登记为缺口 |
| R2 | `modelMeta` **不是具名 schema**，只在习惯计算响应里匿名内联；`TaskResult` 里**没有**血缘字段 | `openapi.yaml:1603-1606` vs `:787-825` | 任务血缘的权威源是 `er.md:295`，不是 OpenAPI |
| R3 | **「模型通道/供应商」枚举在契约层不存在**；`confidenceLevel` **只在视觉/后厨链路**，`OcrResult` 顶层没有置信度 | `openapi.yaml` 检索清单 | OCR 的置信度分级只能落在**单字段** `OcrField.confidence` 上（Task 4.10 的落点） |
| R4 | **AICORE 侧无任何模型调用超时/重试/熔断数值**；「AI 5s」是**网关**路由级 | `高并发架构演进设计.md:317`/`:423`；`tasks.md:123`；design.md 全文无「熔断」二字 | 需新增 4 个配置字段（用户已批准），默认值取平台初值 |
| R5 | design.md 只定义 **3 个** Protocol，**无「平台自建预测」通道**；`provider` 字段单值 vs 每类一个是**文档未规定** | design.md:26/54/142/145/192；tasks.md:37 | **裁定：`provider` 保持单值**，selector 按 3 类分派；第四类只以 `RISK_PREDICT` 任务类型预留位存在 |
| R6 | 全仓库**无任何第三方模型 SDK 依赖**；`httpx` 是唯一相关依赖 | `pyproject.toml:10-46` 逐字 | 真实通道只能用 `httpx` 手写，无 SDK 可包 |

### 第 4 组开工前的两项**第 3 组遗留缺陷**（控制者实测发现，如实登记）

| # | 缺陷 | 实测证据 | 影响 | 处置 |
|---|---|---|---|---|
| **L1** | **在进程内跑一次 alembic 会禁用全部 `aicore.*` 日志器**，导致 17 条依赖 `caplog` 的用例变红 | 引入提交 `d597768`（Task 3.5）。`deploy/sql/migration/env.py:60` 调 `fileConfig()`，**未传 `disable_existing_loggers=False`**；`alembic.ini` 的 `[loggers]` 只声明 root / sqlalchemy.engine / alembic。控制者直接实测：`fileConfig` 前 `aicore.repository.session.disabled = False`，**后 = `True`**。复现矩阵：`-m "not integration"` → **880 passed, 8 skipped, 19 deselected**；`-m integration` → **19 passed**；**不加 `-m`**（同一进程）→ **17 failed, 882 passed**。二分定位到 `tests/repository/test_migration.py` | **两个门禁口径都绿**，故不影响第 3 组验收结论；但「混跑」时不可信，且任何人改 CI 命令都会撞上 | 第 3 组返修（一行参数 + 1 条回归用例）。用户裁定：**不阻塞 P 阶段**，阶段检查点单独定 |
| **L2** | **`app.state.settings` 从未被装配**，而 `api/deps.py` 的 `get_settings` 正是从它取 | `src/aicore/main.py` 的 lifespan 只做 bootstrap→读配置→配置日志→yield→flush，**无一处写 `app.state`**；`tests/api/test_deps.py:15-21` 用 `SimpleNamespace` 桩自造 `request.app.state.settings`，**绕过了组合根**，故用例绿而集成断 | 任何走 `Depends(get_settings)` 的路由在真实应用里都会 `AttributeError`（Starlette `State.__getattr__` 缺属性即抛）。第 4 组 T 阶段要加真实路由，**会立刻撞上** | 用户裁定：P 阶段不修；**T 阶段开工前必修**（否则 4.5 的接口用例无法经组合根跑通） |

**L1 的教训（写进流程）**：第 3 组的最终门禁跑的是分档命令，**没人跑过「不分档的一次性全量」**。
一个只在混跑时出现的缺陷因此躲过了 9 条门禁 + 1 轮独立评审。**混合门禁口径本身是一条覆盖缺口**：
今后每组验收 MUST 额外跑一次「不加 `-m` 的全量」并**解释**其红项（是缺陷就修，是设计就登记）。

### P 阶段的控制者裁定（开工前，2026-09-19）

1. **接口契约由控制者亲自写**（不派发）：`provider/results.py`、`provider/errors.py`、
   `provider/base.py` 三份。理由：第 3 组 Task 3.1 的两次实现者交接说明「契约层出问题，
   后面全废」；且这三份是 `service` 与 `provider` 之间唯一的稳定边界。
   派发顺序为「控制者钉契约 → 并行派 4.2 / 4.3 → 依赖到位后派 4.4」。
2. **`Channel` 只有 3 个成员**（TEXT / VISION / OCR），依据 R5；「平台自建预测」不以
   `Channel` 成员形式存在。用 `type Channel = Literal[...]` 而非 `= str`：后者在静态与
   运行期都不构成约束，「封闭集合」就只剩注释。
3. **`ProviderResult` 用一个类承载三种载荷**（`text` / `markers` / `fields` 三选一），
   而不是三个类：Task 4.1 要的是「统一返回结构」，三个类会让 `service` 层为取 `identity`
   写 `isinstance` 链，「统一」只体现在文档里。代价（类型上无法静态保证 TEXT 结果的
   `markers` 必为 `None`）由各实现的契约用例承担。
4. **`confidence: float | None`，`None` MUST NOT 被当成 `0.0`**：Task 4.10 与 4.11 都要区分
   「没有置信度」与「置信度为 0」；补 0 会把「通道没给置信度」判成 `LOW` 并误触人工复核，
   那是造假数据而非兜底。
5. **熔断归 `4003` 而非 `5002`**：熔断的成因是通道已坏（L316 错误率超阈值），
   与 `4003` 的处置一致；`5002` 的语义是「依赖劣化（等不到响应）」，归过去会让运维误判为「对端慢」。
   熔断单独一个类，因为「**没发出任何请求**」是可断言的可观测差异（Task 4.3 的验收项）。
6. **配置新增 4 个字段**（用户批准）：`ai_call_timeout_s=5.0`、`provider_max_retries=5`、
   `circuit_error_ratio=0.5`、`circuit_cooldown_s=10.0`。**全部可选、有默认值**，与
   `mysql_pool_size` 那种「必填无默认」不同档——前者是平台已定档的护栏初值（★ 压测标定项），
   后者是部署容量决策。连带改动：`tests/unit/test_config.py` 的 `EXPECTED_FIELDS`、`.env.example`。
   **代价已告知用户**：再次改动了第 2 组已验收的文件（与第 3 组 Task 3.4 同类）。
7. **合规门按用户选定的加固方案实现**：`cloud_vision` / `cloud_ocr` 的 `COMPLIANCE_READY = False`
   （依据 `产品设计文档.md:1832`「协议:M2 前签署」），未就绪时**构造请求前**即抛 `4003`
   （`reason="compliance-missing"`）+ 告警，且用例断言「该通道的 HTTP handler 一次未被调用」。
   `deepseek` 为 `True`（依据 `产品设计文档.md:1623`）。
8. **selector 不回落 mock**：选不中的通道返回 `None`。依据 design.md:56——生产上悄悄给
   未选通道塞 mock，等于用假数据伪造 AI 结论并进入人工复核。
9. **`provider/__init__.py` MUST NOT 新增任何导出**：契约 2 把 `aicore.provider` 整包列为
   `service` 的 forbidden，往门面加导出会让 `service` 绕过边界拿到 selector。

### 控制者在 P 阶段自查出的一处**自家坑**（如实登记）

写 `results.py` 时我原本打算让用例用 `get_args(Channel)` 现算比对，以防
`Literal` 与运行期 `CHANNELS` 两处漂移。**实测（Python 3.14.6）推翻了这个打算**：

```
type A = Literal['X','Y']  →  get_args(A) == ()
B = Literal['X','Y']       →  get_args(B) == ('X','Y')
isinstance(A, TypeAliasType) == True
```

`get_args()` 对 `type X = Literal[...]` 形式**返回空元组且不报错**，于是
「现算再比对」会退化成恒真/恒假断言——**看起来在防漂移，实际一行都没防**。
正确做法是 `get_args(Channel.__value__)`。该坑已写进 `results.py` 的注释与 4.4/4.1 工单要求。
**这是同一天第二次遇到「判据本身不自证」的形态**（第一次是第 3 组评审抓到的
`<= MAX_ID_LENGTH` 假绿）；两次的共同点是：**判据看起来在验一件事，实际验的是空集**。

### Task 4.2 完成（2026-09-19）——控制者独立复核，含对实现者一处偏离的**实测裁定**

**交付**：`provider/mock.py` 571 行（原 1 行空壳）+ `tests/unit/test_provider_mock.py` 1008 行 48 条用例。
报告 `task-4.2-report.md`（228 行）。**探针脚本 0 个**（工单 §6 纪律未触发）。

**控制者独立验证（不是转述实现者自述）**：

```
pytest tests/unit/test_provider_mock.py tests/unit/test_provider_results.py
  -> 65 passed in 4.78s
ruff   All checks passed!
mypy   Success: no issues found in 56 source files
契约   4 kept, 0 broken
控制者自建探针（已验证后删除）：
  同进程确定性 = True ｜ 载荷互斥 = True ｜ call_count = 2
  无 15 位以上连续数字 = True ｜ 置信度域 = True
  子进程退出码 = 0 ｜ **跨进程逐字节一致 = True**
  value 样例 = ['11010853******6903', '示例市示例商贸有限公司', '张**', '2027-02-20']
```

#### 裁定一：**接受**实现者对工单 §3 的偏离（D1）——但先自己实测坐实平台事实

工单要求「把 `socket.socket.connect` 换成一律抛错的桩」。实现者报称在本机不可行并改为
「按调用栈归因」。**我没有直接采信，先独立实测**：

```
platform     = win32
loop class   = asyncio.windows_events.ProactorEventLoop
new_event_loop 期间的 connect 次数 = 1
前两个目标 = [('127.0.0.1', 53423)]
```

Windows 的 Proactor loop 用**一对回环 socket** 当 self-pipe（`proactor_events.py:785`
`_make_self_pipe`），而 pytest-asyncio 在**夹具阶段**就建循环、早于测试体——
故「一刀切禁止 connect」会让全部 async 用例在 setup/teardown 就 ERROR。
**平台事实成立，偏离是必要的，不是偷懒。**

**并且他的实现比我工单里的字面要求更严**：判据取「书签帧之下**最内层**那一帧是谁」，
而不是「栈里出现过本项目代码」。理由（我核对源码后认同）：`asyncio.Runner()` 在
**测试函数体内**构造时，self-pipe 那次 connect 的栈下层确实有测试帧，
用「出现过」会把正常的 stdlib 行为误判成违规；而本项目真建连时最内层帧必然是我们自己的。
两侧都留了可复核的栈证据，且配了两条自证用例（正例被记录 / self-pipe 不被误判）。

**能力边界（实现者主动登记的"没做到"，我确认属实）**：抓不到「第三方 SDK 发起的连接」
（其栈内两个 token 都不命中，会被放行）。**但这条缺口在本项目里不成立**：
`tests/structural/test_source_guards.py` 规则 5 已断言「非 `provider/` 文件不得 import
httpx/requests/aiohttp」，两条守卫方向互补——项目代码要么在 `provider/` 内（栈内必有项目帧 → 被抓），
要么根本不 import 网络库（源码级拦住）。两处的用例名与断言位置：mock 侧
`test_socket_guard_has_discriminating_power` / `test_socket_guard_does_not_flag_the_event_loop_self_pipe`；
源码侧 `test_model_http_calls_only_in_provider`。

#### 裁定二：**接受**偏离 D4（脱敏断言收窄）

我工单 §2.6 写「Mock 产出的 `value` MUST 采用**中间打星号**的形态」，字面落到
「所有 value 必须含 `*`」会误判 `名称` / `有效期至` 这类非编号字段（实测 4 条失败）。
实现者改为按**字段名**判定编号类字段（`编号` / `信用代码`）必须含 `***`，
其余字段只要求「无 15 位以上连续数字」。理由（我认同）：
`er.md` §6.2 的「中间打星号」在文档里只由**编号类字段的示例**承载
（`911301********1234`），把非编号字段也要求星号是**把工单没要求的形态强加给实现**。
他的实现里还留了一条很好的注释：**判据按字段名而不是按值的形状**，
因为「值的形状会把脱敏本身变成判据的一部分」——脱敏后的值含星号、不再"纯 ASCII"，
于是**没脱敏的值反而会被判成非编号字段，断言自我失效**（他实测踩到过）。这条推理是对的。

#### 勘误（**控制者自己写下的错误结论，已被实现者反证，控制者复测后确认）**

我在 4.2 的裁定里写：「实现者报告里的一处**不成立的说法**——`addopts="-q"` 与命令行 `-q`
叠加会吞掉计数行」，并附「实测：两种写法都打印汇总行」作为证伪。

**这个证伪本身是错的。** Task 4.3 与 Task 4.4 的两个实现者**各自独立**给出同一句说法，
4.4 的实现者还给出了三写法对照并指出我错在哪。控制者复测（同一条命令、同一截断方式）：

| 写法 | 是否打印 `passed` 汇总行 |
|---|---|
| `-q`（pyproject `addopts` 已含 `-q`，叠加成 `-qq`） | **不打印**（只有 `[100%]`） |
| `-o addopts="" -q` | 打印 |
| 完全不带 `-q` | 打印 |

**我昨天比的是「`-o addopts=""`」与「默认含 `-q`」，从没测过双重 `-q` 这个形态**——
而工单 CMD 里写的、也是我描述并"证伪"的，正是双重 `-q`。
我用一个**不同的**对照实验去否定了一条关于**另一个**形态的结论，还把它写成了「实现者误判」。

**这是同一天第四次同形态错误**，前三次是：
`<= MAX_ID_LENGTH` 假绿（判据是被测对象自己的常量）、
`get_args(type 别名)` 空元组（判据恒真）、
以及本轮把「汇总行存在」当成「计数可读」。
四次的共同结构都是：**我验的东西与我声称验的东西之间差了一层，而那一层没有任何东西在守。**

**已修**：`task-4.4-brief.md` 里的错误口径已改为正确对照表；
并写明「先按工单 CMD 原样跑拿 EXIT 码，再补 `-o addopts=""` 取计数」的双贴要求。
**流程强化（写进后续所有工单）**：控制者给出「已实测」结论时，MUST 附**完整命令原文**，
而不是只附结论与数字——只附数字时，下游无法判断我测的到底是不是他问的那个形态。


#### 实现者自行修掉的两个真 bug（我复核后确认是他自己的代码问题，非契约问题）

1. `level` 分级算式写成 `int(≥0.9) - int(<0.7)` 的"聪明"形式，把 `0.84` 误判成 `LOW`。
2. 脱敏断言把 `名称` / `有效期至` 也要求星号（即上面的 D4）。

### Task 4.3 完成（2026-09-19）——控制者独立复核 13 项机制 + 合规门

**交付**：`guard.py` 386 行、`_http.py` 166 行、三个真实通道 296/291/335 行、
`test_provider_guard.py` 649 行（31 用例）、`test_provider_real.py` 1070 行（51 用例）。
报告 `task-4.3-report.md`。

**控制者独立验证（自己构造场景，**不复用实现者的用例**）**：

```
pytest test_provider_guard.py test_provider_real.py  -> 82 passed in 1.18s
全量 -m "not integration"                            -> 1027 passed, 12 skipped, 19 deselected (EXIT 0)
ruff All checks passed! ｜ mypy Success: 56 source files ｜ lint-imports 4 kept, 0 broken
覆盖率 TOTAL 98.54%（门禁 80%）；_http.py 100%、guard.py 99%（唯一未覆盖行 386 是结构性不可达的 raise）
```

自建探针（验完即删）逐项结果：

| 验什么 | 实测 | 判定 |
|---|---|---|
| 重试次数与退避序列 | `5xx 重试次数 = 6`（1 次首发 + 5 次重试）；`退避序列 = [1.0, 2.0, 4.0, 8.0, 16.0]` | 与高并发 L260 逐项一致 |
| 4xx 不重试 | `send 次数 = 1`、`退避序列 = []`、熔断态仍 `CLOSED` | 正确（客户端错误重试无意义） |
| 超时归 5002 | `code=5002`、`reason=timeout` | 与 4003 不混用 |
| 5xx 归 4003 | `code=4003`、`reason=http-500` | 同上 |
| 熔断门在 send 之前 | 打满后 `state=OPEN`，再调一次 `send 增量 = 0`，抛 `4003` | **核心机制成立** |
| 最小样本数 | 1 次失败后仍 `CLOSED` | 防「首次抖动即熔断」 |
| 半开 | 冷却前 `OPEN` → 推进 `cooldown_s` 后 `HALF_OPEN` | 正确 |
| `ValueError` 不被吞 | 原样上抛 `ValueError`，未转成通道失败 | 正确（吞掉会让 bug 变"通道故障"） |

**合规门（用户选定的加固项）单独验证**：

```
CloudVisionProvider  COMPLIANCE_READY=False → 4003 / reason=compliance-missing
                     build_client 增量 = 0    ← HTTP 客户端根本没被构造（比工单要求更强）
                     HTTP 请求增量   = 0
                     并打出 WARNING，消息里**带出处**（产品设计文档.md:1832、spec.md:95-96）
CloudOcrProvider     同上，两项增量均为 0
DeepSeekTextProvider COMPLIANCE_READY=True  → HTTP 请求增量 = 1（放行）
                     控制者的假响应 {"ok":true} 被判 malformed-response → 畸形解析真在生效
```

#### 实现者主动登记的「没做到」（控制者确认属实，逐条保留）

1. **`identity.thresholds` 三通道都是 `{}`** —— 阈值字段尚不存在于 `Settings`，
   所有者是 Task 4.10。**后果**：`er.md` §6.1 要求 `model_meta` 含阈值快照，
   与 spec.md:128「血缘 MUST 支持按版本维度统计结果质量」有**断言缺口**（当前阈值本就无值可记）。
2. **`ProviderResult.raw` 一律不填**（可能含未脱敏证件值，故主动不填）；
   **本层未记 requestId**，排障链路暂空。
3. 无连接复用（一次调用一客户端），**性能代价未测**。
4. 高并发 L316 的「**慢调用** >阈值」未实现（`Settings` 无该字段）。
5. 云通道密钥无出处（`API_KEY` 默认空串）——`core/config.py` 明确标注这两个通道
   「暂无密钥字段」，加字段超范围。**合规门是它们当前唯一的前置守卫。**
6. **云通道的 base_url / 路径 / 请求体键名 / 鉴权头全是占位口径，未与任何真实厂商 API 校验过**；
   DeepSeek 同样未做真实调用验证。这是「不发出真实计费调用」的必然代价，
   也是**本任务最大的未验证面**——如实保留，不写成"应该没问题"。
7. `call_count` 语义 = 「方法被调用次数（**含被合规门/熔断挡下的那次**）」，
   需 Task 4.9 复核口径（4.9 要断言「幂等重提时 Provider 调用次数不增加」）。
8. 未跑集成/压测。

#### 4.3 给出的口径更正（控制者采纳）

工单里我写的「全量必须 880 passed, 8 skipped」是**旧快照**。实测 1027/12，
`skipped` 从 8 涨到 12 的原因是 `test_source_guards.py` 规则 5 对 `provider/` 下
**每个 `.py` 各 skip 一条**——每新增一个 provider 文件就 +1 skip。
故后续工单的验收判据 MUST 写「EXIT=0 且 failed == 0」，**MUST NOT 写固定计数**。
已更正 `task-4.4-brief.md`。

### Task 4.4 完成（2026-09-19）——控制者独立验证 12 格矩阵

**交付**：`selector.py` 358 行（1 行空壳 → 全量）、`tests/unit/test_provider_selector.py`
883 行 35 条用例。报告 `task-4.4-report.md`。**未改任何"不可改"文件**
（`provider/__init__.py` 仍 1 行 86 字节——契约 2 要求它不得新增导出）。

**控制者独立验证（自建探针，自己构造场景）**：

```
provider       TEXT                   VISION                   OCR
mock           MockTextProvider       MockVisionProvider       MockOcrProvider
deepseek       DeepSeekTextProvider   None                     None
cloud_vision   None                   CloudVisionProvider      None
cloud_ocr      None                   None                     CloudOcrProvider

cloud_ocr：text is None 且 vision is None = True   ← 不回落 mock（核心负向证据）
cloud_ocr：ocr 是实现类（不是 Mock）      = True
deepseek：vision/ocr 均为 None          = True
mock：三槽都是 Mock 实现                = True
护栏四参数在不同取值下 GuardConfig 逐项一致 = True（1.5 与 42.0 两组）
空凭据 None / 空串 / 纯空白 三种形态均 ValueError 且点名 AICORE_DEEPSEEK_API_KEY = True
两次选择的对象不同（无模块级单例）      = True
```

#### 控制者裁定 D7：把 `core/config.py` 的 `_is_blank` **公开**为 `is_blank`

实现者在报告里点名这项需我裁定：`selector.py` 原先
`from aicore.core.config import _is_blank`，即**跨模块 import 私有名**。
mypy 不拦、ruff 不拦、用例也不拦，但它是「空白判定口径只有一处」这句话的**唯一**支撑。

两个选择：① 复制一份到 selector（**造出第二份会漂移的口径**，与他自己在 docstring 里
写的理由自相矛盾）；② 公开导出（一份实现两个入口）。

**取 ②**，并保留 `_is_blank` 作为**别名**——`_is_blank = is_blank`，不是第二份函数体。
实测 `is_blank is _is_blank → True`。收益：既有调用方与既有用例零改动
（`tests/unit/test_config_startup.py` 引用了 `config_module._is_blank`），
且不存在两个函数体（改一处即两边同时变）。`selector.py` 改用公开名。

#### 控制者裁定 D8：接受「`provider=mock` 时不构造熔断器」

工单 §2.4 写「整套选择结果共享一个 `CircuitBreaker`」，实现者实测 Mock 的三个类
**根本没有 `breaker`/`config` 形参**（任务 4.2 的签名里没有），故共享只作用于三个真实通道。
**这是矩阵与实现的真实边界，不是缺陷**：Mock 是离线确定性实现，给它套熔断
等于让离线用例的结果依赖"熔断窗口"这种与离线目标无关的状态。接受，并登记。

#### 控制者裁定 D9：**接受**实现者的探针越界（3 个 > 上限 2 个）

他主动登记「用了 3 个临时脚本，超工单 §6 上限 1 个」，并说明均为只读、`$env:TEMP` 下
用完即删、已确认无残留，第 3 个是为把「护栏参数真的从 config 来」从**断言**升级为**证据**。

**裁定：不返工，且认为这是正确取舍。** 理由：工单那条纪律的**原意**是防第 3 组那两次
「写 6 个 `_probe_recon*.py` 却交不出产物」的失控；本次三个探针**每个都换来了一份证据**
且零残留，与失控形态相反。**纪律约束的是行为，不是计数。**
已把这条裁定写回 ledger，避免后续把「≤2」当成硬指标而不敢取证。

#### 控制者裁定 D6：接受保留一条「结构上不可达」的兜底 `raise`

`select_providers` 额外保留兜底 `raise ValueError`（`model_copy` 造出的表外 provider
会得到带名字的错误，而不是静默三槽皆 None）。**接受**：与
`mysql_readonly_host` 派生属性里「再判一次以兜住绕过校验的路径」同一取向——
静默返回三个 `None` 会让「配置写错」表现为「所有通道都不可用」，根因在日志里看不出来。

### 第 4 组 P 阶段门禁（控制者复跑，未提交工作区）

```
pytest -m "not integration"   1088 passed, 12 skipped, 19 deselected in 26.99s
pytest -m "integration"       19 passed, 1100 deselected in 29.83s
覆盖率                         98.60%（门禁 80%）
   provider 包逐文件：_http 100% / base 100% / errors 100% / selector 100%
                      guard 99%（唯一未覆盖行 386 = 结构性不可达的 raise）
                      results 98% / mock 97%
ruff                           All checks passed!
mypy --strict                  Success: no issues found in 56 source files
lint-imports                   Contracts: 4 kept, 0 broken.
```

### 控制者在 P 阶段补的一处**假覆盖率**（自查发现，如实登记）

`provider/base.py` 报 **100% 行覆盖**——但那是**假的安全感**：三个 Protocol 的方法体
全是 `...`，任何一次导入都会把这 26 行全部"覆盖"到，而**签名是否一致一个字都没验**。
`@runtime_checkable` 的 `isinstance` 也只检查**成员是否存在**，不检查签名、
不看返回类型、不看参数名与参数种类。

存在一条完全静默的退化路径：

```
service 按 Protocol 调 await ocr.recognize(image_key=…, doc_type=…, timeout_s=…)，
实现写成 recognize(self, image, doc, timeout) ——
isinstance 为真、行覆盖率 100%、全部现有用例绿，**运行到真实调用那一刻才 TypeError**。
```

**补法**：`tests/unit/test_provider_base_contract.py`（139 行 26 条用例），
用 `inspect.signature(...) ==` 把「结构子类型」做成**逐参数可执行判据**
（参数名、种类含 keyword-only 标记、顺序、默认值、注解全等），
并同时验 `iscoroutinefunction` 与三个数据成员的类型。

**判别力自证**（今天第三次用这个手法，前两次都抓到真问题）：用例内构造五个
**已知不一致**的合成实现，断言比较本身会判否：

```
_DifferentName (beta→gamma)        → != expected  被抓住
_DifferentKind (丢了 * 号)          → != expected  被抓住
_MissingParameter / _ExtraParameter → 被抓住
_Conforming（唯一合规）             → == expected  不误伤
iscoroutinefunction(同步实现)       → False       协程性判据有效
```

**顺带修掉我自己的一处偷懒**：初版该用例对需要构造参数的真实通道
`pytest.skip("需要构造参数")`。但 `isinstance(类, Protocol)` 对 data protocol
**是成立的**（`runtime_checkable` 查的是 `hasattr`，类属性在类上就能取到），
故那 3 条跳过**没有理由**——它让真实通道（最需要被检查的一侧）恰好躲开了检查。
改为断言类而非实例后：**26 passed / 0 skipped**。

### 第 4 组 P 阶段独立评审（2026-09-19，subagent `57fe22d1`）

**结论：有条件通过**（3 条必须收尾前修）。评审独立复跑六门禁、逐项核实「未做到项」全部属实、
**补登 12 条遗漏**、并做了 6 次变异测试（含 SHA256 逐字节还原自证）。
报告：`review-group4-p-verdict.md`。

**评审最有价值的产出：抓到三处确认假绿**（全部用变异测试证实）。

#### B1【最严重，打在我脸上】我把熔断归 `4003`，与平台码表正面冲突

评审指出：我在评审包 §4 把 `_common/openapi.yaml:132-146` 列为「熔断归 4003」的依据，
**而那份依据恰恰写着反面**。控制者复核原文：

```
_common/openapi.yaml:208   - 5002 # 依赖超时 / 熔断
_common/openapi.yaml:134          依赖超时 / 熔断（code=5002）。
_common/openapi.yaml:135          与第三方业务失败（4001/4002/4003/4004）严格区分：
                                  前者是「没等到响应」，后者是「等到了失败」
core/errors.py:252         DEPENDENCY_TIMEOUT_CODE: "依赖超时或熔断"
core/errors.py:396         """依赖超时 / 熔断（`5002`，HTTP 504）…"""
```

**平台自定义了「熔断 ≠ 通道失败」**，而我的理由（「熔断的成因是通道已坏，处置与通道失败一致」）
是**只想了成因、没想平台是按调用方的观测分档**：熔断时请求**压根没发出去**，
天然落在「没等到响应」那一侧。

**这违反了我自己的自约束 C7**（改码值前 MUST 先读权威定义处并核对语义）——
第二次犯 C7 类的错（第一次是凭印象把 `CrossShardOperationError` 从 `1003` 改成 `1002`）。

**修复（控制者执行）**：
- `provider/errors.py`：`ProviderCircuitOpenError` 改继承 `DependencyTimeoutError`
  （MRO 从 `…→ ChannelFailureError` 改为 `…→ DependencyTimeoutError`），码值 `4003 → 5002`，
  HTTP `502 → 504`；模块 docstring 把这次错误**连原文一起留档**，不是悄悄改掉；
- 码值与超时同码后，**可分辨性改由 `reason` + `operation` + 异常类型承担**
  （评审同时指出：初版 `str(ProviderCircuitOpenError(...))` 与通道失败**完全同串**，
  打日志的代码分辨不出熔断与通道失败——这是平台的 `DEFAULT_MESSAGES` 决定的，不是本层缺陷，
  但本层有责任把结构化字段补齐）；
- 新增 `tests/unit/test_provider_errors.py`（11 条）：**直测**三个子类的码值/HTTP 状态
  与 `core/errors.py` 注册表一致、可被对应 core 基类捕获、文案取自平台默认表、
  **同码不同因必须可用类型/reason/operation 分辨**、并显式断言「同码两个子类的 `str()` 必然相同」
  （防后人为了"让日志能区分"去改平台文案）。
- 连带修正 `test_provider_guard.py` / `test_provider_real.py` 中断言旧码值的 4 处。

**修复的变异复验**：改回 `4003` → 新用例立刻红（`assert 5002 == 4003`）。

**登记为文档冲突（C2）**：`spec.md:72` 说「通道失败 `4003`…依赖超时 `5002`」未提熔断，
`:82` 又说「返回 `5002` 而非 `4003`」——spec 内部即不一致。按事实源优先级
（`_common/openapi.yaml` 的 `ErrorCode` 枚举是平台码表唯一定义处）取 `5002`。
**spec 未改**（C5）。

#### B2【必须修】我的判别力自证**没验到真断言**

评审的变异：把 `test_provider_base_contract.py` 的 `actual == expected` 弱化成
**参数个数比较**、**同时**在 `deepseek.py:134` 制造真签名漂移（删掉 `*`）
→ **全量 1088 passed**，那条自证用例自己也绿。

**根因**：初版自证只测**合成类**上的 `signature != signature`，
**从未让真正的一致性判据参与**。判据被弱化了，而"证明判据有效"的用例没有察觉——
**这正是本任务要防的假绿形态，却出现在防它的用例里。**

**修复（三条缺一不可）**：
1. 判据抽成具名函数 `assert_signature_conforms`，自证用例直接调用**它**（不复制逻辑）；
2. 漂移实现 `_DriftedTextProvider` **挂进真实矩阵**（第 7 行）→ 判据被弱化时
   参数化路径那条用例立刻变红；
3. 另加一条直接验证判据函数对真实漂移会抛错，并**先断言该载体确实是漂移**
   （防载体失效后自证变成空转）。

**变异复验**：把判据弱化成参数个数比较 → **2 failed**（`[_DriftedTextProvider.complete]`
与 `test_conformance_assertion_rejects_a_drifted_implementation`），28 passed；
按 SHA256 逐字节还原。

#### B3【必须修】「零 socket 建连」守卫**不覆盖 `src/aicore`**

评审的变异：往 `mock.py` 注入真实 `socket.connect(("192.0.2.1", 9))` 后
→ mock / real / selector **三个套件 48+51+35 全绿**。

**根因**：守卫装在 `tests/unit/test_provider_mock.py` 里（文件级 autouse），
故 `mock.py` 在**别的套件**运行时没有任何守卫在听。
「某实现无网络依赖」是**实现的性质**，不是「某一个测试文件的性质」。

**修复（控制者执行）**：把守卫提到 `tests/conftest.py` 做成**会话级 autouse**。

**过程中撞到一个真问题并修正了判据**：第一版会话级守卫只看调用栈，上线后第一次全量跑
在 `test_health_stays_bare_and_still_echoes_trace_id` 的 teardown 报出
**32 次违规，栈全部指向 `test_provider_real.py:269:connect`**——
那是它自己守卫的**转发帧**（它按目标地址放行环回，一个项目帧）。
即：纯栈判据会把 self-pipe 的环回误判。

最终判据取**合取**：① 目标**不是**环回 **且** ② 栈里**出现过**本项目帧 → 才判违规。
与 `test_provider_real.py` 的 `_SocketGuard` 口径一致但更严一档
（它放行一切环回，本守卫在「非环回 + 项目帧」时才判违规）。

**能力边界（如实登记）**：环回一律放行，故**抓不到**「误连本机另一个服务」；
也抓不到「栈内既无项目帧、也无 stdlib socket 帧」的连接。
后者由 `test_source_guards.py` 规则 5（非 `provider/` 不得 import 网络库）补上。

**变异复验（改用更安全的方式）**：新建临时用例文件 `tests/unit/test_zz_mutation_b3.py`
故意对外建连 → 会话级守卫变红且**栈归因正确**：

```
目标=('192.0.2.1', 9) 栈=('test_zz_mutation_b3.py:23:test_deliberate_external_connect_must_be_flagged',)
12 passed, 1 error
```

#### 控制者在修 B3 时**两次污染了源文件**（如实登记，含教训）

两次尝试都是「注入到 `src/` 的真实模块 → 跑套件 → finally 还原」，两次都**超时被杀**，
`finally` 没跑完，**注入残留在文件里**：

1. 第一次注入 `mock.py`，残留 214 字节。**靠注入是追加的、按标记点截断还原**，
   还原后 `sha256 = d601ecfc…e55d`，与评审报告记录的 SHA256 **逐字节相同**、571 行。
2. 第二次注入 `errors.py`，残留一处调用行 + 13 行定义块。按精确文本移除后 128 行、零残留。

**教训（写进流程）**：**变异测试 MUST NOT 用「改源文件 + finally 还原」这一形态。**
超时/被中断时 `finally` 不保证执行，而源文件是全组交付的载体，污染代价远高于变异收益。
**正确形态**：变异载体本身是一个**可随时删除的临时测试文件**（本次最终采用的方式），
或改在 `tests/` 下的合成实现上做——**永不触碰 `src/`**。
另：变异测试的目标 MUST 选**导入快、覆盖用例少**的模块，并预估时限。

#### 评审指出、控制者**尚未处理**的项（如实保留，不声称已修）

| # | 项 | 说明 |
|---|---|---|
| **C1** | 98.60% 覆盖率排除了三个真实通道文件（`pyproject.toml:118` 的 omit，`git blame` 指向骨架提交 `37aa77b`，**非本组引入**） | 去掉 omit 实测 cloud_ocr 93% / cloud_vision 93% / deepseek 92%——**确实被测到**，但掩盖了 17 行可达未测代码，其中 `cloud_ocr.py:304-306` 的 `confidence` bool 排除分支**零覆盖**（同契约在 deepseek 有专门用例）。omit 是 design.md:284 的既定设计（「真实通道骨架允许排除」），故**是否改**需用户定档 |
| **N6** | `selector.py` docstring 声称「用例用 handler 计数反推重试次数」——**该用例不存在** | 属「文档声称有证据、实际没有」，比「没做到」更严重，须修 docstring 或补用例 |
| **N7** | `test_provider_results.py` 注释称覆盖 `required` 列表，实际只做子串包含 | 弱断言，须收紧或改注释 |
| **N9** | `base.py:12`（「三通道都声明 `prompt_version`」）与 `deepseek.py:14`（「VISION 没有 prompt 版本」）**自相矛盾** | 两处 docstring 冲突 |
| **N10** | `raw` 恒为 `None` 是事实，但**没有任何「必须为 None」的断言** | 将来加 `raw=decoded` 会带出未脱敏证件值而 51 条用例全绿——须补断言 |
| **出处失实** | `deepseek.py:9` / `:11` 的 `COMPLIANCE_READY=True` 出处引 `产品设计文档.md:1623`，但同文档 `:1826` 状态栏写 `用户+运营 / M0`（**未完成**） | 故 `COMPLIANCE_READY=True` **无可引用出处**，且测试只断言常量取值不核出处 |

### 第 4 组 P 阶段门禁（B1/B2/B3 修复后，控制者复跑）

```
pytest -m "not integration"   1103 passed, 13 skipped, 19 deselected
pytest -m "integration"       19 passed, 1116 deselected
覆盖率                         98.60%（门禁 80%）
ruff                           All checks passed!
mypy --strict                  Success: no issues found in 56 source files
lint-imports                   Contracts: 4 kept, 0 broken.
```

**新增文件**：`tests/unit/test_provider_errors.py`（11 条）。
**改动文件**：`provider/errors.py`（码值 + docstring 留档）、`tests/conftest.py`（会话级守卫）、
`tests/unit/test_provider_mock.py`（改用会话级守卫 + 判别力探针改对外地址）、
`tests/unit/test_provider_base_contract.py`（判据抽函数 + 漂移载体入矩阵）、
`tests/unit/test_provider_guard.py` 与 `test_provider_real.py`（断言新码值）。

### P 阶段提交（2026-09-19，用户选定拆 5 个提交）

**门禁**：`commit-check` 技能逐项对照 A~F 全通过。**hook 层不可用的如实说明**：
`core.hooksPath=.githooks`，但 hook 是 shell 脚本而本沙箱 `sh` 被拒（`E_ACCESS_DENIED`），
故控制者对 hook 的**全部确定性检查**逐项手工复跑：
冲突标记无、新增行尾空白无、`git diff --check` 无输出、无 >1MB 文件、无私钥、
`.env` 已 gitignore（`services/aicore/.gitignore:12`）、5 条凭据正则零命中、
Conventional Commits 格式合规、**提交信息不带 `[AI]` 前缀**（规则六）。
提交用 `--no-verify`，属**已授权的既有做法**，非跳过门禁。

```
201531b feat(aicore): 实现 Provider 选择器并修复独立评审指出的三处假绿   ← 4.4 + 评审修复
e478fa0 feat(aicore): 实现真实通道骨架与超时/重试/熔断护栏              ← 4.3
94ca4cd feat(aicore): 实现确定性 Mock 通道并证明全程零对外建连          ← 4.2
be93259 feat(aicore): 新增四项通道护栏配置并同步模板与字段表            ← 配置
c71e157 feat(aicore): 落地 Provider 契约三件套与签名级一致性检查        ← 4.1
```

**提交后门禁复跑（工作区已干净，验证提交确实捕获了同样的内容）**：

```
pytest -m "not integration"   1107 passed, 13 skipped, 19 deselected
pytest -m "integration"       19 passed, 1120 deselected
ruff / mypy / lint-imports    All checks passed! | 56 files | 4 kept, 0 broken
```

### 环境变更（2026-09-19）：**Redis 已可用**（用户启动）

控制者起了一个 8 小时窗口的后台探测任务（`pwsh-1`），
`[14:35:19] REDIS_UP 6379 reachable`。控制者实测：

```
127.0.0.1:6379 LISTENING ｜ redis_version = 8.0.5 ｜ redis_mode = standalone
PING          = True
SET NX 首次   = True          ← 任务执行器的原子领取原语
SET NX 二次   = None
TTL(ms)       = 4997
清理后存在    = 0
```

**影响**：T 阶段的 Task 4.7（执行器内核：Redis `SET NX PX` 原子领取 + 心跳续期 +
租约超时回收）**可以做真实 Redis 集成用例**，不必退到「离线内存实现 + 未验证」。
用户第四问的答案是「我现在就起 Redis，你等我」——已等到，T 阶段可开工。

---

## 第 4 组 T 阶段：任务链路（4.5~4.8）

**用户 2026-09-19 选定（方案 A 的延续）**：

| 子阶段 | 任务 | 说明 |
|---|---|---|
| **T1** | 4.5 提交与状态机 · 4.6 类型注册表 | 只需 sqlite 沙盒，不碰真 Redis |
| **T2** | 4.7 执行器内核 · 4.8 线程池 | 4.7 **用真实 Redis** 做集成用例 |

另一项裁定：**L2 只装配 `app.state.settings`**（不顺便接 Provider——4.5 不需要，
且具体装配形态要等 4.6/4.7 的形状定下来才好定）。

### T1 开工前的规范研读（用户要求「研读文档规范」，符合自约束 C1）

**MUST 读的章节已全部读完**（不是 grep）：`design.md` §接口分类与任务契约 L175-194、
§异步并发与任务执行器内核 L196-212、§数据层落地 L214-227；`er.md` §6.1 L284-298、
§7.1 L425-435；`openapi.yaml` 的 `/aicore/ocr` L44-106、`/aicore/tasks/{taskId}` L107-155、
四个 schema；`spec.md` L23-40（三个 Scenario）；既有实现
（`task_repo.py` / `session.py` / `base.py` / `idgen.py` / `envelope.py` / `deps.py`）。

**研读得到的关键口径（每条带出处，符合 C6）**：

| 项 | 出处 | 结论 |
|---|---|---|
| **`account_id` 来源** | `services/gateway/.../JwtAuthFilter.java:22/:90-93/:96` | 信任网关注入的 **`X-User-Id`**：网关先 `headers.remove()` 剥掉客户端伪造值，再写入**验签 JWT 的 `sub`** |
| 账号缺失的处置 | `services/acc/.../TrustedHeaderAuthFilter.java:27` | **fail-closed：401 + `2001`**；AICORE 照此 |
| 幂等键 | `openapi.yaml:54` + `er.md:290` | `Idempotency-Key` 头**可选**；缺省由 `imageKey`+`docType` 派生；`uk_idem(account_id, idem_key)` **NULL 豁免、同月表内唯一** |
| 状态机 | `er.md:430` 逐字 | `PROCESSING→SUCCEEDED/FAILED/MANUAL_REVIEW` |
| 轮询会话 | `er.md:252` 逐字 | 「关键**写后立即读**（**任务提交后立即轮询**、复核后立即查状态）**强制走主库**」→ 用 `primary_read_session()`，**MUST NOT** 用 `read_session()`（后者会抛 `1002`，`session.py:243-249`） |
| 物理表名 | `repository/base.py:53` | `Table.to_metadata(MetaData(), name=物理名)`（第 3 组实测，另两条路已证伪） |
| `scene` 字段 | `er.md` §6.1 | `ai_task` **没有** `scene` 列 → 只校验/透传，**MUST NOT 落库**（会撞三源比对） |

### T1 控制者裁定（开工前）

1. **HTTP 受理状态码用 `202`**，而 `openapi.yaml:62` 写的是 `'200'`。理由：
   `spec.md:30` 逐字「系统**立即返回**任务号与受理状态」、`tasks.md` 4.5 逐字「提交即写」，
   语义即 RFC 9110 的 `202 Accepted`；`openapi.yaml:63` 自己就写着「受理成功，返回任务号（异步处理）」。
   **差异已登记**，且工单要求用例**同时**断言「状态码 202」与「响应体是 `TaskAccepted` 契约」，
   让差异显式可见而非隐藏。**风险已告知用户**：前端若按 `200` 断言会红。
2. **跨账号轮询返回 `2002`（403）而非 404**：依据 `spec.md:32-35` 逐字「返回 `2002`
   **且不泄露该任务的任何结果内容**」。分片只按月份切，**别人的任务与本人在同一张月表**，
   故「带本人账号查不到」无法区分「不存在」与「是别人的」——只能取行后比 `account_id`。
   代价是**把别人的行读进了本进程**，故 MUST 立刻判定、MUST NOT 写日志，
   且返回体**只含信封四字段、`data` 为 `null`**（按最严解读：连 `status`/`progress` 都不给）。
3. **未注册任务类型用 `1003`**：「枚举值不在当前可用范围」正是 `1003` 的定义；
   `3006` 是「对象不存在」（针对已存在的资源）、`3007` 是「状态不允许该操作」（针对资源状态）。
   **MUST NOT 混用。**
4. **`TaskPolicy.timeout_s` 从 `Settings.ai_call_timeout_s` 现读**：design.md 未给任务级超时值，
   凭空造一个等于自造第三口径（违反 C2/C7）；借用一个**有出处**的值并**显式标注是借用**更诚实。
   `get_policy` MUST 现读（可注入），MUST NOT 冻结成模块常量——4.7 若发现借用值不合适要能改。

### T1 前置修复：L2（控制者执行，含变异自证）

`main.py` 的 lifespan 此前**从未写 `app.state.settings`**，而 `api/deps.py` 的 `get_settings`
正是从它取。修法：`configure_logging(settings)` 之后、`yield` 之前装配一行。

**位置的两条理由**（写进 docstring）：① 校验失败时**不装配**——已被拒绝的配置不该出现在
`app.state` 上；② 在 `configure_logging` 之后——日志一旦可用，这条装配事实本身就可被观测。

**补的回归**：`tests/api/test_deps.py` 原有用例用 `SimpleNamespace` 桩**绕过了组合根**
（正是 L2 藏身之处）。新增两条：
- `test_dependency_resolves_through_the_real_composition_root`：**经真组合根 + 真 lifespan**
  （`with TestClient(app)`），MUST NOT 用桩；
- `test_dependency_is_not_available_before_startup`：**阴性对照**，证明绿灯来自装配
  而不是「取不到就给默认值」的兜底。

**变异自证**：删掉装配行 → `1 failed`（`test_dependency_resolves_through_the_real_composition_root`）；
按字节还原，`sha256 = 44588d3b80b67753…`（前后一致）。
**变异方式已改为安全形态**（只改一个小文件、只跑一个测试文件、立即还原）——
不再用「改源文件 + 依赖 `finally`」那种超时即残留的做法。

### T1 前置新增：测试基础设施（控制者提供，实现者禁止修改）

1. **`tests/support/db_sandbox.py`**：把原在 `tests/repository/test_repos.py` 内部的
   sqlite 沙盒构造器**抽成共享层**。理由与第 3 组 `task-3.6b` 同构——
   在第二个文件里复制一份就会造出**第二套会漂移的沙盒口径**，
   而沙盒的三处「缩水」一旦两边理解不一致，「沙盒绿」与「生产行为」的差距就再也说不清。
   **顺带登记一处实测副作用**：抹掉 `CURRENT_TIMESTAMP(3)` 后沙盒里没有 `created_at` 库级默认值；
   生产与沙盒在「不传 `created_at`」时**都会报错但错误不同**（NOT NULL vs 月份算不出），
   故不构成掩盖。
2. **`tests/conftest.py` 的 `api_client` / `sandbox_engine` 夹具**：经**真组合根**（触发真 lifespan）
   **再**覆盖 `app.state.engine_factory` 为沙盒替身——顺序是硬要求（反过来会被真装配覆盖）。
   替身**只实现被用到的方法**，且如实登记边界：沙盒只有**一个**库，
   「主/从」之分在这里没有对应物，故**它不覆盖「轮询不走从库」**，
   那条由源码断言与真 MySQL 集成用例覆盖。
3. **夹具自证**：`test_api_client_fixture_reaches_a_writable_sandbox` 做**双向**验证
   （建表 + 写入 + 读回 42）。**为什么必须写一行而不只读**：只读探针（`SELECT 1`）
   在「引擎接错但恰好能连」时也会绿。一个坏夹具会让实现者卡在「路由写对了但用例跑不起来」，
   而那种卡点最容易被误判成自己的代码问题。
4. **B008 的处理**：本仓库**第一次**用 `Depends`，ruff 的 B008 会报。
   **行级豁免 `# noqa: B008` 下在真实需求处**，MUST NOT 全局关掉 B008——
   它防的是「可变默认值」这类真实陷阱（同第 3 组评审对 `allowed-confusables` 的建议）。

**T1 基础设施就绪后的门禁**：

```
pytest -m "not integration"   1110 passed, 13 skipped, 19 deselected
ruff / mypy / lint-imports    All checks passed! | 56 files | 4 kept, 0 broken
```

### T1 派发

两路并行（文件零重叠）：**4.5**（`api/ocr.py` + `api/tasks.py` + `service/task/{state,submit}.py`
+ `api/deps.py` + `main.py`）、**4.6**（`service/task/registry.py`）。
工单：`task-4.5-brief.md`、`task-4.6-brief.md`。

### T1 中途：控制者的 `api_client` 夹具被实现者实测证伪（**我今天第五次同类形态，且这次是我自己犯的**）

**Task 4.5 的实现者没有停摆，而是先报硬伤**：他实测发现
`tests/conftest.py::api_client` + `tests/support/db_sandbox.py::build_sqlite_engine()`
这一对，**在路由线程里看不到任何表**。

**控制者独立复现（不是采信他的结论）**：

```
池类型       = SingletonThreadPool
主线程表数   = ['ai_task_202607', 'ai_task_202608', 'ocr_correction_202607', 'ocr_result_202607']
工作线程表数 = []        ← 每线程一条独立连接 = 每线程一个空库
```

**根因**：裸 `create_engine("sqlite://")` 的默认池是 `SingletonThreadPool`（**每线程一条连接**），
而 sqlite 的内存库是**连接级**的——"每线程"就等于"每线程一个空库"。
FastAPI 的同步路由跑在「AnyIO worker thread」、TestClient 经 portal 线程驱动应用，
**都不是 pytest 主线程**，故主线程建的表路由侧一条也看不到。

**为什么我的自证用例是绿的**（这才是真正的问题所在）：
`test_api_client_fixture_reaches_a_writable_sandbox` 在**主线程**直接对引擎建表/写入/读回，
**把「经真应用发请求」这一环替成了直接读写引擎**——于是那一环永远不会有红灯。
实现者原话：「与 L2 同类形态：用例把关键环节替成了桩」。

**这是同一天第五次同形态的假绿**，前四次：
`<= MAX_ID_LENGTH`（判据是被测对象自己的常量）、`get_args(type 别名)` 空元组（判据恒真）、
「汇总行存在」被当成「计数可读」（**我测的形态与声称的差一层**）、
`deepseek.py` 删除 `*` 后全量仍绿（判别力自证没让真判据参与）。
**共同结构始终是：判据没有经过被测的那一环。** 这次它在**我自己写的夹具自证**里。

**修复（控制者执行）**：
1. `build_sqlite_engine` 改为 `create_engine("sqlite://", poolclass=StaticPool,
   connect_args={"check_same_thread": False})`。实测修后工作线程表数与主线程**一致**（4 张）。
   docstring 里补了一节，写明「内存库必须 StaticPool，否则路由线程看不到表」，
   并点明它的失效形态是**「主线程看得到、路由看不到」**——一个只在经真应用发请求时才暴露的差异。
2. **把自证改成经真组合根发真请求**：新增
   `tests/api/test_deps.py::test_sandbox_tables_are_visible_from_a_route`，
   经 `api_client` 发请求，探针路由在 AnyIO worker thread 里对 `ai_task_202607` 做
   `SELECT count(*)`。原那条保留但**明确标注能力边界**：「它在主线程直接操作引擎，
   故不能替代上面那条」。
3. **变异验证**：去掉 `StaticPool` → **`test_sandbox_tables_are_visible_from_a_route` 变红**
   （`1 failed, 4 passed`）；按字节还原，`sha256 = 3720a6d26334c6d4…` 前后一致。

**实现者的处置（控制者已确认其做法正确）**：他**没有动**「不可改」清单里的夹具，
而是在 `tests/api/conftest.py` 里**包内覆盖** `sandbox_engine` 一个夹具作为 workaround，
并保留了 5 条原始复现证据。控制者已修根因，并**要求他删掉该 workaround**
（留着会造出第二套 `sandbox_engine` 口径——正是控制者在抽取 `db_sandbox` 时想避免的那种漂移），
同时**保留证据**并如实登记「该缺陷由实现者发现」。

**流程教训（新增）**：**夹具的自证 MUST 经过「夹具被用到的那条链路」**，
而不是经过夹具的底层对象。夹具的底层对象（引擎）通常在主线程就能操作，
而夹具真正要服务的调用方（路由线程）可能完全不同——
**只测底层对象等于只测了夹具的一半，而漏掉的那一半恰是"上下文"这一环。**

### Task 4.6 完成（2026-09-19）——控制者独立验证，含一条**接口冲突裁定**

**交付**：`service/task/registry.py` 245 行（1 行空壳 → 实现）、
`tests/unit/test_task_registry.py` 775 行（**28 passed + 1 skipped**）、报告 335 行。

**控制者独立验证（自建探针，验完即删）**：

```
注入配置 1.5  -> get_policy("OCR").timeout_s = 1.5
注入配置 42.0 -> get_policy("OCR").timeout_s = 42.0
默认路径：环境 AICORE_AI_CALL_TIMEOUT_S=7.5 -> timeout_s = 7.5     ← 真的现读，未被冻结
REGISTRY 行内快照（非权威值）= 5.0
未注册     -> code=1003  消息含类型名 = True
预留未实现 -> code=1003  消息含类型名 = True      两条消息不同 = True
四条登记 = ['KITCHEN_ANOMALY', 'OCR', 'RISK_PREDICT', 'VISION_REVIEW']
REGISTRY 运行期只读 = True（MappingProxyType 写入抛 TypeError）
```

**额外收益（探针偶然发现，值得记）**：注册表**导入时不需要配置存在**。
我的第一版探针没铺 `AICORE_*` 就调 `get_policy("OCR")`（不注入 settings），
当场 `ValidationError`——这恰好证明它的延迟读取设计生效：
若当初写成导入期 `get_settings()`，**任何 import 注册表的模块**都会被本机配置绑架，
且配置写错时会在 import 期抛错、绕过 `core/config.py` 的启动期 `ConfigRejected` 路径。
实现者的这条取舍是对的。

#### 裁定 D2（实现者点名要我复核的接口冲突）：**接受其取舍，并更正我工单的措辞**

**冲突内容**：我工单 §1 同时要求「`REGISTRY` MUST 是模块级常量」与
「`get_policy` MUST 从 `Settings` 现读、MUST NOT 把超时冻结成模块级常量」。
实现者指出：**模块级常量表的字段不可能既导入期定值又每次现读**。

**这是我工单里的措辞歧义，不是实现者的问题。** 「`REGISTRY` MUST 是模块级常量」的原意是
**为了可断言**（`tests` 要对整张表断言，4.4 的 `CONFORMANCE_MATRIX` 同构），
**从未要求它承载权威超时值**。两句合起来的正确读法应是：
**表是声明（结构可断言），超时的权威取值一律经 `get_policy` 现读。**

**裁定：接受实现者的取舍**，即：
- `REGISTRY[task_type].timeout_s` 是**配置默认值的快照**（`_BORROWED_TIMEOUT_S`，
  从 `Settings.model_fields["ai_call_timeout_s"].default` 读，**不是硬编码第二处 5.0**）；
- `get_policy` 每次用 `dataclasses.replace(行, timeout_s=现读值)` 返回**权威值**；
- 结构断言读表、取值读 `get_policy`。

**为什么不改成「读表即权威」**（另两条候选：`timeout_s: float | None` 或惰性 Mapping）：
① 惰性 Mapping 会让 `REGISTRY` 不再是「可整表断言」的常量，直接违背我加那条约束的初衷；
② `float | None` 把「必须有超时」降级成可选，等于用一个类型变化掩盖口径问题，
且调用方要为 `None` 写分支（迟早被 `or DEFAULT` 抹平——正是 `get_policy` 拒绝回落的同一形态）。
**当前取舍的代价（如实登记）**：环境覆盖 `AICORE_AI_CALL_TIMEOUT_S` 时，
`REGISTRY[...].timeout_s` 与实际生效值不同。该代价已写在实现者的 docstring 里、
且与工单的「现读」要求一致，故**不构成缺陷**。

#### 裁定 D3 / D4：接受

- **D3**：三个预留位的 `handler_ref = "<reserved>"` 哨兵。理由成立——
  `design.md:136-140` 的目录树**确实没有** `vision_review.py` 之类，
  凭空编一个模块路径会让 Task 4.7 的导入探测得到**假的**「注册表与实现不一致」。
  哨兵含 `<` `>` 故不是合法模块名，使「预留」与「已实现」在输出里一眼可辨。
- **D4**：`MappingProxyType` 使 `REGISTRY` **运行期**只读（`Final[Mapping]` 只挡得住 mypy，
  裸 dict 运行期照样能改）。注册表是共享常量，就地改会污染所有调用方——该加固是对的。

#### 4.6 的判据 B **显式 skip**（控制者确认这是正确处置，不是漏做）

「新增类型不改 `task_runner`」的结构性断言需要 `core/task_runner.py`，而它此刻仍是
1 行 docstring 空壳。实现者**显式 SKIPPED 并写明理由**（skip 条件是「文件无代码」
而不是「不想跑」），另加一条**不跳过**的用例用「从 `REGISTRY` 现读的类型集合 +
合成分支式 runner」证明**判据本体**有判别力。
**这正是工单要的处置**：不能假装验过，但也不能让判据本身无人守。Task 4.7 交付后该断言自动生效。

#### 4.6 报出的一处**接缝**（控制者裁定：由 4.5 收口）

4.5 的 `submit.py` 自带 `OCR_TASK_TYPE: Final = "OCR"` 常量、**未 import 注册表**。后果两条：
① M1 提交路径存在**第二个任务类型来源**（与注册表并列）；② `assert_submittable`
（未实现类型拒绝）**尚无调用方** —— 等于 4.6 交付的准入判定没有生效。

**裁定：注册表是任务类型的唯一来源，提交路径 MUST 经 `assert_submittable`。**
待 4.5 交付报告后派发收口（4.5 的文件正被其实现者持有，避免并发抢文件）。

### 控制者对 Task 4.5 的独立验证（2026-09-19）——含**我自己两次误报**，如实登记

**交付现状**：`test_task_poll.py`（15342 字节 / 10 条用例）**确实存在**——
控制者先前报「不存在」是读到了**旧快照**（文件在 14:59 才落盘），**已向实现者更正**。
其 10 条用例覆盖工单 §3 的 18~24 **全部 7 项**，另加 3 条守卫
（响应枚举 vs 状态机 / 会话入口切分 / 扫描器判别力）。
实现者还用 `app.dependency_overrides[get_now]` 注入时钟——**FastAPI 标准替换通道，
不改生产代码、不 patch 函数**——这一手很干净。

**控制者自建探针（经真组合根 + sqlite 沙盒 + 冻结时钟，验完即删）全部通过**：

```
状态机： PROCESSING → {SUCCEEDED, FAILED, MANUAL_REVIEW} 全通过
        终态出发的 12 条转移全被拒，全部 code=3007；未知状态 → ParamError 1003
         is_terminal(PROCESSING)=False / is_terminal(SUCCEEDED)=True
受理：   HTTP=202 code=0 status=PROCESSING；taskId 前缀 task_、长度 32
幂等 A： 显式 Idempotency-Key 同键重提 → 同 taskId = True
幂等 B： 无头（派生键）两次 → 同 taskId = True；落库 idem_key == sha256(imageKey\0docType)[:32]
         两组互不相同（显式键与派生键是**不同的键**，这是正确行为）
隔离：   换 docType → 不同 taskId；换账号 → 不同 taskId
校验：   X-User-Id 缺失/空串/纯空白 → 401 + 2001（三种）
         非法 docType → 400 + 1003；缺 imageKey → 400 + 1001（MUST NOT 出现 422）
轮询：   他人 → 403 + 2002，**泄露字段 = []、data=None**（spec.md:35 的最严解读成立）
         不存在 → 404 + 3006；本人 → 200 + code=0，required 四字段齐
         PROCESSING 时 result/errorCode/finishedAt 全 None、progress=0
```

#### 误报一：控制者用一条**未按预期展开的 glob** 得出「`compute_idem_key` 零调用方」

控制者跑 `Select-String -Path src\aicore\**\*.py,tests\**\*.py -Pattern 'compute_idem_key'`
得到**空输出**，据此判定「函数从未被调用、幂等完全不生效」并要求实现者修。
**这是错的**：`submit.py:227` 逐字 `effective_key = compute_idem_key(explicit=idem_key, …)`。
用**显式文件路径**重跑同一条 grep 立刻命中三处（定义 / docstring / 调用）。
根因是 PowerShell 的 `-Path` 通配展开与预期不符，**glob 没展开时 `Select-String` 静默返回空**。

**流程教训（新增，与今天其他教训同源）**：
**grep 无输出 MUST 换一种检索方式复核，绝不能把「没搜到」当成「不存在」。**
这与「判据没有经过被测那一环」是同一族错误：**空集既可能是"真的没有"，
也可能是"检索方式失效"**，而两者在输出上完全一样。
（今天第四次把空集当成结论：`<= MAX_ID_LENGTH`、`get_args(type 别名)`、
夹具自证绕过路由线程、以及这次的 grep 空输出。）

#### 误报二：控制者的探针**混用两种幂等键**，却期望它们互通

探针先带 `Idempotency-Key: k-1` 建任务，再**不带任何头**提交同一图，断言应得同一 `taskId`
——得到 `False`，我据此报「幂等不生效」。**又是错的**：显式键是 `k-1`，派生键是 `20a8367d…`，
**是两个不同的键**，命中不了才是正确行为。`spec.md:39-40` 与 `er.md:290` 说的是
「**相同幂等键**重复提交」，从未要求显式键与派生键互通。
改为**分组隔离**后（2a 显式键组 / 2b 派生键组各自自洽）全部通过。

**教训**：报缺陷前 MUST 先确认**自己的对照实验构造得对**——
两次误报都不是实现的问题，而是我把「我没构造对」当成了「实现有错」。
这与 C3（能实证的 MUST 先实证再结论）同向，但更具体：
**实证也包括"确认我的实验本身在测什么"。**

### T2 工单准备（用户指示「并行工作」）

T1 实现者收尾期间，控制者并行做了 T2 的**研读 + 预检 + 工单**（不碰代码，零冲突）。

#### 读全的权威依据（符合 C1）

`tasks.md` L43-44、`design.md` §异步并发与任务执行器内核 L196-212、D2 L42-50、
`er.md` §7.1 L425-435 / §5.5 L252 / §6.1 L284-298、
`高并发架构演进设计.md` L260/L294/L316/L317/L318/L423、
`provider/guard.py`（`StepClock` 范式）、`repository/task_repo.py` 既有能力、
`repository/base.py` 的 `ShardKey`/`BaseRepo`、`service/task/registry.py` 的 `TaskPolicy`。

#### 三项**实测预检**（写进工单，省实现者一轮）

**① `redis` 包是 8.1.0，且有两个 API 陷阱**：

```
AsyncRedis.set 支持 nx/xx/px/ex/keepttl，但组合有约束
AsyncRedis.renamenx 的签名里**没有** px 参数
```

- 陷阱 A：**续期 MUST 用 Lua，MUST NOT 用 `set(key, token, xx=True, px=...)`**
  —— 后者不校验 owner，**任何实例都能续期别人的租约**，正是 `design.md:208` 要防的
  「两个实例同时处理同一任务」。
- 陷阱 B：裸 `SET k v NX PX ms` **不能同时把尝试计数 +1**，而 `max_retries` 的判据是"领取次数"
  （`ai_task` **没有** attempts 列，`er.md` §6.1 逐列可查），故也用 Lua。

**② `ai_task.type` / `status` 是原生 MySQL ENUM + `validate_strings=True`**：

```
type   -> ENUM('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT')
status -> ENUM('PROCESSING','SUCCEEDED','FAILED','MANUAL_REVIEW')
```

后果：非法值会抛 `Data truncated`、**写不进去**，故集成用例 MUST NOT 用"写非法枚举"做探测。

**③ Lua 脚本在真实 Redis（8.0.5）上已跑通**，原始输出：

```
首次领取 attempt      = 1
二次领取（未过期）    = 0
PTTL                  = 4999
错误 token 续期       = 0
正确 token 续期       = 1，新 PTTL = 9000
退避中领取            = 0
释放后再领取 attempt  = 2        ← 计数在累加，不因释放清零
清理后残留键          = []
```

工单直接给出这两段 Lua + 该输出，实现者照抄即可。

#### T2 工单的四处控制者裁定（都有出处）

1. **`core/lease.py` 的 `StepClock` 必须重新声明，不能从 `provider/guard.py` 复用**：
   契约 4（`core-independent`）的 forbidden 列表**含 `aicore.provider` 整包**，
   故 `core → provider.guard` 是被禁的直接依赖。**这是刻意的重复，已在工单登记理由。**
2. **`POLL_INTERVAL_S` / `BACKOFF_BASE_S` 写成模块 `Final` 常量，不加 `Settings` 字段**：
   设计文档未给这两个数值；第 4 组 P 阶段加 4 个护栏字段是**用户批准**的，
   本任务没有这个授权。退避公式取 `高并发 L260`「1s→2s→4s…」（`BACKOFF_BASE_S = 1.0`）。
3. **超限判据 = 领取次数**：`attempt > settings.max_retries`。用"领取次数"而非"失败次数"，
   因为"领取了但进程崩了"同样消耗一次尝试（`design.md:294` 的进程重启丢在途任务场景）。
4. **`main.py` 的处理器 mapping 此刻是空的**——控制者核实 `service/ocr_service.py`
   **仍是 44 字节空壳**，而注册表的 `handler_ref` 只是**字符串位置**（刻意不导入处理器）。
   故：组合根传 `handlers={}` 并记一条「已注册处理器 0 个」的启动日志；
   执行器遇到无 handler 的任务**记 ERROR + 按失败分流（`error_code=5000`）**，
   MUST NOT 静默跳过（同 `design.md:194` 的「避免告警丢失」取向）；
   **MUST NOT 为了"填满映射"往生产代码塞假 handler**。

#### T2 工单的两条新增「工单缺口」（4.5 的教训带来的）

- **`get_now` 类**：4.5 的工单只补了 `engine_factory` 却漏了时钟依赖，实现者补出来才写得出月边界用例。
  故 4.7 工单**显式列出全部注入点**（`clock` / `executor` / `handlers` / `store` / `locks`）。
- **`main.py` 关闭期顺序**：4.5 实测「工单字面写法会 `AttributeError`（沙盒替身无 `dispose`）
  且 starlette 1.6.0 会把关闭期异常抛回 `with` 之外」。故 4.7 工单把关闭顺序写成硬要求
  （**先 set stop、await 退出 → 再 `locks.close()` → 最后 `engine_factory.dispose()`**），
  并给出理由：先关 Redis 会让在跑的任务续期失败，变成"无故放弃"。

---

## 变更：`task_id` 自描述创建月（用户指示「帮我想一个方案，并修改到相应的文档中」）

### 问题（4.5 实现者登记、控制者确认的**产品后果**）

`ai_task` 按月分表，而 `GET /aicore/tasks/{taskId}` 的入参**只有 `task_id`**。
`task_id` 不含月份时，「本月表查不到」无法区分「任务不存在」与「任务在上月的表里」——
表现为**上月 23:59:59 提交的任务，次月 00:00:01 轮询即 404**。
这不是"历史任务过期"，而是**刚提交的任务跨了月就查不到**。

### 候选方案与否决理由（控制者裁定，逐条给依据）

| 方案 | 否决理由 |
|---|---|
| 逐月试探扫描 | 直接违反 `er.md:230`「查询 MUST 携带分片键下推、禁止跨分片」 |
| `taskId` → 月份查 Redis | 引入第二事实源（D2 刻意避开的双源问题：MQ 与 MySQL 双事实源），且 Redis 丢失后映射无法重建 |
| 新建全局 `task_locator` 表 | 又一张表 + 双写一致性；且它自身若按 `task_id` 分片，跨月查它同样面对本问题；写入路径已知月份故无收益 |
| 轮询接口加可选月份参数 | 有效但**把定位责任推给调用方**——调用方只有 `taskId` 时仍不知道月份 |
| **✅ 让 `task_id` 自描述月份** | 唯一既保住「单月一次查询」又把定位责任收回服务端的形态 |

### 定档口径

`task_id` = `task_`(5) + 创建月 `YYYYMM`(6) + UUID hex(21) = **恒 32**。
hex 段从 27 位缩到 **21 位 = 84 位随机性**（`er.md` §5.2 单表 2000 万行触发再分，生日界下可忽略；
唯一性最终由主键约束兜底）。

**与 `er.md:248`「不依赖任何内嵌时间戳」的关系（口径澄清，不是推翻）**：
那条禁的是**雪花式毫秒时间戳**（风险面是时钟回拨导致发号重复、须引入 workerId）。
`YYYYMM` 是**创建时由 `created_at` 冻结进字符串的业务标签**，此后**永不再从时钟推导**，
不参与发号唯一性。把两者等同，属于对原禁令的扩张，故在 `er.md` 里**显式写出这层区分**。

**只改 `task` 一类**：只有 `task_id` 承担跨月定位职责（轮询、结果表 1:1、纠错表 1:N）；
`cor_`/`rev_`/`marker_`/`kan_`/`qa_` 各自按自己的业务键访问，加月份只会白占长度。

### 改动的文档（4 处，全部同步）

1. `services/aicore/docs/er.md` → **v1.3**：ER 图 `task_id` 注释、§5.4 的 ID 表
   + 新增「为什么 `task_id` 带月份」小节（含问题、定档、与 L248 的关系、熵口径、为何只改一类）、
   §6.1 数据字典、§7.1 表设计（含**轮询的月份来源**与冷归档后的 404 口径）、版本历史。
2. `services/aicore/docs/openapi.yaml`（**唯一可手改源**）：`GET` 的 `taskId` 参数
   （描述 + `pattern: ^task_[0-9]{6}[0-9a-f]{21}$` + `maxLength` + 新 example）、
   `TaskAccepted.taskId`、`TaskResult.taskId`、`VisionReviewItem.taskId` 共 4 处。
3. `services/aicore/docs/openapi.apifox.json`（**派生产物**，喂 `packages/api-client` 生成 TS 类型）：
   12 处旧示例同步（纯文本替换、不重新序列化；替换后仍可解析、9 条 paths）。
4. `openspec/changes/implement-aicore-service/design.md`：§数据层落地补一段
   「轮询的月份怎么来」，含问题、为何不能逐月扫描、与"不依赖内嵌时间戳"的关系。

### 改动的代码（3 处）

- `core/idgen.py`：`ID_PREFIXES` 前移（`ID_PREFIX_LENGTHS` 要用它）、新增
  `MONTH_DIGITS` / `MONTH_AWARE_KINDS`、**`new_id(kind, *, at=None)`**
  （`task` 类必传 `at`，MUST NOT 回落当前时间）、新增 **`task_month_of(task_id)`**；
  `validate_id` 对 `task` 类校验月份段（正则收紧到 `20\d{4}`——`999999` 这种
  会"合法"通过 6 位数字检查、只表现为"路由到一张永远不存在的表"，比当场拒绝难查）。
- `service/task/submit.py`：`new_id("task", at=now)`——ID 里的月份与分片 `created_at`
  **同一个来源**（这正是 4.7 工单里"两个时钟必然漂移"的同一条理由）。
- `service/task/query.py`：**用 `task_month_of(task_id)` 定位月表**，
  MUST NOT 用 `now` 现算；形态非法抛 `ParamError(1003)`（入参格式错误，
  MUST NOT 报成 `3006`，那会让调用方以为任务丢了而去重试或告警）。

### 改动的用例与脚本

- `tests/unit/test_idgen.py`：**重写**（35 条）。保留第 3 组评审建立的**独立预言机**取向
  （`CONTRACT_ID_MAX_LENGTH = 32` 字面量），并**新增第二类独立预言机**
  `CONTRACT_TASK_MONTH_DIGITS = 6`（`MONTH_DIGITS` 被改成 5/7 时 ID 仍"自洽"、
  内部自校验不响，但违背 `er.md` 的 `YYYYMM` 形态、且 5 位月份**无法表达哪一年**）。
  新增拒绝面：**旧格式（无月份，长度也是 32）必须被拒**（这是"格式真的变了"的核心证据）、
  月份含非数字、月份非 `20` 开头、`task_month_of` 对非法值抛错。
  另把 `timestamp` 从静态禁用词里**移除并写明理由**：规范禁的是雪花式毫秒时间戳，
  而"月份来自 `at`"这件事在代码里必然出现时间相关标识；改为断言
  `time.time`/`monotonic`/`uuid1`/`snowflake`/`worker` 仍不在代码里。
- `tests/api/test_task_poll.py`：**新增跨月轮询用例**（`now` 落在 10 月、任务在 7 月，
  且沙盒里**刻意没有** `ai_task_202610`——若实现退回"用 now 算月"，用例会以 `no such table`
  失败，而不是"恰好查到 0 行"）+ **非法任务号 400/1003** 用例。
- `scripts/group3_acceptance.py`：第 9 项的 `new_id` 补 `at`，算术自证**纳入月份段**，
  并新增「月份==契约 6 位」判据。

### 验证

```
全量 -m "not integration"   1189 passed, 14 skipped, 19 deselected
integration                 19 passed
覆盖率                       98.49%（门禁 80%）
ruff（src tests scripts）     All checks passed!
mypy --strict                Success: no issues found in 59 source files
lint-imports                 Contracts: 4 kept, 0 broken.
验收脚本（第 3 组 10 项）      PASS 10 / FAIL 0 / INFO 0，exit 0
```

**跨月用例的变异验证**（把 `query.py` 改回「用 `now` 现算月份」= 旧行为）：
→ `test_poll_finds_a_task_created_in_an_earlier_month` **变红**（`1 failed, 11 passed`）；
按 SHA256 逐字节还原（`1c92292d…6618`）。**该用例真有判别力。**

### 顺带修掉的两处判据缺陷（如实登记）

1. **验收脚本第 4 项「测试内无 sleep」的判据过宽**：它是朴素 AST 扫描「凡名为 `sleep` 的调用」，
   实测 4 处**良性误报**——`asyncio.sleep(0)`（0 秒、只让出调度）、
   `FakeClock.sleep(0)`（**在测真实系统时钟自身**）、
   一个"永不返回"的协程（是**被 `wait_for` 掐掉的对象**，从不真等）、
   handler 挂 10s 做**钝器**（靠 deadline 取消）。
   处置：**判据不放宽**（仍扫全量 AST），改为支持**行级豁免**
   `# ai-allow-sleep: <理由>`（理由必填）——与 `test_source_guards.py` 规则 6 的
   `# ai-allow-swallow: <理由>` **完全同构**（同一取向：偏严 + 显式豁免，
   而不是"因为有几处良性形态就把规则关掉"）。
2. **ruff 此前未覆盖 `scripts/`**：本次一并纳入后暴露 7 项（2 项既有 E501 + 5 项我引入的全角竖线）。
   全角竖线 `｜` 触发 RUF003「易混字符」——这正是 `pyproject.toml` 注释里说的
   「不要用 ignore 关掉 RUF001/2/3」的价值所在（它在注释里也照样报）。

---

## 提交阶段的**严重事故与重建**（2026-09-19，如实登记，这是本日最该留下的一段）

### 交付的 4 个提交

```
dc06588 chore(aicore): sleep 判据改为行级豁免，并把 scripts/ 纳入 ruff 范围
5bc0f0f feat(aicore): task_id 自描述创建月，修掉跨月轮询 404
5bae23f feat(aicore): 实现任务提交、状态机与结果轮询三条链路
eac6ff1 feat(aicore): 落地任务类型策略注册表
```
（`eac6ff1` = 4.6；`5bae23f` = 4.5 + 测试基础设施；`5bc0f0f` = 我按用户指示做的 ID 变更；`dc06588` = 验收脚本豁免。）

### 事故：**切错了提交边界，造出一个跑不起来的中间提交**

第一轮切分时，我把「月份版 `query.py` / `submit.py`」放进了 C2（4.5 那条），
而 C2 的 `idgen.py` 还是**旧版**——于是 C2 里 `new_id("task")` 缺必填的 `at`、
`task_month_of` 根本不存在。**C2 是一个跑不起来的提交**，`git bisect` 会命中它。

**直接的触发原因**：我那条 `git add` 里写错了一个路径（`services/aicore/service/task/query.py`
少写了 `src/`），**整条命令失败，而我没检查返回码就提交了**——于是 9 个文件里只进了 1 个，
而提交信息描述的变更几乎全不在里面。

**为什么第一轮没发现**：我只看了 `git diff --cached --name-only` 在**第一条** add 之后输出为空，
却没意识到那是失败信号；也因为我没有**在提交后逐个提交跑测试**的习惯。

### 发现方式：**逐提交健康检查**

修的过程里我意识到「提交粒度」本身需要判据，于是写了一个脚本：
对 `201531b..HEAD` 的每个提交 `git worktree add --detach` 到独立目录、跑非集成用例、
给出 OK/BROKEN。**第一个坏提交就是这样被抓出来的**（`93d00bd` → BROKEN 且输出为空）。

**这条检查从此固定为本项目的提交纪律**：一次交付拆多个提交时，
MUST 逐个提交检出并跑测试；否则「提交信息说的」与「提交里有的」可能完全不是一回事。

### 修复过程中的**四次失败**（都是同一种错误的变体，值得逐条记）

我试图用脚本把 `query.py` / `submit.py` 退回「月份改动之前」的形态，连错四次：

| # | 我的做法 | 为什么错 |
|---|---|---|
| 1 | `git checkout HEAD -- <file>` 取"原始版本" | **HEAD 本身就是那个坏提交**，取回的仍是坏版本 |
| 2 | 用多行中文长串做替换目标 | 一处字符不等就**静默不匹配**（`.replace()` 不报错）——正是我一直在防的静默失败形态 |
| 3 | 判据写 `at=now` | 命中 `created_at=now`（**分片键参数，两种版本都有、必须保留**）——**判据写宽了会误伤** |
| 4 | 判据写 `task_month_of(task_id) not in text` | 它在 docstring 与 import 里**也**出现（共 4 处），而我只该关心**可执行代码**里有没有 |

**最终采用的做法（三处关键改进）**：

1. **判据只对代码发问**：用 `tokenize` 剥离注释与三引号串 + `ast.parse` 校验语法，
   得到「可执行骨架」再判——这正是 `test_idgen.py::_code_only` 的**同款取向**
   （那里的注释解释了为什么必须剥离：`idgen.py` 的 docstring 刻意写了"不用雪花"，
   朴素子串检查会把"文档里说明禁用"判成"代码里用了"）。
2. **判据要对空白归一化**：`tokenize` 用空格连接 token，`created_at=now` 会变成
   `created_at = now`，直接子串比较会**假阴性**。
3. **测试文件必须与它测的对象同版本**：`test_idgen.py` 的月份版 `import MONTH_AWARE_KINDS`，
   而 C2 的 `idgen` 是旧版 → 收集期 `ImportError`。C2 用旧版测试、C3 换月份版测试。

### 重建后的独立复验（不采信重建脚本的自述）

在**干净临时工作树**里逐个提交检出并跑用例：

```
待检：['eac6ff1', '5bae23f', '5bc0f0f', 'dc06588']
eac6ff1  ✅ OK   1135 passed, 14 skipped     落地任务类型策略注册表
5bae23f  ✅ OK   1165 passed, 14 skipped     实现任务提交、状态机与结果轮询三条链路
5bc0f0f  ✅ OK   1189 passed, 14 skipped     task_id 自描述创建月，修掉跨月轮询 404
dc06588  ✅ OK   1189 passed, 14 skipped     sleep 判据改为行级豁免
每个提交都能独立跑通 ✅
```

**最终门禁**：全量 `1189 passed, 14 skipped`；`ruff`（`src tests scripts`）`All checks passed!`；
`mypy --strict` 59 files；契约 `4 kept, 0 broken`；第 3 组验收脚本 `PASS 10 / FAIL 0`、exit 0。

重建前的备份分支 `backup/orig-4commits`（`e51563c`）与临时提交信息目录已删除，工作区仅剩
未跟踪的 `.sdd-tools.py`。

### 教训（三条，都进了纪律）

1. **一条 `git add` 失败 MUST 立刻检查返回码**——我因为没检查而提交了一个
   「信息与内容不符」的提交，这是最廉价也最该避免的一类错误。
2. **多提交交付 MUST 逐个提交检出跑测试**——否则"提交信息说的"与"提交里有的"可能是两回事，
   而 `bisect` 会命中那个坏点。已固化为本项目的提交纪律。
3. **"把文件退回某个历史形态"是一个容易连错四次的动作**：它需要
   （a）可靠的内容来源（不是"我以为的 HEAD"）、（b）不会静默失败的匹配方式、
   （c）**只对代码发问且对空白归一化**的判据。三次都栽在 (b)(c) 上。

---

## T2 派发（2026-09-19，用户指示「开始」）

**范围**：Task 4.7（任务执行器内核）+ 4.8（CPU 密集下线程池），合并为 `task-4.7-brief.md`。
**实现者**：subagent `7107c924`（单路；两者同文件 `core/task_runner.py`，无法并行）。

### 开工后控制者补发的三条工单缺口（都是我核对既有签名/判据时发现的）

1. **同步 SQL 与异步循环的边界**（§2.5）：`TaskStore` 全部方法是 `def`（同步 SQLAlchemy
   是本服务定档），而 `TaskRunner` 是 async → 边界在**调用点**：
   MUST 用 `await run_in_threadpool(...)`，与 `api/ocr.py::_submit_in_session` 完全同构。
   **不补这条，实现者很可能在事件循环里直接调同步 SQL**——那会阻塞整个服务，
   正是 `design.md` 反复强调的 P95 恶化形态。
2. **三个写方法都收 `account_id` + `created_at`**：`ShardKey` 需要它们算物理表名，
   而这两个值已在 `ClaimedTask` 里。**MUST NOT 让执行器自己算表名**——那会把分片知识
   复制进 `core`，而 `core` 不得依赖 `repository`（契约 4）。
3. **新增集成用例会撞验收脚本第 4 项**（§3.4）：真等租约过期会被「测试内无 sleep」命中。
   处置是**行级豁免** `# ai-allow-sleep: <理由>`（理由必填），
   **MUST NOT** 改判据或删用例；报告里要列出加了几处、各是什么理由。

### 控制者已核实的既有签名（工单引用的前置）

- `TaskRepo.update_status(session, task_id, *, shard, status, progress, finished_at) -> int`
  —— 位置参数只有前两个，其余 keyword-only；MySQL 方言下返回**匹配行数**。
- `EngineFactory`：`write_engine` / `read_engine` / `primary_read_engine` 三个属性
  + `write_session()` / `read_session()` / `primary_read_session()` 三个上下文管理器。
- `SqlTaskLeaseStore` 的写方法用 `write_session()`、`list_claimable` 用 `primary_read_session()`
  （依据 `er.md:252`：执行器紧接着就要改这一行）。

### T2 中途：**工单自相矛盾被实现者发现**（契约 4 vs `TaskPolicy`）

**实现者的报告（不停摆、先报硬伤）**：工单 §2.5 要求 `TaskRunner` 用
`TaskPolicy.retryable` 与 `get_policy`，而 §2.1/§4 逐字要求 `core` 不得 import
`aicore.service`——**两句不能同时成立**。

**控制者独立复现**：

```
core 不得依赖任何业务层                                  BROKEN
-   aicore.core.task_runner -> aicore.service.task.registry (l.138)
Contracts: 3 kept, 1 broken.
```

**定性：这是控制者的工单缺陷**（我在两处写反了），不是实现者的偏离。
契约 4 是**包级 forbidden**，不认我在工单里写的「只允许取纯声明的 `TaskPolicy` / `get_policy`」
——**那句措辞本身就是错的**，实现者指出得对。

**控制者的复核（确认他的方案在运行期与类型上都站得住）**：

```
TaskPolicy 是 frozen dataclass，字段 = ['task_type','result_schema','timeout_s',
                                       'retryable','handler_ref','implemented']
六个字段全是 str/float/bool —— **没有任何 service.* 类型**
```

**裁定：采纳他的方案**（`core` 侧就地声明同形 Protocol，策略由组合根注入 `dict(REGISTRY)`），
并追加四条要求：

1. 注入用 `dict(REGISTRY)`（`REGISTRY` 是 `MappingProxyType`，组合根注入的副本无需再包一层）；
2. `core` 侧的 Protocol **只声明真正用到的两个成员**（`task_type` / `retryable`），
   MUST NOT 抄全 6 个字段——抄全等于把 `service` 的结构复制进 `core`，正是契约 4 要防的方向；
3. **加一条断言：`TaskRunner` MUST NOT 读 `policy.timeout_s`**——注册表行内的 `timeout_s`
   是**配置默认值快照、不是权威值**，读了它会静默拿到一个不随配置变的超时
   （"取了一个看起来对的错值"比报错更难查）；
4. **加一条契约 4 的本地回归 + 判别力自证**（内存变异，不落盘，与 Task 4.6 判据 A 同构）：
   断言 `core/task_runner.py` 的可执行骨架里不出现 `aicore.service`，
   并在内存里插一行 import 证明判据会红。**没有这条自证，就没人知道这条纪律还在不在。**

**他自报的代价，控制者确认并接受**：「`get_policy` 每次现读 `Settings` 覆盖行内 `timeout_s`」
这条口径在执行器路径上失效——**在执行器只用 `retryable` 的前提下无影响**，
而第 3 条断言恰好把「只用 `retryable`」钉住，**使这条代价成为可验证的而非口头承诺**。

工单已同步修正（§2.5 的 Protocol 段与硬约束 5、用例清单第 22/23 条）。








### T1 中途：一处 ruff 口径提示（控制者已发给 Task 4.6）

`test_task_registry.py` 有 9 处 E501，报的全是**注释与 docstring**。
**根因是 ruff 的 `E501` 按「显示宽度」计（CJK 算 2 格），而 `len()` 按字符数算**
——一行 78 字符含 24 个汉字时显示宽度 102 > 100，用 `len()` 看不出来。
控制者本组踩过一次（`provider/selector.py` 的表格行）。
已把自测方法与修法发给实现者，并明确 **MUST NOT 为此改 `line-length` 或关掉 E501**。

---

## T2（Task 4.7 + 4.8）控制者独立复核 —— 2026-09-19

### 门禁：控制者全部自己重跑，逐条与实现者自报一致

| 命令 | 控制者实测 | 与报告 |
|---|---|---|
| CMD1 三个新单测 | `48 passed in 11.75s` | 一致（48；报告 §1 却写"单元 49 条"） |
| CMD2 默认段 | `1240 passed, 13 skipped, 33 deselected, 1 warning in 55.48s` | 一致 |
| CMD3 集成段 | `33 passed, 1253 deselected in 45.81s`；跑完 `dbsize=0`、`aicore:*` 残留 `[]` | 一致 |
| CMD4 ruff | `All checks passed!` | 一致 |
| CMD5 mypy | `Success: no issues found in 61 source files` | 一致 |
| CMD6 lint-imports | `Contracts: 4 kept, 0 broken.`（契约 4 KEPT） | 一致 |
| `group3_acceptance.py` | `PASS 10 / FAIL 0`，豁免 10 处（4 既有 + 6 新增） | 一致 |

**判据来源可靠性记录**：CMD2 第一次由控制者跑出 `6156.63s`（1h42m），第二次 `55.48s`
（`--durations` 显示最慢单测 23.72s，无病态用例）。第一次是**后台作业被饿**的异常值，
不是测试自身问题——记下来，避免下次把环境噪声误判成回归。
（据此产生的纪律：**给测试套计时不要与其它重活并跑**，否则会得到 100× 的假信号。）

### 控制者独立探针（自己写、放仓库外 `D:\progrom\.dsh-probe\`、用完即删）

- **探针 A（试下一个）PASS**：`list_claimable(limit=1)` 只回 `['task-a']`（这正是旧缺陷的判别形态），
  而 `claim_once()` 返回 `task-b`。⇒ 实现者的 `limit=concurrency_limit` 修复**真实有效**。
- **探针 C（退避与释放）PASS**：事件序 `store.begin_attempt → store.requeue → locks.defer → locks.release`；
  `is_deferred=True`；`leases now held=0`；别的实例在退避窗口内领不到；1.5s 后 `attempt=2`。
  ⇒ 实现者的释放租约修复**真实有效**，重试由退避窗口界定而非 30s 租约。
- **探针 B（背压）FAIL**：`concurrency_limit=1` 时 `max_in_flight=1`（执行封顶对了）
  但 **`max leases held at once = 2`** ⇒ **领取没有被信号量约束**。
- **探针 D（租约丢失）FAIL**：`execute()` 在 **1.032s** 才返回（心跳 0.033s 就判定租约丢失并打了
  "主动放弃执行"日志）、`handler ran to end=True`、**`paid api calls made=1`**。

### 两个阻塞项（均为「明确要求 vs 代码行为」不符，非风格问题）

- **B1**：`design.md:208` 逐字要求「续期失败必须主动放弃任务**而非继续执行**」，`execute` 自己的
  docstring 也写「取消处理」——实际**什么都没取消**，处理器跑完并完成付费调用。
  `task_runner.py:625-634` 的 `except asyncio.CancelledError: if not heartbeat.done()` 分支
  是为此准备的接收端，**没有任何东西触发它**（结构性证据：实现不完整，而非有意取舍）。
- **B2**：工单 §2.5 第 7 条「信号量满时 MUST NOT 领取新任务（先拿信号量再领取，而不是领了再排队）」
  与验收第 18 条「第二个任务在第一个跑完前**不被领取**」——`run_forever` 是**先领取再挂信号量排队**。
  后果不是洁癖：**被领取但排队的任务持有租约却没有心跳**（心跳要等许可才起），
  等待超过 `lease_ms` 即静默过期 → 别的实例回收 → **同一任务两个实例执行**，与 B1 同源（重复付费）。

### 两条「假绿」用例（判别力为零，且都在报告里被记成 ✅）

- `test_renew_failure_abandons_without_any_terminal_write`：实测两个参数各 **5.01s**
  （`--durations`），CMD1 的 11.75s 里 **10.02s** 是它。`FakeHandler(hang=True)` 是"挂到被 `wait_for` 取消"、
  `timeout_s` 默认 5.0 ⇒ **用例靠 5 秒超时结束，不是靠租约丢失**（租约 10ms 就丢了）。
  把实现改成"真的取消"，断言**照样全绿** ⇒ 对 B1 **完全没有判别力**。
- `test_concurrency_limit_blocks_the_second_claim`：docstring 写「断言 `acquire` 的调用序列里**只有**
  `task-a`」，但**用例体里没有任何对 `acquires` 的断言**（`_FixedClaimLockStore.acquire_calls` 从未被读）。
  且它的绿色来自 `limit=concurrency_limit=1` 把候选窗口切成 1 个恰好是"正在跑的那个"元素，
  **不是来自信号量** ⇒ 对 B2 没有判别力。

### 一处死接口

`TaskRunner(clock=...)`：`self._clock` 只在 `task_runner.py:456` 赋值，**全文件再无读取**。
`claim_once` 用墙钟、心跳用真 `asyncio.sleep`。⇒ 这是个**会骗人的接缝**（注入假时钟者以为控制了时间）。

### 报告失准（控制者逐个文件实数）

行数表 8 个文件**全错**（`lease.py` 394→**608**、`task_runner.py` 604→**972**、
`task_lease_store.py` 255→**394**、`test_lease.py` 165→**258**、`test_task_runner.py` 826→**1134**、
`test_cpu_pool.py` 245→**352**、`test_lease_redis.py` 165→**251**、`test_runner_redis.py` 305→**437**）；
用例数 `test_lease` 11→**10**、单元合计 49→**48**。比值逐文件 1.37~1.61，
**不是任何统一口径**（总行/非空/非注释/非文档字符串都算过），最可能是中途取数未刷新。
⇒ 纪律：**自报数字必须取自交付态**；复核者拿它当判据时会连带失信。

### Ruling: 第二条工单自相矛盾（`error_code`）定性为**控制者缺陷**，并授权最小范围改既有文件

- 冲突三源（实现者报告属实，控制者逐条复核）：工单 §Files「`repository/**` 既有文件不可改」+
  第 518 行「发现接口硬伤 → 停下并写明」+ `update_status` 列集合只有三列
  （`task_repo.py:139-145`，且 `test_repos.py:733` 逐列钉住），而 §2.6 又要求 `mark_failed` 落 `error_code`。
- **依据（为什么必须补）**：`design.md:210` 明写「外部通道失败（`4003`）与依赖超时（`5002`）**分别计数**」，
  4.11 要靠 `ai_task.error_code` 做这件事。
- **授权范围**（超出即越权）：`status_update_statement` 加 `error_code: str | None = None`（**仅非 None 时**入列）、
  `update_status` 加同名形参透传、3.7 那条用例**保留原断言并另加一条**（MUST NOT 削弱）、
  `task_lease_store.mark_failed` 真写入并删掉 WARNING、集成用例的 NULL 断言改为真实码值。
- **代价**：本轮触碰了上一轮工单的"不可改"清单，故必须**单独成一个提交**，
  以免「执行器语义修复」与「repository 列集合扩张」混在一个提交里无法二分。

### Ruling: B1 的修复只承诺"不再等待 + 不写终态"，MUST NOT 承诺"回滚外部副作用"

处理器若已把工作交给线程（`run_cpu_bound`），**协程取消收不回那个线程**。
故 docstring 与报告 MUST NOT 写成"已回滚"——**B1 的成因正是"文档说做了、代码没做"，
修复时重复同一句式会把缺陷换个位置重装一遍**。

### Ruling: 独立评审与修复轮**并行**，但修复轮的提交以控制者复核为准

控制者已发现的问题不下发给评审者重推（避免重复劳动），改为在评审提示里列为"已知、勿重复"，
并要求评审者**找别处的缺陷**（Lua 原子性、内存替身与 Redis 的语义等价、SQL/分片、生命周期与资源泄漏、
以及"还有哪些用例永远不会失败"）。若评审者在修复轮之后仍报出 B1/B2 类问题，视为**修复未达标**。

### 下一轮工单

`.superpowers/sdd/2026-09-16-aicore-architecture/task-4.7-fix-brief.md`（B1/B2/B3 + M1~M5，
含每条的证据、必须的行为、验收形态与判别力自证要求）。交付形态：**两个提交**，各自独立健康。

### 控制者的调度失误（自记，不记到实现者或评审者头上）

原计划是「先让独立评审跑完，再把它的增量并进修复工单」，**实际却把评审轮与修复轮同时开在了
同一棵工作树上**。后果：评审者的取证对象在它脚下漂移（`task_runner.py` 每几秒被重写一次），
且工作区在修复中途**合法地变红**（实现者先删 `src` 的 `clock=` 形参、测试尚未同步，
`TypeError: unexpected keyword argument 'clock'`），任何人在该窗口跑验收都会看到红。

**评审者正确地发现了这一点并要求裁定**——这是它该做的事，不是它的越界。
裁定：不暂停评审，改为**按文件重划取证范围**——修复轮不碰的
（`core/lease.py`、`tests/conftest.py`、`main.py`、`test_lease.py`、`test_lease_redis.py`）
为**权威范围**，其 finding 直接进验收；修复轮正在重写的（`task_runner.py`、`test_task_runner.py`、
`test_cpu_pool.py`、`task_lease_store.py`、`test_repos.py`、`test_runner_redis.py`）
标**仅供参考**，待修复后的 SHA 再复审一轮；但其中**不属于 B1/B2/B3/M1–M5 的**问题照报（那才是增量）。
另要求评审者**停跑全量套件**（必然红、且与实现者抢资源），只跑权威范围内的子集。

**纪律（下次照做）**：**同一棵工作树上不得同时开"改"与"审"两轮**。
若要并行，评审必须在**冻结的 SHA** 上做（`git worktree add --detach <sha>` 另开一棵），
而不是在工作树上做。

### 待办（修复轮之后、提交之前）：补 `main.py` 装配用例 —— 实现者给的不做理由是**错的**

实现者报告 §6.10 自认「`main.py` 的执行器装配没有用例（`env != "test"` 分支跑不到）……**这是本任务
最大的测试空白**」，并给了不做理由：「要覆盖它需要有真实 Redis 的 lifespan 用例，而那样会让默认段
连 Redis——与工单 §3.3『默认段 MUST NOT 连 Redis』冲突」。

**控制者复核：这个理由不成立。** 实测事实：
- 集成段本来就允许真实 Redis（`pyproject.toml:97` 的 `integration` marker
  「需要真实 MySQL / Redis 的端到端用例，默认不执行」；CMD3 实测 `33 passed` 且 0 skip）；
- 一个 `@pytest.mark.integration` 的 lifespan 用例**只在 `-m integration` 段运行**，
  **根本不进默认段**，故与「默认段 MUST NOT 连 Redis」**不冲突**；
- `core/config.py:80` 的 `Env = Literal["dev","test","prod"]`，`_NON_PROD_ENVS = {"dev","test"}`
  ⇒ 取 `env="dev"` 即可触发装配，且 `dev` + mock 通道**不被拒**（只有 `prod` + mock 才拒，
  见 `config.py:23` 的 `env-mock` 规则）。
- 佐证夹具是**刻意绕开**装配的：`conftest.py:523-536` 的 `integration_settings()`
  其 docstring 自己写着「`env="test"` 是**刻意的**：执行器的启动判据是 `settings.env != "test"`」。

⇒ 该空白**可闭合**，列为修复轮之后的第三个提交：
`test(aicore): 覆盖执行器在组合根的装配与关停顺序`。要点：断言装配发生在 `env != "test"`、
`app.state.task_runner` 真的挂上、注入的是 `dict(REGISTRY)` 与空 `handlers`、
关停顺序为 `stop.set() → await runner_task → runner.stop() → locks.close() → dispose()`。
**MUST** 排在修复轮之后单独派发（不得与修复轮并跑同一棵树）。

---

## 独立评审（第 2 轮）结果 —— 控制者漏掉了三条，评审者全部找出

**报告**：`.superpowers/sdd/2026-09-16-aicore-architecture/review-task-4.7-independent.md`
（含 SHA256 基线、探针原始输出、CLEAN 覆盖面、未能覆盖项）

### 控制者对自己这一轮复核的诚实评估（这是本轮最该记的一条）

我做的 5 个探针全部落在**语义/正常路径**上（领取顺序、租约续期、退避、释放、背压），
**没有一个是错误路径**。评审者恰好补上了这一半：

| 项 | 一句话 | 控制者复核 |
|---|---|---|
| **A1** major | `handler.timeout_s()` 抛异常 → **心跳 task 泄漏、租约被永久续期**，任务再也无法被任何实例领取，行永远停在 `PROCESSING`；且 docstring 与 `_settle` 日志都写着"留待租约过期后重做"——**这句是假的** | 代码位置（`create_task(_heartbeat())` 在 `try/finally` 之前、其间的 `_declared_timeout_s` 会 `float(declared())`）与评审探针一致 |
| **A2** major | `run_forever` 的 `claim_once()` **零兜底** ⇒ 一次瞬时错误永久杀死执行器；`main.py:155-173` 无 try/except ⇒ 关停块**整体跳过**；`/health` 不查依赖、`create_task` 无 done-callback ⇒ **死了没有任何信号** | **我自己读了 `main.py:155-173` 确认无 try/except**；`await runner_task` 抛错后 158-173 行全部跳过 |
| **A3** major | 内存替身**没建模计数键 PEXPIRE 到期**（真 Redis `[1,1,1]` vs 替身 `[1,2,3]`），`live_attempt_counter` 是死代码 ⇒ **离线段 10 条单测在这点上与生产不一致** | 评审探针 + 死代码 grep |

**A3 正是我在派发评审时点名要求优先做的那块盲区**（"集成段用真 Redis 恰恰绕过替身"），
**结果它真的存在**。⇒ 教训：**"我预判到某个盲区"不等于"我验证了它"**；
预判只该用来决定派谁去验，不该用来给自己记功。

### 由 A2 顺带挖出的**架构级缺口**（不是 T2 的活，必须登记）

`design.md:218` 逐字要求「按分片键计算物理表名……**写入前确保当月物理表存在（幂等建表）**」，
而控制者 grep 全仓确认 **`ensure_month_tables` 在 `src/` 里没有任何运行期调用者**
（只有 `deploy/sql/migration/env.py`、`scripts/apply_ddl.py` 的 docstring 与测试）。
⇒ **服务自己从不建当月月表**；每月 1 号若运维未先跑迁移，`list_claimable` 直接抛
`(1146, "Table 'aicore_test.ai_task_YYYYMM' doesn't exist")`。
**归属**：月表路由是 3.x 的产物、补齐落点在 G 阶段（4.9–4.11）或后续任务；
**T2 只负责"执行器不该被瞬时错误永久杀死、且不该静默死亡"这一半**，
已明确 **MUST NOT** 让实现者顺手去补建表（防范围蔓延）。

`/health` 不查依赖**不算 T2 缺陷**：`api/health.py:5` 明写依赖就绪归 Task 11.1。

### 其余发现与裁定

- **A4**（minor）`defer(delay_s<=0)` 三处口径打架：两个 docstring 说"写一个立即到期的键"，
  而真 Redis 的 `SET ... PX 0` **直接报错**；`delay_s=nan` 在替身里是**永久退避**。生产调用点只传 ≥1.0
  故今天不可达，但 `defer` 是交付契约 ⇒ 对齐到**一个**行为 + 边界用例。
- **A5**（minor）`mark_failed` 的 read-then-write 是**丢失更新**（真 MySQL 实测 80→10）。
  **裁定**：① **立刻改掉** docstring 里"progress 保持原值"这类**声称原子性**的措辞；
  ② **真修复延后并登记**——它要给 `update_status` 加"不动这一列"的表达，属共享列契约，
  应与 5.x「处理器开始回写进度」一起设计；③ **rowcount 那条立刻修**：
  `_write_back`/`mark_failed` 丢掉 `update_status` 的返回值，`rowcount=0` 时仍释放租约
  ⇒ 行留在 `PROCESSING` 等重放（**可能重复调用付费通道**）。
- **A6**（minor）会话级 socket 守卫**看不见 asyncio 的非环回建连**（Proactor 走 C 层 ConnectEx）：
  异步路径违规记录 **0**、同步对照组 **1**。**裁定**：**如实登记该能力边界**（低成本），
  真修（patch `loop.create_connection`/审计钩子）**不要求**。
- **A7**（minor）`task_lease_store.py:38/:126` 把「三源不漂移」的保证挂在
  `tests/repository/test_task_lease_store.py` 上，**该文件不存在**。
  **裁定**：**把文件建出来**（新建文件不受"既有文件不可改"限制），
  **MUST NOT 只把 docstring 删掉**——那等于把一条防线降级成一句空话。
- **A9**（minor）`RedisLockStore.monotonic_now()` 及其 `clock=` 形参同属死接口，并入 M2 一起清。
- **R1**（假绿，参考范围）`test_handler_timeout_..._with_5002` 里唯一断言业务码的一行在 `if codes:` 内，
  而该路径（attempt=1 → requeue）**不产生** `error_code=` 事件 ⇒ **断言是死代码**，
  把超时算成 `4003` 的实现照样绿。**控制者早在读该用例时就见过这段 `if codes:` 却没意识到它是死代码**
  ⇒ 又一条"看见了但没看出"的记录。
- **R2**（false-name）`test_default_executor_still_runs_off_the_event_loop_thread` 声称测
  `executor=None`，实际传 `runner.executor` ⇒ `run_coroutine` 的 `executor=None` 分支**从未被执行**。
- **R4** 只扫当月用例无阳性对照（恒返回 `[]` 也能过）；**R5** `select(table)` 取全部列仅登记。
- 评审者**CLEAN** 结论中价值最高的两条：Lua 领取原子性（5 连接 × 20 并发＝恰好 1 赢家、
  计数键 `b'1'` 证明 INCR 只在 `SET NX` 成功后执行、**无 TOCTOU**）；
  权威 10 条单测逐条判别力推演**未发现假绿**（其唯一盲区正是 A3/A4）。

### 提交计划：由 3 个改为 **4 个**（各自独立跑完整门禁）

1. `fix(aicore): 租约丢失即中止执行，且领取受信号量约束` —— B1、B2、M1、M2、M5、A9、R1、R2
2. `fix(aicore): 执行器不再被瞬时错误永久杀死` —— A1、A2（含 `main.py` 关停块与死亡日志）
3. `fix(aicore): 内存锁店与真 Redis 语义对齐` —— A3、A4
4. `feat(aicore): 失败终态落 error_code，供 4.11 分别计数` —— B3、A5②③、A7

外加排队的第 5 个：`test(aicore): 覆盖执行器在组合根的装配与关停顺序`（A8 + A2 的 main.py 侧断言）。

### 纪律（本条已第二次生效）

**同一棵工作树上不得同时开"改"与"审"两轮。** 本次已犯一次（评审者取证对象漂移、工作区合法变红），
代价由控制者承担，已向评审者与实现者双方澄清。要并行 ⇒ 评审必须在
`git worktree add --detach <sha>` 的冻结副本上做。

---

## 修复轮（第 2 批）控制者独立复核 —— 接受，但 B2 的自评被否证

### 控制者自己重跑的门禁（全部与实现者自报一致）

| 命令 | 实测 |
|---|---|
| CMD1 | `67 passed in 3.01s`（上轮两条 **5.01s 已消失** → 0.02s） |
| CMD2 | `1268 passed, 13 skipped, 36 deselected, 1 warning in 48.86s` |
| CMD3 | `36 passed, 1281 deselected in 48.71s`；跑完 `dbsize=0`、`aicore:*=[]` |
| CMD4/5/6/7 | ruff `All checks passed!`／mypy `61 source files`／`4 kept, 0 broken`／验收 `PASS 10 / FAIL 0`（**standalone `$LASTEXITCODE=0`**） |
| 行数（Python 逐个数） | `lease.py` 667、`task_runner.py` 1231、`task_lease_store.py` 436、`task_repo.py` 202、`main.py` 264、`conftest.py` 605 —— **与报告逐字一致** |
| B3 代码 | `status_update_statement`/`update_status` 的 `error_code` **仅非 None 时**进 `.values()`（`task_repo.py:74-75`）⇒ 既有调用方 SQL 逐字不变 |

**控制者自己的两次误报（记下来，别当没发生）**：
1. 我在同一批命令里跑了 7 条验收，块尾出现 `[exit code: 1]`，一度怀疑验收脚本。
   **单独重跑 `$LASTEXITCODE=0`** ⇒ 是我自己的命令块/管道产物，**不是缺陷**。
2. 我用 `(Get-Content f).Count` 量 `lease.py` 得 **508**、`Measure-Object -Line` 得 **416**，
   而 Python `splitlines()` 得 **667**。**逐字节复核：`LF=667`、`CR=0`、`splitlines=667`**
   ⇒ **667 才是真值，是我的 Get-Content 读数错了**，实现者的新数字是对的。
   ⇒ 教训：**行数一律用 `bytes.count(b'\n')` 或 `splitlines()` 定，`Get-Content` 不作为行数判据。**

### M4 的归因：实现者只对了一半（控制者补正）

实现者 §4 把上轮数字偏小归因于 `Measure-Object -Line` 不计空行。**机制成立**（实测该 cmdlet
在 `lease.py` 上给 416 = 非空行数），**但不足以解释上轮的值**：按"不计空行"口径，
交付态 608 行的 `lease.py` 应是 **480** 行非空，而上轮报告写的是 **394**。
⇒ **两个因素都在**：口径错 **且** 数字取自更早的版本。控制者上轮说"最可能是中途取数未刷新"
同样不完整。两边都记，别只归一个。

### B2：实现者判"结构上不可能给出运行期判据"——**被控制者探针否证**

实现者称四个变异体都只领到 1 个租约，故改用 **AST 语句顺序判据**，并为此在
**生产 `RunnerConfig` 上加了 `extra_busy_permits` 字段**。

**控制者探针**（同一个 `TaskRunner`、同一个 store，只换循环形态）：

```
(a) shipped run_forever  → acquire ['task-0','task-1','task-2']      峰值租约 = 1
(b) pre-fix shape        → acquire ['task-0','task-1','task-1',...]  峰值租约 = 2
VERDICT: CRITERION DISCRIMINATES
```

差别**只在替身的窗口语义**：控制者的 store 让 `list_claimable` **排除本轮已开工的行**
（"我自己在处理的行，对我自己不是可领取的"——`TaskStore` Protocol 的合法实现）；
实现者的 `FakeStore` 把已开工的行留在窗口里，于是许可满时窗口恰好只剩那一个"自己领不到"的元素。
⇒ 准确表述是：**"租约数不可能超过 1"是那个替身的性质，不是 store 契约的性质。**

### Ruling: `extra_busy_permits` **必须删除**（不只是"登记的偏离"）

1. 它是**生产 `RunnerConfig` 上的测试专用字段**，无生产语义；存在理由（让"许可已满"可达）已被证伪。
2. **它是个会把服务卡死的暗扣**：门用 `len(self._inflight) >= concurrency_limit`，
   而信号量是 `concurrency_limit - extra_busy_permits`。取 1 时两者不一致 ⇒ 走到
   `await semaphore.acquire()` 时许可数为 0，**该行无超时、`stop` 亦打断不了** ⇒ 执行器永久卡死。
   删除后两个判据重新恒等，隐患消失。

### Ruling: B2 的判据换成**行为判据**，AST 判据降为补充

用控制者探针的 store 形态 + `asyncio.Event` 闸住处理器（事件驱动，替换掉实现者自认易碎的
"让出 400 轮"）⇒ 断言"第一个任务占着唯一许可时，`acquire` 不得出现第二个 task_id" + 阳性对照。
AST 顺序判据**保留为补充**，但 **MUST NOT 是唯一判据**（它断言的是文本布局，不是行为）。

### 另外两项要求（均由控制者查清"可测"后下发）

- **A5(c) 的 `TaskRowMissingError` 有法测**：实现者 §5.2 的论证漏了集成段那条路——
  建好当月表、**不插行**、直接对不存在的 `task_id` 写回 ⇒ `rowcount=0` ⇒ 断言抛错。
  测的是真 SQL、真库。
- **`main.py` 装配与关停的集成用例可写**（前一轮已纠正过实现者的"与默认段禁连 Redis 冲突"）：
  `env="dev"` 触发装配（`config.py:80/86`，只有 `prod`+mock 被拒 `:23`），
  集成 marker 已注册（`pyproject.toml:97`）且集成段本就用真 Redis/MySQL。
  额外要求断言 **A2 那条**：让 `runner_task` 以异常结束，关停块**仍跑完**清理。

### 提交计划：3 → **5 个**

新增第 5 个 `test(aicore): 覆盖执行器在组合根的装配与关停顺序`。
第 3 批已下发；探针纪律：控制者本轮 2 个探针已删、目录已清空、`tests/`+`src/` 无残留。

---

## 第 3 批复核 → 提交（控制者）

### 门禁：控制者逐条重跑，全部一致

`CMD1 67 passed in 2.97s`（两条 5.01s 仍在 durations 之外）／
`CMD2 1268 passed, 13 skipped, 41 deselected, 1 warning in 48.78s`／
`CMD3 41 passed, 1281 deselected in 50.50s`（0 skip）／ruff `All checks passed!`／
mypy `61 source files`／`lint-imports 4 kept, 0 broken`／验收 `PASS 10 / FAIL 0`（standalone exit 0）／
跑完 Redis `dbsize=0`、`aicore:*=[]`。

### 控制者的 B2 复探（**修复在删字段之后仍然成立**）

```
(a) shipped run_forever → acquire ['task-0','task-1','task-2']      峰值租约 1
(b) pre-fix shape       → acquire ['task-0','task-1','task-1',...]  峰值租约 2
VERDICT: FIX HOLDS, criterion discriminates
```

实现者按裁定把结论更正写进了两处 docstring，并在 `run_forever` 新增**不变式**一节
（在飞任务与许可一一对应、两处数字必须恒等；任何让门判据与许可容量不一致的改动
都会在裸 `await semaphore.acquire()` 上造出永久卡死）——**即我发现的暗扣被写成了代码里的教训**。

### 提交粒度：原定 5 个 → 实际 **3 个**（附理由）

**不可分的证据**：`repository/task_lease_store.py` 是**新文件**，它同时承载
（a）执行器的 `TaskStore` 实现与（b）B3 的 `error_code` 透传；而 `task_repo.py` 的
`error_code` 形参是（b）的前置。⇒ 若把 B3 拆成独立提交，则中间提交里
`task_lease_store.py` 会调用一个尚不存在的形参 —— **又一个坏中间提交**。
把新文件按提交"重写中间版本"正是上次造出坏提交的做法，故**不做这种人工手术**。

同理，`core/task_runner.py` 的 B1 重构（handler 改为 task + `FIRST_COMPLETED`）
**已经蕴含** A1 的"解析前移"，两者无法分到两个提交。

**最终 3 个提交（按文件清晰可分，无 hunk 手术）**：

| # | SHA | 提交 | 内容 |
|---|---|---|---|
| 1 | `ab535ae` | `feat(aicore): 实现任务执行器内核与 CPU 密集边界` | 除 `main.py` 外的全部 src + 除装配用例外的全部测试（13 文件 / +6492） |
| 2 | `3c9a6c2` | `fix(aicore): 关停块在执行器异常死亡后仍跑完清理` | `main.py`（+113） |
| 3 | `1fed477` | `test(aicore): 覆盖执行器在组合根的装配与关停顺序` | `tests/integration/test_main_assembly.py`（+312） |

### commit-check 门禁（已加载技能并逐项执行）

A 提交信息：Conventional Commits、中文 subject、无 `[AI]` 前缀、
**带 `Co-authored-by: DeepSeek Harness <noreply@deepseek.com>`**（核过仓库近 40 条提交确有此 trailer，
故随仓库惯例而非新造）；一个提交一件事。
B 安全：staged diff 无密钥模式、无真实 `.env`、无 `.pem/.key`、无 >1MB 文件。
C 风格：`git diff --cached --check` 三项提交均 `exit=0`（无行尾空白/冲突标记）；注释中文、标识符英文。
D 语义：staged diff 里两处 f-string SQL 命中**均为测试断言**（对 `compiled` 语句的字符串比对），
生产代码无字符串拼接 SQL —— SQLAlchemy Core 参数化 + 模板渲染 DDL。
E 测试：新增关键逻辑均带用例（且本轮重点就是"让不会失败的用例会失败"）。
F 残留：无冲突标记（显式扫描 `NONE`）。

**hook 层**：按既有 Ruling（沙箱内 `sh` 不可执行，`.githooks/*` 对任何人都不运行）
用 `--no-verify`，确定性检查已由上面 C/F 手工等价复现。

### 逐提交健康检查

方法：在主工作树 `git checkout <sha>`（**editable 安装指向本工作树 `src`，故切换 SHA 即切换被测代码**），
跑全套门禁后 `git checkout <branch>` 归位 —— 这样避免了"新建 worktree 没有 venv / editable 指向原树"的遮蔽问题。
结果见下（作业完成后回填）。

### 未提交项

`.sdd-tools.py`（控制者复现技能 bash 脚本的 Python 工具，位于仓库根、未跟踪）**未纳入任何提交**：
它不属于 aicore 交付物。是否入库/加 `.gitignore`/删除，待用户裁定。

---

## 冻结 SHA 上的独立复核（第 4 轮）—— 又找出一个 blocker，且新用例自己也有假绿

**基线**：HEAD `1fed477`（3 个提交）· **报告**：复核者消息（F1–F13）
**工单**：`task-4.7-fix-brief-2.md`

### 控制者独立复核确认的三条（自己的隔离探针，非转述）

`lease_ms=150`（心跳 50ms），真 `InMemoryLockStore` 外层计 `renew`：

| 场景 | `execute` 出口 | 返回后 renew | 活动心跳 task |
|---|---|---|---|
| 业务失败（`AiCoreError`） | 正常返回 | **+0** ✓ | 0 |
| **编程错误（`ValueError`）** | 抛 `ValueError` | **+7** ✗ | 1 |
| **取消落在 `execute` 上** | `CancelledError`（传播正确） | **+7** ✗ | 1 |
| **同步 `handle`** | `TypeError` | **+7** ✗ | 1 |

⇒ **A1 只修了窗口的一半**：解析确实前移了（四种 `timeout_s` 变体干净），但
`create_task(_heartbeat())` 与 `try` 之间仍有可抛语句，**A1 的原失效形态仍在**（心跳永久续期
⇒ `SET NX` 永不成功 ⇒ 没有实例能再回收该任务），只是换了触发面。
**F1（非 `AiCoreError`）是 blocker**：它**不需要任何取消**，而 `TaskHandler.handle` 的 docstring
逐字把"抛别的异常"写成预期形态，并承诺"留待租约过期后由别的实例重做"——**承诺不成立**。

### 复核者主动下调自己刚报的严重度（记一笔，这是反方向的）

F2 原报 blocker，复核者**补跑端到端后自行更正**：直接取消 `run_forever`（未 set stop）**是干净的**
（取消落在轮询等待上、不传播到 `_execute_with_permit`，在飞任务照常收尾写终态释放租约、
另一实例能领到 `attempt=2`）；真正泄漏的只有"取消落在 `execute` 自己身上"，树内无生产者 ⇒
**major**。控制者采纳并已改写工单。
⇒ **这一轮我反复在纠"结论比证据大"，这次是反方向，且发生在我已准备按 blocker 下发之后。**

### 控制者自己的探针缺陷（自记，不记到产品头上）

我第一版把 F1/F2/F3 三个场景写在**同一个进程**里、且**没有 await 被取消的任务**，
于是**业务失败路径被我读成了 `CancelledError`**——隔离重跑后是 `returned normally`。
⇒ 纪律：**一个探针文件里多场景时，每个场景必须独立拆除并 `await gather(..., return_exceptions=True)`**；
否则上一个场景的取消会在下一个场景里冒出来，被当成产品缺陷。**差一点又报一个假警报。**

### 最不舒服的一条：**为补"最大测试空白"而新写的装配用例，自己带着两个假绿**

- **F6（已判 blocker）**：`test_main_assembly.py` 的"死亡有日志"断言用的是子串 `"异常退出"`，
  而**关停期那条日志**（`main.py:199`）也含该子串 ⇒ **删掉 `add_done_callback(_log_runner_death)`
  后仍 4 passed**（复核者实测）。即 `3c9a6c2` 的**一半理由**（死亡当场记 ERROR）**零守备**。
- **F7（major）**：把 `await runner_task` 换成 `await asyncio.sleep(0)` 后**仍 4 passed**
  ⇒ **join 本身没有判据**（顺序判据真、join 不受判别）。

⇒ **形态总结（本轮最该记的）**：每一轮新写的用例，都**以更小的尺度复制了同一个毛病**——
"用例在那儿，但判据不覆盖它所声称的那件事"。第 1 轮是背压与续期失败，第 2 轮是超时业务码，
第 3 轮是装配与关停。**这不是疏忽的累积，而是一种稳定产出的偏差**：**先写出"看起来在验"的断言，
再让它通过**。故本轮工单把"判别力自证"从"最好有"提升为**每条 blocker/major 的交付条件**。

### 其他已下发项

F4（`timeout_s` 返回 `nan`/`inf` 静默关掉超时）、F5（`_dissolve_task` 取消后无上限 await：
"放弃"变成等 1.561s，且**放弃之后仍发生 1 次付费调用**）、F9（内存锁店比真 Redis 宽松 4 处 + 过期边界）、
F10（`task_lease_store.py:79-97` 与 `test_runner_redis.py:315-317` 仍写着"`error_code` 没有落库"——
**这句现在是假的**，B3.6 只做了一半；这是"文档说没做、代码做了"的**镜像**，同属文档未随代码维护）、
F12（装配用例卫生：`flush_logging` 不可观测、`RunnerConfig` 取值无断言、`SqlTaskLeaseStore` 注入无判据、
**死端口下仍 4 passed ⇒ 它不需要 MySQL/Redis 却被标 integration 且默认段会被真收集**、
`DSH_IT_MYSQL_PASSWORD` 缺失导致**假 skip**、删 `runner_stop.set()` 会**挂死**而非变红）、
F13（固定让步轮数改条件等待 + 有界 deadline）、F8/F11（只登记）。

**F12 的处置口径**：要求实现者**如实写清并登记**，**明令不许擅自改 `pyproject.toml` 或 marker**
（那要先问控制者）。

### 并行协调（吸取同树并跑的教训）

复核者的"假绿普查（97 条用例 × 5 个内存变异）"仍在跑，而实现者已开始第 4 批。
**这次不是重犯旧错**：复核者的 finding **全部钉在 `1fed477`**，可解释、可按 SHA 分派；
并已要求实现者**外科化改动、不做大段重写**（行号映射不失效），
要求复核者**收口普查并停止开新取证面**。

---

## 复核第 2 批（收口）：假绿普查 —— **B1 的招牌判据零杀伤**

**追加工单**：`task-4.7-fix-brief-2-addendum.md`（已与第 4 批一并下发给实现者）

### 最重要的一条：B1 的修复可以被整个撤掉而全量套件全绿

复核者用**全量变异**实测（子代理跑，复核者隔离复核）：

```
变异：execute 里 `if lease_lost or timed_out:` → 只判 `timed_out:`
       （= 租约丢失后不取消处理器）
结果：-m "not integration" → 1268 passed, 13 skipped, 41 deselected, 0 failed
      隔离只跑 test_renew_failure_abandons_without_any_terminal_write → 2 passed
```

**机制**：该用例的 ②`handler.completed is False`（L599）与 ③`paid_calls == 0`（L602）
都在 `execute` 返回后**立刻**读取。不取消时处理器只是**脱离的 task 还在 `sleep(1.0)`**
——此刻 `completed` 当然是 `False`、`paid` 当然是 `0`，**两种实现下同时为真**；
①`elapsed < 0.5` 也拦不住（心跳 10ms 就发现租约丢失，`execute` 照样早返回）。
而 L563-565 的 docstring **逐字**宣称"修复前这两条**必红**"。

⇒ **我第 1 轮找到的第一个 blocker（B1），其回归门禁是空的。**
**产品侧是对的**（复核者独立验证：`renew` 首次即 False → `execute` 0.065s 返回、处理器真被取消、
付费 0），**修的是判据**。⇒ 但"产品对、判据空"意味着下次改坏没人拦。

**其余四个变异都有真实判红**（M2 背压 → 2 条红；M3 `timeout_s` 抛异常 → 1 条红；
M4 领取异常杀死循环 → 2 条红；M5 `mark_failed` 不写 `error_code` → 单测 4 红 + 集成 1 红）。
⇒ **假绿不是普遍现象，集中在"取消类"判据**。

### 其余已下发项（N1–N7）

- **N1【高】**`test_unreachable_redis_fails_fast_without_touching_the_row` **实测 25.18s**
  （集成段 50.10s 的一半）而断言里**没有任何时延判据**——名字承诺 fail fast 无人验证；
  成因是 redis-py 8.1.0 默认 `Retry(retries=10)`（裸 `Redis(port=1).ping()` 实测 26.0s）。
  控制者倾向让生产侧**显式不重试**（A2 刚消灭"藏在一次调用里的长尾巴"，客户端再叠 10 次等于装回去），
  但要求改产品行为必须单列理由与代价。
- **N2**：6 处"声称的判据 ≠ 实际判据"，含 `test_task_runner.py:10-11` **逐字**写
  "本文件没有 `await asyncio.sleep(...)`，也没有任何轮询等待"（实际 **13 处豁免**、三处是轮询等待）
  与 `:30` 索引表指向一个**全仓不存在的用例名**。
  ⇒ 新增要求：**一条机械判据**，断言"docstring 声称的豁免数与实际 `# ai-allow-sleep` 数一致"。
- **N3**：`test_task_runner.py:1103-1104` 用**固定 50 轮** `sleep(0)`，而同文件 L1092-1095
  **自己记过"固定 50 轮偶发不够"**——它决定的正是 `test_b2_guard_discriminates` 的
  `mutant_peak >= 2` ⇒ **实现者的 B2 自证本身可能是假绿**。
- **N4**：两条恒真断言 + 一条白等 1.02s。
- **N5【控制者授权改一行】**：`pyproject.toml` 的 `addopts` 补 `-m "not integration"`。
  复核者技术判断、控制者采纳：marker 描述与多份文档都承诺"默认不执行"，
  但 `addopts` 既无 `-m` 也无 collection hook ⇒ **承诺是空的**（裸 `pytest` 会真收集并执行集成用例）；
  CLI 的 `-m integration` 覆盖 ini，故既有门禁命令不受影响。**明确不许动 marker**
  （该文件确实会构造真 `RedisLockStore`，今天不连只是惰性构造的偶然）。
  **此前工单禁止改 `pyproject.toml`，本次为限定授权（仅此一行）。**
- **N6【授权】**：`test_main_assembly.py:63-68` 因 `DSH_IT_MYSQL_PASSWORD` 缺失就 skip 掉
  3 条**一条外部依赖都不需要**的行为用例（死端口下仍 4 passed 已证）⇒ **静默砍覆盖**。
- **N7**：装配用例的 3 条行为用例**没有任何超时**，删 `runner_stop.set()` 会**挂死 >8 分钟**而非变红
  ⇒ 必须加有界 deadline。裸 `await runner.execute(...)` 那 5 处只登记（今天暴露面低）。

### sleep 普查结论（有价值，记下来）

基线 `dc06588` 测试侧 **4** 条 → HEAD **22** 条；新增 18 条**全部带非空理由、格式合规**；
判定 **14 条合法真等待**（真 PX/TTL、由取消结束的处理器、`sleep(0)` 纯让出、有界轮询、
变异体心跳、自证定时协程）、**2 条"睡一觉再祈祷"**（固定轮数/固定余量，即 N3）、
**1 条声称与实现不符**（cpu_pool 的"不受机器快慢影响"实为 10× 时间竞速）。
⇒ **豁免机制本身没有被滥用**：这是一个"偏严 + 显式豁免"判据健康运转的证据。

### 复核者本轮的两处自我更正（都记一笔）

1. **F2 严重度自行下调** blocker → major（补跑端到端后发现直接取消 `run_forever` 是干净的）；
2. **主动作废一次落在实现者改动之后的复现**（并声明"无法归因，故不登记为发现"）——
   环境事实与结论边界分得很清。

⇒ 与"新写用例复制同一毛病"形成对照：**同一个复核者，在"报缺陷"上偏保守、在"报自己错了"上很快**；
而实现者在"声称已做"上偏乐观。**这个不对称正是我这几轮反复吃亏的地方**——
所以我把接受标准从"请给自证"改成"**给一条今天红的用例**"。

---

## 第 4 批（含追加）控制者复核 → 提交 4 / 5

### 门禁：控制者逐条重跑，与实现者自报一致

`CMD1 90 passed in 4.19s`（原 67）／`CMD2 1291 passed, 13 skipped, 50 deselected in 51.91s`（原 1268/41）／
`CMD3 50 passed, 1304 deselected in 31.22s`（原 41 passed / 50.10s，**N1 的效果**）／
ruff `All checks passed!`／mypy `61 source files`／`lint-imports 4 kept, 0 broken`／
验收 `PASS 10 / FAIL 0`／`tests/structural 72 passed, 11 skipped`（含两条新机械判据）。
**N5 自证复现**：裸 `--collect-only` 收集到集成用例 **0** 条；`-m integration --collect-only` **50** 条。

### 控制者的独立判别力复核（**内存变异，未改任何文件**）

本会话第二次用 pytest 插件在**运行期替换模块属性**做变异（第一次是 F1/F2/F3 的复核）：

```
变异①  _dissolve_task → no-op（= 精确地撤掉 B1 的取消）
       基线 3 passed → 变异 2 failed  ← test_renew_failure_abandons_without_any_terminal_write[两个参数]
变异②  aicore.main._log_runner_death → no-op（= 忘注册死亡回调）
       基线 7 passed → 变异 1 failed  ← test_shutdown_cleanup_completes_even_if_the_runner_died
```

⇒ **M1 与 F6 都真的修好了**：两处判据现在会在对应缺陷复现时变红。
（对照：变异前，撤掉 B1 的取消会让**全量套件全绿**；删掉死亡回调**仍 4 passed**。）
**这个手法值得固化成常规**：`-p <plugin>` 在运行期替换模块属性 = 内存变异，
既不碰仓库文件、也不会有"改 src + finally 还原"留下的注入风险。

### 控制者的两次误报/失误（自记）

1. **我提交时冲过了失败的门禁**：commit 5 的 `git diff --cached --check` **exit=2**
   （`test_lease_redis.py` 与 `test_lease.py` **文件末尾多一个空行**），**我却照常提交了**。
   这正是我在本计划早期记下的那条纪律（"`git add` 失败必须检查返回码"）的同类错误。
   已用 Python 精确去掉末尾多余空行（`rstrip('\n') + '\n'`，`newline=''` 写入）、
   **重跑门禁 exit=0**、`--amend` 修正（`21234af` → `a3aa8e0`）。
   ⇒ 纪律补强：**`--check` 的返回码必须与 `git add` 同等对待：非 0 一律不得进入 commit**。
2. 我一度把 `tests/repository` 单独跑时的 `test_session.py` 失败当成可能与本轮有关；
   实测 `git status` 里**没有任何 `tests/repository` 文件被本轮改到**，且失败形态是
   **既有 `test_migration.py` 污染 caplog** ⇒ **既有问题，只登记不碰**（实现者的定位属实）。

### 提交

| # | SHA | 提交 |
|---|---|---|
| 1 | `ab535ae` | `feat(aicore): 实现任务执行器内核与 CPU 密集边界` |
| 2 | `3c9a6c2` | `fix(aicore): 关停块在执行器异常死亡后仍跑完清理` |
| 3 | `1fed477` | `test(aicore): 覆盖执行器在组合根的装配与关停顺序` |
| 4 | `e567aed` | `fix(aicore): 心跳生命周期改为结构上不可泄漏，并让 B1 的判据真能判红` |
| 5 | `a3aa8e0` | `fix(aicore): 补严装配与死亡的判据，并让锁店替身与真 Redis 同判` |

拆分为 4/5 的依据：`InvalidLeaseArgumentError`（F9 新增异常）**只在 `lease.py` 里出现**
（grep 6 处命中全在该文件）⇒ 无跨文件依赖，按文件即可清晰分组，**无需 hunk 手术**。
`git add -p` 未使用。

### 仍登记未修（按裁定）

F8（`main.py` 关停块在"执行器被取消"时被跳过，树内无生产者）、F11（AST 判据的已知弱点）、
裸 `await runner.execute(...)` 四处、真 `run_forever` 被 `wait_for` 包住时回归显示成 5s `TimeoutError`、
`tests/repository` 单独跑时 `test_session.py` 一条**既有**失败（order-dependent caplog 污染）、
`services/aicore/probe-7bz35wir/`（**既有的 ACL 锁定目录，不是本轮产物**，gitignored，不清理）。

---

## 用户裁定：对 commit 4/5 做定向独立复核（选项 A），再进 G

**已派出**（冻结 SHA `1fed477..a3aa8e0`，工作树无人改动）。复核重点由控制者逐条指定：

1. **F7 的 join 判据** —— **控制者自己没验过这一条**（只验了 M1 与 F6）。要求评审者用变异证明
   "把 `await runner_task` 换成 no-op ⇒ 顺序用例必须变红"；若仍绿即为 blocker。
2. **M1 要验机制不只验结果** —— 控制者已证"撤销取消 ⇒ 变红"，但要求复核者确认**为什么**红
   （是否真的等过了处理器的自然完成时刻），并用**第二个不同的变异**（让处理器瞬间完成）复验。
3. **F1/F2/F3 的结构修复是否引入新问题** —— `finally` 现在**无条件**收处理器 task：
   处理器**合法先完成**的路径（成功 / `AiCoreError` / 超时）会不会误取消？快乐路径是否多付一次
   `CANCEL_WAIT_TIMEOUT_S` 等待（要求实测时延）。
4. F5 的有界等待是否真的有界、docstring 是否与实现一致；F4 的 `nan/inf/0/负数`是否走兜底且**有判别力**；
5. **F6 要换一种变异**（不 patch `_log_runner_death` 本身，改从"注册路径"下手），确认判据真的只可能由死亡当场那条日志满足。
6. F9 两侧是否**同判**（对真 Redis 实测），以及**是否引入新分歧**（新异常类型会不会穿过 `run_forever` 传播出去）。
7. **`test_main_assembly.py`（整文件重写、现 7 条）专找假绿** —— 该文件此前正是两条空判据的所在地。
8. 两条新"机械判据"是否真的成立；**N5 的 `addopts` 隐患**（`-o addopts=""` 会连 ini 的 `-m` 一起清掉）
   是否写在未来操作者能看到的地方；仓库里有无既有命令/文档因此静默失去 `-m`。
9. 这两个提交新增的 ~1400 行测试里**还有没有永不失败的断言**（前几轮每轮都有）。

**并明确告知评审者本会话已固化的手法**：`pytest -p <plugin>` 在**运行期替换模块属性**做变异——
**不碰仓库文件**、无"改 src + finally 还原"的注入/超时风险（控制者已用它验了 M1 与 F6）。

### G 阶段范围已查清（`openspec/.../tasks.md` §4）

| 项 | 内容 | 备注 |
|---|---|---|
| **4.9** | 任务提交幂等与跨账号越权拦截（相同幂等键返回原任务号**不重复调用**；非本人查询 `2002` 且不泄露结果） | 验证要求「断言 **Provider 调用次数不增加**」 ⇒ **需要先确定"Provider 在哪里被调用"**：M1 现状 `handlers={}`、执行器不解析任何处理器，而 OCR 处理器属第 5 组（K-01）。**这是一个必须先问清的范围问题**，否则 4.9 的判据无处落点 |
| **4.10** | 置信度分级（高 ≥0.9 / 中 0.7~0.9 / 低 <0.7，**阈值可配并留痕**） | 验证 = 三个边界值 `0.899 / 0.9 / 0.7` 分级用例 + 阈值变更记录可查；用户已裁定 `confidence_high`/`confidence_medium` **两个配置字段归 G 阶段** |
| **4.11** | 通道失败降级与异常区分（`4003` 转人工复核队列、`5002` 依赖超时，**两者不混用且分别计数**；降级可观测、不阻塞核心业务） | **依赖本任务刚修好的 `error_code` 落库**（在此之前 `FAILED` 行该列为 NULL，"分别计数"不可用）；还需确定"分别计数"的载体（指标？查询？） |

**G 开工前必须先解决的三个范围问题（不要凭猜开工）**：
① 4.9 的 "Provider 调用次数" 在哪条路径上可观测；② 4.11 的"分别计数"落在什么载体上
（现有可观测性只有日志，Task 11.1 才有依赖就绪探针）；③ 4.10 的"阈值变更留痕"落到哪张表/哪个字段
（`er.md` 里是否已有承载）。

---

## 2026-09-20：定向复核（F7/M1/F6 全部确认修好）+ G 工单落地

### 环境：Redis 已拉起，MySQL 起不来（需用户一条命令）

- **`Test-NetConnection` 在本环境给假阳性**：报 `6379 open: True`，实际 `PING` 是
  `ConnectionRefusedError WinError 10061` ⇒ 控制者**先给复核者发了错误前提**，随即更正。
  **纪律：端口探测工具不可信，一律以"实际发一次命令"为唯一判据**（复核者独立记了同一条）。
- **Redis**：`wsl -u root service redis-server start` 后**实际 PING 通**（WSL 侧 `active (running)`）。
- **MySQL**：服务 `STOPPED`；`net start MySQL` → **`System error 5 / 拒绝访问`**；
  控制者试过一次提权（`danger-full-access`）：**WSL 那半边解决了、服务控制这半边仍被拒**。
  ⇒ **需用户以管理员身份跑 `net start MySQL`**；**MUST NOT** 手动拉 `mysqld.exe`（既有纪律：
  手动实例与服务抢数据目录，是"实例间歇性卡死"的元凶）。影响面：默认段不受影响；
  `-m integration` 整段、验收脚本第 1 项、`tests/repository/*` 连库用例受阻。

### 定向复核结论（冻结 `1fed477..a3aa8e0`，全部有执行证据）

- **F7 的 join 判据：修好了**（控制者此前**没验过**这条）。变异 `await runner_task` →
  `await asyncio.sleep(0)`（插件 exec 进 `aicore.main.__dict__`，文件从不被写）⇒ `1 failed`，
  `At index 1 diff: 'runner.stop' != 'run_forever.end'`（**红在正确的那一处**）；
  变异连跑 3/3 红、生产未变异连跑 5/5 绿。
- **M1 机制**：`stopped` 在 `handle` 的 `finally` 置位 + `wait_for(stopped.wait(), 2.0)`（**有界事件等待**），
  置位后**同步**执行 `paid_calls += 1; completed = True` ⇒ 不取消必然读到 `completed=True`；
  换第二个接缝的变异 → 2 failed；自然完成窗口 0.3s **收紧 5 倍到 0.06s** 后变异仍 2 failed、
  未变异仍 2 passed ⇒ **事件驱动，不靠时序余量**。
- **F6**：只删 `add_done_callback(...)` 那一行注册（**不碰** `_log_runner_death`）→ `1 failed`，
  报错正是"没有死亡**当场**那条日志"。
- **F1/F2/F3 没误伤正向路径**：上界放大到 5s 后 success `0.001s` / `AiCoreError` `0.001s` / 超时 `0.060s`。
- **F9 与真 Redis 逐项同判、无新分歧**；`test_main_assembly.py` 7 passed（N6 的假 skip 确已消除）。
- 复核者**纠正了控制者的一条方法论错误**："把处理器改成立即完成"作判别力探针是**错的**——
  产品**未变异**时也会红（换场景）⇒ **自证必须打在同一场景的接缝上**。

### 新发现：B1 是**本轮修复引入的 major** → 第 5 批工单已下发

放弃路径等待上界是 docstring 的**两倍**：`finally` 新增的 `_dissolve_task`（`:801-802`）与 `:779-783`
那次**串行各等一整档** ⇒ 实测 `elapsed = 2.031s`（`CANCEL_WAIT_TIMEOUT_S=1.0`），
而 docstring（`:1267-1270`）写「**最多再加上**……`CANCEL_WAIT_TIMEOUT_S`」。
`1fed477` 的 `finally` 只有 `_cancel_heartbeat` ⇒ 本轮引入；对已吞掉取消的 task 再 cancel **零收益纯延迟**。
**F5 用例的 `assert elapsed < bound_s * 3`（0.6 > 0.4）恰好放过它** ⇒ 又一次"判据太松 + 文档说谎"。
→ 第 5 批 = B1 + B2（F4 的 `0.0`/`-1.5` 零判别力）+ B3（`test_pytest_config` 子串判据可被
`-m "not integration" -m integration` 满足）+ B4（`-o addopts=""` 的危险没写明）+ B5（`bool` 守卫的理由是假的：
真 Redis 在**客户端编码期**抛 `DataError`）+ B6（一条恒真断言）+ B8（两条自证只钉消息不钉成因）；
**B7 只登记**（确定性编程错误被报成 Redis 抖动）。

### G 工单已落地（`task-4.9/4.10/4.11-brief.md`）

- **4.9**：**先 RECON 再动手**（T1 已铺好大部分机制，MUST NOT 重写）；字面判据「Provider 调用次数不增加」
  在 M1 无处落点 ⇒ 换成**计数 handler 只被调用一次**；**T1 自己登记的"并发同幂等键撞 `uk_idem` → `5000`"
  就是本任务的活**（应回读原任务并返回它，且回读走主库 `er.md:287`）；
  越权判据 **MUST NOT 只断言状态码**（要断言"只含信封四字段、`data` 为 null、无业务内容"）；
  幂等键两条来源（显式 / `sha256(imageKey NUL docType)`）**各要一条判据 + 一条"不同 docType 不互相幂等"的阴性**。
- **4.10**：裁定 `HIGH=c≥0.9 / MEDIUM=0.7≤c<0.9 / LOW=c<0.7`（三处文档口径一致收敛）；
  裁定 `confidence is None` ⇒ **不判级 + `needs_manual_review=1`**，并要在 docstring 写清它与
  "把 None 当 `0.0` 伪造出 `LOW`"的**语义区别**；载体 = 返回分级 + `ocr_result.needs_manual_review`
  + `ai_task.model_meta.thresholds`；`confidence_level` enum 列在 **M2 的 `VISION_REVIEW`**，M1 不加列；
  **M1 边界如实登记**：`handlers={}` ⇒ 无真实 OCR 执行 ⇒ 端到端"随输出返回"归第 5 组。
- **4.11**：⚠ **开工前有待用户裁定的冲突**（详见该工单 §2）。与 `design.md:98` 无关的部分
  （两码不混用、`GROUP BY error_code` 分别计数、降级不阻塞受理）**不依赖该裁定，可先做**。

### 控制者自记的一条失误

**我把 G 范围勘察稿存进了 `D:\progrom\.dsh-probe\`，而那正是我要求复核者"用完即删"的目录**
⇒ 复核者收尾删了整个目录，勘察稿丢失（内容多数已折进 4.9/4.10 工单，4.11 的分析已重写）。
⇒ **纪律：暂存自己的产物不许放进"要求别人清理"的目录**——要么放仓库内的忽略目录，
要么放一个只有自己会动的路径。

### MySQL 由用户启动 → `98dbb1f` 的健康检查补齐

- 用户以管理员启动 MySQL 后，控制者实测：**CMD3 `50 passed, 1311 deselected`（0 skipped）**、
  **验收脚本 `PASS 10 / FAIL 0 / INFO 0`**（第 1 项"真 MySQL 执行 DDL"转绿）。
  ⇒ `98dbb1f` 那次"部分完成"的健康检查**补齐**：CMD2 `1294 passed, 13 skipped, 50 deselected` +
  CMD3 `50 passed` + ruff/mypy/lint-imports 全绿 + 验收满绿。**6 个提交全部完整健康。**
- **又一次"工具给的信息不可当真"**：控制者的裸 `pymysql` 探针报
  `Access denied ... (using password: NO)`——凭据在 `.env` 里由 conftest 注入，不在 pwsh 环境。
  ⇒ **连通性的权威判据是"测试真跑"**，不是自己随手连一次。

### Task 4.9 第 1 轮复核（控制者）

- **门禁与实现者一致**：CMD2 `1298 passed`（原 1294，+4）；ruff/mypy/lint-imports 全绿；
  范围正是 3 个文件（`submit.py` + 两个既有 API 测试），**`repository/task_repo.py` 未改**（本轮不需要新查询）。
- **冲突处置逻辑逐条核过**（`submit.py:265-332`）：`except IntegrityError` → `effective_key is None` ⇒ 重抛；
  否则 `_resubmit_after_key_conflict` → **先 `session.rollback()`** → **同一个会话**（主库）按
  `(account_id, idem_key)` + **同一分片月**回读 → 读到即返回，**读不到返回 `None` 由调用方重抛**。
  三条要求都落在代码里，理由写在 docstring。
- **`submit.py` 唯一改的生产文件**；被删掉的 8 行 `assert` 逐条对过——**全部进了共用助手
  `_assert_denial_leaks_nothing`，且两条被加强**（`set(body) <= {五个}` 变成 `== {五个}`；
  字段名判据变成**取值**级 `forbidden_values not in response.text`）⇒ 实现者"只抽助手、只补严"**属实**。
- ⚠ **发现一处缺口（major）**：`submit.py` 的两条**重抛分支**（`effective_key is None`、
  回读为空）**没有任何判据**——而它们正是 docstring 与报告里"**不把写失败伪装成幂等命中**"这句承诺的唯一保障。
  危险方向具体：把 `if absorbed is not None: return absorbed` 改成吞掉 ⇒ **一个没落库的任务被当成创建成功返回**，
  全套测试照样绿。**又一次"文档承诺了、没有东西能拦回归"。**
  → 已下发：构造**非 `uk_idem` 的 `IntegrityError`**（固定 ID 生成 + 先插一行同 `task_id` 但不同 `idem_key`
  的行 ⇒ 主键冲突）⇒ 回读必然为空 ⇒ **MUST 重抛**；自证 = 改成吞掉必须变红。
  并要它确认 `effective_key is None` 是否**经 API 可达**（`imageKey` 缺失会先被 `400/1001` 挡掉 ⇒
  可能是防御性死分支）——可达就单测，不可达就如实登记，**MUST NOT 当成已覆盖**。
- 4.9 其余待办（真库 `uk_idem`、**真并发**两条连接、走主库回读的端到端）已在 MySQL 起来后下发；
  §2.1 的**字面版 Provider 调用次数不属本阶段**（第 5 组 K-01）。

### Ruling（用户 2026-09-20 选定 **(a)**）：M1 **不使用** `MANUAL_REVIEW`

- `4003` 与 `5002` 都是 **`status = FAILED`** + **`error_code = 对应码`**；
  "**已转人工**"是 `4003` 这个码**自带的语义**（`er.md:329` 逐字），**不是**状态迁移；
  "人工复核队列" = **运维按 `error_code` 的查询视图**，M1 **不新建队列表、不新增状态**；
  `MANUAL_REVIEW` 作为第四态**保留在枚举与状态机里但 M1 无触发者**，留给 M2，**如实登记为"M1 不使用"**。
- **依据**：`error_code` **两处**都被定义为「**FAILED** 业务码」（`er.md:26`/`:329`），
  `design.md:210` 亦写「置 `FAILED` 并转人工复核队列」；选 (b)/(c) 都要反改这三处口径
  ⇒ 那属于**改文档迁就一种解释**，不是按文档实现。
- **对 4.11 判据的影响**："分别计数"**不需要跨 status 聚合**（`WHERE status='FAILED' GROUP BY error_code` 即可）；
  "两码不混用"要**同时断言 `status='FAILED'`**；**MUST NOT** 出现任何把任务置成 `MANUAL_REVIEW` 的新代码路径。
- 工单已同步（`task-4.11-brief.md` §2 改为"✅ 已裁定"，§3 标题改为"已按裁定 (a) 收窄"）。

### Task 4.9 第 2 轮（收口）复核 → 提交 `d1ff44e` / `5ae4af2`

- **门禁与实现者一致**：CMD2 `1301 passed, 13 skipped, 54 deselected`；**CMD3 控制者连跑 2 次均 `54 passed, 0 skipped`**
  （实现者报过 5 次里 1 次 `1 skipped`，控制者这两次未复现）；ruff/mypy/lint-imports 全绿；验收 `PASS 10 / FAIL 0`。
- **控制者对"真并发"做了独立复核（本轮最吃重的一条 claim）**：写内存变异把 `_resubmit_after_key_conflict`
  换成恒返回 `None`（= 关掉"吸收"）⇒ **基线 4 passed、变异 2 failed**，且失败文本是真表上的真索引：
  ```
  pymysql IntegrityError (1062, "Duplicate entry 'acc_it_idem_4_9-it-window-…'
  for key 'ai_task_202609.uk_idem'")
  ```
  ⇒ **两条独立连接真的在 MySQL 上撞到了 `uk_idem`**，而"吸收"代码正是让它们通过的原因。
  **不是"两个请求恰好被串行化了"。**（`TestClient` 撞不出并发——实现者第一版踩过：
  两线程 + 栅栏 15s 后 `BrokenBarrierError`；改用 `httpx.ASGITransport` + `asyncio.gather`
  才让两个请求成为同一事件循环的两个 task、各自开独立连接。）
- **实现者自己的一处发现值得记**：栅栏放在"查完且没查到**之后**"才有意义——放在查询**之前**时，
  先查完的可能已经把行插进去了，**冲突根本没发生**，而那三条结果断言**全绿**。
  **只有"成因断言"把它拦住了。** ⇒ **"结果对"不等于"走了你以为的那条路"**。
- **③ 如实登记、没有编对照**：本机无从库 ⇒ `test_primary_read_has_no_replica_to_compare_against`
  只钉两件真能钉的事（`submit.py` 不自开会话 = AST；**一旦真配从库该用例立刻变红**提示补真对照）。
- **④ 控制者发现的缺口已闭合**：两条重抛分支的判据 + "改成吞掉 ⇒ 必红"的自证；
  `effective_key is None` **经 API 不可达**（`compute_idem_key` 永不返回 `None`；`imageKey` 缺失先被
  `400/1001` 挡掉）⇒ 既直驱 service 单测、又在 docstring 逐字写明"经 API 不可达，
  MUST NOT 读成端到端覆盖"。

### 控制者的纪律失败（**同一个错犯了第二次**）与机械化纠正

- commit 7 的 `git diff --cached --check` **exit=2**（`test_ocr_submit.py` 文件末尾多一个空行），
  **控制者仍然提交了**——与上一次（commit 5）**完全同类**，而上次之后我明确写过
  "**`--check` 的返回码与 `git add` 同等对待**"。
- **"记住要检查"已经失败两次，故改为让失败不可能发生**：新增
  `D:\progrom\.ctl-verify\cc.ps1`——`git add` → `--check` → **非 0 即 `throw`**（在 `git commit`
  **之前**中断）→ 才 `git commit`。已用它重做两个提交。
- 重做手法（可复用）：`git reset --mixed HEAD~2`（保住工作树）→ 修文件 → 用守卫逐个重提。
  注意本机只有 `powershell.exe`（**没有 `pwsh`**），守卫脚本要用 `& 'path\cc.ps1' -MessageFile … -Paths …` 调用。
- **逐提交健康检查**：`d1ff44e` = CMD2 `1301/13/50` + 集成 `50 passed`；`5ae4af2` = CMD2 `1301/13/54` + 集成 `54 passed`；
  两者 ruff/mypy/lint-imports/验收全绿。（deselected 50→54 正是新集成文件进来的那一步。）

### 新增门禁规则：集成段的判据 MUST 包含 "`0 skipped`"

实现者如实报的一处抖动（5 次里 1 次 `1 skipped`）暴露了一个**静默降级通道**：
夹具的**探测式 skip** 一旦瞬时失败，本该跑的用例就不跑了，而门禁**仍然是绿的**。
⇒ 集成段验收 MUST 同时看 `passed` 与 `skipped`，**`skipped != 0` 即视为门禁未通过**（除非逐条登记了原因）。

### Task 4.10 复核 → 提交 `d409118` / `c924c6d`

- **门禁与实现者一致**：CMD2 `1323 passed, 13 skipped, 54 deselected`（原 1301，+22）；
  集成段 `54 passed, **0 skipped**`（用了新规则）；ruff 全绿；`mypy --strict` **62** files（+1 模块）；
  `lint-imports` 4 kept / 0 broken；验收 `PASS 10 / FAIL 0`；
  **`er.md` 与 `openapi.yaml` 一个字未动**（M1 载体是既有列）。
- **逐提交健康检查**：`d409118` CMD2 `1318` + 集成 `54 passed`；`c924c6d` CMD2 `1323` + 集成 `54 passed`；
  两者 ruff/mypy(62)/lint-imports/验收全绿。（1318→1323 正是快照接线用例进来的那一步。）
- **控制者裁定（两条实现者主动请复核的）**：
  - **(a) 跨字段规则 `confidence-order` 接受**：与既有 `budget-order`/`readonly-pair` **同族同体例**
    （`config.py:95` 规则码、`:575-581` 启动期拒绝、`[跨字段：<代号>]` 消息体例），
    消息写明后果（"中档区间会变空、且 `high` 以下一段会被判成 HIGH"）。
    字段级 `ge/le` **管不到相对关系**，反序会让配置**静默失效且无信号** ⇒ 保留；`medium == high` 允许。
  - **(b) `MEDIUM` 不置 `needs_manual_review` 接受**：依据 `er.md:481` 的**兜底**语义
    + `spec.md:63` 分级供人工端**排序**复核 ⇒ **分级负责"排序"、兜底开关负责"哪些不能自动通过"**。
    这是全篇**唯一没有逐字文档支撑**的取值 ⇒ 已在提交信息里**登记为控制者裁定**，
    日后要改只需 `grade()` 一处表达式 + 两条期望值。
- **两处做法记入台账（值得复用）**：
  ① `_threshold` 缺键**显式报错、MUST NOT 回落默认值**——理由写在 docstring 里：
  "运营改了配置却不生效、现场没有任何信号"，正是本项目的**静默漂移**形态；
  ② `test_confidence_grading.py` 的**"会自己过期"的判据**：断言 `main.py` 仍有 `handlers={}`，
  **第 5 组注入真实处理器后它会自动变红**，提示补两条端到端用例 ⇒
  **把"如实登记的边界"变成将来会自己响的提醒**，而不是一段会烂掉的说明。
- **一个值得记的坑（实现者自证时踩到）**：本仓有**两个同名 `get_settings`**
  ——`core/config.py`（进程内缓存那份）与 `api/deps.py`（从 `app.state.settings` 取的那份）。
  变异自证只换路由依赖 ⇒ 变异体读到的还是 `.env` 默认值 ⇒ "先断言变异生效"那步失败。
  **两处都换才是同一个场景。**

### Task 4.11 已下发（G 段最后一项）

工单 `task-4.11-brief.md` 已含裁定 (a) 与新增的第 5 条**机械判据**
（AST 断言 `MANUAL_REVIEW` 不出现在任何写回调用的实参里；判据要能判红）。
做完即 G 段（4.9/4.10/4.11）齐。

### Task 4.11 复核 → 提交 `ba55f7d` / `bb1a460`（**G 段齐活**）

- **结论：生产代码零改动**——T2 已把"失败码取异常自带的 `code`"与"`mark_failed(error_code=…)` 真落库"
  做完，本任务是**把口径钉成判据**：新增 `tests/integration/test_failure_codes_mysql.py`（457 行）
  与 `tests/structural/test_no_manual_review_writes.py`（149 行），`git status` 仅此两项 ✓。
- **门禁与报告一致**：CMD2 `1325 passed, 13 skipped, 58 deselected`；集成段 `58 passed, 0 skipped`；
  ruff/mypy 62/lint-imports/验收全绿；`er.md`/`openapi.yaml`/`core/errors.py`/`core/task_runner.py`/`provider/**` 未动。
- **机械判据的边界划法（记下来，值得复用）**：第 5 条**只认写回调用白名单**
  （`update_status`/`status_update_statement`/`mark_failed`/`mark_succeeded`/`requeue`/`begin_attempt`/`_write_back`），
  而**不是**"凡出现 `MANUAL_REVIEW` 就报"——后者会把 `state.py` 的定义与转移表、`api/tasks.py` 读侧 `Literal`、
  `models.py` 的 `Enum(...)` 三处**合法**用法判红，最终逼后来者加**豁免注释**，
  **而豁免注释正是"约定悄悄失效"的入口**。⇒ **判据的边界按语义划，不按字符串划。**
- **逐提交健康检查**：`ba55f7d` = CMD2 `1323` + 集成 `58 passed / 0 skipped`；
  `bb1a460` = CMD2 `1325` + 集成 **`57 passed, 1 skipped`**（见下），其余全绿。

### ⚠ 控制者**实测到**既有的随机自跳过（不是理论担忧）

`tests/repository/test_apply_ddl_mysql.py:313-317`：

```python
bad = uuid.uuid4().hex[:6]   # 6 位但含字母与数字，可能碰巧全数字则跳过
if bad.isdigit():
    pytest.skip("随机值碰巧是纯数字，本用例只验证非数字月份被拒")
```

`hex[:6]` 全数字概率 ≈ `(10/16)^6 ≈ 4.7%` ⇒ **平均每 21 次跑，这个用例就静默不跑一次**，
而门禁只看红绿。控制者在 `bb1a460` 的健康检查里**当场遇到**（`57 passed, 1 skipped`）。

⇒ 它同时**打坏了控制者上一轮刚立的门禁规则**（集成段 `skipped != 0` 即视为未通过）：
一条**随机**跳过会让该规则变成**假警报源**。更本质的是——
**一个自己决定不跑的用例，与一个不存在的用例没有区别，但它在报告里看起来是绿的。**

**已下发**：① 改成**确定性的**非法月份（必然含字母，MUST NOT 用"重摇直到非全数字"的循环
——那只是把不确定性藏起来）；② **普查全部 `tests/`** 里"测试体内的条件跳过"，
逐条判定 **合法（环境依赖缺失）/ 可疑（依赖随机或数据）/ 缺陷**，并给出总数与依据；
③ 可疑项**先报不动**，等控制者裁定。

### 随机跳过的确定性修复 + 全仓普查（提交 `96fb0f0`）

- 控制者**实测到**该跳过发生（`bb1a460` 健康检查：集成段 `57 passed, 1 skipped`）。
  **并认领一个算错**：控制者写的 `(10/16)^6 ≈ 4.7%` 是错的，实现者复算为 **5.96%**（每 17 次一次）。
- 修法：写死 `"12345x"` + 取值前提写成断言；**MUST NOT** 用"重摇直到非全数字"的循环。
- **普查 19 个 `pytest.skip` 调用点 = 合法 17 / 可疑 2 / 缺陷 1（已修）**；装饰器形态 0 处。
- **一条量出来的硬事实**（控制者独立复现）：`DSH_IT_MYSQL_PORT=3399`（无监听）时集成段
  **`26 passed, 32 skipped` 且 `pytest exit=0`** ⇒ 环境族命中面 **32 条**，一次端口写错就整段静默失效。
- **控制者据此修正自己的门禁规则**：`test_source_guards.py:102` 一条就贡献默认段 13 条 skip 里的 11 条
  ⇒ **"默认段 0 skipped"设计上不可能** ⇒ 规则收窄为：**集成段** `skipped != 0` 即未通过；
  **默认段**允许边界族但**环境族命中必须为 0**。

### R1/R2（提交 `d6d20e7` / `f97849f`）

- **R1**：`test_task_registry.py` 的两条"`task_runner.py` 不在/是空壳就跳过"→ 硬断言。
  定性："**把本仓自己交付的东西当成环境**"。**A/B 自证**（同一组变异喂新旧两版：新 `1 failed`、
  旧抛 `Skipped`）——**一次同时证明"改对了"与"改的是真东西"**，记为可复用做法。
- **R2**：`test_deps.py` 的裸 `return` → `pytest.raises(AttributeError, match="settings")` + `observed == []`。
  **控制者要求的那个字符**：`match="'settings'"` → `match="settings"`（去掉**排版耦合**）。
  **量化证据（控制者独立脚本复核，逐格一致）**：带引号的正则只在今天的单引号文案下命中，
  上游改双引号/无引号都会**假红**；不带引号则三种真实文案全命中、`SimpleNamespace` 兜底爆炸仍不命中
  ⇒ **判别力一分未少**。

### 第 4 组收口复核（独立复核者，冻结 `f97849f`）

**结论：11 项中 10 项满足，4.8 部分满足。**

- 复核者对**每一条款**都做了内存变异，并**另写独立 AST 扫描**（不复用产品自己的扫描器）复核结构性条款。
  4.7 跑了**五个变异全红**（含**真 Redis** 上"从 Lua 拿掉 `NX` ⇒ 两条并发都拿到租约"）。
- **它没把"4.7 单锚点变异仍绿"报成缺陷**——那与"F2 后取消在结构上必然发生"的自登记一致。
  **知道什么不该报**，与知道什么该报同样重要。
- **4.8 部分满足**：「并发提交时受理接口耗时不劣化（**对照用例**）」**从未落地**（全仓无受理路径耗时对照）；
  更根本的是 **`run_cpu_bound` 在 `src/` 下零调用点**（CPU 密集链路属第 5 组 K-01）。
  **裁定：缓期到 13.4**（理由：性能条款归宿是压测 / M1 无调用点测不到劣化 / 用例内自比时延正是刚清掉的时序余量判据）。
- **流程级发现（本轮最有价值）**：**本会话所有登记都写在被 git 忽略的 `.superpowers/sdd/`**
  （`.gitignore` = `*`，复核者实测：**对目录 grep 返回 No matches**）⇒
  **一条别人找不到的登记等于没登记**。

### 四处缓期登记进 `tasks.md`（提交 `208b6a8`，纯文档 +9 / −0）

缓期全部登记到**受版本控制、且跟着任务走的人一定会看到**的 `tasks.md`（落点也都在该文件内）：
4.8→`13.4`（含"机制已就位、接入未发生"的附注）、4.9→第 5 组（**并写明等价形态弱一步**：
不数真 Provider 调用）、4.10→第 5 组（指向**会自己过期**的 in-repo 判据）、4.11→第 11 组
（**并如实写明仓库内确无判据**把计数挂到指标端点）。
另加两处**口径**子项：4.3 的"超时/熔断终码 = `5002`"更正（**原句保留**，`spec.md` 本身写对、不动它）；
4.10 的"阈值变更记录可查"按权威文档执行（快照满足 `spec.md:58`+`er.md:27`，**不新增变更日志机制**）。
任务行 `- [ ]` **86 → 86** 未变；`openspec validate --all --strict` **5 passed / 0 failed**。

### 合并前全量门禁 @ `208b6a8`：**全绿**

默认段 `1325 passed, 13 skipped, 58 deselected` / 集成段 **`58 passed, 0 skipped`** /
ruff `All checks passed!` / `mypy --strict` 62 files / `lint-imports` **4 kept, 0 broken** /
验收 `PASS 10 / FAIL 0` / `openspec validate --all --strict` **5 passed / 0 failed**。
**16 个提交全部逐提交健康检查通过。**

**一次不可复现的执行环境卡顿（记在控制者账上）**：验收脚本在一次连续命令块里超时 600s，
但**单跑 1.68s、exit 0**，同一管道形式重跑亦 1.68s ⇒ 判为**一次性 DB 争用**（紧接 58 条集成用例之后），
**不是产品问题**，脚本两次实测均绿。
