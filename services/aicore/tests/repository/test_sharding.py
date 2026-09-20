"""`repository/sharding.py` 的用例：分表路由 / 跨分片守卫 / 真实 MySQL 建表（Task 3.3）。

**两段式**（与仓库既有口径一致）：

- **默认段：纯逻辑**，不连数据库、不读时钟。跨月边界一律用**显式构造的 datetime**
  （`2026-01-31T23:59:59.999Z` 与 `2026-02-01T00:00:00.000Z` 这类相邻毫秒），
  故断言结果不随"跑测试时是几月几点"漂移；测试内 MUST NOT 出现 `sleep`（`conftest` 的约定）。
- **`@pytest.mark.integration` 段：真实 MySQL**（`aicore_test`），默认不跑；
  连不上时**显式 skip 并说明原因**——静默通过等于让这道门禁在 CI 里永远不生效。

**清理边界（MUST）**：集成用例只 DROP 自己建的 3 张 `_<演练月>` 分片表；
MUST NOT `DROP DATABASE`、MUST NOT 碰 6 张固定名表（它们与别的用例/同事的库共用）。

**期望值来源**：表清单、月份、错误码一律取自 `sharding` 与 `core/errors.py` 的定档值，
不把实现抄一遍当期望值——抄两遍等于同一个笔误写两处。少数**逐字钉死**的常量
（`1001` / `1003` / `3 / 6 / 9` / 演练月）是工单的定档值，属于独立事实源，必须硬编码。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import DBAPIError

from aicore.core.errors import AICORE_ERROR_CODES, PARAM_ERROR_CODES, ParamError
from aicore.repository import sharding
from aicore.repository.models import LOGICAL_TABLE_NAMES

# ---------------------------------------------------------------------------
# 定档值（硬编码，理由见模块 docstring）
# ---------------------------------------------------------------------------
#: 工单 S1：3 张分片表。
EXPECTED_SHARDED_TABLES = frozenset({"ai_task", "ocr_result", "ocr_correction"})
#: 工单 S1：6 张非分片表。
EXPECTED_FIXED_TABLES = frozenset(
    {
        "vision_review",
        "vision_marker",
        "review_verdict",
        "kitchen_anomaly",
        "risk_predict_result",
        "vision_qa_log",
    }
)
#: 工单 S2 / er.md §5.2：建表顺序（被引用表先建）。
EXPECTED_BUILD_ORDER = ("ai_task", "ocr_result", "ocr_correction")

#: 物理表名的形态：`逻辑名_YYYYMM`。
PHYSICAL_NAME_RE = re.compile(r"^(?P<logical>[a-z_]+)_(?P<month>[0-9]{6})$")

#: 全角数字的 `202601`。用字符码现拼而**不写字面量**：RUF001 会拦下源码里的全角数字
#: （那条规则本身是对的），而这里全角数字恰恰是**被测数据**——`str.isdigit()` 对它返回 True，
#: 故它必须留在用例里，只是不能以字面量形态出现。
FULLWIDTH_MONTH = "".join(chr(0xFF10 + int(digit)) for digit in "202601")

#: 演练库与演练月。月份必须是**合法月份**（`physical_table_name` / `ensure_month_tables`
#: 会校验 `01`~`12`），且取远未来年份：既不与真实流量撞车，也不与
#: `tests/repository/test_apply_ddl_mysql.py` 的 `202613` 撞车。
DRILL_DATABASE = "aicore_test"
DRILL_MONTH = "209901"


# ---------------------------------------------------------------------------
# 1. 表清单（S1）
# ---------------------------------------------------------------------------
def test_table_manifests_are_exactly_three_six_nine() -> None:
    """S1：分片表恰好 3 张、非分片表恰好 6 张、合计 9 张（逐项断言，不靠集合相等推断）。"""
    assert sharding.SHARDED_TABLES == EXPECTED_SHARDED_TABLES
    assert sharding.FIXED_TABLES == EXPECTED_FIXED_TABLES
    assert len(sharding.SHARDED_TABLES) == 3
    assert len(sharding.FIXED_TABLES) == 6
    assert len(sharding.ALL_TABLES) == 9
    assert sharding.ALL_TABLES == EXPECTED_SHARDED_TABLES | EXPECTED_FIXED_TABLES
    # 两张清单互斥：同一张表不能既分片又不分片（两条建表路径会让结构漂移）
    assert not (sharding.SHARDED_TABLES & sharding.FIXED_TABLES)
    # 顺序表与模板表必须一一对应（少了某张表 = ensure_month_tables 静默不建它）
    assert sharding.SHARDED_TABLE_ORDER == EXPECTED_BUILD_ORDER
    assert set(sharding.SHARDED_TABLE_ORDER) == set(sharding.SHARDED_TABLE_FILES)


def test_table_manifests_match_the_model_metadata() -> None:
    """与 Task 3.2 的模型清单交叉核对：两处表集合 MUST 恒等（漂移即报红）。

    本模块 MUST NOT import `models`（工单限定 sharding 只 import `aicore.core.*` 与
    `sqlalchemy`），故一致性只能由**用例**来守——模型加了第 10 张表而 sharding 没跟上时，
    路由会算不出它的物理名（分片表）或建表流程根本不认识它（非分片表）。
    """
    assert set(LOGICAL_TABLE_NAMES.values()) == sharding.ALL_TABLES


# ---------------------------------------------------------------------------
# 2. 物理表名（S1 / S2）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("logical", sorted(EXPECTED_SHARDED_TABLES))
def test_physical_table_name_across_two_months(logical: str) -> None:
    """3 张分片表 × 跨 `2026-01`/`2026-02`：显式构造的 datetime → `xxx_YYYYMM`。"""
    january = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    february = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    assert sharding.physical_table_name(logical, january) == f"{logical}_202601"
    assert sharding.physical_table_name(logical, february) == f"{logical}_202602"


@pytest.mark.parametrize("logical", sorted(EXPECTED_SHARDED_TABLES))
def test_physical_table_name_accepts_known_month_string(logical: str) -> None:
    """「已知月份」的调用方可以直接送 `YYYYMM` 串（循环里复用同一个月时省一次算月）。"""
    name = sharding.physical_table_name(logical, "202602")
    assert name == f"{logical}_202602"
    match = PHYSICAL_NAME_RE.match(name)
    assert match is not None, f"{name} 不符合 xxx_YYYYMM 形态"
    assert match.group("logical") == logical


@pytest.mark.parametrize("logical", sorted(EXPECTED_FIXED_TABLES))
def test_physical_table_name_rejects_fixed_tables(logical: str) -> None:
    """非分片表没有物理分片名：放行会造出谁也查不到的孤儿表（S1）。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.physical_table_name(logical, datetime(2026, 1, 15, tzinfo=UTC))
    assert excinfo.value.code == 1002
    assert logical in str(excinfo.value)


