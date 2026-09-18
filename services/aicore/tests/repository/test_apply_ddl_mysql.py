"""`scripts/apply_ddl.py` 的真实 MySQL 集成用例（Task 3.1 的 FIX-5）。

**为什么要固化这条路径**：首轮把"在真实 MySQL 上执行 DDL"当成一次性手工操作，
仓库里没有任何可复核产物——"跑没跑过"无法从代码与测试看出来。
本用例把那条路径变成可重复执行、可断言的东西。

**默认不跑**（标记 `integration`）；连不上 MySQL 时**显式 skip 并说明原因**，
MUST NOT 静默通过（静默通过等于让这道门禁在 CI 里永远不生效）。

**清理边界（MUST）**：只 DROP 本用例自己建的 3 张 `_<演练月>` 分片表。
MUST NOT `DROP DATABASE`、MUST NOT 碰 6 张固定名表——那些可能与别的用例或同事的库共用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = SERVICE_ROOT / "scripts" / "apply_ddl.py"

#: 本用例的演练库。
DRILL_DATABASE = "aicore_test"

#: 演练月：**按进程唯一**，而不是固定的 `202613`。
#:
#: 为什么必须按进程变（这是实测踩出来的）：本文件会被**并发执行**——多个 subagent 同时跑测试、
#: 或开发者一边跑测试一边跑别的任务。原先写死一个月份时，两个进程会互相 `DROP` 对手刚建的表，
#: 于是幂等断言读到变化的 `CREATE_TIME` 而失败，现象是：
#:     {'ocr_result_202613': 18:44:46} != {'ocr_result_202613': 18:44:48}
#: 那条失败**不是被测代码的问题，是测试自己不够隔离**（同一月份被两个进程共用）。
#: 用 `os.getpid() % 12 + 1` 取月份、年份固定为 2099（远超真实数据，且 6 位格式合法）：
#: 进程号天然互斥，12 个桶对本机并发度足够；`2099xx` 保证不会与任何真实月份撞车。
#:
#: **月份部分必须落在 01~12**：`apply_ddl.py` 的 CLI 校验已与运行期同口径
#: （Task 3.3 的实测发现：首版 CLI 只查"6 位数字"，于是越界的 `202613` 能建表、
#: 同样的月份在运行期 `ensure_month_tables` 会被拒——两条路径严格度不同）。
#: 本文件原先用的就是 `202613`，已随之改为 `209901`~`209912`。
DRILL_YEAR = "2099"
DRILL_MONTH = f"{DRILL_YEAR}{os.getpid() % 12 + 1:02d}"

SHARDED = ("ai_task", "ocr_result", "ocr_correction")
FIXED = (
    "vision_review",
    "vision_marker",
    "review_verdict",
    "kitchen_anomaly",
    "risk_predict_result",
    "vision_qa_log",
)
EXPECTED_FKS_BASE = {
    "fk_vision_marker_review",
    "fk_review_verdict_review",
    "fk_kitchen_anomaly_review",
}
EXPECTED_INDEXES: dict[str, set[str]] = {
    "ai_task": {"idx_account_created", "uk_idem", "idx_status_created", "idx_eval"},
    "ocr_result": set(),
    "ocr_correction": {"idx_task", "idx_field_corrected"},
    "vision_review": {"idx_merchant_created", "idx_status_created", "idx_task"},
    "vision_marker": {"idx_review"},
    "review_verdict": {"idx_reviewed_at"},
    "kitchen_anomaly": {"idx_stream_detected", "idx_status", "idx_review"},
    "risk_predict_result": {"idx_predicted"},
    "vision_qa_log": {"idx_account_created"},
}


def _engine():
    """连**演练库**的引擎。

    环境变量用 `DSH_IT_MYSQL_*`（DSH integration-test），**既不用** `AICORE_MYSQL_*`
    **也不用** `AICORE_TEST_MYSQL_*`：
      - 前者被 `conftest` 顶层注入成 `test_user` 占位值 → 集成测试读它只会拿到假凭据 → 假 skip；
      - 后者会撞上 `core/config.py` 的 `_UnknownEnvVarSource`（它拒绝任何未声明的 `AICORE_*`
        变量，这是 Task 2.1 的正确防线）→ 每次应用启动都被 `ConfigRejected`。
    两处实测现场都写在 `tests/conftest.py` 的那一节里。

    **口令 MUST NOT 硬编码**：只从 `DSH_IT_MYSQL_PASSWORD` 取（`conftest` 会把它从本机
    已被 gitignore 的 `.env` 里回填）。取不到就留空 → 连通性探测失败 → 用例显式 skip，
    而不是把凭据写进版本库换一次"绿灯"。
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


