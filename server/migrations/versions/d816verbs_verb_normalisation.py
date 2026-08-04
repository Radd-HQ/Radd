"""d816verbs: every verb means one thing (RADD-816)

The destructive atom rewrite, in the RADD-701 treatment and under the
no-backcompat rule — no alias survives:

- Nine manage umbrellas with ZERO direct enforcement sites (view/cycle/label/
  release/canned/cardpreset/sla/team/role) are DELETED; stored occurrences in
  role JSONB and api_tokens.scopes rewrite to their create/update/delete
  triple, so every holder keeps exactly the authority the umbrella expanded to.
- `attachment.delete` meant "your own" — it becomes `attachment.delete@own`
  (what it meant), and the unqualified atom now means ANYONE's (nobody held
  that meaning, so nobody gains it here).
- `service_account.delete` had no route; dropped outright.
- The Baseline row gains the Q4 author-own grants (`comment.delete@own`,
  `worklog.delete@own`, `attachment.delete@own`) and the six F6 catalog read
  atoms — the rights everyone already had, as revocable grants.

A stale atom in role JSONB 500s GET /roles the moment the matrix opens
(RoleRead.permissions is typed) — this migration is what prevents that.

Revision ID: d816verbs
Revises: d841searchrel
Create Date: 2026-08-04
"""
import json

import sqlalchemy as sa
from alembic import op

revision = 'd816verbs'
down_revision = 'd841searchrel'
branch_labels = None
depends_on = None

_TRIPLES = {
    "view.manage": ["view.create", "view.update", "view.delete"],
    "cycle.manage": ["cycle.create", "cycle.update", "cycle.delete"],
    "label.manage": ["label.create", "label.update", "label.delete"],
    "release.manage": ["release.create", "release.update", "release.delete"],
    "canned.manage": ["canned.create", "canned.update", "canned.delete"],
    "cardpreset.manage": ["cardpreset.create", "cardpreset.update", "cardpreset.delete"],
    "sla.manage": ["sla.create", "sla.update", "sla.delete"],
    "team.manage": ["team.create", "team.update", "team.delete"],
    "role.manage": ["role.create", "role.update", "role.delete"],
}
_RENAMES = {"attachment.delete": "attachment.delete@own"}
_DROPPED = {"service_account.delete"}

_BASELINE_ADDITIONS = [
    "comment.delete@own",
    "worklog.delete@own",
    "attachment.delete@own",
    "label.read",
    "cycle.read",
    "canned.read",
    "team.read",
    "role.read",
    "cardpreset.read",
]


def _rewrite(atoms: list) -> list:
    out: list[str] = []
    for atom in atoms:
        atom = str(atom)
        if atom in _DROPPED:
            continue
        if atom in _TRIPLES:
            out.extend(a for a in _TRIPLES[atom] if a not in out)
            continue
        renamed = _RENAMES.get(atom, atom)
        if renamed not in out:
            out.append(renamed)
    return out


def upgrade() -> None:
    conn = op.get_bind()
    # 1. role JSONB
    for role_id, permissions in conn.execute(
        sa.text("SELECT id, permissions FROM roles")
    ).fetchall():
        atoms = permissions if isinstance(permissions, list) else json.loads(permissions)
        rewritten = _rewrite(atoms)
        if rewritten != list(atoms):
            conn.execute(
                sa.text("UPDATE roles SET permissions = :perms WHERE id = :id"),
                {"perms": json.dumps(rewritten), "id": role_id},
            )
    # 2. Baseline gains the Q4 + F6 grants (append, dedupe, keep order)
    row = conn.execute(
        sa.text("SELECT id, permissions FROM roles WHERE key = 'baseline'")
    ).fetchone()
    if row is not None:
        atoms = row[1] if isinstance(row[1], list) else json.loads(row[1])
        merged = list(atoms) + [a for a in _BASELINE_ADDITIONS if a not in atoms]
        conn.execute(
            sa.text("UPDATE roles SET permissions = :perms WHERE id = :id"),
            {"perms": json.dumps(merged), "id": row[0]},
        )
    # 3. api_tokens.scopes (spec 113): {"global": [...], "projects": {id: [...]}}
    for token_id, scopes in conn.execute(
        sa.text("SELECT id, scopes FROM api_tokens WHERE scopes IS NOT NULL")
    ).fetchall():
        data = scopes if isinstance(scopes, dict) else json.loads(scopes)
        changed = False
        if isinstance(data.get("global"), list):
            rewritten = _rewrite(data["global"])
            changed |= rewritten != data["global"]
            data["global"] = rewritten
        for pid, atoms in (data.get("projects") or {}).items():
            rewritten = _rewrite(atoms)
            changed |= rewritten != atoms
            data["projects"][pid] = rewritten
        if changed:
            conn.execute(
                sa.text("UPDATE api_tokens SET scopes = :scopes WHERE id = :id"),
                {"scopes": json.dumps(data), "id": token_id},
            )


def downgrade() -> None:
    # The rewrite is semantically lossless forward (umbrella == its triple) but
    # not invertible: nothing distinguishes a rewritten triple from one ticked
    # by hand. No-backcompat: downgrade is a no-op.
    pass
