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
import json
import logging
import sys
import types
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from aicore.api.deps import ACCOUNT_ID_HEADER, get_now
from aicore.api.ocr import IDEMPOTENCY_KEY_HEADER, SUBMITTED_TASK_TYPE, TaskAccepted
from aicore.core.lease import InMemoryLockStore
from aicore.core.task_runner import ClaimedTask, RunnerConfig, TaskRunner
from aicore.repository.task_lease_store import SqlTaskLeaseStore
from aicore.repository.task_repo import TaskRepo
from aicore.service.task.registry import REGISTRY, assert_submittable
from aicore.service.task.submit import submit_ocr_task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: 被变异/被直接驱动的生产模块（Task 4.9 的两条自证与"防御性分支"用例都要读它）。
SUBMIT_PATH = PROJECT_ROOT / "src" / "aicore" / "service" / "task" / "submit.py"

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


def _model_meta_of(row: Mapping[str, Any]) -> Any:
    """把裸 SQL 读回来的 `model_meta` 解析成 dict（JSON 列在裸读下是**字符串**）。

    为什么需要它：ORM 的 `JSON` 类型会在读的时候反序列化，而 `_task_rows` 刻意走**裸 SQL**
    （要绕过被测代码的读路径），于是拿到的就是库里存的那串文本——sqlite 与 MySQL 都一样。
    这不是缺陷，而是"绕过 ORM 就必须自己做这一步"的代价，写在助手注释里免得后人也踩。
    """
    raw = row["model_meta"]
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


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
    # **Task 4.10 改了这一列的口径**：提交期就冻**当次置信度阈值快照**（`spec.md:128`）。
    # 此前这里断言 `model_meta is None`（"血缘归执行期写"）——本任务把"阈值快照"提前到
    # 受理时刻（那是"当次"能被冻结的最早时刻，也是 M1 唯一可观测的时刻），故断言改成
    # **逐字比对那份快照**；其余四个血缘键（channel/provider/modelVersion/promptVersion）
    # 仍归执行期补（第 5 组），见 `submit.py::new_task` 的 docstring。
    expected_thresholds = {
        "high": api_client.app.state.settings.confidence_high,
        "medium": api_client.app.state.settings.confidence_medium,
    }
    assert _model_meta_of(row) == {"thresholds": expected_thresholds}, (
        f"提交期的 model_meta 应只含当次阈值快照 {expected_thresholds!r}（spec.md:128），"
        f"实际 {row['model_meta']!r}"
    )
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

    判据本体抽到 `_assert_distinct_tasks`（Task 4.9 §2.4）：它同时被下面那条
    **"把 key 写死"的判别力自证**使用——同一份判据，两个场景，防止"自证"与"真判据"漂移。
    """
    license_task = _post(api_client, doc_type="BUSINESS_LICENSE")
    permit_task = _post(api_client, doc_type="PERMIT")

    _assert_distinct_tasks(license_task, permit_task, sandbox_engine, expected_rows=2)


def _assert_distinct_tasks(
    first: Response, second: Response, engine: Engine, *, expected_rows: int
) -> None:
    """**"两次提交是两个任务"的判据本体**（Task 4.9 §2.4）。

    两条缺一不可：

    1. 两次的 `taskId` **不同**——这是"没有互相幂等"的直接证据；
    2. 库里**恰好 `expected_rows` 行**——只比 `taskId` 会漏掉「新建后又把号改回去」
       的实现（行数才是"不重复产生任务"的可观测形式）。

    抽成函数是为了让判别力自证把**同一个场景**喂给同一条判据
    （见 `test_hard_coded_idem_key_guard_discriminates`）：只写"相同键幂等"的话，
    一个把幂等键**写死成常量**的实现照样绿——那正是这条判据要防的形态。
    """
    assert first.status_code == 202, f"第一次提交失败：{first.text[:200]}"
    assert second.status_code == 202, f"第二次提交失败：{second.text[:200]}"
    assert first.json()["data"]["taskId"] != second.json()["data"]["taskId"], (
        f"两次不同的提交拿到了同一个 taskId（{first.json()['data']['taskId']}）："
        f"幂等键把两次独立提交合并了——「相同键幂等」这条要求被实现成了「键恒定」"
    )
    assert len(_task_rows(engine)) == expected_rows, (
        f"库里应有 {expected_rows} 行，实际 {len(_task_rows(engine))} 行："
        f"「不重复产生任务」不成立"
    )


def test_hard_coded_idem_key_guard_discriminates(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**§2.4 的判别力自证**：把幂等键**写死成常量**，上面的阴性判据**必须变红**。

    内存变异（**文件从不被写**）：把 `aicore.service.task.submit.compute_idem_key` 换成
    一个**恒返回同一个常量**的实现——即"键写死"。这是"只测相同键幂等"会放过的那个实现：
    它对「同 imageKey + 同 docType 重提 → 同 taskId」**照样绿**，而真实语义已经没了
    （所有账号的所有提交都会命中同一个键）。

    ## 为什么要两条一起看（这才是这条判据的价值）

    本用例在**同一个场景**（同一账号、同 imageKey、**换 docType**）下：

    1. 先断言变异**真的生效**了（两次拿到同一个 taskId）——否则"判据红了"可能只是因为变异
       没打上；
    2. 再把这两次响应喂给 `_assert_distinct_tasks`（**与第 13 条逐字同一份判据**）：
       它**必须抛**。

    即"键写死 ⇒ 阴性判据必红"是**被看见**的，而不是被推断的。
    """
    monkeypatch.setattr(
        "aicore.service.task.submit.compute_idem_key",
        lambda **_kwargs: "hard-coded-idem-key",
    )

    license_task = _post(api_client, doc_type="BUSINESS_LICENSE")
    permit_task = _post(api_client, doc_type="PERMIT")

    assert license_task.status_code == permit_task.status_code == 202
    assert (
        license_task.json()["data"]["taskId"] == permit_task.json()["data"]["taskId"]
    ), "变异没有生效（两次仍是不同任务）：本自证的前提不成立"
    with pytest.raises(AssertionError, match="同一个 taskId"):
        _assert_distinct_tasks(license_task, permit_task, sandbox_engine, expected_rows=2)



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

    _assert_distinct_tasks(mine, theirs, sandbox_engine, expected_rows=2)
    rows = _task_rows(sandbox_engine)
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