def _require_mysql():
    """连不上就**显式跳过**（含原因），而不是让用例随机失败或静默通过。"""
    try:
        engine = _engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"需要真实 MySQL（{DRILL_DATABASE}@127.0.0.1:3306）才能验证 DDL 落地："
            f"{type(exc).__name__}: {exc}"
        )
    return engine


def _run_apply(month: str) -> subprocess.CompletedProcess[str]:
    """跑一次 `apply_ddl.py`。

    刻意走**子进程**而不是 import 后调 `main()`：这样验证的是"运维真正会敲的那条命令"，
    连参数解析、退出码、stdout 一起覆盖到。
    """
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            DRILL_DATABASE,
            "--month",
            month,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(SERVICE_ROOT),
        check=False,
    )


def _drop_drill_shards(engine, month: str) -> None:
    """只清理本用例建的分片表（MUST NOT 动固定名表、MUST NOT DROP DATABASE）。

    **必须按建表顺序的逆序删**：`ocr_correction` 有指向同月 `ocr_result` 的物理外键，
    先删 `ocr_result` 会被 MySQL 以 3730 拒绝。首次写这条清理时正是按建表顺序删的，
    真实库立刻报错（"Cannot drop table ... referenced by a foreign key constraint"）
    —— 这条注释就是那次实测的产物。

    `month` 由调用方传入（而非直接用模块常量）：这样本函数也能被"临时换个隔离月"的
    场景复用，且签名上就看得出它作用在哪个分片上。
    """
    with engine.begin() as conn:
        for logical in reversed(SHARDED):
            conn.execute(text(f"DROP TABLE IF EXISTS `{logical}_{month}`"))


@pytest.fixture
def drill_month() -> str:
    """演练月 = 模块级的**按进程唯一**月份（见 `DRILL_MONTH` 处关于并发隔离的说明）。

    同一进程内所有用例共用这一个月（故每个用例开头都先清一次），
    **跨进程互不干扰**——这正是原先写死月份时缺失的性质。
    """
    return DRILL_MONTH


@pytest.mark.integration
def test_apply_ddl_creates_all_nine_tables(drill_month: str) -> None:
    engine = _require_mysql()
    # 先清掉可能的中断残留，保证本用例断言的是本次执行的结果
    _drop_drill_shards(engine, drill_month)
    try:
        result = _run_apply(drill_month)
        assert result.returncode == 0, (
            f"apply_ddl.py 退出码 {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        # 口令 MUST NOT 出现在脚本输出里。用**环境里真实口令**反查，而不是写死字面量：
        # 写死字面量本身就是"把凭据放进仓库"（commit-check 清单 B 红线），而且换个环境就失效。
        secret = os.environ.get("DSH_IT_MYSQL_PASSWORD", "")
        if secret:
            assert secret not in result.stdout + result.stderr, (
                "apply_ddl.py 的输出里出现了口令明文"
            )
        else:
            # 没凭据时脚本会以非 0 退出；本分支理论上到不了，留一条失败而非静默跳过。
            raise AssertionError("未取到 DSH_IT_MYSQL_PASSWORD，无法做口令泄漏断言")
        assert "***" in result.stdout, "连接目标回显应当把口令遮蔽成 ***（证明用了 hide_password）"

        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT TABLE_NAME FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = :db"
                    ),
                    {"db": DRILL_DATABASE},
                )
            }
        expected = {f"{t}_{drill_month}" for t in SHARDED} | set(FIXED)
        missing = sorted(expected - tables)
        assert not missing, f"apply_ddl.py 跑完仍缺表：{missing}（实际有 {sorted(tables)}）"
    finally:
        _drop_drill_shards(engine, drill_month)
        engine.dispose()


