# AICORE 虚拟环境（.venv）

本目录是**本地开发环境，不入库**（已被 `.gitignore` 覆盖）。本文件说明如何在本机正确重建它，
以及一个必须遵守的编码前置。

## 一、为什么必须激活后才用（编码前置）

本机 Windows 的 ANSI 代码页是 **936（GBK）**。Python 仅在 `PYTHONUTF8=1` 时才进入 UTF-8 模式；
否则 `Path.write_text()`、`open()`、子进程文本管道全部退回 **cp936**，中文源码与文档会被写成
GBK 字节，随后出现乱码、以及 Ruff 报 `stream did not contain valid UTF-8`。

实测（写「中文测试」的实际字节）：

| 状态 | utf8_mode | 首选编码 | 写入字节 |
|---|---|---|---|
| 未激活（无 `PYTHONUTF8`） | `0` | `cp936` | `D6 D0 CE C4 B2 E2 CA D4`（GBK，**错误**） |
| 激活 `\.venv\Scripts\activate.ps1` | `1` | `utf-8` | `E4 B8 AD E6 96 87 …`（UTF-8，正确） |

因此：**任何 Python / pip / pytest / ruff / mypy 命令，都先在已激活该 venv 的 shell 中执行。**

```powershell
# 每个新 shell 先做这一步（把 <repo> 换成本次使用的检出根目录）
. <repo>\services\aicore\.venv\Scripts\activate.ps1
```

激活脚本已内置 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8` 的注入与成对还原
（`deactivate` 会清掉它们），**不依赖用户级环境变量**，换机器 / CI 同样成立。

> 注意：**刚 `python -m venv` 建出来的环境还没有这段注入**（标准 venv 不会写它）。
> 必须按下面 §二 的第 2 步打一次补丁，否则「激活即可用」这条前提不成立。

> 解释器启动后再改 `sys.flags.utf8_mode` 是无效的（该属性只读，实测 `AttributeError: readonly attribute`），
> 所以只能在启动前注入——这是唯一可行的机制。

## 二、重建步骤

> 下例中 `$root` 指**本服务目录**，即 `<repo>\services\aicore`。

```powershell
$root = "<repo>\services\aicore"

# 1) 建环境
python -m venv "$root\.venv"

# 2) 打 UTF-8 补丁（幂等：已在则跳过）
python "$root\tools\patch_venv_utf8.py" "$root\.venv"

# 3) 之后每次使用前先激活；激活后才装依赖与跑命令
. "$root\.venv\Scripts\activate.ps1"
python -m pip install -e "$root[dev]"          # 装运行 + 开发依赖，并把 aicore 装为可编辑包
python -c "import aicore; print(aicore.__version__)"   # 期望输出 0.1.0
python -m pytest --collect-only -q              # 期望 exit 5（当前尚无用例）且无导入错误
```

补丁脚本**保留原文件的换行风格**（Windows 的 `activate.ps1` 为 CRLF）——这一点很关键：
Windows PowerShell 5.1 解析以 LF 结尾的 `.ps1` 会报 `Unexpected token '}'`，激活会静默失败。
脚本同时保留原 BOM 状态，并以 UTF-8 落盘。

**为什么第 2 步不能用「装个包」解决**：`PYTHONUTF8` 必须在解释器启动前生效，
而 `sys.flags.utf8_mode` 启动后只读、`sitecustomize.py` 也改不动它（两者均已实测），
所以补丁只能落在**启动脚本**上——即 venv 的 `activate.ps1`。

## 三、已知环境约束

- **pip 在受限沙箱下会失败**：它需要创建 `0700` 权限的临时目录，若沙箱禁止写入该类目录，
  会报 `PermissionError: [Errno 13]`。此时需以更高权限重试该条命令，不要改用其他方式绕过。
- **不要把本目录改名**：`Scripts\*.exe` 控制台脚本内嵌创建时的绝对路径
  （实测 `lint-imports.exe`、`pytest.exe` 含旧路径），改名后这些工具会失效。
  需要换路径时**新建**环境，不要移动。
- **避免在仓库内留下缓存**：建议为 Python 调用设置 `PYTHONPYCACHEPREFIX` 到本目录下，
  pytest 加 `-p no:cacheprovider`，ruff 加 `--no-cache`，mypy 用本目录内的 `--cache-dir`。
