# Plugin isolation audit — RADD-1343

The objective is the complete audit and refactor requested on 2026-09-25. This is a work ledger, not a completion report. Discovery does not establish ownership or correct runtime behavior.

## Evidence and coverage

`inventory.json` accounts for every existing tracked repository artifact, independent of file extension, plus nonignored new implementation/configuration files in the application, SDK, examples, scripts, deployment and CI roots. It records artifact roles, hashes, import hints, builtin and example manifests, colocated UI files, and package dependencies. Untracked documents/screenshots and gitignored local state are outside discovery; stage a new non-code artifact to include it. The only tracked-file exclusions are the three generated audit ledgers, whose own hashes would be circular.

Refresh with `python scripts/plugin_inventory.py`. `review.json` records ownership decisions and evidence per artifact; changed bytes reset that entry to unreviewed. Removed entries remain in `retired.json` for explicit disposition. Documentation, assets, generated files and tests have distinct roles, but no role automatically grants ownership approval. The module table below remains a manual review ledger.

`python scripts/plugin_inventory.py --check` checks coverage/freshness and review schema without rewriting the ledgers; CI runs it alongside isolated discovery tests. `--require-reviewed` additionally refuses unreviewed/partial current or retired entries and exceptions without a reason. This is a record-completeness gate, not proof that a claimed review or test result is valid. The final audit must inspect the cited evidence and actual runtime behavior. Static imports/declarations are discovery hints and cannot establish dynamic registration or semantic ownership by themselves.

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
| RADD-1355 | Repository-wide discovery and inventory validation | Verified; Waiting for release |
| RADD-1356 | Domain-independent schema and code controls | Verified; Waiting for release |
| RADD-1357 | Owner-contributed option directories | Verified; Waiting for release |
| RADD-1358 | Owner-contributed project/cycle pickers | Verified; Waiting for release |
| RADD-1359 | Owner-contributed team relationships/audiences | Verified; Waiting for release |
| RADD-1360 | Fields-owned controls and generic input primitives | Verified; Waiting for release |
| RADD-1361 | Owner catalog queries and nonvisual contribution lifecycle | Verified; Waiting for release |
| RADD-1362 | Independent scheduling contributions and preview lifecycle | Verified; Waiting for release |
| RADD-1363 | Owner-declared entity destinations for audit navigation | Verified; Waiting for release |
| RADD-1364 | Audit page/history/footer ownership and exact scope access | Verified; Waiting for release |
| RADD-1347 | Issue, automation and editor integrations | In progress |
| RADD-1348 | Pages, dashboards, widgets and navigation | Pending |
| RADD-1349 | Backend public seams, dependencies and background lifecycle | Pending |
| RADD-1350 | Full requirement-by-requirement verification and documentation | Pending |

## Module review ledger

Declared core status is recorded, not accepted as an exemption. Every module must be reviewed. The 57 builtin declarations and the external example are all included.

