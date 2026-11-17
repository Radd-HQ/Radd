# Performance: what was measured, and what to run

The numbers behind `docs/deploy.md`'s sizing. Everything here was measured on
2026-11-17 for RADD-1536; nothing is extrapolated. Re-run it with
`server/scripts/loadtest/` before trusting it on different hardware.

## The test

- **Data**: the perf seed (`server/scripts/perfseed.py`) — 82 projects, 501,308
  items (the largest project holds 100,866), 1.79M comments, 340k worklogs,
  1,200 users — plus `scripts/loadtest/seed_history.py`, which gives every item
  about ten events: **5.0M item events**, 21 GB of database. Before that seed
  the ledger held 1,760 `item.created` events for 501k items, and everything
  that reads it had only ever run over a nearly empty stream.
- **People**: 200 signed-in **Member** accounts (not admins: a member's request
  pays for visibility and permission work an admin's skips), each holding a
  realtime socket, each doing one action then pausing 8 s on average. The mix:
  open a list 24%, an issue 26%, a board 14%, search 8%, an SLQ query 7%, edit
  an issue 8%, comment 4%, three reports at once 4%, My Work 5%. That is about
  47 requests a second when the server keeps up. It is a deliberately busy
  200: real people read more and click less.
- **Shape**: an image built from the tree with the release `Containerfile`,
  under the chart's resources (2 GiB memory
  limit, no CPU limit), PostgreSQL 16 with `shared_buffers=2GB`, both on one
  12-core workstation with the load generator. A closed loop: a user waits for
  an answer before acting again, as a browser does. 120 s ramp, 300 s measured.
- **Not covered**: a real cluster (ingress, network storage), more than one
  node, attachments, wiki co-editing under load, and imports running during
  the test.

## Results

Median / 95th percentile, in seconds.

| Request | before (one process) | after, one process | after, four web processes + worker |
|---|---|---|---|
| detail | 33.34 / 51.01 | 8.70 / 20.41 | 0.24 / 1.37 |
| comments | 33.45 / 51.01 | 8.41 / 20.56 | 0.13 / 0.85 |
| history | 34.29 / 50.46 | 8.46 / 19.78 | 0.19 / 1.00 |
| count | 34.07 / 54.16 | 8.39 / 19.58 | 0.16 / 0.83 |
| list | 33.56 / 53.88 | 8.84 / 23.65 | 0.32 / 1.53 |
| slq | 33.54 / 49.69 | 8.79 / 23.51 | 0.33 / 1.66 |
| search | 32.53 / 46.10 | 8.60 / 21.19 | 0.35 / 1.19 |
| mywork | 34.18 / 51.90 | 8.68 / 21.65 | 0.31 / 1.91 |
| board | 35.91 / 51.74 | 9.66 / 20.56 | 1.06 / 2.98 |
| report | 36.21 / 60.04 | 8.83 / 20.21 | 0.20 / 1.15 |
| update | 33.97 / 47.97 | 9.29 / 20.49 | 0.32 / 1.82 |
| comment | 35.03 / 49.40 | 8.36 / 27.56 | 0.14 / 0.76 |

| | before (one process) | after, one process | after, four web processes + worker |
|---|---|---|---|
| Requests served per second | 5.7 | 19.8 | 44.2 |
| Errors | 1219 of 1696 (72%) | 56 of 5948 (0.9%) | 2 of 13261 (0.02%) |
| Realtime sockets that connected | 54 / 200 | 186 / 200 | 200 / 200 |
| Web CPU (cores, mean) | pinned at 1 | 0.98 | 2.52 |
| Database CPU (cores, mean / peak) | about 1 | 1.5 / 2.0 | 4.4 / 5.9 |
| Consumer lag (events, peak) | — | 705 | 92 |

What the three columns say:

1. **Before, it collapsed.** ("Before" is `main` at `915c02b1`: 0.52.0 plus the
   first half of this wave, indexes included.) Reports rebuilt a project's whole history in Python on
   the event loop (23 s each on the largest project) and held hundreds of
   megabytes while doing it; with 4% of actions being reports the process hit
   its memory limit and served nothing else. With reports taken out of the mix
   it still saturated at 16 requests a second, 11 s median.
2. **After, one process does not collapse, and does not keep up.**
   Reports are SQL aggregates now (RADD-1537: 15 to 375 ms). But one Python
   process is one event loop, and a request costs 25 to 50 ms of Python: about
   20 requests a second is the ceiling whatever the database can do.
3. **Four web processes beside one worker serve the load**: every request
   answered, medians of 0.13 to 0.35 s for everything but the board.

## Budgets

The 95th-percentile targets this project holds itself to at this scale, and
where the four-process run stands:

| Class | Budget (p95) | Measured | |
|---|---|---|---|
| One record: comments, history, count | 1.0 s | 0.83 to 1.00 s | met |
| One record: the issue page | 1.0 s | 1.37 s | **missed** — RADD-1545 |
| Lists, SLQ, search, My Work | 2.0 s | 1.19 to 1.91 s | met |
| Edits and comments | 2.0 s | 0.76 to 1.82 s | met |
| Reports | 2.0 s | 1.15 s | met |
| Board | 2.0 s | 2.98 s | **missed** — RADD-1545 |

The two misses have one cause: at 44 requests a second the DATABASE used 4.4
cores, about 100 ms of database CPU per request. A board on the 100,866-item
project scans the project twice (once to count its columns, once to rank its
cards), and an issue page issues about 38 statements. Both are tracked in
RADD-1545; neither is a reason not to run at this size, and both are far
smaller on a project of ordinary size.

## What to run

