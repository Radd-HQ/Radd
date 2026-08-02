# Spec 87 — Directory-owned teams, per-team delegation, and grants that actually grant

**Status: shipped.**

User direction: *"AD groups need to be used for permission grants — we do it via
linking AD groups to Teams, which seems fine. But if an AD group is linked to a
team I don't want it modifiable, it becomes read-only from AD, otherwise it gets
messy really quickly. I also want local teams that include AD users. And I don't
want just anybody creating/editing Teams — but I do want some sort of per-team
grant so a team leader can modify only that specific team."*

Plus, from the same session: *"make sure there aren't any other dead or useless
grants."* That audit turned out to be the largest part of the work.

## 1. The audit that reframed the problem

Cross-referencing every `Permission` member against every `authz.require` call
found three classes of dead grant:

**Class 1 — atom exists, endpoint doesn't.** The roles matrix rendered a
checkbox that could never do anything: `label.update`, `label.delete`,
`state.delete`, `field.delete`, `webhook.delete`, `team.delete`, `user.delete`,
`import.run`.

**Class 2 — endpoint exists but ignores the atom.** `PATCH /users/{id}` called
`_require_instance_admin()` directly; `dashboard.update`/`dashboard.delete` were
superseded by spec-57 ownership before they ever had a caller.

**Class 3 — the systemic one.** ALL 47 global-scope atoms were undeliverable.
`global_scope_permissions()` branched on `users.instance_role` and never read a
role's permission set, and roles attach only to projects
(`project_members`/`project_teams`). So there was no path by which a non-admin
could hold `label.create`, `team.update`, `cycle.create`, `sla.*`, `canned.*`,
`automation.*`, `role.*`, `user.*` or `dashboard.*` — while the matrix offered
all of them.

Class 3 is why the user's actual request could not be met by "just grant the
team lead `team.update`": that grant had no delivery mechanism, and even if it
had, it would have granted *every* team.

## 2. Global role grants (Class 3)

`global_role_grants` — one row = one role held instance-wide by a user or a
team; exactly one of `user_id`/`team_id` (CHECK-constrained), the `view_shares`
shape. `auth/grants.py` resolves them: the subjects are the person plus every
team they are in.

**Reach: both scopes.** `global_scope_permissions(role, permission_sets)` unions
them at global scope, and `_granted_role_ids` adds them on every project. The
alternative (global scope only) would have minted a *new* dead grant — every
project-scoped atom inside a globally-granted role. Because both feed off the
same two helpers, `permissions_for_projects` and `subjects_for` (field grants)
inherit the behavior for free.

`GET/PUT /roles/{id}/global-grants`, full-state replace, gated on `role.update`
— which, like editing a role's permission set, is escalation-equivalent to
instance admin and documented as such. A grant RESTRICTs deletion of its role.

`/auth/me` now returns `effective_permissions()` rather than a re-derived union,
so grants reach the SPA's gates.

## 3. Atoms removed (Classes 1 & 2)

Built the missing endpoints where the capability was genuinely wanted:
`PATCH`/`DELETE /labels/{id}`, `DELETE /states/{id}` (409 if it is the project
default or holds items — deleting must never silently relocate work),
`DELETE /fields/{id}`, `DELETE /webhooks/{id}`, `DELETE /teams/{id}`.

Dropped four atoms outright: `user.delete` and `import.run` (no endpoint could
exist — accounts are deactivated/merged, the importer is a CLI script) and
`dashboard.update`/`dashboard.delete` (ownership decides). Migration
`3a363a121502` strips them from stored role JSONB — `RoleRead.permissions` is
`list[Permission]`, so a stale string would 500 `GET /roles`.

`PATCH /users/{id}` now honors `user.update`, with `instance_role` changes kept
behind a hard instance-admin check so the atom cannot be a self-serve route to
admin.

The `*.manage` umbrellas that never appear in a `require()` are NOT dead —
they expand via `IMPLIED_PERMISSIONS`.

## 4. Directory-owned teams

`teams.source` (`TeamSource` local|directory) makes "membership belongs to AD" a
first-class state rather than a `directory_group_dn IS NOT NULL` inference.
`ensure_membership_editable` refuses add/remove on a directory team **in the
service**, so every caller gets the same answer.

- **Linking** re-sources the whole roster to `directory`. Left as `manual`,
  those rows would be permanently frozen: unremovable by hand, invisible to the
  sync.
- **Unlinking** re-sources to `manual`. Nobody loses access the moment the link
  goes, which makes unlink the safe escape hatch.