@pytest.mark.parametrize(
    "bad_month",
    [
        "2026-01",  # 带分隔符
        "20261",  # 5 位
        "2026010",  # 7 位
        "2026ab",  # 含字母
        "202613",  # 月份 13：路由永远指不到的月份
        "202600",  # 月份 00
        FULLWIDTH_MONTH,  # 全角数字：`str.isdigit()` 对它返回 True，非 ASCII 判据
        "",  # 空串
    ],
)
def test_physical_table_name_rejects_malformed_month_string(bad_month: str) -> None:
    """`str` 入参 MUST 校验为「6 位数字且月份 01~12」，否则 `ParamError(1002)`。

    全角数字那条是**实测口径**：`str.isdigit()` 对全角数字返回 True，用它做判据会让非法月份
    绕过 `ParamError`（甚至绕过校验拼出一个非 ASCII 的物理表名）。
    """
    with pytest.raises(ParamError) as excinfo:
        sharding.physical_table_name("ai_task", bad_month)
    assert excinfo.value.code == 1002


@pytest.mark.parametrize("bad_at", [None, 202601, 2026.01, b"202601"])
def test_physical_table_name_rejects_wrong_at_type(bad_at: object) -> None:
    """`at` 既不是 datetime 也不是 `YYYYMM` 串时，MUST 是 `ParamError` 而不是未预期异常。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.physical_table_name("ai_task", cast("datetime | str", bad_at))
    assert excinfo.value.code == 1002


# ---------------------------------------------------------------------------
# 3. `shard_month_of` 的跨月边界（时区口径）
# ---------------------------------------------------------------------------
def test_shard_month_of_adjacent_millisecond_boundary() -> None:
    """相邻毫秒跨月：`2026-01-31T23:59:59.999Z` → `202601`；下一秒的 `.000Z` → `202602`。"""
    last_millisecond = datetime(2026, 1, 31, 23, 59, 59, 999000, tzinfo=UTC)
    first_millisecond = datetime(2026, 2, 1, 0, 0, 0, 0, tzinfo=UTC)
    assert (first_millisecond - last_millisecond) == timedelta(milliseconds=1)
    assert sharding.shard_month_of(last_millisecond) == "202601"
    assert sharding.shard_month_of(first_millisecond) == "202602"


def test_shard_month_of_utc_plus_eight_crosses_year() -> None:
    """带 `+08:00` 的 `2026-01-01 00:00` 属 UTC **上一年 12 月** → `202512`。

    这条是本模块最容易写错的一格：若直接 `strftime` 而不先归一到 UTC，会算成 `202601`
    ——跨年错片，而且本地时区越靠东、错得越多。
    """
    beijing_new_year = datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert beijing_new_year.astimezone(UTC).year == 2025
    assert sharding.shard_month_of(beijing_new_year) == "202512"
    # 同一天的 UTC 时刻（2025-12-31T16:00Z）与本地时刻必须落到同一个月
    assert sharding.shard_month_of(beijing_new_year.astimezone(UTC)) == "202512"


def test_shard_month_of_leap_day() -> None:
    """闰年 `2028-02-29T12:00:00Z` → `202802`（2 月 29 日不会被算成 3 月）。"""
    leap_day = datetime(2028, 2, 29, 12, 0, tzinfo=UTC)
    assert sharding.shard_month_of(leap_day) == "202802"


def test_shard_month_of_rejects_naive_datetime() -> None:
    """naive datetime MUST 抛 `ParamError(1002)` 并说明"必须带时区"，MUST NOT 猜时区。

    猜错就是静默跨月错片：`2026-01-01 00:00` 若被当成本地（`+08:00`）算，物理月会落到
    `202512`；被当成 UTC 算则是 `202601`——同一个值两种结果，只能由调用方说清。
    """
    with pytest.raises(ParamError) as excinfo:
        sharding.shard_month_of(datetime(2026, 1, 1, 0, 0))
    assert excinfo.value.code == 1002
    assert "时区" in str(excinfo.value)


def test_shard_month_of_names_the_field_in_error() -> None:
    """`field` 只进报错文案：点名缺时区的是哪个分片键，便于定位调用点。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.shard_month_of(datetime(2026, 1, 1, 0, 0), field="task_created_at")
    assert "task_created_at" in str(excinfo.value)


