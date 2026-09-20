"""阈值**留痕**（`spec.md:128` 的"**当次**快照"）与阈值可配的 API 级判据。Task 4.10 §5.3/§5.4。

## 载体与判据

- **阈值可配** → `Settings.confidence_high` / `confidence_medium`；判据：换一份配置 ⇒
  落库的阈值随之改变（分级本身的"边界移动"在 `tests/unit/test_confidence.py`）。
- **留痕** → `ai_task.model_meta.thresholds`；判据：① 提交时写入当次快照；
  ② **改阈值后旧任务的快照不变**；③ 新任务用新值。

## 为什么"只断言字段存在"不算留痕（工单 §5.4 的原话）

`spec.md:128` 要的是「**当次**置信度阈值快照」——留痕的全部意义是
"**依据什么阈值作出的判定**"可追溯。一个"字段在、但每次读都取当前配置"的实现，
字段确实存在，而留痕是**假的**：运营改一次阈值，历史任务的判定依据就跟着变了。
故判据必须**跨越一次配置变更**：先提交（旧阈值）→ 改配置 → 再提交（新阈值）
→ 回头读**第一个**任务，它的快照必须**还是旧值**。

## 怎么"改配置"（**两处**配置来源，MUST 分清）

- **路由读的那份**：`api/deps.py::get_settings` 从 `request.app.state.settings` 取，
  故用 FastAPI 的标准替换通道 `app.dependency_overrides[get_settings]`（与既有用例替换
  `get_now` 同一手法）——替换依赖等于替换部署形态里的配置来源；
- **全局那份**：`core/config.py::get_settings`（进程内缓存）。本文件的路由用例用不到它，
  但 `test_snapshot_guard_discriminates` 的**变异体**要读"当前配置"，
  它读的正是这一份——故那条自证里两处都要换，否则自证的前提不成立（实测踩过一次）。

## 本文件不覆盖什么（如实登记）

- **通道 → 落库 → 轮询返回分级**的端到端：M1 的 `main.py` 注的是 `handlers={}`，
  **没有真实 OCR 执行** ⇒ `ocr_result.needs_manual_review` 与"随 AI 输出返回分级"
  本阶段只能测到 **service 层**（`grade()`，见 `tests/unit/test_confidence.py`）。
  端到端登记为**第 5 组补**，**MUST NOT** 被读成"已端到端验过"；
  该边界由 `test_m1_has_no_ocr_handler_so_grading_is_not_end_to_end_yet` 守着（到点会响）。
- `confidence_level` 那个 enum 列在 `VISION_REVIEW` 表上（`er.md:63`），属 M2 的任务类型
  （`design.md:190`）⇒ M1 **没有为它加列**（加列会撞 Task 3.6 的三源比对）。
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from aicore.api.deps import ACCOUNT_ID_HEADER, get_now, get_settings
from aicore.core.config import Settings
from aicore.service.task.confidence import thresholds_snapshot_of

ACCOUNT_ID = "acc_confidence_owner"
JULY = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)

CONFIDENCE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "aicore" / "service" / "task" / "confidence.py"
)

#: 平台定档阈值（`er.md:301`）——第一轮提交用它。
BASELINE_THRESHOLDS = {"high": 0.9, "medium": 0.7}
#: 运营调整后的阈值——第二轮用它。**两个值都与平台默认不同**，故"快照没跟着变"
#: 与"快照跟着变了"不可能同时成立。
TUNED_THRESHOLDS = {"high": 0.95, "medium": 0.6}


class _Clock:
    """可注入时钟（`api/deps.py::get_now` 的替身）。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(api_client: TestClient) -> _Clock:
    """把路由的时间源钉进沙盒有表的那个月（202607）。"""
    holder = _Clock(JULY)
    api_client.app.dependency_overrides[get_now] = holder
    return holder


def _settings_with(client: TestClient, thresholds: Mapping[str, float]) -> Settings:
    """按给定阈值造一份**等价配置**（`Settings` 不可变 ⇒ 用 `model_copy`）。"""
    base: Settings = client.app.state.settings
    return base.model_copy(
        update={
            "confidence_high": thresholds["high"],
            "confidence_medium": thresholds["medium"],
        }
    )


def _use_thresholds(client: TestClient, thresholds: Mapping[str, float]) -> None:
    """把**路由读的那份配置**换成给定阈值（替换 `get_settings` 依赖）。"""
    client.app.dependency_overrides[get_settings] = lambda: _settings_with(client, thresholds)


