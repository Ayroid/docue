"""version lifecycle and promotion requests

The version-control half of the hub. Until now `template_versions` recorded
*that* a version existed but not what it meant: an original upload and a
document somebody generated at 2am and never promoted were the same kind of row,
distinguishable only by whether `storage_key` happened to start with
`generated/`. That is a naming convention doing a state machine's job, and it is
why a generated file could sit in the table looking exactly like a template.

Three columns and one table fix it.

**`lifecycle`** is the state. `draft` is a generated document that nobody has
asked to publish; `pending` is one awaiting doc control; `published` is or was
the template's current version; `superseded` is one that used to be. The
distinction `published` vs `superseded` is not redundant against
`templates.current_version_id` -- that pointer says which single version is live
*now*, while `superseded` says "this was live once", which is what makes the
history read as a lineage rather than a pile of files.

**`origin`** says where the bytes came from -- `upload` or `generated`. Derived
from `storage_key` today, which is exactly why it should be a column: the prefix
is a storage detail and the two facts will drift the moment anyone reorganises
the bucket.

**`version_promotions`** is the request itself. A separate table rather than a
`pending_by` column on the version, because a request has its own history --
who asked, who decided, when, and why not -- and because a rejected request must
survive its version being promoted later by somebody else. A column would have
to be overwritten to record the second attempt, losing the first, which is the
one that explains why the document sat unpublished for a week.

`uq_version_promotions_pending` is a partial unique index: at most one *pending*
request per version, unlimited decided ones. Without it a double-clicked submit
button queues the same document twice and doc control approves it twice.

**On `0005_auth`.** This revision chains onto the auth migration rather than
`0005`, and references `users.id` directly, because by the time this was written
the auth branch had already created `users`, `email_otps` and `notifications`
and migrated the shared database to `0005_auth`. Storing names here instead
would have meant a second migration later to convert them, and a window in which
the approval queue could not say which *account* asked for something -- which is
the one fact an approval needs. `requested_role` is still stored as a snapshot,
deliberately: it records the role the requester held *at the time*, so promoting
someone to admin next month does not silently rewrite the history of every
request they ever raised.

Revision ID: 0006
Revises: 0005_auth
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── template_versions: state, provenance, attribution ─────────────────
    op.add_column(
        "template_versions",
        sa.Column("lifecycle", sa.String(20), nullable=False, server_default="published"),
    )
    op.add_column(
        "template_versions",
        sa.Column("origin", sa.String(20), nullable=False, server_default="upload"),
    )
    # Nullable and SET NULL: every version that exists today predates auth and
    # has no author, and deleting an account must not delete the history of what
    # they published.
    op.add_column(
        "template_versions",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_template_versions_created_by",
        "template_versions",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill from the convention the columns replace. Every existing row was
    # written by one of exactly two code paths, and the storage prefix tells
    # them apart unambiguously *for rows that already exist*, which is the only
    # claim this needs to make.
    op.execute(
        """
        UPDATE template_versions
           SET origin = 'generated',
               lifecycle = 'draft'
         WHERE storage_key LIKE 'generated/%'
        """
    )
    # ...except any generated version a template already points at, which was
    # published by an explicit `publish: true` compile and must not be demoted
    # to a draft by this migration.
    op.execute(
        """
        UPDATE template_versions tv
           SET lifecycle = 'published'
          FROM templates t
         WHERE t.current_version_id = tv.id
        """
    )
    # An upload that has been replaced as current is superseded, not published.
    op.execute(
        """
        UPDATE template_versions tv
           SET lifecycle = 'superseded'
          FROM templates t
         WHERE tv.template_id = t.id
           AND tv.lifecycle = 'published'
           AND (t.current_version_id IS NULL OR t.current_version_id <> tv.id)
        """
    )

    op.create_check_constraint(
        "ck_template_versions_lifecycle",
        "template_versions",
        "lifecycle IN ('draft', 'pending', 'published', 'superseded')",
    )
    op.create_check_constraint(
        "ck_template_versions_origin",
        "template_versions",
        "origin IN ('upload', 'generated')",
    )
    op.create_index("ix_template_versions_lifecycle", "template_versions", ["lifecycle"])

    # ── version_promotions ────────────────────────────────────────────────
    op.create_table(
        "version_promotions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        # A snapshot, not a lookup. See the module docstring.
        sa.Column("requested_role", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["template_versions.id"], ondelete="CASCADE"),
        # RESTRICT on the requester: a pending request whose author has been
        # deleted is not something doc control should be asked to decide.
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_version_promotions_status",
        ),
    )
    op.create_index("ix_version_promotions_template_id", "version_promotions", ["template_id"])
    op.create_index("ix_version_promotions_status", "version_promotions", ["status"])
    # One pending request per version; any number of decided ones.
    op.create_index(
        "uq_version_promotions_pending",
        "version_promotions",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_version_promotions_pending", table_name="version_promotions")
    op.drop_index("ix_version_promotions_status", table_name="version_promotions")
    op.drop_index("ix_version_promotions_template_id", table_name="version_promotions")
    op.drop_table("version_promotions")

    op.drop_index("ix_template_versions_lifecycle", table_name="template_versions")
    op.drop_constraint("ck_template_versions_origin", "template_versions", type_="check")
    op.drop_constraint("ck_template_versions_lifecycle", "template_versions", type_="check")
    op.drop_constraint(
        "fk_template_versions_created_by", "template_versions", type_="foreignkey"
    )
    op.drop_column("template_versions", "created_by_id")
    op.drop_column("template_versions", "origin")
    op.drop_column("template_versions", "lifecycle")
