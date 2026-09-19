"""`GET /aicore/tasks/{taskId}` 契约用例。Task 4.5 §3 的第 18~24 条。

## 造状态为什么必须直接改库

本任务的提交接口只受理 OCR（受理态固定 `PROCESSING`），终态由 Task 4.7 的执行器写入。
要覆盖「终态怎么渲染」，用例只能**绕过接口**把行改成 `SUCCEEDED` / `FAILED`，
或把 `account_id` 改成别人——否则这一组断言永远跑不到终态分支
（本项目反复出现的形态：用例把关键环节替成了桩，于是那一环永远不会有红灯）。

改库用**裸 SQL 打在物理表名上**，而不是经仓储：用被测代码自己的读路径去验它自己的读路径，
同一个缺陷会在两侧同时成立。

## 时间

与 `test_ocr_submit.py` 同口径：沙盒只有 `ai_task_202607` / `ai_task_202608`，
故统一把时钟钉在 2026-07（`api/deps.py::get_now` 的注入点）。
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from aicore.api.deps import ACCOUNT_ID_HEADER, get_now
from aicore.api.tasks import DECLARED_STATUSES, TaskResult
from aicore.core.idgen import new_id
from aicore.service.task.state import ALL_STATUSES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI = PROJECT_ROOT / "docs" / "openapi.yaml"
TASKS_PY = PROJECT_ROOT / "src" / "aicore" / "api" / "tasks.py"
OCR_PY = PROJECT_ROOT / "src" / "aicore" / "api" / "ocr.py"

ACCOUNT_ID = "acc_poll_owner"
OTHER_ACCOUNT_ID = "acc_poll_other"
JULY = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
#: 「跨月轮询」用例用的**另一个月**：任务在 7 月、轮询时刻在 10 月（相隔 3 个月，跨了季度）。
#: 刻意让沙盒里**没有** `ai_task_202610` 这张表：若实现退回"用 now 算月"，
#: 用例会以 `no such table` 失败（带判定力），而不是"恰好查到 0 行"。
OCTOBER = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)

#: 直接写库时的终态完成时间（**字符串**：裸 `text()` 绑定把 `datetime` 交给 sqlite3 会报
#: `InterfaceError`——驱动只认 str/int/float/bytes/None）。
FINISHED_AT_TEXT = "2026-07-15 10:31:00.000000"
#: 上面那个值按 UTC 渲染出来的契约形状（`_utc_iso` 的口径）。
FINISHED_AT_ISO = "2026-07-15T10:31:00Z"


class _Clock:
    """可注入时钟（`api/deps.py::get_now` 的替身）。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(api_client: TestClient) -> _Clock:
    """把路由的时间源钉进沙盒有表的那个月。

    **注意**：v1.3 之后分片月**不再**由 `now` 现算（改由 `task_id` 内嵌的月份决定），
    故本夹具的作用缩小为「让提交接口生成 7 月的 `task_id` 并落进 7 月表」——
    它仍是必要的（`submit.py` 用 `now` 同时算分片与 ID），但**不再是分片月的来源**。
    """
    holder = _Clock(JULY)
    api_client.app.dependency_overrides[get_now] = holder
    return holder


def _submit(client: TestClient, *, user: str = ACCOUNT_ID) -> str:
    """经**真接口**提交一个 OCR 任务，返回任务号（轮询用例的前置条件）。"""
    response = client.post(
        "/aicore/ocr",
        json={"imageKey": "cert/oss/2026/07/poll.jpg", "docType": "PERMIT"},
        headers={ACCOUNT_ID_HEADER: user},
    )
    assert response.status_code == 202, (
        f"前置提交失败（{response.status_code}）：{response.text[:200]}"
    )
    task_id: str = response.json()["data"]["taskId"]
    return task_id


def _get(client: TestClient, task_id: str, *, user: str = ACCOUNT_ID) -> Response:
    return client.get(f"/aicore/tasks/{task_id}", headers={ACCOUNT_ID_HEADER: user})