| Module | Core declaration | Remote sources | Dependencies | Review |
|---|---|---|---|---|
| acme-notes (external example) | False | 11 | projects, auth, events, items | Pending |
| access | default | 0 | projects, events, auth, teams, groups | Pending |
| ai | False | 3 | auth, projects, items, fields, workflow, comments, search, settings, events, pages, timelogging, attachments | Pending |
| alertmanager | False | 0 | projects, auth, items, events, automations | Pending |
| approvals | False | 2 | events, projects, auth, teams, workflow, items | Pending |
| attachments | default | 0 | events, projects, auth, items, access, groups, teams | Pending |
| audit | default | 7 | events, auth, projects, items | UI contributions verified (RADD-1364); backend dependency review remains open |
| auth | default | 3 | events, projects | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| automations | default | 13 | projects, auth, workflow, labels, cycles, releases, items, comments, teams, events, fields, itemtypes | Pending |
| avatars | default | 0 | auth, attachments | Pending |
| backup | default | 3 | auth, events | Schedule contribution verified (RADD-1362); full settings/backend review pending |
| canned | default | 0 | events, projects, auth, items | Pending |
| capabilities | default | 0 | auth | Pending |
| collab | False | 0 | auth, pages | Pending |
| comments | default | 0 | items, auth, projects, events, teams, itemtypes | Pending |
| confluenceimport | False | 0 | auth, events, pages, attachments, comments, labels, access, groups, teams, items, projects | Pending |
| csat | False | 2 | projects, auth, items, settings, events, mailintake, workflow | Pending |
| cycles | default | 7 | projects, auth, events, settings, teams | Picker contributions verified (RADD-1358); remaining review pending |
| dashboards | False | 0 | events, projects, auth, teams, items, cycles, views, reporting, access, groups | Pending |
| events | default | 0 |  | Pending |
| fields | default | 5 | projects, events, auth, teams, access | Catalog contributions verified (RADD-1361); remaining review pending |
| forgejo | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| forms | default | 2 | projects, auth, teams, fields, workflow, labels, cycles, releases, items, events, comments, itemtypes | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| github | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| gitlab | False | 0 | events, projects, auth, items, vcs, automations | Pending |
| groups | default | 2 | events, auth | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| items | default | 2 | projects, workflow, labels, fields, cycles, releases, auth, teams, events, access, itemtypes, linktypes, settings | Change presentation contributed (RADD-1364); remaining UI/backend review pending |
| itemtypes | default | 2 | projects, events, auth | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| jiraimport | False | 0 | auth, projects, fields, items, workflow, comments, cycles, attachments, events, itemtypes, linktypes, notify, releases, timelogging, weblinks, teams | Pending |
| labels | default | 3 | projects, events, auth | Catalog contributions verified (RADD-1361); remaining review pending |
| ldap | False | 0 | events, projects, auth, settings, groups, teams | Pending |
| leave | False | 3 | auth, teams, events | Pending |
| linktypes | default | 0 | projects, events, auth | Pending |
| mailintake | False | 3 | projects, auth, items, comments, automations, events, attachments, settings, workflow | Pending |
| mcp | False | 0 | auth, projects, fields, linktypes | Pending |
| milestones | False | 2 | projects, auth, events | Pending |
| monitoring | False | 4 | auth, events | Settings UI verified; backend review pending |
| notify | default | 0 | events, projects, auth, items, comments, teams | Pending |
| pages | False | 2 | events, projects, auth, workflow, items, attachments, labels, comments, notify, access, groups, search, teams, settings | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| participants | False | 3 | events, projects, auth, teams, items, notify | Pending |
| pluginmgr | default | 0 | auth, events | Pending |
| projects | default | 7 | events | Picker contributions verified (RADD-1358); remaining review pending |
| realtime | default | 0 | events, auth | Pending |
| releases | default | 2 | projects, auth, events, workflow | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| reporting | default | 0 | events, projects, auth, workflow, cycles, items | Pending |
| screens | default | 0 | projects, events, auth, fields, itemtypes | Pending |
| scripts | False | 6 | auth, events, projects, items | Settings UI verified; backend review pending |
| search | default | 0 | events, projects, auth, workflow, items, comments, access, fields, teams | Pending |
| settings | default | 0 | events, projects, auth | Pending |
| slas | False | 0 | events, projects, auth, settings, workflow, items, comments, automations, reporting, teams | Pending |
| sso | False | 0 | events, projects, auth, teams | Pending |
| teams | default | 6 | events, projects, auth, groups | Option and relationship contributions verified (RADD-1357/1359); remaining review pending |
| timelogging | default | 0 | events, projects, auth, teams, items, settings | Pending |
| vcs | default | 0 | projects, auth, events, items, timelogging | Pending |
| views | default | 0 | projects, workflow, items, fields, auth, events, access, groups, teams | Pending |
| webhooks | default | 0 | projects, events, auth, fields, items | Pending |
| weblinks | default | 0 | projects, auth, events, items | Pending |
| workflow | default | 2 | projects, events, auth, settings, teams | Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |

## Confirmed findings still requiring remediation

- RADD-1355 closes the source-root/file-extension discovery gap exposed by RADD-1354. Newly discovered migrations, SDK/package/build files, tools, deployment configuration, tests and reference artifacts are explicitly unreviewed. RADD-1344 remains open for their ownership/evidence audit.
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
frontend absence/withdrawal, not a new backend permission to disable it. The then-current
scan contained 57 builtin manifests and 1497 files; RADD-1355 expands that scope. This
stage does not certify the remaining inventory.


## RADD-1355 verification

Discovery now accounts for 2,581 artifacts across the repository: 58 plugin manifests
(57 builtin and one external example), 18 package manifests, and 214 migration files
are included. These counts describe discovery, not completed review. The old filesystem
scan had included two gitignored virtualenv bootstrap files; their retirement records
explain that exclusion without deleting the environment. Four old `partially-reviewed`
status spellings were normalized to `partially_reviewed` with evidence and issue links
preserved. No ownership decisions were promoted merely by expanding the scan.

Nine isolated-git tests cover unknown tracked file types, source/config roots, new
unstaged sources, ignored/local artifacts, review invalidation and preservation,
non-mutating freshness checks, deletion/staging/restoration, builtin/external manifests,
colocated example UI, package dependencies, parse failures, external symlinks, required
evidence and explicit exceptions, and generated-ledger exclusions. Local freshness and
lint checks pass. The strict review-completeness gate correctly fails on the remaining
unreviewed entries. A CI job now runs the discovery tests and freshness check; no remote
CI run or deployment is claimed. Application behavior and plugin choices are unchanged.

