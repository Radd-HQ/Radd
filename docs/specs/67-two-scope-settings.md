# Spec 67 — Two-scope settings (instance → project) + project-level SLA policies

User direction: the spec-50 instance→workspace→project scalar cascade is one
layer too many for a single-workspace deployment — the workspace layer only
ever duplicated the instance one (there is exactly one workspace, PLAN §9).
Collapse to **INSTANCE (product defaults) → PROJECT (overrides)**. In the same
move, SLA policies stop being workspace-wide-with-optional-project and become
plainly **project-level**, and the settings IA is re-cut: the Instance page
keeps only server/deploy status while a "General" tab holds the editable
product defaults.

## 1. Settings: the workspace scope is retired

- `SettingScope` = `INSTANCE | PROJECT`. Every registered `SettingSpec` is
  settable at both scopes; descriptions now say "the instance sets the
  default; projects override".
- `service.resolve(session, key, *, project_id?)` — resolution is project →
  instance → env/config default. The `workspace_id` parameter is gone; every
  caller updated (slas/evaluation, workflow/transitions, timelogging,
  cycles stats, csat sender, workspace `GET /instance`).
- `set`/`clear`/router: workspace scope now fails schema validation (422) —
  the enum shrink does it. Router gates: instance → instance admin, project →
  `project.manage`.
- Migration: workspace-scope rows are promoted to instance scope where no
  instance row exists for the key (one per key — newest `updated_at` wins,
  because NULL `scope_id`s don't collide under the unique constraint and
  duplicate instance rows would break the single-row lookups); the rest are
  deleted. Idempotent.

## 2. SLA policies become project-level

- `PolicyCreate.project_id` REQUIRED; the service derives `workspace_id` from
  the project (the column stays — denormalised for report/event queries).
  `PolicyUpdate` cannot move a policy to another project.
- `list_policies(session, project_id)`; `GET /sla-policies?project_id=`
  (item.read on that project) replaces the `workspace_id` param.
- `matched_policy(item)` = the item's project's enabled policies ordered
  (position, created_at), first priorities-filter match — the workspace-wide
  branch is gone. The engine now groups per project instead of per workspace;
  grouping-by-matched-policy is unchanged.
- Gating unchanged: `SLA_*` atoms stay workspace-scoped (admins), resolved via
  the policy's project's workspace.
