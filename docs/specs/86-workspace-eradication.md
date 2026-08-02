# Spec 86 — Workspace eradication

User direction: "I want the concept of workspace completely gone
from all modules and all plugins — we have server deployment settings, global
settings, and project settings/overrides. That's it." Spec 67 collapsed the
workspace SETTINGS scope; this spec removes the ENTITY. Pre-OSS is the last
cheap moment.

## Target architecture

- **Server** (env/deploy) → **Global** (instance-wide product config +
  entities) → **Project** (scoped entities + overrides). No middle layer.
- Users are users OF THE SERVER: `users.instance_role` (admin|member) is THE
  role ladder. Any ACTIVE user holds the builtin member floor at global
  scope; `instance_role=admin` is the global admin. No membership rows.
- Teams, labels, cycles (+series), views, dashboards, automation rules,
  canned responses, roles, field definitions, SLA policy denorms: GLOBAL
  (workspace_id dropped). Projects: global containers (workspace_id dropped;
  keys were already globally unique).
- Events lose `workspace_id`; the realtime predicate becomes "authenticated"
  (frames are payload-free entity pings; misdelivery = a refetch of RBAC'd
  endpoints — already the design). Notification events keep their
  per-recipient rule.
- API: every `workspace_id` query/body param is DELETED (breaking; all
  consumers are in-repo). MCP tool schemas, SDK examples, AI prompts, seed,
  importer, demo scripts swept.
