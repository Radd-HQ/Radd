"""automations rules engine + system actor

Creates automation_rules and seeds the automation system actor (a login-disabled
instance-admin user) so the engine can apply changes/comments and tag its events for
the loop guard. Chained directly on e4390d7d9542 (spec 14) as a sibling head — the
supervisor merges it with spec 17's branch; do NOT `alembic merge` here.

Revision ID: d49968ce89b4
Revises: e4390d7d9542

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd49968ce89b4'
down_revision = 'e4390d7d9542'
branch_labels = None
depends_on = None

# Must match radd.modules.automations.types.SYSTEM_ACTOR_ID / _EMAIL / _NAME.
SYSTEM_ACTOR_ID = '00000000-0000-0000-0000-000000a70a70'
SYSTEM_ACTOR_EMAIL = 'automation@radd.system'
SYSTEM_ACTOR_NAME = 'Automation'


def upgrade() -> None:
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('condition_slq', sa.Text(), nullable=False),
        sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['workspace_id'], ['workspaces.id'],
            name=op.f('fk_automation_rules_workspace_id_workspaces'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_rules')),
    )
    op.create_index(
        op.f('ix_automation_rules_workspace_id'), 'automation_rules', ['workspace_id'], unique=False
    )
    # Seed the engine's system actor. Login-disabled (null password), instance-admin so
    # authz never blocks engine-applied writes; its id tags events for the loop guard.
    op.execute(
        sa.text(
            "INSERT INTO users (id, email, name, password_hash, instance_role, active) "
            "VALUES (CAST(:id AS uuid), :email, :name, NULL, 'admin', true) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(id=SYSTEM_ACTOR_ID, email=SYSTEM_ACTOR_EMAIL, name=SYSTEM_ACTOR_NAME)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM users WHERE id = CAST(:id AS uuid)").bindparams(id=SYSTEM_ACTOR_ID)
    )
    op.drop_index(op.f('ix_automation_rules_workspace_id'), table_name='automation_rules')
    op.drop_table('automation_rules')
