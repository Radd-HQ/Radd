"""builtin field rule access read write spec 50

Revision ID: 5a53e459d033
Revises: faadd4470e3e

"""
from alembic import op
import sqlalchemy as sa


revision = '5a53e459d033'
down_revision = 'faadd4470e3e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows are all WRITE rules (spec 36) — backfill via server_default,
    # then drop the default so the column matches the ORM (Python-side default).
    op.add_column(
        'builtin_field_rules',
        sa.Column('access', sa.String(length=10), nullable=False, server_default='write'),
    )
    op.alter_column('builtin_field_rules', 'access', server_default=None)
    op.drop_constraint(op.f('uq_builtin_field_rules_workspace_id_project_id_field_su_5bf5'), 'builtin_field_rules', type_='unique')
    op.create_unique_constraint(op.f('uq_builtin_field_rules_workspace_id_project_id_field_subject_type_subject_id_access'), 'builtin_field_rules', ['workspace_id', 'project_id', 'field', 'subject_type', 'subject_id', 'access'])
    # NOTE: autogenerate also proposed dropping ix_doc_pages_fts — a false positive
    # (functional GIN expression index Alembic can't introspect). Omitted on purpose.


def downgrade() -> None:
    op.drop_constraint(op.f('uq_builtin_field_rules_workspace_id_project_id_field_subject_type_subject_id_access'), 'builtin_field_rules', type_='unique')
    op.create_unique_constraint(op.f('uq_builtin_field_rules_workspace_id_project_id_field_su_5bf5'), 'builtin_field_rules', ['workspace_id', 'project_id', 'field', 'subject_type', 'subject_id'])
    op.drop_column('builtin_field_rules', 'access')
