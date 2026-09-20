"""`provider/results.py` 契约用例（控制者自写，Task 4.1）。

## 为什么这三份契约由控制者自己写用例

`provider/{results,errors,base}.py` 是 `service` 与 `provider` 之间**唯一稳定的边界**。
第 3 组 Task 3.1 的两次实现者交接（`b158a9e3`、`73c4c5e6`）说明「契约层出问题，后面全废」，
故契约与其判据都由控制者持有，实现者只在工单给定的签名内填空。

## 本文件防的是哪一类错

不是「实现写错」，而是**契约与权威文档漂移**：

- `er.md` §6.1 L295 规定 `model_meta` 的 5 个键名是 camelCase；
- `openapi.yaml:708-726` 规定 `OcrField` 的键名是 `fieldName` / `value` / `confidence`；
- `openapi.yaml:853-857` 规定 `ConfidenceLevel` 只有 HIGH / MEDIUM / LOW。

三处都是**跨服务契约**——改名不会让任何一条现有用例变红（没人拿文档来比），
却会让落库的 JSON 与前端契约分叉。故本文件**从文档现读现比**，而不是把期望值抄成常量。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest

from aicore.provider.results import (
    CHANNELS,
    Channel,
    OcrField,
    ProviderIdentity,
    ProviderResult,
    to_jsonable,
)

# ---------------------------------------------------------------------------
# 文档路径：从仓库根现算，不写绝对路径（换机器/换 worktree 都要能跑）
# ---------------------------------------------------------------------------
SERVICE_ROOT = Path(__file__).resolve().parents[2]
ER_MD = SERVICE_ROOT / "docs" / "er.md"
OPENAPI_YAML = SERVICE_ROOT / "docs" / "openapi.yaml"

#: `er.md` §6.1 `model_meta` 行的逐字键名清单（出处见测试函数内的断言消息）。
EXPECTED_MODEL_META_KEYS = frozenset(
    {"channel", "provider", "modelVersion", "promptVersion", "thresholds"}
)


def _identity(**overrides: Any) -> ProviderIdentity:
    base: dict[str, Any] = {
        "channel": "OCR",
        "provider": "mock",
        "model_version": "mock-ocr-v1",
        "prompt_version": "mock-prompt-v1",
        "thresholds": {"high": 0.9, "medium": 0.7},
    }
    base.update(overrides)
    return ProviderIdentity(**base)


# ---------------------------------------------------------------------------
# 1. 通道封闭集合：Literal 与运行期集合 MUST 同集合
# ---------------------------------------------------------------------------
def test_channel_literal_and_runtime_set_agree() -> None:
    """`Literal` 的成员与运行期 `CHANNELS` 必须逐项相等（防两处漂移）。

    **MUST 走 `Channel.__value__`**：实测（Python 3.14.6）`type X = Literal[...]` 形式下
    `get_args(X)` 返回**空元组且不报错**：

        type A = Literal['X','Y']  ->  get_args(A) == ()
        B = Literal['X','Y']       ->  get_args(B) == ('X','Y')

    若这里写成 `get_args(Channel)`，断言会退化成 `set() == CHANNELS`（恒假）或
    `frozenset() <= CHANNELS`（恒真）——**看起来在防漂移，实际一行都没防**。
    故本用例先用一条前置断言把 `get_args` 的返回值钉成非空，
    让「哪天 Python 改了行为、`__value__` 不再需要」这件事**显式暴露**而不是静默退化成假绿。
    """
    direct = get_args(Channel)
    via_value = get_args(Channel.__value__)

    assert direct == (), (
        f"本用例的前提失效：get_args(Channel) 不再是空元组而是 {direct!r}。"
        f"说明 Python 改了 type 别名的行为——请把下面的 via_value 换成 direct 并复核本断言"
    )
    assert via_value, "get_args(Channel.__value__) 取不到成员：type 别名的结构变了"
    assert set(via_value) == set(CHANNELS)


def test_channels_has_exactly_three_members() -> None:
    """恰 3 个成员。**「四类通道」的第四类在 M1 没有实现**，故不以 Channel 形式存在。

    依据：`spec.md:11` 说四类，但 `design.md:54` / `:142` 与 `tasks.md:37` 都只定义 3 个
    Protocol，`design.md:145` 的真实通道文件只有 3 个，`design.md:26` 逐字
    「不实现 K-03/K-04/K-05/K-06 的业务逻辑（只保留任务类型枚举与通道路由扩展位）」，
    `design.md:192` 把第四类登记为 `RISK_PREDICT` 任务类型的**预留注册位**。

    这条断言的作用不是「数字好看」，而是：**若有人为「平台自建预测」加一个 Channel 成员，
    这里立刻变红并被迫回答「它的实现在哪个文件」**。
    """
    assert len(CHANNELS) == 3, f"通道数从 3 变成了 {len(CHANNELS)}：{sorted(CHANNELS)}"


# ---------------------------------------------------------------------------
# 2. model_meta：键名与 er.md §6.1 逐字一致
# ---------------------------------------------------------------------------
def test_model_meta_key_names_match_er_md_section_6_1() -> None:
    """`as_model_meta()` 的键集合与 `er.md` §6.1 的 `model_meta` 注释行逐字一致。

    从 `er.md` **现读**而不是抄常量：抄常量等于把「文档写对了」验两遍，
    验不出「代码与文档一起改错」。
    """
    er_text = ER_MD.read_text(encoding="utf-8")
    # `er.md` §6.1 的 model_meta 行形如：
    #   | model_meta | JSON | YES | — | NULL | **模型/Prompt 血缘（2026-09-16 增）**：
    #   `{channel, provider, modelVersion, promptVersion, thresholds（high/medium）}`；…
    match = re.search(r"`\{(channel, provider[^}]*)\}`", er_text)
    assert match is not None, (
        f"在 {ER_MD} 里找不到 `{{channel, provider …}}` 形式的 model_meta 键清单："
        f"er.md §6.1 的该行被改写了，请人工核对后更新本用例"
    )
    documented = [item.split("（")[0].strip() for item in match.group(1).split(",")]
    # thresholds 在文档里写作 `thresholds（high/medium）`，括号内是**子键**说明，
    # 不是键名的一部分；上面已按「（」切掉。子键由下一条用例单独钉。
    assert set(documented) == EXPECTED_MODEL_META_KEYS, (
        f"er.md 记的是 {sorted(documented)}，本模块常量是 {sorted(EXPECTED_MODEL_META_KEYS)}"
    )

    assert _identity().as_model_meta().keys() == EXPECTED_MODEL_META_KEYS


def test_model_meta_uses_camel_case_not_snake_case() -> None:
    """落库键名 MUST 是 camelCase。

    依据：`er.md` §6 通用约定「枚举值与 `openapi.yaml` 的 `components.schemas` 一一对应」，
    而 openapi.yaml 全篇 camelCase（`taskId` / `createdAt` / `confidenceLevel`…）。
    落库 JSON 若用 snake_case，前端与 5.7 的「字段与 er.md §6.1 一致」都会对不上。
    """
    meta = _identity().as_model_meta()
    assert "modelVersion" in meta and "promptVersion" in meta
    assert "model_version" not in meta and "prompt_version" not in meta


def test_model_meta_thresholds_carries_high_and_medium() -> None:
    """`thresholds` 的子键是 `high` / `medium`（`er.md` §6.1 的 `thresholds（high/medium）`）。"""
    meta = _identity().as_model_meta()
    assert set(meta["thresholds"]) == {"high", "medium"}


def test_model_meta_thresholds_are_copied_not_aliased() -> None:
    """`as_model_meta()` MUST 返回快照的**副本**，不得把内部 `Mapping` 直接暴露出去。

    为什么较真：`er.md` §6.1 把 `thresholds` 叫「阈值快照」——快照的意义是
    「事后能知道当时用的是什么阈值」。若返回的是同一个 dict，调用方改一下就会
    **静默改写历史血缘**，而 `dataclass(frozen=True)` 拦不住内部可变对象。
    """
    identity = _identity(thresholds={"high": 0.9, "medium": 0.7})
    snapshot = identity.as_model_meta()["thresholds"]
    snapshot["high"] = 0.1
    assert identity.thresholds["high"] == 0.9, "as_model_meta() 暴露了内部 Mapping 本体"


# ---------------------------------------------------------------------------
# 3. 通道类别的运行期校验
# ---------------------------------------------------------------------------
def test_unknown_channel_is_rejected_at_construction() -> None:
    """未知通道必须**构造期**失败，而不是留到落库或前端才发现。

    运行期校验补的是类型检查器的盲区：`channel="TEXTX"` 这种值在配置/字典拼装路径上
    很常见，mypy 管不到——那正是配置写错的真实形态。
    """
    with pytest.raises(ValueError, match="未知通道类别"):
        _identity(channel="TEXTX")


@pytest.mark.parametrize("channel", sorted(CHANNELS))
def test_every_documented_channel_is_accepted(channel: str) -> None:
    """三个合法类别逐个可用（防「只放行了 OCR」这类半成品）。"""
    assert _identity(channel=channel).channel == channel


# ---------------------------------------------------------------------------
# 4. 置信度 MUST 可表达「没有」（None ≠ 0.0）
# ---------------------------------------------------------------------------
def test_missing_confidence_stays_none_never_zero() -> None:
    """`confidence` 缺省是 `None` 而**不是** `0.0`。

    依据：Task 4.10（置信度分级）与 Task 4.11（通道失败/超时分别计数）都要区分
    「通道没给置信度」与「置信度为 0」。补 `0.0` 会把前者判成 `LOW`（`<0.7`）
    并误触人工复核 —— 那是**造假数据**，不是兜底。
    """
    result = ProviderResult(identity=_identity())
    assert result.confidence is None
    assert result.confidence != 0.0


def test_ocr_field_confidence_may_be_none() -> None:
    """单字段置信度同样可缺省（`OcrField.confidence = None`），语义同上。"""
    field = OcrField(fieldName="统一社会信用代码", value="911301********1234")
    assert field.confidence is None


# ---------------------------------------------------------------------------
# 5. OcrField 的键名与 openapi.yaml 的 OcrField schema 一致
# ---------------------------------------------------------------------------
def test_ocr_field_uses_the_openapi_field_names() -> None:
    """`OcrField` 的三个键名 MUST 与 `openapi.yaml` 的 `OcrField` 逐字一致。

    同时覆盖 `required: [fieldName, value, confidence]`：三个字段都必须能在
    **不传任何可选参数**的前提下出现（`confidence` 可为 `None`，但键要在）。
    出处：`services/aicore/docs/openapi.yaml:708-726`。

    **P 阶段独立评审 N7 的修正**：初版这里只做 `name in body` 的**子串包含**检查——
    于是把 `required:` 那行整行删掉、或把 `confidence` 从 required 里拿掉，
    本用例照样绿（子串还在 schema 的 properties 里）。那与 docstring 声称的
    「覆盖 required 列表」不符。现改为**解析 `required` 列表本体**再比对。
    """
    text = OPENAPI_YAML.read_text(encoding="utf-8")
    block = re.search(r"\n    OcrField:\n(.*?)\n    \w", text, re.DOTALL)
    assert block is not None, f"在 {OPENAPI_YAML} 里找不到 OcrField schema"
    body = block.group(1)

    required_match = re.search(r"required:\s*\[([^\]]*)\]", body)
    assert required_match is not None, (
        "OcrField 的 schema 里没有 required 列表：本用例的前提失效，请先核对文档"
    )
    documented_required = {
        item.strip() for item in required_match.group(1).split(",") if item.strip()
    }
    assert documented_required == {"fieldName", "value", "confidence"}, (
        f"openapi.yaml 的 OcrField.required 是 {sorted(documented_required)}，"
        f"与本模块的三个字段不符"
    )

    # 键名存在性与「渲染后恰好三个键」——后者才是与 required 对齐的那一侧
    for name in documented_required:
        assert f"{name}:" in body, f"openapi.yaml 的 OcrField 里没有 {name} 属性"
    assert set(to_jsonable(OcrField(fieldName="x", value="y", confidence=0.5))) == (
        documented_required
    ), "渲染出的键集合与 openapi.yaml 的 required 列表不一致"


# ---------------------------------------------------------------------------
# 6. to_jsonable：递归渲染与兼容
# ---------------------------------------------------------------------------
def test_to_jsonable_renders_tuple_as_json_array() -> None:
    """`tuple` MUST 渲染成 JSON 数组（JSON 没有元组）。"""
    rendered = to_jsonable((OcrField(fieldName="a", value="b"),))
    assert isinstance(rendered, list) and rendered[0]["fieldName"] == "a"


def test_to_jsonable_renders_mapping_keys_as_str() -> None:
    """非 `str` 键 MUST 转成 `str`：JSON 对象的键只能是字符串，`json.dumps` 对 int 键会报错。"""
    assert to_jsonable({1: "a"}) == {"1": "a"}


def test_to_jsonable_is_json_serializable_end_to_end() -> None:
    """整条结果必须真的能 `json.dumps`（而不是只「看起来像」能）。

    这是最实在的一条：`ai_task.model_meta` 是 JSON 列，
    渲染不出来的结构会在**写库那一刻**才炸，而那时任务已经在跑了。
    """
    import json

    result = ProviderResult(
        identity=_identity(),
        fields=(OcrField(fieldName="a", value="b", confidence=0.98),),
        confidence=0.98,
        raw={"channel": "OCR", "tokens": [1, 2]},
    )
    dumped = json.dumps(to_jsonable(result), ensure_ascii=False)
    assert "fieldName" in dumped and "model_version" in dumped


def test_to_jsonable_and_as_model_meta_use_different_casing_on_purpose() -> None:
    """**两套键名并存是刻意的**，这条用例把它钉住，免得后人「统一」掉一个。

    | 出口 | 键名风格 | 谁消费 |
    |---|---|---|
    | `to_jsonable(result)` | dataclass **字段名**（`model_version`） | 进程内排障 / 评估集导出 |
    | `identity.as_model_meta()` | **camelCase**（`modelVersion`） | 落库 `ai_task.model_meta` |

    为什么不能只留一套：

    - 只留 camelCase → Python 侧字段名与渲染名不一致，`to_jsonable` 就得带一张
      改名表，任何新增字段都要两处同步，而这张表没有任何东西在守；
    - 只留 snake_case → 落库 JSON 与 `er.md` §6.1 和 openapi.yaml 的 camelCase 分叉，
      Task 5.7 的验收项「字段与 `er.md` §6.1 一致」直接失败。

    即 data class 的**属性名**归 Python 侧（`model_version`），
    它的**序列化契约**归文档侧（`modelVersion`），两者本就该分开。
    """
    result = ProviderResult(identity=_identity())
    assert "model_version" in to_jsonable(result)["identity"]
    assert "modelVersion" not in to_jsonable(result)["identity"]
    assert "modelVersion" in result.identity.as_model_meta()
    assert "model_version" not in result.identity.as_model_meta()


# ---------------------------------------------------------------------------
# 7. 三个真实通道的 `raw` 与 `thresholds` 现状 MUST 被断言（评审 N10）
#
# 评审的原话：`raw` 恒为 `None` 是事实，但**没有任何「必须为 None」的断言**——
# 将来有人加 `raw=decoded`，会把未脱敏的证件值带进结果结构，而 51 条用例全绿。
# 「主动不填」这种安全决策如果只写在 docstring 里，就没有任何东西在守它。
#
# 这两条**不是**在断言「设计正确」，而是在断言「当前状态 + 意图」，使任何单边改动
# 都必须面对一次红灯与一次有意识的裁决。
# ---------------------------------------------------------------------------
def test_provider_result_raw_contract_is_documented() -> None:
    """`ProviderResult.raw` 的字段级契约必须写明它不得含未脱敏值。

    这条守的是**结构**（字段上的承诺），与下面那条守**行为**（当前实现填不填）互补。
    """
    import dataclasses

    fields_map = {f.name: f for f in dataclasses.fields(ProviderResult)}
    assert "raw" in fields_map, "ProviderResult 没有 raw 字段：契约变了，请复核本组用例"
    # 默认值必须是 None：若哪天改成默认 {}，调用方会拿到一个"看起来有值"的空壳
    assert fields_map["raw"].default is None, "raw 的默认值不是 None"


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("aicore.provider.cloud_ocr", "CloudOcrProvider"),
        ("aicore.provider.cloud_vision", "CloudVisionProvider"),
        ("aicore.provider.deepseek", "DeepSeekTextProvider"),
    ],
)
def test_real_channels_do_not_populate_raw(module_name: str, class_name: str) -> None:
    """三个真实通道 MUST 保持 `raw` 为 `None`（源码级断言）。

    **为什么用源码级而不是行为级**：行为级需要构造假响应跑通一次调用，
    而那只能覆盖「某一条路径」；漏掉的分支（畸形响应、空响应）恰恰是最可能被塞进
    `raw` 的地方。源码级断言覆盖**所有路径**——只要出现对 `raw=` 的赋值就红。

    **这条断言的边界（如实写明）**：它是子串检查，改名（如 `raw = payload`）即绕过。
    真正的保证是「`raw` 的契约写在字段上 + 本用例迫使任何改动都必须有意识地
    改掉这条断言」。故它 MUST NOT 被当作「已验证不含未脱敏值」的证据。
    """
    import importlib

    module = importlib.import_module(module_name)
    assert hasattr(module, class_name), f"{module_name} 里没有 {class_name}"
    source_path = SERVICE_ROOT / "src" / "aicore" / "provider" / (
        f"{module_name.rsplit('.', 1)[1]}.py"
    )
    source = source_path.read_text(encoding="utf-8")
    assert len(source) > 1000, "读到的源码过短：路径可能已失效（断言会退化成空扫描）"

    offenders = [
        f"L{index}: {line.strip()}"
        for index, line in enumerate(source.splitlines(), start=1)
        if "raw=" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, (
        f"{class_name} 对 ProviderResult.raw 赋了值：{offenders}\n"
        f"raw 的契约是「MUST NOT 含未脱敏的证件值」，而本层无法判断外部返回内容是否已脱敏"
        f"（见各通道模块 docstring 的『已知边界』）。若确需回填，MUST 先加脱敏校验并更新本断言。"
    )