The actual ownership review remains in RADD-1344/1346–1350. Complete discovery does not
justify marking those tasks complete. Newly visible package metadata also makes build
and packaging dependencies available for that review instead of assuming the shared
local toolchain proves isolated plugin packaging.


## RADD-1356 verification

The SDK schema form/default helper no longer depends on Automations. Typed enum
members and cloned defaults retain their types; blank numeric inputs remove the
value; unknown enum members and unsupported/unlisted structured values remain
intact. Boolean groups normalize only on user edit. This is a small generic form,
not a full schema validator; richer data needs an owner-contributed editor.

The host CodeEditor no longer imports Scripts or Markdown UI. Scripts explicitly
chooses Python; other callers can choose a supported language or plain text.
Language lookup and syntax colors are shared generic utilities. The controlled
editor uses the current callback, does not echo external values as edits, ignores
obsolete grammar loads and responds to read-only/label changes. Browser inspection
also exposed default CodeMirror gutter colors overriding theme utilities; editor
theme rules now use the app's semantic colors directly. The former SchemaFields
and PythonEditor files are removed with explicit retirement records. SDK 1.5 gates
Automations' new helper import and Scripts' updated control contract.

Evidence: host + 13 plugin remotes build; all 51 frontend tests pass; 19 backend
capability/kernel/module-contract tests pass. The new actual-bundle browser proof
passes 13 checks covering typed/unknown values, safe clearing, retained data,
JavaScript/Python grammars, current callbacks, controlled updates, live read-only
state, delayed Rust grammar rejection, measured height and dark/light gutter colors,
Scripts/AI absence and withdrawal/re-enable, Scripts failed-bundle recovery, retained
drafts and no unintended script execution. The automation canvas actual-bundle
regression passes all 15 checks after extraction. Screenshots were inspected; the
local backend and built frontend were refreshed. An authenticated local probe
confirms Automations/Scripts advertise SDK 1.5, the shared shim exports the helper,
the remote/lazy canvas assets and actual shape endpoints work, and plugin choices
are unchanged. The temporary token was removed.

Remaining ownership work is unchanged: the automation editor, inspector forms,
integration selectors and VCS pages still need migration; Scripts' test mutation
lifecycle is not certified by a proof that deliberately executes no scripts.
The discovery ledger contains 2,586 artifacts and 4 retirement entries at this
stage. Discovery and these focused checks do not certify the rest of the inventory.


## RADD-1357 verification

Twelve option directories are now contributed by Auth, Teams, Workflow, Itemtypes,
Releases, Forms, Pages and Groups. Their owner bundles define endpoints, nouns,
row presentation and entity cache metadata. SDK 1.6 supplies a generic slot contract
and reference/text/multiple-value/modal controls. The host DirectoryChoices file is
only an SDK re-export; the former query module retains transitional source-name
aliases without transport, noun tables or cache tags. TeamChoices now uses the
contributed ID directory and preserves its caller footer and clear option.

Mounted provider controls own cancellation signals and zero-retention query caches.
Withdrawal removes an internally opened modal and its queries; saved values stay in
the caller. Reactivation resolves fresh data. An externally open modal retains a
close control, unavailable explanation and caller footer. Free text/template tokens
remain editable without a provider. Presets require no directory read. Scoped role
lookup passes scope to both browse and resolve, and query keys distinguish scopes.
The server continues to enforce all directory permissions.

Evidence: host + all 19 remotes build; 53 frontend tests; 25 backend directory-option,
people-option, capability, module-contract and kernel tests; targeted Python lint.
The new actual-bundle browser proof passes 11 grouped checks: all twelve sources
resolve, browse, withdraw and restore; paging/search reach row 125; role scope updates;
presets with browsing forbidden; two observed in-flight cancellations (browse and
saved-value lookup); failed bundle recovery; denied reads and retry; preserved
multiple values with duplicate prevention; dismissible standalone fallback. It
makes 83 mocked option requests using actual owner bundles. Existing Auth/Teams
contribution (10), automation-canvas (15), and shared-control (13) browser checks
also pass. Screenshots were inspected after waiting for modal animations to finish.
The browser command now includes the new proof.