# ---------------------------------------------------------------------------
# Task 4.9 §2.1：幂等的「调用费用」代理判据（处理器只被调用一次）
# ---------------------------------------------------------------------------
class _CountingHandler:
    """**计数处理器**：把"被调用了几次"记下来（Task 4.9 §2.1）。

    它就是 `spec.md:25`「不重复产生任务**与调用费用**」里"调用费用"的可观测代理：
    执行器把一个任务交给处理器一次，就等于对该任务发起了一次（真实世界里的）付费模型调用。
    替身即可，**MUST NOT** 依赖第 5 组的真 OCR 处理器——那条端到端用例登记为待补（见报告）。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def timeout_s(self) -> float:
        return 5.0

    async def handle(self, task: ClaimedTask) -> None:
        self.calls.append(task.task_id)


async def test_duplicate_submit_yields_one_claimable_task_and_one_handler_call(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """**§2.1**：同一 `(account_id, idem_key)` 提交两次 ⇒ 处理器**只被调用一次**。

    ## 为什么判据长这样（工单 §2.1 的裁定）

    字面判据是"Provider 调用次数不增加"，但 M1 的受理路径**根本不调 Provider**
    （`main.py` 注的是 `handlers={}`、`service/ocr_service.py` 还是空壳）⇒ 字面判据没有落点。
    等价且可测的形态（照工单执行）：计数 handler 的 `TaskRunner` + 三件事一起断言——

    1. `ai_task` 只多一行；
    2. 第二次返回**原 `taskId`**；
    3. **可领取任务只有一条** ⇒ 执行器只会把它交给处理器一次 ⇒ 处理器**只被调用一次**。

    第 3 条是这条用例的核心：前两条只说明"库里没有第二行"，而**执行器看到几条**才是
    "会不会产生第二次调用费用"的直接原因（一个写了两行但只让一行 PROCESSING 的实现，
    行数断言会红、而它其实不会多花钱——反过来，一个多写一行 PROCESSING 的实现，
    行数断言也会红但**原因不同**；两条一起才能定位）。

    ## 为什么用 `list_claimable` + `execute`，而不是 `runner.run_once()`

    `run_once()` 会用执行器**自己的墙钟**（`TaskRunner.now` 现取 `datetime.now(UTC)`）算分片月，
    而沙盒只有 `ai_task_202607` / `ai_task_202608` 两张表（今天是 2026-09）
    ——`run_once()` 会去扫一张不存在的月表。
    执行器的时钟**没有注入点**（A9 刻意删掉了 `TaskRunner(clock=)`：`finished_at` 这类
    写库时间不该被假时钟改写），故这里显式把 `now=JULY` 交给**执行器自己的**
    `list_claimable`（`claim_once` 内部那一步），再按执行器的顺序把这一条交给处理器。
    窗口本身（"只扫当月"）由集成用例覆盖，不在这里重复。
    """
    first = _post(api_client)
    second = _post(api_client)
    task_id = first.json()["data"]["taskId"]

    assert second.json()["data"]["taskId"] == task_id, "同 imageKey + docType 重提应返回原任务号"
    assert len(_task_rows(sandbox_engine)) == 1, "重复提交不得新建行"

    handler = _CountingHandler()
    locks = InMemoryLockStore()
    store = SqlTaskLeaseStore(api_client.app.state.engine_factory)
    runner = TaskRunner(
        store=store,
        locks=locks,
        handlers={SUBMITTED_TASK_TYPE: handler},
        policies=dict(REGISTRY),
        config=RunnerConfig(
            lease_ms=30_000, max_retries=3, concurrency_limit=2, poll_interval_s=0.0
        ),
    )
    try:
        claimable = store.list_claimable(limit=10, now=clock.now)
        assert [task.task_id for task in claimable] == [task_id], (
            f"可领取任务应恰好是那一条（{task_id}），实际 "
            f"{[task.task_id for task in claimable]}：重复提交让执行器看到了两条 ⇒ 会产生第二次调用"
        )

        claim = await locks.acquire(task_id, lease_ms=30_000)
        assert claim is not None
        await runner.execute(claimable[0], claim=claim)
    finally:
        await runner.aclose()

    assert handler.calls == [task_id], (
        f"处理器被调用了 {len(handler.calls)} 次（{handler.calls}）："
        f"「不重复调用模型」不成立——每一次调用在真实世界里都是一笔费用"
    )


# ---------------------------------------------------------------------------
# Task 4.9 §2.2：并发同键 —— 撞 uk_idem 之后回读原任务（不是 5000）
# ---------------------------------------------------------------------------
def test_racing_duplicate_submit_returns_the_original_task(
    api_client: TestClient,
    sandbox_engine: Engine,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**§2.2**：并发同键 —— 第二个 `insert` 撞 `uk_idem` 后 MUST **回读并返回原任务**。

    ## 怎么在不必真并发的前提下复现这个竞态

    竞态在**代码视角**下的形态只有一种：`find_by_idem_key` 返回 `None`（查的时候对方还没提交），
    紧随其后的 `insert` 撞唯一键（提交发生在这两步之间）。故本用例让**第一次**幂等查询
    故意返回 `None`（`miss_once`），其余查询走真实现——这是对"两个请求交错执行"的**忠实等价物**，
    而且是**确定性**的（真起两个线程去撞，在 sqlite 沙盒上受单连接序列化影响，反而不稳定）。

    第一次请求正常提交（行已落库、事务已提交），第二次请求因此**必然**在 `insert` 上撞
    `uk_idem`（沙盒的表是从 `models.py` 复制的，**带着** `UniqueConstraint` ⇒ sqlite 真的会拒）。

    ## 判据（四条，缺一条就会被"吸收掉但答错"的实现蒙混过去）

    1. HTTP **202**（不是 5000）——工单要求"两个响应都必须成功"；
    2. 返回的 `taskId` 是**原任务**（第一次那个）——幂等的语义就在这一条；
    3. 库里仍然**只有一行**（被丢弃的那个 `task_id` 没有落库）；
    4. **成因**：日志里出现"撞了 uk_idem …… 已回读"——否则"返回原任务号"也可能是
       由别的原因造成的（例如第二次查询恰好命中了），那条本身不构成"冲突被吸收"的证据。

    ## 这条覆盖不到什么（如实登记，MUST NOT 当成 MySQL 判据）

    它覆盖的是**冲突分支的处置逻辑**（捕获 → 回滚 → 回读 → 返回）。
    真 MySQL 上的 `uk_idem` 行为、**真并发**（两个连接同时提交）与"回读确实走在主库上"
    这三件事**必须**由集成用例在真库上验——本轮 MySQL 停摆，故登记为**待补**，
    **不用本用例顶替**（详见 `task-4.9-report.md` 的待补清单）。
    """
    first = _post(api_client, idempotency_key="idem-race")
    assert first.status_code == 202
    original_task_id = first.json()["data"]["taskId"]

    real_find = TaskRepo.find_by_idem_key
    calls: list[int] = []

    def miss_once(self: TaskRepo, session: Any, **kwargs: Any) -> Any:
        """第一次返回 `None`（= 对方还没提交），之后走真实现（= 回读那一步）。"""
        calls.append(1)
        if len(calls) == 1:
            return None
        return real_find(self, session, **kwargs)

    monkeypatch.setattr(TaskRepo, "find_by_idem_key", miss_once)

    with caplog.at_level(logging.INFO, logger="aicore.service.task.submit"):
        second = _post(api_client, idempotency_key="idem-race")

    assert second.status_code == 202, (
        f"并发同键的第二个请求应回 202（返回原任务），实际 {second.status_code}："
        f"{second.text[:300]}——这正是 T1 登记的缺口（撞 uk_idem 变成 5000）"
    )
    assert second.json()["data"]["taskId"] == original_task_id, (
        f"返回的不是原任务号：{second.json()['data']['taskId']} != {original_task_id}"
    )
    assert len(_task_rows(sandbox_engine)) == 1, (
        f"库里应只有原任务那一行，实际 {len(_task_rows(sandbox_engine))} 行"
    )
    assert any("撞了 uk_idem" in record.getMessage() for record in caplog.records), (
        f"没有冲突被吸收的日志：{caplog.text!r}——"
        f"「返回原任务号」必须来自回读那一步，而不是别的原因"
    )