def _set_task_columns(engine: Engine, task_id: str, **values: Any) -> None:
    """直接改库（不经接口、不经仓储）：造终态与「别人的账号」。"""
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(
            text(f"update ai_task_202607 set {assignments} where task_id = :task_id"),
            {**values, "task_id": task_id},
        )


def test_poll_finds_a_task_created_in_an_earlier_month(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """**本变更的核心证据（`er.md` §5.4 v1.3）**：上月提交的任务，下月仍能轮询到。

    ## 这条用例在修好之前必然红（这就是它的价值）

    改之前，分片月由**当前时刻**现算，于是「本月表查不到」无法区分
    「任务不存在」与「任务在上月的表里」——上月 23:59:59 提交、次月 00:00:01 轮询即 404。
    而逐月试探扫描被 `er.md` §5.3「查询 MUST 携带分片键下推、禁止跨分片」禁止。

    改之后，月份从 `task_id` 自身解析（`task_` + `YYYYMM` + …），故：
    **`now` 落在 10 月，而任务在 7 月——仍能查到，且只查 7 月那一张表。**

    ## 构造方式与"为什么这样构造"

    直接往沙盒的 `ai_task_202607` 插一行（`task_id` 用 `at=JULY` 生成），
    **不**经提交接口：提交接口会用注入时钟的月份生成 `task_id`，
    那样"任务所在月"与"提交时刻"就是同一个值，**构造不出跨月场景**。
    把 `now` 钉在 10 月（`OCTOBER`）后，`_get` 走的仍是真路由。

    **一个刻意的细节**：沙盒里**没有** `ai_task_202610` 这张表，
    故若实现退回"用 now 算月"，本用例会以 `no such table`（500）失败——
    这正是我们要的判定力，而不是"恰好查到 0 行"。
    """
    task_id = _insert_task_row(sandbox_engine, account_id=ACCOUNT_ID, at=JULY)

    clock.now = OCTOBER
    response = _get(api_client, task_id)

    assert response.status_code == 200, (
        f"上月创建的任务在次月轮询失败（HTTP {response.status_code}）：{response.text[:300]}\n"
        f"分片月必须从 task_id 里解析（er.md §5.4 v1.3），MUST NOT 用当前时刻现算"
    )
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["taskId"] == task_id
    assert body["data"]["status"] == "PROCESSING"


def test_poll_rejects_a_malformed_task_id(
    api_client: TestClient, clock: _Clock
) -> None:
    """`taskId` 形态非法 → `400` + `1003`，**MUST NOT** 报成 `404`（对象不存在）。

    依据与分工：`service/task/query.py::load_owned_task` 对解不出月份的 `task_id`
    抛 `ParamError(1003)`（枚举或范围非法）——「你给的任务号不是任务号」是**入参格式错误**，
    报 404 会让调用方以为"任务丢了"，从而去重试或告警，而真正该做的是改调用参数。

    这里用旧格式（`task_` + 27 位 hex，**长度也是 32**）作为样例：
    它正是本变更之前的形态，若判据漏了月份段，它会以"长度合法"的方式被放行，
    然后路由到一张用当前月算出来的表——即本变更要修的原始缺陷。
    """
    legacy = "task_" + "9f2e7c1a3b4d5e6f7a8b9cdef01"

    response = _get(api_client, legacy)

    assert response.status_code == 400, (
        f"非法任务号应回 400（入参格式错误），实际 {response.status_code}：{response.text[:200]}"
    )
    assert response.json()["code"] == 1003


def _insert_task_row(
    engine: Engine, *, account_id: str, at: datetime, status: str = "PROCESSING"
) -> str:
    """往沙盒的 `ai_task_<at 所在月>` 直接插一行，返回 `task_id`。

    用 `at` 生成 `task_id`（月份内嵌其中）并写进**同一个月**的表——
    这样"行所在月"与"ID 里的月份"一致，正是生产上的不变式
    （`submit.py` 用同一个 `now` 同时算分片与 ID，见 `new_task` 的 docstring）。
    """
    task_id = new_id("task", at=at)
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into ai_task_202607 "
                "(task_id, account_id, idem_key, type, status, progress, "
                " error_code, model_meta, is_eval_sample, created_at, finished_at) "
                "values (:task_id, :account_id, null, 'OCR', :status, 0, "
                " null, null, 0, :created_at, null)"
            ),
            {"task_id": task_id, "account_id": account_id, "status": status, "created_at": at},
        )
    return task_id