The local backend was reloaded and the current build is served. An authenticated
read-only probe confirms all eight remotes advertise SDK 1.6 and all twelve real
option endpoints return their contracts, including saved-value resolution where
rows exist. All plugin choices remain unchanged; Leave/GitHub/Forgejo stay disabled;
the ephemeral token was removed. Core-plugin withdrawal in browser fixtures verifies
frontend absence handling, not a new permission to disable required backend modules.

The stage inventory contains 2,620 artifacts and 4 retirement entries. Remaining
work includes host automation forms/integration selectors, project/cycle pickers,
TeamSelect's independent saved-reference lookup, and all other unreviewed/partial
inventory entries. The provider migration does not certify those consuming pages.

## RADD-1358 verification

Projects owns both project picker controls, directory transport, saved ID/key
resolution and public contracts. Cycles owns both cycle controls, ID/name modes,
status presentation, project/all scope and date/completion filtering. SDK 1.7 owns
only generic paging/lifetime behavior and the shared Switch. Host adapters have
no feature queries or state; query/type re-exports preserve existing consumers.
An open cycle picker now resets its scope when the caller changes project.

Evidence: host + 21 remotes typecheck/build; 54 frontend tests; 27 focused backend
project/cycle directory, capability, module-contract and kernel tests; targeted
Python lint. The actual-bundle picker proof passes 14 grouped checks (34 requests,
3 observed aborts): initially absent owners, saved IDs/keys/names, full callbacks,
permission filters, 125-row paging/search, custom empty values, scoped cycles,
preloaded labels, accessibility props, withdrawal during browsing or resolution,
fresh reactivation, missing references, denied-read retry, failed bundle recovery,
and standalone dismissal. Existing option-directory (11) and automation-canvas
(15) grouped checks pass. The picker proof is included in `test:browser` and the
rendered cycle picker screenshot was inspected.

The local backend was reloaded and serves the new build. An authenticated,
read-only probe verified both SDK 1.7 manifests/assets, permission-filtered projects,
summary, existing project ID/key resolution, and cycle filtering/project scope.
The local cycle results were empty, so real saved-cycle resolution is covered by
the populated browser fixture, not claimed for the local data. Plugin choices
were unchanged; Leave/GitHub/Forgejo remain disabled. The temporary token was
removed after the probe.

This does not certify the remaining host navigation, project/cycle pages,
`useProjectDirectory`/`useCycleDirectory`, or their query/type compatibility barrels.
Browser fixtures still observe independent host navigation directory requests;
absence assertions target picker-owned queries explicitly. Core-plugin withdrawal
in fixtures proves frontend lifecycle handling, not backend disable permission.
Automation forms, TeamSelect's saved-reference query and all other partial or
unreviewed inventory entries remain work under the full goal.

## RADD-1359 verification

Teams now owns relationship selectors, standalone choices and the audience editor,
including saved-reference requests, optional counts, paging and staged additions.
Host team files contain only slot adapters and unavailable fallbacks. Comment
preview presentation and policy wording moved beside the comment UI; other callers
retain their own explanations. The shared selection summary says “N selected
teams” because a selection does not always restrict visibility (SLA rules use it
too). Unapplied additions are discarded on cancellation or owner withdrawal;
complete applied ID arrays remain in the caller.

Evidence: host + 21 remotes build; final Teams bundle typecheck/build after the
summary wording change; 55 frontend tests; 39 backend team-reference/directory,
comment-reply-audience, capability, module-contract and kernel tests. Existing
cancellation/realtime tests now load the actual owner reference query, retaining
key normalization, count-mode separation and entity-invalidation assertions.
A boundary test prevents state/query logic returning to the team adapters or
comment-specific policy copy entering Teams.

The actual-bundle relationship proof passes 13 grouped checks (31 requests, three
observed aborts): initial absence, direct saved-ID resolution, preloaded labels,
error/disabled props, permission refusal/retry, missing references, withdrawal
mid-reference and mid-browse, fresh re-enable, 125-row search/paging, empty choice,
125-ID audience windows, optional member counts, read-only controls, removal
without losing off-page IDs, staged additions across searches, duplicate prevention,
cancel/withdraw semantics, failed-bundle recovery, and standalone dismissal.
Option-directory (11) and Auth/Teams directory (10) regression groups also pass.
The new proof is in `test:browser`; picker and audience screenshots were inspected.

The running local app serves the new Teams bundle. An authenticated read-only
probe verified all three contributed controls in the served asset, ID-valued
options, a real saved team's name and optional member counts. Plugin enablement
was unchanged (Leave/GitHub/Forgejo disabled), and its temporary token was removed.
No backend restart was needed for this UI-only stage; nothing was published.