# ---------------------------------------------------------------------------
# Task 4.9 复核补漏：**"回读为空 ⇒ 重抛"这条安全分支**的判据
# ---------------------------------------------------------------------------
#: 变异体模块名（`sys.modules` 里的临时条目，用完即撤；见 `_mutant_submit_module`）。
_MUTANT_SUBMIT_MODULE = "dsh_mutant_submit"

#: 强制固定的 `task_id`（让 `insert` 撞**主键**而不是 `uk_idem`）。
_CLASHING_TASK_ID = "task_20260700000000000000000000000001"

#: 预置行的 `created_at`：`created_at` **必须绑字符串**（裸 `text()` 把 `datetime` 交给
#: sqlite3 会报 `InterfaceError`——驱动只认 str/int/float/bytes/None；与 `test_task_poll.py`
#: 的 `FINISHED_AT_TEXT` 同一处置）。值落在注入时钟那个月内，与接口写的是同一张月表。
_CLASH_CREATED_AT_TEXT = "2026-07-15 10:30:00.000000"


def _mutant_submit_module(anchor: str, replacement: str) -> Any:
    """把 `service/task/submit.py` 的源码在**内存里**改一处，编译出一个变异模块。

    与 `tests/unit/test_task_runner.py::_mutant_runner_class` 同一取向
    （工单纪律：MUST NOT「改 `src/` + `finally` 还原」——那条路一旦被打断就把变异体留在工作树里）。
    返回**模块**而不是函数：调用方还要改它自己的全局（例如把 `new_id` 换掉）。
    """
    source = SUBMIT_PATH.read_text(encoding="utf-8")
    count = source.count(anchor)
    assert count == 1, (
        f"变异锚点在 service/task/submit.py 里出现 {count} 次（要求恰好 1 次）：{anchor!r}——"
        f"锚点漂了就必须先修锚点，MUST NOT 让它静默变成'什么都没变'"
    )
    module = types.ModuleType(_MUTANT_SUBMIT_MODULE)
    module.__file__ = str(SUBMIT_PATH)
    code = compile(source.replace(anchor, replacement), str(SUBMIT_PATH), "exec")
    sys.modules[_MUTANT_SUBMIT_MODULE] = module
    try:
        exec(code, module.__dict__)
    finally:
        del sys.modules[_MUTANT_SUBMIT_MODULE]
    return module


