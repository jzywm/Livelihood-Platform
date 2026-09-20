"""SQLAlchemy 2.x 声明式模型：AICORE 9 张表在代码侧的**唯一映射**。

**权威与改动顺序（MUST）**：结构以 `deploy/sql/ddl/*.sql` 为**唯一权威**，本模块只是它的
代码侧映射；字段口径来自 `docs/er.md` §6 数据字典。任何结构变更 MUST **先改 DDL、
再改本模块**，MUST NOT 反向定义 DDL 里没有的列或索引。两边的偏差由
`tests/repository/test_ddl_matches_er.py`（Task 3.1，er.md ↔ DDL）与
`scripts/compare_schema.py`（Task 3.6，比对源含本模块的 `Base.metadata`）强制抓出。

**分片表只写逻辑表名（MUST）**：`ai_task` / `ocr_result` / `ocr_correction` 按月分表，
物理名形如 `ai_task_202601`。本模块的 `__tablename__` 一律取**逻辑名**，物理名由
`repository/sharding.py` 的 `physical_table_name()` 现算 —— 元数据里必须是逻辑名，
Task 3.6 的离线比对才谈得上「逐列比对」；`LOGICAL_TABLE_NAMES` 是「模型类 -> 逻辑表名」
的唯一出处。本模块 MUST NOT 定义「每月一个模型类」的子类，也 MUST NOT 让任何
`__tablename__` 含 `YYYYMM`。

**类型映射**（逐条对齐工单，MUST NOT 自创）：

| DDL 类型 | 本模块 |
|---|---|
| `varchar(n)` | `String(n)`，标注 `Mapped[str]`（可空列 `Mapped[str \\| None]`） |
| `enum(...)` | `Enum(..., native_enum=True, validate_strings=True, length=<最长值长度>)` |
| `tinyint(1)` | `Boolean()`（MySQL 里 `BOOL` 就是 `tinyint(1)` 的同义词） |
| `int unsigned` | `Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")`，见偏差 1 |
| `decimal(p,s)` | `Numeric(p, s)`（MySQL 里 `NUMERIC` 与 `DECIMAL` 同义） |
| `datetime(3)` | `DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")`，见偏差 2 |
| `json` | `JSON()`；标注按语义收窄（`JsonValue` 是 JSON 值域的唯一别名） |

**偏差 1：`Integer(unsigned=True)` 在 SQLAlchemy 2.0.54 上不可用。** 工单要求写
`Integer(unsigned=True)`，但通用 `Integer` 在本版本**不接受任何参数**，实测直接
`TypeError: Integer() takes no arguments` —— `unsigned` 只由 MySQL 方言的 `_IntegerType`
处理。故改用 `with_variant`：主类型仍是通用 `Integer()`，MySQL 方言下渲染
`INTEGER UNSIGNED`（与 DDL 一致），其他方言渲染 `INTEGER`。**没有静默降级成有符号
`Integer()`** —— 那会让 Task 3.5 的 autogenerate 每次都想把列改回有符号。
渲染结果由 `tests/unit/test_models.py` 编译 MySQL DDL 守住。

**偏差 2：通用 `DateTime()` 不带 fsp，套不住 DDL 的 `datetime(3)`。** 工单要求
`DateTime()` 且 MUST NOT `timezone=True`（本模块遵守后一条：MySQL `DATETIME` 不存时区，
UTC 是应用层约定）。但 `DateTime()` 渲染出的 `DATETIME` 是 **fsp=0**，会丢掉 DDL 明确
要求的毫秒精度（er.md §6 通用约定「时间 `datetime(3)` 毫秒精度」）。故同样用 `with_variant`
在 MySQL 侧补 `DATETIME(3)`；主类型仍是 `DateTime()`、仍无时区。

**服务端默认值 MUST 显式写出**：DDL 的 `DEFAULT CURRENT_TIMESTAMP(3)` / `DEFAULT 0` /
`DEFAULT 'PROCESSING'` 一律用 `server_default=text(...)` 表达（字符串默认值带内层单引号），
否则 Task 3.5 的 autogenerate 会认为库里多了一个默认值、每次都想生成 `alter_column`，
迁移不再收敛。`NULL DEFAULT NULL` 的列**不写** `server_default`（MySQL 可空列的隐含默认
就是 NULL）。`default=`（Python 侧）本模块一律不写，取值时刻由业务决定。

**其他通用约定**：枚举值集合与顺序、主键、可空性、索引名与列序、外键名 MUST 与 DDL 逐字
一致；索引与唯一键一律**显式命名**（MUST NOT 让 SQLAlchemy 自动生成 `ix_xxx`，
Task 3.6 要拿名字逐项比对）；主键只用 `primary_key=True` 表达，MUST NOT 在
`__table_args__` 里再写一遍 `PrimaryKeyConstraint`。分片表的物理外键名形如
`fk_ocr_correction_task_{month}`（MySQL 的约束名在 schema 内唯一，必须带月份后缀），
本模块只写**逻辑名** `fk_ocr_correction_task`，月份后缀同样由建表流程现算。
列/表 COMMENT 未镜像（工单未要求，见 Task 3.2 报告的遗留问题一节）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSON 列的值域别名（全模块唯一一处）：对象型列按语义收窄到 `dict[str, Any]`，
# 数组型列收窄到 `list[Any]`，故各列的 `Mapped[...]` MUST NOT 退化成 `Mapped[Any]`
# 或 `object` —— 那会让 Task 3.7 的读写代码失去类型检查。
type JsonValue = dict[str, Any] | list[Any]


def _datetime_ms() -> DateTime:
    """`datetime(3)` 的列类型：通用 `DateTime()` + MySQL 侧毫秒精度（见模块偏差 2）。"""
    return DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


def _unsigned_int() -> Integer:
    """`int unsigned` 的列类型：通用 `Integer()` + MySQL 侧 UNSIGNED（见模块偏差 1）。"""
    return Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class Base(DeclarativeBase):
    """声明式基类。元数据里的表名是**逻辑名**，物理分片名由 repository/sharding.py 现算。"""


class AiTask(Base):
    """`ai_task` 统一异步 AI 任务（**按月分表**）。DDL：`10_ai_task.template.sql`。"""

    __tablename__ = "ai_task"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    idem_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(
        Enum(
            "OCR",
            "VISION_REVIEW",
            "KITCHEN_ANOMALY",
            "RISK_PREDICT",
            name="ai_task_type",
            native_enum=True,
            validate_strings=True,
            length=15,  # 最长值 KITCHEN_ANOMALY = 15 个字符
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "PROCESSING",
            "SUCCEEDED",
            "FAILED",
            "MANUAL_REVIEW",
            name="ai_task_status",
            native_enum=True,
            validate_strings=True,
            length=13,  # 最长值 MANUAL_REVIEW = 13 个字符
        ),
        nullable=False,
        server_default=text("'PROCESSING'"),
    )
    progress: Mapped[int] = mapped_column(
        _unsigned_int(),
        nullable=False,
        server_default=text("0"),
    )
    error_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    is_eval_sample: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        _datetime_ms(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(_datetime_ms(), nullable=True)

    __table_args__ = (
        Index("idx_account_created", "account_id", "created_at"),
        UniqueConstraint("account_id", "idem_key", name="uk_idem"),
        Index("idx_status_created", "status", "created_at"),
        Index("idx_eval", "is_eval_sample", "type"),
    )


class OcrResult(Base):
    """`ocr_result` 证照 OCR 结果（**随任务同月分表**）。DDL：`11_ocr_result.template.sql`。"""

    __tablename__ = "ocr_result"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    fields_json: Mapped[list[Any]] = mapped_column(JSON(), nullable=False)
    validity: Mapped[str] = mapped_column(
        Enum(
            "VALID",
            "EXPIRING",
            "EXPIRED",
            "UNKNOWN",
            name="ocr_result_validity",
            native_enum=True,
            validate_strings=True,
            length=8,  # 最长值 EXPIRING = 8 个字符
        ),
        nullable=False,
    )
    category_match: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("0"),
    )
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    suggestions_json: Mapped[list[Any] | None] = mapped_column(JSON(), nullable=True)
    needs_manual_review: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("0"),
    )

    # DDL 里本表只有 PRIMARY KEY(task_id)，无其他索引与外键（同月分片的一致性靠路由保证）。
    __table_args__ = ()


class OcrCorrection(Base):
    """`ocr_correction` 人工核验纠错回流（**同月分表**）。DDL：`12_ocr_correction.template.sql`。"""

    __tablename__ = "ocr_correction"

    correction_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(
            "ocr_result.task_id",
            # 物理约束名是 fk_ocr_correction_task_{month}（同月兄弟表），月份后缀由建表流程现算。
            name="fk_ocr_correction_task",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    human_value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    corrected_by: Mapped[str] = mapped_column(String(64), nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(
        _datetime_ms(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )

    __table_args__ = (
        Index("idx_task", "task_id"),
        Index("idx_field_corrected", "field_name", "corrected_at"),
    )


class VisionReview(Base):
    """`vision_review` 视觉合规审核记录（不分片）。DDL：`20_vision_review.sql`。"""

    __tablename__ = "vision_review"

    review_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    biz_type: Mapped[str] = mapped_column(
        Enum(
            "RAW_MATERIAL",
            "CERTIFICATE",
            "INSPECTION_SAMPLE",
            "KITCHEN",
            name="vision_review_biz_type",
            native_enum=True,
            validate_strings=True,
            length=17,  # 最长值 INSPECTION_SAMPLE = 17 个字符
        ),
        nullable=False,
    )
    merchant_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_keys_json: Mapped[list[Any]] = mapped_column(JSON(), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "AI_PROCESSING",
            "PENDING",
            "CONFIRMED",
            "REFERRED",
            "REJECTED",
            "ARCHIVED",
            name="vision_review_status",
            native_enum=True,
            validate_strings=True,
            length=13,  # 最长值 AI_PROCESSING = 13 个字符
        ),
        nullable=False,
        server_default=text("'AI_PROCESSING'"),
    )
    confidence_level: Mapped[str | None] = mapped_column(
        Enum(
            "HIGH",
            "MEDIUM",
            "LOW",
            name="vision_review_confidence_level",
            native_enum=True,
            validate_strings=True,
            length=6,  # 最长值 MEDIUM = 6 个字符
        ),
        nullable=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    markers_count: Mapped[int] = mapped_column(
        _unsigned_int(),
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        _datetime_ms(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(_datetime_ms(), nullable=True)

    __table_args__ = (
        Index("idx_merchant_created", "merchant_id", "created_at"),
        Index("idx_status_created", "status", "created_at"),
        Index("idx_task", "task_id"),
    )


class VisionMarker(Base):
    """`vision_marker` 疑似问题标记（不分片）。

    物理外键 -> vision_review；DDL 见 `21_vision_marker.sql`。
    """

    __tablename__ = "vision_marker"

    marker_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(
            "vision_review.review_id",
            name="fk_vision_marker_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(
        Enum(
            "HIGH",
            "MEDIUM",
            "LOW",
            name="vision_marker_level",
            native_enum=True,
            validate_strings=True,
            length=6,  # 最长值 MEDIUM = 6 个字符
        ),
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    suggestion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("idx_review", "review_id"),)


class ReviewVerdict(Base):
    """`review_verdict` 人工复核结论留痕（不分片，与 vision_review 1:1）。

    DDL 见 `22_review_verdict.sql`。
    """

    __tablename__ = "review_verdict"

    review_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(
            "vision_review.review_id",
            name="fk_review_verdict_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        primary_key=True,
    )
    action: Mapped[str] = mapped_column(
        Enum(
            "CONFIRM",
            "REFER",
            "REJECT",
            "ARCHIVE",
            name="review_verdict_action",
            native_enum=True,
            validate_strings=True,
            length=7,  # 最长值 CONFIRM / ARCHIVE = 7 个字符
        ),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    # 复核时间无 server_default：业务写入时刻决定，库兜默认值会把「忘记写时间」变成静默假数据。
    reviewed_at: Mapped[datetime] = mapped_column(_datetime_ms(), nullable=False)
    authority_written: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("0"),
    )
    authority_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    authority_written_at: Mapped[datetime | None] = mapped_column(_datetime_ms(), nullable=True)

    __table_args__ = (Index("idx_reviewed_at", "reviewed_at"),)


class KitchenAnomaly(Base):
    """`kitchen_anomaly` 后厨直播异常标记（不分片）。DDL：`23_kitchen_anomaly.sql`。"""

    __tablename__ = "kitchen_anomaly"

    anomaly_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 可空列上的物理外键：NULL 不受约束（未进复核流的标记留 NULL），非 NULL 必须是真实记录。
    review_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(
            "vision_review.review_id",
            name="fk_kitchen_anomaly_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )
    merchant_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stream_id: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    confidence_level: Mapped[str | None] = mapped_column(
        Enum(
            "HIGH",
            "MEDIUM",
            "LOW",
            name="kitchen_anomaly_confidence_level",
            native_enum=True,
            validate_strings=True,
            length=6,  # 最长值 MEDIUM = 6 个字符
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "PENDING",
            "CONFIRMED",
            "REJECTED",
            "ARCHIVED",
            name="kitchen_anomaly_status",
            native_enum=True,
            validate_strings=True,
            length=9,  # 最长值 CONFIRMED = 9 个字符
        ),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    # 识别时间无 server_default：由识别流程写入。
    detected_at: Mapped[datetime] = mapped_column(_datetime_ms(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(_datetime_ms(), nullable=True)

    __table_args__ = (
        Index("idx_stream_detected", "stream_id", "detected_at"),
        Index("idx_status", "status", "detected_at"),
        Index("idx_review", "review_id"),
    )


class RiskPredictResult(Base):
    """`risk_predict_result` 风险商户预测结果（不分片）。DDL：`24_risk_predict_result.sql`。"""

    __tablename__ = "risk_predict_result"

    # merchant_id 作主键 = 每商户最新一次覆盖，历史走审计；它是 CRED 域 ID 的只读引用。
    merchant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    merchant_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_level: Mapped[str] = mapped_column(
        Enum(
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
            name="risk_predict_result_risk_level",
            native_enum=True,
            validate_strings=True,
            length=8,  # 最长值 CRITICAL = 8 个字符
        ),
        nullable=False,
    )
    factors_json: Mapped[list[Any]] = mapped_column(JSON(), nullable=False)
    suggestions_json: Mapped[list[Any] | None] = mapped_column(JSON(), nullable=True)
    # 预测时间无 server_default：由预测流程写入。
    predicted_at: Mapped[datetime] = mapped_column(_datetime_ms(), nullable=False)

    __table_args__ = (Index("idx_predicted", "predicted_at"),)


class VisionQaLog(Base):
    """`vision_qa_log` 图像问答留痕（不分片）。DDL：`25_vision_qa_log.sql`。"""

    __tablename__ = "vision_qa_log"

    qa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_key: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(String(200), nullable=False)
    answer: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    disclaimer: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _datetime_ms(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
    )

    __table_args__ = (Index("idx_account_created", "account_id", "created_at"),)


# 「模型类 -> 逻辑表名」的唯一出处：分片表用它取逻辑名，物理名由 Task 3.3 现算。
# 键集合与 Base.metadata.tables 的键集合恒等（tests/unit/test_models.py 守着）。
LOGICAL_TABLE_NAMES: dict[type[Base], str] = {
    AiTask: "ai_task",
    OcrResult: "ocr_result",
    OcrCorrection: "ocr_correction",
    VisionReview: "vision_review",
    VisionMarker: "vision_marker",
    ReviewVerdict: "review_verdict",
    KitchenAnomaly: "kitchen_anomaly",
    RiskPredictResult: "risk_predict_result",
    VisionQaLog: "vision_qa_log",
}