- Permission atom `workspace.manage` → `global.manage` (stored role JSONB
  rewritten by migration); `WorkspaceRole`/memberships endpoints deleted —
  role management = `users.instance_role` (the Users page's dropdown).
- The `workspace` module becomes `projects` (containers + key counters).
  `workspace.created` events retire; `project.created` hooks unchanged.

## Execution stages (each ends green: pytest + tsc + vite)

1. **Server singleton + API purge** — a `default_workspace(session)`
   get-or-create accessor; every router resolves it internally and the
   `workspace_id` params are DELETED from the HTTP surface; authz
   short-circuits: active user ⇒ member floor of the singleton,
   workspace-admin ⇔ (instance_role admin ∨ existing admin membership row).
   Service signatures/tables unchanged (stage-3 fodder). Members/workspaces
   HTTP endpoints deleted (Users page already manages roles).
2. **Web purge** — useCurrentWorkspace + every workspace param/type/copy
   removed from the SPA; auth/me consumed without memberships.
3. **Hard drop** — migration: merge-to-global (labels dedupe by name w/
   item_labels repoint; teams/roles/cycles/views name collisions suffixed;
   workspace-admin memberships promote to instance_role=admin; then DROP
   workspace_memberships, workspaces, and every workspace_id column incl.
   events), module rename workspace→projects, atom rename in code +
   stored-role JSONB, service-signature + test-fixture sweep, seed/importer/
   MCP/SDK/demo/docs sweep.

## Risks / decisions

- BREAKING API by design (pre-OSS, in-repo consumers only).
- Multi-tenancy, if ever wanted, returns as a HOSTING-layer concern (one
  deployment per tenant), not an in-app entity.
- The live DB may hold junk workspaces from old demo runs — the stage-3
  migration merges them (dedupe rules above) rather than deleting data.

## As-built notes — stage 1

Server-only; tables/models/service signatures untouched (stage-3 fodder); no
migration. `uv run pytest` green at 812.

- **Singleton resolver**: `workspace.service.default_workspace(session)` —
  first existing workspace by `created_at` (live data wins), get-or-create
  with slug/name from `workspace/types.py` (`DEFAULT_WORKSPACE_SLUG="main"`);
  the create path still dispatches the in-txn `workspace.created` hook, so
  builtin roles seed. No caching (one cheap query per resolve).
- **HTTP surface**: every `workspace_id` query param DELETED (projects,
  teams, labels, cycles + cycle-series, views, dashboards, automations
  [list + runnable], canned, fields + field-rules, webhooks, roles, docs
  spaces + docs search, work-categories, timesheet, reports velocity + sla,
  search, items `/slq/suggest`, states [now `project_id?` — omitted = every
  readable project], audit [instance-wide only]); routers resolve the
  singleton internally. Body `workspace_id` fields removed from OpenAPI via
  `SkipJsonSchema[uuid.UUID | None] = None` (still SETTABLE, so service-level
  callers/tests keep passing explicit ids; the router always overwrites with
  the singleton): ProjectCreate, TeamCreate, LabelCreate, CycleCreate,
  RuleCreate, CannedResponseCreate, RoleCreate, FieldDefinitionCreate,
  FieldRulesReplace, DocSpaceCreate, WorkCategoryCreate, EndpointCreate,
  ViewCreate, DashboardCreate, GeneralWorklogCreate (anchor validator
  dropped — router anchors project-less entries to the singleton),
  NlQueryRequest, GroupImportRequest, and the widget configs
  (ReportVelocity/ReportSla/SlqCount/SlqList — `widgets.py` backfills omitted
  ids from the dashboard so STORED configs stay complete; explicit mismatch
  still 409s). Read schemas keep `workspace_id` (stage 3). Stray
  `workspace_id` params/fields from the interim SPA are silently ignored
  (verified: no strict rejection).
- **Deleted endpoints**: POST /workspaces and all four
  /workspaces/{id}/members routes. Interim survivor: deprecated read-only
  `GET /workspaces` → `[the singleton]` (useCurrentWorkspace reads data[0];
  stage 2 removes the caller, stage 3 the endpoint).
- **Authz** (`auth/authz.py`): `_global_role` synthesizes membership —
  inactive → nothing; instance_role=admin OR (compat) an ADMIN
  workspace_memberships row anywhere → ALL; any other ACTIVE user → member
  (floor + global member set; project scope adds role grants). New public
  `is_admin(session, user)`. The `workspace_id` kwarg on
  `effective_permissions`/`require` is retained but its value ignored.
  `permissions_for_projects` collapsed to the one-global-role pass;
  `subjects_for` unchanged. `_workspace_role`/`_best_workspace_role` removed
  (tests now stub `_has_admin_membership` + `_project_permission_sets`).
  Audit service gate = global `WORKSPACE_MANAGE` (was per-workspace/instance
  two-branch).
- **Role ladder**: `PATCH /users/{id}` accepts `instance_role`
  (admin|member; instance-admin only; self-demotion 409) — replaces the
  members role dropdown. `/auth/me` emits ONE synthetic singleton
  `workspaces` entry (role = synthesized admin/member + global permission
  set) so the interim SPA parses unchanged.
- **Realtime**: `should_deliver` = authenticated sees every entity frame;
  notification frames stay per-recipient. `ClientInfo` = `user_id` only; the
  router no longer snapshots memberships. Frame payloads still carry
  `workspace_id` (stage 3).
- **MCP**: `workspace` slug inputs dropped from search_items / list_projects
  / search_docs; `list_workspaces` tool deleted (enum + handler + catalog).
  list_projects output no longer echoes workspace_id. AI NL→SLQ prompt
  reworded ("tracker", not "workspace").
- **Events/emission**: untouched — `workspace_id` still stamped on events,
  frames, and read schemas (stage 3 drops the column).
- **Tests**: 812 green. Semantics-driven updates: authz stub rewrite;
  realtime predicate; "outsider denied" tests became "active user sees /
  INACTIVE user denied" (rollup, timelog batch, sla batch, slq suggest);
  view/dashboard transfer-to-non-member 409s became transfer-to-INACTIVE
  409s; dashboards count-parity test pinned on a project filter (open floor
  makes unfiltered totals DB-dependent); widget PATCH shape test now expects
  SlqError (workspace_id no longer required in config shape); new
  `test_instance_role_patch_and_self_demotion_guard`.
- **Deferred**: web/ purge (stage 2); tables/columns/module rename, service
  signatures + fixtures, seed/importer/demo sweeps, `workspace.manage` →
  `global.manage` atom rename, events column drop, membership service
  functions + `sync_workspace_membership` (SSO/LDAP still write rows —
  harmless: admin rows map onto the compat admin tier), suggest_values'
  member-based assignee suggestions (stage 3 switches to active users).
  Known stage-1 edges: projects living in junk non-singleton workspaces are
  invisible to the singleton-scoped list endpoints (same as the SPA's
  data[0] behavior today); concurrent first-boot `default_workspace` creates
  could race on the unique slug (seed creates it first in practice).

## As-built notes — stage 2

Web-only; nothing under `server/` touched (`uv run pytest` re-run green).
`tsc -b && vite build` clean; smoke-verified against the live stage-1 server
(`GET /teams|/states|/views|/cycles` param-less, `/auth/me` synthetic entry).

- **Vocabulary deleted** (`web/src/lib/types.ts`): `Workspace`,
  `WorkspaceRole`/`WorkspaceRoleValue`, `WorkspaceMember`/`-Add`/`-Update`,
  `MeWorkspaceMembership`. Every remaining read/create type lost its
  `workspace_id` field (Role, Project, Team, Cycle, CycleSeries, FieldDef,
  Label, View, Dashboard, Rule, WorkCategory, AuditEntry, CannedResponse,
  SlaPolicy, SearchResult, DocSpace + all the *Create shapes,
  `WidgetConfig.workspace_id`, `GroupImportRequest`, `NlQueryRequest`,
  `User.workspaces` summary). `Permission.workspaceManage` renamed to
  `Permission.globalManage` — the VALUE stays the LEGACY wire atom
  `"workspace.manage"` until stage 3 renames the stored key.
- **lib/queries.ts**: `workspacesQuery` + `queryKeys.workspaces` +
  `workspaceMembersQuery` deleted; `ApiPath.workspaces` +
  `apiWorkspaceMembers/MemberPath` gone from constants. Query factories lost
  their `workspaceId` parameter — `projectsQuery()`, `teamsQuery()`
  (absorbed `allTeamsQuery`), `labelsQuery()`, `fieldsQuery()`,
  `fieldRulesQuery(projectId|null)`, `viewsQuery()`, `dashboardsQuery()`,
  `rolesQuery()`, `cyclesQuery(status?)`, `cycleSeriesQuery()`,
  `automationsQuery()`, `runnableAutomationsQuery()`,
  `workCategoriesQuery(includeArchived?)`, `cannedResponsesQuery()`,
  `docSpacesQuery()`, `velocityQuery(last, measure)`,
  `slaReportQuery(projectId|null, weeks)`, `searchQuery(q, limit)`,
  `docsSearchQuery(q, limit)`, `timesheetQuery`/`auditQuery` params,
  and `workspaceStatesQuery` → `allStatesQuery()` (`GET /states`, no param).
  Query KEYS dropped the `{workspaceId}` component (plain string keys); NO
  query sends `workspace_id` anymore (grep-verified zero hits in web/src).
- **usePermissions** (`lib/hooks.ts`): parses `/auth/me`'s synthetic
  `workspaces[0]` entry as THE global permission set (typed by a narrow
  `MeGlobalGrant { permissions }` marked LEGACY); `perms.global(p)` semantics
  unchanged for consumers. `useCurrentWorkspace` deleted;
  `useProjectByKey`/`useItemByKey` resolve against the flat `projectsQuery()`
  list (the multi-workspace fan-out in `useItemByKey` is gone) and no longer
  return a `workspace` member.
- **Component sweep**: every `workspace`/`workspaceId` prop removed —
  view.tsx, Sidebar, ViewModal/ViewSharingEditor, BulkActionBar, NewItemModal,
  NewProjectModal, DashboardModal/DashboardSharingModal, WidgetModal/
  WidgetCard, CommandPalette, RichEditor, RuleEditor/ActionsBuilder/
  RuleTestPanel, FormEditor/FormSharing/FormDefaultsEditor, TeamPanel/
  TeamDirectoryGroup, TransitionsSection (approver options = all ACTIVE users;
  `workspaceMembersQuery` gone), BuiltinFieldsSection, NewFieldModal,
  RoleModal, IssueProperties/ItemDetailBody/IssuePanel/TimeTrackingPanel/
  PlanningFields/quick-actions, ItemDocsSection, CommentsThread, the report
  cards (Velocity/Burnup/Sla), SlqFilterBar/SlqEditor/AskAiBar suggest wiring
  (scope = optional `project_id` only), plus every settings/project route.
- **Users page** (`routes/settings/users.tsx`): the Workspace-role column +
  add-to/remove-from-workspace actions are GONE; the Role column (Admin |
  Member) drives `users.instance_role` via `PATCH /users/{id}` (instance
  admins only; self-row guarded client-side, 409 server-side). The
  "Workspaces" summary column dropped. `WORKSPACE_ROLE_*` display maps in
  meta.ts replaced by `INSTANCE_ROLE_LABELS/ORDER`.
- **Copy**: no user-visible "workspace" wording remains — sharing reads
  "Everyone on this server", the login card says "Sign in to your tracker",
  users/audit/settings descriptions use server/global vocabulary, and the
  "workspace-spanning view" concept is "all-projects" everywhere
  (`RoutePath.workspaceView` → `RoutePath.allProjectsView`;
  `routes/workspace-reports.tsx` → `routes/global-reports.tsx` /
  `GlobalReportsPage`; the `/reports` URL is unchanged).
- **Realtime** (`lib/realtime.ts`): client already reads only
  `entity`/ignores everything else — verified; frame `workspace_id` is inert.
  `Entity.workspace` cache tag deleted; the `workspace_membership` server
  entity (rows survive until stage 3) maps to `Entity.member` only, and the
  `workspace` entity string is now unknown → ignored by design.
- **LEGACY wire aliases kept for stage 3** (each commented at the type):
  1. `/auth/me` still emits the synthetic `workspaces` array — the SPA reads
     entry 0's `permissions` as the global set (`MeGlobalGrant`).
  2. `workspace_access` on View/Dashboard read + create/sharing shapes — the
     wire name for "everyone on this server"; UI label reworded.
  3. Realtime frames still carry `workspace_id` (client never reads it), and
     the `workspace.manage` permission atom string rides under
     `Permission.globalManage`.
- **Deferred to stage 3**: everything server-side (columns/tables/module
  rename, atom rename, `/auth/me` reshape, deprecated `GET /workspaces`
  removal — the SPA no longer calls it).

## As-built notes — stage 3 (final)

The hard drop landed. Migration `f4a9c31e77d2` **applied** (live DB now at that
head; `alembic check` reports no workspace diffs — the ORM matches the migrated
schema exactly). Post-migration sanity: `workspaces` + `workspace_memberships`
tables GONE, `workspace_id` dropped from all 21 tables, `views.global_access` /
`dashboards.global_access` present, labels merged/deduped to 2114, roles=3,
work_categories=7, admins=3, all eight global uniques + `ck_worklogs_ck_worklogs_scope`
present. Backup preserved at `var/backups/pre-spec86-stage3.dump` (untouched).

- **Module rename**: `modules/workspace` → `modules/projects` (git mv, done by
  the prior stage-3 pass). `projects/types.py` = `ProjectEvent.PROJECT_CREATED`
  + `ProjectEntity.PROJECT`; `WorkspaceEvent`/`WorkspaceEntity`/`WORKSPACE_CREATED`
  gone. Subscribers (workflow/views/itemtypes) + automations catalog now bind
  `ProjectEvent.PROJECT_CREATED`.
- **Seeding relocation** (the retired `workspace.created` hook): builtin roles
  ensure on startup via `auth.subscribers.ensure_seeded` (already in place) +
  `roles.ensure_builtin_roles(session)`; **default work categories** now ensure
  on startup via a new `timelogging` `on_startup=(categories.ensure_seeded,)`
  hook calling `ensure_default_categories(session)` in a short-lived committed
  session. `WorkCategory` is GLOBAL (uq_work_categories_name). `radd/seed.py`
  creates NO workspace — it seeds the admin user then calls both ensure paths.
- **Models**: every remaining `workspace_id` column/FK/index dropped; scoped
  uniques recreated as the migration's exact GLOBAL names (uq_labels_name,
  uq_teams_name, uq_roles_key, uq_cycle_series_label, uq_doc_spaces_slug,
  uq_field_definitions_key, uq_work_categories_name, uq_builtin_field_rules_scope);
  `views`/`dashboards` `workspace_access` → `global_access` (nullable string);
  worklogs CHECK rewritten to `item_id IS NOT NULL OR category_id IS NOT NULL`
  (name `ck_worklogs_ck_worklogs_scope` via the naming convention).
