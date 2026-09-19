"""`POST /aicore/ocr` 契约用例。Task 4.5 §3 的第 9~17 条。

## 这些用例为什么**必须**经 `api_client`

`api_client` 走**真组合根**（`create_app()` + 真 lifespan）再注入 sqlite 沙盒会话替身，
即：身份依赖、会话装配、写后立即读、信封与异常处理四条链路都是真的，只有「引擎指向哪里」
被换成了内存库。若直接调路由函数或自己拼 Request，`app.state.engine_factory` 未装配这类
断链（L2 的同型缺陷）会被整个绕过去——T1 之前那条夹具自证用例正是栽在这里。

## 时间为什么必须靠注入

`tests/support/db_sandbox.py` 只建 `ai_task_202607` / `ai_task_202608` 两张月表，
而分片月由路由的 `now` 现算（`service/task/submit.py` 的月边界口径）。
故本文件统一把时钟钉进 2026-07——这既是「`now` 可注入」这条硬要求的用法，
也顺带证明「时间源只有一处」（`api/deps.py::get_now`）。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from aicore.api.deps import ACCOUNT_ID_HEADER, get_now
from aicore.api.ocr import IDEMPOTENCY_KEY_HEADER, TaskAccepted

ACCOUNT_ID = "acc_ocr_owner"
OTHER_ACCOUNT_ID = "acc_ocr_other"
IMAGE_KEY = "cert/oss/2026/07/abc123.jpg"
DOC_TYPE = "BUSINESS_LICENSE"

#: 沙盒有表的那个月（`SANDBOX_TABLES` 的 `ai_task_202607`）。
JULY = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)


class _Clock:
    """可注入时钟（`api/deps.py::get_now` 的替身）：`now` 可被用例改写以构造月边界。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(api_client: TestClient) -> _Clock:
    """把路由的时间源钉进沙盒有表的那两个月。

    注入点是 `app.dependency_overrides[get_now]`（FastAPI 的标准替换通道），
    **不改生产代码、不 patch 函数**：`get_now` 是路由显式声明的依赖，
    替换它等于替换部署形态里的时钟，而不是绕过被测逻辑。
    每个用例一个新建的 app（`api_client` 夹具），故覆盖不会跨用例泄漏。
    """
    holder = _Clock(JULY)
    api_client.app.dependency_overrides[get_now] = holder
    return holder


def _derived_key(image_key: str, doc_type: str) -> str:
    """派生的幂等键口径（工单 §2.2）：`sha256("<imageKey>\\x00<docType>")` 的 hex 前 32 位。"""
    return hashlib.sha256(f"{image_key}\x00{doc_type}".encode()).hexdigest()[:32]


def _post(
    client: TestClient,
    *,
    user: str | None = ACCOUNT_ID,
    image_key: str | None = IMAGE_KEY,
    doc_type: str | None = DOC_TYPE,
    scene: str | None = None,
    idempotency_key: str | None = None,
) -> Response:
    """发一次提交。**缺省即"字段/头不出现"**（不是送空串），三态才分得清。"""
    payload: dict[str, Any] = {}
    if image_key is not None:
        payload["imageKey"] = image_key
    if doc_type is not None:
        payload["docType"] = doc_type
    if scene is not None:
        payload["scene"] = scene
    headers: dict[str, str] = {}
    if user is not None:
        headers[ACCOUNT_ID_HEADER] = user
    if idempotency_key is not None:
        headers[IDEMPOTENCY_KEY_HEADER] = idempotency_key
    return client.post("/aicore/ocr", json=payload, headers=headers)


def _task_rows(engine: Engine, *, month: str = "202607") -> list[dict[str, Any]]:
    """直连沙盒库读月表全部行（断言「库内到底有几行、长什么样」）。

    刻意**不用仓储读**：用被测代码自己的读路径去验它自己的写路径，等于让同一个缺陷
    在两侧同时成立（写错表名 + 读错表名 = 用例全绿）。这里用裸 SQL 打在**物理表名**上。
    """
    with engine.connect() as conn:
        rows = conn.execute(text(f"select * from ai_task_{month}")).mappings().all()
    return [dict(row) for row in rows]


