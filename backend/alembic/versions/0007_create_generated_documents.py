"""generated_documents: a document is not a version of its template

`0005` decided not to create this table, reasoning that every *fact* about a
generated document was already recorded across `template_versions`,
`change_specs` and `qa_runs`, and that a third place to write them would create
drift. The facts part was right. What was missing was never a fact, it was a
**distinction** -- and without it "a document somebody made" and "a revision of
the template" became the same row.

The cost of that showed up in the data. `MOM Sample` reached v7 because six
people generated minutes from it; the form itself never changed once. Every one
of those documents landed in doc control's approval queue. And on this database
the template the library serves for `Minutes of Meeting (MOM) Form` is a v2 with
`venue = 'Conference Room 4'` and `date = '2026-08-22'` baked into it: a filled
-in document was approved *as the blank form*, and nothing could notice, because
the schema had no way to say those were different kinds of thing.

So a compile now writes here by default. A document has **no version number**,
never enters the approval queue, and is not a candidate for anything until its
author explicitly submits it -- at which point `promoted_version_id` records
which version it became, and the version carries its own row in
`template_versions` as before.

**Why not a `kind` column on `template_versions` instead.** Because half that
table's meaning would then be conditional: `version_number` and
`approval_status` are required for a revision and meaningless for a document,
`UNIQUE (template_id, version_number)` could not hold, and every query would
have to remember to filter. A separate table makes "documents do not have
version numbers" a fact the database enforces rather than a convention each
query re-implements.

**`base_version_id` is the lineage that matters here.** A document is derived
from the exact bytes of one version, and that is what makes it reproducible and
what tells you it is stale when the template moves on. It is not
`parent_version_id` in the `template_versions` sense, because a document is not
in that lineage at all.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The exact version these bytes were compiled from.
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("change_spec_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        # Set only if the author later submitted this document as a template
        # version. Null is the ordinary case and means "this is somebody's
        # document", not "not yet promoted".
        sa.Column("promoted_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_version_id"], ["template_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["generation_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["change_spec_id"], ["change_specs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["promoted_version_id"], ["template_versions.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("storage_bucket", "storage_key", name="uq_generated_documents_key"),
    )
    op.create_index("ix_generated_documents_template_id", "generated_documents", ["template_id"])
    op.create_index("ix_generated_documents_created_by", "generated_documents", ["created_by"])
    op.create_index("ix_generated_documents_created_at", "generated_documents", ["created_at"])

    # `change_specs.result_version_id` stays as it is: it still points at a
    # version when one was produced. A spec that produced a document now points
    # at that instead, so the two are never both set.
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


def downgrade() -> None:
    op.drop_constraint("fk_change_specs_result_document", "change_specs", type_="foreignkey")
    op.drop_column("change_specs", "result_document_id")
    op.drop_index("ix_generated_documents_created_at", table_name="generated_documents")
    op.drop_index("ix_generated_documents_created_by", table_name="generated_documents")
    op.drop_index("ix_generated_documents_template_id", table_name="generated_documents")
    op.drop_table("generated_documents")
