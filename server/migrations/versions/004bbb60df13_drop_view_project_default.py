"""drop view project_default

The surface-designation concept is retired (user direction: projects just ship
with seeded default views — no backing/reference layer, no delete protection).
The seeded Board/List/Planning rows stay as plain views; only the marker
column goes.

Revision ID: 004bbb60df13
Revises: 62681dd4006c

"""
from alembic import op
import sqlalchemy as sa


revision = '004bbb60df13'
down_revision = '62681dd4006c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('views', 'project_default')


def downgrade() -> None:
    op.add_column('views', sa.Column('project_default', sa.String(length=10), nullable=True))