@pytest.mark.parametrize("bad_value", ["2026-01-15", "202601", 202601])
def test_shard_month_of_rejects_string_input(bad_value: object) -> None:
    """只收 `datetime`，**不收 `str`**（反证：字符串入口不存在，避免"随手传个日期也能过"）。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.shard_month_of(cast(datetime, bad_value))
    assert excinfo.value.code == 1002


# ---------------------------------------------------------------------------
# 4. 模板渲染（占位符协议 / 外键约束名带月份）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("logical", sorted(EXPECTED_SHARDED_TABLES))
def test_rendered_shard_template_has_no_brace_left(logical: str) -> None:
    """渲染后**剥注释**的 SQL 骨架里 MUST NOT 有 `{` 残留（残留 = 不可执行 SQL）。

    "剥注释"要用 `sharding.sql_skeleton`：它既吃 `--` 行注释，也掏空 `'...'` 字面量的内容。
    后者不是多余步骤——模板的**列 COMMENT 字符串**里本来就有花括号示例
    （``COMMENT '... GET /aicore/tasks/{taskId}'``、``COMMENT '... {x,y,width,height}'``），
    只剥行注释的话三张模板会一起"报红"，而那属于**文档**，MUST NOT 为迁就断言删掉。
    """
    rendered = sharding.render_shard_template(logical, "202601")
    skeleton = sharding.sql_skeleton(rendered)
    leftovers = sorted(set(re.findall(r"\{[^}]*\}", skeleton)))
    assert not leftovers, f"{logical} 渲染后骨架里仍残留占位符 {leftovers}"
    assert "{" not in skeleton, f"{logical} 渲染后骨架里仍含 '{{' 字符，渲染不完整"
    # 正向：物理表名真的落进 CREATE TABLE
    assert f"CREATE TABLE IF NOT EXISTS `{logical}_202601`" in skeleton


def test_rendered_correction_template_carries_month_into_foreign_key_name() -> None:
    """`{month}` MUST 同时替换进**外键约束名**：MySQL 约束名 schema 内唯一，
    写死会在第二个月报 `ERROR 1826`（Task 3.1 的真实 MySQL 实证）。"""
    rendered = sharding.render_shard_template("ocr_correction", "202602")
    assert "CONSTRAINT `fk_ocr_correction_task_202602` FOREIGN KEY" in rendered
    assert "REFERENCES `ocr_result_202602` (`task_id`)" in rendered
    # 反证：同一模板换一个月渲染，约束名必须跟着换（否则两个月会撞名）
    other = sharding.render_shard_template("ocr_correction", "202603")
    assert "fk_ocr_correction_task_202602" not in other
    assert "fk_ocr_correction_task_202603" in other


@pytest.mark.parametrize("logical", sorted(EXPECTED_FIXED_TABLES))
def test_template_for_rejects_fixed_tables(logical: str) -> None:
    """分片模板只属于 3 张分片表；非分片表问模板路径 MUST 抛错（两个方向都拦）。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.template_for(logical)
    assert excinfo.value.code == 1002
    with pytest.raises(ParamError) as excinfo:
        sharding.render_shard_template(logical, "202601")
    assert excinfo.value.code == 1002


