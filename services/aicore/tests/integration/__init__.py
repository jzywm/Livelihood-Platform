"""`tests/integration/` 是包（与 `tests/unit` / `tests/repository` / `tests/api` 同形）。

加 `__init__.py` 是为了让 `tests.integration.test_*` 的模块名稳定、可被
`-p no:cacheprovider` 之外的工具（如 IDE / `--import-mode=importlib`）一致地解析。
它在 `tests/` 这一层已有先例（`tests/__init__.py` 等），故不引入新的约定。
"""
