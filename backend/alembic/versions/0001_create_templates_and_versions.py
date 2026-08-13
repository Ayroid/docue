"""create templates and template_versions

Revision ID: 0001
Revises:
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("format IN ('xlsx', 'docx', 'pptx')", name="ck_templates_format"),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_templates_status"),
    )
    op.create_index("ix_templates_format", "templates", ["format"])
    op.create_index("ix_templates_status", "templates", ["status"])

    op.create_table(
        "template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("upload_status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("template_id", "version_number", name="uq_template_versions_template_id_version_number"),
        sa.UniqueConstraint("storage_bucket", "storage_key", name="uq_template_versions_bucket_key"),
        sa.CheckConstraint("upload_status IN ('uploaded', 'failed')", name="ck_template_versions_upload_status"),
    )
    op.create_index("ix_template_versions_template_id", "template_versions", ["template_id"])

    # templates.current_version_id -> template_versions.id, added after both tables exist
    # to resolve the circular dependency between the two tables.
    op.create_foreign_key(
        "fk_templates_current_version",
        "templates",
        "template_versions",
        ["current_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_templates_current_version", "templates", type_="foreignkey")
    op.drop_index("ix_template_versions_template_id", table_name="template_versions")
    op.drop_table("template_versions")
    op.drop_index("ix_templates_status", table_name="templates")
    op.drop_index("ix_templates_format", table_name="templates")
    op.drop_table("templates")
