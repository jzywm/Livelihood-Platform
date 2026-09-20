### Task 2.5: traceId 上下文传播

**Files:**
- Modify: `services/aicore/src/aicore/core/trace.py`
- Modify: `services/aicore/src/aicore/main.py`（挂中间件）
- Create: `services/aicore/tests/unit/test_trace.py`

**Interfaces:**
- Consumes: 无
- Produces: `TRACE_ID_HEADER = "X-Request-Id"`；`get_trace_id() -> str`；
  `set_trace_id(value: str) -> None`；`new_trace_id() -> str`（16 位 hex）；
  `TraceIdMiddleware`（ASGI 中间件）；`copy_context_for_thread()`（跨线程池传递用）

**硬约束**：请求头是 **`X-Request-Id`**（不是 `X-Trace-Id`）；网关未注入时**自行生成**且该行为
**在日志中可区分**（加标记字段），以免掩盖网关故障；**跨线程池（`run_in_executor`）必须显式传递**
——丢失 traceId 是典型的静默故障。

- [ ] Step 1~N：先写「注入 → 透传」「未注入 → 自行生成且可区分」两条用例，
  再写「跨线程池后仍能取到同一 traceId」用例

**验收**：两条路径用例通过；跨线程池用例通过；生成行为在日志字段中可区分