def _insert_row_with_a_taken_primary_key(engine: Engine, *, idem_key: str) -> str:
    """先插一行**占了 `_CLASHING_TASK_ID` 这个主键**、但幂等键**不同**的行。

    于是下一次 `insert` 会撞**主键**（不是 `uk_idem`），而按 `(account_id, 幂等键)` 回读
    **必然为空**——这正是"安全分支"（读不到 ⇒ 原样重抛）唯一能被触发的形态。
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into ai_task_202607 "
                "(task_id, account_id, idem_key, type, status, progress, "
                " error_code, model_meta, is_eval_sample, created_at, finished_at) "
                "values (:task_id, :account_id, :idem_key, 'OCR', 'PROCESSING', 0, "
                " null, null, 0, :created_at, null)"
            ),
            {
                "task_id": _CLASHING_TASK_ID,
                "account_id": ACCOUNT_ID,
                "idem_key": idem_key,
                "created_at": _CLASH_CREATED_AT_TEXT,
            },
        )
    return _CLASHING_TASK_ID


def test_conflict_without_a_rereadable_row_is_not_absorbed(
    api_client: TestClient,
    sandbox_engine: Engine,
    clock: _Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**"回读为空 ⇒ 重抛"**：不是 `uk_idem` 的冲突 MUST NOT 被当成幂等命中。

    ## 这条守的是什么（复核者点出的危险方向）

    吸收分支的判据只有 `test_racing_duplicate_submit_returns_the_original_task` 一条，
    而它覆盖的是**吸收成功**那一侧。若哪天有人把

    ```python
    if absorbed is not None:
        return absorbed
    raise
    ```

    改成"读不到也返回成功"，那么**一个根本没落库的任务会被当成创建成功返回给调用方**
    （回执里给一个查不到的任务号，调用方随后轮询永远 404），而"吸收"那条用例**照样绿**。

    ## 怎么造出"幂等键在、但回读为空"

    两个条件同时给：

    1. **幂等键走显式头**（`Idempotency-Key`）——于是 `effective_key` 非空，回读那一步
       真的会执行（`effective_key is None` 时会直接重抛，那是另一条分支）；
    2. **冲突来自主键而不是 `uk_idem`**——先插一行占住即将生成的 `task_id`
       （`new_id` 被固定成 `_CLASHING_TASK_ID`，**内存变异**），而那行的 `idem_key` 是**别的值**。
       于是 `insert` 撞主键 ⇒ `rollback` 后按 `(account_id, 幂等键)` 回读**必然为空**。

    ## 观测形态：`TestClient` 会把"没被吞掉的服务端异常"原样抛回

    `TestClient` 的默认是 `raise_server_exceptions=True`，故"产品**没有**吞掉这个异常"
    在这里表现为**调用处抛出 `IntegrityError`**（这正是想要的）；而"吞掉了"会得到
    一个正常返回的响应——两种形态都由同一个判据助手 `_assert_conflict_was_not_absorbed` 判。
    **`caplog` 那一半补上"HTTP 层确实映射成了 500/5000"**：异常处理器跑了，
    只是被测试客户端又抛了回来（否则"抛出来了"并不能证明平台信封是对的）。
    """
    monkeypatch.setattr("aicore.service.task.submit.new_id", lambda *_a, **_k: _CLASHING_TASK_ID)
    _insert_row_with_a_taken_primary_key(sandbox_engine, idem_key="idem-other-row")

    outcome: Any
    with caplog.at_level(logging.ERROR, logger="aicore.core.errors"):
        try:
            outcome = _post(api_client, idempotency_key="idem-pk-clash")
        except IntegrityError as exc:
            outcome = exc

    assert "code=5000" in caplog.text, (
        f"这次冲突没有按内部错误（5000）落一条 ERROR：{caplog.text!r}——"
        f"「没被吞掉」必须同时意味着「平台信封把它报成了 5000」"
    )
    _assert_conflict_was_not_absorbed(outcome, sandbox_engine)


