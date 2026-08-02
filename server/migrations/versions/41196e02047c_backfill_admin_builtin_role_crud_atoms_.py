"""backfill admin builtin role crud atoms spec 50

Spec 50 gives every resource a granular create/update/delete atom. The builtin
`admin` project role is defined as the whole PROJECT_PERMISSIONS set, which grew
by 21 project-scoped atoms — mirror them into existing workspaces' stored admin
rows so the seeded definition and the data stay identical (the immutability
contract, same as spec 36's 43c250fb2a01). `member`/`viewer` are unchanged: their
capabilities flow through umbrella expansion, not new stored grants.

Correctness does not depend on this backfill (project.manage transitively implies
every one of these atoms at check time) — it only keeps the roles-matrix display
truthful for pre-existing admin rows.

Revision ID: 41196e02047c
Revises: 5a434af1d358

"""
from alembic import op


revision = '41196e02047c'
down_revision = '5a434af1d358'
branch_labels = None
depends_on = None

_ADMIN_ADDS = (
    "item.delete",
    "comment.delete",
    "worklog.delete",
    "state.create",
    "state.update",
    "state.delete",
    "field.create",
    "field.update",
    "field.delete",
    "release.create",
    "release.update",
    "release.delete",
    "form.create",
    "form.update",
    "form.delete",
    "view.create",
    "view.update",
    "view.delete",
    "member.create",
    "member.update",
    "member.delete",
)


def upgrade() -> None:
    for value in _ADMIN_ADDS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = permissions || '["{value}"]'::jsonb
            WHERE is_builtin AND key = 'admin'
              AND NOT permissions @> '["{value}"]'::jsonb
            """
        )


def downgrade() -> None:
    for value in _ADMIN_ADDS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = permissions - '{value}'
            WHERE is_builtin AND key = 'admin'
            """
        )
