"""worklogs: nullable item + project/workspace scope (spec 59)

Revision ID: 43a780816f08
Revises: 0e31acda072d

"""
from alembic import op
import sqlalchemy as sa


revision = '43a780816f08'
down_revision = '0e31acda072d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('worklogs', sa.Column('project_id', sa.Uuid(), nullable=True))
    op.add_column('worklogs', sa.Column('workspace_id', sa.Uuid(), nullable=True))
    op.alter_column('worklogs', 'item_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.create_index(op.f('ix_worklogs_project_id'), 'worklogs', ['project_id'], unique=False)
    op.create_index(op.f('ix_worklogs_workspace_id'), 'worklogs', ['workspace_id'], unique=False)
    op.create_foreign_key(op.f('fk_worklogs_project_id_projects'), 'worklogs', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(op.f('fk_worklogs_workspace_id_workspaces'), 'worklogs', 'workspaces', ['workspace_id'], ['id'], ondelete='CASCADE')
    # Spec 59: item-bound rows keep their scope via the item; itemless rows must
    # carry a workspace AND a category (the category is their identity).
    op.create_check_constraint(
        'ck_worklogs_scope',
        'worklogs',
        'item_id IS NOT NULL OR (workspace_id IS NOT NULL AND category_id IS NOT NULL)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_worklogs_scope', 'worklogs', type_='check')
    # Itemless rows can't survive a non-nullable item_id.
    op.execute('DELETE FROM worklogs WHERE item_id IS NULL')
    op.drop_constraint(op.f('fk_worklogs_workspace_id_workspaces'), 'worklogs', type_='foreignkey')
    op.drop_constraint(op.f('fk_worklogs_project_id_projects'), 'worklogs', type_='foreignkey')
    op.drop_index(op.f('ix_worklogs_workspace_id'), table_name='worklogs')
    op.drop_index(op.f('ix_worklogs_project_id'), table_name='worklogs')
    op.alter_column('worklogs', 'item_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('worklogs', 'workspace_id')
    op.drop_column('worklogs', 'project_id')