- **Services/routers**: `workspace_id` params/filters/attrs deleted across
  canned, automations (+engine/scheduler), timelogging (worklog scope is now
  project|None + a required category), search (indexer/service/deflect — index
  rows + `SearchHit`/`SearchResult` lose `workspace_id`; suggestions enumerate
  globally), slas (report/evaluation/engine — `state_rows(project_id, since)`,
  `sync_states` drops ws), notify (create_notification/watch/unwatch), webhooks
  (fan-out delivers to all active endpoints), docs (spaces/search/links/service
  now global), dashboards + views (sharing = `global_access`; widget configs
  lose `workspace_id`), reporting (velocity/sla_report drop ws), ai, forms
  (share-subject validation = any active user; global teams), participants,
  comments, approvals, audit (gate = `GLOBAL_MANAGE`), attachments, csat, mcp.
  Every `default_workspace`/`get_workspace`/`create_workspace`/`list_workspaces`
  call deleted (those functions no longer exist).
- **Atom rename**: `Permission.WORKSPACE_MANAGE` → `GLOBAL_MANAGE` (value
  `global.manage`); stored role JSONB migrated (`workspace.manage` →
  `global.manage`). audit/service.py updated.
- **SSO/LDAP**: `sync_workspace_membership` gone. Provisioning creates active
  users (member floor automatic); admin-group mapping sets
  `users.instance_role='admin'`, re-synced per login (demotes to member when
  out of the admin group). `GroupImportRequest` dropped its workspace field;
  `import_groups(session, group_dns, provision_members, actor_id)` — group
  import provisions + adds team rows, no "workspace seat". Config
  `oidc/ldap_default_workspace_slug` removed.
