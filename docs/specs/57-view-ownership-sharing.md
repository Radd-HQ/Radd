# Spec 57 — View ownership + sharing (users, teams, levels, transfer)

**Status: shipped** (rounds 17–18 of the polish thread).

## Problem

Pre-57, "sharing" a view meant surrendering it: `owner_id` went NULL, every
workspace member saw it, and only holders of the `view.*` RBAC atoms could
edit it. No team-scoped visibility, no per-grantee permissions, no way to
share an existing personal view, and workspace views were visible to everyone
regardless of team.

## Model

- **Ownership is never surrendered.** `views.owner_id` = the creator, in every
  visibility mode. The owner has full control: edit, manage sharing, delete —
  and *only* the owner re-shares/deletes (admins included: not shared with you
  ⇒ the view does not exist for you, 404).
- **`view_shares`** — one grant per row: exactly one of `user_id`/`team_id`,
  at a `ShareLevel` (`viewer` | `editor`). FK CASCADE on view/user/team.
  Replaced atomically via `PUT /views/{id}/sharing` (owner-gated), mirroring
  the field-permissions full-list-replace pattern.
- **`views.workspace_access`** (`ShareLevel | NULL`) — what every workspace
  member gets; NULL = not workspace-visible. Turning it on is a broadcast and
  is gated on `view.create` (same bar as creating a workspace-shared view).
- **Visibility** = owner ∪ direct user grants ∪ team grants (via membership) ∪
  all members when `workspace_access` is set. Enforced in `list_views` and on
  every single-view access.
- **Levels:** `viewer` sees it; `editor` edits the view *definition*
  (query/axes/filters); `owner` = **co-ownership** (round 18): full control —
  edit, re-share, delete, transfer. Grantable to people or teams; never valid
  for `workspace_access` (anyone in the workspace could delete/transfer —
  409). Item visibility/editing inside the view is untouched — that's item
  RBAC.
- **Transfer (round 18):** `POST /views/{id}/transfer {user_id}` — the owner
  or a co-owner reassigns `owner_id`. The target must hold `item.read` in the
  view's scope (409 otherwise, incl. deactivated users); the target's
  now-redundant grant rows are dropped; the PREVIOUS owner stays on as an
  editor grantee so a transfer never locks anyone out by accident (the new
  owner can revoke). Exposed in the modal's Sharing section ("Transfer
  ownership to…", applied last on save — after the sharing PUT, since the
  actor may lose manage rights the moment it lands).
- **Legacy** (pre-57 rows, `owner_id` NULL): migration `5e4a41d09ca0` backfills
  `workspace_access='viewer'`; the `view.update`/`view.delete` atoms keep
  managing them (there is no owner to ask).

## API

- `ViewRead` gains `owner` (ref), `workspace_access`, `shares[]`, and
  per-actor `can_edit`/`can_manage` computed server-side (the client never
  re-derives team membership). `shared` = visible beyond the owner.
- `ViewCreate` gains `workspace_access` + `shares[]` (sharing at birth);
  `shared: true` remains as the pre-57 alias for `workspace_access=viewer`.
  User/team sharing needs only `item.read`; workspace_access needs `view.create`.
- `PUT /views/{id}/sharing {workspace_access, shares[]}` — full-state replace.
  409s: duplicate subject, unknown user, team outside the workspace.
- User-merge repoints `view_shares.user_id` (dedupe inventory).

## Frontend

`ViewSharingEditor` in the view modal (shown to the owner / on create):
workspace-access select ("no access / can view / can edit", disabled without
view-manage rights) + person/team grant rows with levels. Sharing state saves
inline on POST, via the PUT on edit. The view page gates Edit on `can_edit`,
Delete on `can_manage`, and shows "by {owner}" when the view isn't yours.

## Tests

`tests/test_view_sharing.py` — the matrix: visibility (owner/direct/team/
outsider-404), viewer-403 vs editor-edit, owner-only re-share + delete,
revocation, broadcast gate, legacy atom fallback.
