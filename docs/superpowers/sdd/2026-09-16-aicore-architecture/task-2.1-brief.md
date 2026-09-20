### Task 2.1: 配置模型

**Files:**
- Modify: `services/aicore/src/aicore/core/config.py`
- Modify: `services/aicore/src/aicore/api/deps.py`（`get_settings` 定类型）
- Create: `services/aicore/tests/unit/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `aicore.core.config.Settings`（Pydantic `BaseSettings` 子类，`env` 为 `dev|test|prod`）；
  `aicore.core.config.get_settings() -> Settings`（带缓存）；`Settings` 字段名与 `.env.example` 的 `AICORE_` 前缀变量一一对应

**关键取向**：必填项**不给默认值**（默认值会把配置错误隐藏到运行时）；`extra="forbid"`（写了不存在的项要报错）。

- [ ] Step 1~N：先写失败用例（字段级校验：必填缺失即抛 `ValidationError`），再实现 `Settings`，
  再验证 `grep` 无硬编码密钥、`.env` 被 `.gitignore` 覆盖

**验收**：配置加载用例通过；缺失必填项抛错；不存在配置项抛错；`get_settings()` 返回同一实例（缓存）