Remaining scope: CommentsThread still batches preview labels using the owner query
through a transitional host re-export. Its lifecycle/ownership must be handled in
the full comments migration without replacing batching with one request per row.
The new comment preview file is correctly identified as Comments-owned but still
host-located; it is partial, not approved final architecture. Teams settings,
rosters, automation forms, navigation and all other partial/unreviewed artifacts
remain in the complete goal.

## RADD-1360 verification

Fields now owns CustomFieldsForm/CustomFieldControl and public definitions/value
types. Host controls render owner slots; type files retain compatibility exports.
SDK 1.8 owns generic TokenMultiSelect and ErrorText. No field registry lookup was
added to these supplied-definition controls. Unknown types display a read-only
saved value, and removed select options remain visible until deliberately replaced.
Zero, false and null retain their distinct meanings. Field locks explicitly disable
controls and close open token suggestions. The boolean thumb is positioned within
its track. Token choices now handle focused-button keyboard activation, clamp a
highlight when options change, and use semantic error-hover color.

Evidence: host + 22 remotes typecheck/build; final Fields bundle typecheck/build;
56 frontend tests; 38 focused backend field-default/option/writability, capability,
module-contract and kernel tests; targeted Python lint. Boundary checks enforce
owner form adapters and domain-independent SDK primitives. The actual-bundle
browser proof passes 13 grouped checks: all nine field types, removed/unknown
values, keyed changes, numeric/boolean/null semantics, available select replacement,
125-option search/render cap, orphaned multi-select values, live locks, withdrawal
with an open popup, reactivation/failed bundle recovery, standalone field callbacks,
generic tokens without Fields, keyboard activation/create/remove, changed-option
highlight validity, and nested Escape dismissal. Screenshot inspection found and
confirmed the boolean thumb fix; a bounding-box assertion now covers it.
Existing shared-control (13) and option-directory (11) regression groups pass.
The new proof is included in `test:browser`.

The browser observed zero field-registry reads from the supplied-definition
controls, but two `/fields/settings-summary` reads from the existing host settings
sidebar (`routes/settings/layout.tsx`). This is a confirmed remaining dependency,
not suppressed evidence or an approved exception. Browser core-module withdrawal
exercises frontend absence/recovery and does not permit disabling required backend
modules.

The backend was reloaded to register the new remote. A read-only authenticated
local probe verified its SDK 1.8 manifest and both served contracts, plus the wire
shape of 319 authorized field definitions. Plugin choices were unchanged;
Leave/GitHub/Forgejo stayed disabled; the ephemeral token was discarded. Nothing
was pushed or deployed externally.

Remaining work includes field registry queries, settings/navigation, display-cell
presentation, automation picker data and inspectors, host-located consuming feature
pages, and all other partial/unreviewed artifacts. This stage does not claim those
features have achieved full ownership or lifecycle isolation.

## RADD-1361 verification

SDK 1.9 now has a nonvisual query-source registry, with declarative sources and
loader-scoped imperative registration. Owners define namespaced keys, transport
and cache metadata. Queries carry consumer, activation, arguments and enabled-state
identity, cancellation signals and zero unused retention. Failed/absent sources
expose availability separately from empty success; query errors hide prior data.
The loader withdraws sources on disable/replacement/failure and suppresses late
activation registrations. A browser reload exposed a collision flaw in the first
implementation: a competing plugin could claim a key after its owner disappeared.
Enforcing the plugin namespace prevents that takeover, including while the owner
is absent or loading.

Fields and Labels own their catalog transport/types and register `fields.catalog`
and `labels.catalog`. Automation picker data consumes these sources instead of
host query factories, reports unavailable/loading/error state, and supports retry.
Saved custom-field keys in action/finding selectors remain visible when missing;
existing values are preserved. Query compatibility exports remain for pages not
yet migrated. Full catalog reads are intentionally unchanged in this ownership
stage; no pagination or broad scale improvement is claimed.

Evidence: host + 23 remotes typecheck/build; 59 frontend tests; 28 focused backend
field-listing/scoped-member, capability, module-contract and kernel tests; targeted
Python lint. Loader tests cover query-only modules, withdrawal/reactivation,
activation failure rollback and suppression of late registration. The actual-bundle
query proof passes 12 grouped checks (21 requests, 4 observed cancellations):
initial absence, actual owner rows/metadata, entity invalidation, independent owner
withdrawal, fresh re-enable, denied-read retry, failed remote recovery, namespace
collision rejection, argument-change cancellation, disabled-consumer/refetch refusal,
independent consumers, and the real automation editor's saved field key/value
through Fields withdrawal. Existing field-control (13) and automation-canvas (15)
regression groups pass. The editor screenshot was inspected. The new proof is in
`test:browser`.

