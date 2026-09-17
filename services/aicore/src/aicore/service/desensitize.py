"""图像脱敏前置阶段。

【合规红线 D4 / R-03】脱敏失败或超时 MUST 拒绝外发，MUST NOT 出现「异常后继续执行」
的降级分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。

第 4 组实现具体算法；本任务仅建文件以保证结构检查从第一天起生效。
"""