- Migration: `DELETE FROM sla_policies WHERE project_id IS NULL` (workspace-
  wide policies can't be auto-assigned to a project; the live DB had none),
  then `project_id SET NOT NULL`.

## 3. Frontend

- `ScopedSettingsEditor` scope = instance | project. Badge on an un-overridden
  row: "Inherited" at project scope, "Default" at instance scope.
- Workspace settings **General** tab = the INSTANCE-scope editor ("Defaults
  for every project — each project can override these under its own
  settings"), nav-gated to instance admins (writes are instance-scope).
- The **Instance** tab is renamed **Server** and keeps only the deploy-status
  grid (SSO/LDAP/SMTP/MFA/AI/storage/workers/connectors) — its settings
  editor moved to General.
- SLA policies moved to **project settings → SLAs**
  (`/p/$projectKey/settings/sla`, `ProjectSettingsSection.sla`); the
  workspace-settings route/nav entry is gone. Nav gate = workspace
  `sla.manage` (same as the old page). The policy form lost its project
  selector — the project comes from the URL. Priority tiers / business hours /
  first-match ordering UI intact.

## As-built notes

- Migration `a7c2e19b4f30` (chained on `004bbb60df13`), covers both data moves;
  written defensively for other installs (multi-workspace promotion picks one
  row per key; both steps re-run clean).
- The cycle-stats handle (`GET /cycles/{id}/stats`) formats durations with the
  instance-default `timelog_hours_per_day` — cycles span projects, so there is
  no single project override to apply (was: workspace resolve).
- The project-settings nav items switched from a bare `permission` field to
  `show(perms, project)` predicates (settings-layout idiom) so the SLAs tab
  could gate on a workspace-scope permission.
- `tests/test_scoped_settings.py` reworked to the two-scope cascade;
  transition-mode tests now set the scalar at project scope; SLA tests create
  policies with `project_id`. Suite: 716 green (unchanged count).

## As-built follow-up (global scope + consolidation)

Same-day follow-up wave (user direction), four moves:

### 1. `timelog_hours_per_day` is instance-ONLY

"Remove the per project 8h/day, just make this a global instance setting" — a
`1d` duration must mean the same thing on every timesheet row and cycle handle.

- `SettingSpec.scopes` for the key = `(INSTANCE,)`; description reworded
  ("Global — one instance-wide value"). `set_value` already 409s on a scope
  outside the spec's `scopes` (verified — spec 50 built the guard); as extra
  defense `service.resolve` now filters its lookup order to the spec's scopes,
  so a stale project row could never shadow the key, and `list_for_scope`
  already hides it from the project editor.
- `timelogging.service`: `_hours_per_day(session, project)` +
  `_hours_per_day_scoped(session, project_id?)` collapsed into one
  `_hours_per_day(session)` instance resolve (worklog create/update, general
  worklogs, estimates, item summary). Cycle stats were already instance-level.
- **`GET /instance` (`InstanceConfigRead`) gains `timelog_hours_per_day` (int,
  resolved through the cascade) + `timelog_days_per_week` (int, env-only)** —
  the SPA duration formatter reads them instead of hardcoding 8. The
  unauthenticated `/instance/login-options` mirror carries them too (same
  schema; harmless non-secrets, work_week_days precedent).
- Migration `c4f8a25d91e7` (chained on `a7c2e19b4f30`, hand-written —
  autogenerate proposes the `ix_doc_pages_fts` false-positive drop): defensive
  `DELETE FROM scoped_settings WHERE key='timelog_hours_per_day' AND
  scope='project'` (live DB had no such rows).

### 2. Scope vocabulary: "workspace" → "global"

Where "workspace" named a permission SCOPE it now reads **global**; the
workspace ENTITY keeps its name everywhere (tables, `workspace_id` params,
memberships, `WorkspaceRole`).

- `PermissionScope.WORKSPACE = "workspace"` → `PermissionScope.GLOBAL =
  "global"` — a WIRE change: `GET /permissions` rows now carry
  `scope: "global"` (the web mirror updates in the follow-up pass).
- **Permission atom KEYS are untouched** — `workspace.manage`, `sla.manage`, …
  are stored strings in role rows and are NOT migrated; `workspace.manage`'s
  resource is the workspace entity, so its key is entity-correct as-is.
- authz internals: `workspace_scope_permissions` → `global_scope_permissions`,
  `WORKSPACE_MEMBER_SCOPE` → `MEMBER_GLOBAL_SCOPE` (`WORKSPACE_MEMBER_FLOOR`
  keeps its name — it is about workspace-entity membership); call sites in
  `auth/router.py` (`/auth/me`) and tests updated.
- Catalog DESCRIPTIONS (the roles-matrix tooltips) swept: "manage the
  workspace's automation rules" → "Create and manage automation rules
  (global)", etc. (cycle/timesheet/role/import/automation/sla/label/webhook/
  canned/doc.read + project.create); entity-meaning usages
  (workspace settings/memberships) stay. The cycle description also dropped
  the "(sprints)" gloss per the language rule. Scope-word code comments in
  automations/slas/timelogging routers updated alongside.

### 3. Shared head-seeded consumer scaffold

`events/runner.py` `run_head_seeded(consumer_name, *, batch_size, plan,
deliver) -> int` extracts the near-verbatim shape of the three
delivery-flavored consumers (csat sender, googlechat notifier, mailintake
outbound): seed-at-head on first start, per-event `plan` with log-don't-crash
(planning may WRITE through the runner's session — csat creates survey rows +
emits `csat.requested`), cursor + planning writes COMMIT before `deliver`
runs post-commit (at-most-once). All three `run_once`s are now thin wrappers.
Behavior deltas, all deliberate: googlechat delivery moved AFTER the cursor
commit (was before — the crash-window duplicate became a dropped ping;
fire-and-forget either way) and its formatting gained the per-event
try/except; mailintake's batch-level SMTP gate became a per-event plan guard
(same observable behavior). The partial siblings were left hand-rolled — real
semantic differences, a second helper would contort: search indexer (backlog
replay IS the index build, savepoint per event, no head-seed), notify
(watch-only bootstrap OVER the backlog), automations (one transaction per
event, mid-batch commits), webhooks (fan-out rows are the delivery).

### 4. googlechat dispatcher honors `run_workers`

The loop gate was URL-only, so a web-only process (spec 48 split) would
double-consume the cursor alongside the worker; now `settings.run_workers and
bool(settings.googlechat_webhook_url)` like every other worker loop.

Suite: 716 green (unchanged count); migration applied, single head
`c4f8a25d91e7`.

### 5. Web pass (follow-up to §1–§2)

The SPA mirror of the wire changes above, plus the deferred web cleanups:

- **Wire mirrors:** `PermissionScope` in `web/src/lib/types.ts` is now
  `project | global | instance` (roles-matrix group label reads "Global
  permissions" in `PermissionMatrix`); `InstanceConfig` gained
  `timelog_hours_per_day` / `timelog_days_per_week`. Verified nothing web-side
  hardcodes `timelog_hours_per_day` at project scope — `ScopedSettingsEditor`
  is registry-driven, so the key simply stops appearing there.
- **Duration config threaded (kills the hardcoded 8):** `lib/duration.ts`
  `formatDuration(seconds, config?)` takes a `DurationConfig`
  `{hoursPerDay, daysPerWeek}` (default 8/5 = the server-mirroring fallback
  while `GET /instance` is in flight); new `useDurationConfig()` in
  `lib/hooks.ts` reads the pair off `instanceConfigQuery`. Consumers updated:
  the timesheet page/grid (`routes/timesheet.tsx`, all totals/cells) and the
  item history feed's "logged 1d 2h" verb (`components/items/HistoryTab.tsx`)
  — the only two importers; every other duration string is server-formatted.
  `formatHours` stays config-free (pure hours).
- **Scope vocabulary in the UI:** `usePermissions().workspace(p)` →
  **`.global(p)`** (~29 call sites); user-visible scope-words swept to
  "global"/"Global" (view sharing "Everyone (global)"/"Global access",
  fields scope column + New-field modal, labels/canned/automations/cycles
  settings descriptions, sidebar "New global view", builtin-field rules
  "Global (all projects)"). The workspace ENTITY keeps its name (types,
  `workspace_id`, members page, "No workspace exists yet", login's "Sign in
  to your workspace"); files/routes not renamed (`workspace-reports.tsx`,
  `workspace_access` wire field).
- **Deferred `useBucketDrop()`:** `web/src/lib/bucket-drop.ts` extracts the
  copy-pasted per-bucket drop-target wiring (dragging payload + hovered-bucket
  state, dragover preventDefault/dropEffect, the dragleave relatedTarget
  contains-guard, drop) from `ViewBoard` columns, `ViewSwimlanes` cells, and
  `ViewList` sections. ViewList's within-section row REORDER wiring stays
  local (different gesture; its extra state resets via the hook's `onClear`).
- **Deferred `<QueryError>`:** `web/src/components/QueryError.tsx`
  (`{label, error}` → the standard `text-sm text-red-400` "Failed to load …"
  line) replaces ~28 drifting inline boxes across view/cycle/roadmap/
  timesheet/projects-index/docs-index/doc-space and routes/settings/* (+
  `ScopedSettingsEditor`); pages with padded wrappers keep the wrapper.
  Compact panel/modal error lines (profile prefs, time panel, tabs) keep
  their bespoke presentation deliberately.