The backend was reloaded for the manifests and serves the new build. A read-only
authenticated probe verified both SDK 1.9 sources and their real catalogs (319 fields,
2,305 labels). Plugin enablement was unchanged, Leave/GitHub/Forgejo remain disabled,
and the temporary token was removed. Nothing was pushed or deployed externally.

Remaining: the query proof observed five independent host settings-summary reads.
Those, compatibility-query consumers, field/label settings, other automation
queries/inspectors, navigation and all remaining partial/unreviewed artifacts still
need migration. The new nonvisual contract enables that work; it does not establish
full platform separation by itself.

## RADD-1362 verification

The former host ScheduleEditor mixed shared scheduling inputs with an Automations
endpoint and automation-specific guidance, including when rendered inside Backups.
Actual backend review established a legitimate shared platform contract:
`radd.schedule` already owns arithmetic for both independent schedulers. SDK 1.10
now owns controlled schedule inputs and types; Automations and Backup each contribute
their editor, transport and contextual help. `radd.schedule_preview` holds the shared
preview schema/arithmetic. `/backups/schedule/preview` requires instance admin access
and works with no Automations route. The existing Automations preview policy remains
authenticated arithmetic. No schedule rows, enablement choices or retention settings
are changed by this migration.

Preview transport aborts on draft changes or contribution withdrawal, including a
pending debounce. Results are scoped to each draft transition, so A → B → A cannot
revive A's previous dates. HTTP failure shows retry; server validation refusal shows
its error. Custom saved intervals remain visible and unchanged. The shared control
names scheduler and reader timezones and follows the current input theme. Visual
review led to stronger helper-text contrast. Feature instruction text belongs to the
owning wrapper. Host backup settings and automation graph inspector now render thin
slot adapters, but their other feature ownership remains unfinished.

The first actual-bundle run caught a missing federation export, which a successful
host/remote build did not catch. The shared shim was corrected, and an AST safeguard
now compares its runtime exports against the SDK entry point, including type-only
and star exports. The automation algorithm test loads the actual shared schedule
contract in its isolated test directory.

Evidence:
- Host plus 24 remotes built; 63 frontend tests passed.
- 65 focused backend tests passed: preview ownership, schedule kinds, scheduled
  automations, module contracts, kernel contracts and route shadowing. Ruff passed
  for the changed backend logic and new tests.
- `browser-schedule-contributions.mjs`: 13 groups against actual Automations and
  Backup bundles. Covers absent owners, independent backup operation, saved custom
  intervals, kind/weekday/time edits, cron examples/refusals, in-flight cancellation,
  A → B → A, withdrawal/re-enable, failed previews/retry, failed remote recovery,
  debounce withdrawal, theme/contrast, and the actual host Backup settings modal.
  The proof performs no persistent writes.
- `browser-automation-canvas.mjs`: all 15 existing graph/lifecycle groups passed,
  including the actual host editor and version preview.
- Local server was reloaded and both owner manifests/bundles and preview endpoints
  were probed with an ephemeral admin token, then the token was discarded. Valid
  seven-minute schedules return five UTC runs; one-minute schedules return a
  refusal. Leave/GitHub/Forgejo remain disabled and the loaded plugin set is unchanged.
- Screenshots inspected: `/tmp/radd-schedule-contributions-light.png`,
  `/tmp/radd-schedule-contributions-dark.png`, `/tmp/radd-backup-schedule.png`.
  Logs are `/tmp/radd-1362-{build,unit,backend,browser,canvas,reload}.log`.

Remaining work includes the full automation editor, audit history contribution,
public cross-plugin contracts, Backup settings ownership, and every other partial
or unreviewed inventory artifact. This stage does not establish complete plugin
isolation.

## RADD-1363 verification

Removed the host Audit's cross-feature destination table. All 46 pre-existing
entries were assigned to their 33 owning modules and now use `EntityLinkSpec` in
those manifests. The kernel owns only local-template validation, URI-component
substitution, fallback ordering and lifecycle. The public `radd.sdk` exports the
contract. Existing declarative entity/reference URLs derive contributions, preserving
third-party navigation without adding those plugins to a central table.

Audit resolves `entity_url` and `entity_owner` after its existing scope authorization
and over the same registered subject refs it returns. It does not trust historical
payload URLs or alter stored events. Missing/disabled owners leave labels and changes
readable without a destination. The current host consumer hides cached links when
capabilities withdraw their owner; plugin/build changes replace the audit query
identity and cancel older reads. Query replacement no longer borrows a previous
scope's audit rows. Failed target bundles use the existing generic unavailable page.

