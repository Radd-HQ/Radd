# Spec 26 — Notifications, watchers, and the Inbox

Tier-1 item 1 from `docs/roadmap-ideas.md`: nothing currently tells you an issue was
assigned to you, you were @mentioned, or a comment landed on something you follow.
This spec adds the `notify` module — an outbox consumer that fans item/comment events
out into per-user notifications — plus watchers, an in-app Inbox, and SMTP email digests.

## Module: `radd/modules/notify/`

An outbox consumer (cursor `notify.consumer`), mirroring the webhooks/automations
dispatcher pattern (in-process task, single-instance assumption, pure polling).

### Tables

- `item_watchers` — (item_id FK work_items CASCADE, user_id) PK pair + created_at.
  A row = user follows the item.
- `notifications` — id uuid PK, user_id (recipient, indexed), workspace_id?,
  event_id? (source outbox row), `type` (NotificationType), item_id?, actor_id?,
  payload JSONB (item_key, item_title, excerpt, from/to, …), read_at?, emailed_at?,
  created_at. Index (user_id, read_at) for the unread badge.

### NotificationType (StrEnum)

`assigned` · `mentioned` · `state_changed` · `commented` (SLA breach arrives with spec 30).

### Consumer rules (pure planner + thin I/O)

`planner.py` is pure: `(event kind, payload, watchers, readable-user filter) → [PlannedNotification]`,
unit-tested in `tests/test_notify.py`. `consumer.py` wraps it with DB I/O.

- `item.created` — auto-watch the creator + assignee; assignee ≠ actor → `assigned`;
  parse @mentions in the description → `mentioned`.
- `item.updated` — `changes` diff drives it: an `assignee` change auto-watches + notifies
  the new assignee (`assigned`); a `state` change notifies watchers (`state_changed`,
  from/to in payload); a `description` change re-parses mentions (`mentioned`).
- `comment.created` — auto-watch the author; notify watchers (`commented`, excerpt);
  parse @mentions in the **full body** (loaded via the comments service — the event
  excerpt is capped) → `mentioned`. **Internal comments notify only recipients holding
  `comment.read_internal`** on the project (checked via `authz.permissions_for_projects`).
- Never notify the actor about their own action. Within one event a user gets ONE
  notification — precedence `assigned`/`mentioned` > `state_changed`/`commented`.
- Every recipient must hold `item.read` on the project (grants are per-user-checked).
- Automation-caused events (`actor_id = SYSTEM_ACTOR_ID`) DO notify (a bot state
  change is still news) — attributed to the system actor.
- **First start bootstraps watch-only**: with no cursor row yet, the consumer walks
  the ENTIRE historical backlog applying auto-watch only (creators/assignees/
  commenters follow what they touched) and suppressing notifications — so a fresh
  deploy gets a sensible watcher graph and notifications begin from first start,
  not as spam for months-old events.

### Mentions

`@[Display Name](user-uuid)` tokens (what the rich editor will emit, spec 29) **and**
`@user@example.com` (a `@`-prefixed registered email — typeable today from a plain
textarea). Regexes live in `types.py`; resolution filters to existing active users.

### API

- `GET /notifications?unread=&limit=&offset=` → newest-first, actor names resolved
  (like audit), `unread_count` included in an envelope.
- `POST /notifications/read` `{ids}` · `POST /notifications/read-all` → 204.
- `PUT /items/{id}/watch` / `DELETE /items/{id}/watch` (idempotent, `item.read`) —
  manual follow/unfollow; emits `item.watched`/`item.unwatched` (audit).
- `GET /items/{id}/watchers` → `{watching, watchers: [{id, name}]}` (`item.read`).

All `/notifications` routes are personal (recipient = the authenticated user) — no
extra permission beyond auth.

### Events emitted

`notification.created` (payload: recipient user_id, type, item_id) — this is what the
realtime module (spec 27) pushes so bells update live. `item.watched`/`item.unwatched`
on manual watch changes. Auto-watch rows are silent (no event spam per consumer pass).
The consumer only reacts to `item.*`/`comment.*` event types, so its own emissions
never feed back (no loop).

### Email digests

A second loop (same dispatcher task pair) every `RADD_NOTIFY_EMAIL_INTERVAL` (default
300s): for each user with unemailed, unread notifications (≤ `RADD_NOTIFY_EMAIL_MAX_AGE_HOURS`
old), send ONE plain-text digest (stdlib `smtplib` via `asyncio.to_thread` — no new
dependency) listing each notification with a `RADD_APP_BASE_URL/issues/KEY` link; stamp
`emailed_at`. Already-read rows are stamped without sending. Empty `RADD_SMTP_HOST`
(the default) disables the loop entirely.

Settings (config.py): `smtp_host/port/username/password/starttls/from_address`,
`notify_poll_interval`, `notify_batch`, `notify_email_interval`,
`notify_email_max_age_hours`, `app_base_url`.

## Frontend

- **Inbox** route `/inbox` (sidebar link with live unread badge, polled every 30s —
  realtime invalidation arrives with spec 27): notification rows (type icon, actor,
  item key+title, excerpt, relative time), unread-only toggle, mark-read on click
  (navigates to the issue), mark-all-read button.
- **Watch toggle** on the issue detail header (bell icon next to star/flag) +
  watcher count; `GET /items/{id}/watchers` behind it.
- Cache: new `Entity.notification` / `Entity.watcher` tags; the unread-count and list
  queries tag `notification`; watch mutations invalidate `watcher`.

## Known simplifications

- Unwatching doesn't stick against future auto-watch triggers (comment again → re-watched);
  a `muted` tri-state is the upgrade if it annoys.
- No per-user notification/email preferences yet (global SMTP on/off only).
- Digest send is per-user serial, plain text, no HTML template.
- Consumer runs in-process (same single-instance assumption as webhooks/automations).
- Mention parsing of a comment EDIT re-notifies mentioned users only if still mentioned
  (no dedup against a prior mention of the same user on the same comment).
  Actually: comment.updated is NOT consumed at all in this slice — only creates.
