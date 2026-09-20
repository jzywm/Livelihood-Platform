"""证照 OCR 提交（K-01）。Task 4.5。

**契约来源**：`docs/openapi.yaml` 的 `/aicore/ocr`（L44-106）与 `OcrRequest`（L696-707）、
`TaskAccepted`（L774-786）；业务码与状态码的映射由 `core/errors.py` 统一出口负责
（路由只抛业务异常，MUST NOT 自行拼装信封）。

## 四处口径，逐条说明理由

### 1. HTTP `202`（而不是 openapi 里写的 `'200'`）

控制者裁定，已在 ledger 登记：`spec.md:30` 逐字「系统**立即返回**任务号与受理状态
（`PROCESSING`）」、`tasks.md` 4.5 逐字「**提交即写** `ai_task` 返回 `taskId`」，
语义是**受理**（Accepted）；`openapi.yaml:63` 自己就写着「受理成功，返回任务号（异步处理）」。
RFC 9110 的 `202 Accepted` 定义即「请求已被接受处理，但处理尚未完成」，与本接口逐字一致；
`200` 会与「轮询已有结果」的语义混同。
**风险已被告知**：若前端契约测试按 `200` 断言会红，故用例**同时**断言「状态码是 202」
与「响应体是 `TaskAccepted` 契约」，让该差异显式可见而不是被藏起来。

### 2. 本接口自己声明的「必填 / 枚举」走**业务路径**（`400` + `1001`/`1003`），不走框架校验

本接口在 `openapi.yaml:73-74` 声明的是 `'400'`（`BadRequest`），**没有**声明 `422`；
而 FastAPI 的 pydantic 校验路径会把「缺必填 / 枚举非法」渲染成 **HTTP 422**
（`core/errors.py` 的 `VALIDATION_HTTP_STATUS`，第 2 组定档、既有用例钉住，本任务 MUST NOT 改）。
两条口径不能同时成立，故本模块把**本接口自己声明的规则**（`imageKey`/`docType` 必填、
两个枚举的取值域）收回到业务异常路径：`ParamError(1001/1003)` → `400`，
响应体仍是平台信封。**如实登记的边界**：请求体不是 JSON 对象、字段类型不是字符串这类
**解析/类型层**失败仍由框架渲染（`422` + `1002`/`1001`）——那是平台全局行为，
不属本接口能改的范围；本模块只保证本接口声明的必填与枚举不出现 422
（用例 `test_invalid_doc_type_and_missing_image_key_are_400_not_422` 正面钉住）。

代价是 `OcrRequest` 的字段注解是 `str | None`（不是 `DocType` 枚举），故 FastAPI 自动生成的
`/openapi.json` 对这几个字段只显示 `string`。**契约权威仍是 `docs/openapi.yaml`**
（本项目口径：它是「唯一可手改源」），运行期取值域由下面的 `DocType` / `OcrScene`
两个 `StrEnum` 单点判定。

### 3. `scene` 只校验、不落库

`er.md` §6.1 的 `ai_task` **没有** `scene` 列，`ocr_result` 也没有；本任务 MUST NOT 为它新增列
（会撞 Task 3.6 的三源比对——`er.md` ↔ DDL ↔ `models.py`）。故 `scene` 经枚举校验后**即丢弃**，
既不进 `ai_task` 也不传给编排（提交编排不消费它）。这是**如实登记的丢弃**，
不是「透传到某个下游」——本任务没有那个下游。

### 4. 同步数据库访问下线程池

`design.md` L200-204 的并发模型把 MySQL 访问定在**线程池**（同步 SQLAlchemy 会话）：
路由是 `async def`（I/O 等待型入口在事件循环），但 `submit_ocr_task` 是同步仓储调用
（本服务不引入 async driver，理由见 `repository/session.py`）。直接调用会把整个事件循环
卡在一次数据库往返上——那是「并发数不高但 P95 爆表」的典型成因。故用 `run_in_threadpool`
把「开会话 + 写库 + 写后立即读」整体交给工作线程：会话**在哪个线程创建就在哪个线程用完**
（sqlite/MySQL 连接都有线程亲和性）。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from aicore.api.deps import (
    SessionFactory,
    get_account_id,
    get_engine_factory,
    get_now,
    get_settings,
)
from aicore.core.config import Settings
from aicore.core.envelope import Envelope
from aicore.core.errors import PARAM_MISSING_CODE, PARAM_VALUE_CODE, ParamError
from aicore.service.task.confidence import confidence_thresholds
from aicore.service.task.registry import TaskPolicy, assert_submittable
from aicore.service.task.state import PROCESSING
from aicore.service.task.submit import SubmitOutcome, submit_ocr_task

#: 幂等键请求头（`openapi.yaml:54` 逐字「支持 `Idempotency-Key` 头」）。
#: 只属于本路由的请求契约，故常量落在这里（账号头的常量归 `api/deps.py`，那是跨路由的装配点）。
IDEMPOTENCY_KEY_HEADER: Final = "Idempotency-Key"

#: 本端点受理的任务类型（**接口自己的声明**：这个接口提交的就是证照 OCR）。
#:
#: **它不是第二份「任务类型表」**：类型表只有 `service/task/registry.py` 的 `REGISTRY` 一份
#: （`design.md:194`：未注册的类型必须显式失败）。这里只是「本端点提交哪一类」这一句话，
#: 且**立刻**被下面的 `assert_submittable` 按注册表校验：拼错、未注册、或 M1 未实现
#: 都会在受理处被拒（`1003`），MUST NOT 静默落库。
SUBMITTED_TASK_TYPE: Final = "OCR"

#: 受理状态的**mypy 接线点**：下面的 `TaskAccepted.status` 必须写成字面量
#: `Literal["PROCESSING"]`——mypy 不接受 `Literal[PROCESSING]`（`Final` 变量不能作
#: `Literal` 参数），故字符串在注解里被迫重抄一遍。这一行把抄件与 `state.py` 的常量接起来：
#: 谁改了 `PROCESSING` 的取值，这里立刻报类型错。
_ACCEPTED_STATUS: Final[Literal["PROCESSING"]] = PROCESSING


class DocType(StrEnum):
    """证照类型（`openapi.yaml` 的 `DocType`，L686-690，三个取值逐字一致）。

    它是本接口 `docType` 的**唯一**取值域：路由用 `DocType(value)` 判定，
    MUST NOT 在别处再写一份字符串清单（多一份就会漂移成「接口收得进、编排认不出」）。
    """

    BUSINESS_LICENSE = "BUSINESS_LICENSE"
    PERMIT = "PERMIT"
    INSPECTION_REPORT = "INSPECTION_REPORT"


class OcrScene(StrEnum):
    """OCR 应用场景（`openapi.yaml` 的 `OcrScene`，L691-695）。

    取值只用于**校验**：见模块 docstring 第 3 条——`ai_task` 没有该列，本任务不落库。
    """

    MERCHANT_ONBOARDING = "MERCHANT_ONBOARDING"
    CERT_RENEWAL = "CERT_RENEWAL"
    SUPERVISOR_REVIEW = "SUPERVISOR_REVIEW"


class OcrRequest(BaseModel):
    """`POST /aicore/ocr` 请求体形状（`openapi.yaml:696-707`）。字段名 MUST 保持 camelCase。

    必填 `imageKey` / `docType`（与 openapi 的 `required: [imageKey, docType]` 一致）、
    可选 `scene`。三个字段**都由本模块的方法显式判定**，而不是交给 pydantic 的枚举/必填——
    理由见模块 docstring 第 2 条（本接口声明的是 400，框架校验路径给的是 422）。

    本模型**不设** `extra="forbid"`：openapi 未声明 `additionalProperties: false`，
    收紧多余字段属于改契约；而字段名写错（如 `image_key`）仍会被「缺 `imageKey`」
    这条必填判定拦住（`1001`），不会静默当默认值通过。
    """

    # N815 说明：该规则管的是「类作用域里的 mixedCase 变量名」，而平台契约字段名就是 camelCase
    # （与 `core/envelope.py` 的 `traceId` 同一处理），逐个字段行级豁免而不是关规则。
    imageKey: str | None = None  # noqa: N815
    docType: str | None = None  # noqa: N815
    scene: str | None = None


class TaskAccepted(BaseModel):
    """受理回执（`openapi.yaml:774-786`）：`taskId` + 固定 `PROCESSING`。

    `status` 的取值域是**单元素**枚举 `[PROCESSING]`（不是 `TaskStatus` 四值）：
    受理回执说的是「已受理」，不是任务当前状态。故**幂等命中一个已 `SUCCEEDED` 的任务**时，
    本回执仍回 `PROCESSING` —— 这是 openapi 定档的形状，调用方要拿状态就去轮询
    `GET /aicore/tasks/{taskId}`（`openapi.yaml:52` 逐字「前端轮询 … 取结果」）。
    """

    taskId: str  # noqa: N815
    status: Literal["PROCESSING"]


router = APIRouter(prefix="/aicore", tags=["ocr"])


def require_image_key(payload: OcrRequest) -> str:
    """`imageKey` 必填判定：没送到 → `ParamError(1001)`（HTTP 400）。

    只判「有没有送到」（`None`）：**空串不在这里拒**——`openapi.yaml` 对该字段只声明
    `type: string`、没有 `minLength`，擅自收紧属于改契约（该边界登记在任务报告里）。
    """
    if payload.imageKey is None:
        raise ParamError(
            "缺少必填字段 imageKey（证照图像 OSS 对象键）",
            code=PARAM_MISSING_CODE,
        )
    return payload.imageKey


def require_doc_type(payload: OcrRequest) -> DocType:
    """`docType` 必填 + 枚举判定：缺 → `1001`；非枚举值 → `1003`（两者都 HTTP 400）。

    `1003` 是「枚举或范围非法」这一档（`core/errors.py` 的三档参数码之一）：
    调用方送来的是参数**写错了取值**，不是「没送到」，两档必须分开，
    否则前端无法区分「补字段」与「改取值」两种处置。
    """
    if payload.docType is None:
        raise ParamError("缺少必填字段 docType（证照类型）", code=PARAM_MISSING_CODE)
    try:
        return DocType(payload.docType)
    except ValueError:
        raise ParamError(
            f"docType 取值非法：只能是 {[member.value for member in DocType]} 之一",
            code=PARAM_VALUE_CODE,
        ) from None


def validate_scene(payload: OcrRequest) -> None:
    """`scene` 可选，但给了就必须是枚举值（非法 → `1003`）；**校验通过即丢弃**。

    丢弃的理由见模块 docstring 第 3 条：`ai_task` / `ocr_result` 都没有该列，
    本任务 MUST NOT 为它新增列（三源比对会红）。所以这里是「收下并检查、然后不带走」，
    而不是「透传给下游」——没有下游可传。
    """
    if payload.scene is None:
        return
    try:
        OcrScene(payload.scene)
    except ValueError:
        raise ParamError(
            f"scene 取值非法：只能是 {[member.value for member in OcrScene]} 之一",
            code=PARAM_VALUE_CODE,
        ) from None


@router.post(
    "/ocr",
    status_code=202,
    response_model=Envelope[TaskAccepted],
    summary="提交证照 OCR 核验任务【M1 · K-01】",
)
async def submit_ocr(
    payload: OcrRequest,
    account_id: Annotated[str, Depends(get_account_id)],
    factory: Annotated[SessionFactory, Depends(get_engine_factory)],
    now: Annotated[datetime, Depends(get_now)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_KEY_HEADER)] = None,
) -> Envelope[TaskAccepted]:
    """受理一次证照 OCR 任务：落 `ai_task` 后立即返回任务号。

    依赖的四个提供者各管一件事，且都**可被替换**（测试注入固定时钟 / 沙盒会话 / 阈值）：

    - `get_account_id`：身份取网关注入的 `X-User-Id`，缺失 / 空白即 `2001`（fail-closed）；
    - `get_engine_factory`：会话工厂由组合根装配（写路径用 `write_session()`——
      本次请求要落一行 `ai_task`）；
    - `get_now`：**由调用方传入的时刻**——分片月与 `created_at` 都由它现算，
      查幂等与插入共用同一个值（月边界，见 `service/task/submit.py`）；
    - `get_settings`：**只为两个置信度阈值**（Task 4.10）。它们在受理时被冻进
      `ai_task.model_meta.thresholds`（`spec.md:128` 的"**当次**快照"），执行期读回它来分级。
      注意这里**不读** `provider` / 凭据之类的字段——路由只用它做这一件事。

    幂等：`Idempotency-Key` 头显式给了就用它，否则由 `imageKey` + `docType` 派生
    （`er.md:290`「同 imageKey+docType 返回原任务号」）。命中时返回**原任务号**且库行数不增。

    准入：落库**之前**先过 `assert_submittable`，拿到策略再交给编排——
    任务类型的唯一来源是注册表（`design.md:194`），本端点只声明「提交哪一类」。
    若 `SUBMITTED_TASK_TYPE` 被改成未注册或 M1 未实现的类型，请求会在**受理处**被拒
    （`400` + `1003`），而不是先落一行再让执行器发现没人能处理它。
    """
    image_key = require_image_key(payload)
    doc_type = require_doc_type(payload)
    validate_scene(payload)
    # 准入判定：未注册 / M1 未实现 → ParamError(1003)（HTTP 400），落在落库之前。
    # 传出的策略也带回类型，故「类型从哪来」在这条路径上只有一个答案。
    policy: TaskPolicy = assert_submittable(SUBMITTED_TASK_TYPE)
    outcome: SubmitOutcome = await run_in_threadpool(
        _submit_in_session,
        factory,
        account_id=account_id,
        image_key=image_key,
        doc_type=doc_type.value,
        idem_key=idempotency_key,
        now=now,
        policy=policy,
        thresholds=confidence_thresholds(
            high=settings.confidence_high,
            medium=settings.confidence_medium,
        ),
    )
    return Envelope[TaskAccepted].ok(TaskAccepted(taskId=outcome.task.task_id, status=PROCESSING))


def _submit_in_session(
    factory: SessionFactory,
    *,
    account_id: str,
    image_key: str,
    doc_type: str,
    idem_key: str | None,
    now: datetime,
    policy: TaskPolicy,
    thresholds: Mapping[str, float],
) -> SubmitOutcome:
    """在工作线程里开会话并完成提交（**同步**函数，故 MUST 经 `run_in_threadpool` 调用）。

    **为什么不写成 `async def` 再逐句 await**：本服务的数据库访问是同步 SQLAlchemy
    （`repository/session.py` 已定档：同步会话 + 线程池，MUST NOT 引入 async driver），
    故这里的边界就是「整块同步工作交给线程池」，而不是把同步调用拆进 await 链。
    会话的 `with` 也必须在**同一个线程内**闭合：连接有线程亲和性，跨线程用同一条连接
    会直接报错（sqlite 的 `check_same_thread` 就是这么拦的）。
    """
    with factory.write_session() as session:
        return submit_ocr_task(
            session,
            account_id=account_id,
            image_key=image_key,
            doc_type=doc_type,
            idem_key=idem_key,
            now=now,
            policy=policy,
            thresholds=thresholds,
        )
