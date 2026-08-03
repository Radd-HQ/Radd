"""sso provisioning template: scoped role grants + teams (RADD-780/781)

Revision ID: e780ssotmpl
Revises: cc302ccad603
Create Date: 2026-08-03

Replaces RADD-777's single `sso_providers.default_role_id` — one role, global
scope — with the shape the setting actually needed: any number of (role, scope)
grants, plus the teams a new account joins.

Hand-written for the same reason cc302ccad603 was: `--autogenerate` wants to
DROP `item_embeddings` and `page_embeddings` (spec 103 manages those at runtime,
outside `Base.metadata`), DROP a plugin's table, and rename a dozen indexes left
from the RADD-701 docs→pages rename. None of that belongs here.

The old column is BACKFILLED before it is dropped: any provider configured with
a role under 0.13.0 keeps it, as a global grant. Dropping first would silently
discard an admin's configuration on upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e780ssotmpl'
down_revision = 'cc302ccad603'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sso_provider_default_grants',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('provider_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        # NULL = instance-wide, exactly as in global_role_grants.
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['provider_id'], ['sso_providers.id'],
            name=op.f('fk_sso_provider_default_grants_provider_id_sso_providers'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['role_id'], ['roles.id'],
            name=op.f('fk_sso_provider_default_grants_role_id_roles'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'], ['projects.id'],
            name=op.f('fk_sso_provider_default_grants_project_id_projects'), ondelete='CASCADE',
        ),
        sa.UniqueConstraint('provider_id', 'role_id', 'project_id', name='uq_sso_default_grant'),
    )
    op.create_index(
        op.f('ix_sso_provider_default_grants_provider_id'),
        'sso_provider_default_grants', ['provider_id'],
    )

    op.create_table(
        'sso_provider_default_teams',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('provider_id', sa.Uuid(), nullable=False),
        sa.Column('team_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['provider_id'], ['sso_providers.id'],
            name=op.f('fk_sso_provider_default_teams_provider_id_sso_providers'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['team_id'], ['teams.id'],
            name=op.f('fk_sso_provider_default_teams_team_id_teams'), ondelete='CASCADE',
        ),
        sa.UniqueConstraint('provider_id', 'team_id', name='uq_sso_default_team'),
    )
    op.create_index(
        op.f('ix_sso_provider_default_teams_provider_id'),
        'sso_provider_default_teams', ['provider_id'],
    )

    # Carry 0.13.0's single global role forward before the column goes.
    op.execute(
        """
        INSERT INTO sso_provider_default_grants (id, provider_id, role_id, project_id)
        SELECT gen_random_uuid(), id, default_role_id, NULL
        FROM sso_providers
        WHERE default_role_id IS NOT NULL
        """
    )
    op.drop_constraint(
        op.f('fk_sso_providers_default_role_id_roles'), 'sso_providers', type_='foreignkey'
    )
    op.drop_column('sso_providers', 'default_role_id')


def downgrade() -> None:
    op.add_column('sso_providers', sa.Column('default_role_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_sso_providers_default_role_id_roles'),
        'sso_providers', 'roles', ['default_role_id'], ['id'], ondelete='SET NULL',
    )
    # Best effort: a single column cannot hold a scoped list, so only a global
    # grant survives the round trip. Anything project-scoped is dropped, which
    # is the honest limit of going backwards from a richer model.
    op.execute(
        """
        UPDATE sso_providers p
        SET default_role_id = g.role_id
        FROM sso_provider_default_grants g
        WHERE g.provider_id = p.id AND g.project_id IS NULL
        """
    )
    op.drop_table('sso_provider_default_teams')
    op.drop_table('sso_provider_default_grants')
