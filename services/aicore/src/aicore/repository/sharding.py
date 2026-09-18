"""按月分表路由：逻辑表 + 业务时间 → 物理表 `xxx_YYYYMM`（Task 3.3）。

**权威依据**（下面每条规则都出自这里，不是实现者的偏好）：

- `docs/superpowers/specs/2026-09-16-aicore-architecture-design.md` §2.3（数据库约定：
  分片表只有 3 张 / 分片键 / 路由禁令 / ID 形态）与 §5.3（分表路由三条加固）；
- `services/aicore/docs/er.md` §5.2（分片矩阵）、§5.3（分表路由规则与事件回写）、
  §5.4（分布式 ID 与主键策略）、§5.5（读写分离与冷热归档）。

**六条硬约束 → 代码落点**（S 编号沿用工单）：

- **S1** 分片表只有 3 张，物理名 `xxx_YYYYMM`
  → `SHARDED_TABLES`、`physical_table_name`
- **S2** 分片键 `ShardingKey(account_id, created_at)`；结果表随 `task_id` 同月同分片
  → `shard_month_of`、`SHARDED_TABLE_ORDER`
- **S3** 查询必须携带分片键下推；缺失直接抛错，MUST NOT 退化为全表扫描
  → `require_shard_key`、`MissingShardKeyError`
- **S4** 禁止跨分片 JOIN / 聚合 / 事务
  → `assert_single_shard`、`CrossShardOperationError`
- **S5** 只认业务字段 `created_at` / `task_id` 所在月，不依赖内嵌时间戳
  → `shard_month_of`（只收 datetime）
- **S6** 异步任务结果表同分片，1:1 查询不跨分片
  → `SHARDED_TABLE_ORDER` 的同月同后缀

**时区口径（`er.md` §6 绪：UTC 存储）**：`shard_month_of` 对 aware datetime 先
`astimezone(UTC)` 再取 `%Y%m`；naive datetime **直接抛 `ParamError`**，MUST NOT 猜它是
UTC 还是本地时间——「本地 `2026-01-01 00:00`」若被当成 UTC 就算成 `202601`，而它 UTC 是
`202512`，**猜错就是静默跨月错片**（比抛错危险得多）。

**月份只从业务字段算（S5）**：`ocr_result` / `ocr_correction` 的月份由 `task_id` 对应任务的
`created_at` 决定——`task_id` 是「`task_` 前缀 + UUID」，**不含任何内嵌时间戳**
（`er.md` §5.4 L248），故调用方 MUST 传入该任务的 `created_at`；本模块 MUST NOT 尝试从
`task_id` 里解析月份。

**渲染只有一份实现**：`render_shard_template` / `render_fixed_table_ddl` 是 `{table}` /
`{month}` 占位符协议的**唯一实现处**，`scripts/apply_ddl.py`（Task 3.1 的建表脚本）改为
import 本模块——两份渲染实现必然漂移，而漂移的表现是「脚本建的表与运行期建的表不是同一个
结构」。`{month}` 会**同时**替换进外键约束名（`fk_ocr_correction_task_{month}`）：MySQL 的
外键约束名在 **schema 内唯一**，写死会在第二个月报 `ERROR 1826`。

**事务边界不在这里**：`ensure_month_tables` 只发 DDL，**不 DROP、不显式 commit**——建表归属
哪个事务由调用方（Task 3.4 的会话 / Task 3.7 的仓库）决定。

**本模块的依赖面**：只 import `aicore.core.*` 与 `sqlalchemy`（分层契约 3：repository 层
MUST NOT 依赖 service；也 MUST NOT 反向依赖 api / provider / port）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy.engine import Connection

from aicore.core.errors import (
    PARAM_FORMAT_CODE,
    PARAM_MISSING_CODE,
    PARAM_VALUE_CODE,
    ParamError,
)

# 服务根 = 本文件的上四级（repository/ -> aicore/ -> src/ -> services/aicore/）。
# `scripts/apply_ddl.py` 也从这里取 DDL 目录：**「DDL 在哪」只允许有一处定义**。
SERVICE_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: DDL 权威定义目录（spec §5.5：纯 SQL DDL 是结构定义的唯一权威）。
DDL_DIR: Final[Path] = SERVICE_ROOT / "deploy" / "sql" / "ddl"

# ---------------------------------------------------------------------------
# 表清单（S1）：9 张表 = 3 张分片表 + 6 张非分片表
#
# **顺序即建表顺序**：`ocr_correction` 的物理外键指向同月的 `ocr_result_YYYYMM`，
# 被引用表必须先建（`er.md` §5.2/§7.3、spec §5.1）。`ai_task` 排第一：它是分片键的来源表
# （`ocr_result` / `ocr_correction` 随 `task_id` 同月落同分片）。
#
# 分片表只登记**逻辑名**：物理名（`ai_task_202601`）与物理外键约束名
# （`fk_ocr_correction_task_202601`）一律由本模块**现算**，MUST NOT 在任何清单里写死月份——
# 写死等于把「按月分表」退回「每月手工改配置」。
# ---------------------------------------------------------------------------

#: 分片表的建表顺序（被引用表在前）。`ensure_month_tables` 按此顺序建。
SHARDED_TABLE_ORDER: Final[tuple[str, ...]] = ("ai_task", "ocr_result", "ocr_correction")

#: 分片表：逻辑名 -> `.template.sql` 文件名（含 `{table}` / `{month}` 占位符）。
SHARDED_TABLE_FILES: Final[Mapping[str, str]] = {
    "ai_task": "10_ai_task.template.sql",
    "ocr_result": "11_ocr_result.template.sql",
    "ocr_correction": "12_ocr_correction.template.sql",
}

#: 非分片表：逻辑名 -> `.sql` 文件名（可直接执行，无占位符）。
FIXED_TABLE_FILES: Final[Mapping[str, str]] = {
    "vision_review": "20_vision_review.sql",
    "vision_marker": "21_vision_marker.sql",
    "review_verdict": "22_review_verdict.sql",
    "kitchen_anomaly": "23_kitchen_anomaly.sql",
    "risk_predict_result": "24_risk_predict_result.sql",
    "vision_qa_log": "25_vision_qa_log.sql",
}

#: 需要按月分表的 3 张逻辑表（S1）。
SHARDED_TABLES: Final[frozenset[str]] = frozenset(SHARDED_TABLE_ORDER)

#: 不分片的 6 张逻辑表（S1）。
FIXED_TABLES: Final[frozenset[str]] = frozenset(FIXED_TABLE_FILES)

#: AICORE 全部 9 张逻辑表（S1）。
ALL_TABLES: Final[frozenset[str]] = SHARDED_TABLES | FIXED_TABLES

#: 分片月 `YYYYMM` 的判据：**只认 ASCII 数字**。
#: 不用 `str.isdigit()`：它对上标（`²`）也返回 True，随后的 `int()` 会抛 `ValueError`
#: ——那会让非法月份绕过 `ParamError` 变成未预期异常（等于把参数问题报成服务故障）。
_MONTH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]{6}")

#: 占位符协议（模板顶部注释是权威说明）：`{table}` = 本表物理名，`{month}` = 同月兄弟表月份。
_TABLE_PLACEHOLDER: Final[str] = "{table}"
_MONTH_PLACEHOLDER: Final[str] = "{month}"

#: 花括号 token（自检用）：`{...}` 形态的任何残留。
_BRACE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\{[^}]*\}")

#: SQL 行注释前缀。
_SQL_LINE_COMMENT: Final[str] = "--"

#: SQL 单引号字符串字面量（含 `\'` 转义）：自检时掏空其内容，见 `sql_skeleton`。
_SQL_STRING_LITERAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"'(?:[^'\\]|\\.)*'")

#: 表总数的定档值（S1：3 张分片表 + 6 张非分片表）。
_EXPECTED_TABLE_COUNT: Final = 9


def _check_table_manifests() -> None:
    """导入期自检：表清单三处口径必须自洽（少一处会让某张表被**静默跳过**）。

    挡住的三个静默失效点：

    1. `SHARDED_TABLE_ORDER` 与 `SHARDED_TABLE_FILES` 键集不等——新加一张分片表时只改字典
       不改元组，`ensure_month_tables` 就**不建那张表**，直到第一次写入才炸；
    2. 同一张逻辑表既登记为分片表又登记为非分片表（两条建表路径各建一份，结构必然漂移）；
    3. 表总数不是 9（S1 的定档值被改坏）。

    放在导入期而不是用例里：这三个失效点一旦成立，"代码能跑"本身就是错的，
    越早炸越好；用例是第二道防线（`tests/repository/test_sharding.py` 逐项断言）。
    """
    if set(SHARDED_TABLE_ORDER) != set(SHARDED_TABLE_FILES):
        raise RuntimeError(
            f"分片表清单不自洽：顺序表 {sorted(SHARDED_TABLE_ORDER)} vs "
            f"模板表 {sorted(SHARDED_TABLE_FILES)}"
        )
    overlap = SHARDED_TABLES & FIXED_TABLES
    if overlap:
        raise RuntimeError(f"同一张表不能既分片又不分片：{sorted(overlap)}")
    if len(ALL_TABLES) != _EXPECTED_TABLE_COUNT:
        raise RuntimeError(
            f"逻辑表应为 {_EXPECTED_TABLE_COUNT} 张（3 分片 + 6 非分片），"
            f"实际 {len(ALL_TABLES)}：{sorted(ALL_TABLES)}"
        )


_check_table_manifests()


# ---------------------------------------------------------------------------
# 错误类：**继承 `ParamError` 而不是 `AiCoreError`**（工单硬要求）
#
# `ParamError` 是**唯一**做了「码值必须落在 `PARAM_ERROR_CODES` 内」构造期校验的类；
# 直接继承 `AiCoreError` 就绕过了那道校验（写错码值要到发响应时才暴露）。
# 故口径是：**保留 `ParamError` 的校验、改类名表达语义**——两者都要。
# ---------------------------------------------------------------------------
class MissingShardKeyError(ParamError):
    """缺分片键（业务码 **`1001`**，参数缺失）。

    **码值定档理由（MUST NOT 改成 `1002`）**：`core/errors.py` 的映射表把 `1001` 定为
    「`missing` —— 必填项没送到」，而本异常要表达的正是「这次操作没带分片键」；
    `1002` 是「其余全部……**兜底档**」，本异常能明确归类到 `missing`，
    用兜底档会让码值语义漂移。

    **为什么继承 `ParamError`**：见本段上方注释——`ParamError` 是唯一带码值构造期校验的类。
    """

    #: 类属性与构造参数**都**给码值：类属性让「不构造实例也能读到码」（错误映射表、文档、
    #: 反射都直接读类属性），构造参数让 `ParamError` 的构造期校验照常跑起来。
    code: int = PARAM_MISSING_CODE

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, code=PARAM_MISSING_CODE)


class CrossShardOperationError(ParamError):
    """跨分片操作（业务码 **`1003`**，枚举或范围非法）。

    **码值定档理由（MUST NOT 改成 `1002`）**：跨分片是「两个月的分片键被组合进同一次
    操作」，属**取值组合越界**，落在 `1003` 的「枚举或范围非法」语义内；
    `1002` 是「三桶都归不进去」的兜底档，跨分片能明确归类，用兜底档会让码值语义漂移。
    **也不取业务规则段的码**（如 `3007` 这类已锁 409 资源冲突的码）：跨分片是**参数组合**
    问题（`1xxx` 段），不是业务规则失败；何况 `AICORE_ERROR_CODES` 里根本没有 `3007`，
    写它连 `ParamError` 的构造期校验都过不去。张冠李戴会让前端按错的语义处置。

    **出处（S4）**：spec §2.3 / `er.md` §5.3「**禁止跨分片 JOIN / 聚合 / 事务**」。
    """

    #: 同 `MissingShardKeyError`：类属性 + 构造参数都给码值。
    code: int = PARAM_VALUE_CODE

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, code=PARAM_VALUE_CODE)


# ---------------------------------------------------------------------------
# 占位符渲染的公共工具
# ---------------------------------------------------------------------------
def sql_skeleton(source: str) -> str:
    """SQL 的**可执行骨架**：剥掉 `--` 行注释，并把 `'...'` 字面量的内容掏空。

    **为什么需要它**（而不是直接扫 `{`）：模板里的花括号示例落在**注释的字符串字面量**里，
    例如 ``COMMENT '... GET /aicore/tasks/{taskId}'`` 与
    ``COMMENT '... {channel, provider, modelVersion, ...}'``；`21_vision_marker.sql` 的
    `bbox_json` 注释里也有 `{x,y,width,height}`。这些串在 MySQL 里是**数据**，
    永远不会被当 SQL 解析，所以「渲染后还有没有残留占位符」只应对**代码骨架**发问。
    **MUST NOT** 反过来把注释里的示例花括号删掉：那是给人看的文档，
    为迁就一条断言而改文档是本末倒置。
    """
    without_comments = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(_SQL_LINE_COMMENT)
    )
    return _SQL_STRING_LITERAL_PATTERN.sub("''", without_comments)


def _assert_no_placeholder(rendered: str, *, source: str) -> None:
    """渲染后自检：SQL 骨架里 MUST NOT 有 `{` 残留（有则立刻炸，见两个渲染函数）。

    抛 `RuntimeError` 而不是 `ParamError`：残留占位符是**模板/实现的缺陷**，不是调用方
    参数问题——若抛 `ParamError` 会把它报成 400「参数错误」误导排查，`RuntimeError` 经
    兜底处理器成 `5000` 内部错误才是对的语义。
    """
    skeleton = sql_skeleton(rendered)
    if "{" not in skeleton:
        return
    leftovers = sorted(set(_BRACE_TOKEN_PATTERN.findall(skeleton)))
    raise RuntimeError(
        f"{source} 渲染后 SQL 骨架里仍有占位符残留 {leftovers}："
        f"模板写错时必须在渲染期就炸，MUST NOT 把不可执行 SQL 送去数据库"
    )


def _require_month(month: object, *, source: str) -> str:
    """校验分片月 `YYYYMM`：6 位 ASCII 数字且月份在 `01`~`12`；非法抛 `ParamError(1002)`。

    **为什么要卡 `01`~`12`**：`shard_month_of` 算出来的月必然合法，非法月份只可能来自
    「调用方自己拼的串」。放行 `202613` 会建出一张**路由永远指不到**的表（静默错片），
    宁可在入口炸掉。
    """
    if not isinstance(month, str) or _MONTH_PATTERN.fullmatch(month) is None:
        raise ParamError(
            f"{source} 的分片月必须是 6 位数字 YYYYMM，收到 {type(month).__name__}",
            code=PARAM_FORMAT_CODE,
        )
    if not 1 <= int(month[4:]) <= 12:
        raise ParamError(
            f"{source} 的分片月 {month} 里月份必须落在 01~12",
            code=PARAM_FORMAT_CODE,
        )
    return month


# ---------------------------------------------------------------------------
# 路由：业务时间 → 分片月 → 物理表名
# ---------------------------------------------------------------------------
def shard_month_of(created_at: datetime, *, field: str = "created_at") -> str:
    """业务时间 → 分片月 `YYYYMM`（**先归一到 UTC** 再取月）。

    **只收 `datetime`，不收 `str`**（工单硬要求）：物理月必须由业务时间字段算出来，
    收字符串等于给「随手传个 `2026-01-15` 也能过」留一个模糊入口。需要「已知月份」的
    调用方走 `physical_table_name(logical, at="202601")`。

    **`task_id` 不参与算月（S5）**：`task_id` 是 `task_` + UUID，不含时间戳；
    `ocr_result` / `ocr_correction` 的月份由**该任务**的 `created_at` 决定，
    调用方传入即可——本函数不去猜、也不解析 `task_id`。

    **naive datetime 直接抛 `ParamError(1002)`**：`er.md` §6 绪定的是 UTC 存储，naive 值
    既可能是 UTC 也可能是本地时间，两种解释差一个时区；猜错就是静默跨月错片，
    故宁可让调用方补上时区。

    `field` 只进报错文案：点名是哪个业务时间字段（`created_at` / `task_id` 对应的时间），
    便于定位是谁没带时区。
    """
    if not isinstance(created_at, datetime):
        raise ParamError(
            f"分片键 {field} 必须是 datetime（不接受字符串等其它形态）",
            code=PARAM_FORMAT_CODE,
        )
    # `tzinfo` 非空但 `utcoffset()` 返回 None 的畸形时区也算 naive：`astimezone` 对这种值
    # 会按**本地时区**解释，等于静默换了个时区口径。
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ParamError(
            f"分片键 {field} 必须带时区：naive datetime 无法判断 UTC 归属，猜错会跨月错片",
            code=PARAM_FORMAT_CODE,
        )
    return created_at.astimezone(UTC).strftime("%Y%m")


def physical_table_name(logical: str, at: datetime | str) -> str:
    """逻辑表 + 业务时间（或已知分片月）→ 物理表名 `xxx_YYYYMM`。

    - `at` 是 `datetime`：走 `shard_month_of`（UTC 归一 + naive 拒绝）；
    - `at` 是 `str`：必须是合法的 `YYYYMM`（6 位数字、月份 `01`~`12`），否则
      `ParamError(1002)`——这条口子只服务「月份已经算好」的调用方（如循环里复用同一个月），
      MUST NOT 变成「随手传个日期串」的入口。

    **只对分片表有效（S1）**：6 张非分片表的物理名就是逻辑名，传进来一律 `ParamError(1002)`
    ——放行会造出 `vision_review_202601` 这种**谁也查不到的孤儿表**（建表、写入都"成功"，
    查询永远落空）。
    """
    if logical not in SHARDED_TABLES:
        raise ParamError(
            f"表 {logical} 不是分片表（分片表只有 {sorted(SHARDED_TABLES)}），没有物理分片名",
            code=PARAM_FORMAT_CODE,
        )
    if isinstance(at, str):
        month = _require_month(at, source=f"physical_table_name({logical})")
    elif isinstance(at, datetime):
        month = shard_month_of(at)
    else:
        raise ParamError(
            f"physical_table_name 的 at 只能是 datetime 或 YYYYMM 串，收到 {type(at).__name__}",
            code=PARAM_FORMAT_CODE,
        )
    return f"{logical}_{month}"


# ---------------------------------------------------------------------------
# 模板渲染（`scripts/apply_ddl.py` 从本模块 import，MUST NOT 各写一份）
# ---------------------------------------------------------------------------
def template_for(logical: str) -> Path:
    """分片表 → 其 DDL 模板路径（`.template.sql`，含 `{table}` / `{month}` 占位符）。

    非分片表**没有模板**：6 张固定名表是可直接执行的 `.sql`，走 `render_fixed_table_ddl`。
    传非分片表一律 `ParamError(1002)`——两个方向都拦（`render_fixed_table_ddl` 对分片表
    同样抛），否则「把固定名表当分片表建」会静默建出上面说的孤儿表。
    """
    filename = SHARDED_TABLE_FILES.get(logical)
    if filename is None:
        raise ParamError(
            f"表 {logical} 不是分片表（分片表只有 {sorted(SHARDED_TABLES)}），没有分片模板",
            code=PARAM_FORMAT_CODE,
        )
    return DDL_DIR / filename


def render_shard_template(logical: str, month: str) -> str:
    """渲染分片表模板 → 可执行 SQL（`{table}` → 物理表名，`{month}` → 分片月）。

    **`{month}` 会同时替换进外键约束名**（模板里写的是
    ``CONSTRAINT `fk_ocr_correction_task_{month}` ``）：MySQL 的外键约束名在 **schema 内唯一**
    （不是表内唯一），把约束名写死会在第二个月报
    `ERROR 1826 Duplicate foreign key constraint name`——Task 3.1 已在真实 MySQL 上实测。
    本函数对**整份模板**做占位符替换，约束名自然带上月份；这是刻意保留的语义，
    MUST NOT 收窄成"只替换表名"。

    **渲染后自检「骨架里没有 `{` 残留」**：模板写错时**立刻炸**，而不是把不可执行 SQL 送去
    数据库等 MySQL 报语法错（那时的报错位置离真正原因很远，最难回推）。判据只看 SQL 骨架
    （见 `sql_skeleton`）：注释与字符串字面量里的花括号是文档示例，不算残留。

    月份格式**不在这里校验**：Task 3.1 的 `apply_ddl.py --month` 只做「6 位数字」检查并有用例
    钉住那条 CLI 契约；月份的业务校验落在 `physical_table_name` 的 `str` 分支与
    `ensure_month_tables`（两个**运行期**入口）上。
    """
    source = template_for(logical)
    rendered = source.read_text(encoding="utf-8")
    rendered = rendered.replace(_TABLE_PLACEHOLDER, f"{logical}_{month}")
    rendered = rendered.replace(_MONTH_PLACEHOLDER, month)
    _assert_no_placeholder(rendered, source=source.name)
    return rendered


def render_fixed_table_ddl(logical: str) -> str:
    """非分片表 → 可直接执行的 DDL 原文（`.sql`，无占位符）。

    **只对非分片表有效**：传分片表一律 `ParamError(1002)`（反向同理，
    `render_shard_template` 对非分片表也抛）——分片表必须经渲染才能执行，
    直接返回原文等于把 `{table}` 这种不可执行文本送去数据库。

    与分片渲染共用同一条自检：固定名表的骨架里也 MUST NOT 出现 `{`（出现即说明这个文件
    被误当模板、或它本该改名为 `.template.sql`）。
    """
    filename = FIXED_TABLE_FILES.get(logical)
    if filename is None:
        raise ParamError(
            f"表 {logical} 是分片表（{sorted(SHARDED_TABLES)}），"
            f"必须经 render_shard_template 渲染，没有固定名 DDL",
            code=PARAM_FORMAT_CODE,
        )
    path = DDL_DIR / filename
    ddl = path.read_text(encoding="utf-8")
    _assert_no_placeholder(ddl, source=path.name)
    return ddl


# ---------------------------------------------------------------------------
# 幂等建表（S2 / S6）
# ---------------------------------------------------------------------------
def ensure_month_tables(conn: Connection, month: str) -> None:
    """幂等确保 `month` 的三张分片物理表存在（写入前调用，spec §5.3）。

    **建表顺序 MUST 为 `ai_task` → `ocr_result` → `ocr_correction`**：`ocr_correction` 的物理
    外键指向**同月**的 `ocr_result_YYYYMM`，被引用表必须先建（`er.md` §5.2/§7.3、spec §5.1）；
    顺序就是 `SHARDED_TABLE_ORDER`。反序建会被 MySQL 以"找不到被引用表"拒绝——集成用例用
    「反序 MUST 失败 + 正序 MUST 成功」正面钉住这条，而不是只信任这个循环写对了。

    **幂等**：模板本身就是 `CREATE TABLE IF NOT EXISTS`，复跑零错误；本函数**不 DROP 任何
    东西**（删表是不可逆动作，不属于"确保存在"）。

    **不提交事务**：只发 DDL，事务边界归调用方（Task 3.4 的会话 / Task 3.7 的仓库）。
    补充一句实话：MySQL 对 DDL 本身有**隐式提交**语义，所以"本函数不 commit"并不等于
    "调用方能在同一事务里回滚建表"——这里能保证的是本模块不擅自替调用方决定边界。

    用 `conn.exec_driver_sql(sql)` 而不是 `conn.execute(text(sql))`：DDL 是**纯 SQL 文本**、
    没有绑定参数，`text()` 会去解析 `:name` / `%` 这类标记，给模板正文引入一类与渲染无关的
    语法坑；驱动层直发既贴合 DDL 的语义，也省掉一次无谓的 SQL 文本改写。
    """
    validated = _require_month(month, source="ensure_month_tables")
    for logical in SHARDED_TABLE_ORDER:
        conn.exec_driver_sql(render_shard_template(logical, validated))


# ---------------------------------------------------------------------------
# 跨分片守卫（S3 / S4）
# ---------------------------------------------------------------------------
def require_shard_key(value: object, *, field: str) -> None:
    """分片键存在性守卫：`None` / 空串 / 仅空白 → `MissingShardKeyError`。

    **出处（S3）**：`er.md` §5.3「查询**必须携带分片键下推**」+ spec §2.3 同款原文，
    以及 spec §5.3 的加固「查询**未携带分片键时直接抛错**，而非退化为全表扫描」。
    只把这条写在文档里等于没写：没有本守卫，「忘了带分片键」的代码会安静地扫全部分片
    （跨月分片表连 UNION 都拼不出来时，就是静默少数据或全表扫描）。

    **判据只认三种**：`None`、空串、仅空白串。非字符串（例如把 `account_id` 传成了数字）
    不算「缺失」——那是类型问题，由调用方的类型注解与 `mypy src` 兜住；
    本守卫不越权把类型错误改判成缺参（改判会让码值语义漂移，与 1001 的定档不符）。

    `field` 只进报错文案：点名缺的是哪个分片键（`account_id` / `created_at` / `task_id`）。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingShardKeyError(
            f"缺少分片键 {field}：查询 MUST 携带分片键下推，MUST NOT 退化为全表扫描"
        )


