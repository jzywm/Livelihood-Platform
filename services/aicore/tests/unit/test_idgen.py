"""`core/idgen.py` 用例（Task 3.8 建立；2026-09-19 按 `er.md` §5.4 v1.3 扩展 `task_id` 月份段）。

## 本文件的核心是「独立预言机」，不是"跑一遍看没报错"

第 3 组独立评审在这里抓到过一处**假绿**：原先 21 处期望值**全部**由 `MAX_ID_LENGTH` 现算，
于是把常量改成**自洽但错误**的值（如 35——各前缀 hex 位数仍落在 `uuid4().hex` 的 32 位之内，
内部自校验不响）时，**整套用例与验收脚本一起变绿**，
而 33~35 字符的 ID 写进 `varchar(32)` 会让**每一行都插不进去**。

故本文件的判据分两层，**两层都要有**：

- **内部自洽**（可现算）：各前缀该有多少位 hex —— 这是被测对象内部的算术，
  现算合理（改前缀时不会留下第二份会漂移的账）；
- **外部契约**（必须写死字面量）：`32` 这个上限、以及 `task_id` 的**月份段是 6 位** ——
  它们来自 `er.md` §5.4/§6，是**文档契约**，不是实现细节。
  缺了这一层，整条验证链就没有独立预言机。

## `task_id` 的月份段（v1.3 新增，本文件相应扩展）

`task_id` = `task_` + 创建月 `YYYYMM` + UUID hex，**总长仍恒为 32**。
故 hex 段从 27 位缩到 **21 位（84 位随机性）**；
`new_id("task")` 因此**必须传 `at`**（创建时刻）——ID 里的月份与落库分片表 MUST 只有一个来源。
"""

from __future__ import annotations

import concurrent.futures
import inspect
import re
from datetime import UTC, datetime, timedelta

import pytest

from aicore.core.idgen import (
    ID_PREFIX_LENGTHS,
    ID_PREFIXES,
    MAX_ID_LENGTH,
    MONTH_AWARE_KINDS,
    MONTH_DIGITS,
    new_id,
    task_month_of,
    validate_id,
)


def idgen_module() -> object:
    """取 `aicore.core.idgen` 模块对象（供 `inspect.getsource` 用）。"""
    import aicore.core.idgen

    return aicore.core.idgen


#: 6 种 kind，逐字对齐 `er.md` §5.4 的 ID 前缀表。
EXPECTED_KINDS = {"task", "cor", "rev", "marker", "kan", "qa"}

#: **外部契约（字面量，MUST NOT 由被测常量现算）**：`er.md` §5.4 的所有 ID 列都是
#: `varchar(32)`，故"总长恰为 32"是一条**来自文档的硬约束**。
CONTRACT_ID_MAX_LENGTH = 32

#: **外部契约（字面量）**：`er.md` §5.4 v1.3 定档 `task_id` 内嵌 `YYYYMM`，即 **6 位十进制**。
#: 与 `CONTRACT_ID_MAX_LENGTH` 同属"文档说了算"的那一层，故不取自 `MONTH_DIGITS`。
CONTRACT_TASK_MONTH_DIGITS = 6

#: **外部契约（字面量）**：`task_` 前缀本身的长度（`er.md` §5.4 表格逐字为 `task_`）。
CONTRACT_TASK_PREFIX = "task_"

#: 固定时刻：`task_id` 需要 `at`，用一个常量让「ID 里的月份」可预期、可断言。
AT = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
AT_MONTH = "202607"


def make_id(kind: str, *, at: datetime = AT) -> str:
    """按 kind 生成 ID。

    `task` 类**必须**给 `at`（模块设计如此），故这里统一用关键字传：
    「所有 kind 用同一个入口生成」让本文件其余用例不必逐个分辨哪类要传时刻。
    """
    return new_id(kind, at=at)


def expected_length(kind: str) -> int:
    """该 kind 的 ID 应有的长度（= 总上限，因为 hex 段按剩余位数截取）。"""
    return MAX_ID_LENGTH


