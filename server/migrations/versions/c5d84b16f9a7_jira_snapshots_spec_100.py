"""jira snapshots — cached Jira downloads (spec 100)

The importer becomes cache-first: a JQL result set is downloaded ONCE into
`jira_snapshot_issues`, and profiling, mapping, the dry run, the import, a
re-import and relinking all read those rows instead of Jira. Spec 90 re-paged
Jira on every run, so fixing one mapping mistake meant downloading tens of
thousands of issues again.

Raw issue JSON is stored per row (JSONB, so Postgres TOAST-compresses it) because
the transform is pure and re-runnable — a fix re-reads the ORIGINAL payload rather
than something already lossily interpreted. Attachment BINARIES go to the ordinary
attachment store; `jira_snapshot_blobs` is the index that lets a delete reclaim them.

Revision ID: c5d84b16f9a7
Revises: b3f21a7c8e04

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'c5d84b16f9a7'
down_revision = 'b3f21a7c8e04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jira_snapshots',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('connection_id', sa.Uuid(), nullable=True),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('jira_project_key', sa.String(length=100), nullable=False),
        sa.Column('jql', sa.Text(), nullable=False),
        sa.Column('include_attachments', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('include_history', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('stage', sa.String(length=20), nullable=False),
        sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('problems', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('catalogs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('issue_count', sa.Integer(), nullable=False),
        sa.Column('byte_size', sa.BigInteger(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['connection_id'], ['jira_connections.id'],
            name=op.f('fk_jira_snapshots_connection_id_jira_connections'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['actor_id'], ['users.id'],
            name=op.f('fk_jira_snapshots_actor_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_snapshots')),
    )
    op.create_table(
        'jira_snapshot_issues',
        sa.Column('snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('jira_key', sa.String(length=100), nullable=False),
        sa.Column('jira_id', sa.String(length=30), nullable=False),
        sa.Column('jira_updated_at', sa.DateTime(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ['snapshot_id'], ['jira_snapshots.id'],
            name=op.f('fk_jira_snapshot_issues_snapshot_id_jira_snapshots'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('snapshot_id', 'jira_key', name=op.f('pk_jira_snapshot_issues')),
    )
    op.create_index(
        'ix_jira_snapshot_issues_snapshot', 'jira_snapshot_issues',
        ['snapshot_id', 'jira_key'], unique=False,
    )
    op.create_table(
        'jira_snapshot_blobs',
        sa.Column('snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('jira_attachment_id', sa.String(length=30), nullable=False),
        sa.Column('jira_key', sa.String(length=100), nullable=False),
        sa.Column('storage_name', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=300), nullable=False),
        sa.Column('content_type', sa.String(length=120), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ['snapshot_id'], ['jira_snapshots.id'],
            name=op.f('fk_jira_snapshot_blobs_snapshot_id_jira_snapshots'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'snapshot_id', 'jira_attachment_id', name=op.f('pk_jira_snapshot_blobs'),
        ),
    )
    op.create_index(
        'ix_jira_snapshot_blobs_snapshot', 'jira_snapshot_blobs', ['snapshot_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_jira_snapshot_blobs_snapshot', table_name='jira_snapshot_blobs')
    op.drop_table('jira_snapshot_blobs')
    op.drop_index('ix_jira_snapshot_issues_snapshot', table_name='jira_snapshot_issues')
    op.drop_table('jira_snapshot_issues')
    op.drop_table('jira_snapshots')
