"""Seeing the running system from outside it (RADD-1530).

Three small things, with no new dependency:

- **A request ID** on every request: taken from `X-Request-ID` when a proxy sent a
  sane one, minted otherwise, returned on the response, and attached to every log
  line written while that request is being served (a contextvar, so it follows
  the request across awaits).
- **JSON logs** (`RADD_LOG_FORMAT=json`): one object per line, with the request ID
  and any structured `extra` a caller attached (the browser error reports of
  `modules/diagnostics` arrive that way).
- **`/metrics`** in the Prometheus text format (`RADD_METRICS_ENABLED=true`,
  optionally behind `RADD_METRICS_TOKEN`): request counts and latency by route,
  event-loop lag, the database pool, per-consumer lag, and the age of the last
  backup.

The metrics registry is deliberately tiny and in-process. With more than one
process each exposes its own numbers; a scraper that sees every pod adds them up.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radd.config import settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
#: What an incoming ID may look like. Anything else is replaced, not trusted: the
#: value is written into logs and echoed in a header.
_SANE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

#: Upper bounds of the latency histogram, in seconds.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
#: `LogRecord` attributes that are the record itself, not caller-supplied `extra`.
_STANDARD = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def accept_request_id(incoming: str | None) -> str:
    """The ID this request is known by: the proxy's when it is sane, a new one otherwise."""
    if incoming and _SANE_REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


class Metrics:
    """Counters and one histogram, enough for the questions an operator asks first."""

    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.latency_buckets: dict[tuple[str, str], list[int]] = defaultdict(
            lambda: [0] * (len(LATENCY_BUCKETS) + 1)
        )
        self.latency_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.loop_lag_seconds = 0.0

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests[(method, route, str(status))] += 1
        key = (method, route)
        self.latency_sum[key] += seconds
        buckets = self.latency_buckets[key]
        for index, bound in enumerate(LATENCY_BUCKETS):
            if seconds <= bound:
                buckets[index] += 1
        buckets[-1] += 1  # +Inf: every observation

    def reset(self) -> None:
        self.__init__()


metrics = Metrics()


def _labels(**labels: str) -> str:
    inner = ",".join(
        f'{name}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for name, value in labels.items()
    )
    return "{" + inner + "}"


def render_metrics(extra: list[str] | None = None) -> str:
    """The registry in the Prometheus text exposition format."""
    lines = [
        "# HELP radd_http_requests_total Requests served, by method, route template and status.",
        "# TYPE radd_http_requests_total counter",
    ]
    for (method, route, status), count in sorted(metrics.requests.items()):
        lines.append(f"radd_http_requests_total{_labels(method=method, route=route, status=status)} {count}")
    lines += [
        "# HELP radd_http_request_duration_seconds Time to serve a request, by method and route template.",
        "# TYPE radd_http_request_duration_seconds histogram",
    ]
    for (method, route), buckets in sorted(metrics.latency_buckets.items()):
        for bound, count in zip((*LATENCY_BUCKETS, "+Inf"), buckets, strict=True):
            lines.append(
                "radd_http_request_duration_seconds_bucket"
                f"{_labels(method=method, route=route, le=str(bound))} {count}"
            )
        lines.append(
            f"radd_http_request_duration_seconds_sum{_labels(method=method, route=route)} "
            f"{metrics.latency_sum[(method, route)]:.6f}"
        )
        lines.append(
            f"radd_http_request_duration_seconds_count{_labels(method=method, route=route)} {buckets[-1]}"
        )
    lines += [
        "# HELP radd_event_loop_lag_seconds How late the event loop last ran a timer it was due to run.",
        "# TYPE radd_event_loop_lag_seconds gauge",
        f"radd_event_loop_lag_seconds {metrics.loop_lag_seconds:.6f}",
    ]
    return "\n".join([*lines, *(extra or [])]) + "\n"


