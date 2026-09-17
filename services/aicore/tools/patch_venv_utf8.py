"""为 venv 的 activate.ps1 打 UTF-8 补丁（幂等，可重复执行）。

用途
----
本机 Windows 的 ANSI 代码页为 936（GBK），Python 仅在 ``PYTHONUTF8=1`` 时进入
UTF-8 模式；否则 ``Path.write_text`` / ``open`` / 子进程文本管道退回 cp936，
中文源码与文档会被写成 GBK 字节并产生乱码。

``PYTHONUTF8`` 必须在解释器**启动前**生效：``sys.flags.utf8_mode`` 启动后只读
（实测 ``AttributeError: readonly attribute``），``sitecustomize.py`` 也改不动它。
因此补丁只能落在启动脚本上——即 venv 的 ``activate.ps1``。

用法
----
    python services/aicore/tools/patch_venv_utf8.py <venv_dir>

    # 例（$root 为本服务目录）：
    python "$root\\tools\\patch_venv_utf8.py" "$root\\.venv"

退出码：0 成功（含「已打过补丁」）；2 参数或目标文件缺失；3 补丁结构异常。
"""

from __future__ import annotations

import pathlib
import sys

MARKER = "AICORE 追加：强制本虚拟环境使用 UTF-8"

INJECT = """\
# {marker}。
# 本机 Windows 的 ANSI 代码页为 936（GBK），Python 仅在 PYTHONUTF8=1 时进入 UTF-8 模式，
# 否则 Path.write_text / open() / 子进程文本管道均退回 cp936，中文源码与文档会被写成 GBK
# 字节并产生乱码。此处随激活注入，使该 venv 的语义不依赖外部用户级环境变量。
# 注意：解释器启动后再改 sys.flags.utf8_mode 无效（只读），必须在启动前注入。
foreach ($_v in @('PYTHONUTF8', 'PYTHONIOENCODING')) {
    if (Test-Path -Path "Env:$_v") {
        Copy-Item -Path "Env:$_v" -Destination "Env:_OLD_VIRTUAL_$_v"
    }
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
""".replace("{marker}", MARKER)

RESTORE = """\
    # 还原 UTF-8 相关变量（AICORE 追加）
    foreach ($_v in @('PYTHONUTF8', 'PYTHONIOENCODING')) {
        $old = "Env:_OLD_VIRTUAL_$_v"
        if (Test-Path -Path $old) {
            Copy-Item -Path $old -Destination "Env:$_v"
            Remove-Item -Path $old
        }
        else {
            Remove-Item -Path "Env:$_v" -ErrorAction SilentlyContinue
        }
    }
"""

DEACTIVATE_ANCHOR = "    # Just remove VIRTUAL_ENV_PROMPT altogether.\r\n"
PATH_ANCHOR = (
    '$Env:PATH = "$VenvExecDir$([System.IO.Path]::PathSeparator)$Env:PATH"\r\n'
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    venv = pathlib.Path(sys.argv[1])
    target = venv / "Scripts" / "activate.ps1"
    if not target.is_file():
        print(f"找不到 {target}", file=sys.stderr)
        return 2

    raw = target.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")

    if MARKER in text:
        print(f"已打过补丁，跳过：{target}")
        return 0

    # 换行风格必须原样保留：Windows PowerShell 5.1 解析以 LF 结尾的 .ps1 会报
    # Unexpected token，故不能想当然写成 \n（本文件原始为 CRLF）。
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    newline = "\r\n" if crlf >= lf_only else "\n"

    if DEACTIVATE_ANCHOR not in text:
        print("补丁锚点 1 缺失（deactivate 结构不匹配），中止", file=sys.stderr)
        return 3
    text = text.replace(DEACTIVATE_ANCHOR, DEACTIVATE_ANCHOR + RESTORE.replace("\n", newline), 1)

    if PATH_ANCHOR not in text:
        print("补丁锚点 2 缺失（activate 末尾 PATH 块不匹配），中止", file=sys.stderr)
        return 3
    # 追加到文件最末尾，确保 PATH 设置仍在原位置、注入位于最后
    text = text.replace(PATH_ANCHOR, PATH_ANCHOR, 1)
    inject = "\n" + INJECT.replace("\n", newline)
    if not text.endswith(newline):
        text += newline
    text += inject

    target.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    print(f"已打补丁：{target}（换行风格 {newline!r}，BOM={bom}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
