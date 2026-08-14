"""template visibility and per-user grants

Who may *see* a template, as opposed to whether it has been approved. The two
are deliberately independent: approval is a property of a version and answers
"is this published?", visibility is a property of the template and answers "is
this published *to you*?". A restricted template can be perfectly approved and
still invisible, and conflating them would mean the only way to hide a document
was to refuse to approve it.

**Why a mode column and not only a grant table.** A pure access-control list --
one row per user per template, the literal SharePoint model -- makes the common
case the expensive one. Most of this corpus is standard YMSLI forms that
everyone needs; publishing one under a pure ACL means writing a row for every
account, and every new joiner needs one on every template. `visibility` lets the
ordinary template cost nothing to share and reserves the grant table for the
documents that genuinely need naming names.

**`public` is the default and every existing row gets it**, which is what makes
this migration a no-op for behaviour: `public` is exactly the rule that was in
force before this column existed -- any signed-in caller, subject to approval.
Nothing becomes restricted until an admin says so.

**Grants are per user, not per principal.** An earlier sketch had nullable
`user_id`/`group_id` with a check constraint, so departments could land later
without a schema change. That was a seam for something with no table to point
at: there are no groups in this product, a nullable FK to nothing is not a
design, and adding groups later needs its own migration regardless. `user_id` is
therefore NOT NULL, and a `groups` table -- if it ever exists -- adds a second
grant table or a second nullable column then, with the check constraint written
at the moment it can actually be enforced.

`permission` ships with only `view` used by any caller. `manage` exists in the
constraint so that granting someone the right to re-share a template later is a
value change rather than a constraint migration on a live table.

`expires_at` is honoured by every read path from the day it exists rather than
being added when someone asks: a grant that outlives its reason is the failure
mode of every sharing system, and a nullable column that means "forever" costs
nothing.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `server_default` rather than a data migration: it backfills every existing
    # row in one statement and keeps working for inserts written against the old
    # model, which matters while a previous build is still serving traffic.
    op.add_column(
        "templates",
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default="public",
        ),
    )
    op.create_check_constraint(
        "ck_templates_visibility",
        "templates",
        "visibility IN ('public', 'restricted')",
    )
    # Partial: `public` is the overwhelming majority and is never the selective
    # half of a query -- the index is only ever useful for finding the
    # restricted ones, so indexing the rest is dead weight on every write.
    op.create_index(
        "ix_templates_restricted",
        "templates",
        ["visibility"],
        postgresql_where=sa.text("visibility = 'restricted'"),
    )

    op.create_table(
        "template_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False, server_default="view"),
        # Who granted it. Nullable only so that deleting an admin account does
        # not cascade away the access they handed out -- the grant outlives the
        # person who made it, and SET NULL says "we no longer know who" rather
        # than silently revoking half the hub.
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("permission IN ('view', 'manage')", name="ck_template_grants_permission"),
        # One grant per person per template. Re-sharing with someone who already
        # has access is an update of their permission, not a second row -- two
        # rows would make "what can this person do" a question with more than
        # one answer.
        sa.UniqueConstraint("template_id", "user_id", name="uq_template_grants_template_user"),
    )
    # The shape every read path uses: "does this caller have a live grant on
    # this template". Composite and in this order because `template_id` is the
    # equality the correlated EXISTS pins first.
    op.create_index(
        "ix_template_grants_template_user", "template_grants", ["template_id", "user_id"]
    )
    # The other direction, for "everything shared with me".
    op.create_index("ix_template_grants_user_id", "template_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_template_grants_user_id", table_name="template_grants")
    op.drop_index("ix_template_grants_template_user", table_name="template_grants")
    op.drop_table("template_grants")
    op.drop_index("ix_templates_restricted", table_name="templates")
    op.drop_constraint("ck_templates_visibility", "templates", type_="check")
    op.drop_column("templates", "visibility")
