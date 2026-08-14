"""create generation_sessions and question_plans

Plan §8's generation tables, and the point at which `change_specs.session_id`
stops being null. `0004` left that column nullable and unconstrained precisely
because this table did not exist yet; it now has something to point at, and a
foreign key is added to say so.

**Why `question_plans` hangs off `version_id` rather than a session.** Plan §10
④ describes the question plan as *cached per version*, and that is the whole
value of the table: the second session started against the same version costs
zero planner calls. It is also the Bedrock-outage story from §14 -- a plan that
was computed once survives the model being unavailable later, which matters
more on a demo day than it does in production.

`covers_regions` is a real `TEXT[]`, not JSONB. It is only ever read as a list
of ids and compared against the schema, and an array column can be indexed and
queried with `&&` if the review screen ever needs "which question covered this
region".

Two deviations from §8's DDL, both deliberate:

* `user_id` is nullable and carries no foreign key. There is no `users` table
  and no auth; a not-null column would have to be filled with a fabricated id
  on every insert, which is worse than an honest null.
* `generated_documents` is **not** created here. Every column §8 puts on it --
  the storage key, the format, the base and result versions, the QA verdict --
  is already recorded across `template_versions`, `change_specs` and `qa_runs`
  by the compile path that shipped in `0004`. Adding a third place to write the
  same facts would create exactly the drift `change_specs` exists to prevent.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        # No users table yet. Null rather than a fabricated id.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tier", sa.String(4), nullable=False, server_default="T2"),
        sa.Column("user_intent", sa.Text(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        # The context agent's partition of every region into known / must_ask /
        # inferable / not_applicable, kept so a resumed session does not re-run
        # the stage and possibly partition differently.
        sa.Column("known_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # {region_id: value} from the extractor, and from the deriver. Kept
        # apart because the split is what the review screen badges on: typed
        # values and inferred ones are not the same claim.
        sa.Column("filled_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("derived_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # The transcript: one entry per answered question, with what was
        # extracted from it. This is what makes a session resumable and what
        # `GET /sessions/{sid}` replays into the chat.
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_version_id"], ["template_versions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('active', 'planned', 'compiled', 'committed', 'abandoned')",
            name="ck_generation_sessions_status",
        ),
        sa.CheckConstraint("tier IN ('T1', 'T2', 'T3')", name="ck_generation_sessions_tier"),
    )
    op.create_index("ix_generation_sessions_template_id", "generation_sessions", ["template_id"])
    op.create_index(
        "ix_generation_sessions_base_version_id", "generation_sessions", ["base_version_id"]
    )
    op.create_index("ix_generation_sessions_status", "generation_sessions", ["status"])

    op.create_table(
        "question_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_no", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("example", sa.Text(), nullable=True),
        # The region cluster this one question covers. Every id in here was
        # checked against the version's schema before the row was written --
        # the planner may not invent targets (contract C5).
        sa.Column(
            "covers_regions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("planner_version", sa.String(50), nullable=True),
        sa.Column(
            "cached_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["version_id"], ["template_versions.id"], ondelete="CASCADE"),
        # One plan per version, so a cache read is unambiguous and a second
        # planner run cannot leave two half-plans interleaved.
        sa.UniqueConstraint("version_id", "question_no", name="uq_question_plans_version_question"),
    )
    op.create_index("ix_question_plans_version_id", "question_plans", ["version_id"])

    # `0004` created this column with nothing to reference. Now there is.
    op.create_foreign_key(
        "fk_change_specs_session",
        "change_specs",
        "generation_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_change_specs_session", "change_specs", type_="foreignkey")

    op.drop_index("ix_question_plans_version_id", table_name="question_plans")
    op.drop_table("question_plans")

    op.drop_index("ix_generation_sessions_status", table_name="generation_sessions")
    op.drop_index("ix_generation_sessions_base_version_id", table_name="generation_sessions")
    op.drop_index("ix_generation_sessions_template_id", table_name="generation_sessions")
    op.drop_table("generation_sessions")
