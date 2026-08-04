# Corrections to the spec-115 audit

Everything below was verified against the working tree at commit `2a506fb`.
Format: what the audit says → what the code says. Sections the audit got
fully right are listed once at the end.

## 1. The three "confirmed holes" — one wrong endpoint, one wrong field class

### H1 is bulk MOVE, not bulk edit — and it skips more than field grants

The audit cites `items/bulk.py:277` as bulk *edit* skipping field grants.
That line is in `bulk_move_items`. The two paths differ completely:

- **Bulk edit is clean.** `_apply_one` (`bulk.py:85-99`) forwards every
  patch through `update_item`, which runs `_check_builtin_field_rules`,
  `_field_ctx`, `writable_check` AND `workflow.check_transition`
  (`items/service/core.py:147-218`). A field-restricted user gets a
  `FORBIDDEN` skip row. Bulk edit cannot touch custom fields at all.
- **Bulk move is the hole, three times over.** `_move_one`
  (`bulk.py:161-244`) mutates ORM objects directly: `state_id` (`:196`),
  `type_id`/`release_id` (`:201-204`), `custom_fields` (`:208-210`). Its
  only gate is `ITEM_UPDATE` (`:277`). It skips **(a)** builtin/custom
  field grants, **(b)** workflow-transition guards — `check_transition`
  has exactly ONE call site in the server (`core.py:218`) and this path
  isn't it — and **(c)** approval consumption (`core.py:230-238`). A user
  who can't move an item to Done directly can bulk-move it onto a
  DONE-category state in another project, guard never fired, approval
  never spent.

**RADD-834 must be re-pointed at `bulk_move_items` and widened to guards +
approvals.** Suggested fix shape: `_move_one` re-enters the service path
(or calls the same three checks) rather than growing a parallel copy —
a parallel copy is the defect class this whole wave exists to remove.

### H2 confirmed exactly; the realtime half of the worry is unfounded

`items/history.py:116` passes `payload["changes"]` verbatim into
`HistoryEntry`; the only filter in the file is internal-comments (`:105-114`)
and the only permission read is `ITEM_READ` (`:82`). The event payload is
unfiltered *by documented design* (`items/service/read.py:41-44, 61-70`:
"stream consumers are trusted; only API responses are filtered per-actor")
— history is an API response that forgot it isn't a stream consumer.
`changes.py` emits old→new for 10 of the 11 read-restrictable builtins and
every custom field **with display names**.

Not leaks: realtime WS frames are payload-free
(`realtime/broadcaster.py:23-28` — `{"entity", "event_type"}` only), and
the audit log's rendering of `changes` is gated on `GLOBAL_MANAGE`
(`audit/service.py:30`).

### H3 is wrong about custom fields, live for `description`, and hides a second oracle

Custom fields **never reach the search index**: `search_index` has four
text columns (`search/models.py:19-30`), the indexer writes only those
(`indexer.py:81-87`), and the `FieldDefinition.indexed` flag is dead code
(`fields/models.py:37`; `items/listing.py:5` says so).

What IS live:

- **`description` is read-restrictable** (`fields/types.py:80-85` excludes
  only title/state/priority) **and searchable**: `/search` builds a
  `ts_headline` over `description || comments_text` and returns it as the
  snippet (`search/service.py:122-127`); `similar_to_text` returns
  `row.description[:240]` raw (`:266`); the restricted text also goes to
  the embedding provider. The only scoping anywhere in the search module is
  project-level (`_scope`, `:87`).
- **SLQ is a value oracle for read-restricted fields.** The compiler gets
  every field definition with no grant context (`items/listing.py:57-71`,
  `slq/custom.py:62-65`), so `q=salary_band > 100000` filters, sorts and
  counts on a field the actor cannot read. Rows come back stripped, but
  membership in the result set discloses the value by bisection —
  `/items/count` and `/items/ids` make the oracle cheap.

## 2. Five cross-project read leaks the audit missed — live today, no relations involved

These are `readable_projects`-level holes in the CURRENT model. They belong
in phase 0 with RADD-834, both because they are live and because fixing
them builds exactly the plumbing relations will need.

| # | Leak | Evidence |
|---|---|---|
| N1 | **Timesheet ignores project readability entirely.** `timesheet.build()` takes no actor, lists EVERY project, and emits issue key+title per row; the router calls `require_member` and discards the readable map. MCP `list_worklogs` identical. (`timelogging/timesheet.py:28-94`, `timesheet_router.py:43`, `mcp/tools.py:472-496`.) `timelog_batch` (`service.py:141`) DOES filter — the two paths already disagree. |
| N2 | **Link/parent/epic hydration has no permission plumbing at all.** `hydration.py:116` (`_links`), `:107` (`_parents_by_id`), `:243` (`epic_ref`), `:75` (`_child_counts`) — every `ItemRead` leaks key+title of cross-project link targets, parents, epics, and child counts. The roadmap dependency view renders from this same payload. |
| N3 | **SLQ item-key autocomplete is unfiltered** — `slq/suggest_values.py:264-272` selects key+title with no readability filter. |
| N4 | **Epic rollup descendants cross projects** — `rollup.py:34` filters roots only; the descendant frontier (`:70-86`) is unfiltered. |
| N5 | Baseline `page.read` **defeats RADD-791 restricted spaces**: the space branch of `effective_permissions` unions the Baseline (`authz.py:269-277`), and the seeded Baseline holds `page.read` (`types.py:561`). A "restricted" space is readable by every active user until an admin edits the Baseline row. Capability defect rather than leak, but live. |

