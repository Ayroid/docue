"""Connectivity smoke test for DATABASE_URL. Never prints the password."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from app.core.config import settings
from app.db.session import engine


def masked_url() -> str:
    url = engine.url
    return f"{url.drivername}://{url.username}:***@{url.host}:{url.port}/{url.database}"


def main() -> int:
    print(f"Connecting to {masked_url()} ...")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"FAILED to connect: {type(exc).__name__}: {exc}")
        return 1

    print("Connected OK.")

    tables = inspect(engine).get_table_names()
    print(f"Existing tables: {tables or '(none yet)'}")

    if "templates" in tables and "template_versions" in tables:
        print("templates / template_versions already present.")
    else:
        print("Migration not applied yet -- run: uv run alembic upgrade head")

    return 0


if __name__ == "__main__":
    sys.exit(main())
