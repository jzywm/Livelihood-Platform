"""OCR 任务提交编排：幂等键派生 + 落 `ai_task` + 写后立即读。Task 4.5。

## 权威依据

- `er.md` **§7.1 L430**（状态机与约束）、**§6.1 L284-298**（`ai_task` 逐列口径）、
  **§5.2 L217**（按月分表 `ai_task_YYYYMM`）、**§5.3**（查询 MUST 携带分片键下推）、
  **§5.5 L252**（关键「写后立即读」强制走主库）；
- `openapi.yaml` **L54** 逐字「幂等：同 imageKey 同 docType 重复提交返回原任务号
  （支持 `Idempotency-Key` 头）」；`design.md` **L179**（`POST /aicore/ocr` 落 `ai_task`）；
- `spec.md` **L37-40**（重复提交 MUST 幂等：返回原任务号，不新建任务、不重复调用模型）。

## 幂等键的口径（这是「幂等」能不能站住的关键）

| 情形 | 取值 |
|---|---|
| 显式给了 `Idempotency-Key` | **原样使用**（`openapi.yaml:54`「支持 `Idempotency-Key` 头」） |
| 没给（或缺省 / 纯空白） | `sha256("<image_key>\x00<doc_type>")` 的 hex 前 32 位 |

派生分支的依据是 `er.md:290` 逐字「同 imageKey+docType 返回原任务号」。
四条硬约束：

1. **长度 MUST ≤ 64**（`er.md:290` `idem_key varchar(64)`）：超长抛 `ParamError(1003)`，
   **MUST NOT 静默截断**——截断会让两个不同的键落成同一个值，把「两次独立提交」判成幂等命中；
2. **派生分支 MUST NOT 返回 `None`**：`uk_idem` 是 **NULL 豁免**的唯一键，
   派生值为 `None` 时同一 `imageKey` 重复提交不会命中唯一键，幂等**直接失效**（返回类型里的
   `None` 只服务「显式键缺省且调用方选择不去重」这一形态，当前实现不可达，见函数 docstring）；
3. **MUST NOT 把 `account_id` 拼进键**：`uk_idem` 已是 `(account_id, idem_key)` **两列**，
   再拼一次是重复；「换账号同图 = 不同任务」由两列唯一键实现，不是靠拼串；
4. **`\x00` 分隔符不可省**：`("a", "bc")` 与 `("ab", "c")` 若直接相接会派生出同一个键——
   这是**跨字段的碰撞**，而它恰好会命中幂等、把别人的任务当成自己的返回。用不可出现在
   `imageKey` / `docType` 里的 NUL 作分隔，碰撞面就只剩 sha256 本身。

## 月边界：查幂等与插入 MUST 用同一个月

分片月由**同一个 `now`** 现算（`ShardKey.month` 与 `AiTask.created_at` 同源），
两处共用同一个值。若各算一次「当前时间」，跨月瞬间（23:59:59.999 提交、查幂等已用上月）
会造出重复任务。`tests/api/test_ocr_submit.py` 有专门用例钉住这条（含 docstring 说明
「跨月不幂等是设计而非缺陷」：`uk_idem` 是**同月表内**唯一）。

## 任务类型的唯一来源是**注册表**（控制者裁定，2026-09-19）

`ai_task.type` 的取值域与「M1 能不能提交这一类」都只有一处声明：
`service/task/registry.py` 的 `REGISTRY` 与 `assert_submittable`（`design.md:194`：
「未注册的类型必须显式失败（而非静默忽略），避免告警丢失」）。

本模块因此**不再自带** `OCR_TASK_TYPE` 之类的类型常量（曾有过，已删）：两个来源必然漂移，
而漂移的表现是「注册表说 VISION_REVIEW 未实现、提交路径却照样落库」。
类型经 `submit_ocr_task(policy=…)` 传入，由**受理处**（`api/ocr.py`）先过
`assert_submittable` 再交进来；`new_task` 只按传入值落库，MUST NOT 自己查表或校验类型
（准入判定属注册表职责，重复实现会让两处判定漂移）。

## 写后立即读（`er.md` §5.5）

`submit_ocr_task` 的读（幂等查询）、写（`insert`）、写后立即读（按主键查回）走的是
**调用方传入的同一个 `Session`**：`repository/base.py` 的 R3 保证「同会话即主库连接」，
故「刚写的行立刻被轮询读到」这件事不需要调用方额外做对什么。MUST NOT 在这里自开引擎或
自造会话——事务边界与「走主库还是从库」都归调用方（路由）决定。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aicore.core.config import is_blank
from aicore.core.errors import (
    PARAM_VALUE_CODE,
    AiCoreError,
    ParamError,
)
from aicore.core.idgen import new_id
from aicore.repository.base import ShardKey
from aicore.repository.models import AiTask
from aicore.repository.task_repo import TaskRepo
from aicore.service.task.registry import TaskPolicy
from aicore.service.task.state import PROCESSING

_logger = logging.getLogger(__name__)

#: `idem_key` 的列宽（`er.md` §6.1 L290：`varchar(64)`）。
MAX_IDEM_KEY_LENGTH: Final = 64

#: 派生键的 hex 位数。取 32（**128 位熵**）的理由：按生日界，128 位在「单表 2000 万行即再分」
#: （`er.md` §5.2）的容量下碰撞概率可忽略，且与全服务 32 字符业务号（`er.md` §5.4）同形；
#: 余下的 32 字符余量留给显式键（客户端可能带更长的业务键）。
_DERIVED_IDEM_KEY_LENGTH: Final = 32

if _DERIVED_IDEM_KEY_LENGTH > MAX_IDEM_KEY_LENGTH:  # pragma: no cover - 导入期自检
    # 常量被改坏时**导入即炸**，而不是等落库时被 MySQL 截断/报错（那时离原因很远）。
    raise RuntimeError(
        f"派生幂等键长度 {_DERIVED_IDEM_KEY_LENGTH} 超过列宽 {MAX_IDEM_KEY_LENGTH}"
        f"（er.md §6.1 L290）：改常量前先确认列宽"
    )


class TaskNotPersistedError(AiCoreError):
    """写入后立即读**没能读回**刚写的任务（业务码 `5000`，HTTP 500）。

    这是**不该发生**的形态：同一个会话、同一张月表、按主键读回。读到 `None` 只可能是
    「写没落下去」或「读打到了别的表」，两种都会让调用方拿到一个**查不到的任务号**
    （受理回执说成功、轮询永远 404），故 fail fast 抛内部错误，MUST NOT 当成正常返回。

    文案取平台默认（`core/errors.py` 的「服务内部错误」），**不回显内部细节**；
    诊断信息（分片月）由 `submit_ocr_task` 写进日志，堆栈与细节不进响应体。
    """

    code: int = 5000


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """提交结果：任务本体 + 本次是否**新建**。

    `created=False` 表示幂等命中（返回的是**既有**任务，MUST NOT 改动它任何一列）。
    调用方据此区分「新建」与「命中」，但两者对外的受理回执形状相同（`TaskAccepted`）。
    """

    task: AiTask
    created: bool


def compute_idem_key(*, explicit: str | None, image_key: str, doc_type: str) -> str | None:
    """算出生效的幂等键（显式优先，否则由 `imageKey` + `docType` 派生）。

    返回类型是 `str | None`（`ai_task.idem_key` 可空，见 `er.md` §6.1 L290），
    但**当前实现永远不会返回 `None`**：两条分支都产出字符串。保留 `None` 这一支是为了
    「调用方显式选择不做去重」这种形态留在签名里（列可空、`find_by_id_key` 也有跳过查询的
    分支），MUST NOT 把它读成「派生分支可能失败所以给了 None」——派生分支**不可能**为 None，
    那正是下面这段实现要保证的事。

    空白串按「没给」处理：`Idempotency-Key: `（头在、值为空）不是有效的幂等键，
    若原样传给仓储会在 `require_shard_key` 处变成 `1001 缺分片键`——把「客户端没给键」
    报成「缺分片键」既错又难查；当成没给、改走派生，幂等语义反而更完整。
    """
    if explicit is not None and not is_blank(explicit):
        if len(explicit) > MAX_IDEM_KEY_LENGTH:
            raise ParamError(
                f"幂等键长度 {len(explicit)} 超过 idem_key 列宽 {MAX_IDEM_KEY_LENGTH}"
                f"（er.md §6.1 L290）：MUST NOT 静默截断（截断会让不同键碰撞）",
                code=PARAM_VALUE_CODE,
            )
        return explicit
    digest = hashlib.sha256(f"{image_key}\x00{doc_type}".encode()).hexdigest()
    return digest[:_DERIVED_IDEM_KEY_LENGTH]


def new_task(*, account_id: str, task_type: str, idem_key: str | None, now: datetime) -> AiTask:
    """按 `er.md` §6.1 L284-298 **逐列**造一条新任务（不落库）。

    逐列口径（`status`/`progress`/`error_code`/`model_meta`/`is_eval_sample`/`finished_at`
    的取值都出自该表，不是实现者的偏好）：

    | 列 | 取值 | 依据 |
    |---|---|---|
    | `task_id` | `new_id("task", at=now)`（32 位业务号，非雪花） | `er.md` §5.4 v1.3 |
    | ↑ 其中**内嵌创建月 `YYYYMM`**，故轮询能自行定位月表（见 `query.py`） | 同上 |
    | `type` | 传入的 `task_type`（受理处从注册表策略里带来） | §6.1 L291 + `design.md:194` |
    | `status` | 固定 `PROCESSING`——**不得由调用方指定** | §6.1 L292 列默认值 |
    | `progress` | `0` | §6.1 L293「0~100」 |
    | `error_code` / `finished_at` | `None`（终态才有值） | §6.1 L294 / L298 |
    | `model_meta` | `None`：**执行期才写血缘**（通道/供应商/prompt 版本），归 4.7 | §6.1 L295 |
    | `is_eval_sample` | `False`：固定评估集样本由取样流程标记，不在提交期决定 | §6.1 L296 |

    `now` 由**调用方**传入（可注入固定时钟）：测试要能构造跨月边界与固定时间，
    而测试内 MUST NOT 出现任意 sleep（`tests/conftest.py` 文件头）。
    **时区口径**：`er.md` §6 绪定「UTC 存储」，故传 UTC 感知时间；
    naive 值会在 `TaskRepo.insert` / `ShardKey` 处被拒（`ParamError(1002)`），
    因为「猜错时区」的表现是**静默跨月错片**，比抛错危险得多。
    """
    return AiTask(
        task_id=new_id("task", at=now),
        account_id=account_id,
        idem_key=idem_key,
        type=task_type,
        status=PROCESSING,
        progress=0,
        error_code=None,
        model_meta=None,
        is_eval_sample=False,
        created_at=now,
        finished_at=None,
    )


def submit_ocr_task(
    session: Session,
    *,
    account_id: str,
    image_key: str,
    doc_type: str,
    idem_key: str | None,
    now: datetime,
    policy: TaskPolicy,
) -> SubmitOutcome:
    """受理一次 OCR 提交：幂等命中即返回既有任务，否则落库并读回。**顺序是硬要求**。

    1. **先查幂等**：`find_by_idem_key` **带 `account_id`**（`uk_idem` 是两列唯一键）——
       只按 `idem_key` 查会让 A 账号的键命中 B 账号的任务；
    2. **命中即返回**（`created=False`）：MUST NOT 新建、MUST NOT 更新既有行任何一列
       （`spec.md:39-40`「返回原任务号，不新建任务、不重复调用模型」——改一列都可能让
       已在执行的任务被重排或结论被覆盖）；
    3. **未命中**：`new_task` + `TaskRepo.insert`（`created=True`）；
    4. **写后立即读**：紧接着用**同一个 `Session`** 按主键查回（`er.md` §5.5：
       任务提交后立即轮询强制走主库；`repository/base.py` R3：同会话即主库连接）。
       读回的行才是返回值——受理回执因此反映**库里真实的行**，而不是内存里那份「以为写进去了」
       的对象。

    `idem_key` 形参是**显式的头值**（未给为 `None`）；生效键由 `compute_idem_key` 在内部派生
    ——派生规则属 service 关切，api 层只负责把请求头原样带进来，MUST NOT 在路由里重写一遍
    （`image_key` / `doc_type` 也因此不是摆设：它们正是派生分支的输入）。

    `policy` 是**已过准入判定**的任务类型策略（受理处调 `assert_submittable` 的返回值）：
    本函数不重复判定，只取 `policy.task_type` 落库。把「准入」与「使用」分成两步，
    是为了让「未实现类型被拒」只发生在受理处一个地方（两处判定必然漂移）。

    ## 并发同键：撞 `uk_idem` 之后**回读原任务**，而不是报 5000（Task 4.9 收口）

    第 1 步（查幂等）与第 3 步（插入）是两次独立语句，**并发**请求可能同时通过第 1 步，
    于是第二个 `insert` 撞 `uk_idem(account_id, idem_key)` 唯一键。T1 把它登记为已知缺口；
    本任务按 `spec.md:25`「重复提交 MUST 幂等，返回**原任务标识**而不重复产生任务与调用费用」
    收口——**并发重复是"重复提交"的一种**，故处置与串行重复一致：**返回原任务**。

    实现要点（三条都必须做对）：

    1. **只捕 `IntegrityError`，且只在"确实能回读到原任务"时才吸收**：回读成功 ⇒ 返回原任务
       （`created=False`）；回读为空 ⇒ **原样重抛**。冲突可能来自别的约束（外键等），
       把"读不到"也当成幂等命中会把一次真实的写失败伪装成成功——那比报错危险得多；
    2. **回读前必须 `rollback()`**：`IntegrityError` 之后会话处于"失败事务"状态，
       不先回滚的话后续 `SELECT` 会被驱动/ORM 直接拒绝（psycopg 的
       `current transaction is aborted` 同族形态）。事务边界归 service（`repository/base.py`
       的 `_insert` 明说"不 commit、不 flush，事务边界归调用方"）；
    3. **回读走的是同一个会话**——它来自 `factory.write_session()`（**主库**）：
       `er.md:287` 逐字「关键**写后立即读**（任务提交后立即轮询）**强制走主库**，
       避免主从延迟读到旧状态」。若这里另开一个只读会话，恰好会从从库读到一个**还没同步**
       的空结果，于是"回读为空 ⇒ 重抛"变成常态——收口反而把冲突重新变成 5000。

    吸收成功时记一条 **INFO**（不是 WARNING）：这是**设计内的**并发形态、且已经正确收口，
    运维看到它应当知道"有一次并发重复提交被吸收了"，而不是"出错了"。
    `_resubmit_after_key_conflict` 是这段逻辑的唯一落点（含上面三条的逐条注释）。
    """
    shard = ShardKey(account_id=account_id, created_at=now)
    repo = TaskRepo()
    effective_key = compute_idem_key(explicit=idem_key, image_key=image_key, doc_type=doc_type)
    if effective_key is not None:
        existing = repo.find_by_idem_key(
            session,
            shard=shard,
            account_id=account_id,
            idem_key=effective_key,
        )
        if existing is not None:
            return SubmitOutcome(task=existing, created=False)
    task = new_task(
        account_id=account_id,
        task_type=policy.task_type,
        idem_key=effective_key,
        now=now,
    )
    try:
        repo.insert(session, task)
    except IntegrityError:
        if effective_key is None:
            # 没有幂等键就不可能撞 `uk_idem`（NULL 豁免），故这次冲突来自别的约束
            # ⇒ 不吸收，原样上抛（不把别的写失败伪装成幂等命中）。
            raise
        absorbed = _resubmit_after_key_conflict(
            session,
            repo,
            shard=shard,
            account_id=account_id,
            idem_key=effective_key,
            task_id=task.task_id,
        )
        if absorbed is not None:
            return absorbed
        raise
    persisted = repo.get_by_id(session, task.task_id, shard=shard)
    if persisted is None:
        _logger.error(
            "任务写入后立即读失败：分片月=%s（同会话按主键读回为空，写后立即读未能成立）",
            shard.month,
        )
        raise TaskNotPersistedError
    return SubmitOutcome(task=persisted, created=True)


def _resubmit_after_key_conflict(
    session: Session,
    repo: TaskRepo,
    *,
    shard: ShardKey,
    account_id: str,
    idem_key: str,
    task_id: str,
) -> SubmitOutcome | None:
    """`uk_idem` 冲突后的回读：拿到**原任务**就返回它，读不到返回 `None`（由调用方重抛）。

    三条要求的落点（理由全在 `submit_ocr_task` 的"并发同键"一节，这里只写怎么做）：

    1. `session.rollback()`——把会话从"失败事务"状态里带出来，之后的 `SELECT` 才执行得了；
    2. 用**同一个会话**（主库）按 `(account_id, idem_key)` + **同一个分片月**回读：
       月必须与插入用的是同一个 `now` 派生的月，否则会去另一张表里找一个不在那里的行；
    3. 回读带 `account_id`（`uk_idem` 是两列）：只按 `idem_key` 查会让 A 账号的键
       命中 B 账号的任务——那正是 R6 禁的形态。

    `task_id` 只用于日志（把"被丢弃的那个号"与"留下来的那个号"都记下来，
    排查并发问题时能对上）。
    """
    session.rollback()
    existing = repo.find_by_idem_key(
        session,
        shard=shard,
        account_id=account_id,
        idem_key=idem_key,
    )
    if existing is None:
        return None
    _logger.info(
        "并发同幂等键提交：本次插入的 %s 撞了 uk_idem，已回读并返回原任务 %s"
        "（account=%s、分片月=%s；spec.md:25 的「返回原任务标识」对并发同样成立）",
        task_id,
        existing.task_id,
        account_id,
        shard.month,
    )
    return SubmitOutcome(task=existing, created=False)
