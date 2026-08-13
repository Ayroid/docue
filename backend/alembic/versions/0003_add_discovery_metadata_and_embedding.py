"""add generated discovery metadata, tags and the pgvector embedding

Plan §8 and §9, Track B. The columns a searcher actually matches against.

**What gets embedded is the generated metadata, not the document.** That is the
plan's §9 argument and it decides this schema: there is one vector per
*template*, on `templates`, rather than a chunk table keyed to document text. A
template's body is either boilerplate or one project's specifics -- the BFL's is
thirty rows of Fit/Gap classifications -- so a chunk index matches nothing a
searcher types, and its highlights explain nothing when shown.

Three indexes, one per retrieval signal:

* **HNSW over `embedding`** with `vector_cosine_ops`, because Cohere embeddings
  are normalised and cosine is the metric they are trained for.
* **GIN over the tsvector** of the text a searcher's words land in. `form_id` is
  in it deliberately: `YMSLI-F-MOM` is the strongest lexical term in the corpus
  and exactly the acronym case §9 says embeddings handle worst.
* **GIN over `tags`** for filtering by tag without a scan.

The tsvector index is an expression index rather than a stored column: it stays
correct when any of its inputs is updated, with nothing to keep in sync.

`vector(1024)` matches what `cohere.embed-v4:0` was measured to return at
`output_dimension=1024` -- v4 is Matryoshka-trained, so that width is a
supported output and not a truncation. Changing the width means re-embedding
every row, so it is pinned here and asserted in `app/ai/bedrock.py::embed`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 1024

# What a query's words are matched against. Weighted: a hit in the title or the
# form id should outrank the same word buried in a purpose statement.
#
# `tags` is deliberately absent. Postgres requires every function in an index
# expression to be IMMUTABLE, and `array_to_string` is only STABLE -- including
# it makes `CREATE INDEX` fail outright with "functions in index expression must
# be marked IMMUTABLE". The workaround is an IMMUTABLE SQL wrapper, and it isn't
# worth it: tags are matched through the GIN index on the array itself, they are
# already part of the embedded text, and in the generated corpus the tag terms
# also appear in the title or purpose ("BFL" is in "Business Function List (BFL)
# Template"). So the lexical signal loses nothing real.
_TSVECTOR = """
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(form_id, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(purpose, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(when_to_use, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(category, '')), 'C')
"""


def upgrade() -> None:
    # Already installed on the shared RDS (0.8.1), but a fresh database needs
    # it and the migration has to stand on its own.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("templates", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("templates", sa.Column("when_to_use", sa.Text(), nullable=True))
    op.add_column("templates", sa.Column("audience", sa.Text(), nullable=True))
    op.add_column("templates", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column(
        "templates",
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "templates",
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
    )
    # Which model and prompt produced the metadata above. Without it, a
    # re-generated corpus is indistinguishable from a stale one, and there is no
    # way to tell which rows need re-embedding after a prompt change.
    op.add_column(
        "templates", sa.Column("metadata_model", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "templates", sa.Column("metadata_prompt_version", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "templates", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.execute(
        "CREATE INDEX ix_templates_embedding_hnsw ON templates "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(f"CREATE INDEX ix_templates_search_tsv ON templates USING gin (({_TSVECTOR}))")
    op.create_index("ix_templates_tags", "templates", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_templates_tags", table_name="templates")
    op.execute("DROP INDEX IF EXISTS ix_templates_search_tsv")
    op.execute("DROP INDEX IF EXISTS ix_templates_embedding_hnsw")
    for column in (
        "embedded_at",
        "metadata_prompt_version",
        "metadata_model",
        "embedding",
        "tags",
        "category",
        "audience",
        "when_to_use",
        "purpose",
    ):
        op.drop_column("templates", column)
    # The extension is deliberately left installed: other things may use it, and
    # dropping it would cascade to any other vector column in the database.
