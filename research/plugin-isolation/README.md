# Plugin isolation audit — RADD-1343

The objective is the complete audit and refactor requested on 2026-09-25. This is a work ledger, not a completion report. Discovery does not establish ownership or correct runtime behavior.

## Evidence and coverage

`inventory.json` records discovered backend, frontend, SDK and example source files, imports, module declarations and remote sources. Refresh with `python scripts/plugin_inventory.py`. `review.json` records ownership decisions and evidence per file; edits invalidate earlier file reviews. All entries begin unreviewed. The inventory is intentionally broader than optional plugins.

## Work groups

| Issue | Scope | Status |
|---|---|---|
| RADD-1344 | Complete inventory, ownership and boundary safeguards | In progress |
| RADD-1345 | Person status and timesheet data contributions | Verified; Waiting for release |
| RADD-1346 | Settings, imports and VCS provider UI | In progress |
| RADD-1351 | Shared settings contracts and truthful page lifecycle | Verified; Waiting for release |
| RADD-1352 | Scripts/Monitoring settings and AI/mail health contributions | Verified; Waiting for release |
| RADD-1353 | Owner-contributed directory controls | Verified; Waiting for release |
| RADD-1354 | Automations-owned canvas, graph model and scoped shape queries | Verified; Waiting for release |
| RADD-1347 | Issue, automation and editor integrations | In progress |
| RADD-1348 | Pages, dashboards, widgets and navigation | Pending |
| RADD-1349 | Backend public seams, dependencies and background lifecycle | Pending |
| RADD-1350 | Full requirement-by-requirement verification and documentation | Pending |

## Module review ledger

Declared core status is recorded, not accepted as an exemption. Every module must be reviewed.

| Module | Core declaration | Remote sources | Dependencies | Review |
|---|---|---|---|---|
| access | default | 0 | projects, events, auth, teams, groups | Pending |
| ai | False | 3 | auth, projects, items, fields, workflow, comments, search, settings, events, pages, timelogging, attachments | Pending |
| alertmanager | False | 0 | projects, auth, items, events, automations | Pending |
| approvals | False | 2 | events, projects, auth, teams, workflow, items | Pending |
| attachments | default | 0 | events, projects, auth, items, access, groups, teams | Pending |
| audit | default | 0 | events, auth, projects, items | Pending |
| auth | default | 1 | events, projects | Pending |
| automations | default | 11 | projects, auth, workflow, labels, cycles, releases, items, comments, teams, events, fields, itemtypes | Pending |
| avatars | default | 0 | auth, attachments | Pending |
| backup | default | 0 | auth, events | Pending |
| canned | default | 0 | events, projects, auth, items | Pending |
| capabilities | default | 0 | auth | Pending |
| collab | False | 0 | auth, pages | Pending |
| comments | default | 0 | items, auth, projects, events, teams, itemtypes | Pending |
| confluenceimport | False | 0 | auth, events, pages, attachments, comments, labels, access, groups, teams, items, projects | Pending |
| csat | False | 2 | projects, auth, items, settings, events, mailintake, workflow | Pending |
| cycles | default | 0 | projects, auth, events, settings, teams | Pending |
| dashboards | False | 0 | events, projects, auth, teams, items, cycles, views, reporting, access, groups | Pending |
| events | default | 0 |  | Pending |
| fields | default | 0 | projects, events, auth, teams, access | Pending |
| forgejo | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| forms | default | 0 | projects, auth, teams, fields, workflow, labels, cycles, releases, items, events, comments, itemtypes | Pending |
| github | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| gitlab | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| groups | default | 0 | events, auth | Pending |
| items | default | 0 | projects, workflow, labels, fields, cycles, releases, auth, teams, events, access, itemtypes, linktypes, settings | Pending |
| itemtypes | default | 0 | projects, events, auth | Pending |
| jiraimport | False | 0 | auth, projects, fields, items, workflow, comments, cycles, attachments, events, itemtypes, linktypes, notify, releases, timelogging, weblinks, teams | Pending |
| labels | default | 0 | projects, events, auth | Pending |
| ldap | False | 0 | events, projects, auth, settings, groups, teams | Pending |
| leave | False | 3 | auth, teams, events | Pending |
| linktypes | default | 0 | projects, events, auth | Pending |
| mailintake | False | 3 | projects, auth, items, comments, automations, events, attachments, settings, workflow | Pending |
| mcp | False | 0 | auth, projects, fields, linktypes | Pending |
| milestones | False | 2 | projects, auth, events | Pending |
| monitoring | False | 4 | auth, events | Settings UI verified; backend review pending |
| notify | default | 0 | events, projects, auth, items, comments, teams | Pending |
| pages | False | 0 | events, projects, auth, workflow, items, attachments, labels, comments, notify, access, groups, search, teams, settings | Pending |
| participants | False | 3 | events, projects, auth, teams, items, notify | Pending |
| pluginmgr | default | 0 | auth, events | Pending |
| projects | default | 0 | events | Pending |
| realtime | default | 0 | events, auth | Pending |
| releases | default | 0 | projects, auth, events, workflow | Pending |
| reporting | default | 0 | events, projects, auth, workflow, cycles, items | Pending |
| screens | default | 0 | projects, events, auth, fields, itemtypes | Pending |
| scripts | False | 6 | auth, events, projects, items | Settings UI verified; backend review pending |
| search | default | 0 | events, projects, auth, workflow, items, comments, access, fields, teams | Pending |
| settings | default | 0 | events, projects, auth | Pending |
| slas | False | 0 | events, projects, auth, settings, workflow, items, comments, automations, reporting, teams | Pending |
| sso | False | 0 | events, projects, auth, teams | Pending |
| teams | default | 1 | events, projects, auth, groups | Pending |
| timelogging | default | 0 | events, projects, auth, teams, items, settings | Pending |
| vcs | default | 0 | projects, auth, events, items, timelogging | Pending |
| views | default | 0 | projects, workflow, items, fields, auth, events, access, groups, teams | Pending |
| webhooks | default | 0 | projects, events, auth, fields, items | Pending |
| weblinks | default | 0 | projects, auth, events, items | Pending |
| workflow | default | 0 | projects, events, auth, settings, teams | Pending |

