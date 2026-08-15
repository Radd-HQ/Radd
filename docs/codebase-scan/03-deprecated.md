# Deprecated paths and compatibility shims still carried

82 lines across `server/src/radd` match deprecation vocabulary
(`legacy|deprecat|superseded|obsolete|no longer used`). Most are *historical
notes* explaining why something looks the way it does — those are valuable and
are not listed. What follows is live compatibility code: branches that exist
only for data or callers predating a spec.

---

## 1. "Legacy owner-less views" — **CORRECTED (RADD-895): permanent policy, not an ageing shim**

The scan framed the second authorisation path in `modules/views/service.py` as
"a permanent branch serving a finite, ageing set of rows" and recommended a
count-then-backfill retirement. That framing was wrong, and RADD-895 renamed
the vocabulary to say so: the docstrings now read **"SEEDED owner-less
views"** (service.py:67, :117, :193, :536, :562) — every new project seeds
plain Board/List/Planning views (specs 61-67), those rows are deliberately
owner-less, and the `view.*` RBAC-atom fallback is their intended authz path.
The set can never reach zero, so the retire-by-backfill recommendation is
moot. Kept as recorded history: the original observation that every view
write asks two questions (owner/editor grant, else — `owner_id IS NULL` — an
RBAC atom) is accurate; it is design, not backcompat residue.

## 2. `FieldDefinitionCreate.project_id` — **CORRECTED (RADD-895): retired**

At scan time `fields/schemas.py` carried `_fold_legacy_scope`, folding the
legacy single-scope `project_id` alias into `project_ids` (spec 91 gave custom
fields multi-project scope). The scan said "retire when a major version lets
the API break"; RADD-895 ("the backcompat mechanisms are gone", commit
00182d7) took the no-backcompat-until-V1 route instead — the validator is
deleted and `FieldDefinitionCreate` takes `project_ids` only
(`grep -rn _fold_legacy_scope server/src` → 0).

## 3. `teams/types.py` fixed role ladder — **CORRECTED (RADD-893): deleted**

The scan quoted the "Legacy fixed role ladder" docstring and asked "check
whether anything still reads it; if not, this is a straight delete". Nothing
did, and the RADD-893 dead-code sweep took it: `teams/types.py` today holds
`TeamEvent`/`TeamEntity`/`TeamChange` plus the RADD-829 retirement note, and
`grep -rn ProjectRole` across `server/src`, `web/src` and `sdk` returns only
two migration docstrings.

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

## 6. Spec-86 workspace residue — see `05-comments.md` — **FIXED (RADD-1097)**

The workspace entity is gone; two comments described it as live scope. The
RADD-1097 rename-residue sweep deleted both — details in `05`.

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
