"""backfill builtin role permissions (spec 36)

Existing workspaces' builtin role ROWS were seeded from the then-current
definitions. Spec 36 adds per-entity manage permissions (the admin project set
grew) and gives members form.manage — mirror both into stored rows so the
seeded definitions and the data stay identical (the immutability contract).

Revision ID: 43c250fb2a01
Revises: ed44871272ba

"""
from alembic import op

revision = '43c250fb2a01'
down_revision = 'ed44871272ba'
branch_labels = None
depends_on = None

_ADMIN_ADDS = ("state.manage", "release.manage", "field.manage")
_MEMBER_ADDS = ("form.manage",)


def _append(key: str, values: tuple[str, ...]) -> None:
    for value in values:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = permissions || '["{value}"]'::jsonb
            WHERE is_builtin AND key = '{key}'
              AND NOT permissions @> '["{value}"]'::jsonb
            """
        )


def upgrade() -> None:
    _append("admin", _ADMIN_ADDS)
    _append("member", _MEMBER_ADDS)


def downgrade() -> None:
    for key, values in (("admin", _ADMIN_ADDS), ("member", _MEMBER_ADDS)):
        for value in values:
            op.execute(
                f"""
                UPDATE roles
                SET permissions = permissions - '{value}'
                WHERE is_builtin AND key = '{key}'
                """
            )
