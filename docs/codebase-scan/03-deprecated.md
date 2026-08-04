# Deprecated paths and compatibility shims still carried

82 lines across `server/src/radd` match deprecation vocabulary
(`legacy|deprecat|superseded|obsolete|no longer used`). Most are *historical
notes* explaining why something looks the way it does — those are valuable and
are not listed. What follows is live compatibility code: branches that exist
only for data or callers predating a spec.

---

## 1. "Legacy owner-less views" — the largest shim, 8 sites

`modules/views/service.py` carries a second authorisation path throughout for
views created before spec 57 gave views an owner:

```python
# views/service.py:518
async def _require_manage(session, view_id, actor, *, legacy_atom: Permission):
    """… Legacy owner-less views fall back to the view.* RBAC atom (`legacy_atom`)."""
# :115  "…or — legacy owner-less views — a view.update holder in scope."
# :172, :495, :682, and router.py:114, :141
```

Every view write therefore asks *two* questions: the owner/editor grant, and —
if `owner_id IS NULL` — an RBAC atom. That is a permanent branch serving a
finite, ageing set of rows.

**Worth measuring before deciding:** `SELECT count(*) FROM views WHERE owner_id
IS NULL`. If it is zero on the live instance, the whole path can go. If it is
small, a backfill (assign the creator, or an admin) retires it. This is the
kind of shim that is cheap to keep and cheaper to remove once, and it interacts
directly with spec 115's access work — RADD-816 touches these atoms.

## 2. `FieldDefinitionCreate.project_id` — single-scope alias

```python
# modules/fields/schemas.py:13
# `project_id` is a legacy single-scope alias folded into project_ids
# :30
def _fold_legacy_scope(self) -> "FieldDefinitionCreate":
```

Spec 91 gave custom fields multi-project scope; the singular form is folded into
the list on the way in. Harmless and small. Retire when a major version lets the
API break, or keep — it costs one validator.

## 3. `teams/types.py` — a fixed role ladder that predates data roles

```python
# modules/teams/types.py:5
"""Legacy fixed role ladder. Since spec 06 project roles are DATA (auth `roles`…"""
```

An enum kept for readability of old code paths. Check whether anything still
reads it; if not, this is a straight delete.

## 4. `automations/types.py:19` — a sentinel predating its enum

```python
# Legacy alias — the sentinel predates the enum (kept so callers read naturally).
```

Deliberate and documented. Listed for completeness; no action recommended.

## 5. `workflow/guards.py:61` — verbatim failure strings

```python
# The legacy failure strings, kept verbatim — they're in toasts, tooltips and
```

Correct decision (user-visible copy should not churn silently). No action.

## 6. Spec-86 workspace residue — see `05-comments.md`

The workspace entity is gone; two comments still describe it as live scope.
Those are non-factual comments rather than dead code, so they are in `05`.

---

## Not deprecated, frequently mistaken for it

Recording these so a future sweep does not "clean" them:

- **`EMPTY_BASELINE`** (`auth/authz.py:77`) — looks like a leftover constant; it
  is a deliberate fail-closed default for a DB mid-migration. The comment at
  :72-76 explains it and should be kept.
- **`SYSTEM_ACTOR_ID`** — not dead; it is the documented actor for genuinely
  automated flows (webhook sweeps, connector links) per CLAUDE.md.
- **`PermissionScope.INSTANCE`** — declared, and no atom currently carries it.
  It is a real tier held for admin-only atoms, not drift; spec 115's contract
  test exempts it explicitly rather than tolerating it loosely.
- **`/integrations/alertmanager`** — uncalled by the SPA because Alertmanager
  calls it. See `02-dead-surface.md`.
