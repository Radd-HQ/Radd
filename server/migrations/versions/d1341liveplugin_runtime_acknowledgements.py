"""Leased plugin runtime acknowledgements across replicas."""
from alembic import op
import sqlalchemy as sa

revision = 'd1341liveplugin'
down_revision = 'd1336signatures'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('plugin_processes',
                    sa.Column('process_id', sa.String(200), primary_key=True),
                    sa.Column('report', sa.JSON(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('plugin_processes')
