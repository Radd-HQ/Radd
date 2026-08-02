"""backup schedules and runs (spec 99)

The artifacts themselves are NOT tabled: a restore rewrites the database, so a
table listing backups would roll its own inventory back with it. The directory is
the inventory (`radd/backup/store.py`); only configuration and history live here.

Autogenerate also proposed dropping `acme_notes` (the example plugin's table,
present in a dev database but not in the loaded model set) and the `doc_pages`
FTS expression index (hand-built, invisible to autogenerate). Both were removed
by hand — neither has anything to do with this change.

Revision ID: 14f8b70e554f
Revises: ef4be162afa1

"""
import sqlalchemy as sa
from alembic import op

revision = '14f8b70e554f'
down_revision = 'ef4be162afa1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'backup_schedules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('include_attachments', sa.Boolean(), nullable=False),
        sa.Column('keep_last', sa.Integer(), nullable=True),
        sa.Column('keep_days', sa.Integer(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=20), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['created_by_id'], ['users.id'],
            name=op.f('fk_backup_schedules_created_by_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_backup_schedules')),
    )
    op.create_index(
        op.f('ix_backup_schedules_due'), 'backup_schedules', ['next_run_at'],
        unique=False, postgresql_where=sa.text('enabled'),
    )
    op.create_table(
        'backup_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stage', sa.String(length=30), nullable=False),
        sa.Column('artifact_name', sa.String(length=120), nullable=True),
        # BigInteger: an artifact can exceed 2 GB, which Integer cannot hold.
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('schedule_id', sa.Uuid(), nullable=True),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['actor_id'], ['users.id'],
            name=op.f('fk_backup_runs_actor_id_users'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['schedule_id'], ['backup_schedules.id'],
            name=op.f('fk_backup_runs_schedule_id_backup_schedules'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_backup_runs')),
    )
    op.create_index(
        op.f('ix_backup_runs_started_at'), 'backup_runs', ['started_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_backup_runs_started_at'), table_name='backup_runs')
    op.drop_table('backup_runs')
    op.drop_index(op.f('ix_backup_schedules_due'), table_name='backup_schedules')
    op.drop_table('backup_schedules')
