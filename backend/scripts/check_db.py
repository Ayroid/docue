"""Connectivity smoke test for DATABASE_URL. Never prints the password."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect

from app.db.session import check_db_connection, engine, masked_url

logging.basicConfig(level=logging.INFO)


def main() -> int:
    try:
        check_db_connection()
    except Exception as exc:
        print(f"FAILED to connect: {type(exc).__name__}: {exc}")
        return 1

    print(f"Connected OK ({masked_url()}).")

    tables = inspect(engine).get_table_names()
    print(f"Existing tables: {tables or '(none yet)'}")

    if "templates" in tables and "template_versions" in tables:
        print("templates / template_versions already present.")
    else:
        print("Migration not applied yet -- run: uv run alembic upgrade head")

    return 0


if __name__ == "__main__":
    sys.exit(main())
