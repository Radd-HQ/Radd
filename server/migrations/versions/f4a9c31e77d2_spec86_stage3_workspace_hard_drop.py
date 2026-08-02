"""spec 86 stage 3 — the workspace hard drop.

Data first, drops last, one revision:

1. Merge every non-singleton workspace into the singleton (first workspace by
   created_at): labels dedupe by lower(name) with item_labels repoint; builtin
   roles collapse onto the singleton's rows (role FKs repointed:
   project_members / project_teams / field_permissions / builtin_field_rules);
   unique-constrained config rows (custom roles, teams, cycle_series,
   doc_spaces, field_definitions, work_categories) move with a suffix rename
   on collision. Nothing is deleted except exact duplicates.
2. Admin workspace_memberships promote to users.instance_role='admin'; the
   memberships table drops.
3. Stored role permission JSONB: "workspace.manage" -> "global.manage".
4. views.workspace_access / dashboards.workspace_access -> global_access.
5. Every workspace_id column (FKs / indexes / uniques included) drops; the
   scoped uniques are recreated as global ones; the worklogs scope CHECK is
   rewritten; the workspaces table drops LAST.

Irreversible by design (pre-migration backup: var/backups/pre-spec86-stage3.dump).

Revision ID: f4a9c31e77d2
Revises: 12e3da9fab36

"""
import sqlalchemy as sa
from alembic import op

revision = 'f4a9c31e77d2'
down_revision = '12e3da9fab36'
branch_labels = None
depends_on = None


def _scalar(bind, sql: str, **params):
    return bind.execute(sa.text(sql), params).scalar()


def _rows(bind, sql: str, **params):
    return bind.execute(sa.text(sql), params).fetchall()


def _exec(bind, sql: str, **params) -> None:
    bind.execute(sa.text(sql), params)


def _free_value(bind, table: str, column: str, base: str, fmt: str) -> str:
    """First non-colliding rename candidate: fmt.format(base, n) for n = 2, 3, ..."""
    n = 2
    while True:
        candidate = fmt.format(base=base, n=n)
        hit = _scalar(bind, f"SELECT 1 FROM {table} WHERE {column} = :v LIMIT 1", v=candidate)
        if hit is None:
            return candidate
        n += 1


def _merge_labels(bind, singleton: str, ws: str) -> None:
    """Merge one workspace's labels into the singleton by lower(name)."""
    for dupe_id, name in _rows(
        bind,
        "SELECT id, name FROM labels WHERE workspace_id = :ws ORDER BY created_at, id",
        ws=ws,
    ):
        target_id = _scalar(
            bind,
            "SELECT id FROM labels WHERE workspace_id = :s AND lower(name) = lower(:n) "
            "ORDER BY created_at, id LIMIT 1",
            s=singleton, n=name,
        )
        if target_id is None:
            _exec(bind, "UPDATE labels SET workspace_id = :s WHERE id = :d", s=singleton, d=dupe_id)
            continue
        _exec(
            bind,
            "UPDATE item_labels il SET label_id = :t WHERE il.label_id = :d AND NOT EXISTS "
            "(SELECT 1 FROM item_labels il2 WHERE il2.item_id = il.item_id AND il2.label_id = :t)",
            t=target_id, d=dupe_id,
        )
        _exec(bind, "DELETE FROM item_labels WHERE label_id = :d", d=dupe_id)
        _exec(bind, "DELETE FROM labels WHERE id = :d", d=dupe_id)


def _repoint_role(bind, dupe: str, target: str) -> None:
    """Move every reference from a duplicate builtin role onto the singleton's."""
    _exec(bind, "UPDATE project_members SET role_id = :t WHERE role_id = :d", t=target, d=dupe)
    _exec(bind, "UPDATE project_teams SET role_id = :t WHERE role_id = :d", t=target, d=dupe)
    # Polymorphic subject grants: delete rows that would collide with an
    # existing grant for the target, then repoint the rest.
    _exec(
        bind,
        "DELETE FROM field_permissions fp WHERE fp.subject_type = 'role' AND fp.subject_id = :d "
        "AND EXISTS (SELECT 1 FROM field_permissions fp2 WHERE fp2.field_id = fp.field_id "
        "AND fp2.subject_type = 'role' AND fp2.subject_id = :t AND fp2.access = fp.access)",
        t=target, d=dupe,
    )
    _exec(
        bind,
        "UPDATE field_permissions SET subject_id = :t WHERE subject_type = 'role' AND subject_id = :d",
        t=target, d=dupe,
    )
    _exec(
        bind,
        "DELETE FROM builtin_field_rules br WHERE br.subject_type = 'role' AND br.subject_id = :d "
        "AND EXISTS (SELECT 1 FROM builtin_field_rules br2 WHERE br2.subject_type = 'role' "
        "AND br2.subject_id = :t AND br2.field = br.field AND br2.access = br.access "
        "AND br2.project_id IS NOT DISTINCT FROM br.project_id)",
        t=target, d=dupe,
    )
    _exec(
        bind,
        "UPDATE builtin_field_rules SET subject_id = :t WHERE subject_type = 'role' AND subject_id = :d",
        t=target, d=dupe,
    )


