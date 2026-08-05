# Radd frontend audit — long lists without search/filter, 2026-08-05

Dataset used for scale (from `server/scripts/perfseed.py` targets + CLAUDE.md): **82 projects, ~3,088 users (1,031 active / 2,057 disabled AD), 2,293 teams, 2,016 labels, 319 custom-field defs, 107 status names, 61 issue-type names, ~250 views, 503k items, 1.8M comments; Jira import inbound: 337 fields / 83 statuses / 59 types.**

All paths below live under `<repo>/`.

## Executive summary

**47 surfaces audited** (32 page-level lists + 15 pickers/dropdowns). **27 have no search/filter at all; 3 more have a filter but no pagination.** Item surfaces (boards/lists/My Work/timesheet) are healthy — SLQ + `Pager` (spec 41) already solve them. The problem is concentrated in **settings/admin lists and in the kit `Select` dropdown**, which only does first-letter jump type-ahead, never filtering.

The worst 5:

1. **The user-picker class — 7 call sites, ~1,031 options each, no search.** Assignee/Reporter on the issue rail, New Item modal, bulk bar, timesheet person filter, project "Add member", team "Add member", and the Jira-import per-row user mapper all render a `Select`/`SelectField` over the full user directory. One component fix (`Select` gains a search input) clears all seven.
2. **Settings → Teams** — 2,293 expandable rows, no filter, no paging (`web/src/routes/settings/teams.tsx:41`).
3. **Settings → Labels** — 2,016 rows in one `<ul>`, no filter (`web/src/routes/settings/labels.tsx:43`).
4. **Settings → Fields master rail** — 319 definitions in a 260 px rail, no filter (`web/src/routes/settings/fields.tsx:132`) — while the *options* list inside a field already grows a filter input at >12 entries, so the page filters 200 options but not 319 fields.
5. **Wiki page tree + Jira import users table** — a space's full page list rendered as an unfilterable tree (`web/src/components/pages/PageTree.tsx:143`), and hundreds of unmatched Jira users each carrying a 3,000-option dropdown (`web/src/components/settings/jira/UsersTable.tsx:92`).

## Full table — page-level list surfaces

Severity: CRITICAL = thousands of rows, unbounded, no filter · MAJOR = hundreds, or a filter/pagination half missing · MINOR = dozens. "API paginates?" reflects the server router today.