- **Name and project grants stay local.** AD CNs (`SG-RND-Pipeline-RW`) make
  poor display names, and deciding what an AD group may do *here* is the entire
  point of linking it.

Migration `78c86f700dbe` backfills `source='directory'` for linked teams but
deliberately does NOT re-source their existing rows — under spec 84 a linked
team could carry hand-added members, and converting them would let the next
reconcile delete anyone absent from AD, i.e. an upgrade that silently revokes
access.

**Stale-group guard.** An empty transitive member search is ambiguous: the group
may be empty, or renamed/deleted (exactly what happens in a domain reorg).
Believing the second revokes everything the team grants. `reconcile_team` now
confirms the DN still resolves before acting, raising `StaleDirectoryGroup` and
flagging `teams.directory_missing_since`. While that flag is set,
`sync_login_membership` holds removals too — otherwise the login path drains the
team one sign-in at a time, around the periodic guard.

**A broken link does NOT unlock the team** (user direction): while
the link is in place the roster is read-only, full stop. A missing group keeps
its people and stops all removals, but re-opening editing is a deliberate human
act — unlink. The server never infers "unlink me" from a directory it may be
failing to read correctly. The Teams page shows an amber `AD group missing` badge
on the row, and the panel a banner with a one-click **Unlink and edit here**.

That guarantee needs a reliable signal, so `get_group()` no longer answers `None`
for everything. It returns `None` only for a genuine not-found and raises
**`DirectoryUnreachable`** when the directory cannot be asked — connection
refused, bind rejected, timeout — including from the eager `auto_bind` in
`service_connection()`, which previously escaped the `try` entirely. An outage
now propagates (the run records an error and touches nothing) instead of
flagging healthy teams as stale and telling an admin their AD is wrong.

## 5. Per-team delegation

`teams.owner_id` + `team_managers` (the spec-57 ownership idiom). A manager need
not be a member — a lead may run a team they are not on — and the row is
independent of `team_members`, so it survives a directory sync.

Two tiers in the router:

- `_require_manage` = `team.update` atom ∪ owner ∪ manager → roster + rename.
- `_require_own` = `team.update` atom ∪ owner → appointing managers, transfer.
  A delegate must not be able to appoint further delegates or hand the team away.

**The safety property:** a team leader decides *who is on their team*, never
*what their team is entitled to*. Attaching a team to a project is
`member.create` on that project, held by project admins. Linking to AD stays on
the global atom for the same reason.

`DELETE /teams/{id}` is refused while the team still grants project access —
dropping it would silently revoke everyone, and the project's access list is
where that decision belongs. Transfer keeps the previous owner as a manager (no
accidental lockout). Pre-87 teams have `owner_id` NULL: a supported state that
falls back to the atoms, not a gap to backfill by guessing.

## API

- `GET/PUT /roles/{id}/global-grants`
- `PATCH /labels/{id}`, `DELETE /labels/{id}`, `DELETE /states/{id}`,
  `DELETE /fields/{id}`, `DELETE /webhooks/{id}`, `DELETE /teams/{id}`
- `PUT /teams/{id}/managers`, `POST /teams/{id}/transfer`
- `TeamRead` gains `source`, `owner_id`, `managers`, and per-actor
  `can_manage`/`can_delete` (resolved server-side — per-team delegation is not
  visible in the permission union, so the client cannot re-derive it)
- `MeRead` gains `manages_teams` — same reason: it gates the Teams settings nav
  for a leader who holds no global team atom

## Frontend

Teams settings: an AD badge on directory rows, a locked read-only roster with
the reason and the way out, and `TeamStewardship` (owner, managers, transfer,
delete) shown to owners and atom holders. Roles settings: `RoleGlobalGrants` per
role — the UI that makes global atoms grantable at all — invalidating
`authState` on save since effective permissions change.

## Tests

- `tests/test_global_grants.py` — delivery of a global atom, resolution via
  team, umbrella expansion, project-scope reach (direct + batched), full-state
  replace, subject validation, role-deletion guard, inactive users hold nothing.
- `tests/test_team_delegation.py` — stewardship is per-team, transfer keeps the
  old owner as manager + refuses inactive targets, delete blocked while
  attached, directory rosters read-only, and the vanished-group guard across
  both sync paths.
- `tests/test_crud_completion.py` — the state-delete guards and label rename
  collision.
- `tests/test_ad_depth.py::test_reconcile_team_joiner_leaver_and_idempotent` was
  rewritten: it previously asserted spec-84 mixed membership (a manual row
  surviving on a linked team), a state now unreachable through any real path.
