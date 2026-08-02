# Spec 27 — Realtime (WebSocket live updates)

Tier-1 item 2 from `docs/roadmap-ideas.md`: live boards/issues/inbox without refresh.
The substrate was ready-made: the event outbox is the push source, and the frontend
already invalidates caches BY ENTITY (`lib/cache.ts`), so one WS message →
`invalidateEntities()` makes every surface live with no per-view code.

## Module: `radd/modules/realtime/` — NO tables, NO migration

- **WS endpoint** `GET /api/v1/ws` (FastAPI websocket route; `CommitBeforeSendMiddleware`
  passes non-http scopes through untouched). **Auth on the handshake**: the
  `radd_session` cookie (same as REST) — no cookie/invalid → close `4401`. PAT bearer
  auth is not supported on WS (browser clients only, documented).
- **Hub** (`hub.py`): in-memory connection registry — per connection the user id, their
  workspace-id set, and instance-admin flag (captured at connect; membership changes
  apply on reconnect). `should_deliver()` is a pure predicate, tested in
  `tests/test_realtime.py`.
- **Broadcaster** (`broadcaster.py`): an in-process loop tailing the outbox from the
  stream head at startup — **deliberately NOT a `consumer_offsets` consumer**: realtime
  is ephemeral, missed events during downtime are covered by clients refetching on
  reconnect. Polls every `RADD_REALTIME_POLL_INTERVAL` (0.5s), fans matching events
  out as compact JSON; a failed send drops the connection.

## Delivery filter (the permission model)

Messages carry NO payload data — only `{entity, event_type, workspace_id}` — so the
worst a misdelivered message can cause is a refetch of endpoints that are themselves
RBAC'd. Rules (pure, in `hub.should_deliver`):

- `notification` events → ONLY the recipient (`payload.user_id`), their private signal.
- `workspace_id`-scoped events → members of that workspace (instance admins get all).
- Null-workspace events (user/instance-level) → instance admins only.

## Client (`web/src/lib/realtime.ts`)

`useRealtime()` mounted once in the app shell (`AppLayout`):

- Connects to `ws(s)://<host>/api/v1/ws` (Vite dev proxy gains `ws: true`).
- Each message maps the server entity string → frontend `Entity` tags
  (`SERVER_ENTITY_TAGS` — e.g. `comment` → `[comment, item]` because comment counts
  ride on items) and queues them in a Set flushed every 200ms
  (`REALTIME_COALESCE_MS`) → ONE `invalidateEntities()` per burst.
- Reconnect with exponential backoff (1s → 30s cap). **On every (re)connect it
  invalidates ALL entity tags once** — anything missed while disconnected refetches.
- Unknown entity strings are ignored (a future module's events are simply inert
  until the client map learns them).

The notifications badge/inbox thus update within a second of the notify consumer
writing rows (`notification.created` → recipient's socket → `Entity.notification`).
The 30s badge poll stays as a fallback.

## Known simplifications

- In-process, single-instance (same as webhooks/automations dispatchers); multi-replica
  needs a shared bus (Postgres LISTEN/NOTIFY or Redis) when the worker split happens.
- Workspace membership is snapshotted at connect — role/membership changes take effect
  on the next reconnect.
- No server→client pings; dead connections are reaped on the next failed send.
- Events between server start and a client's connect are not replayed (clients fetch
  fresh on mount anyway).
- The whole-catalog invalidation on reconnect is deliberately coarse (correct, cheap
  at studio scale).
