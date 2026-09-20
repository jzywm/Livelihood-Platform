# Review package 305112d..b5c5c7d

## Commits

b5c5c7d fix(aicore): 补齐红线豁免约定并修正契约与测试包指向

## Stat

 services/aicore/src/aicore/__init__.py        | 2 +-
 services/aicore/src/aicore/core/__init__.py   | 2 +-
 services/aicore/src/aicore/provider/base.py   | 2 +-
 services/aicore/src/aicore/service/verdict.py | 9 ++++++++-
 services/aicore/tests/structural/__init__.py  | 0
 5 files changed, 11 insertions(+), 4 deletions(-)

## Diff

```diff
diff --git a/services/aicore/src/aicore/__init__.py b/services/aicore/src/aicore/__init__.py
index 2b8e799..e925b8b 100644
--- a/services/aicore/src/aicore/__init__.py
+++ b/services/aicore/src/aicore/__init__.py
@@ -1,8 +1,8 @@
 """AI 能力中心服务（AICORE）· 民生甄选平台。

 分层：core（横切）/ api（协议适配）/ service（业务编排）/ provider（外部模型通道）
      / repository（自有库访问）/ port（跨服务出向端口）。
-分层依赖规则见 setup.cfg 的 import-linter 契约与 tests/structural/。
+分层依赖规则见 .importlinter 的 import-linter 契约与 tests/structural/。
 """

 __version__ = "0.1.0"
diff --git a/services/aicore/src/aicore/core/__init__.py b/services/aicore/src/aicore/core/__init__.py
index f3d6eea..0ac1ac1 100644
--- a/services/aicore/src/aicore/core/__init__.py
+++ b/services/aicore/src/aicore/core/__init__.py
@@ -1 +1 @@
-"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 setup.cfg 契约）。"""
+"""横切关注点。本层 MUST NOT 依赖 service / provider / repository（见 .importlinter 契约）。"""
diff --git a/services/aicore/src/aicore/provider/base.py b/services/aicore/src/aicore/provider/base.py
index ab72412..6e1d2d4 100644
--- a/services/aicore/src/aicore/provider/base.py
+++ b/services/aicore/src/aicore/provider/base.py
@@ -1,14 +1,14 @@
 """外部模型通道 Protocol。

 service 层 MUST 只依赖本文件的 Protocol，MUST NOT 导入任何具体实现
-（mock / deepseek / cloud_vision / cloud_ocr）——由 setup.cfg 的 import-linter 契约强制。
+（mock / deepseek / cloud_vision / cloud_ocr）——由 .importlinter 的 import-linter 契约强制。
 """

 from __future__ import annotations

 from typing import Any, Protocol, runtime_checkable


 @runtime_checkable
 class TextProvider(Protocol):
     """文本模型通道。"""
diff --git a/services/aicore/src/aicore/service/verdict.py b/services/aicore/src/aicore/service/verdict.py
index 0cb544a..c7b0199 100644
--- a/services/aicore/src/aicore/service/verdict.py
+++ b/services/aicore/src/aicore/service/verdict.py
@@ -1 +1,8 @@
-"""C8 权威回写前置条件：无人工复核结论则不存在回写入口。第 8 组实现。"""
+"""C8 权威回写前置条件。
+
+【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过
+人工结论的回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
+确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。
+
+第 8 组实现具体校验；本任务仅建文件以保证结构检查从第一天起生效。
+"""
diff --git a/services/aicore/tests/structural/__init__.py b/services/aicore/tests/structural/__init__.py
new file mode 100644
index 0000000..e69de29

```
