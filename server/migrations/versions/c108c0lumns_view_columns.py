"""view list columns (spec 108)

`views.columns` — ordered LIST-surface column ids (builtin names or
`cf.<key>`); NULL = the view type's default set. Widths stay client-side
(per-user ergonomics). Pure column add.

Revision ID: c108c0lumns
Revises: b107appl1es
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c108c0lumns"
down_revision = "b107appl1es"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "views",
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("views", "columns")
