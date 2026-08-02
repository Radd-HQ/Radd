# Spec 105 — Operator monitoring page

User ask: an admin-only Settings page showing DB health, entity counts,
embedding status, and what the background workers are doing.

## `monitoring` module (optional bootstrap plugin)

`GET /monitoring/overview` (instance-admin, 403 otherwise):

- **database**: `SHOW server_version`, `pg_database_size`, active connections
  (`pg_stat_activity`), `ok` (the handler answering IS the round-trip proof).
- **counts**: APPROXIMATE live-tuple estimates from `pg_stat_user_tables` for
  projects / work_items / users / comments / worklogs / doc_pages /
  attachments / events / search_index — catalog metadata, deliberately never
  other modules' tables, instant at any corpus size.
- **workers**: every consumer's cursor vs the stream head via the NEW public
  seam `events.service.consumer_status()` — lag + server-computed
  `seconds_since_update` (same clock that wrote the row, TZ-proof).
- **workers_in_process**: `RADD_RUN_WORKERS` — a web-only node explains that
  "no movement here" means "look at the worker process".

## SPA — Settings → Monitoring (Activity icon, admin nav gate)

5s poll while open. Cards: Database · Contents (approximate) · **Semantic
index** (composed CLIENT-side from the ai module's `/ai/embeddings/coverage`,
so monitoring never depends on the optional ai plugin — the card just hides
when AI is off) · **Background workers** table: per-consumer plain-language
description ("Builds semantic-search vectors", …), backlog, last movement,
and an OK / Catching up / **Stalled** chip — stalled = backlog AND a cursor
frozen ≥2 min, the failure mode coverage numbers alone cannot distinguish
from "slow". Zero lag with an old cursor is OK (idle stream), not stalled.
