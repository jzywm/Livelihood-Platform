# Review package 37aa77b..HEAD

## Commits

780ba42 docs(aicore): 记录虚拟环境 UTF-8 前置与重建步骤
2b5f635 fix(aicore): 收窄 Ruff 易混字符豁免并补齐 anyio 开发依赖

## Stat

 services/aicore/VENV.md        | 51 ++++++++++++++++++++++++++++++++++++++++++
 services/aicore/pyproject.toml | 18 +++++++++++----
 2 files changed, 65 insertions(+), 4 deletions(-)

## Diff

```diff
diff --git a/services/aicore/VENV.md b/services/aicore/VENV.md
new file mode 100644
index 0000000..7e9a9a2
--- /dev/null
+++ b/services/aicore/VENV.md
@@ -0,0 +1,51 @@
+# AICORE 虚拟环境（.venv）
+
+本目录是**本地开发环境，不入库**（已被 `.gitignore` 覆盖）。本文件说明如何在本机正确重建它，
+以及一个必须遵守的编码前置。
+
+## 一、为什么必须激活后才用（编码前置）
+
+本机 Windows 的 ANSI 代码页是 **936（GBK）**。Python 仅在 `PYTHONUTF8=1` 时才进入 UTF-8 模式；
+否则 `Path.write_text()`、`open()`、子进程文本管道全部退回 **cp936**，中文源码与文档会被写成
+GBK 字节，随后出现乱码、以及 Ruff 报 `stream did not contain valid UTF-8`。
+
+实测（写「中文测试」的实际字节）：
+
+| 状态 | utf8_mode | 首选编码 | 写入字节 |
+|---|---|---|---|
+| 未激活（无 `PYTHONUTF8`） | `0` | `cp936` | `D6 D0 CE C4 B2 E2 CA D4`（GBK，**错误**） |
+| 激活 `\.venv\Scripts\activate.ps1` | `1` | `utf-8` | `E4 B8 AD E6 96 87 …`（UTF-8，正确） |
+
+因此：**任何 Python / pip / pytest / ruff / mypy 命令，都先在已激活该 venv 的 shell 中执行。**
+
+```powershell
+# 每个新 shell 先做这一步
+. D:\progrom\services\aicore\.venv\Scripts\activate.ps1
+```
+
+激活脚本已内置 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8` 的注入与成对还原
+（`deactivate` 会清掉它们），**不依赖用户级环境变量**，换机器 / CI 同样成立。
+
+> 解释器启动后再改 `sys.flags.utf8_mode` 是无效的（该属性只读，实测 `AttributeError: readonly attribute`），
+> 所以只能在启动前注入——这是唯一可行的机制。
+
+## 二、重建步骤
+
+```powershell
+$root = "D:\progrom\services\aicore"
+python -m venv "$root\.venv"
+. "$root\.venv\Scripts\activate.ps1"          # 必须先激活（见上）
+python -m pip install -e "$root[dev]"          # 装运行 + 开发依赖，并把 aicore 装为可编辑包
+python -c "import aicore; print(aicore.__version__)"   # 期望输出 0.1.0
+python -m pytest --collect-only -q              # 期望 exit 5（当前尚无用例）且无导入错误
+```
+
+## 三、已知环境约束
+
+- **pip 在受限沙箱下会失败**：它需要创建 `0700` 权限的临时目录，若沙箱禁止写入该类目录，
+  会报 `PermissionError: [Errno 13]`。此时需以更高权限重试该条命令，不要改用其他方式绕过。
+- **不要把本目录改名**：`Scripts\*.exe` 控制台脚本内嵌创建时的绝对路径
+  （实测 `lint-imports.exe`、`pytest.exe` 含旧路径），改名后这些工具会失效。
+  需要换路径时**新建**环境，不要移动。
+- **避免在仓库内留下缓存**：建议为 Python 调用设置 `PYTHONPYCACHEPREFIX` 到本目录下，
+  pytest 加 `-p no:cacheprovider`，ruff 加 `--no-cache`，mypy 用本目录内的 `--cache-dir`。
diff --git a/services/aicore/pyproject.toml b/services/aicore/pyproject.toml
index e1b7236..dc74f98 100644
--- a/services/aicore/pyproject.toml
+++ b/services/aicore/pyproject.toml
@@ -23,35 +23,45 @@ dependencies = [
 ]

 [project.optional-dependencies]
 dev = [
     "pytest>=9.1",
     "pytest-asyncio>=1.4",
     "pytest-cov>=7.1",
     "import-linter>=2.15",
     "ruff>=0.16",
     "mypy>=2.3",
+    # tests/conftest.py 的 anyio_backend 夹具是 brief 强制项；
+    # anyio 此前只是 pytest-asyncio 的传递依赖，显式声明后夹具才有直接的依赖归属（Task 1.4 继续扩展该文件）。
+    "anyio>=4.15",
 ]

 [tool.setuptools.packages.find]
 where = ["src"]

 [tool.ruff]
 line-length = 100
 target-version = "py312"

 [tool.ruff.lint]
 select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "RUF"]
-# 注释与文档使用中文是本仓库的强制要求（DEVELOPMENT_CONSTRAINTS.md §2），
-# 而 RUF001/RUF002/RUF003 会把中文全角标点（：；，等）判为「歧义字符」并报错。
-# 关闭这三条，使 Ruff 与中文文档策略相容；其余 RUF 规则保持开启。
-ignore = ["RUF001", "RUF002", "RUF003"]
+# 注释与文档使用中文是本仓库的强制要求（DEVELOPMENT_CONSTRAINTS.md §2）。
+# 注意：不要用 ignore 关闭 RUF001/RUF002/RUF003 —— 那会连带关掉字符串字面量里的
+# 易混字符检测，而那里才是该规则安全价值最高的地方（西里尔字母 а、全角数字
+# 悄悄混进环境变量名 / 字典键 / 断言字符串时，只有这三条规则能发现）。
+# 因此改为逐个放行中文文档实际用到的全角标点，规则本身全部保持开启：
+#   （ U+FF08 全角左括号    ） U+FF09 全角右括号
+#   ： U+FF1A 全角冒号      ； U+FF1B 全角分号
+# 本集合由 ruff check --output-format=json 实测得出（本仓库当前仅这 4 个字符触发），
+# 它们只出现在中文注释与 docstring 中，不参与标识符与键值，放行无安全代价。
+# 后续若中文文档引入新的全角标点（如「，」U+FF0C），应在本行按需追加，而非改回 ignore。
+allowed-confusables = ["（", "）", "：", "；"]

 [tool.mypy]
 python_version = "3.12"
 strict = true
 files = ["src"]

 [[tool.mypy.overrides]]
 module = ["tests.*"]
 strict = false


```