@pytest.mark.parametrize("logical", sorted(EXPECTED_SHARDED_TABLES))
def test_render_fixed_table_ddl_rejects_sharded_tables(logical: str) -> None:
    """分片表必须经渲染才能执行，直接取固定名 DDL MUST 抛错（反向同理）。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.render_fixed_table_ddl(logical)
    assert excinfo.value.code == 1002


@pytest.mark.parametrize("logical", sorted(EXPECTED_FIXED_TABLES))
def test_render_fixed_table_ddl_returns_executable_sql(logical: str) -> None:
    """6 张非分片表的 DDL：可直接执行（骨架无占位符）、表名就是逻辑名、幂等建表。"""
    ddl = sharding.render_fixed_table_ddl(logical)
    skeleton = sharding.sql_skeleton(ddl)
    assert "{" not in skeleton, f"{logical} 的固定名 DDL 骨架里出现花括号（它不该是模板）"
    assert f"CREATE TABLE IF NOT EXISTS `{logical}`" in skeleton


class _FakeSqlFile:
    """假 DDL 文件：只实现渲染路径真的会用到的两个成员（`name` / `read_text`）。"""

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self._text = text

    def read_text(self, encoding: str = "utf-8") -> str:
        # `encoding` 只用于对齐 `Path.read_text` 的调用签名；假对象不做解码。
        del encoding
        return self._text


class _FakeDdlDir:
    """假 DDL 目录：`目录 / 文件名` 的语义与 `Path` 一致（`__truediv__`）。

    **为什么不用 `tmp_path`**：本项目的沙箱环境禁止在系统临时目录下建目录
    （`PermissionError: [WinError 5]`，`tests/unit/test_config.py` 已登记过同一限制），
    而这里根本不需要真实文件——假的目录对象既省掉一次磁盘写，也让"模板内容"直接写在用例里。
    """

    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    def __truediv__(self, filename: str) -> _FakeSqlFile:
        return _FakeSqlFile(filename, self._files[filename])


def test_shard_template_self_check_fires_on_broken_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反证：模板写错（占位符拼错）时**渲染期就炸**，而不是把不可执行 SQL 送去数据库。

    做法是把 `sharding.DDL_DIR` 换成一个只装着坏模板的假目录——若自检写成"永远通过"，
    本用例会拿到一句含 `{oops}` 的 SQL 而全绿，那就等于没有自检。
    """
    broken = "CREATE TABLE IF NOT EXISTS `{table}` (`x` int) ENGINE=InnoDB;\nSELECT {oops};\n"
    monkeypatch.setattr(sharding, "DDL_DIR", _FakeDdlDir({"10_ai_task.template.sql": broken}))
    with pytest.raises(RuntimeError, match="占位符残留"):
        sharding.render_shard_template("ai_task", "202601")


