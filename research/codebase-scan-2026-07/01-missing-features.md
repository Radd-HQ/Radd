# Missing usability features

Each grep returned **zero** hits across `server/src/radd`, so absence is
measured. Whether each is *wanted* is the judgement — marked per entry.

---

## Issue tracking

### 1. No clone / duplicate an issue — **CORRECTED (RADD-1088): shipped 2026-08-15**

At scan time this was real (`grep -riE 'clone|duplicate_item|copy_item'
server/src/radd` → 0). RADD-1088 built it: `items/service/clone.py` +
`POST /items/{id}/clone`, routed THROUGH `create_item` so every creation and
field-grant check applies — the copy carries the shape of the work (title,
description, kind, type, priority, labels, dates, estimate, custom fields,
parent) and never the trail (comments, worklogs, history, watchers,
assignee/reporter). That also answers the adjacent "create from a template"
gap for internal users: clone an exemplar and retitle.

### 2. An issue cannot move between projects — **CORRECTED (RADD-1087): this was wrong**

This section measured the wrong seam. `update_item` indeed never writes
`project_id` — deliberately — but the move operation exists as spec 68's
**bulk move** (`modules/items/bulk.py: bulk_move_items`, `POST
/items/bulk/move`, the BulkActionBar's cross-project flow): the item keeps
its identity, gets the target's next number, and the OLD KEY KEEPS RESOLVING
via `ItemKeyAlias` (the re-key concern below was solved with a redirect, not
avoided). State maps by name then category, type by name, the release
clears, dropped custom fields are write-checked in BOTH projects (RADD-834),
and arriving runs the target's transition guards. RADD-1087 added the
`move_item` MCP tool over the same machinery. Left deliberately as-is:
children stay unless selected (hierarchy spans projects, spec 80).
Worth designing before building; the absence is not an oversight.

### 3. No kind conversion (epic ↔ issue ↔ subtask) — **CORRECTED (RADD-1089): shipped 2026-08-15**

At scan time this was real (`grep -riE 'convert|change_kind'` → 0), and the
prediction held: the hierarchy rules were already written, only the operation
was missing. RADD-1089 built it as `items/service/convert.py` +
`POST /items/{id}/convert` — `kind` stays create-only on every OTHER surface
on purpose; a conversion either satisfies the hierarchy shape or refuses
naming what blocks it (children to re-parent, subtasks to promote), and the
one automatic adjustment (detaching an incompatible parent) lands in the same
`changes` list as the kind change.

### 4. No merge of duplicate issues — **CORRECTED (RADD-1090): shipped 2026-08-15**

At scan time this was real (`grep -riE 'merge_item|merge_issue'` → 0): Radd
found duplicates (`POST /ai/similar`) and offered nothing to do about them.
RADD-1090 built `items/service/merge.py` + `POST /items/{id}/merge` —
merge(source → target) repoints everything the duplicate accumulated
(comments, attachments, links, watchers, participants, worklogs, VCS/web/page
links, labels, service-desk thread) with an EXPLICIT, ratcheted repoint list
(the spec-89 `_MERGE_REPOINT` lesson); the source becomes a closed tombstone
in a canceled-category state, linked `duplicates` to the target.

### 5. No recurring issues — **measured absent**, lower value

`grep -riE 'recurring|repeat'` → 0

Defensible omission; automations (spec 15) can approximate it. Listed for
completeness.

---

## Wiki (Pages)

### 6. No draft / unpublished state — **measured absent**, high value

`grep -riE 'draft|unpublished|is_published' server/src/radd` → 0

A page is live from its first keystroke. `page_versions` exists (spec 43), so
history is there, but there is no way to write a page over several sittings
without everyone seeing it half-finished. This is the single most-requested wiki
feature after search, and the version table means the storage half already
exists.

### 7. No per-page restrictions — **CORRECTED (RADD-792/948): shipped**

At scan time this was real (`grep -riE 'page_restrict|restrict.*page'` → 0):
RADD-791 had made a **space** a grant scope, and a single sensitive page inside
an open space had no answer except moving it. It landed exactly the way this
section predicted — a spec-92 resource type with no new primitive:
`modules/pages/page_access.py` now opens with "Per-PAGE restriction, on the
spec-92 access framework (RADD-792)" and registers `PAGE_RESOURCE = "page"`
beside `page_space`, with narrow-only semantics (an unrestricted page follows
its space; a restriction names its readers), tightened by RADD-948.

### 8. No page-level "who can see this" — **inferred; re-scoped now that 7 shipped**

The restriction mechanism exists (see 7). What remains is the author-facing
half: before publishing, an author still cannot preview the RESOLVED audience
of a page — who the space default plus the page's restriction actually adds up
to. Spec 115 §5.10 U2 territory.

---

## Cross-cutting

### 9. Webhook deliveries have no UI — **measured**, see `02-dead-surface.md`

`GET /webhooks/{endpoint_id}/deliveries` exists
(`modules/webhooks/router.py:56`) and nothing calls it. So a webhook that fails
is silent: the data explaining why is recorded, served, and unreachable.

### 10. Plugin contribution settings have no UI — **CORRECTED: measurement error**, see `02`

The scan's grep missed the caller: `web/packages/plugin-sdk/src/slots.tsx` is
non-UTF8, so plain grep skips it as a binary file. `grep -a` finds the admin
half wired exactly where spec 94 says — the PUT at `slots.tsx:244` and the GET
at `:270` call `/plugins/*/contribution-settings` from the SDK's per-contribution
toggle. Both scopes of the two-scope design are delivered.

### 11. No access-request flow — **inferred**

A refusal is a toast. There is no "request access" anywhere, and Radd holds the
data to route one (the grant tables know who can approve). Covered by spec 115
RADD-836 U3 — noted here so the wiki/issue view of it is not lost.

### 12. No "recently viewed" for pages or issues — **inferred**

`views` are saved queries; there is no per-user recent list. Pins exist
(`topbar-prefs`, `NavPin`) and are manual. For a wiki of any size, recents are
how people actually navigate.

### 13. No page or issue *favourites* distinct from pins — **inferred**

`starred` exists on items (`ItemRead.starred`) and there is no equivalent for
pages, so the two halves of the app have different mental models for the same
gesture.

### 14. Bulk operations are issue-only — **inferred**

`items/bulk.py` has no counterpart for pages (bulk move, bulk label, bulk
delete). A space reorganisation is one page at a time.
