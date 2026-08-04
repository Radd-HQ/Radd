# The corrected execution plan — A→Z, one release

Supersedes the order table in `115-execution-prompt.md`. Everything else in
that brief (definition of done, verification bar, tracking, releasing, the
nine traps) still governs; trap amendments are at the end. All 22 filed
issues remain; **four new issues get filed** (marked NEW) and **five get
edited before any code is written** (step 0).

## Step 0 — fix the tracker so the handoff is self-consistent

The tracker is the record an executor reads; today it contradicts the plan
in five places. Half a day, zero code.

1. **RADD-834 — rewrite.** The hole is `bulk_move_items`, not bulk edit
   (`01-corrections.md` §1). Scope: field grants + workflow guards +
   approval consumption in `_move_one`, by re-entering the service path,
   never by a parallel copy. Add `estimate_points` to
   `_BUILTIN_FIELD_MAP`, and a regression guard for the archived/rank
   near-miss. H2 (history) stays in this issue as filed.
2. **RADD-828 — rewrite** to match D9 (public pages + CSAT stay; the
   Done-when currently strips them) and to the Q1 answer (Requester role,
   not Baseline).
3. **RADD-823 — comment** stating D13 is decided (`item.team_id`) and the
   `@relation` syntax is normative (the issue's existing comment calls it
   still-open).
4. **RADD-813 — comment** stating Groups IS in this release (the epic's
   plan-complete comment says the opposite; the amended brief is the later
   word). Reparent **RADD-810** into the epic so the release sweep closes
   it.
5. **File the NEW issues** (below): N-leaks, search-grants, search-index
   schema, per-item writability, nav gating (`05-nav-gating.md`). Check
   RADD-822's In-Progress state is real, else back to Todo.

## The order

Rationale unchanged where unannotated. **⚠ = scope amended here.**

