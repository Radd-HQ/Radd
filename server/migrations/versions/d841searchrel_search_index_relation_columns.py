"""d841searchrel: search_index carries relation columns (RADD-841)

`reporter_id`/`assignee_id`/`team_id` join the denormalized row so a
relation-scoped actor (item.read@own/@team, RADD-823) can filter FTS results
without joining work_items per query. Mirrors, not owners — no FKs; the
indexer and its startup sweep keep them in step. Backfilled here from
work_items so existing rows carry them immediately (a full replay would too,
but nobody should have to reindex to get correct access answers).

Revision ID: d841searchrel
Revises: d832grpsubj
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'd841searchrel'
down_revision = 'd832grpsubj'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('search_index', sa.Column('reporter_id', sa.Uuid(), nullable=True))
    op.add_column('search_index', sa.Column('assignee_id', sa.Uuid(), nullable=True))
    op.add_column('search_index', sa.Column('team_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_search_index_reporter_id'), 'search_index', ['reporter_id'])
    op.create_index(op.f('ix_search_index_assignee_id'), 'search_index', ['assignee_id'])
    op.create_index(op.f('ix_search_index_team_id'), 'search_index', ['team_id'])
    op.execute(
        """
        UPDATE search_index si SET
            reporter_id = wi.reporter_id,
            assignee_id = wi.assignee_id,
            team_id = wi.team_id
        FROM work_items wi
        WHERE wi.id = si.item_id
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_search_index_team_id'), table_name='search_index')
    op.drop_index(op.f('ix_search_index_assignee_id'), table_name='search_index')
    op.drop_index(op.f('ix_search_index_reporter_id'), table_name='search_index')
    op.drop_column('search_index', 'team_id')
    op.drop_column('search_index', 'assignee_id')
    op.drop_column('search_index', 'reporter_id')