def _openapi_task_result() -> dict[str, Any]:
    """**现读** `docs/openapi.yaml` 的 `TaskResult`（期望值 MUST NOT 抄成常量）。"""
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    schema: dict[str, Any] = spec["components"]["schemas"]["TaskResult"]
    return schema


def test_processing_task_polls_with_empty_result(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 18 条：`PROCESSING` 任务轮询 → `200` + `result` / `errorCode` / `finishedAt` 全空。

    `openapi.yaml:806` 逐字「PROCESSING 时为空，FAILED 时为空」；
    `progress` 此时是 `0`（提交时写的就是 0），`createdAt` 是受理时刻的 UTC ISO 8601。
    """
    task_id = _submit(api_client)

    response = _get(api_client, task_id)

    assert response.status_code == 200, f"轮询失败：{response.text[:200]}"
    assert response.json()["code"] == 0
    data = response.json()["data"]
    assert data["taskId"] == task_id
    assert data["type"] == "OCR"
    assert data["status"] == "PROCESSING"
    assert data["progress"] == 0
    assert data["result"] is None
    assert data["errorCode"] is None
    assert data["finishedAt"] is None
    assert data["createdAt"] == "2026-07-15T10:30:00Z", (
        f"createdAt 应是注入时刻的 UTC ISO 8601：收到 {data['createdAt']!r}"
    )


def test_succeeded_task_reports_progress_and_finished_at(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 19 条：手工置为 `SUCCEEDED` 的任务 → `progress=100`、`finishedAt` 非空。

    终态由 Task 4.7 的执行器写入，这里直接改库构造（见模块 docstring）。
    `result` 仍为 `None`：`OcrResult` 的装配归 Task 5.6（本任务只做回执骨架）。
    """
    task_id = _submit(api_client)
    _set_task_columns(
        sandbox_engine, task_id, status="SUCCEEDED", progress=100, finished_at=FINISHED_AT_TEXT
    )

    data = _get(api_client, task_id).json()["data"]

    assert data["status"] == "SUCCEEDED"
    assert data["progress"] == 100
    assert data["finishedAt"] == FINISHED_AT_ISO
    assert data["result"] is None, "OcrResult 的装配属 Task 5.6：本任务边界内 result 为空"
    assert data["errorCode"] is None, "SUCCEEDED 不得带 errorCode"


def test_failed_task_reports_error_code_as_a_string(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 20 条：手工置为 `FAILED` 且 `error_code='4003'` → `errorCode == "4003"`（**字符串**）。

    `openapi.yaml:813` 逐字 `type: string`；`er.md` §6.1 L294 的列也是 `varchar(16)`。
    两层都是字符串，故 MUST NOT 出现 `4003`（数字）——数字形状会让前端按码表查不到。
    """
    task_id = _submit(api_client)
    _set_task_columns(
        sandbox_engine,
        task_id,
        status="FAILED",
        error_code="4003",
        finished_at=FINISHED_AT_TEXT,
    )

    data = _get(api_client, task_id).json()["data"]

    assert data["status"] == "FAILED"
    assert data["errorCode"] == "4003"
    assert isinstance(data["errorCode"], str), "errorCode 必须是字符串（openapi.yaml:813）"
    assert data["finishedAt"] == FINISHED_AT_ISO
    assert data["result"] is None, "FAILED 时 result 为空（openapi.yaml:806）"


def test_unknown_task_id_is_404_with_code_3006(
    api_client: TestClient, clock: _Clock
) -> None:
    """第 21 条：不存在的 `taskId` → `404` + `3006`（`openapi.yaml:140-141`）。

    任务号用 `new_id("task", at=...)` 现造：形态合法（前缀 + 月份 + 32 位）但库里必然没有，
    故「404」不是靠畸形输入换来的。
    """
    absent = new_id("task", at=datetime(2026, 7, 15, 10, 30, tzinfo=UTC))

    response = _get(api_client, absent)

    assert response.status_code == 404, f"不存在的任务号应回 404：{response.text[:200]}"
    body = response.json()
    assert body["code"] == 3006
    assert body["data"] is None


def test_cross_account_poll_is_403_and_leaks_nothing(
    api_client: TestClient, clock: _Clock
) -> None:
    """第 22 条：跨账号 → `403` + `2002`，且响应体**不含**任何任务字段。

    `spec.md:32-35` 逐字：「返回 `2002` **且不泄露该任务的任何结果内容**」，
    按最严解读处理：连 `status` / `progress` 都不给——能拿到状态就能推断出
    「这个 taskId 真实存在」，而持有人未必有权知道这件事。
    """
    task_id = _submit(api_client)  # 属于 ACCOUNT_ID

    response = _get(api_client, task_id, user=OTHER_ACCOUNT_ID)

    assert response.status_code == 403, f"跨账号应回 403：{response.text[:200]}"
    body = response.json()
    assert body["code"] == 2002
    assert body["data"] is None
    assert set(body) <= {"code", "message", "data", "traceId", "timestamp"}
    for field in (
        "taskId",
        "type",
        "status",
        "progress",
        "result",
        "errorCode",
        "createdAt",
        "finishedAt",
    ):
        assert f'"{field}"' not in response.text, (
            f"跨账号响应体里出现了 {field}（spec.md:35 要求不泄露任何内容）：{response.text}"
        )


def test_account_id_really_participates_in_the_filter(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 23 条：`account_id` 必须**真的**参与过滤——双向对照。

    做法：① 本人先查得到（证明行在）；② 把行的 `account_id` 直接改成别人的；
    ③ 本人再查 → `2002`；④ **对方**查同一个 taskId → `200`。
    第 ④ 步是关键：它排除「其实查不到」这种解释（若过滤没生效或行被改坏，
    ④ 会 404 而不是 200，于是这条用例就不会以"2002 恰好出现"收场）。
    """
    task_id = _submit(api_client)
    assert _get(api_client, task_id).status_code == 200, "前置：本人的任务本人应查得到"

    _set_task_columns(sandbox_engine, task_id, account_id=OTHER_ACCOUNT_ID)

    denied = _get(api_client, task_id)
    assert denied.status_code == 403, f"行已属于别人，本人查询应 403：{denied.text[:200]}"
    assert denied.json()["code"] == 2002

    allowed = _get(api_client, task_id, user=OTHER_ACCOUNT_ID)
    assert allowed.status_code == 200, (
        f"行确实存在且已属于 {OTHER_ACCOUNT_ID}：若这里 404，说明上面的 2002 其实是「查不到」"
        f"（{allowed.text[:200]}）"
    )
    assert allowed.json()["data"]["taskId"] == task_id


def test_response_fields_match_openapi_required_list(
    api_client: TestClient, clock: _Clock
) -> None:
    """第 24 条：出参字段集合**从 `openapi.yaml` 现读**比对（不抄常量）。

    三向比对：① 响应体覆盖 openapi 的 `required`；② 响应体没有契约外字段；
    ③ **模型自身**的必填集合恰好等于 openapi 的 `required`（多一个必填也会与契约不符，
    而只比响应体抓不到这件事——响应体里反正都会带上）。
    """
    schema = _openapi_task_result()
    required = set(schema["required"])
    properties = set(schema["properties"])
    assert required == {"taskId", "type", "status", "createdAt"}, (
        f"openapi 的 required 列表变了（现读结果）：{sorted(required)}"
    )

    task_id = _submit(api_client)
    data = _get(api_client, task_id).json()["data"]

    assert required <= set(data), f"响应体缺 openapi 声明的必填字段：{sorted(required - set(data))}"
    assert set(data) <= properties, f"响应体出现契约外字段：{sorted(set(data) - properties)}"

    model_required = {
        name for name, field in TaskResult.model_fields.items() if field.is_required()
    }
    assert model_required == required, (
        f"模型必填集合 {sorted(model_required)} 与 openapi 的 required {sorted(required)} 不一致"
    )


def test_response_enums_track_openapi_and_the_state_machine() -> None:
    """第 24 条的延伸：`type` / `status` 的取值域与权威来源一致。

    `api/tasks.py` 里的字面量是**被迫重抄**的（mypy 不接受 `Literal[PROCESSING]`），
    故这里用两道比对把抄件钉回权威：

    - `status` ↔ `service/task/state.py` 的四个常量（`ALL_STATUSES`）；
    - `type` ↔ **现读** `openapi.yaml` 的 `TaskType` 枚举。
    """
    schema = TaskResult.model_json_schema()
    defs = schema["$defs"]
    status_enum = set(defs["TaskStatusValue"]["enum"])
    type_enum = set(defs["TaskTypeValue"]["enum"])

    assert status_enum == ALL_STATUSES, (
        f"回执模型的 status 取值域 {sorted(status_enum)} 与状态机 {sorted(ALL_STATUSES)} 不一致"
    )
    assert set(DECLARED_STATUSES) == ALL_STATUSES, (
        "api/tasks.py 的 DECLARED_STATUSES 与 state.py 的状态集合漂移了"
    )
    openapi_type_enum = set(
        yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]["TaskType"][
            "enum"
        ]
    )
    assert type_enum == openapi_type_enum, (
        f"回执模型的 type 取值域 {sorted(type_enum)} 与 openapi 的 TaskType "
        f"{sorted(openapi_type_enum)} 不一致"
    )


def _called_session_entries(source: str) -> set[str]:
    """源码里**真正被调用**的会话入口方法名（AST 层，不看 docstring 里的示例文字）。"""
    entries: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write_session", "read_session", "primary_read_session"}
        ):
            entries.add(node.func.attr)
    return entries


