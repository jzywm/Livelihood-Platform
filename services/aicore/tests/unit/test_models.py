"""Task 3.2 用例：SQLAlchemy 模型与 DDL 的逐列一致性（纯元数据断言，**无需数据库**）。

**期望值从哪来**：一律**照 `deploy/sql/ddl/*.sql` 逐列写死**（DDL 是列定义的唯一权威，
见 `src/aicore/repository/models.py` 模块 docstring）。本文件 MUST NOT 现场解析 DDL 取期望值
——那样「模型与 DDL 一起改错」也会全绿，用例就失去了判别力；也 MUST NOT 用正则从 DDL
推导期望，每个列名、可空性、枚举值、索引名都在这里**独立抄写一遍**，模型漂移才有红灯。
列顺序也断言：DDL 正文的列序即期望元组顺序。

覆盖：逻辑表名 / 主键 / 列集合与顺序 / 逐列可空性 / 枚举值集合与顺序 / 显式 length /
索引与唯一键名及列序 / 4 个物理外键 / server_default 存在性与反向断言 /
元数据里没有物理分片名 / MySQL 方言渲染（`INTEGER UNSIGNED`、`DATETIME(3)` 等）。
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import DateTime, Table, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from aicore.repository.models import (
    LOGICAL_TABLE_NAMES,
    AiTask,
    Base,
    KitchenAnomaly,
    OcrCorrection,
    OcrResult,
    ReviewVerdict,
    RiskPredictResult,
    VisionMarker,
    VisionQaLog,
    VisionReview,
)

# ---------------------------------------------------------------------------
# 9 个模型 -> 逻辑表名（照 DDL 文件名逐字抄写，与 models.LOGICAL_TABLE_NAMES 相互独立）
# ---------------------------------------------------------------------------
MODEL_TABLE_NAMES: dict[type[Base], str] = {
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

MODELS: tuple[type[Base], ...] = tuple(MODEL_TABLE_NAMES)
MODEL_IDS: list[str] = [MODEL_TABLE_NAMES[model] for model in MODELS]

# ---------------------------------------------------------------------------
# 主键（照 DDL 的 PRIMARY KEY 写死；分片表的物理名另算，逻辑名见上）
# ---------------------------------------------------------------------------
EXPECTED_PRIMARY_KEY: dict[type[Base], str] = {
    AiTask: "task_id",
    OcrResult: "task_id",
    OcrCorrection: "correction_id",
    VisionReview: "review_id",
    VisionMarker: "marker_id",
    ReviewVerdict: "review_id",
    KitchenAnomaly: "anomaly_id",
    RiskPredictResult: "merchant_id",
    VisionQaLog: "qa_id",
}

# ---------------------------------------------------------------------------
# 逐列清单（列名与顺序照 DDL 正文写死：多一列、少一列、换序都会红）
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS: dict[type[Base], tuple[str, ...]] = {
    # 10_ai_task.template.sql
    AiTask: (
        "task_id",
        "account_id",
        "idem_key",
        "type",
        "status",
        "progress",
        "error_code",
        "model_meta",
        "is_eval_sample",
        "created_at",
        "finished_at",
    ),
    # 11_ocr_result.template.sql
    OcrResult: (
        "task_id",
        "fields_json",
        "validity",
        "category_match",
        "summary",
        "suggestions_json",
        "needs_manual_review",
    ),
    # 12_ocr_correction.template.sql
    OcrCorrection: (
        "correction_id",
        "task_id",
        "field_name",
        "ai_value",
        "human_value",
        "confidence",
        "corrected_by",
        "corrected_at",
    ),
    # 20_vision_review.sql
    VisionReview: (
        "review_id",
        "task_id",
        "biz_type",
        "merchant_id",
        "merchant_name",
        "batch_id",
        "image_keys_json",
        "status",
        "confidence_level",
        "confidence",
        "markers_count",
        "created_at",
        "reviewed_at",
    ),
    # 21_vision_marker.sql
    VisionMarker: (
        "marker_id",
        "review_id",
        "label",
        "level",
        "confidence",
        "bbox_json",
        "suggestion",
    ),
    # 22_review_verdict.sql
    ReviewVerdict: (
        "review_id",
        "action",
        "comment",
        "reviewed_by",
        "reviewed_at",
        "authority_written",
        "authority_event_id",
        "authority_written_at",
    ),
    # 23_kitchen_anomaly.sql
    KitchenAnomaly: (
        "anomaly_id",
        "review_id",
        "merchant_id",
        "merchant_name",
        "stream_id",
        "anomaly_type",
        "confidence",
        "confidence_level",
        "status",
        "detected_at",
        "reviewed_at",
    ),
    # 24_risk_predict_result.sql
    RiskPredictResult: (
        "merchant_id",
        "merchant_name",
        "risk_score",
        "risk_level",
        "factors_json",
        "suggestions_json",
        "predicted_at",
    ),
    # 25_vision_qa_log.sql
    VisionQaLog: (
        "qa_id",
        "account_id",
        "image_key",
        "question",
        "answer",
        "confidence",
        "disclaimer",
        "created_at",
    ),
}

# ---------------------------------------------------------------------------
# 逐列可空性（照 DDL 的 NOT NULL / NULL 写死；这是本文件的核心价值）
# ---------------------------------------------------------------------------
EXPECTED_NULLABLE: dict[type[Base], dict[str, bool]] = {
    AiTask: {
        "task_id": False,
        "account_id": False,
        "idem_key": True,
        "type": False,
        "status": False,
        "progress": False,
        "error_code": True,
        "model_meta": True,
        "is_eval_sample": False,
        "created_at": False,
        "finished_at": True,
    },
    OcrResult: {
        "task_id": False,
        "fields_json": False,
        "validity": False,
        "category_match": False,
        "summary": False,
        "suggestions_json": True,
        "needs_manual_review": False,
    },
    OcrCorrection: {
        "correction_id": False,
        "task_id": False,
        "field_name": False,
        "ai_value": True,
        "human_value": False,
        "confidence": True,
        "corrected_by": False,
        "corrected_at": False,
    },
    VisionReview: {
        "review_id": False,
        "task_id": True,
        "biz_type": False,
        "merchant_id": True,
        "merchant_name": True,
        "batch_id": True,
        "image_keys_json": False,
        "status": False,
        "confidence_level": True,
        "confidence": True,
        "markers_count": False,
        "created_at": False,
        "reviewed_at": True,
    },
    VisionMarker: {
        "marker_id": False,
        "review_id": False,
        "label": False,
        "level": False,
        "confidence": False,
        "bbox_json": True,
        "suggestion": True,
    },
    ReviewVerdict: {
        "review_id": False,
        "action": False,
        "comment": True,
        "reviewed_by": False,
        "reviewed_at": False,
        "authority_written": False,
        "authority_event_id": True,
        "authority_written_at": True,
    },
    KitchenAnomaly: {
        "anomaly_id": False,
        "review_id": True,
        "merchant_id": True,
        "merchant_name": True,
        "stream_id": False,
        "anomaly_type": False,
        "confidence": False,
        "confidence_level": True,
        "status": False,
        "detected_at": False,
        "reviewed_at": True,
    },
    RiskPredictResult: {
        "merchant_id": False,
        "merchant_name": True,
        "risk_score": False,
        "risk_level": False,
        "factors_json": False,
        "suggestions_json": True,
        "predicted_at": False,
    },
    VisionQaLog: {
        "qa_id": False,
        "account_id": True,
        "image_key": False,
        "question": False,
        "answer": False,
        "confidence": True,
        "disclaimer": False,
        "created_at": False,
    },
}

# ---------------------------------------------------------------------------
# 枚举列（照 DDL 的 enum(...) 写死：值的集合**与顺序**都要一致）
# ---------------------------------------------------------------------------
EXPECTED_ENUMS: dict[tuple[type[Base], str], tuple[str, ...]] = {
    (AiTask, "type"): ("OCR", "VISION_REVIEW", "KITCHEN_ANOMALY", "RISK_PREDICT"),
    (AiTask, "status"): ("PROCESSING", "SUCCEEDED", "FAILED", "MANUAL_REVIEW"),
    (OcrResult, "validity"): ("VALID", "EXPIRING", "EXPIRED", "UNKNOWN"),
    (VisionReview, "biz_type"): (
        "RAW_MATERIAL",
        "CERTIFICATE",
        "INSPECTION_SAMPLE",
        "KITCHEN",
    ),
    (VisionReview, "status"): (
        "AI_PROCESSING",
        "PENDING",
        "CONFIRMED",
        "REFERRED",
        "REJECTED",
        "ARCHIVED",
    ),
    (VisionReview, "confidence_level"): ("HIGH", "MEDIUM", "LOW"),
    (VisionMarker, "level"): ("HIGH", "MEDIUM", "LOW"),
    (ReviewVerdict, "action"): ("CONFIRM", "REFER", "REJECT", "ARCHIVE"),
    (KitchenAnomaly, "confidence_level"): ("HIGH", "MEDIUM", "LOW"),
    (KitchenAnomaly, "status"): ("PENDING", "CONFIRMED", "REJECTED", "ARCHIVED"),
    (RiskPredictResult, "risk_level"): ("LOW", "MEDIUM", "HIGH", "CRITICAL"),
}

ENUM_CASES: list[tuple[type[Base], str, tuple[str, ...]]] = [
    (model, column, values) for (model, column), values in EXPECTED_ENUMS.items()
]
ENUM_IDS: list[str] = [
    f"{model.__tablename__}.{column}" for model, column, _ in ENUM_CASES
]

# ---------------------------------------------------------------------------
# 非主键索引（索引名 MUST 逐字等于 DDL：SQLAlchemy 自动生成的 ix_xxx 会在这里变红）
# ---------------------------------------------------------------------------
EXPECTED_INDEXES: dict[type[Base], dict[str, tuple[str, ...]]] = {
    AiTask: {
        "idx_account_created": ("account_id", "created_at"),
        "idx_status_created": ("status", "created_at"),
        "idx_eval": ("is_eval_sample", "type"),
    },
    # ocr_result 只有 PRIMARY KEY(task_id)，无附加索引
    OcrResult: {},
    OcrCorrection: {
        "idx_task": ("task_id",),
        "idx_field_corrected": ("field_name", "corrected_at"),
    },
    VisionReview: {
        "idx_merchant_created": ("merchant_id", "created_at"),
        "idx_status_created": ("status", "created_at"),
        "idx_task": ("task_id",),
    },
    VisionMarker: {"idx_review": ("review_id",)},
    ReviewVerdict: {"idx_reviewed_at": ("reviewed_at",)},
    KitchenAnomaly: {
        "idx_stream_detected": ("stream_id", "detected_at"),
        "idx_status": ("status", "detected_at"),
        "idx_review": ("review_id",),
    },
    RiskPredictResult: {"idx_predicted": ("predicted_at",)},
    VisionQaLog: {"idx_account_created": ("account_id", "created_at")},
}

# 唯一约束（只有 ai_task 的 uk_idem；其余表为空字典 —— 主键不算唯一约束）
EXPECTED_UNIQUES: dict[type[Base], dict[str, tuple[str, ...]]] = {
    AiTask: {"uk_idem": ("account_id", "idem_key")},
    OcrResult: {},
    OcrCorrection: {},
    VisionReview: {},
    VisionMarker: {},
    ReviewVerdict: {},
    KitchenAnomaly: {},
    RiskPredictResult: {},
    VisionQaLog: {},
}

# ---------------------------------------------------------------------------
# 物理外键（4 条）：模型侧写**逻辑**约束名，物理名带 {month} 后缀由建表流程现算
# ---------------------------------------------------------------------------
EXPECTED_FOREIGN_KEYS: list[tuple[type[Base], str, str, str, str, str]] = [
    (
        OcrCorrection,
        "task_id",
        "fk_ocr_correction_task",
        "ocr_result.task_id",
        "RESTRICT",
        "RESTRICT",
    ),
    (
        VisionMarker,
        "review_id",
        "fk_vision_marker_review",
        "vision_review.review_id",
        "RESTRICT",
        "RESTRICT",
    ),
    (
        ReviewVerdict,
        "review_id",
        "fk_review_verdict_review",
        "vision_review.review_id",
        "RESTRICT",
        "RESTRICT",
    ),
    (
        KitchenAnomaly,
        "review_id",
        "fk_kitchen_anomaly_review",
        "vision_review.review_id",
        "RESTRICT",
        "RESTRICT",
    ),
]
FK_IDS: list[str] = [
    f"{model.__tablename__}.{column}" for model, column, *_ in EXPECTED_FOREIGN_KEYS
]

# ---------------------------------------------------------------------------
# server_default（照 DDL 的 DEFAULT 写死；字符串默认值带内层单引号）
# ---------------------------------------------------------------------------
EXPECTED_SERVER_DEFAULTS: dict[type[Base], dict[str, str]] = {
    AiTask: {
        "status": "'PROCESSING'",
        "progress": "0",
        "is_eval_sample": "0",
        "created_at": "CURRENT_TIMESTAMP(3)",
    },
    OcrResult: {"category_match": "0", "needs_manual_review": "0"},
    OcrCorrection: {"corrected_at": "CURRENT_TIMESTAMP(3)"},
    VisionReview: {
        "status": "'AI_PROCESSING'",
        "markers_count": "0",
        "created_at": "CURRENT_TIMESTAMP(3)",
    },
    VisionMarker: {},
    ReviewVerdict: {"authority_written": "0"},
    KitchenAnomaly: {"status": "'PENDING'"},
    RiskPredictResult: {},
    VisionQaLog: {"created_at": "CURRENT_TIMESTAMP(3)"},
}

DEFAULT_CASES: list[tuple[type[Base], str, str]] = [
    (model, column, expected)
    for model, columns in EXPECTED_SERVER_DEFAULTS.items()
    for column, expected in columns.items()
]
DEFAULT_IDS: list[str] = [
    f"{model.__tablename__}.{column}" for model, column, _ in DEFAULT_CASES
]

# 6 位月份后缀：分片表物理名（ai_task_202601）的判据，元数据里 MUST NOT 出现
PHYSICAL_SUFFIX_RE = re.compile(r"_\d{6}$")


def _mysql_ddl(table: Table) -> str:
    """把模型的表渲染成 MySQL 方言的 CREATE TABLE 文本（纯离线，不连库）。"""
    return str(CreateTable(table).compile(dialect=mysql.dialect()))


def _server_default_text(model: type[Base], column: str) -> str | None:
    """取某列 server_default 的 SQL 文本（无默认值时为 None）。"""
    default = model.__table__.columns[column].server_default
    return None if default is None else str(default.arg)


# ---------------------------------------------------------------------------
# 1. 9 个模型 <-> 逻辑表名
# ---------------------------------------------------------------------------
def test_logical_table_names_has_exactly_nine_entries() -> None:
    """LOGICAL_TABLE_NAMES 恰 9 项：键集合等于 9 个模型类，值等于预期逻辑名。"""
    assert len(LOGICAL_TABLE_NAMES) == 9
    assert set(LOGICAL_TABLE_NAMES) == set(MODEL_TABLE_NAMES)
    assert LOGICAL_TABLE_NAMES == MODEL_TABLE_NAMES


@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_tablename_equals_logical_name(model: type[Base]) -> None:
    """每个模型的 __tablename__ 等于 LOGICAL_TABLE_NAMES 里登记的逻辑名。"""
    assert model.__tablename__ == LOGICAL_TABLE_NAMES[model] == MODEL_TABLE_NAMES[model]


# ---------------------------------------------------------------------------
# 2. 主键
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_primary_key_matches_ddl(model: type[Base]) -> None:
    """主键列名与 DDL 一致，且**只有一列**（复合主键/重复 PK 会在这里变红）。"""
    primary_key = model.__table__.primary_key
    assert tuple(column.name for column in primary_key.columns) == (
        EXPECTED_PRIMARY_KEY[model],
    )


# ---------------------------------------------------------------------------
# 3. 列集合与顺序 + 逐列可空性
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_column_names_and_order_match_ddl(model: type[Base]) -> None:
    """列名与顺序与 DDL 正文一致：多一列、少一列、换序都会红。"""
    assert tuple(model.__table__.columns.keys()) == EXPECTED_COLUMNS[model]
    # 可空性字典的键集合必须与列清单相同：防止有人加列却忘了写期望值（漏项即静默放过）
    assert set(EXPECTED_NULLABLE[model]) == set(EXPECTED_COLUMNS[model])


NULLABLE_CASES: list[tuple[type[Base], str, bool]] = [
    (model, column, nullable)
    for model, columns in EXPECTED_NULLABLE.items()
    for column, nullable in columns.items()
]
NULLABLE_IDS: list[str] = [
    f"{model.__tablename__}.{column}" for model, column, _ in NULLABLE_CASES
]


@pytest.mark.parametrize(
    ("model", "column", "expected"), NULLABLE_CASES, ids=NULLABLE_IDS
)
def test_column_nullable_matches_ddl(
    model: type[Base], column: str, expected: bool
) -> None:
    """逐列断言 nullable（期望值照 DDL 写）：模型与 DDL 走偏会被抓住。"""
    actual = model.__table__.columns[column].nullable
    assert actual is expected, (
        f"{model.__tablename__}.{column} 的 nullable 应为 {expected}，实际 {actual}"
    )


# ---------------------------------------------------------------------------
# 4. 枚举值集合（顺序也要一致）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("model", "column", "values"), ENUM_CASES, ids=ENUM_IDS)
def test_enum_values_match_ddl(
    model: type[Base], column: str, values: tuple[str, ...]
) -> None:
    """枚举列的取值与顺序与 DDL 一致，且 native_enum / validate_strings 均开启。"""
    column_type = model.__table__.columns[column].type
    assert tuple(column_type.enums) == values
    assert column_type.native_enum is True
    assert column_type.validate_strings is True


@pytest.mark.parametrize(("model", "column", "values"), ENUM_CASES, ids=ENUM_IDS)
def test_enum_length_is_longest_value(
    model: type[Base], column: str, values: tuple[str, ...]
) -> None:
    """每列显式写的 length 必须等于最长枚举值长度（写小了会被静默截断）。"""
    column_type = model.__table__.columns[column].type
    assert column_type.length == max(len(value) for value in values)


# ---------------------------------------------------------------------------
# 5. 索引与唯一键（名字逐字一致，列序也要一致）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_indexes_match_ddl(model: type[Base]) -> None:
    """非主键索引名与列序逐项等于 DDL（自动生成的 ix_xxx 会在这里变红）。"""
    actual = {
        index.name: tuple(column.name for column in index.columns)
        for index in model.__table__.indexes
    }
    assert actual == EXPECTED_INDEXES[model]


@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_unique_constraints_match_ddl(model: type[Base]) -> None:
    """唯一约束名与列序逐项等于 DDL（ai_task 的 uk_idem；其余表无）。"""
    actual = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert actual == EXPECTED_UNIQUES[model]


# ---------------------------------------------------------------------------
# 6. 物理外键
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("model", "column", "name", "target", "ondelete", "onupdate"),
    EXPECTED_FOREIGN_KEYS,
    ids=FK_IDS,
)
def test_foreign_keys_match_ddl(
    model: type[Base],
    column: str,
    name: str,
    target: str,
    ondelete: str,
    onupdate: str,
) -> None:
    """4 条物理外键的目标表/列、约束名与 RESTRICT 规则逐项一致。"""
    table = model.__table__
    foreign_keys = list(table.columns[column].foreign_keys)
    assert len(foreign_keys) == 1, f"{table.name}.{column} 应恰有 1 个外键"
    foreign_key = foreign_keys[0]
    assert foreign_key.target_fullname == target
    assert foreign_key.constraint.name == name
    assert foreign_key.ondelete == ondelete
    assert foreign_key.onupdate == onupdate


def test_metadata_has_exactly_four_foreign_keys() -> None:
    """元数据里的外键总数恰 4 条（多一条少一条都要有人解释）。"""
    actual = {
        (table.name, foreign_key.parent.name, foreign_key.constraint.name)
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
    }
    assert actual == {
        (model.__tablename__, column, name)
        for model, column, name, *_ in EXPECTED_FOREIGN_KEYS
    }


def test_foreign_key_names_carry_no_month_suffix() -> None:
    """分片表外键的物理名带 {month}，模型侧 MUST 只写逻辑名（月份后缀由建表流程现算）。"""
    names = [
        foreign_key.constraint.name
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
    ]
    offenders = [name for name in names if name and PHYSICAL_SUFFIX_RE.search(name)]
    assert not offenders, f"外键名写死了物理月份后缀：{offenders}"


# ---------------------------------------------------------------------------
# 7. server_default 存在性 + 反向断言
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("model", "column", "expected"), DEFAULT_CASES, ids=DEFAULT_IDS
)
def test_server_default_matches_ddl(
    model: type[Base], column: str, expected: str
) -> None:
    """带 DDL 默认值的列必须显式写出 server_default，且 SQL 文本逐字一致。"""
    actual = _server_default_text(model, column)
    assert actual == expected, (
        f"{model.__tablename__}.{column} 的 server_default 应为 {expected!r}，"
        f"实际 {actual!r}"
    )


@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_columns_without_ddl_default_have_no_server_default(model: type[Base]) -> None:
    """反向断言：DDL 里没有 DEFAULT 的列，模型侧 MUST NOT 顺手加 server_default。"""
    actual = {
        column.name
        for column in model.__table__.columns
        if column.server_default is not None
    }
    assert actual == set(EXPECTED_SERVER_DEFAULTS[model])


@pytest.mark.parametrize(
    ("model", "column"),
    [
        (VisionReview, "reviewed_at"),
        (KitchenAnomaly, "detected_at"),
        (KitchenAnomaly, "reviewed_at"),
        (RiskPredictResult, "predicted_at"),
    ],
    ids=[
        "vision_review.reviewed_at",
        "kitchen_anomaly.detected_at",
        "kitchen_anomaly.reviewed_at",
        "risk_predict_result.predicted_at",
    ],
)
def test_business_time_columns_have_no_server_default(
    model: type[Base], column: str
) -> None:
    """业务写入时刻决定的列（复核/识别/预测时间）MUST NOT 有 server_default。

    库兜默认值会把「忘记写时间」变成静默假数据，故这四条要单独反向断言。
    """
    assert _server_default_text(model, column) is None


# ---------------------------------------------------------------------------
# 8. 元数据里没有物理分片名
# ---------------------------------------------------------------------------
def test_metadata_table_names_are_logical_only() -> None:
    """Base.metadata.tables 的键集合恰是 9 个逻辑名，不含任何物理分片名。"""
    tables = Base.metadata.tables
    assert len(tables) == 9
    assert set(tables) == set(MODEL_TABLE_NAMES.values())
    offenders = [name for name in tables if PHYSICAL_SUFFIX_RE.search(name)]
    assert not offenders, f"元数据里出现物理分片表名：{offenders}"


def test_no_model_tablename_contains_year_month() -> None:
    """任何模型的 __tablename__ MUST NOT 含 YYYYMM（分片靠路由，不靠模型）。"""
    for model in MODELS:
        assert PHYSICAL_SUFFIX_RE.search(model.__tablename__) is None
        assert not re.search(r"\d{6}", model.__tablename__)


# ---------------------------------------------------------------------------
# 9. MySQL 方言渲染：with_variant 的偏差（见 models.py 模块 docstring）必须真的生效
# ---------------------------------------------------------------------------
def test_unsigned_columns_render_integer_unsigned() -> None:
    """`int unsigned` 的两列在 MySQL 下渲染成 INTEGER UNSIGNED（偏差 1 的证据）。

    工单要求的 `Integer(unsigned=True)` 在 SQLAlchemy 2.0.54 上抛
    `TypeError: Integer() takes no arguments`，故改用 with_variant；本用例守住
    「没有静默降级成有符号 INTEGER」——那会让 Task 3.5 的 autogenerate 反复改列。
    """
    assert "progress INTEGER UNSIGNED NOT NULL DEFAULT 0" in _mysql_ddl(AiTask.__table__)
    assert "markers_count INTEGER UNSIGNED NOT NULL DEFAULT 0" in _mysql_ddl(
        VisionReview.__table__
    )


def test_datetime_columns_render_millisecond_precision() -> None:
    """`datetime(3)` 在 MySQL 下渲染成 DATETIME(3)，且无时区（偏差 2 的证据）。"""
    ai_task_ddl = _mysql_ddl(AiTask.__table__)
    assert "created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)" in ai_task_ddl
    assert "finished_at DATETIME(3)" in ai_task_ddl
    # 无 server_default 的列不得渲染出 DEFAULT（reviewed_at 在 review_verdict 里带 FK 场景）
    vision_review_ddl = _mysql_ddl(VisionReview.__table__)
    assert "reviewed_at DATETIME(3)" in vision_review_ddl
    assert "reviewed_at DATETIME(3) DEFAULT" not in vision_review_ddl


@pytest.mark.parametrize("model", MODELS, ids=MODEL_IDS)
def test_datetime_columns_are_not_timezone_aware(model: type[Base]) -> None:
    """MUST NOT timezone=True：MySQL DATETIME 不存时区，UTC 是应用层约定。"""
    for column in model.__table__.columns:
        if isinstance(column.type, DateTime):
            assert column.type.timezone is False, (
                f"{model.__tablename__}.{column.name} 不应带时区"
            )


def test_datetime_column_count_is_not_vacuous() -> None:
    """非空下限：上面那条用例的扫描范围塌成 0 时必须报警，而不是静默全绿。"""
    total = sum(
        1
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime)
    )
    assert total == 11, f"datetime(3) 列应有 11 列，实际扫到 {total} 列"


def test_other_types_render_as_ddl_synonyms() -> None:
    """其余类型的渲染：BOOL = tinyint(1)、NUMERIC = decimal、ENUM 内联、VARCHAR 带长度。"""
    ai_task_ddl = _mysql_ddl(AiTask.__table__)
    assert "is_eval_sample BOOL NOT NULL DEFAULT 0" in ai_task_ddl
    assert "type ENUM('OCR','VISION_REVIEW','KITCHEN_ANOMALY','RISK_PREDICT') NOT NULL" in (
        ai_task_ddl
    )
    assert "task_id VARCHAR(32) NOT NULL" in ai_task_ddl
    assert "risk_score NUMERIC(5, 2) NOT NULL" in _mysql_ddl(
        RiskPredictResult.__table__
    )
    assert "confidence NUMERIC(3, 2) NOT NULL" in _mysql_ddl(VisionMarker.__table__)


def test_foreign_key_renders_restrict_and_logical_target() -> None:
    """外键渲染出 RESTRICT 与逻辑目标表名（物理名 ai_task_YYYYMM 不在这里出现）。"""
    ddl = _mysql_ddl(OcrCorrection.__table__)
    assert (
        "CONSTRAINT fk_ocr_correction_task FOREIGN KEY(task_id) "
        "REFERENCES ocr_result (task_id) ON DELETE RESTRICT ON UPDATE RESTRICT"
    ) in ddl
    assert PHYSICAL_SUFFIX_RE.search(ddl) is None
