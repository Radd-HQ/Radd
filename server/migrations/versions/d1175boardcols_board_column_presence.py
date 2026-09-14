"""RADD-1175: board column presence lives on the view

A state-axis board rendered every state as a column whether or not it held an
item, and nothing on the view could change that. Two columns, both shared shape
like `column_order` (never a personal preference): `collapse_empty_columns`
turns an empty bucket into a narrow rail that is still a drop target, and
`hidden_columns` names bucket keys the view never shows. Loosely validated
lists, so a departed state degrades to an ignored key.

Revision ID: d1175boardcols
Revises: d123ledger
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1175boardcols"
down_revision = "d123ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "views",
        sa.Column(
            "collapse_empty_columns", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "views",
        sa.Column("hidden_columns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("views", "hidden_columns")
    op.drop_column("views", "collapse_empty_columns")