def _merge_roles(bind, singleton: str, ws: str) -> None:
    for role_id, key, is_builtin in _rows(
        bind,
        "SELECT id, key, is_builtin FROM roles WHERE workspace_id = :ws ORDER BY position, key",
        ws=ws,
    ):
        if is_builtin:
            target = _scalar(
                bind,
                "SELECT id FROM roles WHERE workspace_id = :s AND key = :k AND is_builtin LIMIT 1",
                s=singleton, k=key,
            )
            if target is not None:
                _repoint_role(bind, str(role_id), str(target))
                _exec(bind, "DELETE FROM roles WHERE id = :d", d=role_id)
                continue
        collision = _scalar(
            bind, "SELECT 1 FROM roles WHERE workspace_id = :s AND key = :k", s=singleton, k=key
        )
        if collision:
            key = _free_value(bind, "roles", "key", key, "{base}_{n}")
            _exec(bind, "UPDATE roles SET key = :k WHERE id = :r", k=key, r=role_id)
        _exec(bind, "UPDATE roles SET workspace_id = :s WHERE id = :r", s=singleton, r=role_id)


def _merge_named(bind, singleton: str, ws: str, table: str, column: str, fmt: str) -> None:
    """Move rows to the singleton, suffix-renaming on (workspace_id, column) collision."""
    for row_id, value in _rows(
        bind, f"SELECT id, {column} FROM {table} WHERE workspace_id = :ws ORDER BY created_at, id",
        ws=ws,
    ):
        collision = _scalar(
            bind,
            f"SELECT 1 FROM {table} WHERE workspace_id = :s AND {column} = :v LIMIT 1",
            s=singleton, v=value,
        )
        if collision:
            value = _free_value(bind, table, column, value, fmt)
            _exec(bind, f"UPDATE {table} SET {column} = :v WHERE id = :r", v=value, r=row_id)
        _exec(bind, f"UPDATE {table} SET workspace_id = :s WHERE id = :r", s=singleton, r=row_id)


