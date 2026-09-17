"""AI 能力中心服务（AICORE）· 民生甄选平台。

分层：core（横切）/ api（协议适配）/ service（业务编排）/ provider（外部模型通道）
     / repository（自有库访问）/ port（跨服务出向端口）。
分层依赖规则见 setup.cfg 的 import-linter 契约与 tests/structural/。
"""

__version__ = "0.1.0"
