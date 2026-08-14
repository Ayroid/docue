"""add accounts, email OTPs, in-app notifications and version approval

Three new tables and a review state on `template_versions`.

**Existing versions are backfilled to `approved`, not `pending`.** Every
template already in the hub was uploaded when there was no approval gate and is
already published; defaulting them to `pending` would empty the library on
deploy and dump the whole corpus into doc control's queue as if it had just
arrived. The gate applies to what comes next.

Approval is on the *version* rather than the template on purpose: v2 of an
approved template is an unreviewed document, and hanging the flag on
`templates` would publish it the moment it was uploaded.

`users.email` and `users.username` are both unique because the login form takes
either one. Email is stored lowercased by `app.core.security.normalize_email`,
which makes the plain unique index a genuine case-insensitive constraint and
avoids needing the citext extension on RDS.

**On the revision id.** This is `0004_auth`, not `0004`, and that is not a typo.
`feature/change-spec-compile` already carries a revision identified as `0004`,
and two files claiming one id cannot coexist in a script directory -- Alembic
rejects the whole tree, not just the duplicate. Both branches legitimately
follow `0003`, so this is an ordinary parallel-branch history: once the other
merges there are two heads off `0003`, and whoever merges second runs
`alembic merge` to join them. Numbering this `0005` would be worse -- it would
claim to depend on work it has never seen.

Revision ID: 0004_auth
Revises: 0003
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_auth"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled')", name="ck_users_status"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "email_otps",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        # sha256 of the code -- the plaintext is never stored, so a dump of this
        # table cannot be used to verify an address or reset a password.
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')", name="ck_email_otps_purpose"
        ),
    )
    op.create_index("ix_email_otps_user_id", "email_otps", ["user_id"])
    op.create_index("ix_email_otps_purpose", "email_otps", ["purpose"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # Deliberately not foreign keys: a notification is a record of what was
        # said and should survive the template it refers to, exactly as
        # `jobs.entity_id` does.
        sa.Column("template_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    # The bell polls "unread, newest first" on every page load, and that is the
    # only query this table serves hot.
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.add_column(
        "templates",
        sa.Column(
            "owner_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_templates_owner_id", "templates", ["owner_id"])

    # server_default 'approved' so the backfill of existing rows is the same
    # statement as the column add. The application default is `pending` (see the
    # model), which is what new uploads get; the server default is dropped below
    # so the two can never disagree for a row inserted outside the ORM.
    op.add_column(
        "template_versions",
        sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="approved"),
    )
    op.alter_column("template_versions", "approval_status", server_default="pending")
    op.create_index("ix_template_versions_approval_status", "template_versions", ["approval_status"])
    op.create_check_constraint(
        "ck_template_versions_approval_status",
        "template_versions",
        "approval_status IN ('pending', 'approved', 'rejected')",
    )

    op.add_column(
        "template_versions",
        sa.Column(
            "submitted_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_template_versions_submitted_by", "template_versions", ["submitted_by"])
    op.add_column(
        "template_versions",
        sa.Column(
            "reviewed_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("template_versions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("template_versions", sa.Column("review_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_versions", "review_note")
    op.drop_column("template_versions", "reviewed_at")
    op.drop_column("template_versions", "reviewed_by")
    op.drop_index("ix_template_versions_submitted_by", table_name="template_versions")
    op.drop_column("template_versions", "submitted_by")
    op.drop_constraint("ck_template_versions_approval_status", "template_versions", type_="check")
    op.drop_index("ix_template_versions_approval_status", table_name="template_versions")
    op.drop_column("template_versions", "approval_status")

    op.drop_index("ix_templates_owner_id", table_name="templates")
    op.drop_column("templates", "owner_id")

    op.drop_table("notifications")
    op.drop_table("email_otps")
    op.drop_table("users")