| Surface | File | Entity | Scale | Filter? | Pagination? | Severity |
|---|---|---|---|---|---|---|
| Settings → Teams | `web/src/routes/settings/teams.tsx:41` | teams | **2,293** | No | No (API: none) | **CRITICAL** |
| Settings → Labels | `web/src/routes/settings/labels.tsx:43` | labels | **2,016** (auto-created on use) | No | No (API: none) | **CRITICAL** |
| Settings → Fields (master rail) | `web/src/routes/settings/fields.tsx:132` | custom field defs | **319** | No (options *inside* a field: yes, >12) | No (API: none) | **CRITICAL** |
| Settings → Users | `web/src/routes/settings/users.tsx:100-157` | users | 3,088 unfiltered | **Yes** — server q + source/active (spec 84, debounced) | No — unfiltered query renders all 3,088 rows (API: q but no limit/offset) | MAJOR |
| Settings → Groups | `web/src/routes/settings/groups.tsx:51` | mirrored AD groups | hundreds at a real AD | No | No (API: none) | MAJOR |
| Settings → Releases (per project) | `web/src/routes/settings/releases.tsx:65` | releases | hundreds (years of Jira versions) | No | No (API: none) | MAJOR |
| Settings → Audit log | `web/src/routes/settings/audit.tsx:53,94` | audit entries | unbounded | Partial — entity-type select only, no text q | No — fixed `AUDIT_LIMIT = 200`; **server already has limit+offset** (`server/src/radd/modules/audit/router.py:28`) | MAJOR |
| Wiki space page tree | `web/src/components/pages/PageTree.tsx:143` via `web/src/routes/page-space.tsx:38` | pages of a space | thousands per space | No in-tree filter (global `/pages/search` exists, q+limit) | No — full space fetched | MAJOR |
| Jira import mapping tables | `web/src/components/settings/jira/FieldsTable.tsx:88-103`, `VocabTables.tsx:39-46`, `UsersTable.tsx:198-205` | 337 fields / 83 statuses / 61 types / unmatched users | hundreds per band | No text filter — only the used/unused collapse (`MappingSection.tsx`) | No | MAJOR |
| Sidebar projects section | `web/src/components/shell/Sidebar.tsx:432` (+ views 478, dashboards 285, spaces 370) | projects + nested views | 82 projects × ~3 views | No | No | MAJOR |
| Project access → members list | `web/src/routes/settings/projects.tsx:136` | project members | dozens–hundreds | No | No | MINOR |
| Settings → Link types | `web/src/routes/settings/link-types.tsx:89` | link types | dozens | No | No (API: none) | MINOR |
| Settings → States (per project) | `web/src/routes/settings/states.tsx:72` | workflow states | ~5-20/project (107 names instance-wide) | No | No | MINOR |
| Settings → Issue types (per project) | `web/src/routes/settings/issue-types.tsx:62` | issue types | handful/project (61 names) | No | No | MINOR |
| Settings → Screens | `web/src/routes/settings/screens.tsx:91,187` | types + field rows | dozens | No | No | MINOR |
| Settings → Roles | `web/src/routes/settings/roles.tsx:58` | roles | dozens | No | No | MINOR |
| Settings → Automations | `web/src/routes/settings/automations.tsx:67` | rules | dozens–low hundreds | No | No | MINOR |
| Settings → Canned responses | `web/src/routes/settings/canned.tsx:50` | canned responses | dozens | No | No | MINOR |
| Settings → Forms (per project) | `web/src/routes/settings/forms.tsx:77` | intake forms | dozens | No | No | MINOR |
| Settings → Forgejo repos | `web/src/routes/settings/forgejo.tsx:186` | repos per connection | dozens–hundreds at a real forge | No | No | MINOR |
| Settings → Backups | `web/src/routes/settings/backups.tsx:470` | backups | grows daily, hundreds/yr | No | No | MINOR |
| Settings → Service accounts | `web/src/routes/settings/service-accounts.tsx:82` | accounts+keys | dozens | No | No | MINOR |
| Settings → User duplicates | `web/src/components/settings/UserDuplicates.tsx:47` | duplicate groups | dozens–hundreds at 3k users | No | No | MINOR |
| Settings → Leave/Holidays | `web/src/components/settings/LeaveSections.tsx:74` | leave periods | dozens | No | No | MINOR |
| Projects index | `web/src/routes/projects-index.tsx:59` | projects | 82 | No | No (API: none) | MINOR |
| Pages index (spaces) | `web/src/routes/pages-index.tsx:58` | wiki spaces | dozens | No | No | MINOR |
| Inbox | `web/src/routes/inbox.tsx:74` | notifications | capped at 100 | Unread toggle only, no q | No pager — **server has limit+offset (≤200)**, older 100+ unreachable | MINOR |
| Jira import run problems | `web/src/components/settings/jira/ProblemList.tsx` | import problems | hundreds | Grouped by mapping, no q | No | MINOR |
| AI providers/roles/presets, Storage hosts/rules, SSO providers, Plugins, Monitoring, Tokens | `web/src/components/settings/Ai*.tsx`, `storage/*`, `signin/*`, `routes/settings/plugins.tsx`, `monitoring.tsx`, `TokensPanel.tsx` | config rows | <20 each | No (not needed) | n/a | OK |
| Item lists/boards/swimlanes, My Work, cycle page, dashboards, reports, timesheet grid | `web/src/routes/view.tsx:1215` etc. | items/worklogs | 503k | **Yes — SLQ bars** | **Yes — `Pager`** | OK (healthy) |
| Settings → Cycles | `web/src/routes/settings/cycles.tsx:50-115` | cycles | 90+ | **Yes** — client name filter + completed fold | No (fine) | OK — **the model to copy** |

## Pickers without real search

The kit `Select` (`web/src/components/Select.tsx:65`) does *jump* type-ahead — printable characters move the highlight to the first label match — it never filters the panel. `SelectField` funnels `<option>` children into it. Over ~1,000 rows that is effectively no search.

**CRITICAL — full user directory (~1,031 active options, 3,088 fetched via `usersQuery` → `GET /users/directory`, which takes no `q`):**

| Picker | File |
|---|---|
| Assignee + Reporter, issue rail | `web/src/components/items/IssueProperties.tsx:529-560` |
| Assignee, New Item modal | `web/src/components/items/NewItemModal.tsx:329-341` |
| Assign-to, bulk action bar | `web/src/components/views/BulkActionBar.tsx:206-215` |
| Person filter, timesheet | `web/src/routes/timesheet.tsx:263-281` |
| "Add member", project access | `web/src/routes/settings/projects.tsx:169-181` |
| "Add member", team panel | `web/src/components/settings/TeamPanel.tsx:200-212` |
| Per-row "Pick a user…" + "Attribute all unmatched to…", Jira import | `web/src/components/settings/jira/UsersTable.tsx:85-97, 152-165` |

