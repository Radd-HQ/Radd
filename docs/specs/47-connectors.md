# Spec 47 — Connector wave: Forgejo, Google Chat, Alertmanager, email-to-issue

Four small modules, each the same dormant-unless-configured shape as the
GitLab connector (spec 31). All talk through existing seams (vcs, items,
events outbox); none add frontend surface beyond what already renders
(vcs links, items, notifications).

## `forgejo` — VCS webhook receiver (mirror of spec 31)

`POST /integrations/forgejo` — Forgejo/Gitea webhook (push +
pull_request events). Auth: constant-time compare of the
`X-Forgejo-Signature`/`X-Gitea-Signature` HMAC-SHA256 of the raw body
against `RADD_FORGEJO_WEBHOOK_SECRET` ("" = disabled/403). Pure
`parsing.py` (tested): push → branch link + commit links from messages;
pull_request → upserting `merge_request`-type link (external id
`pr:<repo>:<number>`, status open/merged/closed). Same key extraction
rules as gitlab (`TD-123`, word-bounded, case-insensitive). Writes via
`vcs.upsert_vcs_link` as SYSTEM actor; `RADD_FORGEJO_MERGE_TRANSITION_STATE`
mirrors the gitlab setting.

## `googlechat` — outbound notifier (outbox consumer)

Posts compact cards to a Google Chat **incoming webhook URL** on selected
events. `RADD_GOOGLECHAT_WEBHOOK_URL` ("" = consumer not started),
`RADD_GOOGLECHAT_EVENT_TYPES` (csv, default
`item.created,sla.breached,doc_page.created`). Consumer offset
`googlechat.notifier` (dispatcher mirrors webhooks/notify); message = simple
`{text: "…"}` with item key/title + absolute link (`RADD_APP_BASE_URL`).
Delivery failures log + advance (a chat ping is not worth a retry queue).
Pure `format_message(event) -> str | None` (tested). First start bootstraps
at the stream HEAD (no history spam — offset row seeded like notify's
watch-only bootstrap but simpler: just start at max id).

## `alertmanager` — alert intake → items

`POST /integrations/alertmanager` — Prometheus Alertmanager webhook.
Auth: bearer/token query `?token=` constant-time vs
`RADD_ALERTMANAGER_TOKEN` ("" = disabled/403). Config:
`RADD_ALERTMANAGER_PROJECT_KEY` (target project). Dedup: table
`alert_items` (fingerprint text PK, item_id FK, created_at) — new
fingerprint + status firing → create item (title = alertname + summary
annotation, description = labels/annotations table markdown, label
`alert`); existing fingerprint firing → comment "still firing / N alerts";
status resolved → comment "resolved" (+ optional
`RADD_ALERTMANAGER_RESOLVE_STATE` state NAME transition, like gitlab
merge). Acts as SYSTEM actor. Pure `plan_alerts(payload) -> [AlertPlan]`
(tested). One tiny migration for `alert_items`.

## `mailintake` — email-to-issue for the service desk

An IMAP poller (stdlib `imaplib`, runs in a thread via the same
startup-hook pattern): `RADD_MAIL_IMAP_HOST` ("" = disabled),
`_PORT` (993 SSL), `_USERNAME`, `_PASSWORD`, `_FOLDER` (INBOX),
`_POLL_SECONDS` (60), `RADD_MAIL_PROJECT_KEY`. Each UNSEEN message →
item (title = Subject, description = text/plain body truncated 10k,
reporter = sender matched to a user by email else noted in description;
label `email`); message flagged \Seen (the checkpoint — no state table).
A reply to an existing thread (subject contains an item key `[TD-123]` or
`Re:` + key match) → public comment instead. Pure
`parse_email(raw) -> EmailPlan` + key-extraction (tested with fixture
bytes). SYSTEM actor.

## Shared

All four register in `RADD_MODULES`; settings in `config.py`; module rows
in `docs/modules.md`; events they create flow to history/notify/realtime
automatically (they write through items/comments/vcs services).

## Known simplifications

- ftrack connector: not built in-core — it's the canonical EXTERNAL
  extension example (needs studio credentials; the spec-44 SDK is the
  vehicle). Air-gapped Chat relay likewise deferred with it.
- googlechat is fire-and-forget (no retry/dead-letter — webhooks module is
  the guaranteed path); mailintake trusts IMAP \Seen as its cursor.