def expected_pattern(kind: str) -> re.Pattern[str]:
    """从 `ID_PREFIXES` / `MONTH_AWARE_KINDS` / `MONTH_DIGITS` 现算该 kind 的完整正则。

    用 `MONTH_DIGITS`（被测常量）而不是字面量 6：本条属**内部自洽层**。
    字面量的那一层由 `test_prefix_and_hex_lengths_sum_to_the_documented_width`
    与 `test_task_id_month_segment_is_six_digits_per_contract` 承担。
    """
    prefix = ID_PREFIXES[kind]
    month = r"20\d{4}" if kind in MONTH_AWARE_KINDS else ""
    hex_len = MAX_ID_LENGTH - len(prefix) - (MONTH_DIGITS if kind in MONTH_AWARE_KINDS else 0)
    return re.compile(rf"^{re.escape(prefix)}{month}[0-9a-f]{{{hex_len}}}$")


# ---------------------------------------------------------------------------
# 第 0 层：独立预言机（对文档契约，不对被测对象）
# ---------------------------------------------------------------------------
def test_max_id_length_matches_the_documented_column_width() -> None:
    """**独立预言机**：`MAX_ID_LENGTH` 必须等于 `er.md` 的列宽 32（字面量，不取自被测对象）。

    这条用例是整个 ID 验证链的**锚**：其余期望值多由 `MAX_ID_LENGTH` 现算，
    没有它，常量被改成自洽的错误值时全套会一起变绿（独立评审的实测：
    改成 35 → 验收脚本仍 PASS 10/FAIL 0、全量只红 1 条附带红）。
    `er.md` §5.4 的每一行 ID 列都是 `varchar(32)` —— 这是**文档契约**，不是实现细节。
    """
    assert MAX_ID_LENGTH == CONTRACT_ID_MAX_LENGTH, (
        f"MAX_ID_LENGTH={MAX_ID_LENGTH} 与 er.md §5.4 的列宽 "
        f"{CONTRACT_ID_MAX_LENGTH} 不符：33+ 字符的 ID 写不进 varchar(32)，每一行都会插不进去"
    )


def test_task_id_month_segment_is_six_digits_per_contract() -> None:
    """**独立预言机（v1.3 新增）**：`task_id` 的月份段长度必须是 **6**（`YYYYMM`）。

    与上一条同理：`MONTH_DIGITS` 被改成 5 或 7 时，ID 仍然"自洽"（长度账会跟着变、
    内部自校验不响），但**违背 `er.md` §5.4 v1.3 定档的 `YYYYMM` 形态**，
    且 5 位的月份无法表达"哪一年"，跨年轮询会路由到错误的表。
    """
    assert MONTH_DIGITS == CONTRACT_TASK_MONTH_DIGITS, (
        f"MONTH_DIGITS={MONTH_DIGITS} 与 er.md §5.4 v1.3 的 `YYYYMM`（6 位）不符"
    )
    assert {"task"} == MONTH_AWARE_KINDS, (
        f"带月份的 ID 类型应恰好是 {{'task'}}，实际 {sorted(MONTH_AWARE_KINDS)}："
        f"er.md §5.4 只为 `task_id` 定档了自描述分片月"
    )


def test_every_prefix_actually_produces_exactly_32_characters() -> None:
    """六种前缀各自生成的 ID，长度**恰好** 32（不是"不超过"）。

    与 `test_each_prefix_generates_a_valid_id_of_exact_length` 的区别：那条用的
    `expected_length(kind)` 由 `MAX_ID_LENGTH` 现算，属"内部自洽"；
    本条把 32 写成字面量，属"对文档契约的独立核对"。两条都要有。
    """
    for kind in sorted(EXPECTED_KINDS):
        value = make_id(kind)
        assert len(value) == CONTRACT_ID_MAX_LENGTH, (
            f"{kind} 生成的 ID 长度 {len(value)}，契约要求恰好 {CONTRACT_ID_MAX_LENGTH}：{value!r}"
        )


def test_prefix_and_hex_lengths_sum_to_the_documented_width() -> None:
    """前缀长度 + 月份位数（仅 task）+ hex 位数 == 32，且**逐前缀**核对（防"一长一短互相掩盖"）。"""
    for kind in sorted(EXPECTED_KINDS):
        prefix = ID_PREFIXES[kind]
        month_len = MONTH_DIGITS if kind in MONTH_AWARE_KINDS else 0
        hex_len = ID_PREFIX_LENGTHS[kind]
        assert len(prefix) + month_len + hex_len == CONTRACT_ID_MAX_LENGTH, (
            f"{kind}: 前缀 {len(prefix)} + 月份 {month_len} + hex {hex_len} "
            f"!= {CONTRACT_ID_MAX_LENGTH}"
        )


