"""RADD-1285: shipping is a workflow transition, not two typed-in state names.

1. `workflow_transitions.on_release` — "moves automatically when a release is
   published".
2. Every configured spec-112 pair (project override, else the instance row, else
   the RADD_RELEASE_WAITING_STATE / RADD_RELEASE_SHIPPED_STATE env default)
   whose two names resolve to states in the project becomes an on-release row
   waiting → shipped: an existing row with that edge is flagged, otherwise one is
   appended. A pair that no longer resolves did nothing before and converts to
   nothing now.
3. A hand-built `require_field` on the Release builtin with op `set` becomes the
   named `require_release` check.
4. The two settings' rows are deleted; the keys no longer exist.

Revision ID: d1285releaseflow
Revises: d1283threadpolicy
"""
import json
import os
import uuid

import sqlalchemy as sa
from alembic import op

revision = "d1285releaseflow"
down_revision = "d1283threadpolicy"
branch_labels = None
depends_on = None

WAITING, SHIPPED = "release_waiting_state", "release_shipped_state"


def _name(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    return str(value or "").strip()


def upgrade() -> None:
    op.add_column(
        "workflow_transitions",
        sa.Column("on_release", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    bind = op.get_bind()

    # 3. require_field(release, set) → require_release
    for row_id, rules in bind.execute(sa.text("SELECT id, rules FROM workflow_transitions")).all():
        changed, rewritten = False, []
        for rule in rules or []:
            params = rule.get("params") or {}
            if (rule.get("check") == "require_field" and params.get("kind") == "builtin"
                    and params.get("key") == "release" and params.get("op") == "set"):
                rewritten.append({"check": "require_release", "params": {}})
                changed = True
            else:
                rewritten.append(rule)
        if changed:
            bind.execute(sa.text("UPDATE workflow_transitions SET rules = CAST(:r AS jsonb) WHERE id = :i"),
                         {"r": json.dumps(rewritten), "i": row_id})

    # 2. settings → on-release transitions
    rows = bind.execute(sa.text(
        "SELECT scope, scope_id, key, value FROM scoped_settings WHERE key IN (:w, :s)"
    ), {"w": WAITING, "s": SHIPPED}).all()
    instance = {WAITING: os.environ.get("RADD_RELEASE_WAITING_STATE", ""),
                SHIPPED: os.environ.get("RADD_RELEASE_SHIPPED_STATE", "")}
    per_project: dict = {}
    for scope, scope_id, key, value in rows:
        if scope == "instance":
            instance[key] = _name(value)
        elif scope == "project" and scope_id is not None:
            per_project.setdefault(scope_id, {})[key] = _name(value)

    for (project_id,) in bind.execute(sa.text("SELECT id FROM projects")).all():
        own = per_project.get(project_id, {})
        waiting = _name(own.get(WAITING, instance[WAITING]))
        shipped = _name(own.get(SHIPPED, instance[SHIPPED]))
        if not waiting or not shipped:
            continue
        states = {name.lower(): sid for sid, name in bind.execute(
            sa.text("SELECT id, name FROM states WHERE project_id = :p"), {"p": project_id}).all()}
        from_id, to_id = states.get(waiting.lower()), states.get(shipped.lower())
        if from_id is None or to_id is None or from_id == to_id:
            continue
        existing = bind.execute(sa.text(
            "SELECT id FROM workflow_transitions WHERE project_id = :p AND from_state_id = :f "
            "AND to_state_id = :t ORDER BY position LIMIT 1"
        ), {"p": project_id, "f": from_id, "t": to_id}).scalar()
        if existing is not None:
            bind.execute(sa.text("UPDATE workflow_transitions SET on_release = true WHERE id = :i"),
                         {"i": existing})
            continue
        position = bind.execute(sa.text(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM workflow_transitions WHERE project_id = :p"
        ), {"p": project_id}).scalar()
        bind.execute(sa.text(
            "INSERT INTO workflow_transitions (id, project_id, from_state_id, to_state_id, rules, "
            "applies_when, position, on_release) VALUES (:i, :p, :f, :t, '[]'::jsonb, '[]'::jsonb, :pos, true)"
        ), {"i": uuid.uuid4(), "p": project_id, "f": from_id, "t": to_id, "pos": position})

    # 4. the settings are gone
    bind.execute(sa.text("DELETE FROM scoped_settings WHERE key IN (:w, :s)"), {"w": WAITING, "s": SHIPPED})


def downgrade() -> None:
    op.drop_column("workflow_transitions", "on_release")