def test_accepted_returns_202_with_the_task_accepted_contract(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 9 条：受理返回 `202` + `TaskAccepted` 形状 + 信封 `code == 0`。

    **同时**断言状态码与响应体契约：`openapi.yaml:62` 写的是 `'200'`，而工单按
    `spec.md:30`「立即返回任务号与受理状态」的受理语义裁定用 `202`（已在 ledger 登记差异）。
    两条一起断言，是为了让这个差异**显式可见**（谁改回 200，这里立刻红），而不是藏起来。
    """
    response = _post(api_client)

    assert response.status_code == 202, (
        f"受理状态码应为 202 Accepted（工单裁定，openapi 写 200 的差异已登记），"
        f"实际 {response.status_code}：{response.text[:200]}"
    )
    body = response.json()
    assert body["code"] == 0, f"成功信封的业务码必须是 0（不是 HTTP 200）：{body}"
    assert set(body) >= {"code", "message", "traceId", "timestamp", "data"}

    data = body["data"]
    TaskAccepted.model_validate(data)  # 契约形状：多字段 / 少字段都会在这里失败
    assert set(data) == {"taskId", "status"}
    assert data["taskId"].startswith("task_"), f"任务号前缀应为 task_：{data['taskId']!r}"
    assert data["status"] == "PROCESSING"


def test_submission_writes_exactly_one_row_with_the_declared_columns(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 10 条：库内确实多了一行，且逐列对齐 `er.md` §6.1。

    逐列断言（而不是只看 status）是因为「默认值兜底」会让漏写的列看起来是对的：
    `is_eval_sample` / `progress` / `status` 三列在 DDL 里都有 `server_default`，
    少写一个也照样能插入成功——只有逐列读回来才分得出「写了 0」与「库给了 0」。
    """
    response = _post(api_client)
    task_id = response.json()["data"]["taskId"]

    rows = _task_rows(sandbox_engine)
    assert len(rows) == 1, f"一次提交应恰好落一行，实际 {len(rows)} 行"
    row = rows[0]

    assert row["task_id"] == task_id
    assert row["account_id"] == ACCOUNT_ID
    assert row["type"] == "OCR"
    assert row["status"] == "PROCESSING"
    assert row["progress"] == 0
    assert row["finished_at"] is None, "非终态不得有 finished_at"
    assert row["error_code"] is None, "PROCESSING 不得有 error_code"
    assert row["model_meta"] is None, "血缘（model_meta）在执行期才写，归 Task 4.7"
    assert row["is_eval_sample"] == 0
    assert str(row["created_at"]).startswith("2026-07-15 10:30"), (
        f"created_at 应等于注入的 now（UTC 存储、无时区列），实际 {row['created_at']!r}"
    )
    assert row["idem_key"] == _derived_key(IMAGE_KEY, DOC_TYPE)
    assert len(row["idem_key"]) <= 64, "er.md §6.1 L290：idem_key 是 varchar(64)"


def test_same_explicit_idempotency_key_returns_the_same_task(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 11 条：同 `Idempotency-Key` 重提 → 同一 `taskId`、库行数不增。

    `spec.md:39-40` 逐字「返回原任务号，**不新建任务、不重复调用模型**」——
    行数不增是这条硬要求的可观测形式（只比 taskId 会漏掉「新建后又把号改回去」的实现）。
    """
    first = _post(api_client, idempotency_key="idem-explicit-1")
    second = _post(api_client, idempotency_key="idem-explicit-1")

    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["taskId"] == second.json()["data"]["taskId"]

    rows = _task_rows(sandbox_engine)
    assert len(rows) == 1, f"幂等命中不得新建行，实际 {len(rows)} 行"
    assert rows[0]["idem_key"] == "idem-explicit-1", "显式键 MUST 原样落库（不派生、不改写）"


def test_same_image_key_and_doc_type_without_header_is_idempotent(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 12 条：无 `Idempotency-Key` 但同 `imageKey` + `docType` → 同一 `taskId`。

    依据 `er.md:290` 逐字「同 imageKey+docType 返回原任务号」。
    顺带钉住派生口径本身（sha256 的 hex 前 32 位）：只断言「两次相同」的话，
    一个把 `docType` 丢掉的实现（只用 imageKey 派生）也能通过本用例的一半。
    """
    first = _post(api_client)
    second = _post(api_client)

    assert first.json()["data"]["taskId"] == second.json()["data"]["taskId"]
    rows = _task_rows(sandbox_engine)
    assert len(rows) == 1
    assert rows[0]["idem_key"] == _derived_key(IMAGE_KEY, DOC_TYPE)


def test_different_doc_type_makes_a_different_task(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 13 条：**不同** `docType` → 不同 `taskId`（派生键必须带上 docType）。

    同 imageKey 换了证照类型就是另一件事：同一张图按「营业执照」和按「许可证」解析，
    结果结构不同，故 MUST NOT 被幂等合并。
    """
    license_task = _post(api_client, doc_type="BUSINESS_LICENSE")
    permit_task = _post(api_client, doc_type="PERMIT")

    assert license_task.json()["data"]["taskId"] != permit_task.json()["data"]["taskId"]
    assert len(_task_rows(sandbox_engine)) == 2


def test_different_account_with_same_image_key_makes_a_different_task(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 14 条：**不同账号**同 `imageKey` + `docType` → **不同** `taskId`（`uk_idem` 是两列）。

    同时钉住「MUST NOT 把 `account_id` 拼进 `idem_key`」：两行的 `idem_key` **必须相同**
    （派生只吃 imageKey + docType），差别只由 `(account_id, idem_key)` 两列唯一键实现。
    若有人把账号拼进了键，下面那条集合断言会立刻红。
    """
    mine = _post(api_client, user=ACCOUNT_ID)
    theirs = _post(api_client, user=OTHER_ACCOUNT_ID)

    assert mine.json()["data"]["taskId"] != theirs.json()["data"]["taskId"]
    rows = _task_rows(sandbox_engine)
    assert len(rows) == 2
    assert {row["account_id"] for row in rows} == {ACCOUNT_ID, OTHER_ACCOUNT_ID}
    assert {row["idem_key"] for row in rows} == {_derived_key(IMAGE_KEY, DOC_TYPE)}, (
        "两行的 idem_key 应相同（派生不吃账号）：不同即说明账号被拼进了幂等键"
    )


@pytest.mark.parametrize("header_value", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_missing_or_blank_account_header_is_401_and_writes_nothing(
    api_client: TestClient,
    sandbox_engine: Engine,
    clock: _Clock,
    header_value: str | None,
) -> None:
    """第 15 条：`X-User-Id` 缺失 / 空串 / 纯空白 → `401` + `2001`（三个参数化）。

    **fail-closed 的两层含义**：① 状态码是 401、业务码是 2001；② **一行都不许落**
    ——若回落到「匿名账号」或某个默认账号，未鉴权请求就会写进某个真实账号的任务表，
    那既是越权写入，也让越权查询看起来合法。故这里直接断言月表为空。
    """
    response = _post(api_client, user=header_value)

    assert response.status_code == 401, (
        f"X-User-Id={header_value!r} 应判为未鉴权，"
        f"实际 {response.status_code}：{response.text[:200]}"
    )
    body = response.json()
    assert body["code"] == 2001
    assert body["data"] is None
    assert _task_rows(sandbox_engine) == [], "未鉴权请求 MUST NOT 落任务行（fail-closed）"


def test_invalid_doc_type_and_missing_image_key_are_400_not_422(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 16 条：`docType` 非枚举 → `400` + `1003`；`imageKey` 缺失 → `400` + `1001`。

    **为什么强调不是 422**：FastAPI 的 pydantic 校验路径会把这两类失败渲染成 HTTP 422，
    而本接口在 `openapi.yaml:73-74` 只声明了 `'400'`。工单裁定本接口自己声明的必填与枚举
    走**业务路径**（400 + 平台信封），故 `api/ocr.py` 用 `require_*` 显式判定；
    这条用例把「422 不出现」正面钉住（改回 pydantic 枚举会立刻红）。
    """
    bad_doc_type = _post(api_client, doc_type="ID_CARD")
    assert bad_doc_type.status_code == 400, (
        f"docType 非枚举应为 400（不是框架的 422），实际 {bad_doc_type.status_code}"
    )
    assert bad_doc_type.json()["code"] == 1003
    assert bad_doc_type.json()["data"] is None

    missing_image_key = _post(api_client, image_key=None)
    assert missing_image_key.status_code == 400
    assert missing_image_key.json()["code"] == 1001

    assert _task_rows(sandbox_engine) == [], "参数不合法的请求 MUST NOT 落任务行"


def test_scene_is_validated_but_never_persisted(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 16 条的延伸：`scene` 合法值放行、非法值 `1003`，且**始终不落库**。

    依据：`er.md` §6.1 的 `ai_task` 没有 `scene` 列，`ocr_result` 也没有，
    本任务 MUST NOT 为它新增列（会撞 Task 3.6 的三源比对）。故「列清单里没有 scene」
    是设计事实，而不是遗漏——这条断言把它变成可核对的证据。
    """
    accepted = _post(api_client, scene="SUPERVISOR_REVIEW")
    assert accepted.status_code == 202
    row = _task_rows(sandbox_engine)[0]
    assert "scene" not in row, f"ai_task 不应有 scene 列（er.md §6.1），实际列：{sorted(row)}"

    rejected = _post(api_client, scene="BOGUS_SCENE")
    assert rejected.status_code == 400
    assert rejected.json()["code"] == 1003
    assert len(_task_rows(sandbox_engine)) == 1, "非法 scene 的请求不得落行"


@pytest.mark.parametrize(
    ("task_type", "expect_in_message"),
    [
        ("VISION_REVIEW", "M1 未实现"),
        ("NOT_A_REGISTERED_TYPE", "未注册"),
    ],
)
def test_acceptance_path_really_gates_on_the_registry(
    api_client: TestClient,
    sandbox_engine: Engine,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    task_type: str,
    expect_in_message: str,
) -> None:
    """受理路径上 `assert_submittable` **真的被调用**（控制者裁定的接线验收位）。

    做法：把本端点声明的任务类型**换掉**（monkeypatch `api/ocr.py` 的模块级常量），
    再发一次正常请求。两类失败都必须发生，且都发生在**落库之前**：

    - `VISION_REVIEW`：已注册但 M1 未实现（`design.md:190` 的预留位）→ `400` + `1003`；
    - `NOT_A_REGISTERED_TYPE`：未注册（调用方拼错 / 新类型忘了登记）→ `400` + `1003`。

    **为什么必须写成行为断言**：断言「`assert_submittable` 被 import 了」只能证明它存在
    （Task 4.6 已经证明过），证明不了它在调用链上——而「没有生产调用方」正是这次接线的起因。
    若谁把受理处的准入调用删掉，本用例会拿到 `202`（而不是 400），且库里会落下一行
    ——两条断言同时变红，判别力来自这里。

    消息也必须可分辨（`design.md:194`：留给运维的告警要能区分「预期内的预留位」与
    「预期外的未注册输入」），故参数化里连带断言消息关键词。
    """
    monkeypatch.setattr("aicore.api.ocr.SUBMITTED_TASK_TYPE", task_type)

    response = _post(api_client)

    assert response.status_code == 400, (
        f"未通过准入判定的类型 {task_type!r} 应被拒（400），实际 {response.status_code}："
        f"{response.text[:200]}"
    )
    body = response.json()
    assert body["code"] == 1003, f"准入失败的业务码应为 1003（枚举非法）：{body}"
    assert expect_in_message in body["message"], (
        f"告警消息应能区分两类拒绝（期望含 {expect_in_message!r}）：{body['message']!r}"
    )
    assert _task_rows(sandbox_engine) == [], "准入失败的请求 MUST NOT 落库（判定必须在写之前）"


def test_month_boundary_resubmit_creates_a_second_task_by_design(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """第 17 条：月边界 —— **跨月不幂等是设计而非缺陷**。

    处置口径：`uk_idem(account_id, idem_key)` 是「**同月表内**唯一」
    （`er.md` §7.1 L429 逐字），而幂等查询与插入都只落在 `now` 所在的那张月表上。
    故 23:59:59.999 提交、次日 00:00:00.001 用**同一个显式幂等键**重提时，查的是
    **另一张物理表**——查不到，于是新建任务、返回新任务号。这不是漏判：
    两次提交本就是两个分片上的两行，「同月表内唯一」这条约束在跨月时无定义。
    要让跨月也判幂等，需要一张**非分片**的全局幂等索引表（或把幂等窗口显式定义成
    「最近 N 个月」），那是新的设计决定，不在本工单范围内——故此处如实登记为**已知且正确**的行为。

    时间取自沙盒实际存在的两个月（202607 / 202608）：工单举例写的 2027-03/04 在沙盒里
    没有对应的物理表，而 `db_sandbox.py` 的注释说明这两个月正是为「跨月边界」准备的。
    语义与工单要求逐字一致（月末最后一毫秒 → 次月第一毫秒 + 同一幂等键）。
    """
    clock.now = datetime(2026, 7, 31, 23, 59, 59, 999000, tzinfo=UTC)
    july = _post(api_client, idempotency_key="idem-month-edge")
    clock.now = datetime(2026, 8, 1, 0, 0, 0, 1000, tzinfo=UTC)
    august = _post(api_client, idempotency_key="idem-month-edge")

    assert july.status_code == 202 and august.status_code == 202
    assert july.json()["data"]["taskId"] != august.json()["data"]["taskId"], (
        "跨月重提落到了同一个 taskId：说明幂等查询与插入用了**两个不同的月份**"
    )
    assert len(_task_rows(sandbox_engine, month="202607")) == 1
    assert len(_task_rows(sandbox_engine, month="202608")) == 1
