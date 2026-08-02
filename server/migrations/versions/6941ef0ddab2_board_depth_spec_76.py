"""board depth (spec 76)

WIP limits + issue templates + epic rollup: `views.wip_limits` (nullable JSONB
{state_id: int>=1} — soft state-axis board column limits) and
`issue_types.description_template` (nullable TEXT — markdown prefilled into the
new-item description). The rollup endpoint is read-only (no schema).

Revision ID: 6941ef0ddab2
Revises: 9176930be113

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '6941ef0ddab2'
down_revision = '9176930be113'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('issue_types', sa.Column('description_template', sa.Text(), nullable=True))
    op.add_column('views', sa.Column('wip_limits', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('views', 'wip_limits')
    op.drop_column('issue_types', 'description_template')
