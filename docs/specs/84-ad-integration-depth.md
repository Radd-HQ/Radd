# Spec 84 — AD/LDAP depth: team↔group links, group import, user administration

User direction: teams linkable to AD groups (nested membership honored), group
import from the directory, a real user-administration surface for
LDAP-provisioned accounts, and a UI for merging duplicate users across auth
sources. Builds on spec 42 (direct bind + transitive admin groups), spec 49
(service-account enumeration), and the existing `POST /users/{id}/merge`.

## 1. Team ↔ AD group links (nested-aware)

- `teams.directory_group_dn` (nullable TEXT) + `directory_group_name` (CN for
  display). Set/cleared via the team PATCH (team.manage).
- `team_members` gains `source` (StrEnum manual|directory, default manual):
  sync touches ONLY directory-source rows — hand-added members are never
  removed by a sync, and a manual add of a synced user stays manual.
- Membership resolution uses the transitive matching rule
  (LDAP_MATCHING_RULE_IN_CHAIN, the spec-42 idiom) so NESTED groups count.
- Sync paths:
  a. **On LDAP login**: after bind, the user's transitive membership against
     each linked team's DN → join/leave that user's directory-source rows
     (mirrors the admin-group re-sync).
  b. **Periodic reconcile** (service account required): PeriodicLoop
     `ldap.groupsync` (interval `RADD_LDAP_GROUP_SYNC_SECONDS`, default 3600,
     gated bind-account-configured + run_workers): per linked team, search
     transitive members, match to EXISTING Radd users (UPN/email), reconcile
     directory-source rows. Unknown directory members are NOT auto-provisioned
     here (import is explicit).
  c. **On-demand**: `POST /teams/{id}/directory-sync` (team.manage; 409 when
     no bind account) → the same reconcile, returns {added, removed}.

## 2. Group import

- `GET /ldap/groups?q=` (instance admin; 409 without a bind account) →
  `[{cn, dn, description, member_count}]` via a paged group search.
- `POST /ldap/groups/import {workspace_id, group_dns: [...],
  provision_members: bool}` → per group: create-or-link a team (name = CN,
  linked via §1), resolve transitive members, optionally PROVISION unknown
  users (the spec-42 provision path), add directory-source memberships.
  Response: per-group {team_id, created, members_added, users_provisioned}.

## 3. User administration

- `users.source` (StrEnum local|ldap|oidc|unknown): set at creation/provision
  going forward; migration backfills local where a password hash exists,
  unknown otherwise. `users.last_login_at` (nullable) stamped on every
  successful login (all three paths).
- `PATCH /users/{id}` (instance admin): `active` (deactivate revokes
  sessions + blocks login incl. LDAP/OIDC), `name`. If an update endpoint
  already exists, extend it.
- `GET /users` grows filters: `q` (email/name), `source`, `active`; response
  carries source/active/last_login_at (+ workspace memberships summary).
- `GET /users/duplicates` (instance admin): candidate groups sharing a
  normalized email local-part or exact case-insensitive name — feeds the
  merge UI; heuristic only, never auto-merges.
- **Admin Users page** (web, the instance users surface): columns email /
  name / source badge / active / last login / workspaces; search + source +
  active filters; row actions: activate/deactivate; a "Possible duplicates"
  section and a select-two → **Merge dialog** (pick the survivor, shows what
  the merge does) calling the existing endpoint; an **Import from AD**
  affordance (directory user search → select → provision) and an **Import
  groups** dialog (§2). Teams settings: a "Directory group" field on the
  team editor (DN picker via the group search) + "Sync now" with the
  added/removed result.

## 4. Tests

- Pure reconcile planner: directory memberships × existing rows → add/remove
  sets (manual rows untouched; leaver removed; joiner added once).
- Source backfill + PATCH deactivate revokes sessions (DB-backed).
- Group import service with a stubbed directory search (match the existing
  ldap test style); duplicates heuristic.

## Known simplifications

- Reconcile matches directory members to EXISTING users only; provisioning
  stays an explicit import action.
- One directory (the configured AD); no multi-forest.
- Group sync trusts the bind account's read view; no delta/USN tracking —
  full reconcile per tick at a long interval.

## As-built notes

Shipped exactly as specced; migration `8dcb99d261e6`, 13 new tests in
`server/tests/test_ad_depth.py` (808 total green). Implementation shape:

- **Planner is pure and idempotent** — `ldap/groupsync.plan_reconcile(emails,
  rows, users_by_email)`: add = resolved directory members with NO row of any
  source (a manual row blocks a duplicate directory add — team_members' PK is
  (team, user), so this is also what keeps the apply conflict-free); remove =
  directory-source rows no longer in the group. Applied via
  `teams.service.apply_directory_membership` (inserts DIRECTORY rows, deletes
  ONLY DIRECTORY rows, emits one `team.updated`/`directory_synced` with
  added/removed counts when anything changed).
