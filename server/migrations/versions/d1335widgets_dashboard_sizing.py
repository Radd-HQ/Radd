"""Fine dashboard sizing, preserving the previous thirds arrangement."""

from alembic import op
import sqlalchemy as sa

revision = "d1335widgets"
down_revision = "d1334review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "dashboard_widgets", sa.Column("height", sa.Integer(), nullable=False, server_default="360")
    )
    op.add_column(
        "dashboard_widgets",
        sa.Column("collapsed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE dashboard_widgets SET width = width * 4")


def downgrade():
    op.execute(
        "UPDATE dashboard_widgets SET width = LEAST(3, GREATEST(1, CEIL(width / 4.0)::integer))"
    )
    op.drop_column("dashboard_widgets", "collapsed")
    op.drop_column("dashboard_widgets", "height")
