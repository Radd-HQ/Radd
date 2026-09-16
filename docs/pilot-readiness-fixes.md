# Pilot readiness fixes: release and operator notes

Released in v0.40.2: RADD-1180, RADD-1181, RADD-1182 and RADD-1158.
No schema migration is required. Deployment upgrades remain a separate operator
action; v0.40.1 does not contain these fixes.

## Wiki collaboration

Connections now check current page access on connect, before sending frames,
before accepting document changes, and at the existing idle refresh deadline.
The check uses the same space, page and ancestor restrictions as normal page
access. Removed readers and downgraded editors lose their old connection and
must join again with their current permissions. Checks run in fresh database
sessions; old joins are not durable permission grants.

Active traffic cannot extend a revoked permission. Idle connections close on
the configured refresh deadline; a subsequent send or document change checks
immediately. Frames already delivered before revocation cannot be recalled.
The stricter checks add database work per document update/outbound frame;
representative co-editing concurrency remains part of the company pilot.

## Jira comment audiences

- Ordinary public comments remain public to their parent item's readers.
- Service-desk notes marked `jsdPublic: false` import as internal.
- Comments with Jira role/group restrictions are **omitted** until an explicit
  audience mapping is available. Their restrictions remain in the snapshot and
  import draft. Both dry-run and import show a `comment_restricted` problem with
  the source issue/comment ID; their bodies are not copied into the problem.
- Omitted comments are not recorded as imported, so a future explicit audience
  mapping can import them. Dry-run counts exclude these omissions and existing
  imported IDs. Sample/export-file imports also preserve internal visibility and
  omit unresolved restrictions when that metadata is present in the file.

This release does **not** correct historical rows. Reimport still deduplicates
existing comments. Do not interpret an upgrade or a successful reimport as a
historical confidentiality repair. Old exports that discarded visibility
metadata need reconciliation against Jira or retained source snapshots.

## Review historical comments without changing data

Run from `server/`, with `RADD_DATABASE_URL` configured for the instance to audit:

```bash
.venv/bin/python -m radd.modules.jiraimport.audit_comments > comment-visibility-review.jsonl
# Optional: limit to an exact import run (repeat --run-id for several).
.venv/bin/python -m radd.modules.jiraimport.audit_comments --run-id RUN_UUID > run-review.jsonl
```

The command uses a PostgreSQL **READ ONLY, REPEATABLE READ** transaction. It has
no apply option and prints JSONL: scope, findings, then summary. Comments and
source issue bodies, user email addresses and credentials are excluded. The
report contains IDs and source audience names, so retain it with operator
records rather than posting it publicly.

| Action | Meaning and next step |
|---|---|
| `make_internal` | Snapshot identifies an internal note, but the current target is public. Preview an explicit visibility correction after backing up. |
| `review_restricted_audience` | Snapshot names a Jira role/group. Agree the intended Radd audience; internal alone is not equivalent. Existing team IDs are included for review, not assumed correct. |
| `source_unavailable` | Snapshot or exact source comment cannot be found. Reconcile with source/backup; this is not a safe result. |
| `target_missing` | Ledger target no longer exists. Do not recreate it automatically. |
| `no_change_indicated` | Available source metadata does not indicate a change; counted in the summary, omitted from individual findings. |

The join uses each creation record's exact run, snapshot, issue key and comment
ID. It does not guess from matching text or names. Processing uses bounded
ledger windows. Imports without provenance records are outside coverage; a
clean report is not a certification of those legacy imports or of source
metadata completeness.

Before an actual repair, preserve a backup and the before-state, review source
audiences and identity mappings, apply corrections through the normal comment
service, then recheck REST/search/notifications/history as permitted and excluded
users. The report is the preparation step; no repair or company-data mutation
was performed during development of this batch.

## New Item fields

The modal uses the existing `fieldInScope` rule to show only global fields and
fields scoped to the selected project. Submission also filters against that
scope, so stale field values cannot be sent to a different project. This keeps
the existing registry API and query cache contract.

## Validation before rollout

Run the backend suite and `cd web && npm run check`. The focused backend cases
cover revoked/reused collaboration joins, downgraded editors, restricted
ancestors, idle expiry, stored import visibility, dry-run omissions and the
read-only historical report. The browser proof requires a disposable localhost
instance and synthetic administrator credentials:

```bash
RADD_PROOF_EMAIL=... RADD_PROOF_PASSWORD=... node web/scripts/new-item-fields-proof.mjs --base http://127.0.0.1:18002
```

It creates and cleans up synthetic projects/fields/items and verifies A → B → A
creation, global/shared/project fields, and saved API values. Do not use a
company database for this proof. Company deployment update and acceptance of
AD, SMTP, restore and representative load remain separate rollout work.
