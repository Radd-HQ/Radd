"""leave periods + team holidays

Revision ID: 87ca350e4aef
Revises: acca7433a9b7

Hand-trimmed from autogenerate: the tool also proposed dropping the
runtime-managed embeddings tables (deliberately outside Base.metadata), the
disabled acme-notes plugin's table, and several expression indexes it cannot
see — all noise, all removed. Only leave_periods belongs to this revision.
"""
from alembic import op
import sqlalchemy as sa

revision = '87ca350e4aef'
down_revision = 'acca7433a9b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('leave_periods',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('team_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(user_id IS NULL) <> (team_id IS NULL)', name=op.f('ck_leave_periods_ck_leave_one_subject')),
    sa.CheckConstraint('start_date <= end_date', name=op.f('ck_leave_periods_ck_leave_dates_ordered')),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_leave_periods_team_id_teams'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_leave_periods_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leave_periods'))
    )
    op.create_index(op.f('ix_leave_periods_end_date'), 'leave_periods', ['end_date'], unique=False)
    op.create_index(op.f('ix_leave_periods_start_date'), 'leave_periods', ['start_date'], unique=False)
    op.create_index(op.f('ix_leave_periods_team_id'), 'leave_periods', ['team_id'], unique=False)
    op.create_index(op.f('ix_leave_periods_user_id'), 'leave_periods', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leave_periods_user_id'), table_name='leave_periods')
    op.drop_index(op.f('ix_leave_periods_team_id'), table_name='leave_periods')
    op.drop_index(op.f('ix_leave_periods_start_date'), table_name='leave_periods')
    op.drop_index(op.f('ix_leave_periods_end_date'), table_name='leave_periods')
    op.drop_table('leave_periods')