@pytest.mark.integration
def test_apply_ddl_foreign_keys_carry_month_and_restrict(drill_month: str) -> None:
    engine = _require_mysql()
    _drop_drill_shards(engine, drill_month)
    try:
        result = _run_apply(drill_month)
        assert result.returncode == 0, result.stderr

        with engine.connect() as conn:
            fks = {
                row[0]: (row[1], row[2], row[3])
                for row in conn.execute(
                    text(
                        "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE, UPDATE_RULE "
                        "FROM information_schema.REFERENTIAL_CONSTRAINTS "
                        "WHERE CONSTRAINT_SCHEMA = :db"
                    ),
                    {"db": DRILL_DATABASE},
                )
            }
        expected_names = EXPECTED_FKS_BASE | {f"fk_ocr_correction_task_{drill_month}"}
        missing = sorted(expected_names - set(fks))
        assert not missing, f"缺外键：{missing}（实际有 {sorted(fks)}）"

        # 分片外键必须指向**同月**的 ocr_result（这是 Task 3.1 FIX-4 的核心断言）
        referenced, delete_rule, update_rule = fks[f"fk_ocr_correction_task_{drill_month}"]
        assert referenced == f"ocr_result_{drill_month}", (
            f"分片外键未指向同月表：实际 -> {referenced}"
        )
        for name, (_ref, delete_rule, update_rule) in fks.items():
            assert (delete_rule, update_rule) == ("RESTRICT", "RESTRICT"), (
                f"{name} 的动作不是显式 RESTRICT：DELETE={delete_rule} UPDATE={update_rule}"
            )
    finally:
        _drop_drill_shards(engine, drill_month)
        engine.dispose()


@pytest.mark.integration
def test_apply_ddl_indexes_match_er_md(drill_month: str) -> None:
    engine = _require_mysql()
    _drop_drill_shards(engine, drill_month)
    try:
        assert _run_apply(drill_month).returncode == 0
        with engine.connect() as conn:
            for logical, want in EXPECTED_INDEXES.items():
                physical = f"{logical}_{drill_month}" if logical in SHARDED else logical
                got = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                            "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tbl"
                        ),
                        {"db": DRILL_DATABASE, "tbl": physical},
                    )
                }
                got.discard("PRIMARY")
                assert got == want, (
                    f"{physical} 索引与 er.md §7 不一致："
                    f"期望 {sorted(want)} 实际 {sorted(got)}"
                )
    finally:
        _drop_drill_shards(engine, drill_month)
        engine.dispose()


@pytest.mark.integration
def test_apply_ddl_is_idempotent(drill_month: str) -> None:
    """复跑零错误：全部 `CREATE TABLE IF NOT EXISTS` 的直接后果。"""
    engine = _require_mysql()
    _drop_drill_shards(engine, drill_month)
    try:
        first = _run_apply(drill_month)
        assert first.returncode == 0, first.stderr
        # 记录首次建表时间，第二次若真"重建"过，CREATE_TIME 会变
        create_time_sql = text(
            "SELECT TABLE_NAME, CREATE_TIME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = :db AND TABLE_NAME LIKE :pat"
        )
        params = {"db": DRILL_DATABASE, "pat": f"%\\_{drill_month}"}
        with engine.connect() as conn:
            before = dict(conn.execute(create_time_sql, params).all())

        second = _run_apply(drill_month)
        assert second.returncode == 0, (
            f"复跑失败（不幂等）：退出码 {second.returncode}\n{second.stderr}"
        )
        with engine.connect() as conn:
            after = dict(conn.execute(create_time_sql, params).all())
        assert before, "没查到演练月的分片表，前置执行可能失败"
        assert before == after, (
            f"复跑改变了表的创建时间，说明表被重建过（不是幂等）：\n前 {before}\n后 {after}"
        )
    finally:
        _drop_drill_shards(engine, drill_month)
        engine.dispose()


@pytest.mark.integration
def test_apply_ddl_rejects_bad_month(drill_month: str) -> None:
    """参数自检：非法月份 MUST 以非 0 退出码拒绝，MUST NOT 静默建到错月份。"""
    bad = uuid.uuid4().hex[:6]  # 6 位但含字母与数字，可能碰巧全数字则跳过
    if bad.isdigit():
        pytest.skip("随机值碰巧是纯数字，本用例只验证非数字月份被拒")
    result = _run_apply(bad)
    assert result.returncode != 0, "非法月份应被拒绝"
    assert "6 位数字" in result.stderr, f"拒绝原因应可读，实际 stderr：{result.stderr!r}"
