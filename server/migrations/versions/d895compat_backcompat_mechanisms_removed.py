"""d895compat: the backcompat mechanisms leave, their rows migrate (RADD-895)

Four one-shot data moves, each retiring a runtime dual path found by the
2026-08 backcompat audit (research/audit-2026-08/06-backcompat-hacks.md):

1. `users.source = 'unknown'` (the pre-spec-84 lazy-migration sentinel) is
   resolved NOW instead of "on next login": rows with a `user_identities` row
   became `oidc` (an SSO subject is pinned to them), everything else `local`.
   The column's server_default drops the sentinel too — `UserSource.UNKNOWN`
   and both lazy-upgrade branches (sso + ldap) are deleted in the same change.
2. `storage_hosts.root_dir = ''` on filesystem hosts (the "read the env at
   runtime" sentinel) is backfilled with the env's `attachments_dir`, so the
   ROW says where the bytes live — the `or settings.attachments_dir` fallbacks
   are deleted with it, and a validator now refuses an empty root_dir.
3. `teams.owner_id NULL` (pre-spec-87 rows kept administrable via the
   team.update atom) gains an owner: the team's first manager if any, else the
   oldest active instance admin. NULL stays *possible* — RADD-784 deliberately
   SET-NULLs ownership when the owner's account is hard-deleted — but no row
   is born or left ownerless by history any more.
4. `forms.public_token` is dropped — the model column died with RADD-828/893
   (tokened public forms), and only this table column remained.

Revision ID: d895compat
Revises: d844partrel
Create Date: 2026-08-05
"""
import sqlalchemy as sa
from alembic import op

from radd.config import settings

revision = 'd895compat'
down_revision = 'd844partrel'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. users.source: 'unknown' rows resolve now, not on next login.
    conn.execute(sa.text(
        "UPDATE users SET source = 'oidc' WHERE source = 'unknown' AND EXISTS ("
        "  SELECT 1 FROM user_identities ui WHERE ui.user_id = users.id)"
    ))
    conn.execute(sa.text("UPDATE users SET source = 'local' WHERE source = 'unknown'"))
    op.alter_column('users', 'source', server_default='local')

    # 2. storage_hosts.root_dir: the '' sentinel becomes the env value it meant.
    conn.execute(
        sa.text(
            "UPDATE storage_hosts SET root_dir = :root "
            "WHERE host_type = 'filesystem' AND root_dir = ''"
        ).bindparams(root=settings.attachments_dir)
    )

    # 3. teams.owner_id: first manager (deterministic pick), else oldest admin.
    conn.execute(sa.text(
        "UPDATE teams SET owner_id = ("
        "  SELECT tm.user_id FROM team_managers tm"
        "  WHERE tm.team_id = teams.id ORDER BY tm.user_id LIMIT 1)"
        " WHERE owner_id IS NULL AND EXISTS ("
        "  SELECT 1 FROM team_managers tm WHERE tm.team_id = teams.id)"
    ))
    conn.execute(sa.text(
        "UPDATE teams SET owner_id = ("
        "  SELECT u.id FROM users u"
        "  WHERE u.instance_role = 'admin' AND u.active"
        "  ORDER BY u.created_at, u.id LIMIT 1)"
        " WHERE owner_id IS NULL"
    ))

    # 4. forms.public_token: the RADD-893 leftover column.
    op.drop_constraint('uq_forms_public_token', 'forms', type_='unique')
    op.drop_column('forms', 'public_token')


def downgrade() -> None:
    # The data moves are one-way (the sentinel states they retire carry no
    # information worth reconstructing); only the schema shape comes back.
    op.add_column('forms', sa.Column('public_token', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_forms_public_token', 'forms', ['public_token'])
    op.alter_column('users', 'source', server_default='unknown')