Registration requires explicit links to name the plugin’s own entity/ref/event/CRUD
types and rejects duplicate types and collisions with active owners before any mutation, removes old link keys on replacement, and ignores stale-generation cleanup.
The full Audit page, permission affordances, footer and structured-change renderer
still require migration; moving these destinations does not mark them complete.

Evidence:
- `server/tests/fixtures/audit-entity-destinations.json` records every former mapping;
  the owner-declaration test verifies all 46 concrete results. Ordered page-id and
  scoped-setting fallbacks, project key escaping, template rejection, owner collisions,
  replacement/withdrawal/reset and EntitySpec/EntityRefSpec compatibility are covered.
- 66 backend tests passed across entity links, audit ledger, audit credential security,
  audit MCP, module/kernel contracts, frontend federation and plugin workflow. Audit
  scope/redaction tests remain green; a DB-backed test verifies labels/changes survive
  removal and restoration of a destination contribution.
- 67 frontend tests passed, including URL parsing/safety, cached-owner withdrawal and
  an AST guard against restoring feature-specific navigation in the Audit helper.
- Host plus 24 remotes built. `browser-audit-entity-links.mjs` passed 7 groups with
  47 exact destinations, 14 audit reads and one confirmed abort. It uses actual Python
  owner declarations and the actual host Audit page, opens the real Milestones bundle
  with its hash intact, and covers owner withdrawal/restoration, failed bundle recovery
  and denied refreshes. It performs no persistent writes. Its unavailable project/person
  pickers are deliberate fixture omissions, not evidence that those controls were tested.
- Local server reloaded; an ephemeral-token probe inspected 200 real audit rows,
  including 81 current owner links. The filtered local dataset contained no GitHub/
  Forgejo connection/repository audit rows, so that local probe establishes no historical
  VCS withdrawal claim; the browser fixture and registry tests cover it. Plugin choices
  were unchanged and Leave/GitHub/Forgejo remain disabled. Token discarded afterwards.
- Screenshot `/tmp/radd-audit-entity-links.png` inspected. The temporary scope-denied
  toast belongs to the refusal scenario immediately before recovery. Logs:
  `/tmp/radd-1363-{build,unit,backend,browser,reload}.log`.

## RADD-1364 — Audit UI and exact-scope history contributions

Moved the complete Audit frontend into seven owner source files: page, URL/link
helpers, query hooks, wire types, history panel, footer and remote entry. Audit
contributes its navigation and page through the existing catch-all. Removed host
Audit page/helper, transport/keys/constants/types and settings footer implementation;
the editor history adapter emits a generic slot. The SDK avatar now uses the host's shared avatar so status contributions remain
visible in Audit. SDK 1.11 adds generic change
presentation and shared date, table, pagination and collapse controls. Items' two
owner source files contribute issue vocabulary and suggestions; Auth owns role
grant wording emitted by its grants service. Public Projects
picker contracts now use an explicit package export and declared dependency.

Confirmed behavior corrections: exact project access replaces global/any-project
permission guesses; access caches participate in permission invalidation; denied
refreshes hide stale rows/footers/panels; changed filters request page 1 immediately
and do not resurrect a previous page after A→B→A navigation; external URL navigation
cancels pending search edits; To-day filtering includes fractional seconds at the
end of the day. Page-contribution withdrawal also removes links to that page.
Owner-formatting preserves bare/redacted changes and unknown saved values.

Verification is recorded below. This stage does not certify
all Items UI, all Audit backend dependencies, the general navigation system, or
all contents of modified shared barrels. Audit/Items are still declared core;
missing/failed remote fixtures verify contribution lifetimes, not a new ability
to disable these core plugins in Settings. The full per-artifact audit stays open.

Final stage evidence:

- Host and all 26 remotes built against SDK 1.11; 72 frontend tests passed,
  including owner formatting, redaction, host/owner boundaries, public-contract
  exports and federation-shim parity. Ruff checks passed for the changed Python
  declarations, endpoints and tests.
- 68 backend tests passed across Audit ledger/credential security/MCP, entity
  destinations, module/kernel contracts, federation and plugin workflow. The
  added DB-backed access matrix tests instance admin, exact managed project,
  another project, an outsider and a constrained admin credential against the
  same ledger authorization function. The actual capabilities response carries
  both owner remotes and Audit's project-navigation requirement.
- `browser-audit-contributions.mjs`: 17 groups, 77 recorded requests, three
  confirmed aborts. Actual Audit, Items, Projects, Auth and Leave bundles mounted in the
  host. Tests cover absent and open withdrawal, fresh restored values, disposed
  Audit caches, bundle failures/recovery, isolated contribution disabling,
  permission invalidation, URL filter/pagination transitions, actual picker
  interaction and saved IDs while picker owners are unavailable. A fixture page
  supplies generic slot context; it is not a replacement Audit implementation.