## Confirmed findings still requiring remediation

- The inventory currently scans application source roots and `.py/.ts/.tsx/.css`. RADD-1354 exposed omitted build helpers (`web/packages/plugin-sdk/vite.mjs`, `web/scripts/build-all.mjs`) and plugin package/config files. Their verification is recorded below, but RADD-1344 must expand discovery before the inventory can establish complete codebase coverage.
- Host router directly imports optional settings pages and optional Pages/Dashboards/CSAT routes (`web/src/router.tsx`). Generic slot routes coexist with plugin-specific route components.
- RADD-1351 unifies the SDK capability cache and makes discovery conservative. Other identity/query cache ownership remains under review.
- RADD-1351 fixes generic plugin-page loading/failure/withdrawal and render boundaries. Other direct contribution render sites still need review.
- Leave's residual status/timesheet coupling has been removed in RADD-1345. Source review is recorded only for the portions actually examined; this does not mark the entire backend Leave module reviewed.

## RADD-1345 verification

The Leave remote supplies typed `personIndicators` and `timesheetAnnotations` data. Avatar/name, pickers and timesheet consume generic facts; plugin data queries use activation generation and actor-specific cache identity. The loader withdraws sources on disable and failed activation. Unused queries receive cancellation through their AbortSignal. Settings mutations invalidate the plugin's data consumers.

The built-browser regression covers initial disabled state, live enable, withdrawal of cached status, failed remote loading, personal leave add/delete, holiday submission and slot withdrawal, calendar withdrawal, aborted in-flight status lookup and successful fresh activation. Loader unit tests cover data-only remotes and late registration after disable. AST boundary tests check remote relative imports and prevent Leave vocabulary/endpoints re-entering the host. Other plugins and cross-plugin interaction coverage remain pending.

RADD-1345 result: host and all 9 remote bundles build/type-check; 37 frontend unit/boundary tests and 11 focused backend tests pass; the expanded built-browser regression passes all 12 lifecycle/form checks. Local backend manifest reloaded (PID 1955690), health passes. Local Leave enable/disable probe verifies manifest and served remote in the same process and restores disabled. No external deployment.

## RADD-1351 verification

The SDK exposes generic settings chrome and controls through the host registry, shares timezone formatting and the account-cancelled API transport, and reads the host capabilities cache. Settings navigation accepts owner/group/admin metadata. Page slots render callbacks inside their error boundary, distinguish loading/unavailable/failure, and recover when a registration is replaced. Imports and activation time out; unsupported SDK minimum versions are rejected.

Verified: host + 9 actual remote bundles build/type-check; all 40 frontend tests and 12 capabilities/module-contract backend tests pass. The built-host page fixture passes 8 lifecycle/error/cache checks; the actual Leave remote passes all 12 lifecycle/form/data-cancellation regressions. Recovered-page screenshot inspected. These checks prove the shared contracts, not ownership of every SDK primitive or host settings page. Feature migrations continue in RADD-1352 and the remaining work groups.

## RADD-1352 verification

Scripts and Monitoring settings now live in their owners' remotes, including queries and wire types, and register page/navigation contributions. The host no longer names their routes or API paths. Scripts preserves interpreter rebuild, package install/remove, index/offline settings and audit links; it reports read failures before showing actionable forms. Monitoring accepts independent AI and Mail health cards. Each card owns its endpoint and polling; withdrawal aborts reads and discards unused caches. Consumer descriptions come from each plugin's declaration and are withdrawn independently of durable cursor rows. The new Mail health endpoint preserves the instance-admin data boundary.

Evidence: host + all 10 remotes type-check/build; 42 frontend tests; 17 focused consumer/capability/permission/boundary backend tests plus 31 kernel/runtime/mail-transport regressions. `browser-settings-ownership.mjs` loads the four actual remote bundles and passes 12 form/lifecycle/dependency/failure checks, including initially disabled pages, saved configuration after re-enable, fresh AI coverage, an aborted in-flight query, no polling after withdrawal, permission denial and a utility class exclusive to a remote source. Both page screenshots were inspected. The scan initially omitted classes when using a directory glob; an explicit recursive source-file pattern fixed it, and the browser now asserts the remote-only width.

