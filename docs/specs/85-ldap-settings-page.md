# Spec 85 — Consolidated Directory (LDAP) settings + automatic user sync

User direction: stop scattering AD affordances — ONE instance
settings page for the directory. Define a users search DN and have Radd
import ALL of them automatically and keep them in sync; define a groups
search location, import groups and link them to teams FROM THAT PAGE. The
spec-84 Users page keeps ACCOUNT administration only (merge/dedupe/
deactivate); its AD import dialogs move here.

## 1. Editable directory settings (spec-50 cascade, INSTANCE-only keys)

- New SettingKeys (STRING/BOOL, instance scope only; env values are the
  cascade defaults so existing deploys keep working):
  - `ldap_user_sync_base` (default = env `ldap_user_search_base`)
  - `ldap_user_sync_enabled` (BOOL, default false — the automation switch)
  - `ldap_user_sync_deactivate_missing` (BOOL, default false — deactivate
    ldap-source users that vanish from the directory; OFF by default so a
    transient AD outage can't lock people out)
  - `ldap_group_search_base` (default = env-derived base_dn)
- All directory searches (user sync, group browser, group import) resolve
  through the cascade, not raw env.

## 2. Automatic user sync (the "just grab all of them" ask)

- PeriodicLoop `ldap-usersync` (interval `RADD_LDAP_USER_SYNC_SECONDS`,
  default 3600; gated run_workers + bind account + `ldap_user_sync_enabled`):
  search the configured base → PROVISION unknown users (source=ldap, SSO-only
  accounts, default-workspace member seat — the spec-84 import path), UPDATE
  changed display names/emails on ldap-source users, and — only when the
  toggle is on — DEACTIVATE ldap-source users missing from the directory
  (never touches local/oidc accounts; revokes sessions like the manual
  deactivate).
- `POST /ldap/sync/users` = the same pass on demand (instance admin, 409
  without bind account). Results recorded in a tiny `directory_sync_state`
  table (kind PK user_sync|group_sync, last_run_at, last_result JSONB:
  provisioned/updated/deactivated/errors) served by `GET /ldap/sync-status`.
- Group reconcile (spec 84's hourly loop) reports into the same state table.

## 3. Groups from the configured location

- `GET /ldap/groups` honors `ldap_group_search_base` (q narrows within it).
- The page lists discovered groups with their LINK STATE (linked team name
  when a team has that DN) and per-row actions: **Import as team** (choose
  workspace; provision-members checkbox), **Link to existing team** (team
  picker), **Unlink**. Bulk select → import. (Auto-creating a team for every
  AD group is deliberately NOT done — a base can hold hundreds of groups;
  import stays a click, sync of linked teams is already automatic.)

## 4. The page (web) + de-scattering

- New instance-admin settings tab **Directory** (`/settings/directory`):
  1. Status card — host, bind account, enabled flags (instance/status).
  2. **User sync** card — base DN input, enable toggle, deactivate-missing
     toggle (ScopedSettingsEditor idiom), "Sync now", last-run result line.
  3. **Groups** card — base DN input, search box, the group table of §3.
- Users page: AD import dialogs REMOVED (pointer link "Directory settings →"
  where they were); it keeps search/filters/badges/deactivate/duplicates/
  merge. Teams settings keep the per-team directory picker (contextual), but
  the Directory page is the central place.
- Members page subtitle clarifies scope ("this workspace's membership —
  server-wide accounts live in Users").

## 5. Tests

- Sync pass service-level with stubbed directory: provisions new, updates
  renamed, deactivates missing ONLY when toggled, never touches local/oidc.
- Settings resolution: cascade override beats env default.
- Sync-state read endpoint shape.

## Known simplifications

- One users base + one groups base (no multi-OU lists yet — the filter env
  stays for shaping).
- Deactivate-missing trusts one clean read; no quorum/grace window beyond
  the OFF default.

## As-built notes

Shipped as specced; migration `12e3da9fab36` (`directory_sync_state` — the
ldap module's first table), 4 new tests in `server/tests/test_directory_sync.py`
(812 total green). Implementation shape:

- **Registry**: `SettingSpec` grew `config_attr` — the env-default attribute
  when it differs from the key name. Only `ldap_user_sync_base` uses it
  (default = the pre-existing `RADD_LDAP_USER_SEARCH_BASE`); the other three
  keys got real config attrs (`ldap_group_search_base`, `ldap_user_sync_enabled`,
  `ldap_user_sync_deactivate_missing`, all env-settable). Empty base DNs fall
  back to `base_dn()` at USE time in `ldap.service.resolved_user_base()` /
  `resolved_group_base()` — the registered default stays the verbatim env value,
  mirroring how `user_search_base()` treats the raw env.
- **Base threading**: the async wrappers own cascade resolution (they have the
  session); the blocking ldap3 functions take the resolved base as a plain
  parameter (`search_directory_users(q, base)`, `_search_groups_sync(q, base)`,
  `_search_group_members_sync(dn, base)`). `groups.search_groups` /
  `search_group_members` now take the session as their first argument.
  `search_directory_users(base=None)` keeps the raw-env fallback for the
  session-less spec-49 script. Group LISTING searches under the group base;
  transitive MEMBER resolution searches under the user base (member entries
  are user objects — a groups-OU base would never contain them).
- **Matching is BY EMAIL** (the enumeration's dedupe key), so the sync updates
  display names only; a changed mail attribute reads as leaver+joiner (old
  account deactivates only when the toggle is on, new one is provisioned).
  Email-change-in-place is out of scope. The sync never REactivates a
  deactivated account that reappears — admin deactivation sticks.
- **Deactivation reuse**: `auth.service.deactivate_user(session, user,
  actor_id)` — active=False + `revoke_sessions()` (the seam the spec-84 PATCH
  now also revokes through) + a `user.updated` event with the new
  `UserChange.DIRECTORY_DEACTIVATED` action.
- **Loop gating**: `ldap-usersync` start-gates on `run_workers AND
  bind_account_enabled()` (the PeriodicLoop contract checks `enabled` at
  startup only); the `ldap_user_sync_enabled` cascade value is re-resolved
  INSIDE each tick, so the Directory-page toggle arms/disarms without a
  restart. `sleep_first=True`; "Sync now" covers immediacy.
- **State rows**: both loops + `POST /ldap/sync/users` upsert
  `directory_sync_state` (user_sync: {provisioned, updated, deactivated,
  errors}; group_sync: {teams, added, removed, errors}; error lists capped at
  20). `GET /ldap/sync-status` is instance-admin but does NOT require the bind
  account — a de-configured deploy can still read history.
- **Web**: `/settings/directory` (nav tab "Directory", instance-admin).
  `ScopedSettingsEditor` grew `filter` + `disabled` props — the Directory page
  picks its keys (disabled + amber hint when no bind account), the General tab
  excludes them (`DIRECTORY_SETTING_KEYS` in lib/types). Spec-84's dialogs were
  REUSED from `components/settings/DirectoryImportDialogs.tsx` (they were never
  inline in users.tsx, so no move): `ImportUsersDialog` behind the User-sync
  card's "Import users…", `ImportGroupsDialog` with a new `preselected` prop
  (fixed pre-checked list, no in-dialog search) behind the group table's
  per-row "Import as team" and bulk "Import selected". Link state resolves via
  a new instance-wide `allTeamsQuery` (GET /teams without workspace_id; query
  key shares the "teams" prefix so existing invalidations refresh it);
  link/unlink are the ordinary team PATCH. users.tsx keeps a pointer link
  ("Import from AD → Directory settings"); members.tsx subtitle now points
  server-wide accounts at Users. The per-team picker on Teams stays.
- **Real-AD still unverified**: everything spec-85 ran against stubbed
  searches + the test DB only — the cascade-resolved bases against a live
  directory, the usersync loop end-to-end, and a real deactivate-missing pass
  have not touched the configured AD (the running :8000 predates this build;
  next restart arms `ldap-usersync`, dormant until `ldap_user_sync_enabled`
  is switched on).