- `browser-audit-entity-links.mjs`: seven groups, 47 exact destinations, 11 reads,
  one abort; updated to load Audit's actual remote. Existing Projects/Cycles
  picker proof also passed all 14 groups, 34 requests, three aborts. The existing
  Leave proof passed 12 groups, including profile, holidays, timesheet and
  in-flight status withdrawal (writes only against its mocked fixture).
- Light/dark screenshots `/tmp/radd-audit-contributions-{light,dark}.png` inspected.
  A deliberate denied-refresh toast remains briefly in the dark screenshot; it
  is expected feedback from that test scenario, not a successful-read error.
- Local backend reloaded at `http://localhost:8000`. An ephemeral-token probe
  verified served Audit/Items/Auth bytes against all three built bundles, SDK 1.11, the
  contributed navigation requirement, global and project access responses and
  25 actual audit rows. The token was discarded. Leave/GitHub/Forgejo remain
  disabled; the before/after enabled-plugin list is identical. No external
  deployment or repository push was performed.

## RADD-1365 — Complete Automations frontend contribution

Moved the remaining rule editor, graph inspector/forms, token assistance,
dry-run/runs/versions panels, settings and integration policies from the host
into Automations. Removed executable host automation facades, transport and
catalog-specific shell invalidation. The settings route/navigation belongs to
the plugin; VCS/Email/Alertmanager callers now supply generic integration context.
Actual registry owner IDs travel with templates and trigger catalog entries.
Manual quick actions use the SDK's nonvisual command contribution contract.

Projects, Items and Pages own lookup requests; public types/data packages connect
pickers, Fields/Labels catalogs, item vocabulary and comment visibility without
importing another owner's implementation. A contracts-only UI package does not
need an empty remote. Generic confirmation/clipboard/filter/debounce/icon/error
primitives are shared rather than copied. The editor keeps mounted-scope reads,
fresh capability revisions and cancellable mutation generations. Runs and
versions expose read failures; obsolete reports and denied cached results are
hidden. Saved references survive missing dependent owners. Screenshots exposed
name/note inputs shrinking because a flex item class was applied to the input
inside a column; sizing now belongs to their outer row wrappers.

Final stage evidence:

- `node web/scripts/build-all.mjs` passed: host plus 26 executable plugin remotes,
  with seven public contract packages linked before host typechecking. SDK 1.12
  adds commands and the integration-settings slot; Projects/Pages now declare
  SDK 1.9 for their query-source contributions.
- 78 frontend tests passed, including actual command-registry withdrawal,
  retained callbacks, in-flight cancellation, loader rollback, ownership
  boundaries and generated-shim parity. 78 backend tests passed across templates,
  runs, versions, graph, samples, federation, module contracts and plugin workflow.
  Three existing dependency deprecation warnings remain. Changed Python files
  passed Ruff.
- `browser-automation-editor.mjs` passed 16 groups with 156 requests, seven mocked
  writes and four confirmed aborts. It loads actual host/owner bundles and generates
  catalog fixtures from the real backend registry. Coverage includes absent owners,
  explicit integration identity, unsaved template drafts, rich graph/inspector
  editing, current-draft previews, saved unavailable triggers, dependent lookup
  withdrawal, version preview/restore, stale or denied reports, A→B→A cancellation,
  open save withdrawal, authoritative recovery, failed bundle replacement and
  management permission loss/recovery. Browser writes affect only mocked fixtures.
- Existing actual-bundle proofs also passed: canvas 15 groups/13 requests/three
  aborts; query contributions 12 groups/21 requests/four aborts; Audit 17
  groups/77 requests/three aborts. Light/dark editor screenshots were inspected;
  the browser asserts the corrected name input is at least 30 pixels high.
- The local app at `http://localhost:8000` serves byte-identical builds for all
  six probed owners (Automations, Items, Projects, Pages, Fields, Labels). Its
  catalog has 50 nodes, 96 triggers and nine templates with enabled registry
  owners; nine local rules remain. Contributed Automations navigation and SDK
  declarations were checked. The temporary verification token was discarded.
  Leave, GitHub and Forgejo remain disabled, and the full enabled-plugin set is
  unchanged. No external deployment or repository push occurred.

Core owners remain core; missing-bundle fixtures exercise contribution lifetimes,
not a new ability to disable them in Settings. Backend/action separation,
remaining VCS/Email/Alertmanager implementation and built-in item quick-action
ownership stay in the epic's full inventory. Moved files whose entire behavior
has not been individually audited remain partially reviewed.