def test_fixed_ddl_self_check_fires_on_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """反证（固定名表一侧）：骨架里出现花括号即报错——它要么该改名为 `.template.sql`，
    要么是某次误编辑把模板正文粘进了固定名 DDL。"""
    broken = "CREATE TABLE IF NOT EXISTS `vision_review` (`x` int);\nSELECT {oops};\n"
    monkeypatch.setattr(sharding, "DDL_DIR", _FakeDdlDir({"20_vision_review.sql": broken}))
    with pytest.raises(RuntimeError, match="占位符残留"):
        sharding.render_fixed_table_ddl("vision_review")


def test_sql_skeleton_strips_comments_and_literal_contents() -> None:
    """`sql_skeleton` 的口径：行注释整行去掉、字面量内容掏空、其余原样保留。"""
    source = (
        "-- 注释里的 {A} 不算残留\n"
        "CREATE TABLE `t` (`c` int COMMENT '{B}', `d` varchar(8)) ENGINE=InnoDB;\n"
    )
    skeleton = sharding.sql_skeleton(source)
    assert "{A}" not in skeleton
    assert "{B}" not in skeleton
    assert "CREATE TABLE `t`" in skeleton
    assert "`d` varchar(8)" in skeleton


# ---------------------------------------------------------------------------
# 5. 缺分片键（S3）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("missing", [None, "", "   ", "\t\n"])
def test_require_shard_key_rejects_missing_values(missing: object) -> None:
    """`None` / 空串 / 仅空白 MUST 抛 `MissingShardKeyError`，且码值**逐字**是 `1001`。"""
    with pytest.raises(sharding.MissingShardKeyError) as excinfo:
        sharding.require_shard_key(missing, field="account_id")
    assert excinfo.value.code == 1001
    assert "account_id" in str(excinfo.value)


@pytest.mark.parametrize("present", ["acc_1", "0", " task_1 ", "非空"])
def test_require_shard_key_accepts_present_values(present: str) -> None:
    """有值就放行（含 `"0"` 这类"看起来假"的字符串：空判据只认 None/空/仅空白）。"""
    assert sharding.require_shard_key(present, field="account_id") is None


# ---------------------------------------------------------------------------
# 6. 跨分片（S4）
# ---------------------------------------------------------------------------
def test_assert_single_shard_rejects_cross_month() -> None:
    """两个月的分片键被组合进同一次操作 → `CrossShardOperationError`，码值逐字 `1003`。

    消息 MUST 点名 `operation` 与涉及月份：运维看到报错要能直接定位是哪次调用跨了片。
    """
    with pytest.raises(sharding.CrossShardOperationError) as excinfo:
        sharding.assert_single_shard(["202601", "202602"], operation="ocr_result.read")
    assert excinfo.value.code == 1003
    message = str(excinfo.value)
    assert "ocr_result.read" in message
    assert "202601" in message
    assert "202602" in message


def test_assert_single_shard_deduplicates_same_month() -> None:
    """同一个月出现多次仍是单分片：去重后恰好 1 个，返回它。"""
    assert sharding.assert_single_shard(["202601", "202601", "202601"], operation="x") == "202601"
    assert sharding.assert_single_shard(["202602"], operation="x") == "202602"


def test_assert_single_shard_rejects_empty() -> None:
    """一个分片键都没带 → `MissingShardKeyError`（1001），而不是"没有月份所以我放行"。"""
    with pytest.raises(sharding.MissingShardKeyError) as excinfo:
        sharding.assert_single_shard([], operation="ai_task.list")
    assert excinfo.value.code == 1001
    assert "ai_task.list" in str(excinfo.value)


def test_assert_single_shard_consumes_generator_once() -> None:
    """传生成器也必须能判跨分片：实现必须**先物化**，否则第二次遍历得到空结果。"""
    months: Iterator[str] = iter(["202601", "202602"])
    with pytest.raises(sharding.CrossShardOperationError):
        sharding.assert_single_shard(months, operation="ocr_correction.list")


def test_assert_single_shard_rejects_malformed_single_month() -> None:
    """只剩一个月但格式畸形时 MUST 抛错：本函数是"拼物理表名前的最后一道守卫"，
    放行畸形月份等于给调用方一个假的放行信号（fail-open）。"""
    with pytest.raises(ParamError) as excinfo:
        sharding.assert_single_shard(["2026-01"], operation="ai_task.list")
    assert excinfo.value.code == 1002


