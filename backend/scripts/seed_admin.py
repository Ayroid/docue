"""Create (or repair) the first administrator.

The hub needs one admin before anyone can approve anything, and the admin API
itself requires an admin to call it -- so the first one cannot be made through
the product. This script is that bootstrap, and it is the only place a role is
granted from configuration.

It is idempotent: run it twice and the second run promotes and re-activates the
existing account rather than failing on the unique index. It never rewrites a
password that is already set unless `--reset-password` is passed, so re-running
it after someone has changed their own password does not silently revert it.

    uv run python scripts/seed_admin.py
    uv run python scripts/seed_admin.py --email ops@ymsli.com --password 'S3cret...' --reset-password
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    hash_password,
    normalize_email,
    normalize_username,
    password_problem,
)
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import ROLE_ADMIN, STATUS_ACTIVE, User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the first TemplateHub administrator.")
    parser.add_argument("--email", default=settings.seed_admin_email)
    parser.add_argument("--username", default=settings.seed_admin_username)
    parser.add_argument("--password", default=settings.seed_admin_password)
    parser.add_argument("--full-name", default=settings.seed_admin_full_name)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Overwrite the password of an existing account. Off by default so a "
        "re-run cannot revert a password its owner has since changed.",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        print(
            "Need an email and a password. Pass --email/--password, or set\n"
            "SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD in .env.",
            file=sys.stderr,
        )
        return 2

    if (problem := password_problem(args.password)) is not None:
        print(f"Refusing that password: {problem}", file=sys.stderr)
        return 2

    email = normalize_email(args.email)
    username = normalize_username(args.username)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            # A seeded admin is verified on creation. There is no mailbox to
            # check during a first-run bootstrap, and leaving it `pending` would
            # lock the hub out of its own admin panel.
            user = User(
                email=email,
                username=username,
                full_name=args.full_name,
                password_hash=hash_password(args.password),
                role=ROLE_ADMIN,
                status=STATUS_ACTIVE,
                email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.commit()
            print(f"Created admin {user.username} <{user.email}>.")
            return 0

        changes = []
        if user.role != ROLE_ADMIN:
            user.role = ROLE_ADMIN
            changes.append("promoted to admin")
        if user.status != STATUS_ACTIVE:
            user.status = STATUS_ACTIVE
            changes.append("activated")
        if not user.email_verified:
            user.email_verified = True
            user.email_verified_at = datetime.now(timezone.utc)
            changes.append("email marked verified")
        if args.reset_password:
            user.password_hash = hash_password(args.password)
            changes.append("password reset")

        db.commit()
        print(
            f"{user.username} <{user.email}> already exists"
            + (f" -- {', '.join(changes)}." if changes else "; nothing to change.")
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