- **Events/realtime**: `Event` carries no `workspace_id` (emit + all consumers
  updated); realtime frames are workspace-free; the dead `workspace_membership`
  cache-tag mapping removed from `web/src/lib/realtime.ts`.
- **Web tail**: `/auth/me` flat shape (`global_role` + top-level `permissions`)
  consumed by `hooks.ts`; `workspace_access` → `global_access` across ViewModal
  / ViewSharingEditor / DashboardSharingModal + types (label stays "Everyone on
  this server"). `tsc -b && vite build` clean.
- **Tests**: fixtures no longer create workspaces or membership rows — an active
  `User` holds the global member floor, `instance_role=admin` is the global
  admin; builtin roles + work categories come from the migrated DB. Cross-scope
  ISOLATION tests reframed to the global reality (cross-workspace rejection →
  unknown-team/unknown-project rejection; workspace-scoped exact-set assertions →
  project- or entity-scoped/subset checks, since the shared DB's committed rows
  are now globally visible — e.g. suggest tests narrow by run-unique prefixes,
  screens tests key custom fields with a run suffix now that field keys are
  GLOBALLY unique, the SLA-report smoke pins to its own project). A few
  now-vacuous cross-workspace tests were dropped and a couple of member-floor
  tests added (authz). **Final: `uv run pytest -q` = 810 passed** (was 812;
  net −2 from the deleted isolation tests). `create_app()` imports clean;
  `alembic current` = `f4a9c31e77d2`.
- **Seed/importer/demo**: `radd/seed.py` de-workspaced (above). `scripts/import_jira.py`
  dropped `--workspace`/`resolve_workspace`/the `/workspaces` + membership calls
  and every `workspace_id` body/param (projects/fields/cycles are global). The
  bash `demo_*.sh` walkthroughs still POST `/workspaces` (pre-spec-86) — they
  already assumed a FRESH DB and are marked with a spec-86 header note rather
  than rewritten (they are manual walkthroughs, not part of the suite).
- **Not committed** (per instructions). The pre-drop `:8000` bg server predates
  the migration and will error against the migrated DB until restarted — expected.