async def live_metrics() -> list[str]:
    """Gauges read at scrape time: the pool, the consumers, the newest backup. Each is
    guarded — a metrics scrape must answer even when the thing it measures is down."""
    lines: list[str] = []
    try:
        from radd.db import engine

        pool = engine.pool
        lines += [
            "# HELP radd_db_pool_connections Database connections, by state.",
            "# TYPE radd_db_pool_connections gauge",
            f'radd_db_pool_connections{_labels(state="in_use")} {pool.checkedout()}',
            f'radd_db_pool_connections{_labels(state="idle")} {pool.checkedin()}',
            f'radd_db_pool_connections{_labels(state="overflow")} {max(0, pool.overflow())}',
        ]
    except Exception:  # noqa: BLE001
        logger.debug("pool metrics unavailable", exc_info=True)
    try:
        from radd.db import SessionLocal
        from radd.modules.events import service as events

        async with SessionLocal() as session:
            consumers = await events.consumer_status(session)
        lines += [
            "# HELP radd_consumer_lag_events Events a consumer has not yet read.",
            "# TYPE radd_consumer_lag_events gauge",
            "# HELP radd_consumer_seconds_since_progress Seconds since a consumer's cursor last moved.",
            "# TYPE radd_consumer_seconds_since_progress gauge",
            "# HELP radd_consumer_failed_events Events a consumer failed on: being retried, or dead.",
            "# TYPE radd_consumer_failed_events gauge",
        ]
        for row in consumers:
            if not row["registered"]:
                continue  # a renamed consumer's leftover cursor is residue, not a stall
            name = _labels(consumer=row["name"])
            lines.append(f"radd_consumer_lag_events{name} {row['lag']}")
            lines.append(f"radd_consumer_seconds_since_progress{name} {row['seconds_since_update']}")
            for status in ("pending", "dead"):
                lines.append(
                    "radd_consumer_failed_events"
                    f"{_labels(consumer=row['name'], status=status)} {row[f'failed_{status}']}"
                )
    except Exception:  # noqa: BLE001
        logger.debug("consumer metrics unavailable", exc_info=True)
    try:
        from radd.backup import store

        # Reads each artifact's footer from disk: off the event loop.
        listed = await asyncio.to_thread(store.listing)
        complete = [item.created_at for item in listed if item.complete]
        if complete:
            newest = max(complete)
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - newest).total_seconds()
            lines += [
                "# HELP radd_backup_age_seconds Age of the newest complete backup.",
                "# TYPE radd_backup_age_seconds gauge",
                f"radd_backup_age_seconds {age:.0f}",
            ]
    except Exception:  # noqa: BLE001
        logger.debug("backup metrics unavailable", exc_info=True)
    return lines


class ObservabilityMiddleware:
    """Gives every request an ID and records how long it took, by ROUTE TEMPLATE —
    `/items/{item_id}`, never the path, or every item would be its own time series."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or ()).get(REQUEST_ID_HEADER.lower().encode())
        identifier = accept_request_id(incoming.decode("latin-1") if incoming else None)
        token = request_id.set(identifier)
        status = 500
        started = time.perf_counter()

        async def with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = identifier
            await send(message)

        try:
            await self.app(scope, receive, with_id)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            metrics.observe(scope.get("method", "GET"), route, status, time.perf_counter() - started)
            request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """Stamps the current request's ID on every record written while serving it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request ID, the
    exception if any, and whatever structured `extra` the caller attached."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        for key, value in vars(record).items():
            if key not in _STANDARD and key != "request_id" and not key.startswith("_"):
                entry[key] = value
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Attach the request-ID filter to every handler, and the JSON formatter when
    `log_format` asks for it. Idempotent: the app factory runs more than once in tests."""
    json_lines = settings.log_format.lower() == "json"
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(existing, RequestIdFilter) for existing in handler.filters):
                handler.addFilter(RequestIdFilter())
            if json_lines and not isinstance(handler.formatter, JsonFormatter):
                handler.setFormatter(JsonFormatter())


async def watch_event_loop(interval: float = 1.0) -> None:
    """Measure how late the loop runs a timer. A request that blocks the loop (heavy
    Python work on the request path) shows up here before anyone complains."""
    loop = asyncio.get_running_loop()
    while True:
        due = loop.time() + interval
        await asyncio.sleep(interval)
        metrics.loop_lag_seconds = max(0.0, loop.time() - due)
