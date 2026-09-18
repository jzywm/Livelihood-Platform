"""三源（有库时四源）结构一致性校验器 —— 可作 CI 门禁（Task 3.6）。

```
python scripts/compare_schema.py                # 两源：DDL ↔ er.md、DDL ↔ 模型元数据
python scripts/compare_schema.py --with-mysql   # 叠加 information_schema 第四路
python scripts/compare_schema.py --month 202601 # 渲染模板用的月（缺省 202601，**不取当前月**）
```

退出码：全部一致 `0`；任一不一致非 `0`；`--with-mysql` 连不上库时**也是非 0**
（MUST NOT 静默降级成"两源通过"——那会让人以为真库也验过了）。

**为什么要有它（而不是只留测试）**：spec §5.6 要求"任一条边不一致即失败"，
而要成为**门禁**就必须能在 CI / 提交钩子里以退出码表达结论。测试是给开发者本地跑的，
本脚本是给流水线跑的；两者共用 `repository/schema.py` 的同一套解析（**MUST NOT 各写一份**）。

**SQL 与结构的唯一来源**：`deploy/sql/ddl/**`、`docs/er.md`、`repository/models.py`。
本脚本自己**不解析任何结构文本**，只做"取源 → 调 `schema.diff` → 报结论"。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 允许 `python scripts/compare_schema.py` 直接运行（脚本不在包内，需把 src 挂上路径）
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT / "src"))

from aicore.repository import schema  # noqa: E402
from aicore.repository.sharding import ALL_TABLES  # noqa: E402

#: 渲染模板用的**缺省**月。刻意是常量而非当前月：本校验与"今天是几月"无关，
#: 取当前月会让同一份代码在不同日期得出不同结论（元旦、月末尤其明显）。
DEFAULT_MONTH = "202601"

#: 期望的逻辑表数量。解析塌了必须报警，而不是"两边都解出 0 张表"却报一致。
EXPECTED_TABLE_COUNT = len(ALL_TABLES)


def _load_sources(month: str) -> dict[str, dict[str, schema.TableSpec]]:
    return {
        "DDL(deploy/sql/ddl)": schema.parse_ddl_directory(schema.DDL_DIR, month=month),
        "er.md §6 数据字典": schema.parse_er_md(schema.ER_MD.read_text(encoding="utf-8")),
        "SQLAlchemy 元数据": schema.from_metadata(schema.load_metadata()),
    }


def _database_url(database: str):
    from sqlalchemy.engine import URL

    def _env(name: str, default: str) -> str:
        for prefix in ("DSH_IT_MYSQL_", "AICORE_MYSQL_"):
            value = os.environ.get(f"{prefix}{name}")
            if value:
                return value
        return default

    return URL.create(
        drivername="mysql+pymysql",
        username=_env("USER", "aicore_dev"),
        password=_env("PASSWORD", ""),
        host=_env("HOST", "127.0.0.1"),
        port=int(_env("PORT", "3306")),
        database=database,
        query={"charset": "utf8mb4"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="三源（或四源）结构一致性校验")
    parser.add_argument(
        "--month", default=DEFAULT_MONTH, help=f"模板渲染月（缺省 {DEFAULT_MONTH}）"
    )
    parser.add_argument("--with-mysql", action="store_true", help="叠加 information_schema")
    parser.add_argument("--database", default="aicore_test", help="第四路要读的库")
    args = parser.parse_args(argv)

    sources = _load_sources(args.month)
    print(f"[INFO] 模板渲染月 = {args.month}（缺省常量，刻意不取当前月）")

    # 非空下限：解析塌了（正则失效、文件被换）会让所有源都变成 0 张表而"彼此一致"。
    for name, tables in sources.items():
        print(f"[INFO] {name:24} 解析到 {len(tables)} 张表")
        if len(tables) != EXPECTED_TABLE_COUNT:
            print(
                f"[FAIL] {name} 只解析到 {len(tables)} 张表，期望 {EXPECTED_TABLE_COUNT}"
                f"（解析塌了会表现为'所有源彼此一致'，必须先拦住）",
                file=sys.stderr,
            )
            return 1

    if args.with_mysql:
        from sqlalchemy import create_engine

        url = _database_url(args.database)
        if not url.password:
            # 本脚本不像测试那样有 conftest 帮忙从 .env 回填口令，故缺凭据时要给可操作的提示，
            # 而不是抛一个 "using password: NO" 让运维自己猜。
            print(
                "[FAIL] --with-mysql 需要 MySQL 口令，但 DSH_IT_MYSQL_PASSWORD / "
                "AICORE_MYSQL_PASSWORD 都为空。请先设置（本机开发口令在 services/aicore/.env 里）",
                file=sys.stderr,
            )
            return 2
        try:
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                sources[f"information_schema({args.database})"] = schema.from_information_schema(
                    conn, args.database
                )
            engine.dispose()
        except Exception as exc:
            # 连不上 MUST 是非 0：静默降级成"两源通过"会让人以为真库也验过了。
            print(
                f"[FAIL] --with-mysql 连不上 {url.render_as_string(hide_password=True)}："
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
    else:
        print("[WARN] 未传 --with-mysql：**真实库结构未被校验**（只比了文本与元数据三源）")

    names = list(sources)
    failed = False
    for left_index in range(len(names)):
        for right_index in range(left_index + 1, len(names)):
            left_name, right_name = names[left_index], names[right_index]
            differences = schema.diff(sources[left_name], sources[right_name])
            if differences:
                failed = True
                print(f"[FAIL] {left_name} vs {right_name}：{len(differences)} 处差异")
                for item in differences:
                    print(f"    - {item}")
            else:
                print(f"[ OK ] {left_name} vs {right_name}：一致")

    if failed:
        print("[FAIL] 结构一致性校验未通过", file=sys.stderr)
        return 1
    print(f"[DONE] {len(names)} 个来源两两一致（{len(sources[names[0]])} 张表）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
