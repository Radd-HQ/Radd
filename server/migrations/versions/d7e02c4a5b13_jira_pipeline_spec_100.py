"""jira import pipeline — plans, runs, ledger, pending refs (spec 100)

Replaces the spec-90 pair (`jira_import_plans` / `jira_import_runs`), which could
only express per-FIELD mappings and had no provenance at all — a bad import was
unwound with hand-written SQL.

- `jira_plans` binds a plan to a cached SNAPSHOT and holds all nine mapping
  tables (fields + eight vocabularies) in one JSONB document.
- `jira_runs` is one row shape for a dry run, an import and a rollback, because
  they are the same pipeline with `commit` on or off.
- `jira_import_records` is the ledger rollback replays in reverse; the monotonic
  id is load-bearing, since undo order must be the exact inverse of write order.
- `jira_pending_refs` is the cross-project relink queue: a DEV→TD link recorded
  while TD does not exist yet, resolved when TD is imported.

Revision ID: d7e02c4a5b13
Revises: c5d84b16f9a7

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'd7e02c4a5b13'
down_revision = 'c5d84b16f9a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jira_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('radd_project_id', sa.Uuid(), nullable=True),
        sa.Column('radd_project_key', sa.String(length=20), nullable=False),
        sa.Column('radd_project_name', sa.String(length=200), nullable=False),
        sa.Column('mappings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('provisioned_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['snapshot_id'], ['jira_snapshots.id'],
            name=op.f('fk_jira_plans_snapshot_id_jira_snapshots'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['radd_project_id'], ['projects.id'],
            name=op.f('fk_jira_plans_radd_project_id_projects'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_plans')),
        sa.UniqueConstraint('name', name=op.f('uq_jira_plans_name')),
    )
    op.create_table(
        'jira_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('plan_id', sa.Uuid(), nullable=True),
        sa.Column('snapshot_id', sa.Uuid(), nullable=True),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('plan_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('stage', sa.String(length=20), nullable=False),
        sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('problems', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['jira_plans.id'],
                                name=op.f('fk_jira_runs_plan_id_jira_plans'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['jira_snapshots.id'],
                                name=op.f('fk_jira_runs_snapshot_id_jira_snapshots'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'],
                                name=op.f('fk_jira_runs_actor_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                name=op.f('fk_jira_runs_project_id_projects'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_runs')),
    )
    op.create_table(
        'jira_import_records',
        sa.Column('id', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.String(length=40), nullable=False),
        sa.Column('entity_id', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_schema', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['jira_runs.id'],
                                name=op.f('fk_jira_import_records_run_id_jira_runs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_import_records')),
    )
    op.create_index(op.f('ix_jira_import_records_run_id'), 'jira_import_records', ['run_id'])
    op.create_index('ix_jira_import_records_run', 'jira_import_records', ['run_id', 'id'])
    op.create_table(
        'jira_pending_refs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=True),
        sa.Column('source_item_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('target_jira_key', sa.String(length=100), nullable=False),
        sa.Column('link_type', sa.String(length=30), nullable=False),
        sa.Column('inward', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('web_link_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['jira_runs.id'],
                                name=op.f('fk_jira_pending_refs_run_id_jira_runs'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_item_id'], ['work_items.id'],
                                name=op.f('fk_jira_pending_refs_source_item_id_work_items'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_pending_refs')),
    )
    op.create_index(op.f('ix_jira_pending_refs_source_item_id'), 'jira_pending_refs', ['source_item_id'])
    op.create_index('ix_jira_pending_refs_target', 'jira_pending_refs', ['target_jira_key'])

    # The spec-90 pair is superseded: per-field mappings only, and no provenance.
    op.drop_table('jira_import_runs')
    op.drop_table('jira_import_plans')


def downgrade() -> None:
    op.drop_index('ix_jira_pending_refs_target', table_name='jira_pending_refs')
    op.drop_index(op.f('ix_jira_pending_refs_source_item_id'), table_name='jira_pending_refs')
    op.drop_table('jira_pending_refs')
    op.drop_index('ix_jira_import_records_run', table_name='jira_import_records')
    op.drop_index(op.f('ix_jira_import_records_run_id'), table_name='jira_import_records')
    op.drop_table('jira_import_records')
    op.drop_table('jira_runs')
    op.drop_table('jira_plans')