def _assert_conflict_was_not_absorbed(outcome: Any, engine: Engine) -> None:
    """**"回读为空 ⇒ 重抛"的判据本体**（Task 4.9 复核补漏）。

    `outcome` 有两种形态，取决于被测实现有没有吞掉那个异常：

    - **`IntegrityError`（异常对象）**：产品**没有**吞——`TestClient` 默认
      `raise_server_exceptions=True`，服务端未处理的异常会原样抛回调用方；
    - **`Response`**：产品吞掉了异常并回了一个响应——此时 MUST 是失败响应；
      "回 2xx + 一个查不到的任务号"正是要防的那一类。

    两种形态下都还要断言**库里没有幻影行**（`len(rows) == 1` 即只有测试预置的那一行）：
    只断言"没成功"不够——一个"回了 500 却已经把半行写进去/没回滚干净"的实现也会漏过。

    抽成函数是为了让判别力自证把**同一个场景**喂给同一条判据。
    """
    if isinstance(outcome, BaseException):
        assert isinstance(outcome, IntegrityError), (
            f"抛出来的不是那个约束冲突，而是 {type(outcome).__name__}：{outcome!r}"
        )
    else:
        assert outcome.status_code == 500, (
            f"本应抛出却返回了成功：HTTP {outcome.status_code} {outcome.text[:200]}——"
            f"一个**根本没落库**的任务被当成了创建成功返回"
        )
        assert outcome.json()["code"] == 5000, (
            f"业务码应为 5000（内部错误），实际 {outcome.json()['code']}"
        )
        assert outcome.json()["data"] is None, (
            f"失败的冲突回执带了 data：{outcome.json()['data']!r}——"
            f"调用方会拿着一个查不到的任务号去轮询（永远 404）"
        )
    assert len(_task_rows(engine)) == 1, (
        f"库里应只有测试预置的那一行，实际 {len(_task_rows(engine))} 行："
        f"失败路径上又落了行（或回读为空却没回滚干净）"
    )


