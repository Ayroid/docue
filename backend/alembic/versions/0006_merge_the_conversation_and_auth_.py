"""merge the conversation and auth migration lines

Two `0005`s were written against `0004` at the same time, on branches that did
not know about each other: `0005` created `generation_sessions` and
`question_plans` for the fill conversation, `0005_auth` created `users`,
`email_otps` and `notifications` and put versions behind an approval gate.

Both are applied to the shared database. Neither depends on the other -- they
touch disjoint tables, and `0005_auth`'s only edits to an existing table are
columns on `templates` and `template_versions`, which `0005` never reads. So
this merge carries no DDL: the schemas were already compatible, and the only
thing broken was alembic's idea of where "head" is. `alembic upgrade head`
errors outright with two heads, which would have blocked the next migration
whoever wrote it.

**On the stamping this needed.** The shared database recorded only `0005_auth`
in `alembic_version`, even though `0005`'s tables were physically present --
they had been created by the one-off reconcile script rather than by alembic
(see `scripts/`, and the commit that added it). `0005` was inserted into
`alembic_version` before this revision was applied, which records what was
already true rather than changing anything.

Revision ID: 0006
Revises: 0005, 0005_auth
Create Date: 2026-08-14

"""
from typing import Sequence, Union

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = ("0005", "0005_auth")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No DDL. See the module docstring."""


def downgrade() -> None:
    """No DDL. Splitting the lines again only restores two heads."""
