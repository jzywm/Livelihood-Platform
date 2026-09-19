"""前缀化业务 ID（`前缀 + UUID4 hex`，**总长恒为 32**；`task_id` 额外带创建月）。

## 权威口径

- `er.md` §5.4 L239–L248：各表 ID 的生成方式；**「Python 侧不参与雪花域」**——
  AICORE 用业务号 + UUID，**不用雪花、无 workerId、无时钟回拨风险面**；
- spec §2.3：ID 形态 `前缀 + UUID`，**均为 `varchar(32)`**；
- spec §5.8：格式 `前缀 + UUID 去连字符后的 hex`，**总长必须 ≤32**，
  「裸 UUID 是 36 字符，**超限 4 位**」是本项最容易写错的地方，
  故生成时**校验总长 ≤32，超限即抛错**（而非静默截断）。
- **`er.md` §5.4「为什么 task_id 带月份」（2026-09-19 定档，v1.3）**：
  `task_id` 形如 `task_` + `YYYYMM`（创建月）+ UUID hex，**总长仍恒为 32**。

## 6 个前缀（逐字取自 `er.md` §5.4，含下划线）

| `kind` | 前缀 | 对应 ID 列 | 带月份？ |
|---|---|---|---|
| `task` | `task_` | `ai_task.task_id` / `ocr_result.task_id` | **是** |
| `cor` | `cor_` | `ocr_correction.correction_id` | 否 |
| `rev` | `rev_` | `vision_review.review_id` / `review_verdict.review_id` | 否 |
| `marker` | `marker_` | `vision_marker.marker_id` | 否 |
| `kan` | `kan_` | `kitchen_anomaly.anomaly_id` | 否 |
| `qa` | `qa_` | `vision_qa_log.qa_id` | 否 |

`risk_predict_result.merchant_id` **不在本表**：`er.md` §5.4 L244 明写
「**源服务生成，只读引用，不重新发号**」——本服务 MUST NOT 给它发号，
故 `new_id("merchant")` 抛 `ValueError`。

## 为什么只有 `task_id` 带月份

因为**只有它承担跨月定位职责**：`GET /aicore/tasks/{taskId}` 的入参只有 `task_id`，
而 `ai_task` 按月分表——月份必须能从 `task_id` 自身得出，否则轮询无法定位月表
（`er.md` §5.4 详述了这个问题与后果）。
`cor_` / `rev_` / `marker_` / `kan_` / `qa_` 各自按自己的业务键访问
（`task_id`、`review_id`、`merchant_id`…），不承担跨月定位职责，
给它们加月份只会白占长度、并连带改动各自的宽度账。

## 为什么截断 UUID 是安全的（不是权宜之计）

UUID4 有 **122 位随机性**；本模块保留 **84~116 位**
（`task_` 因带 6 位月份只余 21 个 hex 字符 = 84 位，其余前缀 25~29 位 = 100~116 位）。
按生日界，84 位在「单表 2000 万行即触发再分」（`er.md` §5.2）的容量下碰撞概率可忽略，
且 ID 的唯一性**最终由数据库主键约束兜底**。
两害相权：截断的风险是"概率极低的主键冲突"，超长的风险是**每一行都写不进去**。

即便如此，`new_id` 仍在生成后**自校验**长度与格式，不满足即抛 `ValueError`——
这是"常量被改错时立刻炸"的保险，而不是靠调用方记得检查。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Final

#: 所有 ID 列的宽度（`er.md` §5.4 均为 `varchar(32)`）。
MAX_ID_LENGTH: Final[int] = 32

#: 创建月段的位数：`YYYYMM`，6 位十进制（`er.md` §5.4 v1.3）。
MONTH_DIGITS: Final[int] = 6

#: `kind` -> 前缀。**前缀自带下划线**，取值逐字对齐 `er.md` §5.4。
ID_PREFIXES: Final[dict[str, str]] = {
    "task": "task_",
    "cor": "cor_",
    "rev": "rev_",
    "marker": "marker_",
    "kan": "kan_",
    "qa": "qa_",
}

#: 带创建月的 ID 类型。**只有 `task`**：见模块 docstring「为什么只有 task_id 带月份」。
MONTH_AWARE_KINDS: Final[frozenset[str]] = frozenset({"task"})

#: 每类 ID 的 hex 位数。**由 `MAX_ID_LENGTH`、`ID_PREFIXES` 与 `MONTH_DIGITS` 现算**，
#: 不写字面量：改任一处常量时不会留下第二份会漂移的账。
#: 带月份的类要额外扣掉 `MONTH_DIGITS` 位。
#:
#: **公开导出（Task 3.8 独立评审后改名）**：验收脚本与用例要断言
#: "前缀长度 + 月份位数 + hex 位数 == 32"这条**算术本身**，而它是本模块对外可见的契约
#: （各前缀的位数分布影响可读性与排障），不是内部实现细节。
ID_PREFIX_LENGTHS: Final[dict[str, int]] = {
    kind: MAX_ID_LENGTH - len(prefix) - (MONTH_DIGITS if kind in MONTH_AWARE_KINDS else 0)
    for kind, prefix in ID_PREFIXES.items()
}

#: 月份段的匹配式：6 位十进制，且**首两位是 `20`**（本平台的生命周期内年份都以 20 开头）。
#: 收紧到 `20\d{4}` 而不是 `\d{6}`：后者会把 `task_999999…` 这类明显非月份的值放过，
#: 而它在业务上只会表现为"路由到一张永远不存在的表"——比当场拒绝难查得多。
_MONTH_PATTERN: Final[re.Pattern[str]] = re.compile(r"20\d{4}")

#: 合法 ID：`<前缀>[<月份>]<恰好该前缀应有的 hex 位数>`。
#:
#: **逐前缀各生成一条分支**，而不是"任意前缀 + 任意位数 + 事后循环比对"：
#: 逐前缀分支让"长度必须与该前缀相符（含月份段）"由正则**构造**保证，
#: 不依赖后续循环里的 `startswith` 判断顺序（那种写法在新增前缀时会静默放宽）。
#: 用 `fullmatch`（不是 `match`）：`match` 会放过尾随垃圾字符，
#: 而 ID 会被直接写进 `varchar(32)` 主键。
_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    "|".join(
        f"{re.escape(ID_PREFIXES[_kind])}"
        + (r"20\d{4}" if _kind in MONTH_AWARE_KINDS else "")
        + f"[0-9a-f]{{{ID_PREFIX_LENGTHS[_kind]}}}"
        for _kind in ID_PREFIXES
    )
)


def _require_known_kind(kind: str) -> str:
    """取前缀；未知 `kind` 抛 `ValueError`（fail fast，与 `AiCoreError` 的构造期校验同取向）。"""
    try:
        return ID_PREFIXES[kind]
    except KeyError:
        raise ValueError(
            f"未知的 ID 类型 {kind!r}：只能是 {sorted(ID_PREFIXES)} 之一"
            f"（`merchant` 刻意不在其中：er.md §5.4 L244 规定其 ID 由源服务生成、本服务只读引用）"
        ) from None


def task_month_of(task_id: str) -> str:
    """从 `task_id` 解析出创建月 `YYYYMM`。

    **这是「轮询跨月可查」的落地点**（`er.md` §5.4 v1.3）：`GET /aicore/tasks/{taskId}`
    的入参只有 `task_id`，月份只能从这里来；逐月试探扫描被
    `er.md` §5.3「查询 MUST 携带分片键下推」直接禁止。

    传进来的值**不是合法 `task_id`** 时抛 `ValueError`：调用方（路由层）应当先用
    `validate_id(value, "task")` 判定，把它当**入参格式错误**（`1003`）处理，
    而不是让它变成一次"路由到不存在的表"的静默失败。
    """
    if not validate_id(task_id, "task"):
        raise ValueError(
            f"不是合法的任务号（{task_id!r}）：期望 `task_` + 6 位创建月 + "
            f"{ID_PREFIX_LENGTHS['task']} 位小写 hex，总长 {MAX_ID_LENGTH}"
            f"（er.md §5.4 的 `task_id` 形态）"
        )
    prefix = ID_PREFIXES["task"]
    return task_id[len(prefix) : len(prefix) + MONTH_DIGITS]


def new_id(kind: str, *, at: datetime | None = None) -> str:
    """生成一个 `kind` 类型的 ID，**总长恒等于 `MAX_ID_LENGTH`**。

    先取 `uuid4().hex` 再截到该前缀允许的位数。截断位置由 `ID_PREFIX_LENGTHS` 决定，
    **MUST NOT** 在函数体里写 `[:21]` 这类字面量——长度账只允许有一处。

    **`at` 是 `kind in MONTH_AWARE_KINDS`（当前只有 `task`）时的必填参数**：
    它给出**创建时刻**，取其 UTC 年月（`YYYYMM`）拼进 ID。
    - **MUST 由调用方传入**，MUST NOT 在函数内取 `datetime.now()`：
      那样"这个任务属于哪个月"就有两个来源（调用方用于算分片 `created_at` 的时钟、
      与本函数内部的时钟），两者一旦不一致，就会出现**ID 里的月份与落库的分片表不符**——
      表现为"提交成功但轮询 404"，且难以复现。强制传入使月份只有一个来源。
    - 不做「未传就回落到当前时间」的兜底：那正是上面那个双源问题的另一种写法。
    """
    prefix = _require_known_kind(kind)
    month = ""
    if kind in MONTH_AWARE_KINDS:
        if at is None:
            raise ValueError(
                f"生成 {kind!r} 类 ID 必须传 `at`（创建时刻）：ID 内嵌的创建月来自它，"
                f"MUST NOT 让本函数自己取当前时间（那会让 ID 里的月份与落库分片表有两个来源）"
            )
        month = f"{at.year:04d}{at.month:02d}"
        if not _MONTH_PATTERN.fullmatch(month):  # pragma: no cover - 年份越界才可达
            raise ValueError(
                f"创建月 {month!r} 不在支持的范围内（`20\\d{{4}}`）："
                f"ID 里的月份段是 `er.md` §5.4 定档的 6 位 `YYYYMM`"
            )
    value = prefix + month + uuid.uuid4().hex[: ID_PREFIX_LENGTHS[kind]]
    # 自校验：常量被改错时立刻炸，而不是把一个超长串送去数据库。
    if len(value) != MAX_ID_LENGTH:
        raise ValueError(
            f"生成的 ID 长度 {len(value)} 不等于 {MAX_ID_LENGTH}（前缀 {prefix!r}）："
            f"检查 ID_PREFIXES / ID_PREFIX_LENGTHS / MAX_ID_LENGTH 是否被改坏"
        )
    if not validate_id(value, kind):  # pragma: no cover - 不可达的防御性检查
        # 为什么标 `no cover` 而不是造一个测试：`ID_PREFIX_LENGTHS` 由 `MAX_ID_LENGTH` 与前缀长度
        # **现算**，故"长度对但格式不对"在结构上进不来（上面的长度检查已先拦）。
        # 留它在这儿是为了挡住"将来有人把 `ID_PREFIX_LENGTHS` 改成手写字面量"这种改法——
        # 那时本分支就会变成可达的真防线。造一个测试只能靠 monkeypatch 把常量改成自相矛盾的值，
        # 那种测试测的是"猴补丁生效"，不是这条断言的价值。
        raise ValueError(f"生成的 ID 未通过自校验：{value!r}")
    return value


def validate_id(value: str, kind: str | None = None) -> bool:
    """校验 ID 形态。

    口径（**MUST 精确，过宽等于没校验**）：

    - 长度**恰好等于** `MAX_ID_LENGTH`：`new_id` 恒生成满 32 位，
      若只要求"在 `len(prefix)+1 .. 32` 之间"，一个被错误截短的串也会被放过；
    - 命中**某个**已知前缀（`kind` 给出时必须是该 kind 的前缀）；
    - `kind in MONTH_AWARE_KINDS`（`task`）时，前缀之后**必须是 6 位 `YYYYMM`**
      （且年份以 `20` 开头），其后才是 hex；
    - 其余部分全是**小写 hex**，且非空；
    - `value` 不是 `str`（如 `None`）一律为 `False`，不抛异常——本函数用于"值可能来自外部"的判定点。

    `kind` 未知时抛 `ValueError`（与 `new_id` 一致：这是**编程错误**，不是数据问题）。
    """
    if not isinstance(value, str):
        return False
    if len(value) != MAX_ID_LENGTH:
        return False
    if kind is not None:
        prefix = _require_known_kind(kind)
        if not value.startswith(prefix):
            return False
        remainder = value[len(prefix) :]
        if kind in MONTH_AWARE_KINDS:
            month, remainder = remainder[:MONTH_DIGITS], remainder[MONTH_DIGITS:]
            if not _MONTH_PATTERN.fullmatch(month):
                return False
        return len(remainder) == ID_PREFIX_LENGTHS[kind] and bool(
            re.fullmatch(r"[0-9a-f]+", remainder)
        )
    return _ID_PATTERN.fullmatch(value) is not None