def test_conflict_safety_guard_discriminates(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**判别力自证**：把吸收分支改成"读不到也返回成功"，上一条判据**必须变红**。

    内存变异（**文件从不被写**）——正是复核者点名的那个改法：

    ```python
    if absorbed is not None:
        return absorbed
    raise
    ```

    改成"读不到就返回本次刚造的那个对象"（`created=True`）⇒ 接口会回 **202 + 一个库里
    不存在的 `taskId`**。本用例在**同一个场景**（同一个主键冲突、同一个显式幂等键）下：

    1. 先断言变异**生效**（响应不再是异常，而是 202）；
    2. 再把响应喂给 `_assert_conflict_was_not_absorbed`（**与上一条逐字同一份判据**）
       ⇒ **必须抛**，且红在"本应抛出却返回了成功"那一条上。
    """
    mutant = _mutant_submit_module(
        "        if absorbed is not None:\n"
        "            return absorbed\n"
        "        raise\n",
        "        if absorbed is None:\n"
        "            return SubmitOutcome(task=task, created=True)\n"
        "        return absorbed\n",
    )
    monkeypatch.setattr("aicore.api.ocr.submit_ocr_task", mutant.submit_ocr_task)
    mutant.__dict__["new_id"] = lambda *_a, **_k: _CLASHING_TASK_ID
    _insert_row_with_a_taken_primary_key(sandbox_engine, idem_key="idem-other-row")

    response = _post(api_client, idempotency_key="idem-pk-clash")

    assert response.status_code == 202, (
        f"变异没有生效（响应是 {response.status_code}）：本自证的前提不成立"
    )
    with pytest.raises(AssertionError, match="本应抛出却返回了成功"):
        _assert_conflict_was_not_absorbed(response, sandbox_engine)


def test_none_idem_key_conflict_is_not_absorbed(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`effective_key is None` 时的冲突 MUST 原样上抛——**防御性分支，经 API 不可达**。

    ## 它为什么不可达（如实登记，MUST NOT 当成"已覆盖的行为"）

    `effective_key` 只有在 `compute_idem_key(...)` 返回 `None` 时才为空，而那个函数的
    docstring 逐字写着"**当前实现永远不会返回 `None`**"：显式键非空即原样返回，
    否则 `sha256(...)` 的 hex 切片——两条分支都产出字符串。
    经 API 更绕不到：`imageKey` 缺失会先被 `require_image_key` 挡成 `400/1001`
    （见 `test_invalid_doc_type_and_missing_image_key_are_400_not_422`）。

    ## 那还测它干什么

    因为它是**唯一的"不吸收"出口之一**，而它的判据是"没有幂等键 ⇒ 这个冲突不可能是
    `uk_idem` ⇒ MUST NOT 吸收"。这条语义**可以被写错**（例如把守卫删掉，让一个外键/主键
    冲突也走回读并返回"成功"）。故这里**绕过 API 直接驱动 service**，
    把触发条件（`compute_idem_key` 返回 `None`）显式注入，断言它**抛出**而不是被吞。

    `compute_idem_key` 的返回值被注入，是这条分支**唯一**的入口；注入它不等于"造了一个
    产品里不存在的场景"——产品里写的就是"若返回 None 则不查幂等"，
    本用例验的是那半句话的后果。
    """
    monkeypatch.setattr("aicore.service.task.submit.compute_idem_key", lambda **_k: None)
    monkeypatch.setattr("aicore.service.task.submit.new_id", lambda *_a, **_k: _CLASHING_TASK_ID)
    _insert_row_with_a_taken_primary_key(sandbox_engine, idem_key="idem-other-row")

    with (
        pytest.raises(IntegrityError, match="task_id"),
        api_client.app.state.engine_factory.write_session() as session,
    ):
        submit_ocr_task(
            session,
            account_id=ACCOUNT_ID,
            image_key=IMAGE_KEY,
            doc_type=DOC_TYPE,
            idem_key="idem-explicit-ignored",
            now=JULY,
            policy=assert_submittable(SUBMITTED_TASK_TYPE),
            thresholds={"high": 0.9, "medium": 0.7},
        )

    assert len(_task_rows(sandbox_engine)) == 1, "失败路径上又落了行"
