"""seed roadmap project views

Roadmap as a view type (spec 79): new projects seed a Roadmap view via the
project-created hook (views/defaults.DEFAULT_VIEW_DEFS); this backfills every
existing project that has no roadmap-type view yet — same shape as the other
seeds (workspace-visible viewer, owner NULL, empty query). Hand-written data
migration, the 62681dd4006c idiom.

Revision ID: d1f80c2eedc3
Revises: 6941ef0ddab2

"""
from alembic import op


revision = 'd1f80c2eedc3'
down_revision = '6941ef0ddab2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO views (id, workspace_id, project_id, name, view_type, query,
                           group_by, swimlane_by, cycle_filter, quick_filters,
                           owner_id, workspace_access, position)
        SELECT gen_random_uuid(), p.workspace_id, p.id, 'Roadmap', 'roadmap', '',
               NULL, NULL, NULL, '[]'::jsonb,
               NULL, 'viewer', 0
        FROM projects p
        WHERE NOT EXISTS (
            SELECT 1 FROM views v
            WHERE v.project_id = p.id AND v.view_type = 'roadmap'
        )
        """
    )


def downgrade() -> None:
    # Remove only untouched seeded rows (name/query still pristine).
    op.execute(
        """
        DELETE FROM views
        WHERE view_type = 'roadmap' AND owner_id IS NULL
          AND name = 'Roadmap' AND query = ''
        """
    )
