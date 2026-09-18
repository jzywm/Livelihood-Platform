"""前缀化业务 ID（`前缀 + UUID4 hex`，**总长恒为 32**）。

## 权威口径

- `er.md` §5.4 L239–L248：各表 ID 的生成方式；**「Python 侧不参与雪花域」**——
  AICORE 用业务号 + UUID，**不用雪花、无 workerId、无时钟回拨风险面**；
- spec §2.3：ID 形态 `前缀 + UUID`，**均为 `varchar(32)`**；
- spec §5.8：格式 `前缀 + UUID 去连字符后的 hex`，**总长必须 ≤32**，
  「裸 UUID 是 36 字符，**超限 4 位**」是本项最容易写错的地方，
  故生成时**校验总长 ≤32，超限即抛错**（而非静默截断）。

## 6 个前缀（逐字取自 `er.md` §5.4，含下划线）

| `kind` | 前缀 | 对应 ID 列 |
|---|---|---|
| `task` | `task_` | `ai_task.task_id` / `ocr_result.task_id` |
| `cor` | `cor_` | `ocr_correction.correction_id` |
| `rev` | `rev_` | `vision_review.review_id` / `review_verdict.review_id` |
| `marker` | `marker_` | `vision_marker.marker_id` |
| `kan` | `kan_` | `kitchen_anomaly.anomaly_id` |
| `qa` | `qa_` | `vision_qa_log.qa_id` |

`risk_predict_result.merchant_id` **不在本表**：`er.md` §5.4 L244 明写
「**源服务生成，只读引用，不重新发号**」——本服务 MUST NOT 给它发号，
故 `new_id("merchant")` 抛 `ValueError`。

## 为什么截断 UUID 是安全的（不是权宜之计）

UUID4 有 **122 位随机性**；本模块保留 100~116 位（25~29 个 hex 字符）。
按生日界，该位数下的碰撞概率远低于同月分片表的容量上限
（`er.md` §5.2：单表 >2000 万行即触发再分），且 ID 的唯一性**最终由数据库主键约束兜底**。
两害相权：截断的风险是"概率极低的主键冲突"，超长的风险是**每一行都写不进去**。

即便如此，`new_id` 仍在生成后**自校验**长度与格式，不满足即抛 `ValueError`——
这是"常量被改错时立刻炸"的保险，而不是靠调用方记得检查。
"""

from __future__ import annotations

import re
import uuid
from typing import Final

#: 所有 ID 列的宽度（`er.md` §5.4 均为 `varchar(32)`）。
MAX_ID_LENGTH: Final[int] = 32

#: `kind` -> 前缀。**前缀自带下划线**，取值逐字对齐 `er.md` §5.4。
ID_PREFIXES: Final[dict[str, str]] = {
    "task": "task_",
    "cor": "cor_",
    "rev": "rev_",
    "marker": "marker_",
    "kan": "kan_",
    "qa": "qa_",
}

#: 每个前缀下 UUID hex 取多少位 = `MAX_ID_LENGTH - len(prefix)`。
#: 由常量现算而非写字面量：改 `MAX_ID_LENGTH` 或改前缀长度时不会留下第二份会漂移的账。
_UUID_HEX_LENGTHS: Final[dict[str, int]] = {
    kind: MAX_ID_LENGTH - len(prefix) for kind, prefix in ID_PREFIXES.items()
}

#: 合法 ID：`<前缀><恰好该前缀应有的 hex 位数>`。
#:
#: **逐前缀各生成一条分支**，而不是"任意前缀 + 任意位数 + 事后循环比对"：
#: 逐前缀分支让"长度必须与该前缀相符"由正则**构造**保证，
#: 不依赖后续循环里的 `startswith` 判断顺序（那种写法在新增前缀时会静默放宽）。
#: 用 `fullmatch`（不是 `match`）：`match` 会放过尾随垃圾字符，
#: 而 ID 会被直接写进 `varchar(32)` 主键。
_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    "|".join(
        f"{re.escape(ID_PREFIXES[_kind])}[0-9a-f]{{{_UUID_HEX_LENGTHS[_kind]}}}"
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


def new_id(kind: str) -> str:
    """生成一个 `kind` 类型的 ID，**总长恒等于 `MAX_ID_LENGTH`**。

    先取 `uuid4().hex` 再截到该前缀允许的位数。截断位置由 `_UUID_HEX_LENGTHS` 决定，
    **MUST NOT** 在函数体里写 `[:27]` 这类字面量——长度账只允许有一处。
    """
    prefix = _require_known_kind(kind)
    value = prefix + uuid.uuid4().hex[: _UUID_HEX_LENGTHS[kind]]
    # 自校验：常量被改错时立刻炸，而不是把一个超长串送去数据库。
    if len(value) != MAX_ID_LENGTH:
        raise ValueError(
            f"生成的 ID 长度 {len(value)} 不等于 {MAX_ID_LENGTH}（前缀 {prefix!r}）："
            f"检查 ID_PREFIXES / MAX_ID_LENGTH 是否被改坏"
        )
    if not validate_id(value, kind):  # pragma: no cover - 不可达的防御性检查
        # 为什么标 `no cover` 而不是造一个测试：`_UUID_HEX_LENGTHS` 由 `MAX_ID_LENGTH` 与前缀长度
        # **现算**，故"长度对但格式不对"在结构上进不来（上面的长度检查已先拦）。
        # 留它在这儿是为了挡住"将来有人把 `_UUID_HEX_LENGTHS` 改成手写字面量"这种改法——
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
    - 前缀之后全是**小写 hex**，且非空；
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
        return len(remainder) == _UUID_HEX_LENGTHS[kind] and bool(
            re.fullmatch(r"[0-9a-f]+", remainder)
        )
    return _ID_PATTERN.fullmatch(value) is not None
