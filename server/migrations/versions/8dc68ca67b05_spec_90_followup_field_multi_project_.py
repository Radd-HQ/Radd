"""spec 90 followup: field multi-project scope

Revision ID: 8dc68ca67b05
Revises: 359b250bda3a

Field scope moves from a single `field_definitions.project_id` (NULL = global,
set = one project) to a `field_definition_projects` association: NO rows = global,
one or more rows = scoped to those projects. Existing scoped fields are backfilled
into the association before the column is dropped, so scope is preserved.
"""
from alembic import op
import sqlalchemy as sa


revision = '8dc68ca67b05'
down_revision = '359b250bda3a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('field_definition_projects',
    sa.Column('field_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['field_id'], ['field_definitions.id'], name=op.f('fk_field_definition_projects_field_id_field_definitions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_field_definition_projects_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('field_id', 'project_id', name=op.f('pk_field_definition_projects'))
    )
    # Preserve existing single-project scopes as association rows before dropping the column.
    op.execute(
        "INSERT INTO field_definition_projects (field_id, project_id) "
        "SELECT id, project_id FROM field_definitions WHERE project_id IS NOT NULL"
    )
    op.drop_constraint(op.f('fk_field_definitions_project_id_projects'), 'field_definitions', type_='foreignkey')
    op.drop_column('field_definitions', 'project_id')


def downgrade() -> None:
    op.add_column('field_definitions', sa.Column('project_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('fk_field_definitions_project_id_projects'), 'field_definitions', 'projects', ['project_id'], ['id'])
    # Lossy: a multi-project field can only keep one scope in the single column —
    # take the lowest project_id; global fields (no rows) stay NULL.
    op.execute(
        "UPDATE field_definitions fd SET project_id = ("
        "SELECT MIN(project_id) FROM field_definition_projects fp WHERE fp.field_id = fd.id)"
    )
    op.drop_table('field_definition_projects')
