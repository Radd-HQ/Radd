# Radd deep-scan audit — 2026-08-05

> **Historical snapshot.** This audit describes the tree as of 2026-08-05;
> it is preserved because publishing self-criticism keeps it honest, and many
> findings drove the RADD-8xx/10xx fix waves. Check the tracker before trusting
> any individual claim — a good number of them have since been fixed.

Nine parallel full-codebase audits (~76k lines Python / ~78k lines TypeScript), each saved as a
category report in this directory. Every finding carries `file:line`, evidence, and a concrete fix;
each report ends with the systemic (whole-class) remedies.

| # | Report | Headline |
|---|---|---|
| 01 | [Architecture: kernel/plugin violations](01-architecture-kernel-plugin.md) | 78 non-spine cross-module model imports, 30/53 modules with undeclared deps, 4+ import cycles, 4 kernel registries with exactly one client each |
| 02 | [Backend bad practices](02-bad-practices-backend.md) | Middleware buffers whole responses in RAM; `_rebalance_ranks` = 503k UPDATEs in one request; silent `except` on plugin boot state; enum bypasses |
| 03 | [Frontend bad practices](03-bad-practices-frontend.md) | The issue-rail state chip ships a drifted second copy of the workflow palette (In Progress = yellow); charts still draw the retired indigo accent; 46 hand-rolled buttons |
| 04 | [Misleading docs & comments](04-misleading-docs-comments.md) | ~50 verified contradictions: `merge_users` docstring promises an audit shell but the code hard-deletes; CLAUDE.md preamble is 12 releases stale; `/health` doesn't exist |
| 05 | [Dead code — backend](05-dead-code-backend.md) / [frontend](05-dead-code-frontend.md) | ~1,100 backend + ~660 frontend deletable lines; the grant-expiry sweep NEVER RUNS (TaskSpec registry has zero readers); live 404 on the issue page's linked-pages section |
| 06 | [Backcompat hacks](06-backcompat-hacks.md) | 19 live compat mechanisms + 4 dead aliases, all violating the no-backcompat-until-V1 rule; removal cost stated per finding |
| 07 | [Missing features](07-missing-features.md) | Top gaps: responsive shell (zero breakpoints), Slack connector, list filters, comment threads/reactions, AI-triage automations, security bundle |
| 08 | [List search filters](08-list-search-filters.md) | 47 surfaces audited, 27 without any filter; ONE `Select` change kills the whole 1,031-option-picker class |

**Caveats.** Each report is one agent's sweep, agent-verified against the tree; two contradictions
between reports were re-checked by hand (`/health` does not exist — report 05-backend carries the
correction; docs/modules.md module count differs by whether `__init__.py`-only dirs are counted).
Before acting on any CERTAIN-dead deletion, the build + test suite is the regression check the
reports themselves prescribe.

---

## What the scan actually says (three sentences)

The module system is real — all 53 modules load through the kernel, the frontend plugin host is
clean, function-level dead code is rare, type safety is exemplary — but **the kernel's contribution
registries were built and then not adopted by the core** (permissions, settings keys, MCP tools,
SLQ builtins each have exactly one client), so the platform's own modules still couple by direct
model imports, 30 of them with undeclared dependencies. The debt is concentrated in **seams that
were half-migrated by a spec wave and never swept** (spec-90/100 wizard leftovers, RADD-828
remnants, spec-92 doc drift, pre-Dusk chart hexes), plus a handful of **genuine runtime bugs the
scan surfaced on the way** (list below). Feature-wise the tracker is deep, but it is missing the
things an evaluator hits in the first hour: a phone-usable shell, Slack, and — your observation,
confirmed at 27 of 47 surfaces — the ability to type into a long list.

## Bugs found by the scan (fix regardless of any plan)

1. **Issue page linked-pages section 404s today** — SPA builds `/items/{id}/docs`, route is
   `/items/{id}/pages` (`web/src/lib/constants/api-paths.ts:195` vs `pages/router.py:463`).
2. **`access.sweep_expired_grants` never executes** — the only `TaskSpec` in the codebase is
   registered into a registry nothing reads; expired grant rows accumulate forever.
3. **Plugin enable/disable state silently discarded on any boot DB error** —
   `pluginmgr/boot.py:33` `except Exception: return {}` (the exact bug class RADD already shipped once).
