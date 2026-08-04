# Missing usability features

Each grep returned **zero** hits across `server/src/radd`, so absence is
measured. Whether each is *wanted* is the judgement — marked per entry.

---

## Issue tracking

### 1. No clone / duplicate an issue — **measured absent**, high value

`grep -riE 'clone|duplicate_item|copy_item' server/src/radd` → 0

Every tracker has this and it is the most-used bulk shortcut in practice:
"another one of these, same fields, new title". Radd has bulk *edit*
(`items/bulk.py`) and no bulk *create-from*.

Adjacent and also absent: **create issue from an existing one as a template**.
Intake forms (`modules/forms/`) cover the external path; an internal user has no
equivalent.

### 2. An issue cannot move between projects — **measured absent**, high value

`update_item` (`modules/items/service/core.py:143-210`) writes title, state,
priority, type, parent, assignee, reporter, team, cycle, release, flag,
estimate — and never `project_id`. There is no `move_item`.

```python
# core.py:143 — the full field list; project_id is not among them
async def update_item(session, item_id, data: ItemUpdate, actor) -> ItemRead:
```

Filing in the wrong project is the single most common triage mistake, and the
only remedy today is close-and-refile, which loses the comment thread, the
history and the key. **The key is the hard part** — keys are
`PROJECT-N` and instance-unique, so a move either re-keys (breaking every link
and commit reference) or keeps a key whose prefix no longer matches its project.
Worth designing before building; the absence is not an oversight.

### 3. No kind conversion (epic ↔ issue ↔ subtask) — **measured absent**

`grep -riE 'convert|change_kind'` → 0

`kind` is set at create and is immutable thereafter. "This turned out to be
bigger than one issue" is an ordinary discovery, and today it means refiling.
The hierarchy rules already exist (`items/hierarchy.py`) to validate a target
kind, so the guard is written — only the operation is missing.

### 4. No merge of duplicate issues — **measured absent**

`grep -riE 'merge_item|merge_issue'` → 0

Users and teams both have merge (`_MERGE_REPOINT` in auth, spec 88/89); issues
do not. Duplicate detection exists — `POST /ai/similar`, fused similar-issues —
so Radd finds duplicates and then offers nothing to do about them beyond a
`duplicates` link type.

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

### 7. No per-page restrictions — **measured absent**, medium value

`grep -riE 'page_restrict|restrict.*page'` → 0

RADD-791 made a **space** a grant scope, which is the right primary unit. But a
single sensitive page inside an open space (a postmortem, a salary band, an
incident writeup) has no answer except moving it to another space. Confluence's
per-page restriction is the model, and the spec-92 framework could carry it as a
resource type with no new primitive — `page_space` is already registered
(`modules/pages/page_access.py:64`).

### 8. No page-level "who can see this" — **inferred**

Follows from 7 and from spec 115 §5.10 U2. An author cannot tell who will read
a page before publishing it.

---

## Cross-cutting

### 9. Webhook deliveries have no UI — **measured**, see `02-dead-surface.md`

`GET /webhooks/{endpoint_id}/deliveries` exists
(`modules/webhooks/router.py:56`) and nothing calls it. So a webhook that fails
is silent: the data explaining why is recorded, served, and unreachable.

### 10. Plugin contribution settings have no UI — **measured**, see `02`

`GET`/`PUT /plugins/{id}/contribution-settings`
(`modules/pluginmgr/router.py:42,49`) are uncalled. CLAUDE.md describes the
global-admin half of spec 94's two-scope toggles as shipped; the per-user half
(`/auth/me/preferences`) is wired and the admin half is not.

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