| # | Issue | What changed in review |
|---|---|---|
| 1 | **RADD-834** ⚠ | Re-pointed at bulk move; + guards + approvals + estimate_points (step 0 rewrite). Live holes fix first, unchanged reasoning. |
| 2 | **NEW-A: five cross-project read leaks** | Timesheet actor filter (N1), link/parent/epic/child-count hydration (N2), SLQ key autocomplete (N3), rollup descendants (N4) — all `readable_projects`-level, no relations needed. Do now because they are live AND because they build the exact plumbing relations reuse: `hydrate()` gains an actor, `timesheet.build()` gains an actor. N5 (Baseline `page.read` defeats restricted spaces) is *documented* here and resolved at step 27 by the Q2 Baseline flip. |
| 3 | **NEW-B: search stops leaking restricted text** | The corrected H3: read-restricted `description` out of snippets/similar/embeddings (conservative indexing — restricted content indexes for nobody, the "public text only by construction" precedent); SLQ compiler refuses filter/sort on fields the actor can't read (closes the bisection oracle incl. `/items/count`, `/items/ids`). Independent of relations; do early. |
| 4 | **RADD-809 — inspector** ⚠ | + space scope (`permission_sources` takes project only — no `page.*` atom is explainable today) and the UI passes it; + resource grants, Team view, backlinks as filed; + "held by default-open vs granted" distinction. Trim §5.6's "effective answers" to counts — guard-level conclusions ("cannot transition FOO-*") are workflow-data-dependent and out of scope. 833 extends it later; build the provenance rows to be extended. |
| 5 | **RADD-836 (U1 only) — View as** | Unchanged: read-only server-side impersonation, admin-only, audited. The wave's verification tool; everything after this is checked through it. |
| 6 | **RADD-824 (bug half)** ⚠ | Client gates view.manage → view.create; ALSO the second step found in review: personal views need only `item.read` server-side (`PERSONAL_VIEW_PERMISSION`), so the button logic distinguishes personal from broadcast. |
| 7 | **RADD-814 — scope on the grant** ⚠ | As designed (checkable_at + ladder + one `holds()` seam + one client `can()`). Add cleanups found: retire `PermissionScope.INSTANCE` (zero atoms) or give it atoms, delete dead `ALL_PERMISSIONS`, memoise the `require_anywhere` path (7 unmemoised O(all-projects) sites). Migration surface measured: 192 require sites, 19 with computed atoms — those 19 get hand-checked. |
| 8 | **RADD-810** | Resolved in 814's terms, as briefed. |
| 9 | **RADD-829 — groups entity + migration** ⚠ | No-backcompat simplifications: surrogate-PK rewrite of `team_members` without preserving `MemberSource` (it retires — a fifth retirement); mixed manual/directory rows resolved crudely (directory rows die, the group carries the membership); `TeamChange` directory event values retire with no alias; `directory_sync_state` payload changes shape. Name collisions between groups and teams: groups get their own namespace + DN uniqueness. |
| 10 | **RADD-830 — subject graph** ⚠ | ORDER WITHIN THE STEP: (a) memoise today's `user_team_ids` on `session.info` FIRST — it's already called twice per batched resolution; (b) then swap the memoised body for the recursive CTE (cycle guard + depth limit, **fail closed**, cyclic fixture in tests); (c) `SubjectContext.group_ids` as a REQUIRED field — six construction sites break loudly. Perf gate: list hydration + MCP `require_anywhere(refuse_when_empty=True)` measured against the 503k dev DB before/after. |
| 11 | **RADD-831 — LDAP syncs groups** ⚠ | New requirement made explicit: today's sync resolves members transitively (`LDAP_MATCHING_RULE_IN_CHAIN`) and throws the structure away — it must now ALSO fetch group→group edges. The `directory_missing_since` two-path invariant (periodic loop refuses removals; login path skips removals) moves to groups **plus the new case**: a missing parent in a nested chain must not read as "children have no parent". Login-time sync answers a different LDAP question than edge-walking — decide per-user probe vs graph lookup here. |
| 12 | **RADD-832 — groups as grant subjects** ⚠ | Scope per Q3: the two grant tables (`global_role_grants.group_id` — XOR becomes exactly-one-of-three — and `access_grants` GROUP subject + `_validate_subject` + `subject_referenced` deletion guard). All other team-subject tables stay team-only, documented. + The reverse-CTE headcount endpoint (batched; the grant UI's "resolves to N people" and U4 both ride it). |
| 13 | **NEW-C: `search_index` carries relation columns** | Prerequisite for relations reaching search: add `reporter_id`/`assignee_id`/`team_id` to `search_index`, indexer writes them and re-indexes on their change (it currently only reacts to item/comment events — the trigger set widens). Decision recorded: columns, not per-query `work_items` joins — FTS and the vector pool query the index without joining, and deflect's join stays its own path. Schema change, own ticket, before 823. |
| 14 | **RADD-823 — relations kernel** ⚠ | As designed, plus the review's structural findings: (a) **the item-resolution seam does not exist and is created here** — `items.service.require_readable_item(...) → (item, project, perms)`; the ~15 inline `require_item`+`require` copies convert (list in `01-corrections` agent seam inventory: history, worklogs, watchers, participants, weblinks, vcs, sla, csat, approvals, transitions, canned, mailintake, pages-links, stars, item-links); the comments/attachments parent registries are the free win; (b) `forms/requests.visible_condition` absorbed into the registry as the first relation, not left as a copy; (c) the normative resolution-semantics table (ladder × lattice × effect × field grants) lands in the spec with a property test — before deny exists, so deny slots in; (d) spec-113 note: the token-scope intersection becomes lattice-aware (`item.read` key ∩ `item.read@team` account = `@team`). |
| 15 | **RADD-817 — items adopt relations** ⚠ | The three shared builders are one edit each (`listing.py:83`, `bulk.py:308`, `read.py:84` — carries lists/boards/reports/counts/MCP). Then the independents, by name: `views/counts.py:77` (sidebar badges), rollup, link typeahead (`links.py:59`), suggest_values, deflect, semantic pool (`ai/service.py:393`), kernel entity CRUD hook (`kernel/entities.py:223` — per-row today, needs a query hook for plugin relations). Notifications: thread the item into `notify/consumer._allowed` (`:269`) — the single delivery choke point; `_handle_item_event` currently never loads the row. |
| 16 | **NEW-D: per-item writability for the SPA** | The spec-96 contract (`readonly_field_keys` is item-independent) breaks under relations + D10. Item payload (or a `/items/{id}/capabilities` endpoint) carries the actor's per-row verdict; `useItemWritability`, BulkActionBar, quick-actions consume it. Without this the wave reintroduces edit-then-error. |
| 16b | **NEW-E: nav shows only what is useful** (`05-nav-gating.md`) | One `useNavFacts()` predicate source shared by Sidebar, the collapsed rail (which today gates NOTHING), the palette Goto rows and link pins; two server booleans (`timesheet`, `portal`) join the bootstrap payload, everything else derives from lists the shell already loads. Fixed destinations (Timesheet/Reports/Portal/Projects), the Dashboards section and "New dashboard" gain gates; plugin-nav `requires` moves onto `can()`. Must land before RADD-828 — a requester account is the acid test. |
| 17 | **RADD-816 + rest of RADD-824 — verbs + manage** ⚠ | Syntax is `@own`, not `.own` (§5.2 read with substitution). Start from **11** dead atoms, not 9: `attachment.delete` has no behaviour to preserve (delete-own actually rides `attachment.create`), `service_account.delete` has no route. The issue carries a per-atom disposition table (stored-atom stays / demoted to UI affordance / deleted), written before code. `global.manage` is not treated as an umbrella (it isn't one). Author-own hardcoded rights → seeded `@own` grants per Q4. One destructive rename migration (roles + token scopes + access_grants), no ceremony (no-backcompat). |
| 18 | **RADD-819 — deny** | Slots into the semantics table written at step 14. Inert until a row is written, as designed. |
| 19 | **RADD-822 — field scope vs grants wording** | As filed; + say restriction-scoping only exists for fields (2 of 6 resources, `01-corrections` §3). |
| 20 | **RADD-818 — plugin parity + uninstall sweep** ⚠ | Kernel `access_resources` registry (the SDK function exists; make it declarative), **withdraw-on-disable** (today a dead plugin's ResourceSpec and grants stay live), uninstall sweep covers roles + `api_tokens.scopes` + access_grants, and the framework owns orphan-grant GC (`clear_resource` today is adopter-goodwill). Contract test extends to plugin scopes. |
| 21 | **RADD-826 — project admins assign roles** | D14 intersection is scope-aware ("holds at the scope of the grant being made"). |
| 22 | **RADD-833 — groups admin + inspector path** | As briefed (needs 830's transitive resolution + 809's provenance rows). |
| 23 | **RADD-815 — matrix by resource, presets + sentence builder** | As briefed; model is final by now. |
| 24 | **RADD-836 (rest) — audience indicator, refusal page, impact preview** | All resolvers exist by now; U4's headcount rides step 12's endpoint. |
| 25 | **RADD-835 — the sweep** ⚠ | The checklist is replaced by the review's seam inventory: verify the three builders + created seam cover what they claim, then walk the independents (§B list) and the write paths (agent 3's S2 table: MCP, automations-as-SYSTEM noted as designed, importer, forms, connectors). Downgrades applied: realtime is a stated coarse side-channel (payload-free), webhooks a documented SYSTEM bypass, notification inbox rows and presigned URLs stated freeze-at-delivery properties. Pages export walks the subtree after one gate — page relations must be checked here. Proof harness: extend `restricted-access-proof.mjs` family with a relation-restricted actor; every claim proven to FAIL pre-change once. |
| 26 | **RADD-828 — requesters** ⚠ | Per rewrite + Q1: `UserSource.EMAIL`, `create_session` refuses, Requester role seeded with the Q1 shape, spec-110 email matching so a later SSO login joins the account. `/public/forms` + portal machinery removed; `/public/pages` + `/public/csat` STAY. |
| 27 | **RADD-825 — Baseline pre-flight + the flip** ⚠ | The report as designed (both atoms). **Per Q2: the release flips the row** — the migration narrows the Baseline to `item.read@own`, drops `page.read`, and seeds one instance-wide staff role restoring today's effective access for existing active users; fresh-instance seed is `item.read@own`. The pre-flight report is run against the live DB before tagging. This supersedes the brief's "must NOT ship flipped" section, and it is what finally fixes N5 (restricted spaces). |
| 28 | **RADD-820 — expiry + granted-by** | As filed. Smallest, last. |

## Dependency spine (what truly blocks what)

```
834, NEW-A, NEW-B, 824-bug        — independent, any order, all before the model work
809 → 836-U1                       — observability before every model change
814 → 810                          — the root cause, then its client casualties
829 → 830 → {831, 832}             — groups; 830 is the keystone
NEW-C → 823 → 817 → NEW-D → NEW-E  — search schema, relations, adoption, then the SPA pair
{814, NEW-E} → 828                 — requesters land in a nav that already hides what they lack
{823, 809} → 816/824-model → 819   — verbs need the syntax + inspector; deny needs the semantics table
{814, 816} → 818                   — plugin parity needs settled vocabulary
830 → {826-D14, 833, 836-U4}       — everything reading the subject graph
everything → 835                   — the sweep verifies the wave
{823-relations} → 828 → 825        — requesters need @own enforced; the Baseline act comes last
```

## Trap amendments (extends the brief's nine)

10. **The seam you were told to use must be built first.** There is no
    item-resolution seam today — 15 endpoints have inline copies. Creating
    `require_readable_item` and converting them IS step 14a, before any
    relation is enforced anywhere.
11. **`SubjectContext` is the silent-failure shape.** Required field, not
    defaulted — a missed construction site must fail to compile, because at
    runtime it fails as a quiet denial.
12. **Fix leaks at the query, never the serializer** —
    `forms/requests.py:11-32` already states why; N1–N4 are all
    query-level fixes.
13. **The SLQ compiler is part of the access surface.** It reads field
    definitions with no grant context; anything it will filter or sort by
    is disclosable by bisection. Grant checks live at compile time.
14. **19 `require()` sites pass computed atoms** — the 814 migration
    cannot be a pure mechanical rewrite; those get eyes.

## Release

Per the brief (minor version, image tag, CD, sweep). Release notes carry,
beyond the brief's three bullets: the five leak fixes (N1–N4 + search), the
bulk-move guard fix, and — per no-backcompat — a plain list of what was
dropped without aliases (TeamChange directory events, MemberSource,
`/public/forms`, the renamed atoms).