| People active at once | Web | Worker | Postgres |
|---|---|---|---|
| up to about 50 (derived from the one-process ceiling, not run separately) | 1 process (the chart's default) | in the same process | 2 vCPU, 4 GB |
| about 200 (measured) | `web.processes: 4`, `workers.enabled: true` | 1 pod | 6 vCPU, 8 GB, `max_connections` ≥ 100 |

One web process serves about 20 requests a second. Memory measured at the end
of the four-process run: 919 MB for the four web processes together, 190 MB
for the worker.

Two things to know before raising `web.processes`:

- **Wiki co-editing lives in one process's memory.** The chart's Ingress sends
  `/api/v1/collab` to the single worker pod when `workers.enabled` is true. If
  your traffic reaches Radd some other way, route that path to the
  `<release>-worker` Service yourself. This routing is rendered and reviewed,
  **not yet exercised on a cluster**: open one wiki page in two browsers after
  the change and check that each sees the other typing.
- **Login and write throttles are per process**, so a limit of N becomes up to
  N times the number of processes.

## Single requests

One user, the largest project, in process (no network), this release:

| Request | Wall | Python CPU |
|---|---|---|
| Issue page | 29 ms | 25 ms |
| 50-row list | 56 ms | 47 ms |
| History tab | 32 ms (was 1,531 ms) | 15 ms |
| Board | 860 ms | 77 ms |
| Search, a common word | 89 ms | 49 ms |
| Edit one field | 58 ms | 48 ms |
| Throughput report, 30 days | 14 ms (was about 23 s) | 11 ms |
| Cumulative flow, 30 days or a year | 285 ms | 10 to 13 ms |
| Time in state | 376 ms | 10 ms |
| Velocity | 14 ms | 12 ms |
| Timesheet, one month for everyone (10,408 logs) | 295 ms | 252 ms |
| Timesheet, one year for everyone (91,814 logs) | refused with the reason (was 5.4 s and 453 MB) | — |

## The second pass (epic RADD-1548)

A browser on the same database, one user, after the first results above were
written. Page measurements first, then the 200-user test.

| What | Before | After |
|---|---|---|
| JavaScript on a cold load, over the wire | about 2,000 KB | about 700 KB (gzip, RADD-1549) |
| Issue page: API calls / bytes | 43 / 534 KB | 29 / 30 KB |
| Board: requests for the first screen | one per column | one (RADD-1545), about 235 ms steady |
| Unfiltered item count on 100k issues | 82 ms | 18 ms (covering index, RADD-1552) |
| `/auth/me`: SQL statements | 19 | 10 (RADD-1560) |
| List page: DOM nodes | 10,961 | 3,519 (50 rows, RADD-1553) |
| Idle embedder | a sweep every few seconds | backs off to 5 minutes (RADD-1550) |

The 200-user test, run again on the same database with four web processes and
one worker (median / 95th percentile, seconds):

| Request | first pass | second pass |
|---|---|---|
| detail | 0.24 / 1.37 | 0.04 / 0.26 |
| comments | 0.13 / 0.85 | 0.02 / 0.08 |
| history | 0.19 / 1.00 | 0.04 / 0.11 |
| count | 0.16 / 0.83 | 0.02 / 0.05 |
| list | 0.32 / 1.53 | 0.05 / 0.26 |
| slq | 0.33 / 1.66 | 0.07 / 0.35 |
| search | 0.35 / 1.19 | 0.09 / 0.34 |
| mywork | 0.31 / 1.91 | 0.04 / 0.34 |
| board | 1.06 / 2.98 | 0.24 / 0.56 |
| report | 0.20 / 1.15 | 0.03 / 0.24 |
| update | 0.32 / 1.82 | 0.06 / 0.22 |
| comment | 0.14 / 0.76 | 0.02 / 0.21 |

| | first pass | second pass |
|---|---|---|
| Requests served per second | 44.2 | 46.9 (bounded by the users' think time) |
| Errors | 2 of 13,261 | 1 of 14,064 |
| Web CPU (cores, mean) | 2.52 | 1.55 |
| Database CPU (cores, mean / peak) | 4.4 / 5.9 | 1.5 / 2.2 |
| Consumer lag (events, peak) | 92 | 44 |

The test script calls the API directly, so it does not exercise the batch
route or compression; those are in the browser numbers above.

The board's 860 ms above was the window-function read; it is now a bounded
read per cell, and the session asks PostgreSQL for a custom plan each time,
because the generic plan it switched to after five executions was 25 times
slower on this data.

## Upgrading a large instance

`d1537transitions` folds the existing ledger into `item_transitions` once. On
the 5.0M-event database that took **11 min 20 s**, during which `work_items`
cannot be written (the migration holds a lock on it). The chart runs
migrations before the new pods start, so this is downtime: plan for about two
minutes per million item events. An instance with a few thousand issues will
not notice.

## Running it again

```bash
# A separate Postgres. NEVER the working database: the seed and the test write.
uv run --with numpy python scripts/perfseed.py --db postgresql://…/radd --yes
uv run python scripts/loadtest/seed_history.py --db postgresql://…/radd --cycle-project GRQ
RADD_DATABASE_URL=postgresql+psycopg://…/radd uv run python scripts/loadtest/users.py --count 200
# Start the app with RADD_METRICS_ENABLED=true and RADD_AUTH_LOGIN_IP_ATTEMPTS
# raised (all 200 sign in from one address), then:
uv run python scripts/loadtest/run.py --base http://127.0.0.1:8010 --users 200 \
    --app-container <app> --db-container <db> --out results.json
```

A database copied from a real instance carries its webhooks, mail accounts and
connector tokens. Run the app against such a copy on a network with no way out
(`podman network create --internal`), or it will poll real mailboxes and call
real URLs. The run for this document did exactly that, and the logs show the
copy trying.
