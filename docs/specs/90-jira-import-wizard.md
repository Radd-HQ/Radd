# Spec 90 — Jira import wizard (live connection, field mapping, staged import)

**Status: shipped.**

User direction: wipe the DB and re-import from Jira, but change the flow —
pre-import users from LDAP, import issues, then *relink links to the new Radd
issues rather than back at old Jira*. And build a wizard: list Jira projects,
pick one, set a JQL filter, load the result into an inbound schema, and map
fields to local custom fields (creating them where needed).

This replaces the offline two-script path (`jira_export_build.py` +
`import_jira.py`, which round-tripped through a hand-fetched JSON dump) with a
live connection and an in-app wizard. The scripts remain for CLI/bulk use; the
canonical Jira-markup converter moved into the module
(`radd/modules/jiraimport/markup.py`), with `scripts/jira_markup.py` now a
re-export so there is one backend implementation.

## The module: `jiraimport`

Live against **Jira Server/DC REST v2**, authenticating with a **PAT (Bearer)**
or **basic auth** (username + password) — PAT wins when set, else basic, so
`RADD_JIRA_USER`/`RADD_JIRA_PASSWORD` work with the PAT line commented. Config:
`RADD_JIRA_BASE_URL`, `RADD_JIRA_PAT` | `RADD_JIRA_USER`+`_PASSWORD`,
`RADD_JIRA_VERIFY_SSL`, `RADD_JIRA_PAGE_SIZE`.

### 1. Discovery (phase 1)

- `GET /jira/status` — configured? live? which auth mode? Never 500s: a missing
  or broken connection is a state the wizard renders.
- `GET /jira/projects` — the project picker.
- `POST /jira/preview {jql, sample_size}` — runs the JQL and infers an **inbound
  schema** from a sample (`inference.py`, pure). For every field: its Radd type
  (trusting Jira's catalog over sample cardinality — a `string` stays text even
  on a small sample), populate rate, distinct/dominant signals, and whether it is
  `builtin` (native column), `likely_noise` (constant default, ordering key, or
  the devstatus blob), or a real mappable field. On the live DEV project this
  turned 321 raw fields into ~13 worth mapping.

### 2. Field mapping + plans (phase 2)

`jira_import_plans` stores a reusable config: Jira project + JQL + target Radd
project + per-field mappings. Each mapping (`mapping.py`, pure) is one of:
`ignore`, `map` (into an existing custom field), `create` (a new field, Radd type
+ options), `native` (route the value into a native Radd feature — see below), or
`builtin` (the Jira field IS a standard column like summary/status, auto-handled,
display only).

**Native-target mapping** (`FieldAction.NATIVE` + `BuiltinTarget`): many Jira
fields mean a native Radd concept, not a custom field — Domain → a **team**
assignment, Watchers → **watchers**, Epic Link → the **parent** relationship,
plus **status → workflow state**, assignee/labels/cycle/priority/start/target
dates. The suggester recognizes Epic Link → parent and Watchers → watchers by
name; team/status are offered so the admin can point Domain at a team or remap
statuses. Teams, cycles and **workflow states** are find-or-created (like
labels); parent uses the existing two-pass resolution, so **the epic need not be
imported before its children** — every item is created first, then parents are
linked once all exist.