The local backend serves the new manifests, assets and mail-health endpoint. A local authenticated probe disables/re-enables Scripts and Monitoring in the same PID, checks API withdrawal and restores every initial plugin state. Saved interpreter/index configuration is compared before/after. No package/interpreter mutation was performed on the user's local data; those form writes were exercised against the browser fixture. No external publication.

Remaining for these modules: full backend ownership and dependency review, Monitoring's fixed catalog-count list, and its legacy `overview.mail` compatibility field. AI/mail settings and other host UI remain in later inventory groups; adding health contributions does not imply their entire feature UI is isolated. Scripts' automation integration and saved-node lifecycle require the RADD-1347 audit.

## RADD-1353 verification

The VCS dependency trace found its identity map imports a host-owned PeopleDirectorySelect with both Auth and Teams queries. Those query providers now live in their owning remotes, contributed through the generic SDK DirectorySelect contract. SDK 1.4 adds paged transport and reusable generic search/pagination/modal controls; no directory endpoint or entity kind is encoded in the SDK control. Existing host callers use a thin compatibility adapter. This is a prerequisite for VCS migration, not completion of VCS or all Auth/Teams UI ownership.

Evidence: 44 frontend tests, 19 focused capabilities/kernel/module-contract backend tests, host + all 12 remotes type-check/build. `browser-directory-contributions.mjs` passes 10 checks using the actual Auth/Teams bundles: unavailable controls; paged totals/search/selection; team/member/manager/owner source semantics; withdrawal of each provider while a request is in flight; restored fresh data; failed bundle isolation/recovery; denied data with retry; modal focus/dismissal; and the existing host Audit page adapter updating its selected actor. Screenshot inspected. A local authenticated probe checks the two advertised/served remotes, actual paged directory endpoints, and all three team candidate purposes. No plugin choices were changed; ephemeral token discarded. Auth and Teams remain required core plugins, so browser withdrawal tests establish frontend behavior, not a new backend disable permission.

Next dependency work: VCS's remaining host imports include IntegrationAutomations/RuleEditor, business-time formatting, entity cache metadata and shared form primitives. IntegrationAutomations also hardcodes the Email group and derives event prefixes from display labels; ownership of those selectors must be resolved in the automation migration. VCS's common form uses Forgejo-named wire types for all providers; the common contract belongs to VCS, while provider configuration belongs to each connector. The VCS host/provider page migration remains unfinished.


## RADD-1354 verification

Automations now contributes `automation.graph.canvas` from its own remote, including
its lazy React Flow chunk and styles. Graph wire types, layout/catalog/output helpers,
visuals and shape queries moved to the owner. Existing editor and version-preview
callers use a slot adapter. Shapes are explicit graph inputs; the process-global shape
cache and host shape endpoint helper are gone. Queries are scoped to a mounted
consumer and live catalog, deduplicated for equivalent requests, canceled on withdrawal
or obsolete params, and discarded when unused. Catalog nodes name their actual owner
so retained catalogs cannot continue shape reads from a withdrawn provider.

The renderer compares catalog content, read-only state and resolved shapes, rather
than catalog lengths. Unresolved nodes preserve saved wires with nonconnectable
handles. Read-only Delete no longer removes nodes inside React Flow. A contributed
filter/source does not inherit the built-in SLQ summary merely by sharing its kind.
Controls use SDK theme tokens. The remote build helper converts CommonJS requires of
shared packages to ESM imports and substitutes the production environment; actual
bundle tests exposed both Node-global failures during migration.

Evidence: host and all 13 remotes type-check/build; 47 frontend tests; 24 focused
node-shape/catalog/capability/kernel/module-contract backend tests. The actual bundle
browser proof passes 15 checks, including separate graph consumers, parameter changes
and late replies, three in-flight cancellations, provider withdrawal with a retained
catalog, denied shapes, content-preserving recovery, same-sized catalog replacement,
read-only and editable Delete, missing/failed remote recovery, and the existing host
RuleEditor plus VersionsPanel using independent shapes. It also measures visible
nodes/styles and verifies control contrast in dark/light themes. Screenshots inspected.
Shared build changes additionally pass the 12 settings and 10 directory actual-remote
browser regressions. The local backend advertises/serves the remote and lazy chunk,
returns owner metadata for 50 catalog nodes, and answers actual AI/Scripts shape
requests. Plugin choices are unchanged; the temporary local probe token is removed.

Scope remains incomplete: RuleEditor/GraphEditor/GraphInspector/TokenReference,
settings, integration selectors, form providers, generic schema defaults and remaining
backend ownership still need review/migration under RADD-1347. Source barrels and the
host's call to the owner shape hook are temporary migration dependencies, not a final
host architecture. Automations remains a required core plugin: browser tests exercise
frontend absence/withdrawal, not a new backend permission to disable it. The complete
inventory contains 57 modules and 1497 source files; this stage does not certify the
remaining inventory.