# ---------------------------------------------------------------------------
# 7. 错误类语义（继承链 + 构造期校验不能被绕过）
# ---------------------------------------------------------------------------
def test_error_classes_keep_param_error_validation() -> None:
    """两个异常都 MUST 是 `ParamError` 的子类，且 `AiCoreError` 的码值校验仍然生效。

    为什么要继承 `ParamError` 而不是 `AiCoreError`：`ParamError` 是**唯一**做了
    "码值必须落在 `PARAM_ERROR_CODES` 内"构造期校验的类；直接继承 `AiCoreError`
    就绕过了那道校验——写错码值要到发响应时才发现（前端收到平台表里不存在的码）。
    """
    assert issubclass(sharding.MissingShardKeyError, ParamError)
    assert issubclass(sharding.CrossShardOperationError, ParamError)
    assert sharding.MissingShardKeyError.code == 1001
    assert sharding.CrossShardOperationError.code == 1003
    assert sharding.MissingShardKeyError.code in PARAM_ERROR_CODES
    assert sharding.CrossShardOperationError.code in PARAM_ERROR_CODES
    assert {1001, 1003} <= AICORE_ERROR_CODES

    # 反证一：假码构造 MUST 抛 ValueError（构造期校验没被绕过）
    class _FakeCodeError(ParamError):
        code = 9999

    with pytest.raises(ValueError, match="不在本服务的错误码集合"):
        _FakeCodeError()

    # 反证二：ParamError 只接受 1xxx 三档，跨段码（2001 未登录）必须被拒
    with pytest.raises(ValueError, match="ParamError 的 code 只能是"):
        ParamError("参数错误", code=2001)

    # 反证三：真实异常实例的码值就是定档值（不是靠继承"看起来像"）
    assert sharding.MissingShardKeyError("缺键").code == 1001
    assert sharding.CrossShardOperationError("跨片").code == 1003


# ---------------------------------------------------------------------------
# 8. `ensure_month_tables`：顺序 / 不提交 / 不 DROP（假 Connection，纯逻辑）
# ---------------------------------------------------------------------------
class _RecordingConnection:
    """记录调用的假 `Connection`：只实现本模块真的会用到的几个方法。

    **为什么需要假对象**：`ensure_month_tables` 的两条硬约束——建表顺序、
    不提交事务——在真实库上很难直接观测（MySQL 对 DDL 有隐式提交，看不出实现是否 commit 过）。
    假对象把"这次调用到底做了什么"变成可断言的事实；若实现改成 `conn.execute(...)`、
    `conn.commit()` 或额外 DROP，本用例会立刻变红（未实现的方法直接抛 `AttributeError`）。
    """

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.calls: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.calls.append("exec_driver_sql")
        self.statements.append(statement)

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


def test_ensure_month_tables_executes_three_ddls_in_build_order() -> None:
    """建表顺序 MUST 为 `ai_task` → `ocr_result` → `ocr_correction`（被引用表先建，S2）。

    顺序错了在真实库上是**硬失败**（外键找不到被引用表），但那是集成用例的代价（要连库）；
    这里先用假对象把顺序钉死，让默认段也能拦住"循环写反了"。
    """
    recorder = _RecordingConnection()
    sharding.ensure_month_tables(cast(Connection, recorder), DRILL_MONTH)

    assert recorder.calls == ["exec_driver_sql"] * 3, (
        f"只允许 exec_driver_sql（既不 commit 也不 rollback），实际调用 {recorder.calls}"
    )
    created = [
        match.group(1)
        for statement in recorder.statements
        for match in re.finditer(r"CREATE TABLE IF NOT EXISTS `([^`]+)`", statement)
    ]
    assert created == [f"{logical}_{DRILL_MONTH}" for logical in EXPECTED_BUILD_ORDER]
    # 幂等前提：每条都是 IF NOT EXISTS；且**一条 DROP 都不许有**（删表不可逆）
    for statement in recorder.statements:
        assert "CREATE TABLE IF NOT EXISTS" in statement
        assert "DROP" not in statement.upper()


def test_ensure_month_tables_rejects_bad_month_before_any_sql() -> None:
    """非法月份 MUST 在发任何 SQL 之前被拒（否则会建出路由永远指不到的表）。"""
    recorder = _RecordingConnection()
    with pytest.raises(ParamError) as excinfo:
        sharding.ensure_month_tables(cast(Connection, recorder), "202613")
    assert excinfo.value.code == 1002
    assert recorder.calls == [], f"非法月份不该发出任何 SQL，实际 {recorder.statements}"


