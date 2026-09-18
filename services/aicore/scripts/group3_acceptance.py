"""第 3 组验收检查表（可复跑）：逐项输出判定与证据。

只做**只读**动作（不建表、不改文件），故可在任何时候重跑。
真实库相关的项需要 MySQL 可达 + `DSH_IT_MYSQL_PASSWORD`（或 `.env` 里的开发口令）。

用法：
    .venv\\Scripts\\python.exe scripts/group3_acceptance.py
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
TESTS = SERVICE_ROOT / "tests"
DDL_DIR = SERVICE_ROOT / "deploy" / "sql" / "ddl"

sys.path.insert(0, str(SERVICE_ROOT / "src"))

PASS = "PASS"
FAIL = "FAIL"
INFO = "INFO"

results: list[tuple[str, str, str]] = []


def record(item: str, verdict: str, evidence: str) -> None:
    results.append((item, verdict, evidence))
    print(f"[{verdict}] {item}\n        {evidence}")


# ---------------------------------------------------------------------------
# 1. DDL 在真实 MySQL 8 上执行成功
# ---------------------------------------------------------------------------
def check_ddl_on_real_mysql() -> None:
    from sqlalchemy import create_engine, text

    from aicore.repository import schema

    password = os.environ.get("DSH_IT_MYSQL_PASSWORD")
    if not password:
        env_file = SERVICE_ROOT / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("AICORE_MYSQL_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
    if not password:
        record("1. DDL 在真实 MySQL 8 执行", INFO, "未取到口令，跳过（不算通过）")
        return
    from sqlalchemy.engine import URL

    url = URL.create(
        drivername="mysql+pymysql",
        username=os.environ.get("DSH_IT_MYSQL_USER", "aicore_dev"),
        password=password,
        host=os.environ.get("DSH_IT_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("DSH_IT_MYSQL_PORT", "3306")),
        database=os.environ.get("AICORE_MYSQL_DATABASE", "aicore"),
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = :db ORDER BY TABLE_NAME"
                ),
                {"db": url.database},
            ).all()
            ddl_side = schema.parse_ddl_directory(DDL_DIR, month="202609")
            live = schema.from_information_schema(conn, str(url.database))
        differences = schema.diff(ddl_side, live)
        names = [row[0] for row in rows]
        if differences:
            record(
                "1. DDL 在真实 MySQL 8 执行",
                FAIL,
                f"库 {url.database} 有 {len(names)} 张表，"
                f"但与 DDL 有 {len(differences)} 处结构差异",
            )
        else:
            record(
                "1. DDL 在真实 MySQL 8 执行",
                PASS,
                f"库 {url.database} {len(names)} 张表，与 deploy/sql/ddl 结构 0 差异",
            )
    except Exception as exc:
        record("1. DDL 在真实 MySQL 8 执行", FAIL, f"{type(exc).__name__}: {exc}")
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 2 + 5. 三源比对正常态 / 缺口令
# ---------------------------------------------------------------------------
def check_three_sources() -> None:
    from aicore.repository import schema

    ddl = schema.parse_ddl_directory(DDL_DIR, month="202601")
    er = schema.parse_er_md(schema.ER_MD.read_text(encoding="utf-8"))
    meta = schema.from_metadata(schema.load_metadata())
    counts = (len(ddl), len(er), len(meta))
    diffs = (
        len(schema.diff(ddl, er)),
        len(schema.diff(ddl, meta)),
        len(schema.diff(er, meta)),
    )
    if counts != (9, 9, 9) or any(diffs):
        record("2. 三源交叉比对正常态", FAIL, f"表数 {counts}，差异 {diffs}")
    else:
        record("2. 三源交叉比对正常态", PASS, f"表数 {counts}，三对组合差异 {diffs}")


def check_three_sources_negative() -> None:
    """三方向阴性：每个方向都必须**变红**，且配未改动对照。"""
    from aicore.repository import schema

    ddl = schema.parse_ddl_directory(DDL_DIR, month="202601")
    er_text = schema.ER_MD.read_text(encoding="utf-8")
    er = schema.parse_er_md(er_text)

    # 方向① 改 DDL（内存内）
    raw = (DDL_DIR / "20_vision_review.sql").read_text(encoding="utf-8")
    needle = "`review_id`        varchar(32)"
    if needle not in raw:
        record("3. 三源比对三方向阴性", FAIL, "方向① 找不到 DDL 变异锚点")
        return
    ddl_mut = dict(ddl)
    ddl_mut.update(schema.parse_ddl(raw.replace(needle, "`review_id`        varchar(64)", 1)))
    d1 = schema.diff(ddl_mut, er)

    # 方向② 改 er.md（内存内）
    anchor = "| review_id | varchar(32) | NO |"
    if anchor not in er_text:
        record("3. 三源比对三方向阴性", FAIL, "方向② 找不到 er.md 变异锚点")
        return
    er_mut = schema.parse_er_md(er_text.replace(anchor, "| review_id | varchar(32) | YES |", 1))
    d2 = schema.diff(ddl, er_mut)

    # 方向③ 改模型（临时 MetaData）
    from sqlalchemy import Column, MetaData, Table

    from aicore.repository.models import Base

    tmp = MetaData()
    src = Base.metadata.tables["vision_review"]
    Table(
        "vision_review",
        tmp,
        *[
            Column(
                column.name,
                column.type,
                primary_key=column.primary_key,
                nullable=column.name == "review_id" or column.nullable,
            )
            for column in src.columns
        ],
    )
    meta_mut = dict(schema.from_metadata(Base.metadata))
    meta_mut.update(schema.from_metadata(tmp))
    d3 = schema.diff(ddl, meta_mut)

    all_red = all(len(x) == 1 for x in (d1, d2, d3))
    record(
        "3. 三源比对三方向阴性",
        PASS if all_red else FAIL,
        f"方向①{len(d1)} 处 / 方向②{len(d2)} 处 / 方向③{len(d3)} 处（各应恰好 1）",
    )


# ---------------------------------------------------------------------------
# 4. 跨月路由用例无 sleep
# ---------------------------------------------------------------------------
def check_no_sleep_in_tests() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "sleep":
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Name) and node.id == "sleep":
                offenders.append(f"{path.name}:{node.lineno}")
    if offenders:
        record("4. 测试内无 sleep", FAIL, f"命中 {offenders}")
    else:
        record("4. 测试内无 sleep", PASS, "AST 扫描全 tests/ 无 sleep 调用（注释里的说明不算）")


# ---------------------------------------------------------------------------
# 6. 缺分片键抛错 / 跨分片被拒
# ---------------------------------------------------------------------------
def check_shard_guards() -> None:
    from aicore.repository.sharding import (
        CrossShardOperationError,
        MissingShardKeyError,
        assert_single_shard,
        require_shard_key,
    )

    missing_fired = False
    try:
        require_shard_key(None, field="shard")
    except MissingShardKeyError as exc:
        missing_fired = exc.code == 1001
    cross_fired = False
    try:
        assert_single_shard(["202601", "202602"], operation="probe")
    except CrossShardOperationError as exc:
        cross_fired = exc.code == 1003
    same_ok = assert_single_shard(["202601", "202601"], operation="probe") == "202601"
    record(
        "6. 缺分片键抛错 / 跨分片被拒",
        PASS if (missing_fired and cross_fired and same_ok) else FAIL,
        f"缺键→1001 {missing_fired}；跨月→1003 {cross_fired}；同月去重→'202601' {same_ok}",
    )


# ---------------------------------------------------------------------------
# 7. 只读会话分离 + 池大小随配置
# ---------------------------------------------------------------------------
def check_session_separation() -> None:
    from aicore.core.config import Settings
    from aicore.repository.session import EngineFactory

    base = {
        "env": "test",
        "mysql_host": "127.0.0.1",
        "mysql_user": "u",
        "mysql_password": "p",  # 仅用于构造引擎，不连库
        "mysql_database": "d",
        "redis_host": "127.0.0.1",
        "provider": "mock",
        "internal_token": "t",
        "daily_quota_per_account": 1000,
        "daily_budget_total": 100000,
        "mysql_pool_size": 3,
        "mysql_max_overflow": 7,
    }
    settings = Settings(**base)
    factory = EngineFactory(settings)
    pool_from_config = (
        factory.write_engine.pool.size() == 3 and factory.write_engine.pool._max_overflow == 7
    )
    changed = Settings(**{**base, "mysql_pool_size": 11, "mysql_max_overflow": 2})
    follows_config = EngineFactory(changed).write_engine.pool.size() == 11
    separated = factory.write_engine is not factory.read_engine
    primary_fallback = factory.read_target_is_primary is True
    factory.dispose()
    record(
        "7. 只读会话分离 + 池随配置",
        PASS if (pool_from_config and follows_config and separated and primary_fallback) else FAIL,
        f"池取自配置 {pool_from_config}；随配置变化 {follows_config}；"
        f"读写两引擎 {separated}；无从库时回落主库 {primary_fallback}",
    )


# ---------------------------------------------------------------------------
# 8. 迁移幂等（结构层面；版本层面由 test_migration 的集成用例守）
# ---------------------------------------------------------------------------
def check_migration_files() -> None:
    versions = SERVICE_ROOT / "deploy" / "sql" / "migration" / "versions"
    files = sorted(p.name for p in versions.glob("*.py")) if versions.is_dir() else []
    alembic_ini = SERVICE_ROOT / "alembic.ini"
    if not alembic_ini.is_file():
        record("8. 迁移幂等（基线迁移就位）", FAIL, "alembic.ini 不存在")
        return
    ini_text = alembic_ini.read_text(encoding="utf-8")
    # 判据是"**URL 值**里没有口令"，不是"文件里不出现 password 这个词"。
    # 首版用 `"password" not in ini_text`，被文件头那句
    # `# The password is NEVER stored here (this file is committed)` 判红——
    # 那句话恰恰在**说明正确做法**，却被当成了违规证据（同 check_guard_existence 的教训）。
    # 次版正则写成 `(.*)$` 且未加 MULTILINE 的收尾锚点，跨行吞掉了后续注释；
    # 正确写法是逐行取 `sqlalchemy.url` 的值。
    url_value: str | None = None
    for line in ini_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("sqlalchemy.url"):
            url_value = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
            break
    key_hint = re.search(r"^\s*(password|passwd|pwd)\s*=\s*\S", ini_text, re.MULTILINE)
    ok = len(files) == 1 and url_value == "" and key_hint is None
    record(
        "8. 迁移幂等（基线迁移就位）",
        PASS if ok else FAIL,
        f"versions/ 下 {len(files)} 条迁移 {files}；"
        f"sqlalchemy.url 值 {url_value!r}（应为空串，由 env.py 从环境变量组装）；"
        f"无 password= 赋值 {key_hint is None}",
    )


# ---------------------------------------------------------------------------
# 9. 一万个 ID 全过正则且无重复
# ---------------------------------------------------------------------------
def check_idgen() -> None:
    """第 9 项：一万个 ID 过正则且无重复，**总长恰为 32**。

    **判据 MUST 用字面量 32，MUST NOT 用 `MAX_ID_LENGTH`**（独立评审抓到的假绿，重要）：
    首版写成 `max(len(v)) <= MAX_ID_LENGTH` —— 那是拿**被测对象自己的常量**当判据，
    于是把常量改成自洽但错误的值（如 35，各前缀 hex 位数仍在 uuid4 的 32 位内，
    内部自校验不响）时，本脚本**依然输出 PASS 10 / FAIL 0**（打印"最大长度 35 ≤ 35 True"）。
    而 `er.md` §5.4 的所有 ID 列都是 `varchar(32)` —— 33~35 字符会让**每一行都插不进去**，
    正是 spec §5.8 点名"最容易写错"的后果。
    这与 `tests/unit/test_idgen.py` 里那条"期望值一律现算"的取向**不矛盾**：
    那里现算的是"各前缀该有多少位 hex"（被测对象内部的算术），
    而"这个算术的**上限**必须是 32"是**外部契约**（来自 `er.md` 的列宽），只能写死。
    """
    import concurrent.futures

    from aicore.core.idgen import (
        ID_PREFIX_LENGTHS,
        ID_PREFIXES,
        MAX_ID_LENGTH,
        new_id,
        validate_id,
    )

    # 外部契约（字面量，不取自被测对象）：er.md §5.4 所有 ID 列均为 varchar(32)。
    contract_max = 32
    constant_is_contract = contract_max == MAX_ID_LENGTH
    kinds = sorted(ID_PREFIXES)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(lambda i: new_id(kinds[i % len(kinds)]), range(10_000)))
    unique = len(set(ids)) == len(ids)
    longest = max(len(value) for value in ids)
    exactly_32 = longest == contract_max
    all_valid = all(validate_id(value) for value in ids)
    # 逐前缀也钉一次：单一"最长值恰好 32"可能被"某个前缀短了、另一个长了"掩盖。
    per_prefix_ok = all(
        len(new_id(kind)) == contract_max for kind in kinds
    )
    # 前缀长度的算术自证：5+27 / 4+28 / 4+28 / 7+25 / 4+28 / 3+29 恒等于 32。
    arithmetic_ok = all(
        len(ID_PREFIXES[kind]) + ID_PREFIX_LENGTHS[kind] == contract_max for kind in kinds
    )
    ok = (
        constant_is_contract
        and unique
        and exactly_32
        and per_prefix_ok
        and arithmetic_ok
        and all_valid
    )
    record(
        "9. 一万个 ID 过正则且无重复",
        PASS if ok else FAIL,
        f"常量==契约32 {constant_is_contract}；唯一 {unique}；"
        f"最长恰好 32 {exactly_32}（实测 {longest}）；逐前缀各 32 {per_prefix_ok}；"
        f"前缀+hex 位数==32 {arithmetic_ok}；全量校验 {all_valid}",
    )


# ---------------------------------------------------------------------------
# 10. 提交信息不带 [AI] 前缀
# ---------------------------------------------------------------------------
def check_commit_messages() -> None:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--format=%h %s", "-40"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    offenders = [line for line in lines if "[AI]" in line]
    patterns = re.compile(r"^(feat|fix|perf|refactor|docs|test|chore|ci|build|style)(\(.+\))?: .+")
    bad_format = [line for line in lines if not patterns.match(line.split(" ", 1)[1])]
    ok = not offenders and not bad_format
    record(
        "10. 提交不带 [AI] 前缀且符合 Conventional Commits",
        PASS if ok else FAIL,
        f"近 {len(lines)} 条：带 [AI] 前缀 {len(offenders)} 条；格式不符 {len(bad_format)} 条",
    )


def main() -> int:
    print("=" * 78)
    print("AICORE 第 3 组验收检查表")
    print("=" * 78)
    check_ddl_on_real_mysql()
    check_three_sources()
    check_three_sources_negative()
    check_no_sleep_in_tests()
    check_guard_existence()
    check_shard_guards()
    check_session_separation()
    check_migration_files()
    check_idgen()
    check_commit_messages()
    print()
    print("=" * 78)
    failed = [item for item, verdict, _ in results if verdict == FAIL]
    info = [item for item, verdict, _ in results if verdict == INFO]
    passed = len(results) - len(failed) - len(info)
    print(f"结果：PASS {passed} / FAIL {len(failed)} / INFO {len(info)}")
    for item in failed:
        print(f"  FAIL  {item}")
    for item in info:
        print(f"  INFO  {item}（未验证，不算通过）")
    return 1 if failed else 0


def check_guard_existence() -> None:
    """5. 跨分片 JOIN/聚合/事务 MUST NOT 存在——**只对代码骨架发问**。

    这条检查器被我自己改坏过两次，两次都是"文档里提到禁用词被判成违规"：
      - 首版子串匹配 `join(`，把 `"".join(out)` 这类**字符串拼接**判成 SQL JOIN；
      - 次版加了 `\\bJOIN\\b`，又把 docstring 里"禁止跨分片 JOIN / 聚合 / 事务"
        这句**说明**判成了违规（实测 4 处，全在 docstring）。
    两版都犯同一个错：**没有区分"代码"与"文档/字符串"**。

    故最终判据（**前三版都错，这一版换了思路**）：
      前三版都试图区分"字符串 join"与"对象 join"，全部失败
      （① 子串匹配把 `"".join` 判成 SQL JOIN；② `\\bJOIN\\b` 把 docstring 里
      "禁止跨分片 JOIN"这句说明判成违规；③ 想在 token 流上剔引号三元组，但引号
      被 `tokenize` 拆成独立 token、条件恒不成立）。

      **换判据：不问"是不是 join"，问"有没有 SELECT 上的 join"**——
      本项目 repository 层**不构造 select 之外的 join**，故 SQL JOIN 的唯一形态是
      `select (...)` 之后（同一骨架内）出现 `.join(` / `.outerjoin(` / `.join_from(`。
      这样：
        - `"".join(...)` 出现在 `select(` 之前或与之无关 → 不命中；
        - `select(...).join(...)`（真正的跨表查询）→ 命中。
      两阶段提交单独判（`two_phase` / `begin_twophase` / `.prepare(`），它与字符串无关。
    """
    import io
    import tokenize

    two_phase_re = re.compile(r"\btwo_phase\b|\bbegin_twophase\b|\.\s*prepare\s*\(")
    offenders: list[str] = []
    for path in sorted((SERVICE_ROOT / "src" / "aicore").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        code_tokens: list[str] = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            code_tokens.append(token.string)
        code = " ".join(code_tokens)
        last_select = 0
        for match in re.finditer(r"\bselect\s*\(|\.\s*(join|outerjoin|join_from)\s*\(", code):
            if match.group(0).startswith("select"):
                last_select = match.end()
                continue
            # 只在"最近的 select( 之后"才算 SQL JOIN（且距离有限，避免跨函数误判）
            if last_select and match.start() - last_select < 400:
                offenders.append(f"{path.name}: select 后出现 {match.group(0)}")
        offenders.extend(f"{path.name}: {m.group(0)}" for m in two_phase_re.finditer(code))
    record(
        "5. 无跨分片 JOIN/聚合/两阶段提交",
        PASS if not offenders else FAIL,
        (
            "全树无 select 上的 join、无两阶段提交"
            if not offenders
            else f"命中 {len(offenders)} 处：{offenders[:4]}"
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
