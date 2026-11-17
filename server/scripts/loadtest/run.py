"""Concurrent people on one instance (RADD-1536): N signed-in members, each
holding a realtime socket and doing what a person does — open a list, open a
board, read an issue, search, edit, comment, look at a report — with a pause
between actions. Closed loop: a user waits for an answer before thinking again,
so a slow server lowers the request rate instead of queueing without bound,
which is what browsers do.

    uv run python scripts/loadtest/run.py --base http://127.0.0.1:8010 \\
        --users 200 --ramp 120 --hold 300 --out results.json

Accounts come from `users.py`. Nothing here is a dependency of the app: httpx
and websockets are already in the environment (k6 and locust are not).

The numbers it prints are per ENDPOINT CLASS (p50/p95/p99, errors), plus what
`/metrics` said during the run: event-loop lag, pool use, consumer lag.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import statistics
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx
import websockets

from users import EMAIL, PASSWORD  # the sibling script; run from scripts/loadtest or via its path

API = "/api/v1"
#: What a person does, and how often. Weights sum to 100.
MIX = (
    ("list", 24), ("board", 14), ("detail", 26), ("search", 8), ("slq", 7),
    ("update", 8), ("comment", 4), ("report", 4), ("mywork", 5),
)
SLQ = (
    "assignee = me AND category != done ORDER BY updated DESC",
    "priority = high AND category = in_progress",
    "category = todo ORDER BY created DESC",
    'title ~ "render"',
    "updated > today-7d",
)
WORDS = ("render", "cache", "shot", "farm", "publish", "crash", "license", "review", "export")
PRIORITIES = ("low", "normal", "high", "blocker")


@dataclass
class World:
    """What the users act on: readable projects (weighted by size) and item ids."""

    projects: list[str] = field(default_factory=list)
    weights: list[int] = field(default_factory=list)
    items: dict[str, list[str]] = field(default_factory=dict)

    def project(self, rng: random.Random) -> str:
        return rng.choices(self.projects, weights=self.weights)[0]

    def item(self, rng: random.Random) -> str:
        return rng.choice(self.items[self.project(rng)])


class Recorder:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.recording = False

    def add(self, name: str, seconds: float, status: int | str) -> None:
        if not self.recording:
            return
        self.samples[name].append(seconds)
        if not (isinstance(status, int) and status < 400):
            self.errors[name][str(status)] += 1


async def call(client: httpx.AsyncClient, rec: Recorder, name: str, method: str, path: str, **kw):
    started = time.perf_counter()
    try:
        response = await client.request(method, API + path, **kw)
    except httpx.HTTPError as error:
        rec.add(name, time.perf_counter() - started, type(error).__name__)
        return None
    rec.add(name, time.perf_counter() - started, response.status_code)
    return response if response.status_code < 400 else None


async def act(action: str, client: httpx.AsyncClient, rec: Recorder, world: World, rng: random.Random):
    if action == "list":
        project = world.project(rng)
        await asyncio.gather(
            call(client, rec, "list", "GET", "/items", params={"project_id": project, "limit": 50}),
            call(client, rec, "count", "GET", "/items/count", params={"project_id": project}),
        )
    elif action == "board":
        params = {"project_id": world.project(rng), "axis": "state", "item_limit": 25}
        await call(client, rec, "board", "GET", "/items/grouped", params=params)
    elif action == "detail":
        item = world.item(rng)
        await asyncio.gather(
            call(client, rec, "detail", "GET", f"/items/{item}"),
            call(client, rec, "comments", "GET", f"/items/{item}/comments/feed"),
            call(client, rec, "history", "GET", f"/items/{item}/history"),
        )
    elif action == "search":
        await call(client, rec, "search", "GET", "/search", params={"q": rng.choice(WORDS)})
    elif action == "slq":
        params = {"q": rng.choice(SLQ), "limit": 50, "project_id": world.project(rng)}
        await call(client, rec, "slq", "GET", "/items", params=params)
    elif action == "update":
        body = {"priority": rng.choice(PRIORITIES)}
        await call(client, rec, "update", "PATCH", f"/items/{world.item(rng)}", json=body)
    elif action == "comment":
        body = {"body": f"load test note {rng.random():.6f}"}
        await call(client, rec, "comment", "POST", f"/items/{world.item(rng)}/comments", json=body)
    elif action == "report":
        project = {"project_id": world.project(rng)}
        await asyncio.gather(
            call(client, rec, "report", "GET", "/reports/throughput", params={**project, "interval": "week"}),
            call(client, rec, "report", "GET", "/reports/cumulative-flow", params={**project, "interval": "week"}),
            call(client, rec, "report", "GET", "/reports/time-in-state", params=project),
        )
    elif action == "mywork":
        await asyncio.gather(
            call(client, rec, "mywork", "GET", "/dashboards/my-work/activity"),
            call(client, rec, "slq", "GET", "/items", params={"q": SLQ[0], "limit": 50}),
        )


async def hold_socket(base: str, cookie: str, stop: asyncio.Event, opened: list[int]) -> None:
    url = re.sub(r"^http", "ws", base) + API + "/ws"
    try:
        async with websockets.connect(url, additional_headers={"Cookie": cookie}) as socket:
            opened.append(1)
            waiter = asyncio.create_task(stop.wait())
            while not stop.is_set():
                receive = asyncio.create_task(socket.recv())
                done, _ = await asyncio.wait({receive, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if receive not in done:
                    receive.cancel()
    except Exception:  # noqa: BLE001 — a dropped socket is counted by its absence
        pass


async def user(index: int, args, rec: Recorder, world: World, stop: asyncio.Event, sockets: list[int]):
    rng = random.Random(index)
    await asyncio.sleep(args.ramp * index / max(1, args.users))
    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout) as client:
        started = time.perf_counter()
        try:
            login = await client.post(
                API + "/auth/login", json={"email": EMAIL.format(index=index), "password": PASSWORD}
            )
            status: int | str = login.status_code
        except httpx.HTTPError as error:
            status = type(error).__name__
        rec.add("login", time.perf_counter() - started, status)
        if status != 204:
            return
        cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        socket = asyncio.create_task(hold_socket(args.base, cookie, stop, sockets))
        actions, weights = zip(*(pair for pair in MIX if pair[0] not in args.skip), strict=True)
        while not stop.is_set():
            await act(rng.choices(actions, weights=weights)[0], client, rec, world, rng)
            try:
                await asyncio.wait_for(stop.wait(), timeout=rng.expovariate(1 / args.think))
            except TimeoutError:
                pass
        await socket


async def discover(args) -> World:
    """Sign in as the first user and learn what a member can see."""
    world = World()
    async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
        body = {"email": EMAIL.format(index=0), "password": PASSWORD}
        (await client.post(API + "/auth/login", json=body)).raise_for_status()
        projects = (await client.get(API + "/projects")).json()
        for project in projects:
            count = (await client.get(API + "/items/count", params={"project_id": project["id"]})).json()
            total = count.get("count", count.get("total", 0)) if isinstance(count, dict) else int(count)
            if total < 50:
                continue
            ids: list[str] = []
            for offset in (0, 400, 2000):
                page = await client.get(
                    API + "/items", params={"project_id": project["id"], "limit": 200, "offset": offset}
                )
                ids += [row["id"] for row in page.json()] if page.status_code == 200 else []
            if ids:
                world.projects.append(project["id"])
                world.weights.append(total)
                world.items[project["id"]] = ids
    if not world.projects:
        raise SystemExit("the first load user can read no project with items — check its grants")
    print(f"world: {len(world.projects)} projects, {sum(world.weights):,} items visible to a member")
    return world


_METRIC = re.compile(r"^(radd_[a-z_]+)(\{[^}]*\})? ([0-9.eE+-]+)$")


async def watch(args, stop: asyncio.Event, series: dict[str, list[float]]) -> None:
    """Sample `/metrics` and container CPU while the run holds."""
    headers = {"Authorization": f"Bearer {args.metrics_token}"} if args.metrics_token else {}
    previous: dict[str, tuple[float, int]] = {}
    async with httpx.AsyncClient(base_url=args.base, timeout=10) as client:
        while not stop.is_set():
            try:
                text = (await client.get("/metrics", headers=headers)).text
            except httpx.HTTPError:
                text = ""
            for line in text.splitlines():
                match = _METRIC.match(line)
                if not match:
                    continue
                name, labels, value = match.groups()
                if name == "radd_event_loop_lag_seconds":
                    series["loop_lag_s"].append(float(value))
                elif name == "radd_db_pool_connections" and 'state="in_use"' in (labels or ""):
                    series["pool_in_use"].append(float(value))
                elif name == "radd_consumer_lag_events":
                    series["consumer_lag_max"].append(float(value))
            for label, container in (("app", args.app_container), ("db", args.db_container)):
                if not container:
                    continue
                # Cumulative CPU time, differenced between samples: the percentage
                # `podman stats` prints is an average over the container's LIFE,
                # which reads as "80% busy" long after the load has gone.
                proc = await asyncio.create_subprocess_exec(
                    "podman", "stats", "--no-stream", "--format", "{{.CPUNano}}", container,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                out = (await proc.communicate())[0].decode().split()
                if not out:
                    continue
                now, used = time.monotonic(), int(out[0])
                if label in previous:
                    then, before = previous[label]
                    series[f"{label}_cpu_cores"].append((used - before) / 1e9 / (now - then))
                previous[label] = (now, used)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def summarise(rec: Recorder, series: dict[str, list[float]], args, sockets: int) -> dict:
    classes = {}
    for name, values in sorted(rec.samples.items()):
        errors = sum(rec.errors[name].values())
        classes[name] = {
            "requests": len(values),
            "p50_ms": round(quantile(values, 0.50) * 1000, 1),
            "p95_ms": round(quantile(values, 0.95) * 1000, 1),
            "p99_ms": round(quantile(values, 0.99) * 1000, 1),
            "max_ms": round(max(values) * 1000, 1),
            "errors": errors,
            "error_kinds": dict(rec.errors[name]),
        }
    total = sum(len(values) for values in rec.samples.values())
    observed = {
        name: {"mean": round(statistics.mean(values), 3), "max": round(max(values), 3)}
        for name, values in series.items() if values
    }
    return {
        "users": args.users, "skipped": args.skip, "ramp_s": args.ramp, "hold_s": args.hold, "think_s": args.think,
        "sockets_open": sockets, "requests": total,
        "requests_per_second": round(total / args.hold, 1),
        "errors": sum(entry["errors"] for entry in classes.values()),
        "classes": classes, "observed": observed,
    }


def table(summary: dict) -> str:
    lines = ["| class | requests | p50 ms | p95 ms | p99 ms | max ms | errors |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, row in summary["classes"].items():
        lines.append(
            f"| {name} | {row['requests']} | {row['p50_ms']} | {row['p95_ms']} | {row['p99_ms']} "
            f"| {row['max_ms']} | {row['errors']} |"
        )
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--ramp", type=float, default=120, help="seconds over which users arrive")
    parser.add_argument("--hold", type=float, default=300, help="seconds measured at full load")
    parser.add_argument("--think", type=float, default=8, help="mean seconds between a user's actions")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--skip", action="append", default=[], help="an action to leave out (repeatable)")
    parser.add_argument("--metrics-token", default="")
    parser.add_argument("--app-container", default="")
    parser.add_argument("--db-container", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    world = await discover(args)
    rec, stop, sockets = Recorder(), asyncio.Event(), []
    series: dict[str, list[float]] = defaultdict(list)
    users = [asyncio.create_task(user(i, args, rec, world, stop, sockets)) for i in range(args.users)]
    print(f"ramping {args.users} users over {args.ramp:.0f}s")
    await asyncio.sleep(args.ramp + 5)
    rec.recording = True  # only the plateau is measured
    watcher = asyncio.create_task(watch(args, stop, series))
    print(f"holding for {args.hold:.0f}s")
    await asyncio.sleep(args.hold)
    rec.recording = False
    stop.set()
    await asyncio.gather(*users, watcher, return_exceptions=True)
    summary = summarise(rec, series, args, len(sockets))
    print(table(summary))
    print(json.dumps({k: v for k, v in summary.items() if k != "classes"}, indent=1))
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(summary, handle, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
