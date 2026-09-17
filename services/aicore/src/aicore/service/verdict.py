"""C8 权威回写前置条件。

【合规红线 D5 / C8】无人工复核结论则 MUST NOT 存在回写入口，MUST NOT 出现绕过
人工结论的回写分支——本文件受 tests/structural/test_source_guards.py 的 AST 扫描强制。
确需吞掉异常时，必须在该 except 行加 `# noqa: ai-allow-swallow: <理由>` 显式豁免。

第 8 组实现具体校验；本任务仅建文件以保证结构检查从第一天起生效。
"""