def _merge_workspace(bind, singleton: str, ws: str) -> None:
    _merge_labels(bind, singleton, ws)
    _merge_roles(bind, singleton, ws)
    _merge_named(bind, singleton, ws, "teams", "name", "{base} ({n})")
    _merge_named(bind, singleton, ws, "cycle_series", "label", "{base} ({n})")
    _merge_named(bind, singleton, ws, "doc_spaces", "slug", "{base}-{n}")
    _merge_named(bind, singleton, ws, "field_definitions", "key", "{base}_{n}")
    _merge_named(bind, singleton, ws, "work_categories", "name", "{base} ({n})")
    # builtin_field_rules: identical rule tuples across workspaces are pure
    # duplicates once the scope collapses — drop the newcomer, keep the rest.
    _exec(
        bind,
        "DELETE FROM builtin_field_rules br WHERE br.workspace_id = :ws AND EXISTS "
        "(SELECT 1 FROM builtin_field_rules br2 WHERE br2.workspace_id = :s "
        "AND br2.field = br.field AND br2.subject_type = br.subject_type "
        "AND br2.subject_id = br.subject_id AND br2.access = br.access "
        "AND br2.project_id IS NOT DISTINCT FROM br.project_id)",
        ws=ws, s=singleton,
    )
    _exec(
        bind,
        "UPDATE builtin_field_rules SET workspace_id = :s WHERE workspace_id = :ws",
        s=singleton, ws=ws,
    )
    # Everything else (projects, cycles, views, dashboards, automation_rules,
    # canned_responses, sla_policies, screens, webhook_endpoints, search_index,
    # worklogs, notifications, events) has no workspace-scoped unique — the
    # column drop below IS the move to global; rows keep their data untouched.


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------ data
    singleton = _scalar(bind, "SELECT id FROM workspaces ORDER BY created_at, id LIMIT 1")
    if singleton is not None:
        others = [
            r[0] for r in _rows(
                bind,
                "SELECT id FROM workspaces WHERE id != :s ORDER BY created_at, id",
                s=singleton,
            )
        ]
        for ws in others:
            _merge_workspace(bind, str(singleton), str(ws))

    # Admin membership anywhere -> instance admin (the compat tier becomes real).
    _exec(
        bind,
        "UPDATE users SET instance_role = 'admin' WHERE instance_role != 'admin' AND id IN "
        "(SELECT user_id FROM workspace_memberships WHERE role = 'admin')",
    )

    # Stored role JSONB: the workspace.manage atom becomes global.manage.
    _exec(
        bind,
        "UPDATE roles SET permissions = (permissions - 'workspace.manage') || '[\"global.manage\"]'::jsonb "
        "WHERE permissions ? 'workspace.manage'",
    )

    # ----------------------------------------------------------------- drops
    _exec(bind, "DROP TABLE IF EXISTS workspace_memberships")

    _exec(bind, "ALTER TABLE views RENAME COLUMN workspace_access TO global_access")
    _exec(bind, "ALTER TABLE dashboards RENAME COLUMN workspace_access TO global_access")

    # (table, has_fk, unique_constraint_to_drop, index_to_drop)
    drops = (
        ("automation_rules", True, None),
        ("builtin_field_rules", False, "uq_builtin_field_rules_workspace_id_project_id_field_su_09fa"),
        ("canned_responses", False, None),
        ("cycle_series", True, "uq_cycle_series_workspace_id_label"),
        ("cycles", True, None),
        ("dashboards", True, None),
        ("doc_spaces", True, "uq_doc_spaces_workspace_id_slug"),
        ("events", False, None),
        ("field_definitions", True, "uq_field_definitions_workspace_id_key"),
        ("labels", True, "uq_labels_workspace_id_name"),
        ("notifications", False, None),
        ("projects", True, None),
        ("roles", True, "uq_roles_workspace_id_key"),
        ("screens", False, None),
        ("search_index", False, None),
        ("sla_policies", False, None),
        ("teams", True, "uq_teams_workspace_id_name"),
        ("views", True, None),
        ("webhook_endpoints", True, None),
        ("work_categories", True, "uq_work_categories_workspace_id_name"),
        ("worklogs", True, None),
    )
    _exec(bind, "ALTER TABLE worklogs DROP CONSTRAINT IF EXISTS ck_worklogs_ck_worklogs_scope")
    for table, has_fk, unique in drops:
        if unique:
            _exec(bind, f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {unique}")
        if has_fk:
            _exec(bind, f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_workspace_id_workspaces")
        _exec(bind, f"DROP INDEX IF EXISTS ix_{table}_workspace_id")
        _exec(bind, f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")

    # The formerly workspace-scoped uniques become global ones.
    for table, name, column in (
        ("labels", "uq_labels_name", "name"),
        ("teams", "uq_teams_name", "name"),
        ("roles", "uq_roles_key", "key"),
        ("cycle_series", "uq_cycle_series_label", "label"),
        ("doc_spaces", "uq_doc_spaces_slug", "slug"),
        ("field_definitions", "uq_field_definitions_key", "key"),
        ("work_categories", "uq_work_categories_name", "name"),
    ):
        _exec(bind, f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({column})")
    _exec(
        bind,
        "ALTER TABLE builtin_field_rules ADD CONSTRAINT uq_builtin_field_rules_scope "
        "UNIQUE (project_id, field, subject_type, subject_id, access)",
    )
    _exec(
        bind,
        "ALTER TABLE worklogs ADD CONSTRAINT ck_worklogs_ck_worklogs_scope "
        "CHECK (item_id IS NOT NULL OR category_id IS NOT NULL)",
    )

    _exec(bind, "DROP TABLE IF EXISTS workspaces")


def downgrade() -> None:
    raise NotImplementedError(
        "spec 86 stage 3 is irreversible — restore var/backups/pre-spec86-stage3.dump instead"
    )
