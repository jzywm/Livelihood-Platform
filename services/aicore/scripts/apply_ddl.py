"""按 `deploy/sql/ddl/**` 建立 AICORE 库表结构（分片表 + 非分片表）。

**为什么需要这个脚本（Task 3.1 的 FIX-5）**：首轮把"在真实 MySQL 上执行 DDL"当成一次性手工操作，
仓库里**没有任何可复核的产物** —— 于是"跑没跑过"无法从代码与测试里看出来（控制者实测两库皆空）。
本脚本把那条路径固化成**可重复执行**的命令，集成用例再包一层断言。

**SQL 的唯一来源是 `deploy/sql/ddl/**`**：本脚本**不自己拼任何 DDL 语句**，
只做两件事 —— ① 把 `{table}` / `{month}` 渲染成物理名；② 决定建表**顺序**。
理由：纯 SQL DDL 是权威定义（spec §5.5），脚本一旦开始拼 SQL，就等于出现第二份结构定义。

**渲染与月份算法都在 `repository/sharding.py`（Task 3.3 收编，MUST NOT 在本脚本再写一份）**：
`render_shard_template` / `render_fixed_table_ddl` / `shard_month_of` 是唯一实现处。
理由：两份渲染实现必然漂移，而漂移的表现是"脚本建的表与运行期建的表不是同一个结构"
—— 那种不一致只会在生产写入时才暴露。本脚本因此只保留"运维 CLI"该有的东西：
参数解析、目标库、顺序、退出码。

**建表顺序（MUST）**：`ai_task` → `ocr_result` → `ocr_correction`，被引用表先建；
`ocr_correction` 的物理外键指向**同月**的 `ocr_result_YYYYMM`（`er.md` §5.2/§7.3）。
顺序取自 `sharding.SHARDED_TABLE_ORDER`。6 张非分片表之间无依赖，按文件名字典序即可。

**幂等**：全部走 `CREATE TABLE IF NOT EXISTS`，复跑零错误；本脚本**不 DROP 任何东西**。

**口令来源（为什么不复用 `core.config.Settings`）**：`Settings` 有 9 个必填项（渠道、内部凭据、
配额预算护栏等），只为了拿 MySQL 连接信息而构造它，会让"建表"这件基础设施操作依赖一整份应用配置。
故本脚本按 `AICORE_MYSQL_*` 读环境变量，**缺省值只面向本机开发**（`aicore_dev`）。

用法：
    python scripts/apply_ddl.py                                # 建到 aicore（当前月）
    python scripts/apply_ddl.py --database aicore_test --month 202607
    python scripts/apply_ddl.py --dry-run                      # 只打印将要执行的 SQL
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from aicore.repository.sharding import (
    FIXED_TABLE_FILES,
    SHARDED_TABLE_FILES,
    SHARDED_TABLE_ORDER,
    render_fixed_table_ddl,
    render_shard_template,
    shard_month_of,
)

#: 本机开发缺省值（**仅**用户名与主机；口令 MUST NOT 有默认值 —— 见 `build_engine`）。
_DEFAULT_USER: Final[str] = "aicore_dev"


def current_month() -> str:
    """当前 UTC 月份（`YYYYMM`）。

    `er.md` §6 绪：时间**UTC 存储**；故分片月也按 UTC 取，
    避免本地时区在月初/月末把物理表算到相邻月份。
    **月份算法不在这里**：复用 `sharding.shard_month_of`，与运行期路由共用同一条
    UTC 归一规则（否则"脚本按本地月建表、运行期按 UTC 月查表"就是必然的错月）。
    """
    return shard_month_of(datetime.now(UTC))


def build_engine(database: str) -> Engine:
    """建一个**不打印口令**的引擎。用 `URL.create` 而不是手工拼串。

    环境变量查两组，先 `DSH_IT_MYSQL_*` 后 `AICORE_MYSQL_*`：
    前者是**演练库**的凭据（集成测试与本地建表演练用），后者是应用自身配置。
    为何不能用 `AICORE_MYSQL_*` 一组打天下、也不能用 `AICORE_TEST_MYSQL_*`，
    见 `tests/conftest.py` 的说明（一个是假凭据导致假 skip，一个是撞上
    `_UnknownEnvVarSource` 的 `AICORE_*` 命名空间拒绝）。
    """

    def _env(name: str) -> str | None:
        for prefix in ("DSH_IT_MYSQL_", "AICORE_MYSQL_"):
            value = os.environ.get(f"{prefix}{name}")
            if value:
                return value
        return None

    password = _env("PASSWORD")
    if not password:
        print(
            "[FAIL] 未取到 MySQL 口令：请设 DSH_IT_MYSQL_PASSWORD（演练库）"
            "或 AICORE_MYSQL_PASSWORD（应用配置）。口令 MUST NOT 硬编码在脚本里。",
            file=sys.stderr,
        )
        raise SystemExit(2)

    url = URL.create(
        drivername="mysql+pymysql",
        username=_env("USER") or _DEFAULT_USER,
        password=password,
        host=_env("HOST") or "127.0.0.1",
        port=int(_env("PORT") or "3306"),
        database=database,
        query={"charset": "utf8mb4"},
    )
    return create_engine(url, pool_pre_ping=True)


def plan_statements(month: str) -> list[tuple[str, str]]:
    """返回 `[(说明, SQL), ...]`，顺序即执行顺序（**不连数据库，可 dry-run**）。

    分片表按 `sharding.SHARDED_TABLE_ORDER`（被引用表先建）；6 张非分片表按
    `sharding.FIXED_TABLE_FILES` 的登记顺序（即文件名字典序，彼此无依赖）。
    渲染一律走 `sharding` 的渲染函数：**渲染只有一份实现**，本脚本不再持有任何
    占位符替换逻辑（Task 3.3 收编）。
    """
    planned: list[tuple[str, str]] = []
    for logical in SHARDED_TABLE_ORDER:
        planned.append(
            (
                f"{SHARDED_TABLE_FILES[logical]} -> {logical}_{month}",
                render_shard_template(logical, month),
            )
        )
    for logical, filename in FIXED_TABLE_FILES.items():
        planned.append((filename, render_fixed_table_ddl(logical)))
    return planned


def _reject_bad_month(month: str) -> None:
    """CLI 的月份校验 MUST 与**运行期**同一口径（6 位数字 + 月份 01~12）。

    **为什么这条要单独写并说明**（Task 3.3 的实测发现）：首版这里只查"6 位数字"，
    而运行期的 `sharding.ensure_month_tables` / `physical_table_name(str)` 卡 `01~12`。
    于是 `--month 202613` 能建出表、同样的月份在运行期会被拒——
    **同一份渲染逻辑的两条路径严格度不同**，CLI 能造出运行期不认的结构。
    那正是"两份路径不一致"的典型形态（本任务存在的意义就是消灭它），故 CLI 收紧到同口径。
    错误消息里点明月份范围，避免运维只看到"不合法"却不知合法范围。
    """
    problem: str | None = None
    if len(month) != 6 or not month.isdigit():
        problem = "必须是 6 位数字 YYYYMM"
    elif not 1 <= int(month[4:]) <= 12:
        problem = f"月份部分必须在 01~12，收到 {month[4:]!r}"
    if problem is not None:
        print(f"[FAIL] --month 不合法（{problem}），收到 {month!r}", file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 deploy/sql/ddl 建立 AICORE 库表结构")
    parser.add_argument("--database", default="aicore", help="目标库（默认 aicore）")
    parser.add_argument("--month", default=None, help="分片月 YYYYMM（默认当前 UTC 月）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的语句，不连库")
    args = parser.parse_args(argv)

    month = args.month or current_month()
    _reject_bad_month(month)

    planned = plan_statements(month)
    print(
        f"[INFO] 目标库 = {args.database} / 分片月 = {month} / 语句数 = {len(planned)}"
    )

    if args.dry_run:
        for label, sql in planned:
            head = " ".join(sql.split())[:110]
            print(f"  --- {label}\n      {head} ...")
        print("[INFO] dry-run：未连数据库")
        return 0

    engine = build_engine(args.database)
    # 打印目标时**不带口令**：render_as_string(hide_password=True) 是 SQLAlchemy 的显式安全开关。
    print(f"[INFO] 连接目标 = {engine.url.render_as_string(hide_password=True)}")

    try:
        with engine.begin() as conn:
            for label, sql in planned:
                conn.execute(text(sql))
                print(f"  [OK] {label}")
    except Exception as exc:
        # 顶层命令式脚本：如实报错并给非 0 退出码（这是"命令行工具"的正常契约，
        # 不是吞异常——错误照原样打到 stderr，调用方按退出码判断）。
        # 只打印异常类型与消息，不打印整条 SQL。
        print(f"[FAIL] 执行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"[DONE] {len(planned)} 条语句执行完毕"
        f"（全部 CREATE TABLE IF NOT EXISTS，可安全复跑）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
