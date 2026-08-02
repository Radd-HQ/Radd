"""sla priorities position business hours spec 63

Revision ID: fb577d3807f9
Revises: 7be36ff1ac2c

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'fb577d3807f9'
down_revision = '7be36ff1ac2c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (stripped: autogenerate's known ix_doc_pages_fts false-positive drop)
    op.add_column('sla_policies', sa.Column('priorities', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('sla_policies', sa.Column('position', sa.Integer(), server_default='0', nullable=False))
    op.add_column('sla_policies', sa.Column('business_start_minute', sa.Integer(), nullable=True))
    op.add_column('sla_policies', sa.Column('business_end_minute', sa.Integer(), nullable=True))
    # Backfill first-match order by name (per workspace) so existing policies keep
    # a stable, predictable ordering under spec 63's first-match resolution.
    op.execute(
        """
        UPDATE sla_policies SET position = numbered.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY workspace_id ORDER BY name, id) - 1 AS rn
            FROM sla_policies
        ) AS numbered
        WHERE sla_policies.id = numbered.id
        """
    )


def downgrade() -> None:
    op.drop_column('sla_policies', 'business_end_minute')
    op.drop_column('sla_policies', 'business_start_minute')
    op.drop_column('sla_policies', 'position')
    op.drop_column('sla_policies', 'priorities')
