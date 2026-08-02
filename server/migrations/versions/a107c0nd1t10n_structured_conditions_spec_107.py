"""structured transition conditions + per-entry approvers (spec 107)

Two data reshapes, no new tables:

- `workflow_transitions.rules`: the five legacy presence checks
  (require_assignee/team/estimate/comment/fields) become `require_field`
  condition rows ({kind, key, op}); `require_approval`'s flat
  user_ids/team_ids/required become per-entry approver rules
  ([{kind, id, name, required?}]) — the old count only translates when the
  rule was exactly one team (otherwise every subject keeps its own bar:
  users approve personally, teams default to 1).
- `approval_requests`: the three snapshot columns collapse into one
  `approvers` JSONB of the same entries; in-flight requests convert.

Revision ID: a107c0nd1t10n
Revises: 87ca350e4aef
Create Date: 2026-07-30
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a107c0nd1t10n"
down_revision = "87ca350e4aef"
branch_labels = None
depends_on = None

_LEGACY_BUILTIN = {
    "require_assignee": "assignee",
    "require_team": "team",
    "require_estimate": "estimate",
    "require_comment": "comment",
}


def _names(bind, table: str) -> dict[str, str]:
    return {
        str(row_id): name
        for row_id, name in bind.execute(sa.text(f"SELECT id, name FROM {table}")).all()
    }


def _entries(user_ids, team_ids, required, users: dict, teams: dict) -> list[dict]:
    entries: list[dict] = []
    for uid in user_ids or []:
        uid = str(uid)
        entries.append({"kind": "user", "id": uid, "name": users.get(uid, uid)})
    team_list = [str(tid) for tid in (team_ids or [])]
    sole_team = len(team_list) == 1 and not (user_ids or [])
    for tid in team_list:
        entries.append(
            {
                "kind": "team",
                "id": tid,
                "name": teams.get(tid, tid),
                "required": int(required or 1) if sole_team else 1,
            }
        )
    return entries


def _field_rule(kind: str, key: str) -> dict:
    return {"check": "require_field", "params": {"kind": kind, "key": key, "op": "set"}}


def upgrade() -> None:
    bind = op.get_bind()
    users = _names(bind, "users")
    teams = _names(bind, "teams")

    # --- approval_requests: three snapshot columns -> one entries list ---
    op.add_column(
        "approval_requests",
        sa.Column(
            "approvers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    for row_id, user_ids, team_ids, required in bind.execute(
        sa.text(
            "SELECT id, approver_user_ids, approver_team_ids, required"
            " FROM approval_requests"
        )
    ).all():
        bind.execute(
            sa.text("UPDATE approval_requests SET approvers = :entries WHERE id = :id"),
            {
                "entries": json.dumps(_entries(user_ids, team_ids, required, users, teams)),
                "id": row_id,
            },
        )
    op.drop_column("approval_requests", "approver_user_ids")
    op.drop_column("approval_requests", "approver_team_ids")
    op.drop_column("approval_requests", "required")

    # --- workflow_transitions.rules: legacy checks -> structured conditions ---
    for row_id, rules in bind.execute(
        sa.text("SELECT id, rules FROM workflow_transitions")
    ).all():
        new_rules: list[dict] = []
        for rule in rules or []:
            check = rule.get("check")
            params = rule.get("params") or {}
            if check in _LEGACY_BUILTIN:
                new_rules.append(_field_rule("builtin", _LEGACY_BUILTIN[check]))
            elif check == "require_fields":
                new_rules.extend(
                    _field_rule("custom", key) for key in params.get("keys") or []
                )
            elif check == "require_approval":
                new_rules.append(
                    {
                        "check": "require_approval",
                        "params": {
                            "approvers": _entries(
                                params.get("user_ids"),
                                params.get("team_ids"),
                                params.get("required"),
                                users,
                                teams,
                            )
                        },
                    }
                )
            else:
                new_rules.append(rule)
        bind.execute(
            sa.text("UPDATE workflow_transitions SET rules = :rules WHERE id = :id"),
            {"rules": json.dumps(new_rules), "id": row_id},
        )


def downgrade() -> None:
    """Lossy where the new model is richer: value conditions (is/is_not/gte/lte)
    drop entirely; per-entry counts collapse to max(entry required)."""
    bind = op.get_bind()
    _legacy_check = {value: key for key, value in _LEGACY_BUILTIN.items()}

    op.add_column(
        "approval_requests",
        sa.Column(
            "approver_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column(
            "approver_team_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "approval_requests",
        sa.Column("required", sa.Integer(), nullable=False, server_default="1"),
    )

    def _flat(entries) -> tuple[list[str], list[str], int]:
        user_ids = [e["id"] for e in entries or [] if e.get("kind") == "user"]
        team_ids = [e["id"] for e in entries or [] if e.get("kind") == "team"]
        required = max(
            [int(e.get("required") or 1) for e in entries or [] if e.get("kind") == "team"],
            default=1,
        )
        return user_ids, team_ids, required

    for row_id, entries in bind.execute(
        sa.text("SELECT id, approvers FROM approval_requests")
    ).all():
        user_ids, team_ids, required = _flat(entries)
        bind.execute(
            sa.text(
                "UPDATE approval_requests SET approver_user_ids = :u,"
                " approver_team_ids = :t, required = :r WHERE id = :id"
            ),
            {
                "u": json.dumps(user_ids),
                "t": json.dumps(team_ids),
                "r": required,
                "id": row_id,
            },
        )
    op.drop_column("approval_requests", "approvers")

    for row_id, rules in bind.execute(
        sa.text("SELECT id, rules FROM workflow_transitions")
    ).all():
        old_rules: list[dict] = []
        field_keys: list[str] = []
        for rule in rules or []:
            check = rule.get("check")
            params = rule.get("params") or {}
            if check == "require_field":
                if params.get("op") != "set":
                    continue  # value conditions have no legacy shape
                key = str(params.get("key") or "")
                if params.get("kind") == "builtin" and key in _legacy_check:
                    old_rules.append({"check": _legacy_check[key], "params": {}})
                elif params.get("kind") == "custom":
                    field_keys.append(key)
            elif check == "require_approval":
                user_ids, team_ids, required = _flat(params.get("approvers"))
                old_rules.append(
                    {
                        "check": "require_approval",
                        "params": {
                            "user_ids": user_ids,
                            "team_ids": team_ids,
                            "required": required,
                        },
                    }
                )
            else:
                old_rules.append(rule)
        if field_keys:
            old_rules.append({"check": "require_fields", "params": {"keys": field_keys}})
        bind.execute(
            sa.text("UPDATE workflow_transitions SET rules = :rules WHERE id = :id"),
            {"rules": json.dumps(old_rules), "id": row_id},
        )
