"""sso provisioning rules: domain -> starting access (RADD-782)

Revision ID: f782ssorules
Revises: e780ssotmpl
Create Date: 2026-08-03

One provider serves several populations — `@acme.example` and `@partner.example`
arrive through the same Google button and should not land with the same access.
This puts a RULE between the provider and its grants, and repoints the grant and
team rows onto it.

Behaviour-free on upgrade: every provider that has a template today gets ONE
unnamed rule with an empty domain list, which matches everyone — exactly what
the flat template did. Hand-written for the reason the last two were:
`--autogenerate` wants to drop the runtime-managed embeddings tables and a
plugin's table, none of which belongs here.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f782ssorules'
down_revision = 'e780ssotmpl'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sso_provisioning_rules',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('provider_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        # EMPTY = matches every address. That default is what makes the backfill
        # below preserve behaviour rather than change it.
        sa.Column('domains', sa.dialects.postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['provider_id'], ['sso_providers.id'],
            name=op.f('fk_sso_provisioning_rules_provider_id_sso_providers'),
            ondelete='CASCADE',
        ),
    )
    op.create_index(
        op.f('ix_sso_provisioning_rules_provider_id'),
        'sso_provisioning_rules', ['provider_id'],
    )

    # One catch-all rule per provider that currently has a template.
    op.execute(
        """
        INSERT INTO sso_provisioning_rules (id, provider_id, name, position, domains)
        SELECT gen_random_uuid(), p.id, '', 0, '[]'::jsonb
        FROM sso_providers p
        WHERE EXISTS (SELECT 1 FROM sso_provider_default_grants g WHERE g.provider_id = p.id)
           OR EXISTS (SELECT 1 FROM sso_provider_default_teams t WHERE t.provider_id = p.id)
        """
    )

    for table, unique in (
        ('sso_provider_default_grants', 'uq_sso_default_grant'),
        ('sso_provider_default_teams', 'uq_sso_default_team'),
    ):
        op.add_column(table, sa.Column('rule_id', sa.Uuid(), nullable=True))
        op.execute(
            f"""
            UPDATE {table} c
            SET rule_id = r.id
            FROM sso_provisioning_rules r
            WHERE r.provider_id = c.provider_id
            """
        )
        op.drop_constraint(unique, table, type_='unique')
        op.drop_column(table, 'provider_id')
        op.alter_column(table, 'rule_id', nullable=False)
        op.create_foreign_key(
            op.f(f'fk_{table}_rule_id_sso_provisioning_rules'),
            table, 'sso_provisioning_rules', ['rule_id'], ['id'], ondelete='CASCADE',
        )
        op.create_index(op.f(f'ix_{table}_rule_id'), table, ['rule_id'])

    op.create_unique_constraint(
        'uq_sso_default_grant', 'sso_provider_default_grants',
        ['rule_id', 'role_id', 'project_id'],
    )
    op.create_unique_constraint(
        'uq_sso_default_team', 'sso_provider_default_teams', ['rule_id', 'team_id']
    )


def downgrade() -> None:
    # Collapses every rule back onto the provider — a flat template cannot hold
    # per-domain access, so anything domain-specific merges. The honest limit of
    # going backwards from a richer model.
    for table, unique in (
        ('sso_provider_default_grants', 'uq_sso_default_grant'),
        ('sso_provider_default_teams', 'uq_sso_default_team'),
    ):
        op.add_column(table, sa.Column('provider_id', sa.Uuid(), nullable=True))
        op.execute(
            f"""
            UPDATE {table} c
            SET provider_id = r.provider_id
            FROM sso_provisioning_rules r
            WHERE r.id = c.rule_id
            """
        )
        op.drop_constraint(unique, table, type_='unique')
        op.drop_column(table, 'rule_id')
        op.alter_column(table, 'provider_id', nullable=False)
        op.create_foreign_key(
            op.f(f'fk_{table}_provider_id_sso_providers'),
            table, 'sso_providers', ['provider_id'], ['id'], ondelete='CASCADE',
        )
    op.create_unique_constraint(
        'uq_sso_default_grant', 'sso_provider_default_grants',
        ['provider_id', 'role_id', 'project_id'],
    )
    op.create_unique_constraint(
        'uq_sso_default_team', 'sso_provider_default_teams', ['provider_id', 'team_id']
    )
    op.drop_table('sso_provisioning_rules')