def test_session_entries_match_the_declared_split() -> None:
    """会话选型（工单 §1.5 的硬要求）：提交用写会话、轮询用**主库只读**会话。

    行为层验不了这件事：sqlite 沙盒只有一个库，「主↔从」在那里没有对应物
    （`tests/conftest.py` 的替身 docstring 已如实登记该边界）。而「用了哪个会话入口」
    在源码里是**可机械检查**的事实，故这里用 AST 断言：

    - `api/ocr.py` MUST 只用 `write_session()`；
    - `api/tasks.py` MUST 只用 `primary_read_session()`——`er.md:252` 逐字
      「任务提交后立即轮询」属写后立即读，MUST NOT 用 `read_session()`
      （`repository/session.py:243-249` 的 `session_needs_primary` 守卫会拒绝）。

    用 AST 而不是字符串搜索：两个模块的 docstring 里都**写着** `read_session()` 这个反例，
    字符串搜索会假红——判据必须只看真正的调用。
    """
    ocr_entries = _called_session_entries(OCR_PY.read_text(encoding="utf-8"))
    tasks_entries = _called_session_entries(TASKS_PY.read_text(encoding="utf-8"))

    assert ocr_entries == {"write_session"}, f"提交路由的会话入口应为 write_session：{ocr_entries}"
    assert tasks_entries == {"primary_read_session"}, (
        f"轮询路由的会话入口应为 primary_read_session（写后立即读走主库）：{tasks_entries}"
    )


def test_session_entry_scanner_discriminates() -> None:
    """阴性对照：上面的扫描器必须能检出从库会话，否则上一条恒真。"""
    assert _called_session_entries("factory.read_session()") == {"read_session"}
    assert _called_session_entries("f.primary_read_session()") == {"primary_read_session"}
    # docstring 里的示例不算调用（这正是用 AST 的理由）
    assert _called_session_entries('"""MUST NOT 用 read_session() 跑轮询。"""\n') == set()