**Value-level mapping** (`value_map: {jira_value: radd_value}`) — the granular
control layer. Meaning depends on the target: a **team** name (`L1` →
`Support Tier 1`, created on the fly), a **state** name (`In Review` →
`QA Review`, find-or-created with the Jira status's category), or a renamed
**select option** (`P1` → `Critical`). Unmapped values pass through (team/option)
or fall back to category (status). A create-select's options are rebuilt from the
mapped targets.

The per-value table is seeded from the field's **configured option set**, not
values sampled from issues: `preview` takes the picked `project_key` and pulls
`field_option_sets` — `createmeta` `allowedValues` (every select's full option
list, unioned across issue types) and `/project/{key}/statuses` (the whole
workflow's statuses). These REPLACE the sample-derived distinct values (a field
the sample thought empty/text but that has a configured option set is promoted to
select), so an option no ticket currently uses still appears. Best-effort — a
createmeta/statuses failure falls back to sampled values.

**Field label + scope on create:** a created custom field carries an explicit
display label (`create_name`, independent of the snake_case `target_key`) and a
scope (`create_scope`: `global` — shared by every project — or `project` —
attached to the import's target). Project-scoped fields need the project first,
so the runner resolves/creates it before ensuring fields.

- `POST /jira/plans/suggest` — inferred schema × existing fields → a **pre-filled
  grid** (builtins→builtin, noise/empty→ignore, slug-matches→map, else create).
  The admin adjusts; they don't start blank.
- `POST /jira/plans/validate` — catches missing targets, key collisions, selects
  without options, before a run.
- `GET/POST/PATCH/DELETE /jira/plans[/{id}]`.

### 3. Staged background import (phase 3)

`jira_import_runs` IS the progress bar: the runner (`runner.py`) rewrites
`stage`/`counts`/`errors` and commits per page, so `GET /jira/runs/{id}` shows
live progress. `POST /jira/runs {plan_id}` snapshots the plan and fires an
in-process task; a restart fails any run left mid-flight (`mark_interrupted` on
startup).

The runner calls Radd's own services directly (no HTTP): create the mapped
fields, resolve/create the project, then page through the JQL creating items with
**preserved Jira IDs 1:1** (DEV-15885 → item 15885), original timestamps,
mapped custom fields (`issuemap.py`, pure — decodes obfuscated emails, status
categories, priorities, sprint beans, per-type value rendering with select-option
filtering), comments, worklogs, and sprint→cycle links. Parents resolve in a
second pass once every item exists.

### 4. Relink pass (phase 4)

The LINKS stage runs *after* every issue exists: each Jira issue link becomes a
**native Radd link** when both ends are in the imported set (this run or a prior
import, resolved by remapping the Jira key to the Radd item key), or a **web-link
fallback** to the Jira issue otherwise. This is the "relink to new issues rather
than old Jira" the user asked for — cross-project included.

### 5. The wizard (phase 5)

`Settings → Import from Jira` (instance admin). A stepper: connect check → pick
project + JQL → preview (issue count + schema summary) → map fields (the grid,
noise/native collapsed) → name the plan + Radd project → run with live progress
(stage, counts, skipped-issue details). The mapping grid buckets fields into
"with data" / "skipped by default" / "handled natively" so a 300-field project
stays workable.

User pre-import stays a separate, prior step (spec 88's
`POST /ldap/directory-users/import`) — the wizard's run screen points at it, so
assignees/reporters/comment authors resolve to real accounts.

## Tests

- `test_jira_inference.py` — catalog-over-cardinality typing, builtin/noise
  flagging, option-set bounding, sort order.
- `test_jira_mapping.py` — slug generation, suggestion (map-vs-create), the
  validation matrix, plan CRUD.
- `test_jira_issuemap.py` — email decoding, timestamps, priority/kind/category,
  per-type value rendering + select filtering, parent/epic/comments/worklogs/links.
- `test_jira_discovery.py` — endpoint gating (admin, 409-unconfigured, 422 bad
  JQL) with the client stubbed; auth-mode precedence.
- `test_jira_runner.py` — the DB-backed integration proof: issues/fields/comments
  imported, parents resolved, a native link + a web-link fallback, and
  `mark_interrupted` failing a stale run.

Verified live against a production Jira DC (basic auth): 42 projects, a
14,540-issue DEV preview, and a bounded run importing real issues with 0 errors —
preserved IDs/timestamps, custom fields, comments, worklogs, cycles, parents.

## Follow-up — attribution: placeholder people, never the importer

Imported work was being credited to whoever clicked import. Three separate
defects, found by counting rows rather than reading code:

| Record | Cause | Damage in one real import |
|---|---|---|
| Worklogs | `create_worklog` took an `author_id` ARGUMENT and ignored `WorklogCreate.author_id`, which the importer had faithfully populated | 9,751 of 9,751 credited to the importer |
| Comments | `comments/service.py` fell back to `actor.id` whenever the author did not resolve | 13,705 credited to the importer |
| Items | Passed explicitly, so an unresolved reporter stayed NULL | 623 unattributed (wrong, but not misleading) |

All three were only reachable because an unresolved person had nowhere to go: a
Jira service account (`jiraman`) that never existed in AD, ex-employees, and
contractors all resolved to nothing.

**The importer now provisions the people it names.** `IssueDraft.people` carries
`email -> display name` for every person an issue mentions (assignee, reporter,
comment and worklog authors, watchers), and the runner ensures an account exists
for each before the issue is written, through a new public seam
`auth.ensure_imported_user(...)` — an importer must never hand-build a `User` row.

Placeholders are **active with no password**, `source=jira`:

- ACTIVE because `_resolve_assignee` refuses an inactive assignee, so inactive
  placeholders could never hold the assignment they exist for.
- PASSWORD-LESS because a placeholder must not be a way in.

**Adoption is the point of the synthesized email.** `person_email` already builds
`<jira username>@<FALLBACK_EMAIL_DOMAIN>`, which normally equals the person's real
directory address. Spec 88's rule is "an exact email match is the account, full
stop", so when that person later appears in AD the import classifies the
placeholder as `linked`, `overwrite` re-addresses **that same row** (id kept,
source `jira` -> `ldap`), and every item, comment and worklog it owned is already
theirs — no merge, no duplicate. Verified end to end. Where Jira and AD genuinely
disagree on the address, the spec-88 preview offers a merge instead, which now
also transfers ownership and deletes the loser.

**Not repairable in place.** Records already imported cannot be corrected: the
true author was never stored, so there is nothing to recover it from. A re-import
is the remedy — and note `_import_comments_worklogs` deliberately skips issues
that already exist, so an upsert will NOT backfill; the items have to be removed
(or imported into a fresh project) for their comments and worklogs to come back
correctly attributed.

## Review — what the audit found, and what it did not

**Field specs already come first, and are authoritative.** `service.preview`
fetches `/field` (the catalog) and, when a project is chosen, `createmeta`
`allowedValues` plus `/project/{key}/statuses` — in parallel with the JQL sample.
`inference._classify` uses Jira's declared type FIRST and falls back to sample
cardinality only when Jira names no type, and `_apply_option_sets` REPLACES
sampled values with the configured option set, so the mapping grid shows options
no sampled ticket happens to use. The run pipeline is likewise ordered
`FIELDS -> ISSUES -> LINKS`. No change needed.

**Defaults are sound, with one exception fixed.** The wizard opens with
built-in → `builtin`, name-matched natives → `native`, noise/empty → `ignore`,
slug-matches-an-existing-field → `map`, and everything else → `create` at the
inferred type. The exception was the generated JQL: `ORDER BY created DESC`.
A long import pages through the result set, and an issue created in Jira WHILE
it runs inserts at position 0 under DESC, shifting every later page. Now
`ORDER BY created ASC`, where new issues append at the end and the window never
moves under the paging.

Also: `users_created` is surfaced in the run progress, and the wizard's tip no
longer tells you to import AD users first as a prerequisite — it explains that
unknown people get placeholders, and that a later AD import adopts them in place.

## Merge coverage audit

"Move the survivor's id into every place the old id was used" was checked against
the SCHEMA rather than the code. 35 user-bearing columns; 31 covered; **4 gaps**:

| Column | Delete rule | Consequence |
|---|---|---|
| `global_role_grants.user_id` | CASCADE | merging **destroyed** the person's granted global roles (spec 87) |
| `team_managers.user_id` | CASCADE | merging **destroyed** the teams they manage (spec 87) |
| `backup_runs.actor_id` | SET NULL | blanked who took a backup (spec 99) |
| `backup_schedules.created_by_id` | SET NULL | blanked who owns a schedule |

The two CASCADE ones matter: now that a merge DELETES the source, those rows went
with it silently — the same class of loss as the `instance_role` demotion.

Both are unique per user, so they are dedupe entries, not plain repoints — and
`global_role_grants` is unique on `(role_id, user_id, project_id)` where
`project_id IS NULL` means global scope (spec 91). `=` never matches NULL, so the
dedupe SQL now compares with `IS NOT DISTINCT FROM`; without that, two "same"
global grants would both survive and violate the unique index at merge time.

**The audit is now a test** (`tests/test_merge_coverage.py`). It walks the mapper
metadata for FKs to `users.id` plus user-shaped UUID columns and fails when one
is not in `_MERGE_REPOINT` / `_MERGE_DEDUPE` / `_MERGE_PURGE` or an `_EXEMPT`
entry with a stated reason — so the next module that stores a user id has to
decide what a merge does with it, instead of discovering it in production. Two
further checks: every rule names a column that still exists, and every dedupe
rule's entity columns correspond to a real unique key.

## Follow-up — the last-touched date

`work_items.updated_at` existed all along (TimestampMixin) and SLQ exposes
`updated` as both filterable and SORTABLE — but nothing imported Jira's
`updated`. `create_item` set `updated_at = created_at`, so imported issues were
not stamped with the import time (good) yet every one of them read as untouched
since the day it was raised. In a real import that was 8,922 of 8,923 items with
`updated_at == created_at`, which quietly breaks `ORDER BY updated`, `updated > …`
and every recently-updated view. `updated` was already in `BUILTIN_JIRA_FIELDS`,
so the wizard even claimed it was "handled natively".

Now `IssueDraft.updated` carries `fields.updated`, and `ItemCreate`/`ItemUpdate`
take an `updated_at` on the same import-only footing as `created_at`
(`project.manage`). No `updated` in the source falls back to the creation time,
never to `now()`.

**The re-import half is the subtle one.** The column carries `onupdate=now()`, so
an upsert that did not state the time would stamp the whole project as touched
today — worse than the original bug, because it would look freshly active.
Assigning the attribute puts the column in the UPDATE's SET clause, which is what
suppresses `onupdate`; the upsert path passes `draft.updated or draft.created`
for exactly that reason. `test_jira_updated_date_is_imported_and_survives_a_reimport`
covers both halves and was checked to fail without the fix.

## Follow-up — story points as a native target

"Map to feature" offered ten native targets and not story points, so Jira's
points — which ship as a CUSTOM field ("Story Points" / "Story point estimate")
— could only ever become a generic number field. Radd has had a first-class
`work_items.estimate_points` since spec 70, and it is what velocity, burndown,
cycle sums and SLQ `points` read; a look-alike custom field leaves all of them
empty.

`BuiltinTarget.POINTS` now exists end to end: the enum, `_apply_native` (through
a `_points` parser), both runner paths, the `BuiltinTarget` const and the
`BUILTIN_TARGETS` dropdown in `MappingGrid.tsx`. `_NATIVE_BY_NAME` also suggests
it automatically for Jira's own names, so the common case needs no clicking.

Three decisions worth recording:

- **A native concept beats a slug-matching custom field.** If a `story_points`
  custom field already exists, the wizard still suggests NATIVE — the same
  precedence Epic Link → PARENT already had. The grid is editable, so an admin
  who wants the custom field changes that row.
- **Out-of-range values are dropped, not clamped.** `ItemCreate` bounds points
  0–999; turning an 8000 into 999 would invent an estimate nobody made. Junk and
  blanks become None (unestimated), never 0 — 0 is a real estimate.
- **The upsert guards points like a relation.** `estimate_points` follows the
  explicit-null-CLEARS idiom, so passing an unestimated draft straight through
  would wipe an estimate somebody set in Radd after the first import. It is now
  in the same `if … is not None` group as assignee/team/cycle, and
  `test_story_points_import_natively_and_survive_a_reimport` proves a hand-set
  estimate survives a re-import while Jira's own value still wins where it has one.
