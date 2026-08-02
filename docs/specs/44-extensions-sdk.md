# Spec 44 — Extensions SDK + runner (out-of-process connectors)

The "people write their own extensions" pillar. A new top-level **`sdk/`**
directory — an independent **Apache-2.0** uv project (`radd-sdk`, package
`radd_sdk`) so private studio connectors are unambiguously fine (PLAN §9).
Ergonomics modeled on shotgunEvents: drop a .py file in a plugins dir, get
called with events, crash without taking the daemon down.

## Architecture

The tracker already exposes everything needed — **no server changes**:
- `GET /api/v1/events?after=<offset>&limit=` (PAT auth) — the durable outbox.
- The full REST API for actions (items, comments, links, releases…).

`radd_sdk` is a client-side runner that polls, dispatches, and checkpoints:

- `radd_sdk/client.py` — `RaddClient(base_url, token)`: thin httpx wrapper
  (PAT bearer auth, JSON errors → `RaddApiError`), `.events(after, limit)`,
  `.get/.post/.patch/.delete` passthroughs, convenience `.create_item`,
  `.add_comment`, `.update_item`, `.find_item(key)`.
- `radd_sdk/runner.py` — `Runner(client, plugins_dir, state_path,
  poll_interval=2.0)`: loads every `*.py` in `plugins_dir`; each plugin
  defines `register(reg)` and calls `reg.on(event_type_glob, callback)`
  (globs: `item.*`, `*`); the loop polls `/events`, dispatches each event to
  matching callbacks as `callback(client, event)`; a plugin exception is
  logged and skips THAT plugin for THAT event (never the loop); offset is
  checkpointed to `state_path` (JSON) after each batch — **at-least-once**
  delivery, same as the in-server consumers. **Hot reload**: file mtime
  change → module re-imported before the next batch (shotgunEvents
  behavior). Per-plugin offsets are deliberately NOT kept (one stream
  cursor; a new plugin starts at the current head unless `--from-start`).
- `radd_sdk/cli.py` — `radd-runner --url http://tracker:8000 --token
  radd_pat_… --plugins ./plugins --state ./runner-state.json
  [--from-start] [--poll 2]` (also env: RADD_URL/RADD_TOKEN/…).
- `sdk/plugins-examples/label_on_breach.py` — working example: on
  `sla.breached`, add label `sla-breached` + comment on the item.
- `sdk/README.md` — quickstart (make a service-account PAT, write a plugin,
  run the daemon), delivery semantics, Apache-2.0 header; `sdk/LICENSE` =
  Apache-2.0.

## Tests

`sdk/tests/` (pure, no network): glob matching, plugin load/reload from a
tmp dir, dispatch isolation (a raising plugin doesn't stop others),
checkpoint save/load. Run with the sdk project's own `uv run pytest`.

## Known simplifications

- Polling (2s default), not LISTEN/NOTIFY push — fine at studio event rates;
  the server seam for push already exists (realtime WS) if needed later.
- One offset per runner process (run several runners for isolation).
- The in-process GitLab connector stays in-process (spec 31) — hoisting it
  onto the runner is mechanical now the SDK exists, deferred.