# ---------------------------------------------------------------------------
# 9. 真实 MySQL（默认不跑）：幂等建表 / 外键带月份 / 建表顺序
# ---------------------------------------------------------------------------
def _engine() -> Engine:
    """连**演练库**的引擎。

    口令只从 `DSH_IT_MYSQL_PASSWORD` 取（`conftest` 会把它从本机已被 gitignore 的 `.env`
    回填），**MUST NOT 硬编码**：取不到就让连通性探测失败并 skip，
    而不是把凭据写进版本库换一次"绿灯"。为什么不用 `AICORE_MYSQL_*`：那组已被 `conftest`
    注入成 `test_user` 占位值，集成测试读它只会拿到假凭据 → 假 skip（现场记录见 `conftest`）。
    """
    password = os.environ.get("DSH_IT_MYSQL_PASSWORD")
    if not password:
        pytest.skip(
            "未配置 DSH_IT_MYSQL_PASSWORD（或 .env 里的 AICORE_MYSQL_PASSWORD）："
            "集成用例需要真实演练库凭据；凭据 MUST NOT 硬编码进仓库"
        )
    url = URL.create(
        drivername="mysql+pymysql",
        username=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        password=password,
        host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
        database=os.environ.get("DSH_IT_MYSQL_DATABASE", DRILL_DATABASE),
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True)


def _require_mysql() -> Engine:
    """连不上就**显式跳过**（含原因），而不是让用例随机失败或静默通过。"""
    try:
        engine = _engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"需要真实 MySQL（{DRILL_DATABASE}）才能验证分片建表：{type(exc).__name__}: {exc}"
        )
    return engine


def _drop_drill_shards(engine: Engine) -> None:
    """只清理本用例建的 3 张 `_<演练月>` 分片表。

    MUST NOT `DROP DATABASE`、MUST NOT 碰 6 张固定名表（它们与别的用例/同事的库共用）。
    **逆建表顺序删**：`ocr_correction_<月>` 有指向同月 `ocr_result_<月>` 的物理外键，
    先删 `ocr_result_<月>` 会被 MySQL 以 3730 拒绝（`test_apply_ddl_mysql.py` 已实测）。
    """
    with engine.begin() as conn:
        for logical in reversed(EXPECTED_BUILD_ORDER):
            conn.execute(text(f"DROP TABLE IF EXISTS `{logical}_{DRILL_MONTH}`"))


def _table_names(conn: Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = :db"),
            {"db": DRILL_DATABASE},
        )
    }


def _foreign_keys(conn: Connection) -> dict[str, tuple[str, str, str]]:
    return {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            text(
                "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE, UPDATE_RULE "
                "FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = :db"
            ),
            {"db": DRILL_DATABASE},
        )
    }


@pytest.mark.integration
def test_ensure_month_tables_creates_nine_tables_with_month_fks() -> None:
    """真实 MySQL：`aicore_test` 里 9 张表齐备（3 张 `_<演练月>`），外键约束名带月份。

    6 张固定名表由 `render_fixed_table_ddl` 幂等建（`CREATE TABLE IF NOT EXISTS`），
    这样"9 张齐备"这条断言才有对象可查；它们**不在清理范围**内（MUST NOT 碰）。
    """
    engine = _require_mysql()
    _drop_drill_shards(engine)
    remaining: set[str] = set()
    try:
        with engine.begin() as conn:
            sharding.ensure_month_tables(conn, DRILL_MONTH)
            for logical in sorted(sharding.FIXED_TABLES):
                conn.exec_driver_sql(sharding.render_fixed_table_ddl(logical))

        with engine.connect() as conn:
            tables = _table_names(conn)
            foreign_keys = _foreign_keys(conn)

        expected = {f"{logical}_{DRILL_MONTH}" for logical in EXPECTED_SHARDED_TABLES}
        expected |= set(EXPECTED_FIXED_TABLES)
        assert expected <= tables, f"缺表：{sorted(expected - tables)}（实际有 {sorted(tables)}）"

        fk_name = f"fk_ocr_correction_task_{DRILL_MONTH}"
        assert fk_name in foreign_keys, f"分片外键名没带月份：实际外键 {sorted(foreign_keys)}"
        referenced, delete_rule, update_rule = foreign_keys[fk_name]
        assert referenced == f"ocr_result_{DRILL_MONTH}", (
            f"分片外键未指向同月表：实际 -> {referenced}"
        )
        assert (delete_rule, update_rule) == ("RESTRICT", "RESTRICT"), (
            f"外键动作不是显式 RESTRICT：DELETE={delete_rule} UPDATE={update_rule}"
        )
    finally:
        _drop_drill_shards(engine)
        with engine.connect() as conn:
            remaining = _table_names(conn)
        engine.dispose()

    dropped = {f"{logical}_{DRILL_MONTH}" for logical in EXPECTED_SHARDED_TABLES}
    assert not (dropped & remaining), f"清理没删干净：{sorted(dropped & remaining)}"
    assert set(EXPECTED_FIXED_TABLES) <= remaining, (
        f"清理把固定名表也删了：{sorted(set(EXPECTED_FIXED_TABLES) - remaining)}"
    )


