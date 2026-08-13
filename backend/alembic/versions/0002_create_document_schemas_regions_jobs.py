"""create document_schemas, document_regions and jobs; harvest columns

Plan §8, Track A. Adds the three tables ingestion writes, plus the four columns
that let ingestion keep what detection already finds and currently throws away:
`templates.form_id`, `templates.house_pattern`,
`template_versions.in_doc_version` and `template_versions.fingerprint`.

`document_schemas` and `document_regions` hang off `version_id`, never
`template_id` -- v2 of a template may have regions v1 didn't, so a schema
belongs to the bytes it was read from.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── harvest columns on the existing tables ────────────────────────────
    op.add_column("templates", sa.Column("form_id", sa.String(100), nullable=True))
    op.add_column("templates", sa.Column("house_pattern", sa.String(50), nullable=True))
    op.create_index("ix_templates_form_id", "templates", ["form_id"])

    op.add_column(
        "template_versions", sa.Column("in_doc_version", sa.String(30), nullable=True)
    )
    op.add_column(
        "template_versions",
        sa.Column("fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # ── document_schemas ─────────────────────────────────────────────────
    op.create_table(
        "document_schemas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detector_version", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["version_id"], ["template_versions.id"], ondelete="CASCADE"),
        # One schema per version: re-ingesting replaces it rather than adding one.
        sa.UniqueConstraint("version_id", name="uq_document_schemas_version_id"),
    )
    op.create_index("ix_document_schemas_version_id", "document_schemas", ["version_id"])

    # ── document_regions ─────────────────────────────────────────────────
    op.create_table(
        "document_regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("semantic_role", sa.String(100), nullable=True),
        sa.Column("value_type", sa.String(20), nullable=True),
        # Polymorphic by design: {sheet, ref} | {para_index, run_span} |
        # {slide_index, shape_id}. Three sets of typed columns would be mostly
        # null in every row.
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_content", sa.Text(), nullable=True),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("derivable_from", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("row_template_ref", sa.String(200), nullable=True),
        sa.Column("detection_method", sa.String(30), nullable=False),
        sa.Column("question_group", sa.Integer(), nullable=True),
        # The detector's own ordinal, which restarts per sheet and is therefore
        # not a total order, plus the document-wide position that is.
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        # Not decoration: carries a table's `columns` and `template_row`, a
        # block's `insert_at_row`, the docx caption's `caption_count_template`.
        # The compiler bridge reads it, so a schema without it is readable but
        # not usable. An addition to §8's DDL, which predates detector notes.
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["version_id"], ["template_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("version_id", "region_id", name="uq_document_regions_version_region"),
    )
    op.create_index("ix_document_regions_version_id", "document_regions", ["version_id"])
    op.create_index("ix_document_regions_kind", "document_regions", ["kind"])
    # Plan §8: the question planner pulls a version's regions grouped by the
    # question that covers them.
    op.create_index(
        "ix_document_regions_version_question_group",
        "document_regions",
        ["version_id", "question_group"],
    )

    # ── jobs ─────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        # Deliberately not a foreign key: a job outlives what it refers to, and
        # the ingestion log should stay readable after a version is deleted.
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(40), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress"),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_entity_id", "jobs", ["entity_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_entity_id", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_document_regions_version_question_group", table_name="document_regions")
    op.drop_index("ix_document_regions_kind", table_name="document_regions")
    op.drop_index("ix_document_regions_version_id", table_name="document_regions")
    op.drop_table("document_regions")

    op.drop_index("ix_document_schemas_version_id", table_name="document_schemas")
    op.drop_table("document_schemas")

    op.drop_column("template_versions", "fingerprint")
    op.drop_column("template_versions", "in_doc_version")

    op.drop_index("ix_templates_form_id", table_name="templates")
    op.drop_column("templates", "house_pattern")
    op.drop_column("templates", "form_id")
