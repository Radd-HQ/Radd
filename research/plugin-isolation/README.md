# Plugin isolation audit — RADD-1343

The objective is the complete audit and refactor requested on 2026-09-25. This is a work ledger, not a completion report. Discovery does not establish ownership or correct runtime behavior.

## Evidence and coverage

The record is the **module review ledger** below: 57 builtin modules and the
external example, each with its review status and the issue that moved it.

`scripts/plugin_inventory.py` is an on-demand discovery tool. It inventories
every tracked artifact (and new source/config files), with hashes, import hints,
manifests and package dependencies, and keeps per-file review notes. Its output
lives in `research/plugin-isolation/ledger/`, which is gitignored (RADD-1374). A
per-file hash ledger committed to git made every commit — a docs typo included —
regenerate about 4 MB of JSON to satisfy a CI freshness gate, and reset a changed
file's review to "unreviewed". The CI job is gone. The durable invariants live in
tests: `server/tests/test_module_contracts.py` (declared cross-module imports) and
`web/scripts/plugin-boundaries.test.mjs` (host/plugin frontend boundaries).

Static imports and declarations are discovery hints; they cannot establish
dynamic registration or ownership by themselves. The final audit inspects actual
runtime behaviour.

## Course correction (2026-09-26)

A four-way review of RADD-1340–1366 changed the plan (Hussein's decisions):

- **Core modules are static plugins** (RADD-1373). Core, non-disableable modules
  keep their UI in `modules/<m>/ui/src` and contribute through the same slot API,
  but the host bundles and registers them at boot. Only optional plugins
  (`core=False`) are federated remotes. Moving core UI into remotes had bought
  nothing (a core plugin cannot be withdrawn) and cost a load gap on every
  picker, uncached refetches, and host code still importing plugin source by
  relative path.
- **The per-file ledger left git and CI** (RADD-1374); see above.
- **Confirmed bugs** from the moves are tracked as RADD-1371 (automation catalog
  500 with Milestones on, page-space gate, aborted writes) and RADD-1372 (live
  plugin toggling: process-wide drain and 503, skipped shutdown hooks, consumers
  replaying their backlog on re-enable).
- **Integration behaviours returned to their pages** as plain settings run by the
  owning plugin (RADD-1367: Email, VCS, Alertmanager) — separate from isolation,
  decided the same day.

## Work groups

| Issue | Scope | Status |
|---|---|---|
| RADD-1344 | Complete inventory, ownership and boundary safeguards | Safeguards delivered (module contracts + plugin boundaries); per-file ledger retired from CI by decision (RADD-1374); Waiting for release |
| RADD-1345 | Person status and timesheet data contributions | Verified; Waiting for release |
| RADD-1346 | Settings, imports and VCS provider UI | Delivered via 1366/1377–1382/1389/1390; Waiting for release (Page spaces moves with 1348) |
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
| RADD-1365 | Automations frontend contribution | Verified; Waiting for release |
| RADD-1366 | VCS settings and connector-owned declarations | Revised after review; Waiting for release |
| RADD-1371 | Automations review fixes (catalog 500, page-space gate, aborted writes) | Waiting for release |
| RADD-1372 | Live plugin toggling: per-plugin drain, no process-wide 503, no backlog replay | Waiting for release |
| RADD-1373 | Core modules as static plugins; pending state for optional remotes | Waiting for release |
| RADD-1375 | Compatibility re-exports deleted; a boundary test refuses new ones | Waiting for release (in the 1373 commit) |
| RADD-1376 | UI details the moves lost (change lines, focus ring, spinner labels, tokens, Leave) | Waiting for release (in the 1373 commit) |
| RADD-1374 | Ledger out of git and CI; module table is the record | Waiting for release |
| RADD-1377 | SDK bridges for plugin settings pages (ScopedSettings, RoleGrants, toast); SDK shim exports derived from source | Waiting for release |
| RADD-1378 | Settings → Email is mailintake's remote | Waiting for release |
| RADD-1379 | Settings → AI is ai's remote | Waiting for release |
| RADD-1380 | Sign-in providers are sso's remote section of the core Sign-in page | Waiting for release |
| RADD-1381 | Settings → Directory is ldap's remote | Waiting for release |
| RADD-1382 | Jira/Confluence importers are remotes; "Import" nav group replaces the host hub | Waiting for release |
| RADD-1383 | Approval gates are a `TRANSITION_CHECK` socket approvals provides (fail closed) | Waiting for release |
| RADD-1384 | Search sources contributed (pages, ai) | Waiting for release |
| RADD-1385 | Notify subjects, audiences and mail transport contributed (pages, participants, mailintake) | Waiting for release |
| RADD-1386 | The SLA report is slas's; reporting's chart kit is a bundled core package | Waiting for release |
| RADD-1387 | Automations/storage routing stop reaching leave, mailintake, participants, ai | Waiting for release |
| RADD-1391 | Team-restricted internal comments no longer reach every internal reader's inbox (found by 1385) | Waiting for release |
| RADD-1388 | Guessed status-token classes (uncoloured errors) fixed and refused | Waiting for release |
| RADD-1389 | Server status renders capabilities generically; outbound mail is mailintake's | Waiting for release |
| RADD-1390 | Settings rows declare their page (`page_scopes`); nav icons from one registry | Waiting for release |
| RADD-1392 | Pages is core; the wiki UI is the bundled pages package | Waiting for release |
| RADD-1393 | Dashboards is core; My Work widgets contributed via WidgetTypeSpec | Waiting for release |
| RADD-1394 | Plugins contribute list columns and card cells; SLA timers first | Waiting for release |
| RADD-1395 | Editor extension points; editor AI is the ai plugin's (palette Ask + query-bar NL remain) | Waiting for release |
| RADD-1396 | SLA settings page and queue views are the slas plugin's | Waiting for release |
| RADD-1397 | Co-editing's UI is the collab plugin's (ProseMirror shared on demand; yjs private to the remote) | Waiting for release |
| RADD-1399 | Proof harness removes its Chrome profiles (/tmp filled) | Waiting for release |
| RADD-1400 | Palette and query-bar contributed modes; Ask and NL→SLQ are ai's | Waiting for release |
| RADD-1401 | Public CSAT survey page is csat's (`public.page`); mailed bodies are mailintake's (`content.body`) | Waiting for release |
| RADD-1347 | Issue, automation and editor integrations | Delivered; Waiting for release |
| RADD-1348 | Pages, dashboards, widgets and navigation | Delivered: Pages and Dashboards are core bundled packages (1392/1393); Waiting for release |
| RADD-1349 | Backend public seams, dependencies and background lifecycle | Delivered via 1383–1387; guard test refuses core→optional edges; Waiting for release |
| RADD-1350 | Full requirement-by-requirement verification and documentation | This record; Waiting for release |

## Module review ledger

Two review levels, stated honestly. **Reviewed** means the module was moved or inverted in this epic, and its surfaces verified against a real backend and the mocked suite. **Guarded** means it is covered by the mechanical checks, but nobody re-read it file by file. Those checks are `test_module_contracts.py` (declared imports, spine-only model imports, no core → optional reach) and `plugin-boundaries.test.mjs` (plugin UI imports, no host re-exports, no AI/SLA/collab/csat/mail vocabulary in `web/src` apart from named exceptions, a derived SDK surface, registry-shipped nav icons, status tokens). The core modules' host-owned UI is not a violation: core modules are static plugins by decision (RADD-1373), and moving their UI into packages is optional.

Which modules are core or optional, where each one's UI lives and what it `depends_on` are generated from the plugin manifests in [docs/modules.md](../../docs/modules.md#at-a-glance); this ledger keeps only the review verdicts.

| Module | Review |
|---|---|
| acme-notes (external example) | Loads headless as an external remote (spec 94 acceptance); not re-audited |
| access | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| ai | Reviewed — RADD-1379/1384/1387/1395/1400: settings, editor, read-mode, issue, draft, palette and query-bar surfaces are its remote; search candidates and the llm routing rule are its socket providers; `web/src` holds no AI vocabulary (boundary test) |
| alertmanager | Reviewed — RADD-1370: settings page is its remote; receiver behaviours are its own settings |
| approvals | Reviewed — RADD-1383/1393: approval gates are its `TRANSITION_CHECK` provider (fail closed); the approver editor and the My Work widget are its remote |
| attachments | Reviewed — RADD-1387: storage rule types come from the socket; no reach into ai |
| audit | Reviewed — RADD-1363/1364: bundled package; owners declare entity destinations |
| auth | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| automations | Reviewed — RADD-1365/1371/1387: its UI is the bundled package; no reach into optional plugins |
| avatars | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| backup | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Schedule contribution verified (RADD-1362); full settings/backend review pending |
| canned | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| capabilities | Reviewed — RADD-1389: rows name their owning plugin; owns only `workers` |
| collab | Reviewed — RADD-1397: the live session, editor binding and presence are its remote; ProseMirror is shared on demand, yjs stays private |
| comments | Guarded — core; UI contract only; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| confluenceimport | Reviewed — RADD-1382: its page is its remote under the "Import" nav group |
| csat | Reviewed — RADD-1386/1401: CSAT folds into the SLA report through a slas→csat weak edge; the tokened public survey page is its remote through the new `public.page` slot (`/public/csat/$token`), loaded for anonymous visitors exactly as the visitor shell already loads remotes |
| cycles | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Picker contributions verified (RADD-1358); remaining review pending |
| dashboards | Reviewed — Core since RADD-1393: UI is the bundled package; My Work widgets are `WidgetTypeSpec` contributions (`personal` + `suggest`) |
| events | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| fields | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Catalog contributions verified (RADD-1361); remaining review pending |
| forgejo | Reviewed — RADD-1366/1369: contributes wording to the VCS settings; per-repository switches |
| forms | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| github | Reviewed — RADD-1366/1369: contributes wording to the VCS settings; per-repository switches |
| gitlab | Reviewed — RADD-1366/1369: contributes wording to the VCS settings; per-repository switches |
| groups | Reviewed — Its audit link points at `/settings/directory` (ldap's page); only an entity's owner may declare its link (RADD-1390) |
| items | Reviewed — RADD-1383: calls `workflow.state_moved` instead of approvals |
| itemtypes | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| jiraimport | Reviewed — RADD-1382: its page is its remote under the "Import" nav group |
| labels | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Catalog contributions verified (RADD-1361); remaining review pending |
| ldap | Reviewed — RADD-1381/1389: Directory page is its remote; its capability feeds Server status. Justified exception: the login page's LDAP form stays host (pre-auth) |
| leave | Reviewed — RADD-1345/1387: person status and timesheet data contributions; provides `PERSON_AVAILABILITY` |
| linktypes | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| mailintake | Reviewed — RADD-1368/1378/1385/1387/1389/1401: settings page is its remote; provides `MAIL_TRANSPORT`, the send_email node and the outbound_mail capability; draws mailed bodies (signature fold + restore) by claiming them through the `content.body` slot |
| mcp | Reviewed — No UI; tool catalog through the kernel registry (spec 114); no core module reaches it (guard) |
| milestones | Reviewed — Contributed entity, nav and SLQ field (north star); RADD-1371 fixed its catalog ownership |
| monitoring | Reviewed — RADD-1352: settings page and health cards are its remote |
| notify | Reviewed — RADD-1385/1391: subjects, audiences and mail transport through sockets; team-restricted comment leak fixed. Named exception: its `sla_breach`/`sla_due_soon` kinds |
| pages | Reviewed — Core since RADD-1392: the wiki UI is the bundled package; provides `SEARCH_DOCUMENTS` and `NOTIFICATION_SUBJECT` (RADD-1384/1385) |
| participants | Reviewed — RADD-1385/1387: provides `NOTIFICATION_AUDIENCE` and the add_participant node; its issue card is its remote |
| pluginmgr | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| projects | Reviewed — RADD-1378/1389: blocker urls from owners' entity links; `/instance/status` deleted |
| realtime | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| releases | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Option contributions and role history presentation verified (RADD-1357/1364); remaining review pending |
| reporting | Reviewed — RADD-1386: SLA report moved out; its chart kit is a bundled package |
| screens | Reviewed — RADD-1396: the dead `sla` row is removed |
| scripts | Reviewed — RADD-1352/1269: settings page and node inspectors are its remote |
| search | Reviewed — RADD-1384: reads `SEARCH_DOCUMENTS`/`SEMANTIC_CANDIDATES`; imports neither pages nor ai |
| settings | Reviewed — RADD-1390: rows carry `homed` from `SettingSpec.page_scopes` |
| slas | Reviewed — RADD-1386/1394/1396: report, list columns and card cells (`slas.timer`), issue panel, settings page and queue views (`slas.queue`) are its remote |
| sso | Reviewed — RADD-1380/1389: provider registry is its remote section of the core Sign-in page. Justified exception: login-page provider buttons stay host (pre-auth) |
| teams | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file; earlier: Option and relationship contributions verified (RADD-1357/1359); remaining review pending |
| timelogging | Guarded — core; UI bundled package; edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| vcs | Reviewed — RADD-1366/1369: VCS settings belong to it; connectors contribute wording |
| views | Reviewed — RADD-1394/1396: contributed item attributes and list-surface view types |
| webhooks | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| weblinks | Guarded — core; UI host-owned by decision (core = static, RADD-1373); edges enforced by test_module_contracts (declared imports, spine models, no optional reach); not re-audited file by file |
| workflow | Reviewed — RADD-1383: evaluates contributed transition checks; publishes the rule-editor slot contract |

## Remaining work and justified exceptions (2026-09-26)

**Justified exceptions** (named in the boundary tests where applicable):
- **Login page:** its SSO buttons and LDAP form stay in the host. Nothing remote can load before sign-in (RADD-1380/1381).
- **notify's SLA kinds:** `sla_breach`/`sla_due_soon` are core notify's vocabulary (RADD-1396).
- **Groups' audit link:** it points at ldap's Directory page, because only an entity's owner may declare its link and no core page lists groups (RADD-1390).
- **History tab sentences for plugin events:** the issue History tab still writes the sentences for `csat.*`, `mail.*` (and approvals, participants, vcs) events itself. It is the history of every plugin's events, and those events outlive the plugin that emitted them. Letting plugins supply them is a cross-plugin change of its own. The boundary test names the rows and fails once they are gone (RADD-1401).

**Remaining:**
- **RADD-1398:** a plain home load fetches ~210 script chunks. Measure it before changing anything.
- **SDK peer dependencies:** it does not declare `prosemirror-*` as peer dependencies, so an external plugin that binds the editor must install them itself (RADD-1397).
- **Per-file ledger** (`scripts/plugin_inventory.py`): it stays an on-demand tool writing to an ignored path (RADD-1374). File-by-file ownership of migrations, build and deploy config (RADD-1344) was not re-audited.

**Resolved since the first audit:**
- The host router no longer imports optional settings pages, the Pages/Dashboards routes or the public CSAT page (RADD-1378–1382, 1392, 1393, 1401). Route contributions match patterns (`$name` segments), and a `public.page` slot serves pre-auth plugin pages.
- Core modules no longer reach optional plugins, and a test refuses the class (RADD-1349).
- **RADD-1395 live-provider proof:** verified on 2026-09-27 against a live qwen3.8-27b served at localhost:8221 (`editor-ai-proof.mjs`, all checks; `ai-protect-proof`, `ai-provider-options-proof` and `ai-settings-page-proof` too). It had been unverified until then because the model host refused connections from the build machine.

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
- Light/dark schedule and backup screenshots inspected.

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
- Entity-link screenshot inspected. The temporary scope-denied toast belongs to the
  refusal scenario immediately before recovery.

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
- Light/dark screenshots inspected.
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

## RADD-1366 — VCS settings and connector-owned declarations

VCS now contributes its settings/navigation and shared connection/repository and
identity-map workflow. Forgejo, GitHub and GitLab each contribute their own tab,
endpoint configuration, guidance and legacy redirect through the public VCS
contract. Host settings/transport/provider lists and dead connector constants
were removed. Provider tab order is explicit, independent of import timing; a
missing requested provider keeps its URL selection and restores when available.
The core VCS page offers an empty state when all connector tabs are unavailable.

Shared request cancellation and entity invalidation are SDK primitives used by
VCS, Automations and the host. Provider reads have fresh mounted scopes and hide
denied cached data; permission withdrawal disposes all credential drafts. Auth,
Projects and Time Logging own their directory/category lookups, while VCS retains
saved IDs and identity selections during their withdrawal. Time Logging formats
held durations on the server using its configured working-day units; VCS's
unmatched-author DTO carries that display value with the original seconds.
Identity rows wait for their reads before reporting an empty or fully matched
state. Screenshot review caught squeezed repository names, now rendered on a
separate row and checked by browser measurement.

Stage evidence:

- Host plus 31 executable remotes built against SDK 1.13, with nine public
  contract packages. All 79 frontend tests passed, including ownership/import
  guards, shared entity invalidation and federation parity. All 80 backend tests
  passed across time mirroring, connector configuration, federation, module
  contracts and plugin workflow (three existing dependency warnings). The new
  DB-backed endpoint test proves eight hours renders as `1d 1h` for a seven-hour
  working day. Changed Python files passed Ruff.
- `browser-vcs-settings.mjs` passed 13 groups using actual VCS, all three
  connector, Auth, Projects, Time Logging, Automations and Audit bundles: 210
  requests, seven writes against mocked fixtures, two confirmed transport
  aborts. It checks initial absence, matching URL/legacy paths, preserved
  credentials, mirroring/backfill/test, actual person selection/replay/unmapping,
  missing lookup owners, denied refresh, provider and VCS withdrawal/recovery,
  failed provider and VCS bundle replacement, and permission loss/recovery.
  Light/dark screenshots inspected.
- Existing Automations actual-bundle proof passed 16 groups/156 requests/four
  aborts after adopting the SDK mutation lifetime. Existing Audit proof passed
  17 groups/77 requests/three aborts after shared invalidation extraction.
- Local backend reloaded and served bytes checked for VCS, GitLab, Time Logging,
  Automations, Projects and Auth. Its existing GitLab connection/repository are
  still present; no credentials are exposed by the reads. There are no locally
  unmatched authors, so duration content is proven by the DB-backed test rather
  than a local row. The temporary probe token was discarded. Leave/GitHub/Forgejo
  remain disabled and the complete enabled-plugin list is unchanged. No external
  push/deployment occurred.

**Revised 2026-09-26 after review** (same issue, before commit): a static review
found four defects. The SDK `useContributionMutation` keyed its lifetime on the
whole instance's plugin list and ABORTED in-flight writes on any capability
change — an accepted create reported "no longer current" and a retry duplicated
it; a backfill died on a tab switch. It is deleted: VCS and Automations use plain
`useMutation`. The category select showed a raw UUID while categories loaded; it
now waits, and names archived or deleted categories. The connectors' legacy
redirect pages existed only for stale audit links; their `EntityLinkSpec`s name
`/settings/vcs?host=<provider>` and the redirects are gone. The host's
`invalidateEntities` lost its `EntityTag` typing; it wraps the SDK function typed
again. Also: connector configs carry wording only (paths/tags/audit types follow
from the provider key), each repository row owns its mutations (one save no longer
disables every row), removals confirm, the repo toggles are SDK `Switch`es, the
`VcsScope`/per-mount identities are gone, and the page no longer embeds the
automation panel (RADD-1369 brings the behaviours back as switches).
`browser-vcs-settings.mjs` was updated to match and passes 13 groups (149
requests, 7 mocked writes, one read aborted on VCS withdrawal; no write aborted).
The loading flash while connector bundles register is RADD-1373's pending state.

Remaining ownership is explicit: the VCS issue-reference panel, backend
connectors/ingestion and realtime server-entity mapping still need their full
inventory audit. Core bundle-withdrawal fixtures do not make core VCS or Time
Logging administratively disableable. Large shared/backend artifacts retain
partial status; this stage is not completion of RADD-1343/1346/1347.


---

## Appendix: ownership notes (moved from `docs/modules.md`, 2026-09-27)

As recorded in the module map when each change landed; the map now describes only the result.

### Personal dashboards and email signatures (RADD-1333–1338)

`dashboards` exposes private My Work widget definitions and current-access-filtered personal activity. It reads the append-only log through `events.service.query_events` and checks current item and comment visibility. Deferred, optional reads of `comments`, `forms`, and `approvals` are declared weak dependencies; the latter two select relevant defaults. Shared and personal definitions use the same widget schemas and twelve-column layout. Personal definitions live in the user's server preferences; shared definitions remain dashboard-owned.

`mailintake.signatures` runs domain-scoped bounded regex rules, conservative built-ins, then the optional `ai.mail_signature` feature through the configured chat role. `items.service` and `comments.service` own reversible annotation writes and restoration authorization. Bodies remain intact; read schemas expose the signature annotation beside the same visible body. Description field restrictions blank the annotation too. The requester read surface includes annotations only for already-visible descriptions and public comments. `mailintake.signature_router` owns admin settings/preview and delegates restoration to those services.


### Settings contribution ownership (RADD-1352)

Scripts and Monitoring own their settings pages in their colocated `ui/` remotes, declared via `PluginUiManifest.nav` and `settings.page`. The host router/navigation no longer names either feature. Scripts owns its interpreter/package types, queries and forms; remote inspectors reuse the local run-result type. Queries consume AbortSignal, are stale on mount and are discarded after their last observer leaves.

Monitoring offers the `settings.section` match `monitoring` inside its card grid. AI contributes `EmbeddingHealthCard` and its coverage query; Mail intake contributes `MailHealthCard` and the admin-only `/mail/health` endpoint. Neither page nor host has a visibility switch for these cards. The overview's existing `mail` API field remains for compatibility through the declared `monitoring -> mailintake.service` optional seam; the new UI does not consume it. Monitoring's catalog table-count list remains a backend audit item.

`RaddPlugin.consumer_descriptions` supplies operator text for its own `consumer_names`; event consumer status reads descriptions from currently registered plugin declarations. Withdrawal removes descriptions while preserving saved cursors as retired. Every builtin consumer now declares its description at its owner. RADD-1372: `RaddPlugin.consumer_resume` declares, per consumer, where it continues when its plugin is (re-)enabled — `ConsumerResume.CURSOR` (the default: catch up) or `HEAD` (skip what happened while off; `mailintake.outbound`, `csat.sender`). The head-seeded runner only seeds a FIRST start; the plugin manager applies HEAD on re-enable. Tailwind scans colocated remote sources generically, so moving a form out of the host does not silently remove its theme utilities.


### Directory contribution ownership (RADD-1353)

Auth's `ui/src/index.tsx` owns the people-directory picker query (`auth.people`). Teams' remote owns team choices (`teams.teams`) and member/manager/owner candidates (`teams.candidates`). Both register the public `directory.select` slot, with UI SDK minimum 1.4. A plugin needing a person picker (such as VCS identity mapping) uses the generic SDK DirectorySelect; it does not import a host feature component. The source provider owns endpoints, candidate rules, query keys and realtime entity tags. Generic modal/search/pagination stay in the platform through the SDK's shared control adapters. The host's existing PeopleDirectorySelect callers now delegate through this seam, with their behavior preserved; migration of those calling features is still pending.

**RADD-1364 — Audit frontend ownership.** Audit now owns its page, URL filters,
access/catalog/ledger reads, entity history panel and settings footer under
`server/src/radd/modules/audit/ui`. Generic settings-footer and entity-history
slots replace host Audit rendering and permission guesses. `/audit/access` uses
the ledger's exact scope rule, including constrained admin credentials. SDK 1.11
owns generic change rendering and shared date/table/pagination/collapse primitives;
Items contributes issue-specific history wording and field suggestions through
its own remote, while Auth contributes its role-grant wording. The SDK avatar
uses the shared host avatar to preserve contributed person status indicators. Projects publishes its picker data/type contract as an explicit
package export. Filter changes reset pagination immediately, external navigation
cancels stale search drafts, and the To date includes the final fractional second.
Queries abort on contribution withdrawal, use fresh observer-owned cache keys,
and participate in permission invalidation. Both new remotes retain their existing
core-plugin policy. Other Items UI and Audit backend cross-feature seams remain
in the complete isolation inventory.

### Automations UI ownership — RADD-1365

The complete automation settings/editor frontend now lives under
`server/src/radd/modules/automations/ui/src`: inspectors, graph editing, previews,
runs, versions, integration templates and their transport/lifetimes. The host
uses the generic settings catch-all and integration slot. Manual item commands
are nonvisual contributions through SDK 1.12. Items/Pages/Projects own preview
lookup transport; public owner contracts supply picker types and shared metadata.
Registry owner IDs replace template display-group/prefix inference. Existing
Automation backend services and action dependency ownership are still under the
full audit; this change does not certify them or the remaining host VCS/Email UI.
See `docs/plugin-platform.md` and the RADD-1365 inventory evidence.

RADD-1371 fixes two things that move broke. Trigger owners come from
`registries.event_owners()`, which counts events an `EntitySpec` DERIVES as well
as declared `event_types` — the catalog had KeyError'd (500) on
`milestone.created` whenever Milestones was on. "Page is in space" matches a
saved space ID or slug: the picker stores IDs since RADD-1365, the ref carries
both, older graphs hold slugs.

RADD-1369 gives every GitLab/GitHub/Forgejo repository row two switches, OFF
by default and for existing rows (migration `d1369vcspolicy`): `move_on_merge`
(a merged MR/PR moves the issues it names to their project's waiting state —
`releases.pipeline.waiting_state_id`, restored — skipping issues already in a
done category) and `publish_on_release` (a published release/tag runs
`pipeline.on_release_published` for the default project). Both live in
`vcs/policies.py`, called by the three receivers after they fire their
triggers; `vcs` now `depends_on` workflow + releases. The per-host automation
templates that duplicated them are deleted; the triggers and the
`release.publish` node stay. Settings → Version control shows them on each
repository row.

RADD-1373 — **core plugins' UI is bundled into the host; optional plugins stay remotes.** A core module's `ui/package.json` carries `"radd": {"bundled": true}` and an entry export; its manifest declares no `remote`. `web/scripts/plugin-packages.mjs` links plugin packages and generates `web/src/plugins/static.generated.ts`, and `plugin-loader.syncStaticPlugins` registers them at boot, withdrawing them only when `/capabilities` stops listing the plugin. The host imports plugin contracts through package exports only. SDK: `setRemotesLoading`/`useRemotesLoading` + `Slot`'s `pending`; per-mount query identities are gone from option/directory/query-source/command queries and the core pickers. Details: `docs/plugin-platform.md` §8 "Bundled core plugins, remote optional plugins".

RADD-1366 moves version-control settings into VCS and connector remotes.
`vcs/ui` owns the provider-neutral page (hosts, repository rows, identity map);
GitHub, Forgejo and GitLab each contribute one tab carrying only their WORDING
(`VcsHostConfig`) — REST paths, cache tags and audited entity types follow from
the provider key by VCS's one convention (`hostPaths`/`hostEntities`/
`historyEntities`). Their audit links point at `/settings/vcs?host=<provider>`
(EntityLinkSpec), so no redirect routes exist. Projects/Auth supply pickers, and
Time Logging supplies category queries and server-formatted held durations.
