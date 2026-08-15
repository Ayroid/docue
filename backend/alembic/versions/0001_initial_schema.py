"""initial schema -- squashed baseline

A single fresh baseline replacing what used to be eight migrations
(0001-0008, including a duplicate-revision merge from two independently
written `0005_*` files). Written for local-only development, where every
run starts against an empty database and there is no production history to
preserve -- so the old incremental story (harvest columns added in 0002,
discovery metadata in 0003, auth bolted on in 0005_auth while conversation
tables landed in a sibling 0005, generated_documents carved out in 0007,
visibility/grants in 0008) is collapsed into the one shape those migrations
converged on, verified column-for-column against every model in
`app/models/`.

Two genuinely circular FK pairs from the original history are preserved
exactly as they were resolved there, because collapsing history doesn't
remove the cycle:

  * `templates.current_version_id` <-> `template_versions.id`: templates
    is created first with the column nullable and no FK, template_versions
    is created next (it can reference templates.id immediately), then the
    FK back onto templates is bolted on.
  * `change_specs.result_document_id` <-> `generated_documents.id`:
    change_specs is created first without that column, generated_documents
    is created next (it can reference change_specs.id immediately via
    change_spec_id), then the column + FK is bolted onto change_specs.

Every other foreign key is created inline because this migration is free to
choose a creation order with no other cycles in it -- unlike the original
history, which had to introduce `generation_sessions` after `change_specs`
already existed and therefore needed a deferred `fk_change_specs_session`.

No native Postgres ENUM types anywhere: every status/kind/role/permission
field is a plain VARCHAR plus a named CHECK constraint, so there is no
`CREATE TYPE`/`checkfirst` concern to manage here.

Revision ID: 0001
Revises:
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 1024

# What a query's words are matched against. Weighted: a hit in the title or
# the form id should outrank the same word buried in a purpose statement.
# Kept in sync with `app/search/hybrid.py`, which references this migration
# by name in a comment.
_TSVECTOR = """
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(form_id, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(purpose, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(when_to_use, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(category, '')), 'C')
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── users ───────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled')", name="ck_users_status"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    # ── templates ───────────────────────────────────────────────────────
    # current_version_id is nullable with no FK yet -- template_versions
    # doesn't exist until the next statement. Bolted on below.
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("form_id", sa.String(100), nullable=True),
        sa.Column("house_pattern", sa.String(50), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("when_to_use", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("metadata_model", sa.String(100), nullable=True),
        sa.Column("metadata_prompt_version", sa.String(50), nullable=True),
        sa.Column("embedded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("format IN ('xlsx', 'docx', 'pptx')", name="ck_templates_format"),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_templates_status"),
        sa.CheckConstraint("visibility IN ('public', 'restricted')", name="ck_templates_visibility"),
    )
    op.create_index("ix_templates_format", "templates", ["format"])
    op.create_index("ix_templates_status", "templates", ["status"])
    op.create_index("ix_templates_form_id", "templates", ["form_id"])
    op.create_index("ix_templates_owner_id", "templates", ["owner_id"])
    op.create_index("ix_templates_tags", "templates", ["tags"], postgresql_using="gin")
    # Partial: `public` is the overwhelming majority and never the selective
    # half of a query -- only useful for finding the restricted ones.
    op.create_index(
        "ix_templates_restricted",
        "templates",
        ["visibility"],
        postgresql_where=sa.text("visibility = 'restricted'"),
    )
    op.execute(
        "CREATE INDEX ix_templates_embedding_hnsw ON templates "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(f"CREATE INDEX ix_templates_search_tsv ON templates USING gin (({_TSVECTOR}))")

    # ── template_versions ───────────────────────────────────────────────
    op.create_table(
        "template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("upload_status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("in_doc_version", sa.String(30), nullable=True),
        sa.Column("fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # A fresh DB has no existing rows to backfill, so this goes straight
        # to the application default ("pending") instead of the historical
        # two-step add-as-"approved"-then-alter-to-"pending" dance.
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "version_number", name="uq_template_versions_template_id_version_number"),
        sa.UniqueConstraint("storage_bucket", "storage_key", name="uq_template_versions_bucket_key"),
        sa.CheckConstraint("upload_status IN ('uploaded', 'failed')", name="ck_template_versions_upload_status"),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_template_versions_approval_status",
        ),
    )
    op.create_index("ix_template_versions_template_id", "template_versions", ["template_id"])
    op.create_index("ix_template_versions_parent_version_id", "template_versions", ["parent_version_id"])
    op.create_index("ix_template_versions_approval_status", "template_versions", ["approval_status"])
    op.create_index("ix_template_versions_submitted_by", "template_versions", ["submitted_by"])

    # templates.current_version_id -> template_versions.id, bolted on now
    # that both tables exist -- resolves the one genuine circular pair.
    op.create_foreign_key(
        "fk_templates_current_version",
        "templates",
        "template_versions",
        ["current_version_id"],
        ["id"],
    )

    # ── document_schemas ────────────────────────────────────────────────
    op.create_table(
        "document_schemas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detector_version", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        # One schema per version: re-ingesting replaces it rather than adding one.
        sa.UniqueConstraint("version_id", name="uq_document_schemas_version_id"),
    )
    op.create_index("ix_document_schemas_version_id", "document_schemas", ["version_id"])

    # ── document_regions ────────────────────────────────────────────────
    op.create_table(
        "document_regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("semantic_role", sa.String(100), nullable=True),
        sa.Column("value_type", sa.String(20), nullable=True),
        # Polymorphic by design: {sheet, ref} | {para_index, run_span} |
        # {slide_index, shape_id}. Three sets of typed columns would be
        # mostly null in every row.
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_content", sa.Text(), nullable=True),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("derivable_from", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("row_template_ref", sa.String(200), nullable=True),
        sa.Column("detection_method", sa.String(30), nullable=False),
        sa.Column("question_group", sa.Integer(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("version_id", "region_id", name="uq_document_regions_version_region"),
    )
    op.create_index("ix_document_regions_version_id", "document_regions", ["version_id"])
    op.create_index("ix_document_regions_kind", "document_regions", ["kind"])
    op.create_index(
        "ix_document_regions_version_question_group",
        "document_regions",
        ["version_id", "question_group"],
    )

    # ── jobs ────────────────────────────────────────────────────────────
    # Deliberately no FK on entity_id: a job outlives what it refers to, and
    # the ingestion log should stay readable after a version is deleted.
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(40), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress"),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_entity_id", "jobs", ["entity_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    # ── generation_sessions ─────────────────────────────────────────────
    op.create_table(
        "generation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tier", sa.String(4), nullable=False, server_default="T2"),
        sa.Column("user_intent", sa.Text(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("known_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("filled_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("derived_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'planned', 'compiled', 'committed', 'abandoned')",
            name="ck_generation_sessions_status",
        ),
        sa.CheckConstraint("tier IN ('T1', 'T2', 'T3')", name="ck_generation_sessions_tier"),
    )
    op.create_index("ix_generation_sessions_template_id", "generation_sessions", ["template_id"])
    op.create_index("ix_generation_sessions_base_version_id", "generation_sessions", ["base_version_id"])
    op.create_index("ix_generation_sessions_status", "generation_sessions", ["status"])

    # ── question_plans ──────────────────────────────────────────────────
    op.create_table(
        "question_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_no", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("covers_regions", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("planner_version", sa.String(50), nullable=True),
        sa.Column("cached_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        # One plan per version, so a cache read is unambiguous.
        sa.UniqueConstraint("version_id", "question_no", name="uq_question_plans_version_question"),
    )
    op.create_index("ix_question_plans_version_id", "question_plans", ["version_id"])

    # ── change_specs ────────────────────────────────────────────────────
    # result_document_id is not here yet -- generated_documents doesn't
    # exist until the next statement. Bolted on below (the other genuine
    # circular pair).
    op.create_table(
        "change_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "result_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("spec_version", sa.String(10), nullable=False),
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tier", sa.String(4), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('planned', 'compiled', 'committed', 'failed')",
            name="ck_change_specs_status",
        ),
    )
    op.create_index("ix_change_specs_session_id", "change_specs", ["session_id"])
    op.create_index("ix_change_specs_template_id", "change_specs", ["template_id"])
    op.create_index("ix_change_specs_base_version_id", "change_specs", ["base_version_id"])
    op.create_index("ix_change_specs_status", "change_specs", ["status"])

    # ── qa_runs ─────────────────────────────────────────────────────────
    op.create_table(
        "qa_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "change_spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_specs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "result_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("structural", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("functional", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("visual", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assertions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("repairs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall", sa.String(10), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("overall IN ('pass', 'fail')", name="ck_qa_runs_overall"),
    )
    op.create_index("ix_qa_runs_change_spec_id", "qa_runs", ["change_spec_id"])
    op.create_index("ix_qa_runs_overall", "qa_runs", ["overall"])

    # ── generated_documents ─────────────────────────────────────────────
    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "change_spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_specs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "promoted_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("storage_bucket", "storage_key", name="uq_generated_documents_key"),
    )
    op.create_index("ix_generated_documents_template_id", "generated_documents", ["template_id"])
    op.create_index("ix_generated_documents_created_by", "generated_documents", ["created_by"])
    op.create_index("ix_generated_documents_created_at", "generated_documents", ["created_at"])

    # change_specs.result_document_id -> generated_documents.id, bolted on
    # now that both tables exist -- resolves the other circular pair.
    op.add_column(
        "change_specs",
        sa.Column("result_document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_change_specs_result_document",
        "change_specs",
        "generated_documents",
        ["result_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── email_otps ──────────────────────────────────────────────────────
    op.create_table(
        "email_otps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        # sha256 of the code -- the plaintext is never stored.
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')", name="ck_email_otps_purpose"
        ),
    )
    op.create_index("ix_email_otps_user_id", "email_otps", ["user_id"])
    op.create_index("ix_email_otps_purpose", "email_otps", ["purpose"])

    # ── notifications ───────────────────────────────────────────────────
    # template_id/version_id deliberately not FKs: a notification is a
    # record of what was said and should survive the template it refers to.
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    # The bell polls "unread, newest first" on every page load.
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    # ── template_grants ─────────────────────────────────────────────────
    op.create_table(
        "template_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(20), nullable=False, server_default="view"),
        sa.Column(
            "granted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("permission IN ('view', 'manage')", name="ck_template_grants_permission"),
        sa.UniqueConstraint("template_id", "user_id", name="uq_template_grants_template_user"),
    )
    op.create_index("ix_template_grants_template_user", "template_grants", ["template_id", "user_id"])
    op.create_index("ix_template_grants_user_id", "template_grants", ["user_id"])


def downgrade() -> None:
    op.drop_table("template_grants")
    op.drop_table("notifications")
    op.drop_table("email_otps")
    op.drop_constraint("fk_change_specs_result_document", "change_specs", type_="foreignkey")
    op.drop_column("change_specs", "result_document_id")
    op.drop_table("generated_documents")
    op.drop_table("qa_runs")
    op.drop_table("change_specs")
    op.drop_table("question_plans")
    op.drop_table("generation_sessions")
    op.drop_table("jobs")
    op.drop_table("document_regions")
    op.drop_table("document_schemas")
    op.drop_constraint("fk_templates_current_version", "templates", type_="foreignkey")
    op.drop_table("template_versions")
    op.drop_table("templates")
    op.drop_table("users")
    # The extension is deliberately left installed: dropping it would cascade
    # to any other vector column in the database.