**MAJOR — hundreds of options:** cycle picker (all cycles instance-wide, 90+) and release picker in `web/src/components/items/PlanningFields.tsx:66-79, 120-133` and in `NewItemModal.tsx:59-62`; project (82) + view (~250) selects in `web/src/components/dashboards/WidgetModal.tsx:227+`; registry-field select (319) in `web/src/components/forms/FormFieldsPicker.tsx:130-140`; project selects in `service-accounts.tsx:286`, `forgejo.tsx:205`, timesheet `:249`; select-type custom fields render `field.options` (can be hundreds — spec-100 `extend_options` feeds them) in `web/src/components/items/CustomFieldsForm.tsx:80-92`.

**Already good (prior art):** `TokenMultiSelect` (filtering combobox — though it renders *all* matches unsliced: 2,016 label options mount 2k DOM rows, `TokenMultiSelect.tsx:70-72`); `SubjectPicker` (filters, caps at 12 rows); NewItemModal parent search (server-backed); `DependenciesSection`, `ItemPagesSection`, `UnscheduledTray`, card-designer `AttrPalette`, mention autocomplete, directory import dialogs (server-backed `q`).

**Adjacent finding:** a *user-type* custom field is a raw "User id" text input — no picker at all (`CustomFieldsForm.tsx:144-150`).

## Recommended systemic fix

One fix per layer, not per page. Existing machinery to build on: `useDebounced` (`web/src/lib/hooks.ts:346`) + `SEARCH_DEBOUNCE_MS`, `Pager`, `TokenMultiSelect`'s filter loop, `SubjectPicker`'s cap-at-12 shape, and the two pages that already did it right (cycles = client filter, users = server `q`).

1. **`Select` grows a `searchable` mode — this is the single highest-leverage change.** A filter input pinned at the top of the existing panel, filtering `options` via the `labelText` helper that already exists for type-ahead, rendered rows capped (~200 + "keep typing — N more"). Auto-enable when `options.length > ~15` so **every `SelectField` call site inherits it with zero edits** — all 7 CRITICAL pickers and every MAJOR picker die in one commit. Add the same match-cap to `TokenMultiSelect` (slice visible matches ~50).

2. **`useListFilter(rows, keys)` + a small `ListSearchInput`** for settings lists — extract the cycles-page pattern (`cycles.tsx:50-66`, including its "filtering opens the collapsed fold" behavior, which the Jira mapping bands need verbatim). Client-side is correct here: every one of these pages already fetches the full list, so <~2,500 rows filter instantly with no API change. Roll out to: Teams, Labels, Fields rail, Groups, Releases, Link types, Automations, Canned, Forgejo repos, Backups, projects-index, Sidebar projects section, Jira mapping bands, and PageTree (match + keep-ancestors expansion).

3. **Server-backed search where the *fetch* is the problem**, second wave — client filtering fixes findability but a 2,293-row `/teams` payload is the real risk at 10×. Endpoints that already accept a query: `/users` (`q`+`source`+`active` — but **no limit/offset**), `/audit` (**limit+offset already, no `q`**), `/pages/search`, LDAP directory search, `/notifications` (limit+offset), `/items` (SLQ, paged). Endpoints needing `q` (+ `limit`/`offset`, `{rows,total}` shape — no-backcompat rule applies): `/teams`, `/labels`, `/fields`, `/groups`, `/users/directory`, `/views`, `/cycles`, `/projects`, `/projects/{id}/releases`, `/page-spaces/{id}/pages`. When `usersQuery` exceeds a threshold, the searchable `Select` flips from client filtering to the server `q` — same component, same call sites.

**Rollout order:** (1) searchable `Select`/`SelectField` — kills the whole CRITICAL picker class; (2) `useListFilter` on Teams, Labels, Fields; (3) MAJOR: audit `q` + `Pager` (server is already able), users-table pagination, Groups, Releases, PageTree filter, Jira bands, Sidebar project filter; (4) MINOR pages opportunistically as they're touched. Worth filing as one epic with those four child issues — steps 1 and 2 are each one meaningful unit.
