"""storage hosts + polymorphic attachments spec 102

Hand-written data step: installs with existing attachments (or jira snapshot
blobs) get ONE storage host row derived from the environment settings —
mirroring `attachments.hosts.seed_values()`, inlined here because migrations
are frozen history and must not track app code. Fresh installs seed at startup
instead. Attachment rows backfill to `entity_type='item'` + that host.

Revision ID: 164d25776678
Revises: 6769faf965b9

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from radd.config import settings

revision = '164d25776678'
down_revision = '6769faf965b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('storage_hosts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('host_type', sa.String(length=20), nullable=False),
    sa.Column('endpoint', sa.String(length=500), nullable=False),
    sa.Column('access_key', sa.String(length=200), nullable=False),
    sa.Column('secret_key', sa.Text(), nullable=False),
    sa.Column('bucket', sa.String(length=200), nullable=False),
    sa.Column('region', sa.String(length=100), nullable=False),
    sa.Column('secure', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('root_dir', sa.String(length=500), nullable=False),
    sa.Column('delivery_mode', sa.String(length=20), nullable=False),
    sa.Column('presign_expiry_seconds', sa.Integer(), nullable=True),
    sa.Column('user_selectable', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_storage_hosts')),
    sa.UniqueConstraint('name', name=op.f('uq_storage_hosts_name'))
    )
    op.create_table('storage_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('rule_type', sa.String(length=20), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_storage_rules'))
    )
    op.create_table('attachment_move_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_host_id', sa.Uuid(), nullable=False),
    sa.Column('target_host_id', sa.Uuid(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('moved', sa.Integer(), nullable=False),
    sa.Column('failed', sa.Integer(), nullable=False),
    sa.Column('problems', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['source_host_id'], ['storage_hosts.id'], name=op.f('fk_attachment_move_jobs_source_host_id_storage_hosts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_host_id'], ['storage_hosts.id'], name=op.f('fk_attachment_move_jobs_target_host_id_storage_hosts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attachment_move_jobs'))
    )

    # --- attachments: nullable-first columns, backfill, then constraints ------
    op.add_column('attachments', sa.Column('entity_type', sa.String(length=50), nullable=True))
    op.add_column('attachments', sa.Column('entity_id', sa.Uuid(), nullable=True))
    op.add_column('attachments', sa.Column('storage_host_id', sa.Uuid(), nullable=True))
    op.add_column('attachments', sa.Column('state', sa.String(length=10), nullable=True))
    op.add_column('jira_snapshot_blobs', sa.Column('storage_host_id', sa.Uuid(), nullable=True))

    bind = op.get_bind()
    has_rows = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM attachments) OR EXISTS (SELECT 1 FROM jira_snapshot_blobs)"
    )).scalar()
    if has_rows:
        host_id = _seed_env_host(bind)
        bind.execute(sa.text(
            "UPDATE attachments SET entity_type = 'item', entity_id = item_id, "
            "storage_host_id = :host, state = 'stored'"
        ), {"host": host_id})
        bind.execute(sa.text(
            "UPDATE jira_snapshot_blobs SET storage_host_id = :host"
        ), {"host": host_id})

    op.alter_column('attachments', 'entity_type', nullable=False)
    op.alter_column('attachments', 'entity_id', nullable=False)
    op.alter_column('attachments', 'storage_host_id', nullable=False)
    op.alter_column('attachments', 'state', nullable=False)
    op.drop_index(op.f('ix_attachments_item_id'), table_name='attachments')
    op.create_index('ix_attachments_entity', 'attachments', ['entity_type', 'entity_id'], unique=False)
    op.create_index(op.f('ix_attachments_storage_host_id'), 'attachments', ['storage_host_id'], unique=False)
    op.drop_constraint(op.f('fk_attachments_item_id_work_items'), 'attachments', type_='foreignkey')
    op.create_foreign_key(op.f('fk_attachments_storage_host_id_storage_hosts'), 'attachments', 'storage_hosts', ['storage_host_id'], ['id'], ondelete='RESTRICT')
    op.drop_column('attachments', 'item_id')
    # False-positive drops stripped (acme_notes example plugin, backup partial
    # indexes, the doc_pages functional FTS index — Alembic can't introspect them).


def _seed_env_host(bind) -> uuid.UUID:
    """One host row from the environment — the frozen twin of hosts.seed_values()."""
    host_id = uuid.uuid4()
    if settings.attachment_storage == 's3':
        row = {
            'id': host_id,
            'name': settings.s3_bucket or 's3',
            'host_type': 's3',
            'endpoint': settings.s3_endpoint,
            'access_key': settings.s3_access_key,
            'secret_key': settings.s3_secret_key,
            'bucket': settings.s3_bucket,
            'region': '',
            'secure': settings.s3_secure,
            'root_dir': '',
            'delivery_mode': 'presigned',  # the spec-33 S3 path always redirected
        }
    else:
        row = {
            'id': host_id,
            'name': 'Local disk',
            'host_type': 'filesystem',
            'endpoint': '',
            'access_key': '',
            'secret_key': '',
            'bucket': '',
            'region': '',
            'secure': False,
            'root_dir': settings.attachments_dir,
            'delivery_mode': 'proxy',
        }
    bind.execute(sa.text(
        "INSERT INTO storage_hosts (id, name, host_type, endpoint, access_key, secret_key,"
        " bucket, region, secure, root_dir, delivery_mode, user_selectable, is_default, source)"
        " VALUES (:id, :name, :host_type, :endpoint, :access_key, :secret_key, :bucket,"
        " :region, :secure, :root_dir, :delivery_mode, false, true, 'env')"
    ), row)
    return host_id


def downgrade() -> None:
    op.drop_column('jira_snapshot_blobs', 'storage_host_id')
    op.add_column('attachments', sa.Column('item_id', sa.UUID(), autoincrement=False, nullable=True))
    op.execute("UPDATE attachments SET item_id = entity_id WHERE entity_type = 'item'")
    op.execute("DELETE FROM attachments WHERE entity_type != 'item'")
    op.alter_column('attachments', 'item_id', nullable=False)
    op.drop_constraint(op.f('fk_attachments_storage_host_id_storage_hosts'), 'attachments', type_='foreignkey')
    op.create_foreign_key(op.f('fk_attachments_item_id_work_items'), 'attachments', 'work_items', ['item_id'], ['id'], ondelete='CASCADE')
    op.drop_index(op.f('ix_attachments_storage_host_id'), table_name='attachments')
    op.drop_index('ix_attachments_entity', table_name='attachments')
    op.create_index(op.f('ix_attachments_item_id'), 'attachments', ['item_id'], unique=False)
    op.drop_column('attachments', 'state')
    op.drop_column('attachments', 'storage_host_id')
    op.drop_column('attachments', 'entity_id')
    op.drop_column('attachments', 'entity_type')
    op.drop_table('attachment_move_jobs')
    op.drop_table('storage_rules')
    op.drop_table('storage_hosts')