4. **`group.synced` is a phantom automation trigger** — offered in the catalog, never emitted.
5. **State chip palette drift** — `IssueProperties.tsx:22-35` paints In Progress yellow / Done green,
   contradicting `--chart-*` everywhere else, in both themes.
6. **Wasted authz query per keystroke-path call** — dead `effective_permissions` result in
   `fields/router.py:137` (hot `/fields/writable` path).
7. **Backup download buffers the whole artifact in RAM** — `middleware.py:29-53` buffers every
   non-SSE response; a multi-GB backup download is held in a Python list.
8. **Drag-to-rank can issue 503k UPDATEs in one transaction** — `items/service/queries.py:289`,
   instance-wide, inside a user request.
9. **Diff-review CSS classes don't match the classes the plugin emits** — deletions render
   unstyled (`editor.css:184-194` vs `diff/decoration-plugin.ts:239+`).
10. **Vacuous proof** — `page-print-proof.mjs:136` asserts on a selector that exists nowhere.

---

## The plan

Phased so each phase is one epic in RADD with child issues, each child = one commit. Phases 1-3 are
where I'd start; 4-6 are steady-state burn-down; 7 is roadmap. Within every phase the systemic fix
lands **before** the per-site cleanups it obsoletes.

### Phase 1 — Bug wave (small, immediate)
The ten bugs above. Two afternoons of work, all independently shippable, no design decisions.
The middleware fix (#7) and rank rebalance (#8) want the perf-seed DB as their proof.

### Phase 2 — Findability: the list-filter epic *(your named priority)*
Per report 08, one epic, four children, in this order:
1. **`Select` grows a `searchable` mode** (filter input in the panel, auto-on above ~15 options,
   row cap + "keep typing") — every `SelectField` call site inherits it with zero edits; kills all
   7 CRITICAL user-pickers and every MAJOR picker in one commit. Cap `TokenMultiSelect` matches too.
2. **`useListFilter` + `ListSearchInput`** extracted from the cycles page; roll out to Teams (2,293
   rows), Labels (2,016), Fields rail (319), Groups, Releases, Jira mapping bands, PageTree, Sidebar.
3. **Server-backed `q`/`limit`/`offset`** on `/teams`, `/labels`, `/fields`, `/groups`,
   `/users/directory`, `/projects`, releases, space pages (no-backcompat: change response shape to
   `{rows,total}` outright); flip the searchable Select to server mode above a threshold.
4. **Wire what the server already supports**: audit log `q`+Pager (limit/offset exist), Users page
   pagination, Inbox pager.

### Phase 3 — Architecture ratchet (stop the bleeding, then drain)
Per report 01, the order matters — the test comes first so the class can't regrow:
1. **Decide the real spine** (recommended: add read-only `WorkItem`, `State`, `Team`, plus the
   `events.Event` payload re-exported from `events.service`; everything else off-limits), write it
   into CLAUDE.md rule 1.
2. **One CI test, two assertions** (AST-walk, `test_route_shadowing.py` style): (a) no `X.models`
   import outside the blessed set, (b) every `radd.modules.X` import appears in `depends_on` (add
   `weak_depends` to `RaddPlugin` for feature-detected reverse edges). Green it by fixing the
   mechanical cases (Event re-export = 13 sites in one move; declared-deps table).
3. **Finish the four registry migrations** the kernel already shipped, using `milestones` as the
   template: permission atoms on `RaddPlugin` (kill the central `Permission` enum), `SettingSpec`
   contributions (kill `SettingKey`), MCP tools into owner modules (delete `pages_bridge.py`),
   SLQ builtins (`cycle`/`release`/`type`/`team`/`state`) into owner `SlqFieldSpec`s.
4. **Invert auth's feature knowledge** — one `fact_provider` socket for nav-facts / scope labels /
   subjects; kernel sockets for `kernel/entities.py`'s auth/projects/events needs; `project_purge`
   hook replacing `jiraimport/rollback.py`'s table list.
5. Burn down the remaining §3 model-import list to green (access read seams, groups service writes
   for ldap sync, forms portal reads, etc.).

### Phase 4 — Deletion wave (dead code + backcompat, one sweep)
Reports 05×2 + 06 are effectively one epic: **~1,800 lines + 5 assets + 2-3 drop migrations.**
- Backend: RADD-828 cluster (incl. `Form.public_token` drop), spec-90 wizard schemas + `ImportStage`,
  never-wired kernel machinery (`ConsumerSpec`, `automation_actions/conditions`, `settings_keys`,
  `register_cascade`, … 
  — deciding TaskSpec's fate belongs to bug #2), 12 CERTAIN-dead routes, sso identity surface,
  39 import lines, `jira_page_size`.
- Frontend: the query-factory/api-path chain, meta.ts constants, 16 dead types, dead diff CSS,
  brand SVGs; a conscious decision on the 8 legacy redirect routes (recommend: delete `/docs`,
  members, leave; keep `/kb` until V1 since the instance is public).
- Backcompat: all 19 mechanisms from report 06 — attachments alias routes, Forgejo env fallback
  (+ its capability check), `UserSource.UNKNOWN` one-shot migration, dual-shape parsers
  (`shared`, `role`, `project_id`), wire mirrors (`item_id` on attachments/comments), frontend
  pre-101 tolerance, `teams.owner_id` backfill, storage `root_dir` validator. Also **rename** the
  live-but-mislabeled paths ("LEGACY owner-less views" is load-bearing; the label invites deletion).
- Decide-clusters flagged, not deleted: page-templates API family (only server-side consumer),
  webhooks CRUD (API-only surface with no UI — keep documented or build the settings page),
  plugin install/uninstall endpoints.

### Phase 5 — Docs truth pass
Report 04's triage order: (1) the two security-relevant lies (`merge_users`/`delete_user`
docstrings, service-accounts comment — or make the comment true by badging SERVICE accounts in the
directory); (2) CLAUDE.md preamble rewrite + the broken `--workspace` command in two places + the
`/health` sentence (or build `/health` — the Helm probe would rather have it); (3) docs/modules.md
refresh (3 missing module rows, wrong workflow event names, depends cells) folded into Phase 3's
`depends_on` fixes so doc and code change together; (4) endpoint descriptions, contributing.md's
stale known-failure paragraph, plugin-platform.md banner, PLAN.md date-stamps.

### Phase 6 — Hygiene ratchets + kit growth
- **Backend**: one `radd.clock.utcnow()` (kills 30 copies); tunables sweep into `config.py`
  (timeouts, batch sizes, `db_pool_*`); enum-literal CI check; ruff `BLE001`/`S110`/`S112` on
  repo-wide (no catch without a logger); `Snapshot[T]` TTL helper for the four module-level caches;
  split `authz.py`/`auth/service.py` along their own section markers.
- **Frontend**: semantic status tier (`--color-danger/-warning/-success`) + charts consume
  `var(--chart-*)`/`var(--accent-fill)` (fixes every theme-blind hex as a class); kit grows
  `IconButton` (34 copies), `ErrorText` (109), `Callout` (9), `Popover`; `useKeyedRows` for the 8
  index-keyed builders; focus trap in `Modal`; rebuild `SubjectPicker` on the combobox mechanics;
  extend the zero-zinc grep to hex-in-tsx and unmapped shades.

### Phase 7 — Product gaps (roadmap, needs your prioritization)
Report 07's top 10 by adoption impact. My recommendation for the first three slots, given the
public-demo goal: **(1) responsive shell pass** (the collapsible rail is halfway there; zero
breakpoints today), **(2) Slack connector** (clone the proven googlechat shape), **(3) comment
threads + reactions** (most visible daily-use gap; `reply_to_id` + a reactions table). Close behind:
the AI-triage automation action (`complete_choice` makes it small and it defends the "AI-native"
positioning), the security bundle (sessions UI + login audit events + rate limiting — three small
changes that jointly pass a security review), and open-duplicate detection at creation (the
`/ai/similar` seam already exists). Phase 2 already covers gap #3 (list filters).

---

## Suggested tracker mapping

Per the working agreement (file before building): one epic per phase, children as above — Phase 1's
ten bugs are ten small issues; Phase 2 is the epic with four children from report 08; Phase 3's
ratchet test is its own issue (it's the deliverable that closes the class); Phase 4 is one epic
with the four sweep commits from the dead-code reports as children. Reports 01-08 can be attached
to the epics as the evidence base.
