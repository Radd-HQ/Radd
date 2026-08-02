"""seed builtin project views

Every project ships with one editable, workspace-visible view per built-in
surface (Board/List/Planning) — `views.project_default` marks which view backs
each surface. New projects seed via the project-created hook; this backfills
existing projects that lack a designated view for a slot (idempotent).

Revision ID: 62681dd4006c
Revises: 97f19379ae3c

"""
from alembic import op


revision = '62681dd4006c'
down_revision = '97f19379ae3c'
branch_labels = None
depends_on = None

# (slot, name, view_type, group_by-or-NULL) — mirrors views/defaults.BUILTIN_VIEW_DEFS.
_DEFS = (
    ("board", "Board", "board", "state"),
    ("list", "List", "list", None),
    ("planning", "Planning", "planning", None),
)


def upgrade() -> None:
    for slot, name, view_type, group_by in _DEFS:
        group_by_sql = f"'{group_by}'" if group_by else "NULL"
        op.execute(
            f"""
            INSERT INTO views (id, workspace_id, project_id, name, view_type, query,
                               group_by, swimlane_by, cycle_filter, quick_filters,
                               owner_id, workspace_access, project_default, position)
            SELECT gen_random_uuid(), p.workspace_id, p.id, '{name}', '{view_type}', '',
                   {group_by_sql}, NULL, NULL, '[]'::jsonb,
                   NULL, 'viewer', '{slot}', 0
            FROM projects p
            WHERE NOT EXISTS (
                SELECT 1 FROM views v
                WHERE v.project_id = p.id AND v.project_default = '{slot}'
            )
            """
        )


def downgrade() -> None:
    # Remove only untouched seeded rows (name/type/query still pristine).
    for slot, name, view_type, _group_by in _DEFS:
        op.execute(
            f"""
            DELETE FROM views
            WHERE project_default = '{slot}' AND owner_id IS NULL
              AND name = '{name}' AND view_type = '{view_type}' AND query = ''
            """
        )