def test_task_id_is_prefix_plus_month_plus_hex_total_32() -> None:
    """把 `task_id` 的**逐段形态**钉成可读的一条（契约的"最小可核形式"）。

    62 位 UUID hex 里我们只取 21 位；本条同时断言**熵的下限**：
    21 个 hex 字符 = 84 位随机性，与 `er.md` §5.4 的生日界论证一致
    （单表 2000 万行触发再分，84 位下碰撞概率可忽略）。
    """
    prefix = CONTRACT_TASK_PREFIX
    task_id = make_id("task")
    assert task_id.startswith(prefix), task_id
    month = task_id[len(prefix) : len(prefix) + CONTRACT_TASK_MONTH_DIGITS]
    payload = task_id[len(prefix) + CONTRACT_TASK_MONTH_DIGITS :]
    assert month == AT_MONTH, f"月份段应是 {AT_MONTH}（来自 at），实际 {month}"
    assert len(payload) == ID_PREFIX_LENGTHS["task"]
    assert ID_PREFIX_LENGTHS["task"] * 4 >= 64, (
        f"task 的 hex 段只有 {ID_PREFIX_LENGTHS['task'] * 4} 位随机性，低于可接受的 64 位"
    )
    assert len(task_id) == CONTRACT_ID_MAX_LENGTH


# ---------------------------------------------------------------------------
# 第 1 层：生成与校验
# ---------------------------------------------------------------------------
def test_prefix_table_is_exactly_the_six_from_er_md() -> None:
    """前缀表恰好 6 项且前缀带下划线：`er.md` §5.4 逐字。"""
    assert set(ID_PREFIXES) == EXPECTED_KINDS, f"kind 集合不符：{sorted(ID_PREFIXES)}"
    for kind, prefix in ID_PREFIXES.items():
        assert prefix.endswith("_"), f"{kind} 的前缀 {prefix!r} 未带下划线（er.md 均为 `xxx_`）"
        assert prefix.isascii() and prefix.islower(), f"{kind} 的前缀 {prefix!r} 应为小写 ASCII"


def test_merchant_is_not_issuable() -> None:
    """`merchant` 不在前缀表：er.md §5.4 L244 规定其 ID 由源服务生成、本服务只读引用。"""
    assert "merchant" not in ID_PREFIXES
    with pytest.raises(ValueError, match="merchant"):
        new_id("merchant")


@pytest.mark.parametrize("kind", sorted(EXPECTED_KINDS))
def test_each_prefix_generates_a_valid_id_of_exact_length(kind: str) -> None:
    """6 种前缀各生成一次：前缀正确、长度恰好 32、通过校验。"""
    value = make_id(kind)
    assert value.startswith(ID_PREFIXES[kind]), f"{kind} 的前缀不对：{value!r}"
    assert len(value) == expected_length(kind), (
        f"{kind} 长度 {len(value)} != {expected_length(kind)}"
    )
    assert len(value) <= MAX_ID_LENGTH
    assert expected_pattern(kind).match(value), f"{kind} 不匹配现算正则：{value!r}"
    assert validate_id(value, kind) is True
    assert validate_id(value) is True  # kind=None 的通用分支也要认


def test_ids_are_lowercase_hex_after_prefix() -> None:
    """前缀（与 task 的月份段）之后必须是**小写** hex（大写会让"同一 ID"出现两种写法）。"""
    for kind in EXPECTED_KINDS:
        offset = len(ID_PREFIXES[kind]) + (MONTH_DIGITS if kind in MONTH_AWARE_KINDS else 0)
        remainder = make_id(kind)[offset:]
        assert remainder == remainder.lower(), f"{kind} 的 hex 段含大写：{remainder!r}"
        assert all(char in "0123456789abcdef" for char in remainder), (
            f"{kind} 的 hex 段含非 hex 字符：{remainder!r}"
        )


