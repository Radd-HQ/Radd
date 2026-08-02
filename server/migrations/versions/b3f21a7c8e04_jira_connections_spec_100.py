"""jira_connections — admin-managed Jira instances (spec 100)

Replaces the env-only configuration of spec 90, which could name exactly one
instance and needed a redeploy to change (including to fix a typo in the URL).
`jiraimport.connections.seed_from_env` turns an existing RADD_JIRA_* environment
into a row on first startup, so deployed instances keep working untouched.

The credential is stored as-is because a PAT must be replayable to sign every
request — same precedent and same caveat as `webhook_endpoints.secret`.

Revision ID: b3f21a7c8e04
Revises: a1c7e9d40b52

"""
import sqlalchemy as sa
from alembic import op

revision = 'b3f21a7c8e04'
down_revision = 'a1c7e9d40b52'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jira_connections',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('base_url', sa.String(length=500), nullable=False),
        sa.Column('auth_mode', sa.String(length=20), nullable=False),
        sa.Column('username', sa.String(length=200), nullable=False),
        sa.Column('credential', sa.String(length=500), nullable=False),
        sa.Column('verify_ssl', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jira_connections')),
        sa.UniqueConstraint('name', name=op.f('uq_jira_connections_name')),
    )


def downgrade() -> None:
    op.drop_table('jira_connections')
