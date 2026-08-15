# Sample data

Fully **synthetic** demo datasets for the offline importer (`scripts/import_jira.py`).
Every project, person, issue and comment here is fictional — invented for these files;
`example.com` addresses throughout. Any resemblance to real people or products is
coincidental.

- `jira_sample.json` — **Skyline** (`SKY`): a fictional media-platform team. 16 users,
  26 issues (3 epics with children), 5 custom fields, comments — enough to make boards,
  reports and search feel real.
- `jira_sample_dev.json` — **Nimbus** (`NIM`): a small 8-issue set for quick import
  tests.

Import either one:

```bash
uv run python scripts/import_jira.py --file scripts/sample_data/jira_sample.json \
  --email you@example.com --password change-me
```

Issues keep the `jira_key` from the file 1:1 (`SKY-1004` stays `SKY-1004`), which is
what makes the importer's ID-preservation behavior visible in a demo.

To import from a real Jira instance, don't build files like these by hand — use the
live wizard at **Settings → Import from Jira**, which connects, maps and imports with
rollback support (spec 100).
