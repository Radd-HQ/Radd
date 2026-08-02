"""events.silent — quiet-scope flag for bulk imports (spec 100)

Marks an event as emitted inside `events.quiet()`. Consumers that reach OUTSIDE
the instance (notify, webhooks, automations, realtime, and everything on the
head-seeded delivery scaffold) skip these rows; the search index and the
activity/history feed still consume them, so an imported issue is findable and
has history.

`server_default=false()` rather than a backfill: every existing row predates the
flag and none of them were imports.

Revision ID: a1c7e9d40b52
Revises: 14f8b70e554f

"""
import sqlalchemy as sa
from alembic import op

revision = 'a1c7e9d40b52'
down_revision = '14f8b70e554f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'events',
        sa.Column('silent', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('events', 'silent')
