# Spec 100 — the Jira importer rebuilt: cache-first, explicit, reversible

**.** Replaces the spec-90 wizard. Same goal, opposite design: nothing is
guessed silently, nothing is downloaded twice, and nothing is unrecoverable.

## Why

Spec 90 worked, but it was written *against one Jira instance while importing from
it*, and every shortcut that implies became a permanent property:

- **Hardcoded to one Jira.** `FALLBACK_EMAIL_DOMAIN = "<the studio's domain>"` was written
  into real `users` rows. The sprint field was read as the literal
  `customfield_10002` unconditionally. `NOISE_JIRA_FIELDS` hid six literal
  `customfield_*` ids. Issue type → epic/issue/subtask was `"epic" in name`.
  Priority, status category and link type were English lookup tables. None of it
  was visible or overridable.
- **Re-paged Jira on every run.** Fixing one mapping mistake meant downloading
  tens of thousands of issues again.
- **Silent data loss.** `/search` inlines one page of comments/worklogs per issue
  and reports the real total; spec 90 took the inline list at face value, so an
  issue with 87 comments imported 20. Attachments, versions, components and
  changelog were not imported at all.
- **No preview and no way back.** The first sight of the result was after tens of
  thousands of rows were committed. Unwinding was hand-written SQL — literally
  what its own tests did.
- **Cross-project links were one-shot.** Importing DEV left every link to TD dead,
  and importing TD later never went back.
- **Imports spammed the instance.** 45k `item.created` events into notify,
  automations and webhooks, with no suppression.

## The pipeline

```
Connections ─→ Snapshot ─→ Profile ─→ Plan ─→ Provision ─→ Dry run ─→ Import ─→ Relink
  (DB rows)    (download    (pure,    (nine    (real Radd  (writes    (reads    (repeatable,
               once, cached) offline)  tables)  targets)    nothing)   cache)     cross-run)
                                                                          │
                                                                      Rollback
```

Downstream of the snapshot **nothing touches Jira**, which is what makes the dry
run, a re-import and relinking fast, deterministic and repeatable.

## De-hardcoding: two mechanisms

**1. Jira's own stable type keys.** `/field` exposes `schema.custom` — a plugin
type key identical on every instance. Spec 90 discarded it. `schemakeys.py` maps
it, and `client.field_catalog` now captures it. Verified live against
the studio's Jira DC on:

| spec 90 hardcoded | discovered via |
|---|---|
| `customfield_10002` (Sprint) | `gh-sprint` |
| `customfield_10003` (Epic Link) | `gh-epic-link` |
| `customfield_10007` + `13701` | `gh-lexo-rank` (two fields; one id could never cover both) |
| `customfield_13400` | `devsummary` |
| `customfield_51604` | **not present on the instance at all** — the list had gone stale against its own Jira |

**2. Every remaining vocabulary is an editable mapping table**, counted from the
snapshot: issue types (kind + spec-51 type), statuses (state + `StateCategory`),
priorities, link types, users, sprints, versions, components, fields. Suggestions
come from stable signals — Jira's `statusCategory.key`, its priority `id` order,
its link-type outward phrasing, an exact email match — never an English word list.

`FALLBACK_EMAIL_DOMAIN` is gone: `connections.placeholder_email_domain` derives it
from the connection host (or `RADD_JIRA_PLACEHOLDER_EMAIL_DOMAIN`), and with no
domain `person_email` invents **nothing**.

## Hidden and ignored unless used

`FieldBand` (`in_use` / `noise` / `unused` / `builtin`) replaces spec 90's
`is_builtin` + `likely_noise` booleans, which could not express "unused" — so a
field nothing fills in scored as ordinary data and sat at the TOP of the grid.
Only `in_use` renders expanded; the rest collapse **and default to ignore**, each
carrying a human `band_reason` shown verbatim so hiding is a judgement you can
overrule. The same rule drives every vocabulary table, keyed on the snapshot
`count`.

Measured live: **337 fields → 14 decisions. 59 issue types → 6. 83 statuses → 10.
272 components → 0.**

## Modules

```
jiraimport/
  schemakeys.py     Jira's stable type keys — the de-hardcoding table
  connections.py    DB-managed instances; env seeds one row, once
  client.py         JiraClient bound to one JiraCreds; ONE http connection reused
  snapshot/         download.py (staged job) · store.py (offline reads) · service.py
  profile/          accumulate.py (PURE, one streaming pass) · types.py
  plan/             schemas · suggest.py (PURE) · validate.py (PURE) · service.py
  provision.py      create real targets, idempotent, ledgered
  transform.py      PURE: cached issue + plan → draft
  apply.py          draft → writes (or a dry-run count) + ledger
  runs.py           the pipeline; one `commit` flag serves dry run and import
  relink.py         cross-run resolution of pending references
  rollback.py       ledger replayed in reverse
```