def test_ten_thousand_concurrent_ids_are_unique_and_all_valid() -> None:
    """**并发生成 1 万个**：全量过正则 + 无重复（spec §5.8 的明确要求）。

    用线程池而不是串行循环：`uuid4().hex` 的截断正确性在并发下才谈得上被验证；
    串行循环既证明不了并发安全，也更容易"碰巧"不复现问题。
    """
    total = 10_000
    kinds = sorted(EXPECTED_KINDS)

    def make(index: int) -> str:
        return make_id(kinds[index % len(kinds)])

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(make, range(total)))

    assert len(ids) == total
    assert len(set(ids)) == total, f"出现重复 ID：{total - len(set(ids))} 个"

    invalid_length = [value for value in ids if len(value) > MAX_ID_LENGTH]
    assert not invalid_length, f"{len(invalid_length)} 个 ID 超过 {MAX_ID_LENGTH} 字符"

    # 逐 kind 现算正则做全量校验（不用通用分支，确保每种前缀都被覆盖到）
    for kind in kinds:
        pattern = expected_pattern(kind)
        for value in ids:
            if value.startswith(ID_PREFIXES[kind]):
                assert pattern.match(value), f"{kind} 的 ID 不匹配：{value!r}"
    bad = [value for value in ids if not validate_id(value)]
    assert not bad, f"{len(bad)} 个 ID 未通过 validate_id，例如 {bad[:3]}"


# ---------------------------------------------------------------------------
# 第 2 层：`task_id` 的月份（v1.3 新增）
# ---------------------------------------------------------------------------
def test_task_month_of_round_trips_the_creation_month() -> None:
    """`task_month_of` MUST 解出 `at` 给出的那个月——这是跨月轮询的全部地基。"""
    for month in (1, 7, 12):
        at = datetime(2026, month, 15, 10, 30, tzinfo=UTC)
        assert task_month_of(make_id("task", at=at)) == f"2026{month:02d}"


def test_task_month_of_handles_year_boundary() -> None:
    """跨年：12 月与次年 1 月 MUST 解成不同的月份串（`YYYYMM` 里年份不能丢）。"""
    december = task_month_of(make_id("task", at=datetime(2026, 12, 31, 23, 59, tzinfo=UTC)))
    january = task_month_of(make_id("task", at=datetime(2027, 1, 1, 0, 1, tzinfo=UTC)))
    assert (december, january) == ("202612", "202701")


def test_same_image_task_at_different_months_differs_only_in_the_month_segment() -> None:
    """同一个 `at` 之外的一切相同时，`task_id` 只应在**月份段**上不同（结构断言）。

    这条防的是"月份被拼在别处"（如拼在尾部）：那样 `task_month_of` 的定长切片会读错段，
    而读错的后果是**路由到错误的月表**——表现为轮询随机 404。
    """
    july = make_id("task", at=datetime(2026, 7, 15, tzinfo=UTC))
    august = make_id("task", at=datetime(2026, 8, 15, tzinfo=UTC))
    assert july[5:11] == "202607" and august[5:11] == "202608"
    assert july[:5] == august[:5] == CONTRACT_TASK_PREFIX
    assert len(july) == len(august) == CONTRACT_ID_MAX_LENGTH


def test_new_id_requires_at_for_task() -> None:
    """`new_id("task")` 不传 `at` MUST 抛错，**MUST NOT** 回落成"取当前时间"。

    为什么这条是硬要求而不是风格：`task_id` 里的月份与调用方用于算分片 `created_at`
    的时钟 MUST 是**同一个来源**。若本函数自己取 `datetime.now()`，
    两个时钟一旦不同（注入的固定时钟、跨月的一瞬、容器时区差异），
    就会出现**ID 里的月份与落库的分片表不符**——表现为"提交成功但轮询 404"，
    且极难复现。回落兜底正是那个 bug 的另一种写法。
    """
    with pytest.raises(ValueError, match="必须传 `at`"):
        new_id("task")


def test_new_id_does_not_accept_at_for_non_month_aware_kinds_by_requiring_it() -> None:
    """非 task 类**不需要** `at`（传了也无害），但 MUST NOT 被要求传。"""
    for kind in sorted(EXPECTED_KINDS - MONTH_AWARE_KINDS):
        assert len(new_id(kind)) == CONTRACT_ID_MAX_LENGTH