- **Directory wire code** stays the spec-42 pattern: sync `ldap3` under
  `asyncio.to_thread`. Group ops live in `ldap/groups.py` on the spec-49
  service connection (extracted as `service.service_connection()`); the login
  path's linked-team probing extends `_bind_and_lookup` (the direct-bind
  connection answers `memberOf:1.2.840.113556.1.4.1941:=<team dn>` per linked
  team; matches ride back on `DirectoryUser.team_group_dns`).
- **`member_count` on GET /ldap/groups is the DIRECT `member` attribute
  length** (documented in the schema) — cheap display; sync/import always
  resolve transitively.
- **PeriodicLoop** `ldap-groupsync` registered via the ldap module's
  `on_startup/on_shutdown` (its first ever), `sleep_first=True`, gated
  `run_workers AND bind_account_enabled()` — config read live per tick.
- **`last_login_at` is stamped in `auth.service.create_session`** rather than
  three call sites: sessions are minted exclusively by the login endpoints
  (local, TOTP, LDAP, OIDC), so the one seam covers all paths by construction.
- **`users.source` upgrade rule**: ldap/sso `provision` claims a pre-84
  `unknown` row on login (never overwrites local/oidc/ldap). The spec-49
  script is untouched (it creates password accounts → `local`); the new
  in-app import provisions SSO-only `source=ldap` accounts instead.
- **Import provisioning bypasses `RADD_LDAP_AUTO_PROVISION`** — that flag
  gates *login-time* provisioning; an explicit admin import with
  `provision_members=true` is its own authorization. Group-import provisioned
  users get a member seat in the TARGET workspace; user-import provisioned
  users get one in `RADD_LDAP_DEFAULT_WORKSPACE_SLUG` (what first login would
  have done).
- **409 vs 403**: missing bind account answers 409 (deploy incomplete) on all
  spec-84 endpoints; missing instance-admin stays 403.
- **Web**: new `/settings/users` page (instance-admin nav tab "Users"): table
  w/ source badges (Local/AD/SSO/Unknown), activate/deactivate (self-row
  hidden), last-login, workspace summary, debounced q + source/active filters;
  "Possible duplicates" cards → survivor-radio Merge dialog (sequential
  `POST /users/{id}/merge` for >2-account groups); Import-from-AD +
  Import-groups dialogs gated on `instance/status.ldap_bind_account` (new
  field). Teams settings `TeamPanel` grew a Directory-group row (CN chip +
  unlink, group search picker for instance admins, "Sync now" → "+A / −R"
  toast) and AD badges on directory-sourced members.
- **Real-AD verification (read-only against the configured
  directory — the bind account was live in the dev env)**: the paged group
  search (q + counts + descriptions), BASE-scope group lookup by DN (and a
  clean None for a missing DN), TRANSITIVE whole-group member resolution
  (`2d-hods-ldn` → 2 members, correct username/mail/displayName), and the
  q-narrowed user filter all ran against the real AD and returned correct
  results. Still unverified against a real directory: the login-time
  linked-team probe (needs a real direct-bind login) and the WRITE paths
  (group import / reconcile / periodic loop — exercised only with stubbed
  search + a test DB; nothing was linked or imported in the live instance).
  Note for the next restart of :8000: with the bind account configured and
  run_workers on, the hourly `ldap-groupsync` loop arms — a no-op until some
  team is actually linked to a group.
- **Members merged into Users (web-only)**: with the workspace
  layer collapsed (spec 67), the separate settings Members page was duplicate
  scatter — deleted (`routes/settings/members.tsx` + its nav tab; the
  `/settings/members` route stays registered as a `beforeLoad` redirect to
  Users, the settings-index idiom, so old links survive). The Users table
  gained a **Workspace role** column joined client-side from
  `workspaceMembersQuery` (current workspace): the Members page's role
  dropdown (admin/member via `PATCH /workspaces/{id}/members/{user_id}`), an
  inline X remove (DELETE), and an "Add to workspace" action on active
  non-member rows (POST, default role member) — all workspace.manage-gated
  with the Members page's exact client-side self-row guard (own row: read-only
  badge, no remove; the server has no self guard). Nav gate widened to
  `ws(workspace.manage) OR instanceAdmin`. **GET /users gating decision: NO
  server change** — the endpoint was never instance-admin-only; it requires
  `user.manage` at GLOBAL scope, which workspace admins hold (global-scope
  admin → ALL), and the old Members page already read it. A non-instance
  workspace admin therefore sees the full read-only table (source badges,
  last-login, workspace summary, filters); the MUTATING instance-admin
  controls (activate/deactivate, duplicates+merge, the Directory pointer) stay
  hidden for them and API-403'd. Membership add/remove also invalidates the
  users queries (the rows' workspace-name summary changes).