Latent near-miss worth one line in RADD-834: `set_archived` and
`reorder_item` (`core.py:251, 339`) skip `_check_builtin_field_rules` —
correct only while `archived`/`rank` stay ungrantable. And
**`estimate_points` is writable but absent from `_BUILTIN_FIELD_MAP`
entirely** (no rule can govern it; it still appears in history diffs).

## 3. Fact corrections that change execution details

| Audit says | Code says | Consequence |
|---|---|---|
| `role_grants` | The table is **`global_role_grants`** (`auth/models.py:137`), already carrying `project_id` + `space_id` + a two-way `one_subject` XOR CHECK | Grep targets; the Groups change rewrites the XOR to exactly-one-of-three |
| Six resources incl. "page space" (§1) | The sixth is **per-page** `"page"` (`pages/page_access.py:48-76`); space access is a different mechanism (`global_role_grants.space_id`) | The inspector and grant UI must not conflate them |
| §3.1 "per-project restriction works" | Only for `field`/`builtin_field` — the other four register `project_scoped=False` and `add_grant` **hard-rejects** a scoped grant on them | §3.1's claim is true for 2 of 6 resources; F12's wording fix must say so |
| F5.2 `has_manage` bypasses Layer 3 | Only in the **flag** model (`access/resolution.py:68-69`); `effective_level` never reads it | D1's removal changes fields/attachments/pages and is a **no-op for views/dashboards** — say so, or someone expects a change that never comes |
| F7: plugins **cannot** contribute an ACL resource | `sdk.register_access_resource` already exists (`sdk.py:78-79`, tested) | The real gap is **declarative + lifecycle**: no kernel registry entry, nothing withdraws a resource on disable, a dead plugin's grants stay live, and `clear_resource` is adopter-called with no framework sweeper (orphan grants have no FK and no GC) |
| F9: uninstall leaves atoms in roles | Confirmed — and **`api_tokens.scopes` is a second stranding site** (`auth/models.py:96-99`) | The uninstall sweep covers roles + token scopes + access_grants |
| F13: nine dead manage atoms | **Eleven dead atoms**: the nine, plus `attachment.delete` (matrix advertises "remove your own attachments"; delete-own is actually gated on `attachment.create`, delete-others on `project.manage` — the atom does nothing) and `service_account.delete` (no route exists) | The verb-normalisation table (RADD-816) starts from 11, and `attachment.delete`'s rename has no behaviour to preserve |
| F13: view.manage hides the button | Two steps worse: `PERSONAL_VIEW_PERMISSION = ITEM_READ` (`views/service.py:65`) — creating a personal view needs only item.read server-side, so the client gate over-hides for ordinary members too (conceded at `Sidebar.tsx:110-112`) | RADD-824's bug half is bigger than filed |
| §2: admin "short-circuits everything" | Admin results still pass `_narrow_to_key_scope` (`authz.py:291-304`) — the spec-113 API-key intersection applies to admins | Correct behaviour; D1/D7's "bypasses everything" wording should carry the exception |
| F5: `manage` meanings | Additionally: `global.manage` is NOT a global umbrella — it implies only label/webhook/canned/cardpreset + a few CRUD triples (`types.py:293-300`), not user/team/role/sla/cycle/automation manage | Sharper F5; the disposition table must not assume it umbrellas |
| — | `PermissionScope.INSTANCE` has **zero atoms** and no resolution branch; `ALL_PERMISSIONS` (`authz.py:54`) is dead back-compat that excludes plugin atoms | Both are cleanup lines in RADD-814 |
| — | 14 grantable builtins, not 15; `state` is **write-only** grantable; 11 are read-restrictable | Test fixtures and the audit's S1 |
| F10 | Additionally: the inspector has **no space scope** — `permission_sources` takes `project` only, so no `page.*` atom is explainable; the UI passes userId only | RADD-809 scope grows: space parameter + UI |

## 4. Numbers that reproduce exactly

92 atoms (50 global / 38 project / 4 space), one scope each;
`expand_permissions` fixpoint expansion (project.manage → 24 atoms); the
Baseline as a mutable seeded row; the F13 per-atom reference counts (every
bucket matches); F4's comment text verbatim; F6 (`CrudAction.READ` has zero
references); F8 (`kernel/specs.py:111` omits `space`); F11 (no expiry, no
granted-by — attribution exists only in outbox events); the 15 kernel
registries with none for access resources; `in_scope` as quoted; the two
resolution models; six `register_resource` sites; attachment presign is
pure HMAC, default TTL 300s (per-host 30–86400), no revocation.
192 `require`/`require_anywhere` sites (+17 `require_member`), 19 passing
computed atoms — the §5.1 migration surface.

## 5. Downgrades — checklist rows that are safer than §5.9 claims

- **Realtime WS**: frames carry `{entity, event_type}` only, no id, no
  payload; a row-hidden user's refetch goes through filtered endpoints.
  Residual: a coarse "something changed" side-channel, already
  project-blind today. Downgrade from "leak" to stated property.
- **Webhooks**: unfiltered SYSTEM payloads are a *documented decision*
  (`read.py:62-64`), and endpoint rows cannot even represent a subject
  scope (`webhooks/models.py:11-22`). A stated bypass, not sweep work.
- **Notification inbox rows** freeze `item_key`+`item_title` at delivery;
  a later revocation doesn't retract them. Same class as the presigned-URL
  caveat — state it, don't chase it.