class TestValidateRejects:
    """反例组：`validate_id` 的每一条判据都要有一条"会拒绝"的证据。"""

    def test_wrong_prefix_for_kind(self) -> None:
        value = make_id("task")
        assert validate_id(value, "cor") is False

    def test_too_short(self) -> None:
        prefix = CONTRACT_TASK_PREFIX + AT_MONTH
        assert validate_id(prefix + "0" * (CONTRACT_ID_MAX_LENGTH - len(prefix) - 1), "task") is (
            False
        )

    def test_too_long(self) -> None:
        prefix = CONTRACT_TASK_PREFIX + AT_MONTH
        assert validate_id(prefix + "0" * (CONTRACT_ID_MAX_LENGTH - len(prefix) + 1), "task") is (
            False
        )

    def test_non_hex_remainder(self) -> None:
        prefix = CONTRACT_TASK_PREFIX + AT_MONTH
        assert validate_id(prefix + "Z" * (CONTRACT_ID_MAX_LENGTH - len(prefix)), "task") is False

    def test_uppercase_hex_remainder(self) -> None:
        prefix = CONTRACT_TASK_PREFIX + AT_MONTH
        assert validate_id(prefix + "A" * (CONTRACT_ID_MAX_LENGTH - len(prefix)), "task") is False

    def test_empty_and_missing_prefix(self) -> None:
        assert validate_id("") is False
        assert validate_id("0" * MAX_ID_LENGTH) is False

    def test_non_string_input(self) -> None:
        """外部值可能是 None / 数字：判为 False，**不抛异常**（本函数用于判定点）。"""
        assert validate_id(None) is False  # type: ignore[arg-type]
        assert validate_id(12345) is False  # type: ignore[arg-type]

    def test_unknown_kind_raises(self) -> None:
        """未知 kind 是**编程错误**，抛 `ValueError`（与 `new_id` 一致）。"""
        with pytest.raises(ValueError, match="merchant"):
            new_id("merchant")
        with pytest.raises(ValueError):
            validate_id("task_" + "0" * (CONTRACT_ID_MAX_LENGTH - len("task_")), "nope")


class TestValidateRejectsBadMonth:
    """v1.3 新增：月份段的每一条判据都要有"会拒绝"的证据。"""

    def test_legacy_format_without_month_is_rejected(self) -> None:
        """**旧格式（无月份）必须被拒**：它是本变更之前的形态，长度也是 32。

        这条是"格式真的变了"的核心证据——若判据漏了月份段，
        `task_` + 27 位 hex 会以长度合法的方式通过，而它**无法解析月份**，
        路由会退化成"用当前月查"——即本变更要修的原始缺陷。
        """
        legacy = CONTRACT_TASK_PREFIX + "9f2e7c1a3b4d5e6f7a8b9cdef01"
        assert len(legacy) == CONTRACT_ID_MAX_LENGTH, (
            f"构造的旧格式样例长度应为 {CONTRACT_ID_MAX_LENGTH}，实际 {len(legacy)}："
            f"本用例的前提是「旧格式长度也合法、只有缺月份段」，长度不对就测不到该前提"
        )
        assert validate_id(legacy, "task") is False
        assert validate_id(legacy) is False

    def test_month_with_non_digits_is_rejected(self) -> None:
        value = CONTRACT_TASK_PREFIX + "20abcd" + "a" * 21
        assert validate_id(value, "task") is False

    def test_month_without_20_century_prefix_is_rejected(self) -> None:
        """月份必须匹配 `20\\d{4}`：`999999` 这种非年份值 MUST NOT 被放过。

        为什么收紧到世纪前缀：`999999` 会"合法"地通过 6 位数字检查，
        而它只会表现为"路由到一张永远不存在的表"——比当场拒绝难查得多。
        """
        value = CONTRACT_TASK_PREFIX + "999999" + "a" * 21
        assert validate_id(value, "task") is False

    def test_task_month_of_rejects_malformed_id(self) -> None:
        """`task_month_of` 对非法 `task_id` 抛 `ValueError`（调用方据此报 `1003`）。"""
        for bad in ("", "task_2026", CONTRACT_TASK_PREFIX + "9" * 27, "cor_" + "a" * 28):
            with pytest.raises(ValueError, match="不是合法的任务号"):
                task_month_of(bad)