## Tables

`jira_connections` · `jira_snapshots` / `_issues` / `_blobs` · `jira_plans` ·
`jira_runs` · `jira_import_records` (the ledger) · `jira_pending_refs` (the
relink queue). The spec-90 pair is dropped.

## Guarantees, verified on a real 126-issue DEV slice

- **126/126 imported**, Jira numbers preserved 1:1, original `created_at`.
- **248 events, 0 not silent. 0 notifications.** `events.quiet()` + `events.silent`;
  notify/webhooks/automations/realtime skip silent rows, search + history do not.
- **256 comments across 18 distinct authors** — nobody credited to the importer.
- **15 worklogs recovered** on 2 issues by the truncation backfill (real spec-90 loss).
- **47 pending cross-project refs** parked with stand-in web links, grouped by
  target project (`31 × TD-*`, `9 × ITC-*`, …) and resolvable by Relink.
- **784 ledger rows**; rollback removed 744 cleanly and refuses to delete a project
  whose issues were kept because a human edited them.

## Three bugs the live run found (and fixed)

1. `IssueTypeCreate` requires a colour — 6 issue types failed to provision.
2. A **mapped field scoped to other projects** ("unknown field" on 38 issues).
   Provisioning now widens the scope additively, ledgered so rollback restores it.
3. A **select value outside the target field's options** killed 7 whole issues.
   The value is now dropped and reported by issue; the issue survives.

## Every problem names the mapping that caused it

`Problem` carries `section` + `mapping_key`, so "6 issues skipped" becomes "the
Jira status 'Needs Discussion' is not mapped to a Radd state" with a **Fix in
Statuses → Needs Discussion** button that opens the tab, expands the band and
rings the row. Messages describe the DECISION, not Radd's validator: `"site:
unknown field"` reads as "a mapped custom field is not usable in this project".

A run that skipped issues no longer shows a green "Done" — it is amber *"Done,
with skips"*, the result column carries a clickable `⚠ N skipped — what to fix`,
and the newest run with problems expands by default.

## Adding missing select options

Mapping into an existing select whose option list predates the import is routine,
and a value outside it was being dropped. `fields.service.extend_options` is a new
public, ADDITIVE-only operation — `update_field` holds options immutable, and
rightly so for the dangerous edits (removing or renaming one silently invalidates
items already storing that value); adding one cannot invalidate anything.

Per-field checkbox on each `Map to field` row, ticked by default wherever it would
save data, showing exactly what it would add. The previous list is ledgered, so
rollback restores the curated set. On the live DEV plan it offered 16 additions
across four fields (`affected_show_s`, `department`, `software`, `domain`).

Writing the test for it caught a latent bug: `_restore` built `options =
:options::jsonb`, which SQLAlchemy's `text()` parses as a bind parameter — so
EVERY JSONB restore was broken, including the field-scope widening. Now
`CAST(:options AS jsonb)`.

## Departed people keep their attribution

A Jira project full of ex-employees is the normal case, and their history is the
reason you are importing. `_resolve_assignee` refuses a deactivated account —
correct for new work, and it covers BOTH assignee and reporter — so every issue
owned by a leaver would have been skipped the moment leavers existed in Radd as
inactive users.

It gained `allow_inactive`, gated at the call site on `project.manage` AND on the
write being historical (`created_at`/`updated_at` present) — the same pattern as
the timestamp overrides. An import restates history; it is not a new assignment.
Ordinary creation still refuses, pinned by its own test. The account stays
deactivated: importing history must not put an offboarded person back into every
assignee picker. Comments and worklogs never had an active check, so that
attribution was always safe.

The People tab flags a matched leaver (`matched_inactive`) — "deactivated, but
their history is kept".

## Skipping disabled directory accounts

`ldap_exclude_disabled` is a cascade-resolved instance setting (Settings →
Directory → User sync), composed onto `ldap_user_filter` rather than baked into
it, and skipped if the deploy already hand-wrote the clause. ON by default: the
shipped filter had no account-status check at all, and on a live directory that
is 2057 disabled accounts against 1031 active. Verified end to end against a real
AD — 1028 → 3072 → 1028 as the toggle flips, with no restart.

## Not done

Jira Cloud (ADF descriptions, `/search/jql`) — the client sits behind the
connection seam, so it can be added without touching the pipeline.
