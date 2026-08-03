"""sso provider default role grant (RADD-777)

Revision ID: cc302ccad603
Revises: d712tmpl
Create Date: 2026-08-03 19:27:22.700303

Hand-written, and deliberately so. `--autogenerate` produced forty statements:
it wanted to DROP `item_embeddings` and `page_embeddings` (spec 103 manages
those at runtime, outside `Base.metadata`, so the model tree has never known
about them), DROP the `acme_notes` plugin table, and rename a dozen indexes and
constraints left over from the RADD-701 docs→pages rename. Every one of those is
autogenerate reporting that the model tree is not the whole schema — none of
them belongs in a migration about one nullable column.

What this actually does: one column and its foreign key.
"""
from alembic import op
import sqlalchemy as sa

revision = 'cc302ccad603'
down_revision = 'd712tmpl'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sso_providers', sa.Column('default_role_id', sa.Uuid(), nullable=True))
    # SET NULL, not CASCADE: deleting a role must not delete the provider that
    # happened to reference it. A signup then simply starts on the Baseline,
    # which is the right failure — an admin tidying the role list should never
    # be able to break the login path.
    op.create_foreign_key(
        op.f('fk_sso_providers_default_role_id_roles'),
        'sso_providers',
        'roles',
        ['default_role_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_sso_providers_default_role_id_roles'), 'sso_providers', type_='foreignkey'
    )
    op.drop_column('sso_providers', 'default_role_id')