@pytest.mark.integration
def test_ensure_month_tables_is_idempotent() -> None:
    """第二次调用零错误且**没有重建表**：幂等是"写入前确保存在"的前提。

    判据用 `information_schema.TABLES.CREATE_TIME` 前后一致——只看"没抛异常"是不够的：
    先 DROP 再 CREATE 也不抛异常，但那会让当月已有数据消失。
    """
    engine = _require_mysql()
    _drop_drill_shards(engine)
    create_time_sql = text(
        "SELECT TABLE_NAME, CREATE_TIME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME LIKE :pat"
    )
    params = {"db": DRILL_DATABASE, "pat": f"%\\_{DRILL_MONTH}"}
    try:
        with engine.begin() as conn:
            sharding.ensure_month_tables(conn, DRILL_MONTH)
        with engine.connect() as conn:
            before = dict(conn.execute(create_time_sql, params).all())

        with engine.begin() as conn:
            sharding.ensure_month_tables(conn, DRILL_MONTH)
        with engine.connect() as conn:
            after = dict(conn.execute(create_time_sql, params).all())

        assert before, "没查到演练月的分片表，前置执行可能失败"
        assert before == after, (
            f"复跑改变了表的创建时间，说明表被重建过（不是幂等）：\n前 {before}\n后 {after}"
        )
    finally:
        _drop_drill_shards(engine)
        engine.dispose()


@pytest.mark.integration
def test_build_order_forward_succeeds_and_reverse_fails() -> None:
    """建表顺序的**顺序探测**：反序 MUST 被 MySQL 拒绝，正序 MUST 成功。

    反序这次不是"理论上会失败"：`ocr_correction` 模板里有指向同月 `ocr_result_<月>` 的物理
    外键，被引用表不存在时 MySQL 直接拒绝建表（报找不到被引用的表）。
    正序那步走**真实建表入口** `ensure_month_tables`：前两张已存在时它是幂等的，
    故这一步同时验证了"入口自己按对顺序建表"。
    """
    engine = _require_mysql()
    _drop_drill_shards(engine)
    try:
        # 反序：先建引用方 —— MUST 失败
        with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
            conn.exec_driver_sql(sharding.render_shard_template("ocr_correction", DRILL_MONTH))
        assert f"ocr_result_{DRILL_MONTH}" in str(excinfo.value), (
            f"反序建表应报「找不到被引用的 ocr_result_{DRILL_MONTH}」，实际：{excinfo.value}"
        )

        # 正序第一步：被引用表先建
        with engine.begin() as conn:
            for logical in ("ai_task", "ocr_result"):
                conn.exec_driver_sql(sharding.render_shard_template(logical, DRILL_MONTH))

        # 正序第二步：再单独建引用方（走真实入口）
        with engine.begin() as conn:
            sharding.ensure_month_tables(conn, DRILL_MONTH)

        with engine.connect() as conn:
            tables = _table_names(conn)
            foreign_keys = _foreign_keys(conn)
        expected = {f"{logical}_{DRILL_MONTH}" for logical in EXPECTED_SHARDED_TABLES}
        assert expected <= tables, f"正序建表后仍缺表：{sorted(expected - tables)}"
        assert f"fk_ocr_correction_task_{DRILL_MONTH}" in foreign_keys, (
            f"缺带月份的外键：实际 {sorted(foreign_keys)}"
        )
    finally:
        _drop_drill_shards(engine)
        engine.dispose()