def test_over_length_guard_actually_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    """**核心负向证据**：把上限改小后，`new_id` MUST 抛 `ValueError`（不是静默截断）。

    没有这条，"超限即抛错"就只是文档里的一句话——而这句话正是 spec §5.8 点名
    「最容易写错」的地方。用 monkeypatch 改模块常量，验证自校验真的在守。
    """
    import aicore.core.idgen as idgen

    monkeypatch.setattr(idgen, "MAX_ID_LENGTH", 10)
    with pytest.raises(ValueError, match="长度"):
        idgen.new_id("marker")


def _code_only(source: str) -> str:
    """剥掉注释与字符串字面量，只留**可执行骨架**。

    为什么必须剥（这条断言首次写错时正是栽在这里）：`idgen.py` 的模块 docstring 里
    **刻意写了**"不用雪花、无 workerId"来记录禁用理由——那是文档，
    而朴素的子串检查会把"文档里说明禁用"判成"代码里用了"（实测报 `worker` 命中）。
    结论：这类检查 MUST 只对代码发问。用 `tokenize` 而不是正则，
    因为它才真正区分"注释/字符串"与"代码"（正则分不清 `"uuid1"` 与 `uuid1`）。
    """
    import io
    import tokenize

    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def test_no_snowflake_or_timestamp_or_uuid1() -> None:
    """防回归（**弱断言，真正的保证在评审**）：代码骨架里不得出现雪花/uuid1 的踪迹。

    `er.md` §5.4 L247 明确「Python 侧不参与雪花域，无 workerId、无时钟回拨风险面」；
    `uuid1` 含 MAC 与时间戳，属可预测 + PII 风险，本服务 MUST NOT 使用。
    这里只能做子串级检查（静态工具查不出"语义上是不是雪花"），
    故如实标注为弱断言，不假装它能替代评审。

    **`timestamp` 已从禁用词里移除（v1.3）**：`task_id` 现在内嵌**创建月**，
    而"月份来自 `at`（创建时刻）"这件事在代码里必然出现时间相关标识（`at.year` / `at.month`）。
    规范禁的是**雪花式毫秒时间戳**（时钟回拨风险面、须 workerId），
    而 `YYYYMM` 是创建时冻结进字符串的业务标签、此后不再从时钟推导——
    把它与"时间戳"等同属于对原禁令的扩张，故这里改为断言
    **`time.time` / `monotonic` / `uuid1` / `snowflake` / `worker` 仍不在代码里**，
    月份段的存在另由上面的 `task_month_of` 与形态用例覆盖。
    """
    source = inspect.getsource(idgen_module())
    code = _code_only(source).lower()
    for forbidden in ("snowflake", "worker", "time.time", "uuid1", "monotonic"):
        assert forbidden not in code, (
            f"idgen.py 的**代码**里出现禁用痕迹 {forbidden!r}："
            f"er.md §5.4 禁止雪花方案（docstring 里说明禁用理由不算违规）"
        )
    # 反向自检：若剥离逻辑失效（把整份源码都剔掉），上面的断言就成了空断言。
    assert "uuid4" in code, "剥离后连 uuid4 都没了，说明 _code_only 把代码也剥掉了"


def test_month_segment_is_not_derived_from_the_clock_at_use_time() -> None:
    """`task_month_of` MUST NOT 读时钟：它只做字符串解析。

    这条把"月份是冻结的标签、不是时钟读数"变成可执行判据：
    若有人把实现改成"和当前月比对后再返回"，跨月查询就会重新失败，
    而本用例通过「构造一个远在未来/过去的 `at` 仍能解出对应月份」把它钉住。
    """
    far_past = make_id("task", at=datetime(2001, 2, 1, tzinfo=UTC))
    far_future = make_id("task", at=datetime(2099, 11, 1, tzinfo=UTC))
    assert task_month_of(far_past) == "200102"
    assert task_month_of(far_future) == "209911"
    # 与"当前时刻"无关：再加一天也不会改变解析结果（同一个 ID 解出同一个月份）。
    assert task_month_of(far_future) == task_month_of(far_future)
    assert (datetime.now(UTC) - timedelta(days=1)) != far_future  # 明确本用例不依赖当前时间
