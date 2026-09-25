# Plugin isolation audit — RADD-1343

The objective is the complete audit and refactor requested on 2026-09-25. This is a work ledger, not a completion report. Discovery does not establish ownership or correct runtime behavior.

## Evidence and coverage

`inventory.json` records every backend, frontend, SDK and example source file, imports, module declarations and remote sources. Refresh with `python scripts/plugin_inventory.py`. `review.json` records ownership decisions and evidence per file; edits invalidate earlier file reviews. All entries begin unreviewed. The inventory is intentionally broader than optional plugins.

## Work groups

| Issue | Scope | Status |
|---|---|---|
| RADD-1344 | Complete inventory, ownership and boundary safeguards | In progress |
| RADD-1345 | Person status and timesheet data contributions | Verified; Waiting for release |
| RADD-1346 | Settings, imports and VCS provider UI | Pending |
| RADD-1347 | Issue, automation and editor integrations | Pending |
| RADD-1348 | Pages, dashboards, widgets and navigation | Pending |
| RADD-1349 | Backend public seams, dependencies and background lifecycle | Pending |
| RADD-1350 | Full requirement-by-requirement verification and documentation | Pending |

## Module review ledger

Declared core status is recorded, not accepted as an exemption. Every module must be reviewed.

| Module | Core declaration | Remote sources | Dependencies | Review |
|---|---|---|---|---|
| access | default | 0 | projects, events, auth, teams, groups | Pending |
| ai | False | 2 | auth, projects, items, fields, workflow, comments, search, settings, events, pages, timelogging, attachments | Pending |
| alertmanager | False | 0 | projects, auth, items, events, automations | Pending |
| approvals | False | 2 | events, projects, auth, teams, workflow, items | Pending |
| attachments | default | 0 | events, projects, auth, items, access, groups, teams | Pending |
| audit | default | 0 | events, auth, projects, items | Pending |
| auth | default | 0 | events, projects | Pending |
| automations | default | 0 | projects, auth, workflow, labels, cycles, releases, items, comments, teams, events, fields, itemtypes | Pending |
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
| leave | False | 2 | auth, teams, events | Pending |
| linktypes | default | 0 | projects, events, auth | Pending |
| mailintake | False | 2 | projects, auth, items, comments, automations, events, attachments, settings, workflow | Pending |
| mcp | False | 0 | auth, projects, fields, linktypes | Pending |
| milestones | False | 2 | projects, auth, events | Pending |
| monitoring | False | 0 | auth, events | Pending |
| notify | default | 0 | events, projects, auth, items, comments, teams | Pending |
| pages | False | 0 | events, projects, auth, workflow, items, attachments, labels, comments, notify, access, groups, search, teams, settings | Pending |
| participants | False | 3 | events, projects, auth, teams, items, notify | Pending |
| pluginmgr | default | 0 | auth, events | Pending |
| projects | default | 0 | events | Pending |
| realtime | default | 0 | events, auth | Pending |
| releases | default | 0 | projects, auth, events, workflow | Pending |
| reporting | default | 0 | events, projects, auth, workflow, cycles, items | Pending |
| screens | default | 0 | projects, events, auth, fields, itemtypes | Pending |
| scripts | False | 2 | auth, events, projects, items | Pending |
| search | default | 0 | events, projects, auth, workflow, items, comments, access, fields, teams | Pending |
| settings | default | 0 | events, projects, auth | Pending |
| slas | False | 0 | events, projects, auth, settings, workflow, items, comments, automations, reporting, teams | Pending |
| sso | False | 0 | events, projects, auth, teams | Pending |
| teams | default | 0 | events, projects, auth, groups | Pending |
| timelogging | default | 0 | events, projects, auth, teams, items, settings | Pending |
| vcs | default | 0 | projects, auth, events, items, timelogging | Pending |
| views | default | 0 | projects, workflow, items, fields, auth, events, access, groups, teams | Pending |
| webhooks | default | 0 | projects, events, auth, fields, items | Pending |
| weblinks | default | 0 | projects, auth, events, items | Pending |
| workflow | default | 0 | projects, events, auth, settings, teams | Pending |

## Confirmed findings still requiring remediation

- Host router directly imports optional settings pages and optional Pages/Dashboards/CSAT routes (`web/src/router.tsx`). Generic slot routes coexist with plugin-specific route components.
- SDK capability queries use a separate cache and `useHasPlugin` defaults true while loading (`web/packages/plugin-sdk/src/hooks.ts`); capability withdrawal needs a unified contract.
- SettingsPluginPage shows an indefinite spinner for absent or failed contributions, and directly calls a contribution render function instead of a boundary-wrapped slot.
- Leave's residual status/timesheet coupling has been removed in RADD-1345. Source review is recorded only for the portions actually examined; this does not mark the entire backend Leave module reviewed.

## RADD-1345 verification

The Leave remote supplies typed `personIndicators` and `timesheetAnnotations` data. Avatar/name, pickers and timesheet consume generic facts; plugin data queries use activation generation and actor-specific cache identity. The loader withdraws sources on disable and failed activation. Unused queries receive cancellation through their AbortSignal. Settings mutations invalidate the plugin's data consumers.

The built-browser regression covers initial disabled state, live enable, withdrawal of cached status, failed remote loading, personal leave add/delete, holiday submission and slot withdrawal, calendar withdrawal, aborted in-flight status lookup and successful fresh activation. Loader unit tests cover data-only remotes and late registration after disable. AST boundary tests check remote relative imports and prevent Leave vocabulary/endpoints re-entering the host. Other plugins and cross-plugin interaction coverage remain pending.

RADD-1345 result: host and all 9 remote bundles build/type-check; 37 frontend unit/boundary tests and 11 focused backend tests pass; the expanded built-browser regression passes all 12 lifecycle/form checks. Local backend manifest reloaded (PID 1955690), health passes. Local Leave enable/disable probe verifies manifest and served remote in the same process and restores disabled. No external deployment.
