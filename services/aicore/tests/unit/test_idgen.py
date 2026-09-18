"""前缀化 ID 用例（Task 3.8）。

**本项为什么值得单独写一整套用例**：裸 UUID 是 **36 字符**，而 `er.md` §5.4 所有 ID 列都是
`varchar(32)` —— 超限 4 位。写错的表现是**每一行都插不进去**（或更糟：被静默截断成互相冲突的值）。
故这里把三件事都钉死：① 6 种前缀逐一验证；② 1 万个并发生成全量过正则且无重复；
③ "超限即抛错"的自校验**真的会响**（用 monkeypatch 把上限改小，必须抛 `ValueError`）。

用例内的正则/长度期望值**全部从 `ID_PREFIXES` 与 `MAX_ID_LENGTH` 现算**，
MUST NOT 把 `task_[0-9a-f]{27}` 这类写完的常数抄进来——抄了就等于把"长度算对"这件事验两遍，
而且两边一起错时都发现不了。
"""

from __future__ import annotations

import concurrent.futures
import inspect
import re

import pytest

from aicore.core.idgen import ID_PREFIXES, MAX_ID_LENGTH, new_id, validate_id


def idgen_module() -> object:
    """取 `aicore.core.idgen` 模块对象（供 `inspect.getsource` 用）。"""
    import aicore.core.idgen as module

    return module

#: 6 种 kind，逐字对齐 `er.md` §5.4 的 ID 前缀表。
EXPECTED_KINDS = {"task", "cor", "rev", "marker", "kan", "qa"}


def expected_length(kind: str) -> int:
    """该 kind 的 ID 应有的长度（= 总上限，因为 hex 段按剩余位数截取）。"""
    return MAX_ID_LENGTH


def expected_pattern(kind: str) -> re.Pattern[str]:
    """从 `ID_PREFIXES` 现算该 kind 的完整正则。"""
    prefix = ID_PREFIXES[kind]
    hex_len = MAX_ID_LENGTH - len(prefix)
    return re.compile(rf"^{re.escape(prefix)}[0-9a-f]{{{hex_len}}}$")


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
    value = new_id(kind)
    assert value.startswith(ID_PREFIXES[kind]), f"{kind} 的前缀不对：{value!r}"
    assert len(value) == expected_length(kind), (
        f"{kind} 长度 {len(value)} != {expected_length(kind)}"
    )
    assert len(value) <= MAX_ID_LENGTH
    assert expected_pattern(kind).match(value), f"{kind} 不匹配现算正则：{value!r}"
    assert validate_id(value, kind) is True
    assert validate_id(value) is True  # kind=None 的通用分支也要认


def test_ids_are_lowercase_hex_after_prefix() -> None:
    """前缀之后必须是**小写** hex（大写会让"同一 ID"出现两种写法，主键比对变脆）。"""
    for kind in EXPECTED_KINDS:
        remainder = new_id(kind)[len(ID_PREFIXES[kind]) :]
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
        return new_id(kinds[index % len(kinds)])

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


class TestValidateRejects:
    """反例组：`validate_id` 的每一条判据都要有一条"会拒绝"的证据。"""

    def test_wrong_prefix_for_kind(self) -> None:
        value = new_id("task")
        assert validate_id(value, "cor") is False

    def test_too_short(self) -> None:
        prefix = ID_PREFIXES["task"]
        assert validate_id(prefix + "0" * (MAX_ID_LENGTH - len(prefix) - 1), "task") is False

    def test_too_long(self) -> None:
        prefix = ID_PREFIXES["task"]
        assert validate_id(prefix + "0" * (MAX_ID_LENGTH - len(prefix) + 1), "task") is False

    def test_non_hex_remainder(self) -> None:
        prefix = ID_PREFIXES["task"]
        assert validate_id(prefix + "Z" * (MAX_ID_LENGTH - len(prefix)), "task") is False

    def test_uppercase_hex_remainder(self) -> None:
        prefix = ID_PREFIXES["task"]
        assert validate_id(prefix + "A" * (MAX_ID_LENGTH - len(prefix)), "task") is False

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
            validate_id("task_" + "0" * 27, "nope")


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
    """防回归（**弱断言，真正的保证在评审**）：代码骨架里不得出现雪花/时间戳/uuid1 的踪迹。

    `er.md` §5.4 L247 明确「Python 侧不参与雪花域，无 workerId、无时钟回拨风险面」；
    `uuid1` 含 MAC 与时间戳，属可预测 + PII 风险，本服务 MUST NOT 使用。
    这里只能做子串级检查（静态工具查不出"语义上是不是雪花"），
    故如实标注为弱断言，不假装它能替代评审。
    """
    source = inspect.getsource(idgen_module())
    code = _code_only(source).lower()
    for forbidden in ("snowflake", "worker", "time.time", "uuid1", "timestamp", "monotonic"):
        assert forbidden not in code, (
            f"idgen.py 的**代码**里出现禁用痕迹 {forbidden!r}："
            f"er.md §5.4 禁止雪花/内嵌时间戳方案（docstring 里说明禁用理由不算违规）"
        )
    # 反向自检：若剥离逻辑失效（把整份源码都剔掉），上面的断言就成了空断言。
    assert "uuid4" in code, "剥离后连 uuid4 都没了，说明 _code_only 把代码也剥掉了"
