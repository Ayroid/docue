"""create change_specs and qa_runs; version lineage

Plan §8. `change_specs` is what makes every generated document replayable --
the exact specification that produced it, kept as the JSON it arrived as.
`qa_runs` records the §11 verdict on each compile, with `visual` left null
until LibreOffice and the vision pass exist.

Also adds `template_versions.parent_version_id`, which §8 calls out as the
column that "enables branching, not just a line": a version derived from v1
records v1 as its parent, so two derivations from the same base are siblings
rather than a chain.

Both new tables deviate from §8's DDL in the same way and for the same reason:
they reference the change spec and the version directly rather than going
through `generated_documents`, because that table belongs to the conversational
session flow which does not exist yet. A compile run without a session still
needs an audit trail, and a dry run has QA but no version at all.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "template_versions",
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_template_versions_parent",
        "template_versions",
        "template_versions",
        ["parent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_template_versions_parent_version_id", "template_versions", ["parent_version_id"]
    )

    op.create_table(
        "change_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Nullable: a spec compiled straight against a version has no session.
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("spec_version", sa.String(10), nullable=False),
        # Verbatim, not normalised into operation rows: replay means replaying
        # exactly what arrived.
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tier", sa.String(4), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_version_id"], ["template_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_version_id"], ["template_versions.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('planned', 'compiled', 'committed', 'failed')",
            name="ck_change_specs_status",
        ),
    )
    op.create_index("ix_change_specs_session_id", "change_specs", ["session_id"])
    op.create_index("ix_change_specs_template_id", "change_specs", ["template_id"])
    op.create_index("ix_change_specs_base_version_id", "change_specs", ["base_version_id"])
    op.create_index("ix_change_specs_status", "change_specs", ["status"])

    op.create_table(
        "qa_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("change_spec_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("structural", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("functional", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Null until plan §11 Level 3 exists. An empty column is honest where a
        # hardcoded pass would not be.
        sa.Column("visual", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assertions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("repairs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall", sa.String(10), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["change_spec_id"], ["change_specs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_version_id"], ["template_versions.id"], ondelete="SET NULL"),
        sa.CheckConstraint("overall IN ('pass', 'fail')", name="ck_qa_runs_overall"),
    )
    op.create_index("ix_qa_runs_change_spec_id", "qa_runs", ["change_spec_id"])
    op.create_index("ix_qa_runs_overall", "qa_runs", ["overall"])


def downgrade() -> None:
    op.drop_index("ix_qa_runs_overall", table_name="qa_runs")
    op.drop_index("ix_qa_runs_change_spec_id", table_name="qa_runs")
    op.drop_table("qa_runs")

    op.drop_index("ix_change_specs_status", table_name="change_specs")
    op.drop_index("ix_change_specs_base_version_id", table_name="change_specs")
    op.drop_index("ix_change_specs_template_id", table_name="change_specs")
    op.drop_index("ix_change_specs_session_id", table_name="change_specs")
    op.drop_table("change_specs")

    op.drop_index("ix_template_versions_parent_version_id", table_name="template_versions")
    op.drop_constraint("fk_template_versions_parent", "template_versions", type_="foreignkey")
    op.drop_column("template_versions", "parent_version_id")
