"""置信度分级用例（Task 4.10 §5 的判据 1/2/3/5）。

## 本文件覆盖哪些判据（工单 §5 的逐条对应）

| 工单 §5 | 用例 |
|---|---|
| 1 边界三分（`0.899/0.9/0.7` + 各档内一个值） | `test_boundary_values_map_to_the_ruled_levels` |
| 2 `None` 不判级 + `needs_manual_review=1` | `test_none_confidence_is_not_graded_...` |
| 3 阈值可配、**边界随之移动** | `test_changing_the_high_threshold_moves_the_boundary` 等 |
| 5 `MUST NOT` 被用作跳过人工确认的依据 | `test_verdict_has_no_field_that_could_skip_...` |

判据本体抽在两个助手里（`_assert_ruled_levels` / `_assert_verdict_has_no_skip_field`），
**自证喂的就是它们**——"自证"与"真判据"因此不会各自漂移。

判别力自证（工单 §5 末段点名的那两条）：`test_boundary_rule_guard_discriminates`
（`>=` / `>` 互换 ⇒ 边界判据必红）、`test_skip_human_guard_discriminates`
（加 `skip_review` 字段 ⇒ 字段集合判据必红）。

## 为什么"只测三个边界"不够（工单 §5 第 1 条的原话）

只测 `0.899 / 0.9 / 0.7` 的话，一个"把整段都判成 MEDIUM"的实现只在 `0.899` 那一格通过、
另两格红——**看起来**判据有效；但一个"`c >= 0.7` 全判 MEDIUM、只有 `None` 判 None"的实现
同样会红。真正需要的是**各档内再取一个值**：`0.95`（HIGH 内部）、`0.8`（MEDIUM 内部）、
`0.1`（LOW 内部）——三个一起才能排除"档位归属整体错位"。
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from aicore.core.config import Settings
from aicore.service.task.confidence import (
    MODEL_META_THRESHOLDS_KEY,
    ConfidenceLevel,
    ConfidenceVerdict,
    classify_confidence,
    confidence_thresholds,
    grade,
    thresholds_snapshot_of,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIDENCE_PATH = PROJECT_ROOT / "src" / "aicore" / "service" / "task" / "confidence.py"

#: 平台定档阈值（`er.md:301`）。用例里显式写出而不是从 `Settings` 取：
#: 这两条线是**被测输入**，从被测配置里取会让"配置写错"与"三分写错"混在一起。
HIGH = 0.9
MEDIUM = 0.7
THRESHOLDS = confidence_thresholds(high=HIGH, medium=MEDIUM)


# ---------------------------------------------------------------------------
# 判据 1：边界三分（`0.899/0.9/0.7` + 各档内一个值）
# ---------------------------------------------------------------------------
#: 逐格断言表（**判据本体**）：控制者裁定的边界归属 + 各档内的一个值。
#:
#: 三个边界值（`0.9/0.899/0.7`）是工单 §1 验收逐字点名的；`0.95/0.8/0.1` 是
#: **各档再各一个值**——只测边界会让"整段判成 MEDIUM"这类实现蒙混过关（见模块 docstring）。
_RULED_LEVELS: tuple[tuple[float, str], ...] = (
    (0.9, "HIGH"),  # 显式边界优先（er.md:63 的 HIGH≥0.9）
    (0.899, "MEDIUM"),
    (0.7, "MEDIUM"),  # 余下区间自然取半开
    (0.95, "HIGH"),  # 档内
    (0.8, "MEDIUM"),  # 档内
    (0.1, "LOW"),  # 档内
    (1.0, "HIGH"),  # 值域上端
    (0.0, "LOW"),  # 值域下端
    (0.6999, "LOW"),
)


def _assert_ruled_levels(classify: Callable[..., Any], level: Any) -> None:
    """**三分表的判据本体**：逐格断言，`level` 是**被测模块自己的**枚举类型。

    为什么要传枚举进来：判别力自证用的是**内存变异模块**，它的 `ConfidenceLevel`
    与生产的是**两个不同的类对象**（`StrEnum` 成员因此 `is not` 相等），
    按名字取被测方自己的枚举才能让同一份判据对两边都成立。

    "同一份判据"是本函数存在的理由（工单与前几批的一贯要求）：
    自证若复制一份断言，两边会各自漂移，于是"自证能判红"证明的就不是"真判据能判红"。
    """
    for confidence, expected_name in _RULED_LEVELS:
        got = classify(confidence, high=HIGH, medium=MEDIUM)
        expected = level[expected_name]
        assert got is expected, (
            f"c={confidence} 应判 {expected_name}，实际 {got}——"
            f"边界归属规则：HIGH = c >= {HIGH}、MEDIUM = {MEDIUM} <= c < {HIGH}、LOW = c < {MEDIUM}"
        )


def test_boundary_values_map_to_the_ruled_levels() -> None:
    """三分表逐格断言（控制者裁定的边界归属，见 `confidence.py` 的模块 docstring §一）。"""
    _assert_ruled_levels(classify_confidence, ConfidenceLevel)


def test_a_value_inside_each_band_is_not_merely_the_band_of_the_boundary() -> None:
    """**阴性对照**：三档**各自**都要有一个"离边界很远"的值落在同一档。

    这条是上一条的必要补充：上一条里 `0.95/0.8/0.1` 已经各有一个，但把"档内值"
    与"边界值"混在同一张参数表里时，一个**只按边界判**的实现仍然可能蒙混
    （例如把 `>= 0.9` 写成 `>= 0.95`——那会让 `0.9` 红，从而暴露；
    但把 `MEDIUM` 写成 `[0.7, 0.9)` 之外还要求 `< 0.85` 这类形态就会被 `0.8` 抓到）。
    故这里单独把三档的**内部点**再断言一遍，并断言三档互不相同——
    一个"所有输入都返回同一个档"的实现会在这里红。
    """
    inside = {
        classify_confidence(0.95, high=HIGH, medium=MEDIUM),
        classify_confidence(0.8, high=HIGH, medium=MEDIUM),
        classify_confidence(0.1, high=HIGH, medium=MEDIUM),
    }
    assert inside == {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW}, (
        f"三档的内部点应给出三个**不同**的档位，实际 {inside}"
    )


def test_boundary_rule_guard_discriminates() -> None:
    """**判别力自证**：把 `>=` 互换为 `>`（= 闭区间口径），边界用例**必须变红**。

    内存变异（**文件从不被写**）：`>=` 与 `>` 的差别**只在边界点上**——
    `0.9` 与 `0.7` 各被两档同时包含，正是工单 §2 说的那个重叠。
    变异后：`0.9 → MEDIUM`、`0.7 → LOW`，而 `0.899` 仍是 MEDIUM ⇒ 判据在边界格上红。

    这就是"边界归属规则"为什么要被单独钉住：它是**两处文档重叠**的唯一收口点，
    写错方向（闭区间）在其余所有输入上都看不出差别。
    """
    mutant = _mutant_confidence_module(
        "    if confidence >= high:\n"
        "        return ConfidenceLevel.HIGH\n"
        "    if confidence >= medium:\n"
        "        return ConfidenceLevel.MEDIUM\n",
        "    if confidence > high:\n"
        "        return ConfidenceLevel.HIGH\n"
        "    if confidence > medium:\n"
        "        return ConfidenceLevel.MEDIUM\n",
    )

    # 变异**生效**：先证明边界归属真的变了（否则"判据红了"可能只是变异没打上）。
    assert (
        mutant.classify_confidence(0.9, high=HIGH, medium=MEDIUM) is mutant.ConfidenceLevel.MEDIUM
    )
    assert mutant.classify_confidence(0.7, high=HIGH, medium=MEDIUM) is mutant.ConfidenceLevel.LOW

    # 同一份判据（`_assert_ruled_levels`）喂给变异体 ⇒ **必须红**，且红在 0.9 那一格上。
    with pytest.raises(AssertionError, match=r"c=0\.9 应判 HIGH"):
        _assert_ruled_levels(mutant.classify_confidence, mutant.ConfidenceLevel)


# ---------------------------------------------------------------------------
# 判据 2：`None` 不判级 + 兜底
# ---------------------------------------------------------------------------
def test_none_confidence_is_not_graded_but_goes_to_manual_review() -> None:
    """`None` ⇒ **不判级**（不是 `LOW`）+ `needs_manual_review = 1`（控制者裁定）。

    三段断言，第二段是关键：

    1. `level is None`；
    2. **显式断言它没变成 `LOW`**——这是"把 `None` 当 `0.0`"那个错误实现的唯一可观测差别
       （若只断言 `needs_manual_review is True`，两种实现**都给 True**：`LOW` 也转人工 ⇒
       判据没有判别力）；
    3. 兜底置位（`er.md:40`：「置信度不足转人工核验兜底」）。
    """
    verdict = grade(None, thresholds=THRESHOLDS)

    assert verdict.level is None, f"没有置信度时 MUST NOT 判级，实际 {verdict.level}"
    assert verdict.level is not ConfidenceLevel.LOW, (
        "`None` 被当成了 `LOW`：那是**造假数据**——系统凭空宣称『本次判定置信度极低』，"
        "而真实情况是『通道没给这个数』（provider/results.py 的 docstring 逐字禁止补 0）"
    )
    assert verdict.needs_manual_review is True, "没有置信度 ⇒ 无法自证可靠 ⇒ 必须转人工兜底"


def test_zero_confidence_is_graded_low_and_is_indistinguishable_from_none_only_by_level() -> None:
    """对照：`0.0` **判 `LOW`**，且与 `None` 的差别**只在 `level` 上**。

    这条把"两者的区别"钉死：它们的 `needs_manual_review` **相同**（都转人工），
    差别是 `0.0` 有一个**真实的** `LOW` 分级，而 `None` 没有分级。
    这正是 `provider/results.py` 用 `float | None` 而不是 `float` 的全部理由。
    """
    zero = grade(0.0, thresholds=THRESHOLDS)
    missing = grade(None, thresholds=THRESHOLDS)

    assert zero.level is ConfidenceLevel.LOW
    assert missing.level is None
    assert zero.needs_manual_review is missing.needs_manual_review is True


# ---------------------------------------------------------------------------
# 判据 3：阈值可配 ⇒ **边界随之移动**
# ---------------------------------------------------------------------------
def test_changing_the_high_threshold_moves_the_boundary() -> None:
    """改 `high` ⇒ 同一份输入的分级改变（判据断言"移动"本身，不是"读到了配置"）。"""
    confidence = 0.85
    assert classify_confidence(confidence, high=0.9, medium=0.7) is ConfidenceLevel.MEDIUM
    assert classify_confidence(confidence, high=0.8, medium=0.7) is ConfidenceLevel.HIGH, (
        "把 HIGH 的下界从 0.9 调到 0.8 之后，0.85 仍在 MEDIUM —— 阈值没有真的生效"
    )


def test_changing_the_medium_threshold_moves_the_boundary() -> None:
    """改 `medium` ⇒ 低/中的分界随之移动（`0.5` 从 `LOW` 变 `MEDIUM`）。"""
    confidence = 0.5
    assert classify_confidence(confidence, high=0.9, medium=0.7) is ConfidenceLevel.LOW
    assert classify_confidence(confidence, high=0.9, medium=0.4) is ConfidenceLevel.MEDIUM


def test_threshold_ordering_is_a_config_concern_not_a_classifier_concern() -> None:
    """`medium > high` 时三分**仍是良定义的函数**（MEDIUM 档为空），不抛错。

    为什么不在分类器里再报一次错：`high`/`medium` 的**相对关系**是配置关切，
    由 `core/config.py` 的跨字段校验在启动期拦下（`confidence-order`）。
    分类器只管"两条线画在哪"——两个值传进来它就要给答案。这条用例把这份分工钉住：
    若哪天有人在分类器里加了 `raise`，它会红。
    """
    assert classify_confidence(0.85, high=0.7, medium=0.9) is ConfidenceLevel.HIGH
    assert classify_confidence(0.75, high=0.7, medium=0.9) is ConfidenceLevel.HIGH
    assert classify_confidence(0.65, high=0.7, medium=0.9) is ConfidenceLevel.LOW


# ---------------------------------------------------------------------------
# 阈值快照：写与读共用一套键名（留痕的载体）
# ---------------------------------------------------------------------------
def test_thresholds_snapshot_keys_match_provider_identity_contract() -> None:
    """快照的键名是 `{high, medium}`——**逐字对齐** `ProviderIdentity.thresholds`。

    依据：`provider/results.py::ProviderIdentity` 的 docstring 写着
    「`thresholds` | 判定阈值快照 `{high, medium}`」，而快照要经 `as_model_meta()`
    落进 `ai_task.model_meta.thresholds`（`er.md:27`）。两处键名不一致会让
    "写得进、读不出"——而在 JSON 里读 `None` 不会报错，只会静默变成没有阈值。
    """
    snapshot = confidence_thresholds(high=0.9, medium=0.7)
    assert snapshot == {"high": 0.9, "medium": 0.7}
    # 读回来必须是同一份（往返一致）。
    assert thresholds_snapshot_of({MODEL_META_THRESHOLDS_KEY: snapshot}) == snapshot


def test_thresholds_snapshot_of_missing_or_broken_meta_returns_none() -> None:
    """取不到快照 ⇒ **返回 `None`**，**MUST NOT** 回落到"当前配置"。

    回落会让"留痕"变成不可证伪：一个没有快照的历史任务会被今天的阈值解释，
    而现场看不出异常。故"没有当次快照"必须如实交回调用方（与
    `provider/results.py` 对 `confidence=None` 的口径同构）。
    """
    assert thresholds_snapshot_of(None) is None
    assert thresholds_snapshot_of({}) is None
    assert thresholds_snapshot_of({"channel": "OCR"}) is None
    assert thresholds_snapshot_of({MODEL_META_THRESHOLDS_KEY: "not-a-mapping"}) is None


def test_missing_threshold_key_is_an_explicit_error() -> None:
    """快照缺 `high` / `medium` ⇒ **显式报错**，MUST NOT 用内置默认值兜底。

    理由（`er.md:301` 把阈值标为"已定档、运营期可调"）：一个"读不到就当我 0.9"的兜底
    会让运营改了配置却不生效，而现场没有任何信号——正是本项目反复出现的静默漂移。
    """
    with pytest.raises(ValueError, match="high"):
        grade(0.95, thresholds={"medium": 0.7})
    with pytest.raises(ValueError, match="medium"):
        grade(0.95, thresholds={"high": 0.9})


# ---------------------------------------------------------------------------
# 判据 5：`MUST NOT` 被用作跳过人工确认的依据
# ---------------------------------------------------------------------------
def _assert_verdict_has_no_skip_field(verdict_cls: Any) -> None:
    """**判据本体**：分级结果的字段集合**恰好**是 `{level, needs_manual_review}`。

    `spec.md:58` 末句逐字：「置信度 **MUST NOT** 被用作跳过人工确认的依据」；
    `:63` 说分级是**排序**依据；`:65-68` 说高置信度**仍不**自动执行任何动作。

    这条判据抓的是那个形态：只要有人给分级结果加一个能表达"免人工"的字段
    （`skip_review` / `auto_confirm` / `bypass_manual` …），字段集合就变了 ⇒ 当场红。
    **它不是形式主义**：加字段是实现"高置信度免人工"的**第一步**，而这一步在本项目里
    没有别的守备（M1 没有执行链路，端到端的"没自动执行"要等第 5 组才验得到）。

    传类进来（而不是直接读模块级 `ConfidenceVerdict`）是为了让判别力自证把
    **变异模块的那个类**喂给同一份判据。
    """
    assert {field.name for field in fields(verdict_cls)} == {
        "level",
        "needs_manual_review",
    }, (
        f"{verdict_cls.__name__} 的字段集合变了：{sorted(f.name for f in fields(verdict_cls))}——"
        f"新增字段若表达『免人工/跳过复核』，就违反 spec.md:58 末句；"
        f"请先回工单确认，不要顺手加"
    )


def test_verdict_has_no_field_that_could_skip_human_confirmation() -> None:
    """`ConfidenceVerdict` 的字段集合**恰好**是两个——没有"免人工/跳过复核"的落点。

    判据本体在 `_assert_verdict_has_no_skip_field`（供自证复用），说明见它的 docstring。
    """
    _assert_verdict_has_no_skip_field(ConfidenceVerdict)


def test_skip_human_guard_discriminates() -> None:
    """**判别力自证**：给变异体加一个 `skip_review` 字段，上一条判据**必须变红**。

    内存变异（**文件从不被写**）：在 `ConfidenceVerdict` 上加一个默认 `False` 的
    `skip_review: bool`——这正是"高置信度免人工"落地的第一步。
    同一份判据（字段集合恰好两个）喂给变异体 ⇒ **必须抛**，且抛在"字段集合变了"上。
    """
    mutant = _mutant_confidence_module(
        "    level: ConfidenceLevel | None\n    needs_manual_review: bool\n",
        "    level: ConfidenceLevel | None\n"
        "    needs_manual_review: bool\n"
        "    skip_review: bool = False\n",
    )

    assert "skip_review" in {field.name for field in fields(mutant.ConfidenceVerdict)}, (
        "变异没有生效：本自证的前提不成立"
    )
    with pytest.raises(AssertionError, match="字段集合变了"):
        _assert_verdict_has_no_skip_field(mutant.ConfidenceVerdict)


def test_high_confidence_does_not_clear_the_manual_review_flag_of_low_confidence() -> None:
    """负向的行为版：`HIGH` **不**免人工——它只是不置"兜底"位，输出仍进人工端。

    `spec.md:63`：分级用于**排序**复核；`:65-68`：高置信度仍待人工确认。
    故 `grade(0.99)` 的 `needs_manual_review is False` 只表示"不进**兜底**队列"
    （`er.md:481` 的语义），**不表示**"不用人看"。这条用例把该语义写成断言：
    同一个 `HIGH` 结果在不同阈值下**不会**改变"是否有分级"这件事，
    而 `LOW`/`None` **一定**置位兜底——即置位规则只看"是否不足"，与"是否高"无关。
    """
    high = grade(0.99, thresholds=THRESHOLDS)
    assert high.level is ConfidenceLevel.HIGH
    assert high.needs_manual_review is False, (
        "HIGH 不该进**兜底**队列（它仍进人工端，只是排序靠前）"
    )

    # 阈值上移之后同一个数变成 MEDIUM：**仍然**不置兜底位（MEDIUM 也不在"不足"档）。
    shifted = grade(0.99, thresholds=confidence_thresholds(high=0.999, medium=0.7))
    assert shifted.level is ConfidenceLevel.MEDIUM
    assert shifted.needs_manual_review is False


# ---------------------------------------------------------------------------
# 配置侧：两个字段的默认值来自 `er.md:301` 的定档
# ---------------------------------------------------------------------------
def test_settings_expose_the_documented_default_thresholds() -> None:
    """`Settings` 的两个阈值默认值 == `er.md:301` 的定档值（0.9 / 0.7）。

    现读 `Settings.model_fields` 的默认值，而不是构造一份 `Settings`
    （构造要全套必填项，那是 `tests/unit/test_config.py` 的事）。
    """
    assert Settings.model_fields["confidence_high"].default == 0.9
    assert Settings.model_fields["confidence_medium"].default == 0.7


# ---------------------------------------------------------------------------
# 内存变异工具（判别力自证用；**MUST NOT 落盘**）
# ---------------------------------------------------------------------------
_MUTANT_MODULE_NAME = "dsh_mutant_confidence"


def _mutant_confidence_module(anchor: str, replacement: str) -> Any:
    """把 `service/task/confidence.py` 在**内存里**改一处，编译出一个变异模块。

    与 `tests/api/test_ocr_submit.py::_mutant_submit_module`、
    `tests/unit/test_task_runner.py::_mutant_runner_class` 同一取向
    （工单纪律：MUST NOT「改 `src/` + `finally` 还原」——那条路一旦被打断就把变异体留在工作树里）。
    """
    source = CONFIDENCE_PATH.read_text(encoding="utf-8")
    count = source.count(anchor)
    assert count == 1, (
        f"变异锚点在 confidence.py 里出现 {count} 次（要求恰好 1 次）：{anchor!r}——"
        f"锚点漂了就必须先修锚点，MUST NOT 让它静默变成'什么都没变'"
    )
    module = types.ModuleType(_MUTANT_MODULE_NAME)
    module.__file__ = str(CONFIDENCE_PATH)
    code = compile(source.replace(anchor, replacement), str(CONFIDENCE_PATH), "exec")
    sys.modules[_MUTANT_MODULE_NAME] = module
    try:
        exec(code, module.__dict__)
    finally:
        del sys.modules[_MUTANT_MODULE_NAME]
    return module