def _post(client: TestClient) -> str:
    """提交一个任务，返回任务号。

    每次用**新的显式幂等键**：固定键会让第二次提交走幂等命中路径（返回原任务、不落新行），
    于是"新任务用新阈值"这条断言会拿到老任务的快照——第一版就是这么错的。
    """
    response = client.post(
        "/aicore/ocr",
        json={"imageKey": "cert/oss/2026/07/conf.jpg", "docType": "BUSINESS_LICENSE"},
        headers={
            ACCOUNT_ID_HEADER: ACCOUNT_ID,
            "Idempotency-Key": f"idem-conf-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 202, f"提交失败（{response.status_code}）：{response.text[:200]}"
    task_id: str = response.json()["data"]["taskId"]
    return task_id


def _snapshot_of(engine: Engine, task_id: str) -> dict[str, Any] | None:
    """裸 SQL 读回该任务的 `model_meta`（并解析 JSON）。

    裸读（不经仓储）是刻意的：用被测代码的读路径去验它自己的写路径，同一个缺陷会在
    两侧同时成立。JSON 列在裸读下是**字符串**（ORM 才会反序列化），故这里 `json.loads`。
    """
    with engine.connect() as conn:
        raw = conn.execute(
            text("select model_meta from ai_task_202607 where task_id = :task_id"),
            {"task_id": task_id},
        ).scalar()
    if raw is None:
        return None
    parsed: Any = json.loads(raw) if isinstance(raw, str) else raw
    assert isinstance(parsed, dict), f"model_meta 不是 JSON 对象：{parsed!r}"
    return parsed


def _frozen_snapshot_reader(engine: Engine) -> Callable[[str], Any]:
    """**生产的读法**：裸 SQL 读行 → 解析 JSON → 取 `thresholds`（不经过被测代码）。"""
    return lambda task_id: (lambda meta: None if meta is None else meta.get("thresholds"))(
        _snapshot_of(engine, task_id)
    )


def _assert_snapshot_is_frozen(
    read_thresholds: Callable[[str], Any], *, task_id: str, expected: Mapping[str, float]
) -> None:
    """**判据本体**：旧任务的阈值快照 MUST 仍是**当次**（旧）值。

    抽成函数是为了让判别力自证把**变异体的读法**喂给同一份判据
    （见 `test_snapshot_guard_discriminates`）：自证若复制一份断言，两边会各自漂移，
    于是"自证能判红"证明的就不是"真判据能判红"。
    """
    got = read_thresholds(task_id)
    assert got == expected, (
        f"改阈值之后，**旧任务**的快照跟着变了：{got!r}（应为 {expected!r}）——"
        f"那不是 spec.md:128 要的『当次快照』，而是『读当前配置』："
        f"留痕因此不可证伪（历史任务的判定依据会随运营改配置而漂移）"
    )


# ---------------------------------------------------------------------------
# §5.4 留痕：**当次快照**（跨越一次配置变更）
# ---------------------------------------------------------------------------
def test_threshold_snapshot_is_frozen_at_submission(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """**§5.4 的判据**：提交时冻结快照；改阈值后**旧任务的快照仍是旧值**。

    三步（缺一步这条就退化成"字段存在"）：

    1. 用**旧阈值**提交任务 A ⇒ 其 `model_meta.thresholds` == 旧值；
    2. 把配置改成**新阈值**；
    3. 再提交任务 B ⇒ B 是新值，而**回头读 A 仍是旧值**（判据本体）。

    第 3 步的"回头读 A"是核心：一个"读当前配置"的实现会在这里红。
    """
    _use_thresholds(api_client, BASELINE_THRESHOLDS)
    task_a = _post(api_client)
    read_thresholds = _frozen_snapshot_reader(sandbox_engine)
    _assert_snapshot_is_frozen(read_thresholds, task_id=task_a, expected=BASELINE_THRESHOLDS)

    _use_thresholds(api_client, TUNED_THRESHOLDS)
    task_b = _post(api_client)
    assert read_thresholds(task_b) == TUNED_THRESHOLDS, (
        f"改配置之后提交的任务没有用新阈值：{read_thresholds(task_b)!r}——"
        f"那说明路由没读配置（写死常量也能过这一条的一半）"
    )

    _assert_snapshot_is_frozen(read_thresholds, task_id=task_a, expected=BASELINE_THRESHOLDS)


def test_snapshot_keys_match_the_threshold_contract(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """快照的**键名**是 `{high, medium}`——与 `ProviderIdentity.thresholds` 逐字一致。

    键名不一致的失效形态是**静默**的：JSON 里读不到那个键只会得到 `None`，
    而 `thresholds_snapshot_of` 取不到时**不回落**默认值（刻意的，见它的 docstring），
    于是分级会在很久以后因缺阈值而报错。故这里在**落库形态**上把键名钉一次。
    """
    _use_thresholds(api_client, BASELINE_THRESHOLDS)
    task_id = _post(api_client)

    assert set(_snapshot_of(sandbox_engine, task_id) or {}) == {"thresholds"}
    assert thresholds_snapshot_of(_snapshot_of(sandbox_engine, task_id)) == BASELINE_THRESHOLDS


def test_threshold_config_really_reaches_the_route(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock
) -> None:
    """§5.3 的接线判据：路由读的是**当前配置**（换一份配置 ⇒ 落库的值随之改变）。

    与留痕那条的分工：那条钉"旧任务不漂移"，这条钉"配置真的被读到"。
    只有后者绿 = "写死常量也能过"；只有前者绿 = "配置改了不生效"。
    """
    _use_thresholds(api_client, {"high": 0.93, "medium": 0.61})
    task_id = _post(api_client)

    assert _frozen_snapshot_reader(sandbox_engine)(task_id) == {"high": 0.93, "medium": 0.61}


# ---------------------------------------------------------------------------
# 判别力自证：把"读当次快照"改成"读当前配置" ⇒ 留痕判据必红
# ---------------------------------------------------------------------------
_MUTANT_MODULE_NAME = "dsh_mutant_confidence_snapshot"


def _mutant_confidence_module(anchor: str, replacement: str) -> Any:
    """把 `service/task/confidence.py` 在**内存里**改一处，编译出一个变异模块。

    与 `tests/unit/test_confidence.py::_mutant_confidence_module` 同一取向
    （工单纪律：变异一律在内存里，MUST NOT「改 `src/` + `finally` 还原」）。
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


def test_snapshot_guard_discriminates(
    api_client: TestClient, sandbox_engine: Engine, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**判别力自证**：把"读当次快照"改成"读当前配置" ⇒ 留痕判据**必红**。

    ## 变异（内存变异，文件从不被写）

    `thresholds_snapshot_of` 的职责是"**从行里读回当次快照**"。把它换成"读当前配置"
    就是 `spec.md:128` 要防的那个实现：留痕字段还在，但它**不再代表当次**。

    ## ⚠ 两处配置来源都要换（实测踩过一次）

    变异体读的是 **`core/config.py::get_settings`**（进程内缓存那份），
    而路由读的是 **`api/deps.py::get_settings`**（从 `app.state.settings` 取的那份）。
    第一版只换了路由依赖 ⇒ 变异体读到的仍是 `.env` 里的平台默认值 ⇒
    "变异生效"那一步直接失败。故本自证**两处都换成同一份配置**，才是同一个场景。

    ## 断言（两半）

    1. 变异**真的生效**：只提交一个任务、改配置之后，变异体的读法给出的值**跟着变了**
       （生产读法给的是行里那份旧快照）；
    2. 同一场景喂给**与上一条逐字同一份判据** `_assert_snapshot_is_frozen` ⇒ 必须红。
    """
    mutant = _mutant_confidence_module(
        "    if model_meta is None:\n        return None\n",
        "    from aicore.core.config import get_settings as _live_settings\n"
        "\n"
        "    del model_meta\n"
        "    _live = _live_settings()\n"
        "    return confidence_thresholds(\n"
        "        high=_live.confidence_high, medium=_live.confidence_medium\n"
        "    )\n",
    )

    _use_thresholds(api_client, BASELINE_THRESHOLDS)
    task_a = _post(api_client)

    # 改配置：路由那份 + 全局那份（变异体读的是后者）。
    _use_thresholds(api_client, TUNED_THRESHOLDS)
    monkeypatch.setattr(
        "aicore.core.config.get_settings", lambda: _settings_with(api_client, TUNED_THRESHOLDS)
    )

    # ① 变异真的生效：同一次读，变异体给的是**当前配置**，生产读法给的是**行里的旧快照**。
    live_reader = lambda task_id: mutant.thresholds_snapshot_of(  # noqa: E731 - 一次性读法
        _snapshot_of(sandbox_engine, task_id)
    )
    produced = _frozen_snapshot_reader(sandbox_engine)
    assert live_reader(task_a) == TUNED_THRESHOLDS, "变异没有生效：本自证的前提不成立"
    assert produced(task_a) == BASELINE_THRESHOLDS, "生产读法竟然也读了当前配置：前提不成立"

    # ② 同一份判据喂给变异体的读法 ⇒ **必红**（旧任务的快照"跟着变了"）。
    with pytest.raises(AssertionError, match="当次快照"):
        _assert_snapshot_is_frozen(live_reader, task_id=task_a, expected=BASELINE_THRESHOLDS)


# ---------------------------------------------------------------------------
# M1 边界：端到端**没有**验（如实登记成一条会自己过期的判据）
# ---------------------------------------------------------------------------
def test_m1_has_no_ocr_handler_so_grading_is_not_end_to_end_yet() -> None:
    """**M1 边界**：受理路径**没有** OCR 处理器 ⇒ 分级尚未端到端。

    这条不是"测试一个不存在的东西"，而是把工单要求的**如实登记**变成一条**会自己过期**的判据：

    - 今天：`main.py` 注的是 `handlers={}`（M1 的事实，Task 4.7 的 §2.8）⇒
      "通道 → 落库 `needs_manual_review` → 轮询返回分级"这条端到端链路**不存在**；
    - 第 5 组注入真实 OCR 处理器之后，这条会**自动变红**，提示必须补：
      ① 端到端断言 `ocr_result.needs_manual_review`；② 端到端断言分级随输出返回。

    这样"待第 5 组补"就不是报告里的一句注释，而是一个到点会响的提醒。
    """
    main_source = (Path(__file__).resolve().parents[2] / "src" / "aicore" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "handlers={}" in main_source, (
        "main.py 不再注入空 handlers ⇒ M1 的 OCR 执行可能已经落地："
        "请补两条端到端判据（① ocr_result.needs_manual_review ② 分级随输出返回），"
        "并删掉本用例与报告里的『待第 5 组补』"
    )
