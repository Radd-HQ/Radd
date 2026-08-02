"""two-scope settings + project-level SLA policies (spec 67)

The instance→workspace→project settings cascade collapses to two scopes
(INSTANCE defaults → PROJECT overrides): for a single-workspace deployment the
workspace layer only duplicated the instance one. Data moves, no DDL on
`scoped_settings`:

- Each workspace-scope row is promoted to the instance scope IF no instance
  row already exists for its key (one promotion per key — with multiple
  workspaces the most recently updated row wins, since NULL scope_ids don't
  collide under the unique constraint and duplicates would break the service's
  single-row lookups).
- Remaining workspace-scope rows are deleted.

SLA policies become project-level (`project_id` NOT NULL). Workspace-wide
policies (`project_id IS NULL`) are DELETED, not auto-assigned — there is no
principled project to attach them to. The live DB has none (verified: its one
policy already carries a project_id); other installs lose only the
workspace-wide rows, which have no equivalent in the new model. The
denormalised `workspace_id` column stays (report/event queries).

Both steps are idempotent re-runs (no workspace rows / already NOT NULL).

Revision ID: a7c2e19b4f30
Revises: 004bbb60df13

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c2e19b4f30'
down_revision = '004bbb60df13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Promote one workspace-scope settings row per key to the instance scope
    # (skipping keys that already have an instance row), then drop the rest.
    op.execute(
        """
        UPDATE scoped_settings SET scope = 'instance', scope_id = NULL
        WHERE id IN (
            SELECT DISTINCT ON (ws.key) ws.id
            FROM scoped_settings ws
            WHERE ws.scope = 'workspace'
              AND NOT EXISTS (
                  SELECT 1 FROM scoped_settings inst
                  WHERE inst.scope = 'instance' AND inst.key = ws.key
              )
            ORDER BY ws.key, ws.updated_at DESC
        )
        """
    )
    op.execute("DELETE FROM scoped_settings WHERE scope = 'workspace'")

    # SLA policies: workspace-wide rows are retired (see docstring), then the
    # column becomes NOT NULL.
    op.execute("DELETE FROM sla_policies WHERE project_id IS NULL")
    op.alter_column('sla_policies', 'project_id', existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    # Deleted workspace-scope settings and workspace-wide SLA policies are not
    # recoverable; only the structural change reverts.
    op.alter_column('sla_policies', 'project_id', existing_type=sa.Uuid(), nullable=True)
