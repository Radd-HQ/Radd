"""card designer (spec 109)

`views.card_layout` — the board-card layout ({v, cells, max_labels}); NULL =
the view type's default card. Plus `card_layout_presets`, the shared instance
library of named layouts (copy-on-apply).

Revision ID: d109cardlay
Revises: c108c0lumns
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d109cardlay"
down_revision = "c108c0lumns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "views",
        sa.Column("card_layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "card_layout_presets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_layout_presets")),
    )


def downgrade() -> None:
    op.drop_table("card_layout_presets")
    op.drop_column("views", "card_layout")
