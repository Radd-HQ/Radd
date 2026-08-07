"""RADD-929: one grant model — fold project_members and project_teams into role grants.

Three tables expressed one fact ("this subject holds this role on this project")
and `auth.authz_core._granted_role_ids` unioned all three into a single set:

    role_ids  = project_members  (user → project → role)
    role_ids |= project_teams    (team → project → role)
    role_ids |= global_role_grants scoped to the project

The outcome was identical whichever table carried the row, so the Teams panel
could show a team's RADD entitlement twice — once as a "project attachment",
once as a "role grant" — and neither label was more true than the other.

`global_role_grants` is already the general form: subject (user | team | group)
× role × scope (project | space | neither). This migration repoints the other
two into it and drops them.

**Nothing is lost and nothing is gained.** Each old row becomes exactly one
grant with the same (subject, role, project), so every account's effective
permissions are byte-identical after the upgrade — which is the property worth
checking on a live instance, because a permission migration that silently
widens access is the failure nobody notices.

Two details that decide correctness:

* **The dedupe is `WHERE NOT EXISTS`, not `ON CONFLICT DO NOTHING`.** A team can
  already hold the same role on the same project through BOTH an attachment and
  a grant — that duplication is the bug being fixed, so it is the *expected*
  input, not an edge case. `ON CONFLICT` does not catch it: the unique
  constraint is (role_id, team_id, project_id, **space_id**), `space_id` is NULL
  for every project-scoped grant, and Postgres treats NULLs as distinct, so the
  index never matches and the clause silently does nothing. The result would be
  two identical grant rows — the same duplication, now inside the one table
  meant to end it, and visible as a repeated row on the project's Access screen.
  Verified against the real schema before shipping; `ON CONFLICT` inserted 3 of
  3 rows where 2 were expected.
* **`granted_by` is left NULL.** The old tables recorded no granter, and
  inventing one — the migration's actor, the project owner — would put a name
  against a decision that person may never have made.

Irreversible: the downgrade recreates the tables empty rather than guessing
which grants used to be attachments. Per the project's pre-1.0 rule, losing
that distinction is preferred to carrying a `source` column that exists only to
answer a question nobody asks.
"""

from alembic import op

revision = "d929grants"
down_revision = "d922payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # project_members → a user-subject grant scoped to the project.
    op.execute(
        """
        INSERT INTO global_role_grants (id, role_id, user_id, project_id, created_at, updated_at)
        SELECT gen_random_uuid(), pm.role_id, pm.user_id, pm.project_id, now(), now()
        FROM project_members pm
        WHERE NOT EXISTS (
            SELECT 1 FROM global_role_grants g
            WHERE g.role_id = pm.role_id
              AND g.user_id = pm.user_id
              AND g.project_id = pm.project_id
              AND g.space_id IS NULL
        )
        """
    )
    # project_teams → a team-subject grant scoped to the project.
    op.execute(
        """
        INSERT INTO global_role_grants (id, role_id, team_id, project_id, created_at, updated_at)
        SELECT gen_random_uuid(), pt.role_id, pt.team_id, pt.project_id, now(), now()
        FROM project_teams pt
        WHERE NOT EXISTS (
            SELECT 1 FROM global_role_grants g
            WHERE g.role_id = pt.role_id
              AND g.team_id = pt.team_id
              AND g.project_id = pt.project_id
              AND g.space_id IS NULL
        )
        """
    )
    op.drop_table("project_members")
    op.drop_table("project_teams")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_members (
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id uuid NOT NULL REFERENCES roles(id),
            PRIMARY KEY (project_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE project_teams (
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            role_id uuid NOT NULL REFERENCES roles(id),
            PRIMARY KEY (project_id, team_id)
        )
        """
    )
