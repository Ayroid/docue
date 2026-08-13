"""One-off: make the shared RDS match migration `0005`. **Destructive, read first.**

    uv run python scripts/reconcile_0005.py          # show what it would do
    uv run python scripts/reconcile_0005.py --apply  # do it

Why this exists. On 2026-08-14 the shared database was found carrying
`generation_sessions` and `question_plans` with `alembic_version` stamped
`0005`, while **no `0005` migration existed in any branch, local or remote**,
and `NEXT_STEPS.md` had no entry for it. Someone built and applied it without
pushing. Their columns differ from ours:

    generation_sessions   extra `question_plan` jsonb and `change_spec_id` uuid
    question_plans        `prompt_version` where 0005 says `planner_version`
    change_specs          no `fk_change_specs_session`

Both tables were empty, so the call was that our repo is the source of truth
and the DB should be brought to it rather than the other way round.

What it does, in one transaction:

  1. counts rows in both tables and **aborts if either is non-empty** -- the
     approval was to drop two empty tables, and it stops being that decision
     the moment someone's session is in there;
  2. drops both;
  3. rewinds `alembic_version` to `0004`;

then runs `alembic upgrade head` to apply `0005` properly, so the schema and
the migration history agree rather than being patched into alignment.

Delete this file once it has run. It documents a collision, not a workflow.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("generation_sessions", "question_plans")


def main() -> int:
    apply = "--apply" in sys.argv

    from app.db.session import engine, masked_url

    print(f"database: {masked_url()}")

    with engine.connect() as conn:
        stamped = conn.execute(text("select version_num from alembic_version")).scalar()
        print(f"alembic_version: {stamped}")

        counts = {}
        for table in TABLES:
            exists = conn.execute(
                text(
                    "select 1 from information_schema.tables "
                    "where table_schema = 'public' and table_name = :t"
                ),
                {"t": table},
            ).scalar()
            counts[table] = (
                conn.execute(text(f'select count(*) from "{table}"')).scalar()
                if exists
                else None
            )
            print(f"  {table}: {'absent' if counts[table] is None else f'{counts[table]} rows'}")

    occupied = {t: n for t, n in counts.items() if n}
    if occupied:
        print()
        print("ABORT: these tables have rows:")
        for table, n in occupied.items():
            print(f"  {table}: {n}")
        print(
            "The approved action was dropping two EMPTY tables. With data in them this is a\n"
            "different decision -- find out whose it is before going further."
        )
        return 1

    if not apply:
        print()
        print("Dry run. Would drop:")
        for table in TABLES:
            if counts[table] is not None:
                print(f"  drop table {table} cascade")
        print("  update alembic_version set version_num = '0004'")
        print("  then: alembic upgrade head")
        print()
        print("Re-run with --apply to do it.")
        return 0

    with engine.begin() as conn:
        # Re-check inside the transaction that drops them: this is a shared
        # database and the counts above were taken on a different connection.
        for table in TABLES:
            if counts[table] is None:
                continue
            n = conn.execute(text(f'select count(*) from "{table}"')).scalar()
            if n:
                raise SystemExit(f"ABORT: {table} gained {n} row(s) since the check")

        conn.execute(text("drop table if exists question_plans cascade"))
        conn.execute(text("drop table if exists generation_sessions cascade"))
        conn.execute(text("update alembic_version set version_num = '0004'"))
        print("dropped both tables; alembic rewound to 0004")

    print("running alembic upgrade head...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(result.stdout[-2000:] or result.stderr[-2000:])
    if result.returncode != 0:
        print("alembic upgrade FAILED -- the database is at 0004 with both tables gone.")
        return 1

    # Prove the result rather than trusting the exit code.
    with engine.connect() as conn:
        stamped = conn.execute(text("select version_num from alembic_version")).scalar()
        columns = {
            table: [
                r[0]
                for r in conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name = :t order by ordinal_position"
                    ),
                    {"t": table},
                )
            ]
            for table in TABLES
        }
        fk = conn.execute(
            text("select 1 from pg_constraint where conname = 'fk_change_specs_session'")
        ).scalar()

    print()
    print(f"alembic_version: {stamped}")
    for table, cols in columns.items():
        print(f"  {table}: {len(cols)} columns -> {', '.join(cols)}")
    print(f"  fk_change_specs_session present: {bool(fk)}")

    ok = (
        stamped == "0005"
        and "planner_version" in columns["question_plans"]
        and "question_plan" not in columns["generation_sessions"]
        and bool(fk)
    )
    print()
    print("reconcile: PASS -- the schema now matches migration 0005" if ok else "reconcile: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
