# radd-sdk

Client SDK + plugin runner for [Radd](../README.md) — write out-of-process
extensions and connectors against a running tracker. Independent of the server
codebase and licensed **Apache-2.0**, so private studio connectors built on it
are unambiguously fine.

Ergonomics modeled on shotgunEvents: drop a `.py` file in a plugins dir, get
called with events, crash without taking the daemon down.

## How it works

The tracker already exposes everything needed — no server plugins, no sandbox:

- `GET /api/v1/events?after=<offset>&limit=` — the durable event outbox
  (every `item.*`, `comment.*`, `sla.*`, … event, in order, with an integer id).
- The full REST API for actions (items, comments, links, releases, …).

`radd-runner` polls the outbox, dispatches each event to your plugins, and
checkpoints the offset to a JSON state file.

## Quickstart

**1. Create a personal access token** (ideally on a dedicated service account):
log in to the tracker, then *profile → API tokens*, or via the API:

```bash
curl -s -c /tmp/c -X POST http://tracker:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' -d '{"email":"bot@example.com","password":"…"}'
curl -s -b /tmp/c -X POST http://tracker:8000/api/v1/tokens \
  -H 'Content-Type: application/json' -d '{"name":"runner"}'   # → {"token": "radd_pat_…", …}
```

**2. Write a plugin** — any `*.py` file that defines `register(reg)`:

```python
# plugins/greet.py
def register(reg):
    reg.on("item.created", on_created)   # glob over the event type: item.*, *, exact

def on_created(client, event):
    client.add_comment(event.payload["item_id"], "Welcome aboard!")
```

Callbacks receive `(client, event)`: `client` is a `RaddClient` (authenticated,
ready for `get/post/patch/delete` plus `find_item`, `create_item`,
`update_item`, `add_comment`, `events`), `event` is a frozen dataclass with
`id`, `event_type`, `entity_type`, `entity_id`, `payload`, `created_at`,
`actor_id`.

**3. Run the daemon:**

```bash
uv sync
uv run radd-runner --url http://tracker:8000 --token radd_pat_… \
    --plugins ./plugins --state ./runner-state.json [--from-start] [--poll 2]
```

Flags can also come from the environment: `RADD_URL`, `RADD_TOKEN`,
`RADD_PLUGINS`, `RADD_STATE`, `RADD_POLL`.

A working example lives in
[`plugins-examples/label_on_breach.py`](plugins-examples/label_on_breach.py):
on `sla.breached` it adds an `sla-breached` label and comments on the item.

## Delivery semantics

- **At-least-once.** The offset is checkpointed to the state file after each
  batch, so a crash mid-batch re-delivers that whole batch on restart. Make
  handlers idempotent (check before you write, like the example plugin does).
- **One cursor per runner.** All plugins in one runner share the stream offset
  (deliberately no per-plugin offsets). Run several runners — each with its own
  state file — when you need isolation or independent replay.
- **Fresh start.** With no state file, the runner starts at the current head of
  the stream (new events only). Pass `--from-start` to replay the full history
  from offset 0.
- **Crash isolation.** A plugin exception is logged and skips *that plugin for
  that event* — other plugins and the loop keep going.
- **Hot reload.** A plugin file's mtime change re-imports it before the next
  batch; new files are picked up, deleted files dropped. No daemon restart.
- **Polling**, 2s by default — fine at studio event rates; the tracker's
  realtime WS seam exists if push is ever needed.

## Development

```bash
uv sync
uv run pytest
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