def assert_single_shard(months: Iterable[str], *, operation: str) -> str:
    """单分片守卫：本次操作涉及的月份去重后必须恰好 1 个月，返回该月。

    **出处（S3 / S4）**：spec §2.3 的「路由禁令：**禁止跨分片 JOIN / 聚合 / 事务**」与
    `er.md` §5.3 同款原文（「跨月查询禁全表扫描 UNION，聚合走异步/从库」；S6 要求结果表
    与其任务同分片，1:1 查询不跨分片）。跨分片操作在**语法层往往跑得通**（MySQL 不拦
    `UNION` 两个月分片表），但结果语义与事务语义都不成立（分片事务没有全局协调者），
    故必须在拼 SQL 之前拒绝，而不是等数据错乱。

    三档判据：

    - 长度 0 → `MissingShardKeyError`：本次操作**一个**分片键都没带（S3）；
    - 去重后 > 1 → `CrossShardOperationError`：消息点名 `operation` 与全部月份，
      便于运维直接定位是哪次调用跨了片；
    - 恰好 1 → 返回它（调用方拿它去 `physical_table_name` 拼物理表名）。

    `months` 收 `Iterable` 但**立刻物化一次**：生成器只能消费一次，先物化才能既做去重、
    又拼报错文案，不会把「传了个生成器」变成难以复现的空结果。
    """
    involved = list(months)
    if not involved:
        raise MissingShardKeyError(
            f"操作 {operation} 未携带任何分片月：查询 MUST 携带分片键下推，MUST NOT 全表扫描"
        )
    unique = list(dict.fromkeys(involved))
    if len(unique) > 1:
        raise CrossShardOperationError(
            f"操作 {operation} 跨分片：涉及月份 {unique}，"
            f"禁止跨分片 JOIN / 聚合 / 事务，请按单个月份拆成多次操作"
        )
    # 单月也要过格式校验：本函数是"拼物理表名前的最后一道守卫"，
    # 放行一个畸形月份等于给调用方一个假的放行信号（fail-open）。
    return _require_month(unique[0], source=f"操作 {operation} 的分片月")
