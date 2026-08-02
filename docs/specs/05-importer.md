# Spec 05 — Jira sample importer (Wave 3) + sample-data schema (Wave 1)

## Sample file schema (frozen — the Wave-1 data agent produces it, the importer consumes it)

`server/scripts/sample_data/jira_sample.json`:

```json
{
  "project": {"key": "TD", "name": "TD Support"},
  "fields": [
    {"key": "show", "name": "Show", "type": "select", "options": ["RUX", "BNX"], "required": false},
    {"key": "department", "name": "Department", "type": "select", "options": ["FX"], "required": true}
  ],
  "users": [{"email": "jane@example.com", "name": "Jane Doe"}],
  "issues": [
    {
      "jira_key": "TD-48728",
      "title": "(RUX) - rnd sequence shots not showing",
      "description": "plain text body",
      "kind": "issue",
      "parent_jira_key": null,
      "status_category": "in_progress",
      "priority": "high",
      "labels": ["houdini"],
      "assignee_email": "jane@example.com",
      "custom_fields": {"show": "RUX", "department": "Pipeline"},
      "comments": [{"author_email": "jane@example.com", "body": "text", "created": "T10:00:00"}]
    }
  ]
}
```

Rules for the data agent: fetch ~25 real recent issues from Jira TD (mix of bugs/features)
and ~8 from DEV including one epic with 3+ children (`kind: "epic"` / children carry
`parent_jira_key`); map Jira status → `status_category` (triage|backlog|todo|in_progress|done|canceled),
Jira priority → low|normal|high|blocker; carry real labels; populate show/department/domain/software/site
custom fields from the real values (define those fields in `fields` with the option lists actually
seen); include real comment text (truncate >500 chars); collect involved users into `users`
(display name + fabricated `firstname.lastname@example.com` emails — do NOT export real addresses).
Two files: `jira_sample.json` (TD) and `jira_sample_dev.json` (DEV). Valid JSON, UTF-8.
Allowed paths for the data agent: `server/scripts/sample_data/` only.

## Importer (Wave 3)

`server/scripts/import_jira.py` — pure API client (dogfoods the REST API; no direct DB).
Env/args: `--file`, `--api http://localhost:8000/api/v1`, `--token radd_pat_...` (PAT) or
`--email/--password` (session login). Idempotent-ish: skips existing project key with a warning
unless `--project-key OVERRIDE` given; creates missing fields (tolerates 409), users
(random password, instance member; tolerates 409), labels implicitly, items in two passes
(epics/parents first, then children via `parent_id` lookup), maps `status_category` to the
project's default state of that category, posts comments (as importing actor; prefix body with
`[jira: author, date]`), stores `jira_key` in a `jira_key` text custom field it defines itself.
Prints a summary table (created/skipped/errors). Exit non-zero on any error.

Verify: run against both sample files on a fresh workspace; then `GET /items?project_id` shows
imported issues with fields/labels/comments. Show summary output in report.
