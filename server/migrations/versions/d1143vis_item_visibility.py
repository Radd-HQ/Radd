"""d1143vis: work_items.visibility + its search_index mirror (spec 121 §3, RADD-1143)

`public` (default, backfilled — everything an existing project shows today
stays visible to exactly the people who saw it) | `internal` | `restricted`.
The search mirror carries the column so FTS and the semantic pool can apply
the row guard without joining work_items (the d841 rule).

Revision ID: d1143vis
Revises: d1142princ
Create Date: 2026-09-13
"""

import sqlalchemy as sa
from alembic import op

revision = "d1143vis"
down_revision = "d1142princ"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
    )
    op.create_index("ix_work_items_visibility", "work_items", ["visibility"])
    op.add_column(
        "search_index",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
    )


def downgrade() -> None:
    op.drop_column("search_index", "visibility")
    op.drop_index("ix_work_items_visibility", table_name="work_items")
    op.drop_column("work_items", "visibility")
